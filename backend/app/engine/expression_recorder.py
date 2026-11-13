"""Expression recorder: what each of the owner's long option positions would have made expressed another way.

Why (research note, November 13, 2026): on the owner's history, positions held past the entry session lost about
twice in option movement cost what their direction earned, and the cost did not depend on how expensive the option
looked at entry. The history cannot say what a cheaper expression of the same idea would have made, because no
quotes were kept for contracts he did not buy. This records them, so the comparison is paired: same idea, same
moments, same direction exposure, different instrument.

When a long option position's first ``buy_to_open`` fill arrives, the recorder picks the alternatives once from the
live chains and quotes every leg:

- ``as_traded``: the contract he bought, priced by the same rules as the others (the paired baseline);
- ``deeper``: the same expiry and side with the delta nearest ``DEEP_DELTA`` (only when that is deeper than his);
- ``spread``: his contract bought and, sold against it, the same-expiry strike nearest one at-the-money straddle
  move further out of the money (a debit spread);
- ``later``: the strike nearest his in the first expiration at least ``LATER_DAYS`` after the fill and after his;
- ``shares``: the underlying (short for a put: a measuring stick a Roth IRA cannot trade; none for index options).

Every alternative is sized to his fill's delta: units = contracts x (his contract's delta per contract) / (the
alternative's delta per unit), at each entry fill's own quotes. Each later entry fill adds units the same way;
each ``sell_to_close`` closes the same fraction of every alternative as of his open contracts; a position still
open at 15:58 New York on its expiration day is closed there. Buys pay the ask and sells receive the bid, for him
and for every alternative. Quotes are taken when the fill is seen, not at the fill's own second; the lag is
stored and the scorecard leaves out positions with a snapshot later than ``LATE_SECONDS``.

Storage is an append-only SQLite file of its own (``EXPRESSION_RECORDER_PATH``), not the journal database: no
migration, and nothing here writes the journal, sends a message or suggests an order. A position opened before
the recorder saw its first entry fill is skipped. Off unless ``EXPRESSION_RECORDER_ENABLED=true`` (the owner's
switch); it runs on the level alert monitor's loop. ``scripts/expression_scorecard.py`` reads the file.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from sqlalchemy import or_
from sqlmodel import Session, select

from app.engine.analytics import wall_time
from app.engine.chart_math import ET
from app.engine.options_chain import options_chain
from app.engine.options_implied import straddle
from app.engine.options_models import OptionChain, OptionContract
from app.engine.position_alerts import anchor
from app.engine import tradier
from app.models import Account, Fill, Trade, TradeFill

log = logging.getLogger(__name__)

RUN_SECONDS = 20
STALE_SECONDS = 15 * 60  # a fill first seen later than this is not quoted (its moment has passed)
GIVE_UP_SECONDS = 10 * 60  # a fill still unquoted this long after it happened is recorded unavailable
RETRY_SECONDS = 60
LATE_SECONDS = 5 * 60  # the scorecard leaves out positions with a snapshot this far from its fill
DEEP_DELTA = 0.70
DEEPER_BY = 0.10
LATER_DAYS = 21
EXPIRY_MINUTE = 15 * 60 + 58
OPEN_MINUTE, LAST_MINUTE = 9 * 60 + 30, 16 * 60 + 15
CHAIN_SYMBOL = {"SPXW": "SPX"}
NO_SHARES = {"SPX", "SPXW", "NDX", "NDXP", "XSP", "RUT", "RUTW", "VIX", "VIXW"}
ALTERNATIVES = ("as_traded", "deeper", "spread", "later", "shares")
DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "expression_recorder.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS position (
    key TEXT PRIMARY KEY,           -- account id | the first entry fill's source id
    trade_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiration TEXT NOT NULL,
    legs TEXT NOT NULL,             -- JSON: alternative -> [{symbol, sign, multiplier}]
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot (
    fill_key TEXT PRIMARY KEY,      -- account id | fill source id, or expiry | position key
    position_key TEXT,
    role TEXT NOT NULL,             -- entry | exit | expiry | skipped
    executed_at TEXT,               -- the fill's New York wall time
    contracts REAL,
    price REAL,                     -- dollars per contract, as the journal stores fills
    quoted_at REAL NOT NULL,
    status TEXT NOT NULL,           -- recorded | unavailable | skipped
    quotes TEXT,                    -- JSON: symbol -> {bid, ask, delta}
    note TEXT
);
CREATE INDEX IF NOT EXISTS snapshot_position ON snapshot (position_key);
"""


