"""The desk's live book from Robinhood (app/engine/robinhood_book.py) and its join onto the desk's rows
(``GET /copilot/desk/threads``). Runs against tests/robinhood_fake.py; nothing here reaches Robinhood."""

from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from app.engine import robinhood_book as rb
from app.engine import robinhood_read as rh
from app.models import Fill, Trade
from tests.robinhood_fake import GUIDE, SECRETS, FakeRobinhood, instrument, option_position, option_quote, token_file
from tests.test_copilot_desk import desk, read  # noqa: F401  (fixtures)
from tests.test_copilot_plans import NBIS, T0, alert, engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import buy, clock, marks, planned_nbis  # noqa: F401  (fixtures)

SATURDAY = 1794675600.0  # 2026-11-14 12:00 New York, a Saturday: quiet refreshes


@pytest.fixture
def fake(monkeypatch):
    server = FakeRobinhood()
    monkeypatch.setattr(rh, "_transport", server.transport)
    return server


def make_feed(tmp_path, *, enabled=True, accounts=("roth ira", "mcp"), now=None, file=True):
    path = token_file(tmp_path / "robinhood-token.json") if file else tmp_path / "missing.json"
    moment = {"t": now or SATURDAY}
    s = rb.Settings(enabled=enabled, token_file=str(path), accounts=accounts)
    return rb.Feed(settings_fn=lambda: s, now=lambda: moment["t"]), moment


def snap(tmp_path):
    feed, _ = make_feed(tmp_path)
    feed.refresh()
    return feed.snapshot(kick=False)


# --------------------------------------------------------------------------- the snapshot

def test_the_snapshot_joins_positions_with_instruments_and_quotes(tmp_path, fake):
    view, snapshot = snap(tmp_path)
    assert view["state"] == "ok"
    assert view["accounts"] == [  # Roth and MCP by default; Individual only while it holds something
        {"label": "Roth IRA", "masked": "••8267", "total_value": 9860.12, "cash": 1200.5, "buying_power": 1150.0},
        {"label": "MCP", "masked": "••7884", "total_value": 0.0, "cash": 0.0, "buying_power": 0.0}]
    [p] = snapshot["positions"]
    assert (p["symbol"], p["side"], p["strike"], p["expiry"], p["quantity"]) == ("NBIS", "call", 100.0, "2026-10-23", 2.0)
    assert (p["avg_cost"], p["mark"], p["bid"], p["ask"]) == (310.0, 420.0, 4.15, 4.25)  # a contract: 4.20 x 100
    assert (p["usd"], p["pct"], p["day_change_pct"]) == (220.0, 35.5, 20.0)  # (420 - 310) x 2; 4.20 vs 3.50 yesterday
    assert p["greeks"] == {"delta": 0.55, "gamma": 0.03, "theta": -0.12, "vega": 0.04, "iv": 0.65}
    assert (p["account"], p["last4"]) == ("Roth IRA", "8267")
    assert len(fake.calls) <= rb.MAX_CALLS and snapshot["complete"]


def test_nothing_from_robinhood_leaves_but_masked_numbers(tmp_path, fake):
    view, _ = snap(tmp_path)
    text = json.dumps(view)
    assert "333338267" not in text and "444447884" not in text and "111118888" not in text
    assert GUIDE not in text and "opt-nbis" not in text and "chain-" not in text
    assert not any(secret in text for secret in SECRETS)


def test_an_account_not_listed_shows_only_while_it_holds_something(tmp_path, fake):
    fake.options["111118888"] = [option_position("opt-old", "MU", expiry="2026-11-20")]
    fake.instruments["opt-old"] = instrument("opt-old", "MU", strike="870.0000", expiry="2026-11-20")
    view, _ = snap(tmp_path)
    assert [a["label"] for a in view["accounts"]] == ["Individual", "Roth IRA", "MCP"]
    feed, _ = make_feed(tmp_path, accounts=("roth ira",))  # the list is a setting
    fake.options.pop("111118888")
    feed.refresh()
    assert [a["label"] for a in feed.view(kick=False)["accounts"]] == ["Roth IRA"]


