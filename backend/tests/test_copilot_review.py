"""The trade and position review (docs/copilot-lab.md § Review a trade or position): assembled from a seeded journal,
every section present for a closed trade and for an open position (with its `now`), free of identifiers, within the tool
bound; Webull and unknown ids refused; simulated in the fixture, unavailable in replay; never given to research jobs."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot, copilot_book, copilot_review, copilot_tools, research_job
from app.ai.copilot_fixture import OPEN_REVIEW_ID, FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.engine import capture_links, position_alerts
from app.engine.chart_math import ET
from app.models import (Account, Fill, FillMarketContext, PositionAlert, PositionWatch, Trade, TradeCapture, TradeFill,
                        TradePathMetrics)
from app.routers.fills import _rebuild_trades
from tests.secret_scan import leaks

ROTH, WEBULL = UUID(int=1001), UUID(int=1002)
DAY = (datetime.now() - timedelta(days=3)).replace(hour=10, minute=5, second=0, microsecond=0)  # a journal wall clock
EXPIRY = (DAY + timedelta(days=30)).date()
CALL = {"option_type": "call", "strike": 100, "expiration": EXPIRY}
REVIEWED = UUID(int=1)  # a trade's id is its first entry fill's id
HELD = UUID(int=12)  # the open call
OPENED = DAY + timedelta(days=2, minutes=10)
SECRETS = ("8267", "4242", "RH-55501234", "WB-99887766", str(ROTH), str(WEBULL))


def fill(n, ticker, side, qty, price, at, account=ROTH, **option):
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type="option" if option else "stock", side=side,
                contracts=qty, price=price, executed_at=at, raw_email_id=f"review:{n}", **option)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Robinhood Roth 8267", type="roth_ira", last4="8267", broker="robinhood",
                            broker_account_id="RH-55501234"))
        session.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull",
                            broker_account_id="WB-99887766"))
        session.add_all([
            fill(1, "NBIS", "buy_to_open", 2, 310, DAY, **CALL),                                   # the reviewed trade:
            fill(2, "NBIS", "sell_to_close", 2, 255, DAY + timedelta(minutes=275), **CALL),         # -$110 after 275 min
            fill(3, "NBIS", "buy", 10, 90, DAY - timedelta(days=5)),                                # an earlier NBIS trade: +$50
            fill(4, "NBIS", "sell", 10, 95, DAY - timedelta(days=5, minutes=-30)),
            fill(5, "NBIS", "buy", 5, 100, DAY + timedelta(days=1)),                                # a later one: -$25
            fill(6, "NBIS", "sell", 5, 95, DAY + timedelta(days=1, minutes=40)),
            fill(7, "CRWV", "buy", 5, 100, DAY - timedelta(days=2)),                                # another symbol
            fill(8, "CRWV", "sell", 5, 110, DAY - timedelta(days=2, minutes=-10)),
            fill(9, "NBIS", "buy", 3, 50, DAY - timedelta(days=1), account=WEBULL),                 # dormant: never shown
            fill(10, "NBIS", "sell", 3, 60, DAY - timedelta(days=1, minutes=-5), account=WEBULL),
            fill(11, "NBIS", "buy", 1, 92, DAY + timedelta(days=2)),                                # still open
            fill(12, "NBIS", "buy_to_open", 2, 300, OPENED, option_type="call", strike=105, expiration=EXPIRY),  # open call
        ])
        session.commit()
        _rebuild_trades(session, "test")
        yield session
    engine.dispose()


def _seed_world(db):
    """What the review reads besides the trade: path metrics, the entry's day P&L, a sent give-back alert (and one that
    was never sent), and a plan captured an hour before the entry."""
    trade = db.get(Trade, REVIEWED)
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    key = position_alerts.anchor(entries)
    entry_utc = capture_links.entry_utc(trade.opened_at)
    db.add(TradePathMetrics(trade_id=trade.id, data_source="test", fetched_at=datetime.utcnow(), option_path_quality="ok",
                            option_mfe_pct=20.0, option_peak_unrealized_pnl=124, option_giveback_from_peak=234,
                            underlying_mfe_pct=2.4))
    db.add(FillMarketContext(fill_id=UUID(int=1), data_source="alpaca_sip", fetched_at=datetime.utcnow(), realized_pnl_today_before=45))
    alert = dict(account_id=ROTH, source_key=key, generation=1, trade_id=trade.id, contract="NBIS 100C", contracts=2,
                 avg_cost=310, mark=320, gain=20, gain_pct=0.0323, peak_gain=124, peak_gain_pct=0.2)
    db.add(PositionAlert(kind="giveback", detected_at=entry_utc + timedelta(minutes=103), delivery="sent", **alert))
    db.add(PositionAlert(kind="hold_hour", detected_at=entry_utc + timedelta(minutes=60), delivery="expired", **alert))
    capture = TradeCapture(client_id="c1", received_at=entry_utc - timedelta(hours=1), account_id=ROTH,
                           account_label="Robinhood Roth 8267", underlying="NBIS", side="buy_calls", instrument="option",
                           mode="discretionary", setup_label="Group recovery",
                           wording="Buy the first higher low after the neoclouds turn; out below 92.50 or if NBIS loses the open.",
                           context_state="unavailable", image_state="unavailable")
    db.add(capture)
    db.commit()
    capture_links.link(db, capture, trade.id)


def _secret_free(out) -> str:
    text = copilot_tools.bounded(out)
    assert len(text) <= copilot_tools.MAX_RESULT_CHARS and json.loads(text) == json.loads(json.dumps(out, default=str))
    ids = {str(UUID(int=n)) for n in range(1, 13)}
    assert not leaks(text, (*SECRETS, *ids)), text
    assert "trade_id" not in text and "fill_id" not in text and "account_label" not in text
    return text


def test_the_review_carries_each_section(db):
    _seed_world(db)
    review = copilot_review.trade_review(str(REVIEWED), session=db)
    _secret_free(review)
    assert review["state"] == "ok" and "trimmed" not in review
    assert set(review["provenance"]) == {"trade", "path", "plan", "origin", "alerts", "habits", "comparison"}

    t = review["trade"]
    assert t["contract"] == f"NBIS {EXPIRY.month}/{EXPIRY.day}/{EXPIRY.year % 100:02d} 100C" and t["account"] == "Robinhood Roth"
    assert (t["pnl_usd"], t["pnl_pct"], t["hold_minutes"], t["status"], t["expired_worthless"]) == (-110.0, -17.7, 275, "closed", False)
    assert t["entry_time"].startswith(DAY.isoformat()) and t["entry_time"][-6:] in ("-04:00", "-05:00")  # New York, with offset
    assert (t["entry_price"], t["exit_price"], t["fills"]) == (310.0, 255.0, {"count": 2, "entries": 1, "exits": 1})

    path = review["path"]
    assert (path["option_peak_pct"], path["option_peak_unrealized_usd"], path["option_giveback_from_peak_usd"]) == (20.0, 124.0, 234.0)

    plan = review["plan"]
    assert plan["setup"] == "Group recovery" and plan["timing"] == "pre_entry" and "92.50" in plan["wording"]

    alerts = review["alerts"]
    assert alerts["sent"] == 1 and [a["kind"] for a in alerts["alerts"]] == ["giveback"]  # the unsent one is left out
    [alert] = alerts["alerts"]
    assert (alert["gain_pct"], alert["peak_gain_pct"], alert["then"]) == (3.2, 20.0, "closed_later")
    assert (alert["value_at_alert_usd"], alert["realized_after_usd"], alert["vs_closing_at_alert_usd"]) == (640.0, 510.0, -130.0)

    habits = {h["habit"]: h["this_trade"] for h in review["habits"]["habits"]}
    assert habits == {"Was up 10% and $50, then closed red": "yes", "Held an hour or more, closed red the same day": "yes",
                      "Expired worthless": "no", "Opened while the day was already green": "yes"}

    rows = review["comparison"]["trades"]
    assert [r["pnl_usd"] for r in rows] == [-25.0, 50.0]  # newest first; not this trade, not CRWV, not Webull, not the open one
    assert rows[0]["pnl_pct"] == -5.0 and "account" not in rows[0]  # percent, the same unit as the trade's own


def test_a_bare_trade_reads_missing_sections_plainly(db):
    review = copilot_review.trade_review(str(REVIEWED), session=db)
    _secret_free(review)
    assert review["path"]["state"] == "missing" and review["plan"]["state"] == "none" and review["alerts"]["sent"] == 0
    assert {h["this_trade"] for h in review["habits"]["habits"]} >= {"unknown (data missing)"}
    stock = copilot_review.trade_review(str(UUID(int=3)), session=db)
    assert stock["habits"]["state"] == "not_applicable" and stock["trade"]["contract"] == "NBIS stock"


def _seed_open(db, monkeypatch):
    """The open call: marked at $310 a contract (+$20), its watch peaked at $362 (+$124) and fired a give-back, and a plan
    captured before it. Quotes are stubbed; the marking path is copilot_book's."""
    from app.engine import quotes
    monkeypatch.setattr(copilot_book, "_warm_option_quotes", lambda trades: None)
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: 95.0 for s in symbols})
    monkeypatch.setattr(copilot_book, "_mark", lambda trade, q: (310.0, "2026-10-23T15:10:00Z") if trade.instrument_type == "option"
                        else (q.get(trade.ticker), None))
    trade = db.get(Trade, HELD)
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    key, entry_utc = position_alerts.anchor(entries), capture_links.entry_utc(trade.opened_at)
    db.add(PositionWatch(account_id=ROTH, source_key=key, generation=1, contracts=2, avg_cost=300, peak_mark=362,
                         peak_at=entry_utc + timedelta(minutes=20), armed_at=entry_utc + timedelta(minutes=10)))
    db.add(PositionAlert(kind="giveback", detected_at=entry_utc + timedelta(minutes=50), delivery="sent", account_id=ROTH,
                         source_key=key, generation=1, trade_id=trade.id, contract="NBIS 105C", contracts=2, avg_cost=300,
                         mark=309, gain=18, gain_pct=0.03, peak_gain=124, peak_gain_pct=0.2067))
    capture = TradeCapture(client_id="c2", received_at=entry_utc - timedelta(minutes=30), account_id=ROTH,
                           account_label="Robinhood Roth 8267", underlying="NBIS", side="buy_calls", instrument="option",
                           mode="discretionary", setup_label="Copilot plan",
                           wording="Entry above 101 on a 5m close; invalidation below 97.50; time stop 11:30.",
                           context_state="unavailable", image_state="unavailable")
    db.add(capture)
    db.commit()
    capture_links.link(db, capture, trade.id)


