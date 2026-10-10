"""Historical demo MCP: signed OAuth, frozen ownership and shared browser receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select

from app.engine import access, cloud_practice_access, historical_replay
from app.main import app
from app.models import AccessPrincipal, DecisionContext, DecisionEvent, DecisionRecord, Fill, JobRun
from cloud_mcp_d1 import create_server
from tests.test_browser_access import boundary as boundary  # noqa: F401
from tests.test_historical_replay import historical as historical, choose, start  # noqa: F401
from tests.test_cloud_mcp_d0 import (signing_key as signing_key, _token, _jwks, _write_config,
    _request, PROFILE_ID, ISSUER, JWKS_URL)  # noqa: F401


@pytest.fixture
def linked(historical, signing_key, tmp_path):
    h = historical
    config, keys = tmp_path / 'historical.json', tmp_path / 'keys.json'
    _write_config(config, sample_only=True, exercise_kind='historical', decision_writes=True,
        jwks_file=str(keys), backend_socket=str(tmp_path / 'reads.sock'),
        profiles=[{'subject': 'owner-subject', 'id': PROFILE_ID, 'enabled': True,
                   'principal_id': 'history-test', 'principal_version': 1}])
    now = int(time.time())
    keys.write_text(json.dumps({'issuer_url': ISSUER, 'jwks_url': JWKS_URL, 'fetched_at': now,
        'expires_at': now + 3600, 'keys': _jwks(signing_key.public_key())['keys']}))
    for flag in ('TJ_CLOUD_MCP_ENABLED', 'TJ_CLOUD_MCP_HISTORICAL_ENABLED', 'TJ_CLOUD_MCP_DECISION_WRITES'):
        h.b.patch.setenv(flag, 'true')
    h.b.patch.setenv('TJ_CLOUD_MCP_CONFIG', str(config))
    h.b.patch.setattr(app.state, 'cloud_mcp_sample_only', True, raising=False)
    cloud_practice_access.verifier.cache_clear()
    token = _token(signing_key, scope='d0:profile practice:read practice:write')
    with TestClient(app) as client:
        client.headers['authorization'] = 'Bearer ' + token
        yield SimpleNamespace(h=h, config=config, token=token, backend=client, signer=signing_key)
    cloud_practice_access.verifier.cache_clear()


def path(linked, symbol='MU'):
    return f'/cloud-mcp/practice/opportunities/{linked.h.ids[symbol]}/choice'


def payload(linked, decision='skip'):
    value = {'decision': decision, 'rationale': 'Frozen historical evidence only'}
    if decision == 'take':
        value['plan'] = linked.h.plan
    if decision == 'wait':
        value.update(wait_condition='Reassess historical confirmation', wait_expiry=linked.h.plan['expiry'])
    return value


def run_path(linked):
    return f'/cloud-mcp/practice/runs/{linked.h.run_id}'


@pytest.mark.parametrize('decision', ['take', 'wait', 'skip'])
def test_signed_mcp_historical_save_read_retry_browser_identity(linked, decision):
    before = linked.backend.get(run_path(linked))
    assert before.status_code == 200, before.text
    envelope = before.json()
    assert envelope['schema_version'] == 'historical-demo-practice-v1'
    assert envelope['sample_data'] is False and envelope['demo_only'] is True
    browser = linked.h.b.public.get(f'/practice/runs/{linked.h.run_id}').json()
    assert envelope['run'] == browser
    with Session(linked.h.b.engine) as db:
        snapshots = {m.__name__: [r.model_dump(mode='json') for r in db.exec(select(m)).all()]
                     for m in (DecisionContext, DecisionEvent, Fill, JobRun)}
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        args = {'opportunity_id': str(linked.h.ids['MU']), **payload(linked, decision)}
        first = _request(client, 'tools/call', {'name': 'record_practice_choice', 'arguments': args}, linked.token)['result']
        assert not first.get('isError'), first
        saved = first['structuredContent']
        assert saved['schema_version'] == 'historical-demo-choice-v1' and saved['created']
        assert saved['choice']['status'] == 'practice_draft_unarmed'
        retry = _request(client, 'tools/call', {'name': 'record_practice_choice', 'arguments': args}, linked.token)['result']['structuredContent']
        assert retry['created'] is False and retry['choice'] == saved['choice']
        read = _request(client, 'tools/call', {'name': 'get_practice_choice',
            'arguments': {'opportunity_id': args['opportunity_id']}}, linked.token)['result']['structuredContent']
        assert read['choice'] == saved['choice']
    browser = linked.h.b.public.get(f'/practice/runs/{linked.h.run_id}').json()
    assert browser['opportunities'][0]['choice'] == saved['choice']
    with Session(linked.h.b.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 1
        assert snapshots == {m.__name__: [r.model_dump(mode='json') for r in db.exec(select(m)).all()]
                             for m in (DecisionContext, DecisionEvent, Fill, JobRun)}
    # Recreating both adapter and backend token verifier retains persisted bytes.
    cloud_practice_access.verifier.cache_clear()
    assert linked.backend.get(path(linked)).json()['choice'] == saved['choice']


def test_browser_first_concurrent_retry_conflict_and_expired_receipt(linked):
    assert choose(linked.h, decision='take').status_code == 201
    expected = linked.backend.get(path(linked)).json()['choice']
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Browser rationale must match byte-for-byte.
        body = {**payload(linked, 'take'), 'rationale': 'Historical fixture choice; no live performance claim'}
        assert set(pool.map(lambda _: linked.backend.post(path(linked), json=body).status_code, range(4))) == {200}
    assert linked.backend.post(path(linked), json=payload(linked)).status_code == 409
    with Session(linked.h.b.engine) as db:
        from app.models import PracticeRun
        run = db.get(PracticeRun, linked.h.run_id)
        run.deadline = access.now() - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert linked.backend.post(path(linked), json=body).status_code == 200
    assert linked.backend.get(path(linked)).json()['choice'] == expected
    assert linked.backend.post(path(linked, 'NBIS'), json=payload(linked)).status_code == 422


def test_replay_results_and_continuation_never_enter_mcp_projection(linked):
    assert choose(linked.h).status_code == 201
    assert start(linked.h).status_code == 201
    def forbidden(*args, **kwargs):
        raise AssertionError('MCP must not inspect replay events or sealed continuation')
    linked.h.b.patch.setattr(historical_replay, 'replay_view', forbidden)
    result = linked.backend.get(run_path(linked))
    assert result.status_code == 200, result.text
    assert all(o['replay'] is None for o in result.json()['run']['opportunities'])
    assert 'nonce' not in result.text and 'continuation' not in result.text
    assert linked.backend.get(path(linked)).status_code == 200


@pytest.mark.parametrize('flag', ['TJ_CLOUD_MCP_HISTORICAL_ENABLED', 'TJ_HISTORICAL_REPLAY_ENABLED',
    'TJ_MARKET_DECISION_WRITES', 'TJ_DOT_TRIAL_ENABLED', 'TJ_ACCESS_SAMPLE_DATA'])
def test_disabled_demo_boundary_refuses_reads_and_writes(linked, flag):
    linked.h.b.patch.setenv(flag, 'false')
    assert linked.backend.get(run_path(linked)).status_code in {403, 503}
    assert linked.backend.post(path(linked), json=payload(linked)).status_code in {403, 503}


@pytest.mark.parametrize('change', [{'enabled': False}, {'version': 2},
    {'credential_expires_at': access.now() - timedelta(seconds=1)},
    {'grants_json': json.dumps({'symbols': ['MU'], 'run_ids': [], 'journal_read': False})}])
def test_current_revocation_and_assignment_denials(linked, change):
    with Session(linked.h.b.engine) as db:
        principal = db.get(AccessPrincipal, 'history-test')
        for key, value in change.items():
            setattr(principal, key, value)
        db.add(principal)
        db.commit()
    assert linked.backend.get(run_path(linked)).status_code in {401, 403}
    assert linked.backend.post(path(linked), json=payload(linked)).status_code in {401, 403}


def test_read_scope_config_mode_binding_and_integrity(linked):
    readonly = _token(linked.signer, scope='d0:profile practice:read')
    assert linked.backend.get(run_path(linked), headers={'authorization': 'Bearer ' + readonly}).status_code == 200
    assert linked.backend.post(path(linked), headers={'authorization': 'Bearer ' + readonly}, json=payload(linked)).status_code == 401
    with Session(linked.h.b.engine) as db:
        from app.models import PracticeOpportunity
        opp = db.get(PracticeOpportunity, linked.h.ids['MU'])
        context = db.get(DecisionContext, opp.context_id)
        context.data_json += ' '
        db.add(context)
        db.commit()
    assert linked.backend.get(run_path(linked)).status_code == 404
    assert linked.backend.post(path(linked), json=payload(linked)).status_code == 404
    config = json.loads(linked.config.read_text())
    config['exercise_kind'] = 'synthetic'
    linked.config.write_text(json.dumps(config))
    assert linked.backend.get(run_path(linked)).status_code == 401


def test_lost_response_and_permission_revoked_during_body(linked):
    dropped = False
    async def transport(request):
        nonlocal dropped
        response = await httpx.ASGITransport(app=app).handle_async_request(request)
        if request.method == 'POST' and not dropped:
            dropped = True
            await response.aread()
            raise httpx.ReadError('Lost committed response', request=request)
        return response
    server = create_server(linked.config, backend_transport=httpx.MockTransport(transport))
    with TestClient(server.streamable_http_app()) as client:
        args = {'opportunity_id': str(linked.h.ids['MU']), **payload(linked)}
        result = _request(client, 'tools/call', {'name': 'record_practice_choice', 'arguments': args}, linked.token)['result']
        assert result['isError'] and 'receipt' in json.dumps(result)
        recovered = _request(client, 'tools/call', {'name': 'get_practice_choice',
            'arguments': {'opportunity_id': args['opportunity_id']}}, linked.token)['result']['structuredContent']
        assert recovered['status'] == 'recorded'
    from app.routers import cloud_choices
    original = cloud_choices._parse_choice
    def revoke(raw):
        with Session(linked.h.b.engine) as db:
            principal = db.get(AccessPrincipal, 'history-test')
            principal.enabled = False
            db.add(principal)
            db.commit()
        return original(raw)
    linked.h.b.patch.setattr(cloud_choices, '_parse_choice', revoke)
    assert linked.backend.post(path(linked, 'NBIS'), json=payload(linked)).status_code == 403
    with Session(linked.h.b.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 1


def test_mismatched_frozen_actor_and_spoofed_fields(linked):
    from app.models import PracticeRun
    import uuid
    assert linked.backend.get(f'/cloud-mcp/practice/runs/{uuid.uuid4()}').status_code == 404
    assert linked.backend.get(path(linked).replace(str(linked.h.ids['MU']), str(uuid.uuid4()))).status_code == 404
    for key in ('actor', 'context_id', 'operation_id', 'symbol'):
        assert linked.backend.post(path(linked), json={**payload(linked), key: 'spoof'}).status_code == 422
    with Session(linked.h.b.engine) as db:
        run = db.get(PracticeRun, linked.h.run_id)
        metadata = json.loads(run.brief_json)
        metadata[0]['assigned_agent'] = 'agent:another-assistant'
        run.brief_json = json.dumps(metadata)
        db.add(run)
        db.commit()
    assert linked.backend.get(run_path(linked)).status_code == 404
    assert linked.backend.post(path(linked), json=payload(linked)).status_code == 404


def test_missing_minutes_and_original_clocks_survive_exact_projection(linked):
    from copy import deepcopy
    original = deepcopy(linked.h.original)
    bars = original['packets']['NBIS']['recent_minute_bars']
    cutoff = original['simulated_as_of']
    # Remove three supplied pre-cutoff minutes; do not fill them forward.
    from app.engine import decisions
    before = [bar for bar in bars if decisions._utc(bar['t'], 'bar') < decisions._utc(cutoff, 'cutoff')]
    removed = {bar['t'] for bar in before[3:6]}
    original['packets']['NBIS']['recent_minute_bars'] = [bar for bar in bars if bar['t'] not in removed]
    with Session(linked.h.b.engine) as db:
        run = historical_replay.prepare(db, original, identifier='history-gaps', proof=True)
        new_id = run.id
    grants = {**linked.h.grants, 'run_ids': [str(new_id)]}
    made = linked.h.b.owner.post('/access/assistants', json={'identifier': 'history-gaps', 'grants': grants})
    assert made.status_code == 201, made.text
    from tests.test_browser_access import signin
    assert signin(linked.h.b, identifier='history-gaps', key=made.json()['key']).status_code == 200
    config = json.loads(linked.config.read_text())
    config['profiles'][0]['principal_id'] = 'history-gaps'
    linked.config.write_text(json.dumps(config))
    cloud_practice_access.verifier.cache_clear()
    response = linked.backend.get(f'/cloud-mcp/practice/runs/{new_id}')
    assert response.status_code == 200, response.text
    browser = linked.h.b.public.get(f'/practice/runs/{new_id}')
    assert browser.status_code == 200, browser.text
    assert response.json()['run'] == browser.json()
    nbis = next(o for o in response.json()['run']['opportunities'] if o['symbol'] == 'NBIS')
    packet = nbis['context']['packet']
    assert len(packet['recent_minute_bars']) == 57
    assert not removed & {bar['t'] for bar in packet['recent_minute_bars']}
    assert packet['simulated_as_of'] == original['simulated_as_of']
    assert packet['retrieved_at'] == original['captured_at']
    assert linked.backend.get(run_path(linked)).status_code == 404


@pytest.mark.parametrize("change", ["context", "assignment", "deleted_opportunity"])
def test_frozen_resource_changed_during_body_is_refused(linked, change):
    from app.routers import cloud_choices
    from app.models import PracticeOpportunity
    original = cloud_choices._parse_choice
    def corrupt(raw):
        with Session(linked.h.b.engine) as db:
            opp = db.get(PracticeOpportunity, linked.h.ids['MU'])
            if change == 'context':
                context = db.get(DecisionContext, opp.context_id)
                context.data_json += ' '
                db.add(context)
            elif change == 'deleted_opportunity':
                db.delete(opp)
            else:
                from app.models import PracticeRun
                run = db.get(PracticeRun, linked.h.run_id)
                metadata = json.loads(run.brief_json)
                metadata[0]['assigned_agent'] = 'agent:another-assistant'
                run.brief_json = json.dumps(metadata)
                db.add(run)
            db.commit()
        return original(raw)
    linked.h.b.patch.setattr(cloud_choices, '_parse_choice', corrupt)
    response = linked.backend.post(path(linked), json=payload(linked))
    assert response.status_code in {404, 422}, response.text
    with Session(linked.h.b.engine) as db:
        assert not db.exec(select(DecisionRecord)).all()
