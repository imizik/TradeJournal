"""The desk's Context pane (GET /copilot/desk/{investigation_id}/picture|timeline|history): today's picture with the
plan's levels and fills, what touched the thread newest first, and the owner's record at the plan's invalidation.
Owner-only, read-only, no network (bars and the history engine are stubbed)."""

from datetime import date, datetime, timedelta
import json
import time
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.ai import copilot_review
from app.ai.copilot_fixture import FixtureEvidence
from app.database import get_session
from app.engine import chart_render, desk_context, ping_images
from app.engine.chart_feed import chart_feed
from app.engine.chart_history import HistoryError, chart_history
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from app.models import (CopilotInvestigation, DayJournalEntry, Fill, LevelAlert, LevelAlertEvent, PhonePing, PlanTimeStop,
                        ResearchJob, ThesisWatchTrigger)
from app.routers import copilot_plans as plan_routes
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import (  # noqa: F401  (fixtures)
    CRWV, NBIS, ROTH, T0, alert, buy_and_link, capture, engine, quotes, time_stop,
)
from tests.test_today import RADAR_EVENT, clock, epoch  # noqa: F401  (fixtures)

NOW = epoch(T0 + timedelta(minutes=289))  # 14:49 New York, Wednesday Oct 21 (the clock fixture)
NONE = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def lab(engine, quotes, clock, monkeypatch):  # noqa: F811
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(plan_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def investigation(db_engine, inv=NBIS, symbol="NBIS"):
    with Session(db_engine) as db:
        db.add(CopilotInvestigation(id=UUID(inv), title=f"{symbol} reclaim", symbol=symbol, transcript_json="[]", evidence_json="{}"))
        db.commit()


def planned(db_engine):
    """NBIS entry 95.90 (hit at 95.92 and pinged), invalidation 92.30 armed, time stop 15:30, 2 calls bought 10:05."""
    investigation(db_engine)
    plan = capture(db_engine, "NBIS")
    time_stop(db_engine, NBIS, "NBIS", delivery="sent")
    alert(db_engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=4))
    alert(db_engine, NBIS, "NBIS", "invalidation", 92.3, minute=2)
    buy_and_link(db_engine, plan)
    with Session(db_engine) as db:
        entry = db.exec(select(LevelAlert).where(LevelAlert.plan_role == "entry")).one()
        event = LevelAlertEvent(alert_id=entry.id, generation=1, level=95.9, price=95.92, source="stream",
                                event_at=T0 + timedelta(minutes=4), delivery="sent")
        db.add(event)
        db.commit()
        return str(event.id)


def bars(start=T0, n=120, base=94.0):
    """Regular-session minute bars from ``start`` (naive UTC), plus two pre-market bars that the picture leaves out."""
    first = int(epoch(start))
    early = [{"time": first - 3600 + 60 * i, "open": base, "high": base, "low": base, "close": base, "extended": True} for i in range(2)]
    return early + [{"time": first + 60 * i, "open": base + i / 100, "high": base + i / 100 + 0.05, "low": base + i / 100 - 0.05,
                     "close": base + i / 100} for i in range(n)]


def drawn(monkeypatch):
    seen = []
    real = chart_render.render

    def render(chart):
        seen.append(chart)
        return real(chart)
    monkeypatch.setattr(desk_context.chart_render, "render", render)
    return seen


# ------------------------------------------------------------------ picture


def test_the_picture_is_todays_session_with_the_plan_levels_and_the_fills(lab, engine, monkeypatch):  # noqa: F811
    planned(engine)
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: bars() if symbol == "NBIS" else [])
    seen = drawn(monkeypatch)
    response = lab.get(f"/copilot/desk/{NBIS}/picture")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    [chart] = seen
    assert chart.title == "NBIS" and chart.note == "NOW 95.19"
    assert [b.get("extended") for b in chart.bars[:1]] == [None]  # the regular session once it has bars
    assert [(level.price, level.label) for level in chart.levels] == [(95.9, "TRIG 95.90"), (92.3, "INV 92.30")]
    # The option fill recorded no underlying price, so it is a line at 10:05 rather than a point.
    assert [(t.time, t.label) for t in chart.times] == [(int(epoch(T0 + timedelta(minutes=5))), "IN")]
    assert lab.get(f"/copilot/desk/{NBIS}/picture").content == response.content  # same content, same bytes


