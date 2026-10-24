#!/usr/bin/env python3
"""Offline: how long chart workspace responses stall the API's event loop.

The real /charts/workspace route with invented candles from a stubbed feed and an
in-memory database. No credentials, provider calls or trading data. A tiny async
route is probed every 10ms while workspace reads run back to back; its delay is the stall every
other request (streams, Dashboard) sees. Run with the backend virtualenv Python
from the repository root; the absolute numbers depend on this machine's CPU.
"""
import json
import os
import socket
import statistics
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"  # never a configured database
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
import uvicorn
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.chart_math import ET, chart_bars, indicators
from app.engine.symbol_info_tradier import SymbolEvents
from app.routers import charts

DAY = date(2026, 10, 23)
MINUTES = [{"time": int((datetime(2026, 10, 23, 4, tzinfo=ET) + timedelta(minutes=i)).timestamp()), "open": 100 + i % 7 * 0.13,
            "high": 100.4 + i % 5 * 0.11, "low": 99.6 - i % 3 * 0.09, "close": 100 + i % 11 * 0.07, "volume": 1000 + i * 37 % 9000}
           for i in range(960)]
for bar in MINUTES:
    bar["end_time"] = bar["time"] + 60
DAILY = indicators([{"time": int(datetime(2021, 1, 4, tzinfo=ET).timestamp()) + d * 86400, "end_time": int(datetime(2021, 1, 4, 16, tzinfo=ET).timestamp()) + d * 86400,
                     "open": 80 + d % 13, "high": 82 + d % 13, "low": 78 + d % 13, "close": 81 + d % 17 * 0.5, "volume": 2_000_000 + d * 911 % 900_000,
                     "source": "tradier", "extended": False, "vwap": None, "vwap_sd": None} for d in range(1200)])


def workspace(symbol, frames, *_, **__):
    panels = {f: {"bars": DAILY if f == "1D" else chart_bars(MINUTES, [], f, "extended", {DAY: None}), "markers": []} for f in frames}
    return {"symbol": symbol, "panels": panels, "fetched_at": {"intraday": 1}, "intraday_as_of": MINUTES[-1]["time"], "issues": [],
            "adjustment": None, "quotes": [{"symbol": symbol, "last": 100.0}], "checked_at": int(time.time())}


def build_app():
    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/bench.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(charts.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session

    @app.get("/ping")
    async def ping():
        return {}

    charts.chart_feed.workspace = workspace
    charts.symbol_info_tradier.symbol_events = SymbolEvents(root=Path(tempfile.mkdtemp()), spawn=lambda work: None)
    charts.symbol_info_tradier.tradier.TRADIER_API_KEY = ""
    return app


def percentile(values, share):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 2)


if __name__ == "__main__":
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    layouts = {"single": "symbol=MRVL&intervals=1m,5m,15m,1h,1D&session=extended",
               "multi": "symbol=MRVL&intervals=1m,5m,15m,1h,1D&session=extended&extras=SPY:5m.15m,QQQ:5m.1h"}
    readers = int(os.environ.get("BENCH_READERS", "1"))
    result = {"environment": "local uvicorn, one worker, invented candles; stall = /ping delay while %d client(s) read the workspace back to back" % readers,
              "layouts": {}}
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            for name, query in layouts.items():
                body = client.get(f"/charts/workspace?{query}")
                body.raise_for_status()
                reads = []
                for _ in range(15):
                    start = time.perf_counter()
                    client.get(f"/charts/workspace?{query}").raise_for_status()
                    reads.append((time.perf_counter() - start) * 1000)
                idle = []
                for _ in range(100):
                    start = time.perf_counter()
                    client.get("/ping")
                    idle.append((time.perf_counter() - start) * 1000)
                    time.sleep(0.01)
                stop = threading.Event()

                def load():
                    with httpx.Client(base_url=base, timeout=30) as reader:
                        while not stop.is_set():
                            reader.get(f"/charts/workspace?{query}")
                workers = [threading.Thread(target=load) for _ in range(readers)]
                for worker in workers:
                    worker.start()
                busy = []
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    start = time.perf_counter()
                    client.get("/ping")
                    busy.append((time.perf_counter() - start) * 1000)
                    time.sleep(0.01)
                stop.set()
                for worker in workers:
                    worker.join()
                result["layouts"][name] = {
                    "response_bytes": len(body.content),
                    "workspace_ms_median": round(statistics.median(reads), 2),
                    "ping_idle_ms_p50": percentile(idle, 0.5),
                    "ping_under_load_ms": {"p50": percentile(busy, 0.5), "p95": percentile(busy, 0.95), "max": round(max(busy), 2), "samples": len(busy)},
                }
        print(json.dumps(result, indent=2))
    finally:
        server.should_exit = True
