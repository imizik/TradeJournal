"""Focused search gates and restart primitives, no provider/network calls."""
import json
import random
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import factory_search as search
from app.engine.factory_gates import prior_candidates, required_t


def test_every_trial_counts_once_including_reservations_and_failed_screen():
    records = [{'id': 'a', 'reached_confirmation': False, 'attempt_state': 'reserved'},
               {'id': 'a', 'reached_confirmation': False, 'attempt_state': 'completed'},
               {'id': 'b', 'reached_confirmation': False, 'attempt_state': 'interrupted'}]
    assert prior_candidates(records) == 2
    assert len(search.latest(records)) == 2
    assert required_t(prior_candidates(records) + 1) > required_t(1)


def test_model_never_receives_exam_fields_or_hidden_text():
    records = [{'id': 'x', 'spec': {'family': 'vwap_reclaim'}, 'verdict': 'failed_exam',
                'notes': 'secret exam 123', 'summary': 'secret',
                'periods': {'discovery': {'n': 100}, 'confirm': {'n': 50}, 'holdout': {'secret': 99}}}]
    text = json.dumps(search.safe_digest(records))
    assert 'holdout' not in text and 'secret' not in text and 'failed_exam' not in text
    assert 'discovery' in text and 'confirm' in text


def test_random_catalog_and_boundaries():
    rng = random.Random(5)
    specs = [search.validate(search.sample(rng)) for _ in range(300)]
    assert {s.family for s in specs} == set(search.rules.FAMILIES)
    assert {'orb', 'fade'} <= {dict(s.params).get('setup') for s in specs}
    assert set(search.LEVEL_FEATURES) <= {f.feature for s in specs for f in s.filters}
    with pytest.raises(ValueError):
        search.validate({'family': 'vwap_reclaim', 'costs': {'slippage_bps': 0}})
    with pytest.raises(ValueError):
        search.validate({'family': 'vwap_reclaim', 'model': {'kind': 'logistic'}})


def test_durable_reservation_and_restart_dedup(tmp_path, monkeypatch):
    ledger = tmp_path / 'ledger.jsonl'
    monkeypatch.setattr(search, 'LEDGER', ledger)
    record = {'id': 'abc', 'attempt_state': 'reserved'}
    search.append(record)
    recovered = search.read_ledger(ledger)
    assert 'abc' in search.latest(recovered)  # proposal selection will skip it
    search.append({**record, 'attempt_state': 'completed'})
    assert len(search.latest(search.read_ledger(ledger))) == 1


def test_recovered_pass_emits_proposal_without_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(search, 'ROOT', tmp_path)
    record = {'id': 'pass', 'verdict': 'passed', 'attempt_state': 'completed', 'search_night': '2026-10-15', 'periods': {'confirm': {'mean_r': 0.3}}}
    search.reconcile_proposals([record])
    path = tmp_path / 'research/reports/s1-v3-proposal-pass.json'
    assert json.loads(path.read_text())['evidence'] == record
    path.unlink()  # simulate a supervisor loss after ledger completion
    search.reconcile_proposals([record])
    assert json.loads(path.read_text())['evidence'] == record
    assert len(list(path.parent.glob('s1-v3-proposal-*.json'))) == 1


def test_worker_deadline_survives_supervisor_exit(tmp_path):
    import subprocess
    import time
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({'timeout_seconds': 1, 'spec': search.rules.canonical(search.rules.parse_spec({'family':'vwap_reclaim'})), 'prior_candidates': 0}))
    code = '''import os,sys,time,subprocess
sys.path.insert(0,sys.argv[1])
worker_code = "import sys,time;sys.path.insert(0,sys.argv[1]);import factory_search as s;s.evaluate=lambda *a,**kw:time.sleep(30);s.worker(sys.argv[2])"
p=subprocess.Popen([sys.executable,'-c',worker_code,sys.argv[1],sys.argv[2]])
print(p.pid,flush=True)
os._exit(0)
'''
    started = time.monotonic()
    # Child retains stdout. communicate returns only after the orphan closes it.
    parent = subprocess.Popen([sys.executable, '-c', code, str(Path(search.__file__).parent), str(job)], stdout=subprocess.PIPE)
    parent.communicate(timeout=5)
    assert time.monotonic() - started < 5
    assert not job.with_suffix('.result.json').exists()


