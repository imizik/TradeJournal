"""Radar PR 5: news near each saved event, or a plain "cause unknown"."""
from datetime import UTC, datetime, timedelta
import copy
import json
from pathlib import Path
import sqlite3

import pytest

from app.engine import radar_news
from app.engine.chart_math import ET
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RadarStore
from tests.test_radar_runner import OPEN, Calendar, Quotes, _universe

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())
FIRST_SEEN = datetime(2026, 10, 20, 15, 12, 4, tzinfo=UTC)  # the sample event, 11:12:04 New York


def _event(n=1, minutes_after=0):
    event = copy.deepcopy(FIXTURE["event"])
    event["event_id"] = f"rad_test_{n}"
    event["first_seen_at"] = (FIRST_SEEN + timedelta(minutes=minutes_after)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return event


def _article(headline, at, symbols=("MU",), url=None):
    return {"id": hash(headline), "headline": headline, "summary": "", "symbols": list(symbols), "source": "benzinga",
            "created_at": at.isoformat().replace("+00:00", "Z"), "url": url or f"https://example.com/{abs(hash(headline))}"}


class Reader:
    def __init__(self, articles=(), fail=False):
        self.calls, self.articles, self.fail = [], list(articles), fail

    def __call__(self, symbols, start, end):
        self.calls.append((symbols, start, end))
        if self.fail:
            raise RuntimeError("Alpaca news timed out")
        return list(self.articles)


@pytest.fixture
def store(tmp_path):
    return RadarStore(tmp_path / "radar.sqlite")


def _after(minutes):
    return FIRST_SEEN + timedelta(minutes=minutes)


def test_first_check_then_one_recheck_after_fifteen_minutes(store):
    store.append_event(_event())
    reader = Reader()
    assert radar_news.enrich(store, "2026-10-20", _after(1), reader) == 1
    assert radar_news.enrich(store, "2026-10-20", _after(10), reader) == 0  # too soon to recheck
    assert radar_news.enrich(store, "2026-10-20", _after(16), reader) == 1  # 15 minutes after the first check
    assert radar_news.enrich(store, "2026-10-20", _after(40), reader) == 0  # two checks at most
    assert [c["checked_at"] for c in store.news_checks("rad_test_1")] == ["2026-10-20T15:13:04.000Z", "2026-10-20T15:28:04.000Z"]
    assert len(reader.calls) == 2


def test_no_check_once_the_event_is_two_hours_old(store):
    store.append_event(_event())
    reader = Reader()
    assert radar_news.enrich(store, "2026-10-20", _after(120), reader) == 0
    assert reader.calls == [] and store.news_checks("rad_test_1") == []
    # A first check at 1h50 gets no recheck past the two-hour mark.
    assert radar_news.enrich(store, "2026-10-20", _after(110), reader) == 1
    assert radar_news.enrich(store, "2026-10-20", _after(126), reader) == 0


def test_at_most_three_requests_per_pass_and_leftovers_wait(store):
    for n in range(5):
        store.append_event(_event(n, minutes_after=n))
    reader = Reader()
    assert radar_news.enrich(store, "2026-10-20", _after(6), reader) == 3
    assert [c[0] for c in reader.calls] == [["MU"]] * 3
    assert [bool(store.news_checks(f"rad_test_{n}")) for n in range(5)] == [True, True, True, False, False]
    assert radar_news.enrich(store, "2026-10-20", _after(7), reader) == 2  # the leftovers, oldest first
    assert all(store.news_checks(f"rad_test_{n}") for n in range(5))


def test_found_keeps_five_catalyst_first_with_the_before_after_marker(store):
    store.append_event(_event())
    articles = [_article(f"Analyst chatter {i} on MU", _after(-i - 1)) for i in range(5)]
    articles += [_article("Micron raises guidance", _after(-30)),
                 _article("Micron upgrade after the open", _after(3)),
                 _article("Old story outside the window", _after(-25 * 60)),
                 _article("Unrelated symbol story", _after(-2), symbols=("AAPL",)),
                 _article("Not https", _after(-2), url="http://example.com/x")]
    reader = Reader(articles)
    radar_news.enrich(store, "2026-10-20", _after(5), reader)
    [(symbols, start, end)] = reader.calls
    assert symbols == ["MU"] and start == FIRST_SEEN - timedelta(hours=24) and end == _after(5)
    [check] = store.news_checks("rad_test_1")
    assert check["status"] == "found" and len(check["headlines"]) == 5
    titles = [h["headline"] for h in check["headlines"]]
    assert titles[:2] == ["Micron upgrade after the open", "Micron raises guidance"]  # catalyst words first, newest first
    assert titles[2:] == ["Analyst chatter 0 on MU", "Analyst chatter 1 on MU", "Analyst chatter 2 on MU"]
    assert [h["timing"] for h in check["headlines"]] == ["after", "before", "before", "before", "before"]
    assert check["headlines"][0] == {"headline": "Micron upgrade after the open", "source": "benzinga",
                                     "published_at": "2026-10-20T15:15:04.000Z", "url": check["headlines"][0]["url"],
                                     "symbols": ["MU"], "timing": "after"}


def test_none_found_and_unavailable_stay_distinct(store):
    store.append_event(_event(1))
    store.append_event(_event(2))
    store.append_news(radar_news.check(_event(1), _after(1), Reader([_article("Stale", _after(-25 * 60))])))
    store.append_news(radar_news.check(_event(2), _after(1), Reader(fail=True)))
    assert [c["status"] for c in store.news_checks("rad_test_1")] == ["none_found"]
    assert [c["status"] for c in store.news_checks("rad_test_2")] == ["unavailable"]
    malformed = radar_news.check(_event(1), _after(1), lambda *a: {"news": "not a list"})
    assert malformed["status"] == "unavailable" and malformed["headlines"] == []


def test_a_refused_provider_is_unavailable_not_none_found(store, monkeypatch):
    from app.engine import news
    store.append_event(_event())
    monkeypatch.setattr(news, "_alpaca_get_fast", lambda path, params: {})  # what a 403/404 returns
    radar_news.enrich(store, "2026-10-20", _after(1))
    monkeypatch.setattr(news, "_alpaca_get_fast", lambda path, params: {"news": []})
    radar_news.enrich(store, "2026-10-20", _after(17))
    assert [c["status"] for c in store.news_checks("rad_test_1")] == ["unavailable", "none_found"]


def test_original_event_is_unchanged_and_news_rows_are_immutable(store):
    store.append_event(FIXTURE["event"])
    store.append_revision(FIXTURE["revisions"][0])
    radar_news.enrich(store, "2026-10-20", _after(2), Reader([_article("Micron raises guidance", _after(-30))]))
    assert store.event(FIXTURE["event"]["event_id"]) == FIXTURE["event"]
    assert store.revisions(FIXTURE["event"]["event_id"]) == FIXTURE["revisions"]
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE event_news SET status='none_found'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM event_news")
    with pytest.raises(ValueError):
        store.append_news({"event_id": "x", "checked_at": "t", "status": "maybe", "headlines": []})


def _runner(store, reader, hour=11, minute=15):
    clock = lambda: datetime(2026, 10, 20, hour, minute, 5, tzinfo=ET).timestamp()  # noqa: E731
    return RadarRunner(store, Calendar(OPEN), universe=_universe(10), quotes=Quotes(), clock=clock, news=reader)


def test_runner_checks_news_after_the_pass_and_a_provider_failure_never_breaks_it(store):
    store.append_event(_event())
    pass_id = _runner(store, Reader(fail=True)).run_once()
    [row] = store.passes()
    assert row["id"] == pass_id and row["status"] == "ok" and len(store.quotes(pass_id)) == 10
    assert [c["status"] for c in store.news_checks("rad_test_1")] == ["unavailable"]


def test_runner_survives_an_enrichment_crash(store, monkeypatch):
    store.append_event(_event())
    monkeypatch.setattr(radar_news, "enrich", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert _runner(store, Reader()).run_once() is not None
    assert store.passes()[0]["status"] == "ok"


def test_runner_checks_no_news_outside_regular_hours(store):
    store.append_event(_event())
    reader = Reader()
    assert _runner(store, reader, hour=16, minute=30).run_once() is None
    assert reader.calls == [] and store.news_checks("rad_test_1") == []


def test_existing_file_without_the_news_table_still_opens(tmp_path):
    path = tmp_path / "old.sqlite"
    RadarStore(path).append_event(FIXTURE["event"])
    with sqlite3.connect(path) as db:
        for trigger in ("event_news_no_update", "event_news_no_delete"):
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE event_news")
    store = RadarStore(path)
    assert store.event(FIXTURE["event"]["event_id"]) == FIXTURE["event"]
    assert store.latest_news() == {}
    store.append_news(FIXTURE["news_checks"][0])
    assert store.news_checks(FIXTURE["event"]["event_id"]) == [FIXTURE["news_checks"][0]]
