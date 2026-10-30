"""The notification policy for the app's own phone pings (docs/copilot-lab.md § Phone ping policy): the daily cap with
its priority order, the per-position quiet window (merge or suppress), the flag, the New York day, the fail-open gate;
each copilot-side sender adopting it; and what the owner did after each ping, read from the fills and plan links."""

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot_review
from app.database import get_session
from app.engine import notification_policy as policy
from app.engine import ntfy, plan_time_stops, premarket_prep, reconstructor, research_queue
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor, create_alert
from app.engine.plan_nudges import PlanNudges
from app.engine.plan_time_stops import PlanTimeStops
from app.engine.position_alerts import PositionAlerts
from app.engine.premarket_prep import PremarketPreps
from app.models import (Account, CaptureLink, Fill, LevelAlertEvent, PhonePing, PlanNudge, PlanTimeStop, PositionAlert,
                        PremarketPrep, Trade, TradeFill)
from app.routers import position_alerts as position_alerts_router
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
INV = "44444444-4444-4444-8444-444444444444"
n = iter(range(100, 10_000))


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    for name in ("ALERT_POLICY_ENABLED", "PING_DAILY_CAP", "PING_QUIET_MINUTES", "PLAN_NUDGE_DAILY_CAP", "PING_PREOPEN_ALLOWANCE",
                 *(f"PING_BUDGET_{kind.upper()}" for kind in policy.BUDGETS)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "false")
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def phone(monkeypatch):
    sent = []
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    return sent


def decide(db, kind, source, *, anchor="pos-1", now=None, sender="test", title=None, body="body"):
    return policy.decide(db, sender=sender, source_id=source, kind=kind, title=title or f"{kind} {source}", body=body,
                         now=at("10:00") if now is None else now, anchor=anchor, symbol="SNDK")


def rows(engine):
    with Session(engine) as db:
        return db.exec(select(PhonePing).order_by(PhonePing.decided_at)).all()


