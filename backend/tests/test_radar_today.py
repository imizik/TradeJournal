"""The session's Radar feed for the copilot, cut at a moment: nothing first seen, revised, checked or recorded later shows."""
import copy
import json
from pathlib import Path

from app.engine import radar_today
from app.engine.radar_comparison import epoch
from app.engine.radar_store import RadarStore
from tests.test_radar_movers import UNIVERSE, _pass, _q, _quotes, _stamp

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())
SESSION = "2026-10-22"


def _event(n: int, first_seen: str, **over) -> dict:
    event = copy.deepcopy(SAMPLE["event"])
    event.update(event_id=f"rad_t_{n}", session_date=SESSION, first_seen_at=_stamp(first_seen), universe_version="t", **over)
    return event


def _revision(event_id: str, n: int, at: str, status="extended") -> dict:
    return {"event_id": event_id, "revision": n, "recorded_at": _stamp(at), "status": status,
            "measures": {"relative_pct": 4.0 + n}, "evidence": [], "note": f"revision {n}"}


def _news(event_id: str, at: str, headline: str | None) -> dict:
    heads = [{"headline": headline, "source": "wire", "published_at": _stamp("14:00"), "url": "https://x.example/1",
              "symbols": ["MU"], "timing": "before"}] if headline else []
    return {"event_id": event_id, "checked_at": _stamp(at), "status": "found" if headline else "none_found", "headlines": heads}


def _store(tmp_path) -> RadarStore:
    store = RadarStore(tmp_path / "radar.sqlite")
    for minute, quotes in (("14:19", [_q("SPY", 100.0, minute="14:19"), _q("AAA", 95.0, minute="14:19")]),
                           ("14:34", _quotes()),
                           ("15:04", [_q("SPY", 101.0, minute="15:04"), _q("AAA", 120.0, minute="15:04")])):
        store.append_pass(_pass(minute), quotes)
    store.append_event(_event(1, "14:20", symbols=["AAA"], group="Chips", summary="AAA up early"))
    store.append_event(_event(2, "14:50", symbols=["CCC"], group="Lone", summary="CCC later"))
    store.append_revision(_revision("rad_t_1", 1, "14:30"))
    store.append_revision(_revision("rad_t_1", 2, "14:55", status="faded"))
    store.append_news(_news("rad_t_1", "14:25", None))
    store.append_news(_news("rad_t_1", "14:58", "a later headline"))
    store.append_feedback("rad_t_1", "useful", _stamp("15:30"))
    return store


def test_the_cut_hides_everything_after_the_moment(tmp_path):
    store = _store(tmp_path)
    cut = radar_today.feed(store, SESSION, epoch(_stamp("14:40")), universe=UNIVERSE)
    assert cut["state"] == "ok" and cut["as_of"] == "2026-10-22T18:40:00Z"
    assert [e["event_id"] for e in cut["events"]] == ["rad_t_1"] and cut["events_total"] == 1
    only = cut["events"][0]
    assert only["latest"]["status"] == "extended" and only["latest"]["note"] == "revision 1"  # revision 2 came later
    assert only["news"]["status"] == "none_found" and only["news"]["headlines"] == []  # the later check is hindsight
    assert only["rating"] is None  # ratings carry no time the store exposes, so a cut never shows them
    assert cut["movers"]["pass_at"] == _stamp("14:34") and cut["movers"]["earlier_pass_at"] == _stamp("14:19")
    assert cut["passes_recorded"] == 2
    assert "later" not in json.dumps(cut) and "120" not in json.dumps(cut["movers"])


def test_no_cut_shows_the_whole_session_newest_first_with_ratings(tmp_path):
    store = _store(tmp_path)
    full = radar_today.feed(store, SESSION, None, universe=UNIVERSE)
    assert [e["event_id"] for e in full["events"]] == ["rad_t_2", "rad_t_1"] and full["as_of"] == _stamp("15:04")
    first = full["events"][1]
    assert first["latest"]["status"] == "faded" and first["news"]["headlines"][0]["headline"] == "a later headline"
    assert first["rating"] == "useful" and full["events"][0]["rating"] is None
    assert first["news"]["headlines"][0].keys() == {"headline", "source", "published_at", "timing"}  # no url, no symbols
    assert full["movers"]["pass_at"] == _stamp("15:04") and full["movers"]["leaders"][0]["symbol"] == "AAA"
    assert full["movers"]["leaders"][0].keys() == {"symbol", "last", "day_pct", "from_open_pct", "vs_spy", "sector", "vs_sector", "last_15m_pct"}


def test_group_filter_matches_a_curated_group_or_one_symbol(tmp_path):
    store = _store(tmp_path)
    assert [e["event_id"] for e in radar_today.feed(store, SESSION, None, group="chips", universe=UNIVERSE)["events"]] == ["rad_t_1"]
    assert [e["event_id"] for e in radar_today.feed(store, SESSION, None, group="ccc", universe=UNIVERSE)["events"]] == ["rad_t_2"]
    out = radar_today.feed(store, SESSION, None, group="Nothing", universe=UNIVERSE)
    assert out["events"] == [] and out["group"] == "Nothing" and out["state"] == "ok"  # the movers still stand


def test_limit_and_bounding_drop_events_never_cut_json(tmp_path):
    store = _store(tmp_path)
    for n in range(3, 40):
        store.append_event(_event(n, "14:21", summary="S" * 400))
    out = radar_today.feed(store, SESSION, None, limit=5, universe=UNIVERSE)
    assert len(out["events"]) == 5 and out["events_total"] == 39
    bounded = radar_today.bounded(radar_today.feed(store, SESSION, None, universe=UNIVERSE), 6000)
    text = json.dumps(bounded, default=str, separators=(",", ":"))
    assert len(text) <= 6000 and json.loads(text)["events_shown"] == len(bounded["events"]) < 12


def test_an_empty_session_and_no_usable_spy(tmp_path):
    store = RadarStore(tmp_path / "radar.sqlite")
    out = radar_today.feed(store, SESSION, None, universe=UNIVERSE)
    assert out["state"] == "no_data" and out["events"] == [] and out["movers"] is None and "reason" in out
    store.append_pass(_pass("14:34"), [_q("AAA", 90.0)])  # a pass without SPY
    out = radar_today.feed(store, SESSION, None, universe=UNIVERSE)
    assert out["state"] == "ok" and out["movers"] is None and "SPY" in out["movers_reason"]
