"""Unusual options on his held and watched names (GET /copilot/unusual): the volume-vs-open-interest rule and its minimum
size, the ticker rule against the recorded sessions (and saying when there are none), held then Watching scope with
hidden names left out, the read cache and pacing, stale and unavailable readings, at the close, and that nothing here
sends anything or reads Robinhood. No network."""

from datetime import UTC, date, datetime, timedelta
import inspect
import json

import pytest
from sqlmodel import Session

from app.engine import desk_chain, desk_unusual as du
from app.engine.options_models import OptionChain, OptionContract
from app.models import ChartSettingsRecord, DayJournalEntry, OptionChainSnapshot, OptionSnapshotDay, Trade
from tests.test_desk_ticket import NOW, REPO, ROTH, T0, WED, engine, lab  # noqa: F401  (shared fixtures)
from tests.test_desk_chain import WEBULL, chain_of, reader, session_open  # noqa: F401

E1, E2, E3, E4 = date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 30), date(2026, 11, 6)


def contract(strike, kind="call", volume=10, oi=100, expiry=E1, root="NBIS", last=1.25, underlying="NBIS"):
    return OptionContract(symbol=f"{root}{expiry:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying=underlying,
                          root=root, expiration=expiry, option_type=kind, strike=strike, multiplier=100, bid=1.2, ask=1.3,
                          last=last, bid_size=None, ask_size=None, volume=volume, open_interest=oi, bid_time=None,
                          ask_time=None, trade_time=None, iv=None, iv_smoothed=None, delta=None, gamma=None, theta=None,
                          vega=None, greeks_updated_at=None)


def chain(expiry, *contracts, underlying="NBIS"):
    return OptionChain(underlying, expiry, "tradier", datetime.fromtimestamp(NOW - 5, UTC), tuple(contracts))


def three(*heavy, underlying="NBIS"):
    """Three nearest expiries of quiet contracts, with ``heavy`` added to the first."""
    quiet = [contract(100.0, kind, expiry=e, underlying=underlying, root=underlying) for e in (E1, E2, E3) for kind in ("call", "put")]
    return [chain(e, *[c for c in quiet if c.expiration == e], *[h for h in heavy if h.expiration == e], underlying=underlying)
            for e in (E1, E2, E3)]


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(du, "PATH", tmp_path / "desk_unusual.json")
    du.reset()
    yield
    du.reset()


@pytest.fixture
def market_open(monkeypatch):
    monkeypatch.setattr(du, "_session", lambda now: ("regular", WED))


@pytest.fixture
def market_closed(monkeypatch):
    monkeypatch.setattr(du, "_session", lambda now: ("closed", WED + timedelta(days=1)))


def hold(engine, ticker="NBIS", account=ROTH, status="open"):  # noqa: F811
    with Session(engine) as db:
        db.add(Trade(account_id=account, ticker=ticker, instrument_type="option", contracts=1, option_type="call", strike=100.0,
                     expiration=E3, avg_entry_premium=1.0, total_premium_paid=100.0, opened_at=datetime(2026, 10, 20, 10, 0),
                     status=status))
        db.commit()


def watch(engine, *symbols):  # noqa: F811
    with Session(engine) as db:
        db.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": list(symbols)}), revision=1,
                                   updated_at=datetime(2026, 10, 20)))
        db.commit()


def hide(engine, symbol):  # noqa: F811
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id=f"f-{symbol}", day=WED, kind="follow", symbol=symbol, text="Not following", created_at=T0))
        db.commit()


