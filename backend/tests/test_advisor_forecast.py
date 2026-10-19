"""Synthetic forecast math, timing, isolation and immutable receipt acceptance."""
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import advisor_forecast as core  # noqa: E402
import advisor_forecast_runtime as runtime  # noqa: E402
from advisor_forecast_exchange import ForecastExchange  # noqa: E402


@pytest.fixture
def spec():
    return core.with_timing(core.read_json(core.SPEC_DIR / "spec.json"), 0)


def packet(spec, day="2098-02-01", ticker="MU"):
    prior = [f"2098-01-{i:02d}" for i in range(1, 21)]
    start, _ = core.timing(spec)
    return core.snapshot(day, ticker, core.fixture_bars(day, count=start - 571),
                         {d: core.fixture_bars(d) for d in prior}, prior,
                         core.at(day, spec["snapshot"]["capture_start"]) + timedelta(seconds=5), spec)


def forecast(**changes):
    return {"direction": "up", "terminal_price": 101, "low": 99, "high": 102,
            "support": "synthetic only", "invalidation": "synthetic only", "uncertainty": "synthetic only", **changes}


def record(spec, day, ticker, variant=0):
    p = packet(spec, day, ticker)
    start, end = core.timing(spec)
    bars = core.fixture_bars(day, start, end - start)
    down = variant in (3, 4)
    for b in bars:
        b["h"], b["l"] = (101, 98) if down else (102, 99)
    bars[-1]["c"] = 99 if down else 101
    f = forecast(direction="down" if variant == 3 else "up", terminal_price=99 if variant == 3 else 101,
                 low=98 if down else 99, high=101 if down else 102)
    started = core.at(day, spec["snapshot"]["capture_start"]) + timedelta(seconds=6)
    return {"session": day, "ticker": ticker, "snapshot": p,
            "receipt": core.receipt(p, f, started, started + timedelta(seconds=1), spec),
            "outcome": core.outcome(day, ticker, bars, core.at(day, "11:05:05"), spec),
            "baseline": core.deadline_baseline(p, core.fixture_bars(day, count=start + 2 - 570), core.at(day, spec["snapshot"]["submission_deadline"]) + timedelta(seconds=5), spec),
            "audit": {"web_status": "verified_no_external_access", "evidence_type": "complete_platform_trace", "evidence_sha256": "a" * 64,
                      "model_name": None, "model_source": "unavailable", "synthetic_fixture": True}}


@pytest.fixture
def study(spec):
    days = [(date(2098, 2, 1) + timedelta(days=i)).isoformat() for i in range(20)]
    rows = [record(spec, day, ticker, i % 5) for i, day in enumerate(days) for ticker in spec["tickers"]]
    return days, rows, core.at(days[-1], "11:06:00")


def test_hand_calculated_math_and_quantiles(spec):
    p = packet(spec)
    assert p["sideways_threshold"] == pytest.approx(.0025)
    assert (p["baseline_low"], p["baseline_high"], p["width_cap_usd"]) == (99, 102, 3)
    assert core.quantile(list(range(1, 21)), 1 - .8) == 4
    assert core.quantile(list(range(1, 21)), .8) == 16
    assert core.classify(.0025, .0025) == core.classify(-.0025, .0025) == "sideways"
    assert core.classify(.0025001, .0025) == "up"
    assert core.classify(-.0025001, .0025) == "down"


def test_hand_calculated_full_score(spec, study):
    days, rows, now = study
    report = core.score(days, rows, spec, now)
    m = report["overall"]
    assert m["cases"] == 140
    assert m["direction_accuracy"] == pytest.approx(.8)
    assert max(m["baseline_direction_on_answered"].values()) == pytest.approx(.6)
    assert m["direction_advantage"] == pytest.approx(.2)
    assert m["range_coverage"] == 1
    assert m["baseline_range_coverage"] == pytest.approx(.6)
    assert m["mean_width_fraction"] == m["baseline_mean_width_fraction"] == pytest.approx(.03)
    assert m["terminal_mae_fraction"] == pytest.approx(.004)
    assert report["verdict"] == "replication_only"
    assert len(report["by_session"]) == 20


