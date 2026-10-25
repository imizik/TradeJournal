"""Frozen intake through the official supervisor, with invented ledger/jobs only."""
import fcntl
import json
import os
from unittest.mock import patch
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
# CLI bootstrap must not leak provider settings into other test modules.
with patch("dotenv.dotenv_values", return_value={}), patch.dict(os.environ):
    import factory_search as search

SPEC = Path(__file__).resolve().parents[2] / 'research/specs/opening_range_breakout_rvol2_v1.json'


@pytest.fixture
def intake(tmp_path, monkeypatch):
    root = tmp_path / 'factory'
    (root / 'research/specs').mkdir(parents=True)
    ledger = root / 'research/ledger.jsonl'
    ledger.write_text('')
    out = root / 'backend/data/factory'
    monkeypatch.setattr(search, 'ROOT', root)
    monkeypatch.setattr(search, 'DEFAULT_OUT', out)
    monkeypatch.setattr(search, 'OUT', out / 'search')
    monkeypatch.setattr(search, 'LEDGER', ledger)
    monkeypatch.setattr(search, 'require_checkout', lambda: None)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 25, 23, tzinfo=search.ET).astimezone(tz or search.ET)
    monkeypatch.setattr(search, 'datetime', Clock)

    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected model, provider, evaluator, git or message operation')
    for name in ('codex_ideas', 'claude_ideas', 'sample', 'evaluate', 'notify'):
        monkeypatch.setattr(search, name, forbidden)
    monkeypatch.setattr(search.subprocess, 'Popen', forbidden)
    persisted, proposed = [], []
    monkeypatch.setattr(search, 'persist_research', lambda: persisted.append(True))
    monkeypatch.setattr(search, 'reconcile_proposals', lambda _: None)
    monkeypatch.setattr(search, 'proposal', proposed.append)
    monkeypatch.setattr(search, 'code_version', lambda: 'fixture-code')

    def records(rows):
        ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def budget(value):
        search.OUT.mkdir(parents=True, exist_ok=True)
        (search.OUT / '2026-10-25-seconds.json').write_text(json.dumps(value))

    def run(**overrides):
        args = dict(spec_path=SPEC, authorize_spec=search.FROZEN_ORB_ID,
                    expected_ledger_sha256=search.ledger_snapshot()[1])
        args.update(overrides)
        return search.tick(**args)
    return SimpleNamespace(root=root, ledger=ledger, records=records, budget=budget, run=run,
                           persisted=persisted, proposed=proposed)


def test_inspection_is_read_only_and_never_exposes_outcomes(intake, capsys):
    intake.records([{'id': 'a', 'attempt_state': 'reserved'},
                    {'id': 'a', 'attempt_state': 'completed', 'periods': {'holdout': {'secret': 123}}},
                    {'id': 'b', 'attempt_state': 'interrupted'}])
    before = {p: p.read_bytes() for p in intake.root.rglob('*') if p.is_file()}
    search.main(['--inspect-spec', str(SPEC)])
    output = capsys.readouterr().out
    state = json.loads(output)
    assert state['candidate_id'] == search.FROZEN_ORB_ID
    assert state['prior_candidates'] == 2 and state['next_attempt'] == 3
    assert state['evaluation_authorized'] is False and state['mode'] == 'inspection_only'
    assert 'holdout' not in output and 'secret' not in output
    assert before == {p: p.read_bytes() for p in intake.root.rglob('*') if p.is_file()}
    assert not search.OUT.exists() and not intake.persisted


@pytest.mark.parametrize('attempt_state', ['reserved', 'completed', 'interrupted', 'failed'])
def test_every_counted_identity_is_refused_without_retries(intake, attempt_state, tmp_path):
    intake.records([{'id': search.FROZEN_ORB_ID, 'attempt_state': attempt_state, 'verdict': 'failed_screen'}])
    raw = json.loads(SPEC.read_text())
    renamed = tmp_path / 'renamed.json'
    renamed.write_text(json.dumps({**raw, 'name': 'a new name', 'notes': 'no new identity'}))
    before = intake.ledger.read_bytes()
    with pytest.raises(RuntimeError, match='already counted'):
        intake.run(spec_path=renamed)
    assert intake.ledger.read_bytes() == before and not intake.persisted
    assert not list(search.OUT.glob('*.job.json'))
    assert not list(search.OUT.glob('*-seconds.json'))


def test_changed_ledger_receipt_is_refused_before_recovery_or_budget(intake):
    digest = search.ledger_snapshot()[1]
    intake.records([{'id': 'another', 'attempt_state': 'reserved'}])
    with pytest.raises(RuntimeError, match='changed since inspection'):
        intake.run(expected_ledger_sha256=digest)
    assert not intake.persisted and not list(search.OUT.glob('*.job.json'))


