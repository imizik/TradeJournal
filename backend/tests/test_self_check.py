"""The desk's open self-check (engine/self_check.py): six checks a minute after each regular open, each on its own
timeout, none writing into his books; one Telegram line under its own budget of one a day; the newest run on the health
strip. Never on a day the calendar does not confirm as a session."""

import asyncio
import json
import time
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import (desk_health, desk_sparks, notification_policy, paper_book, paper_replay, phone, replay_options,
                        self_check, telegram)
from app.engine.chart_math import ET
from app.models import PaperEvent, PaperRun, PhonePing
from app.routers import copilot_desk

OPEN = datetime(2026, 11, 16, 9, 30, tzinfo=ET).timestamp()  # Monday Nov 16, the first live session
AT = OPEN + 65  # 09:31:05


def q(symbol, bid, ask, at, last=None):
    stamp = int(at * 1000)
    return SimpleNamespace(symbol=symbol, bid=bid, ask=ask, bid_date=stamp, ask_date=stamp, last=last, mid=None)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def kept(tmp_path, monkeypatch):
    monkeypatch.setattr(self_check, "ROOT", tmp_path / "self_check")
    return tmp_path / "self_check"


@pytest.fixture
def live(monkeypatch):
    """Fresh SPY and 590 call quotes at 09:31:05, yesterday's contract trades, and a counter of every read."""
    state = SimpleNamespace(quotes={"SPY": q("SPY", 590.30, 590.32, AT - 2, last=590.37),
                                    "SPY261116C00590000": q("SPY261116C00590000", 1.10, 1.14, AT - 3)},
                            asked=[], trades={("SPY261116C00590000", date(2026, 11, 13)): [{"time": OPEN, "close": 1.0}] * 5})
    monkeypatch.setattr(paper_book, "_live_quotes", lambda symbols: state.asked.append(list(symbols)) or
                        {s: state.quotes[s] for s in symbols if s in state.quotes})
    monkeypatch.setattr(paper_replay, "days", lambda now, count=1: [{"date": "2026-11-13"}])
    monkeypatch.setattr(replay_options, "off_reason", lambda day, now: None)

    def trades(occ, day):
        state.asked.append(("timesales", occ, day))
        return state.trades.get((occ, day), [])
    monkeypatch.setattr(replay_options, "trades", trades)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("ALERT_APP_URL", raising=False)
    return state


def runner(at=AT - 30, error=None):
    return SimpleNamespace(last_pass_at=at, last_error=error)


# --------------------------------------------------------------------------- the exact Telegram texts

def test_the_line_says_all_ok_or_names_each_failure_and_why():
    ok = [{"name": n, "status": "ok", "detail": ""} for n in self_check.NAMES]
    assert self_check.line(ok, AT) == "Self-check 09:31 ✅ all 6 OK"
    failed = [*ok]
    failed[0] = {"name": "paper pricing", "status": "fail", "detail": "no fresh SPY quote since 09:30:12"}
    failed[2] = {"name": "replay", "status": "fail", "detail": "timesales 500"}
    assert self_check.line(failed, AT) == ("Self-check 09:31 ⚠️ 2 of 6 failed: paper pricing (no fresh SPY quote since 09:30:12), "
                                           "replay (timesales 500)")
    off = [*ok]
    off[1] = {"name": "paper runner", "status": "off", "detail": "not running"}
    assert self_check.line(off, AT) == "Self-check 09:31 ✅ 5 of 6 OK, off: paper runner"


def test_the_health_strip_rides_the_line_and_telegram_renders_it():
    health = {"overall": "bad", "sources": [{"id": "robinhood", "name": "Robinhood", "state": "down"},
                                            {"id": "radar", "name": "Radar", "state": "stale"},
                                            {"id": "prices", "name": "Prices", "state": "live"},
                                            {"id": "self_check", "name": "Self-check", "state": "unknown"}]}
    assert self_check.data_line(health) == "Data: Robinhood down, Radar behind"
    assert self_check.data_line({"overall": "ok", "sources": [{"id": "prices", "name": "Prices", "state": "live"},
                                                              {"id": "self_check", "name": "Self-check", "state": "unknown"}]}) == "Data: all live"
    assert self_check.data_line(None) == "Data: health strip not read"
    assert telegram.text_for("Self-check 09:31 ✅ all 6 OK", "Data: all live") == "<b>Self-check 09:31 ✅ all 6 OK</b>\nData: all live"


