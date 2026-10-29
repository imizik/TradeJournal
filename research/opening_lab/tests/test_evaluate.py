import json
import math
import random
from datetime import date, timedelta

import pytest

from research.opening_lab import evaluate
from research.opening_lab.contract import CHECKPOINTS_ET, ROUND_TRIP_COST_BPS, checkpoint_ts


def _et(i):
    return f"{9 + (30 + i) // 60:02d}:{(30 + i) % 60:02d}"


def bar(day, hhmm, o, c):
    return {"t": checkpoint_ts(day, hhmm), "o": o, "h": max(o, c), "l": min(o, c), "c": c,
            "v": 1000, "vw": None, "n": None}


def session(day, spy=None, qqq=None, close="16:00", early=False, drop=()):
    """Flat 100.0 tape 09:30-10:59 with overrides {hhmm: (o, c)}; ``drop`` removes bars."""
    def minutes(over):
        over = over or {}
        return [bar(day, hm, *over.get(hm, (100.0, 100.0)))
                for hm in (_et(i) for i in range(90)) if hm not in drop]
    return {"date": day, "schedule": {"open": "09:30", "close": close, "early_close": early},
            "symbols": {"SPY": {"daily": [], "minutes": minutes(spy), "volume_profile": {}},
                        "QQQ": {"daily": [], "minutes": minutes(qqq), "volume_profile": {}}},
            "news": [], "macro": [], "provenance": {}}


def fc(spy=0.5, qqq=0.5, action="WAIT", symbol=None):
    return {"spy_p_up": spy, "qqq_p_up": qqq, "action": action, "symbol": symbol, "reason": ""}


def rec(day, cp, forecast, agent="claude", variant="market", status="ok", latency=None, cost=None):
    return {"date": day, "checkpoint_et": cp, "agent": agent, "variant": variant,
            "status": status, "forecast": forecast, "latency_s": latency, "cost_usd": cost}


D = "2026-07-15"


# Outcomes ---------------------------------------------------------------------------------
def test_outcome_entry_and_exit_bars_hand_computed():
    s = session(D, spy={"09:36": (100.0, 100.05), "09:40": (100.08, 100.10),
                        "09:45": (100.0, 99.80), "09:50": (100.0, 100.30)})
    out = evaluate.outcomes(s, "09:35")
    assert out["SPY"][5] == pytest.approx(10.0)      # 100.10 / 100.00
    assert out["SPY"][10] == pytest.approx(-20.0)    # 99.80 / 100.00
    assert out["SPY"][15] == pytest.approx(30.0)     # 100.30 / 100.00
    assert out["QQQ"] == {5: 0.0, 10: 0.0, 15: 0.0}


def test_outcome_missing_bars_are_none_never_forward_filled():
    exit_gone = session(D, spy={"09:44": (100.0, 100.5)}, drop=("09:45",))
    out = evaluate.outcomes(exit_gone, "09:35")
    assert out["SPY"][10] is None and out["SPY"][5] == 0.0 and out["SPY"][15] == 0.0
    entry_gone = session(D, drop=("09:36",))
    assert evaluate.outcomes(entry_gone, "09:35")["QQQ"] == {5: None, 10: None, 15: None}
    no_symbol = session(D)
    del no_symbol["symbols"]["QQQ"]
    assert evaluate.outcomes(no_symbol, "09:35")["QQQ"] == {5: None, 10: None, 15: None}


def test_outcome_ten_oclock_plus_fifteen_boundary():
    s = session(D, spy={"10:01": (200.0, 200.0), "10:15": (200.0, 201.0),
                        "10:16": (201.0, 250.0)})
    assert evaluate.outcomes(s, "10:00")["SPY"][15] == pytest.approx(50.0)
    assert evaluate.outcomes(session(D, drop=("10:15",)), "10:00")["SPY"][15] is None


def test_outcome_early_close():
    # A real early close (13:00) does not touch the opening window.
    normal = evaluate.outcomes(session(D, spy={"09:41": (100.0, 100.0), "09:55": (100.0, 100.2)}),
                               "09:40")
    early = evaluate.outcomes(session(D, spy={"09:41": (100.0, 100.0), "09:55": (100.0, 100.2)},
                                      close="13:00", early=True), "09:40")
    assert early == normal and early["SPY"][15] == pytest.approx(20.0)
    # A bar starting at/after the scheduled close is never used, even if present in the data.
    cut = evaluate.outcomes(session(D, close="09:50", early=True), "09:40")
    assert cut["SPY"][5] == 0.0 and cut["SPY"][10] is None and cut["SPY"][15] is None