def buy(engine, when="10:00", ticker="SNDK", qty=2, strike=230):
    i = next(n)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=ROTH, ticker=ticker, instrument_type="option", side="buy_to_open", contracts=qty, price=310,
                    executed_at=datetime.combine(WED, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{i}",
                    option_type="call", strike=strike, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        trade = db.exec(select(Trade).join(TradeFill, TradeFill.trade_id == Trade.id).where(TradeFill.fill_id == UUID(int=i))).one()
        return trade.id, policy.anchor(ROTH, f"gmail:{i}")


def sell(engine, when, qty=2, ticker="SNDK", strike=230):
    i = next(n)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=ROTH, ticker=ticker, instrument_type="option", side="sell_to_close", contracts=qty, price=350,
                    executed_at=datetime.combine(WED, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{i}",
                    option_type="call", strike=strike, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


# ------------------------------------------------------------------ the gate

def test_the_priority_order_and_what_the_cap_never_drops():
    assert [policy.rank(k) for k in ("expiry_final", "invalidation", "giveback", "time_stop", "entry", "hold_hour", "nudge", "prep",
                                     "evening_review", "radar_event", "radar_digest", "thesis_watch", "research")] == list(range(13))
    assert policy.rank("expiry_first") == policy.rank("expiry_eve") == policy.rank("time_stop") and policy.rank("link") == policy.rank("nudge")
    assert policy.rank("week_review") == policy.rank("day_replay") == policy.rank("prep")
    assert policy.rank("radar_something") == 13  # an unknown kind goes last
    assert policy.enabled() and policy.daily_cap() == 12 and policy.quiet_seconds() == 600 and policy.preopen_allowance() == 2
    assert {k: policy.budget(k) for k in policy.BUDGETS} == {"nudge": 2, "prep": 1, "radar_event": 4, "radar_digest": 2,
                                                             "thesis_watch": 2, "research": 1}
    assert (policy.budget("link"), policy.budget("week_review"), policy.budget("hold_hour"), policy.budget("evening_review")) == (2, 1, None, None)


def test_each_low_kind_spends_only_its_own_budget_and_the_ceiling_holds_the_rest(engine):
    with Session(engine) as db:
        for i in range(4):
            assert decide(db, "radar_event", f"r{i}", anchor=f"sym-{i}").action == "send"
        held = decide(db, "radar_event", "r4", anchor="sym-4")
        assert held.action == "hold" and held.reason == "Not sent: Radar's 4 single pings for today are spent."
        # Radar's singles being spent takes nothing from the digest, the nudges or research.
        assert decide(db, "radar_digest", "d1", anchor=None).action == "send"
        assert decide(db, "nudge", "n1", anchor="p-n1").action == "send"
        assert decide(db, "link", "l1", anchor="p-l1").action == "send"  # a link ping shares the nudges' budget
        assert decide(db, "nudge", "n2", anchor="p-n2").reason == "Not sent: Plan nudges' 2 pings for today are spent."
        assert decide(db, "prep", "prep1", anchor=None).action == "send"
        assert decide(db, "week_review", "w1", anchor=None).reason == "Not sent: The prep and review pings' 1 ping for today is spent."
        assert decide(db, "research", "q1", anchor=None).action == "send"
        assert decide(db, "research", "q2", anchor=None).reason == "Not sent: Research's 1 ping for today is spent."
        for i in range(3):  # 9 sent; the ceiling of 12 holds the time stop and one-hour alerts too
            assert decide(db, "hold_hour", f"h{i}", anchor=f"p{i}").action == "send"
        assert decide(db, "radar_digest", "d2", anchor=None).reason == "Not sent: 12 pings already went out today (cap 12)."
        assert decide(db, "time_stop", "t1", anchor="p-t1").action == "hold"
        assert decide(db, "expiry_eve", "e1", anchor="p-e1").action == "hold"
        for kind in ("giveback", "invalidation", "expiry_final", "evening_review"):  # never over the ceiling
            assert decide(db, kind, f"top-{kind}", anchor=f"p-{kind}" if kind != "evening_review" else None).action == "send"
    decisions = [(r.kind, r.decision) for r in rows(engine)]
    assert decisions.count(("radar_event", "sent")) == 4 and ("evening_review", "sent") in decisions
    assert sum(d == "sent" for _, d in decisions) == 16 and sum(d == "over_cap" for _, d in decisions) == 7


def test_before_the_open_the_budgeted_kinds_share_the_pre_open_allowance(engine, monkeypatch):
    with Session(engine) as db:
        assert decide(db, "prep", "prep1", anchor=None, now=at("08:30")).action == "send"
        assert decide(db, "thesis_watch", "t1", anchor="symbol:NBIS", now=at("08:50")).action == "send"
        held = decide(db, "thesis_watch", "t2", anchor="symbol:SNDK", now=at("09:10"))
        assert held.action == "hold" and "the 2 pre-open pings" in held.reason and "before 9:30 AM New York" in held.reason
        assert decide(db, "hold_hour", "h1", anchor="p1", now=at("09:20")).action == "send"  # not a budgeted kind
        # At the open the kind's own budget is what is left: thesis watch has its second ping.
        assert decide(db, "thesis_watch", "t3", anchor="symbol:SNDK", now=at("09:31")).action == "send"
        assert decide(db, "thesis_watch", "t4", anchor="symbol:AMD", now=at("09:40")).reason == (
            "Not sent: Thesis watch's 2 pings for today are spent.")
    monkeypatch.setenv("PING_PREOPEN_ALLOWANCE", "0")
    monkeypatch.setenv("PING_BUDGET_RESEARCH", "3")
    assert policy.preopen_allowance() == 0 and policy.budget("research") == 3
    with Session(engine) as db:
        assert decide(db, "research", "q1", anchor=None, now=at("09:00")).action == "hold"
        assert decide(db, "research", "q2", anchor=None, now=at("10:00")).action == "send"


def test_october_29_pre_open_pings_no_longer_hold_radar_or_the_evening_review(engine):
    """Oct 29, 2026: nine pings by 09:50 (prep, thesis watch on pre-open headlines, research, nudges) spent the shared
    pool, and every Radar ping and the 16:30 evening review were held."""
    morning = [("prep", "08:30"), ("thesis_watch", "08:41"), ("thesis_watch", "08:55"), ("thesis_watch", "09:05"),
               ("thesis_watch", "09:12"), ("research", "09:20"), ("research", "09:34"), ("nudge", "09:41"), ("nudge", "09:49")]
    with Session(engine) as db:
        for i, (kind, hhmm) in enumerate(morning):
            decide(db, kind, f"m{i}", anchor=f"symbol:S{i}", now=at(hhmm))
        digest = decide(db, "radar_digest", "digest-1000", anchor=None, now=at("10:00"))
        single = decide(db, "radar_event", "r1", anchor="symbol:LAD", now=at("10:12"))
        second = decide(db, "radar_digest", "digest-1400", anchor=None, now=at("14:00"))
        evening = decide(db, "evening_review", "ev", anchor=None, now=at("16:30"))
        assert (digest.action, single.action, second.action, evening.action) == ("send", "send", "send", "send")
        assert policy.held_text(db, at("16:30")) == "4 pings held today (thesis watch 3, research 1)"
    morning_sent = [r.kind for r in rows(engine) if r.decision == "sent" and r.decided_at < utc(at("09:50"))]
    assert morning_sent == ["prep", "thesis_watch", "research", "nudge", "nudge"]


def test_the_quiet_window_merges_an_undelivered_different_kind_and_suppresses_the_rest(engine):
    with Session(engine) as db:
        first = decide(db, "giveback", "g1", now=at("10:00"), title="SNDK: give-back triggered", body="Peak +$120, now +$10.")
        assert first.action == "send" and first.append == ""
        # Its send failed and is retrying; a one-hour alert for the same position rides with it.
        merged = decide(db, "hold_hour", "h1", now=at("10:04"), title="SNDK: open an hour", body="Re-decide.")
        assert merged.action == "merge" and "Merged into the give-back ping 4 min earlier" in merged.reason
        retry = decide(db, "giveback", "g1", now=at("10:05"))
        assert retry.action == "send" and retry.append == "\n\nAlso: SNDK: open an hour. Re-decide."
        assert decide(db, "hold_hour", "h1", now=at("10:05")).action == "merge"  # the merged one stays merged
        policy.delivered(db, retry, at("10:05"))
        db.commit()
        # Delivered: a time stop 2 minutes later is suppressed, not merged; so is another give-back.
        stop = decide(db, "time_stop", "t1", now=at("10:07"))
        assert stop.action == "hold" and "a give-back ping went out 7 min earlier for the same position (quiet window 10 min)" in stop.reason
        assert decide(db, "giveback", "g2", now=at("10:08")).action == "hold"
        assert decide(db, "hold_hour", "other", anchor="pos-2", now=at("10:08")).action == "send"  # another position
        assert decide(db, "time_stop", "t2", now=at("10:11")).action == "send"  # the window has passed
    by_source = {r.source_id: r for r in rows(engine)}
    assert by_source["h1"].decision == "merged" and by_source["h1"].merged_into == by_source["g1"].id
    assert by_source["t1"].decision == "suppressed" and by_source["g1"].delivered_at is not None


def test_a_more_important_ping_is_never_held_by_the_quiet_window(engine):
    with Session(engine) as db:
        hold = decide(db, "hold_hour", "h1", now=at("15:00"))
        policy.delivered(db, hold, at("15:00"))
        db.commit()
        assert decide(db, "giveback", "g1", now=at("15:02")).action == "send"
        assert decide(db, "expiry_final", "f1", now=at("15:31")).action == "send"  # after a give-back 29 min earlier
        final = decide(db, "expiry_final", "f1", now=at("15:31"))
        policy.delivered(db, final, at("15:31"))
        db.commit()
        # A last-day final or an invalidation is never held by the window: a second plan's invalidation in the same
        # symbol is its own message (each sender already writes one row per firing).
        broke = decide(db, "invalidation", "i1", now=at("15:33"))
        assert broke.action == "send"
        policy.delivered(db, broke, at("15:33"))
        db.commit()
        assert decide(db, "invalidation", "i2", now=at("15:34")).action == "send"
        again = decide(db, "expiry_final", "f2", now=at("15:35"))
        assert again.action == "send"
        policy.delivered(db, again, at("15:35"))
        db.commit()
        assert decide(db, "giveback", "g2", now=at("15:36")).action == "hold"  # less important than the final just sent


def test_the_flag_off_passes_everything_through_but_still_records(engine, monkeypatch):
    monkeypatch.setenv("ALERT_POLICY_ENABLED", "false")
    with Session(engine) as db:
        for i in range(20):
            assert decide(db, "nudge", f"n{i}", now=at("10:00") + i).action == "send"
    kept = rows(engine)
    assert len(kept) == 20 and {r.decision for r in kept} == {"sent"} and "passed through" in kept[0].reason
    monkeypatch.setenv("ALERT_POLICY_ENABLED", "TRUE")
    assert policy.enabled()


def test_the_cap_counts_a_new_york_day_not_a_utc_one(engine):
    with Session(engine) as db:
        for i in range(12):  # 19:00 New York is 23:00 UTC
            assert decide(db, "hold_hour", f"h{i}", anchor=f"p{i}", now=at("19:00") + i).action == "send"
        assert decide(db, "hold_hour", "late", anchor="p-late", now=at("20:30")).action == "hold"  # 00:30 UTC: still Wednesday in New York
        assert decide(db, "hold_hour", "next", anchor="p-next", now=at("00:05", date(2026, 10, 22))).action == "send"
    start, end = policy.day_bounds(at("20:30"))
    assert (start, end) == (utc(at("00:00")), utc(at("00:00", date(2026, 10, 22))))


def test_settings_are_read_from_the_environment(engine, monkeypatch):
    monkeypatch.setenv("PING_DAILY_CAP", "2")
    monkeypatch.setenv("PING_QUIET_MINUTES", "1")
    monkeypatch.setenv("PING_BUDGET_NUDGE", "0")
    assert policy.daily_cap() == 2 and policy.quiet_seconds() == 60 and policy.budget("nudge") == 0
    with Session(engine) as db:
        assert decide(db, "nudge", "n1", now=at("10:00")).reason == "Not sent: Plan nudges' 0 pings for today are spent."
        assert decide(db, "hold_hour", "h1", anchor="p1", now=at("10:00")).action == "send"
        assert decide(db, "hold_hour", "h2", anchor="p2", now=at("10:00")).action == "send"
        assert decide(db, "hold_hour", "h3", anchor="p3", now=at("10:00")).action == "hold"
        assert decide(db, "giveback", "g1", anchor="p1", now=at("10:00") + 30).action == "send"  # more important than the one-hour alert
        assert decide(db, "giveback", "g2", anchor="p1", now=at("10:00") + 45).action == "hold"  # its duplicate, 15 s later
        assert decide(db, "giveback", "g3", anchor="p1", now=at("10:02")).action == "send"  # the 1-minute window has passed
    monkeypatch.setenv("PING_DAILY_CAP", "lots")
    monkeypatch.setenv("PING_BUDGET_NUDGE", "some")
    assert policy.daily_cap() == 12 and policy.budget("nudge") == 2


def test_a_broken_policy_table_sends_the_ping_unjudged(engine):
    with Session(engine) as db:
        db.exec(text("DROP TABLE phone_ping"))
        db.commit()
        ticket = decide(db, "nudge", "n1")
        assert ticket.action == "send" and ticket.id is None and "could not be read" in ticket.reason
        policy.delivered(db, ticket, at("10:00"))  # nothing to record, nothing raised
        assert db.get(Account, ROTH) is not None  # the session is still usable
        assert policy.held_back_today(db, at("10:00")) == {"count": 0, "by_kind": {}}


# ------------------------------------------------------------------ the senders

def position_alert(engine, kind, when="10:00", source_key="gmail:1", generation=1):
    with Session(engine) as db:
        row = PositionAlert(account_id=ROTH, source_key=source_key, kind=kind, generation=generation, trade_id=uuid4(),
                            contract="SNDK 10/23/26 230C", contracts=2, avg_cost=310, mark=320, bid=318, gain=20, gain_pct=0.0323,
                            peak_gain=124, peak_gain_pct=0.2, detected_at=utc(at(when)))
        db.add(row)
        db.commit()
        return row.id


def test_position_alerts_hold_a_one_hour_alert_over_the_cap_and_never_a_give_back(engine, phone, monkeypatch):
    monkeypatch.setenv("PING_DAILY_CAP", "0")
    clock = Clock(at("10:01"))
    watcher = PositionAlerts(engine, Calendar(), clock=clock, quotes=lambda symbols: {})
    hold = position_alert(engine, "hold_hour")
    give = position_alert(engine, "giveback", when="10:00")
    watcher.deliver()
    with Session(engine) as db:
        held, sent = db.get(PositionAlert, hold), db.get(PositionAlert, give)
        assert held.delivery == "held" and "cap 0" in held.last_error and held.attempts == 0
        assert sent.delivery == "sent" and sent.delivered_at is not None
        pings = {p.source_id: p for p in db.exec(select(PhonePing)).all()}
        assert pings[str(hold)].decision == "over_cap" and pings[str(give)].decision == "sent"
        assert pings[str(give)].anchor == f"{ROTH}:gmail:1" and pings[str(give)].delivered_at is not None
        assert pings[str(give)].sender == "position_alerts" and pings[str(give)].symbol == "SNDK"
    assert [title for title, _, _ in phone] == ["SNDK 10/23/26 230C: give-back triggered"]


def test_a_failed_send_keeps_its_decision_and_carries_a_merged_ping_on_the_retry(engine, monkeypatch):
    calls = []

    def publish(title, body, **kw):
        calls.append((title, body))
        if len(calls) == 1:
            raise ntfy.NtfyError("ntfy refused the notification (503).")  # surely unsent: retried with a backoff

    monkeypatch.setattr(ntfy, "publish", publish)
    clock = Clock(at("10:01"))
    watcher = PositionAlerts(engine, Calendar(), clock=clock, quotes=lambda symbols: {})
    give = position_alert(engine, "giveback", when="10:00")
    watcher.deliver()
    hold = position_alert(engine, "hold_hour", when="10:01")
    clock.now = at("10:01") + 10
    watcher.deliver()  # the give-back waits on its 30-second backoff; the one-hour alert merges into it
    with Session(engine) as db:
        assert db.get(PositionAlert, give).delivery == "pending" and db.get(PositionAlert, hold).delivery == "held"
        assert "Merged into the give-back ping" in db.get(PositionAlert, hold).last_error
    clock.now = at("10:03")
    watcher.deliver()
    assert len(calls) == 2 and calls[1][0] == "SNDK 10/23/26 230C: give-back triggered"
    assert "\n\nAlso: SNDK 10/23/26 230C: open an hour, re-decide. Open 60 min" in calls[1][1]
    with Session(engine) as db:
        assert db.get(PositionAlert, give).delivery == "sent"
        assert [p.decision for p in db.exec(select(PhonePing).order_by(PhonePing.decided_at)).all()] == ["sent", "merged"]


def test_plan_nudges_and_link_pings_ride_the_same_policy(engine, phone, monkeypatch):
    trade_id, anchor = buy(engine, "09:50")
    clock = Clock(at("09:54"))
    nudges = PlanNudges(engine, Calendar(), clock=clock)
    with Session(engine) as db:
        key = anchor.split(":", 1)[1]
        db.add(PlanNudge(account_id=ROTH, source_key=key, trade_id=trade_id, ticker="SNDK", contract="SNDK 10/23/26 230C",
                         side="buy_to_open", contracts=2, price=310, opened_at=datetime.combine(WED, datetime.strptime("09:50", "%H:%M").time()),
                         detected_at=utc(at("09:53"))))
        db.commit()
    nudges.deliver()
    with Session(engine) as db:
        nudge = db.exec(select(PlanNudge)).one()
        ping = db.exec(select(PhonePing)).one()
        assert nudge.delivery == "sent" and ping.kind == "nudge" and ping.anchor == anchor and ping.sender == "plan_nudges"
        assert ping.trade_id == trade_id and ping.delivered_at is not None
    assert phone[0][0] == "SNDK 10/23 230C: no plan yet"
    # Over the cap: held with the reason, the nudge's own daily cap untouched.
    monkeypatch.setenv("PING_DAILY_CAP", "1")
    with Session(engine) as db:
        db.add(PlanNudge(account_id=ROTH, source_key="gmail:other", trade_id=trade_id, ticker="SNDK", contract="SNDK 10/23/26 230C",
                         side="buy_to_open", contracts=2, price=310, opened_at=datetime.combine(WED, datetime.strptime("09:50", "%H:%M").time()),
                         detected_at=utc(at("09:53"))))
        db.commit()
    nudges.deliver()
    with Session(engine) as db:
        held = db.exec(select(PlanNudge).where(PlanNudge.source_key == "gmail:other")).one()
        assert held.delivery == "held" and held.last_error == "Not sent: 1 ping already went out today (cap 1)."
    assert len(phone) == 1


def test_a_time_stop_and_a_plan_invalidation_share_the_position_anchor(engine, phone):
    trade_id, anchor = buy(engine, "10:05")
    clock = Clock(at("15:30"))
    stops = PlanTimeStops(engine, Calendar(), clock=clock)
    with Session(engine) as db:
        first = plan_time_stops.create(db, client_id="card-1", investigation_id=INV, symbol="SNDK", text="out by 15:30", now=at("10:00"),
                                       calendar=Calendar()).id
        second = plan_time_stops.create(db, client_id="card-2", investigation_id=INV, symbol="SNDK", text="out by 15:34", now=at("10:00"),
                                        calendar=Calendar()).id
    stops.run()
    stops.deliver()
    with Session(engine) as db:
        ping = db.exec(select(PhonePing)).one()
        assert ping.sender == "plan_time_stops" and ping.kind == "time_stop" and ping.anchor == anchor and ping.trade_id == trade_id
        assert db.get(PlanTimeStop, first).delivery == "sent"
    # The plan's invalidation breaks 2 minutes later: more important, it goes out and shares the anchor.
    with Session(engine) as db:
        alert_id = create_alert(db, symbol="SNDK", price=92.3, reference=94.0, condition="crosses", interval=None, session="regular",
                                source_kind="copilot", source_id=INV, label="SNDK invalidation", now=at("10:00"), plan_role="invalidation").id
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("15:32"))
    monitor.reload()
    monitor.record([monitor._event(monitor._watched[alert_id], 92.27, at("15:32") - 30, "stream", None)])
    monitor.deliver()
    with Session(engine) as db:
        event = db.exec(select(LevelAlertEvent)).one()
        ping = db.exec(select(PhonePing).where(PhonePing.sender == "level_alerts")).one()
        assert event.delivery == "sent" and ping.kind == "invalidation" and ping.anchor == anchor and ping.source_id == str(event.id)
    # The second time stop, 4 minutes after the first for the same position, is suppressed.
    clock.now = at("15:34")
    stops.run()
    stops.deliver()
    with Session(engine) as db:
        held = db.get(PlanTimeStop, second)
        assert held.delivery == "held" and "a time stop ping went out 4 min earlier for the same position" in held.last_error
    assert [t for t, _, _ in phone] == ["SNDK time stop", "SNDK invalidation broke"]


def test_an_entry_trigger_without_a_position_is_anchored_to_the_symbol(engine, phone):
    with Session(engine) as db:
        alert_id = create_alert(db, symbol="NBIS", price=95.9, reference=94.0, condition="crosses", interval=None, session="regular",
                                source_kind="copilot", source_id=INV, label="NBIS entry", now=at("10:00"), plan_role="entry").id
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("10:42"))
    monitor.reload()
    monitor.record([monitor._event(monitor._watched[alert_id], 95.93, at("10:41"), "stream", None)])
    monitor.deliver()
    with Session(engine) as db:
        ping = db.exec(select(PhonePing)).one()
        assert (ping.kind, ping.anchor, ping.trade_id, ping.symbol) == ("entry", "symbol:NBIS", None, "NBIS")
    assert phone[0][0] == "NBIS entry trigger hit"


