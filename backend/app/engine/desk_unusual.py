"""Unusual options activity on the names he holds or watches (docs/copilot-lab.md § Unusual options).

Read-only. Nothing here places, sends or stages an order, nothing reads Robinhood, nothing pings and nothing is rated.

- **Which names.** The underlyings of his open journal trades (Webull left out, as on the rest of the desk), then his
  Watching list (``desk_watch``), never a ticker he set to Not following; at most ``MAX_SYMBOLS``. When the not-followed
  setting cannot be read nothing is shown, since a hidden ticker must stay silent.
- **What is read.** Each name's nearest ``EXPIRIES`` expiries through the options feed (``options_feed.chains``: Tradier
  through the C4.1 adapter, its 24-a-minute pacing inside the 30-a-minute options budget), the same cache the Chain tab
  and the chart read, so a chain the desk read in the last ``REFRESH_S`` seconds costs nothing. A pass starts only while
  the desk is asking (the Feed's minute read) and only in the regular session; it reads one name every ``GAP_S``
  seconds, so it adds at most eight reads a minute (three expiries a name and, once every 30 minutes, its expiry
  list), six once the lists are in, and nothing for a name whose chains the desk read in the last five minutes.
- **The two rules.** A contract is unusual when its volume today is at least ``VOL_OI`` times its open interest (last
  night's count, as OCC publishes it) and at least ``MIN_VOLUME`` contracts; a contract with no open interest at all
  and that much volume counts too. A ticker is unusual on its call (or put) side when that side's volume so far today,
  over its nearest ``TICKER_EXPIRIES`` expiries after today (same-day expiries left out on both sides), is at least ``TICKER_X`` times its average full session over its last
  ``HISTORY_SESSIONS`` recorded sessions (the nightly option snapshots, ``options_recorder``) and at least
  ``TICKER_MIN`` contracts. A name the recorder has fewer than ``MIN_HISTORY`` sessions of gets the contract rule only,
  and the reply says so; so does a name whose read came back short (``partial``).
- **No side guessed.** The chain carries volume and the last price, not which trades hit the bid or the ask, so no side
  is shown.
- **Honest gaps.** A missing volume or open interest is skipped, never read as zero. A name not read yet, or whose read
  failed, is named in a grey line. In the session a name read more than ``STALE_S`` seconds ago is stale. Outside the
  session the last session's list is shown, labelled at the close, from ``PATH`` (kept across restarts).
"""
from __future__ import annotations

from datetime import date, datetime
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable

from sqlalchemy import or_
from sqlmodel import Session, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

VOL_OI = 3.0  # a contract's volume today at least this many times its open interest
MIN_VOLUME = 500  # and at least this many contracts
TICKER_X = 2.0  # a ticker's call or put volume today at least this many times its usual full session
TICKER_MIN = 1000  # and at least this many contracts
HISTORY_SESSIONS = 20
MIN_HISTORY = 5
EXPIRIES = 3  # the nearest expiries read per name
# The ticker rule's expiries: the nearest two after the session's own day, on both sides of the comparison, so a same-day
# (0DTE) expiry the nightly snapshot may or may not list never makes today look busier than its history.
TICKER_EXPIRIES = 2
MAX_SYMBOLS = 12
PER_SYMBOL = 5  # contracts shown per name
MAX_ROWS = 20
REFRESH_S = 300  # a name is read again once its last read is this old
STALE_S = 900  # in the session, a name read longer ago than this is stale (three missed refreshes)
GAP_S = 30  # seconds between names in a pass
PATH = Path(__file__).resolve().parents[2] / "data" / "desk_unusual.json"
ALIASES = {"SPXW": "SPX"}

RULE = (f"Unusual: a contract that has traded at least {VOL_OI:g}× its open interest today, and at least {MIN_VOLUME:,} "
        f"contracts; or a ticker whose call or put volume so far today, on its nearest two expiries after today, is at least "
        f"{TICKER_X:g}× its average full day on the same expiries over its last {HISTORY_SESSIONS} recorded sessions, and "
        f"at least {TICKER_MIN:,} contracts. Only the nearest "
        f"{EXPIRIES} expiries of names you hold or watch are read, every few minutes in market hours. Open interest is "
        "last night's count. The chain does not say whether trades hit the bid or the ask, so no side is shown.")

