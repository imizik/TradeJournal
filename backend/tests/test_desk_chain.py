"""The desk's Chain tab (GET /copilot/chain): one expiry of the selected ticker's option chain around the price, with his
held and planned contracts marked. The strike window, the expiry order, the brief cache, honest stale and missing quotes,
the marks, and that nothing here sends anything or reads Robinhood. No network."""

from datetime import UTC, date, datetime
import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlmodel import Session

from app.engine import desk_chain, desk_ticket
from app.engine.options_feed import OptionsFeed
from app.engine.options_models import OptionChain, OptionContract
from app.models import Trade
from app.routers import copilot_ticket as ticket_routes
from tests.test_desk_ticket import NOW, REPO, ROTH, chain_read, engine, lab, plan, ticket  # noqa: F401  (shared fixtures)
from tests.test_desk_ticket import contract as ticket_contract

EXPIRY = date(2026, 11, 13)
WEBULL = UUID(int=3)


def contract(strike, kind="call", bid=1.0, ask=1.1, quoted=NOW - 30, expiry=EXPIRY, root="NBIS", delta=0.5, iv=0.6):
    at = datetime.fromtimestamp(quoted, UTC) if quoted else None
    return OptionContract(symbol=f"{root}{expiry:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying="NBIS", root=root,
                          expiration=expiry, option_type=kind, strike=strike, multiplier=100, bid=bid, ask=ask, last=None,
                          bid_size=None, ask_size=None, volume=12, open_interest=340, bid_time=at, ask_time=at, trade_time=None,
                          iv=iv, iv_smoothed=None, delta=delta, gamma=None, theta=None, vega=None, greeks_updated_at=None)


def chain_of(strikes, expiry=EXPIRY, **kw):
    contracts = tuple(contract(s, kind, expiry=expiry, **kw) for s in strikes for kind in ("call", "put"))
    return OptionChain("NBIS", expiry, "tradier", datetime.fromtimestamp(NOW - 5, UTC), contracts)


def reader(chain=None, live=(date(2026, 10, 21), EXPIRY), spot=95.0, fetched=NOW - 5, issue=None, asked=None):
    def read(symbol, expiration, ttl):
        if asked is not None:
            asked.append({"symbol": symbol, "expiration": expiration, "ttl": ttl})
        return {"live": list(live) if live is not None else None, "chain": chain, "fetched": fetched, "issue": issue,
                "spot": spot, "spot_at": NOW - 3, "spot_issue": None, "simulated": False}
    return read


@pytest.fixture
def session_open(monkeypatch):
    monkeypatch.setattr(desk_chain, "_session", lambda now: ("regular", (int(NOW) - 3600, int(NOW) + 3600)))


@pytest.fixture
def session_closed(monkeypatch):
    monkeypatch.setattr(desk_chain, "_session", lambda now: ("closed", None))


def view(engine, read, expiration=None, **kw):  # noqa: F811
    kw.setdefault("now", NOW)
    with Session(engine) as db:
        return desk_chain.view(db, "nbis", expiration, read=read, **kw)


def strikes_of(found):
    return [r["strike"] for r in found["rows"]]


# --- the strike window -----------------------------------------------------------------------------------------------

def test_ten_strikes_either_side_of_the_price_with_the_money_marked(engine, session_open):  # noqa: F811
    found = view(engine, reader(chain_of([float(s) for s in range(70, 121)]), spot=95.4))
    assert found["state"] == "ok" and found["symbol"] == "NBIS"
    assert strikes_of(found) == [float(s) for s in range(85, 106)]  # 95 is nearest 95.4
    assert found["atm_strike"] == 95.0 and [r["strike"] for r in found["rows"] if r["atm"]] == [95.0]
    assert found["centred_on"] == "price" and found["spot"] == 95.4