def test_a_held_plan_ping_is_recorded_on_the_event_and_not_retried(engine, phone, monkeypatch):
    monkeypatch.setenv("PING_DAILY_CAP", "0")
    with Session(engine) as db:
        alert_id = create_alert(db, symbol="NBIS", price=95.9, reference=94.0, condition="crosses", interval=None, session="regular",
                                source_kind="copilot", source_id=INV, label="NBIS entry", now=at("10:00"), plan_role="entry").id
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("10:42"))
    monitor.reload()
    monitor.record([monitor._event(monitor._watched[alert_id], 95.93, at("10:41"), "stream", None)])
    monitor.deliver()
    monitor.deliver()
    with Session(engine) as db:
        event = db.exec(select(LevelAlertEvent)).one()
        assert event.delivery == "held" and "cap 0" in event.last_error and event.attempts == 0
    assert phone == []


def test_pre_market_prep_and_research_are_held_before_position_pings(engine, phone, monkeypatch):
    monkeypatch.setenv("PING_PREOPEN_ALLOWANCE", "0")  # nothing budgeted goes out before the open
    clock = Clock(at("08:31"))
    monkeypatch.setattr(research_queue, "time", SimpleNamespace(time=clock))
    preps = PremarketPreps(engine, Calendar(), clock=clock, spawn=lambda work: None)
    with Session(engine) as db:
        db.add(PremarketPrep(day=WED, detected_at=utc(at("08:30")), body="Line one\nLine two", delivery="pending"))
        db.commit()
    preps.deliver()
    with Session(engine) as db:
        prep = db.exec(select(PremarketPrep)).one()
        assert prep.delivery == "held" and "pre-open pings" in prep.last_error
        ticket = research_queue.gate("job-1", {"title": "Research: NBIS – guidance cut", "message": "Summary.", "path": "/copilot-lab"}, session=db)
        assert ticket.held and "pre-open pings" in ticket.reason
        assert decide(db, "hold_hour", "h1", anchor="p1").action == "send"
        assert policy.held_back_today(db, at("09:00")) == {"count": 2, "by_kind": {"pre-market prep": 1, "research": 1}}
    assert phone == []
    monkeypatch.delenv("PING_PREOPEN_ALLOWANCE")
    with Session(engine) as db:
        db.add(PremarketPrep(day=date(2026, 10, 22), detected_at=utc(at("08:30")), body="Line one\nLine two", delivery="pending"))
        db.commit()
    preps.deliver()
    with Session(engine) as db:
        assert [p.delivery for p in db.exec(select(PremarketPrep).order_by(PremarketPrep.day)).all()] == ["held", "sent"]
        ping = db.exec(select(PhonePing).where(PhonePing.sender == "premarket_prep", PhonePing.decision == "sent")).one()
        assert ping.kind == "prep" and ping.delivered_at is not None
    assert phone[0][:2] == (premarket_prep.TITLE, "Line one\nLine two")