def test_scanner_adapter_prefix_causality_with_injected_minutes(monkeypatch):
    from app.engine import factory_search_family as adapter
    from app.engine.factory_data import Series
    from app.engine.market_map import resample
    from tests.test_factory import weekdays, bar
    from datetime import date
    days = weekdays(date(2025, 6, 2), 17)
    minutes = [bar(d, m, 100, 100.5, 99.5, 100) for d in days[:-1] for m in range(570, 590)]
    today = [bar(days[-1], m, 100, 100.5, 99.5, 100) for m in range(570, 585)]
    today += [bar(days[-1], m, 100.2, 100.9, 100.1, 100.8, 1500) for m in range(585, 590)]
    today += [bar(days[-1], m, 100.8, 180, 10, 100.8) for m in range(590, 600)]
    from app.engine.factory_rules import Context
    observed = []
    for count in (20, len(today)):
        minute = Series.build('TEST', minutes + today[:count], 1)
        monkeypatch.setattr(adapter, 'MINUTE_LOADER', lambda *args: minute)
        series = Series.build('TEST', resample(minute.bars(), 5), 5)
        family = adapter.ScannerFamily().start(series)
        signals = [family.on_bar(i, Context(flat=True, halted=False, accept=lambda _: True)) for i in range(len(series))]
        observed.append([s for s in signals if s and s.index <= len(minutes)//5 + 3])
    assert observed[0] and observed[0] == observed[1]


@pytest.mark.parametrize('bound,value', [('low', 0.0), ('high', -0.5)])
def test_claude_canonical_filters_preserve_spec_id_and_gate_boundaries(bound, value):
    public = {'low': 'min', 'high': 'max'}[bound]
    proposal = {'family': 's1_research', 'params': {'setup': 'fade'},
                'filters': [{'feature': 'prior_day_high', bound: value,
                             'high' if bound == 'low' else 'low': None}],
                'note': 'Claude idea'}
    normalized = search.validate(proposal)
    expected = search.validate({'family': 's1_research', 'params': {'setup': 'fade'},
                               'filters': [{'feature': 'prior_day_high', public: value}]})
    assert search.rules.spec_id(normalized) == search.rules.spec_id(expected)
    assert proposal['filters'][0][bound] == value  # raw answer is retained
    with pytest.raises(ValueError, match='conflicting filter bounds'):
        search.validate({'family': 's1_research', 'filters': [
            {'feature': 'prior_day_high', 'low': 0, 'min': 1}]})
    with pytest.raises(ValueError, match='universe/costs'):
        search.validate({**proposal, 'costs': {'slippage_bps': 0}})


def test_claude_format_translation_does_not_broaden_intraday_scope():
    with pytest.raises(ValueError, match='intraday only'):
        search.validate({'family': 'recovery_swing',
                         'filters': [{'feature': 'trend', 'low': 0, 'high': None}]})



def test_next_claude_brief_contains_failures_and_excludes_exam_evidence():
    records = [{'id': 'claude-failed', 'search_origin': 'claude-plan',
                'spec': {'family': 's1_research'}, 'verdict': 'failed_exam',
                'notes': 'PRIVATE_EXAM_NUMBER',
                'periods': {'discovery': {'n': 214, 'mean_r': -0.088874, 'edge_t': -0.795647},
                            'holdout': {'PRIVATE_EXAM_NUMBER': 999}},
                'gates': {'screen': {'passed': False, 'checks': [
                    ['214 trades (at least 100)', True],
                    ['average -0.089R after costs (above 0)', False]]},
                          'exam': {'passed': False, 'checks': [['PRIVATE_EXAM_NUMBER', False]]}}}]
    brief = search.idea_prompt(records)
    assert 'claude-plan' in brief and 'claude-failed' in brief
    assert 'average -0.089R after costs' in brief
    assert '-0.088874' in brief and '-0.795647' in brief
    assert 'PRIVATE_EXAM_NUMBER' not in brief and 'failed_exam' not in brief
    assert 'Learn from the recorded failed screen checks' in brief


def test_codex_is_plan_only_without_tools_memory_or_project_context():
    args = search.codex_command('codex', '/schema', '/answer', 'configured-model')
    assert '--ignore-user-config' in args and '--ephemeral' in args
    assert args[args.index('--sandbox')+1] == 'read-only'
    assert 'forced_login_method="chatgpt"' in args and 'model_provider="openai"' in args
    assert 'memories.use_memories=false' in args and 'memories.generate_memories=false' in args
    assert 'project_doc_max_bytes=0' in args and 'web_search="disabled"' in args
    assert 'mcp_servers={}' in args and 'agents.enabled=false' in args
    assert 'multi_agent_v2' in args
    assert {'shell_tool', 'plugins', 'hooks', 'multi_agent', 'memories', 'view_image', 'code_mode_host', 'apps'} <= {args[i+1] for i,v in enumerate(args) if v=='--disable'}
    assert args[args.index('--model')+1] == 'configured-model'


@pytest.fixture
def codex_batch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(search, 'OUT', tmp_path)
    monkeypatch.setattr(search.Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'NEVER_SEND_API_KEY')
    monkeypatch.setenv('CODEX_API_KEY', 'NEVER_SEND_CODEX_KEY')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'NEVER_SEND_CLAUDE_KEY')
    state = SimpleNamespace(envelope=False, reservations=[], processes=[], status='Logged in using ChatGPT', tools=False,
                            raw=[{'family':'vwap_reclaim','filters':[{'feature':'trend','min':0}],
                                  'exits':{'max_sessions':1}}])
    def status(args, **kwargs):
        assert state.reservations == [search.IDEA_SECONDS]
        assert args[-2:]==['login','status']
        assert not any('API_KEY' in k for k in kwargs['env'])
        return SimpleNamespace(stdout=state.status, stderr='', returncode=0)
    monkeypatch.setattr(search.subprocess, 'run', status)
    class Process:
        def __init__(self, args, **kwargs):
            self.args=args
            self.kwargs=kwargs
            self.returncode=0
            state.processes.append(self)
            assert not list(Path(kwargs['cwd']).iterdir())
            assert not any('API_KEY' in k for k in kwargs['env'])
        def communicate(self, prompt, timeout):
            assert timeout==300 and 'PRIVATE_EXAM' not in prompt
            Path(self.args[self.args.index('--output-last-message')+1]).write_text(json.dumps({'specs_json':json.dumps({'specs':state.raw} if state.envelope else state.raw)}))
            events=[{'type':'item.completed','item':{'type':'error','message':'Non-fatal CLI warning'}},
                    {'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':50}}]
            if state.tools:
                events.append({'type':'item.completed','item':{'type':'command_execution'}})
            return '\n'.join(json.dumps(e) for e in events), ''
    monkeypatch.setattr(search.subprocess, 'Popen', Process)
    return state


