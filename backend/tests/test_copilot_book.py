"""Copilot Lab's chart and book tools (docs/copilot-lab.md): bounded, with provenance, never an account identifier;
simulated in the fixture and unavailable in replay. Providers are stubbed; the journal is a seeded in-memory database."""
import asyncio
import json
from datetime import date, datetime
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import copilot, copilot_book, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.engine import jo_briefing, quotes
from app.engine.quotes import OptionQuoteResult
from app.models import Account, Fill, Tag, TradeTag
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=1), UUID(int=2)
LATER = date(2099, 1, 15)
CALL = {"option_type": "call", "strike": 100, "expiration": LATER}
SECRETS = ("8267", "4242", "RH-55501234", "WB-99887766", str(ROTH), str(WEBULL))


def fill(n, ticker, side, qty, price, at, account=ROTH, **option):
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type="option" if option else "stock", side=side,
                contracts=qty, price=price, executed_at=datetime.fromisoformat(at), raw_email_id=f"book:{n}", **option)


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
            fill(1, "NBIS", "buy_to_open", 2, 310, "2026-10-20T09:42", **CALL),   # open: 2 calls at $3.10
            fill(2, "CRWV", "buy", 10, 120, "2026-10-15T10:00"),                   # open: 10 shares at $120
            fill(3, "CRWV", "buy", 5, 100, "2026-10-01T10:00"),                    # closed: in at 100, out at 110
            fill(4, "CRWV", "sell", 5, 110, "2026-10-01T15:00"),
            fill(5, "CRWV", "buy", 4, 90, "2026-09-20T10:00", account=WEBULL),     # Webull: dormant, never shown
            fill(6, "CRWV", "sell", 4, 95, "2026-09-20T11:00", account=WEBULL),
            fill(7, "NBIS", "buy", 3, 50, "2026-10-21T10:00", account=WEBULL),
        ])
        session.commit()
        _rebuild_trades(session, "test")
        yield session
    engine.dispose()


@pytest.fixture
def marks(monkeypatch):
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: {"CRWV": 131.2}.get(s) for s in symbols})
    monkeypatch.setattr(quotes, "option_mark", lambda req: (OptionQuoteResult(mid=4.0, last_price=3.9), 1792768320.0))


def _secret_free(out):
    text = copilot_tools.bounded(out)
    assert len(text) <= copilot_tools.MAX_RESULT_CHARS and json.loads(text) == json.loads(json.dumps(out, default=str))
    assert not [s for s in SECRETS if s in text]
    return text


# --------------------------------------------------------------------------- validation

@pytest.mark.parametrize("name,args", [
    ("get_chart_context", {"symbol": "NBIS"}), ("get_chart_context", {"symbol": "NBIS", "timeframe": "2m"}),
    ("get_positions", {"account": "x"}), ("get_trades", {"symbol": "NBIS", "limit": 11}),
    ("get_trades", {"limit": 3}), ("get_memories", {"limit": 0}), ("get_memories", {"symbol": "nb!s"}),
    ("get_owner_context", {}), ("get_owner_context", {"symbol": "NBIS", "limit": 1}),
])
def test_inputs_are_validated(name, args):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate(name, args)


def test_inputs_are_normalized():
    assert copilot_tools.validate("get_chart_context", {"symbol": "nbis", "timeframe": "15m"}) == {"symbol": "NBIS", "timeframe": "15m"}
    assert copilot_tools.validate("get_positions", {}) == {}
    assert copilot_tools.validate("get_trades", {"symbol": "crwv"}) == {"symbol": "CRWV", "limit": 5}
    assert copilot_tools.validate("get_memories", {}) == {"limit": 5}


# --------------------------------------------------------------------------- the chart

def _workspace(bars=1200, zones=60, label="L" * 300, big=987654.321):
    stamp = 1792700000
    rows = [{"time": stamp + 60 * i, "open": big, "high": big, "low": big, "close": big + (i % 7), "volume": 999_999_999,
             "rvol": 12.3456, "extended": i % 2 == 0, "vwap": big, "vwap_sd": 12.3456, "end_time": stamp + 60 * i + 60}
            for i in range(bars)]
    found = [{"id": f"z{i}", "low": big - 500 + 20 * i, "high": big - 495 + 20 * i, "label": label, "score": 3.14159} for i in range(zones)]
    return {"panels": {"5m": {"bars": rows, "level_events": {z["id"]: {"state": "reclaimed"} for z in found}}},
            "auto_levels": {"atr": 12.5, "zones": found, "missing": {"a": "m" * 500, "b": "n" * 500, "c": "o" * 500, "d": "p"}},
            "rvol": {"state": "ready", "traded": 20, "message": "x" * 900},
            "quotes": [{"symbol": "NBIS", "last": big, "open": big, "day_high": big, "day_low": big, "previous_close": big,
                        "change_percentage": -12.3456, "volume": 999_999_999, "trade_time": stamp}],
            "intraday_as_of": stamp, "session": "extended", "market": {"date": "2026-10-23", "status": "open", "description": "d" * 50},
            "issues": ["i" * 500] * 10, "delayed": False}