def test_an_option_fill_with_its_underlying_price_is_a_point_and_webull_is_left_out(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    with Session(engine) as db:
        db.add(Fill(account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1, price=300,
                    executed_at=datetime(2026, 10, 21, 10, 30), raw_email_id="gmail:700", option_type="call", strike=100,
                    expiration=date(2026, 10, 23), underlying_price_at_fill=94.4))
        db.add(Fill(account_id=ROTH, ticker="NBIS", instrument_type="option", side="sell_to_close", contracts=1, price=330,
                    executed_at=datetime(2026, 10, 21, 11, 0), raw_email_id="gmail:701", option_type="call", strike=100,
                    expiration=date(2026, 10, 23), underlying_price_at_fill=94.9))
        db.add(Fill(account_id=ROTH, ticker="NBIS", instrument_type="stock", side="buy", contracts=5, price=93.0,
                    executed_at=datetime(2026, 10, 20, 11, 0), raw_email_id="gmail:702"))  # yesterday: not today's picture
        db.commit()
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: bars())
    seen = drawn(monkeypatch)
    assert lab.get(f"/copilot/desk/{NBIS}/picture").status_code == 200
    [chart] = seen
    assert chart.levels == ()  # no plan, no lines
    assert [(m.price, m.label, m.tone) for m in chart.marks] == [(94.4, "IN", "amber"), (94.9, "OUT", "amber")]


def test_the_picture_says_why_it_is_unavailable(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    investigation(engine, CRWV, None)
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: [])
    assert lab.get(f"/copilot/desk/{NBIS}/picture").json() == {"detail": "No NBIS minute bars for today yet."}
    assert lab.get(f"/copilot/desk/{CRWV}/picture").json() == {"detail": "This thread has no symbol, so there is no chart."}

    def broken(symbol):
        raise RuntimeError("Tradier unavailable")
    monkeypatch.setattr(ping_images, "today_bars", broken)
    response = lab.get(f"/copilot/desk/{NBIS}/picture")
    assert response.status_code == 404 and response.json() == {"detail": "The NBIS minute bars for today could not be read."}
    # Bars from an earlier day are not today's picture.
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: bars(start=T0 - timedelta(days=1)))
    assert lab.get(f"/copilot/desk/{NBIS}/picture").json() == {"detail": "No NBIS minute bars for today yet."}


def test_the_market_picture_is_qqq_today_with_the_days_fills_and_pings(lab, engine, monkeypatch):  # noqa: F811
    with Session(engine) as db:  # fills keep New York wall time, pings UTC
        db.add(Fill(account_id=ROTH, ticker="NBIS", instrument_type="stock", side="buy", contracts=5, price=93.0,
                    executed_at=datetime(2026, 10, 21, 10, 5), raw_email_id="gmail:710"))
        db.add(Fill(account_id=ROTH, ticker="CRWV", instrument_type="stock", side="sell", contracts=5, price=130.0,
                    executed_at=datetime(2026, 10, 21, 10, 40), raw_email_id="gmail:711"))
        db.add(PhonePing(sender="level_alerts", source_id="p1", kind="giveback", rank=1, symbol="NBIS", decision="sent",
                         title="NBIS gave back", body="", decided_at=T0 + timedelta(minutes=20)))
        db.add(PhonePing(sender="level_alerts", source_id="p2", kind="giveback", rank=1, symbol="NBIS", decision="merged",
                         title="held", body="", decided_at=T0 + timedelta(minutes=21)))  # held back: not drawn
        db.commit()
    asked = []
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: asked.append(symbol) or bars(base=480.0))
    seen = drawn(monkeypatch)
    response = lab.get("/copilot/desk/market/picture")
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    [chart] = seen
    assert asked == ["QQQ"] and chart.title == "QQQ" and chart.levels == ()
    assert [(m.time, m.price, m.label, m.tone) for m in chart.marks] == [
        (int(epoch(T0 + timedelta(minutes=5))), 480.05, "FILL", "amber"),
        (int(epoch(T0 + timedelta(minutes=20))), 480.2, "PING", "violet"),
        (int(epoch(T0 + timedelta(minutes=40))), 480.4, "", "amber"),
    ]


