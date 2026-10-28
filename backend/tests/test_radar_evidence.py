"""Outcome-blind completeness, old-store refusal and zero-event review accounting."""
from dataclasses import asdict
import hashlib
import json
import sqlite3

import pytest

from app.engine.radar_evidence import census
from app.engine.radar_store import RadarStore
from app.engine import radar_rules
from scripts import radar_outcomes as ro
from scripts.radar_outcomes_review import question_for
from tests.test_radar_outcomes import _add_pass, _certify, _event, UNIVERSE, FLAT, SESSION


def populated(tmp_path, origin="live", failed=(), omit=None):
    s = RadarStore(tmp_path / 'radar.sqlite')
    for minute in ['10:00', '10:01', '10:02']:
        if minute != omit:
            _add_pass(s, minute, FLAT)
    _certify(s, {'status': 'open', 'open': 600, 'close': 603}, origin, failed)
    return s


def test_zero_events_are_a_verified_session_and_read_is_immutable(tmp_path):
    s = populated(tmp_path)
    before = hashlib.sha256(s.path.read_bytes()).hexdigest()
    [row] = census(RadarStore(s.path, read_only=True), '2026-10-28')
    assert row['verified'] and row['events'] == 0 and row['recorded_minutes'] == 3
    assert ro.summarize([row])['radar-rules-v1']['sessions'] == 1
    assert hashlib.sha256(s.path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('kwargs,reason', [
    ({'origin': 'replay'}, 'non-live or unsuccessful detection'),
    ({'failed': (2,)}, 'non-live or unsuccessful detection'),
    ({'omit': '10:01'}, 'missing scheduled minute slots'),
])
def test_replay_failed_detection_and_missing_minutes_cannot_count(tmp_path, kwargs, reason):
    [row] = census(populated(tmp_path, **kwargs), '2026-10-28')
    assert not row['verified'] and reason in row['issues']
    assert ro.summarize([row])['radar-rules-v1']['sessions'] == 0


def test_legacy_event_never_acquires_live_provenance(tmp_path):
    s = RadarStore(tmp_path / 'legacy.sqlite')
    start = _add_pass(s, '10:00', FLAT)
    _event(s, 'legacy', 'relative_to_spy', 'up', ['AAA'], start)
    with sqlite3.connect(s.path) as db:
        db.execute('DROP TABLE detection_receipt')
        db.execute('DROP TABLE detection_config')
    old = RadarStore(s.path, read_only=True)
    assert old.detection_evidence() == ({}, {})
    [row] = census(old, '2026-10-28')
    assert not row['verified'] and 'missing detector receipt' in row['issues']
    [event] = ro.score_store(old, UNIVERSE, set(), '2026-10-28')
    assert not event['evidence_verified'] and event['horizons'] == {}


def test_receipts_are_append_only_and_default_to_replay(tmp_path):
    s = populated(tmp_path)
    with sqlite3.connect(s.path) as db, pytest.raises(sqlite3.IntegrityError, match='immutable'):
        db.execute('DELETE FROM detection_receipt')
    with pytest.raises(sqlite3.IntegrityError):
        _add_receipt(s, 1)


def _add_receipt(s, pass_id):
    s.append_detection(pass_id, universe=UNIVERSE, rules=asdict(radar_rules.V1),
                       hours=None, status='ok', event_ids=[], recorded_at='2026-10-27T15:00:00Z')


def test_unrecorded_weekday_and_incomplete_today_are_explicit(tmp_path):
    s = populated(tmp_path)
    rows = census(s, '2026-10-29')
    assert rows[-1]['session_date'] == '2026-10-28'
    assert rows[-1]['issues'] and not rows[-1]['verified']
    assert all(r['session_date'] < '2026-10-29' for r in rows)
    assert census(s, SESSION) == []


def test_twenty_zero_event_days_reach_review_without_a_positive_claim():
    rows = [{'record_type': 'session', 'session_date': f'2026-11-{i:02}', 'rule_version': 'v',
             'verified': True, 'config_digest': 'fixed'} for i in range(1, 21)]
    r = ro.summarize(rows)['v']
    assert r['sessions'] == 20 and r['events'] == 0
    assert r['decision'] == 'no demonstrated timing value over Movers'
    assert question_for(rows, '2026-11-01', None) is None
    rows[-1]['config_digest'] = 'changed'
    assert ro.summarize(rows)['v']['decision'] == 'not reviewed: mixed frozen configurations'


def test_census_only_never_reads_prices_or_writes_output(tmp_path, monkeypatch, capsys):
    s = populated(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('price access')
    monkeypatch.setattr(RadarStore, 'pass_quotes', forbidden)
    out = tmp_path / 'out.jsonl'
    ro.main([str(s.path), '--out', str(out), '--today', '2026-10-28', '--census-only'])
    assert json.loads(capsys.readouterr().out)['sessions'][0]['verified']
    assert not out.exists()


def test_readout_freezes_first_twenty_verified_sessions():
    rows = [{"record_type": "session", "session_date": f"2026-11-{i:02}", "rule_version": "v",
             "verified": True, "config_digest": "fixed"} for i in range(1, 22)]
    event = {"event_id": "later", "session_date": "2026-11-21", "rule_version": "v",
             "evidence_verified": True, "config_digest": "fixed", "horizons": {}}
    r = ro.summarize(rows + [event])["v"]
    assert r["sessions"] == 20 and r["verified_sessions_available"] == 21 and r["events"] == 0


def test_current_universe_cannot_replace_recorded_membership(tmp_path):
    s = RadarStore(tmp_path / "radar.sqlite")
    start = _add_pass(s, "10:00", FLAT)
    _add_pass(s, "11:00", {**FLAT, "AAA": 104.0})
    _event(s, "live", "relative_to_spy", "up", ["AAA"], start)
    _certify(s)
    old = ro.score_store(s, UNIVERSE, set(), "2026-10-28")
    changed = ro.score_store(s, {"version": "new", "symbols": [], "groups": []}, set(), "2026-10-28")
    assert old == changed and old[0]["evidence_verified"]


def test_event_inserted_without_receipt_invalidates_session(tmp_path):
    s = populated(tmp_path)
    _event(s, "backfilled", "relative_to_spy", "up", ["AAA"], s.passes()[0])
    [row] = census(s, "2026-10-28")
    assert not row["verified"] and "events lack unique live receipt provenance" in row["issues"]


def test_additive_upgrade_preserves_legacy_rows_without_certifying_them(tmp_path):
    s = RadarStore(tmp_path / "legacy.sqlite")
    _add_pass(s, "10:00", FLAT)
    before = s.passes(), s.quotes()
    with sqlite3.connect(s.path) as db:
        db.execute("DROP TABLE detection_receipt")
        db.execute("DROP TABLE detection_config")
    upgraded = RadarStore(s.path)
    assert (upgraded.passes(), upgraded.quotes()) == before
    assert upgraded.detection_evidence() == ({}, {})
    assert not census(upgraded, "2026-10-28")[0]["verified"]
