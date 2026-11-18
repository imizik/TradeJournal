"""What's working (docs/copilot-lab.md § What's working): where his money comes from and where it leaks, from his closed
real trades and his closed paper trades, kept apart. Read only: the journal's ``trade`` rows and the paper book's events,
folded by ``paper_book.fold``; no quote, no Robinhood, no outside service.

Each side groups its closed trades into plain-word buckets (call / put / shares; entry time; hold length; days to expiry
at entry; option type with entry time; and, for paper only, whose idea it was and whether his rules were followed) and
reports, per bucket, trades, wins, losses, total and average dollars and win rate.

The money is the journal's own: a real trade is a FIFO ``trade`` row as the journal reconstructs it, and its dollars are
its ``realized_pnl`` (premium ×100, fees and signs already applied), summed exactly as ``/stats`` sums them (closed or
expired rows with a P&L; a win is above zero and every other priced trade a loss, as ``/stats`` counts them). Webull is
left out (dormant by the owner's choice), as the paper scorecard's real side leaves it out. A paper trade is a fully
closed paper position, its dollars ``realized`` from the fold. Journal times are New York wall clocks; paper times are
epochs read in New York. A bucket of fewer than ``MIN_TRADES`` trades is too few to judge and never a verdict; a fact
that is missing (no P&L, no close time, no expiry, no rules check) stays missing and is counted, never read as zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from sqlmodel import Session, col, select

from app.engine.chart_math import ET

MIN_TRADES = 5
WINDOW_DAYS = 30
TOP = 3

TIMES = ("Before 10:00", "10:00–10:30", "10:30–12:00", "12:00–14:00", "After 14:00")
HOLDS = ("Same day", "Overnight", "Multi-day")
DTES = ("0–1 days", "2–7 days", "8–30 days", "Over 30 days")
KINDS = ("Calls", "Puts", "Shares", "Call spreads", "Put spreads")
SOURCES = {"mine": "My ideas", "copilot": "Copilot's ideas", "radar": "Radar's ideas", "scanner": "Scanner's ideas"}
RULES = {"followed": "Rules followed", "broken": "Rules broken"}
DIMENSIONS = ("kind", "entry_time", "hold", "dte", "kind_time", "source", "rules")


def _cents(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def entry_time(moment: datetime) -> str:
    """The entry-time bucket of a New York wall clock (before 10:00 includes the pre-market; 14:00 on is "After 14:00")."""
    minute = moment.hour * 60 + moment.minute
    for end, label in ((600, TIMES[0]), (630, TIMES[1]), (720, TIMES[2]), (840, TIMES[3])):
        if minute < end:
            return label
    return TIMES[4]


def _weekdays_between(opened: date, closed: date) -> int:
    """Weekdays after ``opened`` up to and including ``closed`` (holidays are not known here)."""
    days, step = 0, opened
    while step < closed:
        step += timedelta(days=1)
        days += step.weekday() < 5
    return days


def hold(opened: datetime, closed: datetime | None) -> str | None:
    """Same day (closed on the New York day it opened), overnight (closed the next weekday) or multi-day; None unknown."""
    if closed is None or closed < opened:
        return None
    nights = _weekdays_between(opened.date(), closed.date())
    return HOLDS[0] if closed.date() == opened.date() else HOLDS[1] if nights <= 1 else HOLDS[2]


def dte(opened: datetime, expiry: date | None) -> str | None:
    """Calendar days from the New York entry day to the expiration, bucketed; None when the expiry is unknown."""
    if expiry is None:
        return None
    days = (expiry - opened.date()).days
    if days < 0:
        return None
    return DTES[0] if days <= 1 else DTES[1] if days <= 7 else DTES[2] if days <= 30 else DTES[3]


def kind_time(kind: str, time_label: str) -> str:
    """"Puts before 10:00", "Calls 10:00–10:30", "Shares after 14:00"."""
    return f"{kind} {time_label[0].lower() + time_label[1:] if time_label[0].isalpha() else time_label}"


# --------------------------------------------------------------------------- one side's rows

def _row(*, pnl: Decimal, opened: datetime, closed: datetime | None, kind: str, expiry: date | None, option: bool,
         source: str | None = None, rules: str | None = None) -> dict:
    """One closed trade, as the buckets read it: ``opened``/``closed`` New York wall clocks."""
    when = entry_time(opened)
    return {"pnl": pnl, "closed": closed, "labels": {
        "kind": kind, "entry_time": when, "hold": hold(opened, closed), "kind_time": kind_time(kind, when),
        "dte": dte(opened, expiry) if option else "n/a", "source": source, "rules": rules}}


def real_rows(db: Session) -> tuple[list[dict], list[datetime | None]]:
    """His closed real trades (Webull left out), and the close times of closed ones with no P&L (missing, never zero)."""
    from app.ai.copilot_book import _not_webull
    from app.engine.analytics import wall_time
    from app.models import Account, Trade
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id).where(_not_webull())
                     .where(col(Trade.status).in_(("closed", "expired")))).all()
    rows, unpriced = [], []
    for t in trades:
        if t.realized_pnl is None:
            unpriced.append(wall_time(t.closed_at) if t.closed_at else None)
            continue
        option = t.instrument_type == "option"
        kind = "Shares" if not option else "Calls" if t.option_type == "call" else "Puts" if t.option_type == "put" else None
        rows.append(_row(pnl=Decimal(str(t.realized_pnl)), opened=wall_time(t.opened_at),
                         closed=wall_time(t.closed_at) if t.closed_at else None, kind=kind or "Options (type unknown)",
                         expiry=t.expiration, option=option))
    return rows, unpriced


def paper_rows(db: Session) -> list[dict]:
    """His fully closed paper positions across every live paper run (each run folded on its own)."""
    from app.engine import paper_book, trading_rules
    from app.models import PaperEvent, PaperRun
    runs = db.exec(select(PaperRun.id).where(PaperRun.kind == "live")).all()
    rows = []
    for run_id in runs:
        events = list(db.exec(select(PaperEvent).where(PaperEvent.run_id == run_id)
                              .order_by(col(PaperEvent.effective_at), col(PaperEvent.recorded_at), col(PaperEvent.id))).all())
        for p in paper_book.fold(events):
            if p["status"] == "open" or p.get("closed_at") is None:
                continue
            opened = datetime.fromtimestamp(p["opened_at"], ET).replace(tzinfo=None)
            closed = datetime.fromtimestamp(p["closed_at"], ET).replace(tzinfo=None)
            instrument, side = p.get("instrument"), p.get("option_type")
            word = "Call" if side == "call" else "Put"
            kind = "Shares" if instrument == "stock" else f"{word}s" if instrument == "option" else f"{word} spreads"
            expiry = date.fromisoformat(p["expiry"]) if p.get("expiry") else None
            rows.append(_row(pnl=Decimal(str(p["realized"])), opened=opened, closed=closed, kind=kind, expiry=expiry,
                             option=instrument != "stock", source=p.get("source") or "mine",
                             rules=trading_rules.outcome(p.get("rules"))))
    return rows


# --------------------------------------------------------------------------- the buckets

def bucket(label: str, pnls: list[Decimal]) -> dict:
    wins = sum(1 for v in pnls if v > 0)
    total = sum(pnls, Decimal(0))
    n = len(pnls)
    return {"label": label, "trades": n, "wins": wins, "losses": n - wins, "pnl": _cents(total),
            "avg_pnl": _cents(total / n) if n else None, "win_rate": round(wins / n * 100, 1) if n else None,
            "judged": n >= MIN_TRADES}


def _order(dimension: str) -> tuple[str, ...]:
    return {"kind": KINDS, "entry_time": TIMES, "hold": HOLDS, "dte": DTES, "source": tuple(SOURCES.values()),
            "rules": tuple(RULES.values())}.get(dimension, ())


def side(rows: Iterable[dict], *, paper: bool, unpriced: int = 0) -> dict:
    """One side's totals, buckets per dimension, the facts that were missing, and its top 3 making and losing buckets."""
    rows = list(rows)
    groups: dict[str, dict[str, list[Decimal]]] = {d: defaultdict(list) for d in DIMENSIONS}
    missing = {"pnl": unpriced, "hold": 0, "dte": 0, "rules": 0}
    for r in rows:
        for d, value in r["labels"].items():
            if d in ("source", "rules") and not paper:
                continue
            if d == "rules":
                value = RULES.get(value) if value else None
            elif d == "source":
                value = SOURCES.get(value, value)
            if value is None:
                missing[d] += 1
                continue
            if value == "n/a":
                continue
            groups[d][value].append(r["pnl"])
    dims = {}
    for d in DIMENSIONS:
        if d in ("source", "rules") and not paper:
            continue
        order = _order(d)
        labels = sorted(groups[d], key=lambda k: (order.index(k) if k in order else len(order), k))
        dims[d] = [bucket(k, groups[d][k]) for k in labels]
    if not paper:
        missing.pop("rules")
    judged = [b | {"dimension": d} for d, bs in dims.items() for b in bs if b["judged"]]
    # Ties go to the narrower bucket (option type with entry time first), then by name.
    rank = {d: i for i, d in enumerate(("kind_time", "kind", "entry_time", "hold", "dte", "source", "rules"))}
    making = sorted((b for b in judged if b["pnl"] > 0), key=lambda b: (-b["pnl"], rank[b["dimension"]], b["label"]))[:TOP]
    losing = sorted((b for b in judged if b["pnl"] < 0), key=lambda b: (b["pnl"], rank[b["dimension"]], b["label"]))[:TOP]
    return {**bucket("All", [r["pnl"] for r in rows]), "missing": missing, "dimensions": dims,
            "making": making, "losing": losing}


