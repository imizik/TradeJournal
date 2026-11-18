"""The paper challenge (docs/copilot-lab.md § Paper challenge): a $10,000 paper run with a target and two loss limits
that bite, so paper trading carries real stakes.

- **The rules.** A run started as a challenge records one ``challenge`` event with its rules: a profit target of
  ``TARGET_PCT`` of the starting cash, a daily loss limit of ``DAILY_PCT`` of the start-of-day equity, and a maximum
  drawdown of ``MAX_DD_PCT`` from the run's peak equity.
- **Equity.** Cash plus every open position at the desk's newest prices (``paper_book.worth``), open P&L included. It is
  judged only when every open position has a price no older than ``MARK_FRESH_SECONDS`` (a flat account always: its
  equity is its cash). A stale or missing price is never read as zero; nothing is judged until the prices are fresh.
- **The day.** A New York calendar day. Its start-of-day equity is the first judged equity of that day (``dayopen``):
  the cash when flat, else the first fresh valuation after the open. Today's P&L is equity less that.
- **Daily lock.** Today's P&L at or below minus ``DAILY_PCT`` of the start-of-day equity records one ``lock`` for the
  day: every paper open (market, limit, the copilot's card, Telegram's Paper it) is refused until midnight New York of
  the next trading day, and working opening limits are canceled. Closes stay allowed, so he can always get flat.
- **Peak and failing.** The peak is the largest of the starting cash, every start-of-day equity, every recorded high
  (a ``peak`` event whenever a judged equity beats the recorded peak by more than ``PEAK_STEP``) and the equity being
  judged. Equity at or below the peak less ``MAX_DD_PCT`` fails the run (``fail``): no more opens on it, and no new run
  of any kind for ``COOLDOWN_DAYS`` days, so a reset is never a free way out.
- **Passing.** Equity at or above the starting cash plus ``TARGET_PCT`` without a drawdown fail passes the run
  (``pass``), a milestone: no more opens on it, and a new run can start at once. A daily lock does not stop a pass.
- **Record.** Every challenge run keeps its result on the scorecard: passed, failed or (replaced by a new run first)
  abandoned. All of it is ``paper_event`` rows keyed once each (``result:<run>`` holds the pass or the fail, so a run has
  one result), keyed to the run (``position_id`` is the run's id); nothing is edited and no column was added.

Reads the desk's kept prices; the paper runner's minute adds one quote read through the chart feed (its single-flight and
budget) only when a held position's price is stale. Never Robinhood.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, col, select

from app.engine import paper_book as pb
from app.engine.chart_math import ET
from app.models import PaperEvent, PaperRun

CHALLENGE_CASH = pb.DEFAULT_CASH
TARGET_PCT, DAILY_PCT, MAX_DD_PCT = 10.0, 3.0, 8.0
COOLDOWN_DAYS = 7
MARK_FRESH_SECONDS = 120  # a held position's price this recent counts for the limits
PEAK_STEP = 1.0  # dollars: a new high this far above the recorded peak is recorded
PING_SECONDS = 10 * 60  # a lock or fail recorded longer ago than this is not pinged
KINDS = ("challenge", "dayopen", "peak", "lock", "pass", "fail")
EPS = 0.005  # half a cent


def _day_words(stamp: float) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    return f"{moment.strftime('%a %b')} {moment.day}"


def _until_words(stamp: float) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    return f"{moment.strftime('%a %b')} {moment.day} {moment.strftime('%I:%M %p').lstrip('0')} ET"


def unlock_at(day: date) -> float:
    """Midnight New York of the first trading day after ``day`` (the market calendar; the clock hours when it is out)."""
    from app.engine import desk_sparks
    for ahead in range(1, 15):
        nxt = day + timedelta(days=ahead)
        noon = datetime.combine(nxt, time(12), ET).timestamp()
        if desk_sparks._session(noon)[3] is not None:
            return datetime.combine(nxt, time(0), ET).timestamp()
    return datetime.combine(day + timedelta(days=1), time(0), ET).timestamp()


def start(db: Session, run: PaperRun, now: float) -> None:
    """Record the challenge's rules on a new run (added to the caller's transaction)."""
    db.add(PaperEvent(run_id=run.id, position_id=run.id, kind="challenge", order_key=f"challenge:{run.id}",
                      effective_at=pb._utc(now), data_json=json.dumps(
                          {"target_pct": TARGET_PCT, "daily_pct": DAILY_PCT, "max_dd_pct": MAX_DD_PCT}, sort_keys=True)))


def cooldown_until(db: Session, now: float) -> float | None:
    """When a new run may start after the newest failed challenge, while that is still ahead."""
    newest = db.exec(select(PaperEvent).where(PaperEvent.kind == "fail").order_by(col(PaperEvent.effective_at).desc())).first()
    if newest is None:
        return None
    until = pb._epoch(newest.effective_at) + COOLDOWN_DAYS * 86400
    return until if now < until else None


def state(events: list[PaperEvent]) -> dict | None:
    """The challenge's recorded facts, or None when the run is not a challenge."""
    found = None
    days: dict[str, float] = {}
    locks: dict[str, dict] = {}
    peaks: list[float] = []
    result = None
    for e in events:
        if e.kind not in KINDS:
            continue
        data = json.loads(e.data_json)
        if e.kind == "challenge":
            found = data
        elif e.kind == "dayopen":
            days[data["day"]] = data["equity"]
        elif e.kind == "peak":
            peaks.append(data["equity"])
        elif e.kind == "lock":
            locks[data["day"]] = {**data, "key": e.order_key, "at": pb._epoch(e.effective_at)}
        else:
            result = {**data, "kind": e.kind, "at": pb._epoch(e.effective_at), "key": e.order_key}
    if found is None:
        return None
    return {"rules": found, "days": days, "locks": locks, "peaks": peaks, "result": result}


