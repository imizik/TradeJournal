"""Monitor Jo's explicit price plans using the existing selected-stock pass.

No extra model runs, email tasks, options calls, broker actions or paper fills.
The immutable wake store is authoritative; public status is a derived projection.
"""

from datetime import UTC, datetime
import fcntl
import logging
import math
import os
from pathlib import Path

from sqlmodel import Session

from app.engine import ntfy, scanner_settings
from app.engine.market_watch_wakes import MarketWatchRunner, MarketWatchWakeStore
from conditional_plan_common import (
    FRESH_SECONDS,
    TERMINAL,
    price,
    publish,
    read_json,
    validate_cancel,
    validate_plan,
)
from market_watch_common import parse_time, seal
from stock_watch_common import ET, stamp

log = logging.getLogger(__name__)
DELIVERY = {"max_attempts": 3, "retry_seconds": 60}


def enabled():
    return os.environ.get("CONDITIONAL_PLAN_ENABLED", "").lower() == "true"


def checked_bars(rows, observed, now):
    """Refuse malformed/duplicate completed bars; ignore bars still forming."""
    if (
        not math.isfinite(observed)
        or not 0 <= now.timestamp() - observed <= FRESH_SECONDS
    ):
        raise ValueError("stale_source")
    completed = []
    for b in rows:
        if type(b["time"]) not in (int, float) or type(b["end_time"]) not in (
            int,
            float,
        ):
            raise ValueError("invalid_bar")
        if b["end_time"] > min(observed, now.timestamp()):
            continue
        if (
            not math.isfinite(b["time"])
            or b["time"] % 60
            or b["end_time"] != b["time"] + 60
        ):
            raise ValueError("invalid_bar")
        for k in ("open", "high", "low", "close"):
            price(b[k])
        if (
            not b["low"]
            <= min(b["open"], b["close"])
            <= max(b["open"], b["close"])
            <= b["high"]
        ):
            raise ValueError("invalid_bar")
        completed.append(b)
    completed.sort(key=lambda b: b["time"])
    if not completed or now.timestamp() - completed[-1]["end_time"] > FRESH_SECONDS:
        raise ValueError("stale_bars")
    if len({b["time"] for b in completed}) != len(completed):
        raise ValueError("duplicate_bars")
    return completed