def _window(rows: list[dict], since: datetime | None) -> tuple[list[dict], int]:
    if since is None:
        return rows, 0
    kept = [r for r in rows if r["closed"] is not None and r["closed"] >= since]
    return kept, sum(1 for r in rows if r["closed"] is None)


def report(db: Session, now: float) -> dict:
    """Both sides over the last ``WINDOW_DAYS`` days (by New York close time) and all time."""
    real, unpriced = real_rows(db)
    paper = paper_rows(db)
    wall_now = datetime.fromtimestamp(now, ET).replace(tzinfo=None)
    since = wall_now - timedelta(days=WINDOW_DAYS)
    out = {"as_of": now, "min_trades": MIN_TRADES, "window_days": WINDOW_DAYS, "windows": {}}
    for name, start in (("recent", since), ("all", None)):
        r, r_undated = _window(real, start)
        p, _ = _window(paper, start)
        gaps = len(unpriced) if start is None else sum(1 for c in unpriced if c is not None and c >= start)
        real_side = side(r, paper=False, unpriced=gaps)
        real_side["missing"]["undated"] = r_undated
        out["windows"][name] = {"real": real_side, "paper": side(p, paper=True)}
    return out


# --------------------------------------------------------------------------- the ticket's line and the review's line

def paper_record(db: Session, option_type: str, now: float) -> dict | None:
    """All-time paper record for the order being built: its option type in the entry-time bucket of ``now`` (New York).
    None when paper has no closed trade in that bucket."""
    kind = {"call": "Calls", "put": "Puts"}.get(option_type)
    if kind is None:
        return None
    label = kind_time(kind, entry_time(datetime.fromtimestamp(now, ET)))
    pnls = [r["pnl"] for r in paper_rows(db) if r["labels"]["kind_time"] == label]
    if not pnls:
        return None
    b = bucket(label, pnls)
    return {"label": label[0].lower() + label[1:], "wins": b["wins"], "losses": b["losses"], "pnl": b["pnl"],
            "trades": b["trades"]}


