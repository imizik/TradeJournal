"""/proof's Radar half: ratings, timing against Movers and the morning brief, and the verdict. Read-only."""
from collections import Counter
from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import radar_proof
from app.engine.chart_math import ET
from app.engine.radar_proof import brief_timing, movers_timing, verdict
from app.engine.radar_store import RadarStore
from app.models import MorningBriefingPacket, MorningBriefingRecord
from app.routers import radar
from tests.test_browser_access import boundary  # noqa: F401  (the shared access fixture)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())["event"]
DAY = "2026-10-22"


def _at(hh_mm: str, day=DAY) -> float:
    return datetime.fromisoformat(f"{day}T{hh_mm}:00").replace(tzinfo=ET).timestamp()


def _stamp(hh_mm: str, day=DAY) -> str:
    return datetime.fromtimestamp(_at(hh_mm, day), UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pass(minute, day=DAY):
    return {"session_date": day, "started_at": _stamp(minute, day), "finished_at": _stamp(minute, day), "universe_version": "t",
            "status": "ok", "symbols_requested": 4, "symbols_returned": 4, "unmatched": [], "requests_used": 1,
            "error": None, "skip_reason": None}


def _q(symbol, last, minute, day=DAY):
    return {"symbol": symbol, "last": last, "prev_close": 100.0, "open": 100.0, "high": None, "low": None, "volume": 1,
            "bid": None, "ask": None, "trade_time_ms": _at(minute, day) * 1000, "retrieved_at": _stamp(minute, day)}


def _event(i, symbol, seen, kind="relative_to_spy", direction="up", day=DAY, version="radar-rules-v0"):
    return {**FIXTURE, "event_id": f"e{i}", "session_date": day, "rule_version": version, "kind": kind,
            "direction": direction, "symbols": [symbol], "first_seen_at": _stamp(seen, day)}


def _stock(symbol):
    return {"symbol": symbol, "kind": "stock", "benchmark": False, "sector": None, "sources": []}


UNIVERSE = {"version": "t", "groups": [], "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True, "sources": []},
                                                      _stock("AAA"), _stock("BBB"), _stock("CCC")]}


# ------------------------------------------------------------------ pure pieces

TIMELINE = [(_at("10:00"), {"AAA"}, set()), (_at("10:01"), {"AAA", "BBB"}, {"CCC"})]


def test_movers_timing():
    assert movers_timing(_event(1, "AAA", "10:01"), TIMELINE) == {"result": "movers_first", "lead_minutes": -1.0}
    assert movers_timing(_event(2, "AAA", "10:00"), TIMELINE)["result"] == "movers_first"  # the same pass is not ahead
    assert movers_timing(_event(3, "BBB", "10:00"), TIMELINE) == {"result": "radar_first", "lead_minutes": 1.0}
    assert movers_timing(_event(4, "CCC", "10:00"), TIMELINE)["result"] == "not_in_movers"  # only on the other side
    assert movers_timing(_event(5, "CCC", "10:00", direction="down"), TIMELINE)["result"] == "radar_first"
    assert movers_timing(_event(6, "AAA", "10:00"), [])["result"] == "unavailable"  # quotes pruned: never "not in Movers"


def test_brief_timing():
    briefs = {date(2026, 10, 22): {"AAA"}, date(2026, 10, 24): {"BBB"}, date(2026, 11, 10): {"CCC"}}
    assert brief_timing("AAA", date(2026, 10, 22), briefs) == "brief_first"  # the 08:45 brief beat the intraday event
    assert brief_timing("BBB", date(2026, 10, 22), briefs) == "radar_first"
    assert brief_timing("CCC", date(2026, 10, 22), briefs) == "not_in_brief"  # outside five days


def test_verdict_defaults_to_not_enough_data():
    empty = verdict(Counter(), Counter())
    assert empty["verdict"] == "not_enough_data" and empty["rated"] == 0 and "0 of 20" in empty["reason"]
    small = verdict(Counter(useful=15), Counter(radar_first=15))
    assert small["verdict"] == "not_enough_data" and small["useful_share"] == 1.0
    untimed = verdict(Counter(useful=20, unrated=5), Counter(radar_first=4, unavailable=30))
    assert untimed["verdict"] == "not_enough_data" and "4 of 10" in untimed["reason"]


