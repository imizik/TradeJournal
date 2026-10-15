from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from cloud_mcp_check_ledger import Ledger, Conflict, NotFound
from market_watch_ledger import MarketWatchLedger, TABLES
from tests.test_market_watch_snapshot import fixture_snapshot, NOW
from tests.test_cloud_mcp_check import harness as harness, signing_key as signing_key, call, rpc
from app.engine.market_watch_snapshot import publish_snapshot

ACTOR = 'check_00000000-0000-0000-0000-000000000001'
OTHER = 'check_00000000-0000-0000-0000-000000000002'


def request(input_id, **changes):
    return {'operation_id': 'op1', 'input_id': input_id, 'view': 'down',
            'main': {'text': 'Weak tape', 'supporting_refs': ['/indices/SPY/bar_1m/close'], 'contradicting_refs': []},
            'alternative': {'text': 'Bounce', 'supporting_refs': [], 'contradicting_refs': []},
            'invalidation': {'text': 'Reclaim VWAP', 'evidence_refs': ['/indices/SPY/vwap']},
            'change_summary': 'First read', 'forecasts': [
                {'horizon': h, 'predicate': 'spy_return_lt_zero', 'probability': .6} for h in ('30m', '60m', 'close')],
            'message_intent': 'update', 'prompt_version': 'test-v1', **changes}


@pytest.fixture
def ledger(tmp_path):
    return MarketWatchLedger(Ledger(tmp_path / 'ledger.sqlite'))


def test_atomic_concurrent_retry_restart_and_next_day_recovery(ledger):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: ledger.submit(ACTOR, req, lambda: NOW), range(4)))
    assert len({r['read_id'] for r in receipts}) == 1
    assert sum(not r['replayed'] for r in receipts) == 1
    restarted = MarketWatchLedger(Ledger(ledger.ledger.path))
    recovered = restarted.submit(ACTOR, req, lambda: NOW + timedelta(days=1))
    assert recovered['replayed'] and recovered['read_id'] == receipts[0]['read_id']
    with pytest.raises(Conflict):
        ledger.submit(ACTOR, {**req, 'view': 'up'}, lambda: NOW)
    with pytest.raises(ValueError, match='current session'):
        ledger.submit(ACTOR, {**req, 'operation_id': 'next'}, lambda: NOW + timedelta(days=1))
    exported = ledger.export(ledger.ledger.path, ACTOR)
    assert exported == ledger.export(ledger.ledger.path, ACTOR)
    assert len(exported['reads']) == len(exported['comparators']) == len(exported['messages']) == 1
    assert exported['inputs'][0]['snapshot_json'] == inp['snapshot']
    assert not ledger.export(ledger.ledger.path, OTHER)['reads']
    with sqlite3.connect(ledger.ledger.path) as db:
        for table in TABLES:
            for sql in (f'DELETE FROM {table}', f'UPDATE {table} SET actor="other"', f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
                with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                    db.execute(sql)


def test_parent_forks_cross_actor_references_and_injection(ledger):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'])
    with pytest.raises(NotFound):
        ledger.submit(OTHER, req, lambda: NOW)
    with pytest.raises(ValueError):
        ledger.serve('../private', fixture_snapshot(), lambda: NOW)
    with pytest.raises(ValueError):
        ledger.submit(ACTOR, {**req, 'path': '/etc/passwd'}, lambda: NOW)
    bad = {**req, 'main': {**req['main'], 'supporting_refs': ['/indices/SPY/secrets']}}
    with pytest.raises(ValueError, match='reference'):
        ledger.submit(ACTOR, bad, lambda: NOW)
    first = ledger.submit(ACTOR, req, lambda: NOW)
    with pytest.raises(Conflict, match='parent'):
        ledger.submit(ACTOR, {**req, 'operation_id': 'second'}, lambda: NOW)
    def write(op):
        try:
            return ledger.submit(ACTOR, {**req, 'operation_id': op, 'previous_read_id': first['read_id']}, lambda: NOW)
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ['second', 'third']))
    assert sum(r is not None for r in results) == 1


