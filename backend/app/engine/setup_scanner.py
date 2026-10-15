"""Setup scanner S1: finds setups, freezes them and paper-trades each one by rule.

Runs inside the level alert monitor's loop, beside the Practice paper watcher,
only when ``SETUP_SCANNER_ENABLED`` is true. The rules are in
``scanner_rules`` (pure); this module reads Tradier through the chart feed's
shared budgeted read, the options chain budget and the quote endpoint, and
stores what the rules decide as ``ScannerCandidate`` rows and append-only
``ScannerEvent`` rows. A trade's state is always the fold of its events, so a
restart rebuilds it from the database.

Nothing here touches fills, trades, accounts, decisions or alerts. When
setup emails are configured (``scanner_mail``), each setup with a contract is
also emailed once while fresh so Jo can review it; the email is a notice,
never part of the paper trade. Every entry and exit is priced from an option quote read
after the decision; a decision that cannot be priced within two minutes, or a
condition noticed more than two minutes late, ends the trade ``unresolved``.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import scanner_rules as rules
from app.engine import ntfy, scanner_mail, tradier
from app.engine import shadow_exchange
from app.engine import scanner_settings
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET, normalize_bars
from app.engine.level_alerts import LATENESS
from app.engine.options_chain import OptionsChainError
from app.engine.paper import regular_session
from app.models import ScannerCandidate, ScannerEvent, Trade

log = logging.getLogger(__name__)

SOURCE = "tradier_timesales_1min"
TERMINAL = {"exit", "unresolved", "no_contract"}
EMAIL_SUBJECT = "TJ Setup:"  # the fixed prefix Jo's Gmail trigger watches for
EMAILS_PER_DAY = 15  # bounds Jo's wake-ups; the historical replay averaged 8.8 setups a day
SETUP_NAMES = {"orb": "opening-range break", "fade": "VWAP fade"}


def enabled() -> bool:
    return os.environ.get("SETUP_SCANNER_ENABLED", "false").lower() in ("1", "true", "yes")


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def fold(events: list[ScannerEvent]) -> dict:
    """The trade's state: one entry per event type, by type."""
    return {e.event_type: {**json.loads(e.data_json), "at": _epoch(e.effective_at)} for e in events}


def setup_email(candidate: ScannerCandidate) -> tuple[str, str]:
    """Subject and plain-text body for one setup. Market facts and rule output only: no journal data."""
    contract = json.loads(candidate.contract_json)
    facts = json.loads(candidate.facts_json)
    flags = json.loads(candidate.flags_json)
    side = contract["option_type"].upper()
    at_et = candidate.bar_end.replace(tzinfo=UTC).astimezone(ET)
    expires_et = candidate.expires_at.replace(tzinfo=UTC).astimezone(ET)
    subject = f"{EMAIL_SUBJECT} {candidate.symbol} {side} {SETUP_NAMES[candidate.setup]} {at_et:%H:%M} ET"
    lines = [
        f"Scanner setup {candidate.id}",
        f"{candidate.symbol} {SETUP_NAMES[candidate.setup]}, {candidate.direction} ({side}), 5-minute bar closed {at_et:%H:%M} ET.",
        f"Underlying close {facts['close']}, VWAP {facts['vwap']}, EMA9 {facts['ema9']}, daily ATR {facts['daily_atr14']}.",
        f"Opening range {facts['opening_range_low']} - {facts['opening_range_high']}.",
        f"Rule stop {candidate.stop} and target {candidate.target} on the underlying; 60-minute time stop.",
        f"Contract {contract['symbol']}: {contract['expiration']} {contract['strike']} {contract['option_type']}, "
        f"delta {contract['delta']}, bid {contract['bid']} / ask {contract['ask']} at detection.",
        f"Flags: {', '.join(flags) if flags else 'none'}.",
        f"Stale after {expires_et:%H:%M} ET: do not act on it later.",
        "",
        "For Jo: run pre_trade_check with these exact inputs, then attach_model_verdict.",
        json.dumps({"ticker": candidate.symbol, "side": candidate.direction, "instrument": "option", "horizon": "intraday",
                    "entry": facts["close"], "stop": candidate.stop, "option_type": contract["option_type"],
                    "expiration": contract["expiration"], "strike": contract["strike"],
                    "free_text": f"scanner {candidate.scanner_version} {candidate.setup} setup {candidate.id}",
                    "operation_id": str(candidate.id)}),
        "",
        "Rule-generated paper setup, not advice. The rules-only paper trade is recorded in TradeJournal either way.",
    ]
    from app.engine import stock_watch
    if stock_watch.enabled():
        lines += ["", "After the shadow TAKE/SKIP commit only, review the separate stock alert:",
                  "Stock alert ID: " + stock_watch.signal_id(candidate.symbol, candidate.setup, _epoch(candidate.bar_end))]
    return subject, "\n".join(lines)


