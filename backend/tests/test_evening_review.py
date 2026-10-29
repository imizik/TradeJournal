"""The evening review ping (engine/evening_review.py): once a trading day at 16:30 New York, off by default, one ping
through the notification policy saying what the desk has waiting and opening Close the day; nothing waiting, a
weekend or a holiday sends nothing; at most once, a send that may have arrived is never resent. The counts are the
desk's own (copilot_desk.waiting). No network."""

from datetime import date, datetime

import httpx
import pytest
from sqlmodel import Session, select

from app.engine import ntfy
from app.engine.chart_math import ET
from app.engine.evening_review import EveningReviews, at_minute, message
from app.models import EveningReview, PhonePing
from app.routers import copilot_desk
from tests.test_copilot_desk import WED_CLOSE, desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import NBIS, alert, capture, engine, quotes, time_stop  # noqa: F401  (fixtures)
from tests.test_day_replay import Clock, Phone
from tests.test_today import buy, clock, marks  # noqa: F401  (fixtures)

WED, THU = date(2026, 10, 21), date(2026, 10, 22)
WAITING = {"review": 2, "alerts": 3, "radar": 0, "fills": 1}


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


class Calendar:
    """Every weekday open 9:30-16:00 but Thursday, a holiday."""

    def hours(self, day):
        return {"status": "closed"} if day.weekday() >= 5 or day == THU else {"status": "open", "open": 570, "close": 960}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for name in ("EVENING_REVIEW_PING_ENABLED", "EVENING_REVIEW_PING_AT", "ALERT_POLICY_ENABLED", "PING_DAILY_CAP",
                 "PING_QUIET_MINUTES", "PING_IMAGES_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def job(engine, clock, counts=WAITING):  # noqa: F811
    seen = []
    reviews = EveningReviews(engine, Calendar(), clock=clock, counts=lambda db, now: seen.append(now) or counts)
    reviews.seen = seen
    return reviews


def rows(engine):  # noqa: F811
    with Session(engine) as db:
        return db.exec(select(EveningReview)).all()


def test_at_1630_one_ping_says_what_waits_and_opens_close_the_day_once(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    phone = Phone(monkeypatch)
    now = Clock(at("16:29"))
    reviews = job(engine, now)
    reviews.run()
    assert rows(engine) == [] and reviews.seen == []  # not yet
    now.now = at("18:30")  # past its window: waits for the next day
    reviews._last_run = 0
    reviews.run()
    assert rows(engine) == []
    now.now = at("16:30")
    reviews._last_run = 0
    reviews.run()
    (row,) = rows(engine)
    assert (row.day, row.delivery, row.review, row.alerts, row.radar, row.fills) == (WED, "sent", 2, 3, 0, 1)
    (sent,) = phone.sent
    assert sent["title"] == "Close the day" and sent["body"] == "To review: 2 threads, 3 alerts, 1 fill to link."
    assert sent["path"] == "/copilot-lab?close=1" and sent["direct_click"] is True and sent["image"] is None
    with Session(engine) as db:
        record = db.exec(select(PhonePing).where(PhonePing.sender == "evening_review")).one()
        assert (record.decision, record.kind, record.body) == ("sent", "evening_review", sent["body"])
        assert record.delivered_at is not None
    # Later passes, and a second process, never count or ping the day again.
    for later in ("16:31", "17:45", "18:29"):
        now.now = at(later)
        reviews._last_run = 0
        reviews.run()
        reviews.deliver()
        job(engine, Clock(at(later))).run()
    assert len(rows(engine)) == 1 and len(phone.sent) == 1 and len(reviews.seen) == 1


def test_nothing_waiting_is_recorded_skipped_and_sends_nothing(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    phone = Phone(monkeypatch)
    job(engine, Clock(at("16:30")), counts={"review": 0, "alerts": 0, "radar": 0, "fills": 0}).run()
    (row,) = rows(engine)
    assert (row.delivery, row.body, row.last_error) == ("skipped", None, "Nothing was waiting for review, so nothing was sent.")
    assert phone.sent == []
    reviews = job(engine, Clock(at("17:00")))  # something arrives later: the day was already counted
    reviews.run()
    assert reviews.seen == [] and phone.sent == []


def test_off_by_default_and_no_ping_on_a_weekend_or_a_holiday(engine, monkeypatch):  # noqa: F811
    phone = Phone(monkeypatch)
    reviews = job(engine, Clock(at("16:30")))
    reviews.run()
    assert rows(engine) == [] and reviews.seen == []  # EVENING_REVIEW_PING_ENABLED unset
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    for day in (THU, date(2026, 10, 24)):  # the calendar's holiday, a Saturday
        reviews = job(engine, Clock(at("16:30", day)))
        reviews.run()
        assert reviews.seen == []
    assert rows(engine) == [] and phone.sent == []


def test_the_lab_off_is_skipped_with_why(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    phone = Phone(monkeypatch)
    job(engine, Clock(at("16:30")), counts=None).run()
    (row,) = rows(engine)
    assert row.delivery == "skipped" and "Copilot Lab is off" in row.last_error and phone.sent == []


def test_the_daily_cap_holds_it_and_it_is_recorded(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    monkeypatch.setenv("PING_DAILY_CAP", "0")
    phone = Phone(monkeypatch)
    job(engine, Clock(at("16:30"))).run()
    (row,) = rows(engine)
    assert row.delivery == "held" and "cap" in row.last_error and phone.sent == []
    with Session(engine) as db:
        assert db.exec(select(PhonePing.decision).where(PhonePing.sender == "evening_review")).one() == "over_cap"


def test_a_send_that_may_have_arrived_is_unknown_and_never_resent(engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    calls = []

    def lost(title, body, **kw):
        calls.append(title)
        raise ntfy.NtfyError("ntfy did not answer.") from httpx.ReadTimeout("timed out")
    monkeypatch.setattr(ntfy, "configured", lambda: True)
    monkeypatch.setattr(ntfy, "publish", lost)
    now = Clock(at("16:30"))
    reviews = job(engine, now)
    reviews.run()
    now.now = at("16:45")
    reviews.deliver()
    (row,) = rows(engine)
    assert row.delivery == "unknown" and "not resent" in row.last_error and len(calls) == 1


def test_the_time_is_configurable_but_never_before_the_close(monkeypatch):
    assert at_minute() == 16 * 60 + 30
    monkeypatch.setenv("EVENING_REVIEW_PING_AT", "17:15")
    assert at_minute() == 17 * 60 + 15
    for bad in ("15:30", "25:00", "evening", "17"):
        monkeypatch.setenv("EVENING_REVIEW_PING_AT", bad)
        assert at_minute() == 16 * 60 + 30
    assert message({"review": 1, "alerts": 0, "radar": 2, "fills": 2}) == "To review: 1 thread, 2 Radar hits, 2 fills to link."
    assert message({"review": 0, "alerts": 0, "radar": 0, "fills": 0}) is None


def test_the_counts_are_the_desks_own(desk, engine, clock, monkeypatch):  # noqa: F811
    """At 16:30 the desk asks its close questions (one per symbol) and has one fill to link."""
    capture(engine, "NBIS", minute=5)  # unlinked: the linker suggests it for the 10:05 fill
    time_stop(engine, NBIS, "NBIS")
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    buy(engine, 500)
    buy(engine, 700, "CRWV")  # no plan: asks "Want a plan for this?"
    clock["t"] = WED_CLOSE
    with Session(engine) as db:
        counts = copilot_desk.waiting(db, WED_CLOSE)
    body = desk.get("/copilot/desk/threads").json()
    asking = {r["symbol"] for r in body["threads"] if r["close"] and not r["close"]["reviewed"]}
    linking = {r["fill_to_link"] for r in body["threads"] if r["fill_to_link"]}
    assert counts == {"review": len(asking), "alerts": 0, "radar": 0, "fills": len(linking)}
    assert (counts["review"], counts["fills"]) == (2, 1)
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    phone = Phone(monkeypatch)
    EveningReviews(engine, Calendar(), clock=Clock(WED_CLOSE)).run()  # the real count, through the lab's switch
    (sent,) = phone.sent
    assert sent["body"] == message(counts)


def test_a_desk_source_that_cannot_be_read_is_a_skip_with_why_not_nothing_waiting(desk, engine, clock, monkeypatch):  # noqa: F811
    buy(engine, 700, "CRWV")
    clock["t"] = WED_CLOSE

    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_desk, "_positions", broken)
    with Session(engine) as db, pytest.raises(RuntimeError, match="positions"):
        copilot_desk.waiting(db, WED_CLOSE)
    monkeypatch.setenv("EVENING_REVIEW_PING_ENABLED", "true")
    phone = Phone(monkeypatch)
    EveningReviews(engine, Calendar(), clock=Clock(WED_CLOSE)).run()
    (row,) = rows(engine)
    assert row.delivery == "skipped" and row.last_error == "The desk's counts could not be read (RuntimeError), so nothing was sent."
    assert phone.sent == []


def test_alerts_count_as_close_the_day_walks_them_today_only(desk, engine, clock):  # noqa: F811
    from tests.test_copilot_desk_session import sent
    buy(engine, 500)
    with Session(engine) as db:
        sent(db, "gmail:500", "giveback", 31)  # today, no feedback: counted
        sent(db, "gmail:500", "hold_hour", 60, answer="already_aware")  # today, answered
        sent(db, "gmail:500", "expiry_final", -1200)  # yesterday, still unanswered: the Briefing's list, not the ping
        db.commit()
    clock["t"] = WED_CLOSE
    with Session(engine) as db:
        assert copilot_desk.waiting(db, WED_CLOSE)["alerts"] == 1
