"""Independent reference math on supplied records, with no database or providers.

Uses Decimal event ledgers and scalar recurrences, not the production pandas
calculators. Agreement means reproducibility on these inputs, not broker truth.
"""
from bisect import bisect_right
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
OPEN_SIDES = {"buy", "buy_to_open", "sell_to_open"}
REFERENCE_REVISION = "decimal-reference-v2"


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid numeric input") from exc
    if not result.is_finite():
        raise ValueError("Non-finite numeric input")
    return result


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return result.replace(tzinfo=ET) if result.tzinfo is None else result


def rounded(value, places=6):
    return float(round(value, places)) if value is not None else None


def percent(value, base):
    return rounded((value - base) / base * 100, 4) if value is not None and base else None


def normalized_bars(bars):
    result = []
    seen = set()
    for raw in bars:
        ts = timestamp(raw["t"]).astimezone(UTC)
        if ts in seen:
            raise ValueError("Duplicate bar timestamp")
        seen.add(ts)
        row = {key: number(raw[key]) for key in ("o", "h", "l", "c", "v")}
        if row["l"] > min(row["o"], row["c"]) or row["h"] < max(row["o"], row["c"]) or row["l"] <= 0 or row["v"] < 0:
            raise ValueError("Invalid OHLC/volume input")
        result.append((ts, row))
    return sorted(result, key=lambda row: row[0])


def entry_context(fill, bars):
    ts = timestamp(fill["executed_at"]).astimezone(ET)
    cutoff = ts.astimezone(UTC)
    completed = [(t, b) for t, b in normalized_bars(bars) if t + timedelta(minutes=1) <= cutoff]
    if not completed:
        return {"values": {}, "reason": "No completed minute bars", "completed_bars": 0, "total_bars": len(bars)}
    price = completed[-1][1]["c"]
    start = ts.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(UTC)
    pm_start = start - timedelta(hours=5, minutes=30)
    pm = [b for t, b in completed if pm_start <= t < start]
    rth = [(t, b) for t, b in completed if start <= t]
    or5 = [b for t, b in rth if t < start + timedelta(minutes=5)] if cutoff >= start + timedelta(minutes=5) else []
    or15 = [b for t, b in rth if t < start + timedelta(minutes=15)] if cutoff >= start + timedelta(minutes=15) else []
    volume = sum((b["v"] for _, b in rth), Decimal(0))
    weighted = sum(((b["h"] + b["l"] + b["c"]) / 3 * b["v"] for _, b in rth), Decimal(0))
    vwap = number(rounded(weighted / volume, 4)) if volume > 0 else None
    high = max((b["h"] for _, b in rth), default=None)
    low = min((b["l"] for _, b in rth), default=None)
    opening = next((b["o"] for t, b in completed if t == start), None)
    values = {
        "entry_underlying_price": rounded(price, 4), "entry_vwap": rounded(vwap, 4),
        "entry_vs_vwap_pct": percent(price, vwap), "entry_volume": int(completed[-1][1]["v"]),
        "cumulative_volume_at_entry": int(volume) if rth else None,
        "entry_day_high_so_far": rounded(high), "entry_day_low_so_far": rounded(low),
        "entry_day_range_used_pct": rounded((price - low) / (high - low) * 100, 2) if high is not None and low is not None and high != low else None,
        "entry_context_as_of": (completed[-1][0] + timedelta(minutes=1)).astimezone(ET).replace(tzinfo=None).isoformat(),
        "today_open": rounded(opening),
    }
    for name, series in (("premarket", pm), ("opening_range_5m", or5), ("opening_range_15m", or15)):
        values[f"{name}_high"] = rounded(max((b["h"] for b in series), default=None))
        values[f"{name}_low"] = rounded(min((b["l"] for b in series), default=None))
    return {"values": values, "reason": None, "completed_bars": len(completed), "total_bars": len(bars), "rth_bars": len(rth),
            "pm_bars": len(pm), "or5_bars": len(or5), "or15_bars": len(or15),
            "raw_bar": {"t": completed[-1][0].isoformat(), **{k: float(v) for k, v in completed[-1][1].items()}},
            "day_high_bar": next((t.isoformat() for t, b in rth if b["h"] == high), None),
            "day_low_bar": next((t.isoformat() for t, b in rth if b["l"] == low), None)}


