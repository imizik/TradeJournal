"""The copilot's market regime and Radar-today tools, and quotes with a day change: live, replay, fixture, and the
scripted model. Live reads are the Radar store, the chart feed's index quotes, the macro calendar and the fundamentals
cache; replay cuts every recorded read at the frozen moment and marks the fetched ones unavailable."""
import json
from datetime import datetime

import pytest

from app.ai import copilot, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET
from app.engine.radar_comparison import iso
from app.engine.radar_store import RadarStore, load_universe
from tests.test_copilot import _text, _turn

SESSION = "2026-10-23"
BASE = datetime(2026, 10, 23, 11, 12, tzinfo=ET).timestamp()
PRICES = {"SPY": (671.10, 672.44), "QQQ": (598.40, 600.50), "IWM": (241.30, 242.80), "RSP": (188.75, 189.28),
          "XLK": (262.10, 263.36), "NBIS": (94.35, 97.22), "CRWV": (131.20, 131.73)}  # (last, prev_close)


def _store(path, *, with_future: bool) -> RadarStore:
    version = load_universe()["version"]
    store = RadarStore(path)
    moments = [(BASE - 900, 0.0), (BASE, 0.0)] + ([(BASE + 600, 50.0)] if with_future else [])
    for at, bump in moments:
        rows = [{"symbol": s, "last": last + bump, "prev_close": prev, "open": prev, "high": None, "low": None, "volume": 1000,
                 "bid": None, "ask": None, "trade_time_ms": int(at * 1000), "retrieved_at": iso(at)} for s, (last, prev) in PRICES.items()]
        store.append_pass({"session_date": SESSION, "started_at": iso(at), "finished_at": iso(at), "universe_version": version,
                           "status": "ok", "symbols_requested": 7, "symbols_returned": 7, "unmatched": [], "requests_used": 1,
                           "error": None, "skip_reason": None}, rows)
    for n, (at, summary) in enumerate(((BASE - 600, "NBIS turned up from its session low"),) + (((BASE + 300, "a later event"),) if with_future else ())):
        store.append_event({"event_id": f"rad_t_{n}", "session_date": SESSION, "rule_version": "t", "universe_version": version,
                            "kind": "dip_turn", "direction": "up", "symbols": ["NBIS"], "benchmark": "SPY", "group": "Neoclouds and AI hosting",
                            "first_seen_at": iso(at), "summary": summary, "measures": {"from_low_pct": 2.1}, "evidence": [],
                            "coverage": {"passes_expected": 1, "passes_recorded": 1, "symbols_missing": []},
                            "chart": {"symbol": "NBIS", "from": iso(at - 3600), "to": iso(at)}})
    return store


# --------------------------------------------------------------------------- the tools, validation and allowlists

def test_the_tools_are_registered_validated_and_job_safe():
    assert {"get_market_regime", "get_radar_today"} <= copilot_tools.TOOL_NAMES
    assert copilot_tools.PROVENANCE["get_market_regime"][1] == "fetched" and copilot_tools.PROVENANCE["get_radar_today"][1] == "recorded"
    assert copilot_tools.validate("get_market_regime", {}) == {} and copilot_tools.validate("get_market_regime", {"symbol": "nbis"}) == {"symbol": "NBIS"}
    assert copilot_tools.validate("get_radar_today", {}) == {"limit": 12}
    assert copilot_tools.validate("get_radar_today", {"group": " Chips ", "limit": 3}) == {"group": "Chips", "limit": 3}
    for name, bad in (("get_market_regime", {"symbol": "no ticker"}), ("get_radar_today", {"limit": 0}), ("get_radar_today", {"limit": 13}),
                      ("get_radar_today", {"limit": True}), ("get_radar_today", {"group": ""}), ("get_radar_today", {"group": "x" * 121}),
                      ("get_market_regime", {"limit": 1})):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate(name, bad)
    # Market data only, never the owner's book: both are offered to research jobs and the shadow book.
    assert {"get_market_regime", "get_radar_today"} <= set(research_job.JOB_TOOLS)
    assert "get_market_regime" not in copilot_tools.NOT_CURRENT_TOOLS and "get_radar_today" not in copilot_tools.BOOK_CONTEXT_TOOLS


# --------------------------------------------------------------------------- live