# --------------------------------------------------------------------------- each check

def test_paper_pricing_is_the_paper_books_own_fill_price_on_fresh_quotes(live):
    facts = {}
    assert self_check.check_paper_pricing(AT, facts) == "SPY shares 590.32, SPY $590 Call 11/16/26 1.14"
    assert facts["spy"] == 590.37
    assert live.asked == [["SPY"], ["SPY261116C00590000"]]  # two quote reads


def test_a_stale_quote_fails_pricing_in_its_own_words_and_still_names_the_strike(live):
    live.quotes["SPY"] = q("SPY", 590.30, 590.32, OPEN - 80, last=590.37)  # 09:28:40: older than the 2-minute rule
    facts = {}
    with pytest.raises(self_check.CheckFailed, match=r"^no fresh SPY quote since 09:28:40$"):
        self_check.check_paper_pricing(AT, facts)
    assert facts["spy"] == 590.37  # the replay check still picks its contract


def test_the_paper_runner_passed_in_the_last_two_minutes():
    assert self_check.check_paper_runner(AT, runner()) == "passed 09:30:35"
    with pytest.raises(self_check.CheckFailed, match="no pass since 09:28:05"):
        self_check.check_paper_runner(AT, runner(AT - 180))
    with pytest.raises(self_check.CheckFailed, match="paper runner pass failed"):
        self_check.check_paper_runner(AT, runner(error="Paper runner pass failed"))
    with pytest.raises(self_check._Off):
        self_check.check_paper_runner(AT, None)


def test_replay_reads_previous_session_from_the_contract_still_listed_today(live, monkeypatch):
    assert self_check.check_replay(AT, {"spy": 590.37}) == "5 bars for SPY261116C00590000"
    assert live.asked == [("timesales", "SPY261116C00590000", date(2026, 11, 13))]

    def refused(occ, day):
        raise replay_options.OptionsOff("The contract's trades could not be read: HTTP 500", 503)
    monkeypatch.setattr(replay_options, "trades", refused)
    with pytest.raises(self_check.CheckFailed, match="^timesales 503: The contract's trades could not be read: HTTP 500$"):
        self_check.check_replay(AT, {"spy": 590.37})