def test_the_monitor_runs_the_follow_up_pass_last(engine):
    ran = []
    monitor = LevelAlertMonitor(engine, None, clock=lambda: at("10:00"), follow_ups=type("F", (), {"run": lambda self: ran.append(1)})())
    asyncio.run(monitor.run_once())
    assert ran == [1]


# ------------------------------------------------------------------ acted on

def ping(engine, kind, *, delivered, anchor=None, symbol="SNDK", source=None, sender="test", decision="sent"):
    with Session(engine) as db:
        row = PhonePing(sender=sender, source_id=source or f"{kind}-{next(n)}", kind=kind, rank=policy.rank(kind), symbol=symbol, anchor=anchor,
                        decision=decision, title=kind, body="body", decided_at=utc(at(delivered)),
                        delivered_at=utc(at(delivered)) if decision == "sent" else None)
        db.add(row)
        db.commit()
        return row.id


def judged(engine, ping_id):
    with Session(engine) as db:
        row = db.get(PhonePing, ping_id)
        return row.then, row.then_minutes, policy.then_text(row.then, row.then_minutes)


def test_an_exit_ping_is_answered_by_the_fills_closed_trimmed_or_held(engine):
    _, closed_anchor = buy(engine, "10:00")
    _, trimmed_anchor = buy(engine, "10:00", strike=240)
    _, held_anchor = buy(engine, "11:00", strike=250)
    closed = ping(engine, "giveback", delivered="10:30", anchor=closed_anchor)
    trimmed = ping(engine, "time_stop", delivered="10:30", anchor=trimmed_anchor)
    held = ping(engine, "invalidation", delivered="11:10", anchor=held_anchor)
    clock = Clock(at("10:37"))
    follow = policy.FollowUps(engine, clock=clock)
    sell(engine, "10:36")  # the whole first position
    sell(engine, "10:36", qty=1, strike=240)  # half of the second
    follow.run()
    assert judged(engine, closed) == ("closed", 6, "closed in 6 min")
    assert judged(engine, trimmed) == (None, None, None)  # more could still be sold inside the 15 minutes
    assert judged(engine, held) == (None, None, None)
    clock.now = at("10:46")
    follow.run()
    assert judged(engine, trimmed) == ("trimmed", 6, "trimmed in 6 min")
    clock.now = at("11:26")
    follow.run()
    assert judged(engine, held) == ("held", None, "still held 15 min later")
    with Session(engine) as db:
        assert all(p.judged_at == utc(clock.now) for p in db.exec(select(PhonePing).where(PhonePing.kind == "invalidation")).all())