def test_the_window_stops_at_the_ends_of_the_chain(engine, session_open):  # noqa: F811
    found = view(engine, reader(chain_of([90.0, 92.5, 95.0, 97.5, 100.0]), spot=99.0))
    assert strikes_of(found) == [90.0, 92.5, 95.0, 97.5, 100.0] and found["atm_strike"] == 100.0


def test_without_a_price_the_window_centres_where_calls_and_puts_cost_the_same(engine, session_open):  # noqa: F811
    contracts = []
    for s in range(80, 111):
        contracts.append(contract(float(s), "call", bid=max(100 - s, 0) + 1.0, ask=max(100 - s, 0) + 1.2))
        contracts.append(contract(float(s), "put", bid=max(s - 100, 0) + 1.0, ask=max(s - 100, 0) + 1.2))
    chain = OptionChain("NBIS", EXPIRY, "tradier", datetime.fromtimestamp(NOW - 5, UTC), tuple(contracts))
    found = view(engine, reader(chain, spot=None))
    assert found["atm_strike"] == 100.0 and found["centred_on"] == "parity" and found["spot"] is None


def test_only_the_primary_root_shows(engine, session_open):  # noqa: F811
    spx = [contract(s, k, root=r) for s in (5800.0, 5805.0, 5810.0) for k in ("call", "put") for r in ("SPX", "SPXW")]
    chain = OptionChain("SPX", EXPIRY, "tradier", datetime.fromtimestamp(NOW - 5, UTC), tuple(spx))
    with Session(engine) as db:
        found = desk_chain.view(db, "SPX", None, read=reader(chain, spot=5806.0), now=NOW)
    assert found["root"] == "SPXW" and len(found["rows"]) == 3
    assert all(r["call"]["symbol"].startswith("SPXW") for r in found["rows"])


# --- the expiry list -------------------------------------------------------------------------------------------------

def test_expiries_are_nearest_first_with_0dte_weekly_and_monthly(engine, session_open):  # noqa: F811
    live = [date(2026, 11, 20), date(2026, 10, 21), date(2026, 10, 23), EXPIRY, date(2026, 12, 18)]
    asked = []
    found = view(engine, reader(chain_of([95.0], expiry=date(2026, 10, 21)), live=live, asked=asked))
    assert [(e["date"], e["kind"], e["days"]) for e in found["expiries"]] == [
        ("2026-10-21", "0dte", 0), ("2026-10-23", "weekly", 2), ("2026-11-13", "weekly", 23),
        ("2026-11-20", "monthly", 30), ("2026-12-18", "monthly", 58)]
    assert found["expiration"] == "2026-10-21"
    assert asked == [{"symbol": "NBIS", "expiration": None, "ttl": desk_chain.LIVE_TTL}]


def test_expiries_that_live_through_the_next_report_are_marked(engine, session_open, monkeypatch):  # noqa: F811
    from app.engine import desk_events
    live = [date(2026, 10, 23), date(2026, 10, 28), date(2026, 10, 30), EXPIRY]
    monkeypatch.setattr(desk_events, "_earnings", lambda symbols, today: {"NBIS": {"next": {"date": "2026-10-28", "status": "confirmed"}}})
    found = view(engine, reader(chain_of([95.0], expiry=date(2026, 10, 23)), live=live))
    assert found["earnings"] == {"date": "2026-10-28", "status": "confirmed"}
    # The report's day counts: its time of day is not published, so that expiry may close after it.
    assert [(e["date"], e["earnings"]) for e in found["expiries"]] == [
        ("2026-10-23", False), ("2026-10-28", True), ("2026-10-30", True), ("2026-11-13", True)]
    monkeypatch.setattr(desk_events, "_earnings", lambda symbols, today: {"NBIS": {"state": "none", "next": None}})
    unknown = view(engine, reader(chain_of([95.0], expiry=date(2026, 10, 23)), live=live))
    assert unknown["earnings"] is None and not any(e["earnings"] for e in unknown["expiries"])


def test_the_asked_expiry_is_passed_through(engine, session_open):  # noqa: F811
    asked = []
    found = view(engine, reader(chain_of([95.0]), asked=asked), EXPIRY)
    assert asked[0]["expiration"] == EXPIRY and found["expiration"] == "2026-11-13"