def setup_push(candidate: ScannerCandidate) -> tuple[str, str]:
    """Short phone notification for a setup whose email was just sent."""
    contract = json.loads(candidate.contract_json)
    at_et = candidate.bar_end.replace(tzinfo=UTC).astimezone(ET)
    expires_et = candidate.expires_at.replace(tzinfo=UTC).astimezone(ET)
    title = f"Setup: {candidate.symbol} {contract['option_type'].upper()} {SETUP_NAMES[candidate.setup]} {at_et:%H:%M} ET"
    message = (f"{contract['expiration']} {contract['strike']} {contract['option_type']}, "
               f"bid {contract['bid']} / ask {contract['ask']}. Stop {candidate.stop}, target {candidate.target}. "
               f"Stale after {expires_et:%H:%M} ET.")
    return title, message


def _push(candidate: ScannerCandidate) -> str:
    """Best effort, sent once: a failed push never holds back the email record."""
    if not ntfy.configured():
        return "off"
    try:
        ntfy.publish(*setup_push(candidate), path="/scanner")
    except ntfy.NtfyError as exc:
        log.warning("Setup push for %s not sent: %s", candidate.id, exc)
        return "failed"
    return "sent"


def status_of(candidate: ScannerCandidate, state: dict) -> str:
    if candidate.contract_json is None:
        return "no_contract"
    for kind in ("unresolved", "exit", "exit_intent", "entry"):
        if kind in state:
            return {"exit_intent": "exiting", "entry": "open"}.get(kind, kind)
    return "pending_entry"


def shadow_status_of(candidate: ScannerCandidate, state: dict, now: float | None = None) -> str:
    if candidate.contract_json is None:
        return "no_contract"
    for kind in ("shadow_unresolved", "shadow_exit", "shadow_exit_intent", "shadow_entry"):
        if kind in state:
            return {"shadow_exit_intent": "exiting", "shadow_entry": "open"}.get(kind, "unresolved" if kind == "shadow_unresolved" else "exit")
    decision = state.get("shadow_decision")
    if decision is None:
        if state.get("shadow_handoff", {}).get("status") != "written":
            return "not_published"
        now = datetime.now(UTC).timestamp() if now is None else now
        return "no_response" if _epoch(candidate.expires_at) <= now else "awaiting_decision"
    if decision.get("timing") == "late":
        return "late"
    if decision.get("decision") == "skip":
        return "skipped"
    return "pending_entry"


def _fresh(quote, decided: float) -> bool:
    """Both sides of the quote were updated at or after the decision (Tradier's millisecond times)."""
    return all(isinstance(t, (int, float)) and t >= decided * 1000 for t in (quote.bid_date, quote.ask_date))


def _quote(occ: str):
    return tradier.get_quotes_once([occ]).get(occ)


