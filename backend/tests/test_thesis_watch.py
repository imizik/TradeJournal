"""Thesis watch (docs/copilot-lab.md § Thesis watch): watched set, schedule, each trigger, dedupe, caps, the reassess
hand-off and the prepared deep link. Seeded journal, stubbed news, quotes, bars and earnings; nothing leaves the test."""
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import copilot_investigations as inv
from app.engine import jo_briefing, research_queue, thesis_watch
from app.engine.chart_math import ET
from app.engine.thesis_watch import ThesisWatch
from app.models import Account, Fill, ResearchJob, ThesisWatchTrigger
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=1), UUID(int=2)
WED = date(2026, 10, 21)
n = iter(range(100, 10_000))


def at(hhmm: str, day: date = WED) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET)


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> float:
        return self.now.timestamp()


class Calendar:
    def hours(self, day):
        if day.weekday() >= 5 or day == date(2026, 10, 22):  # a Thursday holiday, for the trading-day count
            return {"status": "closed"}
        return {"status": "open", "open": 570, "close": 960}


class Readers:
    """Stubbed providers; each call is counted so the caps on provider reads can be checked."""

    def __init__(self):
        self.articles, self.quotes, self.bars, self.earnings = [], {}, {}, {}
        self.calls = {"news": [], "quotes": [], "earnings": []}
        self.fail = set()

    def news(self, symbols, start, end):
        self.calls["news"].append((list(symbols), start, end))
        if "news" in self.fail:
            raise RuntimeError("alpaca down")
        return list(self.articles)

    def quote(self, symbols):
        self.calls["quotes"].append(list(symbols))
        if "quotes" in self.fail:
            raise RuntimeError("tradier down")
        return {s: self.quotes[s] for s in symbols if s in self.quotes}

    def bar(self, symbol, day):
        return self.bars.get((symbol, day))

    def earning(self, symbols, today):
        self.calls["earnings"].append(list(symbols))
        return {s: self.earnings.get(s) for s in symbols}


class Phone:
    def __init__(self):
        self.sent = []
        self.fail = False

    def __call__(self, title, message, *, path="", direct_click=False, **kwargs):
        if self.fail:
            raise RuntimeError("ntfy refused")
        self.sent.append({"title": title, "message": message, "path": path, "direct_click": direct_click})
        return f"msg-{len(self.sent)}"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("THESIS_WATCH_ENABLED", "THESIS_WATCH_MOVE_PCT", "THESIS_WATCH_DAILY_CAP", "RESEARCH_QUEUE_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/trade-journal")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def world(engine):
    readers, phone, clock = Readers(), Phone(), Clock(at("10:00"))
    watch = ThesisWatch(engine, Calendar(), clock=clock, news=readers.news, quotes=readers.quote, bars=readers.bar,
                        earnings=readers.earning, publish=phone)
    return watch, readers, phone, clock


def hold(engine, symbol, account=ROTH):
    k = next(n)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=k), account_id=account, ticker=symbol, instrument_type="stock", side="buy", contracts=10,
                    price=120, executed_at=datetime(2026, 10, 20, 10, 5), raw_email_id=f"gmail:{k}"))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def investigate(engine, symbol, as_of=None, status="open"):
    evidence = [{"tool": "get_quotes", "as_of": as_of, "kind": "fetched"}] if as_of else []
    with Session(engine) as db:
        return inv.create(inv.InvestigationFields(title=f"{symbol} thesis", symbol=symbol, status=status, evidence=evidence),
                          session=db)["id"]


def thesis(engine, symbol, text="A two-year infrastructure thesis."):
    with Session(engine) as db:
        receipt = jo_briefing.save_memory(db, jo_briefing.MemorySave(
            operation_id=f"op-{symbol}-{next(n)}", kind="thesis", symbol=symbol, original_text=text,
            source="owner_statement", status="active", owner_confirmed=True))
        return receipt["memory_id"]


def article(symbol, headline, url, when, source="Benzinga"):
    return {"id": url, "headline": headline, "summary": "", "symbols": [symbol], "source": source,
            "created_at": when.astimezone(UTC).isoformat().replace("+00:00", "Z"), "url": url}


def triggers(engine):
    with Session(engine) as db:
        return db.exec(select(ThesisWatchTrigger).order_by(ThesisWatchTrigger.fired_at)).all()


