"""The brief scorecard (``app/engine/brief_scorecard.py``, ``GET /copilot/brief-scorecard``): the named symbols, the excess
and hit arithmetic on fixture bars, unknown and in-progress days, the cache, and the route's gates. Offline: bars are
stubbed, never fetched."""
from datetime import date, datetime
import json

import pytest
from sqlmodel import Session, delete

from app.database import engine
from app.engine import brief_scorecard, ping_images
from app.engine.chart_math import ET
from app.models import CopilotInvestigation, PremarketPrep
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

THU, FRI = date(2026, 11, 5), date(2026, 11, 6)
KNOWN = frozenset({"SPY", "QQQ", "SMH", "NVDA", "CRWV", "APLD", "AI", "MA", "S", "U"})


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        db.exec(delete(PremarketPrep))
        db.exec(delete(CopilotInvestigation))
        db.commit()
    brief_scorecard._cache.clear()
    yield
    brief_scorecard._cache.clear()


def session_bars(day, open_, close, *, minutes=390, start_late=False):
    """Regular-session minutes from 09:30 (or 09:31), the first opening at ``open_`` and the last closing at ``close``."""
    t0 = int(datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp()) + (60 if start_late else 0)
    bars = [{"time": t0 + 60 * i, "open": open_, "high": open_, "low": open_, "close": open_, "volume": 1} for i in range(minutes)]
    bars[-1]["close"] = close
    pre = {"time": t0 - 3600, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}  # pre-market: ignored
    post = {"time": t0 + 390 * 60 + 60, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}  # after hours: ignored
    return [pre, *bars, post]


def stub_bars(monkeypatch, stored, today=None, calls=None):
    def read(symbol, day):
        if calls is not None:
            calls.append((symbol, day))
        return stored.get((symbol, day), [])
    monkeypatch.setattr(ping_images, "stored_bars", read)
    monkeypatch.setattr(ping_images, "today_bars", lambda symbol: (today or {}).get(symbol, []))


def seed(db, day, answer, question="pack naming TSLA NVDA AMD"):
    saved = CopilotInvestigation(title=f"Morning brief {day.isoformat()}", status="open", evidence_json="[]",
                                 transcript_json=json.dumps([{"role": "user", "content": question},
                                                             {"role": "assistant", "content": answer}]))
    db.add(saved)
    db.commit()
    db.add(PremarketPrep(day=day, investigation_id=str(saved.id), delivery="sent", body=answer))
    db.commit()
    return str(saved.id)


def test_named_symbols_are_whole_uppercase_known_tokens_without_the_stoplist():
    text = ("Verdict: NVDA leads; $CRWV gaps up, NVDA again. S&P 500 futures flat, U.S. CPI at 08:30 ET. AI names bid; "
            "the 20-day MA holds. Watch APLD and SPY. nvda lower case, NVDAX, Q3, QQQ.")
    assert brief_scorecard.named(text, KNOWN) == ["NVDA", "CRWV", "APLD", "SPY", "QQQ"]


def test_excess_and_hit_arithmetic_on_fixture_bars(monkeypatch):
    stub_bars(monkeypatch, {("SPY", THU): session_bars(THU, 100, 101),  # +1%
                            ("NVDA", THU): session_bars(THU, 50, 52.1),  # +4.2%: +3.2 pp, a hit
                            ("CRWV", THU): session_bars(THU, 100, 98.5),  # -1.5%: -2.5 pp, no hit
                            ("APLD", THU): session_bars(THU, 20, 19.2)})  # -4%: -5 pp, a hit
    assert brief_scorecard.excess_pp(0.042, 0.01) == pytest.approx(3.2)
    assert brief_scorecard.session_return(session_bars(THU, 50, 52.1), THU) == pytest.approx(0.042)
    row = brief_scorecard.score(["NVDA", "CRWV", "APLD", "SPY"], THU, datetime(2026, 11, 6, 9, 0, tzinfo=ET))
    assert row == {"day": "2026-11-05", "named": 4, "moved": 2, "unknown": 0, "state": "ok"}


def test_missing_bars_are_unknown_counted_in_named_never_in_moved(monkeypatch):
    stub_bars(monkeypatch, {("SPY", THU): session_bars(THU, 100, 101), ("NVDA", THU): session_bars(THU, 50, 60, start_late=True)})
    now = datetime(2026, 11, 6, 9, 0, tzinfo=ET)
    assert brief_scorecard.score(["NVDA", "CRWV", "SPY"], THU, now) == {
        "day": "2026-11-05", "named": 3, "moved": 0, "unknown": 2, "state": "ok"}  # no 09:30 minute: no fill-forward
    stub_bars(monkeypatch, {("NVDA", THU): session_bars(THU, 50, 60)})  # SPY missing: everything unknown
    assert brief_scorecard.score(["NVDA", "SPY"], THU, now)["state"] == "no_bars"


