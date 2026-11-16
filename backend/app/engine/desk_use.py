"""How he uses the copilot desk (docs/copilot-lab.md § How I use the desk): daily totals per desk piece, and which pieces
he folded away.

The desk counts quietly in the browser (``frontend/lib/deskUse.ts``): each piece's opens, taps and seconds on screen (in
15-second buckets), kept on the device and sent here at most once every five minutes. Only ids from the desk's own
catalog arrive: no keystrokes, no message text, no tickers. ``record`` adds them to ``desk_use_day`` (one row per New
York day, device size and piece). ``summary`` is what "How I use the desk" and the fold suggestion read: the last
``WINDOW_DAYS`` calendar days per piece, the last day each piece was used at all, and how many days had any desk use.

Folding is per device size (``desk`` from 768 px, ``phone`` below), saved as one named settings document
(``chart_settings`` row ``desk-folds``), so it follows him to another browser of the same size. Nothing is ever folded
here unasked: only his own tap saves a fold.

Nothing leaves this database; nothing here reads or writes fills, trades, accounts, P&L, quotes or Robinhood.
"""

import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.models import ChartSettingsRecord, DeskUseDay, utc_now_naive

ET = ZoneInfo("America/New_York")
WINDOW_DAYS = 14
SIZES = ("desk", "phone")
FOLDS_KEY = "desk-folds"
PIECE = re.compile(r"^[a-z][a-z0-9.\-]{0,39}$")
MAX_ROWS = 400  # one flush: days × pieces
MAX_FOLDED = 80
OLDEST_DAYS = 60  # counts kept on a device this long ago are still taken; older ones are dropped
MAX_COUNT = 10_000  # opens or taps for one piece in one day
MAX_SEEN = 86_400  # seconds in a day


class UseError(ValueError):
    status = 422


def today(now: datetime | None = None) -> date:
    return (now or datetime.now(ET)).astimezone(ET).date()


def _size(size: str) -> str:
    if size not in SIZES:
        raise UseError(f"size must be one of {', '.join(SIZES)}")
    return size


def _piece(piece: str) -> str:
    if not PIECE.match(piece):
        raise UseError(f"not a desk piece id: {piece[:40]!r}")
    return piece


def record(db: Session, size: str, rows: list[dict], now: datetime | None = None) -> dict:
    """Add one flush of counts. A day older than ``OLDEST_DAYS`` or after tomorrow is skipped (and counted in
    ``skipped``), never refused, so a device that held counts for a long time does not keep retrying them."""
    _size(size)
    if len(rows) > MAX_ROWS:
        raise UseError(f"at most {MAX_ROWS} rows in one save")
    on = today(now)
    added: dict[tuple[date, str], tuple[int, int, int]] = {}
    skipped = 0
    for row in rows:
        day = row["day"]
        if day < on - timedelta(days=OLDEST_DAYS) or day > on + timedelta(days=1):
            skipped += 1
            continue
        piece = _piece(row["piece"])
        opens, taps, seen = (max(0, min(int(row.get(k) or 0), cap)) for k, cap in
                             (("opens", MAX_COUNT), ("taps", MAX_COUNT), ("seen_s", MAX_SEEN)))
        if not (opens or taps or seen):
            continue
        was = added.get((day, piece), (0, 0, 0))
        added[(day, piece)] = (was[0] + opens, was[1] + taps, was[2] + seen)
    for attempt in range(2):
        try:
            for (day, piece), (opens, taps, seen) in added.items():
                found = db.exec(select(DeskUseDay).where(DeskUseDay.day == day, DeskUseDay.size == size,
                                                         DeskUseDay.piece == piece)).first()
                if found is None:
                    found = DeskUseDay(day=day, size=size, piece=piece)
                found.opens = min(found.opens + opens, MAX_COUNT)
                found.taps = min(found.taps + taps, MAX_COUNT)
                found.seen_s = min(found.seen_s + seen, MAX_SEEN)
                found.updated_at = utc_now_naive()
                db.add(found)
            db.commit()
            break
        except IntegrityError:  # another tab's save made the same day's row first: add onto it
            db.rollback()
            if attempt:
                raise
    return {"saved": len(added), "skipped": skipped}


def read_folds(db: Session) -> dict:
    row = db.get(ChartSettingsRecord, FOLDS_KEY)
    data = json.loads(row.data_json) if row else {}
    return {size: {"folded": list(data.get(size, {}).get("folded", [])),
                   "snoozed_until": data.get(size, {}).get("snoozed_until")} for size in SIZES}


def save_folds(db: Session, size: str, folded: list[str], snoozed_until: date | None) -> dict:
    """One device size's folds and the suggestion's snooze, as he set them; the other size is kept as it was."""
    _size(size)
    if len(folded) > MAX_FOLDED:
        raise UseError(f"at most {MAX_FOLDED} folded pieces")
    clean = sorted({_piece(p) for p in folded})
    data = read_folds(db)
    data[size] = {"folded": clean, "snoozed_until": snoozed_until.isoformat() if snoozed_until else None}
    row = db.get(ChartSettingsRecord, FOLDS_KEY) or ChartSettingsRecord(name=FOLDS_KEY, data_json="{}", revision=0)
    row.data_json = json.dumps(data, sort_keys=True)
    row.revision += 1
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return data[size]


def summary(db: Session, size: str, now: datetime | None = None) -> dict:
    """The last ``WINDOW_DAYS`` calendar days (today included) per piece, each piece's last day of use (an open or a
    tap, at any time), how many days had any desk use on this size, and this size's folds."""
    _size(size)
    on = today(now)
    start = on - timedelta(days=WINDOW_DAYS - 1)
    window = db.exec(
        select(DeskUseDay.piece, func.sum(DeskUseDay.opens), func.sum(DeskUseDay.taps), func.sum(DeskUseDay.seen_s))
        .where(DeskUseDay.size == size, DeskUseDay.day >= start, DeskUseDay.day <= on).group_by(DeskUseDay.piece)
    ).all()
    last = db.exec(
        select(DeskUseDay.piece, func.max(DeskUseDay.day))
        .where(DeskUseDay.size == size, (DeskUseDay.opens + DeskUseDay.taps) > 0).group_by(DeskUseDay.piece)
    ).all()
    days = db.exec(select(func.count(func.distinct(DeskUseDay.day))).where(DeskUseDay.size == size)).one()
    first = db.exec(select(func.min(DeskUseDay.day)).where(DeskUseDay.size == size)).one()
    pieces: dict[str, dict] = {}
    for piece, opens, taps, seen in window:
        pieces[piece] = {"opens": int(opens or 0), "taps": int(taps or 0), "seen_s": int(seen or 0), "last_used": None}
    for piece, day in last:
        pieces.setdefault(piece, {"opens": 0, "taps": 0, "seen_s": 0, "last_used": None})["last_used"] = day.isoformat()
    return {
        "size": size,
        "today": on.isoformat(),
        "window_days": WINDOW_DAYS,
        "window_start": start.isoformat(),
        "days_with_use": int(days or 0),
        "first_day": first.isoformat() if first else None,
        "pieces": pieces,
        "folds": read_folds(db)[size],
    }