def daily_indicators(bars, fill_time):
    day = timestamp(fill_time).astimezone(ET).date()
    history = [(t, b) for t, b in normalized_bars(bars) if t.astimezone(ET).date() < day]
    if len(history) < 10:
        return {"values": {}, "bars": len(history), "reason": "Fewer than ten completed daily bars"}
    ema = {}
    gain = loss = atr = None
    closes = []
    previous = None
    signal = None
    for _, b in history:
        close = b["c"]
        closes.append(close)
        for span in (9, 20, 12, 26):
            alpha = Decimal(2) / (span + 1)
            ema[span] = close if span not in ema else alpha * close + (1 - alpha) * ema[span]
        macd = ema[12] - ema[26]
        signal = macd if signal is None else Decimal("0.2") * macd + Decimal("0.8") * signal
        tr = b["h"] - b["l"]
        if previous is not None:
            tr = max(tr, abs(b["h"] - previous), abs(b["l"] - previous))
            delta = close - previous
            up, down = max(Decimal(0), delta), max(Decimal(0), -delta)
            gain = up if gain is None else (gain * 13 + up) / 14
            loss = down if loss is None else (loss * 13 + down) / 14
        atr = tr if atr is None else (atr * 13 + tr) / 14
        previous = close
    values = {"entry_ema_9": rounded(ema[9]), "entry_ema_20": rounded(ema[20]),
              "entry_rsi_14": rounded(100 - 100 / (1 + gain / loss)) if loss else None,
              "entry_atr_14": rounded(atr), "entry_macd": rounded(macd),
              "entry_macd_signal": rounded(signal), "entry_macd_histogram": rounded(macd - signal),
              "previous_day_high": rounded(history[-1][1]["h"]), "previous_day_low": rounded(history[-1][1]["l"]),
              "previous_day_close": rounded(history[-1][1]["c"])}
    for span in (20, 50):
        values[f"entry_sma_{span}"] = rounded(sum(closes[-span:]) / span) if len(closes) >= span else None
    return {"values": values, "bars": len(history), "reason": None,
            "earliest": history[0][0].astimezone(ET).date().isoformat(), "latest": history[-1][0].astimezone(ET).date().isoformat()}


def exposure_direction(fill):
    if fill["instrument_type"] == "stock":
        return True if fill["side"] == "buy" else None
    if fill.get("option_type") not in ("call", "put") or fill["side"] not in OPEN_SIDES:
        return None
    return (fill["option_type"] == "call") == (fill["side"] == "buy_to_open")


def position_ledger(trade, fills):
    ordered = sorted(fills, key=lambda f: (timestamp(f["executed_at"]), f["side"] not in OPEN_SIDES, str(f["id"])))
    if not ordered or ordered[0]["side"] not in OPEN_SIDES:
        raise ValueError("No opening fill")
    sign = Decimal(-1) if ordered[0]["side"] == "sell_to_open" else Decimal(1)
    lots, events = [], []
    realized = entered = paid = exited = proceeds = peak_quantity = Decimal(0)
    for f in ordered:
        quantity, price = number(f["contracts"]), number(f["price"])
        if quantity <= 0 or price < 0:
            raise ValueError("Invalid fill quantity or price")
        if f["side"] in OPEN_SIDES:
            if (f["side"] == "sell_to_open") != (sign < 0):
                raise ValueError("Mixed opening direction")
            lots.append([quantity, price])
            entered += quantity
            paid += quantity * price
        else:
            expected_side = "sell" if f["instrument_type"] == "stock" else "buy_to_close" if sign < 0 else "sell_to_close"
            if f["side"] != expected_side:
                raise ValueError("Closing side conflicts with position")
            exited += quantity
            proceeds += quantity * price
            while quantity:
                if not lots:
                    raise ValueError("Close exceeds available quantity; fill allocation ambiguous")
                used = min(quantity, lots[0][0])
                realized += sign * used * (price - lots[0][1])
                lots[0][0] -= used
                quantity -= used
                if not lots[0][0]:
                    lots.pop(0)
        remaining = sum((q for q, _ in lots), Decimal(0))
        basis = sum((q * p for q, p in lots), Decimal(0))
        peak_quantity = max(peak_quantity, remaining)
        events.append((timestamp(f["executed_at"]).astimezone(UTC), remaining, basis, realized))
    if trade["status"] == "closed" and events[-1][1]:
        raise ValueError("Closed position still has unmatched quantity")
    final = realized if exited else None
    if trade["status"] == "expired":
        final = realized - sign * events[-1][2]
    def financial(value, places=6):
        return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)) if value is not None else None
    values = {"contracts": financial(peak_quantity), "avg_entry_premium": financial(paid / entered),
              "avg_exit_premium": financial(proceeds / exited) if exited else None,
              "total_premium_paid": financial(paid), "realized_pnl": financial(final),
              "pnl_pct": financial(final / paid, 4) if final is not None and paid else None}
    return {"values": values, "events": events, "sign": sign, "final": final}


