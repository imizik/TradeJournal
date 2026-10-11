"""R2 descriptive discovery analysis on supplied immutable R1 observations."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Callable

import numpy as np

from app.engine.factory_data import prior
from app.engine.market_map import ET
from app.engine.research_studio import Definition, Observations, session_close

HORIZONS = ("15m", "30m", "60m", "session_close")
UNITS = ("percent", "prior_daily_atr14")
SPEC = {
    "version": "research-analysis-v1", "primary_horizon": "30m",
    "reference": "immediate next complete five-minute bucket open, same session",
    "endpoints": "exact completed closes at reference+15/30/60 minutes or scheduled session close",
    "units": list(UNITS), "baseline": "ordinary eligible moments including qualifiers, event symbol/clock weights",
    "uncertainty": "joint calendar-week blocks, all symbols together, composition recomputed per draw",
    "draws": 2000, "generator": "NumPy PCG64", "seed": 0, "level": .95,
    "percentile": "linear", "minimum_weeks": 20, "minimum_valid_draws": 1900,
    "week_independence": "approximation; adaptive research is not independent validation",
}


class Cancelled(Exception):
    """An explicit research cancellation, never a valid partial result."""


@dataclass(frozen=True, slots=True)
class _Row:
    symbol: str
    decision_time: str
    clock: int
    week: str
    values: tuple
    reasons: tuple


def _compact(row: dict) -> _Row:
    return _Row(row["symbol"], row["decision_time"], row["clock"], row["week"],
                tuple(tuple(row["outcomes"][h][u] for u in UNITS) for h in HORIZONS),
                tuple(tuple(row["outcomes"][h][u + "_reason"] for u in UNITS) for h in HORIZONS))


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def analysis_id(definition: Definition, data_id: str, code_id: str) -> str:
    for value in (data_id, code_id):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("analysis identity requires content fingerprints")
    return hashlib.sha256(canonical_bytes({"definition": definition.canonical(), "data": data_id,
                                          "analysis_code": code_id, "spec": SPEC, "numpy": np.__version__})).hexdigest()


def _check(cancel: Callable[[], bool]) -> None:
    if cancel():
        raise Cancelled("research run cancelled")


def outcome(observations: Observations, symbol: str, decision: datetime) -> dict:
    # Reuse R1 decision validation before looking at any continuation.
    observations.features(symbol, decision)
    day = decision.astimezone(ET).date()
    q = observations._quality[symbol]
    series = q.series
    cov = q.coverage[day]
    minute = decision.astimezone(ET).hour * 60 + decision.astimezone(ET).minute
    record = {"symbol": symbol, "decision_time": decision.astimezone(timezone.utc).isoformat(),
              "session": str(day), "clock": minute, "week": str(day - timedelta(days=day.weekday())),
              "reference_time": None, "reference_price": None, "atr14": None, "outcomes": {}}
    i = q.index.get(decision)
    reference_reason = ("reference_after_session" if minute >= session_close(day) else
                        "missing_reference" if i is None else
                        "incomplete_reference" if not cov.bucket_complete(minute) else None)
    atr_reason = q.prior_complete(day, 14)
    decision_i = q.index.get(decision - timedelta(minutes=5))
    if series is not None and decision_i is not None and atr_reason is None:
        atr = prior(observations._contexts[symbol].daily.atr, series.session[decision_i])
        if math.isfinite(atr) and atr > 0:
            record["atr14"] = float(atr)
        else:
            atr_reason = "undefined_prior_atr14"
    else:
        atr_reason = atr_reason or "missing_decision_bucket"
    if reference_reason is None:
        record["reference_time"] = decision.astimezone(timezone.utc).isoformat()
        record["reference_price"] = float(series.open[i])
    for horizon in HORIZONS:
        end_minute = session_close(day) if horizon == "session_close" else minute + int(horizon[:-1])
        end_time = decision + timedelta(minutes=end_minute - minute)
        j = q.index.get(end_time - timedelta(minutes=5))
        reason = reference_reason or ("endpoint_after_session" if end_minute > session_close(day) else
                                     "missing_endpoint" if j is None else
                                     "incomplete_endpoint" if not cov.bucket_complete(end_minute - 5) else None)
        close = float(series.close[j]) if reason is None else None
        delta = close - record["reference_price"] if reason is None else None
        record["outcomes"][horizon] = {
            "endpoint_time": end_time.astimezone(timezone.utc).isoformat() if reason is None else None,
            "endpoint_price": close,
            "percent": delta / record["reference_price"] * 100 if reason is None else None,
            "prior_daily_atr14": delta / record["atr14"] if reason is None and not atr_reason else None,
            "percent_reason": reason,
            "prior_daily_atr14_reason": reason or atr_reason,
        }
    return record


def _estimate(event_n, event_sum, control_n, control_sum):
    """One mean and event-composition weighted control mean; never fill gaps."""
    total = float(event_n.sum())
    event = float(event_sum.sum() / total) if total else None
    required = event_n > 0
    missing = required & (control_n <= 0)
    baseline = (float(np.sum(event_n[required] * control_sum[required] / control_n[required]) / total)
                if total and not np.any(missing) else None)
    return event, baseline, event - baseline if event is not None and baseline is not None else None


def summarize(records: list, event_ids: set[tuple[str, str]], *, cancel=lambda: False) -> dict:
    """Joint blocks retain symbol correlation and redo clock weights each draw."""
    records = [r if isinstance(r, _Row) else _compact(r) for r in records]
    weeks = sorted({row.week for row in records})
    groups = sorted({(row.symbol, row.clock) for row in records})
    wi, gi = {w: i for i, w in enumerate(weeks)}, {g: i for i, g in enumerate(groups)}
    rng = np.random.Generator(np.random.PCG64(SPEC["seed"]))
    # Draws use the complete eligible event/control universe, not just event weeks.
    sampled = rng.integers(0, len(weeks), size=(SPEC["draws"], len(weeks))) if weeks else None
    weights = np.zeros((SPEC["draws"], len(weeks)))
    if sampled is not None:
        for k, draw in enumerate(sampled):
            weights[k] = np.bincount(draw, minlength=len(weeks))
    results = {}
    for hi, horizon in enumerate(HORIZONS):
        results[horizon] = {}
        for ui, unit in enumerate(UNITS):
            _check(cancel)
            arrays = [np.zeros((len(weeks), len(groups))) for _ in range(4)]
            en, es, cn, cs = arrays
            missing_event, missing_control = Counter(), Counter()
            valid_events = []
            for row in records:
                is_event = (row.symbol, row.decision_time) in event_ids
                value = row.values[hi][ui]
                if value is None:
                    reason = row.reasons[hi][ui]
                    missing_control[reason] += 1
                    if is_event:
                        missing_event[reason] += 1
                    continue
                w, g = wi[row.week], gi[(row.symbol, row.clock)]
                cn[w, g] += 1
                cs[w, g] += value
                if is_event:
                    en[w, g] += 1
                    es[w, g] += value
                    valid_events.append(value)
            event, baseline, difference = _estimate(en.sum(axis=0), es.sum(axis=0), cn.sum(axis=0), cs.sum(axis=0))
            draws = []
            invalid = 0
            if len(weeks) >= SPEC["minimum_weeks"]:
                for start in range(0, SPEC["draws"], 64):
                    _check(cancel)
                    block = weights[start:start + 64]
                    matrices = [block @ a for a in arrays]
                    for stats in zip(*matrices):
                        estimate = _estimate(*stats)
                        if any(x is None for x in estimate):
                            invalid += 1
                        else:
                            draws.append(estimate)
            available = len(weeks) >= SPEC["minimum_weeks"] and len(draws) >= SPEC["minimum_valid_draws"]
            intervals = {}
            for k, name in enumerate(("event_mean", "baseline_mean", "difference")):
                intervals[name] = (np.quantile(np.array(draws)[:, k], [.025, .975], method="linear").tolist()
                                   if available else None)
            event_groups = en.sum(axis=0)
            control_groups = cn.sum(axis=0)
            matches = [{"symbol": g[0], "clock": g[1], "event_n": int(event_groups[k]),
                        "control_n": int(control_groups[k]),
                        "event_weight": float(event_groups[k] / en.sum()) if en.sum() else 0.0}
                       for k, g in enumerate(groups) if event_groups[k]]
            results[horizon][unit] = {
                "event_n": int(en.sum()), "ordinary_n": int(cn.sum()),
                "matched_ordinary_n": sum(x["control_n"] for x in matches),
                "event_mean": event, "event_median": float(np.median(valid_events)) if valid_events else None,
                "baseline_mean": baseline, "difference": difference,
                "event_exclusions": dict(sorted(missing_event.items())),
                "ordinary_exclusions": dict(sorted(missing_control.items())),
                "matches": matches, "missing_matches": [x for x in matches if x["control_n"] == 0],
                "uncertainty": {"intervals": intervals, "eligible_weeks": len(weeks),
                                "valid_draws": len(draws), "invalid_draws": invalid,
                                "unavailable_reason": None if available else
                                "insufficient_weeks" if len(weeks) < SPEC["minimum_weeks"] else "insufficient_valid_draws"},
            }
    return results


def analyze(observations: Observations, definition: Definition, code_id: str, *, cancel=lambda: False) -> dict:
    _check(cancel)
    preview = observations.preview(definition)
    event_ids = {(e["symbol"], e["decision_time"]) for e in preview["events"]}
    records, events = [], []
    for k, m in enumerate(observations.eligible_moments(definition)):
        if k % 128 == 0:
            _check(cancel)
        row = outcome(observations, m.symbol, m.close)
        records.append(_compact(row))
        if (row["symbol"], row["decision_time"]) in event_ids:
            events.append(row)
    results = summarize(records, event_ids, cancel=cancel)
    _check(cancel)
    return {"run_id": analysis_id(definition, observations.snapshot.identity, code_id),
            "analysis_code_id": code_id, "spec": SPEC, "numpy_version": np.__version__,
            "population": preview, "data_manifest": [list(entry) for entry in observations.snapshot.manifest],
            "horizons": results, "events": events,
            "ordinary_qualifiers_included": True, "interpretation": "descriptive discovery research; no causal or execution claim"}