def test_verdict_with_mixed_ratings():
    timing = Counter(radar_first=4, not_in_movers=2, movers_first=4)
    helping = verdict(Counter(useful=8, already_knew=6, too_late=4, irrelevant=2), timing)
    assert helping["verdict"] == "helping" and helping["useful_share"] == 0.4 and helping["ahead_share"] == 0.6
    weak = verdict(Counter(useful=7, already_knew=6, too_late=5, irrelevant=2), timing)
    assert weak["verdict"] == "not_helping" and weak["reason"] == "Too few rated useful."
    late = verdict(Counter(useful=20), Counter(radar_first=2, movers_first=8))
    assert late["verdict"] == "not_helping" and "Movers usually had it first" in late["reason"]
    assert "40%+" in late["rule"] and "50%+" in late["rule"]


# ------------------------------------------------------------------ store + briefings

@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _brief(db, day, symbols, redacted=False):
    packet = MorningBriefingPacket(operation_id=f"p-{day}-{symbols}", request_sha256="x", day=date.fromisoformat(day), body_json="{}")
    db.add(packet)
    body = {"opportunities": [{"symbol": s} for s in symbols], "items": [{"symbol": None}]}
    db.add(MorningBriefingRecord(packet_id=packet.id, operation_id=f"r-{day}-{symbols}", request_sha256="x",
                                 body_json=json.dumps(body), redacted_at=datetime(2026, 10, 23) if redacted else None))
    db.commit()


def _seed(store):
    store.append_pass(_pass("10:00"), [_q("SPY", 100.0, "10:00"), _q("AAA", 104.0, "10:00")])
    store.append_pass(_pass("10:01"), [_q("SPY", 100.0, "10:01"), _q("AAA", 104.0, "10:01"), _q("BBB", 103.0, "10:01")])
    store.append_pass(_pass("10:00", "2026-10-21"))  # an older session whose quotes are gone
    for event in (_event(1, "AAA", "10:01"), _event(2, "BBB", "10:00"), _event(3, "CCC", "10:00"),
                  _event(4, "AAA", "10:00", day="2026-10-21"), _event(5, "Chips", "10:01", kind="group_move"),
                  _event(9, "AAA", "10:00", day="2026-10-20", version="radar-rules-v-1")):
        store.append_event(event)
    store.append_feedback("e1", "too_late", "2026-10-22T15:00:00Z")
    store.append_feedback("e2", "irrelevant", "2026-10-22T15:00:00Z")
    store.append_feedback("e2", "useful", "2026-10-22T15:01:00Z")  # the latest rating wins
    store.append_feedback("e9", "useful", "2026-10-22T15:00:00Z")  # an older rule version: not pooled


def test_build_over_a_seeded_store(tmp_path, db):
    store = RadarStore(tmp_path / "radar.sqlite")
    _seed(store)
    _brief(db, "2026-10-22", ["AAA"])
    _brief(db, "2026-10-23", ["BBB"])
    _brief(db, "2026-10-23", ["CCC"], redacted=True)
    out = radar_proof.build(RadarStore(tmp_path / "radar.sqlite", read_only=True), db, UNIVERSE)
    assert (out["state"], out["rule_version"], out["sessions"], out["events"], out["stock_events"], out["group_events"]) == (
        "ok", "radar-rules-v0", 2, 5, 4, 1)
    assert out["ratings"] == {"useful": 1, "already_knew": 0, "too_late": 1, "irrelevant": 0, "unrated": 3}
    assert out["movers"] == {"radar_first": 1, "not_in_movers": 1, "movers_first": 1, "unavailable": 1}
    assert out["median_lead_minutes"] == 1.0
    # AAA on the 22nd was briefed that morning; on the 21st Radar had it a day before the brief. The redacted CCC brief is ignored.
    assert out["brief"] == {"radar_first": 2, "brief_first": 1, "not_in_brief": 1}
    assert out["verdict"]["verdict"] == "not_enough_data" and out["verdict"]["rated"] == 2


def test_build_with_no_events(tmp_path, db):
    out = radar_proof.build(RadarStore(tmp_path / "radar.sqlite"), db, UNIVERSE)
    assert out["state"] == "no_data" and out["events"] == 0 and out["verdict"]["verdict"] == "not_enough_data"


def test_endpoint_off_and_on(tmp_path, monkeypatch, boundary):  # noqa: F811
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    assert boundary.owner.get("/radar/proof").json()["state"] == "off"
    path = tmp_path / "radar.sqlite"
    _seed(RadarStore(path))
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "load_universe", lambda: UNIVERSE)
    body = boundary.owner.get("/radar/proof").json()
    assert body["state"] == "ok" and body["events"] == 5
    assert boundary.public.get("/radar/proof").status_code == 401

