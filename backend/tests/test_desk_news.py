"""Headlines on the desk chart (app/engine/desk_news.py, GET /copilot/desk/{id}/news): the candle each headline sits on
(pre-market, after hours and gaps included), grouping, the big-move emphasis, no reason invented for a move with no
headline, the one cached read per symbol, and nothing for a ticker he does not follow. Every headline, link and price is
invented."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session

from app.database import get_session
from app.engine import desk_news
from app.engine.chart_math import ET
from app.models import DayJournalEntry
from app.routers import copilot_plans as plan_routes
from tests.test_copilot_plans import NBIS, engine, quotes  # noqa: F401  (fixtures)
from tests.test_copilot_desk_context import investigation
from tests.test_today import clock  # noqa: F401  (fixtures)

DAY = datetime(2026, 10, 21, tzinfo=ET)  # Wednesday; the shared desk clock reads 14:49 New York on it


def at(hour: int, minute: int = 0, second: int = 0, day: datetime = DAY) -> int:
    return int(day.replace(hour=hour, minute=minute, second=second).timestamp())


def news(when: int, words: str = "Headline", url: str | None = None, symbols=("NBIS",), source: str = "benzinga") -> dict:
    """A row as ``premarket_prep._headline`` returns it."""
    return {"headline": words, "publisher": source, "url": url or f"https://example.com/{when}-{len(words)}",
            "symbols": list(symbols), "_at": datetime.fromtimestamp(when, ET), "at": ""}


def candles(start: int, n: int, step: int = 120, base: float = 100.0, extended=lambda t: False, jump: dict | None = None) -> list[dict]:
    """``n`` quiet candles (range 0.10, close 0.02 above open) from ``start``; ``jump`` {index: (open, close)} moves one."""
    out = []
    price = base
    for i in range(n):
        t = start + i * step
        o, c = (jump or {}).get(i, (price, price + 0.02))
        out.append({"time": t, "open": o, "high": max(o, c) + 0.04, "low": min(o, c) - 0.04, "close": c, "volume": 1000,
                    "extended": extended(t)})
        price = c
    return out


# ------------------------------------------------------------------ the candle a headline sits on


def test_headline_sits_on_the_candle_whose_span_holds_it():
    bars = candles(at(9, 30), 30)
    placed = desk_news.place([news(at(9, 41, 59)), news(at(9, 42))], bars, 120, at(4))
    assert [(p["time"], p["before"]) for p in placed] == [(at(9, 40), False), (at(9, 42), False)]
    assert placed[0]["session"] == "regular" and placed[0]["source"] == "benzinga"


def test_pre_market_and_after_hours_headlines_on_the_2m_chart():
    pre = lambda t: t < at(9, 30) or t >= at(16)  # noqa: E731
    bars = candles(at(4), 480, extended=pre)  # 04:00-20:00
    placed = desk_news.place([news(at(7, 12, 30)), news(at(17, 5))], bars, 120, at(16, day=DAY - timedelta(days=1)))
    by = {p["session"]: p for p in placed}
    assert by["pre-market"]["time"] == at(7, 12) and not by["pre-market"]["before"]
    assert by["after hours"]["time"] == at(17, 4) and not by["after hours"]["before"]


def test_on_the_15m_chart_a_pre_market_headline_waits_for_the_open_candle():
    bars = candles(at(9, 30), 26, step=900)  # regular session only
    placed = desk_news.place([news(at(7, 12)), news(at(10, 5))], bars, 900, at(16, day=DAY - timedelta(days=1)))
    assert [(p["time"], p["before"], p["session"]) for p in placed] == [
        (at(9, 30), True, "pre-market"), (at(10, 0), False, "regular")]


def test_between_sessions_a_headline_sits_on_the_next_session_first_candle():
    tue = DAY - timedelta(days=1)
    bars = candles(at(9, 30, day=tue), 26, step=900) + candles(at(9, 30), 10, step=900)
    placed = desk_news.place([news(at(18, 0, day=tue))], bars, 900, 0)
    assert placed[0]["time"] == at(9, 30) and placed[0]["before"] and placed[0]["session"] == "after hours"


def test_headline_since_the_previous_close_sits_on_the_first_candle_older_ones_are_left_out():
    bars = candles(at(4), 30)
    since = at(16, day=DAY - timedelta(days=1))
    placed = desk_news.place([news(at(18, 30, day=DAY - timedelta(days=1))), news(at(15, 0, day=DAY - timedelta(days=1)))],
                             bars, 120, since)
    assert [(p["time"], p["before"], p["session"]) for p in placed] == [(at(4), True, "after hours")]


def test_headline_after_the_last_candle_waits_for_one():
    bars = candles(at(9, 30), 10)  # last candle 09:48-09:50
    assert desk_news.place([news(at(9, 50, 1))], bars, 120, 0) == []
    assert desk_news.place([news(at(9, 1))], [], 120, 0) == []


def test_session_words():
    assert desk_news.session_word(at(3, 59)) == "overnight"
    assert desk_news.session_word(at(4)) == "pre-market"
    assert desk_news.session_word(at(9, 30)) == "regular"
    assert desk_news.session_word(at(16)) == "after hours"
    assert desk_news.session_word(at(20)) == "overnight"
    assert desk_news.session_word(at(12, day=DAY + timedelta(days=3))) == "weekend"


# ------------------------------------------------------------------ groups


def test_close_headlines_share_one_marker_newest_first_and_a_repeat_shows_once():
    bars = candles(at(9, 30), 60)
    rows = [news(at(10, 0, 30), "First", "https://example.com/a"), news(at(10, 3), "Second", "https://example.com/b"),
            news(at(10, 5, 10), "Third", "https://example.com/c"),  # 10:04 candle: within 6 minutes of 10:00
            news(at(10, 6), "Fourth", "https://example.com/d"),  # 10:06: a marker of its own
            news(at(10, 1), "first", "https://example.com/a2"),  # the same words again
            news(at(10, 7), "Other words", "https://example.com/d")]  # the same link again
    groups = desk_news.group(desk_news.place(rows, bars, 120, 0))
    assert [(g["time"], g["count"], [i["headline"] for i in g["items"]]) for g in groups] == [
        (at(10, 0), 3, ["Third", "Second", "first"]), (at(10, 6), 1, ["Other words"])]
    assert all(not g["emphasis"] and g["move"] is None for g in groups)


def test_15m_groups_only_on_the_same_candle():
    bars = candles(at(9, 30), 26, step=900)
    groups = desk_news.group(desk_news.place([news(at(10, 1), "A"), news(at(10, 14), "B"), news(at(10, 16), "C")], bars, 900, 0))
    assert [(g["time"], g["count"]) for g in groups] == [(at(10, 0), 2), (at(10, 15), 1)]


# ------------------------------------------------------------------ big moves


def test_a_jump_well_beyond_the_day_typical_candle_is_a_move():
    bars = candles(at(9, 30), 60, jump={30: (100.6, 103.1)})  # 10:30: +2.5 against a typical 0.10 range
    moves = desk_news.big_moves(bars, 120)
    assert len(moves) == 1
    move = moves[0]
    assert move["start"] == at(10, 26) and move["end"] == at(10, 32)  # the 5-minute stretch ending at the jump
    assert move["pct"] > 2 and move["range_pct"] > 2


def test_quiet_day_and_tiny_moves_are_not_big():
    assert desk_news.big_moves(candles(at(9, 30), 60), 120) == []
    tiny = candles(at(9, 30), 60, jump={30: (100.6, 100.75)})  # 4x typical, but 0.15% of price
    assert desk_news.big_moves(tiny, 120) == []
    assert desk_news.big_moves(candles(at(9, 30), 5, jump={3: (100, 110)}), 120) == []  # too few candles for a typical


def test_headline_near_a_move_is_emphasised_and_carries_it():
    bars = candles(at(9, 30), 60, jump={30: (100.6, 103.1)})
    rows = [news(at(10, 29), "Why the stock jumped"), news(at(9, 40), "Earlier story")]
    out = desk_news.view(rows, bars, 120, 0, symbol="NBIS")
    by = {g["items"][0]["headline"]: g for g in out}
    assert by["Why the stock jumped"]["emphasis"] and by["Why the stock jumped"]["move"]["pct"] > 2
    assert not by["Earlier story"]["emphasis"] and by["Earlier story"]["move"] is None


def test_a_move_with_no_headline_gets_nothing():
    bars = candles(at(9, 30), 60, jump={30: (100.6, 103.1)})
    assert desk_news.big_moves(bars, 120)  # the move is there
    assert desk_news.view([], bars, 120, 0, symbol="NBIS") == []  # and no marker invents a reason for it
    far = desk_news.view([news(at(11, 0))], bars, 120, 0, symbol="NBIS")  # a headline 28 minutes later
    assert len(far) == 1 and not far[0]["emphasis"]


def test_a_pre_market_jump_counts_against_the_pre_market_when_no_session_yet():
    pre = lambda t: t < at(9, 30)  # noqa: E731
    bars = candles(at(4), 60, extended=pre, jump={40: (101.0, 105.0)})  # 05:20, before any regular candle
    out = desk_news.view([news(at(5, 18), "Contract win")], bars, 120, 0, symbol="NBIS")
    assert out[0]["emphasis"] and out[0]["move"]["pct"] > 3


def test_headline_naming_a_hidden_ticker_or_not_naming_the_symbol_is_left_out():
    bars = candles(at(9, 30), 60)
    rows = [news(at(10, 0), "Both", symbols=("NBIS", "CRWV")), news(at(10, 10), "Other", symbols=("MU",)),
            news(at(10, 20), "Ours")]
    out = desk_news.view(rows, bars, 120, 0, {"CRWV"}, "NBIS")
    assert [g["items"][0]["headline"] for g in out] == ["Ours"]


# ------------------------------------------------------------------ build and the cache


def test_build_states():
    bars = lambda *a: candles(at(9, 30), 60)  # noqa: E731
    heads = lambda *a: [news(at(10, 0))]  # noqa: E731
    since = lambda first: 0  # noqa: E731
    now = at(14, 49)
    ok = desk_news.build("NBIS", "2m", now, set(), bars=bars, headlines=heads, since=since)
    assert ok["state"] == "ok" and len(ok["groups"]) == 1
    assert desk_news.build("NBIS", "1D", now, set(), bars=bars, headlines=heads, since=since)["state"] == "none"
    assert desk_news.build(None, "2m", now, set(), bars=bars, headlines=heads, since=since)["state"] == "none"
    hidden = desk_news.build("NBIS", "2m", now, {"NBIS"}, bars=bars,
                             headlines=lambda *a: pytest.fail("no read for a hidden ticker"), since=since)
    assert hidden["state"] == "hidden" and hidden["groups"] == []
    assert desk_news.build("NBIS", "2m", now, None, bars=bars, headlines=heads, since=since)["state"] == "unavailable"
    assert desk_news.build("NBIS", "2m", now, set(), bars=lambda *a: [], headlines=heads, since=since)["state"] == "none"

    def refused(*a):
        raise RuntimeError("403")
    down = desk_news.build("NBIS", "2m", now, set(), bars=bars, headlines=refused, since=since)
    assert down["state"] == "unavailable" and "not evidence of no news" in down["reason"]


def test_one_provider_read_per_symbol_per_few_minutes(monkeypatch):
    desk_news._cache.clear()
    calls = []
    tick = {"t": 1000.0}
    monkeypatch.setattr(desk_news._time, "monotonic", lambda: tick["t"])
    now = at(14, 49)
    article = {"headline": "Invented", "url": "https://example.com/x", "source": "benzinga", "symbols": ["NBIS"],
               "created_at": datetime.fromtimestamp(at(10, 0), ET).isoformat()}

    def provider(symbol, start, end):
        calls.append((symbol, start.date()))
        return [article]
    first = desk_news.read_headlines("NBIS", now, provider)
    assert desk_news.read_headlines("NBIS", now + 60, provider) == first  # both timeframes share it
    tick["t"] += desk_news.NEWS_TTL_S - 1
    desk_news.read_headlines("NBIS", now, provider)
    assert calls == [("NBIS", (DAY - timedelta(days=desk_news.LOOKBACK_DAYS)).date())]
    desk_news.read_headlines("MU", now, provider)
    tick["t"] += 2
    desk_news.read_headlines("NBIS", now, provider)
    assert [c[0] for c in calls] == ["NBIS", "MU", "NBIS"]
    assert first[0]["headline"] == "Invented" and first[0]["publisher"] == "benzinga"
    desk_news._cache.clear()


# ------------------------------------------------------------------ the route


@pytest.fixture
def lab(engine, quotes, clock, monkeypatch):  # noqa: F811
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(desk_news, "cached_bars", lambda symbol, timeframe, now: candles(at(9, 30), 60, jump={30: (100.6, 103.1)}))
    monkeypatch.setattr(desk_news, "_previous_close", lambda first: at(16, day=DAY - timedelta(days=1)))
    app = FastAPI()
    app.include_router(plan_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_route_marks_followed_symbol_and_none_for_hidden(lab, engine, monkeypatch):  # noqa: F811
    investigation(engine)
    reads = []
    monkeypatch.setattr(desk_news, "read_headlines", lambda symbol, now: reads.append(symbol) or [news(at(10, 29), "Why it jumped")])
    body = lab.get(f"/copilot/desk/{NBIS}/news").json()
    assert body["state"] == "ok" and body["symbol"] == "NBIS" and reads == ["NBIS"]
    assert body["groups"][0]["emphasis"] and body["groups"][0]["items"][0]["url"].startswith("https://")
    assert lab.get("/copilot/desk/symbol:MU/news?timeframe=15m").json()["state"] == "ok"
    assert lab.get(f"/copilot/desk/{NBIS}/news?timeframe=1D").json()["state"] == "none"
    assert lab.get("/copilot/desk/market/news").json()["state"] == "none"
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="hide-NBIS", day=DAY.date(), kind="follow", symbol="NBIS", text="Not following"))
        db.commit()
    hidden = lab.get(f"/copilot/desk/{NBIS}/news").json()
    assert hidden["state"] == "hidden" and hidden["groups"] == [] and reads == ["NBIS", "MU"]