def test_a_symbol_with_no_options_says_so(engine, session_open):  # noqa: F811
    found = view(engine, reader(None, live=[]))
    assert found["state"] == "none" and found["rows"] == [] and "no listed options" in found["message"]


# --- the cache -------------------------------------------------------------------------------------------------------

class _Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


class _Client:
    def __init__(self):
        self.chains = 0
        self.lists = 0

    def expirations(self, symbol):
        self.lists += 1
        return [EXPIRY]

    def chain(self, symbol, expiration):
        self.chains += 1
        return chain_of([95.0], expiry=expiration)


class _Calendar:
    def hours(self, day):
        return None


def test_one_read_per_expiry_kept_for_the_ttl_then_read_again():
    clock, client = _Clock(NOW), _Client()
    feed = OptionsFeed(client=client, calendar=_Calendar(), clock=clock, spawn=lambda work: None)
    pick = lambda live: [EXPIRY]  # noqa: E731
    reads, issue = feed.chains("NBIS", pick, ttl=desk_chain.LIVE_TTL)
    assert issue is None and len(reads) == 1 and client.chains == 1 and client.lists == 1
    clock.at += desk_chain.LIVE_TTL - 1
    feed.chains("NBIS", pick, ttl=desk_chain.LIVE_TTL)
    assert client.chains == 1  # still fresh: no provider call
    clock.at += 2
    feed.chains("NBIS", pick, ttl=desk_chain.LIVE_TTL)
    assert client.chains == 2 and client.lists == 1  # the chain again; the expiry list is kept for half an hour
    # The default (other readers) keeps a minute.
    clock.at += 30
    feed.chains("NBIS", pick)
    assert client.chains == 2


def test_outside_the_session_the_chain_is_kept_longer_and_not_polled(engine, session_closed):  # noqa: F811
    asked = []
    found = view(engine, reader(chain_of([95.0]), asked=asked, fetched=NOW - 3000))
    assert asked[0]["ttl"] == desk_chain.CLOSED_TTL
    assert found["session"] == "closed" and found["poll_seconds"] is None
    assert found["stale"] is False and found["rows"][0]["call"]["state"] == "ok"  # judged closed, not stale
    assert found["fetched_at"] == int(NOW - 3000)


def test_in_the_session_the_desk_polls_every_fifteen_seconds(engine, session_open):  # noqa: F811
    assert view(engine, reader(chain_of([95.0])))["poll_seconds"] == desk_chain.POLL_SECONDS == 15


# --- stale and missing ----------------------------------------------------------------------------------------------

def test_a_missing_bid_or_ask_has_no_mark_and_never_a_zero(engine, session_open):  # noqa: F811
    contracts = (contract(95.0, "call", bid=None, ask=1.2), contract(95.0, "put", bid=0.0, ask=0.0))
    chain = OptionChain("NBIS", EXPIRY, "tradier", datetime.fromtimestamp(NOW - 5, UTC), contracts)
    row = view(engine, reader(chain))["rows"][0]
    for side in ("call", "put"):
        assert row[side]["state"] == "missing" and row[side]["mark"] is None and row[side]["spread"] is None
    assert row["call"]["bid"] is None  # not 0


def test_an_old_quote_in_the_session_is_stale_with_its_numbers_and_time(engine, session_open):  # noqa: F811
    old = NOW - desk_chain.QUOTE_STALE_S - 60
    row = view(engine, reader(chain_of([95.0], quoted=old)))["rows"][0]
    assert row["call"]["state"] == "stale" and row["call"]["mark"] == 1.05 and row["call"]["quoted_at"] == int(old)
    no_time = view(engine, reader(chain_of([95.0], quoted=None)))["rows"][0]
    assert no_time["call"]["state"] == "stale" and no_time["call"]["quoted_at"] is None