def test_the_market_picture_says_why_it_is_unavailable_and_is_refused_while_the_lab_is_off(lab, monkeypatch):
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: [])
    assert lab.get("/copilot/desk/market/picture").json() == {"detail": "No QQQ minute bars for today yet."}
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/desk/market/picture").status_code == 503


def sent(db, symbol, minute, decision="sent", day=0):
    db.add(PhonePing(sender="level_alerts", source_id=f"{symbol}-{minute}-{day}", kind="giveback", rank=1, symbol=symbol,
                     decision=decision, title=f"{symbol} gave back", body="",
                     decided_at=T0 + timedelta(days=day, minutes=minute)))


def radar_hits(tmp_path, monkeypatch, *hits):
    """A Radar store with ``(symbol, iso first_seen_at)`` events, read through the desk's Radar reader."""
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    store = RadarStore(path)
    for i, (symbol, at) in enumerate(hits):
        store.append_event({**RADAR_EVENT, "event_id": f"hit-{i}", "symbols": [symbol], "session_date": at[:10], "first_seen_at": at})


def test_the_thread_picture_marks_todays_pings_and_radar_hits_on_its_symbol(lab, engine, tmp_path, monkeypatch):  # noqa: F811
    investigation(engine)
    with Session(engine) as db:  # pings keep UTC
        sent(db, "NBIS", 20)
        sent(db, "NBIS", 21, decision="merged")  # held back: not drawn
        sent(db, "APLD", 25)  # another symbol
        sent(db, "NBIS", 50)
        sent(db, "NBIS", 20, day=-1)  # yesterday's
        db.commit()
    radar_hits(tmp_path, monkeypatch, ("NBIS", "2026-10-21T14:30:00.000Z"), ("MU", "2026-10-21T14:31:00.000Z"),
               ("NBIS", "2026-10-20T14:30:00.000Z"))
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: bars())
    seen = drawn(monkeypatch)
    assert lab.get(f"/copilot/desk/{NBIS}/picture").status_code == 200
    [chart] = seen
    # On the bar of their minute, the first of each kind labelled.
    assert [(m.time, m.price, m.label, m.tone) for m in chart.marks] == [
        (int(epoch(T0 + timedelta(minutes=20))), 94.2, "PING", "violet"),
        (int(epoch(T0 + timedelta(minutes=30))), 94.3, "RADAR", "blue"),
        (int(epoch(T0 + timedelta(minutes=50))), 94.5, "", "violet"),
    ]


def test_a_missing_radar_store_means_no_radar_marks(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    monkeypatch.setenv("RADAR_ENABLED", "false")
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: bars())
    seen = drawn(monkeypatch)
    assert lab.get(f"/copilot/desk/{NBIS}/picture").status_code == 200
    assert seen[0].marks == ()


def test_the_timeframes_read_their_own_bars_and_only_the_intraday_ones_carry_marks(lab, engine, monkeypatch):  # noqa: F811
    planned(engine)
    with Session(engine) as db:
        sent(db, "NBIS", 20)
        db.commit()
    first = int(epoch(T0 - timedelta(days=1)))  # yesterday 10:00, then today: 15-minute bars
    fifteen = [{"time": first + 900 * i, "open": 94.0, "high": 94.2, "low": 93.8, "close": 94.0 + i / 100} for i in range(24)]
    fifteen += [{"time": int(epoch(T0)) + 900 * i, "open": 95.0, "high": 95.2, "low": 94.8, "close": 95.0 + i / 100} for i in range(24)]
    day = 86400
    daily = [{"time": int(NOW) - day * i, "open": 90.0, "high": 91.0, "low": 89.0, "close": 90.0 + i / 100} for i in range(200, -1, -1)]
    monkeypatch.setattr(desk_context, "fifteen_bars", lambda symbol: fifteen)
    monkeypatch.setattr(desk_context, "daily_bars", lambda symbol: daily)
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: pytest.fail("the 2m read is not the 15m or 1D read"))
    seen = drawn(monkeypatch)

    assert lab.get(f"/copilot/desk/{NBIS}/picture?timeframe=15m").status_code == 200
    chart = seen[-1]
    assert chart.title == "NBIS 15m" and chart.bars[0]["time"] == first
    assert all(b["time"] <= NOW for b in chart.bars) and len(chart.bars) == 24 + 20  # nothing after now
    assert [lv.label for lv in chart.levels] == ["TRIG 95.90", "INV 92.30"]
    # The ping at 10:20 sits on the 10:15 bar.
    assert [(m.price, m.label, m.tone) for m in chart.marks] == [(95.01, "PING", "violet")]

    assert lab.get(f"/copilot/desk/{NBIS}/picture?timeframe=1D").status_code == 200
    chart = seen[-1]
    assert chart.title == "NBIS 1D" and len(chart.bars) == desk_context.DAILY_DAYS + 1
    assert chart.levels == () and chart.marks == () and chart.times == ()

    assert lab.get(f"/copilot/desk/{NBIS}/picture?timeframe=1h").status_code == 422
    monkeypatch.setattr(desk_context, "daily_bars", lambda symbol: [])
    assert lab.get(f"/copilot/desk/{NBIS}/picture?timeframe=1D").json() == {"detail": "No NBIS daily bars yet."}


