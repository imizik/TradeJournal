"""Fixed MU newer-data protocol: causal fixtures, refusals and prior identity."""
from dataclasses import replace
from datetime import date, datetime, timezone
import json
import os
import pytest

from app.engine.research_studio import (
    Definition, Predicate, Observations, NEWER_END, NEWER_PERIODS, session_dates,
    session_close, parse_definition,
)
from app.engine.research_studio_data import DiscoveryCache
from app.engine.research_studio_session import ResearchSession
from app.engine.research_studio_store import ResearchStore, encode_snapshot, decode_snapshot
from tests.test_research_studio import rows, write_day


def question(period=2, rvol=1.5):
    _, start, end = NEWER_PERIODS[period]
    return Definition((Predicate('move_15m_atr', maximum=-.25), Predicate('rvol', minimum=rvol)),
                      universe=('MU',), start=start, end=end, version=2)


def test_definition_is_a_separate_fixed_protocol():
    definition = question()
    assert parse_definition(definition.canonical()) == definition
    for change in ({'version': 1}, {'universe': ('NVDA',)}, {'window_start': 605},
                   {'start': date(2026, 4, 1)}, {'end': date(2026, 10, 12)},
                   {'predicates': (Predicate('rvol', minimum=3),)}):
        with pytest.raises(ValueError):
            replace(definition, **change)
    assert question(rvol=2).identity != definition.identity
    forged = {**definition.canonical(), 'protocol': 'discovery', 'exploratory_exposure': False}
    with pytest.raises(ValueError):
        parse_definition(forged)


def test_calendar_is_not_inferred_from_missing_cache_files():
    discovery = session_dates()
    extended = session_dates(NEWER_END, version=2)
    assert len(discovery) == 335
    assert extended[:len(discovery)] == discovery
    assert sum(date(2024, 10, 1) <= d <= date(2024, 12, 31) for d in extended) == 64
    assert sum(d.year == 2025 for d in extended) == 250
    assert sum(d.year == 2026 for d in extended) == 194
    assert date(2025, 1, 9) not in extended
    assert session_close(date(2025, 7, 3)) == 780
    assert session_close(date(2026, 7, 2)) == 960
    with pytest.raises(ValueError):
        session_dates(NEWER_END)


@pytest.mark.parametrize('approved', [False, True])
def test_source_refuses_unapproved_dates_and_symbols_before_payload_open(tmp_path, monkeypatch, approved):
    root = tmp_path / 'sip'
    root.mkdir()
    source = DiscoveryCache(root, allow_newer_mu=approved)
    def refuse(*args, **kwargs):
        pytest.fail('invalid request opened a source path')
    monkeypatch.setattr(os, 'open', refuse)
    for call in (lambda: source.snapshot(('MU',), through=date(2026, 10, 12), version=2),
                 lambda: source.snapshot(('NVDA',), through=NEWER_END, version=2),
                 lambda: source._read('NVDA', NEWER_END, version=2),
                 lambda: source._read('MU', NEWER_END)):
        with pytest.raises(ValueError):
            call()
    if not approved:
        with pytest.raises(ValueError):
            source.snapshot(('MU',), through=NEWER_END, version=2)


@pytest.fixture
def session(tmp_path):
    root = tmp_path / 'sip'
    root.mkdir()
    store = tmp_path / 'store'
    store.mkdir(mode=0o700)
    # Independent full-minute hand fixture. Populate 25 prior sessions and one
    # event session; all later expected sessions stay missing, never holidays.
    days = [d for d in session_dates(NEWER_END, version=2) if d <= date(2026, 1, 2)][-26:]
    for symbol in ('MU', 'SPY'):
        for day in days:
            raw = rows(day, volume=400 if symbol == 'MU' and day.year == 2026 else 200)
            if symbol == 'MU' and day.year == 2026:
                raw[29].update(c=98, l=98)
            write_day(root, symbol, day, raw)
    source = DiscoveryCache(root, allow_newer_mu=True)
    return ResearchSession(source, ResearchStore(store, source_root=root))


def test_newer_preview_is_causal_gap_aware_and_source_exposure_precedes_read(session, monkeypatch):
    read = session.source._read
    def recorded(symbol, day, **kwargs):
        assert (session.store.root / 'source-exposure.2026-10-09.json').exists()
        return read(symbol, day, **kwargs)
    monkeypatch.setattr(session.source, '_read', recorded)
    definition = question()
    result = session.preview(definition.canonical())
    assert result['event_count'] == 1
    assert result['events'][0]['decision_time'] == '2026-01-02T15:00:00+00:00'
    assert result['coverage']['MU']['expected_sessions'] == 194
    assert result['coverage']['MU']['missing_sessions'] == 193
    obs = session.observations
    moment = datetime(2026, 1, 2, 15, tzinfo=timezone.utc)
    features = obs.features('MU', moment)
    assert features['rvol'].value == 2
    assert features['move_15m_atr'].value == -2
    snapshot = obs.snapshot
    decoded = decode_snapshot(encode_snapshot(snapshot))
    assert decoded.identity == snapshot.identity and decoded.source_version == 2
    assert Observations(decoded).preview(definition)['event_count'] == 1
    with pytest.raises(ValueError):
        Observations(decoded).preview(Definition((Predicate('rvol', minimum=1.5),), universe=('MU',)))
    scope = json.loads((session.store.root / 'source-exposure.2026-10-09.json').read_text())
    assert scope['source_end'] == '2026-10-09' and scope['independent_validation'] is False


def test_discovery_snapshot_roundtrip_keeps_legacy_identity(tmp_path):
    root = tmp_path / 'sip'
    root.mkdir()
    snapshot = DiscoveryCache(root).snapshot(('MU',), through=date(2023, 7, 3))
    restored = decode_snapshot(encode_snapshot(snapshot))
    assert restored.identity == snapshot.identity and restored.source_version == 1
    assert 'source_version' not in json.loads(__import__('gzip').decompress(encode_snapshot(snapshot)))