def test_a_chain_not_read_again_reads_stale_with_its_read_time(engine, session_open):  # noqa: F811
    found = view(engine, reader(chain_of([95.0]), fetched=NOW - 60, issue="Option reads are pacing."))
    assert found["stale"] is True and found["age_s"] == 60 and found["message"] == "Option reads are pacing."
    found = view(engine, reader(chain_of([95.0]), fetched=NOW - 60))
    assert found["stale"] is True and "last read" in found["message"]
    assert view(engine, reader(chain_of([95.0]), fetched=NOW - 10))["stale"] is False


def test_an_unreadable_chain_or_list_is_unavailable(engine, session_open):  # noqa: F811
    found = view(engine, reader(None, issue="Tradier refused option data."))
    assert found["state"] == "unavailable" and found["message"] == "Tradier refused option data." and found["expiries"]
    found = view(engine, reader(None, live=None, issue="Option expirations are not loaded yet."))
    assert found["state"] == "unavailable" and found["expiries"] == []


def test_replay_reads_no_chain(engine):  # noqa: F811
    with Session(engine) as db:
        found = desk_chain.view(db, "NBIS", mode="replay", now=NOW, read=lambda *a: pytest.fail("read in replay"))
    assert found["state"] == "unavailable" and found["rows"] == []


def test_the_fixture_is_the_simulated_nbis_chain_labelled(engine):  # noqa: F811
    with Session(engine) as db:
        found = desk_chain.view(db, "NBIS", mode="fixture", now=NOW)
        other = desk_chain.view(db, "CRWV", mode="fixture", now=NOW)
    assert found["simulated"] is True and found["state"] == "ok" and found["spot"] == 94.35
    assert found["expiries"][0] == {"date": "2026-10-23", "days": 0, "kind": "0dte", "held": False, "earnings": False}
    assert found["atm_strike"] == 95.0 and all(r["call"]["state"] != "stale" for r in found["rows"])
    assert other["state"] == "none" or other["state"] == "unavailable"


# --- spreads and the marks -------------------------------------------------------------------------------------------

def test_a_wide_spread_is_flagged_in_plain_words(engine, session_open):  # noqa: F811
    contracts = (contract(95.0, "call", bid=1.00, ask=1.40), contract(95.0, "put", bid=2.00, ask=2.10))
    chain = OptionChain("NBIS", EXPIRY, "tradier", datetime.fromtimestamp(NOW - 5, UTC), contracts)
    row = view(engine, reader(chain))["rows"][0]
    assert row["call"]["wide"] is True and row["call"]["spread_pct"] == 33.3
    assert row["call"]["spread_note"] == "Wide spread: $40 a contract between bid and ask (33.3% of the mark)"
    assert row["put"]["wide"] is False and row["put"]["spread_note"] is None
    assert row["call"]["delta"] == 0.5 and row["call"]["iv"] == 60.0 and row["call"]["open_interest"] == 340


def hold(engine, strike, kind="call", contracts=2, account=ROTH, status="open", expiry=EXPIRY):  # noqa: F811
    with Session(engine) as db:
        db.add(Trade(account_id=account, ticker="NBIS", instrument_type="option", contracts=contracts, option_type=kind,
                     strike=strike, expiration=expiry, avg_entry_premium=1.0, total_premium_paid=100.0 * contracts,
                     opened_at=datetime(2026, 10, 20, 10, 0), status=status))
        db.commit()


def test_held_contracts_are_marked_with_their_count_and_their_expiry(engine, session_open):  # noqa: F811
    hold(engine, 100.0, "call", 2)
    hold(engine, 100.0, "call", 1)
    hold(engine, 90.0, "put", 3, status="closed")  # closed: not held
    hold(engine, 92.0, "put", 4, account=WEBULL)  # Webull stays out
    hold(engine, 95.0, "call", 1, expiry=date(2026, 11, 20))  # another expiry: marks that expiry only
    found = view(engine, reader(chain_of([float(s) for s in range(85, 106)]), live=(EXPIRY, date(2026, 11, 20))))
    held = {(r["strike"], side): r[side]["held"] for r in found["rows"] for side in ("call", "put") if r[side]["held"]}
    assert held == {(100.0, "call"): 3}
    assert [e["held"] for e in found["expiries"]] == [True, True]