def test_missing_late_and_abstain_have_distinct_denominators(spec, study):
    days, rows, now = study
    r = rows[0]
    r["receipt"] = core.receipt(r["snapshot"], forecast(direction="abstain", terminal_price=None, low=None, high=None),
                                  core.at(days[0], "10:00:06"), core.at(days[0], "10:00:07"), spec)
    r = rows[1]
    r["receipt"] = core.receipt(r["snapshot"], forecast(), core.at(days[0], "10:00:06"), core.at(days[0], "10:02:00.001"), spec)
    rows[2].pop("receipt")
    report = core.score(days, rows, spec, now)
    assert report["overall"]["statuses"] == {"abstain": 1, "late": 1, "missing": 1, "answered": 137}
    assert report["overall"]["answer_fraction"] == pytest.approx(137 / 140)
    assert report["missing_sessions"] == [days[0]]


@pytest.mark.parametrize("n,invalid", [(3, False), (4, True)])
def test_missing_session_limit(spec, study, n, invalid):
    days, rows, now = study
    for d in days[:n]:
        next(r for r in rows if r["session"] == d).pop("receipt")
    report = core.score(days, rows, spec, now)
    assert (report["verdict"] == "invalid") is invalid


@pytest.mark.parametrize("status,kind", [("unverified", "complete_platform_trace"), ("external_access_detected", "complete_platform_trace"), ("verified_no_external_access", "jo_self_report")])
def test_web_access_is_not_a_gate_and_self_report_is_not_evidence(spec, study, status, kind):
    days, rows, now = study
    for r in rows:
        if r["session"] == days[0]:
            r["audit"]["web_status"], r["audit"]["evidence_type"] = status, kind
    report = core.score(days, rows, spec, now)
    assert report["verdict"] == "replication_only"
    assert report["web_access"] == "web access not restricted; bounded by deadline"
    assert report["observed_model_names"] == []


def test_interim_score_missing_outcome_and_duplicate_refused(spec, study):
    days, rows, now = study
    with pytest.raises(ValueError, match="interim"):
        core.score(days, rows, spec, core.at(days[0], "12:00:00"))
    with pytest.raises(ValueError, match="duplicate"):
        core.score(days, rows + rows[:1], spec, now)
    rows[0].pop("outcome")
    assert core.score(days, rows, spec, now)["verdict"] == "invalid"


def test_missing_baseline_invalidates_and_self_identification_is_discarded(spec, study):
    days, rows, now = study
    rows[0].pop("baseline")
    for row in rows:
        row["audit"] = {"model_name": "self-claimed", "model_source": "jo_self_report"}
    report = core.score(days, rows, spec, now)
    assert report["verdict"] == "invalid"
    assert "missing deadline baseline:" + days[0] + ":MU" in report["faults"]
    assert report["observed_model_names"] == []


def test_deadline_baseline_uses_new_prices_without_changing_target_or_cap(spec):
    p = packet(spec)
    bars = core.fixture_bars(p["session"], count=32)
    bars[-1].update(o=101, c=101, h=103, l=100)
    b = core.deadline_baseline(p, bars, core.at(p["session"], "10:02:05"), spec)
    assert b["reference_price"] == 101
    assert b["baseline_low"] == pytest.approx(99.99)
    assert b["baseline_high"] == pytest.approx(103.02)
    assert b["baseline_directions"]["opening_continuation"] == "up"
    assert p["width_cap_usd"] == 3
    assert p["timing"]["capture_start"] == "10:00:00"
    with pytest.raises(ValueError, match="every expected minute"):
        core.deadline_baseline(p, bars + core.fixture_bars(p["session"], 602, 1), core.at(p["session"], "10:02:05"), spec)
    with pytest.raises(ValueError, match="capture window"):
        core.deadline_baseline(p, bars, core.at(p["session"], "10:02:31"), spec)


