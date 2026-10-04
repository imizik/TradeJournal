"""Chart-only split adjustment on supplied bars. Pure: no network, no files.

The chart's one price basis is **split-adjusted**: every price before a split's
ex-date is divided by the split ratio and every volume multiplied by it, so a
10-for-1 split leaves no cliff and EMAs, VWAP, levels and candles agree across
minute, daily and weekly charts. Stored raw bars are never edited; callers hand
raw bars in and get adjusted copies back. Fills and P&L never pass through here.
Dividends are not adjusted, and the response says so.

A split is applied only when a provider recorded it (``chart_splits``). Looking
like a split is never enough to change a price: ``suspect_gaps`` only warns.
"""

from datetime import date, datetime
from math import isfinite, log
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BASIS = "split_adjusted"
DIVIDENDS_NOTE = "Dividends are not adjusted; prices are split-adjusted only."
UNKNOWN_NOTE = ("Split data is unavailable for this symbol, so prices are shown as the provider supplied them. "
                "A stock split would appear as a sudden price cliff.")
# Common split ratios, as price-before / price-after across the split (>1 forward, <1 reverse).
_COMMON = (2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50)
_SUSPECT = sorted({*_COMMON, *(1 / r for r in _COMMON)})
SOURCE = "alpaca_corporate_actions"


def _day(stamp: int) -> date:
    return datetime.fromtimestamp(stamp, ET).date()


def ratio_label(ratio: float) -> str:
    """'10-for-1' for a forward split, '1-for-10' for a reverse split."""
    if ratio >= 1:
        return f"{ratio:g}-for-1"
    return f"1-for-{1 / ratio:g}"


def factor_before(splits: list[dict], day: date) -> float:
    """Divisor for prices dated ``day``: the product of ratios of splits that happen after it."""
    factor = 1.0
    for split in splits:
        if date.fromisoformat(split["ex_date"]) > day:
            factor *= split["ratio"]
    return factor


def _scaled(bar: dict, factor: float) -> dict:
    if factor == 1.0:
        return bar
    row = {k: bar[k] / factor for k in ("open", "high", "low", "close")}
    if bar.get("vwap") is not None:
        row["vwap"] = bar["vwap"] / factor
    return {**bar, **row, "volume": bar["volume"] * factor}


def adjust_minutes(minutes: list[dict], day: date, splits: list[dict]) -> list[dict]:
    """One New York session's raw minutes on the adjusted basis (a split is effective for the whole date)."""
    factor = factor_before(splits, day)
    return minutes if factor == 1.0 else [_scaled(b, factor) for b in minutes]


def apply_splits(daily: list[dict], splits: list[dict]) -> list[dict]:
    """Daily bars on the adjusted basis for exactly these splits, with no check of what the provider did."""
    return [_scaled(b, factor_before(splits, _day(b["time"]))) for b in daily] if splits else daily


def adjust_daily(daily: list[dict], splits: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Daily bars on the adjusted basis, plus what each split needed.

    Tradier's daily history has been seen already split-adjusted (NVDA 2024-06-10,
    checked 2026-10-01) while Alpaca's minutes are raw. Rather than trust either
    habit, each split is checked against the bars themselves: if the close before
    the ex-date to the open after it still jumps by roughly the ratio, the bars are
    raw and are adjusted here; if the jump is gone, the provider already did it.
    A split the bars cannot show (none before or none after) is reported unverified
    and leaves them untouched. Returns ({ex_date: state}) with state one of
    ``provider_adjusted``, ``adjusted_here``, ``unverified``.
    """
    states: dict[str, str] = {}
    pending: list[dict] = []
    for split in splits:
        ex = date.fromisoformat(split["ex_date"])
        before = [b for b in daily if _day(b["time"]) < ex]
        after = [b for b in daily if _day(b["time"]) >= ex]
        if not before or not after:
            # Out of window, or the ex-date's bar is not published yet.
            if before and not after:
                states[split["ex_date"]] = "unverified"
            continue
        jump = log(before[-1]["close"] / after[0]["open"])
        target = log(split["ratio"])
        if abs(jump - target) < abs(jump):
            pending.append(split)
            states[split["ex_date"]] = "adjusted_here"
        else:
            states[split["ex_date"]] = "provider_adjusted"
    if not pending:
        return daily, states
    return apply_splits(daily, pending), states


def suspect_gaps(bars: list[dict], limit: int = 3) -> list[str]:
    """Warnings for overnight jumps that look like a split nobody recorded.

    Never adjusts anything. A close-to-open ratio within 4% of a common split
    ratio, between two different New York dates, is reported with its date.
    """
    found: list[str] = []
    for prev, nxt in zip(bars, bars[1:]):
        if _day(prev["time"]) == _day(nxt["time"]) or not (isfinite(prev["close"]) and nxt["open"] > 0):
            continue
        move = prev["close"] / nxt["open"]
        if any(abs(log(move / r)) < 0.04 for r in _SUSPECT):
            kind = "forward" if move > 1 else "reverse"
            found.append(f"Price jumps {move:.3g}x between {_day(prev['time']).isoformat()} and {_day(nxt['time']).isoformat()}, "
                         f"like a {kind} split that is not in the split data. Prices there are not adjusted.")
            if len(found) >= limit:
                break
    return found


def describe(info: dict, *, daily: dict[str, str] | None = None, suspects: list[str] | None = None) -> dict:
    """The adjustment block sent to the browser: basis, evidence and every limitation to show."""
    warnings = []
    if info["status"] == "unknown":
        warnings.append(UNKNOWN_NOTE)
    elif info["status"] == "stale":
        warnings.append("Split data could not be refreshed today; the last copy is used.")
    for ex, state in (daily or {}).items():
        if state == "unverified":
            warnings.append(f"The {ex} split could not be checked against daily bars yet; daily prices are as the provider supplied them.")
    warnings.extend(suspects or [])
    return {"basis": BASIS, "status": info["status"], "source": SOURCE, "as_of": info["as_of"],
            "splits": [{**s, "label": ratio_label(s["ratio"])} for s in info["splits"]],
            "daily": daily or {}, "dividends": "unsupported", "dividends_note": DIVIDENDS_NOTE,
            "warnings": warnings}