# Metrics ----------------------------------------------------------------------------------
def test_brier_logloss_direction_and_exclusions():
    up = {"09:41": (100.0, 100.0), "09:50": (100.0, 100.1)}
    sessions = {D: session(D, spy=up, qqq=up)}
    report = evaluate.score([rec(D, "09:40", fc(0.7, 0.4))], sessions)
    a = report["agents"][0]
    p = a["probability"]
    assert p["n_points"] == 2
    assert p["brier"] == pytest.approx((0.3 ** 2 + 0.6 ** 2) / 2)
    assert p["brier_skill_vs_coin"] == pytest.approx(1 - 0.225 / 0.25)
    assert p["log_loss"] == pytest.approx(-(math.log(0.7) + math.log(0.4)) / 2, abs=1e-4)
    assert a["direction"] == {"n": 2, "accuracy": 0.5}
    # Zero outcome (flat QQQ) and missing outcome (no SPY exit bar) are excluded and counted.
    s2 = {D: session(D, spy=up, drop=())}
    s2[D]["symbols"]["SPY"]["minutes"] = [b for b in s2[D]["symbols"]["SPY"]["minutes"]
                                          if b["t"] != checkpoint_ts(D, "09:50")]
    p2 = evaluate.score([rec(D, "09:40", fc(0.7, 0.4))], s2)["agents"][0]["probability"]
    assert (p2["n_points"], p2["excluded_zero"], p2["excluded_missing"]) == (0, 1, 1)
    assert p2["brier"] is None


def test_calibration_bins_count_every_point():
    up = {"09:41": (100.0, 100.0), "09:50": (100.0, 100.1)}
    sessions = {D: session(D, spy=up, qqq=up)}
    records = [rec(D, cp, fc(0.5, 0.62)) for cp in ("09:40",)]
    cal = evaluate.score(records, sessions)["agents"][0]["calibration"]
    bins = {row["bin"]: row for row in cal}
    assert bins["0.50-0.55"]["n"] == 1 and bins["0.60-0.65"]["n"] == 1
    assert sum(row["n"] for row in cal) == 2
    assert bins["0.60-0.65"]["freq_up"] == 1.0


def test_take_returns_subtract_cost_and_first_take_of_day():
    spy = {"09:36": (100.0, 100.0), "09:45": (100.0, 100.1),      # cp 09:35: +10 bps at 10 min
           "09:41": (100.0, 100.0), "09:50": (100.0, 99.95)}      # cp 09:40: -5 bps at 10 min
    sessions = {D: session(D, spy=spy)}
    records = [rec(D, "09:35", fc(0.6, 0.5, "LONG", "SPY")),
               rec(D, "09:40", fc(0.4, 0.5, "SHORT", "SPY")),
               rec(D, "09:45", fc())]
    a = evaluate.score(records, sessions)["agents"][0]
    t10 = a["takes"]["10"]
    assert a["takes"]["count"] == 2
    assert t10["mean_net_bps"] == pytest.approx(((10 - ROUND_TRIP_COST_BPS) + (5 - ROUND_TRIP_COST_BPS)) / 2)
    assert t10["total_net_bps"] == pytest.approx(15 - 2 * ROUND_TRIP_COST_BPS)
    assert t10["hit_rate"] == 1.0
    first = a["first_take_of_day"]
    assert first["count"] == 1 and first["10"]["mean_net_bps"] == pytest.approx(9.0)
    # A short into a flat tape loses exactly the cost.
    flat = evaluate.score([rec(D, "09:35", fc(0.4, 0.5, "SHORT", "SPY"))], {D: session(D)})
    assert flat["agents"][0]["takes"]["10"]["mean_net_bps"] == pytest.approx(-ROUND_TRIP_COST_BPS)
    assert flat["agents"][0]["takes"]["10"]["hit_rate"] == 0.0


def test_selectivity_skipped_vs_took():
    spy = {"09:36": (100.0, 100.0), "09:45": (100.0, 100.1)}      # took LONG SPY: +10 gross
    qqq = {"09:41": (100.0, 100.0), "09:50": (100.0, 99.94)}      # skipped, leaned QQQ down: +6
    sessions = {D: session(D, spy=spy, qqq=qqq)}
    records = [rec(D, "09:35", fc(0.6, 0.5, "LONG", "SPY")),
               rec(D, "09:40", fc(0.52, 0.40)),      # larger lean is QQQ (down)
               rec(D, "09:45", fc())]                # no lean: counted, not scored
    s = evaluate.score(records, sessions)["agents"][0]["selectivity"]
    assert s["took_mean_bps"] == pytest.approx(10.0)
    assert s["skipped_mean_bps"] == pytest.approx(6.0)
    assert s["skipped_no_lean"] == 1 and s["skipped_n"] == 1
    assert s["took_minus_skipped_bps"] == pytest.approx(4.0)


def test_coverage_statuses_invalid_latency_and_cost():
    sessions = {D: session(D), "2026-07-16": session("2026-07-16")}
    records = [rec(D, "09:30", fc(), latency=2.0, cost=0.01),
               rec(D, "09:35", fc(), latency=4.0, cost=0.02),
               rec(D, "09:40", None, status="timeout", latency=45.0),
               rec(D, "09:45", {"spy_p_up": 2}, latency=1.0),        # ok status, invalid forecast
               rec(D, "09:30", fc(0.6), latency=3.0)]                # duplicate slot: last wins
    report = evaluate.score(records, sessions)
    a = report["agents"][0]
    assert a["coverage"]["grid"] == 2 * len(CHECKPOINTS_ET)
    assert a["coverage"]["planned"] == 4 and a["coverage"]["ok"] == 2
    assert a["coverage"]["invalid_forecast"] == 1
    assert a["coverage"]["statuses"] == {"ok": 3, "timeout": 1}
    assert report["meta"]["duplicate_records"] == 1
    assert a["latency_s"]["median"] == pytest.approx(3.5)
    assert a["latency_s"]["p95"] == pytest.approx(45.0)
    assert a["cost_usd"] == pytest.approx(0.02)