def option_path(trade, fills, bars):
    if trade["instrument_type"] != "option":
        return {"values": {}, "reason": "Not an option"}
    if not trade.get("closed_at"):
        return {"values": {}, "reason": "Position is open"}
    opened, closed = timestamp(trade["opened_at"]).astimezone(UTC), timestamp(trade["closed_at"]).astimezone(UTC)
    if (closed.astimezone(ET).date() - opened.astimezone(ET).date()).days + 1 > 10:
        return {"values": {}, "reason": "Window exceeds ten calendar days"}
    ledger = position_ledger(trade, fills)
    events = ledger["events"]
    times = [event[0] for event in events]
    samples = []
    for start, b in normalized_bars(bars):
        end = start + timedelta(minutes=1)
        if start < opened or end > closed or any(start <= t < end for t in times):
            continue
        idx = bisect_right(times, start) - 1
        if idx < 0:
            continue
        _, qty, basis, realized = events[idx]
        if not qty or not basis:
            continue
        high, low = b["h"] * 100, b["l"] * 100
        mark_fav = high if ledger["sign"] > 0 else low
        mark_bad = low if ledger["sign"] > 0 else high
        favorable = ledger["sign"] * (mark_fav * qty - basis)
        adverse = ledger["sign"] * (mark_bad * qty - basis)
        samples.append(dict(timestamp=start.isoformat(), quantity=float(qty), cost_basis=float(basis),
                            realized=float(realized), high=float(high), low=float(low),
                            favorable=favorable, adverse=adverse, total=realized + favorable,
                            mfe=favorable / basis * 100, mae=-adverse / basis * 100))
    if not samples:
        return {"values": {}, "reason": "No unambiguous holding-minute bars", "samples": []}
    zero = Decimal(0)
    peak_sample = max(samples, key=lambda s: s["total"])
    peak = max(zero, peak_sample["total"])
    peak_time = timestamp(peak_sample["timestamp"]) if peak > 0 else None
    final = ledger["final"]
    if final is not None and final > peak:
        peak, peak_time = final, closed
    giveback = peak - final if final is not None else None
    # A positive peak must survive the six-place persisted dollar precision.
    # A smaller value cannot support a capture ratio or positive-peak time.
    positive_peak = rounded(peak) > 0
    values = {"option_mfe_pct": rounded(max(zero, max(s["mfe"] for s in samples))),
              "option_mae_pct": rounded(max(zero, max(s["mae"] for s in samples))),
              "option_max_price_seen": max(s["high"] for s in samples), "option_min_price_seen": min(s["low"] for s in samples),
              "option_peak_unrealized_pnl": rounded(max(zero, max(s["favorable"] for s in samples))),
              "option_worst_unrealized_pnl": rounded(min(zero, min(s["adverse"] for s in samples))),
              "option_peak_total_pnl": rounded(peak), "option_giveback_from_peak": rounded(giveback),
              "option_exit_efficiency": rounded(final / peak * 100) if final is not None and positive_peak else None,
              "option_giveback_pct": rounded(giveback / peak * 100) if giveback is not None and positive_peak else None,
              "time_to_option_mfe_minutes": int((peak_time - opened).total_seconds() / 60) if peak_time and positive_peak else None}
    return {"values": values, "reason": None, "samples": [{k: rounded(v) if isinstance(v, Decimal) else v for k, v in s.items()} for s in samples],
            "peak_minute": peak_time.isoformat() if peak_time else None, "bars": len(samples)}