def test_missing_or_odd_fields_read_as_unavailable_never_zero(tmp_path, fake):
    fake.quotes["opt-nbis"] = {"quote": {"instrument_id": "opt-nbis", "mark_price": "n/a"}}
    fake.portfolios["333338267"] = {"total_value": None, "cash": "1.0"}
    fake.options["333338267"].append({"option_id": "opt-x", "chain_symbol": "CRWV", "quantity": "1.0000", "type": "long"})
    view, snapshot = snap(tmp_path)
    roth = view["accounts"][0]
    assert (roth["total_value"], roth["cash"], roth["buying_power"]) == (None, 1.0, None)
    nbis, crwv = snapshot["positions"]
    assert (nbis["mark"], nbis["usd"], nbis["pct"], nbis["day_change_pct"], nbis["avg_cost"]) == (None, None, None, None, 310.0)
    assert (crwv["side"], crwv["strike"], crwv["mark"], crwv["usd"], crwv["avg_cost"]) == (None, None, None, None, None)
    assert rb.contract_key(crwv["symbol"], "option", crwv["side"], crwv["strike"], crwv["expiry"]) is None  # never matched


def test_positions_page_through_and_stocks_get_quotes(tmp_path, fake):
    fake.page = 1
    fake.options["333338267"] = [option_position(f"opt-{i}", "NBIS") for i in range(3)]
    for i in range(3):
        fake.instruments[f"opt-{i}"] = instrument(f"opt-{i}", "NBIS", strike=f"{100 + i}.0000")
        fake.quotes[f"opt-{i}"] = option_quote(f"opt-{i}")
    fake.stocks["333338267"] = [{"symbol": "RKLB", "quantity": "8.000000", "average_buy_price": "50.730000", "type": "long"}]
    fake.stock_quotes["RKLB"] = {"quote": {"symbol": "RKLB", "last_trade_price": "55.730000", "previous_close": "50.0"}}
    _view, snapshot = snap(tmp_path)
    assert [p["strike"] for p in snapshot["positions"] if p["instrument"] == "option"] == [100.0, 101.0, 102.0]
    assert [c[1].get("cursor") for c in fake.calls if c[0] == "get_option_positions" and c[1]["account_number"] == "333338267"] == [None, "1", "2"]
    [stock] = [p for p in snapshot["positions"] if p["instrument"] == "stock"]
    assert (stock["symbol"], stock["quantity"], stock["avg_cost"], stock["mark"], stock["usd"], stock["day_change_pct"]) == \
        ("RKLB", 8.0, 50.73, 55.73, 40.0, 11.5)


def test_a_failed_call_leaves_that_part_unknown_and_a_failed_refresh_keeps_the_last_snapshot(tmp_path, fake):
    fake.fail.add("get_equity_positions")
    feed, moment = make_feed(tmp_path)
    feed.refresh()
    view, snapshot = feed.snapshot(kick=False)
    assert view["state"] == "ok" and not snapshot["complete"]  # options read; with stocks unknown "not on Robinhood" cannot be said
    assert [p["symbol"] for p in snapshot["positions"]] == ["NBIS"]
    fake.fail.add("get_accounts")
    moment["t"] += rb.QUIET_TTL
    feed.refresh()
    view, again = feed.snapshot(kick=False)
    assert view["issue"] == "http" and again is snapshot
    moment["t"] += rb.STALE_REFRESHES * rb.QUIET_TTL
    view, gone = feed.snapshot(kick=False)
    assert view["state"] == "stale" and gone is None  # the book falls back to the journal


