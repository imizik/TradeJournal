"""Your history at this level (docs/copilot-lab.md § Your history at this level): the owner's own closed long option
trades in a symbol replayed over minute bars at a level the same percent from each entry as the drafted invalidation is
from the planned entry (crossed, recovered, not crossed; the time mark), Webull and older trades left out; the small
sample said plainly; free of identifiers and within the tool bound; validated, routed and labelled; simulated in the
fixture, unavailable in replay; never given to research jobs; the scripted model quotes it beside its plan card; the
system prompt asks for it as evidence, never a rule."""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import copilot, copilot_review, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.copilot_replay import ReplayEvidence
from app.models import Account, Fill
from app.routers.fills import _rebuild_trades
from tests.secret_scan import leaks

ROTH, WEBULL = UUID(int=3001), UUID(int=3002)
EXPIRY = date(2026, 11, 20)
CALL = {"option_type": "call", "strike": 100, "expiration": EXPIRY}
PUT = {"option_type": "put", "strike": 100, "expiration": EXPIRY}
NOW = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
# New York wall-clock entries (EDT: 10:05 ET is 14:05Z); each trade is held an hour unless said otherwise.
A, B, C = datetime(2026, 10, 20, 10, 5), datetime(2026, 10, 21, 10, 5), datetime(2026, 10, 22, 10, 5)
SECRETS = ("8267", "4242", "RH-55501234", "WB-99887766", str(ROTH), str(WEBULL))


def fill(n, ticker, side, qty, price, at, underlying=None, account=ROTH, **option):
    return Fill(id=UUID(int=n), account_id=account, ticker=ticker, instrument_type="option", side=side, contracts=qty, price=price,
                executed_at=at, raw_email_id=f"hist:{n}", underlying_price_at_fill=underlying, **option)


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
            fill(1, "NBIS", "buy_to_open", 1, 300, A, underlying=100.0, **CALL),             # crosses -2.2%, recovers, -$12
            fill(2, "NBIS", "sell_to_close", 1, 288, A + timedelta(minutes=60), **CALL),
            fill(3, "NBIS", "buy_to_open", 1, 200, B, underlying=50.0, **CALL),              # crosses at a different price, no
            fill(4, "NBIS", "sell_to_close", 1, 120, B + timedelta(minutes=20), **CALL),     # recovery, -$80, out in 20 min
            fill(5, "NBIS", "buy_to_open", 1, 150, C, underlying=200.0, **CALL),             # dips 1.5% only: not crossed, +$60
            fill(6, "NBIS", "sell_to_close", 1, 210, C + timedelta(minutes=60), **CALL),
            fill(7, "NBIS", "buy_to_open", 1, 100, C + timedelta(hours=2), underlying=200.0, **PUT),   # a put: the other side
            fill(8, "NBIS", "sell_to_close", 1, 90, C + timedelta(hours=3), **PUT),
            fill(9, "NBIS", "buy_to_open", 1, 100, B, underlying=50.0, account=WEBULL, **CALL),        # dormant: out
            fill(10, "NBIS", "sell_to_close", 1, 50, B + timedelta(minutes=60), account=WEBULL, **CALL),
            fill(11, "NBIS", "buy_to_open", 1, 100, A - timedelta(days=400), underlying=80.0, **CALL),  # before the window
            fill(12, "NBIS", "sell_to_close", 1, 50, A - timedelta(days=400, minutes=-60), **CALL),
            fill(13, "CRWV", "buy_to_open", 1, 100, A, underlying=130.0, **CALL),                       # another symbol
            fill(14, "CRWV", "sell_to_close", 1, 50, A + timedelta(minutes=60), **CALL),
        ])
        session.commit()
        _rebuild_trades(session, "test")
        yield session
    engine.dispose()