def equity(run: PaperRun, positions: list[dict], marks: dict) -> tuple[float | None, float | None]:
    """Cash plus every open position at ``marks`` (None when one has no price) and the oldest price's time."""
    open_ = [p for p in positions if p["status"] == "open"]
    cash = pb.account(run, positions)["cash"]
    values = [pb.worth(p, marks) for p in open_]
    at = min((v["at"] for v in values if v is not None), default=None)
    if any(v is None for v in values):
        return None, at
    return round(cash + sum(v["value"] for v in values), 2), at


def _legs(positions: list[dict]) -> list[str]:
    return sorted({leg["quote"] for p in positions if p["status"] == "open" for leg in p["legs"]})


def _store(db: Session, run: PaperRun, kind: str, key: str, at: float, data: dict) -> bool:
    return pb._store(db, run, run.id, kind, key, at, data)


def _end_opening_limits(db: Session, run: PaperRun, now: float, reason: str) -> None:
    for order in pb.orders(pb._events(db, run)):
        if order["status"] == "working" and order["side"] == "open":
            pb._store(db, run, uuid.UUID(order["id"]), "cancel", f"end:{order['id']}", now, {"reason": reason})
            pb._checks.pop(order["id"], None)


def evaluate(db: Session, run: PaperRun, now: float, marks: dict | None = None, record: bool = True) -> dict | None:
    """Judge the run's equity now against its limits (``record``: write the day's start, a new high, a lock, a fail or a
    pass; otherwise only read) and return what the desk shows, or None when the run is not a challenge."""
    events = pb._events(db, run)
    facts = state(events)
    if facts is None:
        return None
    positions = pb.fold(events)
    open_count = sum(1 for p in positions if p["status"] == "open")
    if marks is None:
        marks = pb._marks(_legs(positions))
    eq, prices_at = equity(run, positions, marks)
    fresh = eq is not None and (open_count == 0 or (prices_at is not None and now - prices_at <= MARK_FRESH_SECONDS))
    if fresh and facts["result"] is None and record:
        _judge(db, run, facts, eq, now)
        facts = state(pb._events(db, run))
    return summary(run, facts, now, eq, prices_at, fresh, open_count)


def _judge(db: Session, run: PaperRun, facts: dict, eq: float, now: float) -> None:
    rules, start_cash = facts["rules"], run.starting_cash
    day = pb._ny_day(now).isoformat()
    sod = facts["days"].get(day)
    if sod is None:
        sod = eq
        _store(db, run, "dayopen", f"dayopen:{run.id}:{day}", now, {"day": day, "equity": eq})
    recorded = max([start_cash, *facts["peaks"], *facts["days"].values(), sod])
    if eq > recorded + PEAK_STEP:
        _store(db, run, "peak", f"peak:{run.id}:{now:.0f}", now, {"equity": eq})
    peak = max(recorded, eq)
    floor = round(peak * (1 - rules["max_dd_pct"] / 100), 2)
    if eq <= floor + EPS:
        down = round((peak - eq) / peak * 100, 1)
        data = {"equity": eq, "peak": round(peak, 2), "floor": floor, "drawdown_pct": down,
                "pct": round((eq - start_cash) / start_cash * 100, 1),
                "reason": f"Equity {pb.usd(eq)} fell {down:.1f}% from the peak {pb.usd(peak)} (the limit is {rules['max_dd_pct']:g}%)."}
        if _store(db, run, "fail", f"result:{run.id}", now, data):
            _end_opening_limits(db, run, now, "The challenge failed.")
        return
    limit = round(sod * rules["daily_pct"] / 100, 2)
    today = round(eq - sod, 2)
    if day not in facts["locks"] and today <= -limit + EPS:
        data = {"day": day, "equity": eq, "start_of_day": sod, "pnl": today, "limit": limit,
                "until": unlock_at(pb._ny_day(now))}
        if _store(db, run, "lock", f"lock:{run.id}:{day}", now, data):
            _end_opening_limits(db, run, now, "The daily loss limit locked paper opens.")
    target = round(start_cash * (1 + rules["target_pct"] / 100), 2)
    if eq >= target - EPS:
        data = {"equity": eq, "peak": round(peak, 2), "pct": round((eq - start_cash) / start_cash * 100, 1),
                "reason": f"Equity {pb.usd(eq)} reached the {pb.usd(target)} target."}
        if _store(db, run, "pass", f"result:{run.id}", now, data):
            _end_opening_limits(db, run, now, "The challenge passed.")


