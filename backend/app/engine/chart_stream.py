"""One Tradier market WebSocket shared by private chart viewers.

Only validated trade prices cross the browser-facing event stream. REST candles
remain the authority for volume, studies, and recovery after a missed event.
"""

import asyncio
from datetime import datetime
import json
import logging
import math
import time

import httpx
from websockets.asyncio.client import connect

from app.engine import tradier
from app.engine.chart_math import ET, INTERVALS, session_part


_log = logging.getLogger(__name__)
_INTRADAY = {name: width for name, width in INTERVALS.items() if name not in ("1D", "1W")}


def trade_event(row: dict, *, now: float | None = None) -> dict | None:
    """Reject stale, invalid and correction events before they reach a chart."""
    if row.get("type") != "timesale" or str(row.get("cancel")).lower() == "true" or str(row.get("correction")).lower() == "true":
        return None
    try:
        symbol = str(row["symbol"])
        price = float(row["last"])
        at = float(row["date"]) / 1000
        size = float(row["size"])
        if not symbol or not math.isfinite(price) or price <= 0 or not math.isfinite(size) or size <= 0:
            return None
        if not math.isfinite(at) or abs((now if now is not None else time.time()) - at) > 120:
            return None
        dt = datetime.fromtimestamp(at, ET)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    part = session_part(dt)
    if part is None:
        return None
    minute = dt.hour * 60 + dt.minute
    buckets = {}
    for name, width in _INTRADAY.items():
        anchor = part[1] + ((minute - part[1]) // width) * width
        finish = min(anchor + width, part[2])
        buckets[name] = {
            "time": int(dt.replace(hour=anchor // 60, minute=anchor % 60, second=0, microsecond=0).timestamp()),
            "end_time": int(dt.replace(hour=finish // 60, minute=finish % 60, second=0, microsecond=0).timestamp()),
            "extended": part[0] != "regular",
        }
    return {"type": "tick", "symbol": symbol, "at": at, "price": price, "open": price, "high": price, "low": price,
            "minute": buckets["1m"]["time"], "session": part[0], "buckets": buckets}


class ChartMarketStream:
    """Demand-driven single connection, fan-out and bounded reconnects."""

    def __init__(self):
        self._clients: dict[int, tuple[str, asyncio.Queue]] = {}
        self._next_id = 0
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._pending: dict[tuple[str, int], dict] = {}
        self._latest_at: dict[str, float] = {}

    def subscribe(self, symbol: str) -> tuple[int, asyncio.Queue]:
        self._next_id += 1
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._clients[self._next_id] = (symbol, queue)
        queue.put_nowait({"type": "status", "state": "connecting"})
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run())
        return self._next_id, queue

    def unsubscribe(self, client_id: int) -> None:
        self._clients.pop(client_id, None)

    async def stop(self) -> None:
        self._stopping = True
        self._clients.clear()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def _publish(self, event: dict) -> None:
        for symbol, queue in self._clients.values():
            if event["type"] == "tick" and event["symbol"] != symbol:
                continue
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def _receive(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        wanted = {symbol for symbol, _ in self._clients.values()}
        for line in message.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("error"):
                raise ValueError("Tradier rejected the market-stream subscription")
            tick = trade_event(row)
            if tick is None or tick["symbol"] not in wanted:
                continue
            symbol = tick["symbol"]
            if tick["at"] < self._latest_at.get(symbol, 0):
                continue
            self._latest_at[symbol] = tick["at"]
            key = (symbol, tick["minute"])
            pending = self._pending.get(key)
            if pending is None:
                self._pending[key] = tick
            else:
                pending["high"] = max(pending["high"], tick["price"])
                pending["low"] = min(pending["low"], tick["price"])
                pending["at"] = tick["at"]
                pending["price"] = tick["price"]

    def _flush(self) -> None:
        pending = sorted(self._pending.values(), key=lambda tick: tick["at"])
        self._pending.clear()
        for event in pending:
            self._publish(event)

    async def _session(self) -> tuple[str, str]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{tradier.TRADIER_BASE_URL}/v1/markets/events/session",
                headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"},
            )
            response.raise_for_status()
            stream = response.json()["stream"]
            session_id = stream["sessionid"]
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Invalid Tradier market-stream session")
        # The live session response supplies an HTTPS URL for HTTP streaming.
        # WebSocket clients use Tradier's separate, fixed wss endpoint.
        return "wss://ws.tradier.com/v1/markets/events", session_id

    async def _run(self) -> None:
        delay = 1
        try:
            while self._clients and not self._stopping:
                try:
                    url, session_id = await self._session()
                    async with connect(url, compression=None, proxy=None, open_timeout=10, ping_interval=20) as socket:
                        subscribed: set[str] = set()
                        session_started = time.monotonic()
                        last_flush = session_started
                        delay = 1
                        while self._clients and not self._stopping:
                            wanted = {symbol for symbol, _ in self._clients.values()}
                            if wanted != subscribed:
                                if subscribed and time.monotonic() - session_started > 240:
                                    break  # Renew the short-lived session before changing symbols.
                                await socket.send(json.dumps({"symbols": sorted(wanted), "filter": ["timesale"],
                                                              "sessionid": session_id, "linebreak": True, "validOnly": True}))
                                subscribed = wanted
                                self._publish({"type": "status", "state": "connected"})
                            try:
                                message = await asyncio.wait_for(socket.recv(), timeout=1)
                            except asyncio.TimeoutError:
                                message = None
                            if message is not None:
                                self._receive(message)
                            if time.monotonic() - last_flush >= 1:
                                self._flush()
                                last_flush = time.monotonic()
                        self._flush()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Provider errors never contain a token or session ID in logs.
                    _log.warning("Tradier chart stream disconnected (%s)", type(exc).__name__)
                    self._pending.clear()
                    self._publish({"type": "status", "state": "fallback"})
                    if self._clients and not self._stopping:
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 30)
        finally:
            self._pending.clear()
            self._task = None
            # A new viewer may have subscribed just as the previous viewer left.
            if self._clients and not self._stopping:
                self._task = asyncio.create_task(self._run())
