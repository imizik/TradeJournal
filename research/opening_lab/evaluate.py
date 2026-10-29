"""Honest scorer: outcomes, per-agent metrics and session-bootstrapped comparisons.

Every checkpoint is scored on its own. Checkpoints inside one session are
correlated (same tape, overlapping horizons), so every confidence interval
resamples whole sessions, and a comparison is called "better" or "worse" only
when its 95 % interval excludes zero. Otherwise the verdict is "no detectable
difference", printed with the sample size and the minimum detectable effect so
a reader sees what the sample could and could not resolve.

Record shape (one per session x checkpoint x agent x variant)::

    {"date", "checkpoint_et", "agent", "variant", "status": "ok" | other,
     "forecast": dict | None, "latency_s": float | None, "cost_usd": float | None}
"""

import math
import random
import statistics

from .baselines import BASELINES
from .contract import (CHECKPOINTS_ET, HORIZONS_MINUTES, PRIMARY_HORIZON_MINUTES,
                       ROUND_TRIP_COST_BPS, SYMBOLS, checkpoint_ts, entry_bar_start,
                       VARIANTS, plus_minutes, validate_forecast)

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261028
CI_LEVEL = 0.95
Z_ALPHA, Z_POWER = 1.959964, 0.841621   # two-sided 5 %, 80 % power
LOGLOSS_EPS = 1e-6
CAL_EDGES = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
PRIMARY = PRIMARY_HORIZON_MINUTES


# Outcomes --------------------------------------------------------------------------
def outcomes(session, checkpoint_et):
    """Gross return in bps per symbol and horizon under the contract outcome rule.

    Entry is the OPEN of the bar starting at C + ENTRY_DELAY_MINUTES; exit at h is
    the CLOSE of the bar starting h - 1 minutes after entry. A missing bar, or one
    starting at/after the scheduled close, gives None. Nothing is forward-filled.
    """
    day = session["date"]
    close_hhmm = (session.get("schedule") or {}).get("close") or "16:00"
    close_ts = checkpoint_ts(day, close_hhmm)
    entry_t = entry_bar_start(day, checkpoint_et)
    result = {}
    for sym in SYMBOLS:
        minutes = ((session.get("symbols") or {}).get(sym) or {}).get("minutes") or []
        by_t = {b["t"]: b for b in minutes if b["t"] < close_ts}
        entry = by_t.get(entry_t)
        result[sym] = {}
        for h in HORIZONS_MINUTES:
            exit_bar = by_t.get(plus_minutes(entry_t, h - 1))
            if entry is None or exit_bar is None or not entry.get("o"):
                result[sym][h] = None
            else:
                result[sym][h] = (exit_bar["c"] / entry["o"] - 1.0) * 1e4
    return result


# Small helpers -----------------------------------------------------------------------
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _pct(xs, q):
    """Nearest-rank percentile of a non-empty list."""
    xs = sorted(xs)
    return xs[max(0, math.ceil(q * len(xs)) - 1)]


def _rnd(x, n=4):
    return None if x is None else round(x, n)


def _p_up(forecast, sym):
    return forecast[f"{sym.lower()}_p_up"]


def _take_return(forecast, outcome, h, net=True):
    """Signed return of the forecast's take at horizon h (None if WAIT or missing)."""
    if forecast["action"] == "WAIT":
        return None
    r = outcome[forecast["symbol"]][h]
    if r is None:
        return None
    signed = r if forecast["action"] == "LONG" else -r
    return signed - ROUND_TRIP_COST_BPS if net else signed


def _favoured(forecast):
    """(symbol, +1/-1) the forecast leans toward: the larger |p - 0.5|, or None if flat."""
    leans = [(abs(_p_up(forecast, s) - 0.5), -i, s) for i, s in enumerate(SYMBOLS)]
    lean, _, sym = max(leans)
    if lean == 0:
        return None
    return sym, (1 if _p_up(forecast, sym) > 0.5 else -1)


def _prob_points(forecast, outcome):
    """[(p, y)] on the primary horizon; outcome 0 or None excluded (returned as counts)."""
    points, zero, missing = [], 0, 0
    for sym in SYMBOLS:
        r = outcome[sym][PRIMARY]
        if r is None:
            missing += 1
        elif r == 0:
            zero += 1
        else:
            points.append((_p_up(forecast, sym), 1 if r > 0 else 0))
    return points, zero, missing