def test_one_refresh_per_ttl_and_a_forced_one_no_faster_than_the_gap(tmp_path, fake):
    feed, moment = make_feed(tmp_path)
    feed.refresh()
    first = len(fake.calls)
    feed.refresh()
    feed.refresh(force=True)
    assert len(fake.calls) == first
    moment["t"] += rb.FORCE_GAP_SECONDS
    feed.refresh(force=True)
    assert len(fake.calls) == 2 * first


def test_market_hours_refresh_each_minute_and_quiet_hours_each_quarter_hour():
    from datetime import datetime
    from app.engine.chart_math import ET
    at = lambda *a: datetime(*a, tzinfo=ET).timestamp()  # noqa: E731
    assert rb.ttl(at(2026, 11, 11, 10, 0)) == 60 and rb.ttl(at(2026, 11, 11, 20, 0)) == 900 and rb.ttl(at(2026, 11, 14, 11, 0)) == 900


def test_off_signed_out_and_expired_make_no_call(tmp_path, fake):
    for kwargs, state in (({"enabled": False}, "off"), ({"file": False}, "signed_out")):
        feed, _ = make_feed(tmp_path, **kwargs)
        assert feed.refresh(force=True) == {"state": state} and feed.view() == {"state": state}
    open_file = token_file(tmp_path / "open.json", mode=0o644)
    feed = rb.Feed(settings_fn=lambda: rb.Settings(True, str(open_file), ("mcp",)))
    assert feed.view() == {"state": "signed_out"}
    feed, _ = make_feed(tmp_path)
    fake.status = 401
    feed.refresh()
    assert feed.view(kick=False) == {"state": "expired"}
    fake.status = 200
    feed.refresh(force=True)
    assert fake.methods == ["initialize"] and fake.calls == []


def test_the_default_settings_are_off(monkeypatch):
    for key in ("ROBINHOOD_READ_ENABLED", "ROBINHOOD_TOKEN_FILE", "ROBINHOOD_ACCOUNTS"):
        monkeypatch.delenv(key, raising=False)
    s = rb.settings()
    assert (s.enabled, s.token_file, s.accounts) == (False, None, ("roth ira", "mcp"))
    monkeypatch.setenv("ROBINHOOD_READ_ENABLED", "1")
    assert not rb.settings().enabled  # only the exact word turns it on


# --------------------------------------------------------------------------- matching

def test_matching_prefers_the_same_account_and_says_what_robinhood_does_not_show():
    live = [{"symbol": "NBIS", "instrument": "option", "side": "call", "strike": 100.0, "expiry": "2026-10-23", "last4": "7884"},
            {"symbol": "NBIS", "instrument": "option", "side": "call", "strike": 100.0, "expiry": "2026-10-23", "last4": "8267"},
            {"symbol": "MU", "instrument": "option", "side": "put", "strike": 870.0, "expiry": "2026-11-20", "last4": "8267"}]
    key = ("NBIS", "call", 100.0, "2026-10-23")
    journal = [{"trade_id": "a", "key": key, "last4": "8267"}, {"trade_id": "b", "key": ("ORCL", "stock"), "last4": "8267"}]
    matched, missing, extra = rb.match(journal, {"positions": live, "complete": True})
    assert matched["a"]["last4"] == "8267" and missing == {"b"} and [p["last4"] for p in extra] == ["7884", "8267"]
    _m, missing, _e = rb.match(journal, {"positions": live, "complete": False})
    assert missing == set()
    assert rb.contract_key("nbis", "option", "call", "100.0000", "2026-10-23") == key
    assert rb.contract_key("NBIS", "option", "call", 100, "2026-10-23T00:00") == key


# --------------------------------------------------------------------------- into the desk

@pytest.fixture
def live(tmp_path, fake, monkeypatch, clock):  # noqa: F811
    feed, at = make_feed(tmp_path, now=clock["t"])
    monkeypatch.setattr(rb, "feed", feed)
    feed.refresh()
    at["t"] = clock["t"]
    return feed


