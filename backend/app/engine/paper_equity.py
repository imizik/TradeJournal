"""The paper account's value over time (docs/copilot-lab.md § Paper home): the series behind the Paper home's portfolio
graph (1D / 1W / 1M / All).

- **What a point is.** Cash plus every open position at the prices the paper runner judged with that minute: the same
  sum as the desk's ``paperValue`` and the challenge's equity (``paper_challenge.equity``: each leg's newest kept price,
  an option at its mark, times the multiplier and what is held). A held leg with no price makes the point ``None``,
  never a zero; ``prices_at`` is the oldest price's time, and a point whose prices were older than
  ``paper_challenge.MARK_FRESH_SECONDS`` is ``stale`` (the graph greys it with its time).
- **When.** Once a minute in the regular session, by the paper runner's minute (``paper_book.minute_pass``). A
  challenge run's point uses the prices its minute judged with (``paper_challenge.minute``), so the graph and the
  challenge's status line agree; any other run uses the desk's kept prices. No market-data call of its own.
- **Ranges.** ``1D`` the newest session day with points (a weekend shows Friday), against the last point before it;
  ``1W`` and ``1M`` the last 7 and 30 days, ``ALL`` the run. Each is thinned to the last point per bucket. ``base`` is
  what the change is measured from: the last point before the range, else the starting cash when the run began inside
  it, else the range's first point.

Insert-only ``paper_equity`` rows, one per run and minute; never touches fills, trades, accounts or Robinhood.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

from sqlmodel import Session, col, select

from app.engine import paper_book as pb
from app.engine.chart_math import ET
from app.models import PaperEquity, PaperRun

RANGES = {"1D": 60, "1W": 10 * 60, "1M": 60 * 60, "ALL": None}  # bucket seconds (ALL: sized to the run)
ALL_POINTS = 300  # about this many points across a long run


def _naive(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def record(db: Session, run: PaperRun, now: float, marks: dict | None = None) -> PaperEquity | None:
    """This minute's point for ``run`` at ``marks`` (default: the desk's kept prices), once per minute: a second call in
    the same minute keeps the first. Committed."""
    from app.engine import paper_challenge
    minute = now - now % 60
    if db.exec(select(PaperEquity.id).where(PaperEquity.run_id == run.id, PaperEquity.at >= _naive(minute),
                                             PaperEquity.at < _naive(minute + 60))).first() is not None:
        return None
    positions = pb.fold(pb._events(db, run))
    if marks is None:
        marks = pb._marks(paper_challenge._legs(positions))
    eq, prices_at = paper_challenge.equity(run, positions, marks)
    row = PaperEquity(run_id=run.id, at=_naive(now), equity=eq, cash=pb.account(run, positions)["cash"],
                      prices_at=None if prices_at is None else _naive(prices_at),
                      open_positions=sum(1 for p in positions if p["status"] == "open"))
    db.add(row)
    db.commit()
    return row


def _point(row: PaperEquity) -> dict:
    at = pb._epoch(row.at)
    prices_at = None if row.prices_at is None else pb._epoch(row.prices_at)
    from app.engine import paper_challenge
    stale = row.equity is not None and row.open_positions > 0 and (
        prices_at is None or at - prices_at > paper_challenge.MARK_FRESH_SECONDS)
    return {"at": at, "equity": row.equity, "prices_at": prices_at, "stale": stale}


def _thin(points: list[dict], bucket: int) -> list[dict]:
    """The last point of each ``bucket`` seconds (a 1D series is kept whole)."""
    if bucket <= 60:
        return points
    out: dict[int, dict] = {}
    for p in points:
        out[int(p["at"]) // bucket] = p
    return list(out.values())


def series(db: Session, span: str, now: float) -> dict:
    """The current run's points for ``span`` (``RANGES``), oldest first, with ``base`` (``{value, at}`` or None)."""
    if span not in RANGES:
        raise pb.PaperError(f"Range must be one of {', '.join(RANGES)}.", 422)
    run = pb.current_run(db)
    if run is None:
        return {"range": span, "run": None, "points": [], "base": None, "starting_cash": None}
    started = pb._epoch(run.started_at)
    rows = list(db.exec(select(PaperEquity).where(PaperEquity.run_id == run.id).order_by(col(PaperEquity.at))).all())
    if span == "1D":
        day = pb._ny_day(pb._epoch(rows[-1].at)) if rows else pb._ny_day(now)
        start = datetime.combine(day, time(0), ET).timestamp()
    elif span == "1W":
        start = now - 7 * 86400
    elif span == "1M":
        start = now - 30 * 86400
    else:
        start = started
    inside = [_point(r) for r in rows if pb._epoch(r.at) >= start]
    before = [r for r in rows if pb._epoch(r.at) < start and r.equity is not None]
    if before:
        base = {"value": before[-1].equity, "at": pb._epoch(before[-1].at)}
    elif started >= start or span == "ALL":
        base = {"value": run.starting_cash, "at": started}
    else:
        first = next((p for p in inside if p["equity"] is not None), None)
        base = None if first is None else {"value": first["equity"], "at": first["at"]}
    bucket = RANGES[span]
    if bucket is None:
        bucket = max(3600, int((now - started) / ALL_POINTS) // 3600 * 3600)
    return {"range": span, "run": {"id": str(run.id), "started_at": started}, "starting_cash": run.starting_cash,
            "points": _thin(inside, bucket), "base": base}