class SetupScanner:
    def __init__(self, engine, feed, calendar, options, clock, quote=_quote, *, paper_enabled=True):
        self.engine, self.feed, self.calendar, self.options, self.clock = engine, feed, calendar, options, clock
        self.quote = quote
        self.paper_enabled = paper_enabled
        self._scanned: dict[str, int] = {}  # per symbol, the newest 5-minute bar end already judged
        self._pass_minutes = {}
        self._atr: dict[tuple[str, date], float | None] = {}

    def run(self) -> None:
        try:
            if self.paper_enabled:
                self._run()
            else:
                self._pass_minutes = {}
                today = datetime.fromtimestamp(self.clock(), ET).date()
                session = regular_session(today, self.calendar.hours(today))
                if session is not None:
                    self.scan(today, session, stock_only=True)
        finally:
            # Stock awareness must survive an option-chain failure, lack of a
            # qualifying contract, and the paper scanner's 15:00 cutoff.
            try:
                from app.engine.stock_watch import for_scanner
                watcher = for_scanner(self)
                if watcher is not None:
                    now = self.clock()
                    today = datetime.fromtimestamp(now, ET).date()
                    session = regular_session(today, self.calendar.hours(today))
                    with Session(self.engine) as db:
                        selected = scanner_settings.read_settings(db)["symbols"]
                    watcher.ingest_and_deliver(selected)
                    watcher.observe(self, today, session)
                    watcher.send(self, today)
            except Exception:
                log.exception("Selected-stock awareness pass failed")

    def _run(self) -> None:
        self._pass_minutes = {}
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        session = regular_session(today, self.calendar.hours(today))
        try:
            self.manage(now, today, session)
        finally:
            if session is not None:
                self.scan(today, session)
            try:
                self.shadow_exchange_pass(now, today, session)
            except Exception:
                log.exception("Shadow exchange failed this pass")
            if session is not None:
                try:
                    self.email(today)  # a setup saved on this pass goes out now, not 20 seconds later
                except Exception:
                    log.exception("Setup emails failed this pass")
                try:
                    self.publish_candles(today, session)
                except Exception:
                    log.exception("Scanner candle publication failed this pass")

    # -------------------------------------------------------------- scanning

    def scan(self, today: date, session, *, stock_only=False) -> None:
        now = self.clock()
        bar_end = session.open_at + (int(now - LATENESS) - session.open_at) // rules.BAR_SECONDS * rules.BAR_SECONDS
        last_end = min(int(datetime(today.year, today.month, today.day, rules.LAST_BAR_END_MINUTE // 60,
                                    rules.LAST_BAR_END_MINUTE % 60, tzinfo=ET).timestamp()), session.close_at - 3600)
        if bar_end - rules.BAR_SECONDS < session.open_at + rules.FIRST_BAR_AFTER or bar_end > last_end:
            return
        if now - bar_end > rules.MAX_DELAY_SECONDS + LATENESS:
            return  # too late to act on this bar; a symbol not judged in time simply misses it
        with Session(self.engine) as db:
            settings = scanner_settings.read_settings(db)
        for symbol in settings["symbols"]:
            if self._scanned.get(symbol, 0) >= bar_end:
                continue
            try:
                self._scan_symbol(symbol, today, session, bar_end, last_end, settings, stock_only=stock_only)
                self._scanned[symbol] = bar_end  # a failed read is retried on the next pass while still in time
            except (ChartFeedError, OptionsChainError, ValueError) as exc:
                log.warning("Setup scanner could not judge %s at %s: %s", symbol, _utc(bar_end), exc)
            except Exception:
                log.exception("Setup scanner failed on %s", symbol)

    def _scan_symbol(self, symbol: str, today: date, session, bar_end: int, last_end: int, settings: dict, *, stock_only=False) -> None:
        atr = self._daily_atr(symbol, today)
        if atr is None:
            return
        minutes = self._minutes(symbol, today)
        complete = [m for m in minutes if m["end_time"] <= bar_end]
        if not any(m["time"] >= bar_end - rules.BAR_SECONDS for m in complete):
            raise ChartFeedError("the newest 5-minute bar has no minutes yet")
        bars = rules.five_minute_bars(complete, session.open_at, session.close_at)
        with Session(self.engine) as db:
            # Universe edits must not reset cooldowns, daily caps or open-trade protection.
            saved = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == today,
                                                           ScannerCandidate.symbol == symbol)).all()
            taken = {(c.setup, int(_epoch(c.bar_end))) for c in saved}
            busy = any(status_of(c, fold(self._events(db, c.id))) in ("pending_entry", "open", "exiting") for c in saved)
        signals = rules.scan(bars, atr, session.open_at, last_end, taken)
        signal = signals[-1] if signals and signals[-1]["bar_end"] == bar_end else None
        if signal is None:
            return
        # Freeze/send stock evidence independently, BEFORE option selection.
        # Failure of this advisory path must not alter the paper baseline.
        try:
            from app.engine.stock_watch import for_scanner
            watcher = for_scanner(self)
            if watcher is not None:
                watcher.capture_signal(self, symbol, signal, complete,
                    datetime.fromtimestamp(self._pass_minutes[symbol][1], UTC), settings)
        except Exception:
            log.exception("Stock setup capture failed for %s", symbol)
        if stock_only or busy or any(_epoch(c.bar_end) > bar_end - rules.COOLDOWN_SECONDS for c in saved):
            return
        contract, note = self._contract(symbol, today, signal["direction"])
        detected = self.clock()
        version, params_hash = scanner_settings.identity(settings["symbols"])
        candidate = ScannerCandidate(
            scanner_version=version, params_hash=params_hash, session_date=today, symbol=symbol,
            setup=signal["setup"], direction=signal["direction"], bar_start=_utc(signal["bar_start"]), bar_end=_utc(bar_end),
            detected_at=_utc(detected), expires_at=_utc(detected + rules.EXPIRY_SECONDS), stop=signal["stop"],
            target=signal["target"], flags_json=json.dumps(signal["flags"]),
            facts_json=json.dumps({**signal["facts"], "scanner_universe": settings["symbols"],
                                   "scanner_settings_revision": settings["revision"],
                                   **({"contract_note": note} if note else {})}, sort_keys=True),
            contract_json=json.dumps(contract, sort_keys=True) if contract else None, source=SOURCE,
        )
        with Session(self.engine) as db:
            db.add(candidate)
            try:
                db.flush()
                # Persist with the candidate; recovery never refetches decision bars.
                if contract is not None:
                    frozen = shadow_exchange.candle_packet(complete, bars, min(bar_end, detected), limit=60)
                    db.add(ScannerEvent(candidate_id=candidate.id, key="shadow_candles", event_type="shadow_candles",
                        effective_at=_utc(detected), recorded_at=_utc(detected),
                        data_json=json.dumps({"candles": frozen})))
                db.commit()
            except IntegrityError:
                db.rollback()
                return  # another pass already saved this bar
            db.refresh(candidate)
        if contract is not None:
            self._enter(candidate, self.clock())

    def _contract(self, symbol: str, today: date, direction: str) -> tuple[dict | None, str | None]:
        expiration = rules.pick_expiration(self.options.expirations(symbol), today)
        if expiration is None:
            return None, "no expiration today or 3-7 days out"
        chosen = rules.choose_contract(self.options.chain(symbol, expiration).contracts, direction)
        return chosen, None if chosen else "no contract met the delta and liquidity limits"

    def _daily_atr(self, symbol: str, today: date) -> float | None:
        key = (symbol, today)
        if key not in self._atr:
            data, _, issue = self.feed.read("/v1/markets/history", {
                "symbol": symbol, "interval": "daily", "start": (today - timedelta(days=40)).isoformat(),
                "end": (today - timedelta(days=1)).isoformat()}, 3600)
            if issue:
                raise ChartFeedError(f"daily bars not current: {issue}")
            days = ((data or {}).get("history") or {}).get("day") or []
            days = [days] if isinstance(days, dict) else days
            rows = [r for r in normalize_bars(days, daily=True) if datetime.fromtimestamp(r["time"], ET).date() < today]
            self._atr[key] = rules.atr14(rows)
        return self._atr[key]

    def _minutes(self, symbol: str, today: date) -> list[dict]:
        # The same request the Practice paper watcher makes for a same-day plan, so a shared cache entry.
        observed_at = self.clock()
        data, fetched_at, issue = self.feed.read("/v1/markets/timesales", {
            "symbol": symbol, "interval": "1min", "session_filter": "all",
            "start": today.strftime("%Y-%m-%d 04:00"), "end": today.strftime("%Y-%m-%d 20:00"),
        }, 15)
        if issue:
            raise ChartFeedError(f"minute bars not current: {issue}")
        series = (data or {}).get("series") or {}
        rows = series.get("data") if isinstance(series, dict) else None
        result = normalize_bars(rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else [])
        self._pass_minutes[symbol] = (result, min(observed_at, fetched_at))
        return result

    def publish_candles(self, today, session):
        """Refresh the scanner universe each pass independently of signal eligibility."""
        setups = os.environ.get("SHADOW_SETUPS_DIR")
        if not setups or not session.open_at <= self.clock() <= session.close_at:
            return
        from pathlib import Path
        directory = Path(setups).parent / "candles"
        # The operator owns directory creation and its setgid/read permissions.
        if not directory.is_dir():
            return
        with Session(self.engine) as db:
            symbols = scanner_settings.read_settings(db)["symbols"]
        for symbol in symbols:
            try:
                if symbol not in self._pass_minutes:
                    self._minutes(symbol, today)
                minutes, observed_at = self._pass_minutes[symbol]
                cutoff = min(observed_at, session.close_at)
                complete = [m for m in minutes if session.open_at <= m["time"] and m["end_time"] <= cutoff]
                five = rules.five_minute_bars(complete, session.open_at, session.close_at)
                packet = shadow_exchange.candle_packet(complete, five, cutoff, limit=120)
                if packet:
                    shadow_exchange.atomic_write(directory / f"{symbol}.json",
                        {"format": "scanner-candles-v1", "symbol": symbol, **packet})
            except Exception:
                log.exception("Scanner candle publication failed for %s", symbol)

    # -------------------------------------------------------------- the paper trades

    def manage(self, now: float, today: date, session) -> None:
        try:
            self.email(today)
        except Exception:
            log.exception("Setup emails failed this pass")
        with Session(self.engine) as db:
            rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.contract_json.is_not(None))
                           .where(ScannerCandidate.session_date >= today - timedelta(days=7))).all()
            active = [(c, fold(self._events(db, c.id))) for c in rows]
        for candidate, state in active:
            status = status_of(candidate, state)
            if status not in ("pending_entry", "open", "exiting"):
                continue
            try:
                if candidate.session_date != today or session is None:
                    self._store(candidate, "unresolved", self.clock(), {"reason": "session ended before the trade finished"})
                elif status == "pending_entry":
                    self._enter(candidate, now)
                elif status == "open":
                    self._watch(candidate, state, session)
                else:
                    self._exit(candidate, state)
            except (ChartFeedError, ValueError) as exc:
                log.warning("Scanner trade %s not judged this pass: %s", candidate.id, exc)
            except Exception:
                log.exception("Scanner trade %s failed this pass", candidate.id)

    def shadow_exchange_pass(self, now: float, today: date, session) -> None:
        """Publish setups, import immutable decisions, and manage shadow trades."""
        setups_dir = os.environ.get("SHADOW_SETUPS_DIR")
        outbox_dir = os.environ.get("SHADOW_OUTBOX_DIR")
        with Session(self.engine) as db:
            rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == today)
                           .where(ScannerCandidate.contract_json.is_not(None)).order_by(ScannerCandidate.bar_end)).all()
            active = [(candidate, fold(self._events(db, candidate.id))) for candidate in rows]
            prior_rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date < today)
                                 .where(ScannerCandidate.session_date >= today - timedelta(days=7))
                                 .where(ScannerCandidate.contract_json.is_not(None))).all()
            prior_active = [(candidate, fold(self._events(db, candidate.id))) for candidate in prior_rows]

        for candidate, state in active:
            if setups_dir and "shadow_handoff" not in state:
                if now >= _epoch(candidate.expires_at):
                    self._store(candidate, "shadow_handoff", now, {"status": "expired"})
                else:
                    try:
                        shadow_exchange.write_setup(setups_dir, candidate, state.get("shadow_candles", {}).get("candles"))
                    except Exception as exc:
                        log.warning("Shadow setup handoff for %s failed this pass: %s", candidate.id, exc)
                    else:
                        self._store(candidate, "shadow_handoff", self.clock(), {"status": "written"})

        # Re-read state after handoff writes; decisions are processed only once.
        with Session(self.engine) as db:
            active = [(candidate, fold(self._events(db, candidate.id))) for candidate in rows]
        if outbox_dir:
            for candidate, state in active:
                if "shadow_decision" in state or "shadow_unresolved" in state:
                    continue
                try:
                    decision = shadow_exchange.read_decision(outbox_dir, candidate, state.get("shadow_candles", {}).get("candles"))
                except shadow_exchange.ShadowExchangeError as exc:
                    self._store(candidate, "shadow_unresolved", self.clock(), {"reason": str(exc)})
                    continue
                if decision is None:
                    continue
                stored_at = self.clock()
                data = {**decision, "stored_at": shadow_exchange.utc_z(_utc(stored_at))}
                self._store(candidate, "shadow_decision", stored_at, data)

        # The decision's arrival at this backend is the entry decision time.
        with Session(self.engine) as db:
            active = [(candidate, fold(self._events(db, candidate.id))) for candidate in rows]
        for candidate, state in active:
            status = shadow_status_of(candidate, state)
            if status not in ("pending_entry", "open", "exiting"):
                continue
            try:
                if candidate.session_date != today or session is None:
                    self._store(candidate, "shadow_unresolved", self.clock(), {"reason": "session ended before the trade finished"})
                elif status == "pending_entry":
                    decided = state["shadow_decision"]["at"]
                    self._enter(candidate, now, prefix="shadow_", decided=decided)
                elif status == "open":
                    self._watch(candidate, state, session, prefix="shadow_")
                else:
                    self._exit(candidate, state, prefix="shadow_")
            except (ChartFeedError, ValueError) as exc:
                log.warning("Shadow scanner trade %s not judged this pass: %s", candidate.id, exc)
            except Exception:
                log.exception("Shadow scanner trade %s failed this pass", candidate.id)

        # A restart after a session boundary must close yesterday's still-open
        # shadow paper trade just as the rules-only watcher does.
        for candidate, state in prior_active:
            if shadow_status_of(candidate, state) in ("pending_entry", "open", "exiting"):
                self._store(candidate, "shadow_unresolved", now,
                            {"reason": "session ended before the trade finished"})

    def email(self, today: date) -> None:
        """Email each of today's setups with a contract once, while it is still fresh, up to the daily cap."""
        if not scanner_mail.configured():
            return
        with Session(self.engine) as db:
            rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == today)
                           .where(ScannerCandidate.contract_json.is_not(None)).order_by(ScannerCandidate.bar_end)).all()
            states = [(c, fold(self._events(db, c.id))) for c in rows]
        sent = sum(1 for _, state in states if state.get("email", {}).get("status") == "sent")
        for candidate, state in states:
            if "email" in state:
                continue
            now = self.clock()
            if now > _epoch(candidate.expires_at):
                self._store(candidate, "email", now, {"status": "expired"})
            elif sent >= EMAILS_PER_DAY:
                self._store(candidate, "email", now, {"status": "skipped_daily_cap"})
            else:
                subject, body = setup_email(candidate)
                try:
                    scanner_mail.send(subject, body)
                except scanner_mail.MailError as exc:
                    log.warning("Setup email for %s not sent this pass: %s", candidate.id, exc)
                    continue  # retried on the next pass until the setup goes stale
                self._store(candidate, "email", self.clock(), {"status": "sent", "push": _push(candidate)})
                sent += 1

    def _enter(self, candidate: ScannerCandidate, now: float, prefix: str = "", decided: float | None = None) -> None:
        contract = json.loads(candidate.contract_json)
        decided = _epoch(candidate.detected_at) if decided is None else decided
        quote = self._read_quote(contract["symbol"])
        at = self.clock()
        if at - decided > rules.MAX_DELAY_SECONDS:
            return self._store(candidate, f"{prefix}unresolved", at, {"reason": "no entry quote within two minutes"})
        if quote is not None and quote.ask and quote.ask > 0 and quote.bid is not None and _fresh(quote, decided):
            self._store(candidate, f"{prefix}entry", at, {"ask": quote.ask, "bid": quote.bid, "ask_time": quote.ask_date, "bid_time": quote.bid_date})

    def _watch(self, candidate: ScannerCandidate, state: dict, session, prefix: str = "") -> None:
        entry_at = state[f"{prefix}entry"]["at"]
        contract = json.loads(candidate.contract_json)
        same_day = contract["expiration"] == candidate.session_date.isoformat()
        minutes = self._minutes(candidate.symbol, candidate.session_date)
        now = self.clock()
        found = rules.exit_condition(candidate.direction, candidate.stop, candidate.target, minutes, entry_at,
                                     entry_at + rules.TIME_STOP_SECONDS, rules.flat_at(session.open_at, session.close_at, same_day),
                                     now, LATENESS)
        if found is None:
            return
        if now - found["condition_at"] > rules.MAX_DELAY_SECONDS + LATENESS:
            return self._store(candidate, f"{prefix}unresolved", now, {**found, "condition": found["reason"], "reason": "monitoring gap: exit condition noticed late"})
        self._store(candidate, f"{prefix}exit_intent", now, found)
        state = self._state(candidate)
        if f"{prefix}exit_intent" in state and f"{prefix}exit" not in state:
            self._exit(candidate, state, prefix=prefix)

    def _exit(self, candidate: ScannerCandidate, state: dict, prefix: str = "") -> None:
        contract = json.loads(candidate.contract_json)
        decided = state[f"{prefix}exit_intent"]["at"]
        quote = self._read_quote(contract["symbol"])
        at = self.clock()
        if at - decided > rules.MAX_DELAY_SECONDS:
            return self._store(candidate, f"{prefix}unresolved", at, {"reason": "no exit quote within two minutes"})
        if quote is not None and quote.bid is not None and quote.ask and _fresh(quote, decided):
            exit_ = {"bid": quote.bid, "ask": quote.ask, "bid_time": quote.bid_date, "ask_time": quote.ask_date,
                     "reason": state[f"{prefix}exit_intent"]["reason"]}
            self._store(candidate, f"{prefix}exit", at, {**exit_, **rules.result(state[f"{prefix}entry"], exit_, contract["multiplier"])})

    def _read_quote(self, occ: str):
        try:
            return self.quote(occ)
        except tradier.TradierError as exc:
            log.warning("Scanner quote for %s unavailable: %s", occ, exc)
            return None

    # -------------------------------------------------------------- storage

    @staticmethod
    def _events(db: Session, candidate_id: uuid.UUID) -> list[ScannerEvent]:
        return list(db.exec(select(ScannerEvent).where(ScannerEvent.candidate_id == candidate_id).order_by(ScannerEvent.recorded_at)).all())

    def _state(self, candidate: ScannerCandidate) -> dict:
        with Session(self.engine) as db:
            return fold(self._events(db, candidate.id))

    def _store(self, candidate: ScannerCandidate, kind: str, at: float, data: dict) -> None:
        with Session(self.engine) as db:
            db.add(ScannerEvent(candidate_id=candidate.id, key=kind, event_type=kind, effective_at=_utc(at),
                                recorded_at=_utc(self.clock()), data_json=json.dumps(data, sort_keys=True)))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # already stored by another pass


