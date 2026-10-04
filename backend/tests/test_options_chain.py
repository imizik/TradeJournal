"""Option chain adapter (Charts C4.1): recorded Tradier responses, normalized.

`fixtures/tradier/options_2026-10-01.json` holds live production responses
recorded after the 2026-10-01 close: SPY and SPX expiration lists verbatim, and
verbatim rows from SPY 2026-10-02 and SPX 2026-10-16 (where one response
carried both the SPX and the SPXW root). No network: `httpx.get` and the clock
are replaced. Live access is checked separately by
`scripts/check_options_chain.py`.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

import httpx
import pytest

import app.engine.options_chain as options
from app.engine.options_chain import OptionsChainError, TradierOptions, parse_chain, parse_expirations

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tradier" / "options_2026-10-01.json").read_text())
SPY_DAY = date(2026, 10, 2)
SPX_DAY = date(2026, 10, 16)
CAPTURED = datetime(2026, 10, 2, 1, 37, tzinfo=timezone.utc)


def _spy(payload=None):
    return parse_chain(payload or FIXTURE["spy_chain_2026-10-02"], "SPY", SPY_DAY, CAPTURED)


def _rows(name="spy_chain_2026-10-02"):
    return copy.deepcopy(FIXTURE[name]["options"]["option"])


def _by_symbol(chain):
    return {c.symbol: c for c in chain.contracts}


# --- parsing the recorded responses ----------------------------------------


def test_a_recorded_chain_normalizes_every_field():
    chain = _spy()

    assert (chain.underlying, chain.expiration, chain.provider, chain.fetched_at) == ("SPY", SPY_DAY, "tradier", CAPTURED)
    assert len(chain.contracts) == 9
    atm = _by_symbol(chain)["SPY261002C00764000"]
    assert (atm.underlying, atm.root, atm.expiration, atm.option_type, atm.strike, atm.multiplier) == (
        "SPY", "SPY", SPY_DAY, "call", 764.0, 100)
    assert (atm.bid, atm.ask, atm.last, atm.bid_size, atm.ask_size) == (3.03, 3.05, 3.07, 15, 50)
    assert (atm.volume, atm.open_interest) == (78437, 3553)
    assert (atm.iv, atm.iv_smoothed) == (0.1554, 0.157)
    assert (atm.delta, atm.gamma, atm.theta, atm.vega) == (0.5159, 0.06109, -1.4371, 0.1595)
    # Provider event times are epoch milliseconds: 16:14:59 New York, the SPY option close.
    assert atm.bid_time == datetime(2026, 10, 1, 20, 14, 59, tzinfo=timezone.utc)
    assert atm.trade_time == datetime(2026, 10, 1, 20, 14, 52, 357000, tzinfo=timezone.utc)
    # The greeks' own stamp survives verbatim: its time zone is not documented.
    assert atm.greeks_updated_at == "2026-10-01 20:00:06"


def test_rows_keep_the_providers_order():
    assert [c.symbol for c in _spy().contracts] == [row["symbol"] for row in _rows()]


def test_placeholders_become_unavailable_and_real_zeros_stay_zero():
    contracts = _by_symbol(_spy())
    never = contracts["SPY261002C00525000"]  # deep in the money, never traded
    assert never.trade_time is None and never.last is None
    assert never.iv is None  # Tradier's mid_iv of 0 means "could not compute"
    assert never.iv_smoothed == 0.1999
    assert (never.open_interest, never.volume) == (0, 0)  # observed zeros, not missing

    far = contracts["SPY261002P00500000"]
    assert far.bid == 0.0 and far.ask == 0.01
    assert far.open_interest == 1076 and far.volume == 0
    assert far.gamma == 0.0  # the provider's rounded value is passed through, not recomputed here

    traded_without_iv = contracts["SPY261002C00575000"]
    assert traded_without_iv.iv is None and traded_without_iv.last == 189.89


def test_one_spx_date_keeps_the_spx_and_spxw_roots_apart():
    chain = parse_chain(FIXTURE["spx_chain_2026-10-16"], "SPX", SPX_DAY, CAPTURED)

    assert {c.underlying for c in chain.contracts} == {"SPX"}
    assert sorted((c.root, c.option_type, c.strike, c.open_interest) for c in chain.contracts) == [
        ("SPX", "call", 7680.0, 528), ("SPX", "put", 7680.0, 574),
        ("SPXW", "call", 7680.0, 232), ("SPXW", "put", 7680.0, 448),
    ]


def test_expirations_are_sorted_dates_with_every_root():
    spy = parse_expirations(FIXTURE["spy_expirations"])
    spx = parse_expirations(FIXTURE["spx_expirations"])

    assert (len(spy), spy[0], spy[-1]) == (33, date(2026, 10, 2), date(2029, 1, 19))
    assert spy == sorted(spy)
    # SPXW dailies appear only because every root is requested.
    assert len(spx) == 55 and date(2026, 10, 19) in spx and date(2026, 10, 19) not in spy


def test_the_single_and_empty_shapes():
    assert parse_expirations({"expirations": None}) == []  # an unknown or optionless symbol, as recorded live
    assert parse_expirations({"expirations": {"date": "2026-10-02"}}) == [date(2026, 10, 2)]

    assert _spy({"options": None}).contracts == ()  # a date with nothing listed, as recorded live
    one = _spy({"options": {"option": _rows()[0]}})
    assert [c.symbol for c in one.contracts] == ["SPY261002P00500000"]


def test_a_contract_size_other_than_100_is_kept_and_a_missing_one_is_not_assumed():
    rows = _rows()
    rows[0]["contract_size"] = 10
    rows[1]["contract_size"] = None
    rows[2]["contract_size"] = 0
    contracts = _spy({"options": {"option": rows}}).contracts

    assert [c.multiplier for c in contracts[:3]] == [10, None, None]


def test_missing_greeks_leave_every_greek_unavailable():
    rows = _rows()
    rows[0]["greeks"] = None
    contract = _spy({"options": {"option": rows[:1]}}).contracts[0]

    assert (contract.iv, contract.iv_smoothed, contract.delta, contract.gamma, contract.greeks_updated_at) == (None,) * 5
    assert contract.open_interest == 1076


def _broken(change):
    rows = _rows()
    change(rows)
    return {"options": {"option": rows}}


@pytest.mark.parametrize("change", [
    pytest.param(lambda rows: rows[0].update(expiration_date="2026-10-05"), id="another expiration"),
    pytest.param(lambda rows: rows[0].update(strike=505.0), id="strike disagrees with OCC symbol"),
    pytest.param(lambda rows: rows[0].update(option_type="call"), id="side disagrees with OCC symbol"),
    pytest.param(lambda rows: rows[0].update(root_symbol="SPYW"), id="root disagrees with OCC symbol"),
    pytest.param(lambda rows: rows[0].update(underlying="QQQ"), id="another underlying"),
    pytest.param(lambda rows: rows[0].update(symbol="SPY"), id="not an OCC symbol"),
    pytest.param(lambda rows: rows[0].pop("strike"), id="no strike"),
    pytest.param(lambda rows: rows[0].update(strike="n/a"), id="unreadable strike"),
    pytest.param(lambda rows: rows.append(copy.deepcopy(rows[0])), id="listed twice"),
    pytest.param(lambda rows: rows.append("SPY261002C00764000"), id="a row that is not an object"),
])
def test_a_row_that_does_not_identify_one_contract_rejects_the_whole_chain(change):
    with pytest.raises(ValueError, match="malformed option chain"):
        _spy(_broken(change))


@pytest.mark.parametrize("payload", [{}, {"options": "none"}, {"options": {}}, [], None])
def test_unreadable_chain_shapes_are_errors(payload):
    with pytest.raises(ValueError):
        parse_chain(payload, "SPY", SPY_DAY, CAPTURED)


@pytest.mark.parametrize("payload", [{}, {"expirations": {}}, {"expirations": {"date": 20261002}}, {"expirations": {"date": ["10/02/2026"]}}])
def test_unreadable_expiration_shapes_are_errors(payload):
    with pytest.raises(ValueError):
        parse_expirations(payload)


# --- requests, budget and errors --------------------------------------------


class _Response:
    def __init__(self, status_code=200, payload=None, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class _Clock:
    def __init__(self, now=1_790_904_000.0):
        self.now = now
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def client(clock):
    return TradierOptions(clock=clock, sleep=clock.sleep)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(options.tradier, "TRADIER_API_KEY", "test-token")
    monkeypatch.setattr(options.tradier, "TRADIER_BASE_URL", "https://api.tradier.test")


def _serve(monkeypatch, *responses):
    queue, calls = list(responses), []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(options.httpx, "get", fake_get)
    return calls


def test_one_request_per_expiration_with_greeks(monkeypatch, client, clock):
    calls = _serve(monkeypatch, _Response(payload=FIXTURE["spy_chain_2026-10-02"]))

    chain = client.chain(" spy ", SPY_DAY)

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.tradier.test/v1/markets/options/chains"
    assert calls[0]["params"] == {"symbol": "SPY", "expiration": "2026-10-02", "greeks": "true"}
    assert calls[0]["headers"]["Authorization"] == "Bearer test-token"
    assert len(chain.contracts) == 9
    assert chain.fetched_at == datetime.fromtimestamp(clock.now, timezone.utc)


def test_expirations_ask_for_every_root(monkeypatch, client):
    calls = _serve(monkeypatch, _Response(payload=FIXTURE["spx_expirations"]))

    dates = client.expirations("SPX")

    assert calls[0]["url"].endswith("/v1/markets/options/expirations")
    assert calls[0]["params"] == {"symbol": "SPX", "includeAllRoots": "true", "strikes": "false"}
    assert len(dates) == 55


def test_the_budget_refuses_the_31st_request_in_a_minute_without_calling_out(monkeypatch, client, clock):
    calls = _serve(monkeypatch, _Response(payload={"options": None}))
    for _ in range(30):
        client.chain("SPY", SPY_DAY)
        clock.now += 1

    with pytest.raises(OptionsChainError) as refused:
        client.chain("SPY", SPY_DAY)

    assert refused.value.code == "rate_limited"
    assert len(calls) == 30


def test_a_caller_that_may_wait_sleeps_until_the_oldest_slot_frees(monkeypatch, client, clock):
    calls = _serve(monkeypatch, _Response(payload={"options": None}))
    start = clock.now
    for _ in range(30):
        client.chain("SPY", SPY_DAY)
        clock.now += 1

    client.chain("SPY", SPY_DAY, wait=True)

    assert len(calls) == 31
    assert clock.now == start + 60  # exactly when the first request leaves the window
    assert clock.slept == [30]


def test_a_429_pauses_option_reads_for_a_minute(monkeypatch, client, clock):
    calls = _serve(monkeypatch, _Response(status_code=429), _Response(payload={"options": None}))

    with pytest.raises(OptionsChainError) as limited:
        client.chain("SPY", SPY_DAY)
    clock.now += 30
    with pytest.raises(OptionsChainError) as paused:
        client.chain("SPY", SPY_DAY)

    assert limited.value.code == paused.value.code == "rate_limited"
    assert len(calls) == 1  # nothing is retried, and the pause sends nothing
    clock.now += 30
    client.chain("SPY", SPY_DAY)
    assert len(calls) == 2


def test_a_waiting_caller_sleeps_through_a_pause(monkeypatch, client, clock):
    calls = _serve(monkeypatch, _Response(status_code=429), _Response(payload={"options": None}))
    with pytest.raises(OptionsChainError):
        client.chain("SPY", SPY_DAY)

    client.chain("SPY", SPY_DAY, wait=True)

    assert clock.slept == [60] and len(calls) == 2


@pytest.mark.parametrize("answer, code", [
    pytest.param(_Response(status_code=401), "access_denied", id="401"),
    pytest.param(_Response(status_code=403), "access_denied", id="403"),
    pytest.param(_Response(status_code=400), "provider_unavailable", id="400"),
    pytest.param(_Response(status_code=502), "provider_unavailable", id="502"),
    pytest.param(_Response(payload=None, text="<html>maintenance</html>"), "provider_unavailable", id="not JSON"),
    pytest.param(_Response(payload={"fault": {"faultstring": "Invalid Access Token"}}), "provider_unavailable", id="fault"),
    pytest.param(httpx.ConnectError("no route"), "provider_unavailable", id="transport"),
    pytest.param(_Response(payload={"options": {"option": "garbage"}}), "malformed", id="malformed"),
])
def test_failures_are_coded_and_each_costs_one_request(monkeypatch, client, answer, code):
    calls = _serve(monkeypatch, answer)

    with pytest.raises(OptionsChainError) as failed:
        client.chain("SPY", SPY_DAY)

    assert failed.value.code == code
    assert len(calls) == 1


def test_a_malformed_expiration_list_is_coded(monkeypatch, client):
    _serve(monkeypatch, _Response(payload={"expirations": {"date": 7}}))

    with pytest.raises(OptionsChainError) as failed:
        client.expirations("SPY")

    assert failed.value.code == "malformed"


def test_no_token_and_bad_symbols_never_call_out(monkeypatch, client):
    calls = _serve(monkeypatch, _Response(payload={"options": None}))

    for symbol in ("", "SPY,QQQ", "spy 1", "$SPX"):
        with pytest.raises(ValueError):
            client.chain(symbol, SPY_DAY)
    monkeypatch.setattr(options.tradier, "TRADIER_API_KEY", "")
    with pytest.raises(OptionsChainError) as missing:
        client.expirations("SPY")

    assert missing.value.code == "not_configured"
    assert calls == []


# --- Tradier option field names stop at the adapter -------------------------

APP = Path(__file__).resolve().parents[1] / "app"
# Names only Tradier uses (Alpaca also says expiration_date, so it is not listed).
TRADIER_OPTION_FIELDS = re.compile(
    r"""["'](root_symbol|contract_size|expiration_type|smv_vol|mid_iv|bid_iv|ask_iv|bidsize|asksize|bid_date|ask_date)["']"""
    r"""|/markets/options/"""
)
TRADIER_ADAPTERS = {"engine/tradier.py", "engine/options_chain.py"}


def test_tradier_option_field_names_appear_only_in_tradier_adapters():
    readers = {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if TRADIER_OPTION_FIELDS.search(path.read_text())
    }

    assert "engine/options_chain.py" in readers  # the scan sees the adapter, so it can see a leak
    assert readers <= TRADIER_ADAPTERS, f"read Tradier option fields outside an adapter: {sorted(readers - TRADIER_ADAPTERS)}"
