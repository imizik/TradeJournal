"""Jo-visible refusals and bounded retry flows, with disposable actor-bound ledgers."""
import copy
from datetime import timedelta
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from cloud_mcp_check_ledger import Ledger
from market_watch_ledger import MarketWatchLedger
from app.engine.market_watch_snapshot import publish_snapshot
from tests.test_cloud_mcp_check import harness as harness, signing_key as signing_key, call
from tests.test_market_watch_ledger import request, OTHER
from tests.test_market_watch_snapshot import NOW
from tests.test_tradier_jo_delivery import full_market_snapshot

SCOPE = 'check:read market-watch:read market-watch:submit'


@pytest.fixture
def market(harness, tmp_path):
    public, outbox = tmp_path / 'public', tmp_path / 'outbox'
    public.mkdir()
    outbox.mkdir()
    publish_snapshot(public, full_market_snapshot())
    harness.configure(market_watch_snapshots_dir=str(public), market_watch_outbox_dir=str(outbox))
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        token = harness.token(scope=SCOPE)
        inp = call(client, 'market_watch_snapshot', {}, token)['structuredContent']
        config = json.loads(harness.config_path.read_text())
        ledger = MarketWatchLedger(Ledger(config['ledger_file']))
        yield client, token, inp, ledger, config['profiles'][0]['id'], outbox
    assert not harness.requests


def submit(market, req):
    return call(market[0], 'market_watch_submit', req, market[1])


def refused(result, code):
    assert result['isError'], result
    text = result['content'][0]['text']
    assert f'[{code}]' in text, text
    assert 'private-sentinel' not in text
    return text


@pytest.mark.parametrize('field,value,detail', [
    ('main', {'text': 'private-sentinel'}, 'main: require exactly'),
    ('change_summary', 'private-sentinel' * 150, 'change_summary'),
    ('main', {'text': 'Weak', 'supporting_refs': ['/indices/SPY'] * 11, 'contradicting_refs': []},
     'main.supporting_refs: require a list of at most 10'),
    ('main', {'text': 'Weak', 'supporting_refs': ['/private-sentinel'], 'contradicting_refs': []},
     'main.supporting_refs[0]'),
    ('main', {'text': 'Weak', 'supporting_refs': ['/bad~2private-sentinel'], 'contradicting_refs': []},
     'main.supporting_refs[0]'),
    ('forecasts', [{'horizon': ['private-sentinel']}] * 3, 'three forecast horizons'),
    ('forecasts', [{'horizon': h, 'predicate': 'private-sentinel', 'probability': .6}
                   for h in ('30m', '60m', 'close')], 'forecasts[0]'),
    ('forecasts', [{'horizon': h, 'predicate': 'spy_return_lt_zero', 'probability': 60}
                   for h in ('30m', '60m', 'close')], 'Invalid probability'),
    ('forecasts', [{'horizon': h, 'predicate': 'spy_return_lt_zero', 'probability': None}
                   for h in ('30m', '60m', 'close')], 'abstention_reason'),
    ('phone_summary', 'private-sentinel' * 1200, '16 KiB'),
])
def test_invalid_content_names_rule_then_same_operation_repairs_once(market, field, value, detail):
    req = request(market[2]['input_id'])
    bad = copy.deepcopy(req)
    bad[field] = value
    assert detail in refused(submit(market, bad), 'invalid_content')
    ledger, actor, outbox = market[3:]
    assert ledger.export(ledger.ledger.path, actor)['reads'] == []
    assert list(outbox.iterdir()) == []
    saved = submit(market, req)['structuredContent']
    replay = submit(market, req)['structuredContent']
    assert replay['read_id'] == saved['read_id'] and replay['replayed']
    assert saved['received_at'] == NOW.isoformat()
    exported = ledger.export(ledger.ledger.path, actor)
    assert len(exported['reads']) == len(exported['comparators']) == len(exported['messages']) == 1
    assert len(list(outbox.iterdir())) == 1