def test_baseline_reconstructed_at_score_and_platform_model_changes_flagged(spec, study):
    days, rows, now = study
    for row in rows:
        row["audit"] = {"model_name": "model-a" if row["session"] == days[0] else "model-b",
                        "model_source": "platform", "evidence_type": "platform_record", "evidence_sha256": "a" * 64}
    result = core.score(days, rows, spec, now)
    assert result["observed_model_change"] is True
    assert result["observed_model_names"] == ["model-a", "model-b"]
    rows[0]["baseline"]["baseline_high"] += 1
    with pytest.raises(ValueError, match="baseline integrity"):
        core.score(days, rows, spec, now)


def test_development_approval_never_collects_evaluation(monkeypatch, spec):
    monkeypatch.setattr(runtime, "approval", lambda _: "development")
    monkeypatch.setattr(runtime, "registration", lambda _: {"sessions": ["2098-02-01", "2098-02-02", "2098-02-03"]})
    monkeypatch.setattr(runtime, "now", lambda: core.at("2098-02-03", "10:00:00"))
    network = Mock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr(runtime, "fetch_bars", network)
    assert runtime.job("snapshot", spec)["status"] == "evaluation_not_authorized"
    network.assert_not_called()


def test_baseline_job_freezes_exact_deadline_grid_once(tmp_path, monkeypatch, spec):
    day = "2098-02-01"
    state, baselines = tmp_path / "state", tmp_path / "baselines"
    monkeypatch.setattr(runtime, "STATE", state)
    monkeypatch.setattr(runtime, "BASELINES", baselines)
    monkeypatch.setattr(runtime, "now", lambda: core.at(day, "10:02:05"))
    for ticker in spec["tickers"]:
        core.exclusive_json(state / "snapshots" / day / f"{ticker}.json", packet(spec, day, ticker))
    provider = Mock(return_value={t: core.fixture_bars(day, count=32) for t in spec["tickers"]})
    monkeypatch.setattr(runtime, "fetch_bars", provider)
    runtime.baseline_job(day, {}, spec)
    provider.assert_called_once_with(day, "09:30:00", "10:01:00", spec)
    hashes = core.read_json(baselines / day / "manifest.json")
    assert set(hashes) == set(spec["tickers"])
    assert all(hashes[t] == core.digest(core.read_json(baselines / day / f"{t}.json")) for t in spec["tickers"])
    with pytest.raises(FileExistsError):
        runtime.baseline_job(day, {}, spec)
    assert provider.call_count == 1


@pytest.mark.parametrize("change", ["future", "missing", "duplicate", "nan", "bad_ohlc"])
def test_snapshot_refuses_bad_or_later_bars(spec, change):
    day = "2098-02-01"
    rows = core.fixture_bars(day, count=29)
    if change == "future":
        rows.append(core.fixture_bars(day, 599, 1)[0])
    elif change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = rows[-2]
    elif change == "nan":
        rows[0]["c"] = float("nan")
    else:
        rows[0]["l"] = 103
    with pytest.raises(ValueError):
        core.window(day, rows, 570, 29)


def test_shift_recomputes_55_minute_window(spec):
    shifted = core.with_timing(spec, 5)
    p = packet(shifted)
    assert len(p["bars"]) == 34
    assert p["bars"][-1]["t"].endswith("10:03:00-05:00")
    assert p["timing"]["submission_deadline"] == "10:07:00"
    b = core.deadline_baseline(p, core.fixture_bars(p["session"], count=37), core.at(p["session"], "10:07:05"), shifted)
    assert len(b["bars"]) == 37
    assert b["bars"][-1]["t"].endswith("10:06:00-05:00")
    bars = core.fixture_bars("2098-02-01", 605, 55)
    assert len(core.outcome("2098-02-01", "MU", bars, core.at("2098-02-01", "11:05:01"), shifted)["bars"]) == 55
    with pytest.raises(ValueError):
        core.outcome("2098-02-01", "MU", core.fixture_bars("2098-02-01", 600, 60), core.at("2098-02-01", "11:05:01"), shifted)


