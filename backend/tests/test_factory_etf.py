"""Counted ETF integration over invented prices, ledgers, budgets and artifacts.

No real bundle, environment, ledger, provider, gate evaluation or broker access.
"""
from datetime import date
from dataclasses import replace
from decimal import Decimal
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests import test_factory_intake as shared

intake = shared.intake
fake_worker = shared.fake_worker
search = shared.search
etf = search.etf
NATIVE_POPEN = subprocess.Popen


@pytest.fixture
def bundle(tmp_path, monkeypatch, intake):
    directory = tmp_path / 'invented-bundle'
    directory.mkdir()
    # Sparse INVENTED sessions, deliberately not historical calendar evidence.
    days = [date(2016, m, 28) for m in range(1, 13)] + [date(2017, 1, 31),
            date(2017, 2, 1), date(2017, 2, 28), date(2017, 3, 1), date(2017, 3, 31)]
    rows = [{'day': d.isoformat(), 'close': ['100'] * 5,
             'distribution': ['0'] * 5, 'split': ['1'] * 5} for d in days]
    raw = b''.join(etf.encoded(row) for row in rows)
    (directory / 'sessions.jsonl').write_bytes(raw)
    (directory / 'normalized-actions.json').write_text('{"invented": true}\n')
    calendar = etf.digest(('\n'.join(d.isoformat() for d in days) + '\n').encode())
    monkeypatch.setattr(etf, 'CALENDAR_SHA256', calendar)
    monkeypatch.setattr(etf, 'SESSION_COUNT', len(days))
    monkeypatch.setattr(etf, 'FIRST_LAST', (days[0].isoformat(), days[-1].isoformat()))
    monkeypatch.setattr(etf, 'MONTHLY_COUNT', 2)
    manifest = {'symbols': list(etf.portfolio.SYMBOLS), 'price_window': etf.SPEC['price_window'],
                'sessions': len(days), 'actual_first_last': list(etf.FIRST_LAST),
                'calendar_sha256': calendar,
                'files': {p.name: etf.digest(p.read_bytes()) for p in directory.iterdir()}}
    (directory / 'manifest.json').write_bytes(etf.encoded(manifest))
    monkeypatch.setattr(etf, 'MANIFEST_SHA256', etf.digest(etf.encoded(manifest)))
    for name in etf.CODE_FILES:
        path = intake.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Invented code fingerprint input: ' + name + '\n')
    return directory


def run_etf(intake, bundle, **changes):
    options = dict(spec_path=None, etf_bundle=bundle, authorize_spec=etf.ID,
                   expected_ledger_sha256=search.ledger_snapshot()[1],
                   expected_code_sha256=etf.code_digest(intake.root))
    options.update(changes)
    return search.tick(**options)


def counted_child(intake, monkeypatch, *, failure=None, mutate_result=None):
    """Run real ETF child logic inline; only process transport/PID are invented."""
    starts = []
    monkeypatch.setattr(search.os, 'getppid', search.os.getpid)

    class Process:
        pid = 999999

        def __init__(self, command, **kwargs):
            job = Path(command[-1])
            reservation = json.loads(job.read_text())
            assert search.read_ledger(intake.ledger)[-1] == reservation
            assert reservation['id'] == etf.ID and reservation['spec'] == etf.SPEC
            assert reservation['input_manifest_sha256'] == etf.MANIFEST_SHA256
            assert reservation['code_sha256'] == etf.code_digest(intake.root)
            assert json.loads((search.OUT / '2026-10-25-seconds.json').read_text()) >= reservation['timeout_seconds']
            fd = int(command[command.index('--writer-fd') + 1])
            assert kwargs == {'start_new_session': True, 'pass_fds': (fd,)}
            with (search.OUT / 'writer.lock').open('a') as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            starts.append(reservation)
            self.exit_code = 0
            if failure == 'start':
                raise RuntimeError('invented launch failure')
            if failure == 'evaluation':
                self.exit_code = 1
                return
            if failure == 'timeout':
                return
            if failure == 'changed_input':
                (Path(reservation['input_bundle']) / 'sessions.jsonl').write_text('changed')
                with pytest.raises(ValueError, match='hash mismatch'):
                    search.etf_worker(job, reservation, fd)
                self.exit_code = 1
                return
            search.etf_worker(job, reservation, fd)
            with pytest.raises(FileExistsError):
                search.etf_worker(job, reservation, fd)
            if mutate_result:
                path = job.with_suffix('.result.json')
                result = json.loads(path.read_text())
                mutate_result(result)
                path.write_bytes(etf.encoded(result))

        def wait(self, timeout):
            assert timeout <= 900
            if failure == 'timeout' and timeout != 15:
                raise subprocess.TimeoutExpired('invented', timeout)
            return self.exit_code

    monkeypatch.setattr(search.subprocess, 'Popen', Process)
    return starts


