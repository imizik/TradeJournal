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