def link(path):
    parts = urlsplit(path)
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


# --------------------------------------------------------------------------- off by default, watched set

def test_off_by_default_and_the_runner_is_not_built(engine, monkeypatch):
    assert thesis_watch.enabled() is False and thesis_watch.watch_from_env(engine) is None
    assert thesis_watch.move_pct() == 4.0 and thesis_watch.daily_cap() == 4
    monkeypatch.setenv("THESIS_WATCH_MOVE_PCT", "nope")
    monkeypatch.setenv("THESIS_WATCH_DAILY_CAP", "0")
    assert thesis_watch.move_pct() == 4.0 and thesis_watch.daily_cap() == 4  # malformed falls back
    monkeypatch.setenv("THESIS_WATCH_MOVE_PCT", "2.5")
    monkeypatch.setenv("THESIS_WATCH_DAILY_CAP", "2")
    assert thesis_watch.move_pct() == 2.5 and thesis_watch.daily_cap() == 2


def test_the_watched_set_is_held_first_then_investigations_then_theses_capped_at_25(engine):
    hold(engine, "ZZZ")
    hold(engine, "WBL", account=WEBULL)  # dormant by the owner's choice: never watched
    hold(engine, "NBIS")
    investigate(engine, "NBIS", as_of="2026-10-19T15:00:00Z")  # an older open investigation: the latest updated one is used
    first = investigate(engine, "NBIS", as_of="2026-10-20T15:00:00Z")
    investigate(engine, "CRWV")
    investigate(engine, "OLD", status="closed")  # closed: not watched
    thesis(engine, "NBIS")
    for i in range(30):
        thesis(engine, "T" + chr(65 + i // 26) + chr(65 + i % 26))
    memory = thesis(engine, "APLD")  # the newest thesis: theses are watched newest first, so the cap drops old ones
    with Session(engine) as db:
        rows = thesis_watch.watched_set(db)
    assert len(rows) == 25
    assert [r.symbol for r in rows[:5]] == ["NBIS", "ZZZ", "CRWV", "APLD", "TBD"]
    nbis = rows[0]
    assert nbis.held and nbis.investigation["id"] == first and nbis.memory_id and nbis.reasons == ["held", "investigation", "thesis"]
    assert nbis.investigation["as_of"] == datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    assert rows[3].memory_id == memory and rows[3].investigation is None and not rows[3].held
    assert "WBL" not in {r.symbol for r in rows} and "OLD" not in {r.symbol for r in rows}


# --------------------------------------------------------------------------- schedule

def test_passes_every_15_minutes_in_regular_hours_and_once_in_the_morning(engine, world):
    watch, readers, phone, clock = world
    thesis(engine, "NBIS")
    clock.now = at("07:59")
    assert watch.run_once() is None  # before the morning pass
    clock.now = at("08:00")
    assert watch.run_once() is not None and watch.run_once() is None  # once in the morning
    assert readers.calls["news"][0][1] == at("08:00") - thesis_watch.NEWS_LOOKBACK_MORNING  # overnight lookback
    clock.now = at("09:29")
    assert watch.run_once() is None  # the morning pass is done; the session has not opened
    clock.now = at("09:30")
    assert watch.run_once() is not None  # first regular pass
    assert readers.calls["news"][-1][1] == at("08:00")  # since the last pass, not a fixed lookback
    clock.now = at("09:44")
    assert watch.run_once() is None
    clock.now = at("09:45")
    assert watch.run_once() is not None
    clock.now = at("16:00")
    assert watch.run_once() is None  # closed
    clock.now = at("10:00", date(2026, 10, 24))  # Saturday
    assert watch.run_once() is None
    clock.now = at("10:00", date(2026, 10, 22))  # holiday on the stub calendar
    assert watch.run_once() is None
    assert len(readers.calls["quotes"]) == 3  # one batched quote read per pass, none outside


def test_a_pass_with_nothing_watched_reads_nothing(world):
    watch, readers, phone, clock = world
    result = watch.run_once()
    assert result == {"day": "2026-10-21", "watched": [], "fired": [], "skipped": [], "issues": []}
    assert readers.calls == {"news": [], "quotes": [], "earnings": []}


# --------------------------------------------------------------------------- news

def test_a_new_headline_pings_once_with_the_what_changed_link_and_dedupes_by_url(engine, world):
    watch, readers, phone, clock = world
    saved = investigate(engine, "NBIS")
    readers.articles = [article("NBIS", "Nebius‮ wins $3B deal\x07 with Meta", "https://benzinga.com/a/1", at("09:52"))]
    result = watch.run_once()
    assert [f["kind"] for f in result["fired"]] == ["news"] and result["skipped"] == []
    assert phone.sent == [{"title": "New on NBIS since your thesis", "message": "Nebius wins $3B deal with Meta (Benzinga, 09:52)",
                           "path": phone.sent[0]["path"], "direct_click": True}]
    path, query = link(phone.sent[0]["path"])
    assert path == "/copilot-lab" and query["investigation"] == saved
    assert query["context"].startswith('New since my thesis: "Nebius wins $3B deal with Meta (Benzinga, 09:52)". What changed? Use get_investigation_changes for investigation ')
    assert query["context"].endswith(f"{saved} and say whether it still holds.") and len(query["context"]) <= 300
    [row] = triggers(engine)
    assert row.delivery == "sent" and row.message_id == "msg-1" and str(row.investigation_id) == saved and row.memory_id is None
    assert row.dedupe_key == "news:NBIS:https://benzinga.com/a/1" and row.reassess_job_id is None  # the queue is off
    # The same headline again (a restart's lookback) is written nowhere and sent nowhere.
    clock.now = at("10:15")
    readers.articles.append(article("NBIS", "Nebius wins $3B deal with Meta", "https://benzinga.com/a/1", at("09:52")))
    assert watch.run_once()["fired"] == [] and len(triggers(engine)) == 1 and len(phone.sent) == 1


def test_a_thesis_with_no_investigation_links_the_symbol_with_the_question_prepared(engine, world):
    watch, readers, phone, clock = world
    memory = thesis(engine, "APLD")
    readers.articles = [article("APLD", "Applied Digital " + "x" * 400, "https://benzinga.com/a/2", at("09:58"), source=None)]
    watch.run_once()
    path, query = link(phone.sent[0]["path"])
    assert path == "/copilot-lab" and query["symbol"] == "APLD" and "investigation" not in query
    assert query["context"].startswith('New since my thesis: "Applied Digital xxx') and query["context"].endswith('…". Does it still hold?')
    assert len(query["context"]) <= 300
    [row] = triggers(engine)
    assert row.memory_id == UUID(memory) and row.investigation_id is None and not row.held


def test_one_ping_per_symbol_per_day_and_old_or_ineligible_headlines_do_not_count(engine, world):
    watch, readers, phone, clock = world
    investigate(engine, "NBIS")
    readers.articles = [
        article("NBIS", "Second headline", "https://benzinga.com/a/3", at("09:55")),
        article("NBIS", "First headline", "https://benzinga.com/a/4", at("09:50")),
        article("NBIS", "Before the lookback", "https://benzinga.com/a/5", at("09:00")),
        article("NBIS", "Not https", "http://benzinga.com/a/6", at("09:56")),
        {"id": 7, "headline": "Malformed", "symbols": "NBIS", "created_at": "x", "url": "https://benzinga.com/a/7"},
        article("OTHER", "Not watched", "https://benzinga.com/a/8", at("09:57")),
    ]
    result = watch.run_once()
    assert [f["text"] for f in result["fired"]] == ["Second headline (Benzinga, 09:55)"] and len(phone.sent) == 1
    clock.now = at("10:15")
    readers.articles = [article("NBIS", "Third headline", "https://benzinga.com/a/9", at("10:05"))]
    result = watch.run_once()
    assert result["fired"] == [] and [s["reason"] for s in result["skipped"]] == ["already told today"]
    assert [(t.text, t.delivery) for t in triggers(engine)] == [("Second headline (Benzinga, 09:55)", "sent"), ("Third headline (Benzinga, 10:05)", "skipped")]
    assert len(phone.sent) == 1


def test_a_catalyst_headline_wins_the_symbol_s_one_ping_and_a_news_outage_is_an_issue(engine, world):
    watch, readers, phone, clock = world
    investigate(engine, "NBIS")
    readers.articles = [article("NBIS", "Shares tick up", "https://benzinga.com/a/10", at("09:59")),
                        article("NBIS", "Nebius reports earnings beat", "https://benzinga.com/a/11", at("09:50"))]
    assert [f["text"] for f in watch.run_once()["fired"]] == ["Nebius reports earnings beat (Benzinga, 09:50)"]
    clock.now = at("10:15")
    readers.fail.add("news")
    result = watch.run_once()
    assert result["issues"] == ["news unavailable: RuntimeError"] and result["fired"] == [] and len(triggers(engine)) == 1


# --------------------------------------------------------------------------- moves

def test_a_move_since_the_investigation_s_evidence_uses_that_day_s_cached_bars(engine, world):
    watch, readers, phone, clock = world
    saved = investigate(engine, "NBIS", as_of=at("14:30", date(2026, 10, 20)).isoformat())
    readers.bars[("NBIS", date(2026, 10, 20))] = [
        {"time": int(at("14:29", date(2026, 10, 20)).timestamp()), "close": 100.0},
        {"time": int(at("14:30", date(2026, 10, 20)).timestamp()), "close": 101.0},
        {"time": int(at("15:59", date(2026, 10, 20)).timestamp()), "close": 110.0},  # after the as-of: not the reference
    ]
    readers.quotes["NBIS"] = {"last": 104.9, "previous_close": 110.0}
    assert watch.run_once()["fired"] == []  # +3.9% since the evidence (not -4.6% since the prior close)
    clock.now = at("10:15")
    readers.quotes["NBIS"] = {"last": 105.1, "previous_close": 110.0}
    [fired] = watch.run_once()["fired"]
    assert fired["kind"] == "move" and fired["text"] == "NBIS +4.1% since your investigation's evidence (Oct 20 14:30 NY): 101 → 105.1"
    assert phone.sent[-1]["message"] == fired["text"] and link(phone.sent[-1]["path"])[1]["investigation"] == saved
    [row] = triggers(engine)
    assert row.dedupe_key == f"move:NBIS:evidence:{saved}:2026-10-20T18:30:00+00:00"
    clock.now = at("10:30")
    readers.quotes["NBIS"] = {"last": 120.0, "previous_close": 110.0}
    assert watch.run_once()["fired"] == [] and len(triggers(engine)) == 1  # told once for this evidence


def test_a_thesis_or_an_uncached_evidence_day_moves_against_the_prior_close(engine, world, monkeypatch):
    watch, readers, phone, clock = world
    thesis(engine, "APLD")
    investigate(engine, "NBIS", as_of=at("14:30", date(2026, 10, 20)).isoformat())  # no bars cached for that day
    hold(engine, "ZZZ")  # held with neither: the prior close too
    readers.quotes = {"APLD": {"last": 95.9, "previous_close": 100.0}, "NBIS": {"last": 104.0, "previous_close": 100.0},
                      "ZZZ": {"last": 50.0, "previous_close": 52.0}}
    result = watch.run_once()
    assert sorted(f["text"] for f in result["fired"]) == ["APLD -4.1% since the prior close: 100 → 95.9",
                                                          "NBIS +4.0% since the prior close: 100 → 104"]
    assert {t.dedupe_key for t in triggers(engine)} == {"move:APLD:close:2026-10-21", "move:NBIS:close:2026-10-21"}
    clock.now = at("10:15")
    monkeypatch.setenv("THESIS_WATCH_MOVE_PCT", "3")
    result = watch.run_once()
    assert [f["text"] for f in result["fired"]] == ["ZZZ -3.8% since the prior close: 52 → 50"]
    readers.fail.add("quotes")
    clock.now = at("10:30")
    assert watch.run_once()["issues"] == ["quotes unavailable: RuntimeError"]


# --------------------------------------------------------------------------- earnings

def test_earnings_inside_two_trading_days_fires_once(engine, world):
    watch, readers, phone, clock = world
    investigate(engine, "NBIS")
    thesis(engine, "APLD")
    thesis(engine, "CRWV")
    thesis(engine, "ZZZ")
    # Wed 21: Thu 22 is a stub holiday, so Mon 26 is two trading days out (Fri 23, Mon 26); Tue 27 is three.
    readers.earnings = {"NBIS": "2026-10-26", "APLD": "2026-10-27", "CRWV": "2026-10-21", "ZZZ": "not a date"}
    result = watch.run_once()
    assert sorted(f["text"] for f in result["fired"]) == ["Earnings Mon Oct 26, in 2 trading days", "Earnings Wed Oct 21, today"]
    assert readers.calls["earnings"] == [["NBIS", "ZZZ", "CRWV", "APLD"]]  # one batched read: investigations, then theses newest first
    clock.now = at("10:15")
    assert watch.run_once()["fired"] == [] and len(triggers(engine)) == 2
    assert {t.dedupe_key for t in triggers(engine)} == {"earnings:NBIS:2026-10-26", "earnings:CRWV:2026-10-21"}


# --------------------------------------------------------------------------- caps, outbox, hand-off

def test_the_daily_cap_records_the_rest_as_skipped_and_a_refused_push_is_failed_not_retried(engine, world, monkeypatch):
    watch, readers, phone, clock = world
    for symbol in ("A", "B", "C", "D", "E", "F"):
        thesis(engine, symbol)
    readers.articles = [article(s, f"{s} news", f"https://benzinga.com/{s}", at("09:50")) for s in "ABCDEF"]
    result = watch.run_once()
    assert len(result["fired"]) == 4 and [s["reason"] for s in result["skipped"]] == ["daily cap reached"] * 2
    assert len(phone.sent) == 4
    clock.now = at("10:00", date(2026, 10, 23))  # a new day: the cap resets; the same URLs stay deduped
    watch._last_pass = None
    readers.articles = [article("E", "E news again", "https://benzinga.com/E2", at("09:50", date(2026, 10, 23)))]
    phone.fail = True
    [failed] = watch.run_once()["fired"]
    assert failed["delivery"] == "failed" and failed["reason"].startswith("RuntimeError") and len(phone.sent) == 4
    clock.now = at("10:15", date(2026, 10, 23))
    phone.fail = False
    readers.articles = [article("E", "E news thrice", "https://benzinga.com/E3", at("10:05", date(2026, 10, 23)))]
    assert [s["reason"] for s in watch.run_once()["skipped"]] == ["already told today"]  # a failed push may have landed
    monkeypatch.delenv("NTFY_URL")
    clock.now = at("10:30", date(2026, 10, 23))
    readers.articles = [article("A", "A news again", "https://benzinga.com/A2", at("10:20", date(2026, 10, 23)))]
    assert [s["reason"] for s in watch.run_once()["skipped"]] == ["ntfy not configured"]


def test_with_the_research_queue_on_a_fired_trigger_queues_one_reassess_job_a_day(engine, world, monkeypatch):
    watch, readers, phone, clock = world
    saved = investigate(engine, "NBIS")
    thesis(engine, "APLD")
    monkeypatch.setenv("RESEARCH_QUEUE_ENABLED", "true")
    readers.articles = [article("NBIS", "Nebius news", "https://benzinga.com/n1", at("09:50")),
                        article("APLD", "Applied news", "https://benzinga.com/a1", at("09:50"))]
    result = watch.run_once()
    assert len(result["fired"]) == 2 and len(phone.sent) == 2  # the ping still goes; the queue's result ping is its own
    with Session(engine) as db:
        jobs = db.exec(select(ResearchJob)).all()
        assert len(jobs) == 1 and jobs[0].kind == "reassess" and jobs[0].dedupe_key == f"reassess:{saved}:2026-10-21"
        assert research_queue.view(jobs[0])["input"] == {"investigation_id": saved, "from_investigation": saved,
                                                         "requested_by": "thesis_watch", "trigger": "news"}
        nbis = db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.symbol == "NBIS")).one()
        apld = db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.symbol == "APLD")).one()
        assert nbis.reassess_job_id == jobs[0].id and apld.reassess_job_id is None  # no investigation, nothing to reassess
    clock.now = at("10:00", date(2026, 10, 23))
    watch._last_pass = None
    readers.quotes["NBIS"] = {"last": 110.0, "previous_close": 100.0}
    readers.articles = []
    with Session(engine) as db:  # the queue's own stale trigger already queued today's job: the key is shared
        research_queue.enqueue("reassess", {"investigation_id": saved}, f"reassess:{saved}:2026-10-23", db)
    [fired] = watch.run_once()["fired"]
    assert fired["kind"] == "move"
    with Session(engine) as db:
        assert len(db.exec(select(ResearchJob)).all()) == 2
        assert str(db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.kind == "move")).one().reassess_job_id) == \
            str(db.exec(select(ResearchJob).where(ResearchJob.dedupe_key == f"reassess:{saved}:2026-10-23")).one().id)