def test_chart_context_is_bounded_at_its_worst_and_reads_nothing_new():
    out = copilot_book.compact_chart("NBIS", "5m", _workspace())
    _secret_free(out)
    assert out["bars"]["count_total"] == 1200 and out["bars"]["shown"] == copilot_book.MAX_BARS
    assert len(out["levels"]["above"]) == len(out["levels"]["below"]) == copilot_book.MAX_LEVELS_EACH_SIDE
    small = _workspace(bars=3, zones=0, big=94.0)
    small["auto_levels"]["zones"] = [{"id": "a", "low": 99.0, "high": 99.5, "label": "Prior day high", "score": 2},
                                     {"id": "b", "low": 97.0, "high": 97.4, "label": "Opening range high", "score": 1},
                                     {"id": "c", "low": 95.8, "high": 96.2, "label": "VWAP", "score": 1},
                                     {"id": "d", "low": 90.0, "high": 90.5, "label": "Prior day low", "score": 3}]
    small["panels"]["5m"]["level_events"] = {"b": {"state": "tested"}, "d": {"state": "broken"}}
    out = copilot_book.compact_chart("NBIS", "5m", small)
    assert out["bars"]["shown"] == 3 and out["last"] == 96.0 and out["vwap"] == {"vwap": 94.0, "sd": 12.35, "band_1sd": [81.65, 106.35]}
    assert [z["label"] for z in out["levels"]["above"]] == ["Opening range high", "Prior day high"]  # nearest first
    assert out["levels"]["at"][0]["label"] == "VWAP" and out["levels"]["above"][0]["state"] == "tested"
    assert out["levels"]["below"] == [{"low": 90.0, "high": 90.5, "label": "Prior day low", "score": 3, "state": "broken"}]
    assert out["bars"]["rows"][0][0] == "10-22 16:13" and out["quote"]["previous_close"] == 94.0 and out["rvol"]["baseline_sessions"] == 20


def test_chart_context_reports_an_unavailable_feed(monkeypatch):
    from app.engine import chart_feed as feed

    def refuse(*args, **kwargs):
        raise feed.ChartFeedError("Tradier is not configured.", "not_configured")

    monkeypatch.setattr(feed.chart_feed, "workspace", refuse)
    out = copilot_tools.LiveEvidence().get_chart_context("NBIS", "5m")
    assert out["state"] == "unavailable" and "Tradier" in out["reason"] and out["as_of"]


# --------------------------------------------------------------------------- the book

def test_positions_are_marked_labelled_and_carry_no_account_identifier(db, marks):
    out = copilot_book.positions(session=db)
    text = _secret_free(out)
    rows = {r["symbol"]: r for r in out["positions"]}
    assert set(rows) == {"NBIS", "CRWV"} and out["count"] == 2  # Webull's open NBIS shares are left out
    call = rows["NBIS"]
    assert call["option"] == {"side": "call", "strike": 100.0, "expiry": "2099-01-15"} and call["quantity"] == 2
    assert (call["avg_entry"], call["mark"], call["unrealized_usd"], call["unrealized_pct"]) == (310.0, 400.0, 180.0, 29.0)
    stock = rows["CRWV"]
    assert (stock["avg_entry"], stock["mark"], stock["unrealized_usd"], stock["unrealized_pct"]) == (120.0, 131.2, 112.0, 9.3)
    assert call["account"] == stock["account"] == "Robinhood Roth" and call["days_held"] >= 0
    assert "trade_id" not in text and "last4" not in text


def test_a_large_book_is_capped_and_still_fits(db, marks):
    db.add_all([fill(100 + i, f"T{i:02d}"[:5], "buy", 10, 100 + i, "2026-10-10T10:00") for i in range(40)])
    db.commit()
    _rebuild_trades(db, "test")
    out = copilot_book.positions(session=db)
    _secret_free(out)
    assert out["count"] == 42 and out["shown"] == copilot_book.MAX_POSITIONS