@pytest.mark.parametrize('change', [{'filters': [{'feature': 'rvol', 'min': 1.5}]},
                                   {'params': {'range_minutes': 15}}, {'tickers': ['MU']},
                                   {'costs': {'slippage_bps': 0}}])
def test_spec_variants_cannot_fall_back_to_another_candidate(intake, tmp_path, change):
    path = tmp_path / 'variant.json'
    path.write_text(json.dumps({**json.loads(SPEC.read_text()), **change}))
    with pytest.raises(ValueError):
        intake.run(spec_path=path)
    assert not search.OUT.exists()


@pytest.mark.parametrize('overrides', [{'authorize_spec': None}, {'authorize_spec': 'different'},
                                      {'expected_ledger_sha256': None}, {'expected_ledger_sha256': 'bad'}])
def test_explicit_acknowledgement_is_required_before_any_write(intake, overrides):
    with pytest.raises(ValueError, match='explicit candidate'):
        intake.run(**overrides)
    assert not search.OUT.exists() and not intake.persisted


@pytest.mark.parametrize('used', [86400, 86341, -1, 86401, True, 1.5])
def test_time_budget_refuses_without_reserving_or_launching(intake, used):
    intake.budget(used)
    before = (search.OUT / '2026-10-25-seconds.json').read_bytes()
    with pytest.raises((ValueError, RuntimeError), match='budget'):
        intake.run()
    assert (search.OUT / '2026-10-25-seconds.json').read_bytes() == before
    assert intake.ledger.read_bytes() == b'' and not intake.persisted


def test_attempt_cap_counts_reservations_even_when_completed(intake):
    rows = []
    for n in range(search.NIGHT_CAP):
        rows.extend([{'id': str(n), 'search_night': '2026-10-25', 'attempt_state': 'reserved'},
                     {'id': str(n), 'search_night': '2026-10-25', 'attempt_state': 'completed'}])
    intake.records(rows)
    intake.budget(288)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        intake.run()
    assert len(search.read_ledger(intake.ledger)) == 2 * search.NIGHT_CAP
    assert not intake.persisted


