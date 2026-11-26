"""The day card and the morning glance (engine/day_card.py): today's realized P&L, the cut pings acted on and what
expires the next trading day; the 9:25 list of what is held with each cut line, off by default, once a day, only on a
trading day with something held. No network."""

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlmodel import Session

from app.engine import day_card, day_journal, notification_policy
from app.engine.chart_math import ET
from app.models import Fill, PositionAlert
from app.routers.fills import _rebuild_trades
from tests.test_copilot_plans import ROTH, engine  # noqa: F401  (fixture)
from tests.test_day_replay import Clock, Phone
from tests.test_today import buy

WED, THU, FRI = date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)


class Calendar:
    """Every weekday open 9:30-16:00 but Thursday, a holiday."""

    def hours(self, day):
        return {"status": "closed"} if day.weekday() >= 5 or day == THU else {"status": "open", "open": 570, "close": 960}


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def sell(db_engine, n, buy_n, price, minute=30, symbol="NBIS"):
    with Session(db_engine) as db:
        db.add(Fill(id=UUID(int=n), account_id=ROTH, ticker=symbol, instrument_type="option", side="sell_to_close", contracts=2,
                    price=price, executed_at=datetime(2026, 10, 21, 11, minute), raw_email_id=f"gmail:{n}", option_type="call",
                    strike=100, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def test_holdings_name_the_cut_line_only_where_the_rule_applies(engine):  # noqa: F811
    buy(engine, 500)  # $3.10 on Wednesday, expiring Friday: short-dated
    buy(engine, 501, "CRWV", expiration=date(2026, 11, 20))  # a month out: no cut line
    with Session(engine) as db:
        held = day_card.holdings(db)
    assert [(h["contract"], h["contracts"], h["expiration"], h["cut"]) for h in held] == [
        ("NBIS 10/23/26 100C", 2, FRI, 217.0), ("CRWV 11/20/26 100C", 2, date(2026, 11, 20), None)]
    assert day_card.glance_lines(held, WED) == ("You hold 2", "NBIS 10/23/26 100C ×2 · expires Fri · cut $2.17\n"
                                                              "CRWV 11/20/26 100C ×2 · expires Nov 20")
    assert day_card.glance_lines([], WED) is None


def test_the_card_says_the_close_the_cut_pings_and_what_expires_next_session(engine):  # noqa: F811
    buy(engine, 500)
    buy(engine, 502, "APLD")
    sell(engine, 503, 502, 250, symbol="APLD")  # APLD closed today: 2 x ($2.50 - $3.10) = -$120
    with Session(engine) as db:
        nbis = next(h for h in day_card.holdings(db) if h["contract"].startswith("NBIS"))
        for kind, minute in (("hold_hour", 40), ("same_day_1pm", 50), ("giveback", 45)):  # the give-back is not a cut ping
            db.add(PositionAlert(account_id=ROTH, source_key=f"gmail:{kind}", kind=kind, generation=0, trade_id=nbis["trade_id"],
                                 contract="NBIS 10/23/26 100C", contracts=2, avg_cost=310, delivery="sent",
                                 detected_at=datetime(2026, 10, 21, 14, minute)))
        db.commit()
        entry = day_journal.append(db, day=WED, operation_id="cut", kind="decision", text="Exiting. tapped Cut it on the phone.",
                                   symbol="NBIS")
        entry.created_at = datetime(2026, 10, 21, 15, 0)  # 11:00 New York, after both pings
        db.commit()
        card = day_card.card(db, at("16:30"), Calendar())
    assert (card["pnl"], card["closed"]) == (-120.0, 1)
    assert card["cut"] == {"pings": 2, "acted": 2}  # an Exiting decision after each counts, as the leak bill reads it
    assert card["next_day"] == "2026-10-23"  # Thursday is a holiday
    assert card["expiring"] == [{"contract": "NBIS 10/23/26 100C", "contracts": 2, "cut": 217.0}]
    assert day_card.card_lines(card) == ("Today -$120", "1 trade closed, -$120 realized.\nCut pings: acted on 2 of 2.\n"
                                                         "Expires tomorrow: NBIS 10/23/26 100C ×2, cut $2.17.")


def test_a_quiet_day_has_no_card(engine):  # noqa: F811
    with Session(engine) as db:
        card = day_card.card(db, at("16:30"), Calendar())
    assert card["cut"] == {"pings": 0, "acted": 0} and card["expiring"] == [] and card["closed"] == 0
    assert day_card.card_lines(card) is None


def test_the_morning_glance_is_off_by_default_once_a_day_and_only_while_something_is_held(engine, monkeypatch):  # noqa: F811
    monkeypatch.delenv("MORNING_GLANCE_PINGS", raising=False)
    assert not day_card.glance_enabled()
    monkeypatch.setenv("MORNING_GLANCE_PINGS", "true")
    assert day_card.glance_enabled()
    phone = Phone(monkeypatch)
    now = Clock(at("09:24"))
    glance = day_card.MorningGlance(engine, Calendar(), clock=now)
    assert not glance.due(now())
    now.now = at("09:25")
    assert glance.due(now())
    assert glance.run() == "nothing: no option held" and phone.sent == []
    assert not glance.due(now())  # the day is handled here
    buy(engine, 500)
    fresh = day_card.MorningGlance(engine, Calendar(), clock=Clock(at("09:26")))
    assert fresh.run() == "sent"
    (sent,) = phone.sent
    assert (sent["title"], sent["body"]) == ("You hold 1", "NBIS 10/23/26 100C ×2 · expires Fri · cut $2.17")
    assert sent["path"] == "/copilot-lab" and sent["priority"] <= 2  # silent: a reminder, not a risk
    # A second process (a restart) never sends the day again; the holiday and a later minute are not due.
    assert day_card.MorningGlance(engine, Calendar(), clock=Clock(at("09:30"))).run().startswith("held")
    assert not day_card.MorningGlance(engine, Calendar(), clock=Clock(at("09:25", THU))).due(at("09:25", THU))
    assert not day_card.MorningGlance(engine, Calendar(), clock=Clock(at("09:55"))).due(at("09:55"))
    assert len(phone.sent) == 1
    assert notification_policy.NEVER_HELD.count("morning_glance") == 1
    assert timedelta(minutes=day_card.WINDOW_MINUTES) == timedelta(minutes=30)
