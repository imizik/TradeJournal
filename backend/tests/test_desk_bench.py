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
import os
import time

import pytest

from app.engine import request_timing
from tests.desk_latency import OPTIONS, latency, slow_desk  # noqa: F401  (fixture)
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
