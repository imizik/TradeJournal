"""The owner pack's market and practice sections (docs/copilot-lab.md § Owner context): the turn's market read handed to
the model up front in all three evidence modes, never holding the turn, never leaking past replay's clock, inside the cap."""
import asyncio
import json
import time
from datetime import date, datetime

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import copilot_context, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.engine import practice_goal
from app.engine.chart_math import ET
from app.engine.radar_comparison import iso
from app.engine.radar_store import RadarStore
from tests.test_copilot import _turn
from tests.test_copilot_context import Capture
from tests.test_copilot_regime import BASE, _store


def _market(evidence, symbol, timeout=copilot_context.MARKET_TIMEOUT_S):
    return asyncio.run(copilot_context.market(evidence, symbol, timeout))


def _lines(section):
    return [line["line"] for line in section["lines"]]


# --------------------------------------------------------------------------- fixture

def test_a_symbol_question_carries_the_quote_regime_and_group_line():
    section = _market(FixtureEvidence(), "nbis")
    lines = _lines(section)
    assert section["state"] == "ok" and section["simulated"] is True
    assert lines[0] == "day change SPY -0.20% · QQQ -0.35% · VIX 18.4 (+4.20%)"
    assert "NBIS last 94.35, -2.95% on the day" in lines
    assert any(line.startswith("sector XLK -0.48%; NBIS -2.47 pts vs XLK") for line in lines)
    assert any(line.startswith("Neoclouds and AI hosting: NBIS -2.95% since the open") and "SPY -0.20%" in line for line in lines)
    assert all(line.get("as_of") and line.get("from") for line in section["lines"])
    # Only the events that name the symbol, with their first-seen time.
    assert [e["first_seen"] for e in section["radar_events"]] == ["2026-10-23T14:58:00Z", "2026-10-23T14:30:00Z"]
    assert "leaders_vs_spy" not in section


def test_no_symbol_gives_the_index_line_and_the_days_leaders_and_laggards():
    section = _market(FixtureEvidence(), None)
    assert _lines(section) == ["day change SPY -0.20% · QQQ -0.35% · VIX 18.4 (+4.20%)"]
    assert section["leaders_vs_spy"].startswith("APLD +1.05") and section["laggards_vs_spy"].startswith("NBIS -2.75")
    assert section["radar_events_total"] == 3 and section["movers_as_of"] == "2026-10-23T15:12:00Z"


def test_the_turn_hands_the_model_the_market_lines_and_the_practice_goal_in_the_pack():
    adapter = Capture()
    events = _turn([{"role": "user", "content": "Why is NBIS moving?"}], adapter, FixtureEvidence())
    content = adapter.seen[0][-1]["content"]
    assert "fresh enough to answer from" in content
    pack = json.loads(content.split("\n\n", 1)[1].split("\n")[1])
    keys = list(pack)
    assert keys.index("symbol") < keys.index("market") < keys.index("positions")  # read first, after the header
    assert "NBIS last 94.35, -2.95% on the day" in _lines(pack["market"])
    assert pack["practice"]["goal"].startswith("Simulated:") and pack["practice"]["this_week"].startswith("2 of 3")
    assert "market" in pack["provenance"] and "practice" in pack["provenance"]
    assert len(json.dumps(pack, separators=(",", ":"))) <= copilot_context.MAX_PACK_CHARS + copilot_context.MAX_MARKET_CHARS
    assert "4 market lines" in events[0]["summary"] and "practice goal" in events[0]["summary"]


# --------------------------------------------------------------------------- live

def _live(tmp_path, monkeypatch, quote_rows):
    from app.ai import copilot_extended
    from app.engine import chart_feed as feed_module, symbol_info_tradier
    from app.routers import radar
    store = _store(tmp_path / "radar.sqlite", with_future=False)
    monkeypatch.setattr(radar, "_store", lambda read_only=False: (RadarStore(store.path, read_only=True), None))
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", quote_rows)
    monkeypatch.setattr(copilot_extended, "extended", lambda symbols, now: None)  # the regular session
    monkeypatch.setattr(copilot_extended, "phase", lambda now: "regular")
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "chart_earnings", lambda wanted, watchlist, today: {})
    return copilot_tools.LiveEvidence()


def _rows(symbols):
    table = {"SPY": (671.10, -0.2), "QQQ": (598.40, -0.35), "NBIS": (94.35, -2.95), "VIX": (18.4, 4.2), "US10Y": (4.12, None)}
    return ([{"symbol": s, "last": table[s][0], "change_percentage": table[s][1], "trade_time": BASE} for s in symbols if s in table],
            BASE, None)


def test_live_reads_the_same_cached_readers_the_tools_use(tmp_path, monkeypatch):
    evidence = _live(tmp_path, monkeypatch, _rows)
    section = _market(evidence, "NBIS")
    lines = _lines(section)
    assert section["state"] == "ok" and "simulated" not in section
    assert lines[0] == "day change SPY -0.20% · QQQ -0.35% · VIX 18.4 (+4.20%)"
    assert section["lines"][0]["as_of"].startswith(iso(BASE)[:19])
    assert "NBIS last 94.35, -2.95% on the day" in lines
    assert any(line.startswith("sector XLK ") for line in lines)  # the latest recorded Radar pass
    assert [e["line"] for e in section["radar_events"]] == ["NBIS turned up from its session low"]