def _active_lock(facts: dict, now: float) -> dict | None:
    """The lock in force now: one lasts to its unlock, past a weekend."""
    return next((lock for lock in sorted(facts["locks"].values(), key=lambda f: f["until"], reverse=True)
                 if now < lock["until"]), None)


def summary(run: PaperRun, facts: dict, now: float, eq: float | None, prices_at: float | None, fresh: bool,
            open_count: int) -> dict:
    rules, start_cash = facts["rules"], run.starting_cash
    sod = facts["days"].get(pb._ny_day(now).isoformat())
    live = [eq] if fresh and facts["result"] is None else []
    peak = max([start_cash, *facts["peaks"], *facts["days"].values(), *live])
    target = round(start_cash * (1 + rules["target_pct"] / 100), 2)
    floor = round(peak * (1 - rules["max_dd_pct"] / 100), 2)
    lock = _active_lock(facts, now)
    result = facts["result"]
    return {
        "rules": rules, "starting_cash": start_cash, "target_equity": target, "equity": eq, "prices_at": prices_at,
        "fresh": fresh, "open_positions": open_count, "start_of_day": sod,
        "today_pnl": round(eq - sod, 2) if eq is not None and sod is not None else None,
        "daily_limit": round(sod * rules["daily_pct"] / 100, 2) if sod is not None else None,
        "peak": round(peak, 2), "floor": floor,
        "to_target": round(target - eq, 2) if eq is not None else None,
        "to_floor": round(eq - floor, 2) if eq is not None else None,
        "lock": None if lock is None else {k: lock[k] for k in ("day", "pnl", "limit", "until", "equity", "start_of_day")},
        "result": None if result is None else {"kind": result["kind"], "at": result["at"], "equity": result["equity"],
                                               "pct": result["pct"], "reason": result["reason"],
                                               "next_run_at": result["at"] + COOLDOWN_DAYS * 86400 if result["kind"] == "fail" else None},
    }


def refusal(db: Session, run: PaperRun, now: float) -> str | None:
    """Why a paper open is refused now (a daily lock, a failed or passed challenge), or None."""
    facts = state(pb._events(db, run))
    if facts is None:
        return None
    result = facts["result"]
    if result is not None and result["kind"] == "fail":
        again = result["at"] + COOLDOWN_DAYS * 86400
        return (f"This challenge failed on {_day_words(result['at'])}: {result['reason']} No new paper opens; "
                f"closes still work. A new run can start {_until_words(again)}.")
    if result is not None:
        return f"This challenge passed on {_day_words(result['at'])}. Closes still work; start a new run to trade again."
    lock = _active_lock(facts, now)
    if lock is not None:
        return (f"Daily loss limit hit: today's paper P&L {pb.usd(lock['pnl'])} vs the −{pb.usd(lock['limit'])} limit. "
                f"Paper opens unlock {_until_words(lock['until'])}; closes still work.")
    return None


def reset_refusal(db: Session, now: float) -> str | None:
    """Why a new run cannot replace the current one now: a reset never lifts a daily lock (the 7-day cooldown after a
    fail is ``cooldown_until``'s)."""
    run = pb.current_run(db)
    if run is None:
        return None
    facts = state(pb._events(db, run))
    lock = None if facts is None or facts["result"] is not None else _active_lock(facts, now)
    if lock is None:
        return None
    return f"Today's daily loss limit locked this challenge: a new run can start {_until_words(lock['until'])}, when the lock lifts."


