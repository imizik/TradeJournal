"""The Ticket's Play check (engine/play_check.py): the plan's parts, the after-fill habit rules judged before the entry,
and the holding-overnight arithmetic with the same-delta alternatives. Hand-checked numbers; no network, no model."""

from datetime import UTC, date, datetime
import inspect
from math import sqrt
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import desk_ticket, fill_interrupts, play_check, reconstructor
from app.engine.chart_feed import chart_feed
from app.engine.chart_math import ET
from app.engine.options_models import OptionChain, OptionContract
from app.models import Account, DayJournalEntry
from tests.test_fill_interrupts import ROTH, INDIVIDUAL, WEBULL, WED, FRI, fill, ny, past, seed_history

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    monkeypatch.setattr(play_check, "_history", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1111", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def judge(engine, *, symbol="NBIS", kind="call", strike=100.0, expiry=date(2026, 10, 30), contracts=1, limit=3.20,
          hhmm="10:30", account=ROTH, quiet=None):
    with Session(engine) as db:
        return play_check.habits(db, symbol=symbol, kind=kind, strike=strike, expiry=expiry, contracts=contracts, limit=limit,
                                 multiplier=100, account_id=account, moment=ny(hhmm), quiet=quiet)


def kinds(found):
    return [f["kind"] for f in found["fired"]]


# --- Your habits, before the entry -----------------------------------------------------------------------------------

def test_a_clean_call_fires_nothing(engine):
    found = judge(engine)
    assert found["state"] == "ok" and found["fired"] == [] and found["size"] is None
    assert found["footer"] == "Your record, not advice."


def test_put_entry_and_late_short_dated_with_the_after_fill_lines(engine):
    seed_history(engine)
    late = judge(engine, kind="put", expiry=FRI, hhmm="14:30")  # Friday is two trading days from Wednesday
    assert kinds(late) == ["put_entry", "late_short_dated"]
    # The same record lines the after-fill message carries, from the same records.
    assert late["fired"][0]["line"] == "Put entry: puts −$350 over 6 trades; calls 4, too few to read"
    assert late["fired"][1]["line"] == "Late short-dated buy: 1 past buy after 2 PM with 0–2 days left, too few to read"
    assert kinds(judge(engine, kind="put", expiry=FRI, hhmm="13:59")) == ["put_entry"]  # before 14:00
    assert kinds(judge(engine, kind="call", expiry=date(2026, 10, 26), hhmm="15:00")) == []  # three trading days left


def test_adding_to_a_loser_reads_the_open_position_in_this_contract(engine):
    # He holds one NBIS 100C bought at $320 a contract; buying more at 2.50 ($250) is below that cost.
    fill(engine, ny("09:45"), "NBIS", option_type="call", strike=100, price=320, expiration=date(2026, 10, 30))
    assert kinds(judge(engine, limit=2.50)) == ["add_to_loser"]
    assert judge(engine, limit=2.50)["fired"][0]["line"] == "Adding to a loser: 0 past adds, too few to read"
    assert kinds(judge(engine, limit=3.30)) == []  # above his cost
    assert kinds(judge(engine, strike=105.0, limit=2.50)) == []  # another contract
    assert kinds(judge(engine, limit=None)) == []  # no limit to compare


def test_a_webull_holding_is_not_a_loser_to_add_to(engine):
    fill(engine, ny("09:45"), "NBIS", option_type="call", strike=100, price=320, expiration=date(2026, 10, 30), account=WEBULL)
    assert kinds(judge(engine, limit=2.50)) == []


def test_the_day_already_green_reads_the_plan_accounts_closes_today(engine):
    fill(engine, ny("09:40"), "MU", option_type="call", strike=100, price=100, expiration=date(2026, 10, 30), rebuild=False)
    fill(engine, ny("10:00"), "MU", side="sell_to_close", option_type="call", strike=100, price=300, expiration=date(2026, 10, 30))
    found = judge(engine)
    assert kinds(found) == ["opened_green"]
    assert found["fired"][0]["line"] == "Day already green (+$200 today): 0 past trades opened green, too few to read"
    assert kinds(judge(engine, account=INDIVIDUAL)) == []  # another account's day
    assert kinds(judge(engine, hhmm="09:55")) == []  # before the close
    assert kinds(judge(engine, account=None)) == []  # no account: no day to read