def test_the_15m_read_joins_the_completed_sessions_before_today(monkeypatch):
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed as feed
    monkeypatch.setattr(chart_calendar, "hours", lambda day: None)  # clock hours, no provider read
    monkeypatch.setattr(chart_history, "splits", None)
    today_bar = {"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}
    monkeypatch.setattr(feed, "workspace", lambda symbol, intervals, *a, **k: {"panels": {"15m": {"bars": [today_bar]}}})
    asked = []

    def session(symbol, day):
        asked.append(day)
        start = int(datetime.combine(day, datetime.min.time(), ET).timestamp()) + 10 * 3600  # 10:00 New York
        return [{"time": start + 60 * i, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 1} for i in range(30)]
    monkeypatch.setattr(chart_history, "session", session)
    found = desk_context.fifteen_bars("NBIS")
    assert len(asked) == desk_context.SESSIONS_15M - 1 and all(d.weekday() < 5 for d in asked) and asked == sorted(asked, reverse=True)
    assert found[-1] == today_bar and len(found) == 2 * (desk_context.SESSIONS_15M - 1) + 1  # two 15m bars a session, oldest first
    assert found[0]["time"] < found[2]["time"]

    def refused(symbol, day):
        raise HistoryError("History is still loading.", "pending")
    monkeypatch.setattr(chart_history, "session", refused)
    assert desk_context.fifteen_bars("NBIS") == [today_bar]  # the older sessions are a bonus


def test_a_slow_read_is_cut_off_at_the_budget(engine):  # noqa: F811
    investigation(engine)

    def slow(symbol):
        time.sleep(0.5)
        return bars()
    with Session(engine) as db:
        inv = db.get(CopilotInvestigation, UUID(NBIS))
        started = time.monotonic()
        with pytest.raises(desk_context.Unavailable, match="took too long"):
            desk_context.picture(db, inv, NOW, bars=slow, budget=0.05)
        assert time.monotonic() - started < 0.4


# ------------------------------------------------------------------ timeline


def test_the_timeline_is_what_touched_the_thread_newest_first(lab, engine):  # noqa: F811
    own_event = planned(engine)
    with Session(engine) as db:
        db.add(ResearchJob(kind="reassess", input_json=json.dumps({"investigation_id": NBIS, "question": "Did the group hold?"}),
                           dedupe_key="r1", created_at=T0 + timedelta(minutes=30)))
        db.add(ResearchJob(kind="reassess", input_json=json.dumps({"investigation_id": CRWV, "question": "Not this one"}),
                           dedupe_key="r2", created_at=T0 + timedelta(minutes=31)))
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="t1", day="2026-10-21", fired_at=T0 + timedelta(minutes=60),
                                  text="NBIS signs a data-centre lease", path="/copilot-lab"))
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="move", dedupe_key="t0", day="2026-10-01", fired_at=T0 - timedelta(days=20),
                                  text="Too old", path="/copilot-lab"))
        db.add(PhonePing(sender="level_alerts", source_id=own_event, kind="entry", rank=1, symbol="NBIS", decision="sent",
                         title="NBIS entry hit", body="", decided_at=T0 + timedelta(minutes=4)))
        db.add(PhonePing(sender="plan_time_stops", source_id="t-held", kind="time_stop", rank=3, symbol="NBIS", decision="over_cap",
                         reason="Daily cap reached", title="NBIS time stop", body="", decided_at=T0 + timedelta(minutes=200)))
        db.add(PhonePing(sender="position_alerts", source_id="g1", kind="giveback", rank=2, symbol="NBIS", decision="suppressed",
                         title="NBIS 100C gave back half", body="", decided_at=T0 + timedelta(minutes=90)))
        db.add(PhonePing(sender="position_alerts", source_id="g2", kind="giveback", rank=2, symbol="CRWV", decision="sent",
                         title="Other symbol", body="", decided_at=T0 + timedelta(minutes=91)))
        db.add(DayJournalEntry(operation_id="d1", day=date(2026, 10, 21), kind="decision", text="Holding: the group is still bid.",
                               symbol="NBIS", created_at=T0 + timedelta(minutes=120)))
        db.add(DayJournalEntry(operation_id="d0", day=date(2026, 10, 20), kind="decision", text="Yesterday's", symbol="NBIS",
                               created_at=T0 - timedelta(days=1)))
        db.add(DayJournalEntry(operation_id="u1", day=date(2026, 10, 21), kind="update", text="Not a decision", symbol="NBIS",
                               created_at=T0 + timedelta(minutes=121)))
        db.commit()
    alert(engine, NBIS, "NBIS", None, 97.0, minute=3, source_kind="level")  # a Charts level on the same id: not the thread's
    alert(engine, NBIS, "NBIS", None, 97.5, minute=3)  # a plain watch confirmed from the thread: its own wording
    body = lab.get(f"/copilot/desk/{NBIS}/timeline").json()
    assert body["unavailable"] == [] and body["symbol"] == "NBIS"
    got = [(r["kind"], r["text"], r["detail"]) for r in body["rows"]]
    assert got == [
        ("time_stop", "Time stop pinged", "out by 15:30"),  # delivered_at unset: at its due time, 15:30
        ("ping", "Ping held back · time stop", "NBIS time stop · Daily cap reached"),
        ("decision", "Decision", "Holding: the group is still bid."),
        ("ping", "Ping held back · give-back", "NBIS 100C gave back half"),
        ("thesis", "News · thesis watch", "NBIS signs a data-centre lease"),
        ("revisit", "Revisit queued", "Did the group hold?"),
        ("fill", "Bought 2 NBIS 10/23/26 100C", "linked to the plan"),
        ("alert", "Entry hit", "at 95.92 · pinged"),  # its ping rides on this row, not a second one
        ("alert", "Alert armed", "crosses 97.50 · NBIS None"),
        ("alert", "Invalidation armed", "crosses 92.30 · NBIS invalidation"),
        ("time_stop", "Time stop set for 15:30", "out by 15:30"),
        ("alert", "Entry armed", "crosses 95.90 · NBIS entry"),
    ]
    assert [r["at"] for r in body["rows"]] == sorted((r["at"] for r in body["rows"]), reverse=True)