def test_trades_are_closed_only_newest_first_with_tags(db):
    from sqlmodel import select
    from app.models import Trade
    closed = db.exec(select(Trade).where(Trade.ticker == "CRWV", Trade.status != "open", Trade.account_id == ROTH)).one()
    tag = Tag(name="breakout", source="manual")
    db.add(tag)
    db.commit()
    db.add(TradeTag(trade_id=closed.id, tag_id=tag.id))
    db.commit()
    out = copilot_book.trades("CRWV", 10, session=db)
    _secret_free(out)
    [row] = out["trades"]  # the open lot and Webull's closed trade are not here
    assert (row["entry_price"], row["exit_price"], row["pnl_usd"], row["tags"]) == (100.0, 110.0, 50.0, ["breakout"])
    assert row["hold_minutes"] == 300 and row["account"] == "Robinhood Roth"
    assert copilot_book.trades("ZZZZ", 5, session=db)["trades"] == []


def test_memories_are_the_approved_ones_only(db):
    base = {"kind": "lesson", "source": "owner_statement", "original_text": "I chase green opens."}
    jo_briefing.save_memory(db, jo_briefing.MemorySave(operation_id="m1", status="active", owner_confirmed=True, **base))
    jo_briefing.save_memory(db, jo_briefing.MemorySave(operation_id="m2", status="proposed",
                                                       **{**base, "original_text": "Jo thinks so."}))
    jo_briefing.save_memory(db, jo_briefing.MemorySave(operation_id="m3", status="retired", owner_confirmed=True,
                                                       **{**base, "original_text": "Old rule."}))
    out = copilot_book.memories(10, session=db)
    _secret_free(out)
    assert [m["text"] for m in out["memories"]] == ["I chase green opens."] and out["memories"][0]["kind"] == "lesson"


def test_memories_fit_at_their_cap(db):
    for i in range(12):
        jo_briefing.save_memory(db, jo_briefing.MemorySave(operation_id=f"big{i}", kind="thesis", symbol="NBIS", source="owner_statement",
                                                           original_text="T" * 4000, interpretation="I" * 4000,
                                                           status="active", owner_confirmed=True))
    out = copilot_book.memories(10, session=db)
    _secret_free(out)
    assert len(out["memories"]) == copilot_book.MAX_MEMORIES


# --------------------------------------------------------------------------- fixture, replay and the turn

@pytest.mark.parametrize("name,args", [("get_chart_context", {"symbol": "NBIS", "timeframe": "5m"}), ("get_positions", {}),
                                       ("get_trades", {"symbol": "NBIS", "limit": 5}), ("get_memories", {"limit": 5})])
def test_fixture_book_is_simulated_and_replay_is_unavailable(name, args):
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                           key_configured=False)
    result, event = asyncio.run(copilot._run_tool(FixtureEvidence(), {"id": "t", "name": name, "input": args}, cfg))
    data = json.loads(result["content"])
    assert event["status"] == "ok" and event["provenance"]["kind"] == "simulated" and data["simulated"] is True
    assert "SIMULATED" in event["provenance"]["source"] and len(result["content"]) <= copilot_tools.MAX_RESULT_CHARS
    replay = ReplayEvidence.__new__(ReplayEvidence)  # these four read no snapshot state
    assert getattr(replay, name)(**args)["state"] == "unavailable"


def test_a_scripted_turn_reads_the_book_and_the_chart():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                           key_configured=False)

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "What am I holding in NBIS?"}], "NBIS", cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 23, 11, 12))]
    events = asyncio.run(collect())
    tools = {e["name"]: e for e in events if e["type"] == "tool" and e["status"] != "running"}
    assert set(tools) == {"owner_context", "get_positions", "get_chart_context"} and all(t["status"] == "ok" for t in tools.values())
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Your open positions:" in text and "NBIS option 2 at 610.0, now 455.0" in text and "Simulated" in text
    assert events[-1]["type"] == "done"


def test_the_system_prompt_guards_account_identifiers():
    assert "get_positions" in copilot.SYSTEM_PROMPT and "Never reveal or guess account numbers" in copilot.SYSTEM_PROMPT


# --------------------------------------------------------------------------- review fixes: New York times, worst cases, one batch