def test_off_the_desk_is_exactly_the_journal(desk, engine, quotes, monkeypatch, fake):  # noqa: F811
    trade = planned_nbis(engine)
    monkeypatch.setattr(rb, "feed", rb.Feed(settings_fn=lambda: rb.Settings(False, None, ())))
    body = read(desk)
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert body["robinhood"] == {"state": "off"} and "live" not in row["book"] and "account" not in row["book"]
    assert row["value"]["text"] == "+$180.00" and fake.methods == []


def test_a_matched_position_takes_robinhoods_pnl_and_keeps_its_plan(desk, engine, quotes, live):  # noqa: F811
    trade = planned_nbis(engine)
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=10))
    body = read(desk)
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert row["book"]["live"] == "matched" and row["book"]["account"] == {"label": "Roth IRA", "masked": "••8267"}
    assert (row["book"]["usd"], row["book"]["pct"], row["book"]["quantity"], row["book"]["mark"]) == (220.0, 35.5, 2.0, 420.0)
    # Live prices move it from Robinhood's own numbers: the cost that gives +$220 at its 420 mark, not the journal's.
    assert row["book"]["tick"] == {"quote": "NBIS261023C00100000", "scale": 100, "cost": 310.0, "quantity": 2.0, "sign": 1}
    assert row["value"] == {"text": "+$220.00", "tone": "gain"}
    # The standing's terms are Robinhood's own: its cost a contract, size, and the Greeks its last read kept.
    option = row["book"]["option"]
    assert option | {"greeks": None} == {"side": "call", "strike": 100.0, "expiry": "2026-10-23", "direction": "long",
                                         "quantity": 2.0, "multiplier": 100.0, "cost": 310.0, "greeks": None}
    assert option["greeks"] | {"as_of": None} == {"delta": 0.55, "theta": -0.12, "iv": 0.65, "as_of": None, "source": "robinhood"}
    assert isinstance(option["greeks"]["as_of"], (int, float))
    assert row["investigation_id"] == NBIS and row["book"]["state"] == "on_plan" and row["book"]["track"] is not None
    assert body["robinhood"]["state"] == "ok" and body["robinhood"]["joined"] is True
    assert [a["masked"] for a in body["robinhood"]["accounts"]] == ["••8267", "••7884"]
    text = json.dumps(body)
    assert "333338267" not in text and GUIDE not in text and "opt-nbis" not in text


def test_robinhood_only_positions_are_new_and_journal_only_ones_not_on_robinhood(desk, engine, quotes, live, fake):  # noqa: F811
    trade = buy(engine, 600, "CRWV")
    fake.options["444447884"] = [option_position("opt-ap", "APLD", quantity="1.0000", average="120.0000", expiry="2026-11-27")]
    fake.instruments["opt-ap"] = instrument("opt-ap", "APLD", strike="30.0000", side="put", expiry="2026-11-27")
    fake.quotes["opt-ap"] = option_quote("opt-ap", mark="1.000000")
    live._attempt = 0
    live.refresh()
    body = read(desk)
    [crwv] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert crwv["book"]["live"] == "not_on_robinhood" and crwv["value"]["text"] == "+$180.00"  # left as the journal has it
    new = [r for r in body["threads"] if r["key"].startswith("robinhood:")]
    assert [(r["key"], r["title"], r["instrument"], r["group"]) for r in new] == [
        ("robinhood:••8267:NBIS 10/23/26 100C", "NBIS 10/23/26 100C", "10/23/26 100C", "watch"),
        ("robinhood:••7884:APLD 11/27/26 30P", "APLD 11/27/26 30P", "11/27/26 30P", "watch")]
    nbis, apld = new
    assert nbis["status"] == {"text": "New · not in the journal yet", "tone": "info"} and nbis["trade_id"] is None
    assert apld["book"] | {} == {"usd": -20.0, "pct": -16.7, "expiry": "2026-11-27", "days_held": None, "track": None, "state": "no_plan",
                                 "planned": False, "stop_pct": None, "quantity": 1.0, "mark": 100.0,
                                 "account": {"label": "MCP", "masked": "••7884"}, "live": "new",
                                 "option": {"side": "put", "strike": 30.0, "expiry": "2026-11-27", "direction": "long", "quantity": 1.0,
                                            "multiplier": 100.0, "cost": 120.0,
                                            "greeks": apld["book"]["option"]["greeks"]}}
    assert apld["book"]["option"]["greeks"]["source"] == "robinhood" and apld["book"]["option"]["greeks"]["theta"] == -0.12
    assert apld["path"] == "/copilot-lab?symbol=APLD" and apld["close"] is None and apld["horizon"] is None