def enabled() -> bool:
    return os.environ.get("EXPRESSION_RECORDER_ENABLED", "").lower() == "true"


def store_path() -> Path:
    return Path(os.environ.get("EXPRESSION_RECORDER_PATH") or DEFAULT_PATH)


# ------------------------------------------------------------------ store


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def seen(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        with closing(self._connect()) as db:
            marks = ",".join("?" * len(keys))
            return {r[0] for r in db.execute(f"SELECT fill_key FROM snapshot WHERE fill_key IN ({marks})", keys)}

    def position(self, key: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM position WHERE key = ?", (key,)).fetchone()
        return None if row is None else {**dict(row), "legs": json.loads(row["legs"])}

    def add_position(self, row: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO position (key, trade_id, ticker, option_type, strike, expiration, legs, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (row["key"], row["trade_id"], row["ticker"], row["option_type"], row["strike"], row["expiration"],
                        json.dumps(row["legs"]), row["created_at"]))

    def add_snapshot(self, row: dict) -> bool:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO snapshot (fill_key, position_key, role, executed_at, contracts, price, quoted_at, status, "
                "quotes, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["fill_key"], row.get("position_key"), row["role"], row.get("executed_at"), row.get("contracts"),
                 row.get("price"), row["quoted_at"], row["status"], json.dumps(row["quotes"]) if row.get("quotes") else None,
                 row.get("note")))
            return cursor.rowcount == 1

    def snapshots(self, position_key: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM snapshot WHERE position_key = ? AND role != 'skipped'", (position_key,)).fetchall()
        return [{**dict(r), "quotes": json.loads(r["quotes"]) if r["quotes"] else None} for r in rows]

    def positions(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM position ORDER BY created_at").fetchall()
        return [{**dict(r), "legs": json.loads(r["legs"])} for r in rows]


# ------------------------------------------------------------------ choosing the alternatives (pure)


def _leg(contract: OptionContract, sign: int) -> dict:
    return {"symbol": contract.symbol, "kind": "option", "sign": sign, "multiplier": contract.multiplier or 100}


def further_out(option_type: str, strike: float, than: float) -> bool:
    return strike > than if option_type == "call" else strike < than


def choose(traded: OptionContract, chain: OptionChain, later: OptionChain | None, spot: float | None, shares: str | None) -> dict:
    """Each alternative's legs. ``traded`` is his contract as listed in ``chain``."""
    same = [c for c in chain.contracts if c.root == traded.root and c.option_type == traded.option_type]
    legs = {"as_traded": [_leg(traded, 1)]}
    if traded.delta is not None and abs(traded.delta) < DEEP_DELTA - DEEPER_BY:
        deeper = [c for c in same if c.delta is not None and abs(c.delta) >= abs(traded.delta) + DEEPER_BY]
        if deeper:
            legs["deeper"] = [_leg(min(deeper, key=lambda c: (abs(abs(c.delta) - DEEP_DELTA), c.strike)), 1)]
    if spot:
        move = straddle(chain, spot, traded.root)
        if move.get("state") == "ready":
            target = traded.strike + move["move"] if traded.option_type == "call" else traded.strike - move["move"]
            out = [c for c in same if further_out(traded.option_type, c.strike, traded.strike)]
            if out:
                legs["spread"] = [_leg(traded, 1), _leg(min(out, key=lambda c: (abs(c.strike - target), c.strike)), -1)]
    if later is not None:
        far = [c for c in later.contracts if c.root == traded.root and c.option_type == traded.option_type]
        if far:
            legs["later"] = [_leg(min(far, key=lambda c: (abs(c.strike - traded.strike), c.strike)), 1)]
    if shares:
        legs["shares"] = [{"symbol": shares, "kind": "share", "sign": 1, "multiplier": 1}]
    return legs


def later_expiration(listed: list[date], expiration: date, day: date) -> date | None:
    target = max(expiration + timedelta(days=1), day + timedelta(days=LATER_DAYS))
    return next((d for d in sorted(listed) if d >= target), None)


# ------------------------------------------------------------------ scoring (pure)


class Missing(Exception):
    """A leg without the quote it needs."""


def unit_delta(legs: list[dict], quotes: dict) -> float | None:
    total = 0.0
    for leg in legs:
        if leg["kind"] == "share":
            total += leg["sign"]
            continue
        delta = (quotes.get(leg["symbol"]) or {}).get("delta")
        if delta is None:
            return None
        total += leg["sign"] * delta * leg["multiplier"]
    return total


def value(legs: list[dict], quotes: dict, units: float, opening: bool) -> float:
    """Dollars paid to open (positive for a debit) or received to close ``units`` of an alternative."""
    total = 0.0
    for leg in legs:
        qty = units * leg["sign"] * leg["multiplier"]
        quote = quotes.get(leg["symbol"]) or {}
        price = (quote.get("ask") if qty > 0 else quote.get("bid")) if opening else (quote.get("bid") if qty > 0 else quote.get("ask"))
        if price is None:
            raise Missing(leg["symbol"])
        total += qty * price
    return total


def score(position: dict, snapshots: list[dict]) -> dict:
    """Each alternative's dollars over the position, beside his actual fills and his contract quoted the same way."""
    legs = position["legs"]
    units = {a: 0.0 for a in legs}
    cash = {a: 0.0 for a in legs}
    dead: set[str] = set()
    open_actual = premium = actual = 0.0
    lags, days, problem = [], set(), None
    for snap in sorted(snapshots, key=lambda s: (s["executed_at"] or "", s["quoted_at"])):
        if snap["status"] != "recorded":
            problem = f"a {snap['role']} snapshot is {snap['status']}"
            break
        quotes, contracts = snap["quotes"], float(snap["contracts"])
        days.add((snap["executed_at"] or "")[:10])
        if snap["role"] == "entry":
            lags.append(snap["quoted_at"] - _epoch(snap["executed_at"]))
            base = unit_delta(legs["as_traded"], quotes)
            if not base:
                problem = "his contract had no delta at an entry"
                break
            for a, parts in legs.items():
                if a in dead:
                    continue
                each = unit_delta(parts, quotes)
                if not each or each * base < 0:
                    dead.add(a)
                    continue
                try:
                    cash[a] -= value(parts, quotes, contracts * base / each, opening=True)
                    units[a] += contracts * base / each
                except Missing:
                    dead.add(a)
            open_actual += contracts
            premium += contracts * float(snap["price"])
            actual -= contracts * float(snap["price"])
            continue
        if open_actual <= 1e-9:
            continue  # nothing left open (an exit after the expiry close)
        if snap["role"] == "exit":
            lags.append(snap["quoted_at"] - _epoch(snap["executed_at"]))
        share = min(1.0, contracts / open_actual)
        for a, parts in legs.items():
            if a in dead:
                continue
            try:
                cash[a] += value(parts, quotes, units[a] * share, opening=False)
                units[a] -= units[a] * share
            except Missing:
                dead.add(a)
        open_actual -= min(contracts, open_actual)
        actual += contracts * float(snap["price"] or 0)
    complete = problem is None and premium > 0 and open_actual <= 1e-9 and "as_traded" not in dead
    return {"key": position["key"], "ticker": position["ticker"], "option_type": position["option_type"],
            "complete": complete, "problem": problem if problem or complete else "still open or no entry",
            "late": any(abs(lag) > LATE_SECONDS for lag in lags), "held": "past the entry session" if len(days) > 1 else "same session",
            "premium": round(premium, 2), "actual": round(actual, 2),
            "pnl": {a: round(cash[a], 2) for a in legs if a not in dead}}


def _epoch(wall: str) -> float:
    return datetime.fromisoformat(wall).replace(tzinfo=ET).timestamp()


# ------------------------------------------------------------------ the pass


def _quotes(rows: dict[str, tradier.TradierQuote]) -> dict:
    return {s: {"bid": q.bid, "ask": q.ask, "delta": q.delta} for s, q in rows.items()}


def _symbols(legs: dict) -> list[str]:
    return sorted({leg["symbol"] for parts in legs.values() for leg in parts})


class ExpressionRecorder:
    def __init__(self, engine, *, clock: Callable[[], float] = time.time, chains=options_chain,
                 quote: Callable = tradier.get_quotes_once, store: Store | None = None):
        self.engine = engine
        self.clock = clock
        self.chains = chains
        self.quote = quote
        self.store = store or Store(store_path())
        self.started_at = clock()
        self._last_run = 0.0
        self._failed: dict[str, float] = {}  # fill key -> when its last attempt failed

    def deliver(self) -> None:
        """Nothing to send; present so the monitor can treat it like its other stages."""

    def run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        minute = moment.hour * 60 + moment.minute
        if moment.weekday() >= 5 or not OPEN_MINUTE <= minute <= LAST_MINUTE:
            return
        with Session(self.engine) as db:
            fresh = self._new_fills(db, now)
            for fill in fresh:
                if now - self._failed.get(fill["key"], 0.0) < RETRY_SECONDS:
                    continue
                try:
                    self._handle(db, fill, now)
                except Exception as exc:  # a provider failure: retried every RETRY_SECONDS until GIVE_UP_SECONDS
                    log.warning("Expression snapshot for %s failed: %s", fill["key"], exc)
                    self._failed[fill["key"]] = now
                    if now - _epoch(fill["executed_at"].isoformat()) > GIVE_UP_SECONDS:
                        self._unavailable(db, fill, now, str(exc)[:200])
        if minute >= EXPIRY_MINUTE:
            self._expiries(moment.date(), now)

    def _new_fills(self, db: Session, now: float) -> list[dict]:
        since = datetime.fromtimestamp(max(self.started_at - 60, now - STALE_SECONDS), ET).replace(tzinfo=None)
        rows = db.exec(select(TradeFill.trade_id, Fill.id, Fill.account_id, Fill.raw_email_id, Fill.side, Fill.contracts,
                              Fill.price, Fill.executed_at)
                       .join(TradeFill, TradeFill.fill_id == Fill.id).join(Account, Account.id == Fill.account_id)
                       .where(Fill.instrument_type == "option", Fill.side.in_(("buy_to_open", "sell_to_close")),
                              Fill.executed_at > since, or_(Account.broker.is_(None), Account.broker != "webull"))).all()
        fills = [{"trade_id": r.trade_id, "account_id": r.account_id, "key": f"{r.account_id}|{r.raw_email_id or r.id}",
                  "side": r.side, "contracts": float(r.contracts), "price": float(r.price), "executed_at": wall_time(r.executed_at)}
                 for r in rows]
        seen = self.store.seen([f["key"] for f in fills])
        return sorted((f for f in fills if f["key"] not in seen), key=lambda f: (f["executed_at"], f["key"]))

    def _position_key(self, db: Session, fill: dict) -> tuple[str, Trade]:
        trade = db.get(Trade, fill["trade_id"])
        entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                          .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
        return f"{fill['account_id']}|{anchor(entries)}", trade

    def _handle(self, db: Session, fill: dict, now: float) -> None:
        key, trade = self._position_key(db, fill)
        position = self.store.position(key)
        if position is None:
            if fill["side"] != "buy_to_open" or key != fill["key"] or trade.option_type not in ("call", "put"):
                self.store.add_snapshot({"fill_key": fill["key"], "position_key": key, "role": "skipped", "quoted_at": now,
                                         "status": "skipped", "note": "the recorder did not see this position's first entry"})
                return
            position = self._open(trade, key, fill, now)
        quotes = _quotes(self.quote(_symbols(position["legs"]), greeks=True))
        self.store.add_snapshot({"fill_key": fill["key"], "position_key": key,
                                 "role": "entry" if fill["side"] == "buy_to_open" else "exit",
                                 "executed_at": fill["executed_at"].isoformat(), "contracts": fill["contracts"], "price": fill["price"],
                                 "quoted_at": self.clock(), "status": "recorded", "quotes": quotes})

    def _open(self, trade: Trade, key: str, fill: dict, now: float) -> dict:
        symbol = CHAIN_SYMBOL.get(trade.ticker, trade.ticker)
        chain = self.chains.chain(symbol, trade.expiration)
        strike = float(trade.strike)
        traded = next((c for c in chain.contracts if c.root == trade.ticker and c.option_type == trade.option_type
                       and abs(c.strike - strike) < 1e-6), None)
        if traded is None:
            raise LookupError(f"{trade.ticker} {trade.expiration} {strike:g} {trade.option_type} is not in the chain")
        spot_quote = self.quote([symbol]).get(symbol)
        spot = (spot_quote.mid or spot_quote.last) if spot_quote else None
        when = later_expiration(self.chains.expirations(symbol), trade.expiration, fill["executed_at"].date())
        later = self.chains.chain(symbol, when) if when else None
        legs = choose(traded, chain, later, spot, None if trade.ticker in NO_SHARES else symbol)
        row = {"key": key, "trade_id": str(trade.id), "ticker": trade.ticker, "option_type": trade.option_type, "strike": strike,
               "expiration": trade.expiration.isoformat(), "legs": legs, "created_at": now}
        self.store.add_position(row)
        return row

    def _unavailable(self, db: Session, fill: dict, now: float, note: str) -> None:
        key, _ = self._position_key(db, fill)
        if self.store.position(key) is None:
            self.store.add_snapshot({"fill_key": fill["key"], "position_key": key, "role": "skipped", "quoted_at": now,
                                     "status": "skipped", "note": note})
            return
        self.store.add_snapshot({"fill_key": fill["key"], "position_key": key,
                                 "role": "entry" if fill["side"] == "buy_to_open" else "exit",
                                 "executed_at": fill["executed_at"].isoformat(), "contracts": fill["contracts"],
                                 "price": fill["price"], "quoted_at": now, "status": "unavailable", "note": note})

    def _expiries(self, today: date, now: float) -> None:
        for position in self.store.positions():
            if position["expiration"] != today.isoformat():
                continue
            snaps = self.store.snapshots(position["key"])
            if any(s["role"] == "expiry" for s in snaps):
                continue
            left = sum(float(s["contracts"] or 0) * (1 if s["role"] == "entry" else -1) for s in snaps if s["role"] in ("entry", "exit"))
            if left <= 1e-9:
                continue
            stamp = datetime.fromtimestamp(now, ET).replace(tzinfo=None, second=0, microsecond=0).isoformat()
            row = {"fill_key": f"expiry|{position['key']}", "position_key": position["key"], "role": "expiry",
                   "executed_at": stamp, "contracts": left, "price": 0.0, "quoted_at": now}
            try:
                row.update(status="recorded", quotes=_quotes(self.quote(_symbols(position["legs"]), greeks=True)))
            except Exception as exc:
                log.warning("Expiry snapshot for %s failed: %s", position["key"], exc)
                row.update(status="unavailable", note=str(exc)[:200])
            self.store.add_snapshot(row)
