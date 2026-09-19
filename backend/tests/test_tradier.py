"""Tradier client: response shapes, error mapping, and retry behaviour.

No network. `httpx.post` is replaced, so what is exercised is this module's own
handling of the shapes Tradier documents -- including the one that bites:
`quotes.quote` is an OBJECT for a single symbol and an ARRAY for several.
"""

from __future__ import annotations

import json

import httpx
import pytest

import app.engine.tradier as tradier


class _Response:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test-token")


def _serve(monkeypatch, *responses, record=None):
    """Answer successive posts with the given responses."""
    queue = list(responses)

    def fake_post(url, data=None, headers=None, timeout=None):
        if record is not None:
            record.append({"url": url, "data": data, "headers": headers})
        return queue.pop(0)

    monkeypatch.setattr(tradier.httpx, "post", fake_post)
    monkeypatch.setattr(tradier.time, "sleep", lambda _seconds: None)


def test_single_symbol_comes_back_as_an_object_not_a_list(monkeypatch):
    _serve(monkeypatch, _Response(payload={"quotes": {"quote": {
        "symbol": "SPY", "last": 690.12, "bid": 690.1, "ask": 690.14,
    }}}))

    quotes = tradier.get_quotes(["spy"])

    assert set(quotes) == {"SPY"}
    assert quotes["SPY"].last == 690.12
    assert quotes["SPY"].mid == 690.12


def test_several_symbols_and_unmatched_ones(monkeypatch):
    _serve(monkeypatch, _Response(payload={"quotes": {
        "quote": [
            {"symbol": "SPY", "last": 690.0, "bid": 689.9, "ask": 690.1},
            {"symbol": "NVDA", "last": 180.5, "bid": 180.4, "ask": 180.6},
        ],
        "unmatched_symbols": {"symbol": "NOPE"},
    }}))

    quotes = tradier.get_quotes(["SPY", "NVDA", "NOPE"])

    assert set(quotes) == {"SPY", "NVDA"}
    assert quotes["NVDA"].mid == 180.5


def test_option_greeks_are_passed_through_with_their_timestamp(monkeypatch):
    _serve(monkeypatch, _Response(payload={"quotes": {"quote": {
        "symbol": "TSLA260710C00250000",
        "last": 12.35, "bid": 12.3, "ask": 12.4,
        "bid_date": 1757000000000, "ask_date": 1757000001000,
        "greeks": {
            "delta": 0.55, "gamma": 0.012, "theta": -0.35, "vega": 0.18,
            "mid_iv": 0.4123, "smv_vol": 0.41,
            "updated_at": "2026-09-18T14:00:00Z",
        },
    }}}))

    quote = tradier.get_quotes(["TSLA260710C00250000"], greeks=True)["TSLA260710C00250000"]

    assert quote.iv_mid == 0.4123
    assert quote.delta == 0.55
    # The staleness of an hourly greek is only knowable from this field, so it
    # must survive verbatim rather than being normalized to a datetime here.
    assert quote.greeks_updated_at == "2026-09-18T14:00:00Z"
    assert quote.bid_date == 1757000000000


def test_greeks_flag_is_only_sent_when_asked(monkeypatch):
    record = []
    _serve(
        monkeypatch,
        _Response(payload={"quotes": {"quote": {"symbol": "SPY"}}}),
        _Response(payload={"quotes": {"quote": {"symbol": "SPY"}}}),
        record=record,
    )

    tradier.get_quotes(["SPY"])
    tradier.get_quotes(["SPY"], greeks=True)

    assert "greeks" not in record[0]["data"]
    assert record[1]["data"]["greeks"] == "true"
    # Everything in one request, comma separated -- the whole reason for POST.
    assert record[0]["data"]["symbols"] == "SPY"


def test_symbols_are_batched_into_one_request(monkeypatch):
    record = []
    _serve(monkeypatch, _Response(payload={"quotes": {"quote": []}}), record=record)

    tradier.get_quotes(["spy", " nvda ", "TSLA260710C00250000"])

    assert len(record) == 1
    assert record[0]["data"]["symbols"] == "SPY,NVDA,TSLA260710C00250000"
    assert record[0]["headers"]["Authorization"] == "Bearer test-token"


def test_empty_and_blank_symbol_lists_never_call_out(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("should not have made a request")

    monkeypatch.setattr(tradier.httpx, "post", explode)

    assert tradier.get_quotes([]) == {}
    assert tradier.get_quotes(["", "   "]) == {}


def test_missing_key_is_an_error_not_a_silent_empty(monkeypatch):
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "")
    with pytest.raises(tradier.TradierError, match="TRADIER_API_KEY"):
        tradier.get_quotes(["SPY"])


def test_unauthorized_names_both_causes(monkeypatch):
    _serve(monkeypatch, _Response(status_code=401, payload={}, text="nope"))

    with pytest.raises(tradier.TradierError, match="entitled to market data"):
        tradier.get_quotes(["SPY"])


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    _serve(
        monkeypatch,
        _Response(status_code=429, payload={}, text="slow down", headers={"Retry-After": "1"}),
        _Response(payload={"quotes": {"quote": {"symbol": "SPY", "last": 1.0}}}),
    )

    assert tradier.get_quotes(["SPY"])["SPY"].last == 1.0


def test_rate_limit_that_never_clears_raises(monkeypatch):
    _serve(monkeypatch, *[
        _Response(status_code=429, payload={}, text="slow down", headers={"Retry-After": "1"})
        for _ in range(tradier.MAX_ATTEMPTS)
    ])

    with pytest.raises(tradier.TradierError, match="rate limited"):
        tradier.get_quotes(["SPY"])


def test_transport_errors_are_retried_then_raise(monkeypatch):
    calls = []

    def fake_post(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(tradier.httpx, "post", fake_post)
    monkeypatch.setattr(tradier.time, "sleep", lambda _seconds: None)

    with pytest.raises(tradier.TradierError):
        tradier.get_quotes(["SPY"])
    assert len(calls) == tradier.MAX_ATTEMPTS


def test_non_json_body_is_an_error(monkeypatch):
    _serve(monkeypatch, _Response(payload=None, text="<html>maintenance</html>"))

    with pytest.raises(tradier.TradierError, match="non-JSON"):
        tradier.get_quotes(["SPY"])


def test_absent_and_unparseable_fields_become_none(monkeypatch):
    _serve(monkeypatch, _Response(payload={"quotes": {"quote": {
        "symbol": "THIN", "last": "", "bid": None, "ask": "n/a", "volume": "1234",
    }}}))

    quote = tradier.get_quotes(["THIN"])["THIN"]

    assert quote.last is None
    assert quote.bid is None and quote.ask is None
    assert quote.mid is None
    assert quote.volume == 1234


def test_a_zero_two_sided_market_has_no_mid(monkeypatch):
    _serve(monkeypatch, _Response(payload={"quotes": {"quote": {
        "symbol": "DEAD260710C00250000", "bid": 0.0, "ask": 0.0,
    }}}))

    assert tradier.get_quotes(["DEAD260710C00250000"])["DEAD260710C00250000"].mid is None