_lock = threading.Lock()
_entries: dict[str, dict] | None = None  # by symbol: its latest reading
_running = False
_history_cache: dict[tuple[str, date], dict | None] = {}


# --------------------------------------------------------------------------- which names

def scope(db: Session) -> list[dict]:
    """His held underlyings, then his Watching list, without the names he does not follow: ``[{"symbol", "held"}]``.
    Raises when the not-followed setting cannot be read."""
    from app.engine import day_journal, desk_watch
    from app.engine.options_chain import SYMBOL
    from app.models import Account, Trade
    hidden = day_journal.not_following(db)
    hidden |= {_name(h) for h in hidden}  # Not following SPXW hides SPX too
    held = db.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id).where(Trade.status == "open")
                   .where(or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    held_names = [_name(t) for t in held]
    out: list[dict] = []
    for raw, name in [(t, _name(t)) for t in held] + [(s, _name(s)) for s in desk_watch.state(db)["symbols"]]:
        if (raw or "").strip().upper() in hidden:
            continue
        if name and SYMBOL.fullmatch(name) and name not in hidden and all(o["symbol"] != name for o in out):
            out.append({"symbol": name, "held": name in held_names})
    return out[:MAX_SYMBOLS]


def _name(raw: str | None) -> str:
    name = (raw or "").strip().upper()
    return ALIASES.get(name, name)


# --------------------------------------------------------------------------- the rules

def unusual_contracts(chains, root: str) -> list[dict]:
    """Every contract of ``root`` in ``chains`` that passes the volume-vs-open-interest rule, most traded first."""
    rows = []
    for chain in chains:
        for c in chain.contracts:
            if c.root != root or c.volume is None or c.open_interest is None or c.volume < MIN_VOLUME:
                continue
            if c.open_interest > 0 and c.volume < VOL_OI * c.open_interest:
                continue
            rows.append({"contract": c.symbol, "side": c.option_type, "strike": round(c.strike, 3),
                         "expiration": c.expiration.isoformat(), "volume": c.volume, "open_interest": c.open_interest,
                         "ratio": round(c.volume / c.open_interest, 1) if c.open_interest else None, "last": c.last})
    return sorted(rows, key=lambda r: (-r["volume"], r["expiration"], r["strike"]))


def side_totals(chains, root: str) -> dict[str, int | None]:
    """Call and put volume so far over ``chains``; None for a side any contract left unreported (never a partial sum)."""
    out: dict[str, int | None] = {}
    for side in ("call", "put"):
        volumes = [c.volume for chain in chains for c in chain.contracts if c.root == root and c.option_type == side]
        out[side] = sum(volumes) if volumes and None not in volumes else None
    return out


def ticker_flags(totals: dict[str, int | None], usual: dict | None) -> list[dict]:
    """The sides whose volume today passes the ticker rule against ``usual`` (``{"call", "put", "sessions"}``)."""
    if not usual:
        return []
    flags = []
    for side in ("call", "put"):
        today, avg = totals.get(side), usual.get(side)
        if today is None or not avg or today < TICKER_MIN:
            continue
        multiple = today / avg
        if multiple >= TICKER_X:
            flags.append({"side": side, "today": today, "usual": round(avg), "multiple": round(multiple, 1),
                          "sessions": usual["sessions"]})
    return flags


def history(db: Session, symbol: str, before: date, root: str) -> dict | None:
    """The average full-session call and put volume over each recorded session's nearest ``TICKER_EXPIRIES`` expiries
    after its own day, from the
    nightly snapshots: ``{"call", "put", "sessions"}``; None with fewer than ``MIN_HISTORY`` usable sessions."""
    from app.models import OptionChainSnapshot, OptionSnapshotDay
    days = db.exec(select(OptionSnapshotDay.session_date).where(
        OptionSnapshotDay.underlying == symbol, OptionSnapshotDay.status == "recorded", OptionSnapshotDay.session_date < before)
        .order_by(OptionSnapshotDay.session_date.desc()).limit(HISTORY_SESSIONS)).all()
    if len(days) < MIN_HISTORY:
        return None
    sums: dict[str, list[int]] = {"call": [], "put": []}
    for day in days:
        listed = sorted(e for e in db.exec(select(OptionChainSnapshot.expiration).where(
            OptionChainSnapshot.underlying == symbol, OptionChainSnapshot.session_date == day)).all() if e > day)[:TICKER_EXPIRIES]
        if not listed:
            continue
        blobs = db.exec(select(OptionChainSnapshot.data_json).where(
            OptionChainSnapshot.underlying == symbol, OptionChainSnapshot.session_date == day,
            OptionChainSnapshot.expiration.in_(listed))).all()
        totals = _snapshot_totals(blobs, root)
        for side in ("call", "put"):
            if totals.get(side) is not None:
                sums[side].append(totals[side])
    out: dict = {"sessions": min(len(sums["call"]), len(sums["put"]))}
    for side in ("call", "put"):
        out[side] = sum(sums[side]) / len(sums[side]) if len(sums[side]) >= MIN_HISTORY else None
    return out if out["call"] is not None or out["put"] is not None else None


def _snapshot_totals(blobs: list[str], root: str) -> dict[str, int | None]:
    volumes: dict[str, list] = {"C": [], "P": []}
    for blob in blobs:
        try:
            payload = json.loads(blob)
            cols = payload["columns"]
            i_root, i_type, i_vol = cols.index("root"), cols.index("type"), cols.index("volume")
            for row in payload["rows"]:
                if row[i_root] == root and row[i_type] in volumes:
                    volumes[row[i_type]].append(row[i_vol])
        except (KeyError, TypeError, ValueError, IndexError):
            return {"call": None, "put": None}
    return {name: (sum(v) if v and None not in v else None) for name, v in (("call", volumes["C"]), ("put", volumes["P"]))}


def evaluate(symbol: str, chains, fetched: float | None, day: date, usual: dict | None, issue: str | None) -> dict:
    """One name's reading: its unusual contracts (at most ``PER_SYMBOL``), its ticker flags and what could not be read."""
    from app.engine.options_positioning import primary_root
    root = primary_root(symbol)
    later = sorted((c for c in chains if c.expiration > day), key=lambda c: c.expiration)[:TICKER_EXPIRIES]
    complete = len(later) >= TICKER_EXPIRIES and issue is None
    totals = side_totals(later, root) if complete else {"call": None, "put": None}
    return {"symbol": symbol, "day": day.isoformat(), "read_at": int(fetched) if fetched is not None else None,
            "expirations": sorted(c.expiration.isoformat() for c in chains),
            "contracts": unusual_contracts(chains, root)[:PER_SYMBOL], "tickers": ticker_flags(totals, usual),
            "history": usual is not None, "partial": usual is not None and not complete, "issue": issue}


# --------------------------------------------------------------------------- reading

def _live_read(symbol: str) -> dict:
    from app.engine.options_feed import options_feed
    reads, issue = options_feed.chains(symbol, lambda live: live[:EXPIRIES], ttl=REFRESH_S)
    return {"chains": [r.value for r in reads], "fetched": min((r.fetched for r in reads), default=None), "issue": issue}


def _history_for(symbol: str, day: date, open_db: Callable[[], Session]) -> dict | None:
    key = (symbol, day)
    if key not in _history_cache:
        from app.engine.options_positioning import primary_root
        try:
            with open_db() as db:
                found = history(db, symbol, day, primary_root(symbol))
        except Exception:  # noqa: BLE001 -- no history is the contract rule alone, never a wrong average
            log.warning("Option volume history could not be read for %s", symbol, exc_info=True)
            return None
        with _lock:
            for old in [k for k in _history_cache if k[1] != day]:
                del _history_cache[old]
            _history_cache[key] = found
    return _history_cache[key]


def refresh(symbols: list[str], *, read: Callable[[str], dict] = _live_read, open_db: Callable[[], Session] | None = None,
            clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
            in_session: Callable[[float], bool] | None = None) -> None:
    """Read ``symbols`` one at a time, ``GAP_S`` apart, while the regular session lasts, keeping each reading."""
    if open_db is None:
        from app.database import engine
        open_db = lambda: Session(engine)  # noqa: E731
    in_session = in_session or (lambda now: _session(now)[0] == "regular")
    for index, symbol in enumerate(symbols):
        if index:
            sleep(GAP_S)
        now = clock()
        if not in_session(now):
            return
        day = datetime.fromtimestamp(now, ET).date()
        try:
            got = read(symbol)
        except Exception as exc:  # noqa: BLE001 -- one name's failure is its own grey line
            log.warning("Unusual options read failed for %s", symbol, exc_info=True)
            got = {"chains": [], "fetched": None, "issue": f"The option chain could not be read ({type(exc).__name__})."}
        chains, issue = got.get("chains") or [], got.get("issue")
        previous = _load().get(symbol)
        if not chains and previous and previous["day"] == day.isoformat() and previous.get("read_at"):
            entry = {**previous, "issue": issue or "The option chain could not be read just now."}  # keep its numbers, with their time
        else:
            entry = evaluate(symbol, chains, got.get("fetched"), day, _history_for(symbol, day, open_db) if chains else None,
                             issue if chains or issue else "The option chain could not be read.")
        with _lock:
            _load()[symbol] = entry
            snapshot = dict(_entries or {})
        _save(snapshot)


def _session(now: float) -> tuple[str, date]:
    from app.engine import desk_sparks
    day, phase, _hours, regular = desk_sparks._session(now)
    return ("regular" if phase == "regular" and regular is not None else phase), day


def _start(symbols: list[str], spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
    global _running
    with _lock:
        if _running:
            return
        _running = True

    def work():
        global _running
        try:
            refresh(symbols)
        except Exception:  # noqa: BLE001 -- a background pass has no caller to tell
            log.exception("Unusual options pass failed")
        finally:
            with _lock:
                _running = False
    try:
        (spawn or (lambda job: threading.Thread(target=job, daemon=True, name="desk-unusual").start()))(work)
    except RuntimeError:
        with _lock:
            _running = False


# --------------------------------------------------------------------------- the store

def _load() -> dict[str, dict]:
    global _entries
    if _entries is None:
        try:
            raw = json.loads(PATH.read_text())
            _entries = {k: v for k, v in raw.get("entries", {}).items() if isinstance(v, dict) and "day" in v}
        except (OSError, ValueError, AttributeError):
            _entries = {}
    return _entries


def _save(entries: dict[str, dict]) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "entries": entries}, separators=(",", ":")))
        os.replace(tmp, PATH)
    except OSError:
        log.warning("Unusual options could not be kept on disk", exc_info=True)