_TRY = {
    "kind": lambda k: f"no {k.lower()}" if k != "Shares" else "no share trades",
    "entry_time": lambda k: {"Before 10:00": "no entries before 10:00", "After 14:00": "no entries after 14:00"}.get(
        k, f"no entries between {k.replace('–', ' and ')}"),
    "hold": lambda k: {"Same day": "no same-day round trips", "Overnight": "no overnight holds: close the same day",
                       "Multi-day": "no holds past one night"}[k],
    "dte": lambda k: f"no options with {k} to expiry",
    "kind_time": lambda k: f"no {k[0].lower() + k[1:]}",
}


def leak_line(db: Session, now: float) -> str:
    """The single biggest leak in his last ``WINDOW_DAYS`` days of real trades with enough sample, as one change to try
    on paper next week. It suggests; it never changes a rule or a strategy book."""
    recent = report(db, now)["windows"]["recent"]["real"]
    worst = recent["losing"][0] if recent["losing"] else None
    if worst is None:
        return (f"Biggest leak: none with {MIN_TRADES}+ real trades in the last {WINDOW_DAYS} days, "
                "so nothing to try on paper from it.")
    change = _TRY[worst["dimension"]](worst["label"])
    money = f"{'-' if worst['pnl'] < 0 else ''}${abs(worst['pnl']):,.2f}"
    return (f"Try: {change} next week, on paper. (Biggest real leak, last {WINDOW_DAYS} days: {worst['label']}, "
            f"{worst['trades']} trades, {worst['wins']}W {worst['losses']}L, {money}.)")