def test_message_events_corrections_and_delivery_provenance(ledger):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'])
    first = ledger.submit(ACTOR, req, lambda: NOW)
    correction = ledger.submit(ACTOR, {**req, 'operation_id': 'correct', 'previous_read_id': first['read_id'],
        'correction_of_read_id': first['read_id'], 'message_intent': 'correction'}, lambda: NOW)
    assert correction['message_id'] != first['message_id']
    event = {'kind': 'delivered', 'source': 'owner_report', 'channel': 'email', 'occurred_at': NOW.isoformat()}
    with pytest.raises(ValueError, match='Transport'):
        ledger.append_market_watch_message_event(first['message_id'], 'e1', event, clock=lambda: NOW)
    for i, kind in enumerate(('attempt', 'accepted', 'delivered', 'unknown', 'failed')):
        event = {**event, 'kind': kind, 'source': 'transport', 'transport_receipt_id': 'receipt'}
        result = ledger.append_market_watch_message_event(first['message_id'], str(i), event, clock=lambda: NOW)
        assert result == ledger.append_market_watch_message_event(first['message_id'], str(i), event, clock=lambda: NOW)
        with pytest.raises(Conflict):
            ledger.append_market_watch_message_event(first['message_id'], str(i), {**event, 'error_code': 'changed'}, clock=lambda: NOW)
    rated = ledger.append_market_watch_message_event(first['message_id'], 'rating', {
        'kind': 'rated', 'source': 'owner_report', 'channel': 'none', 'occurred_at': NOW.isoformat(), 'rating': 'useful'}, clock=lambda: NOW)
    assert rated['kind'] == 'rated' and rated['source'] == 'owner_report'


def test_tools_disabled_by_default_and_scoped_audited_without_provider_calls(harness, tmp_path):
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        tools = rpc(client, '', {}, harness.token(), 'tools/list').json()['result']['tools']
        assert not any(t['name'].startswith('market_watch') for t in tools)
    directory = tmp_path / 'market-public'
    directory.mkdir()
    publish_snapshot(directory, fixture_snapshot())
    harness.configure(market_watch_snapshots_dir=str(directory))
    scope = 'check:read market-watch:read market-watch:submit'
    before = len(harness.requests)
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        assert call(client, 'market_watch_snapshot', {}, harness.token())['isError']
        assert rpc(client, 'market_watch_snapshot', {}, harness.token(subject='other', scope=scope)).status_code == 401
        inp = call(client, 'market_watch_snapshot', {}, harness.token(scope=scope))['structuredContent']
        assert call(client, 'market_watch_snapshot', {'path': '/etc/passwd'}, harness.token(scope=scope))['isError']
        req = request(inp['input_id'])
        assert call(client, 'market_watch_submit', req, harness.token(scope='check:read market-watch:read'))['isError']
        receipt = call(client, 'market_watch_submit', req, harness.token(scope=scope))['structuredContent']
        assert receipt['read_id']
        context = call(client, 'market_watch_snapshot', {}, harness.token(scope=scope))['structuredContent']['context']
        assert context['latest_read']['read_id'] == receipt['read_id']
        assert context['discretionary_intents_remaining'] == 2
        (directory / 'latest.json').unlink()
        missing = call(client, 'market_watch_snapshot', {}, harness.token(scope=scope))['structuredContent']
        assert missing['status'] == 'unavailable'
        assert missing['context']['latest_read']['read_id'] == receipt['read_id']
    assert len(harness.requests) == before
    config = json.loads(harness.config_path.read_text())
    with sqlite3.connect(config['ledger_file']) as db:
        names = [r[0] for r in db.execute('SELECT tool FROM tool_call')]
        assert 'market_watch_snapshot' in names and 'market_watch_submit' in names
    # Existing shadow ordering counts market-watch calls as other tools.
    from tests.test_cloud_mcp_shadow import setup, hashed
    candidate = hashed(setup(NOW))
    actor = config['profiles'][0]['id']
    result = Ledger(config['ledger_file']).decide(actor, candidate, 'skip', 'fixture', NOW)
    assert result['clean_order'] is False


