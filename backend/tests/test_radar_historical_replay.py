"""Causal minute alignment, frozen replay parity, and independent closing labels."""
from collections import defaultdict
from datetime import date
from unittest.mock import Mock

from app.engine import radar_rules
from scripts import radar_historical_replay as history
from scripts.radar_replay import replay_session


def test_fixed_sessions_and_previous_close_split_basis():
    dates = history.dates()
    assert len(dates) == 91
    assert dates[:2] == [date(2026, 6, 12), date(2026, 6, 15)]
    assert dates[-1] == date(2026, 10, 21)
    assert date(2026, 6, 19) not in dates and date(2026, 9, 7) not in dates
    prior, day = dates[:2]
    # A later split scales the whole adjusted series by another factor of two.
    daily = {"split": {"A": {prior: {"c": 25}, day: {"o": 26}}},
             "raw": {"A": {prior: {"c": 100}, day: {"o": 52, "c": 55}}}}
    assert history.daily_inputs(daily, prior, day) == ({"A": 50}, {"A": 55})
    assert history.daily_inputs(daily, date(2026, 6, 11), day) == ({}, {})


def test_completed_bars_replay_timing_gaps_and_first_sightings():
    day = date(2026, 6, 15)
    stocks = ["GAP", "DROP"] + [f"S{i:02d}" for i in range(20)]
    names = ["SPY", *stocks]
    universe = {"version": "fixture", "groups": [],
                "symbols": [dict(symbol=s, kind="etf" if s == "SPY" else "stock", benchmark=s == "SPY")
                            for s in names]}
    previous = {s: 100 for s in names}
    bars = {s: {str(i): [100, 100] for i in range(100)} for s in names}
    bars["GAP"] = {str(i): [110, 110] for i in range(100)}
    for i in range(35, 100):
        bars["DROP"][str(i)] = [94, 94]
    del bars["DROP"]["36"]  # breaks three-pass persistence; never fill from another minute
    bars["DROP"]["69"] = [93, 93]
    del bars["SPY"]["99"]
    p, q = history.reconstruct(day, universe, bars, previous)
    assert p[0]["finished_at"].endswith("09:31:00-04:00") and p[-1]["id"] == 100
    assert "DROP" not in q[37] and p[36]["status"] == "partial"
    assert not q[101]
    radar, movers = history.flags(universe, p, q)
    assert radar == [history.Flag(40, "relative_to_spy", "down", ("DROP",))]
    store = Mock()
    store.passes.return_value = p
    store.quotes.return_value = [quote for rows in q.values() for quote in rows.values()]
    [(recorded, _)] = replay_session(store, universe, day.isoformat(), radar_rules.V0)
    assert recorded["first_seen_at"] == p[39]["finished_at"]
    assert (recorded["kind"], recorded["symbols"]) == (radar[0].rule, list(radar[0].symbols))
    assert history.Flag(1, "leaders", "up", ("GAP",)) in movers

    prices = {m: {s: quote["last"] for s, quote in rows.items()} for m, rows in q.items()}
    assert history.forward(radar[0], prices) == [-1.0638, None, None]
    # A group with a missing member endpoint must not change its basket ex post.
    group = history.Flag(7, "group_move", "down", ("DROP", "GAP"), "Example")
    assert history.forward(group, prices)[0] is None

    closing = {**previous, "GAP": 110, "DROP": 93}
    totals = defaultdict(list)
    report = history.analyze(day, universe, bars, previous, closing, totals)
    assert "| 1 | GAP | +10.00 | miss | 09:31 |" in report
    assert any(line.startswith("| 2 | DROP | -7.00 | 10:10 |") for line in report)
    assert totals["Radar lead"] == [350]


def test_fetch_merges_sip_cache_with_paginated_regular_session_reads(tmp_path, monkeypatch):
    import gzip
    import json
    import httpx

    prior, day = history.dates()[:2]
    monkeypatch.setattr(history, "dates", lambda: [prior, day])
    for key, value in (("ALPACA_DATA_FEED", "sip"), ("ALPACA_API_KEY", "fixture"), ("ALPACA_API_SECRET", "fixture")):
        monkeypatch.setenv(key, value)
    cache = tmp_path / "cache"
    path = cache / "stocks/1Min/sip/SPY" / f"{day}.json"
    path.parent.mkdir(parents=True)
    def bar(minute, value):
        return {"t": f"{day}T{minute}:00Z", "o": value, "c": value}
    path.write_text(json.dumps([bar("13:29", 1), bar("13:30", 100), bar("19:59", 101), bar("20:00", 2)]))
    calls = []

    def handle(req):
        query = req.url.params
        assert req.method == "GET" and req.url.host == "data.alpaca.markets" and query["feed"] == "sip"
        calls.append(query["timeframe"])
        if query["timeframe"] == "1Day":
            return httpx.Response(200, json={"bars": {}})
        assert query["symbols"] == "AAA" and query["adjustment"] == "raw"
        if "page_token" not in query:
            return httpx.Response(200, json={"bars": {"AAA": [bar("13:30", 10)]}, "next_page_token": "next"})
        return httpx.Response(200, json={"bars": {"AAA": [bar("13:31", 11)]}, "next_page_token": None})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "Client", lambda **kw: client)
    root = tmp_path / "snapshot"
    history.fetch(root, cache, {"symbols": [{"symbol": s} for s in ("SPY", "AAA")]})
    assert calls == ["1Day", "1Day", "1Min", "1Min"]
    with gzip.open(root / f"{day}.json.gz") as data:
        assert json.load(data) == {"SPY": {"0": [100, 100], "389": [101, 101]},
                                   "AAA": {"0": [10, 10], "1": [11, 11]}}