def test_inspection_hashes_only_and_exposes_no_outcomes(intake, bundle, monkeypatch, capsys):
    intake.records([{'id': 'old', 'periods': {'holdout': {'PRIVATE': 999}}}])
    before = {p: p.read_bytes() for p in intake.root.rglob('*') if p.is_file()}
    monkeypatch.setattr(etf, 'load_sessions', lambda *_: pytest.fail('inspection parsed prices'))
    monkeypatch.setattr(etf.portfolio, 'calculate', lambda *_: pytest.fail('inspection calculated returns'))
    search.main(['--inspect-etf-bundle', str(bundle)])
    output = capsys.readouterr().out
    state = json.loads(output)
    assert state['candidate_id'] == etf.ID and state['next_attempt'] == 2
    assert state['evaluation_authorized'] is False and state['mode'] == 'inspection_only'
    assert state['input_manifest_sha256'] == etf.MANIFEST_SHA256
    assert state['code_sha256'] == etf.code_digest(intake.root)
    assert 'PRIVATE' not in output and 'holdout' not in output
    assert before == {p: p.read_bytes() for p in intake.root.rglob('*') if p.is_file()}
    assert not search.OUT.exists() and not intake.persisted


def test_one_counted_child_produces_only_exploration(intake, bundle, monkeypatch):
    intake.records([{'id': 'a', 'attempt_state': 'reserved'}, {'id': 'a', 'attempt_state': 'failed'},
                    {'id': 'b', 'attempt_state': 'interrupted'}])
    starts = counted_child(intake, monkeypatch)
    run_etf(intake, bundle)
    assert len(starts) == 1 and starts[0]['prior_candidates'] == 2
    records = search.read_ledger(intake.ledger)
    result = records[-1]
    assert len(search.latest(records)) == 3
    assert [r['attempt_state'] for r in records[-2:]] == ['reserved', 'completed']
    assert result['verdict'] == 'exploratory_only' and result['reached_confirmation'] is False
    assert not {'gates', 'periods', 'bar_t'} & result.keys()
    assert result['exploration']['continuation_criterion_met'] is False
    payload = json.loads(etf.artifact_path(intake.root).read_text())
    assert len(payload['calculations']) == 2
    for calculation in payload['calculations']:
        assert len(calculation['active']['monthly_returns']) == 2
        assert list(map(Decimal, calculation['active']['monthly_returns'])) == list(
            map(Decimal, calculation['passive']['monthly_returns']))
        assert len(calculation['decisions']) == 2
    assert len(intake.persisted) == 1 and not (search.DEFAULT_OUT / 'week.lock').exists()
    with pytest.raises(RuntimeError, match='already counted'):
        run_etf(intake, bundle)
    assert len(starts) == 1
    # The ID still counts globally but cannot become a catalog proposal or gate pass.
    assert etf.ID not in json.dumps(search.safe_digest(records))


@pytest.mark.parametrize('state', ['reserved', 'completed', 'failed', 'interrupted'])
@pytest.mark.parametrize('identity', ['same_id', 'same_family', 'same_kind'])
def test_counted_equivalents_and_renamed_bundle_refuse(intake, bundle, state, identity):
    row = {'id': etf.ID if identity == 'same_id' else 'renamed', 'attempt_state': state}
    if identity == 'same_family':
        row['spec'] = {**etf.SPEC, 'name': 'different label'}
    if identity == 'same_kind':
        row['evaluation_kind'] = etf.KIND
    intake.records([row])
    moved = bundle.with_name('renamed-bundle')
    shutil.copytree(bundle, moved)
    assert search.inspect_etf_bundle(moved)['already_counted'] is True
    before = intake.ledger.read_bytes()
    with pytest.raises(RuntimeError, match='already counted'):
        run_etf(intake, moved)
    assert intake.ledger.read_bytes() == before and not intake.persisted
    assert not list(search.OUT.glob('*.job.json'))


@pytest.mark.parametrize('changes', [dict(authorize_spec=None), dict(authorize_spec='renamed'),
    dict(expected_ledger_sha256=None), dict(expected_ledger_sha256='bad'),
    dict(expected_code_sha256=None), dict(expected_code_sha256='0'*64)])
