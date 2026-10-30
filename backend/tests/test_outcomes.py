"""Outcome attribution (app/engine/outcomes.py): each subject kind's row from seeded sources and synthetic stored bars,
open windows staying incomplete and recomputed, the unique key, the action windows, and the alternative's dollars
matching ``exit_habits.follow_up`` and the Radar scorecard on the same inputs."""
from datetime import UTC, date, datetime, time, timedelta
import json
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot_review
from app.database import get_session
from app.engine import exit_habits, notification_policy, outcomes, radar_scorecard, reconstructor
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from app.models import (Account, CaptureLink, CopilotInvestigation, Fill, Outcome, PhonePing, PositionAlert, ShadowBookDecision,
                        ShadowBookEvent, Trade, TradeCapture)
from app.routers import exit_habits as exit_habits_router
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

ROTH = UUID(int=1)
WED = date(2026, 10, 21)  # trading days after it: Oct 22, 23, 26, 27, 28
NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC).timestamp()  # Thursday 16:00 New York: every window over
EARLY = datetime(2026, 10, 22, 17, 0, tzinfo=UTC).timestamp()  # Thursday Oct 22, 13:00 New York: d1 not closed yet
NO_CALENDAR = lambda day: None  # noqa: E731 - weekdays


def at(day: date, hh_mm: str) -> float:
    return datetime.combine(day, time.fromisoformat(hh_mm), ET).timestamp()


def utc(when: str) -> datetime:
    """A New York wall-clock time as naive UTC."""
    return datetime.fromisoformat(when).replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)


