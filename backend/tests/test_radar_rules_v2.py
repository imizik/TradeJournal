"""Frozen opening-drive events must match C06 and the runner's bounded quote reads."""
import numpy as np

from app.engine import radar_rules
from scripts.radar_v2_search import candidates
from tests.test_radar_rules import UNIVERSE, session, steps


def test_v2_matches_registered_search_in_both_directions_and_on_restart(monkeypatch):
    paths = {"AAA": steps((6, 103.), (12, 96.), (18, 104.)), "BBB": steps((1, 104.)),
             "CCC": steps((6, 103.)), "DDD": steps((12, 104.)), "EEE": steps((6, 101.))}
    passes, quotes = session(paths, minutes=24)
    quotes[1]["BBB"]["open"] = 104.0  # overnight gap followed by a flat session
    del quotes[1]["CCC"]  # late first print cannot supply the registered open
    del quotes[7]["DDD"]  # exact five-minute predecessor absent at minute 12
    names = [r["symbol"] for r in UNIVERSE["symbols"]]
    matrix = np.full((390, len(names)), np.nan)
    for minute, qs in quotes.items():
        for j, name in enumerate(names):
            if name in qs:
                matrix[minute-1, j] = qs[name]["last"]
    opening = np.array([quotes[1].get(s, {}).get("open", np.nan) for s in names])
    expected = candidates(UNIVERSE, names, matrix, opening, np.full(len(names), 100.),
                          matrix, [matrix] * 20, {"C06": "drive"})["C06"]
    assert {(e.minute, e.symbols[0], e.direction) for e in expected} == {
        (6, "AAA", "up"), (12, "AAA", "down"), (13, "DDD", "up")}
    monkeypatch.delenv("RADAR_RULES_VERSION", raising=False)
    assert radar_rules.from_env() is radar_rules.V0
    monkeypatch.setenv("RADAR_RULES_VERSION", "v2")
    version = radar_rules.from_env()
    assert version is radar_rules.V2
    saved = []
    for end, p in enumerate(passes):
        ids = radar_rules.needed_pass_ids(passes, end, version)
        assert len(ids) <= 3
        subset = {i: quotes[i] for i in ids}
        events, revisions = radar_rules.detect(UNIVERSE, passes, end, subset, saved, version)
        assert revisions == []
        for e in events:
            assert e["event_id"].startswith("rv2-") and e["rule_version"] == "radar-rules-v2"
            saved.append((e, []))
        assert radar_rules.detect(UNIVERSE, passes, end, subset, saved, version) == ([], [])
    assert saved == radar_rules.replay(UNIVERSE, passes, quotes, version)
    assert {(e["first_seen_at"], e["symbols"][0], e["direction"]) for e, _ in saved} == {
        (passes[e.minute-1]["finished_at"], e.symbols[0], e.direction) for e in expected}
