"""Daily option positioning snapshots (Charts C4.3).

Once per trading session the recorder stores open interest and volume for every
contract of each in-scope underlying's expirations within 45 days. Scope
(decided 2026-09-30): SPY, QQQ and SPX, the underlyings of open positions, and
the first ten chart watchlist names; then (added 2026-10-02) the strategy
factory's core universe, so option positioning can later be tested as a factory
feature on the names the factory trades. Each expiration becomes one
`option_chain_snapshot` row with its contracts packed as JSON, and each
underlying gets one `option_snapshot_day` row per session: recorded, partial or
unavailable.

Open interest history cannot be fetched later, so:

- A snapshot is written only for the session in progress, inside the capture
  window, and never under an earlier date.
- A session that passed with no snapshot at all is marked unavailable by a
  later run, for the underlyings the previous session held. Nothing is ever
  filled in for it.
- A run resumes where an interrupted one stopped: stored expirations are
  skipped, and an underlying already recorded for the session costs no request.

The capture window opens 15 minutes after the regular close (ETF and index
options trade until 16:15) and ends at 20:00 New York, so volume is the whole
session's. Later is refused: SPX's overnight session opens at 20:15 and
Tradier's SPX volume then belongs to the next session (observed 2026-10-01: at
21:38, 728 SPX contracts that had traded that day showed volume 0). Weekends
and holidays record nothing, and an unavailable calendar records nothing rather
than guess.

Every read goes through `options_chain` with ``wait=True``, so the recorder
sleeps for the options budget (30 requests a minute) instead of exceeding it.
It runs as the ``options_snapshot`` job in the sync lane.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from typing import Callable, Protocol

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.engine.factory_rules import CORE_UNIVERSE
from app.engine.options_chain import SYMBOL, OptionsChainError, TradierOptions, options_chain
from app.engine.options_models import OptionChain
from app.models import Account, ChartSettingsRecord, OptionChainSnapshot, OptionSnapshotDay, Trade

FIXED = ("SPY", "QQQ", "SPX")
WATCHLIST_NAMES = 10
# Last in scope, so the names traded live are recorded first if the window runs short.
RESEARCH = CORE_UNIVERSE
HORIZON_DAYS = 45
SETTLE_MINUTES = 15
WINDOW_END = 20 * 60  # minutes of the New York day
LOOKBACK_DAYS = 31  # how far back a run looks for missed sessions
# Option roots journal trades can carry, mapped to the underlying Tradier lists them under.
ALIASES = {"SPXW": "SPX"}
COLUMNS = ["root", "type", "strike", "open_interest", "volume"]
FATAL = {"not_configured", "access_denied"}
NOT_REACHED = "Not reached yet; a run before 20:00 New York resumes here."
MISSED = "No snapshot was taken during this session. Open interest history cannot be backfilled."


class RecorderError(RuntimeError):
    """The run could not record everything it should have. Whatever it did record is kept."""


class Calendar(Protocol):
    def hours(self, day: date) -> dict | None: ...


def scope(db: Session, today: date) -> list[str]:
    """SPY, QQQ and SPX, then open positions' underlyings, then the first ten
    watchlist names, then the factory's core universe; each once, in that order."""
    names = list(FIXED)
    positions = db.exec(
        select(Trade.ticker, Trade.instrument_type, Trade.expiration)
        .join(Account, Account.id == Trade.account_id)
        .where(Trade.status == "open")
        # Webull is dormant by the user's choice (2026-09-24).
        .where(or_(Account.broker.is_(None), Account.broker != "webull"))
    ).all()
    for ticker, kind, expiration in positions:
        if kind == "option" and expiration is not None and expiration < today:
            continue  # expired, not yet closed by the journal
        names.append(ticker or "")
    settings = db.get(ChartSettingsRecord, "default")  # the row every browser shares
    try:
        watchlist = json.loads(settings.data_json).get("watchlist") if settings else None
    except (ValueError, AttributeError):
        watchlist = None
    if isinstance(watchlist, list):
        names += [name for name in watchlist if isinstance(name, str)][:WATCHLIST_NAMES]
    names += RESEARCH
    chosen: list[str] = []
    for name in names:
        symbol = name.strip().upper()
        symbol = ALIASES.get(symbol, symbol)
        if SYMBOL.fullmatch(symbol) and symbol not in chosen:
            chosen.append(symbol)
    return chosen