def _brier(p, y):
    return (p - y) ** 2


def _logloss(p, y):
    p = min(1 - LOGLOSS_EPS, max(LOGLOSS_EPS, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _take_stats(returns_by_h, n_takes):
    out = {"count": n_takes}
    for h in HORIZONS_MINUTES:
        xs = returns_by_h[h]
        out[str(h)] = {"n": len(xs), "missing": n_takes - len(xs),
                       "mean_net_bps": _rnd(_mean(xs), 2),
                       "total_net_bps": _rnd(sum(xs), 2) if xs else None,
                       "hit_rate": _rnd(sum(x > 0 for x in xs) / len(xs), 3) if xs else None}
    return out


# Per-agent metrics ----------------------------------------------------------------------
def _calibration(points):
    edges = (0.0,) + CAL_EDGES + (1.0000001,)
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        inside = [(p, y) for p, y in points if lo <= p < hi]
        label = (f"<{CAL_EDGES[0]:.2f}" if lo == 0 else
                 f">={CAL_EDGES[-1]:.2f}" if hi > 1 else f"{lo:.2f}-{hi:.2f}")
        rows.append({"bin": label, "n": len(inside),
                     "mean_p": _rnd(_mean([p for p, _ in inside]), 3),
                     "freq_up": _rnd(_mean([y for _, y in inside]), 3)})
    return rows


def _agent_metrics(recs, outcome_of, n_grid):
    statuses = {}
    for r in recs:
        st = str(r.get("status"))
        statuses[st] = statuses.get(st, 0) + 1
    ok = [r for r in recs if r["_forecast"] is not None]
    invalid = sum(1 for r in recs if r["status"] == "ok" and r["_forecast"] is None)

    points, zero, missing = [], 0, 0
    for r in ok:
        pts, z, m = _prob_points(r["_forecast"], outcome_of(r))
        points += pts
        zero += z
        missing += m
    brier = _mean([_brier(p, y) for p, y in points])
    directional = [(p > 0.5) == (y == 1) for p, y in points if p != 0.5]

    takes = [r for r in ok if r["_forecast"]["action"] != "WAIT"]
    take_returns = {h: [x for x in (_take_return(r["_forecast"], outcome_of(r), h) for r in takes)
                        if x is not None] for h in HORIZONS_MINUTES}
    first_by_day = {}
    for r in sorted(takes, key=lambda r: (r["date"], r["checkpoint_et"])):
        first_by_day.setdefault(r["date"], r)
    first = list(first_by_day.values())
    first_returns = {h: [x for x in (_take_return(r["_forecast"], outcome_of(r), h) for r in first)
                         if x is not None] for h in HORIZONS_MINUTES}

    took, skipped, no_lean = [], [], 0
    for r in ok:
        f, out = r["_forecast"], outcome_of(r)
        if f["action"] != "WAIT":
            x = _take_return(f, out, PRIMARY, net=False)
            if x is not None:
                took.append(x)
            continue
        fav = _favoured(f)
        if fav is None:
            no_lean += 1
        elif out[fav[0]][PRIMARY] is not None:
            skipped.append(fav[1] * out[fav[0]][PRIMARY])
    took_mean, skip_mean = _mean(took), _mean(skipped)

    latencies = [r["latency_s"] for r in recs if isinstance(r.get("latency_s"), (int, float))]
    costs = [r["cost_usd"] for r in recs if isinstance(r.get("cost_usd"), (int, float))]
    return {
        "coverage": {"grid": n_grid, "planned": len(recs), "ok": len(ok), "invalid_forecast": invalid,
                     "ok_rate": _rnd(len(ok) / len(recs), 3) if recs else None,
                     "statuses": statuses, "sessions_ok": len({r["date"] for r in ok})},
        "probability": {"horizon_min": PRIMARY, "n_points": len(points),
                        "excluded_zero": zero, "excluded_missing": missing,
                        "brier": _rnd(brier),
                        "brier_skill_vs_coin": _rnd(1 - brier / 0.25) if brier is not None else None,
                        "log_loss": _rnd(_mean([_logloss(p, y) for p, y in points]))},
        "calibration": _calibration(points),
        "direction": {"n": len(directional),
                      "accuracy": _rnd(_mean([float(d) for d in directional]), 3)},
        "takes": _take_stats(take_returns, len(takes)),
        "first_take_of_day": _take_stats(first_returns, len(first)),
        "selectivity": {"horizon_min": PRIMARY, "basis": "gross signed bps in the favoured direction",
                        "took_n": len(took), "took_mean_bps": _rnd(took_mean, 2),
                        "skipped_n": len(skipped), "skipped_mean_bps": _rnd(skip_mean, 2),
                        "skipped_no_lean": no_lean,
                        "took_minus_skipped_bps": _rnd(took_mean - skip_mean, 2)
                        if took_mean is not None and skip_mean is not None else None},
        "latency_s": {"n": len(latencies),
                      "median": _rnd(statistics.median(latencies), 3) if latencies else None,
                      "p95": _rnd(_pct(latencies, 0.95), 3) if latencies else None},
        "cost_usd": _rnd(sum(costs), 4) if costs else 0.0,
    }


# Paired comparisons -----------------------------------------------------------------------
def session_bootstrap(per_session, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Ratio-of-sums mean and percentile CI, resampling sessions with replacement.

    ``per_session`` maps a session key to (sum, count). Returns (mean, lo, hi) or
    (mean, None, None) when fewer than two sessions carry data.
    """
    keys = sorted(k for k, (_, n) in per_session.items() if n)
    total_n = sum(per_session[k][1] for k in keys)
    if not total_n:
        return None, None, None
    mean = sum(per_session[k][0] for k in keys) / total_n
    if len(keys) < 2:
        return mean, None, None
    sums = [per_session[k][0] for k in keys]
    counts = [per_session[k][1] for k in keys]
    rng, idx = random.Random(seed), range(len(keys))
    stats = []
    for _ in range(draws):
        pick = rng.choices(idx, k=len(keys))
        stats.append(sum(sums[i] for i in pick) / sum(counts[i] for i in pick))
    stats.sort()
    tail = (1 - CI_LEVEL) / 2
    lo = stats[int(math.floor(tail * (draws - 1)))]
    hi = stats[int(math.ceil((1 - tail) * (draws - 1)))]
    return mean, lo, hi


def _verdict(mean, lo, hi, lower_is_better, n_sessions, n_points):
    size = f"n_sessions={n_sessions}, n_points={n_points}"
    if lo is None:
        return f"insufficient data ({size})"
    if lo > 0 or hi < 0:
        a_lower = hi < 0
        return "better" if a_lower == lower_is_better else "worse"
    return f"no detectable difference ({size})"


def _diff_block(per_session, lower_is_better, draws, seed, unit):
    mean, lo, hi = session_bootstrap(per_session, draws, seed)
    used = {k: v for k, v in per_session.items() if v[1]}
    n_sessions, n_points = len(used), sum(v[1] for v in used.values())
    mde = None
    if lo is not None:
        se = (hi - lo) / (2 * Z_ALPHA)
        mde = (Z_ALPHA + Z_POWER) * se
    return {"unit": unit, "n_sessions": n_sessions, "n_points": n_points,
            "diff_a_minus_b": _rnd(mean, 5), "ci95": [_rnd(lo, 5), _rnd(hi, 5)] if lo is not None else None,
            "min_detectable_effect": _rnd(mde, 5),
            "verdict": _verdict(mean, lo, hi, lower_is_better, n_sessions, n_points)}


def compare(recs_a, recs_b, outcome_of, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Paired A-vs-B on (date, checkpoint) where both have valid forecasts."""
    a = {(r["date"], r["checkpoint_et"]): r for r in recs_a if r["_forecast"] is not None}
    b = {(r["date"], r["checkpoint_et"]): r for r in recs_b if r["_forecast"] is not None}
    brier, ret = {}, {}
    shared = sorted(set(a) & set(b))
    for key in shared:
        day, out = key[0], outcome_of(a[key])
        fa, fb = a[key]["_forecast"], b[key]["_forecast"]
        s, n = brier.get(day, (0.0, 0))
        for sym in SYMBOLS:
            r = out[sym][PRIMARY]
            if r is not None and r != 0:
                y = 1 if r > 0 else 0
                s += _brier(_p_up(fa, sym), y) - _brier(_p_up(fb, sym), y)
                n += 1
        brier[day] = (s, n)
        # Net bps per checkpoint: a WAIT contributes 0; a take with no outcome drops the point.
        ra, rb = _take_return(fa, out, PRIMARY), _take_return(fb, out, PRIMARY)
        if (ra is None and fa["action"] != "WAIT") or (rb is None and fb["action"] != "WAIT"):
            continue
        s, n = ret.get(day, (0.0, 0))
        ret[day] = (s + (ra or 0.0) - (rb or 0.0), n + 1)
    return {"n_sessions": len({k[0] for k in shared}), "n_points": len(shared),
            "brier": _diff_block(brier, True, draws, seed, "Brier per symbol-forecast"),
            "net_return": _diff_block(ret, False, draws, seed,
                                      f"net bps per checkpoint at {PRIMARY} min (WAIT = 0)")}


def _group_order(key):
    agent, variant = key
    rank = VARIANTS.index(variant) if variant in VARIANTS else len(VARIANTS)
    return (agent, rank, str(variant))


# Entry points -------------------------------------------------------------------------------
def score(records, sessions_by_date, *, baseline_agents=None,
          draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Score records against sessions; returns a JSON-serializable report."""
    baseline_agents = set(BASELINES if baseline_agents is None else baseline_agents)
    cache = {}

    def outcome_of(rec):
        key = (rec["date"], rec["checkpoint_et"])
        if key not in cache:
            session = sessions_by_date.get(rec["date"])
            cache[key] = (outcomes(session, rec["checkpoint_et"]) if session else
                          {s: {h: None for h in HORIZONS_MINUTES} for s in SYMBOLS})
        return cache[key]

    groups, duplicates = {}, 0
    for rec in records:
        rec = dict(rec)
        forecast = None
        if rec.get("status") == "ok" and rec.get("forecast") is not None:
            try:
                forecast = validate_forecast(rec["forecast"])
            except ValueError:
                forecast = None
        rec["_forecast"] = forecast
        slot = groups.setdefault((rec["agent"], rec["variant"]), {})
        key = (rec["date"], rec["checkpoint_et"])
        duplicates += key in slot
        slot[key] = rec   # the last record for a slot wins
    groups = {k: sorted(v.values(), key=lambda r: (r["date"], r["checkpoint_et"]))
              for k, v in sorted(groups.items(), key=lambda kv: _group_order(kv[0]))}

    n_grid = len(sessions_by_date) * len(CHECKPOINTS_ET)
    agents = [{"agent": a, "variant": v, "is_baseline": a in baseline_agents,
               **_agent_metrics(recs, outcome_of, n_grid)} for (a, v), recs in groups.items()]

    pairs = []
    models = [k for k in groups if k[0] not in baseline_agents]
    bases = [k for k in groups if k[0] in baseline_agents]
    for m in models:
        pairs += [("model_vs_baseline", m, b) for b in bases]
    for i, m in enumerate(models):
        pairs += [("variant_vs_variant", m, o) for o in models[i + 1:] if o[0] == m[0]]
    comparisons = [{"kind": kind, "a": {"agent": a[0], "variant": a[1]},
                    "b": {"agent": b[0], "variant": b[1]},
                    **compare(groups[a], groups[b], outcome_of, draws, seed)}
                   for kind, a, b in pairs]

    return {
        "meta": {"n_sessions": len(sessions_by_date), "checkpoints": list(CHECKPOINTS_ET),
                 "horizons_min": list(HORIZONS_MINUTES), "primary_horizon_min": PRIMARY,
                 "round_trip_cost_bps": ROUND_TRIP_COST_BPS, "duplicate_records": duplicates,
                 "bootstrap": {"unit": "session", "draws": draws, "seed": seed, "ci": CI_LEVEL},
                 "baseline_agents": sorted(baseline_agents)},
        "agents": agents,
        "comparisons": comparisons,
        "notes": [
            "Brier and log loss pool SPY and QQQ at the primary horizon; returns of exactly 0 "
            "and missing outcomes are excluded and counted.",
            "Take returns are net of the round-trip cost; selectivity compares gross returns in "
            "the favoured direction on skipped vs taken checkpoints.",
            "CIs resample whole sessions because checkpoints within a day are correlated.",
            f"{len(comparisons)} comparisons: at 95 % roughly 1 in 20 true nulls will read "
            "'better' or 'worse' by chance. Treat single hits as hypotheses, not findings.",
            "min_detectable_effect ~ the true difference this sample would detect 80 % of the "
            "time (2.8 standard errors, SE taken from the CI width).",
        ],
    }


def _fmt(x, nd=4):
    return "-" if x is None else f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def render_text(report):
    """Plain terminal rendering of a ``score`` report."""
    m = report["meta"]
    lines = [f"Opening lab scorecard - {m['n_sessions']} sessions, primary horizon "
             f"{m['primary_horizon_min']} min, cost {m['round_trip_cost_bps']} bps round trip",
             ""]
    head = (f"{'agent':<14}{'variant':<8}{'ok/plan':>10}{'brier':>8}{'skill':>8}{'logloss':>9}"
            f"{'dir acc':>8}{'takes':>6}{'net@5':>8}{'net@10':>8}{'net@15':>8}{'hit10':>7}"
            f"{'1st@10':>8}{'took-skip':>10}{'lat p50':>8}{'p95':>7}{'cost$':>8}")
    lines += [head, "-" * len(head)]
    for a in report["agents"]:
        c, p, t, s = a["coverage"], a["probability"], a["takes"], a["selectivity"]
        lines.append(
            f"{a['agent'][:13]:<14}{a['variant'][:7]:<8}{c['ok']:>5}/{c['planned']:<4}"
            f"{_fmt(p['brier']):>8}{_fmt(p['brier_skill_vs_coin'], 3):>8}{_fmt(p['log_loss']):>9}"
            f"{_fmt(a['direction']['accuracy'], 3):>8}{t['count']:>6}"
            f"{_fmt(t['5']['mean_net_bps'], 2):>8}{_fmt(t['10']['mean_net_bps'], 2):>8}"
            f"{_fmt(t['15']['mean_net_bps'], 2):>8}{_fmt(t['10']['hit_rate'], 2):>7}"
            f"{_fmt(a['first_take_of_day']['10']['mean_net_bps'], 2):>8}"
            f"{_fmt(s['took_minus_skipped_bps'], 2):>10}"
            f"{_fmt(a['latency_s']['median'], 1):>8}{_fmt(a['latency_s']['p95'], 1):>7}"
            f"{_fmt(a['cost_usd'], 2):>8}")
    lines += ["", "Calibration (n / mean p / freq up) per agent:"]
    for a in report["agents"]:
        cells = [f"{r['bin']}: {r['n']}/{_fmt(r['mean_p'], 2)}/{_fmt(r['freq_up'], 2)}"
                 for r in a["calibration"] if r["n"]]
        lines.append(f"  {a['agent']}/{a['variant']}: " + ("; ".join(cells) or "no points"))
    if report["comparisons"]:
        lines += ["", "Paired comparisons (A - B; session bootstrap 95% CI; Brier lower is better):"]
    for c in report["comparisons"]:
        lines.append(f"  [{c['kind']}] {c['a']['agent']}/{c['a']['variant']} vs "
                     f"{c['b']['agent']}/{c['b']['variant']}  "
                     f"(shared: {c['n_sessions']} sessions, {c['n_points']} checkpoints)")
        for name in ("brier", "net_return"):
            d = c[name]
            ci = "-" if d["ci95"] is None else f"[{_fmt(d['ci95'][0], 4)}, {_fmt(d['ci95'][1], 4)}]"
            lines.append(f"    {name:<10} diff {_fmt(d['diff_a_minus_b'], 4):>9} CI {ci:<22} "
                         f"MDE {_fmt(d['min_detectable_effect'], 4):>8}  -> {d['verdict']}")
    lines += [""] + [f"Note: {n}" for n in report["notes"]]
    return "\n".join(lines)