def test_parent_refresh_recovery_and_committed_operation_conflict(market):
    first_req = request(market[2]['input_id'])
    first = submit(market, first_req)['structuredContent']
    stale = request(market[2]['input_id'], operation_id='second', message_intent='none')
    assert 'not saved' in refused(submit(market, stale), 'parent_conflict')
    fresh = call(market[0], 'market_watch_snapshot', {}, market[1])['structuredContent']
    assert fresh['context']['latest_read']['read_id'] == first['read_id']
    repaired = {**stale, 'input_id': fresh['input_id'],
                'previous_read_id': fresh['context']['latest_read']['read_id'],
                'change_summary': 'Reconsidered against the latest read; unchanged view, no message.'}
    second = submit(market, repaired)['structuredContent']
    assert second['read_id'] != first['read_id']
    assert submit(market, repaired)['structuredContent']['replayed']
    assert 'do not change the ID' in refused(submit(market, {**repaired, 'view': 'up'}), 'operation_conflict')
    # Recover the first operation even when it is no longer the latest parent.
    assert submit(market, first_req)['structuredContent']['read_id'] == first['read_id']
    ledger, actor, outbox = market[3:]
    exported = ledger.export(ledger.ledger.path, actor)
    assert len(exported['reads']) == len(exported['comparators']) == 2
    assert len(exported['messages']) == 1
    assert len(list(outbox.iterdir())) == 2


def test_missing_and_other_actor_inputs_are_indistinguishable(market):
    other = market[3].serve(OTHER, full_market_snapshot(), lambda: NOW)
    missing = refused(submit(market, request('private-sentinel')), 'input_unavailable')
    foreign = refused(submit(market, request(other['input_id'])), 'input_unavailable')
    assert foreign == missing
    assert other['input_id'] not in foreign and OTHER not in foreign
    assert submit(market, request(market[2]['input_id']))['structuredContent']['read_id']


def test_prior_session_input_has_specific_error(market, harness):
    with TestClient(harness.server(now=NOW + timedelta(days=1)).streamable_http_app()) as client:
        refused(call(client, 'market_watch_submit', request(market[2]['input_id']), market[1]),
                'input_not_current_session')
    ledger, actor = market[3:5]
    assert ledger.export(ledger.ledger.path, actor)['reads'] == []


@pytest.mark.parametrize('error,code', [
    (sqlite3.OperationalError('private-sentinel /ledger/path'), 'ledger_unavailable'),
    (ValueError('private-sentinel corrupt record'), 'ledger_state_invalid'),
])
def test_internal_errors_never_expose_raw_details(market, monkeypatch, error, code):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(MarketWatchLedger, 'submit', fail)
    message = refused(submit(market, request(market[2]['input_id'])), code)
    assert 'unconfirmed' in message and 'not saved' not in message


def test_lost_response_after_commit_requires_exact_retry_without_duplicate(market, monkeypatch):
    original = MarketWatchLedger.submit
    def save_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError('private-sentinel uncertain response')
    monkeypatch.setattr(MarketWatchLedger, 'submit', save_then_fail)
    req = request(market[2]['input_id'])
    assert 'Retry EXACT' in refused(submit(market, req), 'ledger_unavailable')
    monkeypatch.setattr(MarketWatchLedger, 'submit', original)
    recovered = submit(market, req)['structuredContent']
    assert recovered['replayed'] and recovered['read_id'] and recovered['received_at']
    ledger, actor, outbox = market[3:]
    exported = ledger.export(ledger.ledger.path, actor)
    assert len(exported['reads']) == len(exported['messages']) == 1
    assert len(list(outbox.iterdir())) == 1


def test_notice_failure_is_saved_and_exact_retry_recovers(market):
    req = request(market[2]['input_id'])
    # Inject a filesystem handoff failure after server configuration validation.
    outbox = market[5]
    outbox.rmdir()
    outbox.write_text('fixture: not a directory')
    result = submit(market, req)
    assert result['isError'] and 'saved but its notice handoff failed' in result['content'][0]['text']
    outbox.unlink()
    outbox.mkdir()
    assert submit(market, req)['structuredContent']['replayed']
    ledger, actor = market[3:5]
    assert len(ledger.export(ledger.ledger.path, actor)['reads']) == 1
    assert len(list(outbox.iterdir())) == 1
