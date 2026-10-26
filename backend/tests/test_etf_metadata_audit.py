"""No network, real data, broker or Factory evaluations; synthetic metadata only."""
from copy import deepcopy
import json

import httpx
import pytest

from scripts.etf_metadata_audit import (
    ACTIONS_URL, ASSET_URL, AuditError, FIXTURE, MetadataReader,
    audit, fixture_audit, main,
)


@pytest.fixture
def data():
    return json.loads(FIXTURE.read_text())


def run(data):
    calls = []
    def fetch(url, params):
        calls.append((url, deepcopy(params)))
        if url.startswith(ASSET_URL):
            return data['assets'][url.removeprefix(ASSET_URL)]
        return data['pages'][int(params.get('page_token', '0'))]
    result = audit(fetch, data['start'], data['end'], expected=data['expected'],
                   clock=lambda: '2026-10-26T12:00:00+00:00')
    return result, calls


def test_pagination_dates_incomplete_and_missing_known_event(data):
    original = deepcopy(data)
    result, calls = run(data)
    assert data == original
    assert len(calls) == 6
    assert calls[-1][1]['page_token'] == '1'
    assert all(p['data_quality'] == 'all' for u, p in calls if u == ACTIONS_URL)
    assert result['pagination_complete'] is True
    assert result['historical_coverage'] == 'unverified'
    assert result['eligible_for_evaluation'] is False
    assert result['exact_duplicates_ignored'] == 1
    assert len(result['actions']) == 2
    first = result['actions'][0]
    assert first['dates']['ex_date'] == '2023-09-15'
    assert first['dates']['process_date'] == '2023-10-31'
    assert first['observed_at'].startswith('2026-10-26')
    assert first['known_at'] is None
    assert {i['reason'] for i in result['issues']} == {
        'missing_or_changed_cusip', 'missing_effective_date', 'expected_event_not_observed'}


def test_changed_duplicate_preserved_and_flagged(data):
    data['pages'][1]['corporate_actions']['cash_dividends'][0]['rate'] = '2.00'
    result, _ = run(data)
    assert len(result['actions']) == 3
    assert any(i['reason'] == 'conflicting_action_id' for i in result['issues'])


@pytest.mark.parametrize('value', [123, [], 'x'*4097, '1'])
def test_invalid_or_looping_tokens_fail_closed(data, value):
    data['pages'][1]['next_page_token'] = value
    with pytest.raises(AuditError):
        run(data)


def test_page_cap_not_reported_complete(data, monkeypatch):
    import scripts.etf_metadata_audit as module
    monkeypatch.setattr(module, 'MAX_PAGES', 1)
    with pytest.raises(AuditError, match='page cap'):
        run(data)


@pytest.mark.parametrize('raw', [{}, {'corporate_actions': None}, {'corporate_actions': []},
                                 {'corporate_actions': {'cash_dividends': 'bad'}}])
def test_malformed_envelope_is_not_empty_coverage(data, raw):
    data['pages'][0] = raw
    with pytest.raises(AuditError):
        run(data)


@pytest.mark.parametrize('change', [{'symbol': 'QQQ'}, {'id': None}, {'class': 'crypto'}])
def test_identity_mismatch_rejected(data, change):
    data['assets']['SPY'].update(change)
    with pytest.raises(AuditError):
        run(data)


def test_identity_ids_must_be_distinct(data):
    data['assets']['EFA']['id'] = data['assets']['SPY']['id']
    with pytest.raises(AuditError):
        run(data)


@pytest.mark.parametrize('field,value,reason', [
    ('id', None, 'missing_action_id'), ('symbol', 'QQQ', 'missing_or_unexpected_symbol'),
    ('process_date', None, 'missing_process_date'), ('ex_date', 'not-a-date', 'invalid_date'),
])
def test_incomplete_records_retained_and_flagged(data, field, value, reason):
    data['pages'][0]['corporate_actions']['cash_dividends'][0][field] = value
    result, _ = run(data)
    assert any(i['reason'] == reason for i in result['issues'])
    assert result['actions'][0]['raw'][field] == value