# ------------------------------------------------------------------ reading


def day_view(db: Session, day: date, own_entries: list[datetime] | None = None,
             own_trades: list[Trade] | None = None) -> dict:
    """The owner-only three-way comparison for the day and cumulative history.

    ``own_entries`` are the open times of Isaac's option trades that day (New
    York wall clock); they fill the review-time ``sixth_plus_entry`` flag and are never
    read by the scanner itself."""
    rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == day).order_by(ScannerCandidate.bar_end)).all()
    cumulative_rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date <= day)).all()
    linked = link_isaac_trades(list(cumulative_rows), own_trades or [])
    states = {c.id: fold(SetupScanner._events(db, c.id)) for c in cumulative_rows}
    isaac = {c.id: _isaac_view(c, states[c.id], linked[c.id]) for c in cumulative_rows}
    items, totals = [], {"candidates": 0, "trades": 0, "resolved": 0, "unresolved": 0, "no_contract": 0,
                         "pnl": 0.0, "pnl_2x_spread": 0.0, "wins": 0}
    for c in rows:
        state = states[c.id]
        status = status_of(c, state)
        shadow_status = shadow_status_of(c, state)
        flags = json.loads(c.flags_json)
        if own_entries is not None:
            detected_et = c.detected_at.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)
            if sum(1 for t in own_entries if t < detected_et) >= 5:
                flags = flags + ["sixth_plus_entry"]
        exit_ = state.get("exit")
        totals["candidates"] += 1
        if status == "no_contract":
            totals["no_contract"] += 1
        elif status == "unresolved":
            totals["unresolved"] += 1
        if exit_:
            totals["resolved"] += 1
            totals["pnl"] += exit_["pnl"]
            totals["pnl_2x_spread"] += exit_["pnl_2x_spread"]
            totals["wins"] += exit_["pnl"] > 0
        if "entry" in state:
            totals["trades"] += 1
        items.append({
            "id": str(c.id), "symbol": c.symbol, "setup": c.setup, "direction": c.direction,
            "scanner_version": c.scanner_version, "params_hash": c.params_hash,
            "bar_end": c.bar_end.isoformat() + "Z", "detected_at": c.detected_at.isoformat() + "Z",
            "stop": c.stop, "target": c.target, "flags": flags, "facts": json.loads(c.facts_json),
            "contract": json.loads(c.contract_json) if c.contract_json else None, "status": status,
            "shadow": _shadow_view(state, shadow_status),
            "isaac": isaac[c.id],
            "events": {k: {**v, "at": datetime.fromtimestamp(v["at"], UTC).isoformat().replace("+00:00", "Z")} for k, v in state.items()},
        })
    totals["pnl"], totals["pnl_2x_spread"] = round(totals["pnl"], 2), round(totals["pnl_2x_spread"], 2)
    day_score = _shadow_scorecard([(c, states[c.id]) for c in rows], isaac)
    cumulative_score = _shadow_scorecard([(c, states[c.id]) for c in cumulative_rows], isaac)
    return {"date": day.isoformat(), "scanner_version": rules.VERSION, "params_hash": rules.PARAMS_HASH,
            "enabled": enabled(), "totals": totals, "scorecard": {"day": day_score, "cumulative": cumulative_score}, "candidates": items}


