"""Read-only journal analytics, computed from supplied reconstructed positions.

No market data, inference of planned risk, or AI classification is involved.
Naive journal timestamps are America/New_York wall clocks.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from zoneinfo import ZoneInfo

from app.models import Trade

ET = ZoneInfo("America/New_York")


def wall_time(value: datetime) -> datetime:
    return value.astimezone(ET).replace(tzinfo=None) if value.tzinfo else value


def _money(value: Decimal | None) -> float | None:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


def summarize(trades: list[Trade]) -> dict:
    values = [Decimal(str(t.realized_pnl)) for t in trades if t.realized_pnl is not None]
    winners = [v for v in values if v > 0]
    losers = [v for v in values if v < 0]
    gross_profit = sum(winners, Decimal(0))
    gross_loss = -sum(losers, Decimal(0))
    total = sum(values, Decimal(0)) if values else None
    percentages = [Decimal(str(t.pnl_pct)) for t in trades if t.pnl_pct is not None and t.realized_pnl is not None]
    return {
        "count": len(trades),
        "pnl_count": len(values),
        "percentage_count": len(percentages),
        "entry_days": len({wall_time(t.opened_at).date() for t in trades}),
        "total_pnl": _money(total),
        "expectancy": _money(total / len(values)) if values else None,
        "median_pnl": _money(median(values)) if values else None,
        "win_rate": len(winners) / len(values) if values else None,
        "profit_factor": round(float(gross_profit / gross_loss), 2) if gross_loss else None,
        "no_losses": bool(winners) and not losers,
        "avg_winner": _money(gross_profit / len(winners)) if winners else None,
        "avg_loser": _money(-gross_loss / len(losers)) if losers else None,
        "avg_pnl_pct": float(sum(percentages) / len(percentages)) if percentages else None,
    }


def _entry_bucket(trade: Trade) -> str:
    minute = wall_time(trade.opened_at).hour * 60 + wall_time(trade.opened_at).minute
    for end, label in (
        (570, "Before 09:30"), (585, "09:30–09:45"), (615, "09:45–10:15"),
        (660, "10:15–11:00"), (840, "11:00–14:00"), (960, "14:00–16:00"),
    ):
        if minute < end:
            return label
    return "16:00 onward"


def _hold_bucket(trade: Trade) -> str:
    minutes = trade.hold_duration_mins
    if minutes is None or minutes < 0:
        return "Unavailable"
    for end, label in ((15, "Under 15 min"), (60, "15–60 min"), (240, "1–4 hours"), (1440, "4–24 hours")):
        if minutes < end:
            return label
    return "24 hours or longer"


def analyze(
    trades: list[Trade], tags: dict[str, list[str]], *,
    account_id: str | None = None, instrument_type: str | None = None,
    start: date | None = None, end: date | None = None,
) -> dict:
    # Sequence uses the complete supplied history, including open positions,
    # before filtering by close date or instrument. Same-time entries have the
    # same group; UUID ordering never invents a behavioral sequence.
    sequences: dict[str, str] = {}
    histories: dict[tuple, list[Trade]] = defaultdict(list)
    for trade in trades:
        opened = wall_time(trade.opened_at)
        histories[(trade.account_id, trade.ticker, opened.date())].append(trade)
    for history in histories.values():
        first = min(wall_time(t.opened_at) for t in history)
        for trade in history:
            sequences[str(trade.id)] = "First entry time" if wall_time(trade.opened_at) == first else "Repeat entry"

    scoped = [t for t in trades if (not account_id or str(t.account_id) == account_id)
              and (not instrument_type or t.instrument_type == instrument_type)
              and t.status in ("closed", "expired")]
    undated = sum(t.closed_at is None for t in scoped)
    selected = [t for t in scoped if t.closed_at is not None
                and (start is None or wall_time(t.closed_at).date() >= start)
                and (end is None or wall_time(t.closed_at).date() <= end)]
    selected.sort(key=lambda t: (wall_time(t.closed_at), str(t.id)))
    summary = summarize(selected)

    # Aggregate simultaneous closes before measuring drawdown; no arbitrary
    # intra-timestamp ordering may create a fictitious peak.
    closes: dict[datetime, Decimal] = defaultdict(Decimal)
    daily: dict[date, Decimal] = defaultdict(Decimal)
    for trade in selected:
        if trade.realized_pnl is not None:
            pnl = Decimal(str(trade.realized_pnl))
            closes[wall_time(trade.closed_at)] += pnl
            daily[wall_time(trade.closed_at).date()] += pnl
    cumulative = peak = drawdown = Decimal(0)
    for timestamp in sorted(closes):
        cumulative += closes[timestamp]
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    summary["max_drawdown"] = _money(drawdown) if closes else None
    cumulative = Decimal(0)
    curve = []
    for day, pnl in sorted(daily.items()):
        cumulative += pnl
        curve.append({"date": day.isoformat(), "pnl": _money(pnl), "cumulative_pnl": _money(cumulative)})

    winners = sorted((t for t in selected if t.realized_pnl is not None and t.realized_pnl > 0),
                     key=lambda t: (-Decimal(str(t.realized_pnl)), str(t.id)))
    gross_profit = sum((Decimal(str(t.realized_pnl)) for t in winners), Decimal(0))
    concentration = []
    for number in (1, 5):
        top = winners[:number]
        amount = sum((Decimal(str(t.realized_pnl)) for t in top), Decimal(0))
        concentration.append({
            "limit": number, "removed_count": len(top), "winner_pnl": _money(amount) if top else None,
            "gross_profit_share": float(amount / gross_profit) if gross_profit else None,
            "remaining_pnl": _money(sum(closes.values(), Decimal(0)) - amount) if closes else None,
            "trade_ids": [str(t.id) for t in top],
        })

    dimensions: dict[str, dict[str, list[Trade]]] = {name: defaultdict(list) for name in
        ("ticker", "entry_time", "tag", "hold_duration", "instrument", "repeat_entry")}
    for trade in selected:
        labels = {
            "ticker": [trade.ticker], "entry_time": [_entry_bucket(trade)],
            "tag": sorted(set(tags.get(str(trade.id), []))) or ["Untagged"],
            "hold_duration": [_hold_bucket(trade)], "instrument": [trade.instrument_type],
            "repeat_entry": [sequences[str(trade.id)]],
        }
        for name, keys in labels.items():
            for key in keys:
                dimensions[name][key].append(trade)
    breakdowns = {
        name: [{"label": label, **summarize(group), "trade_ids": [str(t.id) for t in group]}
               for label, group in groups.items()]
        for name, groups in dimensions.items()
    }
    return {
        "summary": summary, "curve": curve, "concentration": concentration, "breakdowns": breakdowns,
        "coverage": {"missing_pnl": len(selected) - summary["pnl_count"],
                     "missing_percentage": len(selected) - summary["percentage_count"],
                     "undated_closed_in_scope": undated},
        "trades": [{"id": str(t.id), "ticker": t.ticker, "account_id": str(t.account_id),
                    "instrument_type": t.instrument_type, "option_type": t.option_type,
                    "strike": float(t.strike) if t.strike is not None else None,
                    "expiration": t.expiration.isoformat() if t.expiration else None,
                    "opened_at": wall_time(t.opened_at).isoformat(),
                    "closed_at": wall_time(t.closed_at).isoformat(), "status": t.status,
                    "realized_pnl": _money(Decimal(str(t.realized_pnl))) if t.realized_pnl is not None else None,
                    "pnl_pct": float(t.pnl_pct) if t.pnl_pct is not None else None}
                   for t in reversed(selected)],
    }
