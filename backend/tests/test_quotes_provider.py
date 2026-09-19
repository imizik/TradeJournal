"""The QUOTES_PROVIDER seam in app/engine/quotes.py.

No network on either side: the Tradier client and the yfinance fetchers are
both replaced. What is exercised is the dispatch, the batching, the per-contract
cache, the order the results come back in, and the fallback -- a bad token must
degrade to the old provider rather than blanking the open-position table.
"""

from __future__ import annotations

import pytest

import app.engine.quotes as quotes
from app.engine.tradier import TradierError, TradierQuote


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    quotes._stock_cache.clear()
    quotes._option_chain_cache.clear()
    quotes._option_contract_cache.clear()
    monkeypatch.setattr(quotes, "tradier_configured", lambda: True)
    monkeypatch.setenv("QUOTES_PROVIDER", "tradier")
    yield
    quotes._stock_cache.clear()
    quotes._option_chain_cache.clear()
    quotes._option_contract_cache.clear()


def _serve(monkeypatch, quotes_by_symbol, record=None):
    def fake_get_quotes(symbols, greeks=False):
        if record is not None:
            record.append({"symbols": list(symbols), "greeks": greeks})
        return {s: quotes_by_symbol[s] for s in symbols if s in quotes_by_symbol}

    monkeypatch.setattr(quotes, "tradier_get_quotes", fake_get_quotes)


def _reject(monkeypatch):
    def fake_get_quotes(symbols, greeks=False):
        raise TradierError("token rejected")

    monkeypatch.setattr(quotes, "tradier_get_quotes", fake_get_quotes)


OPTION = quotes.OptionQuoteRequest(
    ticker="TSLA", expiration="2026-07-10", strike=250.0, option_type="call"
)
OTHER = quotes.OptionQuoteRequest(
    ticker="NBIS", expiration="2026-12-18", strike=42.5, option_type="put"
)


# --- provider selection ------------------------------------------------------

def test_default_is_still_yfinance(monkeypatch):
    monkeypatch.delenv("QUOTES_PROVIDER", raising=False)
    assert quotes.quotes_provider() == "yfinance"


def test_tradier_without_a_key_falls_back_rather_than_failing(monkeypatch):
    monkeypatch.setattr(quotes, "tradier_configured", lambda: False)
    assert quotes.quotes_provider() == "yfinance"


def test_an_unknown_provider_name_does_not_break_the_dashboard(monkeypatch):
    monkeypatch.setenv("QUOTES_PROVIDER", "bloomberg")
    assert quotes.quotes_provider() == "yfinance"


def test_case_and_whitespace_do_not_matter(monkeypatch):
    monkeypatch.setenv("QUOTES_PROVIDER", "  Tradier ")
    assert quotes.quotes_provider() == "tradier"


# --- option quotes -----------------------------------------------------------

def test_every_contract_is_asked_for_in_one_request(monkeypatch):
    record = []
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote("TSLA260710C00250000", last=12.3, bid=12.2, ask=12.4),
        "NBIS261218P00042500": TradierQuote("NBIS261218P00042500", last=1.5, bid=1.4, ask=1.6),
    }, record=record)

    results = quotes.get_option_quotes([OPTION, OTHER])

    assert len(record) == 1
    assert record[0]["greeks"] is True
    assert results[0].last_price == 12.3
    assert results[1].last_price == 1.5


def test_results_line_up_with_the_input_order(monkeypatch):
    # The router zips these against its positions, so an off-by-one here prices
    # one position with another's contract.
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote("TSLA260710C00250000", last=12.3),
        "NBIS261218P00042500": TradierQuote("NBIS261218P00042500", last=1.5),
    })

    results = quotes.get_option_quotes([OTHER, OPTION, OTHER])

    assert [r.last_price for r in results] == [1.5, 12.3, 1.5]


def test_premiums_stay_per_share(monkeypatch):
    # frontend/lib/dashboard.ts multiplies by 100. Doing it here too would
    # value every option position at 100x.
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote("TSLA260710C00250000", last=12.3, bid=12.2, ask=12.4, mid=12.3),
    })

    result = quotes.get_option_quotes([OPTION])[0]

    assert result.last_price == 12.3
    assert result.mid == 12.3


