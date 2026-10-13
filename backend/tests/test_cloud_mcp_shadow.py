"""Shadow ledger and isolated MCP, generated tokens/fixture market data only."""
from datetime import timedelta, timezone
import json
import sqlite3
import uuid

from fastapi.testclient import TestClient
import pytest

from cloud_mcp_check_ledger import Ledger, Conflict, digest
import pretrade_features
from tests.test_cloud_mcp_check import harness as harness, signing_key as signing_key, RECEIPT, call, rpc, feature_row


def setup(now=RECEIPT):
    return {"format": "shadow-setup-v1", "candidate_id": str(uuid.uuid4()), "scanner_version": "s1-v1",
        "params_hash": "a" * 64, "session_date": now.date().isoformat(), "symbol": "SPY", "setup": "orb",
        "direction": "long", "bar_start": (now - timedelta(minutes=5)).isoformat(), "bar_end": now.isoformat(),
        "detected_at": now.isoformat(), "expires_at": (now + timedelta(minutes=2)).isoformat(), "stop": 650.,
        "target": 680., "flags": [], "facts": {"close": 660.},
        "contract": {"symbol": "SPY261009C00660000", "option_type": "call", "expiration": "2026-10-09", "strike": 660.}}


def hashed(body):
    return {**body, "content_sha256": digest({k: v for k, v in body.items() if k != "content_sha256"})}


@pytest.fixture
def exchange(harness, tmp_path):
    setups, outbox = tmp_path / "setups", tmp_path / "outbox"
    setups.mkdir()
    outbox.mkdir()
    harness.configure(shadow_setups_dir=str(setups), shadow_outbox_dir=str(outbox))
    candidate = hashed(setup())
    path = setups / f"setup-{candidate['candidate_id']}.json"
    path.write_text(json.dumps(candidate))
    return candidate, path, outbox


