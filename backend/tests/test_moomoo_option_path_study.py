"""Invented offline bars; never provider history, journal fills or live requests."""

from copy import deepcopy
from datetime import datetime, time as day_time
from decimal import Decimal
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from scripts import moomoo_option_path_study as study

COHORT = study.COHORTS[4]
FIXTURE = json.loads((Path(__file__).parent / "fixtures/moomoo/option_path_bars.json").read_text())


def bars(cohort=COHORT):
    return {int(datetime.combine(cohort["day"], day_time.fromisoformat(r["clock"]), study.h.ET).timestamp() * 1000):
            {k: r[k] for k in ("o", "h", "l", "c", "v")} for r in FIXTURE}


def moo_rows(source):
    return [{"time_key": at + 60000, **{field: b[key] for key, field in
             zip(("o", "h", "l", "c", "v"), ("open", "high", "low", "close", "volume"))}}
            for at, b in source.items()]


def test_known_fifo_scale_case_excludes_fill_extremes_and_uses_total_peak():
    source = bars()
    function, hashes = study.local_path_function()
    scenario = study.make_scenario(COHORT, study.scenario_specs("NVDA")["long_scale"], source)
    assert scenario[0].realized_pnl == Decimal("150")
    out = study.compute_scenario(function, scenario, source)
    m = out["metrics"]
    assert m["option_mfe_pct"] == 44.827586
    assert m["option_mae_pct"] == 20
    assert m["option_peak_unrealized_pnl"] == 650
    assert m["option_worst_unrealized_pnl"] == -200
    assert m["option_peak_total_pnl"] == 650
    assert m["option_giveback_from_peak"] == 500
    assert m["option_exit_efficiency"] == 23.076923
    assert m["option_giveback_pct"] == 76.923077
    # 10:01:00 - 09:45:20 = 15m40s; the existing metric floors elapsed minutes.
    assert m["time_to_option_mfe_minutes"] == 15
    assert out["coverage"]["observed_eligible_minutes"] == 6
    assert out["coverage"]["expected_eligible_clock_minutes"] == 57
    assert out["coverage"]["excluded_fill_minutes_present"] == 4
    assert set(hashes) == {"indicators.py", "trade_path.py"}


def test_short_direction_hand_calculation():
    source = bars()
    function, _ = study.local_path_function()
    spec = [("09:45:20", "sell_to_open", 1), ("09:47:40", "buy_to_close", 1)]
    # Prior completed close at exit is 5; hypothetical endpoint is flat.
    scenario = study.make_scenario(COHORT, spec, source)
    out = study.compute_scenario(function, scenario, source)["metrics"]
    assert out["option_mfe_pct"] == 20
    assert out["option_mae_pct"] == 20
    assert out["option_peak_total_pnl"] == 100
    assert out["option_giveback_from_peak"] == 100
    assert out["option_exit_efficiency"] == 0


def test_zero_peak_ratios_and_missing_bars_are_unavailable():
    source = bars()
    function, _ = study.local_path_function()
    scenario = study.make_scenario(COHORT, [("09:45:20", "buy_to_open", 1), ("09:47:40", "sell_to_close", 1)], source)
    flat = {t: dict(o=5, h=5, l=5, c=5, v=1) for t in source}
    out = study.compute_scenario(function, scenario, flat)
    assert out["metrics"]["option_peak_total_pnl"] == 0
    assert out["metrics"]["option_exit_efficiency"] is None
    assert out["metrics"]["time_to_option_mfe_minutes"] is None
    empty = study.compute_scenario(function, scenario, {})
    assert empty["quality"] == "unavailable_bars"
    assert all(v is None for v in empty["metrics"].values())


def test_missing_anchor_never_uses_next_or_moomoo_bar():
    source = bars()
    spec = study.scenario_specs("NVDA")["long_morning"]
    source.pop(min(source))
    assert study.make_scenario(COHORT, spec, source) is None


def test_invalid_hypothetical_allocation_refuses():
    with pytest.raises(study.h.DiagnosticError, match="Hypothetical allocation"):
        study.make_scenario(COHORT, [("09:45:20", "buy_to_open", 1), ("10:45:40", "sell_to_close", 2)], bars())


def test_shift_recovers_intervals_without_mutating_source():
    source = bars()
    wire = moo_rows(source)
    original = deepcopy(wire)
    decoded, stats = study.parse_session(wire, "moomoo", COHORT, -60000, 0)
    assert decoded == source
    assert stats["valid_rows"] == len(source)
    assert wire == original


@pytest.mark.parametrize("bad", [None, True, "secret-response", float("nan"), float("inf"), -1, 0])
def test_malformed_prices_are_counted_not_reflected(bad):
    wire = moo_rows(bars())[:1]
    wire[0]["high"] = bad
    decoded, stats = study.parse_session(wire, "moomoo", COHORT, -60000, 0)
    assert decoded == {}
    assert stats["invalid_rows"] == 1
    assert "secret-response" not in json.dumps(stats)


