"""The desk's live book from Robinhood (docs/robinhood-read-feed.md): a cached snapshot of the owner's accounts and open
positions, read through ``robinhood_read`` (the read-only client), and its join onto the desk's journal position rows.

Off unless ``ROBINHOOD_READ_ENABLED=true`` and the sign-in file (``ROBINHOOD_TOKEN_FILE``) is usable: off, nothing
here touches the network or changes a row. The snapshot is refreshed in the background when a desk read finds it older
than ``ttl`` (a minute in market hours, fifteen outside), one refresh at a time and at most ``MAX_CALLS`` calls each;
``refresh(force=True)`` is the desk's parameterless "refresh now". A read that fails keeps the last snapshot, which
reads ``stale`` once it is three refreshes old; the book then falls back to the journal exactly as it is without the
feed.

Display only. Nothing here writes to the journal (fills, trades, P&L, FIFO). The copilot sees only numbers, tickers and
fixed words from the cached snapshot, through ``copilot_book.live_book``, and never triggers a read. An account appears as its label and its number masked to the last four (``••8267``); the full number, the
sign-in, Robinhood's ids and its ``guide`` text never leave the server. A field missing or of an unexpected shape reads
as unavailable (``None``), never as zero.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from app.engine import robinhood_read as rh
from app.engine.chart_math import ET

log = logging.getLogger(__name__)

DEFAULT_ACCOUNTS = "Roth IRA,MCP"
TYPE_LABELS = {"ira_roth": "Roth IRA", "ira_traditional": "Traditional IRA", "individual": "Individual"}
MAX_CALLS = 40
MAX_PAGES = 5
CHUNK = 20  # quotes above 20 drop their closes
MARKET_TTL, QUIET_TTL = 60, 15 * 60
FORCE_GAP_SECONDS = 15
STALE_REFRESHES = 3


@dataclass(frozen=True)
class Settings:
    enabled: bool
    token_file: str | None
    accounts: tuple[str, ...]


def settings() -> Settings:
    picks = os.environ.get("ROBINHOOD_ACCOUNTS", DEFAULT_ACCOUNTS)
    return Settings(enabled=os.environ.get("ROBINHOOD_READ_ENABLED") == "true",
                    token_file=os.environ.get("ROBINHOOD_TOKEN_FILE") or None,
                    accounts=tuple(p.strip().lower() for p in picks.split(",") if p.strip()))


# --------------------------------------------------------------------------- parsing (defensive: unexpected = None)

def _num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _text(value, limit: int = 40) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _list(data: dict, *keys: str) -> list[dict]:
    for key in keys:
        found = data.get(key)
        if isinstance(found, list):
            return [x for x in found if isinstance(x, dict)]
    return []


def _next(data: dict) -> str | None:
    for key in ("next", "next_cursor", "cursor"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def mask(last4: str | None) -> str | None:
    return f"••{last4}" if last4 else None


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


ACCOUNT_NUMBER = re.compile(r"[A-Za-z0-9]{4,32}")


def _accounts(data: dict) -> list[dict]:
    """Each active account: its number (kept on the server for the calls only), last four (the digits of
    ``rhs_account_number`` when there are some, as the fill emails give them), type and label. No account read is a
    failed read, never an empty book."""
    out = []
    for a in _list(data, "accounts", "results"):
        number = a.get("account_number").strip() if isinstance(a.get("account_number"), str) else ""
        if not ACCOUNT_NUMBER.fullmatch(number) or a.get("deactivated") or a.get("permanently_deactivated"):
            continue
        digits = a.get("rhs_account_number").strip() if isinstance(a.get("rhs_account_number"), str) else ""
        last4 = (digits if digits.isdigit() and len(digits) >= 4 else number)[-4:]
        kind = _text(a.get("brokerage_account_type")) or ""
        nickname = _text(a.get("nickname"), 20)
        label = nickname or TYPE_LABELS.get(kind) or (kind.replace("_", " ").title() if kind else "Account")
        out.append({"number": number, "last4": last4, "label": "".join(ch for ch in label if not ch.isdigit()).strip() or "Account",
                    "type": kind})
    if not out:
        raise rh.ReadError("shape", "no accounts")
    return out


def _portfolio(data: dict) -> dict:
    power = data.get("buying_power")
    return {"total_value": _num(data.get("total_value")), "cash": _num(data.get("cash")),
            "buying_power": _num(power.get("buying_power")) if isinstance(power, dict) else _num(power)}


def _paged(read, account: str) -> list[dict]:
    rows, cursor, seen = [], None, set()
    for _ in range(MAX_PAGES):
        data = read(account, cursor)
        if not any(isinstance(data.get(k), list) for k in ("positions", "results")):
            raise rh.ReadError("shape", "positions reply")  # an unknown shape is unknown, never "holds nothing"
        rows += _list(data, "positions", "results")
        cursor = _next(data)
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    return rows


def _chunks(items: list, size: int = CHUNK):
    return [items[i:i + size] for i in range(0, len(items), size)]


def _option_row(account: dict, p: dict, inst: dict | None, quote: dict | None) -> dict | None:
    qty = _num(p.get("quantity"))
    symbol = _text(p.get("chain_symbol"), 12) or _text((inst or {}).get("chain_symbol"), 12)
    if not qty or not symbol:
        return None
    side = (inst or {}).get("type") if (inst or {}).get("type") in ("call", "put") else None
    direction = "short" if p.get("type") == "short" else "long"
    multiplier = _num(p.get("trade_value_multiplier")) or _num((inst or {}).get("trade_value_multiplier"))
    avg = _num(p.get("average_price"))  # dollars a contract (the premium x 100); a short's may come signed
    avg = abs(avg) if avg is not None else None
    q = quote or {}
    mark_share = _num(q.get("mark_price")) if _num(q.get("mark_price")) is not None else _num(q.get("adjusted_mark_price"))
    mark = mark_share * multiplier if mark_share is not None and multiplier else None
    sign = -1 if direction == "short" else 1
    usd = sign * (mark - avg) * qty if mark is not None and avg is not None else None
    pct = 100 * sign * (mark - avg) / avg if mark is not None and avg else None
    prev = _num(q.get("previous_close_price"))
    expiry = _text(p.get("expiration_date"), 10) or _text((inst or {}).get("expiration_date"), 10)
    return {
        "account": account["label"], "last4": account["last4"], "instrument": "option", "symbol": symbol.upper(),
        "side": side, "strike": _num((inst or {}).get("strike_price")), "expiry": expiry, "direction": direction,
        "quantity": qty, "multiplier": multiplier, "avg_cost": _round(avg), "mark": _round(mark), "bid": _num(q.get("bid_price")),
        "ask": _num(q.get("ask_price")),
        "day_change_pct": _round(100 * (mark_share - prev) / prev, 1) if mark_share is not None and prev else None,
        "greeks": {k: _num(q.get(k)) for k in ("delta", "gamma", "theta", "vega")} | {"iv": _num(q.get("implied_volatility"))},
        "usd": _round(usd), "pct": _round(pct, 1), "opened_at": _text(p.get("opened_at"), 40),
    }


def _stock_quote(item: dict) -> tuple[str | None, dict]:
    q = item.get("quote") if isinstance(item.get("quote"), dict) else item
    close = item.get("close") if isinstance(item.get("close"), dict) else {}
    symbol = _text(q.get("symbol"), 12) or _text(close.get("symbol"), 12)
    last = next((v for v in (_num(q.get(k)) for k in ("last_trade_price", "mark_price", "price")) if v is not None), None)
    prev = _num(q.get("previous_close")) or _num(q.get("adjusted_previous_close")) or _num(close.get("price"))
    return (symbol.upper() if symbol else None), {"last": last, "prev": prev}


def _stock_row(account: dict, p: dict, quote: dict | None) -> dict | None:
    qty, symbol = _num(p.get("quantity")), _text(p.get("symbol"), 12)
    if not qty or not symbol:
        return None
    avg = _num(p.get("average_buy_price"))
    last = (quote or {}).get("last")
    prev = (quote or {}).get("prev")
    sign = -1 if p.get("type") == "short" else 1
    usd = sign * (last - avg) * qty if last is not None and avg is not None else None
    return {
        "account": account["label"], "last4": account["last4"], "instrument": "stock", "symbol": symbol.upper(),
        "side": None, "strike": None, "expiry": None, "direction": "short" if sign < 0 else "long", "quantity": qty, "multiplier": None,
        "avg_cost": _round(avg), "mark": _round(last), "bid": None, "ask": None,
        "day_change_pct": _round(100 * (last - prev) / prev, 1) if last is not None and prev else None, "greeks": None,
        "usd": _round(usd), "pct": _round(100 * sign * (last - avg) / avg, 1) if last is not None and avg else None, "opened_at": None,
    }


def read_snapshot(reader: rh.Reader, picks: tuple[str, ...], now: float) -> dict:
    """One full read: accounts, each one's portfolio and open positions, option instruments and quotes, stock quotes.
    An account whose positions did not read is ``complete: false``; its positions are unknown, not empty."""
    accounts = _accounts(reader.get_accounts())
    held_options, held_stocks = [], []
    for a in accounts:
        try:
            a["values"] = _portfolio(reader.get_portfolio(a["number"]))
        except rh.ReadError as exc:
            if exc.kind == "expired":
                raise
            a["values"] = {"total_value": None, "cash": None, "buying_power": None}
        a["complete"] = True
        options, stocks = [], []
        for read, out in ((reader.get_option_positions, options), (reader.get_equity_positions, stocks)):
            try:
                out += _paged(read, a["number"])
            except rh.ReadError as exc:
                if exc.kind == "expired":
                    raise
                a["complete"] = False
        held_options += [(a, p) for p in options if (_num(p.get("quantity")) or 0) > 0]
        held_stocks += [(a, p) for p in stocks if (_num(p.get("quantity")) or 0) > 0]

    ids = sorted({p["option_id"] for _a, p in held_options if isinstance(p.get("option_id"), str)})
    instruments, quotes, stock_quotes = {}, {}, {}
    for part in _chunks(ids):
        try:
            for inst in _list(reader.get_option_instruments(part), "instruments", "results"):
                if isinstance(inst.get("id"), str):
                    instruments[inst["id"]] = inst
        except rh.ReadError as exc:
            if exc.kind == "expired":
                raise
        try:
            for item in _list(reader.get_option_quotes(part), "results", "quotes"):
                q = item.get("quote") if isinstance(item.get("quote"), dict) else item
                if isinstance(q.get("instrument_id"), str):
                    quotes[q["instrument_id"]] = q
        except rh.ReadError as exc:
            if exc.kind == "expired":
                raise
    symbols = sorted({_text(p.get("symbol"), 12).upper() for _a, p in held_stocks if _text(p.get("symbol"), 12)})
    for part in _chunks(symbols):
        try:
            for item in _list(reader.get_equity_quotes(part), "results", "quotes"):
                symbol, q = _stock_quote(item)
                if symbol:
                    stock_quotes[symbol] = q
        except rh.ReadError as exc:
            if exc.kind == "expired":
                raise

    positions = [row for a, p in held_options
                 if (row := _option_row(a, p, instruments.get(p.get("option_id")), quotes.get(p.get("option_id")))) is not None]
    positions += [row for a, p in held_stocks
                  if (row := _stock_row(a, p, stock_quotes.get((_text(p.get("symbol"), 12) or "").upper()))) is not None]
    holding = {r["last4"] for r in positions}
    shown = [a for a in accounts if a["label"].lower() in picks or a["last4"] in picks or a["type"] in picks
             or a["last4"] in holding or (a["values"]["total_value"] or 0) > 0]
    return {
        "at": now,
        "accounts": [{"label": a["label"], "masked": mask(a["last4"]), "last4": a["last4"], **a["values"], "complete": a["complete"]}
                     for a in shown],
        "complete": all(a["complete"] for a in accounts),
        "positions": positions,
        "calls": reader.calls,
    }


# --------------------------------------------------------------------------- the cache

def market_hours(now: float) -> bool:
    moment = datetime.fromtimestamp(now, ET)
    minutes = moment.hour * 60 + moment.minute
    return moment.weekday() < 5 and 9 * 60 + 25 <= minutes <= 16 * 60 + 15


def ttl(now: float) -> int:
    return MARKET_TTL if market_hours(now) else QUIET_TTL


class Feed:
    def __init__(self, settings_fn=settings, now=time.time):
        self._settings = settings_fn
        self._now = now
        self._sign: rh.Sign | None = None
        self._sign_path: str | None = None
        self._snapshot: dict | None = None
        self._attempt = 0.0
        self._issue: str | None = None
        self._flight = threading.Lock()

    def _signer(self, path: str) -> rh.Sign:
        if self._sign is None or self._sign_path != path:
            self._sign, self._sign_path, self._snapshot = rh.Sign(path, now=self._now), path, None
        return self._sign

    def _gate(self) -> tuple[str, rh.Sign | None, Settings]:
        """``off``, ``signed_out``, ``expired`` or ``ready``, without any network I/O."""
        s = self._settings()
        if not s.enabled:
            return "off", None, s
        if not s.token_file:
            return "signed_out", None, s
        sign = self._signer(s.token_file)
        try:
            _signin, signature = sign.file.read()
        except rh.ReadError:
            return "signed_out", None, s
        if sign.expired:
            return "expired", None, s
        return "ready", sign, s

    def signer(self) -> rh.Sign | None:
        """The feed's sign-in when the feed is on and its file usable, else None (no network I/O). The order-history
        fills (``robinhood_fills``) read through it, so there is one sign-in and one renewal for both."""
        gate, sign, _s = self._gate()
        return sign if gate == "ready" else None

    def refresh(self, force: bool = False) -> dict:
        """Read now (one refresh at a time). ``force`` is the desk's refresh button: still no more than one read every
        ``FORCE_GAP_SECONDS``; without it, only once the snapshot is older than ``ttl``."""
        gate, sign, s = self._gate()
        if gate != "ready":
            return self.view(kick=False)
        now = self._now()
        gap = FORCE_GAP_SECONDS if force else ttl(now)
        if now - self._attempt < gap or not self._flight.acquire(blocking=False):
            return self.view(kick=False)
        try:
            self._attempt = now
            reader = rh.Reader(sign, max_calls=MAX_CALLS)
            try:
                self._snapshot = read_snapshot(reader, s.accounts, self._now())
                self._issue = None
            except rh.ReadError as exc:
                self._issue = exc.kind
                log.warning("Robinhood feed refresh failed (%s)", exc.kind)
            except Exception as exc:  # noqa: BLE001 - an odd reply must not take the desk or the refresh route down
                self._issue = "error"
                log.warning("Robinhood feed refresh failed (%s)", type(exc).__name__)
        finally:
            self._flight.release()
        return self.view(kick=False)

    def _kick(self) -> None:
        if self._flight.locked() or self._now() - self._attempt < ttl(self._now()):
            return
        threading.Thread(target=self.refresh, name="robinhood-feed", daemon=True).start()

    def snapshot(self, kick: bool = True) -> tuple[dict, dict | None]:
        """(the summary the desk shows, the snapshot when it is healthy enough to drive the book, else None)."""
        gate, _sign, _s = self._gate()
        if gate != "ready":
            return {"state": gate}, None
        if kick:
            self._kick()
        snap, now = self._snapshot, self._now()
        if self._sign is not None and self._sign.expired:
            return {"state": "expired"}, None
        if snap is None:
            return {"state": "loading" if self._issue is None else "unavailable"}, None
        age = now - snap["at"]
        state = "stale" if age > STALE_REFRESHES * ttl(now) else "ok"
        summary = {"state": state, "as_of": int(snap["at"]), "issue": self._issue,
                   "accounts": [{k: a[k] for k in ("label", "masked", "total_value", "cash", "buying_power")} for a in snap["accounts"]]}
        return summary, snap if state == "ok" else None

    def view(self, kick: bool = True) -> dict:
        return self.snapshot(kick=kick)[0]


feed = Feed()


# --------------------------------------------------------------------------- the join onto the desk's book

def contract_key(symbol: str | None, instrument: str | None, side: str | None, strike, expiry: str | None) -> tuple | None:
    if not symbol:
        return None
    if instrument != "option":
        return (symbol.upper(), "stock")
    value = _num(strike)
    if side not in ("call", "put") or value is None or not expiry:
        return None
    return (symbol.upper(), side, round(value, 3), str(expiry)[:10])


def label(live: dict) -> str:
    """The journal's contract label for a Robinhood position (``chart_journal.contract_label``)."""
    from app.engine.chart_journal import contract_label
    if live["instrument"] != "option":
        return f"{live['symbol']} stock"
    expiry = None
    try:
        expiry = datetime.strptime(live["expiry"], "%Y-%m-%d").date() if live["expiry"] else None
    except ValueError:
        pass
    return contract_label(live["symbol"], "option", live["side"], live["strike"], expiry)