def link_isaac_trades(candidates: list[ScannerCandidate], trades: list[Trade]) -> dict:
    """Pure, display-only links. Latest detection wins; equal times use lowest ID."""
    linked = {c.id: [] for c in candidates}
    for trade in trades:
        if trade.instrument_type != "option" or trade.option_type not in ("call", "put"):
            continue
        # Trades store naive NY wall clock; candidates store naive UTC.
        opened = trade.opened_at.replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
        direction = "long" if trade.option_type == "call" else "short"
        eligible = [c for c in candidates if c.symbol == trade.ticker and c.direction == direction
                    and c.detected_at <= opened <= c.detected_at + timedelta(minutes=15)]
        if eligible:
            chosen = min(eligible, key=lambda c: (-_epoch(c.detected_at), str(c.id)))
            linked[chosen.id].append(trade)
    for trades_ in linked.values():
        trades_.sort(key=lambda t: (t.opened_at, str(t.id)))
    return linked


def _isaac_view(candidate: ScannerCandidate, state: dict, trades: list[Trade]) -> dict:
    contract = json.loads(candidate.contract_json) if candidate.contract_json else None
    email = state.get("email", {})
    details = []
    for trade in trades:
        opened = trade.opened_at.replace(tzinfo=ET)
        pnl = float(trade.realized_pnl) if trade.status in ("closed", "expired") and trade.realized_pnl is not None else None
        details.append({
            "trade_id": str(trade.id), "account_id": str(trade.account_id),
            "contract": {"ticker": trade.ticker, "option_type": trade.option_type,
                         "strike": float(trade.strike) if trade.strike is not None else None,
                         "expiration": trade.expiration.isoformat() if trade.expiration else None},
            "contracts": float(trade.contracts), "avg_entry_premium": float(trade.avg_entry_premium),
            "opened_at": opened.isoformat(), "closed_at": trade.closed_at.replace(tzinfo=ET).isoformat() if trade.closed_at else None,
            "status": trade.status, "realized_pnl": pnl,
            "pnl_per_contract": pnl / float(trade.contracts) if pnl is not None and trade.contracts > 0 else None,
            "assisted": email.get("status") == "sent" and email.get("at", float("inf")) < opened.timestamp(),
            "contract_differs": bool(contract and ((float(trade.strike) if trade.strike is not None else None) != contract["strike"] or
                                     (trade.expiration.isoformat() if trade.expiration else None) != contract["expiration"])),
        })
    primary = details[0] if details else {"trade_id": None, "contract": None, "opened_at": None,
                                          "status": None, "realized_pnl": None, "pnl_per_contract": None,
                                          "assisted": False, "contract_differs": False}
    return {**primary, "traded": bool(trades), "extra_trade_ids": [t["trade_id"] for t in details[1:]],
            "trades": details}


