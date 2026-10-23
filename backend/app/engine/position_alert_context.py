"""Optional frozen Radar evidence on an already-qualified holding alert.

No triggers, provider reads, calendar refreshes, background jobs or send state.
The regular-session window comes from the alert monitor's existing calendar read.
"""
from datetime import datetime
import json
import logging
import math
import os
import time

from sqlmodel import Session

from app.engine.chart_math import ET
from app.engine.radar_comparison import empty_comparison, epoch, iso
from app.engine.radar_entry import resolve_entry, compare_resolved_entry
from app.engine.radar_runner import enabled
from app.engine.radar_store import RadarStore, load_universe
from app.models import Trade

log = logging.getLogger(__name__)
READ_BUDGET_SECONDS = 0.1


def capture(engine, alert, now: float, regular) -> str:
    """A failure here never invalidates the original alert or its write transaction."""
    result = {"state": "off", "reason": "Recorded market context could not be read."}
    deadline = time.monotonic() + READ_BUDGET_SECONDS
    try:
        # Own read session: an optional DB-read failure must not poison the outbox transaction.
        with Session(engine) as db:
            trade = db.get(Trade, alert.trade_id)
            if trade is None or trade.account_id != alert.account_id:
                result["reason"] = "Recorded position identity could not be verified."
            else:
                result = empty_comparison(trade.ticker.upper(), None, load_universe(), now)
                if resolve_entry(db, trade, result, now, source_key=alert.source_key) and result["group"]:
                    path = os.environ.get("RADAR_STORE", "").strip()
                    if not enabled():
                        result.update(state="off", reason="Radar recording is off.")
                    elif not path or not os.path.isabs(path):
                        result.update(state="off", reason="Radar storage is not configured.")
                    elif regular is None:
                        result["reason"] = "Confirmed regular-session hours unavailable."
                    else:
                        store = RadarStore(path, read_only=True, read_deadline=deadline)
                        result = compare_resolved_entry(store, result, now, regular[1:], live=True)
        return json.dumps({"version": 1, "detected_at": iso(now), "comparison": result}, allow_nan=False)
    except Exception:
        # Fail closed for context, but leave trigger/delivery authority with position_alerts.
        log.warning("Optional holding-alert context unavailable", exc_info=True)
        return json.dumps({"version": 1, "detected_at": iso(now), "comparison": {
            "state": "off", "reason": "Recorded market context could not be read."}})


def phone_text(snapshot: str | None) -> str:
    """Compact observational addendum. No stale numbers, inference or malformed-payload send failure."""
    if snapshot is None:  # legacy alerts keep their original presentation
        return ""
    unavailable = "Since-entry context unavailable."
    try:
        saved = json.loads(snapshot)
        if saved["version"] != 1:
            return unavailable
        result = saved["comparison"]
        state = result["state"]
        if state == "stale":
            return "Since-entry context stale; current movement unavailable."
        if state not in ("ready", "partial"):
            reason = result.get("reason") or "Insufficient recorded coverage."
            return "Since-entry context unavailable: " + reason[:180]
        window, coverage, entry = result["window"], result["coverage"], result["entry"]
        start, end = (datetime.fromtimestamp(epoch(window[key]), ET) for key in ("start", "end"))
        changes = {row["symbol"]: row["change_pct"] for row in result["rows"]}

        def change(symbol):
            value = changes.get(symbol)
            return "unavailable" if value is None or not math.isfinite(value) else f"{value:+.2f}%"

        available, total = coverage["peers_available"], coverage["peers_total"]
        peers = (f"{coverage['peers_down']}/{available} peers lower, {coverage['peers_up']} higher; {total} tracked"
                 if available else f"0/{total} peers covered")
        group = result["group"]["name"][:60]
        return (f"Underlying since entry · {start:%m/%d %H:%M}–{end:%H:%M} ET\n"
                f"{result['symbol']} {change(result['symbol'])} · QQQ {change('QQQ')} · SPY {change('SPY')}\n"
                f"{group}: {peers}\n"
                f"Samples start +{math.ceil(entry['baseline_delay_seconds'])}s after entry; "
                f"{coverage['recorded_minutes']}/{coverage['expected_minutes']} min recorded"
                + (" · partial coverage" if state == "partial" else ""))
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return unavailable