def test_a_losing_ticker_record_of_five(engine):
    for i in range(5):
        fill(engine, ny(f"10:0{i}", date(2026, 10, 14)), "SNDK", option_type="call", strike=500 + i, price=300,
             expiration=date(2026, 10, 30), rebuild=False)
        fill(engine, ny(f"10:1{i}", date(2026, 10, 14)), "SNDK", side="sell_to_close", option_type="call", strike=500 + i,
             price=200 if i else 350, expiration=date(2026, 10, 30), rebuild=i == 4)
    found = judge(engine, symbol="SNDK")
    assert kinds(found) == ["ticker_record"]
    assert found["fired"][0]["line"] == "Your record in SNDK: 5 trades, 20% won, −$350"


def test_large_size_against_the_median_and_its_parts_for_the_desk(engine, monkeypatch):
    rows = [past(f"u{i}", premium=1000.0, pnl=50.0) for i in range(20)]
    monkeypatch.setattr(play_check, "history", lambda db, today: rows)
    found = judge(engine, contracts=4, limit=5.00)  # $2,000: twice the $1,000 median
    assert kinds(found) == ["large_size"]
    assert found["fired"][0]["line"] == "Size: $2,000 is 2.0× your median ($1,000); your 0 past entries above 2×, too few to read"
    assert found["size"] == {"median": 1000.0, "multiple": 2.0, "tail": "your 0 past entries above 2×, too few to read"}
    assert kinds(judge(engine, contracts=3, limit=5.00)) == []  # $1,500
    assert kinds(judge(engine, contracts=4, limit=None)) == []  # no limit: no premium to judge


def test_a_hidden_ticker_stays_silent(engine):
    seed_history(engine)
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="hide-nbis", day=WED, kind="follow", symbol="NBIS", text="Not following"))
        db.commit()
    found = judge(engine, kind="put", expiry=FRI, hhmm="14:30")
    assert found["state"] == "quiet" and found["fired"] == []
    assert kinds(judge(engine, symbol="CRWV", kind="put", expiry=FRI, hhmm="14:30")) == ["put_entry", "late_short_dated"]


def test_the_records_are_cached_until_the_closed_trades_change(engine, monkeypatch):
    seed_history(engine)
    loads = []
    real = fill_interrupts.load_history
    monkeypatch.setattr(fill_interrupts, "load_history", lambda db: loads.append(1) or real(db))
    judge(engine)
    judge(engine, kind="put")
    assert len(loads) == 1
    fill(engine, ny("09:40"), "MU", option_type="call", strike=100, price=100, expiration=date(2026, 10, 30), rebuild=False)
    fill(engine, ny("10:00"), "MU", side="sell_to_close", option_type="call", strike=100, price=300, expiration=date(2026, 10, 30))
    judge(engine)
    assert len(loads) == 2


def test_the_after_fill_size_line_is_unchanged():
    rec = {"n": 5, "pnl": -1300, "green": 1, "median": 1000.0, "entries": 20}
    assert fill_interrupts.line("large_size", rec, paid=2300.0) == (
        "Size: $2,300 is 2.3× your median ($1,000); your 5 past entries above 2×: 20% won, −$1,300")
    assert fill_interrupts.size_tail(rec) == "your 5 past entries above 2×: 20% won, −$1,300"


# --- Play ------------------------------------------------------------------------------------------------------------

def test_play_lines_clean_and_missing():
    row = {"time_stop": {"text": "out by Friday", "state": "pending", "due_at": 0}}
    clean = play_check.play({"invalidation": 90.0, "size": {"contracts": 2}}, row, None)
    assert [(line["part"], line["ok"], line["text"]) for line in clean["lines"]] == [
        ("stop", True, "out at 90"), ("time", True, "out by Friday"), ("size", True, "2 contracts")]
    assert clean["missing"] == [] and clean["fill"] is None
    bare = play_check.play({"invalidation": None, "size": {"contracts": None, "risk_usd": None}}, {"time_stop": None}, None)
    assert bare["missing"] == ["stop", "time", "size"]
    assert bare["fill"] == "Add a stop, a time stop and a size to the plan."
    assert [line["text"] for line in bare["lines"]][1] == "missing: no time stop"
    # A horizon check-in stands for the time; dollars at risk stand for the size.
    other = play_check.play({"invalidation": 90.0, "size": {"risk_usd": 500.0}}, {"time_stop": None}, "swing")
    assert [line["text"] for line in other["lines"]][1:] == ["swing horizon (your check-in; no time stop)", "risk $500"]
    # A target line only once the plan board carries targets at all.
    assert "target" not in [line["part"] for line in clean["lines"]]
    targeted = play_check.play({"invalidation": 90.0, "size": {"contracts": 1}}, {**row, "target": None}, None)
    assert targeted["missing"] == ["target"] and targeted["fill"] == "Add a target to the plan."
    assert play_check.play({"invalidation": 90.0, "size": {"contracts": 1}}, {**row, "target": {"price": 104.5}}, None)["lines"][1]["text"] == \
        "take profit at 104.5"


