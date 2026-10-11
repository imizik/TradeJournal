from datetime import datetime, time, timedelta, timezone, date
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app.engine.market_map import ET
from app.engine.research_studio import NEWER_END, PROSPECTIVE_START, PROSPECTIVE_END, session_dates, parse_definition
from app.engine.research_studio_data import DiscoveryCache
from app.engine.research_studio_prospective import ProspectiveStudy, definitions, due_sessions, sessions
import app.engine.research_studio_prospective as forward


def stamp(day, hour=21):
    return datetime.combine(day, time(hour), ET)


def rows(day, *, event=False):
    out = []
    start = datetime.combine(day, time(9, 30), ET)
    for i in range(390):
        p = 100 if not event or i < 15 else 99 if i < 59 else 101
        out.append({"t": (start+timedelta(minutes=i)).astimezone(timezone.utc).isoformat(),
                    "o": p, "h": p+.2, "l": p-.2, "c": p, "v": 200 if event else 100})
    return out


@pytest.fixture
def study(tmp_path):
    records = tmp_path/"records"
    cache = tmp_path/"future"/"sip"
    warmup = tmp_path/"warmup"/"sip"
    records.mkdir(mode=0o700)
    for root in (cache, warmup):
        for symbol in ("MU", "SPY"):
            (root/symbol).mkdir(mode=0o700, parents=True)
    for day in session_dates(NEWER_END, version=2)[-30:]:
        for symbol in ("MU", "SPY"):
            (warmup/symbol/f"{day}.json").write_text(json.dumps(rows(day)))
    result = ProspectiveStudy(records, cache, warmup)
    result.register(stamp(date(2026, 10, 11)))
    result.seal()
    return result


def test_protocol_calendar_defaults_and_registration_before_source(study, monkeypatch):
    assert len(sessions()) == 124
    assert date(2026, 11, 26) not in sessions()
    assert date(2027, 3, 26) not in sessions()
    assert date(2026, 11, 27) in sessions()
    for definition in definitions():
        assert parse_definition(definition.canonical()) == definition
    plain = DiscoveryCache(study.cache.root, allow_newer_mu=True)
    monkeypatch.setattr(plain, "_read", lambda *a, **k: pytest.fail("unapproved source opened"))
    with pytest.raises(ValueError, match="not operator-approved"):
        plain.snapshot(("MU",), through=PROSPECTIVE_START, version=3)
    assert due_sessions(stamp(PROSPECTIVE_START, 20)) == ()
    assert study.collect(lambda *a: pytest.fail("pre-close network call"), stamp(PROSPECTIVE_START, 20)) == []
    registration = study.registration()
    assert study.register(stamp(PROSPECTIVE_END)) == registration


def test_collect_once_immutable_receipts_and_frozen_warmup(study):
    calls = []
    def fetch(day, symbols):
        calls.append((day, symbols))
        return {symbol: rows(day, event=symbol=="MU") for symbol in symbols}
    assert study.collect(fetch, stamp(PROSPECTIVE_START)) == [{"session": str(PROSPECTIVE_START), "state": "complete"}]
    assert study.collect(fetch, stamp(PROSPECTIVE_START)) == []
    assert len(calls) == 1
    receipt = study._artifact(f"session.{PROSPECTIVE_START}.json")
    path = study.cache.root/"MU"/f"{PROSPECTIVE_START}.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["source"]["MU"]["sha256"]
    # An outside cache correction must not change this study's frozen warm-up.
    (study.warmup.root/"MU"/f"{NEWER_END}.json").write_text("[]")
    with pytest.raises(ValueError, match="not due"):
        study.review(stamp(PROSPECTIVE_END-timedelta(days=1)))
    report = study.review(stamp(PROSPECTIVE_END))
    assert len(report["runs"]) == 2
    for run in report["runs"]:
        assert run["primary_30m_percent"]["event_n"] == 1
        assert run["primary_30m_percent"]["event_mean"] == pytest.approx(2/99*100)
        assert run["primary_30m_percent"]["uncertainty"]["unavailable_reason"] == "insufficient_weeks"
    assert study.review(stamp(PROSPECTIVE_END)) == report
    assert study.status(stamp(PROSPECTIVE_END))["missing_sessions"] == [str(d) for d in sessions()[1:]]


def test_partial_source_is_reported_and_retried_without_overwrite(study):
    def incomplete(day, symbols):
        return {symbol: rows(day)[:-1] for symbol in symbols}
    assert study.collect(incomplete, stamp(PROSPECTIVE_START))[0]["state"] == "incomplete"
    assert not (study.cache.root/"MU"/f"{PROSPECTIVE_START}.json").exists()
    assert study.collect(lambda *a: pytest.fail("duplicate daily attempt"), stamp(PROSPECTIVE_START)) == []
    study.collect(lambda day, symbols: {s: rows(day) for s in symbols}, stamp(PROSPECTIVE_START+timedelta(days=1)))
    assert study.status(stamp(PROSPECTIVE_START+timedelta(days=1)))["completed_sessions"] == 2