def test_a_new_position_whose_order_was_seen_says_so_until_its_fill_is_in(desk, engine, quotes, live):  # noqa: F811
    """docs/robinhood-order-fills.md: the order history saw the buy and its email is not in yet; once the fill is in by
    either route the row is the journal's own trade and this marker is gone (the join above)."""
    from datetime import datetime as _dt
    from decimal import Decimal as _D
    from app.engine.chart_math import ET as _ET
    from app.models import RobinhoodReconciliation
    with Session(engine) as db:
        db.add(RobinhoodReconciliation(key="order:seen-nbis", order_id="seen-nbis", outcome="pending", mode="shadow",
                                       account_last4="8267", instrument_type="option", ticker="NBIS", side="buy",
                                       option_type="call", strike=_D("100"), expiration=_dt(2026, 10, 23).date(),
                                       rh_last_at=_dt.now(_ET).replace(tzinfo=None)))
        db.commit()
    try:
        [nbis] = [r for r in read(desk)["threads"] if r["key"].startswith("robinhood:••8267:NBIS")]
        assert nbis["status"] == {"text": "New · fill seen on Robinhood, email not in yet", "tone": "info"}
    finally:
        with Session(engine) as db:
            db.delete(db.exec(select(RobinhoodReconciliation).where(RobinhoodReconciliation.key == "order:seen-nbis")).one())
            db.commit()


def test_a_ticker_not_followed_stays_hidden_on_a_new_row(desk, engine, quotes, live):  # noqa: F811
    from app.models import DayJournalEntry
    from tests.test_copilot_plans import WED
    with Session(engine) as db:
        db.add(DayJournalEntry(day=WED, operation_id="f-1", kind="follow", symbol="NBIS", text="Not following",
                               created_at=T0 + timedelta(minutes=1)))
        db.commit()
    [row] = [r for r in read(desk)["threads"] if r["key"].startswith("robinhood:")]
    assert row["symbol"] == "NBIS" and row["hidden"] is True


def test_stale_or_expired_falls_back_to_the_journal(desk, engine, quotes, live, clock, fake):  # noqa: F811
    trade = planned_nbis(engine)
    live._now = lambda: clock["t"] + rb.STALE_REFRESHES * rb.ttl(clock["t"]) + 1
    live._attempt = live._now()  # no background refresh in the test
    body = read(desk)
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert body["robinhood"]["state"] == "stale" and "live" not in row["book"] and row["value"]["text"] == "+$180.00"
    assert not [r for r in body["threads"] if r["key"].startswith("robinhood:")]


def test_the_feed_never_writes_to_the_journal(desk, engine, quotes, live):  # noqa: F811
    planned_nbis(engine)

    def counts():
        with Session(engine) as db:
            return len(db.exec(select(Fill)).all()), [(t.id, t.status, t.realized_pnl) for t in db.exec(select(Trade)).all()]
    before = counts()
    read(desk)
    desk.post("/copilot/desk/robinhood/refresh")
    assert counts() == before


