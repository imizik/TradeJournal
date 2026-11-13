"""The desk's walls (GET /copilot/desk/walls, app/engine/desk_walls.py): the Charts ladder's read cut to put wall, call
wall, gamma flip, max pain and the expected move; one shared chain cache with the ladder and the Chain tab; stale or
missing says so; the dealer side is labelled an assumption; a hidden ticker is never read; nothing reads Robinhood.
Every value is invented. No network."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session

from app.engine import desk_walls
from app.engine.options_feed import OptionsFeed
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_options_feed import START, Calendar, Clock, FakeClient, leg
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

REPO = Path(__file__).resolve().parents[2]
NOW = START.timestamp()


def ladder(**over):
    """A ready ladder answer as ``options_feed.ladder`` gives it (the fields this module reads)."""
    base = {"symbol": "SPY", "state": "ready", "expirations": ["2026-10-05"], "spot": 601.2, "fetched_at": NOW - 30,
            "message": None, "walls": {"call_oi": 615.0, "put_oi": 600.0, "call_volume": 610.0, "put_volume": 595.0},
            "flip": {"price": 607.0, "note": "", "assumption": "x"}, "max_pain": {"price": 610.0, "expiration": "2026-10-05"},
            "expected_move": {"state": "ready", "move": 4.2, "percent": 0.007, "expiration": "2026-10-05"}}
    return {**base, **over}


# --- the read ------------------------------------------------------------------------------------------------------

def test_the_ladder_becomes_four_named_lines_a_band_and_the_assumption():
    found = desk_walls.summary(ladder(), now=NOW, live_session=True)
    assert found["state"] == "ready" and found["expiration"] == "2026-10-05" and found["age_s"] == 30
    assert [(level["kind"], level["price"]) for level in found["levels"]] == [
        ("put_wall", 600.0), ("call_wall", 615.0), ("gamma_flip", 607.0), ("max_pain", 610.0)]
    hints = {level["kind"]: level["hint"] for level in found["levels"]}
    assert hints["call_wall"].startswith("Call wall: the strike with the most call open interest") and "ceiling" in hints["call_wall"]
    assert "floor" in hints["put_wall"] and "assumed dealer side" in hints["gamma_flip"] and "not a target" in hints["max_pain"]
    assert found["expected_move"]["low"] == 597.0 and found["expected_move"]["high"] == 605.4 and found["expected_move"]["move"] == 4.2
    # Never presented as fact.
    assert "assumed" in found["assumption"] and "does not say who holds" in found["assumption"]
    assert found["refresh_seconds"] == 60


def test_no_flip_off_spy_qqq_spx_and_no_band_without_a_priced_straddle():
    found = desk_walls.summary(ladder(flip=None, expected_move={"state": "too_wide", "reason": "wide"}), now=NOW, live_session=True)
    assert [level["kind"] for level in found["levels"]] == ["put_wall", "call_wall", "max_pain"]
    assert found["expected_move"] is None and "SPY, QQQ and SPX" in found["flip_note"]


def test_a_read_three_minutes_old_in_the_session_is_stale_but_not_after_the_close():
    old = ladder(fetched_at=NOW - desk_walls.STALE_S - 1)
    stale = desk_walls.summary(old, now=NOW, live_session=True)
    assert stale["state"] == "stale" and stale["message"] and stale["fetched_at"] == NOW - desk_walls.STALE_S - 1
    assert desk_walls.summary(old, now=NOW, live_session=False)["state"] == "ready"
    assert desk_walls.summary(ladder(fetched_at=NOW - 60), now=NOW, live_session=True)["state"] == "ready"


def test_missing_says_why_and_draws_nothing():
    for state, want in (("loading", "loading"), ("unavailable", "unavailable"), ("none", "none")):
        found = desk_walls.summary({"symbol": "SPY", "state": state, "message": "Loaded 0 of 1 expirations."}, now=NOW, live_session=True)
        assert found["state"] == want and found["levels"] == [] and found["expected_move"] is None and found["message"]


def test_replay_reads_nothing_and_the_fixture_is_simulated_nbis():
    assert desk_walls.read("NBIS", mode="replay", ladder=lambda *a: 1 / 0)["state"] == "unavailable"
    found = desk_walls.read("NBIS", mode="fixture")
    assert found["simulated"] is True and found["state"] == "ready" and found["expiration"] == "2026-10-23"
    assert {level["kind"]: level["price"] for level in found["levels"]} == {"put_wall": 90.0, "call_wall": 100.0, "max_pain": 95.0}
    assert desk_walls.read("CRWV", mode="fixture")["state"] == "unavailable"


# --- one model, one cache ------------------------------------------------------------------------------------------

def test_the_desk_reads_through_the_ladder_and_shares_its_chain_cache():
    clock = Clock()
    client = FakeClient(clock)
    feed = OptionsFeed(client=client, calendar=Calendar(), clock=clock, spawn=lambda work: work())
    charts = feed.ladder("SPY", "nearest", True, 100.0)
    assert charts["state"] == "ready" and len(client.calls) == 2  # the list and the nearest chain
    # The desk a moment later: the same call, nothing read again; the same walls.
    found = desk_walls.read("SPY", mode="live", now=clock(), ladder=lambda symbol, expiration: feed.ladder(symbol, "nearest", True, 100.0, expiration))
    assert len(client.calls) == 2 and found["state"] == "ready"
    assert {level["kind"]: level["price"] for level in found["levels"]}["call_wall"] == charts["walls"]["call_oi"]
    # The Chain tab having read the nearest chain leaves nothing for the walls to read either.
    clock.advance(70)
    feed.chains("SPY", lambda live: live[:1], ttl=12)
    calls = len(client.calls)
    feed.ladder("SPY", "nearest", True, 100.0)
    assert len(client.calls) == calls


def test_a_later_expiry_reads_only_that_chain_and_an_unlisted_one_falls_back_to_the_nearest():
    clock = Clock()
    client = FakeClient(clock)
    friday = date(2026, 10, 16)
    client.chains[("SPY", friday)] = [leg("SPY", friday, strike, side, oi=5000 if (side, strike) in (("call", 105), ("put", 95)) else 100)
                                      for strike in range(90, 111) for side in ("call", "put")]
    feed = OptionsFeed(client=client, calendar=Calendar(), clock=clock, spawn=lambda work: work())
    found = feed.ladder("SPY", "nearest", True, 100.0, friday)
    assert found["expirations"] == [friday.isoformat()] and found["walls"]["call_oi"] == 105.0 and found["walls"]["put_oi"] == 95.0
    assert [kind for _, kind, _ in client.calls] == ["list", "chain"]
    gone = feed.ladder("SPY", "nearest", True, 100.0, START.date() - timedelta(days=1))
    assert gone["expirations"] == [START.date().isoformat()]


# --- the route -----------------------------------------------------------------------------------------------------

def test_the_route_is_owner_only_reads_the_feed_and_never_a_hidden_ticker(desk, engine, monkeypatch):  # noqa: F811
    from app.access_manifest import DOMAIN_ROUTES
    from app.models import DayJournalEntry
    from app.routers import copilot_desk
    assert "GET /copilot/desk/walls" in DOMAIN_ROUTES
    asked = []
    monkeypatch.setattr(desk_walls, "_live", lambda symbol, expiration: asked.append((symbol, expiration)) or ladder(symbol=symbol))
    body = desk.get("/copilot/desk/walls", params={"symbol": "spy", "expiration": "2026-10-09"}).json()
    assert asked == [("SPY", date(2026, 10, 9))] and body["levels"] and body["symbol"] == "SPY"
    with Session(engine) as db:
        db.add(DayJournalEntry(day=date(2026, 10, 21), kind="follow", symbol="SPY", text="Not following", operation_id="hide-spy"))
        db.commit()
    body = desk.get("/copilot/desk/walls", params={"symbol": "SPY"}).json()
    assert body["state"] == "none" and body["levels"] == [] and len(asked) == 1
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/walls", params={"symbol": "QQQ"}).status_code == 503


def test_nothing_here_reads_robinhood_or_sends_anything():
    sources = [(REPO / "backend/app/engine/desk_walls.py").read_text(), (REPO / "frontend/lib/deskWalls.ts").read_text()]
    forbidden = ("robinhood_read", "robinhood_trading", "order_tool", "requests.post", 'method: "POST"', "ntfy", "telegram",
                 "notification_policy")
    for text in sources:
        assert not [word for word in forbidden if word.lower() in text.lower()]