def test_clock_storage_and_runtime_fail_before_network(study, monkeypatch):
    def never(*args):
        pytest.fail("network must not run")
    with pytest.raises(ValueError, match="aware"):
        study.collect(never, datetime(2026, 10, 12))
    monkeypatch.setattr(forward, "BUDGET", 1)
    with pytest.raises(ValueError, match="budget"):
        study.collect(never, stamp(PROSPECTIVE_START))
    monkeypatch.setattr(forward, "BUDGET", 250*1024*1024)
    monkeypatch.setattr(study, "_runtime", lambda: {"changed": True})
    with pytest.raises(ValueError, match="runtime changed"):
        study.collect(never, stamp(PROSPECTIVE_START))


def test_future_payload_correction_is_refused_before_review(study):
    study.collect(lambda day, symbols: {s: rows(day) for s in symbols}, stamp(PROSPECTIVE_START))
    (study.cache.root/"MU"/f"{PROSPECTIVE_START}.json").write_text("[]")
    with pytest.raises(ValueError, match="immutable session receipt"):
        study.review(stamp(PROSPECTIVE_END))


def test_symlink_and_replaced_cache_root_are_refused(study):
    (study.cache.root/"MU"/f"{PROSPECTIVE_START}.json").symlink_to(study.store.root/"registration.json")
    with pytest.raises(ValueError):
        study.collect(lambda *a: pytest.fail("linked source must not fetch"), stamp(PROSPECTIVE_START))
    original = study.cache.root
    original.rename(original.with_name("old"))
    original.mkdir()
    with pytest.raises(ValueError, match="root directory changed"):
        study.collect(lambda *a: pytest.fail("replaced root must not fetch"), stamp(PROSPECTIVE_START))


def test_limited_recent_catchup_and_sanitized_failure(study):
    calls = []
    def fail(day, symbols):
        calls.append(day)
        raise ValueError("private-provider-secret-do-not-print")
    with pytest.raises(ValueError, match="collection failed") as exc:
        study.collect(fail, stamp(date(2026, 11, 6)))
    assert "private-provider-secret" not in str(exc.value)
    assert calls == list(due_sessions(stamp(date(2026, 11, 6)))[-5:-4])
    assert "private-provider-secret" not in "".join(p.read_text() for p in study.store.root.glob("attempt.*.json"))


def test_final_collection_failure_closes_network_and_reviews_only_committed_bytes(study):
    def fail(*args):
        raise ValueError("provider unavailable")
    with pytest.raises(ValueError, match="collection failed"):
        study.collect(fail, stamp(PROSPECTIVE_END))
    assert study.collect(lambda *a: pytest.fail("no network after terminal attempt"), stamp(PROSPECTIVE_END+timedelta(days=3))) == []
    # A retained partial file without a committed two-symbol receipt is excluded.
    (study.cache.root/"MU"/f"{PROSPECTIVE_END}.json").write_text(json.dumps(rows(PROSPECTIVE_END, event=True)))
    report = study.review(stamp(PROSPECTIVE_END))
    assert all(run["primary_30m_percent"]["event_n"] == 0 for run in report["runs"])
    assert study._artifact("review-exposure.json")["source_start"] == "2023-06-01"


def provider_module():
    path = Path(__file__).parents[1]/"scripts/research_studio_prospective.py"
    spec = importlib.util.spec_from_file_location("test_forward_provider", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_request_is_market_data_only_with_strict_bounds(monkeypatch):
    module = provider_module()
    monkeypatch.setenv("ALPACA_API_KEY", "invented-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "invented-secret")
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url.host == "data.alpaca.markets"
        assert request.url.path == "/v2/stocks/bars"
        assert request.url.params["feed"] == "sip"
        assert request.url.params["adjustment"] == "raw"
        assert request.url.params["symbols"] == "MU,SPY"
        assert request.url.params["start"].endswith("09:30:00-04:00")
        assert request.url.params["end"].endswith("15:59:59-04:00")
        return httpx.Response(200, json={"bars": {s: rows(PROSPECTIVE_START) for s in ("MU", "SPY")}, "next_page_token": None})
    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.Client(transport=httpx.MockTransport(handle), **kwargs)
    assert len(module.fetch_sip(PROSPECTIVE_START, ("MU", "SPY"), client_factory=factory)["MU"]) == 390
    with pytest.raises(ValueError, match="outside"):
        module.fetch_sip(NEWER_END, ("MU", "SPY"), client_factory=factory)
    with pytest.raises(ValueError, match="outside"):
        module.fetch_sip(PROSPECTIVE_START, ("AAPL",), client_factory=factory)
    assert len(requests) == 1


@pytest.mark.parametrize("response", [
    httpx.Response(403, text="private-provider-secret"),
    httpx.Response(200, json={"bars": {"AAPL": []}, "next_page_token": None}),
    httpx.Response(200, json={"bars": {}, "next_page_token": "same"}),
])
def test_provider_failures_do_not_fallback_or_expose_response(monkeypatch, response):
    module = provider_module()
    monkeypatch.setenv("ALPACA_API_KEY", "invented-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "invented-secret")
    def factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(lambda request: response), **kwargs)
    with pytest.raises(ValueError) as exc:
        module.fetch_sip(PROSPECTIVE_START, ("MU", "SPY"), client_factory=factory)
    assert "private-provider-secret" not in str(exc.value)