def test_live_regime_reads_radar_indices_vix_macro_and_cached_earnings(tmp_path, monkeypatch):
    from app.engine import chart_feed as feed_module, symbol_info_tradier
    from app.routers import radar
    store = _store(tmp_path / "radar.sqlite", with_future=False)
    monkeypatch.setattr(radar, "_store", lambda read_only=False: (RadarStore(store.path, read_only=True), None))
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", lambda symbols: ([
        {"symbol": "VIX", "last": 18.4, "change_percentage": 4.2, "trade_time": BASE},
        {"symbol": "US10Y", "last": 4.123, "change_bps": 3.0, "trade_time": BASE}], BASE, None))
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "chart_earnings", lambda wanted, watchlist, today: {
        wanted[0]: {"state": "ready", "fetched_at": BASE, "message": None, "next": {"date": "2026-11-12", "status": "estimated", "label": "Q3"}, "reports": []}})
    out = copilot_tools.LiveEvidence().get_market_regime("NBIS")
    assert out["session"] == SESSION and out["prior_session"] is True  # the newest recorded session stands in for a quiet day
    radar_block = out["radar"]
    assert radar_block["state"] == "ok" and radar_block["pass_at"] == iso(BASE) and radar_block["earlier_pass_at"] == iso(BASE - 900)
    assert radar_block["indices"]["SPY"]["day_pct"] == round((671.10 / 672.44 - 1) * 100, 3) and radar_block["indices"]["SPY"]["last_15m_pct"] == 0.0
    assert set(radar_block["indices"]) == {"SPY", "QQQ", "IWM", "RSP"}
    sector = radar_block["sector"]
    assert sector["etf"] == "XLK" and sector["symbol_day_pct"] == round((94.35 / 97.22 - 1) * 100, 3)
    assert sector["symbol_vs_sector_pct"] == round(sector["symbol_day_pct"] - sector["day_pct"], 3)
    assert out["vix"] == {"state": "ok", "last": 18.4, "change_pct": 4.2, "as_of": iso(BASE)[:19] + "Z"}
    assert out["us10y"]["yield_pct"] == 4.123 and out["us10y"]["change_bps"] == 3.0
    assert out["macro"]["state"] == "ok" and out["macro"]["calendar"] == "FOMC, CPI and jobs reports only"
    assert out["earnings"]["next"]["date"] == "2026-11-12" and out["earnings"]["state"] == "ready"
    assert len(copilot_tools.bounded(out)) < copilot_tools.MAX_RESULT_CHARS
    # Without a symbol: no sector, no earnings. An untracked symbol says so instead of guessing a sector.
    bare = copilot_tools.LiveEvidence().get_market_regime()
    assert "sector" not in bare["radar"] and bare["earnings"] is None
    assert copilot_tools.LiveEvidence().get_market_regime("ZZZZ")["radar"]["sector"]["state"] == "untracked"


def test_live_regime_degrades_block_by_block(tmp_path, monkeypatch):
    from app.engine import chart_feed as feed_module, symbol_info_tradier
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", lambda symbols: (_ for _ in ()).throw(ChartFeedError("Chart requests are cooling down.", "rate_limited")))
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "chart_earnings", lambda wanted, watchlist, today: {
        wanted[0]: {"state": "loading", "fetched_at": None, "message": None, "next": None, "reports": []}})
    out = copilot_tools.LiveEvidence().get_market_regime("NBIS")
    assert out["radar"] == {"state": "off", "reason": "Radar recording is not switched on."}
    assert out["vix"]["state"] == "unavailable" and "cooling down" in out["vix"]["reason"] and out["us10y"]["state"] == "unavailable"
    assert out["earnings"]["state"] == "loading" and "get_symbol_events" in out["earnings"]["reason"]
    assert out["macro"]["state"] == "ok"  # the calendar is a file
    assert "no backdrop" in copilot._summary("get_market_regime", out) or "Radar off" in copilot._summary("get_market_regime", out)