def reset() -> None:
    """Forget every reading in memory (tests)."""
    global _entries, _running
    with _lock:
        _entries, _running = None, False
        _history_cache.clear()


# --------------------------------------------------------------------------- the view

def _base(state: str, **more) -> dict:
    return {"state": state, "session": "closed", "label": None, "day": None, "rule": RULE, "rows": [], "tickers": [],
            "unread": [], "no_history": [], "partial": [], "stale": [], "held": [], "read_at": None, "message": None,
            "simulated": False, **more}


def view(db: Session, now: float | None = None, *, mode: str = "live", spawn=None) -> dict:
    """What ``GET /copilot/unusual`` returns. In the regular session, names not read in the last ``REFRESH_S`` seconds
    start a background pass (one at a time); the reply is what is kept now, never a provider wait."""
    now = time.time() if now is None else now
    if mode == "replay":
        return _base("unavailable", message="Replay reads no live quotes, so there is no unusual activity to show.")
    try:
        names = scope(db)
    except Exception:  # noqa: BLE001 -- not knowing what is hidden, show nothing rather than a hidden ticker
        log.warning("Unusual options scope could not be read", exc_info=True)
        db.rollback()
        return _base("unavailable", message="Which tickers you follow could not be read, so nothing is shown.")
    if mode == "fixture":
        from app.engine import day_journal
        if "NBIS" in day_journal.not_following(db):
            return _base("ok", label="at the close", simulated=True)
        return _fixture(any(n["symbol"] == "NBIS" and n["held"] for n in names))
    if not names:
        return _base("none", message="No held or watched names to read.")
    phase, today = _session(now)
    live = phase == "regular"
    with _lock:
        kept = {n["symbol"]: dict(e) for n in names if (e := _load().get(n["symbol"]))}
    if live:
        due = [n["symbol"] for n in names if (e := kept.get(n["symbol"])) is None or e["day"] != today.isoformat()
               or e.get("read_at") is None or now - e["read_at"] >= REFRESH_S]
        if due:
            _start(due, spawn)
        day = today.isoformat()
    else:
        day = max((e["day"] for e in kept.values() if e.get("read_at") is not None), default=None)
    shown = {s: e for s, e in kept.items() if e["day"] == day and e.get("read_at") is not None}
    held = {n["symbol"] for n in names if n["held"]}
    rows, tickers = [], []
    stale = [s for s, e in shown.items() if live and now - e["read_at"] > STALE_S]
    for name in names:
        entry = shown.get(name["symbol"])
        if entry is None:
            continue
        extra = {"symbol": name["symbol"], "held": name["held"], "read_at": entry["read_at"], "stale": name["symbol"] in stale}
        rows += [{**row, **extra} for row in entry["contracts"]]
        tickers += [{**flag, **extra} for flag in entry["tickers"]]
    rows.sort(key=lambda r: (r["stale"], -r["volume"]))
    out = _base("ok", session="open" if live else "closed", label="live" if live else ("at the close" if day else None),
                day=day, rows=rows[:MAX_ROWS], tickers=tickers,
                unread=[n["symbol"] for n in names if n["symbol"] not in shown],
                no_history=[s for s, e in shown.items() if not e.get("history")],
                partial=[s for s, e in shown.items() if e.get("partial")], stale=stale, held=sorted(held),
                read_at=max((e["read_at"] for e in shown.values()), default=None))
    if not live and day is None:
        out["message"] = "No reading from a market session yet; the list fills in while the desk is open in market hours."
    elif live and not shown:
        out["message"] = "Reading the option chains of your names; the list fills in over the next few minutes."
    return out