def test_a_skipped_move_or_earnings_comes_back_another_day_but_a_told_one_does_not(engine, world):
    watch, readers, phone, clock = world
    saved = investigate(engine, "NBIS", as_of=at("14:30", date(2026, 10, 19)).isoformat())
    readers.bars[("NBIS", date(2026, 10, 19))] = [{"time": int(at("14:30", date(2026, 10, 19)).timestamp()), "close": 100.0}]
    readers.quotes["NBIS"] = {"last": 105.0, "previous_close": 104.0}
    readers.earnings = {"NBIS": "2026-10-23"}
    readers.articles = [article("NBIS", "News first", "https://benzinga.com/f", at("09:50"))]
    result = watch.run_once()  # the news ping takes the day; the move and the earnings are skipped
    assert [f["kind"] for f in result["fired"]] == ["news"] and sorted(s["kind"] for s in result["skipped"]) == ["earnings", "move"]
    assert {t.dedupe_key for t in triggers(engine) if t.delivery == "skipped"} == {
        f"move:NBIS:evidence:{saved}:2026-10-19T18:30:00+00:00#skipped:2026-10-21", "earnings:NBIS:2026-10-23#skipped:2026-10-21"}
    clock.now = at("10:15")
    assert watch.run_once()["skipped"] == []  # the same day: written once
    clock.now = at("10:00", date(2026, 10, 23))
    watch._last_pass, readers.articles = None, []
    result = watch.run_once()  # still +5% since that evidence: told now; earnings today takes the next day's one ping
    assert [f["text"] for f in result["fired"]] == ["NBIS +5.0% since your investigation's evidence (Oct 19 14:30 NY): 100 → 105"]
    assert [(s["kind"], s["reason"]) for s in result["skipped"]] == [("earnings", "already told today")]
    clock.now = at("10:00", date(2026, 10, 26))
    watch._last_pass = None
    assert watch.run_once()["fired"] == [] and watch.run_once() is None  # told once for this evidence; nothing new