def test_a_waiting_time_stop_says_when_pings_are_off_and_a_skipped_one_says_why(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    monkeypatch.delenv("PLAN_TIME_STOPS_ENABLED", raising=False)
    time_stop(engine, NBIS, "NBIS")
    time_stop(engine, NBIS, "NBIS", client_id="card-2", minute=2, delivery="skipped")
    with Session(engine) as db:
        stop = db.exec(select(PlanTimeStop).where(PlanTimeStop.client_id == "card-2")).one()
        stop.last_error, stop.detected_at = "No open NBIS position opened after the plan, so nothing was sent.", T0 + timedelta(minutes=330)
        db.add(stop)
        db.commit()
    rows = [(r["text"], r["detail"]) for r in lab.get(f"/copilot/desk/{NBIS}/timeline").json()["rows"]]
    assert rows == [("Time stop skipped", "No open NBIS position opened after the plan, so nothing was sent."),
                    ("Time stop set for 15:30", "out by 15:30"),
                    ("Time stop set for 15:30", "out by 15:30 · time-stop pings are off on this server")]


def test_one_failing_source_names_itself_and_a_thread_without_a_plan_is_its_symbol_only(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    with Session(engine) as db:
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="earnings", dedupe_key="t1", day="2026-10-21", fired_at=T0,
                                  text="Earnings Oct 23", path="/copilot-lab"))
        db.commit()

    def broken(*_args):
        raise RuntimeError("boom")
    monkeypatch.setattr(desk_context, "_ping_rows", broken)
    body = lab.get(f"/copilot/desk/{NBIS}/timeline").json()
    assert body["unavailable"] == ["pings"]
    assert [(r["kind"], r["text"]) for r in body["rows"]] == [("thesis", "Earnings · thesis watch")]


