"""Invented accounting only: no strategy, market data, Factory or provider calls."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import subprocess
import sys

import pytest

from scripts.etf_fixture_reconcile import FIXTURE, FIXTURE_SHA256, reconcile


@pytest.fixture
def receipt():
    return json.loads(FIXTURE.read_bytes())


def test_rebuild_balances_and_restart_without_mutating_input(receipt):
    original = deepcopy(receipt)
    rows = reconcile(receipt)
    assert rows == reconcile(receipt)
    assert receipt == original
    assert len(rows) == 8
    assert rows[1].cash == Decimal('7597.60')
    assert rows[2].cash == rows[1].cash
    assert rows[3].receivable == Decimal('48')
    assert rows[4].receivable == 0
    assert rows[5].shares == 48
    assert rows[3].nav == rows[4].nav == rows[5].nav == Decimal('9997.60')
    assert rows[6].cash == rows[7].cash == Decimal('9995.25')
    assert rows[6].settled_cash == Decimal('7645.60')
    assert rows[6].unsettled_sale_proceeds == Decimal('2349.65')
    assert rows[7].unsettled_sale_proceeds == 0
    assert rows[7].settled_cash == rows[7].cash


@pytest.mark.parametrize('index', range(8))
def test_duplicate_delivery_is_idempotent(receipt, index):
    expected = reconcile(receipt)
    receipt['events'].append(deepcopy(receipt['events'][index]))
    assert reconcile(receipt) == expected


def test_conflicting_duplicate_fails(receipt):
    duplicate = deepcopy(receipt['events'][1])
    duplicate['quantity'] = 25
    receipt['events'].append(duplicate)
    with pytest.raises(ValueError, match='conflicting duplicate'):
        reconcile(receipt)


@pytest.mark.parametrize(('index', 'field', 'value'), [
    (1, 'cash', '9999'), (1, 'fee', '2.41'), (1, 'quantity', 25),
    (1, 'quantity', True), (1, 'ask', 'NaN'), (1, 'ask', 'Infinity'),
    (1, 'ask', 100.0), (1, 'ask', '-1'), (1, 'ask', '0.000000001'),
    (2, 'fill', '100'), (3, 'receivable', '0'), (4, 'cash', '7693.60'),
    (5, 'new_per_old', '0.01'), (5, 'shares', 24), (6, 'quantity', 49),
    (6, 'fee', '2.36'), (6, 'settled_cash', '9995.25'),
    (7, 'cash', '12344.90'), (7, 'unsettled_sale_proceeds', '2349.65'),
    (3, 'mark', None), (3, 'mark', '0'), (6, 'intent_id', 'A-buy-1'),
])
def test_invalid_accounting_refused(receipt, index, field, value):
    receipt['events'][index][field] = value
    with pytest.raises(ValueError):
        reconcile(receipt)


@pytest.mark.parametrize('kind', ['late_correction', 'closure', 'halt', 'broker_fill'])
def test_unsupported_events_refused(receipt, kind):
    receipt['events'][3]['type'] = kind
    with pytest.raises(ValueError, match='unsupported'):
        reconcile(receipt)


def test_incomplete_and_reordered_receipts_refused(receipt):
    incomplete = deepcopy(receipt)
    incomplete['events'].pop()
    with pytest.raises(ValueError, match='incomplete'):
        reconcile(incomplete)
    receipt['events'][3], receipt['events'][4] = receipt['events'][4], receipt['events'][3]
    with pytest.raises(ValueError, match='out-of-order'):
        reconcile(receipt)


def test_new_id_cannot_double_post_economic_event(receipt):
    duplicate = deepcopy(receipt['events'][4])
    duplicate['id'] = 'another-payment'
    receipt['events'].insert(5, duplicate)
    with pytest.raises(ValueError, match='out-of-order'):
        reconcile(receipt)


def test_expected_balances_are_assertions_not_state_inputs(receipt):
    receipt['capital'] = '9999'
    with pytest.raises(ValueError, match='cash mismatch'):
        reconcile(receipt)


@pytest.mark.parametrize('field,value', [('kind', 'real'), ('market_data_used', True), ('version', True)])
def test_non_fixture_documents_refused(receipt, field, value):
    receipt[field] = value
    with pytest.raises(ValueError, match='invented'):
        reconcile(receipt)


def test_pinned_cli_has_no_arbitrary_input_or_live_mode():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    script = FIXTURE.parents[2] / 'backend/scripts/etf_fixture_reconcile.py'
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['final']['nav'] == '9995.25'
    for option in ('--input', '--live', '--evaluate'):
        result = subprocess.run([sys.executable, str(script), option], capture_output=True, text=True)
        assert result.returncode == 2


def test_cli_refuses_modified_fixture(monkeypatch, tmp_path):
    import scripts.etf_fixture_reconcile as module

    changed = tmp_path / 'changed.json'
    changed.write_bytes(FIXTURE.read_bytes() + b' ')
    monkeypatch.setattr(module, 'FIXTURE', changed)
    monkeypatch.setattr(sys, 'argv', ['etf_fixture_reconcile.py'])
    with pytest.raises(ValueError, match='pinned invented fixture changed'):
        module.main()
