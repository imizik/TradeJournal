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
VERSION = "scanner-selection-replay-v0"
HOLDOUT_START = date(2026, 9, 14)
NAMESPACE = uuid.UUID("e67f01c8-bc75-4f76-b77c-d92313cfdb16")
LABELS = ["informed-by-history", "independence-unverified", "model-memory-unverified",
          "no-historical-news", "underlying-scored", "basis-unverified"]
DIFFERENCES = (
    "Historical Alpaca SIP raw stock bars replace live Tradier timesales and daily history; exact live signals may differ.",
    "Historical option chains, quotes, delta, liquidity and fills are unavailable; no option contract or premium P&L is inferred.",
    "Scanner cooldown, fade limits and busy state use an underlying-share proxy, not live option trade state.",
    "Entry and exit use completed minute stock bars and an explicit simulated clock; no live monitoring latency or quote freshness is reproduced.",
    "Daily ATR uses only prior raw stock sessions; historical intraday relative volume and macro context are unavailable.",
    "No historical corporate-action coverage verifies raw share basis across the ATR lookback.",
    "A missing minute blocks later setup selection for that symbol; complete five-minute bars match the live scanner on complete data.",
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


def scoring_policy(delay_seconds: int = 60, cost_per_share: float = 0, slippage_bps: float = 0) -> dict:
    """Fixed share proxy: costs are dollars per share per side, slippage is adverse per side."""
    if isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or not 0 <= delay_seconds <= 600:
        raise ValueError("delay_seconds must be an integer from 0 to 600")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in (cost_per_share, slippage_bps)):
        raise ValueError("Proxy costs must be finite and nonnegative")
    body = {"version": VERSION, "entry": "first_full_minute_after_detection_plus_delay_open",
            "exit": "completed_minute_stop_first_then_target; clock_at_first_eligible_open",
            "entry_minute_stop_check": False, "favorable_target_price_cap": True,
            "time_stop_seconds": rules.TIME_STOP_SECONDS, "flat_rule": "scanner_s1_other_day",
            "risk_basis": "abs(detection_close_minus_rule_stop)", "shares": 100,
            "decision_delay_seconds": delay_seconds, "cost_per_share_per_side": float(cost_per_share),
            "slippage_bps_per_side": float(slippage_bps)}
    return {**body, "hash": hashlib.sha256(_canonical(body).encode()).hexdigest()}


def _policy(policy: dict | None) -> dict:
    if policy is None:
        return scoring_policy()
    expected = scoring_policy(policy["decision_delay_seconds"], policy["cost_per_share_per_side"],
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


def _history_card(history_rows: list[dict], symbol: str, signal: dict, day: date) -> dict:
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
    prior = []
    for row in history_rows:
        closed = datetime.fromisoformat(row["closed_at"])
        closed = closed.replace(tzinfo=ET) if closed.tzinfo is None else closed.astimezone(ET)
        if closed < cutoff:
            prior.append({**row, "closed_at": closed.replace(tzinfo=None).isoformat()})
    card = history_card(prior, idea_features(idea, analysis), cutoff.astimezone(UTC))
    card.pop("source_fill_keys", None)
    card.update({"as_of_ny": cutoff.isoformat(), "available": bool(history_rows),
                 "source_state": "provided" if history_rows else "missing"})
    return card


def _packet(symbol: str, signal: dict, day: date, retrieved_at: str, minutes: list[dict], daily: list[dict], fives: list[dict],
            history_rows: list[dict]) -> dict:
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
    history = _history_card(history_rows, symbol, signal, day)
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
            "labels": list(LABELS), "published_at": _stamp(detected), "expired": False,
            "retrieved_at": retrieved_at, "candles_1m_last60": last60, "candles_5m_session": published_fives,
            "unavailable": ["historical_option_chain", "historical_option_quotes", "historical_rvol", "macro_context"]}


def _unresolved(reason: str, entry_at=None, entry_price=None) -> dict:
    return {"status": "unresolved", "resolved": False, "reason": reason,
            "entry_at": entry_at, "exit_at": None, "entry_price": entry_price,
            "exit_price": None, "r": None, "pnl_100": None}