def test_live_radar_today_reads_the_session_or_the_last_recorded_one(tmp_path, monkeypatch):
    from app.routers import radar
    store = _store(tmp_path / "radar.sqlite", with_future=True)
    original = radar._store
    monkeypatch.setattr(radar, "_store", lambda read_only=False: (RadarStore(store.path, read_only=True), None))
    out = copilot_tools.LiveEvidence().get_radar_today(limit=1)
    assert out["state"] == "ok" and out["session"] == SESSION and out["prior_session"] is True  # today is not 2026-10-23
    assert out["events_total"] == 2 and [e["summary"] for e in out["events"]] == ["a later event"]  # newest first, capped
    assert out["movers"]["pass_at"] == iso(BASE + 600) and out["movers"]["spy_day_pct"] == round((721.10 / 672.44 - 1) * 100, 3)
    assert copilot._summary("get_radar_today", out).startswith("2 events (1 shown) · SPY +")
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setattr(radar, "_store", original)
    off = copilot_tools.LiveEvidence().get_radar_today()
    assert off["state"] == "off" and off["events"] == [] and copilot._summary("get_radar_today", off) == "off: Radar recording is not switched on."


def test_live_quotes_carry_change_and_volume_and_fall_back_to_the_quote_engine(monkeypatch):
    from app.engine import chart_feed as feed_module, quotes
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", lambda symbols: ([
        {"symbol": "NBIS", "last": 94.35, "change_percentage": -2.951, "volume": 3_100_000.0, "previous_close": 97.22,
         "day_high": 97.1, "day_low": 92.4, "trade_time": BASE}], BASE - 5, None))
    out = copilot_tools.LiveEvidence().get_quotes(["NBIS", "TSLA"])
    assert out["prices"] == {"NBIS": 94.35, "TSLA": None} and out["not_found"] == ["TSLA"] and out["fetched_at"] == iso(BASE - 5)[:19] + "Z"
    assert out["quotes"]["NBIS"] == {"last": 94.35, "change_pct": -2.95, "volume": 3_100_000.0, "prev_close": 97.22, "day_high": 97.1,
                                     "day_low": 92.4, "trade_time": iso(BASE)[:19] + "Z"}
    assert copilot._summary("get_quotes", out) == "NBIS 94.35 (-2.95%), TSLA None"
    monkeypatch.setattr(feed_module.chart_feed, "quote_rows", lambda symbols: (_ for _ in ()).throw(ChartFeedError("not configured", "not_configured")))
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda tickers: {t: 1.5 for t in tickers})
    back = copilot_tools.LiveEvidence().get_quotes(["NBIS"])
    assert back["prices"] == {"NBIS": 1.5} and back["quotes"] == {} and "price only" in back["source_note"]
    # A watch proposal still finds its price either way.
    assert copilot_tools.propose(copilot_tools.LiveEvidence(), {"kind": "watch", "symbol": "NBIS", "condition": "touches", "price": 90.0,
                                                                  "label": "l", "why": "w"})["proposal"]["last"] == 1.5


# --------------------------------------------------------------------------- replay

def test_replay_cuts_radar_at_the_moment_and_has_no_vix(tmp_path, monkeypatch):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine import symbol_info_tradier
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", lambda symbol, today: {
        "symbol": symbol, "today": today.isoformat(), "earnings": {"state": "ready", "next": {"date": "2026-11-12", "status": "estimated", "label": "Q3"},
                                                                  "reports": [], "fetched_at": BASE}})
    at = parse_at("2026-10-23T11:12")
    full = ReplayEvidence(str(_store(tmp_path / "full.sqlite", with_future=True).path), at)
    cut = ReplayEvidence(str(_store(tmp_path / "cut.sqlite", with_future=False).path), at)
    for name, args in (("get_market_regime", ("NBIS",)), ("get_market_regime", ()), ("get_radar_today", ()), ("get_radar_today", ("NBIS", 1)),
                       ("get_quotes", (["NBIS", "SPY", "TSLA"],))):
        assert json.dumps(getattr(full, name)(*args), sort_keys=True) == json.dumps(getattr(cut, name)(*args), sort_keys=True), name
    regime = full.get_market_regime("NBIS")
    assert regime["as_of"] == "2026-10-23T11:12-04:00" and regime["radar"]["pass_at"] == iso(BASE) and "721" not in json.dumps(regime)
    assert regime["vix"]["state"] == "unavailable" and "snapshot" in regime["vix"]["reason"] and regime["us10y"]["state"] == "unavailable"
    assert regime["earnings"]["next"]["date"] == "2026-11-12" and regime["macro"]["state"] == "ok"
    today = full.get_radar_today()
    assert today["as_of"] == "2026-10-23T11:12-04:00" and [e["summary"] for e in today["events"]] == ["NBIS turned up from its session low"]
    assert today["movers"]["pass_at"] == iso(BASE) and "later" not in json.dumps(today)
    quotes = full.get_quotes(["NBIS", "TSLA"])
    assert quotes["quotes"]["NBIS"]["change_pct"] == round((94.35 / 97.22 - 1) * 100, 2) and quotes["prices"]["TSLA"] is None