def underlying_path(trade, entry_fill, bars, anchor):
    if not trade.get("closed_at") or anchor is None or exposure_direction(entry_fill) is None:
        return {"values": {}, "reason": "Missing closed window, entry anchor, or direction"}
    start, end = timestamp(trade["opened_at"]).astimezone(UTC), timestamp(trade["closed_at"]).astimezone(UTC)
    if (timestamp(trade["closed_at"]).astimezone(ET).date() - timestamp(trade["opened_at"]).astimezone(ET).date()).days + 1 > 10:
        return {"values": {}, "reason": "Window exceeds ten calendar days"}
    anchor = number(anchor)
    if anchor <= 0:
        return {"values": {}, "reason": "Invalid entry anchor"}
    samples = [(t, b) for t, b in normalized_bars(bars) if start < t and t + timedelta(minutes=1) <= end]
    if not samples:
        return {"values": {}, "reason": "No unambiguous holding-minute bars"}
    bullish = exposure_direction(entry_fill)
    favorable = [((b["h"] - anchor) if bullish else (anchor - b["l"])) / anchor * 100 for _, b in samples]
    adverse = [((anchor - b["l"]) if bullish else (b["h"] - anchor)) / anchor * 100 for _, b in samples]
    fi, ai = favorable.index(max(favorable)), adverse.index(max(adverse))
    values = {"underlying_mfe_pct": rounded(max(Decimal(0), max(favorable))),
              "underlying_mae_pct": rounded(max(Decimal(0), max(adverse))),
              "time_to_underlying_mfe_minutes": int((samples[fi][0] - start).total_seconds() / 60),
              "time_to_underlying_mae_minutes": int((samples[ai][0] - start).total_seconds() / 60),
              "moved_in_favor_first": int(fi < ai) if fi != ai else None}
    return {"values": values, "reason": None, "bars": len(samples), "samples": [{"timestamp": t.isoformat(), "high": float(b["h"]), "low": float(b["l"])} for t, b in samples],
            "mfe_bar": samples[fi][0].isoformat(), "mae_bar": samples[ai][0].isoformat(),
            "mfe_high": float(samples[fi][1]["h"]), "mfe_low": float(samples[fi][1]["l"]),
            "mae_high": float(samples[ai][1]["h"]), "mae_low": float(samples[ai][1]["l"])}


def compare_values(stored, reference, *, stale=False, unavailable_reason=None, kind="observed_estimate"):
    checks = []
    for field, expected in reference.items():
        actual = stored.get(field)
        if isinstance(actual, datetime):
            actual = actual.isoformat()
        tolerance = Decimal("0.000001")
        difference = None
        if actual is not None and expected is not None and isinstance(expected, (int, float, Decimal)):
            difference = abs(number(actual) - number(expected))
            match = difference <= tolerance
        else:
            match = actual == expected
        status = "unavailable" if unavailable_reason else "stale" if stale else "unavailable" if actual is None else "matched" if match and expected is not None else "mismatch"
        checks.append({"field": field, "stored": actual, "reference": expected, "difference": rounded(difference),
                       "tolerance": float(tolerance), "status": status, "kind": kind,
                       "matches_reference": match if not unavailable_reason else None,
                       "reason": unavailable_reason or ("Stored calculation version is obsolete" if stale else "Stored value is missing" if actual is None else None)})
    return checks


def context_flags(fill, intraday, daily):
    """Independently evaluate directional labels; no learned edge is implied."""
    direction = exposure_direction(fill)
    price, vwap = intraday.get("entry_underlying_price"), intraday.get("entry_vwap")
    ema9, ema20, macd = daily.get("entry_ema_9"), daily.get("entry_ema_20"), daily.get("entry_macd_histogram")
    values = {}
    values["is_above_vwap"] = int(price > vwap if direction else price < vwap) if direction is not None and price is not None and vwap is not None else None
    values["is_trend_aligned"] = int(price > ema9 > ema20 and macd > 0 if direction else price < ema9 < ema20 and macd < 0) if direction is not None and all(v is not None for v in (price, ema9, ema20, macd)) else None
    boundary = intraday.get("opening_range_5m_high" if direction else "opening_range_5m_low")
    values["is_opening_range_breakout"] = int(price > boundary if direction else price < boundary) if direction is not None and price is not None and boundary is not None else None
    boundary = intraday.get("premarket_high" if direction else "premarket_low")
    values["is_premarket_breakout"] = int(price > boundary if direction else price < boundary) if direction is not None and price is not None and boundary is not None else None
    dt = timestamp(fill["executed_at"]).astimezone(ET)
    minute = dt.hour * 60 + dt.minute
    values["entry_time_bucket"] = "premarket" if minute < 570 else "open" if minute < 600 else "mid" if minute < 900 else "close" if minute < 960 else "afterhours"
    values["is_overnight"] = int(minute < 570 or minute >= 960)
    return values