def test_ledger_retry_timing_call_order_immutable_and_upgrade(tmp_path):
    path = tmp_path / "ledger.db"
    # An old installation has its original table/row before the additive schema opens.
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE check_result (check_id TEXT PRIMARY KEY, saved_at TEXT NOT NULL, result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL)')
    db.execute('INSERT INTO check_result VALUES (?, ?, ?, ?)', ('legacy', 'then', '{"kept":true}', 'old-hash'))
    db.commit()
    before = digest(db.execute('SELECT * FROM check_result').fetchall())
    ledger = Ledger(path)
    assert digest(db.execute('SELECT * FROM check_result').fetchall()) == before
    candidate = hashed(setup())
    ledger.log_call('actor', 'position_check', RECEIPT - timedelta(seconds=1))
    first = ledger.decide('actor', candidate, 'take', 'trigger', RECEIPT)
    assert first['clean_order'] and first['timing'] == 'on_time'
    assert ledger.decide('actor', candidate, 'take', 'trigger', RECEIPT + timedelta(minutes=5)) == first
    with pytest.raises(Conflict):
        ledger.decide('actor', candidate, 'take', 'changed', RECEIPT)
    ledger.log_call('other', 'position_check', RECEIPT.astimezone(timezone(timedelta(hours=-4))))
    late = ledger.decide('other', candidate, 'skip', 'late', RECEIPT + timedelta(minutes=2))
    assert late['timing'] == 'late' and not late['clean_order']
    for table in ('tool_call', 'shadow_decision'):
        for sql in (f'DELETE FROM {table}', f'UPDATE {table} SET actor="x"'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
    db.close()


def test_shadow_auth_history_order_export_restart(harness, exchange):
    candidate, path, outbox = exchange
    previous = feature_row('2026-10-08T15:59:00', 10., 'old')
    previous['side'] = 'call'
    same_day = {**previous, 'closed_at': '2026-10-09T09:59:00', 'source_fill_key': 'f' * 64}
    pretrade_features.publish([previous, same_day], harness.pointer, now=RECEIPT)
    args = {'candidate_id': candidate['candidate_id']}
    token = harness.token(scope='check:read shadow:decide')
    with TestClient(harness.server().streamable_http_app()) as client:
        for name, params in [('shadow_setup', args), ('shadow_decide', {**args, 'decision': 'take', 'reason': 'break'})]:
            assert call(client, name, params, harness.token())['isError']
            assert rpc(client, name, params, harness.token(subject='other', scope='check:read shadow:decide')).status_code == 401
        view = call(client, 'shadow_setup', args, token)['structuredContent']
        assert view['history']['cohorts'][1]['trades'] == 1
        assert view['history_cutoff'] == '2026-10-09T00:00:00-04:00'
        assert not view['expired']
        assert not {'positions', 'notes', 'captures', 'source_fill_keys'} & view.keys()
        call(client, 'position_check', {}, harness.token())
        result = call(client, 'shadow_decide', {**args, 'decision': 'take', 'reason': 'break'}, token)['structuredContent']
        assert not result['clean_order']
        assert result['actor'] == json.loads(harness.config_path.read_text())['profiles'][0]['id']
    exported = outbox / f"decision-{candidate['candidate_id']}.json"
    assert json.loads(exported.read_text()) == result
    assert digest({k: v for k, v in result.items() if k != 'content_sha256'}) == result['content_sha256']
    exported.unlink()  # Recover a committed decision whose export was lost.
    with TestClient(harness.server(now=RECEIPT + timedelta(minutes=3)).streamable_http_app()) as client:
        assert call(client, 'shadow_setup', args, token)['structuredContent']['expired']
        assert call(client, 'shadow_decide', {**args, 'decision': 'take', 'reason': 'break'}, token)['structuredContent'] == result
        exported.write_text('{}')
        assert call(client, 'shadow_decide', {**args, 'decision': 'take', 'reason': 'break'}, token)['isError']


@pytest.mark.parametrize('change', ['id', 'hash', 'yesterday', 'symlink'])
def test_invalid_setups_refused(harness, exchange, change):
    candidate, path, _ = exchange
    args = {'candidate_id': candidate['candidate_id']}
    if change == 'id':
        args['candidate_id'] = '../ledger.db'
    elif change == 'hash':
        path.write_text(json.dumps({**candidate, 'stop': 1}))
    elif change == 'yesterday':
        path.write_text(json.dumps(hashed({**candidate, 'session_date': '2026-10-08'})))
    else:
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
    with TestClient(harness.server().streamable_http_app()) as client:
        for name, params in [('shadow_setup', args), ('shadow_decide', {**args, 'decision': 'skip', 'reason': 'x'})]:
            assert call(client, name, params, harness.token(scope='check:read shadow:decide'))['isError']


def test_late_and_fail_closed_call_log(harness, exchange, monkeypatch):
    candidate, _, _ = exchange
    with TestClient(harness.server(now=RECEIPT + timedelta(minutes=2)).streamable_http_app()) as client:
        params = {'candidate_id': candidate['candidate_id'], 'decision': 'take', 'reason': 'late'}
        assert call(client, 'shadow_decide', params, harness.token(scope='check:read shadow:decide'))['structuredContent']['timing'] == 'late'
        def fail(*args):
            raise sqlite3.OperationalError('test')
        monkeypatch.setattr(Ledger, 'log_call', fail)
        assert call(client, 'position_check', {}, harness.token())['isError']


def test_disabled_and_restart_required_for_path_change(harness, tmp_path):
    with TestClient(harness.server().streamable_http_app()) as client:
        params = {'candidate_id': str(uuid.uuid4())}
        assert 'shadow not enabled' in call(client, 'shadow_setup', params, harness.token(scope='check:read shadow:decide'))['content'][0]['text']
        harness.configure(shadow_setups_dir=str(tmp_path / 'changed'))
        assert rpc(client, 'shadow_setup', params, harness.token(scope='check:read shadow:decide')).status_code == 401


def test_authenticated_malformed_call_is_still_logged(harness, exchange):
    candidate, _, _ = exchange
    with TestClient(harness.server().streamable_http_app()) as client:
        assert call(client, 'position_check', {'unexpected': True}, harness.token())['isError']
        result = call(client, 'shadow_decide', {'candidate_id': candidate['candidate_id'], 'decision': 'skip', 'reason': 'x'},
            harness.token(scope='check:read shadow:decide'))['structuredContent']
        assert not result['clean_order']


def test_concurrent_decisions_are_one_row(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ledger = Ledger(tmp_path / 'ledger.db')
    candidate = hashed(setup())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ledger.decide('actor', candidate, 'take', 'x', RECEIPT), range(2)))
    assert results[0] == results[1]


def test_decision_clock_and_clean_order_are_taken_under_commit_lock(harness, exchange, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import cloud_mcp_check as service
    candidate, _, _ = exchange
    current = [RECEIPT]
    original_server, original_read = service.create_server, service.read_shadow_setup
    reading, resume = threading.Event(), threading.Event()
    def create(*args, **kwargs):
        return original_server(*args, **{**kwargs, 'clock': lambda: current[0]})
    def read(*args):
        reading.set()
        assert resume.wait(10)
        return original_read(*args)
    monkeypatch.setattr(service, 'create_server', create)
    monkeypatch.setattr(service, 'read_shadow_setup', read)
    with TestClient(harness.server().streamable_http_app()) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(call, client, 'shadow_decide', {'candidate_id': candidate['candidate_id'],
            'decision': 'take', 'reason': 'interleaved'}, harness.token(scope='check:read shadow:decide'))
        assert reading.wait(10)
        try:
            current[0] = RECEIPT + timedelta(minutes=2)
            assert not call(client, 'position_check', {}, harness.token()).get('isError')
        finally:
            resume.set()
        result = pending.result()['structuredContent']
    assert result['timing'] == 'late'
    assert not result['clean_order']
    assert result['committed_at'] == '2026-10-09T14:22:00Z'
