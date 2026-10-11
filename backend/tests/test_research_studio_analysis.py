"""Independent hand calculations and fixed-design statistical checks for R2."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import math

import numpy as np
import pytest

from app.engine.market_map import Bar, ET
from app.engine.research_studio import Coverage, Definition, Observations, Predicate, Snapshot, SymbolSnapshot, session_close, session_dates
from app.engine.research_studio_analysis import Cancelled, HORIZONS, analyze, outcome, summarize
from app.engine.research_studio_data import engine_fingerprint

DAY = date(2023, 7, 10)
CODE = "a" * 64


def clock(day=DAY, minute=600):
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)


@pytest.fixture
def snapshot():
    sources = []
    days = session_dates(DAY)
    for symbol in ("MU", "SPY"):
        bars = []
        coverage = []
        for day in days:
            coverage.append(Coverage(day, "present", (1 << (session_close(day) - 570)) - 1))
            for minute in range(570, session_close(day), 5):
                value = {600: 110, 610: 115, 625: 120, 655: 90, 955: 105}.get(minute, 100) if day == DAY and symbol == "MU" else 100
                bars.append(Bar(clock(day, minute).astimezone(timezone.utc), value, value + 1, value - 1, value, 100))
        sources.append(SymbolSnapshot(symbol, tuple(bars), tuple(coverage)))
    return Snapshot(DAY, tuple(sources), tuple((s.symbol, str(d), "b" * 64, 100) for s in sources for d in days), engine_fingerprint())


@pytest.fixture
def definition():
    return Definition((Predicate("minutes", minimum=30),), universe=("MU",), start=DAY, end=DAY,
                      window_start=600, window_end=600)


def changed(snapshot, *, remove_minute=None, day=DAY, partial=False):
    source = snapshot.symbols[0]
    if remove_minute is None:
        return snapshot
    coverage = tuple(replace(c, valid_minutes=c.valid_minutes & ~((1 if partial else 31) << (remove_minute - 570)))
                     if c.day == day else c for c in source.coverage)
    bars = tuple(b for b in source.bars if partial or b.time != clock(day, remove_minute))
    return replace(snapshot, symbols=(replace(source, coverage=coverage, bars=bars), snapshot.symbols[1]))


def test_next_open_and_all_exact_endpoints_with_frozen_atr(snapshot):
    row = outcome(Observations(snapshot), "MU", clock())
    assert row["reference_price"] == 110
    assert row["reference_time"] == clock().astimezone(timezone.utc).isoformat()
    assert row["atr14"] == 2
    for horizon, close in zip(HORIZONS, (115, 120, 90, 105)):
        value = row["outcomes"][horizon]
        assert value["percent"] == pytest.approx((close - 110) / 110 * 100)
        assert value["prior_daily_atr14"] == (close - 110) / 2
        assert value["endpoint_price"] == close


@pytest.mark.parametrize("partial", [False, True])
def test_no_skipping_missing_or_partial_reference(snapshot, partial):
    obs = Observations(changed(snapshot, remove_minute=600, partial=partial))
    row = outcome(obs, "MU", clock())
    assert all(x["percent"] is None for x in row["outcomes"].values())
    assert {x["percent_reason"] for x in row["outcomes"].values()} == {"incomplete_reference" if partial else "missing_reference"}


def test_missing_endpoint_excludes_only_its_horizon(snapshot):
    row = outcome(Observations(changed(snapshot, remove_minute=625)), "MU", clock())
    assert row["outcomes"]["30m"]["percent"] is None
    assert row["outcomes"]["15m"]["percent"] is not None
    assert row["outcomes"]["60m"]["percent"] is not None
    assert row["outcomes"]["session_close"]["percent"] is not None


def test_atr_gap_does_not_erase_percent_results(snapshot):
    row = outcome(Observations(changed(snapshot, remove_minute=600, day=date(2023, 7, 7))), "MU", clock())
    assert row["outcomes"]["30m"]["percent"] is not None
    assert row["outcomes"]["30m"]["prior_daily_atr14"] is None
    assert row["outcomes"]["30m"]["prior_daily_atr14_reason"] == "daily_history_gap"


def test_early_close_and_no_next_session_substitution(snapshot):
    obs = Observations(snapshot)
    row = outcome(obs, "MU", clock(date(2023, 7, 3), 760))
    assert row["outcomes"]["15m"]["percent"] == 0
    assert row["outcomes"]["30m"]["percent_reason"] == "endpoint_after_session"
    assert row["outcomes"]["session_close"]["endpoint_time"] == clock(date(2023, 7, 3), 780).astimezone(timezone.utc).isoformat()
    end = outcome(obs, "MU", clock(date(2023, 7, 3), 780))
    assert {x["percent_reason"] for x in end["outcomes"].values()} == {"reference_after_session"}


def row(week, symbol, value, index, minute=600):
    return {"symbol": symbol, "decision_time": f"{week}:{symbol}:{index}", "clock": minute,
            "week": week, "outcomes": {h: {"percent": value, "prior_daily_atr14": value / 2,
                                                "percent_reason": None, "prior_daily_atr14_reason": None}
                                       for h in HORIZONS}}


def weighted_fixture(weeks=20, shocks=False):
    records, selected = [], set()
    for w in range(weeks):
        week = str(date(2023, 7, 3) + timedelta(weeks=w))
        shock = (w - 10) if shocks else 0
        for symbol, values, n in (("MU", [12, 12, 12, 0], 3), ("AMD", [-4, 4], 1)):
            for k, v in enumerate(values):
                r = row(week, symbol, v + shock, k)
                records.append(r)
                if k < n:
                    selected.add((symbol, r["decision_time"]))
    return records, selected


def test_event_composition_weights_include_qualifying_controls():
    records, selected = weighted_fixture()
    r = summarize(records, selected)["30m"]["percent"]
    assert (r["event_n"], r["ordinary_n"]) == (80, 120)
    assert r["event_mean"] == 8
    assert r["baseline_mean"] == 6.75  # MU ordinary mean9 * .75 + AMD mean0 * .25
    assert r["difference"] == 1.25
    assert {m["symbol"]: m["event_weight"] for m in r["matches"]} == {"MU": .75, "AMD": .25}
    assert r["uncertainty"]["valid_draws"] == 2000
    assert r["uncertainty"]["intervals"]["difference"] == [1.25, 1.25]


def test_joint_blocks_keep_common_symbol_shocks_and_determinism():
    records, selected = weighted_fixture(shocks=True)
    first = summarize(records, selected)
    assert first == summarize(records, selected)
    r = first["30m"]["percent"]["uncertainty"]["intervals"]
    assert r["event_mean"][0] < r["event_mean"][1]
    assert r["difference"] == pytest.approx([1.25, 1.25])
    assert np.diff(r["event_mean"])[0] == pytest.approx(np.diff(r["baseline_mean"])[0])


def test_insufficient_weeks_and_invalid_zero_event_draws_report_unavailable():
    records, selected = weighted_fixture(19)
    r = summarize(records, selected)["30m"]["percent"]["uncertainty"]
    assert r["unavailable_reason"] == "insufficient_weeks"
    assert all(x is None for x in r["intervals"].values())
    records, selected = weighted_fixture(20)
    first_week = records[0]["week"]
    selected = {(r["symbol"], r["decision_time"]) for r in records if r["week"] == first_week}
    r = summarize(records, selected)["30m"]["percent"]["uncertainty"]
    assert 0 < r["valid_draws"] < 1900
    assert r["invalid_draws"] + r["valid_draws"] == 2000
    assert r["unavailable_reason"] == "insufficient_valid_draws"


def test_analysis_cancellation_never_returns_partial_results(snapshot, definition):
    with pytest.raises(Cancelled):
        analyze(Observations(snapshot), definition, CODE, cancel=lambda: True)
    result = analyze(Observations(snapshot), definition, CODE)
    assert result["population"]["event_count"] == 1
    assert result["horizons"]["30m"]["percent"]["event_mean"] == pytest.approx(100 / 11)
    assert result["spec"]["primary_horizon"] == "30m"
    assert result["horizons"]["30m"]["percent"]["uncertainty"]["unavailable_reason"] == "insufficient_weeks"


def test_null_simulation_assesses_fixed_design_coverage_without_requiring_each_trial_null():
    # Selection is independent of future shocks/noise. One selected moment per
    # symbol/session; ordinary moments include it. Weekly shocks shared by symbols.
    rng = np.random.Generator(np.random.PCG64(9841))
    covered, intervals = 0, []
    for trial in range(30):
        records, selected = [], set()
        for w in range(40):
            week = str(date(2023, 7, 3) + timedelta(weeks=w))
            shock = rng.normal()
            for symbol in ("MU", "AMD"):
                for session in range(3):
                    chosen = int(rng.integers(0, 3))
                    for k in range(3):
                        r = row(week, symbol, float(shock + rng.normal()), session * 3 + k)
                        records.append(r)
                        if k == chosen:
                            selected.add((symbol, r["decision_time"]))
        result = summarize(records, selected)["30m"]["percent"]["uncertainty"]["intervals"]["difference"]
        assert result is not None and all(math.isfinite(x) for x in result)
        intervals.append(result)
        covered += result[0] <= 0 <= result[1]
    # Coarse Monte Carlo diagnostic, not a universal calibration guarantee or
    # an acceptance criterion that every null draw must look insignificant.
    assert covered >= 23
    print(f"R2 fixed-design null calibration: {covered}/30 95% intervals cover zero; seed9841,40 joint weeks,2000 draws each")


def test_bootstrap_recomputes_symbol_clock_composition_against_closed_form():
    records, selected = [], set()
    for w in range(20):
        week = str(date(2023, 7, 3) + timedelta(weeks=w))
        for symbol, values in (("MU", [2, 0] if w % 2 == 0 else [0, 0]),
                               ("AMD", [0, 0] if w % 2 == 0 else [10, 0])):
            for k, value in enumerate(values):
                r = row(week, symbol, value, k)
                records.append(r)
                if (w % 2 == 0 and symbol == "MU" and k == 0) or (w % 2 == 1 and symbol == "AMD"):
                    selected.add((symbol, r["decision_time"]))
    result = summarize(records, selected)["30m"]["percent"]
    assert result["event_mean"] == 4
    assert result["baseline_mean"] == pytest.approx(11 / 6)
    # Independent closed-form oracle: each sampled even week adds one MU
    # event and each odd week two AMD events. Weights must change each draw.
    sampled = np.random.Generator(np.random.PCG64(0)).integers(0, 20, size=(2000, 20))
    even = (sampled % 2 == 0).sum(axis=1)
    odd = 20 - even
    event = (2 * even + 10 * odd) / (even + 2 * odd)
    baseline = (even ** 2 + 10 * odd ** 2) / (20 * (even + 2 * odd))
    expected = np.quantile(event - baseline, [.025, .975], method="linear")
    assert result["uncertainty"]["intervals"]["difference"] == pytest.approx(expected)


def test_cancellation_is_checked_during_joint_draws():
    records, selected = weighted_fixture()
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls > 5
    with pytest.raises(Cancelled):
        summarize(records, selected, cancel=cancel)
