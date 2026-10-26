"""Mock transport only. No credentials or market data are read."""
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import etf_input_acquire as acquire  # noqa: E402


@pytest.fixture
def fake_bars(monkeypatch):
    # Invented weekdays, explicitly NOT an exchange calendar or historical prices.
    day, days = date(2016, 1, 4), []
    while len(days) < 2200:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    digest = hashlib.sha256(("\n".join(days)+"\n").encode()).hexdigest()
    monkeypatch.setattr(acquire, "DATES_SHA256", digest)
    row = {"o": 100, "h": 100, "l": 100, "c": 100, "v": 1, "n": 1, "vw": 100}
    return {"bars": {s: [{**row, "t": d+"T05:00:00Z"} for d in days] for s in acquire.SYMBOLS},
            "next_page_token": None}


def test_default_plan_does_not_read_credentials_or_create_archive(monkeypatch, capsys):
    def forbid(*args, **kwargs):
        raise AssertionError("default must remain plan-only")
    monkeypatch.setattr(acquire, "read_keys", forbid)
    monkeypatch.setattr(acquire, "acquire", forbid)
    acquire.main([])
    plan = json.loads(capsys.readouterr().out)
    assert plan["max_requests"] == sum(r["max_pages"] for r in plan["requests"]) == 12
    assert plan["evaluation_authorized"] is False
    assert plan["requests"][0]["params"]["end"] == "2024-09-30T23:59:59-04:00"
    assert plan["requests"][1]["params"]["end"] == "2026-10-26"


def test_keys_are_filtered_without_interpolation_or_environment_loading(tmp_path, monkeypatch):
    source = tmp_path / ".env"
    source.write_text("DATABASE_URL=must-not-load\nALPACA_API_KEY='fixture-key'\nexport ALPACA_API_SECRET='${UNRELATED_SECRET}'\n")
    monkeypatch.setattr(acquire, "CREDENTIAL_SOURCE", source)
    before = dict(os.environ)
    assert acquire.read_keys() == ("fixture-key", "${UNRELATED_SECRET}")
    assert dict(os.environ) == before


def test_fixed_gets_pagination_hashes_and_no_automatic_acceptance(tmp_path, fake_bars):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "data.alpaca.markets"
        assert request.headers["APCA-API-KEY-ID"] == "fixture-key"
        if request.url.path.endswith("bars"):
            if "page_token" not in request.url.params:
                return httpx.Response(200, json={"bars": {"SPY": fake_bars["bars"]["SPY"]}, "next_page_token": "page2"})
            assert request.url.params["page_token"] == "page2"
            return httpx.Response(200, json={"bars": {s: r for s, r in fake_bars["bars"].items() if s != "SPY"}, "next_page_token": None})
        assert request.url.path == "/v1/corporate-actions"
        assert request.url.params["data_quality"] == "all"
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    output = tmp_path / "fresh"
    result = acquire.acquire(output, "fixture-key", "fixture-secret", transport=httpx.MockTransport(respond))
    assert len(calls) == 3 and result["status"] == "acquired_unaccepted"
    assert result["eligible_for_evaluation"] is False and result["strategy_evaluated"] is False
    assert result["historical_actions_complete"] == "unverified"
    assert len(result["daily_coverage"]) == 5
    for page in result["pages"]:
        path = output / page["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == page["sha256"]
        assert path.stat().st_mode & 0o777 == 0o400
    text = (output / "receipt.json").read_text()
    assert "fixture-key" not in text and "fixture-secret" not in text
    with pytest.raises(FileExistsError):
        acquire.acquire(output, "fixture-key", "fixture-secret", transport=httpx.MockTransport(respond))
    assert len(calls) == 3


@pytest.mark.parametrize("fault", ["redirect", "http", "timeout", "malformed", "repeated_token", "page_cap", "oversize", "elapsed"])
def test_failures_preserve_partial_receipt_without_retry_or_acceptance(tmp_path, monkeypatch, fault):
    calls = []
    def respond(request):
        calls.append(request)
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid/leak"})
        if fault == "http":
            return httpx.Response(403, text="sensitive-response-body")
        if fault == "timeout":
            raise httpx.ReadTimeout("sensitive-request-details")
        if fault == "malformed":
            return httpx.Response(200, content=b"bad json")
        if fault == "oversize":
            return httpx.Response(200, content=b"x" * 11)
        return httpx.Response(200, json={"bars": {}, "next_page_token": "same" if fault == "repeated_token" else str(len(calls))})
    if fault == "oversize":
        monkeypatch.setattr(acquire, "MAX_BYTES", 10)
    ticks = iter([0, 121])
    clock = (lambda: next(ticks)) if fault == "elapsed" else (lambda: 0)
    output = tmp_path / fault
    with pytest.raises(acquire.AcquisitionError, match="incomplete") as failure:
        acquire.acquire(output, "fake-key", "fake-secret", transport=httpx.MockTransport(respond), clock=clock)
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == "incomplete" and receipt["eligible_for_evaluation"] is False
    assert "sensitive" not in str(failure.value) and "fake-secret" not in str(failure.value)
    assert len(calls) == {"elapsed": 0, "repeated_token": 2, "page_cap": 4}.get(fault, 1)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_hash", "protected", "nan", "missing_symbol", "unexpected_symbol"])
def test_bad_coverage_refuses_without_returns(fake_bars, monkeypatch, fault):
    rows = fake_bars["bars"]["SPY"]
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows[-1] = rows[-2]
    elif fault == "wrong_hash":
        monkeypatch.setattr(acquire, "DATES_SHA256", "0" * 64)
    elif fault == "protected":
        rows[-1]["t"] = "2024-10-01T04:00:00Z"
    elif fault == "nan":
        rows[-1]["c"] = "NaN"
    elif fault == "missing_symbol":
        del fake_bars["bars"]["BIL"]
    elif fault == "unexpected_symbol":
        fake_bars["bars"]["OTHER"] = []
    with pytest.raises(acquire.AcquisitionError):
        acquire.coverage([fake_bars])


def test_protected_bar_refuses_before_any_action_request(tmp_path, fake_bars):
    fake_bars["bars"]["SPY"][-1]["t"] = "2024-10-01T04:00:00Z"
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=fake_bars)
    with pytest.raises(acquire.AcquisitionError):
        acquire.acquire(tmp_path / "archive", "fake", "fake", transport=httpx.MockTransport(respond))
    assert len(calls) == 1


@pytest.mark.parametrize("args", [["--output", "/unused"], ["--acquire"], ["--acquire", "--output", "relative"], ["--evaluate"]])
def test_cli_refuses_invalid_or_evaluation_arguments_before_keys(args, monkeypatch):
    monkeypatch.setattr(acquire, "read_keys", lambda: pytest.fail("must not read credentials"))
    with pytest.raises(SystemExit):
        acquire.main(args)


def test_cli_deadline_interrupts_a_blocked_acquisition_without_network(tmp_path):
    code = """import sys,time
sys.path.insert(0, sys.argv[1])
import etf_input_acquire as a
a.MAX_SECONDS = 1
a.read_keys = lambda: ('invented', 'invented')
a.acquire = lambda *args: time.sleep(30)
a.main(['--acquire', '--output', sys.argv[2]])
"""
    result = subprocess.run([sys.executable, "-c", code, str(Path(acquire.__file__).parent),
                             str(tmp_path / "unused")], capture_output=True, text=True,
                            timeout=5, cwd=tmp_path)
    assert result.returncode == 1
    assert "acquisition failed" in result.stderr and not result.stdout