def test_exchange_clock_hash_conflicts_and_exact_retry(tmp_path, spec):
    p = packet(spec)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "MU.json", p)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "manifest.json", {t: core.digest(p) for t in spec["tickers"]})
    clock = Mock(return_value=core.at(p["session"], "10:00:06"))
    ex = ForecastExchange(tmp_path / "snapshots", tmp_path / "receipts", spec, enabled=True, clock=clock)
    saved_packet = ex.get_forecast_snapshot("MU")
    clock.return_value = core.at(p["session"], "10:00:07")
    result = ex.save_forecast("MU", saved_packet["snapshot_hash"], forecast())
    assert result["saved_at"].endswith("10:00:07-05:00")
    clock.return_value = core.at(p["session"], "10:03:00")
    assert ex.save_forecast("MU", saved_packet["snapshot_hash"], forecast()) == result
    assert ex.get_forecast_receipt("MU", saved_packet["snapshot_hash"]) == result
    with pytest.raises(ValueError, match="conflict"):
        ex.save_forecast("MU", saved_packet["snapshot_hash"], forecast(terminal_price=100.5))
    with pytest.raises(ValueError, match="hash"):
        ex.save_forecast("MU", "b" * 64, forecast())
    with pytest.raises(ValueError, match="deadline"):
        ex.get_forecast_snapshot("MU")


@pytest.mark.parametrize("save_time,status", [("10:02:00", "answered"), ("10:02:00.001", "late")])
def test_exchange_deadline_is_inclusive_and_enforced_by_server(tmp_path, spec, save_time, status):
    p = packet(spec)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "MU.json", p)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "manifest.json", {t: core.digest(p) for t in spec["tickers"]})
    clock = Mock(return_value=core.at(p["session"], "10:00:06"))
    ex = ForecastExchange(tmp_path / "snapshots", tmp_path / "receipts", spec, enabled=True, clock=clock)
    ex.get_forecast_snapshot("MU")
    clock.return_value = core.at(p["session"], save_time)
    saved = ex.save_forecast("MU", core.digest(p), forecast())
    assert saved["status"] == status
    clock.return_value = core.at(p["session"], "10:05:00")
    assert ex.save_forecast("MU", core.digest(p), forecast()) == saved


def test_model_credentials_and_missing_approval_block_network(monkeypatch, spec):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-never-sent")
    with pytest.raises(ValueError, match="forbidden"):
        runtime.reject_model_credentials()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    network = Mock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr(runtime, "fetch_bars", network)
    monkeypatch.setattr(runtime, "approval", Mock(side_effect=ValueError("not approved")))
    with pytest.raises(ValueError, match="not approved"):
        runtime.job("snapshot", spec)
    network.assert_not_called()


def test_provider_is_fixed_tradier_bounded_and_no_inference_endpoint():
    assert runtime.DATA_URL == "https://api.tradier.com/v1/markets/timesales"
    source = Path(runtime.__file__).read_text()
    assert "api.anthropic.com" not in source and "api.openai.com" not in source
    assert "subprocess" not in source


def test_deployment_is_disabled_and_additive():
    module_spec = importlib.util.spec_from_file_location("forecast_deploy", ROOT / "deploy/advisor_forecast_prepare.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    for action in module.ACTIONS:
        unit, timer = module.service(action), module.timer(action)
        assert "ConditionPathExists=/etc/tj-forecast/approval.json" in unit
        assert "MemoryMax=128M" in unit and "CPUQuota=20%" in unit
        assert "InaccessiblePaths=-/opt/tradejournal -/etc/tradejournal -/var/lib/tradejournal" in unit
        assert "Persistent=false" in timer
        assert "forecast.env" not in unit
        expected_group = "tj-forecast-outcomes" if action in ("outcomes", "baseline") else "tj-forecast-exchange"
        assert f"Group={expected_group}\n" in unit
        writable = module.OUTCOMES if action == "outcomes" else module.BASELINES if action == "baseline" else module.STATE
        assert f"ReadWritePaths={writable}\n" in unit
    assert "10:00:00" in module.timer("snapshot") and "10:05:00" in module.timer("snapshot")
    assert "10:02:00" in module.timer("baseline") and "10:07:00" in module.timer("baseline")