def test_a_failed_or_slow_read_reads_as_unavailable_and_never_holds_the_turn(tmp_path, monkeypatch):
    def broken(symbols):
        from app.engine.chart_feed import ChartFeedError
        raise ChartFeedError("Tradier cooling down")

    evidence = _live(tmp_path, monkeypatch, broken)
    monkeypatch.setattr(type(evidence), "get_group_comparison", lambda self, symbol, group=None: time.sleep(2) or {})
    monkeypatch.setattr(type(evidence), "get_quotes", lambda self, symbols: 1 / 0)
    async def timed():
        started = time.monotonic()
        out = await copilot_context.market(evidence, "NBIS", 0.5)
        return out, time.monotonic() - started

    section, took = asyncio.run(timed())  # (asyncio.run itself then waits for the slow thread; the turn's loop does not)
    assert took < 1.5
    assert section["unavailable"]["quotes"] == "the read failed" and section["unavailable"]["group"].startswith("slower than 0.5")
    # The Radar pass still answers for the indices and the sector; VIX's failure is not invented as a number.
    assert _lines(section)[0].startswith("day change SPY ") and "VIX" not in _lines(section)[0]
    assert section["radar_events"]

    class Bare:  # evidence without market reads gets no section, and a pack without one is untouched
        label = "live"
    assert _market(Bare(), "NBIS") is None and copilot_context.with_market({"state": "ok"}, None) == {"state": "ok"}


# --------------------------------------------------------------------------- replay

def test_replay_reads_the_frozen_moment_and_never_later(tmp_path, monkeypatch):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine import symbol_info_tradier
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", lambda symbol, today: {"symbol": symbol, "today": today.isoformat()})
    at = parse_at("2026-10-23T11:12")
    full = ReplayEvidence(str(_store(tmp_path / "full.sqlite", with_future=True).path), at)
    cut = ReplayEvidence(str(_store(tmp_path / "cut.sqlite", with_future=False).path), at)
    for symbol in ("NBIS", None):
        seen = _market(full, symbol)
        assert json.dumps(seen, sort_keys=True) == json.dumps(_market(cut, symbol), sort_keys=True)
        assert "later" not in json.dumps(seen) and "721" not in json.dumps(seen)
    section = _market(full, "NBIS")
    assert section["lines"][0]["as_of"] == iso(BASE) and "VIX" not in section["lines"][0]["line"]
    assert any(line.startswith("NBIS last 94.35") for line in _lines(section))
    # Replay's pack is unavailable (it would show today's book), but the market lines still reach the model.
    pack = copilot_context.with_market(full.owner_context("NBIS"), section)
    assert pack["state"] == "unavailable" and pack["market"] is section
    assert copilot_context.summary(pack).endswith("market lines")


# --------------------------------------------------------------------------- the cap

def test_an_oversized_pack_slims_the_market_late_and_keeps_its_lines():
    section = _market(FixtureEvidence(), "NBIS")
    pack = {"state": "ok", "as_of": "x", "symbol": "NBIS", "provenance": copilot_context.PROVENANCE,
            "positions": {"state": "ok", "positions": [{"symbol": "NBIS", "note": "x" * 900}] * 6},
            "memories": {"state": "ok", "memories": [{"text": "m" * 230}] * 8},
            "today": {"state": "ok", "entries": [{"text": "t" * 230}] * 6}}
    assert len(json.dumps(section, separators=(",", ":"))) <= copilot_context.MAX_MARKET_CHARS
    out = copilot_context.with_market(pack, section)
    most = copilot_context.MAX_PACK_CHARS + copilot_context.MAX_MARKET_CHARS
    assert out["trimmed"] is True and len(json.dumps(out, separators=(",", ":"))) <= most
    assert "entries" not in out["today"] and "memories" not in out["memories"]
    assert len(out["market"]["lines"]) == 4 and "radar_events" not in out["market"]
    assert all("from" not in line and line["as_of"] for line in out["market"]["lines"])


# --------------------------------------------------------------------------- practice

def test_the_practice_goal_is_the_owners_words_its_measure_and_this_weeks_count():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    copilot_context.clear_habits_cache()
    now = datetime(2026, 11, 10, 10, 30, tzinfo=ET)
    with Session(engine) as db:
        assert copilot_context._practice(db, now) == {"state": "ok", "goal": None}
        copilot_context.clear_habits_cache()
        practice_goal.save(db, text="Plan before I enter.", measure="plan_before_entry", target=None, investigation_id=None,
                           today=date(2026, 11, 3))
        out = copilot_context._practice(db, now)
    assert out["goal"] == "Plan before I enter." and out["measure"] == practice_goal.label("plan_before_entry", None)
    assert out["this_week"].startswith("0 of 0") and "target" not in out and out["as_of"].startswith("2026-11-10")


def test_a_busy_session_never_pushes_the_symbols_own_events_out(tmp_path):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine.radar_store import load_universe
    store = _store(tmp_path / "busy.sqlite", with_future=False)
    for n in range(15):  # newer events on another symbol, more than the read's limit of 12
        at = BASE - 300 + n
        store.append_event({"event_id": f"rad_busy_{n}", "session_date": "2026-10-23", "rule_version": "t",
                            "universe_version": load_universe()["version"], "kind": "dip_turn", "direction": "up",
                            "symbols": ["CRWV"], "benchmark": "SPY", "group": "Other", "first_seen_at": iso(at),
                            "summary": f"CRWV event {n}", "measures": {}, "evidence": [],
                            "coverage": {"passes_expected": 1, "passes_recorded": 1, "symbols_missing": []},
                            "chart": {"symbol": "CRWV", "from": iso(at - 3600), "to": iso(at)}})
    section = _market(ReplayEvidence(str(store.path), parse_at("2026-10-23T11:12")), "NBIS")
    assert [e["line"] for e in section["radar_events"]] == ["NBIS turned up from its session low"]
