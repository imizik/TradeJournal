"""Owner's closed-trade record tool (`get_my_record`) and removal of chase-entry flags from daily_reviewer."""
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import database
from app.ai import copilot, copilot_book, copilot_prompt, copilot_tool_summary, copilot_tools, daily_reviewer, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.ai.copilot_tools import LiveEvidence, ToolInputError
from app.models import Account, Fill, FillMarketContext, Trade, TradeAiTag, TradeFill
from tests.secret_scan import leaks

ROTH = UUID(int=1)
WEBULL = UUID(int=2)
SECRETS = ("8267", "4242", "RH-55501234", "WB-99887766", str(ROTH), str(WEBULL))


def _seed_closed_trade(
    db: Session,
    n: int,
    *,
    account_id: UUID = ROTH,
    ticker: str = "NBIS",
    instrument_type: str = "option",
    opened_at: datetime,
    closed_at: datetime | None,
    pnl: float | None,
    status: str = "closed",
    expiration: date | None = None,
    dte_bucket: str | None = None,
    setup: str | None = None,
    mistakes: list[str] | None = None,
    primary_mistake: str = "none",
    broke_cut_rule: bool = False,
    rule_broken_computed: bool = False,
) -> tuple[Trade, Fill]:
    raw_id = f"record:{n}"
    entry_fill = Fill(
        id=UUID(int=100 + n),
        account_id=account_id,
        ticker=ticker,
        instrument_type=instrument_type,
        side="buy_to_open" if instrument_type == "option" else "buy",
        contracts=1,
        price=100.0,
        executed_at=opened_at,
        raw_email_id=raw_id,
        option_type="call" if instrument_type == "option" else None,
        strike=100.0 if instrument_type == "option" else None,
        expiration=expiration,
    )
    trade = Trade(
        id=UUID(int=1000 + n),
        account_id=account_id,
        ticker=ticker,
        instrument_type=instrument_type,
        contracts=1,
        option_type="call" if instrument_type == "option" else None,
        strike=100.0 if instrument_type == "option" else None,
        expiration=expiration,
        avg_entry_premium=100.0,
        avg_exit_premium=100.0 + pnl if pnl is not None else None,
        total_premium_paid=100.0,
        realized_pnl=Decimal(str(pnl)) if pnl is not None else None,
        pnl_pct=Decimal(str(round(pnl / 100.0, 4))) if pnl is not None else None,
        opened_at=opened_at,
        closed_at=closed_at,
        status=status,
    )
    db.add(entry_fill)
    db.add(trade)
    db.add(TradeFill(trade_id=trade.id, fill_id=entry_fill.id, role="entry"))
    if dte_bucket is not None:
        db.add(
            FillMarketContext(
                fill_id=entry_fill.id,
                data_source="alpaca_iex",
                fetched_at=datetime(2026, 10, 15, 16, 0),
                dte_bucket=dte_bucket,
            )
        )
    if setup is not None:
        db.add(
            TradeAiTag(
                account_id=account_id,
                source_key=raw_id,
                trade_id_at_tagging=trade.id,
                setup=setup,
                mistakes_json=json.dumps(mistakes or []),
                primary_mistake=primary_mistake,
                broke_cut_rule=broke_cut_rule,
                rule_broken_computed=rule_broken_computed,
                model="claude-opus-4-6",
                batch_id="batch-1",
            )
        )
    return trade, entry_fill


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Account(
                id=ROTH,
                name="Robinhood Roth 8267",
                type="roth_ira",
                last4="8267",
                broker="robinhood",
                broker_account_id="RH-55501234",
            )
        )
        session.add(
            Account(
                id=WEBULL,
                name="Webull 4242",
                type="individual",
                last4="4242",
                broker="webull",
                broker_account_id="WB-99887766",
            )
        )
        # 1: NBIS 0dte (via FillMarketContext), vwap_reclaim win; duplicate mistake in mistakes + primary_mistake
        _seed_closed_trade(
            session, 1, ticker="NBIS",
            opened_at=datetime(2026, 10, 10, 9, 45), closed_at=datetime(2026, 10, 10, 10, 30),
            pnl=200.0, expiration=date(2026, 10, 10), dte_bucket="0dte",
            setup="vwap_reclaim", mistakes=["chased_extended", "none"], primary_mistake="chased_extended",
        )
        # 2: NBIS 0dte (fallback from expiration == opened_at.date()), vwap_reclaim loss, broke_cut_rule=True
        _seed_closed_trade(
            session, 2, ticker="NBIS",
            opened_at=datetime(2026, 10, 11, 10, 0), closed_at=datetime(2026, 10, 11, 11, 45),
            pnl=-100.0, expiration=date(2026, 10, 11),
            setup="vwap_reclaim", mistakes=["chased_extended", "held_loser_past_cut"],
            primary_mistake="held_loser_past_cut", broke_cut_rule=True,
        )
        # 3: NBIS 1-3dte (via FillMarketContext), orb_breakout win, rule_broken_computed=True
        _seed_closed_trade(
            session, 3, ticker="NBIS",
            opened_at=datetime(2026, 10, 12, 9, 35), closed_at=datetime(2026, 10, 12, 10, 10),
            pnl=50.0, expiration=date(2026, 10, 14), dte_bucket="1-3dte",
            setup="orb_breakout", mistakes=[], primary_mistake="none", rule_broken_computed=True,
        )
        # 4: NVDA expired 22+dte (fallback 30 days to expiry), earnings_run loss
        _seed_closed_trade(
            session, 4, ticker="NVDA", status="expired",
            opened_at=datetime(2026, 10, 1, 10, 0), closed_at=datetime(2026, 10, 31, 16, 0),
            pnl=-300.0, expiration=date(2026, 10, 31),
            setup="earnings_run", mistakes=["held_loser_past_cut"], primary_mistake="held_loser_past_cut",
        )
        # 5: NBIS untagged closed stock trade (counts in symbol/overall stats, not in tagged subset)
        _seed_closed_trade(
            session, 5, ticker="NBIS", instrument_type="stock",
            opened_at=datetime(2026, 10, 13, 10, 0), closed_at=datetime(2026, 10, 13, 14, 0),
            pnl=25.0,
        )
        # 6: NBIS open trade (must be excluded)
        _seed_closed_trade(
            session, 6, ticker="NBIS", status="open",
            opened_at=datetime(2026, 10, 14, 10, 0), closed_at=None,
            pnl=None, expiration=date(2026, 10, 14), setup="vwap_reclaim",
        )
        # 7: NBIS closed Webull trade (dormant, must stay excluded)
        _seed_closed_trade(
            session, 7, account_id=WEBULL, ticker="NBIS",
            opened_at=datetime(2026, 10, 9, 10, 0), closed_at=datetime(2026, 10, 9, 11, 0),
            pnl=9999.0, expiration=date(2026, 10, 9), dte_bucket="0dte",
            setup="vwap_reclaim", mistakes=["webull_only_mistake"], primary_mistake="webull_only_mistake",
        )
        session.commit()
        yield session
    engine.dispose()