def test_codex_batch_reserves_before_launch_queues_then_reuses(codex_batch, tmp_path):
    state=codex_batch
    rows=[{'id':'old','spec':{'family':'vwap_reclaim', 'notes':'PRIVATE_EXAM'},'notes':'PRIVATE_EXAM',
           'periods':{'holdout':{'PRIVATE_EXAM':123}}}]
    ideas=search.codex_ideas(rows,'2026-10-15',state.reservations.append)
    assert len(ideas)==1 and len(state.processes)==1
    assert search.codex_ideas(rows,'2026-10-15',lambda _:pytest.fail('queue must not reserve'))==ideas
    assert len(state.processes)==1
    receipt=json.loads(next(tmp_path.glob('*.receipt.json')).read_text())
    assert receipt['state']=='completed' and receipt['accepted']==1
    assert receipt['feedback_mode']=='discovery-confirm'
    assert json.loads(next(tmp_path.glob('*.brief.txt')).read_text().split('\n')[-1])['ledger'][0]['id']=='old'
    assert receipt['usage']==[{'input_tokens':100,'output_tokens':50}]
    assert next(tmp_path.glob('*.started.json')).exists()
    assert 'PRIVATE_EXAM' not in next(tmp_path.glob('*.brief.txt')).read_text()


def test_codex_api_auth_refused_after_durable_reservation(codex_batch, tmp_path):
    codex_batch.status='Logged in using an API key'
    with pytest.raises(RuntimeError,match='no API fallback'):
        search.codex_ideas([], '2026-10-15',codex_batch.reservations.append)
    assert not codex_batch.processes
    assert json.loads(next(tmp_path.glob('*.receipt.json')).read_text())['state']=='failed'