def test_a_ping_link_opens_the_desk_on_its_symbol(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("ALERT_APP_URL", "https://example.test")
    assert self_check.check_deep_links() == "/copilot-lab?symbol=SPY"
    monkeypatch.setenv("COPILOT_ENABLED", "false")
    with pytest.raises(self_check.CheckFailed, match="not the desk"):
        self_check.check_deep_links()


def test_the_desk_minute_dispatcher_answers_its_reads_inside_the_app(engine, kept, monkeypatch):
    from app.ai import copilot as copilot_module
    from app.engine import robinhood_book
    from app.routers import copilot as copilot_router
    monkeypatch.setattr(copilot_module, "settings", lambda: SimpleNamespace(enabled=True, evidence="live"))
    kicks = []
    monkeypatch.setattr(robinhood_book.feed, "_gate", lambda: ("ready", None, None))  # signed in: a snapshot read would kick
    monkeypatch.setattr(robinhood_book.feed, "_kick", lambda *a, **k: kicks.append("kick"))
    monkeypatch.setattr(paper_book, "_live_quotes", lambda symbols: pytest.fail("no quote read"))
    app = FastAPI()
    app.include_router(copilot_desk.router, prefix="/copilot")
    app.include_router(copilot_router.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    assert asyncio.run(self_check.check_desk_minute(app)) == "2 reads answered"
    assert kicks == []  # never starts a Robinhood read
    monkeypatch.setattr(copilot_module, "settings", lambda: SimpleNamespace(enabled=False))
    with pytest.raises(self_check.CheckFailed, match="^investigations 503, health 503$"):
        asyncio.run(self_check.check_desk_minute(app))


def test_the_desk_minute_dispatch_works_inside_the_real_app(kept, monkeypatch):
    """The production app's own routers and handlers, past none of its network-facing middleware."""
    from app.ai import copilot as copilot_module
    from app.main import app
    monkeypatch.setattr(copilot_module, "settings", lambda: SimpleNamespace(enabled=True, evidence="live"))
    monkeypatch.setattr(copilot_desk, "_robinhood_health", lambda now: {"state": "off"})
    assert asyncio.run(self_check.check_desk_minute(app)) == "2 reads answered"


def test_a_stale_option_quote_names_the_contract(live):
    live.quotes["SPY261116C00590000"] = q("SPY261116C00590000", 1.10, 1.14, OPEN - 300)  # 09:25:00
    with pytest.raises(self_check.CheckFailed, match=r"^no fresh SPY \$590 Call 11/16/26 quote since 09:25:00$"):
        self_check.check_paper_pricing(AT, {})
    del live.quotes["SPY261116C00590000"]
    with pytest.raises(self_check.CheckFailed, match="No quote for the \\$590 call right now"):
        self_check.check_paper_pricing(AT, {})


def test_the_health_check_fails_only_when_a_source_cannot_be_read(engine, kept, monkeypatch):
    monkeypatch.setattr(copilot_desk, "_robinhood_health", lambda now: {"state": "off"})
    holder = {}
    assert self_check.check_health(engine, AT, holder).startswith("8 sources read")
    monkeypatch.setattr(desk_health, "radar", lambda now, phase, regular: 1 / 0)
    with pytest.raises(self_check.CheckFailed, match="could not read Radar"):
        self_check.check_health(engine, AT, {})


# --------------------------------------------------------------------------- the run

def fake_checks(monkeypatch, *, hang=None, fail=None):
    def make(name, result):
        def check(*_args):
            if name == hang:
                time.sleep(2)
            if name == fail:
                raise RuntimeError("boom")
            return result
        return check
    monkeypatch.setattr(self_check, "check_paper_pricing", make("paper pricing", "priced"))
    monkeypatch.setattr(self_check, "check_replay", make("replay", "bars"))
    monkeypatch.setattr(self_check, "check_deep_links", make("deep links", "/copilot-lab?symbol=SPY"))

    def health(engine, now, holder):
        holder["health"] = {"overall": "ok", "sources": [{"id": "prices", "name": "Prices", "state": "live"}]}
        return "read"
    monkeypatch.setattr(self_check, "check_health", health)

    async def minute(app):
        return "answered"
    monkeypatch.setattr(self_check, "check_desk_minute", minute)


def checker(engine, sent, *, now=AT, session=lambda now: (int(OPEN), int(OPEN + 390 * 60)), timeout=5.0):
    return self_check.SelfCheck(engine, runner=lambda: runner(), clock=lambda: now, timeout=timeout, session=session,
                                send=lambda title, body, path: sent.append((title, body, path)))


def test_once_a_session_one_line_under_its_own_budget_and_kept_for_the_strip(engine, kept, monkeypatch):
    fake_checks(monkeypatch)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    sent = []
    check = checker(engine, sent)
    assert not checker(engine, sent, now=OPEN + 30).due(OPEN + 30)  # 09:30:30: before a minute after the open
    assert check.due(AT)
    entry = asyncio.run(check.run())
    assert sent == [("Self-check 09:31 ✅ all 6 OK", "Data: all live", "/copilot-lab")]
    assert entry["ping"] == "sent" and entry["failed"] == 0
    assert not check.due(AT + 60)  # once a day
    asyncio.run(check.run())
    assert len(sent) == 1
    with Session(engine) as db:
        pings = db.exec(select(PhonePing)).all()
        assert [(p.kind, p.decision) for p in pings] == [("self_check", "sent")]
        assert db.exec(select(PaperEvent)).all() == [] and db.exec(select(PaperRun)).all() == []  # nothing in his books
    kept_entry = json.loads((kept / "2026-11-16.json").read_text())
    assert kept_entry["line"] == "Self-check 09:31 ✅ all 6 OK"
    row = desk_health.self_check(AT + 600)
    assert (row["state"], row["line"]) == ("live", "All 6 OK 9:31")


def test_never_outside_a_regular_session_the_calendar_confirms(engine, kept, monkeypatch):
    sent = []
    holiday = checker(engine, sent, session=lambda now: None)
    assert not holiday.due(AT)
    # Without a calendar answer the clock hours are never trusted: a holiday could look like a session.
    monkeypatch.setattr(desk_sparks, "_session", lambda now: (date(2026, 11, 26), "regular", None, (int(OPEN), int(OPEN) + 1)))
    assert self_check.SelfCheck(engine, clock=lambda: AT).regular(AT) is None


def test_a_hanging_or_failing_check_never_blocks_the_others(engine, kept, monkeypatch):
    fake_checks(monkeypatch, hang="replay", fail="deep links")
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    sent = []
    entry = asyncio.run(checker(engine, sent, timeout=0.5).run())
    status = {r["name"]: (r["status"], r["detail"]) for r in entry["results"]}
    assert status["replay"] == ("fail", "no answer in 0.5 s")
    assert status["deep links"] == ("fail", "RuntimeError: boom")
    assert status["health strip"] == ("ok", "read") and status["paper pricing"] == ("ok", "priced")
    assert sent[0][0] == "Self-check 09:31 ⚠️ 2 of 6 failed: replay (no answer in 0.5 s), deep links (RuntimeError: boom)"
    row = desk_health.self_check(AT + 600)
    assert (row["state"], row["line"]) == ("down", "2 of 6 failed 9:31: replay, deep links")


def test_the_budget_holds_a_second_line_and_never_spends_another_kinds(engine, kept, monkeypatch):
    fake_checks(monkeypatch)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with Session(engine) as db:  # a line already sent today under self_check (a restart with the day's file gone)
        ticket = notification_policy.decide(db, sender="self_check", source_id="earlier", kind="self_check", title="x", body="", now=AT - 30)
        notification_policy.delivered(db, ticket, AT - 30)
        db.commit()
    sent = []
    entry = asyncio.run(checker(engine, sent).run())
    assert sent == [] and entry["ping"].startswith("held:")
    with Session(engine) as db:
        assert notification_policy.budget("paper") == 6
        assert {p.kind for p in db.exec(select(PhonePing)).all()} == {"self_check"}


def test_the_strip_before_today_s_run_and_when_switched_off(kept, monkeypatch):
    assert desk_health.self_check(AT)["state"] == "quiet"
    kept.mkdir(parents=True)
    (kept / "2026-11-13.json").write_text(json.dumps({"day": "2026-11-13", "at": OPEN - 3 * 86400 + 60, "state": "done",
                                                      "results": [{"name": n, "status": "ok"} for n in self_check.NAMES]}))
    row = desk_health.self_check(OPEN - 600)
    assert (row["state"], row["line"]) == ("quiet", "Last run all 6 OK Fri 9:31 · next a minute after the open")
    monkeypatch.setenv("SELF_CHECK_ENABLED", "false")
    assert desk_health.self_check(AT)["state"] == "off"
    assert not self_check.enabled()


def test_phone_sends_it_without_a_why_button():
    assert phone.with_why("self_check", ()) == ()


def test_an_off_check_and_an_unfinished_run_on_the_strip(kept):
    kept.mkdir(parents=True)
    results = [{"name": n, "status": "off" if n == "paper runner" else "ok"} for n in self_check.NAMES]
    (kept / "2026-11-16.json").write_text(json.dumps({"day": "2026-11-16", "at": AT, "state": "done", "results": results}))
    row = desk_health.self_check(AT + 600)
    assert (row["state"], row["line"]) == ("live", "5 of 6 OK 9:31, off: paper runner")
    (kept / "2026-11-16.json").write_text(json.dumps({"day": "2026-11-16", "at": AT, "state": "running"}))
    assert desk_health.self_check(AT + 30)["line"] == "Running now"
    row = desk_health.self_check(AT + 600)  # a restart mid-run: it never finished, and the strip says so
    assert (row["state"], row["line"]) == ("down", "Did not finish · started 9:31")


def test_an_unwritable_folder_never_reruns_the_day(engine, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(self_check, "ROOT", blocker / "self_check")  # under a file: every save fails
    fake_checks(monkeypatch)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    sent = []
    check = checker(engine, sent)
    assert check.due(AT)
    asyncio.run(check.run())
    assert not check.due(AT + 20)
    asyncio.run(check.run())
    assert len(sent) == 1