def _isaac_scorecard(rows: list[tuple[ScannerCandidate, dict]], views: dict, independent_only: bool) -> dict:
    """Setup counts; results include every linked trade, each normalized separately.

    The independent subset removes any setup with an assisted linked trade,
    rather than turning that setup into a false Isaac pass.
    """
    score = {"setups": 0, "traded": 0, "assisted": 0, "independent": 0, "closed": 0,
             "priced": 0, "pnl_per_contract": 0.0, "pnl_dollars": 0.0}
    buckets = {key: {"count": 0, "rules_priced": 0, "rules_pnl": 0.0,
                     "shadow_priced": 0, "shadow_pnl": 0.0, "isaac_priced": 0,
                     "isaac_pnl_per_contract": 0.0, "isaac_pnl_dollars": 0.0}
               for key in ("shadow_only", "isaac_only", "both_took", "both_passed")}
    for candidate, state in rows:
        trades = views.get(candidate.id, {}).get("trades", [])
        assisted = any(t["assisted"] for t in trades)
        if independent_only and assisted:
            continue
        score["setups"] += 1
        traded = bool(trades)
        closed = [t for t in trades if t["status"] in ("closed", "expired")]
        priced = [t for t in closed if t["pnl_per_contract"] is not None]
        per_contract = sum(t["pnl_per_contract"] for t in priced)
        dollars = sum(t["realized_pnl"] for t in closed if t["realized_pnl"] is not None)
        score["traded"] += traded
        score["assisted"] += traded and assisted
        score["independent"] += traded and not assisted
        score["closed"] += len(closed)
        score["priced"] += len(priced)
        score["pnl_per_contract"] += per_contract
        score["pnl_dollars"] += dollars
        decision = state.get("shadow_decision", {})
        # Late, unpublished and missing decisions are never shadow passes.
        if shadow_status_of(candidate, state) in ("not_published", "no_contract") or decision.get("timing") != "on_time":
            continue
        if decision.get("decision") not in ("take", "skip"):
            continue
        take = decision["decision"] == "take"
        key = ("both_took" if traded else "shadow_only") if take else ("isaac_only" if traded else "both_passed")
        bucket = buckets[key]
        bucket["count"] += 1
        rules_exit, shadow_exit = state.get("exit"), state.get("shadow_exit")
        if rules_exit:
            bucket["rules_priced"] += 1
            bucket["rules_pnl"] += rules_exit["pnl"]
        if take and shadow_exit:
            bucket["shadow_priced"] += 1
            bucket["shadow_pnl"] += shadow_exit["pnl"]
        bucket["isaac_priced"] += len(priced)
        bucket["isaac_pnl_per_contract"] += per_contract
        bucket["isaac_pnl_dollars"] += dollars
    for group in [score, *buckets.values()]:
        for key in group:
            if "pnl" in key:
                group[key] = round(group[key], 2)
        count = group["traded"] if "traded" in group else group["count"]
        group["evidence"] = "not enough" if count < 30 else "sufficient count"
    score["group_evidence"] = {key: "not enough" if score[key] < 30 else "sufficient count"
                               for key in ("assisted", "independent", "closed")}
    return {**score, "disagreements": buckets}