def test_an_investigation_saved_today_has_no_move_reference_yet(engine, world):
    watch, readers, phone, clock = world
    investigate(engine, "NBIS", as_of=at("09:45").isoformat())  # the owner just read the price: no "since the prior close"
    readers.quotes["NBIS"] = {"last": 106.0, "previous_close": 100.0}
    assert watch.run_once()["fired"] == [] and triggers(engine) == []


def test_the_owner_s_own_investigation_is_preferred_and_a_research_output_is_never_reassessed(engine, world, monkeypatch):
    watch, readers, phone, clock = world
    monkeypatch.setenv("RESEARCH_QUEUE_ENABLED", "true")
    with Session(engine) as db:
        own = inv.create(inv.InvestigationFields(title="NBIS thesis", symbol="NBIS"), session=db)["id"]
        inv.save_research_result(title="Reassess: NBIS thesis", symbol="NBIS", findings={"summary": "holds"}, session=db)  # newer, but an output
        only_output = inv.save_research_result(title="CRWV deal", symbol="CRWV", findings={"summary": "terms"}, session=db)["id"]
    with Session(engine) as db:
        rows = {r.symbol: r for r in thesis_watch.watched_set(db)}
    assert rows["NBIS"].investigation["id"] == own and rows["CRWV"].investigation["id"] == only_output
    readers.articles = [article("NBIS", "Nebius news", "https://benzinga.com/n", at("09:50")), article("CRWV", "CoreWeave news", "https://benzinga.com/c", at("09:50"))]
    watch.run_once()
    with Session(engine) as db:
        jobs = db.exec(select(ResearchJob)).all()
    assert [j.dedupe_key for j in jobs] == [f"reassess:{own}:2026-10-21"]  # the research output is re-checked by tap only
    assert link(phone.sent[1]["path"])[1]["investigation"] == only_output