def _bars(start_utc: datetime, minutes: int, price, lows: dict[int, float] | None = None, closes: dict[int, float] | None = None):
    """Minute bars from ``start_utc``: flat at ``price`` except a bar's low or close set by minute offset."""
    out = []
    for i in range(minutes):
        at = start_utc + timedelta(minutes=i)
        low = (lows or {}).get(i, price)
        close = (closes or {}).get(i, price)
        out.append({"t": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": price, "h": max(price, close), "l": min(low, close), "c": close, "v": 1000})
    return out


def _utc(wall: datetime) -> datetime:
    return wall + timedelta(hours=4)  # EDT


UNDERLYING = {
    # A: 100 -> low 97.0 at minute 30 (-3%, under the -2.2% target of 97.8); the option sinks then recovers.
    date(2026, 10, 20): _bars(_utc(A), 61, 100.0, lows={30: 97.0}),
    # B: 50 -> low 48.5 at minute 10 (-3%, under 48.9); out at minute 20, never recovers.
    date(2026, 10, 21): _bars(_utc(B), 21, 50.0, lows={10: 48.5}),
    # C: 200 -> low 197 at minute 15 (-1.5%, above 195.6): not crossed. The put later the same day sees a 1% rise.
    date(2026, 10, 22): _bars(_utc(C), 61, 200.0, lows={15: 197.0}) + _bars(_utc(C) + timedelta(hours=2), 61, 200.0, closes={5: 202.0}),
}
OPTIONS = {
    UUID(int=1): _bars(_utc(A), 60, 3.0, closes={30: 2.4, 31: 2.5, 45: 3.1, 59: 2.9}),   # 240 at the cross, later 310 >= 300
    UUID(int=3): _bars(_utc(B), 20, 1.9, closes={10: 1.5, 15: 1.8}),                      # 150 at the cross, never back to 200
    UUID(int=5): _bars(_utc(C), 60, 1.5, closes={15: 1.4, 40: 2.2}),
}


def bars(ticker: str, day: date) -> list[dict]:
    return UNDERLYING.get(day, []) if ticker == "NBIS" else []


def option_bars(trade) -> list[dict] | None:
    return OPTIONS.get(trade.id)


def history(db, **kw):
    return copilot_review.level_history("NBIS", session=db, bars=bars, option_bars=option_bars, now=NOW, **kw)


def test_a_level_is_matched_by_distance_from_each_entry_and_the_counts_follow(db):
    out = history(db, level=97.8, side="below", entry=100.0)
    assert out["state"] == "ok" and out["kind"] == "level" and out["note"] == copilot_review.HISTORY_NOTE
    assert out["asked"] == {"level": 97.8, "side": "below", "entry": 100.0, "entry_from": "planned", "distance_pct": -2.2}
    # Long calls only (the put, Webull, the trade before the window and CRWV stay out): 3 trades, 2 crossed.
    assert out["sample"] == {"trades": 3, "counted": "long calls", "small": True,
                             "note": "Only 3 closed long calls trades in NBIS in the window: too small to weigh."}
    # A (100 -> 97) and B (50 -> 48.5) both crossed 2.2% under their own entry; C (200 -> 197) did not.
    assert out["crossed"] == {"trades": 2, "of": 3, "pct": 66.7, "recovered_to_breakeven": 1, "recovery_known": 2,
                              "median_pnl_from_cross_pct": 0.0, "valued": 2}   # +20% (240 -> 288) and -20% (150 -> 120)
    assert out["pnl"] == {"crossed": {"trades": 2, "pnl_usd": -92.0, "win_rate_pct": 0.0},
                          "not_crossed": {"trades": 1, "pnl_usd": 60.0, "win_rate_pct": 100.0}}
    assert out["coverage"] == {"no_entry_price": 0, "no_bars": 0, "no_option_bars": 0}
    assert set(out["provenance"]) == set(copilot_review.HISTORY_PROVENANCE)
    text = json.dumps(out)
    assert not leaks(text, SECRETS) and len(copilot_tools.bounded(out)) <= copilot_tools.MAX_RESULT_CHARS


def test_the_distance_is_what_matters_not_the_price(db):
    # The same -2.2% drafted from a 50 entry: the same past trades cross it.
    assert history(db, level=48.9, side="below", entry=50.0)["crossed"]["trades"] == 2
    # A wider -5%: no past trade fell that far from its entry.
    wide = history(db, level=95.0, side="below", entry=100.0)
    assert wide["crossed"]["trades"] == 0 and wide["crossed"]["median_pnl_from_cross_pct"] is None
    assert wide["pnl"]["not_crossed"]["trades"] == 3
    # A level above counts the long puts: the one put saw +1% while held.
    above = history(db, level=201.0, side="above", entry=200.0)
    assert above["sample"]["counted"] == "long puts" and above["sample"]["trades"] == 1
    assert above["crossed"]["trades"] == 1 and above["crossed"]["recovery_known"] == 0  # no option bars cached for it
    assert above["coverage"]["no_option_bars"] == 1


def test_a_time_mark_counts_the_trades_still_held_then(db):
    out = history(db, minutes=30)
    assert out["kind"] == "time" and out["asked"] == {"minutes": 30} and out["sample"]["counted"] == "long options"
    assert out["sample"]["trades"] == 4  # calls and the put alike
    # A, C and the put were held past 30 minutes; B was out at 20. From A's 30-minute mark (240) the exit was 288.
    assert out["held_past"]["trades"] == 3 and out["held_past"]["of"] == 4
    assert out["held_past"]["valued"] == 2 and out["held_past"]["recovery_known"] == 2 and out["held_past"]["recovered_to_breakeven"] == 2
    assert out["pnl"]["out_before"] == {"trades": 1, "pnl_usd": -80.0, "win_rate_pct": 0.0}
    assert set(out["provenance"]) == set(copilot_review.TIME_PROVENANCE) and out["note"] == copilot_review.HISTORY_NOTE


def test_missing_bars_or_entry_prices_are_counted_not_guessed(db):
    out = copilot_review.level_history("NBIS", level=97.8, side="below", entry=100.0, session=db, now=NOW,
                                       bars=lambda ticker, day: [], option_bars=lambda trade: None)
    assert out["crossed"] == {"trades": 0, "of": 0, "pct": None, "recovered_to_breakeven": 0, "recovery_known": 0,
                              "median_pnl_from_cross_pct": None, "valued": 0}
    assert out["coverage"]["no_bars"] == 3
    db.get(Fill, UUID(int=1)).underlying_price_at_fill = None
    db.commit()
    assert history(db, level=97.8, side="below", entry=100.0)["coverage"]["no_entry_price"] == 1


def test_without_a_planned_entry_the_current_price_is_the_reference(db, monkeypatch):
    monkeypatch.setattr(copilot_review, "_current_price", lambda symbol: 100.0)
    out = history(db, level=97.8, side="below")
    assert out["asked"]["entry_from"] == "current" and out["asked"]["distance_pct"] == -2.2
    # A level on the wrong side of the reference has no distance to match on.
    wrong = history(db, level=102.0, side="below", entry=100.0)
    assert wrong["state"] == "unavailable" and "is not below the entry 100.0" in wrong["reason"]
    assert history(db, level=98.0, side="above", entry=100.0)["state"] == "unavailable"
    monkeypatch.setattr(copilot_review, "_current_price", lambda symbol: None)
    out = history(db, level=97.8, side="below")
    assert out["state"] == "unavailable" and "pass the planned entry" in out["reason"] and out["note"] == copilot_review.HISTORY_NOTE


# --------------------------------------------------------------------------- the tool

def test_the_tool_is_validated_routed_labelled_and_never_a_job_tool(monkeypatch):
    v = copilot_tools.validate
    assert v("get_level_history", {"symbol": "nbis", "level": 92.3, "side": "below"}) == {"symbol": "NBIS", "level": 92.3, "side": "below", "lookback_days": 180}
    assert v("get_level_history", {"symbol": "NBIS", "level": 92.3, "side": "above", "entry": 95.9, "lookback_days": 30}) == \
        {"symbol": "NBIS", "level": 92.3, "side": "above", "entry": 95.9, "lookback_days": 30}
    assert v("get_level_history", {"symbol": "NBIS", "minutes": 120}) == {"symbol": "NBIS", "minutes": 120, "lookback_days": 180}
    for bad in ({"symbol": "NBIS"}, {"symbol": "NBIS", "level": 92.3}, {"symbol": "NBIS", "level": 0, "side": "below"},
                {"symbol": "NBIS", "level": float("inf"), "side": "below"}, {"symbol": "NBIS", "level": 92.3, "side": "under"},
                {"symbol": "NBIS", "level": 92.3, "side": "below", "minutes": 30}, {"symbol": "NBIS", "minutes": 2},
                {"symbol": "NBIS", "minutes": 30, "side": "below"}, {"symbol": "NBIS", "level": 92.3, "side": "below", "lookback_days": 29},
                {"symbol": "NBIS", "level": 92.3, "side": "below", "lookback_days": 366}, {"symbol": "NBIS", "level": 92.3, "side": "below", "entry": -1},
                {"symbol": "NBIS", "level": True, "side": "below"}, {"symbol": "nb is", "level": 92.3, "side": "below"},
                {"symbol": "NBIS", "level": 92.3, "side": "below", "trade_id": "x"}):
        with pytest.raises(copilot_tools.ToolInputError):
            v("get_level_history", bad)
    seen = []
    monkeypatch.setattr(copilot_review, "level_history", lambda symbol, **kw: seen.append((symbol, kw)) or {"state": "ok"})
    copilot_tools.call(copilot_tools.LiveEvidence(), "get_level_history", v("get_level_history", {"symbol": "NBIS", "level": 92.3, "side": "below", "entry": 95.9}))
    assert seen == [("NBIS", {"level": 92.3, "side": "below", "minutes": None, "entry": 95.9, "lookback_days": 180})]
    assert copilot_tools.provenance("get_level_history", {"state": "ok"}, "live")["kind"] == "saved"
    assert "get_level_history" not in research_job.JOB_TOOLS and "mcp__tradejournal__get_level_history" not in research_job.LAB_TOOLS
    assert "get_level_history" in copilot_tools.BOOK_CONTEXT_TOOLS


def test_replay_is_unavailable_and_the_fixture_is_simulated():
    replay = ReplayEvidence.__new__(ReplayEvidence)
    assert replay.get_level_history("NBIS", level=92.3, side="below")["state"] == "unavailable"
    fixture = FixtureEvidence().get_level_history("NBIS", level=92.3, side="below", entry=95.9)
    assert fixture["simulated"] is True and fixture["state"] == "ok" and fixture["note"] == copilot_review.HISTORY_NOTE
    assert set(fixture["provenance"]) == set(copilot_review.HISTORY_PROVENANCE) and fixture["asked"]["distance_pct"] == -3.75
    assert len(copilot_tools.bounded(fixture)) <= copilot_tools.MAX_RESULT_CHARS
    timed = FixtureEvidence().get_level_history("NBIS", minutes=120)
    assert timed["simulated"] is True and timed["kind"] == "time" and set(timed["provenance"]) == set(copilot_review.TIME_PROVENANCE)


def test_the_scripted_model_asks_for_the_history_and_quotes_it_beside_the_plan():
    cfg = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False, key_configured=False)

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "Context: Plan a trade: yolo NBIS calls"}], "NBIS", cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime(2026, 10, 24, 11, 12))]
    events = asyncio.run(collect())
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_level_history" and e["status"] == "ok"]
    [card] = [e for e in events if e["type"] == "proposal"]
    assert tool["input"] == {"symbol": "NBIS", "level": 92.3, "side": "below", "entry": 95.9, "lookback_days": 180}
    assert tool["provenance"]["kind"] == "simulated"
    assert tool["summary"] == "12 of 31 past NBIS trades crossed -3.8% while held; 5 recovered to breakeven; median -18% from there"
    # The card's row: the counts for the drafted invalidation, so the UI can show them under that field.
    assert tool["history"] == {"symbol": "NBIS", "level": card["invalidation"]["price"], "side": "below", "entry": 95.9, "distance_pct": -3.75, "trades": 31,
                               "crossed": 12, "recovered": 5, "median_from_cross_pct": -18.0, "small": False, "simulated": True}
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Your history: 12 of 31 past NBIS trades crossed -3.8% while held; 5 recovered to breakeven; median -18% from there. Evidence to weigh, not a rule." in text
    assert "validated" not in text and "recommended" not in text
    assert "Too few trades" not in text and copilot.level_history_sentence({"state": "ok", "symbol": "X", "kind": "level", "sample": {"trades": 3, "small": True},
                                                                            "asked": {"distance_pct": -2.0}, "crossed": {"trades": 1, "of": 3, "recovered_to_breakeven": 0}}) \
        == "Your history: 1 of 3 past X trades crossed -2.0% while held; 0 recovered to breakeven. Evidence to weigh, not a rule. Only 3 trades: too small a sample to weigh."
    assert copilot.level_history_card({"state": "unavailable"}) is None and copilot.level_history_card({"state": "ok", "kind": "time"}) is None


def test_the_system_prompt_asks_for_evidence_never_a_rule():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    for phrase in ("Before you propose a trade_plan, call get_level_history for the drafted invalidation",
                   "once more with minutes when the time stop is a length of time",
                   "Say in one sentence what the owner's own history shows there, with the counts",
                   "Never call a level validated, proven or recommended",
                   "the invalidation study found no level or time stop that holds up as a default",
                   "evidence to weigh, not a rule", "When fewer than 10 trades are counted, say the sample is too small to weigh"):
        assert phrase in prompt, phrase
    # The pinned plan sentences stay.
    for phrase in ("exactly one propose_plan kind=trade_plan", "nothing exists until they confirm it"):
        assert phrase in prompt, phrase
