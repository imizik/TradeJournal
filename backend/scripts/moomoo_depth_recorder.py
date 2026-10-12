"""Opt-in moomoo depth recorder for a short watchlist (python -m scripts.moomoo_depth_recorder).

During 04:00-20:00 New York on weekdays it holds one provider connection,
subscribes each watched ticker's order book and trades, refreshes its auth in
place and writes, per ticker per day, one gzip JSON-lines file under the state
directory:

- a book line every 2 seconds for each book kind (ARCA-labelled or other
  market-maker IDs) that updated in that window, from the latest update only.
  Books are never merged, a missing side stays empty and nothing is carried
  forward; a window without an update writes nothing.
- a trade line for every trade print, with its provider direction and type.

It never loads the journal, its database or R2 credentials; the separate
uploader (scripts.depth_upload) moves finished days off the VPS. A failed
connection reconnects with a growing back-off; provider text is never logged.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, time as day_time, timedelta, timezone
import gzip
import json
import logging
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import time
from zoneinfo import ZoneInfo

from websockets.exceptions import WebSocketException

from scripts import moomoo_diagnostic as diagnostic
from scripts import moomoo_lab_server as lab

NEW_YORK = ZoneInfo("America/New_York")
# Premarket through after-hours. Holidays are not known here (no journal or
# calendar access); a holiday session simply receives nothing.
OPEN, CLOSE = day_time(4, 0), day_time(20, 0)
SNAPSHOT_SECONDS = 2.0
FLUSH_SECONDS = 5.0
REFRESH_SECONDS = 240
MAX_TICKERS = 20
DEFAULT_TICKERS = "SPY,MU,NBIS,SNDK,NVDA"
# Stop writing (and say so) rather than fill the disk the journal also needs.
MIN_FREE_BYTES = 2 * 1024 ** 3
# Without the uploader, local days are kept this long and then deleted.
LOCAL_DAYS = 14
BACKOFF = (15, 300)
STATE = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/tradejournal-depth"))
LOG = logging.getLogger("depth-recorder")
DIRECTIONS = {"BUY", "SELL", "NEUTRAL"}


def watchlist(raw: str | None) -> list[str]:
    tickers = []
    for item in (raw or DEFAULT_TICKERS).split(","):
        ticker = item.strip()
        if not diagnostic.STREAM_SYMBOL.fullmatch("US." + ticker):
            raise ValueError("Each watchlist entry must be a plain US stock or ETF ticker.")
        if ticker not in tickers:
            tickers.append(ticker)
    if not 1 <= len(tickers) <= MAX_TICKERS:
        raise ValueError(f"The watchlist holds 1..{MAX_TICKERS} tickers.")
    return tickers


def window(now: datetime) -> tuple[datetime, datetime] | None:
    """The recording window containing `now` (UTC-aware), or None outside it."""
    local = now.astimezone(NEW_YORK)
    if local.weekday() >= 5 or not OPEN <= local.time() < CLOSE:
        return None
    return (datetime.combine(local.date(), OPEN, NEW_YORK), datetime.combine(local.date(), CLOSE, NEW_YORK))


def next_open(now: datetime) -> datetime:
    local = now.astimezone(NEW_YORK)
    day = local.date() + timedelta(days=0 if local.time() < OPEN else 1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, OPEN, NEW_YORK)


def book_line(message: dict, received_ms: int, offset_ms: float | None, symbol: str) -> dict | None:
    """A compact copy of the allowlisted display book, or None if it is not this ticker's."""
    try:
        event = diagnostic.display_book(message, received_ms, offset_ms, symbol)
    except diagnostic.DiagnosticError:
        return None
    level = lambda entry: [entry["price"], entry["volume"], entry["order_count"], entry["mpid"]]
    return {"t": "b", "rx": received_ms, "k": lab.book_kind(event), "books": [
        {"ex": book["exchange"], "ts": book["source_time_ms"], "age": book["estimated_age_ms"],
         "b": [level(entry) for entry in book["bids"]], "a": [level(entry) for entry in book["asks"]]}
        for book in event["books"]]}


def trade_lines(message: dict, received_ms: int, symbol: str) -> list[dict]:
    data = message.get("data")
    if message.get("symbol") != symbol or message.get("type") != "TICKER" or not isinstance(data, dict):
        return []
    ticks = data.get("ticker_list")
    if not isinstance(ticks, list):
        return []
    lines = []
    for tick in ticks[:500]:
        if not isinstance(tick, dict):
            continue
        price, volume = diagnostic.number(tick.get("price")), diagnostic.number(tick.get("volume"))
        if price is None or price <= 0 or volume is None or volume < 0:
            continue
        kind = tick.get("type")
        lines.append({"t": "x", "ts": diagnostic.timestamp(tick.get("time_ms")), "rx": received_ms, "p": price, "v": volume,
                      "d": tick.get("direction") if tick.get("direction") in DIRECTIONS else None,
                      "q": diagnostic.number(tick.get("sequence")),
                      "y": kind if isinstance(kind, str) and re.fullmatch(r"[A-Z_]{1,24}", kind) else None})
    return lines