def session(day: date, steps: list[tuple[str, float]]) -> list[dict]:
    """09:30-16:00 minutes at each step's price from its time on; high and low half a dollar either side."""
    out, price, i = [], steps[0][1], 0
    t, end = at(day, "09:30"), at(day, "16:00")
    while t < end:
        while i < len(steps) and at(day, steps[i][0]) <= t:
            price, i = steps[i][1], i + 1
        out.append({"time": int(t), "open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1})
        t += 60
    return out


SNDK = {WED: session(WED, [("09:30", 100.0), ("10:31", 96.0)]),     # +1h from 10:30: −4%
        date(2026, 10, 22): session(date(2026, 10, 22), [("09:30", 90.0), ("15:00", 88.0)]),  # +1d close: −12%
        date(2026, 10, 23): session(date(2026, 10, 23), [("09:30", 95.0)]),
        date(2026, 10, 26): session(date(2026, 10, 26), [("09:30", 100.0)]),
        date(2026, 10, 27): session(date(2026, 10, 27), [("09:30", 120.0)]),                 # the high inside d5
        date(2026, 10, 28): session(date(2026, 10, 28), [("09:30", 110.0)])}                 # +5d close: +10%


def bars_of(table: dict[str, dict]):
    return lambda symbol, day: table.get(symbol, {}).get(day)


BARS = bars_of({"SNDK": SNDK})


# ------------------------------------------------------------------ windows (pure)

def test_the_three_windows_from_stored_minutes():
    out = outcomes.windows(BARS, NO_CALENDAR, "SNDK", utc("2026-10-21T10:30"), 100.0, NOW)
    assert out["h1"] == {"price": 96.0, "pct": -4.0, "high": 100.5, "low": 95.5, "complete": True}
    assert out["d1"] == {"price": 88.0, "pct": -12.0, "high": 100.5, "low": 87.5, "complete": True}
    assert out["d5"] == {"price": 110.0, "pct": 10.0, "high": 120.5, "low": 87.5, "complete": True}


def test_an_open_window_is_incomplete():
    out = outcomes.windows(BARS, NO_CALENDAR, "SNDK", utc("2026-10-21T10:30"), 100.0, EARLY)
    assert out["h1"]["complete"] is True
    assert out["d1"]["complete"] is False and out["d5"]["complete"] is False


def test_a_missing_session_waits_then_closes_with_what_there_is():
    gap = bars_of({"SNDK": {d: m for d, m in SNDK.items() if d != date(2026, 10, 23)}})
    out = outcomes.windows(gap, NO_CALENDAR, "SNDK", utc("2026-10-21T10:30"), 100.0, NOW)
    assert out["d1"]["complete"] is True and out["d5"]["complete"] is False  # Oct 23 not stored yet
    later = outcomes.windows(gap, NO_CALENDAR, "SNDK", utc("2026-10-21T10:30"), 100.0, NOW + 15 * 86400)
    assert later["d5"]["complete"] is True and later["d5"]["missing"] == "sessions not stored: 2026-10-23"
    assert later["d5"]["price"] == 110.0


def test_five_trading_days_follow_the_market_calendar():
    closed = lambda day: {"status": "closed", "close": None} if day == date(2026, 10, 26) else None  # noqa: E731
    assert outcomes.trading_days_after(closed, WED, 5) == [date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 27),
                                                           date(2026, 10, 28), date(2026, 10, 29)]
    assert outcomes.trading_days_after(NO_CALENDAR, date(2026, 10, 23), 1) == [date(2026, 10, 26)]  # Friday to Monday


def test_no_symbol_is_complete_with_nothing_measured():
    out = outcomes.windows(BARS, NO_CALENDAR, None, utc("2026-10-21T10:30"), None, NOW)
    assert all(out[w]["complete"] and out[w]["price"] is None for w in outcomes.WINDOWS)


# ------------------------------------------------------------------ action windows (pure)

def f(side, qty, when, key="position"):
    return {"id": when, "side": side, "contracts": qty, "price": 1.0, "executed_at": datetime.fromisoformat(when), "key": key}


START = datetime(2026, 10, 21, 10, 30)
LATER = datetime(2026, 10, 22, 12, 0)
OPEN = [f("buy_to_open", 2, "2026-10-21T09:45")]


@pytest.mark.parametrize("fills, minutes, expected", [
    (OPEN + [f("sell_to_close", 2, "2026-10-21T10:40")], 15, "closed"),
    (OPEN + [f("sell_to_close", 1, "2026-10-21T10:40")], 15, "trimmed"),
    (OPEN + [f("sell_to_close", 2, "2026-10-21T10:46")], 15, "held"),     # 16 minutes: outside an exit ping's window
    (OPEN + [f("sell_to_close", 2, "2026-10-21T10:46")], 30, "closed"),   # inside an entry ping's
    (OPEN + [f("buy_to_open", 1, "2026-10-21T10:35")], 15, "added"),
    (OPEN + [f("sell_to_close", 2, "2026-10-21T10:30")], 15, "closed"),   # the start's own minute counts as after
    ([f("buy_to_open", 1, "2026-10-21T10:50")], 30, "entered"),
    ([f("buy_to_open", 1, "2026-10-21T11:01")], 30, "none"),
    ([], 30, "none"),
])
def test_the_action_in_its_window(fills, minutes, expected):
    assert outcomes.action(fills, START, START + timedelta(minutes=minutes), LATER) == expected


def test_the_action_waits_for_its_window_to_end():
    assert outcomes.action(OPEN, START, START + timedelta(minutes=15), START + timedelta(minutes=10)) is None


def test_another_contract_left_open_is_a_trim():
    fills = [f("buy_to_open", 1, "2026-10-21T09:45", "a"), f("buy_to_open", 1, "2026-10-21T09:46", "b"),
             f("sell_to_close", 1, "2026-10-21T10:35", "a")]
    assert outcomes.action(fills, START, START + timedelta(minutes=15), LATER) == "trimmed"


def test_a_group_event_is_read_on_its_top_member():
    group = {"kind": "group_move", "direction": "down", "symbols": ["AAA", "BBB"],
             "evidence": [{"symbol": "AAA", "change_pct": -1.0}, {"symbol": "BBB", "change_pct": -3.0}]}
    assert outcomes.top_member(group) == "BBB"
    assert outcomes.top_member({**group, "direction": "up"}) == "AAA"
    assert outcomes.top_member({"kind": "relative_to_spy", "symbols": ["CCC"], "evidence": []}) == "CCC"


def test_the_trade_page_text():
    row = {"h1": {"pct": -4.4}, "d1": {"pct": -12.0}}
    assert outcomes.after_text(row) == "+1h −4% · +1d −12%"
    assert outcomes.after_text({"h1": {"pct": 2.0}, "d1": None}) == "+1h +2%"
    assert outcomes.after_text({"h1": None, "d1": None}) is None


# ------------------------------------------------------------------ seeded sources

class _Thursday(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 23)


@pytest.fixture(autouse=True)
def on_thursday(monkeypatch):
    """Trade rebuilds expire contracts past the machine's own date; these run as of Oct 23, whatever today is."""
    monkeypatch.setattr(reconstructor, "date", _Thursday)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        s.commit()
        yield s
    engine.dispose()


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pass(store, hh_mm, prices):
    t = at(WED, hh_mm)
    record = {"session_date": WED.isoformat(), "started_at": _stamp(t), "finished_at": _stamp(t + 5), "universe_version": "t",
              "status": "ok", "symbols_requested": 2, "symbols_returned": 2, "unmatched": [], "requests_used": 1, "error": None,
              "skip_reason": None}
    store.append_pass(record, [{"symbol": s, "last": p, "prev_close": 100, "open": 100, "high": None, "low": None, "volume": 1,
                                "bid": None, "ask": None, "trade_time_ms": (t - 1) * 1000, "retrieved_at": _stamp(t + 2)}
                               for s, p in prices.items()])
    return record


@pytest.fixture
def store(tmp_path):
    s = RadarStore(tmp_path / "radar.sqlite")
    first = _pass(s, "10:00", {"SNDK": 100.0, "SPY": 100.0})
    _pass(s, "11:00", {"SNDK": 102.0, "SPY": 100.0})
    _pass(s, "15:59", {"SNDK": 105.0, "SPY": 101.0})  # to the last pass: SNDK +5% against SPY +1%
    s.append_event({"event_id": "sndk-up", "session_date": WED.isoformat(), "rule_version": "v1", "universe_version": "t",
                    "kind": "relative_to_spy", "direction": "up", "symbols": ["SNDK"], "benchmark": "SPY", "group": None,
                    "first_seen_at": first["finished_at"], "summary": "SNDK up", "measures": {},
                    "evidence": [{"symbol": "SNDK", "pass_id": 1, "retrieved_at": first["finished_at"], "last": 100.0, "change_pct": 1.0}],
                    "coverage": {}, "chart": {}})
    return s


def fill(db, side, qty, price, when):
    key = f"gmail:{when}:{side}"
    db.add(Fill(account_id=ROTH, ticker="SNDK", instrument_type="option", side=side, contracts=qty, price=price,
                executed_at=datetime.fromisoformat(when), raw_email_id=key, option_type="call", strike=230,
                expiration=date(2026, 11, 20)))
    return key


def seed(db) -> dict:
    """One closed SNDK trade and one of each output kind on it: an open-trade alert ping (sold 2 at $280 against a $300
    mark, 10 minutes later), an entry ping the policy held, its plan, a Radar hit, Jo research and a Shadow plan."""
    entry = fill(db, "buy_to_open", 2, 200, "2026-10-21T09:45")
    fill(db, "sell_to_close", 2, 280, "2026-10-21T10:40")
    db.commit()
    _rebuild_trades(db, "test")
    alert = PositionAlert(account_id=ROTH, source_key=entry, kind="giveback", generation=0, trade_id=UUID(int=0),
                          contract="SNDK 11/20/26 230C", contracts=2, avg_cost=200, mark=300.0, detected_at=utc("2026-10-21T10:30"),
                          delivery="sent")
    db.add(alert)
    db.flush()
    db.add(PhonePing(sender="position_alerts", source_id=str(alert.id), kind="giveback", rank=2, symbol="SNDK",
                     anchor=f"{ROTH}:{entry}", decision="sent", title="t", body="b", decided_at=utc("2026-10-21T10:30"),
                     delivered_at=utc("2026-10-21T10:30")))
    db.add(PhonePing(sender="level_alerts", source_id="entry-1", kind="entry", rank=4, symbol="SNDK", decision="over_cap",
                     title="t", body="b", decided_at=utc("2026-10-21T09:40")))
    capture = TradeCapture(client_id="c1", received_at=utc("2026-10-21T09:30"), account_id=ROTH, account_label="Roth",
                           underlying="SNDK", side="buy_calls", instrument="option", mode="template", setup_label="Copilot plan",
                           context_state="unavailable", image_state="unavailable")
    db.add(capture)
    db.flush()
    db.add(CaptureLink(capture_id=capture.id, account_id=ROTH, source_key=entry, method="manual", linked_at=utc("2026-10-21T09:50")))
    db.add(CopilotInvestigation(source="jo", title="Jo · SNDK", symbol="SNDK", status="closed", transcript_json="[]",
                                evidence_json="[]", created_at=utc("2026-10-21T12:00")))
    decision = ShadowBookDecision(radar_event_id="sndk-up", session_date=WED, symbol="SNDK", event_json="{}", status="plan",
                                  claimed_at=utc("2026-10-21T10:01"), decided_at=utc("2026-10-21T10:02"))
    db.add(decision)
    db.flush()
    for kind in ("entry", "exit"):
        db.add(ShadowBookEvent(decision_id=decision.id, event_type=kind, effective_at=utc("2026-10-21T10:05"),
                               recorded_at=utc("2026-10-21T10:05"), data_json="{}"))
    db.commit()
    return {"alert": alert, "capture": capture, "decision": decision}


def run(db, store, now=NOW, **kw):
    return outcomes.compute(db, now, bars=BARS, hours=NO_CALENDAR, store=store, start=WED, **kw)


def rows(db) -> dict:
    return {o.subject_kind + (":held" if o.held else ""): o for o in db.exec(select(Outcome)).all()}


def test_every_subject_kind_gets_its_row(db, store):
    seed(db)
    result = run(db, store)
    assert result == {"computed": 6, "by_kind": {"ping": 2, "plan": 1, "radar_event": 1, "research": 1, "shadow_decision": 1},
                      "failed": 0, "waiting": 0, "note": None}
    got = rows(db)
    assert set(got) == {"ping", "ping:held", "plan", "radar_event", "research", "shadow_decision"}
    assert all(o.complete for o in got.values())
    trade = db.exec(select(Trade)).one()

    ping = got["ping"]
    assert (ping.source_kind, ping.action, ping.alt_usd, ping.trade_id, ping.reference_price) == ("giveback", "closed", -40.0, trade.id, 100.0)
    assert json.loads(ping.h1)["pct"] == -4.0 and json.loads(ping.d1)["pct"] == -12.0 and json.loads(ping.d5)["pct"] == 10.0
    held = got["ping:held"]
    assert (held.source_kind, held.action, held.alt_usd) == ("entry", "entered", None)  # the 09:45 entry within 30 minutes

    plan = got["plan"]
    assert (plan.source_kind, plan.action, plan.trade_id, plan.alt_usd) == ("Copilot plan", "entered", trade.id, None)

    radar = got["radar_event"]
    assert (radar.subject_id, radar.symbol, radar.reference_price, radar.action) == ("sndk-up", "SNDK", 100.0, "held")  # open since 09:45, sold 10:40
    assert radar.alt_usd == 4.0  # one share at $100, +5% against SPY's +1%

    research = got["research"]
    assert research.subject_id.endswith(":SNDK") and research.h1 is None and research.action == "none"  # flat by then
    assert json.loads(research.d1)["pct"] == round((88 / 96 - 1) * 100, 2)  # from the 12:00 minute
    shadow = got["shadow_decision"]
    assert (shadow.source_kind, shadow.action, shadow.h1) == ("plan", "closed", None) and json.loads(shadow.d5)["complete"]


def test_alt_usd_matches_the_existing_reads_on_the_same_inputs(db, store):
    seeded = seed(db)
    run(db, store)
    got = rows(db)
    trade = db.exec(select(Trade)).one()
    alert = seeded["alert"]
    fills = notification_policy._fills(db, trade)
    expected = exit_habits.follow_up({"detected_at": alert.detected_at, "contracts": 2.0, "mark": 300.0}, fills, trade.status)
    assert got["ping"].alt_usd == expected["vs_alert"] == -40.0
    event = store.event("sndk-up")
    passes = sorted(store.passes(WED.isoformat()), key=lambda p: (p["started_at"], p["id"]))
    after = radar_scorecard._after(store, event, passes, True, {})
    assert got["radar_event"].alt_usd == round(after["close_pct"] / 100 * 100.0, 2) == 4.0


def test_open_windows_stay_incomplete_and_are_recomputed(db, store):
    seed(db)
    run(db, store, now=EARLY)
    early = rows(db)
    assert not any(o.complete for o in early.values())
    assert json.loads(early["ping"].h1)["complete"] and not json.loads(early["ping"].d1)["complete"]
    stamp = early["ping"].computed_at
    result = run(db, store)
    assert result["computed"] == 6 and len(db.exec(select(Outcome)).all()) == 6  # the same rows, updated
    assert rows(db)["ping"].complete and rows(db)["ping"].computed_at > stamp
    assert run(db, store)["computed"] == 0  # complete rows are left alone


def test_the_cap_leaves_the_rest_for_the_next_run(db, store):
    seed(db)
    assert run(db, store, cap=2)["waiting"] == 4
    assert {o.subject_kind for o in db.exec(select(Outcome)).all()} == {"plan", "ping"}  # the oldest two: 09:30 and 09:40
    assert run(db, store)["computed"] == 4


def test_without_a_radar_file_the_rest_still_run(db):
    seed(db)
    assert run(db, False)["by_kind"] == {"ping": 2, "plan": 1, "research": 1, "shadow_decision": 1}


def test_one_row_per_subject(db):
    for _ in range(2):
        db.add(Outcome(subject_kind="ping", subject_id="same", anchored_at=utc("2026-10-21T10:30")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_a_plan_with_no_trade_stays_open_to_a_link(db, store):
    db.add(TradeCapture(client_id="c2", received_at=utc("2026-10-21T09:30"), account_id=ROTH, account_label="Roth",
                        underlying="SNDK", side="buy_calls", instrument="option", mode="discretionary",
                        context_state="unavailable", image_state="unavailable"))
    db.commit()
    run(db, store)
    plan = rows(db)["plan"]
    assert plan.action == "none" and not plan.complete  # inside the 14 days a link may still come
    run(db, store, now=NOW + 14 * 86400)
    assert rows(db)["plan"].complete


# ------------------------------------------------------------------ surfaces

def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(exit_habits_router.router, prefix="/analytics")
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def test_the_route_returns_rows_and_a_summary_per_kind(db, store):
    seed(db)
    run(db, store)
    body = _client(db).get("/analytics/outcomes", params={"since": "2026-10-21"}).json()
    assert body["since"] == "2026-10-21" and body["note"] == "Counts and price paths, not causation."
    assert len(body["rows"]) == 6
    ping = body["summary"]["ping"]
    assert (ping["count"], ping["complete"], ping["held"], ping["median_d1_pct"]) == (2, 2, 1, -12.0)
    assert ping["actions"] == {"closed": 1, "entered": 1} and (ping["alt_usd_total"], ping["alt_usd_n"]) == (-40.0, 1)
    assert body["summary"]["radar_event"]["alt_usd_total"] == 4.0 and body["summary"]["research"]["alt_usd_total"] is None
    only = _client(db).get("/analytics/outcomes", params={"kind": "plan", "symbol": "sndk"}).json()
    assert list(only["summary"]) == ["plan"] and len(only["rows"]) == 1
    assert _client(db).get("/analytics/outcomes", params={"kind": "nope"}).status_code == 422


def test_owner_only(boundary):  # noqa: F811
    assert boundary.owner.get("/analytics/outcomes").status_code == 200
    assert boundary.public.get("/analytics/outcomes").status_code == 401


def test_the_trade_page_shows_what_followed_each_ping(db, store):
    seeded = seed(db)
    run(db, store)
    listed = outcomes.annotate(db, [{"id": str(seeded["alert"].id), "kind": "giveback"}, {"id": "unknown", "kind": "giveback"}])
    assert [r["after"] for r in listed] == ["+1h −4% · +1d −12%", None]


def test_the_week_review_reads_the_outcomes_by_kind(db, store):
    seed(db)
    run(db, store)
    section = copilot_review._week_outcomes(db, datetime(2026, 10, 19), datetime(2026, 10, 24))
    assert section["state"] == "ok" and "not causation" in section["note"]
    assert section["by_kind"]["ping"] == {"count": 2, "complete": 2, "held": 1, "median_d1_pct": -12.0,
                                          "actions": {"closed": 1, "entered": 1}, "alt_usd_total": -40.0}
    assert copilot_review._week_outcomes(db, datetime(2026, 10, 12), datetime(2026, 10, 17))["state"] == "not_applicable"


# ------------------------------------------------------------------ the pipeline step

def test_a_failed_outcomes_step_never_fails_the_sync_pipeline(monkeypatch):
    """The step's own run row records the failure; the pipeline (whose success Gmail health reads) still succeeds."""
    import types
    from app.models import JobRun
    from app.routers import sync

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sync, "engine", engine)
    monkeypatch.setattr(sync, "execute_job", lambda job_id, runner: runner())
    monkeypatch.setattr(sync, "_import_fills_from_gmail", lambda session, start_enrichment: {"saved": 0, "skipped": 0})
    monkeypatch.setattr(sync, "_run_existing_enrichment", lambda *a: types.SimpleNamespace(total=0, id=None))

    def broken(session, job_id):
        raise RuntimeError("outcome table missing")
    monkeypatch.setattr(sync, "_run_outcomes", broken)
    with Session(engine) as db:
        pipeline = sync._create_run(db, sync.JOB_FULL_PIPELINE, "test", total=sync.PIPELINE_STEPS)
    sync._run_pipeline(pipeline.id)
    with Session(engine) as db:
        runs = {r.job_type: r for r in db.exec(select(JobRun)).all()}
    assert (runs["full_pipeline"].status, runs["full_pipeline"].done, runs["full_pipeline"].total) == ("succeeded", 7, 7)
    assert runs["compute_outcomes"].status == "failed" and "outcome table missing" in runs["compute_outcomes"].error
