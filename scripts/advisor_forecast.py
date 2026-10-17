"""Isolated prospective forecast math and preparation CLI; no application imports."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "research/advisor-forecast"
FIELDS = {"direction", "terminal_price", "low", "high", "support", "invalidation", "uncertainty"}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(ET)


def at(day, hhmmss):
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmmss), ET)


def timing(spec):
    start = time.fromisoformat(spec["snapshot"]["capture_start"])
    end = time.fromisoformat(spec["snapshot"]["forecast_end"])
    return start.hour * 60 + start.minute, end.hour * 60 + end.minute


def with_timing(spec, offset):
    if offset not in spec["timing_policy"]["allowed_offsets_minutes"]:
        raise ValueError("timing offset outside preregistration")
    result = json.loads(json.dumps(spec))
    for field, base in (("completed_by", "09:59:00"), ("last_bar_start", "09:58:00"), ("capture_start", "10:00:00"), ("capture_deadline", "10:00:30"), ("submission_deadline", "10:02:00")):
        result["snapshot"][field] = (at("2098-01-01", base) + timedelta(minutes=offset)).time().isoformat()
    result["timing_offset_minutes"] = offset
    result["snapshot"]["reference_price"] = "close of minute starting " + result["snapshot"]["last_bar_start"]
    result["snapshot"]["direction_reference"] = "open of minute starting " + result["snapshot"]["capture_start"] + ", scoring only"
    result["snapshot"]["path"] = f"all minute bars from {result['snapshot']['capture_start']} up to but excluding 11:00"
    return result


def number(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("finite numeric value required")
    return value


def exclusive_json(path, value):
    """Atomic create-only receipt. A duplicate invocation cannot replace evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write(encoded(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def classify(change, threshold):
    number(change)
    number(threshold, positive=True)
    # Small arithmetic tolerance preserves inclusive decimal boundaries.
    return "up" if change > threshold + 1e-12 else "down" if change < -threshold - 1e-12 else "sideways"


def quantile(values, q):
    return sorted(values)[max(0, math.ceil(round(len(values) * q, 10)) - 1)]


def window(day, rows, start_minute, count):
    """Fail closed on extra/future, duplicate, stale, malformed or missing bars."""
    expected = [at(day, "00:00:00") + timedelta(minutes=start_minute + i) for i in range(count)]
    if len(rows) != count or [stamp(row["t"]) for row in rows] != expected:
        raise ValueError("bars must match every expected minute exactly")
    result = []
    for row in rows:
        clean = {k: number(row[k], positive=k != "v") for k in ("o", "h", "l", "c", "v")}
        if clean["v"] < 0 or not clean["l"] <= min(clean["o"], clean["c"]) <= max(clean["o"], clean["c"]) <= clean["h"]:
            raise ValueError("invalid OHLCV")
        result.append({"t": stamp(row["t"]).isoformat(), **clean})
    return result


def history_stats(day, history, prior_sessions, spec):
    if len(prior_sessions) != spec["history_sessions"] or prior_sessions != sorted(set(prior_sessions)) or any(d >= day for d in prior_sessions):
        raise ValueError("exact prior 20 ordered sessions required")
    if set(history) != set(prior_sessions):
        raise ValueError("missing history; do not skip to older sessions")
    changes, downs, ups = [], [], []
    start, end = timing(spec)
    for d in prior_sessions:
        bars = window(d, history[d], 570, end - 570)
        ref = bars[start - 572]["c"]
        path = bars[start - 570:]
        changes.append(abs(path[-1]["c"] / path[0]["o"] - 1))
        downs.append(min(0, min(b["l"] for b in path) / ref - 1))
        ups.append(max(0, max(b["h"] for b in path) / ref - 1))
    threshold = statistics.median(changes) * spec["sideways_multiplier"]
    low = quantile(downs, 1 - spec["range_quantile"])
    high = quantile(ups, spec["range_quantile"])
    if threshold <= 0 or high <= low:
        raise ValueError("degenerate historical scale")
    return {"sideways_threshold": threshold, "baseline_low_return": low, "baseline_high_return": high,
            "history_hash": digest(history), "prior_sessions": prior_sessions}


def snapshot(day, ticker, current, history, prior_sessions, captured_at, spec):
    captured_at = stamp(captured_at)
    if ticker not in spec["tickers"] or not at(day, spec["snapshot"]["capture_start"]) <= captured_at <= at(day, spec["snapshot"]["capture_deadline"]):
        raise ValueError("snapshot outside capture window/universe")
    start, _ = timing(spec)
    bars = window(day, current, 570, start - 571)
    stats = history_stats(day, history, prior_sessions, spec)
    ref = bars[-1]["c"]
    low, high = ref * (1 + stats["baseline_low_return"]), ref * (1 + stats["baseline_high_return"])
    return {"session": day, "ticker": ticker, "captured_at": captured_at.isoformat(), "spec_hash": digest(spec),
            "provider": spec["provider"], "bars": bars, "reference_price": ref, "timing": spec["snapshot"],
            "baseline_low": low, "baseline_high": high,
            "width_cap_usd": (high - low) * spec["range_width_cap_multiplier"],
            "baseline_directions": {"sideways": "sideways", "up": "up", "down": "down",
                                    "opening_continuation": classify(ref / bars[0]["o"] - 1, stats["sideways_threshold"])}, **stats}


def validate_prediction(prediction, packet):
    if not isinstance(prediction, dict) or set(prediction) != FIELDS or prediction["direction"] not in ("up", "down", "sideways", "abstain"):
        raise ValueError("invalid forecast schema")
    if any(not isinstance(prediction[k], str) or not prediction[k].strip() or len(prediction[k]) > 1500 for k in ("support", "invalidation", "uncertainty")):
        raise ValueError("conditions and uncertainty required")
    if prediction["direction"] == "abstain":
        if any(prediction[k] is not None for k in ("terminal_price", "low", "high")):
            raise ValueError("abstention prices must be null")
        return "abstain"
    low, high, end = [number(prediction[k], positive=True) for k in ("low", "high", "terminal_price")]
    if not low <= packet["reference_price"] <= high or not low <= end <= high or high <= low:
        raise ValueError("range must contain reference and terminal prediction")
    if high - low > packet["width_cap_usd"] + 1e-9:
        raise ValueError("range width cap exceeded")
    return "answered"


def receipt(packet, prediction, started_at, saved_at, spec):
    started_at, saved_at = stamp(started_at), stamp(saved_at)
    if not stamp(packet["captured_at"]) <= started_at <= saved_at:
        raise ValueError("invalid receipt chronology")
    status = validate_prediction(prediction, packet)
    if saved_at > at(packet["session"], spec["snapshot"]["submission_deadline"]):
        status = "late"
    return {"session": packet["session"], "ticker": packet["ticker"], "snapshot_hash": digest(packet),
            "spec_hash": digest(spec), "started_at": started_at.isoformat(),
            "saved_at": saved_at.isoformat(), "latency_seconds": (saved_at - started_at).total_seconds(),
            "seconds_after_snapshot_time": (saved_at - at(packet["session"], spec["snapshot"]["capture_start"])).total_seconds(),
            "status": status, "prediction": prediction}


def outcome(day, ticker, bars, captured_at, spec):
    if not at(day, "11:05:00") <= stamp(captured_at) <= at(day, "11:06:00"):
        raise ValueError("outcome capture window exceeded")
    start, end = timing(spec)
    bars = window(day, bars, start, end - start)
    return {"session": day, "ticker": ticker, "captured_at": stamp(captured_at).isoformat(),
            "start": bars[0]["o"], "terminal": bars[-1]["c"], "low": min(b["l"] for b in bars),
            "high": max(b["h"] for b in bars), "bars": bars}


def metrics(cases, spec):
    counts = Counter(c["status"] for c in cases)
    answered = [c for c in cases if c["status"] == "answered" and c.get("outcome")]
    available = [c for c in cases if c.get("outcome") and c.get("snapshot")]
    labels, confusion = {}, Counter()
    for c in available:
        o, p = c["outcome"], c["snapshot"]
        labels[(c["session"], c["ticker"])] = classify(o["terminal"] / o["start"] - 1, p["sideways_threshold"])
    def accuracy(name, selected):
        return sum(c["snapshot"]["baseline_directions"][name] == labels[(c["session"], c["ticker"])] for c in selected) / len(selected) if selected else None
    widths, baseline_widths, covered, baseline_covered, terminal_errors, low_errors, high_errors = [], [], [], [], [], [], []
    correct = 0
    for c in answered:
        f, p, o = c["receipt"]["prediction"], c["snapshot"], c["outcome"]
        actual = labels[(c["session"], c["ticker"])]
        correct += f["direction"] == actual
        confusion[(actual, f["direction"])] += 1
        ref = p["reference_price"]
        widths.append((f["high"] - f["low"]) / ref)
        baseline_widths.append((p["baseline_high"] - p["baseline_low"]) / ref)
        covered.append(f["low"] <= o["low"] and f["high"] >= o["high"])
        baseline_covered.append(p["baseline_low"] <= o["low"] and p["baseline_high"] >= o["high"])
        terminal_errors.append(abs(f["terminal_price"] - o["terminal"]) / ref)
        low_errors.append(abs(f["low"] - o["low"]) / ref)
        high_errors.append(abs(f["high"] - o["high"]) / ref)
    def mean(xs):
        return statistics.mean(xs) if xs else None
    latency = [c["receipt"]["latency_seconds"] for c in cases if c.get("receipt")]
    baselines = {name: accuracy(name, answered) for name in spec["direction_baselines"]}
    result = {"cases": len(cases), "statuses": dict(counts), "answer_fraction": counts["answered"] / len(cases),
              "abstention_fraction": counts["abstain"] / len(cases), "scored_answers": len(answered),
              "direction_accuracy": correct / len(answered) if answered else None,
              "baseline_direction_on_answered": baselines,
              "baseline_direction_on_available": {name: accuracy(name, available) for name in spec["direction_baselines"]},
              "baseline_available_cases": len(available),
              "confusion": {f"{a}->{b}": n for (a, b), n in sorted(confusion.items())},
              "range_coverage": mean(covered), "baseline_range_coverage": mean(baseline_covered),
              "mean_width_fraction": mean(widths), "baseline_mean_width_fraction": mean(baseline_widths),
              "terminal_mae_fraction": mean(terminal_errors), "low_mae_fraction": mean(low_errors), "high_mae_fraction": mean(high_errors),
              "latency_median_seconds": statistics.median(latency) if latency else None,
              "latency_max_seconds": max(latency) if latency else None}
    result["direction_advantage"] = result["direction_accuracy"] - max(baselines.values()) if answered else None
    result["range_advantage"] = mean(covered) - mean(baseline_covered) if answered else None
    result["per_class_recall"] = {label: sum(n for (a, b), n in confusion.items() if a == b == label) / sum(n for (a, _), n in confusion.items() if a == label)
                                  if any(a == label for a, _ in confusion) else None for label in ("up", "down", "sideways")}
    return result


def score(sessions, records, spec, now):
    """One complete registered evaluation, never a partial convenience subset."""
    if len(sessions) != spec["sample"]["evaluation_sessions"] or sessions != sorted(set(sessions)):
        raise ValueError("complete registered evaluation calendar required")
    if stamp(now) < at(sessions[-1], "11:06:00"):
        raise ValueError("interim scoring prohibited")
    expected = {(d, t) for d in sessions for t in spec["tickers"]}
    indexed = {}
    for c in records:
        key = (c["session"], c["ticker"])
        if key not in expected or key in indexed:
            raise ValueError("duplicate or out-of-sample case")
        indexed[key] = c
    cases, faults = [], []
    for day, ticker in sorted(expected):
        c = dict(indexed.get((day, ticker), {"session": day, "ticker": ticker}))
        c["status"] = "missing"
        p, r, o = c.get("snapshot"), c.get("receipt"), c.get("outcome")
        if p:
            if p["spec_hash"] != digest(spec) or (p["session"], p["ticker"]) != (day, ticker):
                raise ValueError("snapshot provenance mismatch")
        if r and p:
            if r["snapshot_hash"] != digest(p) or r["spec_hash"] != digest(spec) or (r["session"], r["ticker"]) != (day, ticker):
                raise ValueError("receipt provenance mismatch")
            rebuilt = receipt(p, r["prediction"], r["started_at"], r["saved_at"], spec)
            if rebuilt != r:
                raise ValueError("receipt integrity mismatch")
            c["status"] = r["status"]
        elif c.get("failure") in ("late", "invalid", "data_missing", "model_error"):
            c["status"] = c["failure"]
        if o:
            if outcome(day, ticker, o["bars"], o["captured_at"], spec) != o:
                raise ValueError("outcome provenance mismatch")
        else:
            faults.append(f"missing outcome:{day}:{ticker}")
        cases.append(c)
    audits = {}
    for d in sessions:
        evidence = [c.get("audit") for c in cases if c["session"] == d]
        audit = evidence[0] if evidence else None
        if any(e != audit for e in evidence):
            raise ValueError("inconsistent session audit")
        audits[d] = audit or {"web_status": "unverified", "model_name": None}
        if (not audit or audit.get("web_status") != "verified_no_external_access"
                         or audit.get("evidence_type") not in ("complete_platform_trace", "verified_task_tool_isolation")
                         or not isinstance(audit.get("evidence_sha256"), str) or len(audit["evidence_sha256"]) != 64):
            faults.append("web/tool isolation unverified or violated:" + d)
    missing_days = sorted({c["session"] for c in cases if c["status"] not in ("answered", "abstain")})
    if len(missing_days) > spec["gates"]["maximum_missing_sessions"]:
        faults.append("more than three missing evaluation sessions; no extension/restart")
    overall = metrics(cases, spec)
    g = spec["gates"]
    passed = (not faults and overall["answer_fraction"] >= g["answer_fraction"] and overall["scored_answers"] > 0
              and overall["direction_advantage"] >= g["direction_advantage"] - 1e-12
              and overall["range_advantage"] >= g["range_advantage"] - 1e-12
              and overall["mean_width_fraction"] <= overall["baseline_mean_width_fraction"] + 1e-12)
    return {"protocol": spec["protocol"], "spec_hash": digest(spec), "verdict": "invalid" if faults else "replication_only" if passed else "stop_directional_development",
            "faults": faults, "missing_sessions": missing_days, "overall": overall,
            "by_session": {d: metrics([c for c in cases if c["session"] == d], spec) for d in sessions},
            "access_audits": audits, "model_pinned": False,
            "observed_model_names": sorted({a["model_name"] for a in audits.values() if a.get("model_name") and a.get("model_source") == "platform"}),
            "interpretation": "Hosted Jo under frozen task protocol; model unpinned, unknown metadata remains unknown. Correlated exploratory sample, not trading returns or validated skill."}


def fixture_bars(day, start=570, count=90):
    result = []
    for minute in range(start, start + count):
        close = 101 if minute == 659 else 100
        result.append({"t": (at(day, "00:00:00") + timedelta(minutes=minute)).isoformat(), "o": 100, "c": close, "h": 102, "l": 99, "v": 1000})
    return result


def dry_run(output, spec):
    """Explicit invented dates/bars/answers; never a historical or model experiment."""
    spec = with_timing(spec, 0)
    prior = [f"2098-01-{i:02d}" for i in range(1, 21)]
    sessions = [(date(2098, 2, 1) + timedelta(days=i)).isoformat() for i in range(20)]
    records = []
    for day in sessions:
        for ticker in spec["tickers"]:
            history = {d: fixture_bars(d) for d in prior}
            p = snapshot(day, ticker, fixture_bars(day, count=29), history, prior, at(day, "10:00:05"), spec)
            prediction = {"direction": "up", "terminal_price": 101, "low": 99, "high": 102,
                          "support": "Synthetic fixture only", "invalidation": "Synthetic fixture only", "uncertainty": "Invented, not a forecast"}
            r = receipt(p, prediction, at(day, "10:00:06"), at(day, "10:00:07"), spec)
            o = outcome(day, ticker, fixture_bars(day, 600, 60), at(day, "11:05:05"), spec)
            records.append({"session": day, "ticker": ticker, "snapshot": p, "receipt": r, "outcome": o,
                            "audit": {"web_status": "verified_no_external_access", "evidence_type": "complete_platform_trace", "evidence_sha256": digest({"synthetic_fixture": True}), "model_name": None, "model_source": "unavailable", "synthetic_fixture": True}})
    report = score(sessions, records, spec, at(sessions[-1], "11:06:00"))
    assert report["overall"]["direction_accuracy"] == 1
    assert report["overall"]["direction_advantage"] == 0  # always-up ties
    assert report["overall"]["range_advantage"] == 0
    assert report["verdict"] == "stop_directional_development"
    exclusive_json(Path(output) / "synthetic-example.json", records[0])
    exclusive_json(Path(output) / "dry-run.json", {"synthetic_only": True, "model_calls": 0, "provider_calls": 0, "hand_check": "100->101 = +1%; sideways threshold .25%; interval 99..102 width3 contains path; always-up and history tie, so gates fail", "report": report})
    return {"synthetic_only": True, "model_calls": 0, "provider_calls": 0, "cases": len(records), "verdict": report["verdict"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["dry-run"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(dry_run(args.output, read_json(SPEC_DIR / "spec.json"))))


if __name__ == "__main__":
    main()
