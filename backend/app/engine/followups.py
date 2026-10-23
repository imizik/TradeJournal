"""Personal follow-ups on the existing market-watch worker, exchange and transports."""

from datetime import UTC, datetime, timedelta
import fcntl
import logging
import os
from pathlib import Path

from conditional_plan_common import publish, read_json
from followup_common import project, validate_record
from market_watch_common import digest, parse_time, seal, verify
from stock_watch_common import stamp

log = logging.getLogger(__name__)
POLICY = {"max_attempts": 3, "retry_seconds": 60}


def enabled():
    return os.environ.get("JO_FOLLOWUPS_ENABLED", "").lower() == "true"


def publish_stock(directory, symbol, bars, observed, now):
    """Reuse the scanner's completed minutes; no extra provider request or selection change."""
    publish(
        directory,
        f"followup-stock-{symbol}.json",
        seal(
            {
                "format": "jo-followup-stock-v1",
                "symbol": symbol,
                "created_at": stamp(now),
                "observed_at": stamp(datetime.fromtimestamp(observed, UTC)),
                "source": "tradier_timesales_1min",
                "bars": bars[-60:],
            }
        ),
    )


class FollowupRunner:
    def __init__(self, runner):
        self.runner = runner
        self.store = runner.store
        self.directory = runner.snapshots_dir
        self.outbox = runner.outbox_dir
        self.clock = runner.clock

    def ingest(self, now):
        known = {r["record_id"] for r in self.store.records("followup_record")}
        for path in sorted(self.outbox.glob("followup-fur_*.json")):
            if path.stem[len("followup-") :] in known:
                continue
            try:
                record = validate_record(read_json(path, 32 * 1024))
                if (
                    path.name != f"followup-{record['record_id']}.json"
                    or parse_time(record["created_at"]) > now
                ):
                    raise ValueError("Invalid follow-up handoff")
                self.store.append(
                    "followup_record",
                    record,
                    ident=record["record_id"],
                    ref=record["followup_id"],
                )
            except Exception:
                log.exception("Personal follow-up handoff refused")

    def evidence(self, request, now):
        body = request["body"]
        evidence = {
            "stocks": {},
            "stock_events": [],
            "price_plan": None,
            "limitations": [
                "No live positions or private journal access. Public web findings are Jo-reported."
            ],
        }
        events = []
        for symbol in body["symbols"]:
            try:
                value = read_json(self.directory / f"followup-stock-{symbol}.json")
                verify(value)
                if (
                    value["symbol"] != symbol
                    or value["format"] != "jo-followup-stock-v1"
                ):
                    raise ValueError("Stock evidence mismatch")
                cutoff = datetime.fromtimestamp(value["bars"][-1]["end_time"], UTC)
                if (
                    not 0 <= (now - cutoff).total_seconds() <= 180
                    or not 0
                    <= (now - parse_time(value["observed_at"])).total_seconds()
                    <= 180
                ):
                    raise ValueError("Stock evidence stale")
                evidence["stocks"][symbol] = value
            except (OSError, ValueError, KeyError, IndexError):
                evidence["stocks"][symbol] = {
                    "status": "unavailable",
                    "reason": "No fresh published selected-stock bars; do not infer price or pattern",
                }
        latest_alerts = {}
        for alert in self.store.records("stock_alert"):
            if (
                alert["symbol"] in body["symbols"]
                and request["created_at"] < alert["created_at"]
            ):
                latest_alerts[alert["symbol"]] = alert
        for alert in latest_alerts.values():
            if alert["symbol"] in body["symbols"]:
                events.append(alert["alert_id"])
                if now < parse_time(alert["expires_at"]):
                    evidence["stock_events"].append(alert)
        if body["linked_plan_id"]:
            try:
                value = read_json(
                    self.directory
                    / f"conditional-plan-status-{body['linked_plan_id']}.json"
                )
                verify(value)
                if value["plan_id"] != body["linked_plan_id"]:
                    raise ValueError("Plan mismatch")
                evidence["price_plan"] = {
                    "status": value,
                    "monitoring": (
                        value["enabled"]
                        and value["state"] in ("watching", "triggered")
                        and 0
                        <= (now - parse_time(value["checked_at"])).total_seconds()
                        <= 90
                    ),
                }
                # Immutable transition identity survives changing heartbeat/delivery projections.
                events.extend(
                    e["event_id"]
                    for e in value["events"]
                    if e["created_at"] > request["created_at"]
                )
            except (OSError, ValueError, KeyError):
                evidence["limitations"].append("Linked price-plan status unavailable")
        return evidence, digest(sorted(events))

    def push(self, ident, request, created, title, text, *, operational=False):
        # Operational conditions are rechecked on this pass and can be reported after
        # downtime. Keep the original session/id for dedup, never freshen market advice.
        self.runner._deliver(
            "followup_push",
            self.clock(),
            created.date().isoformat(),
            "notice_id",
            ident,
            self.clock() if operational else created,
            10,
            POLICY,
            "push",
            lambda: self.runner.push(title, text),
            extra={"followup_id": request["followup_id"]},
        )

    def run_once(self):
        if self.outbox is None:
            return
        # Same process/restart safety as price watches: never race transport reservations.
        with (Path(str(self.store.path) + ".followups.lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            self.pass_once()

    def pass_once(self):
        now = self.clock()
        active = enabled()
        publish(
            self.directory,
            "followup-readiness.json",
            seal(
                {
                    "format": "jo-followup-readiness-v1",
                    "enabled": active,
                    "created_at": stamp(now),
                    "review_hours": "verified regular market session",
                    "delivery": "existing phone push; acceptance is not phone display",
                }
            ),
        )
        if not active:
            return
        self.ingest(now)
        grouped = {}
        for r in self.store.records("followup_record"):
            grouped.setdefault(r["followup_id"], []).append(r)
        bounds = self.runner._session(now.date())
        in_session = bounds is not None and bounds[0] <= now < bounds[1]
        due = []
        for followup_id, records in grouped.items():
            # UUID filenames have no causal ordering. Reconstruct the immutable parent chain.
            requests = [r for r in records if r["kind"] == "request"]
            if len(requests) != 1:
                continue
            request = requests[0]
            rows = [request]
            while True:
                children = [
                    r
                    for r in records
                    if r["kind"] == "review"
                    and r.get("parent_id") == rows[-1]["record_id"]
                    and r["actor"] == request["actor"]
                ]
                if len(children) != 1:
                    break
                rows.append(children[0])
            rows.extend(
                r
                for r in records
                if r["kind"] == "cancel" and r["actor"] == request["actor"]
            )
            p = project(rows, now)
            evidence, event_key = self.evidence(request, now)
            prior_key = (
                p["latest_review"]["event_key"] if p["latest_review"] else digest([])
            )
            changed = event_key != digest([]) and event_key != prior_key
            is_due = (
                p["state"] == "active"
                and in_session
                and (now >= parse_time(p["next_review_at"]) or changed)
            )
            if is_due:
                due.append([followup_id, p["parent_id"], event_key])
            if (
                p["latest_review"]
                and p["latest_review"]["body"]["notify"]
                and p["state"] in ("active", "resolved")
            ):
                review = p["latest_review"]
                self.push(
                    review["record_id"],
                    request,
                    parse_time(review["created_at"]),
                    "Jo follow-up: " + request["body"]["title"],
                    review["body"]["summary"],
                )
                attempts = [
                    a
                    for a in self.store.records("followup_push")
                    if a.get("notice_id") == review["record_id"]
                ]
                if attempts and attempts[-1]["result"] == "expired":
                    self.push(
                        "undelivered:" + review["record_id"],
                        request,
                        parse_time(review["created_at"]),
                        "Jo follow-up delivery gap: " + request["body"]["title"],
                        "A saved review could not be delivered while fresh. Its explanation is retained in your follow-up history; "
                        + (
                            "this responsibility is closed."
                            if p["state"] == "resolved"
                            else "a later review is still scheduled."
                        ),
                        operational=True,
                    )
            if p["state"] == "expired":
                self.push(
                    "expiry:" + followup_id,
                    request,
                    parse_time(request["body"]["expires_at"]),
                    "Jo follow-up ended: " + request["body"]["title"],
                    "The saved follow-up period ended. This is not a conclusion about the idea. "
                    + (
                        "Last review: " + p["latest_review"]["body"]["summary"]
                        if p["latest_review"]
                        else "No Jo review was saved."
                    ),
                    operational=True,
                )
            effective_due = (
                max(parse_time(p["next_review_at"]), bounds[0])
                if in_session and p["next_review_at"]
                else now
            )
            overdue = is_due and now > effective_due + timedelta(minutes=15)
            if overdue:
                self.push(
                    "overdue:" + p["parent_id"],
                    request,
                    parse_time(p["next_review_at"]) + timedelta(minutes=15),
                    "Jo follow-up needs attention: " + request["body"]["title"],
                    "The planned review has no saved response. The idea has not been reassessed; do not assume Jo is following it successfully.",
                    operational=True,
                )
            delivery = [
                a
                for a in self.store.records("followup_push")
                if a.get("followup_id") == followup_id
            ][-12:]
            publish(
                self.directory,
                f"followup-work-{followup_id}.json",
                seal(
                    {
                        "format": "jo-followup-work-v1",
                        "followup_id": followup_id,
                        "actor": request["actor"],
                        "request_sha256": request["content_sha256"],
                        "parent_id": p["parent_id"],
                        "state": p["state"],
                        "next_review_at": p["next_review_at"],
                        "due": is_due,
                        "overdue": overdue,
                        "in_session": in_session,
                        "reason": "new_evidence" if changed else "planned_review",
                        "event_key": event_key,
                        "evidence": evidence,
                        "delivery": delivery,
                        "created_at": stamp(self.clock()),
                    }
                ),
            )
        if due and not self.runner.setup_window(self.clock()):
            # One batched wake per half-hour/generation; missed email is recovered by the hosted sweep.
            key = "fuw_" + digest([sorted(due), int(now.timestamp()) // 1800])[:32]
            self.runner._deliver(
                "followup_wake",
                now,
                now.date().isoformat(),
                "wake_id",
                key,
                datetime.fromtimestamp(int(now.timestamp()) // 1800 * 1800, UTC),
                30,
                POLICY,
                "email",
                lambda: self.runner.mail(
                    "TJ Market Watch: " + key, "Follow-up wake ID: " + key + "\n"
                ),
            )