def record(
    db: Session,
    *,
    client: TradierOptions | None = None,
    calendar: Calendar | None = None,
    clock: Callable[[], datetime] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[int, str]:
    """Record this session's snapshots. Returns (expirations recorded, message);
    raises RecorderError after committing everything it could when something
    in scope is still missing."""
    client = client or options_chain
    if calendar is None:
        from app.engine.chart_calendar import chart_calendar as calendar
    clock = clock or (lambda: datetime.now(ET))
    now = clock().astimezone(ET)
    today = now.date()
    hours = calendar.hours(today)
    marked = _mark_missed(db, today, calendar)
    lead = f"Marked {marked} missed underlying-session(s) unavailable. " if marked else ""
    if hours is None:
        raise RecorderError(f"The market calendar is unavailable, so nothing was recorded for {today}; the next run retries. {lead}".strip())
    if hours["status"] != "open":
        return 0, f"{lead}Market closed on {today}; nothing to record."
    opens = hours["close"] + SETTLE_MINUTES
    if _minute(now) < opens:
        return 0, f"{lead}Snapshots are taken from {_clock(opens)} to {_clock(WINDOW_END)} New York, after the session's volume is complete."
    if _minute(now) >= WINDOW_END:
        return 0, f"{lead}After {_clock(WINDOW_END)} New York SPX volume belongs to the next session, so nothing was recorded for {today}."

    def capturing() -> bool:
        moment = clock().astimezone(ET)
        return moment.date() == today and _minute(moment) < WINDOW_END

    symbols = scope(db, today)
    for symbol in symbols:
        if db.get(OptionSnapshotDay, (today, symbol)) is None:
            # One at a time: a row another run wrote first stands without undoing the others.
            db.add(OptionSnapshotDay(session_date=today, underlying=symbol, status="partial", note=NOT_REACHED))
            _commit(db)

    stored, complete, problems = 0, 0, []
    for index, symbol in enumerate(symbols, 1):
        day = db.get(OptionSnapshotDay, (today, symbol))
        if day.status == "recorded":
            complete += 1
            continue
        if progress:
            progress(index - 1, len(symbols), f"{symbol}: {index} of {len(symbols)} underlyings")
        if not capturing():
            problems.append(f"the capture window closed before {symbol}")
            break
        try:
            listed = client.expirations(symbol, wait=True)
        except OptionsChainError as exc:
            if exc.code in FATAL:
                raise RecorderError(f"{exc} {lead}".strip()) from exc
            problems.append(f"{symbol} expirations ({exc})")
            _settle(db, day, None, set(), [f"expirations unavailable: {exc}"])
            continue
        wanted = [d for d in listed if today <= d <= today + timedelta(days=HORIZON_DAYS)]
        have = set(db.exec(select(OptionChainSnapshot.expiration).where(
            OptionChainSnapshot.session_date == today, OptionChainSnapshot.underlying == symbol)).all())
        failures = []
        for expiration in wanted:
            if expiration in have:
                continue
            if not capturing():
                failures.append("the capture window closed")
                break
            try:
                chain = client.chain(symbol, expiration, wait=True)
            except OptionsChainError as exc:
                if exc.code in FATAL:
                    raise RecorderError(f"{exc} {lead}".strip()) from exc
                failures.append(f"{expiration} ({exc})")
                continue
            if _store(db, today, symbol, chain):
                stored += 1
            have.add(expiration)
        day = db.get(OptionSnapshotDay, (today, symbol))
        _settle(db, day, wanted, have, failures)
        if day.status == "recorded":
            complete += 1
        else:
            problems.append(f"{symbol} " + (", ".join(failures) or "incomplete"))

    message = f"{lead}{today}: recorded {stored} expiration(s); {complete} of {len(symbols)} underlyings complete."
    if problems:
        shown = "; ".join(problems[:2]) + (f"; and {len(problems) - 2} more" if len(problems) > 2 else "")
        raise RecorderError(f"Options snapshot incomplete for {today}: {shown}. {message} A run before {_clock(WINDOW_END)} New York retries what is missing.")
    return stored, message


def _store(db: Session, session_date: date, underlying: str, chain: OptionChain) -> bool:
    rows = sorted(
        ([c.root, "C" if c.option_type == "call" else "P", c.strike, c.open_interest, c.volume] for c in chain.contracts),
        key=lambda row: (row[0], row[2], row[1]),
    )
    trades = [c.trade_time for c in chain.contracts if c.trade_time is not None]
    db.add(OptionChainSnapshot(
        session_date=session_date, underlying=underlying, expiration=chain.expiration, provider=chain.provider,
        captured_at=_naive_utc(chain.fetched_at), last_trade_at=_naive_utc(max(trades)) if trades else None,
        contracts=len(rows), data_json=json.dumps({"columns": COLUMNS, "rows": rows}, separators=(",", ":")),
    ))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()  # another run stored this expiration first; the snapshot is never replaced
        return False


def _settle(db: Session, day: OptionSnapshotDay, wanted: list[date] | None, have: set[date], failures: list[str]) -> None:
    if wanted is not None:
        day.expirations = len(wanted)
        day.recorded = len(have & set(wanted))
    complete = wanted is not None and day.recorded == day.expirations and not failures
    day.status = "recorded" if complete else "partial"
    if complete:
        day.note = None if wanted else "No listed expirations within 45 days."
    else:
        day.note = ("Missing: " + "; ".join(failures))[:2000] if failures else NOT_REACHED
    day.updated_at = datetime.utcnow()
    db.add(day)
    _commit(db)


def _mark_missed(db: Session, today: date, calendar: Calendar) -> int:
    """Mark every open session in the lookback with no rows at all as unavailable,
    for the underlyings the session before it held. Days the calendar cannot
    describe are left for a later run."""
    start = today - timedelta(days=LOOKBACK_DAYS)
    prior = db.exec(select(func.max(OptionSnapshotDay.session_date)).where(OptionSnapshotDay.session_date < start)).one()
    held: dict[date, set[str]] = defaultdict(set)
    for session_date, underlying in db.exec(
        select(OptionSnapshotDay.session_date, OptionSnapshotDay.underlying).where(
            OptionSnapshotDay.session_date >= (prior or start), OptionSnapshotDay.session_date < today)
    ).all():
        held[session_date].add(underlying)
    previous = held.get(prior, set()) if prior else set()
    marked = 0
    day = start
    while day < today:
        if held.get(day):
            previous = held[day]
        elif previous:
            hours = calendar.hours(day)
            if hours is not None and hours["status"] == "open":
                for underlying in sorted(previous):
                    db.add(OptionSnapshotDay(session_date=day, underlying=underlying, status="unavailable", note=MISSED))
                    marked += 1
        day += timedelta(days=1)
    if marked:
        _commit(db)
    return marked


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent run wrote the same status row; theirs stands


def _minute(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)
