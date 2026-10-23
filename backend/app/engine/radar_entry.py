"""Shared original-entry resolution for Charts and recorded alert context."""
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.engine.chart_journal import stamp
from app.engine.chart_math import ET
from app.engine.radar_comparison import compare_entry, epoch, iso
from app.models import Fill, Trade, TradeFill


def resolve_entry(db: Session, trade: Trade, result: dict, now: float, *, source_key: str | None = None) -> bool:
    """Keep adds/partial exits anchored to the first fill, never the remaining lot."""
    result["window_minutes"] = None
    if trade.status != "open" or trade.instrument_type != "option":
        result["reason"] = "Since-entry context requires a recorded open option trade."
        return False
    first = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(
        TradeFill.trade_id == trade.id, TradeFill.role == "entry",
        Fill.account_id == trade.account_id, Fill.ticker == trade.ticker,
    ).order_by(Fill.executed_at, func.coalesce(Fill.raw_email_id, ""), Fill.id)).first()
    recorded_at = stamp(trade.opened_at)
    if first is None or stamp(first.executed_at) != recorded_at:
        result["reason"] = "The first recorded entry could not be verified from this trade's fills."
        return False
    if source_key is not None and (first.raw_email_id or str(first.id)) != source_key:
        result["reason"] = "The recorded position identity no longer matches this alert."
        return False
    boundary = (recorded_at // 60 + 1) * 60
    result["entry"] = {"trade_id": str(trade.id), "recorded_at": iso(recorded_at),
                       "not_before": iso(boundary), "deadline": iso(boundary + 90),
                       "baseline_at": None, "baseline_delay_seconds": None}
    if datetime.fromtimestamp(recorded_at, ET).date() != datetime.fromtimestamp(now, ET).date():
        result["reason"] = "Only entries from today's regular session are supported; overnight positions are unavailable."
        return False
    if recorded_at > now:
        result["reason"] = "Recorded entry is in the future; context is unavailable."
        return False
    return True


def compare_resolved_entry(store, result: dict, now: float, window, live: bool) -> dict:
    """Use caller-supplied calendar hours: no provider/calendar calls here."""
    entry_clock = datetime.fromtimestamp(epoch(result["entry"]["recorded_at"]), ET)
    entry_minute = entry_clock.hour * 60 + entry_clock.minute
    if not window or not window[0] <= entry_minute < window[1]:
        return {**result, "reason": "Entry is outside a confirmed regular session; context is unavailable."}
    clock = datetime.fromtimestamp(now, ET)
    midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return compare_entry(store, result, today=clock.date().isoformat(), now=now, live=live,
                         regular_start=midnight + window[0] * 60, regular_end=midnight + window[1] * 60)