def test_today_is_in_progress_on_the_latest_minute_from_the_chart_feed(monkeypatch):
    stub_bars(monkeypatch, {}, today={"SPY": session_bars(FRI, 100, 100, minutes=60), "NVDA": session_bars(FRI, 50, 52, minutes=60)})
    row = brief_scorecard.score(["NVDA"], FRI, datetime(2026, 11, 6, 10, 30, tzinfo=ET))
    assert row == {"day": "2026-11-06", "named": 1, "moved": 1, "unknown": 0, "state": "in_progress"}


def test_the_card_pools_briefs_newest_first_and_caches_finished_days(monkeypatch):
    calls = []
    stub_bars(monkeypatch, {("SPY", THU): session_bars(THU, 100, 101), ("NVDA", THU): session_bars(THU, 50, 52.1),
                            ("CRWV", THU): session_bars(THU, 100, 98.5)}, calls=calls)
    monkeypatch.setattr(brief_scorecard, "_known", lambda db: KNOWN)
    now = datetime(2026, 11, 6, 20, 0, tzinfo=ET)
    with Session(engine) as db:
        seed(db, THU, "Verdict: NVDA and CRWV gap; SPY flat.")
        seed(db, FRI, "Verdict: quiet; APLD only.")
        db.add(PremarketPrep(day=date(2026, 11, 4), delivery="unknown"))  # no investigation: not a brief
        db.commit()
        card = brief_scorecard.brief_scorecard(db, now, 7)
        assert (card["state"], card["briefs"], card["named"], card["moved"], card["unknown"]) == ("ok", 2, 4, 1, 1)
        assert [r["day"] for r in card["rows"]] == ["2026-11-06", "2026-11-05"]
        assert card["rows"][0] == {"day": "2026-11-06", "named": 1, "moved": 0, "unknown": 1, "state": "no_bars"}
        assert card["rows"][1] == {"day": "2026-11-05", "named": 3, "moved": 1, "unknown": 0, "state": "ok"}
        assert "NVDA" not in json.dumps(card) and "Verdict" not in json.dumps(card)  # counts only
        before = len([c for c in calls if c[1] == THU])
        assert brief_scorecard.brief_scorecard(db, now, 7) == card
        assert len([c for c in calls if c[1] == THU]) == before  # the finished day came from the cache
        assert brief_scorecard.brief_scorecard(db, now, 1)["briefs"] == 1  # the window moves


def test_a_failing_brief_marks_its_row_and_an_unreadable_store_the_card(monkeypatch):
    stub_bars(monkeypatch, {})
    monkeypatch.setattr(brief_scorecard, "_known", lambda db: KNOWN)
    monkeypatch.setattr(brief_scorecard, "score", lambda *a: 1 / 0)
    now = datetime(2026, 11, 6, 20, 0, tzinfo=ET)
    with Session(engine) as db:
        seed(db, THU, "NVDA")
        card = brief_scorecard.brief_scorecard(db, now, 7)
        assert card["rows"] == [{"day": "2026-11-05", "state": "unavailable"}] and card["named"] == 0
        monkeypatch.setattr(brief_scorecard, "_briefs", lambda *a: 1 / 0)
        assert brief_scorecard.brief_scorecard(db, now, 7)["state"] == "unavailable"


def test_the_route_is_owner_only_gated_and_bounded(boundary, monkeypatch):  # noqa: F811
    stub_bars(monkeypatch, {})
    with Session(engine) as db:
        seed(db, THU, "Verdict: NVDA leads.")
    boundary.patch.delenv("COPILOT_ENABLED", raising=False)
    assert boundary.owner.get("/copilot/brief-scorecard").status_code == 503
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    response = boundary.owner.get("/copilot/brief-scorecard?days=30")
    assert response.status_code == 200
    body = response.json()
    assert {"days", "briefs", "named", "moved", "unknown", "rows", "as_of", "state"} <= set(body) and body["days"] == 30
    assert all(set(r) == {"day", "named", "moved", "unknown", "state"} for r in body["rows"])
    assert boundary.owner.get("/copilot/brief-scorecard?days=0").status_code == 422
    assert boundary.owner.get("/copilot/brief-scorecard?days=31").status_code == 422
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/brief-scorecard").status_code == 403