def test_get_my_record_registered_validated_and_safe():
    schema = {t["name"]: t["input_schema"] for t in copilot_tools.TOOLS}["get_my_record"]
    assert schema["additionalProperties"] is False
    assert "get_my_record" in copilot_tools.BOOK_CONTEXT_TOOLS
    assert "get_my_record" in copilot_tools.PROVENANCE
    assert "get_my_record" in {t["name"] for t in copilot_prompt.TOOLS[copilot_prompt.DESK]}
    assert "get_my_record" in {t["name"] for t in copilot_prompt.TOOLS[copilot_prompt.TELEGRAM]}
    assert "get_my_record" not in research_job.JOB_TOOLS

    assert copilot_tools.validate("get_my_record", {}) == {}
    assert copilot_tools.validate("get_my_record", {"symbol": " nbis ", "setup": "  vwap  reclaim ", "dte_bucket": "0dte"}) == {
        "symbol": "NBIS", "setup": "vwap reclaim", "dte_bucket": "0dte",
    }
    for bad in (
        {"unknown": 1},
        {"symbol": "bad ticker!"},
        {"dte_bucket": "2dte"},
        {"setup": "   "},
        {"setup": "x" * 81},
    ):
        with pytest.raises(ToolInputError):
            copilot_tools.validate("get_my_record", bad)

    assert FixtureEvidence().get_my_record(symbol="NBIS")["simulated"] is True
    assert ReplayEvidence.__new__(ReplayEvidence).get_my_record(symbol="NBIS")["state"] == "unavailable"