def test_the_refresh_route_is_parameterless_and_owner_gated(desk, live, monkeypatch, fake):  # noqa: F811
    body = desk.post("/copilot/desk/robinhood/refresh", params={"name": "place_option_order"}, json={"tool": "cancel_option_order"}).json()
    assert body["state"] == "ok" and all(name in rh.READ_TOOLS for name, _ in fake.calls)
    from app.access_manifest import DOMAIN_ROUTES
    assert "POST /copilot/desk/robinhood/refresh" in DOMAIN_ROUTES
    from app.routers import copilot_desk
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.post("/copilot/desk/robinhood/refresh").status_code == 503


# --------------------------------------------------------------------------- review follow-ups

def test_no_readable_account_or_an_unknown_positions_shape_is_unavailable_never_empty(tmp_path, fake):
    fake.accounts = [{"account_number": "", "brokerage_account_type": "ira_roth"}]
    feed, _ = make_feed(tmp_path)
    feed.refresh()
    assert feed.view(kick=False) == {"state": "unavailable"}
    fake.accounts = [dict(a) for a in FakeRobinhood().accounts]
    fake.tool_get_equity_positions = lambda args: {"holdings": []}
    feed, _ = make_feed(tmp_path)
    feed.refresh()
    _view, snapshot = feed.snapshot(kick=False)
    assert snapshot["complete"] is False  # so nothing is called "not on Robinhood"


def test_an_alphanumeric_account_number_takes_its_last_four_from_the_digits(tmp_path, fake):
    for a in fake.accounts:
        digits = a["account_number"]
        fake.portfolios["5QR" + digits[-5:]] = fake.portfolios.pop(digits)
        if digits in fake.options:
            fake.options["5QR" + digits[-5:]] = fake.options.pop(digits)
        a["account_number"] = "5QR" + digits[-5:]
    view, snapshot = snap(tmp_path)
    assert [a["masked"] for a in view["accounts"]] == ["••8267", "••7884"] and snapshot["positions"][0]["last4"] == "8267"


def test_matching_takes_every_same_account_match_before_any_other():
    key = ("NBIS", "call", 100.0, "2026-10-23")
    live = [{"symbol": "NBIS", "instrument": "option", "side": "call", "strike": 100.0, "expiry": "2026-10-23", "last4": "8267"}]
    journal = [{"trade_id": "other", "key": key, "last4": "5555"}, {"trade_id": "roth", "key": key, "last4": "8267"}]
    matched, missing, extra = rb.match(journal, {"positions": live, "complete": True})
    assert list(matched) == ["roth"] and missing == {"other"} and extra == []


def test_a_short_options_pnl_holds_whatever_the_sign_of_its_average(tmp_path, fake):
    fake.options["333338267"] = [option_position("opt-nbis", "NBIS", average="-310.0000", kind="short")]
    _view, snapshot = snap(tmp_path)
    [p] = snapshot["positions"]
    assert (p["direction"], p["avg_cost"], p["usd"], p["pct"]) == ("short", 310.0, -220.0, -35.5)


def test_a_position_past_the_desks_row_cut_is_in_the_journal_not_new(desk, engine, quotes, live, fake, monkeypatch):  # noqa: F811
    from app.engine import plan_positions
    monkeypatch.setattr(plan_positions, "MAX_ROWS", 1)
    buy(engine, 600, "CRWV")
    planned_nbis(engine)
    fake.options["333338267"].append(option_position("opt-crwv", "CRWV"))
    fake.instruments["opt-crwv"] = instrument("opt-crwv", "CRWV")
    fake.quotes["opt-crwv"] = option_quote("opt-crwv")
    live._attempt = 0
    live.refresh()
    body = read(desk)
    assert [r for r in body["threads"] if r["key"].startswith("robinhood:")] == []