# Bootstrap and verdicts ------------------------------------------------------------------------
def walk_sessions(n, seed=7):
    rng = random.Random(seed)
    out, day = {}, date(2026, 7, 1)
    for i in range(n):
        d = (day + timedelta(days=i)).isoformat()
        tapes = {}
        for sym in ("SPY", "QQQ"):
            price, tape = 100.0, {}
            for k in range(90):
                close = price * (1 + rng.gauss(0, 5e-4))
                tape[_et(k)] = (price, close)
                price = close
            tapes[sym] = tape
        out[d] = session(d, spy=tapes["SPY"], qqq=tapes["QQQ"])
    return out


def agent_records(sessions, agent, decide, variant="market"):
    records = []
    for d, s in sessions.items():
        for cp in CHECKPOINTS_ET:
            records.append(rec(d, cp, decide(evaluate.outcomes(s, cp)), agent, variant))
    return records


_ORACLE_RNG = random.Random(5)


def oracle(out, accuracy=0.75):
    """Peeks at the outcome but is right only ``accuracy`` of the time: skilled, not perfect."""
    up = {sym: ((out[sym][10] or 0) > 0) == (_ORACLE_RNG.random() < accuracy)
          for sym in ("SPY", "QQQ")}
    return fc(0.65 if up["SPY"] else 0.35, 0.65 if up["QQQ"] else 0.35,
              "LONG" if up["SPY"] else "SHORT", "SPY")


def test_bootstrap_is_deterministic_and_resamples_sessions():
    per = {f"d{i}": (float(i % 3 - 1), 2) for i in range(12)}
    a = evaluate.session_bootstrap(per, draws=2000, seed=1)
    assert a == evaluate.session_bootstrap(per, draws=2000, seed=1)
    assert a != evaluate.session_bootstrap(per, draws=2000, seed=2)
    mean, lo, hi = a
    assert mean == pytest.approx(0.0 / 24, abs=1e-12) and lo < mean < hi
    assert evaluate.session_bootstrap({"only": (1.0, 3)}) == (1 / 3, None, None)
    assert evaluate.session_bootstrap({}) == (None, None, None)


def test_skilled_agent_is_better_and_random_agent_is_not():
    sessions = walk_sessions(40)
    rng = random.Random(3)
    _ORACLE_RNG.seed(5)

    def noise(out):
        action = rng.choice(["WAIT", "LONG", "SHORT"])
        return fc(0.5 + rng.uniform(-0.02, 0.02), 0.5 + rng.uniform(-0.02, 0.02),
                  action, None if action == "WAIT" else rng.choice(["SPY", "QQQ"]))

    records = (agent_records(sessions, "oracle", oracle)
               + agent_records(sessions, "noise", noise)
               + agent_records(sessions, "coin", lambda out: fc()))
    report = evaluate.score(records, sessions)
    assert json.loads(json.dumps(report)) == report
    by = {(c["a"]["agent"], c["b"]["agent"]): c for c in report["comparisons"]}
    skilled = by[("oracle", "coin")]
    assert skilled["n_sessions"] == 40 and skilled["n_points"] == 40 * len(CHECKPOINTS_ET)
    assert skilled["brier"]["verdict"] == "better"
    assert skilled["net_return"]["verdict"] == "better"
    assert skilled["brier"]["diff_a_minus_b"] < 0
    assert skilled["brier"]["min_detectable_effect"] > 0
    rand = by[("noise", "coin")]
    assert rand["brier"]["verdict"] != "better"
    assert rand["net_return"]["verdict"].startswith("no detectable difference (n_sessions=40")
    text = evaluate.render_text(report)
    assert "better" in text and "no detectable difference" in text and "MDE" in text


def test_pairing_uses_intersection_and_variant_comparisons():
    sessions = walk_sessions(6, seed=11)
    bars = agent_records(sessions, "claude", oracle, "bars")
    full = agent_records(sessions, "claude", lambda out: fc(), "full")
    for r in full[:7]:                       # first session failed for the full variant
        r.update(status="error", forecast=None)
    report = evaluate.score(bars + full + agent_records(sessions, "coin", lambda o: fc()),
                            sessions, draws=500)
    vv = [c for c in report["comparisons"] if c["kind"] == "variant_vs_variant"]
    assert len(vv) == 1 and vv[0]["a"]["variant"] == "bars" and vv[0]["b"]["variant"] == "full"
    assert vv[0]["n_sessions"] == 5 and vv[0]["n_points"] == 35
    kinds = sorted(c["kind"] for c in report["comparisons"])
    assert kinds == ["model_vs_baseline", "model_vs_baseline", "variant_vs_variant"]