def test_my_record_filters_metrics_tags_and_webull_exclusion(db, monkeypatch):
    overall = copilot_book.my_record(session=db)
    assert overall["state"] == "ok"
    assert overall["trades"] == 5
    assert overall["tagged_trades"] == 4
    assert overall["wins"] == 3 and overall["losses"] == 2
    assert overall["win_rate"] == 0.6
    assert overall["total_pnl"] == -125.0
    assert overall["median_pnl"] == 25.0
    assert overall["broke_cut_rule"] == 2
    assert overall["small_sample"] is True
    assert overall["top_mistakes"] == [
        {"mistake": "held_loser_past_cut", "trades": 2, "total_pnl": -400.0},
        {"mistake": "chased_extended", "trades": 2, "total_pnl": 100.0},
    ]
    assert "9999" not in json.dumps(overall)
    assert leaks(json.dumps(overall), SECRETS) == []

    nbis = copilot_book.my_record(symbol="NBIS", session=db)
    assert nbis["trades"] == 4 and nbis["tagged_trades"] == 3
    assert nbis["wins"] == 3 and nbis["losses"] == 1
    assert nbis["win_rate"] == 0.75
    assert nbis["total_pnl"] == 175.0
    assert nbis["median_pnl"] == 37.5
    assert nbis["broke_cut_rule"] == 2

    reclaim = copilot_book.my_record(symbol="NBIS", setup="VWAP Reclaim", session=db)
    assert reclaim["trades"] == 2 and reclaim["tagged_trades"] == 2
    assert reclaim["wins"] == 1 and reclaim["losses"] == 1
    assert reclaim["win_rate"] == 0.5
    assert reclaim["total_pnl"] == 100.0
    assert reclaim["median_pnl"] == 50.0
    assert reclaim["broke_cut_rule"] == 1
    assert reclaim["top_mistakes"][0] == {"mistake": "chased_extended", "trades": 2, "total_pnl": 100.0}

    assert copilot_book.my_record(setup="reclaim", dte_bucket="0dte", session=db)["trades"] == 2
    assert copilot_book.my_record(dte_bucket="1-3dte", session=db)["total_pnl"] == 50.0
    assert copilot_book.my_record(dte_bucket="22+dte", session=db)["total_pnl"] == -300.0

    missing = copilot_book.my_record(setup="nonexistent_setup", session=db)
    assert missing["trades"] == 0
    assert missing["win_rate"] is None
    assert missing["total_pnl"] == 0.0
    assert missing["median_pnl"] is None
    assert set(missing["known_setups"]) >= {"vwap_reclaim", "orb_breakout", "earnings_run"}

    monkeypatch.setattr(database, "engine", db.get_bind())
    via_tool = copilot_tools.call(LiveEvidence(), "get_my_record", {"symbol": "NBIS", "dte_bucket": "0dte"})
    assert via_tool["trades"] == 2 and via_tool["total_pnl"] == 100.0


def test_my_record_output_is_capped_and_summarized():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Robinhood Roth", type="roth_ira", last4="8267", broker="robinhood"))
        for i in range(1, 21):
            _seed_closed_trade(
                session, i, ticker="SPY",
                opened_at=datetime(2026, 10, i, 10, 0), closed_at=datetime(2026, 10, i, 11, 0),
                pnl=float(i * 10 - 105), expiration=date(2026, 10, i), dte_bucket="0dte",
                setup=f"very_long_setup_name_{i}_" + ("x" * 100),
                mistakes=[f"very_long_mistake_label_{i}_" + ("y" * 100)],
                primary_mistake=f"very_long_mistake_label_{i}_" + ("y" * 100),
            )
        session.commit()
        out = copilot_book.my_record(session=session)
    engine.dispose()

    assert out["trades"] == 20 and out["small_sample"] is False
    assert len(out["top_mistakes"]) == 5
    assert len(out["setups"]) == 8 and out["setups_total"] == 20
    assert all(len(m["mistake"]) <= 60 for m in out["top_mistakes"])
    assert all(len(s["setup"]) <= 60 for s in out["setups"])

    wire = copilot_tools.bounded(out)
    assert len(wire) <= copilot_tools.MAX_RESULT_CHARS
    assert json.loads(wire)["state"] == "ok"

    fact = copilot_tool_summary.summarize("get_my_record", out)
    assert fact is not None and len(fact) <= copilot_tool_summary.MAX_CHARS
    assert "20 trades" in fact
    summary = copilot._summary("get_my_record", out)
    assert "20 trades" in summary and len(summary) <= 160


def test_daily_reviewer_drops_chase_entry_flags_from_prompt_and_context():
    assert "chase_entry_count" not in daily_reviewer._SYSTEM_PROMPT
    assert "is_chase_entry" not in daily_reviewer._SYSTEM_PROMPT

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Robinhood Roth", type="roth_ira", last4="8267", broker="robinhood"))
        trade, entry_fill = _seed_closed_trade(
            session, 50, ticker="SPY",
            opened_at=datetime(2026, 10, 15, 9, 45), closed_at=datetime(2026, 10, 15, 11, 0),
            pnl=120.0, expiration=date(2026, 10, 15),
        )
        session.add(
            FillMarketContext(
                fill_id=entry_fill.id,
                data_source="alpaca_iex",
                fetched_at=datetime(2026, 10, 15, 16, 0),
                is_chase_entry=1,
                is_trend_aligned=1,
                dte_bucket="0dte",
            )
        )
        session.commit()
        ctx = daily_reviewer._assemble_daily_context("2026-10-15", [trade], {str(trade.id): [entry_fill]}, session)
    engine.dispose()

    flags = ctx["summary_stats"]["behavioral_flags"]
    assert "chase_entry_count" not in flags
    assert flags["trend_aligned_count"] == 1
    alpaca_ctx = ctx["trades"][0]["fills"][0]["alpaca_context"]
    assert "is_chase_entry" not in alpaca_ctx
    assert alpaca_ctx["is_trend_aligned"] == 1
    assert "chase_entry_count" not in json.dumps(ctx)
    assert "is_chase_entry" not in json.dumps(ctx)