@pytest.mark.parametrize('lock_kind', ['writer', 'weekly', 'search'])
def test_existing_writer_and_weekly_locks_exclude_manual_intake(intake, lock_kind):
    search.OUT.mkdir(parents=True)
    if lock_kind == 'writer':
        with (search.OUT / 'writer.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(RuntimeError, match='busy'):
                intake.run()
    else:
        lock = search.DEFAULT_OUT / 'week.lock'
        lock.mkdir()
        if lock_kind == 'search':
            (lock / 'search-pid').write_text(str(search.os.getpid()))
        with pytest.raises(RuntimeError, match='busy'):
            intake.run()
        assert lock.exists()
    assert intake.ledger.read_bytes() == b'' and not intake.persisted


def fake_worker(intake, monkeypatch, fail_start=False, fail_result=False, origin='owner-frozen-spec'):
    starts = []

    class Process:
        def __init__(self, command, **kwargs):
            job = Path(command[-1])
            reservation = json.loads(job.read_text())
            records = search.read_ledger(intake.ledger)
            assert records[-1] == reservation
            assert reservation['id'] == search.FROZEN_ORB_ID
            assert reservation['search_origin'] == origin
            assert reservation['spec'] == search.rules.canonical(search.requested_candidate(SPEC))
            assert json.loads((search.OUT / '2026-10-25-seconds.json').read_text()) >= reservation['timeout_seconds']
            assert kwargs['start_new_session'] is True and len(kwargs['pass_fds']) == 1
            with (search.OUT / 'writer.lock').open('a') as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert (search.DEFAULT_OUT / 'week.lock/search-pid').exists()
            starts.append(reservation)
            if fail_start:
                raise RuntimeError('fixture process start failed')
            if not fail_result:
                job.with_suffix('.result.json').write_text(json.dumps({**reservation, 'attempt_state': 'completed', 'verdict': 'failed_screen'}))

        def wait(self, timeout):
            assert timeout <= 900
            return 1 if fail_result else 0
    monkeypatch.setattr(search.subprocess, 'Popen', Process)
    return starts


def test_one_requested_candidate_uses_official_reservation_and_worker_path(intake, monkeypatch):
    intake.records([{'id': str(n), 'attempt_state': 'completed', 'reached_confirmation': False} for n in range(82)])
    starts = fake_worker(intake, monkeypatch)
    intake.run()
    assert len(starts) == 1 and starts[0]['prior_candidates'] == 82
    records = search.read_ledger(intake.ledger)
    assert len({r['id'] for r in records}) == 83
    assert [r['attempt_state'] for r in records[-2:]] == ['reserved', 'completed']
    assert len(intake.persisted) == 1 and not (search.DEFAULT_OUT / 'week.lock').exists()
    with pytest.raises(RuntimeError, match='already counted'):
        intake.run()
    assert len(starts) == 1


@pytest.mark.parametrize('failure', ['start', 'result'])
def test_failed_launch_or_evaluation_still_consumes_identity(intake, monkeypatch, failure):
    starts = fake_worker(intake, monkeypatch, fail_start=failure == 'start', fail_result=failure == 'result')
    if failure == 'start':
        with pytest.raises(RuntimeError, match='start failed'):
            intake.run()
    else:
        intake.run()
    assert len(starts) == 1 and len(search.latest(search.read_ledger(intake.ledger))) == 1
    with pytest.raises(RuntimeError, match='already counted'):
        intake.run()
    assert len(starts) == 1 and len(intake.persisted) == 1


def test_recovery_imports_existing_result_without_reopening_it(intake, monkeypatch):
    intake.records([{'id': 'old', 'attempt_state': 'reserved', 'search_night': '2026-10-24'}])
    search.OUT.mkdir(parents=True)
    job = search.OUT / 'old.job.json'
    job.write_text(json.dumps({'id': 'old'}))
    job.with_suffix('.result.json').write_text(json.dumps({'id': 'old', 'attempt_state': 'completed', 'verdict': 'failed_screen'}))
    starts = fake_worker(intake, monkeypatch)
    intake.run()
    assert len(starts) == 1 and starts[0]['prior_candidates'] == 1
    assert search.latest(search.read_ledger(intake.ledger))['old']['attempt_state'] == 'completed'


def test_daytime_requires_existing_force_flag_without_changing_budgets(intake, monkeypatch):
    class Day(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 26, 12, tzinfo=search.ET)
    monkeypatch.setattr(search, 'datetime', Day)
    with pytest.raises(RuntimeError, match='Outside search hours'):
        intake.run()
    starts = fake_worker(intake, monkeypatch)
    intake.run(force=True)
    assert len(starts) == 1 and starts[0]['timeout_seconds'] == 900


def test_missing_ledger_never_becomes_zero_history(intake):
    intake.ledger.unlink()
    with pytest.raises(FileNotFoundError):
        search.inspect_spec(SPEC)
    with pytest.raises(FileNotFoundError):
        intake.run(expected_ledger_sha256='0'*64)
    assert not intake.persisted


def test_cli_rejects_partial_or_mixed_execution_commands(intake):
    for args in (['--tick', '--spec', str(SPEC)], ['--inspect-spec', str(SPEC), '--force'],
                 ['--worker', 'fake', '--spec', str(SPEC)], ['--tick', '--authorize-spec', search.FROZEN_ORB_ID]):
        with pytest.raises(SystemExit):
            search.main(args)
    assert not search.OUT.exists()


def test_checkout_guard_rejects_application_worktree_and_other_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(search, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError, match='Mac factory checkout'):
        search.require_checkout()
    monkeypatch.setattr(search, 'ROOT', Path('/Users/user/TradeJournal-factory'))
    monkeypatch.setattr(search.subprocess, 'check_output', lambda *a, **kw: 'main\n')
    with pytest.raises(RuntimeError, match='requires factory/ledger'):
        search.require_checkout()


def test_missing_budget_for_used_window_cannot_reset_time(intake):
    intake.records([{'id': 'existing', 'attempt_state': 'reserved', 'search_night': '2026-10-25'}])
    with pytest.raises(ValueError, match='Missing Factory time budget'):
        search.inspect_spec(SPEC)
    with pytest.raises(ValueError, match='Missing Factory time budget'):
        intake.run()
    assert not intake.persisted


def test_scheduled_tick_keeps_existing_proposal_selection(intake, monkeypatch):
    raw = json.loads(SPEC.read_text())
    calls = []
    monkeypatch.setattr(search, 'codex_ideas', lambda *args: calls.append('codex') or [raw])
    monkeypatch.setattr(search, 'sample', lambda rng: raw)
    starts = fake_worker(intake, monkeypatch, origin='codex-plan')
    search.tick()
    assert calls == ['codex'] and len(starts) == 1
    assert len(search.latest(search.read_ledger(intake.ledger))) == 1


def test_exact_minimum_remaining_time_uses_existing_bounded_timeout(intake, monkeypatch):
    intake.budget(search.SECONDS_CAP - 60)
    starts = fake_worker(intake, monkeypatch)
    intake.run()
    assert len(starts) == 1 and starts[0]['timeout_seconds'] == 60
    assert json.loads((search.OUT / '2026-10-25-seconds.json').read_text()) <= search.SECONDS_CAP