def test_iv_carries_its_vendor_timestamp(monkeypatch):
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote(
            "TSLA260710C00250000", bid=12.2, ask=12.4,
            iv_mid=0.41, greeks_updated_at="2026-09-18T14:00:00Z",
        ),
    })

    result = quotes.get_option_quotes([OPTION])[0]

    assert result.iv == 0.41
    assert result.provider == "tradier"
    # Hourly ORATS data. Without this field nothing downstream can say how old.
    assert result.iv_updated_at == "2026-09-18T14:00:00Z"


def test_a_contract_tradier_does_not_know_is_empty_not_a_fallback(monkeypatch):
    record = []
    _serve(monkeypatch, {}, record=record)
    monkeypatch.setattr(quotes, "_fetch_option_chains", _never_called)

    result = quotes.get_option_quotes([OPTION])[0]

    assert len(record) == 1
    assert result.last_price is None and result.provider == "tradier"


def test_a_second_call_inside_the_ttl_is_served_from_cache(monkeypatch):
    record = []
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote("TSLA260710C00250000", last=12.3),
    }, record=record)

    quotes.get_option_quotes([OPTION])
    again = quotes.get_option_quotes([OPTION])

    assert len(record) == 1
    assert again[0].last_price == 12.3


def test_an_expired_cache_entry_is_refetched(monkeypatch):
    record = []
    _serve(monkeypatch, {
        "TSLA260710C00250000": TradierQuote("TSLA260710C00250000", last=12.3),
    }, record=record)

    quotes.get_option_quotes([OPTION])
    stale_result, stale_time = quotes._option_contract_cache["TSLA260710C00250000"]
    quotes._option_contract_cache["TSLA260710C00250000"] = (
        stale_result,
        stale_time - quotes.CACHE_TTL_SECONDS - 1,
    )
    quotes.get_option_quotes([OPTION])

    assert len(record) == 2


def test_an_unparseable_expiration_is_skipped_not_requested(monkeypatch):
    record = []
    _serve(monkeypatch, {}, record=record)

    bad = quotes.OptionQuoteRequest(
        ticker="TSLA", expiration="not-a-date", strike=250.0, option_type="call"
    )
    results = quotes.get_option_quotes([bad])

    assert results[0].last_price is None
    assert record == []  # nothing to ask about


def test_option_failure_falls_back_to_yfinance(monkeypatch):
    _reject(monkeypatch)
    called = []

    def fake_chains(ticker, expirations):
        called.append((ticker, set(expirations)))
        return {e: {(250.0, "call"): quotes.OptionQuoteResult(last_price=99.0)} for e in expirations}

    monkeypatch.setattr(quotes, "_fetch_option_chains", fake_chains)

    results = quotes.get_option_quotes([OPTION])

    assert called == [("TSLA", {"2026-07-10"})]
    assert results[0].last_price == 99.0


# --- stock quotes ------------------------------------------------------------

def test_stock_quotes_batch_and_prefer_the_last_trade(monkeypatch):
    record = []
    _serve(monkeypatch, {
        "SPY": TradierQuote("SPY", last=690.0, mid=689.5),
        "NVDA": TradierQuote("NVDA", last=180.5, mid=180.4),
    }, record=record)

    prices = quotes.get_stock_quotes(["spy", "nvda"])

    assert len(record) == 1 and record[0]["symbols"] == ["SPY", "NVDA"]
    assert prices == {"SPY": 690.0, "NVDA": 180.5}


def test_a_symbol_with_no_print_yet_uses_the_mid(monkeypatch):
    _serve(monkeypatch, {"THIN": TradierQuote("THIN", last=None, mid=4.25)})

    assert quotes.get_stock_quotes(["THIN"]) == {"THIN": 4.25}


def test_an_unknown_ticker_is_none(monkeypatch):
    _serve(monkeypatch, {})

    assert quotes.get_stock_quotes(["NOPE"]) == {"NOPE": None}


def test_stock_failure_falls_back_to_yfinance(monkeypatch):
    _reject(monkeypatch)
    monkeypatch.setattr(quotes, "_get_fast_info_price", lambda _t: 123.45)
    monkeypatch.setattr(quotes.yf, "Ticker", lambda _t: object())

    assert quotes.get_stock_quotes(["SPY"]) == {"SPY": 123.45}


def _never_called(*_args, **_kwargs):
    raise AssertionError("the yfinance path should not have been reached")