# --- Holding overnight -----------------------------------------------------------------------------------------------

NOW = datetime(2026, 11, 13, 10, 0, tzinfo=ET)  # Friday 10:00 New York
NOV20, DEC18 = date(2026, 11, 20), date(2026, 12, 18)


def oc(strike, kind="call", *, mid, delta, theta, iv=0.6, expiry=NOV20, symbol="NBIS"):
    at = NOW.astimezone(UTC)
    return OptionContract(symbol=f"{symbol}{expiry:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}", underlying=symbol, root=symbol,
                          expiration=expiry, option_type=kind, strike=strike, multiplier=100, bid=round(mid - 0.05, 2),
                          ask=round(mid + 0.05, 2), last=None, bid_size=None, ask_size=None, volume=None, open_interest=None,
                          bid_time=at, ask_time=at, trade_time=None, iv=iv, iv_smoothed=None, delta=delta, gamma=None, theta=theta,
                          vega=None, greeks_updated_at="2026-11-13 09:00:00")


def chain(*contracts, expiry=NOV20):
    return OptionChain(underlying="NBIS", expiration=expiry, provider="tradier", fetched_at=NOW.astimezone(UTC), contracts=tuple(contracts))


def fresh(contract, its_chain):
    return {"state": "ok", "mid": round((contract.bid + contract.ask) / 2, 2), "as_of": NOW.timestamp()}


def stop_at(moment: datetime) -> dict:
    return {"text": "out then", "state": "pending", "due_at": int(moment.timestamp())}


MINE = oc(100, mid=3.20, delta=0.40, theta=-0.10)
NEAR = chain(MINE, oc(92.5, mid=7.00, delta=0.70, theta=-0.08), oc(90, mid=8.50, delta=0.80, theta=-0.07),
             oc(95, mid=4.00, delta=0.55, theta=-0.11), oc(95, "put", mid=4.00, delta=-0.45, theta=-0.11),
             oc(107.5, mid=1.00, delta=0.20, theta=-0.06), oc(110, mid=0.60, delta=0.15, theta=-0.04))
LATER = chain(oc(100, mid=6.00, delta=0.45, theta=-0.05, iv=0.55, expiry=DEC18), expiry=DEC18)


def test_black_scholes_against_known_values():
    # At the money, a year, 20% volatility, rate zero: S(2N(0.1) - 1) = 7.9656 for the call and, by parity, the put.
    assert play_check.bs_value("call", 100, 100, 1.0, 0.2) == pytest.approx(7.9656, abs=1e-4)
    assert play_check.bs_value("put", 100, 100, 1.0, 0.2) == pytest.approx(7.9656, abs=1e-4)
    assert play_check.bs_value("call", 105, 100, 0.0, None) == 5 and play_check.bs_value("put", 105, 100, 0.0, 0.3) == 0
    assert play_check.bs_value("call", 100, 100, 0.5, None) is None


def test_decay_and_the_alternatives_sized_to_the_same_delta():
    # Held to the expiry (time stop after it): every break-even is the expiry's.
    found = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=LATER, spot=95.0, now=NOW,
                                 time_stop=stop_at(datetime(2026, 11, 23, 15, 0, tzinfo=ET)), horizon=None, quote_for=fresh)
    assert found["state"] == "ok" and found["show"] is True and found["expires_first"] is True
    assert found["basis"] == "per contract" and found["greeks_as_of"] == "2026-11-13 09:00:00"
    assert found["trading_days"] == 5  # Friday to the next Friday
    rows = {r["name"]: r for r in found["rows"]}
    assert list(rows) == ["as_traded", "deeper", "spread", "later", "shares"]
    mine = rows["as_traded"]
    # One contract: $320 at the 3.20 mid; theta -0.10 a share is $10 a day, 3.1% of the premium; expiry break-even 103.20.
    assert (mine["units"], mine["cost"], mine["max_loss"], mine["decay_day"], mine["decay_pct"]) == (1.0, 320.0, 320.0, 10.0, 3.1)
    assert mine["breakeven"] == 103.2 and mine["breakeven_move_pct"] == pytest.approx((103.2 - 95) / 95 * 100, abs=0.01)
    # Deeper: the 92.5 call (delta 0.70, nearest 0.70). 40 deltas / 70 = 0.571 contracts: $400, $4.57 a day, break-even 99.50.
    deep = rows["deeper"]
    assert deep["label"] == "NBIS $92.5 Call 11/20/26"
    assert (deep["units"], deep["cost"], deep["decay_day"], deep["breakeven"]) == (0.57, 400.0, 4.57, 99.5)
    # Spread: 100/107.5 (the 95 straddle is 8.00, so the short strike nearest 108). 40 / (40 - 20) = 2 spreads at 2.20: $440;
    # theta -0.10 + 0.06 = -0.04 a share, x 100 x 2 = $8 a day; break-even 102.20.
    spread = rows["spread"]
    assert spread["label"] == "NBIS $100/$107.5 Call 11/20/26 spread"
    assert (spread["units"], spread["cost"], spread["max_loss"], spread["decay_day"], spread["breakeven"]) == (2.0, 440.0, 440.0, 8.0, 102.2)
    # Later: the December 100 call (delta 0.45). 40 / 45 = 0.889: $533.33, $4.44 a day; still worth time value on Nov 20,
    # so it breaks even below the November contract's 103.20.
    later = rows["later"]
    assert (later["units"], later["cost"], later["decay_day"]) == (0.89, 533.33, 4.44)
    assert 95 < later["breakeven"] < 103.2
    # Shares: 40 shares at 95, no decay, break-even where bought.
    shares = rows["shares"]
    assert (shares["units"], shares["cost"], shares["max_loss"], shares["decay_day"], shares["breakeven"]) == (40, 3800.0, 3800.0, 0.0, 95.0)
    # The hold costs the option its time value at an unchanged price; shares nothing.
    assert mine["hold_cost"] > 0 and shares["hold_cost"] == 0


