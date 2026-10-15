"""Finite, pure historical S1 setup selection and underlying-share proxy scoring.

The capture is Alpaca SIP/raw; live S1 uses Tradier minute bars, daily ATR and
options. A replay therefore compares selection under the same scanner rules,
not historical option fills or the exact live feed. No clock, network or DB is
read here. Future minutes are retained only in each sealed continuation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
import hashlib
import json
import math
import secrets
import uuid
from zoneinfo import ZoneInfo

from app.engine import scanner_rules as rules

ET = ZoneInfo("America/New_York")
VERSION = "scanner-selection-replay-v2"
STRICT_VERSION = "scanner-selection-replay-v1"
LEGACY_VERSION = "scanner-selection-replay-v0"
SETUP_COUNT_KEYS = ("orb:long", "fade:long", "fade:short")
SENSITIVITY_COST_PER_SHARE_PER_SIDE = 0.02
HOLDOUT_START = date(2026, 9, 14)
NAMESPACE = uuid.UUID("e67f01c8-bc75-4f76-b77c-d92313cfdb16")
LABELS = ["independence-unverified", "model-memory-unverified",
          "no-historical-news", "underlying-scored", "basis-unverified"]
DIFFERENCES = (
    "Historical Alpaca SIP raw stock bars replace live Tradier timesales and daily history; exact live signals may differ.",
    "Historical option chains, quotes, delta, liquidity and fills are unavailable; no option contract or premium P&L is inferred.",
    "Scanner cooldown, fade limits and busy state use an underlying-share proxy, not live option trade state.",
    "Entry and exit use completed minute stock bars and an explicit simulated clock; no live monitoring latency or quote freshness is reproduced.",
    "Daily ATR uses only prior raw stock sessions; historical intraday relative volume and macro context are unavailable.",
    "No historical corporate-action coverage verifies raw share basis across the ATR lookback.",
    "Missing minutes make partial five-minute bars; an empty newest bucket skips only that scan slot, as in live S1. Sparse bars can change signals without proving a setup was missed.",
    "Entry-minute stop not checked (optimistic); target touches are also ignored, matching the live watcher.",
    "If missing scoring minutes make a proxy hold unknown, suppress until its fixed baseline time-stop/flat deadline, then release selection without resolving P&L. Actual live close timing can differ.",
    "The 2-cent-per-share-per-side cost sensitivity changes net proxy R only, never fills, timing, selection or cooldown.",
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stamp(epoch: int | float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _epoch(value: object) -> int:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    if isinstance(value, str):
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            return int(moment.timestamp())
    raise ValueError("A timezone-aware timestamp or epoch is required")


def _scoring_policy(version: str, delay_seconds: int, cost_per_share: float, slippage_bps: float) -> dict:
    """Fixed share proxy: costs are dollars per share per side, slippage is adverse per side."""
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or not 0 <= delay_seconds <= 600:
        raise ValueError("delay_seconds must be an integer from 0 to 600")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in (cost_per_share, slippage_bps)):
        raise ValueError("Proxy costs must be finite and nonnegative")
    body = {"version": version, "entry": "first_full_minute_after_detection_plus_delay_open",
            "exit": "completed_minute_stop_first_then_target; clock_at_first_eligible_open",
            "entry_minute_stop_check": False, "favorable_target_price_cap": True,
            "time_stop_seconds": rules.TIME_STOP_SECONDS, "flat_rule": "scanner_s1_other_day",
            "risk_basis": "abs(detection_close_minus_rule_stop)", "shares": 100,
            "decision_delay_seconds": delay_seconds, "cost_per_share_per_side": float(cost_per_share),
            "slippage_bps_per_side": float(slippage_bps)}
    if version in (VERSION, STRICT_VERSION):
        body["sensitivity_cost_per_share_per_side"] = SENSITIVITY_COST_PER_SHARE_PER_SIDE
    if version == VERSION:
        body["selection_gap_rule"] = "occupied_current_bucket;partial_five_minute_bars;resume_after_empty_bucket"
        body["unknown_proxy_busy_rule"] = "conservative_until_baseline_entry_plus_time_stop_or_flat;monetary_result_unresolved"
        body["invalid_frozen_geometry_rule"] = "count_live_signal;invalidate_proxy_without_entry_or_pnl"
    return {**body, "hash": hashlib.sha256(_canonical(body).encode()).hexdigest()}


def scoring_policy(delay_seconds: int = 60, cost_per_share: float = 0, slippage_bps: float = 0) -> dict:
    """Versioned primary proxy and fixed two-cent per-side cost sensitivity."""
    return _scoring_policy(VERSION, delay_seconds, cost_per_share, slippage_bps)


def _policy(policy: dict | None) -> dict:
    if policy is None:
        return scoring_policy()
    version = policy.get("version")
    if version not in (VERSION, STRICT_VERSION, LEGACY_VERSION):
        raise ValueError("Unrecognized scoring policy version")
    expected = _scoring_policy(version, policy["decision_delay_seconds"], policy["cost_per_share_per_side"],
                               policy["slippage_bps_per_side"])
    if policy != expected:
        raise ValueError("Unrecognized or modified scoring policy")
    return expected


def _minutes(rows: list[dict], open_at: int, close_at: int) -> list[dict]:
    result = []
    seen = set()
    for raw in rows:
        at = _epoch(raw["time"])
        end = _epoch(raw.get("end_time", at + 60))
        if not open_at <= at < close_at:
            continue
        if at % 60 or end != at + 60 or at in seen:
            raise ValueError("Minute bars require unique complete one-minute intervals")
        seen.add(at)
        row = {"time": at, "end_time": end}
        for key in ("open", "high", "low", "close", "volume"):
            row[key] = float(raw[key])
        if (not all(math.isfinite(v) for v in row.values()) or row["volume"] < 0
                or row["low"] <= 0 or row["high"] < max(row["open"], row["close"])
                or row["low"] > min(row["open"], row["close"])):
            raise ValueError("Invalid stock minute bar")
        result.append(row)
    return sorted(result, key=lambda r: r["time"])


def _daily(rows: list[dict], day: date) -> list[dict]:
    prior = []
    seen = set()
    for raw in rows:
        stamp = raw.get("date")
        day_of_bar = date.fromisoformat(stamp) if stamp else datetime.fromtimestamp(_epoch(raw["time"]), ET).date()
        if day_of_bar >= day:
            continue
        if day_of_bar in seen:
            raise ValueError("Duplicate daily bar")
        seen.add(day_of_bar)
        bar = {"date": day_of_bar.isoformat()}
        for key in ("high", "low", "close"):
            bar[key] = float(raw[key])
        if not all(math.isfinite(bar[k]) and bar[k] > 0 for k in ("high", "low", "close")) or bar["high"] < max(bar["low"], bar["close"]):
            raise ValueError("Invalid prior daily bar")
        prior.append(bar)
    return sorted(prior, key=lambda r: r["date"])


def _complete_fives(minutes: list[dict], open_at: int, close_at: int) -> list[dict]:
    groups = {}
    for bar in minutes:
        start = open_at + (bar["time"] - open_at) // 300 * 300
        groups.setdefault(start, []).append(bar)
    complete = [bar for start, rows in sorted(groups.items())
                if start + 300 <= close_at and [r["time"] for r in rows] == list(range(start, start + 300, 60))
                for bar in rows]
    return rules.five_minute_bars(complete, open_at, close_at)


def _history_card(history_rows: list[dict], symbol: str, signal: dict, day: date,
                  history_cards: dict | None = None, candidate_id: str | None = None) -> dict:
    # Import only when history is requested. The owning cohort builder is used
    # verbatim; capture CLI does not import this module or the application.
    from app.engine.pretrade_check import history_card, idea_features

    cutoff = datetime.combine(day, time(), ET)
    facts = signal["facts"]
    minutes = int((signal["bar_end"] - datetime.combine(day, time(9, 30), ET).timestamp()) // 60)
    idea = {"ticker": symbol, "side": signal["direction"], "instrument": "option", "horizon": "intraday",
            "option_type": "call" if signal["direction"] == "long" else "put"}
    analysis = {"request": {"instrument": "option", "option_type": idea["option_type"]},
                "data": {"intraday": {"minutes_since_open": minutes,
                                      "price_vs_vwap_pct": facts["vs_vwap_pct"], "rvol": None}}}
    features = idea_features(idea, analysis)
    if history_cards is not None:
        if (not isinstance(history_cards, dict)
                or set(history_cards) != {"format", "source_state", "source_sha256", "generated_at", "cards"}
                or not isinstance(history_cards.get("source_sha256"), str)
                or len(history_cards["source_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in history_cards["source_sha256"])
                or not isinstance(history_cards.get("cards"), dict)):
            raise ValueError("Invalid cutoff history source")
        _epoch(history_cards["generated_at"])
        card = history_cards.get("cards", {}).get(candidate_id)
        if (history_cards.get("format") != "scanner-replay-cutoff-history-v1"
                or history_cards.get("source_state") not in {"fresh", "stale"}
                or not isinstance(card, dict) or set(card) != {"features", "history_cutoff", "history"}
                or card.get("history_cutoff") != cutoff.isoformat()
                or card.get("features") != {k: features[k] for k in ("underlying", "side", "time_bucket", "vwap_bucket")}):
            raise ValueError("Missing or mismatched pre-session history aggregate")
        result = card.get("history")
        if (not isinstance(result, dict) or set(result) != {"as_of_ny", "available", "source_state", "cohorts"}
                or result.get("as_of_ny") != cutoff.isoformat() or result.get("available") is not True
                or result.get("source_state") != history_cards["source_state"]
                or not isinstance(result.get("cohorts"), list) or len(result["cohorts"]) != 2):
            raise ValueError("Invalid pre-session history aggregate")
        allowed = {"name", "definition", "trades", "distinct_days", "distinct_weeks", "enough", "note",
                   "win_rate", "total_pnl", "avg_pnl", "median_return_pct", "median_mfe_pct", "median_mae_pct",
                   "coverage", "loser_pattern"}
        for cohort, name, keys in zip(result["cohorts"], ("same_setup", "same_ticker_side"),
                                      (("underlying", "side", "time_bucket", "vwap_bucket"), ("underlying", "side"))):
            if (not isinstance(cohort, dict) or set(cohort) - allowed or cohort.get("name") != name
                    or cohort.get("definition") != {k: features[k] for k in keys}
                    or any(type(cohort.get(k)) is not int or not 0 <= cohort[k] <= 100000
                           for k in ("trades", "distinct_days", "distinct_weeks"))
                    or type(cohort.get("enough")) is not bool):
                raise ValueError("Invalid pre-session cohort")
            numeric = ("win_rate", "total_pnl", "avg_pnl", "median_return_pct", "median_mfe_pct", "median_mae_pct")
            if (any(k in cohort and cohort[k] is not None
                    and (type(cohort[k]) not in (int, float) or not math.isfinite(cohort[k])) for k in numeric)
                    or any(k in cohort and not isinstance(cohort[k], str) for k in ("note", "loser_pattern"))):
                raise ValueError("Invalid pre-session cohort values")
            coverage = cohort.get("coverage")
            if coverage is not None and (not isinstance(coverage, dict) or set(coverage) != {"pnl", "path"}
                    or any(type(v) is not int or not 0 <= v <= cohort["trades"] for v in coverage.values())):
                raise ValueError("Invalid pre-session cohort coverage")
        _canonical(result)
        return result
    prior = []
    for row in history_rows:
        closed = datetime.fromisoformat(row["closed_at"])
        closed = closed.replace(tzinfo=ET) if closed.tzinfo is None else closed.astimezone(ET)
        if closed < cutoff:
            prior.append({**row, "closed_at": closed.replace(tzinfo=None).isoformat()})
    card = history_card(prior, features, cutoff.astimezone(UTC))
    card.pop("source_fill_keys", None)
    card.update({"as_of_ny": cutoff.isoformat(), "available": bool(history_rows),
                 "source_state": "provided" if history_rows else "missing"})
    return card


def _packet(symbol: str, signal: dict, day: date, retrieved_at: str, minutes: list[dict], daily: list[dict], fives: list[dict],
            history_rows: list[dict], history_cards: dict | None = None) -> dict:
    detected = signal["bar_end"]
    candidate_id = str(uuid.uuid5(NAMESPACE, f"{rules.VERSION}:{day}:{symbol}:{signal['setup']}:{detected}"))
    candidate = {"format": "shadow-setup-v1", "candidate_id": candidate_id, "scanner_version": rules.VERSION,
                 "params_hash": rules.PARAMS_HASH, "session_date": day.isoformat(), "symbol": symbol,
                 "setup": signal["setup"], "direction": signal["direction"],
                 "bar_start": _stamp(signal["bar_start"]), "bar_end": _stamp(detected),
                 "detected_at": _stamp(detected), "expires_at": _stamp(detected + rules.EXPIRY_SECONDS),
                 "stop": signal["stop"], "target": signal["target"], "flags": signal["flags"],
                 "facts": {**signal["facts"], "contract_note": "historical option contract unavailable"},
                 "contract": None, "source": "alpaca_sip_1min_raw"}
    candidate["content_sha256"] = hashlib.sha256(_canonical(candidate).encode()).hexdigest()
    last60 = [{**m, "feed": "sip", "source": "alpaca_sip_raw"} for m in minutes
              if detected - 3600 <= m["time"] and m["end_time"] <= detected]
    published_fives = [{**b, "time": b["start"], "end_time": b["end"], "feed": "sip",
                        "source": "alpaca_sip_raw"} for b in fives if b["end"] <= detected]
    history = _history_card(history_rows, symbol, signal, day, history_cards, candidate_id)
    facts = signal["facts"]
    levels = {"vwap": facts["vwap"], "or5_high": fives[0]["high"] if fives else None,
              "or5_low": fives[0]["low"] if fives else None,
              "or15_high": facts["opening_range_high"], "or15_low": facts["opening_range_low"],
              "premarket_high": None, "premarket_low": None,
              "day_high": max(m["high"] for m in minutes), "day_low": min(m["low"] for m in minutes),
              "prev_close": daily[-1]["close"] if daily else None,
              "today_open": minutes[0]["open"] if minutes else None}
    return {"schema_version": "shadow-setup-v1", "candidate": candidate,
            "live": {"price": facts["close"], "vwap": facts["vwap"], "rvol": None,
                     "market_state": "rth", "scalp_verdict": None, "setup_score": None,
                     "trigger": None, "invalidation": None, "generated_at": _stamp(detected),
                     "staleness": None, "option": None, "source": "alpaca_sip_raw",
                     "source_times": {"last_completed_minute_at": _stamp(detected),
                                      "prior_daily_session": daily[-1]["date"] if daily else None},
                     "levels": levels},
            "history": history, "history_cutoff": datetime.combine(day, time(), ET).isoformat(),
            "labels": [*LABELS, history_label(history)],
            "published_at": _stamp(detected), "expired": False,
            "retrieved_at": retrieved_at, "candles_1m_last60": last60, "candles_5m_session": published_fives,
            "unavailable": ["historical_option_chain", "historical_option_quotes", "historical_rvol", "macro_context"]}


def history_label(history):
    if not history["available"]:
        return "prior-trade-history-unavailable"
    return "informed-by-history" if any(c["trades"] for c in history["cohorts"]) else "history-available-no-matching-trades"


def _unresolved(reason: str, entry_at=None, entry_price=None) -> dict:
    return {"status": "unresolved", "resolved": False, "reason": reason,
            "entry_at": entry_at, "exit_at": None, "entry_price": entry_price,
            "exit_price": None, "raw_entry_price": entry_price, "raw_exit_price": None,
            "net_fees_100": None, "slippage_100": None,
            "r": None, "pnl_100": None, "r_cost_sensitivity": None, "pnl_100_cost_sensitivity": None}


def score_setup(candidate: dict, continuation: dict, session: dict, policy: dict,
                delay_seconds: int = 0) -> dict:
    """Score only sealed post-cutoff bars. Missing eligible minutes stay unresolved."""
    policy = _policy(policy)
    if policy["version"] == LEGACY_VERSION:
        raise ValueError("Legacy v0 policy is readable but its original scores must not be recomputed")
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or delay_seconds < 0:
        raise ValueError("delay_seconds must be a nonnegative integer")
    # The caller supplies the *total* decision delay. The policy's 60-second
    # field is the frozen Jo comparison setting; the rules baseline passes 0.
    delay = delay_seconds
    open_at, close_at = int(session["open_at"]), int(session["close_at"])
    detected = _epoch(candidate["detected_at"])
    if continuation.get("candidate_id") != candidate["candidate_id"] or continuation.get("cutoff_at") != detected:
        raise ValueError("Continuation identity or cutoff mismatch")
    bars = _minutes(continuation["minutes"], open_at, close_at)
    if any(b["time"] < detected for b in bars):
        raise ValueError("Continuation contains a pre-cutoff minute")
    by_time = {b["time"]: b for b in bars}
    direction = candidate["direction"]
    sign = 1 if direction == "long" else -1
    stop, target = float(candidate["stop"]), float(candidate["target"])
    detection_close = float(candidate["facts"]["close"])
    risk = abs(detection_close - stop)
    if risk <= 0 or sign * (detection_close - stop) <= 0 or sign * (target - detection_close) <= 0:
        # The unchanged live scanner can publish a fade whose stale stretch
        # level puts the stop on the wrong side of its detection close. Count
        # that signal, but never invent a valid underlying-share proxy trade.
        return {**_unresolved("invalid_frozen_stop_target_geometry"), "status": "invalidated"}
    eligible = ((detected + delay) // 60 + 1) * 60
    flat = rules.flat_at(open_at, close_at, False)
    if eligible >= flat:
        return {**_unresolved("entry_after_flat"), "status": "invalidated"}
    bar = by_time.get(eligible)
    if bar is None:
        return _unresolved("missing_entry_minute")
    raw_entry = bar["open"]
    if sign * (raw_entry - stop) <= 0 or sign * (target - raw_entry) <= 0:
        return {**_unresolved("entry_open_at_or_beyond_stop_or_target"), "status": "invalidated"}
    time_stop = eligible + rules.TIME_STOP_SECONDS
    for at in range(eligible + 60, min(close_at, max(by_time, default=eligible) + 60), 60):
        row = by_time.get(at)
        if row is None:
            return _unresolved("missing_exit_minute", eligible, round(raw_entry, 4))
        if at >= min(time_stop, flat):
            reason = "time_stop" if time_stop <= flat else "flat"
            raw_exit = row["open"]
            exit_at = at
        else:
            stop_hit = row["low"] <= stop if sign == 1 else row["high"] >= stop
            target_hit = row["high"] >= target if sign == 1 else row["low"] <= target
            if not (stop_hit or target_hit):
                continue
            reason = "stop" if stop_hit else "target"
            if stop_hit:
                raw_exit = min(row["open"], stop) if sign == 1 else max(row["open"], stop)
            else:
                raw_exit = target
            exit_at = row["end_time"]
        gross_share = sign * (raw_exit - raw_entry)
        slip_share = (raw_entry + raw_exit) * policy["slippage_bps_per_side"] / 10_000
        primary_fees_share = 2 * policy["cost_per_share_per_side"]
        sensitivity_fees_share = 2 * policy["sensitivity_cost_per_share_per_side"]
        primary_share = gross_share - slip_share - primary_fees_share
        sensitivity_share = gross_share - slip_share - sensitivity_fees_share
        return {"status": "resolved", "resolved": True, "reason": reason,
                "entry_at": eligible, "exit_at": exit_at, "entry_price": round(raw_entry, 4),
                "exit_price": round(raw_exit, 4), "raw_entry_price": round(raw_entry, 4),
                "raw_exit_price": round(raw_exit, 4), "net_fees_100": round(100 * primary_fees_share, 2),
                "slippage_100": round(100 * slip_share, 2),
                "r": round(primary_share / risk, 4), "pnl_100": round(100 * primary_share, 2),
                "r_cost_sensitivity": round(sensitivity_share / risk, 4),
                "pnl_100_cost_sensitivity": round(100 * sensitivity_share, 2)}
    return _unresolved("continuation_ends_before_exit", eligible, round(raw_entry, 4))


def _session_inputs(bundle: dict, allow_holdout: bool) -> tuple:
    """Validate a captured day once for both parity and strict count-only selection."""
    day = date.fromisoformat(bundle["session_date"])
    if day >= HOLDOUT_START and not allow_holdout:
        raise ValueError("Holdout session requires explicit allow_holdout=True")
    if bundle.get("feed") != "sip" or bundle.get("adjustment") != "raw":
        raise ValueError("Historical scanner capture requires Alpaca SIP raw bars")
    if set(bundle["symbols"]) != set(rules.UNIVERSE):
        raise ValueError("Capture must contain the frozen S1 universe exactly")
    open_at, close_at = int(bundle["open_at"]), int(bundle["close_at"])
    if datetime.fromtimestamp(open_at, ET).date() != day or not open_at < close_at <= open_at + 23400:
        raise ValueError("Invalid regular session calendar")
    retrieved = _epoch(bundle["retrieved_at"])
    if retrieved < close_at:
        raise ValueError("Capture must be retrieved after the session closes")
    last_end = min(int(datetime.combine(day, time(15), ET).timestamp()), close_at - 3600)
    session = {"open_at": open_at, "close_at": close_at}
    daily_by_symbol = {}
    atr_by_symbol = {}
    daily_atr = {}
    missing_daily = []
    for symbol in rules.UNIVERSE:
        daily = _daily(bundle["symbols"][symbol]["daily"], day)
        atr = rules.atr14(daily)
        if len(daily) < 15 or atr is None:
            missing_daily.append(f"{symbol} ({len(daily)} prior sessions)")
        daily_by_symbol[symbol] = daily
        atr_by_symbol[symbol] = atr
        daily_atr[symbol] = {"prior_sessions": len(daily), "atr14": round(atr, 4) if atr is not None else None,
                             "as_of_session": daily[-1]["date"] if daily else None,
                             "source": "alpaca_sip_1day_raw", "feed": "sip", "adjustment": "raw"}
    if missing_daily:
        raise ValueError("Prior daily ATR requires at least 15 sessions for every symbol: " + ", ".join(missing_daily))
    return day, retrieved, session, last_end, daily_by_symbol, atr_by_symbol, daily_atr


def _select_symbol(symbol: str, day: date, minutes: list[dict], atr: float, session: dict,
                   last_end: int, policy: dict, *, strict: bool) -> list[dict]:
    """Select with live sparse-bucket semantics, or the superseded v1 strict rule."""
    open_at, close_at = session["open_at"], session["close_at"]
    by_time = {m["time"]: m for m in minutes}
    taken: set[tuple[str, int]] = set()
    selected = []
    for bar_end in range(open_at + rules.BAR_SECONDS, last_end + 1, rules.BAR_SECONDS):
        if strict and any(at not in by_time for at in range(open_at, bar_end, 60)):
            break
        prefix = [m for m in minutes if m["end_time"] <= bar_end]
        if not strict and not any(m["time"] >= bar_end - rules.BAR_SECONDS for m in prefix):
            continue
        fives = (_complete_fives(prefix, open_at, close_at) if strict
                 else rules.five_minute_bars(prefix, open_at, close_at))
        signal_list = rules.scan(fives, atr, open_at, last_end, taken)
        signal = signal_list[-1] if signal_list and signal_list[-1]["bar_end"] == bar_end else None
        if signal is None:
            continue
        busy = False
        for prior in selected:
            cutoff = prior["signal"]["bar_end"]
            partial = {"candidate_id": prior["candidate"]["candidate_id"], "cutoff_at": cutoff,
                       "minutes": [m for m in minutes if cutoff <= m["time"] and m["end_time"] <= bar_end]}
            state = score_setup(prior["candidate"], partial, session, policy)
            unknown_open = state["status"] == "unresolved"
            if unknown_open and not strict:
                # Missing prices cannot establish an early stop/target. Bound
                # this conservative unknown hold by the fixed proxy clock;
                # scoring remains unresolved rather than fabricating an exit.
                baseline_entry = (cutoff // 60 + 1) * 60
                deadline = min(baseline_entry + rules.TIME_STOP_SECONDS,
                               rules.flat_at(open_at, close_at, False))
                unknown_open = bar_end < deadline
            if unknown_open or (state["exit_at"] is not None and state["exit_at"] > bar_end):
                busy = True
                break
        if busy or (selected and selected[-1]["signal"]["bar_end"] > bar_end - rules.COOLDOWN_SECONDS):
            continue
        candidate_id = str(uuid.uuid5(NAMESPACE, f"{rules.VERSION}:{day}:{symbol}:{signal['setup']}:{bar_end}"))
        candidate = {"candidate_id": candidate_id, "detected_at": _stamp(bar_end),
                     "direction": signal["direction"], "stop": signal["stop"], "target": signal["target"],
                     "facts": {"close": signal["facts"]["close"]}}
        selected.append({"signal": signal, "prefix": prefix, "fives": fives, "candidate": candidate})
        taken.add((signal["setup"], bar_end))
    return selected


def strict_v1_setup_counts(bundle: dict, *, scoring_policy: dict | None = None,
                           allow_holdout: bool = False) -> dict:
    """Compare old strict v1 counts by symbol and setup, without packets or choices."""
    policy = _policy(scoring_policy)
    if policy["version"] == LEGACY_VERSION:
        raise ValueError("Legacy v0 scores must not be recomputed")
    day, _, session, last_end, _, atr_by_symbol, _ = _session_inputs(bundle, allow_holdout)
    counts = {}
    by_symbol_setup = {}
    by_setup = {key: 0 for key in SETUP_COUNT_KEYS}
    for symbol in rules.UNIVERSE:
        minutes = _minutes(bundle["symbols"][symbol]["minutes"], session["open_at"], session["close_at"])
        selected = _select_symbol(symbol, day, minutes, atr_by_symbol[symbol], session,
                                  last_end, policy, strict=True)
        setup_counts = {key: 0 for key in SETUP_COUNT_KEYS}
        for item in selected:
            signal = item["signal"]
            key = f"{signal['setup']}:{signal['direction']}"
            if key not in setup_counts:
                raise ValueError("Unrecognized frozen scanner setup")
            setup_counts[key] += 1
            by_setup[key] += 1
        counts[symbol] = len(selected)
        by_symbol_setup[symbol] = setup_counts
    return {"version": STRICT_VERSION, "symbols": counts, "by_setup": by_setup,
            "by_symbol_setup": by_symbol_setup, "total": sum(counts.values())}


def generate_session(bundle: dict, *, scoring_policy: dict | None = None,
                     history_rows: list[dict] | None = None, history_cards: dict | None = None,
                     allow_holdout: bool = False) -> dict:
    """Stream available completed bars through live S1 buckets, then seal continuations."""
    policy = _policy(scoring_policy)
    if policy["version"] != VERSION:
        raise ValueError("Superseded policy is retained for reading, not new generation")
    if history_rows and history_cards is not None:
        raise ValueError("Choose feature rows or cutoff aggregate cards, not both")
    day, retrieved, session, last_end, daily_by_symbol, atr_by_symbol, daily_atr = _session_inputs(bundle, allow_holdout)
    open_at, close_at = session["open_at"], session["close_at"]
    setups, gaps = [], []
    coverage_symbols = {}
    eligible_scan_ends = list(range(open_at + rules.FIRST_BAR_AFTER + rules.BAR_SECONDS, last_end + 1,
                                    rules.BAR_SECONDS))
    expected_regular = (close_at - open_at) // 60
    for symbol in rules.UNIVERSE:
        source = bundle["symbols"][symbol]
        minutes = _minutes(source["minutes"], open_at, close_at)
        daily = daily_by_symbol[symbol]
        atr = atr_by_symbol[symbol]
        by_time = {m["time"]: m for m in minutes}
        first_missing = next((at for at in range(open_at, close_at, 60) if at not in by_time), None)
        bucket_counts = {end: sum(end - rules.BAR_SECONDS <= m["time"] < end for m in minutes)
                         for end in range(open_at + rules.BAR_SECONDS, last_end + 1, rules.BAR_SECONDS)}
        blocked_slots = sum(bucket_counts[end] == 0 for end in eligible_scan_ends)
        partial_slots = sum(0 < bucket_counts[end] < 5 for end in eligible_scan_ends)
        selected = _select_symbol(symbol, day, minutes, atr, session, last_end, policy, strict=False)
        strict_selected = (_select_symbol(symbol, day, minutes, atr, session, last_end, policy, strict=True)
                           if first_missing is not None else selected)
        coverage_symbols[symbol] = {"expected_minutes": expected_regular,
            "provided_minutes": len(minutes), "missing_minutes": expected_regular - len(minutes),
            "first_missing_at": _stamp(first_missing) if first_missing is not None else None,
            "first_missing_epoch": first_missing,
            "eligible_scan_slots": len(eligible_scan_ends),
            "evaluated_scan_slots": len(eligible_scan_ends) - blocked_slots,
            "blocked_scan_slots": blocked_slots,
            "scan_minutes_lost": blocked_slots * 5,
            "affected_five_minute_buckets": sum(count < 5 for count in bucket_counts.values()),
            "partial_five_minute_buckets": sum(0 < count < 5 for count in bucket_counts.values()),
            "empty_five_minute_buckets": sum(count == 0 for count in bucket_counts.values()),
            "partial_scan_buckets": partial_slots, "empty_scan_buckets": blocked_slots,
            "setups_emitted": len(selected), "strict_v1_setups_emitted": len(strict_selected),
            "parity_minus_strict_setups": len(selected) - len(strict_selected),
            "actual_suppressed_setups": None}
        if first_missing is not None:
            gaps.append({"symbol": symbol, "reason": "missing_completed_minute", "at": first_missing,
                         "missing_minutes": expected_regular - len(minutes),
                         "blocked_scan_slots": blocked_slots, "partial_scan_buckets": partial_slots,
                         "actual_suppressed_setups": None})
        for item in selected:
            signal, prefix, fives = item["signal"], item["prefix"], item["fives"]
            bar_end = signal["bar_end"]
            packet = _packet(symbol, signal, day, _stamp(retrieved), prefix, daily, fives, history_rows or [], history_cards)
            candidate = packet["candidate"]
            continuation = {"version": VERSION, "nonce": secrets.token_hex(32),
                            "candidate_id": candidate["candidate_id"], "cutoff_at": bar_end,
                            "minutes": [m for m in minutes if m["time"] >= bar_end]}
            setups.append({"packet": packet, "continuation": continuation})
    setups.sort(key=lambda item: (item["packet"]["candidate"]["bar_end"], item["packet"]["candidate"]["symbol"]))
    sums = ("expected_minutes", "provided_minutes", "missing_minutes",
            "eligible_scan_slots", "evaluated_scan_slots", "blocked_scan_slots",
            "scan_minutes_lost", "affected_five_minute_buckets", "partial_five_minute_buckets",
            "empty_five_minute_buckets", "partial_scan_buckets", "empty_scan_buckets",
            "setups_emitted", "strict_v1_setups_emitted", "parity_minus_strict_setups")
    totals = {key: sum(row[key] for row in coverage_symbols.values()) for key in sums}
    coverage = {"session_date": day.isoformat(), "scan_end_at": _stamp(last_end),
                "symbols": coverage_symbols,
                "totals": {**totals, "actual_suppressed_setups": None},
                "suppressed_setup_note": "Strict v1 versus live-bucket v2 counts are observable; actual setups absent from provider data are unknowable. No bars are inferred."}
    return {"session_date": day.isoformat(), "retrieved_at": _stamp(retrieved), "session": session,
            "setups": setups, "differences": list(DIFFERENCES), "gaps": gaps,
            "coverage": coverage, "daily_atr": daily_atr,
            "scanner_version": rules.VERSION, "params_hash": rules.PARAMS_HASH, "scoring_policy": policy,
            "labels": [*LABELS, *sorted({history_label(s["packet"]["history"]) for s in setups})]}