def test_an_open_position_reads_now_plan_alerts_and_comparison(db, monkeypatch):
    _seed_open(db, monkeypatch)
    review = copilot_review.trade_review(str(HELD), session=db)
    text = _secret_free(review)
    assert review["state"] == "ok" and "trimmed" not in review
    assert set(review["provenance"]) == {"trade", "now", "plan", "origin", "alerts", "comparison"} == set(copilot_review.OPEN_PROVENANCE)
    assert "path" not in review and "habits" not in review and "order" in review["note"]

    t = review["trade"]
    assert (t["status"], t["entry_price"], t["quantity"], t["account"]) == ("open", 300.0, 2.0, "Robinhood Roth")
    assert "exit_time" not in t and "pnl_usd" not in t and t["contract"].endswith("105C")

    now, today = review["now"], datetime.now(ET)
    assert (now["mark"], now["open_pnl_usd"], now["open_pnl_pct"], now["open_quantity"]) == (310.0, 20.0, 3.3, 2)
    assert (now["peak_gain_usd"], now["peak_gain_pct"], now["given_back_from_peak_usd"], now["giveback_watch"]) == (124.0, 20.7, 104.0, "fired")
    assert (now["days_to_expiry"], now["expires_today"]) == ((EXPIRY - today.date()).days, False)
    assert abs(now["minutes_held"] - (today - OPENED.replace(tzinfo=ET)).total_seconds() // 60) <= 1 and now["days_held"] in (0, 1)
    assert "weekends" in review["units"]
    assert now["latest_alert"]["kind"] == "giveback" and (now["latest_alert"]["gain_usd"], now["latest_alert"]["gain_pct"]) == (18, 3.0)
    assert now["mark_as_of"] == "2026-10-23T15:10:00Z" and "quote" not in now

    assert review["plan"]["setup"] == "Copilot plan" and "time stop 11:30" in review["plan"]["wording"]
    [alert] = review["alerts"]["alerts"]
    assert alert["then"] == "still_open" and "no result yet" in alert["note"]
    assert [r["pnl_usd"] for r in review["comparison"]["trades"]] == [-25.0, -110.0, 50.0]  # closed NBIS only, not Webull
    assert "WB" not in text


def test_an_open_position_without_a_quote_says_so(db, monkeypatch):
    _seed_open(db, monkeypatch)
    monkeypatch.setattr(copilot_book, "_mark", lambda trade, q: (None, None))
    now = copilot_review.trade_review(str(HELD), session=db)["now"]
    assert "open_pnl_usd" not in now and "given_back_from_peak_usd" not in now and "No current quote" in now["quote"]
    stock = copilot_review.trade_review(str(UUID(int=11)), session=db)  # an open stock: no expiry, no watch
    assert stock["now"]["state"] == "ok" and "days_to_expiry" not in stock["now"] and stock["trade"]["contract"] == "NBIS stock"


def test_webull_and_unknown_trades_are_not_reviewed(db):
    webull = copilot_review.trade_review(str(UUID(int=9)), session=db)
    assert webull["state"] == "unavailable" and "Webull" in webull["reason"] and not leaks(json.dumps(webull), ["4242"])
    with pytest.raises(copilot_review.ReviewNotFound):
        copilot_review.trade_review(str(uuid.uuid4()), session=db)


def test_one_failing_source_leaves_the_rest_standing(db, monkeypatch):
    _seed_world(db)

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(capture_links, "for_trade", boom)
    review = copilot_review.trade_review(str(REVIEWED), session=db)
    assert review["plan"] == {"state": "unavailable"} and review["alerts"]["sent"] == 1 and review["trade"]["pnl_usd"] == -110.0


def test_an_oversized_review_sheds_comparison_then_alerts_and_fits():
    row = {"note": "n" * 300}
    review = {"state": "ok", "provenance": copilot_review.PROVENANCE, "trade": {"contract": "X", "pad": "t" * 1500},
              "plan": {"state": "ok", "wording": "w" * 240},
              "alerts": {"state": "ok", "sent": 6, "shown": 6, "alerts": [dict(row) for _ in range(6)]},
              "comparison": {"state": "ok", "trades": [{"note": "c" * 600} for _ in range(4)]}}
    out = copilot_review.shed(review)
    assert len(json.dumps(out, separators=(",", ":"))) <= copilot_review.MAX_REVIEW_CHARS and out["trimmed"] is True
    assert out["alerts"]["shown"] == len(out["alerts"]["alerts"]) and out["plan"]["wording"] == "w" * 240
    assert copilot_review.MAX_REVIEW_CHARS < copilot_tools.MAX_RESULT_CHARS


# --------------------------------------------------------------------------- the tool

def test_the_tool_is_validated_routed_labelled_and_never_a_job_tool(monkeypatch):
    tid = "0B0E6A3C-7C5D-4F69-9A51-0D6AB8A0B1C2"
    assert copilot_tools.validate("get_trade_review", {"trade_id": tid}) == {"trade_id": tid.lower()}
    for bad in ({"trade_id": "../etc"}, {}, {"trade_id": tid, "symbol": "NBIS"}):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate("get_trade_review", bad)

    def missing(trade_id, session=None):
        raise copilot_review.ReviewNotFound(trade_id)
    monkeypatch.setattr(copilot_review, "trade_review", missing)
    with pytest.raises(copilot_tools.ToolInputError, match="no trade"):
        copilot_tools.call(copilot_tools.LiveEvidence(), "get_trade_review", {"trade_id": tid.lower()})
    assert copilot_tools.provenance("get_trade_review", {"state": "ok"}, "live")["kind"] == "saved"
    assert "get_trade_review" not in research_job.JOB_TOOLS and "mcp__tradejournal__get_trade_review" not in research_job.LAB_TOOLS
    assert "get_trade_review" in copilot_tools.BOOK_CONTEXT_TOOLS  # "what changed" leaves it out of the evidence times


def test_replay_is_unavailable_and_the_fixture_is_simulated():
    replay = ReplayEvidence.__new__(ReplayEvidence)
    assert replay.get_trade_review(str(REVIEWED))["state"] == "unavailable"
    fixture = FixtureEvidence().get_trade_review(str(REVIEWED))
    assert fixture["simulated"] is True and fixture["state"] == "ok" and set(fixture["provenance"]) == set(copilot_review.PROVENANCE)
    assert len(copilot_tools.bounded(fixture)) <= copilot_tools.MAX_RESULT_CHARS


def test_the_fixture_simulates_an_open_review():
    fixture = FixtureEvidence().get_trade_review(OPEN_REVIEW_ID)
    assert fixture["simulated"] is True and fixture["trade"]["status"] == "open"
    assert set(fixture["provenance"]) == set(copilot_review.OPEN_PROVENANCE) and fixture["now"]["giveback_watch"] == "fired"
    assert len(copilot_tools.bounded(fixture)) <= copilot_tools.MAX_RESULT_CHARS
    replay = ReplayEvidence.__new__(ReplayEvidence)
    assert replay.get_trade_review(OPEN_REVIEW_ID)["state"] == "unavailable"


def test_the_scripted_model_reviews_a_position_from_the_alert_link_text():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                           key_configured=False)

    async def collect():
        content = f"Context: Review this position: {OPEN_REVIEW_ID}. Give-back alert at 11:48 AM: was +$96, now +$20."
        return [e async for e in copilot.run_turn([{"role": "user", "content": content}], "NBIS", cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 23, 11, 12))]
    events = asyncio.run(collect())
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_trade_review" and e["status"] == "ok"]
    assert tool["input"] == {"trade_id": OPEN_REVIEW_ID} and tool["summary"].startswith("NBIS 11/21/26 100C -310.00 $ open")
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Simulated model" in text and "decision now" in text and "won't make it an order" in text