def test_the_book_tag_follows_robinhoods_pnl_a_give_back_under_water_is_not_giving_back(desk, engine, quotes, fake, tmp_path,  # noqa: F811
                                                                                        monkeypatch, clock):  # noqa: F811
    from app.engine import plan_positions
    trade = planned_nbis(engine)
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=10))
    # The give-back alert fired with no new high since; the journal's P&L is a gain (+$180): Giving back.
    monkeypatch.setattr(plan_positions, "_watch", lambda db, trade: ("fired", None, True))
    [row] = [r for r in read(desk)["threads"] if r["key"] == f"trade:{trade}"]
    assert row["book"]["state"] == "giving_back"
    # Robinhood shows it under its entry (0.40 a share against 3.10): the tag says how it stands against its plan instead.
    fake.quotes["opt-nbis"] = option_quote("opt-nbis", mark="0.400000")
    feed, at = make_feed(tmp_path, now=clock["t"])
    monkeypatch.setattr(rb, "feed", feed)
    feed.refresh()
    at["t"] = clock["t"]
    [row] = [r for r in read(desk)["threads"] if r["key"] == f"trade:{trade}"]
    assert row["book"]["live"] == "matched" and row["book"]["usd"] < 0
    assert row["book"]["state"] == "on_plan" and row["book"]["planned"] is True


# --------------------------------------------------------------------------- Robinhood's orders on the book

DAY = "2026-10-21"  # the desk clock's day (14:49 New York)


@pytest.fixture
def orders(engine, live, clock, monkeypatch):  # noqa: F811
    """The order-history pass in shadow, as production runs it, on the desk's clock and the feed's sign-in."""
    from app.engine import robinhood_fills as rf
    poller = rf.Poller(engine, live, now=lambda: clock["t"], mode_fn=lambda: "shadow")
    monkeypatch.setattr(rf, "poller", poller)
    return poller


def nbis_close(order_id, executions, **kw):
    from tests.robinhood_fake import option_order
    return option_order(order_id, "NBIS", executions, side="sell", effect="close", strike="100.0000", expiry="2026-10-23", **kw)


def test_a_working_order_and_a_fresh_fill_sit_on_their_book_row(desk, engine, quotes, live, orders, fake):  # noqa: F811
    from tests.robinhood_fake import execution
    from tests.test_robinhood_fills import utc
    trade = planned_nbis(engine)
    fake.option_orders["333338267"] = [
        nbis_close("w1", [], quantity="2.00000", state="confirmed", created_at=utc(14, 40, day=DAY)) | {"price": "4.50000000"},
        nbis_close("f1", [execution("f1a", "4.30000000", "1.00000", utc(14, 42, day=DAY))], created_at=utc(14, 41, day=DAY)),
        nbis_close("gone", [], quantity="1.00000", state="cancelled", created_at=utc(14, 30, day=DAY))]
    orders.run_once()
    calls = len(fake.calls)
    body = read(desk)
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    working, filled = row["book"]["orders"]
    assert working == {"contract": "NBIS 10/23/26 100C", "symbol": "NBIS", "instrument": "option", "action": "Sell to close",
                       "working": True, "quantity": 2.0, "filled": 0.0, "price_kind": "limit", "limit": 4.5, "avg": None,
                       "placed_at": int(utc_epoch(14, 40)), "filled_at": None,
                       "account": {"label": "Roth IRA", "masked": "••8267"}, "pairing": None}
    assert (filled["working"], filled["filled"], filled["avg"], filled["filled_at"], filled["pairing"]) == (
        False, 1.0, 4.3, int(utc_epoch(14, 42)), "provisional")
    assert "orders" not in body["robinhood"]  # nothing left over: no empty group
    assert len(fake.calls) == calls  # the desk read made no Robinhood call
    text = json.dumps(body)
    assert "w1" not in text and "f1a" not in text and "333338267" not in text  # no Robinhood id or account number


def utc_epoch(hh, mm):
    from tests.test_robinhood_fills import epoch
    return epoch(hh, mm, day=DAY)


