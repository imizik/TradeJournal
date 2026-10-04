"""Option chains for the chart: the options levels layer (Charts C4.4), the strike
ladder (C4.5) and the implied move (symbol info T2.1).

Every read goes through the C4.1 adapter (`options_chain`) and its budget of 30
requests a minute, without waiting for a slot: the chart is interactive, so a
read the budget cannot take now is refused, the older copy is served with its
read time, and the next poll tries again.

Refresh cadence, per symbol (C4.4): the nearest three unexpired expirations at
most once every 60 seconds, farther ones (the 45-day scope) at most every 10
minutes, and the expiration list every 30 minutes. A pass reads at most
``PER_PASS`` chains, nearest first, so a first look at a symbol with many
expirations spreads over a few polls instead of spending the minute at once.
And the feed takes at most ``PER_MINUTE`` of the adapter's 30 in any rolling
minute, whatever asks: past that a read waits for the next poll.
The chart asks for its main symbol's scope and only the nearest expiration of
symbols that panels hold (SPY and QQQ 0DTE), which keeps the steady state near
ten requests a minute.

Chains live in memory only. One read on an earlier New York date is not used:
open interest changes overnight. The chart layer never waits: ``chart``
answers from memory and refreshes on a background thread. The ladder and the
Forecast tab wait for their own reads.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
import threading
import time

from app.engine.chart_levels import Level
from app.engine.chart_math import ET
from app.engine.options_chain import OptionsChainError, TradierOptions
from app.engine.options_implied import days_to, straddle, targets
from app.engine.options_models import OptionChain
from app.engine.options_positioning import (DEALER_SIDE, FLIP_SYMBOLS, MEASURES, SCOPES, GammaFlip, Positioning, StrikeRow,
                                            chart_levels, gamma_flip, positioning, primary_root, scope_expirations)

log = logging.getLogger(__name__)

FAST = 3  # the nearest expirations refreshed every minute
FAST_TTL = 60
SLOW_TTL = 600
LIST_TTL = 1800
PER_PASS = 6
PER_MINUTE = 24  # of the options budget's 30, leaving room for the nightly recorder's catch-up run
PACING = "Option reads are pacing to stay within their data allowance; the rest load on the next refresh."
RETRY_SECONDS = 30
KEEP_SYMBOLS = 8
LADDER_STRIKES = 25  # strikes shown on each side of the price
FLIP_DRIFT = 0.01  # a flip computed within 1% of the current price, on the same chains, is reused
SOURCE = "Tradier option chains"


@dataclass(frozen=True, slots=True)
class Layer:
    """What the chart's options layer asks for: a measure, a scope and whether gamma is signed."""
    measure: str = "oi"
    scope: str = "week"
    signed: bool = False

    @classmethod
    def parse(cls, text: str) -> Layer:
        """``oi.week.0``; raises ValueError on anything else."""
        measure, scope, signed = text.split(".")
        if measure not in MEASURES or scope not in SCOPES or signed not in ("0", "1"):
            raise ValueError(text)
        return cls(measure, scope, signed == "1")


@dataclass(frozen=True, slots=True)
class Read:
    fetched: float  # this process's clock when the response arrived
    value: object