def test_receipt_failure_is_atomic_and_clock_sampled_under_lock(ledger, monkeypatch):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'])
    real_insert = ledger.insert
    def fail_comparator(db, table, record, key, operation=None, request_hash=None):
        if table == 'market_watch_comparator':
            raise sqlite3.OperationalError('fixture disk failure')
        return real_insert(db, table, record, key, operation, request_hash)
    monkeypatch.setattr(ledger, 'insert', fail_comparator)
    with pytest.raises(sqlite3.OperationalError):
        ledger.submit(ACTOR, req, lambda: NOW)
    assert ledger.export(ledger.ledger.path, ACTOR)['reads'] == []
    monkeypatch.setattr(ledger, 'insert', real_insert)
    def clock():
        with sqlite3.connect(ledger.ledger.path, timeout=0) as db:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                db.execute('BEGIN IMMEDIATE')
        return NOW + timedelta(seconds=2)
    receipt = ledger.submit(ACTOR, req, clock)
    assert receipt['received_at'] == (NOW + timedelta(seconds=2)).isoformat()


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), True, -.1, 1.1])
def test_invalid_probability_refused(ledger, bad):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'])
    req['forecasts'][0]['probability'] = bad
    with pytest.raises(ValueError):
        ledger.submit(ACTOR, req, lambda: NOW)


def test_overlong_evidence_list_refuses_atomically_and_parent_pointers_recover(ledger):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    req = request(inp['input_id'], message_intent='none')
    # The first live scheduled read enumerated 13 valid fields. Its request
    # must remain rejected; the caller can cite their existing parent instead.
    fields = ('price', 'return_vs_prior_close', 'session_open', 'vwap', 'or15_high', 'or15_low')
    req['main']['supporting_refs'] = [f'/indices/{symbol}/{field}'
        for symbol in ('SPY', 'QQQ') for field in fields] + ['/gaps']
    with pytest.raises(ValueError, match='Invalid evidence references'):
        ledger.submit(ACTOR, req, lambda: NOW)
    exported = ledger.export(ledger.ledger.path, ACTOR)
    assert exported['reads'] == exported['comparators'] == exported['messages'] == []
    req['main']['supporting_refs'] = ['/indices/SPY', '/indices/QQQ', '/gaps']
    receipt = ledger.submit(ACTOR, req, lambda: NOW)
    replay = ledger.submit(ACTOR, req, lambda: NOW)
    assert replay['read_id'] == receipt['read_id'] and replay['replayed']
    exported = ledger.export(ledger.ledger.path, ACTOR)
    assert len(exported['reads']) == len(exported['comparators']) == 1
    assert exported['messages'] == []


def test_scope_config_rejects_private_path_aliases(harness, tmp_path):
    from cloud_mcp_check_common import CheckConfig
    body = json.loads(harness.config_path.read_text())
    for directory in (str(tmp_path), body['ledger_file'], '/tmp/../private'):
        with pytest.raises(ValueError):
            CheckConfig.model_validate({**body, 'market_watch_snapshots_dir': directory})