class PlanMonitor:
    def __init__(
        self,
        store,
        directory,
        outbox,
        *,
        clock=lambda: datetime.now(UTC),
        push=ntfy.publish,
    ):
        self.store, self.directory, self.outbox = store, Path(directory), Path(outbox)
        self.clock, self.push = clock, push
        self.runner = MarketWatchRunner(store, directory, clock=clock, push=push)

    def events(self, plan):
        return [
            e
            for e in self.store.records("plan_event", plan["session_date"])
            if e["plan_id"] == plan["plan_id"]
        ]

    def event(self, plan, state, reason, *, bar=None, occurred=None):
        now = self.clock()
        event = seal(
            {
                "event_id": f"{plan['plan_id']}:{state}",
                "plan_id": plan["plan_id"],
                "plan_sha256": plan["content_sha256"],
                "session_date": plan["session_date"],
                "state": state,
                "reason": reason,
                "bar": bar,
                "occurred_at": stamp(occurred or now),
                "created_at": stamp(now),
            }
        )
        self.store.append(
            "plan_event", event, ident=event["event_id"], ref=plan["plan_id"]
        )

    def ingest(self):
        plans = {p["plan_id"]: p for p in self.store.records("plan")}
        for path in sorted(self.outbox.glob("conditional-plan-cpl_*.json")):
            try:
                p = validate_plan(read_json(path))
                if (
                    path.name != f"conditional-plan-{p['plan_id']}.json"
                    or parse_time(p["created_at"]) > self.clock()
                ):
                    raise ValueError("Plan filename/time mismatch")
                self.store.append("plan", p, ident=p["plan_id"])
                if p["plan_id"] in plans and plans[p["plan_id"]] != p:
                    raise ValueError("Plan changed")
                plans[p["plan_id"]] = p
            except Exception:
                log.exception("Conditional plan import refused: %s", path.name)
        return plans.values()

    def cancellation(self, plan):
        path = self.outbox / f"conditional-plan-cancel-{plan['plan_id']}.json"
        try:
            c = validate_cancel(read_json(path), plan)
        except FileNotFoundError:
            return False
        if parse_time(c["created_at"]) > self.clock():
            raise ValueError("Future cancellation")
        self.store.append(
            "plan_cancel",
            c,
            ident=plan["plan_id"] + ":cancel-request",
            ref=plan["plan_id"],
        )
        return True

    def observe(self, plan, scanner, selected, session, active):
        events = self.events(plan)
        state = events[-1]["state"] if events else "pending_activation"
        if state in TERMINAL:
            return
        now = self.clock()
        if self.cancellation(plan):
            self.event(plan, "cancelled", "owner_cancelled")
            return
        if not active:
            self.event(plan, "cancelled", "monitor_disabled")
            return
        if plan["symbol"] not in selected:
            self.event(plan, "cancelled", "ticker_removed")
            return
        if now >= parse_time(plan["expires_at"]):
            self.event(
                plan,
                "expired",
                "monitoring_window_ended",
                occurred=parse_time(plan["expires_at"]),
            )
            return
        if session is None or not session.open_at <= now.timestamp() < session.close_at:
            self.event(plan, "unavailable", "verified_session_unavailable")
            return
        symbol = plan["symbol"]
        try:
            if symbol not in scanner._pass_minutes:
                scanner._minutes(symbol, now.astimezone(ET).date())
            rows, observed = scanner._pass_minutes[symbol]
            now = self.clock()  # source access can take time
            if now >= parse_time(plan["expires_at"]):
                self.event(
                    plan,
                    "expired",
                    "monitoring_window_ended",
                    occurred=parse_time(plan["expires_at"]),
                )
                return
            bars = checked_bars(rows, observed, now)
            observations = [
                o
                for o in self.store.records("plan_observation", plan["session_date"])
                if o["plan_id"] == plan["plan_id"]
            ]
            # Only FULL minutes beginning at/after commitment may satisfy a condition.
            cursor = (
                observations[-1]["bar"]["end_time"]
                if observations
                else math.ceil(parse_time(plan["created_at"]).timestamp() / 60) * 60
            )
            consecutive = observations[-1]["consecutive"] if observations else 0
            new = [
                b
                for b in bars
                if b["end_time"] > cursor
                and b["end_time"] < parse_time(plan["expires_at"]).timestamp()
            ]
            if new and new[0]["time"] != cursor:
                raise ValueError("missing_minute")
            if state == "pending_activation":
                self.event(plan, "watching", "monitor_accepted")
                state = "watching"
            for b in new:
                if b["time"] != cursor:
                    raise ValueError("missing_minute")
                if now.timestamp() - b["end_time"] > FRESH_SECONDS:
                    raise ValueError("monitoring_gap")
                above = plan["direction"] == "long"
                failed = (
                    b["close"] < plan["invalidation_price"]
                    if above
                    else b["close"] > plan["invalidation_price"]
                )
                met = (
                    b["close"] > plan["trigger_price"]
                    if above
                    else b["close"] < plan["trigger_price"]
                )
                consecutive = consecutive + 1 if met else 0
                frozen = {
                    k: b[k]
                    for k in ("time", "end_time", "open", "high", "low", "close")
                }
                o = seal(
                    {
                        "plan_id": plan["plan_id"],
                        "session_date": plan["session_date"],
                        "bar": frozen,
                        "observed_at": stamp(datetime.fromtimestamp(observed, UTC)),
                        "consecutive": consecutive,
                        "created_at": stamp(now),
                    }
                )
                cursor = b["end_time"]
                at = datetime.fromtimestamp(cursor, UTC)
                if failed:
                    self.event(
                        plan,
                        "invalidated",
                        "invalidation_close",
                        bar=frozen,
                        occurred=at,
                    )
                    self.store.append(
                        "plan_observation",
                        o,
                        ident=f"{plan['plan_id']}:bar:{int(b['end_time'])}",
                        ref=plan["plan_id"],
                    )
                    return
                if state == "watching" and consecutive >= plan["confirm_bars"]:
                    self.event(
                        plan, "triggered", "confirmed_closes", bar=frozen, occurred=at
                    )
                    state = "triggered"
                # Save the transition before advancing the cursor: a crash cannot
                # consume the decisive bar without preserving its state change.
                self.store.append(
                    "plan_observation",
                    o,
                    ident=f"{plan['plan_id']}:bar:{int(b['end_time'])}",
                    ref=plan["plan_id"],
                )
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, ValueError)
                and str(exc)
                in {
                    "stale_source",
                    "stale_bars",
                    "invalid_bar",
                    "duplicate_bars",
                    "missing_minute",
                    "monitoring_gap",
                }
                else "source_unavailable"
            )
            self.event(plan, "unavailable", reason)
            log.warning("Plan %s monitoring unavailable: %s", plan["plan_id"], reason)

    def deliver(self, plan, active):
        if not active:
            return
        events = self.events(plan)
        if not events or self.cancellation(plan):
            return
        latest = events[-1]
        for e in events:
            if e["state"] in ("watching", "cancelled"):
                continue
            # A later invalidation/expiry/unavailable supersedes a queued trigger.
            if e["state"] == "triggered" and latest["state"] != "triggered":
                attempts = [
                    a
                    for a in self.store.records(
                        "plan_push_attempt", plan["session_date"]
                    )
                    if a["event_id"] == e["event_id"]
                ]
                if not attempts:
                    self.runner._attempt(
                        "plan_push_attempt",
                        self.clock(),
                        plan["session_date"],
                        "event_id",
                        e["event_id"],
                        0,
                        "expired",
                        "push",
                        error="superseded",
                    )
                continue
            at = parse_time(e["occurred_at"]).astimezone(ET)
            comparison = "above" if plan["direction"] == "long" else "below"
            inverse = "below" if comparison == "above" else "above"
            messages = {
                "triggered": f"{plan['confirm_bars']} completed 1-minute closes {comparison} {plan['trigger_price']:g}.",
                "invalidated": f"A completed 1-minute close was {inverse} {plan['invalidation_price']:g}.",
                "expired": "The monitoring window ended. No new trigger will be sent.",
                "unavailable": "Monitoring stopped because continuous fresh evidence was unavailable. The price condition is unknown; this is not a trade invalidation.",
            }
            message = f"{messages[e['state']]}\nObserved {at:%H:%M:%S} ET. "
            if e["bar"]:
                message += f"Close {e['bar']['close']:g}. "
            message += f"\nYour saved plan: {plan['rationale']}\nAdvisory only; no entry, exit, or order assumed.\nPlan {plan['plan_id']}"

            def send(e=e, message=message):
                current = self.clock()
                if self.cancellation(plan):
                    raise ValueError("plan_cancelled")
                if e["state"] == "triggered" and current >= parse_time(
                    plan["expires_at"]
                ):
                    raise ValueError("plan_expired")
                if (
                    current - parse_time(e["occurred_at"])
                ).total_seconds() > FRESH_SECONDS:
                    raise ValueError("plan_event_stale")
                return self.push(f"Jo plan: {plan['symbol']} — {e['state']}", message)

            self.runner._deliver(
                "plan_push_attempt",
                self.clock(),
                plan["session_date"],
                "event_id",
                e["event_id"],
                parse_time(e["occurred_at"]),
                FRESH_SECONDS / 60,
                DELIVERY,
                "push",
                send,
            )

    def project(self, plan, active):
        events = self.events(plan)
        observations = [
            o
            for o in self.store.records("plan_observation", plan["session_date"])
            if o["plan_id"] == plan["plan_id"]
        ]
        event_ids = {e["event_id"] for e in events}
        attempts = [
            a
            for a in self.store.records("plan_push_attempt", plan["session_date"])
            if a["event_id"] in event_ids
        ]
        now = stamp(self.clock())
        publish(
            self.directory,
            f"conditional-plan-status-{plan['plan_id']}.json",
            seal(
                {
                    "format": "conditional-plan-status-v1",
                    "plan_id": plan["plan_id"],
                    "plan_sha256": plan["content_sha256"],
                    "state": events[-1]["state"] if events else "pending_activation",
                    "enabled": active,
                    "events": events,
                    "delivery": attempts,
                    "last_bar_end": observations[-1]["bar"]["end_time"]
                    if observations
                    else None,
                    "checked_at": now,
                    "created_at": now,
                }
            ),
        )

    def run(self, scanner, active=True):
        # The existing delivery helper is serialized across process restarts/overlap.
        with open(str(self.store.path) + ".plans.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            now = self.clock()
            day = now.astimezone(ET).date()
            from app.engine.paper import regular_session

            try:
                session = regular_session(day, scanner.calendar.hours(day))
            except Exception:
                session = None
            with Session(scanner.engine) as db:
                selection = scanner_settings.read_settings(db)
            publish(
                self.directory,
                "conditional-plan-readiness.json",
                seal(
                    {
                        "format": "conditional-plan-readiness-v1",
                        "enabled": active,
                        "session_date": day.isoformat(),
                        "symbols": selection["symbols"],
                        "selection_revision": selection["revision"],
                        "session_open_at": stamp(
                            datetime.fromtimestamp(session.open_at, UTC)
                        )
                        if session
                        else None,
                        "session_close_at": stamp(
                            datetime.fromtimestamp(session.close_at, UTC)
                        )
                        if session
                        else None,
                        "created_at": stamp(now),
                    }
                ),
            )
            plans = list(self.ingest())
            for plan in plans:
                try:
                    self.observe(plan, scanner, selection["symbols"], session, active)
                    self.project(plan, active)
                except Exception:
                    log.exception(
                        "Conditional plan observation failed: %s", plan["plan_id"]
                    )
            # Finish observations before potentially slow phone delivery.
            for plan in plans:
                try:
                    self.deliver(plan, active)
                    self.project(plan, active)
                except Exception:
                    log.exception("Conditional plan pass failed: %s", plan["plan_id"])


def run_for_scanner(scanner):
    from app.engine.stock_watch import enabled as stock_enabled

    active = enabled() and stock_enabled()
    monitor = getattr(scanner, "_plan_monitor", None)
    if monitor is None:
        if not active:
            return
        paths = [
            os.environ.get(k, "")
            for k in (
                "MARKET_WATCH_STORE",
                "MARKET_WATCH_SNAPSHOTS_DIR",
                "MARKET_WATCH_OUTBOX_DIR",
            )
        ]
        if not all(p and Path(p).is_absolute() for p in paths):
            raise ValueError(
                "Conditional plans require the existing market-watch exchange"
            )
        monitor = scanner._plan_monitor = PlanMonitor(
            MarketWatchWakeStore(paths[0]),
            paths[1],
            paths[2],
            clock=lambda: datetime.fromtimestamp(scanner.clock(), UTC),
        )
    monitor.run(scanner, active=active)