def _shadow_view(state: dict, status: str) -> dict:
    decision = state.get("shadow_decision")
    entry = state.get("shadow_entry")
    exit_ = state.get("shadow_exit")
    intent = state.get("shadow_exit_intent")
    unresolved = state.get("shadow_unresolved")
    labels = ["informed-by-history", "independence-unverified"]
    if decision:
        labels.extend(label for label in decision.get("labels", []) if label not in labels)
    return {
        "publication": state.get("shadow_handoff", {}).get("status"),
        "decision": decision.get("decision") if decision else None,
        "reason": decision.get("reason") if decision else None,
        "unresolved_reason": unresolved.get("reason") if unresolved else None,
        "timing": decision.get("timing") if decision else None,
        "clean_order": decision.get("clean_order") if decision else None,
        "labels": labels,
        "status": status,
        "entry": _event_public(entry),
        "exit": _event_public(exit_),
        "exit_intent": _event_public(intent),
        "result": {key: exit_[key] for key in ("pnl", "pnl_2x_spread", "return_on_premium") if key in exit_} if exit_ else None,
    }


def _event_public(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {**value, "at": datetime.fromtimestamp(value["at"], UTC).isoformat().replace("+00:00", "Z")}


def _shadow_scorecard(rows: list[tuple[ScannerCandidate, dict]], isaac: dict | None = None) -> dict:
    score = {"setups": len(rows), "decisions": 0, "take": 0, "skip": 0, "late": 0, "no_response": 0, "unresolved": 0,
             "rules_priced": 0, "shadow_priced": 0, "skipped_priced": 0,
             "rules_pnl": 0.0, "shadow_pnl": 0.0, "skipped_rules_pnl": 0.0, "clean_order": 0,
             "not_published": 0, "shadow_setups": 0}
    for candidate, state in rows:
        rules_exit = state.get("exit")
        if rules_exit:
            score["rules_pnl"] += rules_exit["pnl"]
            score["rules_priced"] += 1
        decision = state.get("shadow_decision")
        shadow = shadow_status_of(candidate, state)
        if shadow == "not_published":
            score["not_published"] += 1
        if shadow in ("not_published", "no_contract"):
            continue
        score["shadow_setups"] += 1
        if decision:
            score["decisions"] += 1
            if decision.get("timing") == "late":
                score["late"] += 1
            elif decision.get("decision") == "take":
                score["take"] += 1
            elif decision.get("decision") == "skip":
                score["skip"] += 1
                if rules_exit:
                    score["skipped_rules_pnl"] += rules_exit["pnl"]
                    score["skipped_priced"] += 1
            if decision.get("clean_order") is True:
                score["clean_order"] += 1
        elif shadow == "no_response":
            score["no_response"] += 1
        if shadow == "unresolved":
            score["unresolved"] += 1
        shadow_exit = state.get("shadow_exit")
        if shadow_exit:
            score["shadow_pnl"] += shadow_exit["pnl"]
            score["shadow_priced"] += 1
    for key in ("rules_pnl", "shadow_pnl", "skipped_rules_pnl"):
        score[key] = round(score[key], 2)
    score["evidence"] = "not enough" if score["decisions"] < 30 else "sufficient count"
    score["group_evidence"] = {
        "rules": "not enough" if score["setups"] < 30 else "sufficient count",
        "takes": "not enough" if score["take"] < 30 else "sufficient count",
        "skipped": "not enough" if score["skip"] < 30 else "sufficient count",
    }
    score["isaac"] = _isaac_scorecard(rows, isaac or {}, independent_only=False)
    score["independent"] = _isaac_scorecard(rows, isaac or {}, independent_only=True)
    return score
