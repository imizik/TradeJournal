"""The desk's server time with realistic provider latency (docs/copilot-lab.md § Where the wait goes).

Skipped unless ``DESK_BENCH=1``: it sleeps on purpose. Every Tradier HTTP call (quotes, option quotes, minute bars),
every news read and every Robinhood MCP post takes ``DESK_BENCH_LATENCY`` seconds (0.35 by default), through the real
caches above them. Prints, per desk read: cold (first request after a start), warm (straight after), and at the minute
boundary (the provider caches expired and the Robinhood snapshot due), plus the whole first paint fired at once the way
the page does. Run:

    DESK_BENCH=1 env -u ANTHROPIC_BASE_URL .venv/bin/python -m pytest tests/test_desk_bench.py -s -q
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
import os
import time

import pytest

from app.engine import request_timing
from tests.desk_latency import BOOK, OPTIONS, latency, seed_radar, slow_desk  # noqa: F401  (fixture)
from tests.test_copilot_plans import engine  # noqa: F401  (fixture)
from tests.test_today import clock  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(os.environ.get("DESK_BENCH") != "1", reason="the latency bench sleeps; DESK_BENCH=1 runs it")

LATENCY = float(os.environ.get("DESK_BENCH_LATENCY", "0.35"))
SPARKS = ",".join(OPTIONS)
FIRST_PAINT = ["/copilot/desk/threads", "/copilot/desk/session", "/copilot/desk/feed", f"/copilot/desk/sparks?symbols={SPARKS}",
               "/copilot/desk/scorecard", "/copilot/desk/day-report", "/copilot/desk/pings?day_only=true"]
OPEN_POSITION = ["/charts/journal/positions/NBIS/context"]


def _time(client, path) -> tuple[float, str]:
    start = time.perf_counter()
    response = client.get(path)
    wall = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, (path, response.text)
    timing = response.headers.get("server-timing", "")
    parts = sorted(((p.split(";dur=")[0], float(p.split(";dur=")[1])) for p in timing.split(", ") if ";dur=" in p and not p.startswith("total")),
                   key=lambda kv: -kv[1])[:3]
    return wall, ", ".join(f"{n} {ms:.0f}" for n, ms in parts)


def _paint(client, paths) -> float:
    start = time.perf_counter()
    with ThreadPoolExecutor(len(paths)) as pool:
        for response in pool.map(client.get, paths):
            assert response.status_code == 200, response.text
    return (time.perf_counter() - start) * 1000


def test_desk_latency_table(slow_desk, monkeypatch):  # noqa: F811
    bench = slow_desk
    monkeypatch.setattr(latency, "seconds", LATENCY)
    client = bench.client
    rows = []
    # Cold: the first request of each read after a start, empty caches, no Robinhood snapshot yet.
    cold_paint = _paint(client, FIRST_PAINT)
    first = {route: (body["recent"][0]["ms"], list(body["recent"][0]["sections"].items())[:0] or sorted(
        body["recent"][0]["sections"].items(), key=lambda kv: -kv[1])[:3]) for route, body in request_timing.summary()["routes"].items()}
    bench.expire()
    request_timing.reset()
    for path in FIRST_PAINT + OPEN_POSITION:
        bench.expire()
        cold, cold_top = _time(client, path)
        warm, _ = _time(client, path)
        bench.expire()
        boundary, boundary_top = _time(client, path)
        rows.append((path.split("?")[0].replace("/copilot/desk/", "desk/").replace("/charts/journal/positions/", "positions/"),
                     cold, warm, boundary, cold_top))
    time.sleep(LATENCY * 20)  # let a background Robinhood refresh finish before the warm paint
    warm_paint = _paint(client, FIRST_PAINT)
    bench.expire()
    boundary_paint = _paint(client, FIRST_PAINT)
    print(f"\n\nLatency per outside call: {LATENCY * 1000:.0f} ms\n")
    print("| Read | Cold ms | Warm ms | Minute boundary ms | Slowest sections, cold (ms) |")
    print("|---|---:|---:|---:|---|")
    for name, cold, warm, boundary, top in rows:
        print(f"| {name} | {cold:.0f} | {warm:.0f} | {boundary:.0f} | {top} |")
    print(f"| **first paint, all reads at once** | {cold_paint:.0f} | {warm_paint:.0f} | {boundary_paint:.0f} | |")
    print("\nThe first paint after a start, each read (ms, slowest sections):")
    for route, (ms, top) in sorted(first.items(), key=lambda kv: -kv[1][0]):
        print(f"- {route}: {ms:.0f} ({', '.join(f'{n} {v:.0f}' for n, v in top)})")
    print(f"\nOutside calls made: {len(bench.providers.calls)} "
          f"({', '.join(f'{k} {bench.providers.calls.count(k)}' for k in sorted(set(bench.providers.calls)))})\n")


def _sparks_row(bench, client, path) -> tuple[float, str]:
    """One sparks request: its wall time and the outside calls it made, by path."""
    before = len(bench.providers.spans)
    wall, _top = _time(client, path)
    made = [p for _kind, p, *_ in bench.providers.spans[before:]]
    return wall, ", ".join(f"{n} {made.count(n)}" for n in sorted(set(made))) or "none"


def test_sparks_eleven_symbols(slow_desk, monkeypatch, tmp_path):  # noqa: F811
    """The book's sparklines for its eleven symbols: cold, warm and at the minute boundary, with the outside calls each
    made, once with no Radar recording (pre-market, a symbol outside its universe) and once with the recorder live."""
    bench = slow_desk
    monkeypatch.setattr(latency, "seconds", LATENCY)
    path = f"/copilot/desk/sparks?symbols={','.join(BOOK)}"
    print(f"\n\nLatency per outside call: {LATENCY * 1000:.0f} ms, {len(BOOK)} symbols\n")
    print("| Radar | Read | ms | Outside calls |")
    print("|---|---|---:|---|")
    from app.engine import alpaca
    from app.engine.chart_math import ET
    from datetime import datetime

    def batched(path_, params):  # Alpaca's multi-symbol minutes: one slow call for every symbol asked
        bench.providers.calls.append("alpaca")
        start = time.perf_counter()
        time.sleep(LATENCY)
        bench.providers._span("alpaca", path_, start)
        opened = datetime.fromtimestamp(bench.clock["t"], ET).replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
        stamp = lambda i: datetime.fromtimestamp(opened + 60 * i, ET).astimezone(UTC).isoformat().replace("+00:00", "Z")  # noqa: E731
        return {"bars": {s: [{"t": stamp(i), "c": 50.0 + i / 10} for i in range(200)] for s in params["symbols"].split(",")}}
    for label_, radar_on, sip in (("none", False, False), ("none, batched read", False, True), ("recorder live", True, False)):
        if radar_on:
            seed_radar(tmp_path / "radar.sqlite", bench.clock["t"], (*BOOK, "SPY"), monkeypatch=monkeypatch)
        monkeypatch.setattr(alpaca, "alpaca_configured", lambda sip=sip: sip)
        monkeypatch.setattr(alpaca, "_alpaca_get_fast", batched)
        for label in ("cold", "warm", "minute boundary"):
            if label != "warm":
                bench.expire()
            wall, calls = _sparks_row(bench, bench.client, path)
            print(f"| {label_} | {label} | {wall:.0f} | {calls} |")
    # The first paint with the book's sparklines among its other reads, cold: each read's own wait, so what the sparks
    # hold up shows (the page does not wait for them to draw the book).
    paths = FIRST_PAINT[:3] + [path]

    def timed_get(one):
        start = time.perf_counter()
        assert bench.client.get(one).status_code == 200
        return (time.perf_counter() - start) * 1000
    print("\n| First paint, cold | threads ms | session ms | feed ms | sparks ms |\n|---|---:|---:|---:|---:|")
    for label_, radar_on in (("recorder live", True), ("no recorder, no batched read", False)):
        monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
        if radar_on:
            monkeypatch.setenv("RADAR_ENABLED", "true")
        else:
            monkeypatch.delenv("RADAR_ENABLED", raising=False)
        bench.expire()
        with ThreadPoolExecutor(len(paths)) as pool:
            took = list(pool.map(timed_get, paths))
        print(f"| {label_} | " + " | ".join(f"{ms:.0f}" for ms in took) + " |")
    print()


WATCH = ("NVDA", "RKLB", "AMD", "PLTR", "SOFI", "HOOD", "TSLA", "MSFT", "AAPL", "META", "SMCI", "IONQ", "MU", "AVGO", "ORCL", "ASTS")


def test_first_paint_with_a_16_name_watchlist(slow_desk, monkeypatch, tmp_path):  # noqa: F811
    """The desk's first paint before the Watching list (the seven reads) and with a 16-name watchlist (the Watching read
    added, its names riding the sparks read): cold, warm and at the minute boundary, with the outside calls each paint
    made, once with no Radar recording or batched read (every watched line skipped) and once with the recorder live."""
    bench = slow_desk
    monkeypatch.setattr(latency, "seconds", LATENCY)
    from sqlmodel import Session
    import json as _json
    from app.engine import alpaca
    from app.models import ChartSettingsRecord
    with Session(bench.engine) as db:
        db.add(ChartSettingsRecord(name="default", data_json=_json.dumps({"watchlist": list(WATCH)}), revision=1))
        db.commit()
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    before = FIRST_PAINT
    after = [p if not p.startswith("/copilot/desk/sparks") else f"{p}&watch={','.join(WATCH)}" for p in FIRST_PAINT] + ["/copilot/desk/watching"]
    print(f"\n\nLatency per outside call: {LATENCY * 1000:.0f} ms; {len(WATCH)} watched names\n")
    print("| Radar | Paint | Cold ms | Warm ms | Minute boundary ms | Outside calls (cold) |")
    print("|---|---|---:|---:|---:|---|")
    for label_, radar_on in (("none, no batched read", False), ("recorder live", True)):
        if radar_on:
            seed_radar(tmp_path / "radar.sqlite", bench.clock["t"], tuple(dict.fromkeys((*BOOK, *WATCH, "SPY"))), monkeypatch=monkeypatch)
        for name, paths in (("before (7 reads)", before), ("with Watching (8 reads, 16 names)", after)):
            bench.expire()
            made = len(bench.providers.calls)
            cold = _paint(bench.client, paths)
            calls = bench.providers.calls[made:]
            warm = _paint(bench.client, paths)
            bench.expire()
            boundary = _paint(bench.client, paths)
            print(f"| {label_} | {name} | {cold:.0f} | {warm:.0f} | {boundary:.0f} | "
                  f"{len(calls)} ({', '.join(f'{k} {calls.count(k)}' for k in sorted(set(calls)))}) |")
    print()