# --------------------------------------------------------------------------- fixture and the scripted model

def test_fixture_serves_the_nbis_scenario_and_fits():
    fixture = FixtureEvidence()
    regime = fixture.get_market_regime("NBIS")
    assert regime["radar"]["indices"]["SPY"]["day_pct"] == -0.20 and regime["radar"]["sector"]["etf"] == "XLK"
    assert regime["radar"]["sector"]["symbol_vs_sector_pct"] == round(-2.95 + 0.48, 3) and regime["vix"]["last"] == 18.4
    assert regime["earnings"]["next"]["date"] == "2026-11-12" and regime["macro"]["state"] == "ok"
    assert fixture.get_market_regime("TSLA")["radar"]["sector"]["symbol_day_pct"] is None  # tracked, but not in the scenario's session table
    today = fixture.get_radar_today()
    assert today["events_total"] == 3 and today["events"][0]["kind"] == "group_move" and today["movers"]["laggards"][0]["symbol"] == "NBIS"
    assert [e["event_id"] for e in fixture.get_radar_today(group="CRWV")["events"]] == ["rad_sim_neocloud_1", "rad_sim_crwv_1"]
    assert len(fixture.get_radar_today(limit=1)["events"]) == 1
    for data in (regime, today, fixture.get_quotes(["NBIS", "SPY", "ZZZ"])):
        assert len(copilot_tools.bounded(data)) < copilot_tools.MAX_RESULT_CHARS
    assert fixture.get_quotes(["NBIS", "ZZZ"])["quotes"]["NBIS"]["change_pct"] == -2.95


def test_the_scripted_model_reads_radar_today_and_the_regime():
    events = _turn([{"role": "user", "content": "What did Radar see today?"}], copilot.FakeAdapter(0))
    [tool] = [e for e in events if e["type"] == "tool" and e["name"] == "get_radar_today" and e["status"] == "ok"]
    assert tool["provenance"]["kind"] == "simulated" and tool["summary"] == "3 events (3 shown) · SPY -0.20%"
    text = _text(events)
    assert text.startswith("Verdict: Focus — 3 Radar events this session") and "14:58Z Neoclouds and AI hosting: 5 of 7 members up" in text
    assert "Latest: faded." in text and 'Headline before it: "CoreWeave extends gains on reported capacity deal".' in text
    assert "SPY -0.20% on the day; leaders APLD +1.05% vs SPY" in text

    events = _turn([{"role": "user", "content": "Why is NBIS moving, is it the stock or the market?"}], copilot.FakeAdapter(0))
    names = [e["name"] for e in events if e["type"] == "tool"]
    assert "get_market_regime" in names and "get_group_comparison" in names
    [regime] = [e for e in events if e["type"] == "tool" and e["name"] == "get_market_regime" and e["status"] == "ok"]
    assert regime["input"] == {"symbol": "NBIS"} and regime["summary"] == "SPY -0.20% · QQQ -0.35% · IWM -0.62% · RSP -0.28% · XLK -0.48% · VIX 18.4"
    assert "Backdrop (Radar pass 2026-10-23T15:12:00Z): SPY -0.20%, QQQ -0.35%, IWM -0.62%, RSP -0.28%, XLK -0.48% (NBIS -2.47 points against it), VIX 18.4 (+4.2%)." in _text(events)
    # A plain group question does not pay for the regime read.
    plain = _turn([{"role": "user", "content": "NBIS is bouncing. Is the group confirming?"}], copilot.FakeAdapter(0))
    assert "get_market_regime" not in [e["name"] for e in plain if e["type"] == "tool"]


def test_the_prompt_tells_the_model_when_to_read_them():
    assert "read get_market_regime" in copilot.SYSTEM_PROMPT and "the stock, its group, its sector or the whole market" in copilot.SYSTEM_PROMPT
    assert "get_radar_today lists the session's recorded events" in copilot.SYSTEM_PROMPT
    descriptions = {t["name"]: t["description"] for t in copilot_tools.TOOLS}
    assert "day change %" in descriptions["get_quotes"] and "Price only" not in descriptions["get_quotes"]