def test_hold_cost_and_expected_move_hand_checked():
    # A year to expiry at the money, 20% volatility: held to expiry at an unchanged price it loses all its model value,
    # 7.9656 x 100 = $796.56; the move the volatility gives over the year is 20%.
    now = datetime(2026, 11, 13, 16, 0, tzinfo=ET)
    year = date(2027, 11, 13)
    mine = oc(100, mid=7.97, delta=0.54, theta=-0.01, iv=0.2, expiry=year)
    found = play_check.overnight(symbol="NBIS", traded=mine, chain=chain(mine, expiry=year), later=None, spot=100.0, now=now,
                                 time_stop=stop_at(datetime(2027, 11, 13, 16, 0, tzinfo=ET)), horizon=None, quote_for=fresh)
    row = found["rows"][0]
    assert found["expected_move_pct"] == 20.0
    assert row["hold_cost"] == pytest.approx(796.56, abs=0.01) and row["hold_cost_pct"] == pytest.approx(99.9, abs=0.1)
    assert row["breakeven"] == 107.97 and row["breakeven_move_pct"] == 7.97 and row["vs_expected"] == 0.4


def test_a_stop_before_expiry_breaks_even_below_the_expiry_break_even():
    found = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=None, spot=95.0, now=NOW,
                                 time_stop=stop_at(datetime(2026, 11, 17, 15, 30, tzinfo=ET)), horizon=None, quote_for=fresh)
    mine = found["rows"][0]
    assert found["expires_first"] is False and found["trading_days"] == 2 and found["show"] is True
    assert 95 < mine["breakeven"] < 103.2  # time value left at the stop
    # The expected move over the hold: 0.6 x sqrt(hold in years).
    hold = (datetime(2026, 11, 17, 15, 30, tzinfo=ET) - NOW).total_seconds() / (365 * 86400)
    assert found["expected_move_pct"] == round(0.6 * sqrt(hold) * 100, 2)
    assert "later" not in {r["name"] for r in found["rows"]}  # no later chain read, no later row


def test_when_the_plan_ends_today_the_figures_are_folded_for_the_next_close():
    today = stop_at(datetime(2026, 11, 13, 15, 30, tzinfo=ET))
    folded = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=None, spot=95.0, now=NOW, time_stop=today,
                                  horizon=None, quote_for=fresh)
    assert folded["show"] is False and folded["until_source"] == "time stop"
    nothing = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=None, spot=95.0, now=NOW, time_stop=None,
                                   horizon=None, quote_for=fresh)
    assert nothing["show"] is False and nothing["until_source"] == "next close"
    assert nothing["until"] == int(datetime(2026, 11, 16, 16, 0, tzinfo=ET).timestamp())  # Friday's next close is Monday
    swing = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=None, spot=95.0, now=NOW, time_stop=None,
                                 horizon="swing", quote_for=fresh)
    assert swing["show"] is True and swing["until_source"] == "swing horizon"