def test_one_trigger_s_failure_does_not_lose_the_others(engine, world, monkeypatch):
    watch, readers, phone, clock = world
    thesis(engine, "APLD")
    thesis(engine, "NBIS")
    readers.articles = [article("NBIS", "Nebius news", "https://benzinga.com/n", at("09:50")), article("APLD", "Applied news", "https://benzinga.com/a", at("09:50"))]
    real = watch._queue_reassess
    monkeypatch.setattr(thesis_watch, "deep_link", lambda row, text: (_ for _ in ()).throw(RuntimeError("boom")) if row.symbol == "NBIS" else f"/copilot-lab?symbol={row.symbol}")
    result = watch.run_once()
    assert result["issues"] == ["news NBIS not recorded: RuntimeError"] and [f["symbol"] for f in result["fired"]] == ["APLD"]
    assert [t.symbol for t in triggers(engine)] == ["APLD"] and real is watch._queue_reassess


# --------------------------------------------------------------------------- the lab's Open threads row

def test_recent_triggers_per_investigation_newest_first_and_at_most_three(engine, world):
    watch, readers, phone, clock = world
    saved = investigate(engine, "NBIS")
    other = investigate(engine, "CRWV")
    readers.articles = [article("NBIS", "One", "https://benzinga.com/1", at("09:50"))]
    watch.run_once()
    clock.now, readers.articles = at("10:15"), []
    readers.quotes["NBIS"] = {"last": 110.0, "previous_close": 100.0}
    watch.run_once()
    clock.now, readers.quotes = at("10:30"), {}
    readers.earnings = {"NBIS": "2026-10-23"}
    watch.run_once()
    clock.now, readers.earnings = at("10:45"), {}
    readers.articles = [article("NBIS", "Two", "https://benzinga.com/2", at("10:35"))]
    watch.run_once()
    assert len(triggers(engine)) == 4
    with Session(engine) as db:
        recent = thesis_watch.recent_for(db, [saved, other, "not-a-uuid"])
    assert set(recent) == {saved}
    assert [(r["kind"], r["text"], r["delivery"]) for r in recent[saved]] == [
        ("news", "Two (Benzinga, 10:35)", "skipped"), ("earnings", "Earnings Fri Oct 23, next trading day", "skipped"),
        ("move", "NBIS +10.0% since the prior close: 100 → 110", "skipped")]  # the oldest, the sent one, is past the three
    assert recent[saved][0]["reason"] == "already told today" and recent[saved][0]["path"].startswith("/copilot-lab?investigation=")
    assert set(recent[saved][0]) == {"kind", "text", "fired_at", "delivery", "reason", "path"}