def test_an_entry_trigger_is_answered_by_an_entry_fill_in_the_symbol(engine):
    entered = ping(engine, "entry", delivered="10:00", anchor="symbol:SNDK", symbol="SNDK")
    nothing = ping(engine, "entry", delivered="10:00", anchor="symbol:CRWV", symbol="CRWV")
    clock = Clock(at("10:13"))
    follow = policy.FollowUps(engine, clock=clock)
    buy(engine, "10:12")
    follow.run()
    assert judged(engine, entered) == ("entered", 12, "entered in 12 min")
    assert judged(engine, nothing) == (None, None, None)
    clock.now = at("10:31")
    follow.run()
    assert judged(engine, nothing) == ("no_entry", None, "no entry within 30 min")


def test_a_nudge_is_answered_by_a_plan_link(engine):
    _, anchor = buy(engine, "10:00")
    _, other = buy(engine, "10:00", strike=240)
    linked = ping(engine, "nudge", delivered="10:05", anchor=anchor)
    unlinked = ping(engine, "link", delivered="10:05", anchor=other)
    clock = Clock(at("10:12"))
    follow = policy.FollowUps(engine, clock=clock)
    with Session(engine) as db:
        db.add(CaptureLink(capture_id=uuid4(), account_id=ROTH, source_key=anchor.split(":", 1)[1], method="suggested", linked_at=utc(at("10:11"))))
        db.commit()
    follow.run()
    assert judged(engine, linked) == ("linked", 6, "plan linked in 6 min")
    assert judged(engine, unlinked) == (None, None, None)
    clock.now = at("10:36")
    follow.run()
    assert judged(engine, unlinked) == ("not_linked", None, "no plan linked within 30 min")