def test_a_put_compares_short_shares_said_as_not_in_a_roth():
    put = oc(90, "put", mid=2.00, delta=-0.30, theta=-0.08)
    found = play_check.overnight(symbol="NBIS", traded=put, chain=chain(put, oc(95, mid=4.0, delta=0.55, theta=-0.1),
                                                                     oc(95, "put", mid=4.0, delta=-0.45, theta=-0.1)),
                                 later=None, spot=95.0, now=NOW, time_stop=None, horizon="swing", quote_for=fresh)
    shares = next(r for r in found["rows"] if r["name"] == "shares")
    assert shares["label"] == "Short NBIS shares" and shares["note"] == "not in a Roth IRA"
    assert shares["units"] == 30 and shares["max_loss"] is None and shares["breakeven"] == 95.0
    assert found["rows"][0]["breakeven"] == 88.0  # 90 - 2.00 at the November expiry, inside the swing horizon's 7 days


def test_a_stale_leg_is_grey_with_its_time_and_no_number():
    def stale_deeper(contract, its_chain):
        if contract.strike == 92.5:
            return {"state": "stale", "as_of": 1_700_000_000, "reason": "The latest bid and ask are too old to price an order from."}
        return fresh(contract, its_chain)
    found = play_check.overnight(symbol="NBIS", traded=MINE, chain=NEAR, later=None, spot=95.0, now=NOW, time_stop=None,
                                 horizon="swing", quote_for=stale_deeper)
    deep = next(r for r in found["rows"] if r["name"] == "deeper")
    assert deep["state"] == "stale" and deep["as_of"] == 1_700_000_000
    assert "cost" not in deep and "breakeven" not in deep


# --- On the ticket ---------------------------------------------------------------------------------------------------

def test_the_ticket_carries_the_check(monkeypatch):
    from tests.test_desk_ticket import NOW as TICKET_NOW, plan
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    monkeypatch.setattr(play_check, "_history", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=UUID(int=1), name="Roth IRA", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    plan(engine)  # NBIS 11/13 100C, out at 90, "out by Friday", no size
    at = datetime.fromtimestamp(TICKET_NOW - 30, UTC)
    expiry = date(2026, 11, 13)

    def contract(strike, mid, delta, theta, day=expiry):
        return OptionContract(symbol=f"NBIS{day:%y%m%d}C{int(strike * 1000):08d}", underlying="NBIS", root="NBIS", expiration=day,
                              option_type="call", strike=strike, multiplier=100, bid=mid - 0.1, ask=mid + 0.1, last=None, bid_size=None,
                              ask_size=None, volume=None, open_interest=None, bid_time=at, ask_time=at, trade_time=None, iv=0.7,
                              iv_smoothed=None, delta=delta, gamma=None, theta=theta, vega=None, greeks_updated_at="2026-10-21 09:00:00")

    def read(symbol, day):
        near = OptionChain("NBIS", day, "tradier", at, (contract(100, 3.2, 0.4, -0.08), contract(90, 7.5, 0.72, -0.05)))
        later = OptionChain("NBIS", date(2026, 12, 18), "tradier", at, (contract(100, 6.0, 0.45, -0.04, date(2026, 12, 18)),))
        return {"chain": near, "fetched": TICKET_NOW - 20, "spot": 95.0, "spot_at": TICKET_NOW - 10, "simulated": False, "issue": None,
                "later": later, "later_fetched": TICKET_NOW - 20}

    with Session(engine) as db:
        found = desk_ticket.build(db, "11111111-1111-4111-8111-111111111111", now=TICKET_NOW, chain_read=read)
    check = found["check"]
    assert [(line["part"], line["ok"]) for line in check["play"]["lines"]] == [("stop", True), ("time", True), ("size", False)]
    assert check["habits"]["fired"] == []
    night = check["overnight"]
    assert night["state"] == "ok" and night["show"] is True  # the time stop is two days out
    assert [r["name"] for r in night["rows"]] == ["as_traded", "deeper", "later", "shares"]
    assert night["rows"][0]["decay_day"] == 8.0 and night["rows"][0]["cost"] == 320.0

    def stale(symbol, day):
        return {**read(symbol, day), "fetched": TICKET_NOW - 3600}
    with Session(engine) as db:
        grey = desk_ticket.build(db, "11111111-1111-4111-8111-111111111111", now=TICKET_NOW, chain_read=stale)["check"]["overnight"]
    assert grey["state"] == "stale" and "rows" not in grey
    engine.dispose()


def test_the_check_places_nothing_and_calls_no_model():
    text = inspect.getsource(play_check).lower()
    for word in ("robinhood_read", "place_option_order", "review_option_order", "phone.send", "requests.post", "httpx", "anthropic",
                 "copilot_api", "ntfy", "telegram"):
        assert word not in text