def test_the_threads_route_carries_each_open_investigation_s_triggers(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import delete
    from app.ai import copilot_context
    from app.database import engine as app_engine
    from app.main import app
    with Session(app_engine) as db:
        db.exec(delete(ThesisWatchTrigger))
        db.commit()
        saved = inv.create(inv.InvestigationFields(title="NBIS thesis", symbol="NBIS"), session=db)["id"]
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key=f"news:NBIS:https://benzinga.com/t/{saved}",
                                  investigation_id=UUID(saved), day="2026-10-21", text="Nebius news (Benzinga, 09:50)",
                                  path=f"/copilot-lab?investigation={saved}", delivery="sent", message_id="m"))
        db.commit()
    pack = {"as_of": "2026-10-21T14:00:00Z", "positions": {"state": "ok", "count": 0, "positions": []},
            "investigations": {"state": "ok", "investigations": [{"id": saved, "source": "copilot", "title": "NBIS thesis", "status": "open", "updated_at": "x"}]},
            "watches": {"state": "unavailable"}}
    monkeypatch.setattr(copilot_context, "owner_context", lambda symbol, session=None, now=None, bounded=True: pack)
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_EVIDENCE", "live")
    with TestClient(app) as client:
        body = client.get("/copilot/threads").json()
    [row] = body["investigations"]["investigations"]
    assert [(w["kind"], w["text"], w["delivery"]) for w in row["watch"]] == [("news", "Nebius news (Benzinga, 09:50)", "sent")]
    assert set(body) == {"positions", "investigations", "watches", "as_of"}