def test_explicit_frozen_acknowledgements_required(intake, bundle, changes):
    with pytest.raises(ValueError, match='explicit candidate'):
        run_etf(intake, bundle, **changes)
    assert not search.OUT.exists() and not intake.persisted


@pytest.mark.parametrize('name', ['manifest.json', 'sessions.jsonl', 'normalized-actions.json'])
def test_changed_input_refuses_before_reservation(intake, bundle, name):
    (bundle / name).write_text('changed')
    with pytest.raises(ValueError, match='frozen|hash mismatch'):
        run_etf(intake, bundle)
    assert intake.ledger.read_bytes() == b'' and not search.OUT.exists()


def test_missing_linked_and_relative_bundle_refuse(intake, bundle, tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        run_etf(intake, Path('relative'))
    linked = tmp_path / 'linked'
    linked.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ValueError, match='unlinked'):
        run_etf(intake, linked)
    (bundle / 'sessions.jsonl').unlink()
    with pytest.raises(ValueError, match='Missing'):
        run_etf(intake, bundle)
    assert not search.OUT.exists()


def test_stale_ledger_and_stale_code_refuse(intake, bundle):
    ledger_sha = search.ledger_snapshot()[1]
    code_sha = etf.code_digest(intake.root)
    intake.records([{'id': 'another'}])
    with pytest.raises(RuntimeError, match='changed since inspection'):
        run_etf(intake, bundle, expected_ledger_sha256=ledger_sha)
    (intake.root / etf.CODE_FILES[0]).write_text('changed code')
    with pytest.raises(ValueError, match='code and ledger'):
        run_etf(intake, bundle, expected_code_sha256=code_sha)
    assert not intake.persisted and not list(search.OUT.glob('*.job.json'))


@pytest.mark.parametrize('used', [86400, 86341, -1, True])
def test_existing_budget_limits_apply(intake, bundle, used):
    intake.budget(used)
    with pytest.raises((ValueError, RuntimeError), match='budget'):
        run_etf(intake, bundle)
    assert intake.ledger.read_bytes() == b'' and not intake.persisted


def test_existing_attempt_cap_applies(intake, bundle):
    intake.records([{'id': str(n), 'attempt_state': 'reserved', 'search_night': '2026-10-25'}
                    for n in range(search.NIGHT_CAP)])
    intake.budget(1)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        run_etf(intake, bundle)
    assert not intake.persisted


@pytest.mark.parametrize('lock_kind', ['writer', 'weekly'])
def test_existing_locks_exclude_etf(intake, bundle, lock_kind):
    search.OUT.mkdir(parents=True)
    with (search.OUT / 'writer.lock').open('a') as handle:
        if lock_kind == 'writer':
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            (search.DEFAULT_OUT / 'week.lock').mkdir()
        with pytest.raises(RuntimeError, match='busy'):
            run_etf(intake, bundle)
    assert not intake.persisted


@pytest.mark.parametrize('failure', ['start', 'evaluation', 'timeout', 'changed_input'])
def test_failures_retain_attempt_and_time_charge(intake, bundle, monkeypatch, failure):
    starts = counted_child(intake, monkeypatch, failure=failure)
    killed = []
    monkeypatch.setattr(search.os, 'killpg', lambda *args: killed.append(args))
    if failure == 'start':
        with pytest.raises(RuntimeError, match='launch failure'):
            run_etf(intake, bundle)
    else:
        run_etf(intake, bundle)
    assert len(starts) == 1 and len(search.latest(search.read_ledger(intake.ledger))) == 1
    assert json.loads((search.OUT / '2026-10-25-seconds.json').read_text()) > 0
    assert bool(killed) == (failure == 'timeout')
    assert not etf.artifact_path(intake.root).exists()
    if failure != 'changed_input':
        with pytest.raises(RuntimeError, match='already counted'):
            run_etf(intake, bundle)
    assert len(intake.persisted) == 1


@pytest.mark.parametrize('mutation', [lambda r: r.update(verdict='passed'),
    lambda r: r.update(reached_confirmation=True), lambda r: r.update(gates={'exam': {'passed': True}}),
    lambda r: r.update(id='renamed'), lambda r: r['exploration'].update(artifact_sha256='0'*64)])
def test_completion_cannot_be_a_factory_pass_or_another_identity(intake, bundle, monkeypatch, mutation):
    counted_child(intake, monkeypatch, mutate_result=mutation)
    run_etf(intake, bundle)
    assert search.read_ledger(intake.ledger)[-1]['verdict'] == 'evaluation_error'
    assert len(search.latest(search.read_ledger(intake.ledger))) == 1