def test_codex_tool_event_refused_without_queue(codex_batch, tmp_path):
    codex_batch.tools=True
    with pytest.raises(RuntimeError,match='tool use'):
        search.codex_ideas([], '2026-10-15',codex_batch.reservations.append)
    assert not (tmp_path/'2026-10-15-codex-ideas.json').exists()


def test_codex_spent_batch_never_reopened_and_candidate_id_not_repeated(codex_batch, tmp_path, monkeypatch):
    monkeypatch.setattr(search,'CODEX_BATCH_CAP',1)
    ideas=search.codex_ideas([], '2026-10-15',codex_batch.reservations.append)
    ident=search.rules.spec_id(search.validate(ideas[0]))
    assert search.codex_ideas([{'id':ident}], '2026-10-15',lambda _:pytest.fail('spent batch cannot retry'))==[]
    assert len(codex_batch.processes)==1


def test_codex_budget_refusal_launches_nothing(codex_batch, tmp_path):
    def refuse(_):
        raise RuntimeError('budget exhausted')
    with pytest.raises(RuntimeError,match='budget exhausted'):
        search.codex_ideas([], '2026-10-15',refuse)
    assert not codex_batch.processes and not list(tmp_path.glob('*.started.json'))


def test_idea_brief_explicit_intraday_includes_recovery():
    text=search.idea_prompt([])
    assert 'exits.max_sessions=1' in text and 'including recovery_swing' in text


def test_codex_timeout_including_auth_and_kill_fits_reservation(codex_batch, tmp_path, monkeypatch):
    from types import SimpleNamespace
    elapsed = [0.0]
    calls = []
    monkeypatch.setattr(search.time, 'monotonic', lambda: elapsed[0])
    def status(*args, **kwargs):
        elapsed[0] += kwargs['timeout']
        return SimpleNamespace(stdout='Logged in using ChatGPT', stderr='')
    monkeypatch.setattr(search.subprocess, 'run', status)
    class Resistant:
        pid = 123456
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self, *args, timeout):
            calls.append(timeout)
            elapsed[0] += timeout
            raise search.subprocess.TimeoutExpired('fake', timeout)
    monkeypatch.setattr(search.subprocess, 'Popen', Resistant)
    signals = []
    monkeypatch.setattr(search.os, 'killpg', lambda pid, sig: signals.append(sig))
    with pytest.raises(search.subprocess.TimeoutExpired):
        search.codex_ideas([], '2026-10-15', codex_batch.reservations.append)
    assert calls == [285, 5, 10]
    assert signals == [search.signal.SIGTERM, search.signal.SIGKILL]
    assert elapsed[0] <= search.IDEA_SECONDS
    receipt = json.loads(next(tmp_path.glob('*.receipt.json')).read_text())
    assert receipt['state'] == 'failed' and receipt['elapsed_seconds'] == 330
    monkeypatch.setattr(search, 'CODEX_BATCH_CAP', 1)
    assert search.codex_ideas([], '2026-10-15', lambda _: pytest.fail('spent batch')) == []


def test_codex_guardian_kills_descendants_and_releases_lock_after_supervisor_loss(tmp_path):
    import subprocess
    import time
    lock = tmp_path / 'writer.lock'
    # Fake CLI ignores TERM, spawns a descendant, and would otherwise retain stdout.
    fake = "import signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);time.sleep(30)"
    supervisor = """import fcntl,os,subprocess,sys
handle=open(sys.argv[1],'a')
fcntl.flock(handle,fcntl.LOCK_EX)
subprocess.Popen([sys.executable,'-c',sys.argv[2],'1',sys.executable,'-c',sys.argv[3]],start_new_session=True,pass_fds=(handle.fileno(),))
os._exit(0)
"""
    started = time.monotonic()
    parent = subprocess.Popen([sys.executable, '-c', supervisor, str(lock), search.MODEL_GUARD, fake], stdout=subprocess.PIPE)
    parent.communicate(timeout=5)
    assert time.monotonic() - started < 5  # all descendants closed inherited stdout
    with lock.open('a') as handle:
        search.fcntl.flock(handle, search.fcntl.LOCK_EX | search.fcntl.LOCK_NB)


def test_codex_envelope_is_unwrapped_without_changing_specs(codex_batch):
    codex_batch.envelope = True
    ideas = search.codex_ideas([], '2026-10-15', codex_batch.reservations.append)
    assert ideas == codex_batch.raw
    assert search.validate(ideas[0]) == search.validate(codex_batch.raw[0])