class OptionsFeed:
    def __init__(self, client: TradierOptions | None = None, calendar=None, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self._client = client
        self._calendar = calendar
        self._clock = clock
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="options-feed").start())
        self._lock = threading.Lock()  # guards the state below
        self._fetching = threading.Lock()  # one pass of provider reads at a time; a waiter reuses its result
        self._lists: dict[str, Read] = {}
        self._chains: OrderedDict[str, dict[date, Read]] = OrderedDict()  # by symbol, least recently used first
        self._retry: tuple[float, str] = (0.0, "")
        self._calls: deque[float] = deque()
        self._refreshing: set[str] = set()
        self._flips: dict[tuple, tuple[float, GammaFlip]] = {}

    # ------------------------------------------------------------------ public

    def chart(self, symbol: str, layer: Layer, spot: float | None) -> tuple[list[Level], dict]:
        """The levels the chart draws for ``symbol`` and what the card and the layers panel say
        about them, from memory only. Anything stale refreshes in the background."""
        now = self._now()
        if self._stale(symbol, layer.scope, now):
            self._background(symbol, layer.scope)
        found, info, chains = self._read(symbol, layer.scope, spot, now)
        if found is None:
            return [], {**info, "mode": layer.measure, "signed": layer.signed, "strikes": [], "flip": None}
        flip = self._flip(layer.scope, found, chains, now) if layer.signed and layer.measure == "gamma" else None
        levels = chart_levels(found, layer.measure, layer.signed, flip)
        shown = {level.price for level in levels}
        rows = self._rows(found, [row for row in found.strikes if row.strike in shown], layer.measure, layer.signed)
        return levels, {**info, "mode": layer.measure, "signed": layer.signed, "strikes": rows, "flip": _flip_view(flip)}

    def ladder(self, symbol: str, scope: str, signed: bool, spot: float | None) -> dict:
        """Every strike near the price for the side panel, reading what is stale first."""
        issue = self.refresh(symbol, scope)
        now = self._now()
        found, info, chains = self._read(symbol, scope, spot, now, issue)
        if found is None:
            return {**info, "signed": signed, "rows": [], "walls": {}, "flip": None}
        strikes = list(found.strikes)
        centre = min(range(len(strikes)), key=lambda i: abs(strikes[i].strike - spot)) if spot and strikes else len(strikes) // 2
        near = strikes[max(0, centre - LADDER_STRIKES):centre + LADDER_STRIKES + 1]
        flip = self._flip(scope, found, chains, now) if signed else None
        walls = {f"{side}_{measure}": getattr(found.wall(measure, side), "strike", None)
                 for measure in ("oi", "volume") for side in ("call", "put")}
        return {**info, "signed": signed, "walls": walls, "flip": _flip_view(flip),
                "rows": self._rows(found, near, "gamma", signed)}

    def forecast(self, symbol: str, spot: float | None, earnings: dict | None) -> dict:
        """The at-the-money straddle for the nearest expiration, the nearest Friday and the
        first expiration after the next earnings report (T2.1), reading what is stale first."""
        now = self._now()
        today = now.date()
        base = {"symbol": symbol, "today": today.isoformat(), "source": SOURCE, "spot": spot, "earnings": earnings,
                "moves": [], "message": None}
        root = primary_root(symbol)
        earned = date.fromisoformat(earnings["date"]) if earnings else None
        with self._fetching:
            issue = self._read_list(symbol)
            listed = self._list(symbol)
            if listed is None:
                return {**base, "state": "unavailable", "message": issue or "Option expirations are not loaded yet."}
            chosen = targets(listed, root, now, earned, self._closes(listed[:FAST]))
            wanted = list(dict.fromkeys(d for d in chosen.values() if d is not None))
            issue = self._read_chains(symbol, [d for d in wanted if self._chain_stale(symbol, d, FAST_TTL, today)]) or issue
        if spot is None:
            return {**base, "state": "unavailable", "message": f"No {symbol} price yet."}
        moves = []
        for expiration in wanted:
            read = self._chain(symbol, expiration, today)
            tags = [name for name, value in chosen.items() if value == expiration]
            row = {"tags": tags, "expiration": expiration.isoformat(), "days": days_to(expiration, today)}
            if read is None:
                moves.append({**row, "state": "unavailable", "reason": issue or "Not loaded yet."})
                continue
            moves.append({**row, **straddle(read.value, spot, root), "fetched_at": int(read.fetched)})
        note = None
        if earnings and chosen["earnings"] is None:
            note = "No expiration after the next report is listed yet."
        return {**base, "state": "ready" if listed else "none", "moves": moves, "earnings_note": note,
                "message": issue if any(m["state"] == "unavailable" for m in moves) else None}

    def refresh(self, symbol: str, scope: str, limit: int = PER_PASS) -> str | None:
        """Read the expiration list and up to ``limit`` of the scope's stale chains, nearest
        first. Returns why it could not read something, or None."""
        with self._fetching:
            issue = self._read_list(symbol)
            listed = self._list(symbol)
            if listed is None:
                return issue
            now = self._now()
            stale = [d for d, ttl in self._wanted(symbol, scope, listed, now) if self._chain_stale(symbol, d, ttl, now.date())]
            return self._read_chains(symbol, stale[:limit]) or issue

    # ------------------------------------------------------------------ views

    def _read(self, symbol: str, scope: str, spot: float | None, now: datetime,
              issue: str | None = None) -> tuple[Positioning | None, dict, list[OptionChain]]:
        """Positioning over the scope's chains (and the chains), once every one of them is in memory."""
        root = primary_root(symbol)
        info = {"symbol": symbol, "root": root, "scope": scope, "source": SOURCE, "spot": spot,
                "expirations": [], "scope_note": None, "message": issue or self._cooling()}
        listed = self._list(symbol)
        if listed is None:
            return None, {**info, "state": "unavailable" if info["message"] else "loading"}, []
        wanted = [d for d, _ in self._wanted(symbol, scope, listed, now)]
        info["expirations"] = [d.isoformat() for d in wanted]
        info["scope_note"] = _scope_note(scope, wanted, now.date())
        if not wanted:
            return None, {**info, "state": "none", "message": "No listed expiration within 45 days."}, []
        reads = [self._chain(symbol, d, now.date()) for d in wanted]
        have = [read for read in reads if read is not None]
        if len(have) < len(wanted):
            loading = f"Loaded {len(have)} of {len(wanted)} expirations."
            return None, {**info, "state": "unavailable" if info["message"] else "loading",
                          "message": info["message"] or loading}, []
        chains = [read.value for read in have]
        found = positioning(chains, symbol, spot, now, root, self._closes(wanted))
        return found, {**info, "state": "ready",
                       "fetched_at": int(min(read.fetched for read in have)),
                       "last_trade_at": int(found.last_trade_at.timestamp()) if found.last_trade_at else None,
                       "greeks_updated_at": found.greeks_updated_at,
                       "excluded": found.excluded, "missing": found.missing, "totals": found.totals()}, chains

    @staticmethod
    def _rows(found: Positioning, rows: list[StrikeRow], measure: str, signed: bool) -> list[dict]:
        """What a card or the ladder shows per strike: the values, signed gamma when asked for, and its ranks."""
        ranks = {"rank": found.ranks(measure, None, signed and measure == "gamma"),
                 **{f"{side}_{m}_rank": found.ranks(m, side) for m in ("oi", "volume") for side in ("call", "put")}}
        return [{"strike": row.strike, "call_oi": row.call_oi, "put_oi": row.put_oi, "call_volume": row.call_volume,
                 "put_volume": row.put_volume, "call_gamma": row.call_gamma, "put_gamma": row.put_gamma,
                 "gamma": row.total("gamma", signed), **{key: places.get(row.strike) for key, places in ranks.items()}}
                for row in rows]

    def _flip(self, scope: str, found: Positioning, chains: list[OptionChain], now: datetime) -> GammaFlip | None:
        """The gamma flip on these chains, reused while the price stays within ``FLIP_DRIFT`` of where it was computed."""
        if found.underlying not in FLIP_SYMBOLS or found.spot is None:
            return None
        key = (found.underlying, found.root, scope, tuple(sorted((c.expiration, c.fetched_at) for c in chains)))
        with self._lock:
            saved = self._flips.get(key)
        if saved and abs(saved[0] - found.spot) <= FLIP_DRIFT * found.spot:
            return saved[1]
        flip = gamma_flip(chains, found.underlying, found.spot, now, found.root, self._closes(found.expirations))
        with self._lock:
            self._flips = {k: v for k, v in self._flips.items() if k[:3] != key[:3]}
            self._flips[key] = (found.spot, flip)
        return flip

    # ------------------------------------------------------------------ cache

    def _wanted(self, symbol: str, scope: str, listed: list[date], now: datetime) -> list[tuple[date, int]]:
        """The scope's expirations, each with how long its chain stays fresh."""
        root = primary_root(symbol)
        live = scope_expirations(listed, "all", now, root, self._closes(listed[:FAST]))
        fast = set(live[:FAST])
        chosen = scope_expirations(listed, scope, now, root, self._closes(listed[:FAST]))
        return [(d, FAST_TTL if d in fast else SLOW_TTL) for d in chosen]

    def _stale(self, symbol: str, scope: str, now: datetime) -> bool:
        listed = self._list(symbol)
        if listed is None or self._clock() - self._lists[symbol].fetched >= LIST_TTL:
            return True
        return any(self._chain_stale(symbol, d, ttl, now.date()) for d, ttl in self._wanted(symbol, scope, listed, now))

    def _chain_stale(self, symbol: str, expiration: date, ttl: int, today: date) -> bool:
        read = self._chain(symbol, expiration, today)
        return read is None or self._clock() - read.fetched >= ttl

    def _list(self, symbol: str) -> list[date] | None:
        with self._lock:
            read = self._lists.get(symbol)
        return read.value if read else None

    def _chain(self, symbol: str, expiration: date, today: date) -> Read | None:
        with self._lock:
            read = self._chains.get(symbol, {}).get(expiration)
        if read is None or datetime.fromtimestamp(read.fetched, ET).date() != today:
            return None
        return read

    def _read_list(self, symbol: str) -> str | None:
        with self._lock:
            read = self._lists.get(symbol)
        if read is not None and self._clock() - read.fetched < LIST_TTL:
            return None
        if issue := self._cooling() or self._take():
            return issue
        try:
            listed = self.client.expirations(symbol)
        except OptionsChainError as exc:
            return self._failed(exc)
        with self._lock:
            self._lists[symbol] = Read(self._clock(), listed)
        return None

    def _read_chains(self, symbol: str, expirations: list[date]) -> str | None:
        for expiration in expirations:
            if issue := self._cooling() or self._take():
                return issue
            try:
                chain = self.client.chain(symbol, expiration)
            except OptionsChainError as exc:
                return self._failed(exc)
            with self._lock:
                chains = self._chains.setdefault(symbol, {})
                chains[expiration] = Read(self._clock(), chain)
                for old in [d for d in chains if d < self._now().date()]:
                    del chains[old]  # expired dates leave with the day
                self._chains.move_to_end(symbol)
                while len(self._chains) > KEEP_SYMBOLS:
                    gone, _ = self._chains.popitem(last=False)
                    self._lists.pop(gone, None)
        return None

    def _failed(self, exc: OptionsChainError) -> str:
        wait = 60 if exc.code in ("rate_limited", "access_denied", "not_configured") else RETRY_SECONDS
        with self._lock:
            self._retry = (self._clock() + wait, str(exc))
        return str(exc)

    def _take(self) -> str | None:
        """Claim one read of this minute's ``PER_MINUTE``, or say why not."""
        with self._lock:
            now = self._clock()
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            if len(self._calls) >= PER_MINUTE:
                return PACING
            self._calls.append(now)
        return None

    def _cooling(self) -> str | None:
        with self._lock:
            until, why = self._retry
        return why if self._clock() < until else None

    def _background(self, symbol: str, scope: str) -> None:
        if self._cooling():
            return
        with self._lock:
            if symbol in self._refreshing:
                return
            self._refreshing.add(symbol)

        def work():
            try:
                self.refresh(symbol, scope)
            except Exception:  # a background thread has no caller to tell
                log.exception("Option chain refresh failed for %s", symbol)
            finally:
                with self._lock:
                    self._refreshing.discard(symbol)
        try:
            self._spawn(work)
        except RuntimeError:
            with self._lock:
                self._refreshing.discard(symbol)

    def _closes(self, dates) -> dict[date, int | None]:
        """Each date's close from the market calendar, for expiry times; None where it has none."""
        calendar = self._calendar
        if calendar is None:
            from app.engine.chart_calendar import chart_calendar as calendar
        out = {}
        for day in dates:
            hours = calendar.hours(day)
            out[day] = hours["close"] if hours and hours.get("status") == "open" else None
        return out

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), timezone.utc).astimezone(ET)

    @property
    def client(self) -> TradierOptions:
        if self._client is None:
            from app.engine.options_chain import options_chain
            return options_chain
        return self._client


def _flip_view(flip: GammaFlip | None) -> dict | None:
    if flip is None:
        return None
    return {"price": flip.price, "low": round(flip.searched[0], 2), "high": round(flip.searched[1], 2), "note": flip.note,
            "assumption": DEALER_SIDE}


def _scope_note(scope: str, wanted: list[date], today: date) -> str | None:
    if not wanted:
        return None
    first = wanted[0]
    if scope == "nearest":
        return f"0DTE {first:%b} {first.day}" if first == today else f"Next expiration {first:%a %b} {first.day} (no 0DTE today)"
    if scope == "week":
        monday = first - timedelta(days=first.weekday())
        return f"Week of {monday:%b} {monday.day}: {len(wanted)} expiration{'s' if len(wanted) != 1 else ''}"
    return f"Within 45 days: {len(wanted)} expirations"


options_feed = OptionsFeed()