@pytest.mark.parametrize('has_result', [True, False])
def test_existing_recovery_imports_or_interrupts_without_recalculation(intake, bundle, monkeypatch, has_result):
    counted_child(intake, monkeypatch, failure=None if has_result else 'evaluation')
    run_etf(intake, bundle)
    reservation = search.read_ledger(intake.ledger)[0]
    intake.records([reservation])  # invented supervisor crash before completion append
    monkeypatch.setattr(etf.portfolio, 'calculate', lambda *_: pytest.fail('recalculated'))
    starts = fake_worker(intake, monkeypatch)
    intake.run()  # ordinary ORB intake recovers ETF through the same path
    assert len(starts) == 1 and starts[0]['prior_candidates'] == 1
    assert search.latest(search.read_ledger(intake.ledger))[etf.ID]['attempt_state'] == (
        'completed' if has_result else 'interrupted')


def test_standalone_child_is_refused_before_prices(intake, bundle, monkeypatch):
    monkeypatch.setattr(etf, 'calculate_artifact', lambda *_: pytest.fail('uncounted calculation'))
    with pytest.raises(ValueError, match='counted reservation'):
        search.etf_worker(search.OUT / f'{etf.ID}.job.json', {'evaluation_kind': etf.KIND}, None)


@pytest.mark.parametrize('bad', ['not json', '[]', '{"exploration": null}'])
def test_corrupt_completion_fails_closed_during_recovery(intake, bundle, monkeypatch, bad):
    counted_child(intake, monkeypatch)
    run_etf(intake, bundle)
    reservation = search.read_ledger(intake.ledger)[0]
    result = search.OUT / f'{etf.ID}.job.result.json'
    result.write_text(bad)
    intake.records([reservation])
    fake_worker(intake, monkeypatch)
    intake.run()
    retained = search.latest(search.read_ledger(intake.ledger))[etf.ID]
    assert retained['attempt_state'] == 'failed' and retained['verdict'] == 'evaluation_error'


def test_changed_code_during_preflight_refuses_without_charge(intake, bundle, monkeypatch):
    original = etf.verified_bundle
    calls = []

    def changing(path):
        value = original(path)
        calls.append(path)
        if len(calls) == 2:
            (intake.root / etf.CODE_FILES[0]).write_text('changed while acquiring locks')
        return value
    monkeypatch.setattr(etf, 'verified_bundle', changing)
    with pytest.raises(RuntimeError, match='code changed'):
        run_etf(intake, bundle)
    assert intake.ledger.read_bytes() == b'' and not intake.persisted
    assert not list(search.OUT.glob('*-seconds.json'))


def test_ledger_missing_and_orphan_job_refuse(intake, bundle):
    intake.ledger.unlink()
    with pytest.raises(FileNotFoundError):
        search.inspect_etf_bundle(bundle)
    intake.records([])
    search.OUT.mkdir(parents=True)
    (search.OUT / f'{etf.ID}.job.started').write_text('orphan')
    with pytest.raises(RuntimeError, match='requires audit'):
        run_etf(intake, bundle)
    assert intake.ledger.read_bytes() == b'' and not intake.persisted


@pytest.mark.parametrize('change', ['protected_date', 'missing_date', 'missing_action', 'nan'])
def test_loader_refuses_bad_calendar_or_action_semantics(bundle, change):
    data = [json.loads(line) for line in (bundle / 'sessions.jsonl').read_bytes().splitlines()]
    if change == 'protected_date':
        data[-1]['day'] = '2026-04-01'  # invented; never real protected data
    elif change == 'missing_date':
        data.pop(2)
    elif change == 'missing_action':
        del data[0]['distribution']
    else:
        data[0]['close'][0] = 'NaN'
    with pytest.raises(ValueError):
        etf.load_sessions(b''.join(etf.encoded(row) for row in data))


def test_cli_rejects_mixed_incomplete_or_unguarded_commands(intake, bundle):
    for args in (['--tick', '--etf-bundle', str(bundle)],
                 ['--inspect-etf-bundle', str(bundle), '--force'],
                 ['--tick', '--spec', 'orb', '--etf-bundle', str(bundle)],
                 ['--tick', '--writer-fd', '1'], ['--tick', '--expect-code-sha256', '0'*64]):
        with pytest.raises(SystemExit):
            search.main(args)
    assert not search.OUT.exists()


@pytest.mark.parametrize('base,stress,wanted', [('2', '0', False), ('2', '0.01', True),
    ('1.99', '5', False), ('3', '-0.01', False)])
