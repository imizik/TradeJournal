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