def record(engine, symbol, days, call=1000, put=800, expiries=4):  # noqa: F811
    """``days`` recorded sessions before WED, each with ``expiries`` expirations (the nearest three count)."""
    with Session(engine) as db:
        for back in range(1, days + 1):
            day = WED - timedelta(days=back)
            db.add(OptionSnapshotDay(session_date=day, underlying=symbol, status="recorded"))
            for k in range(expiries):
                rows = [[symbol, "C", 100.0, 50, call // 3 if k < 3 else 99999], [symbol, "P", 100.0, 50, put // 3 if k < 3 else 99999],
                        ["OTHER", "C", 100.0, 50, 99999]]
                db.add(OptionChainSnapshot(session_date=day, underlying=symbol, expiration=day + timedelta(days=k), provider="tradier",
                                           captured_at=datetime(2026, 10, 1), contracts=3,
                                           data_json=json.dumps({"columns": ["root", "type", "strike", "open_interest", "volume"], "rows": rows})))
        db.commit()


def run(engine, symbols, reads, now=NOW, in_session=lambda now: True):  # noqa: F811
    asked, slept = [], []

    def read(symbol):
        asked.append(symbol)
        got = reads(symbol) if callable(reads) else reads
        return got if isinstance(got, dict) else {"chains": got, "fetched": now - 5, "issue": None}
    du.refresh(symbols, read=read, open_db=lambda: Session(engine), clock=lambda: now, sleep=slept.append, in_session=in_session)
    return asked, slept


def view(engine, now=NOW, **kw):  # noqa: F811
    with Session(engine) as db:
        return du.view(db, now, **kw)


# --- the rules -------------------------------------------------------------------------------------------------------

def test_a_contract_is_unusual_at_three_times_its_open_interest_and_the_minimum_size():
    rows = du.unusual_contracts([chain(E1,
        contract(100.0, volume=900, oi=300),  # 3.0x and 900: in
        contract(101.0, volume=870, oi=300),  # 2.9x: out
        contract(102.0, volume=499, oi=10),  # 49.9x but under the minimum size: out
        contract(103.0, "put", volume=600, oi=0),  # no open interest at all: in, with no ratio
        contract(104.0, volume=None, oi=10),  # volume not reported: skipped, never zero
        contract(105.0, volume=5000, oi=None),  # open interest not reported: skipped
        contract(106.0, volume=5000, oi=10, root="NBIS1"),  # another root: out
    )], "NBIS")
    assert [(r["strike"], r["side"], r["volume"], r["open_interest"], r["ratio"]) for r in rows] == [
        (100.0, "call", 900, 300, 3.0), (103.0, "put", 600, 0, None)]
    assert rows[0]["contract"] == "NBIS261021C00100000" and rows[0]["expiration"] == "2026-10-21" and rows[0]["last"] == 1.25
    assert "lean" not in rows[0] and "side_lean" not in rows[0]  # the chain never says bid or ask


def test_side_totals_are_none_when_any_volume_is_missing():
    assert du.side_totals([chain(E1, contract(100.0, volume=5), contract(100.0, "put", volume=7))], "NBIS") == {"call": 5, "put": 7}
    assert du.side_totals([chain(E1, contract(100.0, volume=5), contract(101.0, volume=None))], "NBIS")["call"] is None


def test_a_ticker_side_is_unusual_at_twice_its_usual_day_and_the_minimum():
    usual = {"call": 1000, "put": 400, "sessions": 20}
    flags = du.ticker_flags({"call": 2000, "put": 900}, usual)  # puts 2.25x but under 1,000 contracts
    assert flags == [{"side": "call", "today": 2000, "usual": 1000, "multiple": 2.0, "sessions": 20}]
    assert du.ticker_flags({"call": 1999, "put": None}, usual) == []
    assert du.ticker_flags({"call": 5000, "put": 5000}, None) == []


def test_history_averages_the_nearest_three_expiries_of_recorded_sessions(engine):  # noqa: F811
    record(engine, "NBIS", 6, call=900, put=600)
    with Session(engine) as db:
        found = du.history(db, "NBIS", WED, "NBIS")
    assert found == {"sessions": 6, "call": 900, "put": 600}  # the fourth expiry and the other root are left out


def test_fewer_than_five_recorded_sessions_is_no_history(engine):  # noqa: F811
    record(engine, "NBIS", 4)
    with Session(engine) as db:
        assert du.history(db, "NBIS", WED, "NBIS") is None


# --- scope -----------------------------------------------------------------------------------------------------------

def test_scope_is_held_then_watching_without_hidden_or_webull_or_closed(engine):  # noqa: F811
    hold(engine, "NBIS")
    hold(engine, "SPXW")
    hold(engine, "TSLA", status="closed")
    hold(engine, "GME", account=WEBULL)
    watch(engine, "AMD", "NBIS", "MU", "CRWV")
    hide(engine, "MU")
    with Session(engine) as db:
        assert du.scope(db) == [{"symbol": "NBIS", "held": True}, {"symbol": "SPX", "held": True},
                                {"symbol": "AMD", "held": False}, {"symbol": "CRWV", "held": False}]


def test_scope_is_capped(engine):  # noqa: F811
    watch(engine, *[f"A{i}" for i in range(20)])
    with Session(engine) as db:
        assert len(du.scope(db)) == du.MAX_SYMBOLS


def test_a_hidden_name_never_shows_even_from_an_earlier_reading(engine, market_open):  # noqa: F811
    watch(engine, "NBIS", "AMD")
    run(engine, ["NBIS", "AMD"], lambda s: three(contract(110.0, volume=4000, oi=100, root=s, underlying=s), underlying=s))
    hide(engine, "AMD")
    found = view(engine, spawn=lambda work: None)
    assert {r["symbol"] for r in found["rows"]} == {"NBIS"} and "AMD" not in found["unread"]


def test_when_hidden_names_cannot_be_read_nothing_is_shown(engine, market_open, monkeypatch):  # noqa: F811
    from app.engine import day_journal
    watch(engine, "NBIS")
    run(engine, ["NBIS"], three(contract(110.0, volume=4000, oi=100)))
    monkeypatch.setattr(day_journal, "not_following", lambda db: (_ for _ in ()).throw(RuntimeError("db")))
    found = view(engine, spawn=lambda work: None)
    assert found["state"] == "unavailable" and found["rows"] == [] and "could not be read" in found["message"]


# --- reading, caching, pacing ----------------------------------------------------------------------------------------

def test_in_the_session_a_view_starts_one_pass_for_names_not_read_lately(engine, market_open):  # noqa: F811
    hold(engine, "NBIS")
    watch(engine, "AMD")
    started = []
    found = view(engine, spawn=started.append)
    assert len(started) == 1 and found["label"] == "live" and found["unread"] == ["NBIS", "AMD"] and found["rows"] == []
    assert "fills in" in found["message"]
    assert view(engine, spawn=started.append) and len(started) == 1  # a pass is running: no second one
    du.reset()
    run(engine, ["NBIS", "AMD"], lambda s: three(underlying=s))
    view(engine, now=NOW + du.REFRESH_S - 10, spawn=started.append)
    assert len(started) == 1  # read within REFRESH_S: no pass
    view(engine, now=NOW + du.REFRESH_S + 10, spawn=started.append)
    assert len(started) == 2


def test_a_pass_reads_one_name_at_a_time_gap_seconds_apart_and_stops_at_the_close(engine):  # noqa: F811
    asked, slept = run(engine, ["NBIS", "AMD", "MU"], lambda s: three(underlying=s))
    assert asked == ["NBIS", "AMD", "MU"] and slept == [du.GAP_S, du.GAP_S]
    du.reset()
    clock = iter([True, False])
    asked, _ = run(engine, ["NBIS", "AMD"], lambda s: three(underlying=s), in_session=lambda now: next(clock))
    assert asked == ["NBIS"]


def test_the_live_read_asks_the_options_feed_for_three_expiries_with_the_refresh_ttl(monkeypatch):
    from app.engine import options_feed as feed
    seen = {}

    def chains(symbol, pick, ttl):
        seen.update(symbol=symbol, picked=pick([E1, E2, E3, E4]), ttl=ttl)
        return [], "pacing"
    monkeypatch.setattr(feed.options_feed, "chains", chains)
    assert du._live_read("NBIS") == {"chains": [], "fetched": None, "issue": "pacing"}
    assert seen == {"symbol": "NBIS", "picked": [E1, E2, E3], "ttl": du.REFRESH_S}


def test_live_rows_are_most_traded_first_with_contract_and_ticker_flags(engine, market_open):  # noqa: F811
    hold(engine, "NBIS")
    watch(engine, "AMD")
    record(engine, "NBIS", 6, call=900, put=600)
    run(engine, ["NBIS", "AMD"], lambda s: three(
        contract(110.0, volume=2400, oi=300, root=s, underlying=s),
        contract(90.0, "put", volume=700, oi=100, expiry=E2, root=s, underlying=s), underlying=s)
        if s == "NBIS" else three(contract(50.0, volume=3000, oi=900, root=s, underlying=s), underlying=s))
    found = view(engine, spawn=lambda work: None)
    assert found["state"] == "ok" and found["session"] == "open" and found["label"] == "live"
    assert [(r["symbol"], r["strike"], r["volume"]) for r in found["rows"]] == [
        ("AMD", 50.0, 3000), ("NBIS", 110.0, 2400), ("NBIS", 90.0, 700)]
    assert {r["symbol"]: r["held"] for r in found["rows"]} == {"AMD": False, "NBIS": True}
    # NBIS calls today: 3 quiet x 10 + 2400 = 2430 against a usual 900: 2.7x. Puts 730: under the minimum.
    assert [(t["symbol"], t["side"], t["today"], t["usual"], t["multiple"]) for t in found["tickers"]] == [("NBIS", "call", 2430, 900, 2.7)]
    assert found["no_history"] == ["AMD"] and found["unread"] == [] and found["stale"] == []
    assert found["rule"].startswith("Unusual: a contract that has traded at least 3×") and "bid or the ask" in found["rule"]


def test_a_partial_read_keeps_the_contract_rule_but_not_the_ticker_rule(engine, market_open):  # noqa: F811
    watch(engine, "NBIS")
    record(engine, "NBIS", 6, call=100, put=100)
    run(engine, ["NBIS"], {"chains": three(contract(110.0, volume=2400, oi=300))[:2], "fetched": NOW - 5,
                           "issue": "Option reads are pacing"})
    found = view(engine, spawn=lambda work: None)
    assert [r["strike"] for r in found["rows"]] == [110.0] and found["tickers"] == []


# --- stale and unavailable -------------------------------------------------------------------------------------------

def test_a_failed_read_is_a_grey_line_never_zeros(engine, market_open):  # noqa: F811
    watch(engine, "NBIS", "AMD")
    run(engine, ["NBIS", "AMD"], lambda s: three(underlying=s) if s == "NBIS" else {"chains": [], "fetched": None,
                                                                                   "issue": "Tradier is unreachable"})
    found = view(engine, spawn=lambda work: None)
    assert found["unread"] == ["AMD"] and found["rows"] == [] and found["tickers"] == []


def test_a_failed_reread_keeps_the_last_reading_with_its_time_then_it_goes_stale(engine, market_open):  # noqa: F811
    watch(engine, "NBIS")
    run(engine, ["NBIS"], three(contract(110.0, volume=2400, oi=300)))
    run(engine, ["NBIS"], {"chains": [], "fetched": None, "issue": "rate limited"}, now=NOW + 400)
    found = view(engine, now=NOW + 400, spawn=lambda work: None)
    assert [r["read_at"] for r in found["rows"]] == [int(NOW - 5)] and found["stale"] == []
    later = view(engine, now=NOW + du.STALE_S + 60, spawn=lambda work: None)
    assert later["stale"] == ["NBIS"] and later["rows"][0]["stale"] is True


def test_a_read_that_raises_is_its_own_grey_line(engine, market_open):  # noqa: F811
    watch(engine, "NBIS", "AMD")

    def reads(symbol):
        if symbol == "NBIS":
            raise RuntimeError("boom")
        return three(underlying=symbol)
    asked, _ = run(engine, ["NBIS", "AMD"], reads)
    assert asked == ["NBIS", "AMD"]
    assert view(engine, spawn=lambda work: None)["unread"] == ["NBIS"]


# --- at the close ----------------------------------------------------------------------------------------------------

def test_outside_the_session_the_last_sessions_list_shows_at_the_close_and_nothing_is_read(engine, market_closed):  # noqa: F811
    watch(engine, "NBIS")
    run(engine, ["NBIS"], three(contract(110.0, volume=2400, oi=300)))
    du.reset()  # a restart after the close: the list comes back from disk
    started = []
    found = view(engine, now=NOW + 86400, spawn=started.append)
    assert started == [] and found["session"] == "closed" and found["label"] == "at the close" and found["day"] == "2026-10-21"
    assert [r["strike"] for r in found["rows"]] == [110.0] and found["stale"] == []


def test_outside_the_session_with_no_reading_says_so(engine, market_closed):  # noqa: F811
    watch(engine, "NBIS")
    found = view(engine, spawn=lambda work: pytest.fail("no read outside the session"))
    assert found["rows"] == [] and found["label"] is None and "No reading" in found["message"]


def test_no_names_and_replay(engine, market_open):  # noqa: F811
    watch(engine)
    assert view(engine)["state"] == "none"
    assert view(engine, mode="replay")["state"] == "unavailable"


# --- the route, the fixture, the Chain tab ---------------------------------------------------------------------------

def test_the_route_is_owner_only_and_the_fixture_is_simulated(engine, lab, monkeypatch):  # noqa: F811
    from types import SimpleNamespace
    from app.access_manifest import DOMAIN_ROUTES
    from app.routers import copilot_ticket as routes
    assert "GET /copilot/unusual" in DOMAIN_ROUTES
    monkeypatch.setattr(routes.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    body = lab.get("/copilot/unusual").json()
    assert body["simulated"] is True and body["label"] == "at the close"
    assert [(r["symbol"], r["side"], r["strike"]) for r in body["rows"]] == [("NBIS", "call", 105.0), ("NBIS", "put", 85.0), ("NBIS", "call", 110.0)]
    assert [t["side"] for t in body["tickers"]] == ["call"]
    monkeypatch.setattr(routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/unusual").status_code == 503


def test_the_chain_widens_its_window_to_a_picked_strike(engine, session_open):  # noqa: F811
    with Session(engine) as db:
        found = desk_chain.view(db, "NBIS", None, read=reader(chain_of([float(s) for s in range(60, 131)]), spot=95.0),
                                now=NOW, strike=125.0)
    strikes = [r["strike"] for r in found["rows"]]
    assert strikes[0] == 85.0 and strikes[-1] == 125.0 and found["atm_strike"] == 95.0


def test_nothing_here_sends_pings_or_reads_robinhood():
    sources = [inspect.getsource(du), (REPO / "frontend/components/copilot/DeskUnusual.tsx").read_text()]
    forbidden = ("robinhood_read", "robinhood_trading", "place_option_order", "review_option_order", "order_tool",
                 "requests.post", "method: \"POST\"", "method: 'POST'", "ntfy", "telegram", "notification_policy")
    for text in sources:
        assert not [word for word in forbidden if word.lower() in text.lower()]
