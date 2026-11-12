"""The desk's Watching list (docs/copilot-lab.md § The desk): the names the owner watches and does not hold.

The list of record is the Charts watchlist (the ``chart_settings`` row ``default``, its ``watchlist`` field, at most 30
symbols), so Charts and the desk show one list. The desk adds and removes there; a name removed on the desk is kept in
``watchRemoved`` so a later Robinhood sync does not bring it back, and ``watchImport`` keeps when the last import ran and
which of his lists it read. Both are top-level fields the Charts page does not know: its saves keep them (the settings
route never drops a field a save leaves out).

Robinhood is only read, through ``robinhood_read``'s two watchlist reads and the feed's sign-in, only on the owner's tap
(never on a schedule), at most ``1 + MAX_LISTS`` calls an import. Nothing is ever written to his Robinhood lists. List
names and emoji are third-party text: trimmed, shown as data, and never sent to a model (the copilot is told only the
watched symbols).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
import logging
import re
import threading
from typing import Callable

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.engine import robinhood_read as rh
from app.models import ChartSettingsRecord

log = logging.getLogger(__name__)

SETTINGS = "default"  # the Charts workspace's row (routers/charts.py)
SETTINGS_BYTES = 512_000  # the Charts route's own limit
MAX = 30  # the Charts watchlist's limit (frontend/lib/charts.ts sanitizeSettings, routers/charts.py workspace)
# What Charts shows before its settings are ever saved (frontend/lib/charts.ts DEFAULT_SETTINGS.watchlist): with no
# saved list both screens show the same names.
CHARTS_DEFAULT = ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"]
MAX_REMOVED = 300
MAX_LISTS = 10  # lists one import reads
MAX_ITEMS = 200  # items read from one list
LEVELS_EACH = 4
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
LIST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# Robinhood's item types the import skips, by the word the result line uses. Only ``instrument`` (a stock or ETF) is added.
SKIP_WORD = {"currency_pair": "crypto", "futures": "futures", "futures_product": "futures", "index": "index"}
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")

_import_lock = threading.Lock()


class Full(Exception):
    pass


class Busy(Exception):
    pass


# --------------------------------------------------------------------------- the store

def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _read(db: Session) -> tuple[ChartSettingsRecord | None, dict]:
    row = db.get(ChartSettingsRecord, SETTINGS)
    if row is None:
        return None, {}
    try:
        data = json.loads(row.data_json)
    except ValueError:
        data = {}
    return row, data if isinstance(data, dict) else {}


def _symbols(data: dict) -> list[str]:
    raw = data.get("watchlist")
    if not isinstance(raw, list):
        return list(CHARTS_DEFAULT)
    return list(dict.fromkeys(s for s in raw if isinstance(s, str) and SYMBOL.fullmatch(s)))[:MAX]


def _removed(data: dict) -> list[str]:
    raw = data.get("watchRemoved")
    return [s for s in raw if isinstance(s, str) and SYMBOL.fullmatch(s)] if isinstance(raw, list) else []


def state(db: Session) -> dict:
    """The watched symbols in the Charts order, the names removed on the desk, and the last import."""
    _row, data = _read(db)
    imported = data.get("watchImport") if isinstance(data.get("watchImport"), dict) else None
    return {"symbols": _symbols(data), "removed": _removed(data), "imported": imported}


def _save(db: Session, change: Callable[[dict], object]):
    """Apply ``change`` to the stored settings document and save it on top of the revision it read, as the Charts route
    does (a save on an older revision is refused); a save another device made in between is read again, three times."""
    for _ in range(3):
        db.expire_all()
        row, data = _read(db)
        data = {**data, "watchlist": _symbols(data)}
        outcome = change(data)
        text = json.dumps(data, separators=(",", ":"))
        if len(text.encode()) > SETTINGS_BYTES:
            raise Full("The chart settings are too large to save.")
        now = _now_naive()
        try:
            if row is None:
                db.add(ChartSettingsRecord(name=SETTINGS, data_json=text, revision=1, updated_at=now))
                db.commit()
                return outcome
            result = db.execute(update(ChartSettingsRecord).where(
                ChartSettingsRecord.name == SETTINGS, ChartSettingsRecord.revision == row.revision,
            ).values(data_json=text, revision=ChartSettingsRecord.revision + 1, updated_at=now))
            db.commit()
            if result.rowcount == 1:
                return outcome
        except IntegrityError:
            db.rollback()  # another save created the row first
    raise RuntimeError("the watchlist changed on another device three times; try again")


def add(db: Session, symbol: str) -> None:
    """Add a symbol by hand (already checked by the caller). Taking it back out of the removed names: a later sync may
    bring it again only because he chose it again."""
    def change(data: dict):
        listed = data["watchlist"]
        data["watchRemoved"] = [s for s in _removed(data) if s != symbol]
        if symbol in listed:
            return
        if len(listed) >= MAX:
            raise Full(f"The list holds {MAX} names; stop watching one first.")
        listed.append(symbol)
    _save(db, change)


def remove(db: Session, symbol: str) -> None:
    """Stop watching: out of the list, and remembered so a later Robinhood sync does not bring it back."""
    def change(data: dict):
        data["watchlist"] = [s for s in data["watchlist"] if s != symbol]
        data["watchRemoved"] = ([s for s in _removed(data) if s != symbol] + [symbol])[-MAX_REMOVED:]
    _save(db, change)


# --------------------------------------------------------------------------- what the desk shows

def _epoch(moment: datetime | None) -> int | None:
    return int(moment.replace(tzinfo=UTC).timestamp()) if moment else None


def view(db: Session, day) -> dict:
    """``GET /copilot/desk/watching``: the watched symbols he follows (the Charts order), each one's armed levels (a
    confirmed plan's entry or invalidation, or a chart alert) and a Radar setup card that fired today, with the Robinhood
    connection's state for the import. Database and file reads only: no provider call; prices come from the sparks read.
    A ticker set to Not following is left out; if that setting cannot be read the list is unavailable rather than risk
    showing one."""
    from app.engine import day_journal
    from app.engine.robinhood_book import feed
    from app.models import LevelAlert, RadarSetup
    held = state(db)
    hidden = day_journal.not_following(db)
    symbols = [s for s in held["symbols"] if s not in hidden]
    levels: dict[str, list[dict]] = {}
    setups: dict[str, dict] = {}
    if symbols:
        for alert in db.exec(select(LevelAlert).where(LevelAlert.state == "active", col(LevelAlert.symbol).in_(symbols))
                             .order_by(col(LevelAlert.armed_at).desc())).all():
            rows = levels.setdefault(alert.symbol, [])
            if len(rows) < LEVELS_EACH:
                rows.append({"price": alert.price, "role": alert.plan_role if alert.plan_role in ("entry", "invalidation") else None})
        for row in db.exec(select(RadarSetup).where(RadarSetup.session_date == day.isoformat(), col(RadarSetup.symbol).in_(symbols))
                           .order_by(col(RadarSetup.created_at).desc())).all():
            setups.setdefault(row.symbol, {"at": _epoch(row.created_at), "event_id": row.event_id})
    connection = "ready" if feed.signer() is not None else feed.view(kick=False)["state"]
    imported = held["imported"]
    return {"state": "ok", "symbols": symbols, "count": len(held["symbols"]), "max": MAX, "levels": levels, "setups": setups,
            "imported_at": imported.get("at") if imported else None, "robinhood": connection}


# --------------------------------------------------------------------------- his Robinhood lists (read only, on his tap)

def _text(value, limit: int) -> str:
    return CONTROL.sub("", str(value or "")).strip()[:limit]


def _offered(data: dict) -> tuple[list[dict], int]:
    """His own lists that hold stocks: (each one's id, name, emoji and size; how many lists were not offered: curated
    Robinhood lists he follows and the options watchlist, which the items read rejects)."""
    rows = data.get("watchlists") if isinstance(data, dict) else None
    lists, other = [], 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        allowed = row.get("allowed_object_types")
        options_only = isinstance(allowed, list) and allowed and all(a == "option_strategy" for a in allowed)
        list_id = str(row.get("id") or "")
        if row.get("owner_type") != "custom" or options_only or not LIST_ID.fullmatch(list_id):
            other += 1
            continue
        try:
            size = max(0, int(row.get("item_count") or 0))
        except (TypeError, ValueError):
            size = 0
        lists.append({"id": list_id, "name": _text(row.get("display_name"), 40) or "Untitled list",
                      "emoji": _text(row.get("icon_emoji"), 8), "count": size})
    return lists, other


def _connection():
    from app.engine.robinhood_book import feed
    sign = feed.signer()
    return sign, ("ready" if sign is not None else feed.view(kick=False)["state"])


def robinhood_lists(db: Session) -> dict:
    """``GET /copilot/desk/watching/robinhood``: his own lists by name with their sizes, his custom lists ticked (after an
    import: the ones he chose then, and any list made since). One call. Off, signed out or expired: says so, no call."""
    sign, connection = _connection()
    if sign is None:
        return {"state": connection, "lists": [], "not_offered": 0}
    try:
        lists, other = _offered(rh.Reader(sign, max_calls=1).get_watchlists())
    except rh.ReadError as exc:
        log.warning("Robinhood watchlists could not be read (%s)", exc.kind)
        return {"state": "expired" if exc.kind == "expired" else "unavailable", "lists": [], "not_offered": 0}
    before = state(db)["imported"] or {}
    chose, seen = set(before.get("lists") or []), set(before.get("seen") or [])
    for row in lists:
        row["ticked"] = row["id"] in chose or row["id"] not in seen
    return {"state": "ok", "lists": lists, "not_offered": other}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(result: dict) -> str:
    """"12 added, 4 skipped: crypto": facts and counts only."""
    parts = [f"{len(result['added'])} added"]
    skipped = result["skipped"]
    if skipped:
        total = sum(skipped.values())
        kinds = ", ".join(word if len(skipped) == 1 else f"{n} {word}" for word, n in sorted(skipped.items(), key=lambda kv: -kv[1]))
        parts.append(f"{total} skipped: {kinds}")
    if result["already"]:
        parts.append(f"{result['already']} already watched")
    if result["removed"]:
        parts.append(f"{result['removed']} you stopped watching stay off")
    if result["full"]:
        parts.append(f"{result['full']} not added: the list holds {MAX}")
    if result["failed"]:
        parts.append(f"{_plural(result['failed'], 'list')} could not be read")
    return ", ".join(parts)


def import_lists(db: Session, chosen: list[str]) -> dict:
    """``POST /copilot/desk/watching/robinhood``: read the chosen lists (only his own stock lists, checked against a fresh
    read of his lists, at most ``MAX_LISTS``) and add their stocks and ETFs to the watchlist. Crypto pairs, futures and
    indexes are skipped and counted; a name he stopped watching on the desk is not brought back; nothing is written to
    Robinhood. One import at a time."""
    if not _import_lock.acquire(blocking=False):
        raise Busy("An import is already reading.")
    try:
        sign, connection = _connection()
        if sign is None:
            return {"state": connection}
        wanted = list(dict.fromkeys(i for i in chosen if isinstance(i, str)))
        reader = rh.Reader(sign, max_calls=1 + MAX_LISTS)
        try:
            offered, _other = _offered(reader.get_watchlists())
        except rh.ReadError as exc:
            log.warning("Robinhood watchlists could not be read (%s)", exc.kind)
            return {"state": "expired" if exc.kind == "expired" else "unavailable"}
        picks = [row for row in offered if row["id"] in wanted][:MAX_LISTS]
        found: list[str] = []
        skipped: Counter = Counter()
        failed = 0
        for row in picks:
            try:
                data = reader.get_watchlist_items(row["id"])
            except rh.ReadError as exc:
                if exc.kind in ("expired", "signed_out"):
                    return {"state": "expired"}
                log.warning("a Robinhood watchlist could not be read (%s)", exc.kind)
                failed += 1
                continue
            items = data.get("items") if isinstance(data.get("items"), list) else []
            for item in items[:MAX_ITEMS]:
                if not isinstance(item, dict):
                    continue
                kind, symbol = item.get("object_type"), _text(item.get("symbol"), 16).upper()
                if kind == "instrument" and SYMBOL.fullmatch(symbol):
                    found.append(symbol)
                else:
                    skipped[SKIP_WORD.get(kind, "other")] += 1

        def change(stored: dict) -> dict:
            listed, removed = stored["watchlist"], set(_removed(stored))
            out = {"added": [], "already": 0, "removed": 0, "full": 0}
            for symbol in dict.fromkeys(found):
                if symbol in listed:
                    out["already"] += 1
                elif symbol in removed:
                    out["removed"] += 1
                elif len(listed) >= MAX:
                    out["full"] += 1
                else:
                    listed.append(symbol)
                    out["added"].append(symbol)
            stored["watchImport"] = {"at": datetime.now(UTC).isoformat(timespec="seconds"),
                                     "lists": [row["id"] for row in picks], "seen": [row["id"] for row in offered]}
            return out
        result = {"state": "ok", **_save(db, change), "skipped": dict(skipped), "failed": failed, "lists": len(picks)}
        result["line"] = summary(result)
        return result
    finally:
        _import_lock.release()


# --------------------------------------------------------------------------- adding by hand

def known(db: Session, symbol: str) -> bool | None:
    """Whether ``symbol`` is a ticker: Radar's universe and his traded tickers first (no call), else one quote read that
    must return a price. None when that read failed (not known either way)."""
    from app.engine import spoken_tickers
    from app.engine.chart_feed import chart_feed
    if symbol in spoken_tickers.known_symbols(spoken_tickers.traded(db)):
        return True
    try:
        rows, _stamp, issue = chart_feed.quote_rows([symbol])
    except Exception as exc:  # noqa: BLE001 - an unreachable provider is "could not check", not "unknown"
        log.warning("watchlist add: the quote read failed (%s)", type(exc).__name__)
        return None
    if any(r.get("symbol") == symbol and r.get("last") is not None for r in rows):
        return True
    return None if issue and not rows else False


def watched_line(db: Session) -> str | None:
    """The copilot's one line: the symbols on his saved watchlist that he follows, no prices. None when there are none
    (or the list was never saved: Charts' starting names are not his picks)."""
    from app.engine import day_journal
    _row, data = _read(db)
    if not isinstance(data.get("watchlist"), list):
        return None
    hidden = day_journal.quiet(db)
    symbols = [s for s in _symbols(data) if s not in hidden]
    return ", ".join(symbols) if symbols else None