def test_a_saved_plans_contract_and_levels_are_marked(engine, session_open):  # noqa: F811
    plan(engine, strike=100.0, expiration=EXPIRY)  # entry 95.9, exit 90, capture names the 100 call
    found = view(engine, reader(chain_of([float(s) for s in range(85, 106)])))
    planned = [(r["strike"], side) for r in found["rows"] for side in ("call", "put") if r[side]["planned"]]
    assert planned == [(100.0, "call")]
    marks = {r["strike"]: r["levels"] for r in found["rows"] if r["levels"]}
    assert marks == {96.0: ["entry"], 90.0: ["exit"]}
    assert {(lv["role"], lv["price"], lv["strike"]) for lv in found["levels"]} == {("entry", 95.9, 96.0), ("exit", 90.0, 90.0)}


def test_a_level_between_wide_strikes_or_outside_the_window_marks_none():
    assert desk_chain.level_strike([90.0, 95.0, 100.0], 92.4) == 90.0
    assert desk_chain.level_strike([90.0, 95.0, 100.0], 92.6) == 95.0
    assert desk_chain.level_strike([90.0, 95.0, 100.0], 120.0) is None
    assert desk_chain.level_strike([], 95.0) is None


def test_put_on_ticket_the_chains_pick_replaces_the_plans_contract(engine):  # noqa: F811
    plan(engine, contract="NBIS 11/13 100C")
    named = ticket(engine, chain_read=chain_read(ticket_contract(100), ticket_contract(105, bid=1.5, ask=1.7)))
    assert named["contract"]["strike"] == 100 and named["contract"]["source"] == "plan"
    picked = ticket(engine, pick=(date(2026, 11, 13), 105.0), chain_read=chain_read(ticket_contract(100), ticket_contract(105, bid=1.5, ask=1.7)))
    assert picked["contract"]["strike"] == 105 and picked["contract"]["source"] == "picked" and picked["limit"] == 1.6
    assert picked["plan_contract_words"] == "NBIS 11/13 100C"  # the plan's own words still show


def test_the_ticket_list_says_which_plans_are_a_long_call_or_put(engine):  # noqa: F811
    plan(engine, contract="NBIS 11/13 100C")
    plan(engine, "22222222-2222-4222-8222-222222222222", "CRWV", side="buy_stock", instrument="stock", contract=None, client_id="b")
    with Session(engine) as db:
        rows = {r["symbol"]: r["option_type"] for r in desk_ticket.armed(db)}
    assert rows == {"NBIS": "call", "CRWV": None}


# --- the route, and nothing sends ------------------------------------------------------------------------------------

def test_the_route_reads_the_labs_evidence_and_refuses_a_bad_ticker(engine, lab, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    body = lab.get("/copilot/chain", params={"symbol": "NBIS", "expiration": "2026-11-13"}).json()
    assert body["simulated"] is True and body["expiration"] == "2026-11-13" and len(body["rows"]) == 15
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="live"))
    assert lab.get("/copilot/chain", params={"symbol": "NOT A TICKER"}).status_code == 400
    monkeypatch.setattr(ticket_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/chain", params={"symbol": "NBIS"}).status_code == 503


def test_the_chain_never_sends_and_never_reads_robinhood():
    sources = [inspect.getsource(desk_chain), (REPO / "frontend/components/copilot/DeskChain.tsx").read_text()]
    forbidden = ("robinhood_read", "robinhood_trading", "place_option_order", "review_option_order", "order_tool",
                 "requests.post", "method: \"POST\"", "method: 'POST'", "ntfy", "telegram")
    for text in sources:
        assert not [word for word in forbidden if word.lower() in text.lower()]