class Store:
    """Day files under the state directory; each flush appends one gzip member."""

    def __init__(self, root: Path):
        self.root = root
        self.pending: dict[tuple[str, str], list[dict]] = {}

    def add(self, day: str, ticker: str, line: dict) -> None:
        self.pending.setdefault((day, ticker), []).append(line)

    def flush(self) -> bool:
        """Write pending lines; False (and nothing written) when free disk is low."""
        if not self.pending:
            return True
        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < MIN_FREE_BYTES:
            self.pending.clear()
            return False
        for (day, ticker), lines in self.pending.items():
            folder = self.root / day
            folder.mkdir(exist_ok=True)
            with gzip.open(folder / f"{ticker}.jsonl.gz", "ab") as file:
                file.write("".join(json.dumps(line, separators=(",", ":"), allow_nan=False) + "\n" for line in lines).encode())
        self.pending.clear()
        return True

    def prune(self, today: date) -> None:
        """Without an uploader, keep LOCAL_DAYS of local days; uploaded days are the uploader's to remove."""
        for folder in sorted(self.root.glob("????-??-??")):
            with suppress(ValueError):
                if (today - date.fromisoformat(folder.name)).days > LOCAL_DAYS:
                    shutil.rmtree(folder)


def write_status(root: Path, status: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ".status.json.tmp"
    temporary.write_text(json.dumps(status, separators=(",", ":")))
    temporary.replace(root / "status.json")


def correlated(message: dict, request_id: str) -> dict | None:
    if message.get("id") == request_id:
        return message
    nested = message.get("data")
    if diagnostic.number(message.get("ret_code")) == 0 and isinstance(nested, dict) and nested.get("id") == request_id:
        return nested
    return None


async def record_window(appkey, key, tickers: list[str], until: datetime, store: Store, status: dict,
                        connector=diagnostic.NoRedirectConnect, clock=time.time) -> None:
    """One connection until `until`; raises on any protocol, auth, refresh or socket failure."""
    symbols = ["US." + ticker for ticker in tickers]
    offset = None
    latest: dict[tuple[str, str], dict] = {}
    socket = None
    subscribed = False

    async def receive_until(request_id: str, timeout: float) -> dict:
        give_up = time.monotonic() + timeout
        while True:
            message = json.loads(await diagnostic.bounded_await(socket.recv(), max(0.01, give_up - time.monotonic())))
            if not isinstance(message, dict):
                raise diagnostic.DiagnosticError("WebSocket protocol message is malformed.")
            reply = correlated(message, request_id)
            if reply is not None:
                if diagnostic.protocol_summary(reply)["error_present"]:
                    raise diagnostic.DiagnosticError("Provider refused a control request.")
                return reply
            take(message)

    def take(message: dict) -> None:
        received = int(clock() * 1000)
        symbol = message.get("symbol")
        if symbol not in symbols:
            return
        ticker = symbol[3:]
        day = datetime.fromtimestamp(received / 1000, NEW_YORK).date().isoformat()
        if message.get("type") == "ORDER_BOOK":
            line = book_line(message, received, offset, symbol)
            if line:
                latest[(ticker, line["k"])] = line  # Replace: one book per kind per window.
                status["last_book_ms"][ticker] = received
        elif message.get("type") == "TICKER":
            for line in trade_lines(message, received, symbol):
                store.add(day, ticker, line)
            status["last_trade_ms"][ticker] = received

    logger = logging.Logger("moomoo.depth", level=logging.CRITICAL)  # never log signed frames
    async with connector(diagnostic.WS_URL, proxy=None, open_timeout=10, close_timeout=5, ping_interval=20, ping_timeout=10,
                         max_size=1024 * 1024, max_queue=64, logger=logger) as socket:
        try:
            started = time.time_ns() / 1e6
            await socket.send(json.dumps(diagnostic.websocket_auth(appkey, key, int(clock() * 1000), secrets.token_urlsafe(24)), separators=(",", ":")))
            auth = await receive_until("auth-1", 10)
            if not auth.get("session_id"):
                raise diagnostic.DiagnosticError("Authentication was not confirmed.")
            server_us = diagnostic.number(auth.get("server_time"))
            if server_us and server_us > 0:
                offset = server_us / 1000 - (started + time.time_ns() / 1e6) / 2
            for kind in ("order_book", "ticker"):
                subscribed = True
                await socket.send(json.dumps({"id": "sub-" + kind, "action": "subscribe", kind: symbols}))
                await receive_until("sub-" + kind, 10)
            status.update(state="recording", since=int(clock() * 1000))
            next_snapshot = next_flush = time.monotonic()
            next_refresh = time.monotonic() + REFRESH_SECONDS
            pending = None
            refreshes = 0
            while datetime.now(timezone.utc) < until:
                now = time.monotonic()
                if now >= next_snapshot:
                    for (ticker, _), line in latest.items():
                        store.add(datetime.fromtimestamp(line["rx"] / 1000, NEW_YORK).date().isoformat(), ticker, line)
                    latest.clear()
                    next_snapshot = now + SNAPSHOT_SECONDS
                if now >= next_flush:
                    if not store.flush():
                        status["state"] = "paused: disk space low"
                    elif status["state"].startswith("paused"):
                        status["state"] = "recording"
                    write_status(store.root, status)
                    next_flush = now + FLUSH_SECONDS
                if pending is None and now >= next_refresh:
                    refreshes += 1
                    pending = (f"refresh-{refreshes}", now + 30)
                    await socket.send(json.dumps(diagnostic.websocket_refresh(appkey, key, int(clock() * 1000), secrets.token_urlsafe(24), pending[0]), separators=(",", ":")))
                if pending is not None and now >= pending[1]:
                    raise diagnostic.DiagnosticError("Refresh was not acknowledged.")
                wake = min(next_snapshot, next_flush, pending[1] if pending else next_refresh)
                try:
                    message = json.loads(await diagnostic.bounded_await(socket.recv(), max(0.01, wake - now)))
                except asyncio.TimeoutError:
                    continue
                if not isinstance(message, dict):
                    raise diagnostic.DiagnosticError("WebSocket protocol message is malformed.")
                reply = correlated(message, pending[0]) if pending else None
                if reply is not None:
                    if diagnostic.protocol_summary(reply)["error_present"]:
                        raise diagnostic.DiagnosticError("Refresh was refused.")
                    pending, next_refresh = None, time.monotonic() + REFRESH_SECONDS
                    status["refreshed_ms"] = int(clock() * 1000)
                    continue
                take(message)
        finally:
            for (ticker, _), line in latest.items():
                store.add(datetime.fromtimestamp(line["rx"] / 1000, NEW_YORK).date().isoformat(), ticker, line)
            store.flush()
            if subscribed:
                with suppress(OSError, WebSocketException, asyncio.TimeoutError, ValueError, diagnostic.DiagnosticError):
                    await socket.send(json.dumps({"id": "unsub-1", "action": "unsubscribe", "order_book": symbols, "ticker": symbols}))
                    await diagnostic.bounded_await(socket.recv(), 5)


async def run(tickers: list[str], loader=lab.credentials, connector=diagnostic.NoRedirectConnect, root: Path = STATE) -> None:
    store = Store(root)
    status = {"state": "starting", "tickers": tickers, "reconnects": 0, "last_book_ms": {}, "last_trade_ms": {}}
    delay = BACKOFF[0]
    while True:
        now = datetime.now(timezone.utc)
        store.prune(now.astimezone(NEW_YORK).date())
        span = window(now)
        if span is None:
            status["state"] = "idle until " + next_open(now).isoformat()
            write_status(root, status)
            delay = BACKOFF[0]
            await asyncio.sleep(min(300.0, max(1.0, (next_open(now) - now).total_seconds())))
            continue
        try:
            appkey, key = loader()
            status["state"] = "connecting"
            write_status(root, status)
            await record_window(appkey, key, tickers, span[1], store, status, connector)
            delay = BACKOFF[0]
        except asyncio.CancelledError:
            raise
        except (OSError, WebSocketException, asyncio.TimeoutError, ValueError, diagnostic.DiagnosticError):
            # Fixed text only: provider and credential errors are never logged.
            status["reconnects"] += 1
            status["state"] = f"reconnecting in {delay}s"
            write_status(root, status)
            LOG.warning("Depth connection ended; reconnecting in %ss.", delay)
            await asyncio.sleep(delay + random.uniform(0, 5))
            delay = min(BACKOFF[1], delay * 2)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        tickers = watchlist(os.environ.get("TJ_DEPTH_TICKERS"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    LOG.info("Depth recorder watching %s.", ", ".join(tickers))
    asyncio.run(run(tickers))


if __name__ == "__main__":
    main()