def test_pings_that_cannot_be_answered_are_marked_unmatched_once(engine):
    orphan = ping(engine, "giveback", delivered="10:00", anchor=f"{ROTH}:gmail:nobody")
    unsent = ping(engine, "giveback", delivered="10:00", anchor=f"{ROTH}:gmail:nobody", decision="over_cap")
    foreign = ping(engine, "prep", delivered="10:00")
    follow = policy.FollowUps(engine, clock=Clock(at("10:20")))
    follow.run()
    assert judged(engine, orphan) == ("unmatched", None, None)
    assert judged(engine, unsent) == (None, None, None) and judged(engine, foreign) == (None, None, None)
    with Session(engine) as db:
        assert follow.judge(db, at("10:21")) == 0  # nothing judged twice


def test_a_follow_up_pass_never_stops_the_alert_loop(engine, caplog):
    with Session(engine) as db:
        db.exec(text("DROP TABLE phone_ping"))
        db.commit()
    follow = policy.FollowUps(engine, clock=Clock(at("10:00")))
    follow.run()
    follow._last_run = 0
    follow.run()
    assert [r for r in caplog.records if "follow-up pass failed" in r.message] and follow._warned


# ------------------------------------------------------------------ what the owner sees

@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_the_trade_page_lists_what_followed_each_ping(engine, client):
    trade_id, anchor = buy(engine, "10:00")
    key = anchor.split(":", 1)[1]
    with Session(engine) as db:
        alert = PositionAlert(account_id=ROTH, source_key=key, kind="giveback", generation=1, trade_id=trade_id, contract="SNDK 10/23/26 230C",
                              contracts=2, avg_cost=310, mark=320, gain=20, gain_pct=0.03, detected_at=utc(at("10:30")), delivery="sent",
                              delivered_at=utc(at("10:30")))
        nudge = PlanNudge(account_id=ROTH, source_key=key, trade_id=trade_id, ticker="SNDK", contract="SNDK 10/23/26 230C", side="buy_to_open",
                          contracts=2, price=310, opened_at=datetime.combine(WED, datetime.strptime("10:00", "%H:%M").time()),
                          detected_at=utc(at("10:03")), delivery="held", last_error="Not sent: 12 pings already went out today (cap 12).")
        db.add(alert)
        db.add(nudge)
        db.commit()
        db.add(PhonePing(sender="position_alerts", source_id=str(alert.id), kind="giveback", rank=2, anchor=anchor, decision="sent",
                         title="t", body="b", decided_at=utc(at("10:30")), delivered_at=utc(at("10:30")), then="closed", then_minutes=6))
        db.add(PhonePing(sender="plan_nudges", source_id=str(nudge.id), kind="nudge", rank=6, anchor=anchor, decision="over_cap",
                         title="t", body="b", decided_at=utc(at("10:03"))))
        db.commit()
    body = client.get(f"/trades/{trade_id}/phone-alerts").json()
    listed = {a["kind"]: a for a in body["alerts"]}
    assert listed["plan_nudge"]["delivery"] == "held" and listed["plan_nudge"]["policy"] == "over_cap" and listed["plan_nudge"]["then"] is None
    assert listed["giveback"]["policy"] == "sent" and listed["giveback"]["then"] == "closed in 6 min"


