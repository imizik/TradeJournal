"""A closed trade replayed on the chart (app/engine/trade_replay.py): candles, VWAP, fills, pings, the cut and P&L per bar."""
from datetime import date, datetime
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import trade_replay
from app.engine.chart_math import ET
from app.models import Account, Fill, Trade, TradeFill

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
TUE, WED = date(2026, 11, 17), date(2026, 11, 18)


def ny(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2026, 11, day, hour, minute)


def epoch(hour: int, minute: int = 0, day: int = 17) -> int:
    return int(ny(hour, minute, day).replace(tzinfo=ET).timestamp())


def bar(hour: int, minute: int, close: float, day: int = 17, volume: float = 100, spread: float = 0.0) -> dict:
    """A provider minute bar at a New York (EST) time."""
    return {"t": f"2026-11-{day}T{hour + 5:02d}:{minute:02d}:00Z", "o": close, "h": close + spread, "l": close - spread,
            "c": close, "v": volume}


def minutes(start: tuple[int, int], count: int, price, day: int = 17) -> list[dict]:
    """``count`` consecutive minute bars from ``start``; ``price`` is a number or a function of the minute index."""
    out = []
    for i in range(count):
        total = start[0] * 60 + start[1] + i
        out.append(bar(total // 60, total % 60, price(i) if callable(price) else price, day))
    return out


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))
        session.commit()
        yield session
    engine.dispose()


def make_trade(db, fills, expiration=WED, status="closed", pnl=0.0, instrument="option"):
    """``fills`` are (role, side, contracts, price per contract, naive New York time)."""
    row = Trade(account_id=ROTH, ticker="NBIS", instrument_type=instrument, contracts=1,
                option_type="call" if instrument == "option" else None, strike=100 if instrument == "option" else None,
                expiration=expiration if instrument == "option" else None, opened_at=fills[0][4],
                closed_at=None if status == "open" else fills[-1][4], status=status, realized_pnl=pnl,
                avg_entry_premium=fills[0][3], total_premium_paid=fills[0][3])
    db.add(row)
    db.flush()
    for i, (role, side, qty, price, at) in enumerate(fills):
        fill = Fill(account_id=ROTH, ticker="NBIS", instrument_type=instrument, side=side, contracts=qty, price=price,
                    executed_at=at, raw_email_id=f"nbis-{row.id}-{i}", option_type=row.option_type, strike=row.strike,
                    expiration=row.expiration)
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=row.id, fill_id=fill.id, role=role))
    db.commit()
    return row


def test_an_open_trade_or_one_without_bars_says_why(db):
    def nothing(*args):
        return []
    open_trade = make_trade(db, [("entry", "buy_to_open", 1, 200, ny(10))], status="open")
    assert trade_replay.build(db, open_trade, nothing, nothing)["state"] == "open"
    closed = make_trade(db, [("entry", "buy_to_open", 1, 200, ny(10)), ("exit", "sell_to_close", 1, 250, ny(11))])
    assert trade_replay.build(db, closed, nothing, nothing)["state"] == "no_bars"


def test_a_day_trade_replays_regular_session_minutes_with_vwap_fills_and_pnl_per_bar(db):
    # Bought 2 at $2.00 at 10:00, added 1 at $1.50 at 10:30, sold 3 at $1.80 at 11:00.
    trade = make_trade(db, [("entry", "buy_to_open", 2, 200, ny(10)), ("entry", "buy_to_open", 1, 150, ny(10, 30)),
                            ("exit", "sell_to_close", 3, 180, ny(11))], pnl=-10.0)
    stock = [bar(9, 0, 50, volume=999)] + minutes((9, 30), 390, lambda i: 50 + i * 0.01) + [bar(16, 30, 60)]
    option = {(10, 0): 2.0, (10, 15): 1.6, (10, 30): 1.5, (10, 45): 1.9, (11, 0): 1.8, (12, 0): 1.0}
    body = trade_replay.build(db, trade, lambda ticker, day: stock,
                              lambda symbol, start, end: [bar(h, m, c) for (h, m), c in option.items()])
    assert body["state"] == "ok" and body["interval_minutes"] == 1 and body["contract"] == "NBIS261118C00100000"
    bars = body["bars"]
    assert len(bars) == 390 and bars[0]["time"] == epoch(9, 30) and bars[-1]["time"] == epoch(15, 59)  # pre/post left out
    # RTH VWAP on HLC3 from 9:30: equal volumes, so the mean of the closes so far.
    assert bars[0]["vwap"] == 50 and bars[2]["vwap"] == pytest.approx(50.01)
    at = {b["time"]: b for b in bars}
    assert at[epoch(9, 59)]["pnl"] is None and at[epoch(9, 59)]["held"] == 0  # before the first buy
    assert at[epoch(10)]["held"] == 2 and at[epoch(10)]["pnl"] == 0.0  # 2 x (200 - 200)
    assert at[epoch(10, 20)]["pnl"] == -80.0  # the 10:15 trade carried forward: 2 x (160 - 200)
    assert at[epoch(10, 30)]["held"] == 3 and at[epoch(10, 30)]["avg_cost"] == pytest.approx(183.3333, abs=1e-3)
    assert at[epoch(10, 30)]["pnl"] == -100.0  # 3 x 150 - 550
    assert at[epoch(10, 45)]["pnl"] == 20.0
    assert at[epoch(11)]["held"] == 0 and at[epoch(11)]["pnl"] == -10.0 and at[epoch(11)]["realized"] == -10.0
    assert at[epoch(15, 59)]["pnl"] == -10.0  # flat: the realized result holds
    assert [f["label"] for f in body["fills"]] == ["Bought 2 @ $2.00", "Bought 1 @ $1.50", "Sold 3 @ $1.80"]
    assert [f["entry"] for f in body["fills"]] == [True, True, False] and body["fills"][0]["time"] == epoch(10)
    assert [b["time"] for b in body["option_bars"]] == [epoch(h, m) for h, m in option]
    # One day to expiry, long: the cut line is 30% under the first buy and was never traded through.
    assert body["cut_line"] == {"price": 140.0, "crossed": None}
    assert body["cut"] is None and body["pings"] == [] and body["tag"] is None and body["option_note"] is None