def match(journal: list[dict], snapshot: dict) -> tuple[dict[str, dict], set[str], list[dict]]:
    """(each matched journal trade id -> its Robinhood position, the trade ids Robinhood does not show, the Robinhood
    positions the journal does not have). ``journal``: ``{"trade_id", "key", "last4"}`` per open journal position.
    A journal position matches the same contract in its own account first, else the same contract in any account. A
    position is "not on Robinhood" only when every account's positions were read."""
    live = list(snapshot["positions"])
    keys = [contract_key(p["symbol"], p["instrument"], p["side"], p["strike"], p["expiry"]) for p in live]
    used: set[int] = set()
    matched: dict[str, dict] = {}
    for same_account in (True, False):  # every exact-account match first, then any account
        for row in journal:
            if row["key"] is None or row["trade_id"] in matched:
                continue
            pick = next((i for i, k in enumerate(keys) if i not in used and k == row["key"]
                         and (not same_account or live[i]["last4"] == row.get("last4"))), None)
            if pick is not None:
                used.add(pick)
                matched[row["trade_id"]] = live[pick]
    missing = {r["trade_id"] for r in journal if r["trade_id"] not in matched} if snapshot.get("complete") else set()
    return matched, missing, [p for i, p in enumerate(live) if i not in used]


def account_tag(live: dict) -> dict:
    return {"label": live["account"], "masked": mask(live["last4"])}