def test_comparator_frozen_constants_and_stale_missing_refusal():
    from market_watch_ledger import comparator
    snapshot = fixture_snapshot()
    read = {'read_id': 'fixture'}
    for group in snapshot['indices'].values():
        group['vwap'] = {'value': 105, 'status': 'fresh'}
        group['bar_1m']['close'] = 100
    snapshot['indices']['SPY']['or15_low'] = {'value': 101, 'status': 'fresh'}
    snapshot['indices']['SPY']['or15_high'] = {'value': 110, 'status': 'fresh'}
    snapshot['indices']['QQQ']['or15_low'] = {'value': None, 'status': 'missing'}
    result = comparator(snapshot, read, NOW)
    assert result['signal'] == 'down' and set(result['probabilities'].values()) == {.65}
    for group in snapshot['indices'].values():
        group['bar_1m']['close'] = 111
    result = comparator(snapshot, read, NOW)
    assert result['signal'] == 'up' and set(result['probabilities'].values()) == {.35}
    snapshot['indices']['SPY']['bar_1m']['close'] = 106
    assert comparator(snapshot, read, NOW)['signal'] == 'neutral'
    assert comparator(snapshot, read, NOW + timedelta(seconds=181))['signal'] == 'unavailable'
    snapshot['indices']['SPY']['vwap'] = {'value': None, 'status': 'missing'}
    assert comparator(snapshot, read, NOW)['probabilities']['30m'] is None


def test_current_session_context_recovers_parent_without_other_actor_data(ledger):
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    assert inp['context']['latest_read'] is None
    assert inp['context']['discretionary_intents_remaining'] == 3
    receipt = ledger.submit(ACTOR, request(inp['input_id']), lambda: NOW)
    recovered = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)['context']
    assert recovered['latest_read']['read_id'] == receipt['read_id']
    assert recovered['latest_message_intent']['message_id'] == receipt['message_id']
    assert recovered['latest_message_intent']['read']['read_id'] == receipt['read_id']
    assert recovered['discretionary_intents_remaining'] == 2
    assert recovered['delivery_status'] == 'unverified'
    assert ledger.context(OTHER, lambda: NOW)['latest_read'] is None
    next_day = ledger.context(ACTOR, lambda: NOW + timedelta(days=1))
    assert next_day['latest_read'] is None
    assert next_day['discretionary_intents_remaining'] == 3


def test_daily_intent_budget_atomic_recovery_and_corrections(ledger):
    from market_watch_ledger import MessageBudgetExceeded
    inp = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    parent = None
    requests, receipts = [], []
    for i in range(3):
        req = request(inp['input_id'], operation_id=f'message-{i}', previous_read_id=parent)
        receipt = ledger.submit(ACTOR, req, lambda: NOW)
        requests.append(req)
        receipts.append(receipt)
        parent = receipt['read_id']
    assert ledger.context(ACTOR, lambda: NOW)['discretionary_intents_remaining'] == 0
    # A lost response recovers even after the budget is used and on the next day.
    assert ledger.submit(ACTOR, requests[0], lambda: NOW + timedelta(days=1))['read_id'] == receipts[0]['read_id']
    denied = request(inp['input_id'], operation_id='fourth', previous_read_id=parent)
    with pytest.raises(MessageBudgetExceeded):
        ledger.submit(ACTOR, denied, lambda: NOW)
    assert len(ledger.export(ledger.ledger.path, ACTOR)['reads']) == 3
    # A denied intent does not erase the observation: the same uncommitted
    # operation can be saved without an intent.
    fourth = ledger.submit(ACTOR, {**denied, 'message_intent': 'none'}, lambda: NOW)
    assert fourth['message_id'] is None
    corrected = ledger.submit(ACTOR, request(inp['input_id'], operation_id='correction',
        previous_read_id=fourth['read_id'], message_intent='correction',
        correction_of_read_id=receipts[0]['read_id']), lambda: NOW)
    assert corrected['message_id'] is not None
    assert ledger.context(ACTOR, lambda: NOW)['discretionary_intents_remaining'] == 0
    # Corrections cannot manufacture a budget exemption for an unmessaged read.
    with pytest.raises(ValueError, match='earlier intent'):
        ledger.submit(ACTOR, request(inp['input_id'], operation_id='fake-correction',
            previous_read_id=corrected['read_id'], message_intent='correction',
            correction_of_read_id=fourth['read_id']), lambda: NOW)