def test_the_hold_rule_cut_and_the_cut_line_cross_are_marked(db):
    trade = make_trade(db, [("entry", "buy_to_open", 2, 200, ny(10)), ("exit", "sell_to_close", 2, 60, ny(14))], pnl=-280.0)
    stock = minutes((9, 30), 390, 50)
    option = [bar(10, 30, 1.20), bar(11, 5, 1.41), bar(11, 6, 1.30), bar(11, 7, 0.90)]
    body = trade_replay.build(db, trade, lambda *a: stock, lambda *a: option)
    assert body["cut"] == {"rule": "deep_red", "time": epoch(11, 6), "price": 130.0}  # as the leak bill prices it
    assert body["cut_line"]["price"] == 140.0
    assert body["cut_line"]["crossed"] == {"time": epoch(10, 30), "state": "ignored", "held": 2.0, "cost": 120.0}


def test_no_option_prices_leave_open_pnl_unknown_and_say_so(db):
    trade = make_trade(db, [("entry", "buy_to_open", 1, 200, ny(10)), ("exit", "sell_to_close", 1, 250, ny(11))],
                       expiration=date(2026, 12, 18), pnl=50.0)
    body = trade_replay.build(db, trade, lambda *a: minutes((9, 30), 390, 50), lambda *a: [])
    at = {b["time"]: b for b in body["bars"]}
    assert at[epoch(10, 30)]["pnl"] is None and at[epoch(11)]["pnl"] == 50.0
    assert body["option_note"] and body["cut_line"] is None and body["cut"] is None  # a month out: no cut line


def test_a_stock_trade_marks_at_the_close_and_a_multi_day_hold_draws_five_minute_candles(db):
    trade = make_trade(db, [("entry", "buy", 10, 50, ny(10)), ("exit", "sell", 10, 52, ny(10, 2, day=19))],
                       instrument="stock", pnl=20.0)
    body = trade_replay.build(db, trade, lambda ticker, day: minutes((9, 30), 390, 51, day=day.day), lambda *a: [])
    assert body["interval_minutes"] == 5 and body["multiplier"] == 1 and body["contract"] is None
    assert len(body["bars"]) == 3 * 78 and body["bars"][0]["time"] == epoch(9, 30)
    at = {b["time"]: b for b in body["bars"]}
    assert at[epoch(10)]["pnl"] == 10.0  # 10 shares x (51 - 50), the five-minute candle's last minute
    assert at[epoch(10, 0, day=19)]["pnl"] == 20.0 and at[epoch(10, 0, day=19)]["held"] == 0
    assert body["fills"][1]["label"] == "Sold 10 @ $52.00"


def test_the_pings_that_fired_are_placed_at_their_minute(db):
    from datetime import UTC
    from app.models import PositionAlert
    trade = make_trade(db, [("entry", "buy_to_open", 2, 200, ny(10)), ("exit", "sell_to_close", 2, 150, ny(11, 30))])
    fired = datetime(2026, 11, 17, 16, 0, tzinfo=UTC).replace(tzinfo=None)  # 11:00 New York, stored UTC
    for kind, delivery in (("hold_hour", "sent"), ("no_exit", "held")):
        db.add(PositionAlert(account_id=ROTH, source_key=f"nbis-{trade.id}-0", kind=kind, generation=0, trade_id=trade.id,
                             contract="NBIS 11/18/26 100C", contracts=2, avg_cost=200, detected_at=fired, delivery=delivery))
    db.commit()
    body = trade_replay.build(db, trade, lambda *a: minutes((9, 30), 390, 50), lambda *a: [])
    assert [(p["kind"], p["time"], p["sent"]) for p in body["pings"]] == [("hold_hour", epoch(11), True), ("no_exit", epoch(11), False)]