def _fixture(held: bool) -> dict:
    """SIMULATED: the copilot fixture's NBIS chains with a few invented heavy contracts (sandbox only)."""
    from dataclasses import replace
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    session = date.fromisoformat(SESSION)
    chains = simulated_chains("NBIS", 94.35, session)
    nearest = sorted(d for d in chains if d >= session)[:EXPIRIES]
    invented = {(nearest[0], "call", 105.0): 4210, (nearest[1], "put", 85.0): 3900, (nearest[2], "call", 110.0): 2100}
    picked = []
    for d in nearest:
        chain = chains[d]
        picked.append(replace(chain, contracts=tuple(
            replace(c, volume=invented.get((d, c.option_type, c.strike), c.volume)) for c in chain.contracts)))
    at = datetime.fromisoformat(AT.replace("Z", "+00:00")).timestamp()
    totals = side_totals([c for c in picked if c.expiration > session][:TICKER_EXPIRIES], "NBIS")
    usual = {"call": totals["call"] / 2.6 if totals["call"] else None, "put": None, "sessions": HISTORY_SESSIONS}  # invented
    entry = evaluate("NBIS", picked, at, session, usual, None)
    extra = {"symbol": "NBIS", "held": held, "read_at": entry["read_at"], "stale": False}
    return _base("ok", label="at the close", day=SESSION, simulated=True, read_at=entry["read_at"],
                 rows=[{**r, **extra} for r in entry["contracts"]], tickers=[{**f, **extra} for f in entry["tickers"]],
                 held=["NBIS"] if held else [])