def test_fixed_continuation_boundary_never_claims_validation(bundle, monkeypatch, base, stress, wanted):
    raw = (bundle / 'sessions.jsonl').read_bytes()
    rows, days = etf.load_sessions(raw)
    fixture = etf.portfolio.calculate(rows, days)
    results = tuple(replace(r, annualized_increment_pp=Decimal(value))
                    for r, value in zip(fixture, (base, stress)))
    monkeypatch.setattr(etf.portfolio, 'calculate', lambda *_: results)
    artifact, summary = etf.calculate_artifact(raw, 'a'*64)
    assert summary['continuation_criterion_met'] is wanted
    assert summary['validated'] is False
    assert json.loads(artifact)['validation_status'] == 'exploratory_only'


@pytest.mark.parametrize('state', ['reserved', 'completed', 'failed', 'interrupted'])
@pytest.mark.parametrize('tagged', [True, False])
def test_both_model_briefs_exclude_etf_while_global_count_retains_it(state, tagged):
    from app.engine.factory_brief import brief, ledger_digest
    from app.engine.factory_gates import prior_candidates, required_t

    orb = search.rules.parse_spec({'family': 'opening_range_breakout'})
    ordinary = {'id': search.rules.spec_id(orb), 'name': 'Invented ORB',
                'spec': search.rules.canonical(orb), 'verdict': 'failed_screen'}
    exploration = {'id': etf.ID, 'name': 'ETF_PRIVATE_EXPLORATION',
                   'spec': etf.SPEC, 'attempt_state': state, 'verdict': 'exploratory_only',
                   'exploration': {'secret': 'ETF_PRIVATE_EXPLORATION'}}
    if tagged:
        exploration['evaluation_kind'] = etf.KIND
    records = [ordinary, exploration, dict(exploration)]
    assert ledger_digest(records) == ledger_digest([ordinary])
    assert search.safe_digest(records) == search.safe_digest([ordinary])
    count = prior_candidates(records)
    assert count == 2 and count == len(search.latest(records))
    prompt = brief(date(2026, 10, 26), records, {}, [], 1, required_t(count + 1), count)
    assert 'Invented ORB' in prompt and 'ETF_PRIVATE_EXPLORATION' not in prompt


def test_real_child_inherits_lock_and_completes_invented_case(intake, bundle, monkeypatch, tmp_path):
    # Actual transport/PPID/flock/alarm; data, root, ledger and code pins remain
    # invented. Child bootstrap patches dotenv before importing the CLI.
    child = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
with patch('dotenv.dotenv_values', return_value={}):
    import factory_search as search
root, bundle, job = map(Path, sys.argv[1:4])
search.ROOT = root
search.DEFAULT_OUT = root / 'backend/data/factory'
search.OUT = search.DEFAULT_OUT / 'search'
search.LEDGER = root / 'research/ledger.jsonl'
search.require_checkout = lambda: None  # fixture checkout only
manifest_raw = (bundle / 'manifest.json').read_bytes()
manifest = json.loads(manifest_raw)
search.etf.MANIFEST_SHA256 = search.etf.digest(manifest_raw)
search.etf.CALENDAR_SHA256 = manifest['calendar_sha256']
search.etf.SESSION_COUNT = manifest['sessions']
search.etf.FIRST_LAST = tuple(manifest['actual_first_last'])
search.etf.MONTHLY_COUNT = 2
search.worker(job, int(sys.argv[4]))
'''
    intake.budget(search.SECONDS_CAP - 60)
    starts = []
    scripts = Path(search.__file__).resolve().parent
    log = tmp_path / 'invented-child.log'

    def launch(command, **kwargs):
        fd = command[command.index('--writer-fd') + 1]
        with log.open('w') as output:
            process = NATIVE_POPEN([sys.executable, '-c', child, str(intake.root),
                                  str(bundle), command[-1], fd],
                cwd=tmp_path, env={'PATH': '/usr/bin:/bin',
                                  'PYTHONPATH': str(scripts) + ':' + str(scripts.parent),
                                  'PYTHONDONTWRITEBYTECODE': '1'},
                stdout=output, stderr=subprocess.STDOUT, **kwargs)
        starts.append(process)
        return process
    monkeypatch.setattr(search.subprocess, 'Popen', launch)
    run_etf(intake, bundle)
    assert len(starts) == 1 and starts[0].returncode == 0, log.read_text()
    record = search.read_ledger(intake.ledger)[-1]
    assert record['attempt_state'] == 'completed' and record['verdict'] == 'exploratory_only'
    assert record['timeout_seconds'] == 60
    assert not (search.DEFAULT_OUT / 'week.lock').exists()
