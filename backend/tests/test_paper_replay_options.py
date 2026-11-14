"""Options in paper replay (``app/engine/replay_options.py`` and ``paper_replay``): the picker offers only contracts
whose own trades came back for the replayed day, each read once and within its own small budget; a fill is the
contract's trade bar for the minute just ended plus a half-spread from that minute's range, ×100; a minute it did not
trade is refused; limits fill only on minutes it traded; stop and target are stock levels; an option expiring that day
settles at intrinsic value from the stock's last bar; older days keep options off while shares replay. Invented numbers,
no network."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import chart_feed as chart_feed_module, paper_replay, replay_options as ro, tradier
from app.routers import copilot_paper
from tests.test_paper_book import db, key  # noqa: F401 -- fixtures

DAY = date(2026, 11, 13)  # a Friday
OPEN = int(datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp())  # 09:30 New York
CLOSE = int(datetime(2026, 11, 13, 21, 0, tzinfo=UTC).timestamp())  # 16:00 New York
NOW = datetime(2026, 11, 14, 17, 0, tzinfo=UTC).timestamp()  # Saturday
M = 60
CALL = "NBIS261120C00100000"  # NBIS $100 call, Nov 20
ZERO = "NBIS261113C00100000"  # NBIS $100 call expiring on the replayed day


def at(minute):
    return OPEN + minute * M


def bar(minute, o, h, low, c, volume=1000.0):
    start = OPEN + minute * M
    return {"time": start, "end_time": start + M, "open": o, "high": h, "low": low, "close": c, "volume": volume, "source": "alpaca_sip"}


# The stock trades every minute: 102.9 at 09:34, a dip under 100 at 09:37, the last bar of the day closes 101.50.
STOCK = [bar(m, 102.9, 103.0, 102.8, 102.9) for m in range(0, 7)] + [bar(7, 101.0, 101.0, 99.5, 100.2)] \
    + [bar(m, 100.2, 100.4, 100.0, 100.3) for m in range(8, 20)] + [bar(389, 101.4, 101.6, 101.3, 101.5)]


def print_(minute, o, h, low, c):  # one minute of the contract's trades as Tradier's time and sales returns it
    return {"time": "", "timestamp": OPEN + minute * M, "open": o, "high": h, "low": low, "close": c, "volume": 12}


# The Nov 20 $100 call traded at 09:32, 09:34, 09:35, 09:36 and 09:40 (none at 09:37–09:39).
TRADES = {CALL: [print_(2, 2.20, 2.22, 2.18, 2.20), print_(4, 2.30, 2.40, 2.28, 2.35), print_(5, 2.50, 2.55, 2.45, 2.50),
                 print_(6, 2.59, 2.62, 2.58, 2.60), print_(10, 2.25, 2.30, 2.10, 2.15)],
          "NBIS261120C00101000": [print_(3, 1.90, 1.95, 1.88, 1.92)],
          ZERO: [print_(4, 3.00, 3.10, 2.95, 3.05), print_(388, 1.45, 1.55, 1.40, 1.50)]}


@pytest.fixture(autouse=True)
def market(monkeypatch):
    state = SimpleNamespace(stock={"NBIS": list(STOCK)}, trades=dict(TRADES), reads=[])
    monkeypatch.setattr(paper_replay, "regular", lambda d: (OPEN, CLOSE) if d == DAY else None)
    monkeypatch.setattr(paper_replay, "bars", lambda symbol, d: state.stock[symbol])
    monkeypatch.setattr(ro, "_trading", lambda d: d.weekday() < 5)
    monkeypatch.setattr(tradier, "tradier_configured", lambda: True)

    def read(path, params, ttl, keep=True, low=False):
        assert path == "/v1/markets/timesales" and low and not keep  # a background read the module keeps itself
        state.reads.append(params["symbol"])
        return {"series": {"data": state.trades.get(params["symbol"], [])} if params["symbol"] in state.trades else None}, NOW, None
    monkeypatch.setattr(chart_feed_module.chart_feed, "read", read)
    paper_replay._kept.clear()
    ro._kept.clear()
    ro._reads.clear()
    return state


def run(db, cash=None):  # noqa: F811
    return paper_replay.start(db, {"day": DAY.isoformat(), "starting_cash": cash}, NOW)


def buy(db, r, clock, occ=CALL, qty=2, now=NOW, **extra):  # noqa: F811
    expiry = "2026-11-20" if occ == CALL else "2026-11-13"
    return paper_replay.order(db, {"run_id": str(r.id), "at": clock, "action": "open", "symbol": "NBIS", "instrument": "option",
                                   "option_type": "call", "expiry": expiry, "strike": 100, "quantity": qty, "order_key": key(),
                                   **extra}, now)


def step(db, r, clock, end=False):  # noqa: F811
    return paper_replay.step(db, {"run_id": str(r.id), "at": clock, "end": end}, NOW)


def test_expirations_and_strikes_come_from_the_standard_calendars_and_grids():
    monday = date(2026, 12, 21)  # Dec 25 and Jan 1 are Friday holidays: those weeks expire on Thursday
    holidays = {date(2026, 12, 25), date(2027, 1, 1)}
    ro_trading = ro._trading
    try:
        ro._trading = lambda d: d.weekday() < 5 and d not in holidays
        assert ro.expiries("NBIS", monday) == ["2026-12-24", "2026-12-31", "2027-01-08", "2027-01-15", "2027-01-22"]
        assert ro.expiries("SPY", monday) == ["2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24", "2026-12-28", "2026-12-31"]
    finally:
        ro._trading = ro_trading
    assert ro.strikes("NBIS", 101.3) == [99, 100, 101, 102, 103, 104]
    assert ro.strikes("AAPL", 251.2) == [245, 247.5, 250, 252.5, 255, 257.5]
    assert ro.strikes("SOFI", 12.3) == [11.0, 11.5, 12.0, 12.5, 13.0, 13.5]


def test_the_picker_offers_only_contracts_that_traded_that_day_reading_each_once_and_nothing_after_the_clock(db, market):  # noqa: F811
    first = paper_replay.options("2026-11-13", "nbis", at(5), None, None, None, NOW)
    assert first["off"] is None and first["price"] == 102.9 and first["expiries"][:2] == ["2026-11-13", "2026-11-20"]
    assert market.reads == []  # opening the picker reads no contract
    picked = paper_replay.options("2026-11-13", "NBIS", at(5), "call", "2026-11-20", None, NOW)
    # Strikes 100–105 around 102.9, nearest first; only $100 and $101 traded that day.
    assert sorted(market.reads) == sorted(f"NBIS261120C00{s}000" for s in range(100, 106))
    assert [c["strike"] for c in picked["contracts"]] == [100, 101] and picked["missing"] == [102, 103, 104, 105]
    by = {c["strike"]: c for c in picked["contracts"]}
    # At 09:35 the $100 call's last trade is the 09:34 bar (2.35): its 09:35 and 09:40 trades are the future.
    assert by[100]["last"] == {"price": 2.35, "at": at(5)} and by[100]["label"] == "NBIS $100 Call 11/20/26"
    again = paper_replay.options("2026-11-13", "NBIS", at(5), "call", "2026-11-20", None, NOW)
    assert again["contracts"] == picked["contracts"] and len(market.reads) == 6  # kept: a past day never changes
    # At 09:33:00 the $101 call's only trade (the 09:33 bar) is still the future: not offered, no hint it trades later.
    early = paper_replay.options("2026-11-13", "NBIS", at(3), "call", "2026-11-20", 101, NOW)
    assert early["contracts"] == [] and early["missing"] == [101] and len(market.reads) == 6


def test_contract_reads_stay_within_their_budget_one_at_a_time(db, market, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ro, "PROBES_PER_MINUTE", 3)
    picked = paper_replay.options("2026-11-13", "NBIS", at(5), "call", "2026-11-20", None, NOW)
    assert len(market.reads) == 3 and len(picked["waiting"]) == 3 and "try again in a minute" in picked["waiting_reason"]
    assert set(market.reads) == {f"NBIS261120C00{s}000" for s in (102, 103, 104)}  # nearest the price first


def test_a_market_buy_pays_the_minutes_trade_plus_half_its_range_times_100_and_sells_at_the_bid(db):  # noqa: F811
    r = run(db)
    preview = paper_replay.order(db, {"run_id": str(r.id), "at": at(5), "action": "open", "symbol": "NBIS", "instrument": "option",
                                      "option_type": "call", "expiry": "2026-11-20", "strike": 100, "quantity": 2,
                                      "preview": True}, NOW)["preview"]
    # The 09:34 trade bar: close 2.35, range 2.28–2.40, so the half-spread is 0.06; the 09:35 bar (2.50) is the future.
    assert (preview["close"], preview["half_spread"], preview["half_from"], preview["ask"], preview["bar"]) == (2.35, 0.06, "range", 2.41, at(4))
    assert preview["multiplier"] == 100 and preview["cash"] == -482.0 and preview["stock"] == 102.9
    filled = buy(db, r, at(5), note="0.5 delta on the dip")
    assert filled["filled"]["cash"] == -482.0 and filled["account"]["cash"] == 9518.0
    [held] = filled["positions"]
    assert held["instrument"] == "option" and held["label"] == "NBIS $100 Call 11/20/26" and held["stock"] == 102.9
    assert held["mark"]["per_share"] == 2.35 and held["mark"]["pnl"] == -12.0  # marked at its last trade, no spread
    # Selling at 09:37 takes the 09:36 trade's close 2.60 less 0.02 (half its 2.58–2.62 range).
    sold = paper_replay.order(db, {"run_id": str(r.id), "at": at(7), "action": "close", "position_id": held["id"], "order_key": key()}, NOW)
    assert sold["filled"]["per_share"] == 2.58 and sold["filled"]["pnl"] == 34.0  # 516 − 482
    [trade] = paper_replay.scorecard(db)["trades"]
    assert trade["instrument"] == "option" and trade["label"] == "NBIS $100 Call 11/20/26" and trade["realized"] == 34.0


def test_a_minute_the_contract_did_not_trade_refuses_with_its_last_trades_time(db):  # noqa: F811
    r = run(db)
    with pytest.raises(paper_replay.ReplayError, match="No trade in NBIS \\$100 Call 11/20/26 in the 9:38 AM minute: its last trade was the 9:36 AM bar"):
        buy(db, r, at(9))
    with pytest.raises(paper_replay.ReplayError, match="yet by 9:32 AM"):
        buy(db, r, at(2))  # its first trade is the 09:32 bar, still forming


def test_an_option_limit_fills_only_on_a_minute_the_contract_traded(db):  # noqa: F811
    r = run(db)
    placed = buy(db, r, at(5), order_type="limit", limit_price=2.20)
    assert placed["working"]["reserve"] == 440.0 and placed["account"]["buying_power"] == 9560.0
    # 09:35 (low 2.45) and 09:36 (low 2.58) are too high; 09:37–09:39 had no trade; 09:40's low 2.10 plus the half-spread
    # known at its open (0.02, from the 09:36 minute's 2.58–2.62 range) reaches 2.20.
    assert step(db, r, at(10))["orders"] != []
    stepped = step(db, r, at(11))
    [filled] = stepped["happened"]
    assert (filled["kind"], filled["price"], filled["at"], filled["instrument"]) == ("limit", 2.2, at(10) + 59, "option")
    assert stepped["account"]["cash"] == 9560.0 and stepped["positions"][0]["stock"] == 100.3


def test_stop_and_target_are_stock_levels_and_the_auto_exit_sells_at_the_contracts_next_traded_minute(db):  # noqa: F811
    with pytest.raises(paper_replay.pb.PaperError, match="stock price below 102.9"):
        buy(db, run(db), at(5), stop=105.0)  # a stock level, not the premium
    r = run(db)
    buy(db, r, at(5), stop=100.0, target=110.0, auto=True)
    # The stock's 09:37 bar dips to 99.5: the stop. The contract next trades at 09:40, opening 2.25, less the half-spread
    # known at that open: 0.02 from its previous traded minute (09:36, 2.58–2.62), never 09:40's own later low.
    stepped = step(db, r, at(11))
    assert [(h["kind"], h["price"], h["at"]) for h in stepped["happened"]] == [("stop", 2.23, at(10))]
    [trade] = stepped["closed"]
    assert trade["verdict"]["kind"] == "stop" and trade["verdict"]["auto"] is True
    assert trade["realized"] == round((2.23 - 2.41) * 200, 2) == -36.0


def test_at_the_close_a_0dte_call_settles_at_intrinsic_and_a_later_expiry_sells_at_its_last_trade(db):  # noqa: F811
    r = run(db, cash=5000)
    buy(db, r, at(5), occ=ZERO, qty=1)  # 3.05 + 0.08 (half the 2.95–3.10 range, rounded up) = 3.13
    buy(db, r, at(5), qty=1)  # 2.41
    ended = step(db, r, CLOSE)
    closed = {t["label"]: t for t in ended["closed"]}
    zero = closed["NBIS $100 Call 11/13/26"]
    assert zero["status"] == "expired" and zero["exits"][0]["per_share"] == 1.5  # 101.50 − 100
    assert zero["realized"] == round(150 - 313, 2) and zero["verdict"]["text"] == "Held to expiry; settled on the 101.5 close"
    later = closed["NBIS $100 Call 11/20/26"]
    assert later["verdict"]["kind"] == "flat" and later["exits"][0]["per_share"] == 2.05  # 09:40's 2.15 less 0.10
    assert ended["positions"] == [] and ended["account"]["cash"] == round(5000 - 313 - 241 + 150 + 205, 2)
    assert {h["kind"] for h in ended["happened"]} == {"expired", "flat"}


def test_older_days_and_no_tradier_keep_options_off_with_the_reason_while_shares_still_replay(db, monkeypatch):  # noqa: F811
    later = datetime(2026, 12, 10, 17, 0, tzinfo=UTC).timestamp()
    r = run(db)
    view = paper_replay.view(db, r, at(3))
    assert view["run"]["options_off"] is None
    with pytest.raises(paper_replay.ReplayError, match="about the last 20 days"):
        buy(db, r, at(5), now=later)
    picker = paper_replay.options("2026-11-13", "NBIS", at(5), "call", "2026-11-20", None, later)
    assert "about the last 20 days" in picker["off"] and picker["contracts"] is None
    shares = paper_replay.order(db, {"run_id": str(r.id), "at": at(5), "action": "open", "symbol": "NBIS", "instrument": "stock",
                                     "quantity": 1, "order_key": key()}, later)
    assert shares["filled"]["per_share"] == -102.93  # 102.90 + 0.03 (5 bps, each half rounded up)
    monkeypatch.setattr(tradier, "tradier_configured", lambda: False)
    with pytest.raises(paper_replay.ReplayError, match="Tradier is not connected"):
        buy(db, r, at(6))
    with pytest.raises(paper_replay.ReplayError, match="spreads are not replayed"):
        paper_replay.order(db, {"run_id": str(r.id), "at": at(6), "action": "open", "symbol": "NBIS", "instrument": "spread",
                                "option_type": "call", "expiry": "2026-11-20", "long_strike": 100, "short_strike": 105,
                                "quantity": 1, "order_key": key()}, NOW)


def test_the_picker_route_is_owner_only_and_never_reaches_robinhood(db, monkeypatch):  # noqa: F811
    assert "GET /copilot/paper/replay/options" in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        got = client.get("/copilot/paper/replay/options", params={"day": "2026-11-13", "symbol": "NBIS", "at": at(5),
                                                                  "option_type": "call", "expiry": "2026-11-20"})
        assert got.status_code == 200, got.text
        assert [c["strike"] for c in got.json()["contracts"]] == [100, 101]
        bad = client.get("/copilot/paper/replay/options", params={"day": "2026-11-13", "symbol": "NBIS", "at": at(5),
                                                                  "option_type": "puts", "expiry": "2026-11-20"})
        assert bad.status_code == 400
    source = (Path(__file__).resolve().parents[1] / "app/engine/replay_options.py").read_text().lower()
    assert "robinhood_read" not in source and "import robinhood" not in source