# ------------------------------------------------------------------ your history


def test_history_reads_the_engine_at_the_plans_invalidation_and_says_it_in_one_sentence(lab, engine, monkeypatch):  # noqa: F811
    planned(engine)
    asked = []

    def level_history(symbol, **kwargs):
        asked.append((symbol, {k: v for k, v in kwargs.items() if k != "session"}))
        return FixtureEvidence().get_level_history(symbol, level=kwargs["level"], side=kwargs["side"], entry=kwargs["entry"])
    monkeypatch.setattr(copilot_review, "level_history", level_history)
    body = lab.get(f"/copilot/desk/{NBIS}/history").json()
    assert asked == [("NBIS", {"level": 92.3, "side": "below", "entry": 95.9})]
    assert (body["state"], body["level"], body["side"], body["crossed"], body["trades"], body["won"], body["not_won"]) == \
        ("ok", 92.3, "below", 12, 31, 3, 9)
    assert body["sentence"] == ("12 of 31 past NBIS calls crossed a level 3.8% below entry while held: 3 won, 9 did not. "
                                "5 recovered to breakeven; median -18% from the cross.")
    assert body["simulated"] is True


def test_history_on_the_real_engine_with_no_past_trades_says_so(lab, engine, monkeypatch):  # noqa: F811
    planned(engine)
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: pytest.fail("the planned entry needs no quote"))
    body = lab.get(f"/copilot/desk/{NBIS}/history").json()
    assert body["state"] == "ok" and body["trades"] == 0 and body["small"] is True
    assert body["sentence"] == "No closed NBIS calls in the last 180 days to compare at 3.8% below entry."


def test_history_with_past_trades_but_no_recorded_bars_says_that_not_none(engine):  # noqa: F811
    planned(engine)
    data = {**FixtureEvidence().get_level_history("NBIS", level=92.3, side="below", entry=95.9),
            "crossed": {"trades": 0, "of": 0}, "sample": {"trades": 4, "small": True}}
    with Session(engine) as db:
        body = desk_context.history(db, db.get(CopilotInvestigation, UUID(NBIS)), level_history=lambda *a, **k: data)
    assert body["sentence"] == "4 closed NBIS calls in the last 180 days, but none has recorded minute bars to replay."


def test_history_says_what_is_missing(lab, engine):  # noqa: F811
    investigation(engine)
    assert lab.get(f"/copilot/desk/{NBIS}/history").json() == {
        "state": "missing", "symbol": "NBIS",
        "reason": "No plan invalidation yet. Once you confirm a plan card, your record at its invalidation shows here."}
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    assert lab.get(f"/copilot/desk/{NBIS}/history").json()["state"] == "missing"
    investigation(engine, CRWV, None)
    assert lab.get(f"/copilot/desk/{CRWV}/history").json()["reason"] == "This thread has no symbol, so there is no level to look up."


# ------------------------------------------------------------------ access


def test_an_unknown_thread_and_the_lab_off_are_refused(lab, engine, monkeypatch):  # noqa: F811
    assert lab.get(f"/copilot/desk/{NONE}/timeline").status_code == 404
    assert lab.get("/copilot/desk/not-an-id/history").status_code == 404
    investigation(engine)
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    for part in ("picture", "timeline", "history"):
        assert lab.get(f"/copilot/desk/{NBIS}/{part}").status_code == 503