def test_an_order_with_no_position_goes_to_the_orders_group_and_a_hidden_ticker_stays_hidden(desk, engine, quotes, live, orders, fake):  # noqa: F811
    from app.models import DayJournalEntry
    from tests.robinhood_fake import equity_order, execution, option_order
    from tests.test_copilot_plans import WED
    from tests.test_robinhood_fills import utc
    fake.option_orders["444447884"] = [option_order("n1", "APLD", [], strike="30.0000", kind="put", expiry="2026-11-27",
                                                    quantity="1.00000", state="queued", created_at=utc(14, 45, day=DAY))]
    fake.equity_orders["333338267"] = [equity_order("s1", "RKLB", [execution("s1a", "55.10", "3", utc(14, 44, day=DAY))], side="sell")]
    fake.option_orders["333338267"] = [nbis_close("h1", [], quantity="1.00000", state="queued", created_at=utc(14, 46, day=DAY))]
    with Session(engine) as db:
        db.add(DayJournalEntry(day=WED, operation_id="f-1", kind="follow", symbol="NBIS", text="Not following",
                               created_at=T0 + timedelta(minutes=1)))
        db.commit()
    orders.run_once()
    body = read(desk)
    group = body["robinhood"]["orders"]
    assert [(o["contract"], o["action"], o["working"], o["account"]["masked"]) for o in group] == [
        ("APLD 11/27/26 30P", "Buy to open", True, "••7884"),  # NBIS is not followed: its order stays hidden too
        ("RKLB stock", "Sell", False, "••8267")]
    assert group[1]["price_kind"] == "market" and group[1]["avg"] == 55.1 and group[1]["pairing"] == "provisional"
    assert "NBIS" not in json.dumps(body["robinhood"])
    assert not any(r.get("book", {}).get("orders") for r in body["threads"])


def test_robinhood_off_or_the_pass_off_shows_no_orders(desk, engine, quotes, live, orders, fake, monkeypatch):  # noqa: F811
    from tests.test_robinhood_fills import utc
    trade = planned_nbis(engine)
    fake.option_orders["333338267"] = [nbis_close("w1", [], quantity="1.00000", state="queued", created_at=utc(14, 40, day=DAY))]
    orders.run_once()
    assert [r for r in read(desk)["threads"] if r["key"] == f"trade:{trade}"][0]["book"]["orders"]
    monkeypatch.setattr(rb, "feed", rb.Feed(settings_fn=lambda: rb.Settings(False, None, ())))  # Robinhood off
    body = read(desk)
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert "orders" not in row["book"] and body["robinhood"] == {"state": "off"}
    monkeypatch.setattr(rb, "feed", live)
    orders._mode = lambda: "off"  # the order-history pass switched off: nothing to show
    orders.run_once()
    body = read(desk)
    assert "orders" not in [r for r in body["threads"] if r["key"] == f"trade:{trade}"][0]["book"] and "orders" not in body["robinhood"]


def test_reading_the_orders_on_the_desk_writes_nothing(desk, engine, quotes, live, orders, fake):  # noqa: F811
    from app.models import RobinhoodExecution, RobinhoodReconciliation
    from tests.robinhood_fake import execution
    from tests.test_robinhood_fills import utc
    planned_nbis(engine)
    fake.option_orders["333338267"] = [nbis_close("f1", [execution("f1a", "4.30000000", "1.00000", utc(14, 42, day=DAY))])]
    orders.run_once()

    def state():
        with Session(engine) as db:
            return ([(f.id, f.contracts, f.price) for f in db.exec(select(Fill)).all()],
                    [(t.id, t.status, t.contracts, t.realized_pnl) for t in db.exec(select(Trade)).all()],
                    [(r.key, r.outcome, r.updated_at) for r in db.exec(select(RobinhoodReconciliation)).all()],
                    len(db.exec(select(RobinhoodExecution)).all()))

    before = state()
    for _ in range(5):
        read(desk)
    assert state() == before