def test_the_scripted_model_reviews_a_trade_from_the_deep_link_text():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                           key_configured=False)
    tid = "0b0e6a3c-7c5d-4f69-9a51-0d6ab8a0b1c2"

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": f"Context: Review this trade: {tid}"}], "NBIS", cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 23, 11, 12))]
    events = asyncio.run(collect())
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_trade_review" and e["status"] == "ok"]
    assert tool["input"] == {"trade_id": tid} and tool["provenance"]["kind"] == "simulated"
    assert tool["summary"].startswith("NBIS 11/21/26 100C -110.00 $ · plan ok · 1 alerts")
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Simulated model" in text and "pre_entry" in text and "Thesis vs execution" in text and "cannot support" in text


def test_the_system_prompt_asks_for_the_review_frame():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert "call get_trade_review with the trade id from their message" in prompt
    assert "keep thesis apart from execution" in prompt and "one trade cannot support a lesson" in prompt
    assert "propose a memory only if the owner states one" in prompt
    assert "Review this position:" in prompt and "Lead with the decision now" in prompt
    assert "invalidation and time stop" in prompt and "Never tell them to sell or hold as an order" in prompt


def test_trades_can_leave_one_out(db):
    rows = copilot_book.trades("NBIS", 10, session=db, exclude=REVIEWED)["trades"]
    assert [r["pnl_usd"] for r in rows] == [-25.0, 50.0]
    assert [r["pnl_usd"] for r in copilot_book.trades("NBIS", 10, session=db)["trades"]] == [-25.0, -110.0, 50.0]