def guard(db: Session, now: float, record: bool = True) -> None:
    """Before a paper open: judge the current run (``record``: as the desk's read does) and refuse while it is locked,
    failed or passed. Raises PaperError (409)."""
    run = pb.current_run(db)
    if run is None:
        return
    if record:
        evaluate(db, run, now)
    reason = refusal(db, run, now)
    if reason:
        raise pb.PaperError(reason, 409)


def _quote_marks(symbols: list[str]) -> dict:
    """The legs' prices from one quote read, by the desk's own rule (``desk_ticks._row``): an option at its bid/ask
    midpoint (a no-bid option too), shares at the last trade. A price is stamped with the time it comes from: the
    quote's sides for a midpoint, the trade's time for a last trade (an old trade stays stale)."""
    from app.engine.desk_ticks import _OCC
    from app.engine.quotes import _calc_mid
    out = {}
    for name, quote in pb._live_quotes(symbols).items():
        bid, ask = quote.bid, quote.ask
        price, stamps = None, []
        if _OCC.match(name):
            if bid is not None and ask is not None and ask >= bid >= 0:
                price = _calc_mid(bid, ask)
                stamps = [t / 1000 for t in (quote.bid_date, quote.ask_date) if isinstance(t, (int, float))]
        if price is None:
            price = quote.last
            trade = getattr(quote, "trade_date", None)
            stamps = [trade / 1000] if isinstance(trade, (int, float)) else []
        if isinstance(price, (int, float)) and price > 0 and stamps:
            out[name] = {"last": round(float(price), 4), "at": min(stamps)}
    return out


def minute(db: Session, run: PaperRun, now: float) -> list[dict]:
    """The paper runner's minute in the regular session: judge the run, reading the held legs' quotes once when the
    desk's prices are stale, and return the pings still owed (``pings``)."""
    events = pb._events(db, run)
    facts = state(events)
    if facts is None:
        return []
    if facts["result"] is None:
        legs = _legs(pb.fold(events))
        marks = pb._marks(legs)
        stale = [s for s in legs if s not in marks or now - marks[s]["at"] > MARK_FRESH_SECONDS]
        if stale:
            try:
                marks = {**marks, **_quote_marks(stale)}
            except pb.PaperError:
                pass
        evaluate(db, run, now, marks=marks)
    return pings(db, run, now)


def _judged(db: Session, source: str) -> bool:
    """Whether the paper runner already put this ping to the notification policy (which answers "send" again for a
    source it sent, so the runner must not ask twice)."""
    from app.models import PhonePing
    return db.exec(select(PhonePing).where(PhonePing.sender == "paper", PhonePing.source_id == source)).first() is not None


def pings(db: Session, run: PaperRun, now: float) -> list[dict]:
    """A PAPER ping for a lock or a fail recorded in the last ``PING_SECONDS`` and not yet put to the notification
    policy: each once, whichever read recorded it (the runner's minute, the desk's read or an order's guard)."""
    facts = state(pb._events(db, run))
    if facts is None:
        return []
    out = []
    lock = facts["locks"].get(pb._ny_day(now).isoformat())
    if lock is not None and now - lock["at"] <= PING_SECONDS and not _judged(db, lock["key"]):
        out.append({"source": lock["key"], "symbol": None, "title": "PAPER · Daily loss limit hit, opens locked",
                    "body": (f"Paper, not real money. Today's paper P&L {pb.usd(lock['pnl'])} reached the "
                             f"−{pb.usd(lock['limit'])} daily limit. New paper opens are locked until "
                             f"{_until_words(lock['until'])}; closes still work.")})
    result = facts["result"]
    if result is not None and result["kind"] == "fail" and now - result["at"] <= PING_SECONDS and not _judged(db, result["key"]):
        out.append({"source": result["key"], "symbol": None, "title": "PAPER · Challenge failed",
                    "body": (f"Paper, not real money. {result['reason']} The run is over; a new one can start "
                             f"{_until_words(result['at'] + COOLDOWN_DAYS * 86400)}.")})
    return out


def record_of(db: Session, run: PaperRun, ended_at: float | None, realized: float) -> dict | None:
    """A run's challenge result for the scorecard: passed or failed (with its return at the result), abandoned when a
    newer run replaced it first (its closed P&L as the return), else running. None when it was not a challenge."""
    facts = state(pb._events(db, run))
    if facts is None:
        return None
    result = facts["result"]
    if result is not None:
        return {"result": "passed" if result["kind"] == "pass" else "failed", "at": result["at"], "pct": result["pct"]}
    if ended_at is not None:
        return {"result": "abandoned", "at": ended_at, "pct": round(realized / run.starting_cash * 100, 1)}
    return {"result": "running", "at": None, "pct": None}