def test_duplicates_removed_zero_volume_counted_and_invalid_precision_not_scaled():
    wire = moo_rows(bars())[:2]
    wire[0]["volume"] = "0"
    decoded, stats = study.parse_session(wire, "moomoo", COHORT, -60000, 0)
    assert stats["zero_volume_rows"] == 1
    assert len(decoded) == 2
    decoded, stats = study.parse_session(wire + [wire[0]], "moomoo", COHORT, -60000, 0)
    assert len(decoded) == 1
    assert stats["duplicate_rows"] == 1
    decoded, _ = study.parse_session(wire, "moomoo", COHORT, -60000, True)
    assert all(b["v"] is None for b in decoded.values())


def test_spy_late_session_is_included_but_session_close_excluded():
    cohort = study.COHORTS[-1]
    at = int(datetime.combine(cohort["day"], day_time(16, 14), study.h.ET).timestamp() * 1000)
    source = {at: dict(o=1, h=1, l=1, c=1, v=1), at + 60000: dict(o=1, h=1, l=1, c=1, v=1)}
    decoded, stats = study.parse_session(moo_rows(source), "moomoo", cohort, -60000, 0)
    assert list(decoded) == [at]
    assert stats["expected_clock_minutes"] == 405
    assert stats["outside_session"] == 1


def test_pagination_and_identity_failures_cannot_be_matches():
    function, _ = study.local_path_function()
    result = study.comparisons(COHORT, bars(), bars(), bars(), function, False)
    for row in result.values():
        if "shifted_minus_alpaca" in row:
            assert row["status"] == "source_incomplete_or_unresolved"
            assert row["shifted_minus_alpaca"] is None


@pytest.mark.parametrize("change", [{"code": "US.other"}, {"stock_owner": "US.SPY"},
                                  {"contract_size": 20}, {"lot_size": True}, {"stock_type": "STOCK"}])
def test_nonstandard_or_mismatched_identity_is_refused(change):
    profile = dict(code=COHORT["code"], stock_owner="US.NVDA", stock_type="DRVT", lot_size=100, contract_size=100)
    assert study.profile_matches(profile, COHORT)
    profile.update(change)
    assert not study.profile_matches(profile, COHORT)


@pytest.mark.parametrize("mode", ["ok", "empty", "paged", "permission", "missing_profile"])
def test_fixed_cohort_pipeline_uses_only_bounded_market_reads(monkeypatch, mode):
    def handler(request):
        if request.url.path == study.h.TIME_PATH:
            return httpx.Response(200, json={"server_time_ms": "1791676800000"})
        if request.url.path == study.h.BASIC_PATH:
            profiles = [] if mode == "missing_profile" else [dict(code=c["code"], stock_owner="US." + c["root"],
                stock_type="DRVT", lot_size=100, contract_size=100) for c in study.COHORTS]
            return httpx.Response(200, json={"ret_code": 0, "data": {"basic_list": profiles}})
        if request.url.host == "webapi.moomoo.com":
            c = next(c for c in study.COHORTS if c["code"] in request.url.path)
            if mode == "permission":
                return httpx.Response(200, json={"ret_code": -9, "ret_msg": "secret-response"})
            return httpx.Response(200, json={"ret_code": 0, "data": {
                "kline_list": [] if mode == "empty" else moo_rows(bars(c)),
                "volume_precision": 0, "next_time": 1 if mode == "paged" else 0}})
        assert request.url.host == "data.alpaca.markets"
        assert request.url.path == "/v1beta1/options/bars"
        assert "feed" not in request.url.params
        assert request.url.params["limit"] == "1000"
        c = next(c for c in study.COHORTS if c["occ"] == request.url.params["symbols"])
        rows = [dict(t=datetime.fromtimestamp(t / 1000, study.h.timezone.utc).isoformat(), **b) for t, b in bars(c).items()]
        return httpx.Response(200, json={"bars": {c["occ"]: rows}, "next_page_token": None})

    monkeypatch.setattr(study.h.time, "sleep", lambda _: None)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # public invented fixture
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        reader = study.Reader(client, "public-test-appkey", key)
        report = study.run(reader, {"ALPACA_API_KEY": "public-test-key", "ALPACA_API_SECRET": "public-test-secret"})
    assert report["request_count"] <= 18
    assert len(report["contracts"]) == 8
    assert "secret-response" not in json.dumps(report)
    assert "public-test-secret" not in json.dumps(report)
    assert "public-test-appkey" not in json.dumps(report)
    for contract in report["contracts"].values():
        assert contract["comparison_eligible"] == (mode == "ok")
    if mode == "permission":
        assert sum(r.get("ret_code") == -9 for r in report["requests"].values()) == 1
    with pytest.raises(study.h.DiagnosticError, match="allowlist"):
        study.h.check_destination("moomoo", httpx.Request("GET", study.h.HOST + "/api/v1.0/trade/orders"), study.h.DEFAULT_DAY)