def score_setup(candidate: dict, continuation: dict, session: dict, policy: dict,
                delay_seconds: int = 0) -> dict:
    """Score only sealed post-cutoff bars. Missing eligible minutes stay unresolved."""
    policy = _policy(policy)
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
        raise ValueError("Invalid frozen stop/target geometry")
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
    slip = policy["slippage_bps_per_side"] / 10_000
    cost = policy["cost_per_share_per_side"]
    entry = raw_entry * (1 + sign * slip) + sign * cost
    if sign * (target - entry) <= 0:
        return {**_unresolved("cost_adjusted_entry_at_or_beyond_target"), "status": "invalidated"}
    time_stop = eligible + rules.TIME_STOP_SECONDS
    for at in range(eligible + 60, min(close_at, max(by_time, default=eligible) + 60), 60):
        row = by_time.get(at)
        if row is None:
            return _unresolved("missing_exit_minute", eligible, round(entry, 4))
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
        exit_price = raw_exit * (1 - sign * slip) - sign * cost
        pnl_share = sign * (exit_price - entry)
        return {"status": "resolved", "resolved": True, "reason": reason,
                "entry_at": eligible, "exit_at": exit_at, "entry_price": round(entry, 4),
                "exit_price": round(exit_price, 4), "r": round(pnl_share / risk, 4),
                "pnl_100": round(100 * pnl_share, 2)}
    return _unresolved("continuation_ends_before_exit", eligible, round(entry, 4))


def generate_session(bundle: dict, *, scoring_policy: dict | None = None,
                     history_rows: list[dict] | None = None, allow_holdout: bool = False) -> dict:
    """Stream completed bars through unchanged S1 scanner rules, then seal each continuation."""
    policy = _policy(scoring_policy)
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
    setups, gaps = [], []
    for symbol in rules.UNIVERSE:
        source = bundle["symbols"][symbol]
        minutes = _minutes(source["minutes"], open_at, close_at)
        daily = _daily(source["daily"], day)
        atr = rules.atr14(daily)
        if atr is None:
            gaps.append({"symbol": symbol, "reason": "prior_daily_atr14_unavailable"})
            continue
        by_time = {m["time"]: m for m in minutes}
        taken: set[tuple[str, int]] = set()
        saved = []
        for bar_end in range(open_at + 300, last_end + 1, 300):
            if any(at not in by_time for at in range(open_at, bar_end, 60)):
                gaps.append({"symbol": symbol, "reason": "missing_completed_minute", "at": bar_end})
                break
            prefix = [by_time[at] for at in range(open_at, bar_end, 60)]
            fives = _complete_fives(prefix, open_at, close_at)
            signal_list = rules.scan(fives, atr, open_at, last_end, taken)
            signal = signal_list[-1] if signal_list and signal_list[-1]["bar_end"] == bar_end else None
            if signal is None:
                continue
            busy = False
            for prior in saved:
                partial = {**prior["continuation"], "minutes": [m for m in minutes
                           if prior["continuation"]["cutoff_at"] <= m["time"] and m["end_time"] <= bar_end]}
                state = score_setup(prior["packet"]["candidate"], partial, session, policy)
                if state["status"] == "unresolved" or (state["exit_at"] is not None and state["exit_at"] > bar_end):
                    busy = True
                    break
            if busy or (saved and saved[-1]["continuation"]["cutoff_at"] > bar_end - rules.COOLDOWN_SECONDS):
                continue
            packet = _packet(symbol, signal, day, _stamp(retrieved), prefix, daily, fives, history_rows or [])
            candidate = packet["candidate"]
            continuation = {"version": VERSION, "nonce": secrets.token_hex(32),
                            "candidate_id": candidate["candidate_id"], "cutoff_at": bar_end,
                            "minutes": [m for m in minutes if m["time"] >= bar_end]}
            setups.append({"packet": packet, "continuation": continuation})
            saved.append(setups[-1])
            taken.add((signal["setup"], bar_end))
    setups.sort(key=lambda item: (item["packet"]["candidate"]["bar_end"], item["packet"]["candidate"]["symbol"]))
    return {"session_date": day.isoformat(), "retrieved_at": _stamp(retrieved), "session": session,
            "setups": setups, "differences": list(DIFFERENCES), "gaps": gaps,
            "scanner_version": rules.VERSION, "params_hash": rules.PARAMS_HASH, "scoring_policy": policy}