def test_assistant_sessions_cannot_reach_it(boundary):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    assert boundary.owner.get(f"/copilot/desk/{NONE}/timeline").status_code == 404  # reached, no such thread
    assert signin(boundary).status_code == 200
    for part in ("picture", "timeline", "history"):
        assert boundary.public.get(f"/copilot/desk/{NONE}/{part}").status_code == 403


def test_a_held_ping_for_the_threads_own_alert_shows_and_a_fired_alert_without_its_event_still_does(lab, engine):  # noqa: F811
    investigation(engine)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, state="fired", fired=T0 + timedelta(minutes=50))
    with Session(engine) as db:
        inv = db.exec(select(LevelAlert)).one()
        event = LevelAlertEvent(alert_id=inv.id, generation=1, level=92.3, price=92.25, source="stream",
                                event_at=T0 + timedelta(minutes=50), delivery="sent")
        db.add(event)
        db.flush()
        db.add(PhonePing(sender="level_alerts", source_id=str(event.id), kind="invalidation", rank=1, symbol="NBIS",
                         decision="merged", reason="Merged into the give-back ping", title="NBIS invalidation hit", body="",
                         decided_at=T0 + timedelta(minutes=51)))
        db.delete(event)  # an event gone (retention) still leaves the hit, at the alert's own time
        db.commit()
    rows = [(r["kind"], r["text"], r["detail"]) for r in lab.get(f"/copilot/desk/{NBIS}/timeline").json()["rows"]]
    assert rows == [("ping", "Ping held back · invalidation", "NBIS invalidation hit · Merged into the give-back ping"),
                    ("alert", "Invalidation hit", "crosses 92.30"),
                    ("alert", "Invalidation armed", "crosses 92.30 · NBIS invalidation")]


def test_history_for_a_short_plan_looks_above_and_counts_puts(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    capture(engine, "NBIS", side="buy_puts")
    alert(engine, NBIS, "NBIS", "entry", 92.0)
    alert(engine, NBIS, "NBIS", "invalidation", 95.5)
    asked = []

    def level_history(symbol, **kwargs):
        asked.append(kwargs["side"])
        return FixtureEvidence().get_level_history(symbol, level=kwargs["level"], side=kwargs["side"], entry=kwargs["entry"])
    monkeypatch.setattr(copilot_review, "level_history", level_history)
    body = lab.get(f"/copilot/desk/{NBIS}/history").json()
    assert asked == ["above"] and body["side"] == "above"
    assert body["sentence"].startswith("12 of 31 past NBIS puts crossed a level 3.8% above entry while held: 3 won, 9 did not.")


def test_history_passes_on_the_engines_reason_and_needs_a_planned_entry(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    capture(engine, "NBIS")
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    monkeypatch.setattr(copilot_review, "level_history", lambda *a, **k: pytest.fail("no entry, no engine call"))
    body = lab.get(f"/copilot/desk/{NBIS}/history").json()
    assert body["state"] == "missing" and "no entry level" in body["reason"]
    alert(engine, NBIS, "NBIS", "entry", 91.0, minute=1)
    monkeypatch.setattr(copilot_review, "level_history", lambda *a, **k: {"state": "unavailable", "reason": "92.3 is not below the entry 91.0."})
    assert lab.get(f"/copilot/desk/{NBIS}/history").json() == {
        "state": "unavailable", "symbol": "NBIS", "level": 92.3, "reason": "92.3 is not below the entry 91.0."}


def test_a_picture_request_finding_every_worker_busy_says_so_at_once(engine, monkeypatch):  # noqa: F811
    investigation(engine)
    monkeypatch.setattr(desk_context, "_free", desk_context.threading.BoundedSemaphore(1))
    desk_context._free.acquire()  # a read still running past its budget
    with Session(engine) as db:
        inv = db.get(CopilotInvestigation, UUID(NBIS))
        started = time.monotonic()
        with pytest.raises(desk_context.Unavailable, match="still running"):
            desk_context.picture(db, inv, NOW, bars=lambda symbol: bars())
        assert time.monotonic() - started < 0.2
        desk_context._free.release()
        assert desk_context.picture(db, inv, NOW, bars=lambda symbol: bars()).startswith(b"\x89PNG")