def test_empty_terminal_page_is_not_proof_of_historical_coverage(data):
    data['pages'] = [{'corporate_actions': {}, 'next_page_token': None}]
    result, _ = run(data)
    assert result['pagination_complete']
    assert result['historical_coverage'] == 'unverified'
    assert result['issues'][0]['reason'] == 'expected_event_not_observed'


def test_known_event_found(data):
    data['expected'] = [{'symbol': 'SPY', 'ex_date': '2023-09-15'}]
    result, _ = run(data)
    assert not any(i['reason'] == 'expected_event_not_observed' for i in result['issues'])


@pytest.mark.parametrize('start,end', [('2024-01-01','2023-01-01'), ('2020-01-01','2023-01-01'), ('bad','bad')])
def test_window_rejected_before_transport(start, end):
    with pytest.raises(ValueError):
        audit(lambda *_: pytest.fail('transport called'), start, end)


@pytest.mark.parametrize('status', [301, 302, 401, 403, 429, 500])
def test_http_failure_is_redacted_and_never_retried(status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET_BODY', headers={'Location':'https://example.org'})
    reader = MetadataReader('SECRET_KEY','SECRET_SECRET', transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(AuditError) as exc:
            reader(ACTIONS_URL, {})
        assert 'SECRET' not in str(exc.value)
        assert len(calls) == 1
        assert calls[0].method == 'GET'
    finally:
        reader.close()


@pytest.mark.parametrize('url', ['https://api.alpaca.markets/v2/orders',
                                'https://data.alpaca.markets/v2/stocks/bars',
                                ASSET_URL+'SPY/../orders', 'https://example.org'])
def test_endpoint_allowlist_precedes_transport(url):
    reader = MetadataReader('key','secret', transport=httpx.MockTransport(lambda r: pytest.fail('request escaped')))
    try:
        with pytest.raises(AuditError, match='allowlist'):
            reader(url, {})
    finally:
        reader.close()


@pytest.mark.parametrize('body', [b'invalid JSON', b'x'*2_000_001])
def test_invalid_or_oversized_response_refused(body):
    reader = MetadataReader('key','secret', transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)))
    try:
        with pytest.raises(AuditError):
            reader(ACTIONS_URL, {})
    finally:
        reader.close()


def test_transport_budget():
    reader = MetadataReader('key','secret', transport=httpx.MockTransport(lambda r: httpx.Response(200,json={})))
    try:
        reader.requests = 14
        with pytest.raises(AuditError, match='cap'):
            reader(ACTIONS_URL,{})
    finally:
        reader.close()


def test_default_cli_is_offline(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['etf_metadata_audit'])
    monkeypatch.setattr(httpx.Client, 'stream', lambda *_a, **_kw: pytest.fail('network attempted'))
    main()
    assert json.loads(capsys.readouterr().out)['source'] == 'invented_fixture'
    assert fixture_audit()['historical_known_at'] == 'unavailable'


def test_metadata_cli_missing_credentials_stops(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['etf_metadata_audit','--fetch-metadata','--start','2023-01-01','--end','2023-01-31'])
    monkeypatch.delenv('ALPACA_API_KEY', raising=False)
    monkeypatch.delenv('ALPACA_API_SECRET', raising=False)
    monkeypatch.setattr(httpx.Client, 'stream', lambda *_a, **_kw: pytest.fail('network attempted'))
    with pytest.raises(AuditError, match='explicitly supplied'):
        main()
    assert capsys.readouterr().out == ''


def test_archived_split_sentinel_automatically_checked(data):
    def fetch(url, params):
        if url.startswith(ASSET_URL):
            return data['assets'][url.removeprefix(ASSET_URL)]
        return {'corporate_actions': {}, 'next_page_token': None}
    result = audit(fetch, '2008-07-01', '2008-08-15')
    assert result['expected_events_checked'] == [{'symbol':'EEM','ex_date':'2008-07-24','kind':'forward_splits'}]
    assert result['issues'][0]['reason'] == 'expected_event_not_observed'
