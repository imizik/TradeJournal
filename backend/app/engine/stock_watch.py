"""Selected-stock awareness. Option selection and paper decisions are separate."""

from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine import scanner_mail, scanner_settings, ntfy
from app.models import ScannerCandidate
from market_watch_common import parse_time, seal, digest
from stock_watch_common import (
    FORMAT,
    POLICY,
    stamp,
    validate_alert,
    validate_review,
    write_once,
)

log = logging.getLogger(__name__)
BAR_FIELDS = ("time", "end_time", "open", "high", "low", "close", "volume")
DELIVERY = {"max_attempts": 3, "retry_seconds": 60}


def enabled():
    return os.environ.get("STOCK_WATCH_ENABLED", "").lower() == "true"


def signal_id(symbol, setup, bar_end):
    return "sta_" + str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"stock-setup-v1:{symbol}:{setup}:{int(bar_end)}"
        )
    )


def packet(
    symbol,
    kind,
    direction,
    minutes,
    observed,
    now,
    selection,
    trigger,
    *,
    alert_id,
    code=None,
):
    rows = [
        {k: b[k] for k in BAR_FIELDS}
        for b in minutes
        if b["end_time"] <= observed.timestamp()
    ][-60:]
    p = seal(
        {
            "format": FORMAT,
            "alert_id": alert_id,
            "session_date": now.astimezone(ZoneInfo("America/New_York"))
            .date()
            .isoformat(),
            "symbol": symbol,
            "kind": kind,
            "direction": direction,
            "source": "delivery_diagnostic" if code else "tradier_timesales_1min",
            "detected_at": stamp(now),
            "created_at": stamp(now),
            "expires_at": stamp(now + timedelta(minutes=POLICY["expiry_minutes"])),
            "observed_at": stamp(observed),
            "selected_symbols": selection["symbols"],
            "selection_revision": selection["revision"],
            "evidence": {
                "price": rows[-1]["close"],
                "bars": rows,
                "trigger": trigger,
                "candidate_id": None,
            },
            "trade_eligibility": {
                "status": "not_evaluated",
                "reason": "Stock awareness only. Option eligibility and any paper TAKE/SKIP are handled separately.",
            },
            "diagnostic_code": code,
        }
    )
    return validate_alert(p)


def detect_move(minutes, opened, now, atr, previous=None):
    """Completed, contiguous 15-minute moves and large rebounds/drawdowns. No future bars."""
    rows = sorted(
        (b for b in minutes if opened <= b["time"] and b["end_time"] <= now),
        key=lambda b: b["time"],
    )
    if len(rows) < 16 or now - rows[-1]["end_time"] > POLICY["freshness_seconds"]:
        return None
    tail = rows[-16:]
    if any(b["time"] != tail[0]["time"] + 60 * i for i, b in enumerate(tail)):
        return None
    price, anchor = tail[-1]["close"], tail[0]["close"]
    if price <= 0 or anchor <= 0 or atr is None or atr <= 0:
        return None
    low, high = min(b["low"] for b in rows), max(b["high"] for b in rows)
    choices = []
    if abs(price - anchor) >= max(
        anchor * POLICY["move_fraction"], atr * POLICY["move_atr"]
    ):
        choices.append(("up" if price > anchor else "down", "15m_move", anchor))
    if price - low >= max(
        low * POLICY["reversal_fraction"], atr * POLICY["reversal_atr"]
    ):
        choices.append(("up", "session_rebound", low))
    if high - price >= max(
        high * POLICY["reversal_fraction"], atr * POLICY["reversal_atr"]
    ):
        choices.append(("down", "session_drawdown", high))
    if not choices:
        return None
    # Select the largest threshold-qualified move; do not send both directions from one bar.
    direction, kind, reference = max(choices, key=lambda c: abs(price - c[2]))
    if previous and (
        direction == previous["direction"]
        and abs(price - previous["evidence"]["price"]) < max(price * 0.01, atr * 0.25)
    ):
        return None
    return direction, {
        "kind": kind,
        "reference_price": reference,
        "price": price,
        "change_fraction": price / reference - 1,
        "daily_atr14": atr,
        "window_start": tail[0]["time"],
        "window_end": tail[-1]["end_time"],
        "observed_session_low": low,
        "observed_session_high": high,
        "policy": POLICY,
    }