def test_journal_times_are_new_york_with_their_offset_across_dst(db, marks):
    """Journal times are naive New York wall clocks: never emitted as UTC, and days held count from that moment."""
    from app.engine.chart_math import ET
    db.add_all([fill(20, "AMD", "buy", 1, 150, "2026-11-30T09:30:15"), fill(21, "AMD", "sell", 1, 155, "2026-11-30T10:30:15")])
    db.commit()
    _rebuild_trades(db, "test")
    [summer] = copilot_book.trades("CRWV", 10, session=db)["trades"]
    assert (summer["entry_time"], summer["exit_time"]) == ("2026-10-01T10:00:00-04:00", "2026-10-01T15:00:00-04:00")
    [winter] = copilot_book.trades("AMD", 10, session=db)["trades"]
    assert (winter["entry_time"], winter["exit_time"]) == ("2026-11-30T09:30:15-05:00", "2026-11-30T10:30:15-05:00")
    nbis = next(r for r in copilot_book.positions(session=db)["positions"] if r["symbol"] == "NBIS")
    assert nbis["opened_at"] == "2026-10-20T09:42:00-04:00"
    assert nbis["days_held"] == (datetime.now(ET) - datetime(2026, 10, 20, 9, 42, tzinfo=ET)).days


def _worst_book():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(Account(id=ROTH, name="Individual Brokerage Account With A Long Name Here 1234", type="individual",
                        last4="1234", broker="robinhood"))
    session.commit()
    return session


def test_trades_at_every_cap_fit_with_headroom():
    db = _worst_book()
    tags = [Tag(name=f"T{k}" + "x" * 60, source="manual") for k in range(8)]
    db.add_all(tags)
    db.add_all([fill(5000 + 2 * i + j, "ABCDEFGHIJ", side, 99999.5, 123456.78 if j == 0 else 0.01, f"2020-01-{1 + i:02d}T{9 + 6 * j:02d}:30:15",
                     option_type="put", strike=12345.67, expiration=date(2020, 1, 31))
                for i in range(12) for j, side in enumerate(("buy_to_open", "sell_to_close"))])
    db.commit()
    _rebuild_trades(db, "test")
    from sqlmodel import select
    from app.models import Trade
    db.add_all([TradeTag(trade_id=t.id, tag_id=g.id) for t in db.exec(select(Trade)).all() for g in tags])
    db.commit()
    out = copilot_book.trades("ABCDEFGHIJ", 10, session=db)
    text = copilot_tools.bounded(out)
    assert len(out["trades"]) == 10 and len(out["trades"][0]["tags"]) == copilot_book.MAX_TAGS
    assert all(len(tag) <= copilot_book.MAX_TAG_CHARS for tag in out["trades"][0]["tags"])
    assert len(text) <= copilot_tools.MAX_RESULT_CHARS - 200, len(text)


def test_positions_at_every_cap_fit(monkeypatch):
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: 987654.321 for s in symbols})
    monkeypatch.setattr(quotes, "get_option_quotes", lambda requests: [OptionQuoteResult(mid=9876.5432)] * len(requests))
    monkeypatch.setattr(quotes, "option_mark", lambda req: (OptionQuoteResult(mid=9876.5432), 1792768320.123))
    db = _worst_book()
    db.add_all([fill(1000 + i, f"ABCDEFGH{i:02d}", "sell_to_open", 99999.5, 123456.78, "2020-01-01T09:30",
                     option_type="call", strike=12345.67, expiration=date(2099, 12, 31)) for i in range(20)])
    db.commit()
    _rebuild_trades(db, "test")
    out = copilot_book.positions(session=db)
    text = copilot_tools.bounded(out)
    assert out["shown"] == copilot_book.MAX_POSITIONS and len(text) <= copilot_tools.MAX_RESULT_CHARS, len(text)
    assert out["positions"][0]["account"] == "Individual Brokerage"


def test_option_marks_come_from_one_batched_read(db, monkeypatch):
    batches = []
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: 131.2 for s in symbols})
    monkeypatch.setattr(quotes, "get_option_quotes", lambda requests: batches.append(len(requests)) or [OptionQuoteResult(mid=4.0)] * len(requests))
    monkeypatch.setattr(quotes, "option_mark", lambda req: (OptionQuoteResult(mid=4.0), 1792768320.0))
    db.add(fill(30, "NBIS", "buy_to_open", 1, 200, "2026-10-21T10:00", option_type="put", strike=90, expiration=LATER))
    db.commit()
    _rebuild_trades(db, "test")
    copilot_book.positions(session=db)
    assert batches == [2]  # both open options in one provider read; the marks after it read the cache