def test_the_week_review_counts_pings_by_kind_and_acted_on_share(engine):
    _, anchor = buy(engine, "10:00")
    sell(engine, "10:36")
    ping(engine, "giveback", delivered="10:30", anchor=anchor)
    ping(engine, "nudge", delivered="10:03", anchor=anchor)
    ping(engine, "nudge", delivered="10:04", anchor=anchor, decision="over_cap")
    ping(engine, "entry", delivered="11:00", anchor="symbol:CRWV", symbol="CRWV")
    ping(engine, "research", delivered="12:00", anchor=None, symbol=None)
    with Session(engine) as db:
        policy.FollowUps(engine, clock=Clock(at("13:00"))).judge(db, at("13:00"))
        review = copilot_review.week_review(WED.isoformat(), session=db)
    pings = review["pings"]
    assert pings["state"] == "ok" and (pings["sent"], pings["held"], pings["judged"], pings["acted_on"]) == (4, 1, 3, 1)
    assert pings["acted_on_pct"] == pytest.approx(33.3)
    assert pings["by_kind"]["giveback"] == {"sent": 1, "judged": 1, "acted_on": 1}
    assert pings["by_kind"]["nudge"] == {"sent": 1, "judged": 1, "held": 1}
    assert pings["by_kind"]["entry"] == {"sent": 1, "judged": 1} and pings["by_kind"]["research"] == {"sent": 1}
    assert list(pings["by_kind"]) == ["giveback", "entry", "nudge", "research"]  # the priority order
    assert "pings" in review["provenance"] and "acted_on" in pings["then"]
    with Session(engine) as db:
        assert copilot_review.week_review(date(2026, 9, 2).isoformat(), session=db)["state"] == "none"