class StockWatcher:
    def __init__(
        self,
        store,
        directory,
        outbox,
        *,
        clock=lambda: datetime.now(UTC),
        guard=lambda n: False,
        mail=scanner_mail.send,
        push=ntfy.publish,
    ):
        from app.engine.market_watch_wakes import MarketWatchRunner

        self.store, self.directory, self.outbox = store, Path(directory), Path(outbox)
        self.clock, self.guard, self.mail, self.push = clock, guard, mail, push
        self.runner = MarketWatchRunner(
            store, directory, clock=clock, setup_window=guard
        )
        self.last_minute = None

    def capture(self, alert):
        validate_alert(alert)
        self.store.append("stock_alert", alert, ident=alert["alert_id"])
        prior = next(
            (
                p
                for p in self.store.records("stock_alert", alert["session_date"])
                if p["alert_id"] == alert["alert_id"]
            ),
            None,
        )
        # A repeat detection recovers the original input and expiry, never refreshes them.
        alert = prior or alert
        write_once(self.directory, f"stock-{alert['alert_id']}.json", alert)
        return alert

    def status(self, symbol, reason, *, alert_id=None):
        now = self.clock()
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        key = "stock-status:" + digest([day, symbol, reason, alert_id])
        self.store.append(
            "stock_status",
            seal(
                {
                    "session_date": day,
                    "symbol": symbol,
                    "reason": reason,
                    "alert_id": alert_id,
                    "created_at": stamp(now),
                }
            ),
            ident=key,
        )

    def contacts(self, day):
        contacts = {}
        for a in self.store.records("stock_mail_attempt", day):
            if a["result"] in ("sending", "accepted", "unknown"):
                contacts[a["alert_id"]] = max(
                    contacts.get(a["alert_id"], parse_time(a["occurred_at"])),
                    parse_time(a["occurred_at"]),
                )
        for r in self.store.records("stock_review_notice", day):
            contacts[r["alert_id"]] = max(
                contacts.get(r["alert_id"], parse_time(r["received_at"])),
                parse_time(r["received_at"]),
            )
        return contacts

    def capture_signal(self, scanner, symbol, signal, minutes, observed, selection):
        now = self.clock()
        return self.capture(
            packet(
                symbol,
                "scanner_setup",
                "up" if signal["direction"] == "long" else "down",
                minutes,
                observed,
                now,
                selection,
                {
                    "setup": signal["setup"],
                    "bar_end": signal["bar_end"],
                    "facts": signal["facts"],
                    "reference_stop": signal["stop"],
                    "reference_target": signal["target"],
                },
                alert_id=signal_id(symbol, signal["setup"], signal["bar_end"]),
            )
        )

    def observe(self, scanner, today, session):
        now = self.clock()
        if session is None or not session.open_at <= now.timestamp() < session.close_at:
            return
        minute = int(now.timestamp()) // 60
        if self.last_minute == minute:
            return
        self.last_minute = minute
        with Session(scanner.engine) as db:
            selection = scanner_settings.read_settings(db)
        contacts = self.contacts(today.isoformat())
        for symbol in selection["symbols"]:
            observation = {
                "session_date": today.isoformat(),
                "symbol": symbol,
                "selection_revision": selection["revision"],
                "slot_minute": minute,
                "started_at": stamp(now),
                "source_observed_at": None,
                "bar_end": None,
                "daily_atr14": None,
                "outcome": "source_unavailable",
            }
            try:
                if symbol in scanner._pass_minutes:
                    minutes = scanner._pass_minutes[symbol][0]
                else:
                    minutes = scanner._minutes(symbol, today)
                _, observed = scanner._pass_minutes[symbol]
                atr = scanner._daily_atr(symbol, today)
                completed = [
                    b
                    for b in minutes
                    if session.open_at <= b["time"]
                    and b["end_time"] <= min(now.timestamp(), observed)
                ]
                observation.update(
                    source_observed_at=observed,
                    bar_end=completed[-1]["end_time"] if completed else None,
                    daily_atr14=atr,
                )
                if (
                    now.timestamp() - observed > POLICY["freshness_seconds"]
                    or not completed
                    or now.timestamp() - completed[-1]["end_time"]
                    > POLICY["freshness_seconds"]
                ):
                    observation["outcome"] = "stale_source"
                    self.status(symbol, "stale_source")
                    continue
                if atr is None:
                    observation["outcome"] = "atr_unavailable"
                    self.status(symbol, "atr_unavailable")
                    continue
                if len(completed) >= 16 and any(
                    b["time"] != completed[-16]["time"] + 60 * i
                    for i, b in enumerate(completed[-16:])
                ):
                    observation["outcome"] = "incomplete_recent_window"
                    self.status(symbol, "incomplete_recent_window")
                    continue
                if len(completed) < 16:
                    observation["outcome"] = "insufficient_recent_window"
                    continue
                alerts = [
                    p
                    for p in self.store.records("stock_alert", today.isoformat())
                    if p["symbol"] == symbol
                ]
                anchors = [p for p in alerts if p["alert_id"] in contacts]
                previous = (
                    max(anchors, key=lambda p: contacts[p["alert_id"]])
                    if anchors
                    else None
                )
                if previous and now - contacts[previous["alert_id"]] < timedelta(
                    minutes=POLICY["cooldown_minutes"]
                ):
                    observation["outcome"] = "cooldown"
                    continue
                found = detect_move(
                    minutes,
                    session.open_at,
                    min(now.timestamp(), observed),
                    atr,
                    previous,
                )
                if found:
                    direction, trigger = found
                    self.capture(
                        packet(
                            symbol,
                            "move",
                            direction,
                            minutes,
                            datetime.fromtimestamp(observed, UTC),
                            now,
                            selection,
                            trigger,
                            alert_id="sta_"
                            + str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"stock-move-v1:{today}:{symbol}:{int(trigger['window_end'])}",
                                )
                            ),
                        )
                    )
                    observation["outcome"] = "captured"
                else:
                    observation["outcome"] = "no_setup"
            except Exception:
                observation["outcome"] = "source_unavailable"
                self.status(symbol, "source_unavailable")
                log.exception("Stock awareness could not judge %s", symbol)
            finally:
                # Private, immutable evidence of an actual check, never backfilled.
                self.store.append(
                    "stock_observation",
                    seal({**observation, "checked_at": stamp(self.clock())}),
                    ident="stock-observation:" + digest(
                        [today.isoformat(), minute, symbol, selection["revision"]]
                    ),
                )

    def send(self, scanner, today):
        now = self.clock()
        if self.guard(now):
            self.status("*", "shadow_setup_guard")
            return
        with Session(scanner.engine) as db:
            selection = scanner_settings.read_settings(db)
            candidates = db.exec(
                select(ScannerCandidate).where(ScannerCandidate.session_date == today)
            ).all()
        eligible = {
            signal_id(c.symbol, c.setup, c.bar_end.replace(tzinfo=UTC).timestamp())
            for c in candidates
            if c.contract_json is not None
        }
        attempts = self.store.records("stock_mail_attempt", today.isoformat())
        reserved = {
            a["alert_id"]
            for a in attempts
            if a["result"] in ("sending", "accepted", "unknown")
        }
        alerts = self.store.records("stock_alert", today.isoformat())
        for alert in alerts:
            if now < parse_time(alert["expires_at"]):
                self.capture(alert)
            # Eligible paper setups use their existing single email; its prompt reviews stock only AFTER commit.
            if (
                alert["alert_id"] in eligible
                or alert["symbol"] not in selection["symbols"]
            ):
                continue
            # The per-symbol cooldown bounds wakes without exhausting another
            # selected ticker's capacity or ending coverage before the close.
            contacts = self.contacts(today.isoformat())
            recent = [
                p
                for p in alerts
                if p["symbol"] == alert["symbol"]
                and p["alert_id"] in contacts
                and p["alert_id"] != alert["alert_id"]
                and now - contacts[p["alert_id"]]
                < timedelta(minutes=POLICY["cooldown_minutes"])
            ]
            if recent and alert["alert_id"] not in reserved:
                self.status(alert["symbol"], "cooldown", alert_id=alert["alert_id"])
                continue
            self.capture(alert)

            def send_mail(p=alert):
                if self.clock() >= parse_time(p["expires_at"]):
                    raise ValueError("stock_alert_expired")
                return self.mail(
                    f"TJ Setup: STOCK {p['symbol']} {p['alert_id']}",
                    f"Stock alert ID: {p['alert_id']}\n",
                )

            self.runner._deliver(
                "stock_mail_attempt",
                now,
                today.isoformat(),
                "alert_id",
                alert["alert_id"],
                parse_time(alert["detected_at"]),
                POLICY["expiry_minutes"],
                DELIVERY,
                "email",
                send_mail,
            )
            attempts = self.store.records("stock_mail_attempt", today.isoformat())
            reserved = {
                a["alert_id"]
                for a in attempts
                if a["result"] in ("sending", "accepted", "unknown")
            }

    def ingest_and_deliver(self, selected=None):
        from app.engine.market_watch_snapshot import _read_bounded

        now = self.clock()
        alerts = {p["alert_id"]: p for p in self.store.records("stock_alert")}
        notices = {r["review_id"]: r for r in self.store.records("stock_review_notice")}
        for path in sorted(self.outbox.glob("stock-review-str_*.json")):
            try:
                r = json.loads(_read_bounded(path.absolute(), 16 * 1024))
                if path.name != f"stock-review-{r['review_id']}.json":
                    raise ValueError("Stock review filename mismatch")
                alert = alerts[r["alert_id"]]
                validate_alert(alert)
                validate_review(r, alert)
                if parse_time(r["received_at"]) > now:
                    raise ValueError("Future stock review")
                self.store.append(
                    "stock_review_notice", r, ident=r["review_id"], ref=r["alert_id"]
                )
                notices[r["review_id"]] = r
            except Exception:
                log.exception("Stock review notice refused: %s", path.name)
        for r in notices.values():
            alert = alerts[r["alert_id"]]
            if not r["notify"]:
                continue
            if selected is not None and r["symbol"] not in selected:
                self.status(r["symbol"], "selection_removed", alert_id=r["alert_id"])
                continue
            if now >= parse_time(alert["expires_at"]):
                if not any(
                    a["review_id"] == r["review_id"]
                    for a in self.store.records("stock_push_attempt")
                ):
                    self.runner._attempt(
                        "stock_push_attempt",
                        now,
                        r["session_date"],
                        "review_id",
                        r["review_id"],
                        0,
                        "expired",
                        "push",
                        error="stock_alert_expired",
                    )
                continue
            message = (
                f"{r['summary']}\nInvalidation: {r['invalidation']}\n"
                f"Stock awareness only; option/trade eligibility is separate.\nReview {r['review_id']}"
            )
            if alert["kind"] == "diagnostic":
                message = (
                    f"DELIVERY DIAGNOSTIC — {alert['diagnostic_code']}\n" + message
                )
            title = f"Jo stock review: {r['symbol']} — {r['stance']}"
            if alert["kind"] == "diagnostic":
                title = f"TJ stock delivery diagnostic: {alert['diagnostic_code']}"
            # Never allow a late phone message merely because Jo submitted just before expiry.
            freshness = max(
                0,
                (
                    parse_time(alert["expires_at"]) - parse_time(r["received_at"])
                ).total_seconds()
                / 60,
            )

            def send(title=title, message=message, expires=alert["expires_at"]):
                if self.clock() >= parse_time(expires):
                    raise ValueError("stock_alert_expired")
                return self.push(title, message)

            self.runner._deliver(
                "stock_push_attempt",
                now,
                r["session_date"],
                "review_id",
                r["review_id"],
                parse_time(r["received_at"]),
                freshness,
                DELIVERY,
                "push",
                send,
            )


def for_scanner(scanner):
    if not enabled():
        return None
    if getattr(scanner, "_stock_watcher", None) is None:
        from app.engine.market_watch_wakes import (
            MarketWatchWakeStore,
            _default_setup_window,
        )

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
                "Stock watch requires the existing explicit market-watch store/publication/outbox paths"
            )
        scanner._stock_watcher = StockWatcher(
            MarketWatchWakeStore(paths[0]),
            paths[1],
            paths[2],
            clock=lambda: datetime.fromtimestamp(scanner.clock(), UTC),
            guard=_default_setup_window,
        )
    return scanner._stock_watcher
