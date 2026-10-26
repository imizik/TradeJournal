"""Fixed ETF input admission and exploratory output; called only by Factory.

No CLI, provider, database, broker, model or statistical-gate path. Production
pins have no command-line overrides. Tests replace them for invented inputs.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from app.engine import etf_portfolio as portfolio

KIND = 'etf_bil_exploratory_v1'
SPEC = {
    'family': KIND,
    'symbols': ['SPY', 'EFA', 'EEM', 'IEF', 'BIL'],
    'risk_sleeve_weights': ['0.25'] * 4,
    'signal': {'lookback_months': 12, 'comparison': 'total_return_strictly_above_BIL',
               'tie': 'BIL', 'frequency': 'completed_month_end'},
    'execution': 'mark_existing_then_rebalance_at_next_session_close',
    'holdings': 'fractional_total_return_units_ex_date_reinvestment',
    'cost_rates': ['0.001', '0.003'],
    'price_window': ['2016-01-01', '2024-09-30'],
    'start_nav_date': '2017-01-31', 'first_allocation': '2017-02-01',
    'terminal': '2024-09-30_mark_then_full_liquidation_with_cost',
    'primary_comparator': 'monthly_equal_weight_SPY_EFA_EEM_IEF_same_conventions',
    'descriptive_reference': 'BIL_same_conventions',
    'primary_estimand': '1200_times_mean_paired_monthly_simple_net_return_difference',
    'follow_up': {'base_increment_pp_at_least': '2', 'stress_increment_pp_above': '0'},
    'validation_status': 'exploratory_only',
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       allow_nan=False, default=str) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Economic identity excludes filenames, descriptions, input versions and code:
# moving/rebuilding a bundle must never buy another attempt.
ID = 'etf-' + digest(encoded(SPEC))[:16]
MANIFEST_SHA256 = 'd2f07d938cc66ee7d8fb1fbc155a82823dd5a9574e3fb0e3bd5ecae66c736c43'
CALENDAR_SHA256 = 'e146c2a83fc72017fdde4f6f4fcb4b9862e5def917e435fbe72f642a1bbed9e7'
SESSION_COUNT = 2200
FIRST_LAST = ('2016-01-04', '2024-09-30')
MONTHLY_COUNT = 92
CODE_FILES = ('backend/scripts/factory_search.py', 'backend/scripts/factory_etf.py',
              'backend/scripts/strategy_factory.py', 'backend/app/engine/etf_portfolio.py')


def code_digest(root):
    return digest(b''.join(name.encode() + b'\0' + (root / name).read_bytes()
                           for name in CODE_FILES))


def already_counted(records):
    # Refuse the fixed case even if a historical/manual record used another ID.
    # This intake admits no family variants, so any prior family exposure blocks.
    return any(r.get('id') == ID or r.get('evaluation_kind') == KIND
               or (r.get('spec') or {}).get('family') == KIND for r in records)


def read_file(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing, linked or oversized ETF input')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Oversized ETF input')
    return raw


def verified_bundle(directory):
    """Hash archived bytes only, without computing returns or parsing prices."""
    directory = Path(directory)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError('ETF bundle requires an absolute, unlinked directory')
    raw = read_file(directory / 'manifest.json', 32_000)
    if digest(raw) != MANIFEST_SHA256:
        raise ValueError('ETF manifest does not match the frozen input candidate')
    manifest = json.loads(raw)
    if (manifest['symbols'] != list(portfolio.SYMBOLS)
            or manifest['price_window'] != SPEC['price_window']
            or manifest['sessions'] != SESSION_COUNT
            or manifest['actual_first_last'] != list(FIRST_LAST)
            or manifest['calendar_sha256'] != CALENDAR_SHA256):
        raise ValueError('ETF input metadata differs from frozen scope')
    sessions = None
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('ETF source path leaves bundle')
        path = directory / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != directory.parent):
            raise ValueError('Linked ETF source path')
        data = read_file(path, 4_000_000)
        if digest(data) != expected:
            raise ValueError(f'ETF input hash mismatch: {name}')
        if name == 'sessions.jsonl':
            sessions = data
    if sessions is None:
        raise ValueError('Missing normalized ETF sessions')
    return manifest, sessions


def load_sessions(raw):
    """Only the reserved child calls this, using bytes verified in that child."""
    data = [json.loads(line) for line in raw.splitlines()]
    days = tuple(date.fromisoformat(r['day']) for r in data)
    if (len(days) != SESSION_COUNT or not days
            or (days[0].isoformat(), days[-1].isoformat()) != FIRST_LAST
            or any(d < date(2016, 1, 1) or d > portfolio.CUTOFF for d in days)
            or digest(('\n'.join(d.isoformat() for d in days) + '\n').encode()) != CALENDAR_SHA256):
        raise ValueError('ETF calendar differs from the reviewed complete window')
    rows = []
    for record, day in zip(data, days):
        if (set(record) != {'day', 'close', 'distribution', 'split'}
                or any(not isinstance(record[k], list) or len(record[k]) != 5
                       or any(not isinstance(v, str) for v in record[k])
                       for k in ('close', 'distribution', 'split'))):
            raise ValueError('ETF rows require explicit decimal-string prices and actions')
        rows.append(portfolio.Session(day, *(tuple(Decimal(v) for v in record[k])
                                            for k in ('close', 'distribution', 'split'))))
    rows = tuple(rows)
    portfolio.validate_sessions(rows, days)
    return rows, days


def calculate_artifact(raw, code_sha256):
    rows, days = load_sessions(raw)
    results = portfolio.calculate(rows, days)
    if (len(results) != 2 or tuple(r.cost_rate for r in results) != portfolio.COSTS
            or any(len(r.active.monthly_returns) != MONTHLY_COUNT for r in results)):
        raise ValueError('ETF calculation departed from the frozen analysis contract')
    increments = [str(r.annualized_increment_pp) for r in results]
    follow_up = (results[0].annualized_increment_pp >= Decimal('2')
                 and results[1].annualized_increment_pp > 0)
    summary = {'annualized_increment_pp': increments, 'monthly_observations': MONTHLY_COUNT,
               'continuation_criterion_met': follow_up, 'validated': False}
    payload = {'evaluation_kind': KIND, 'candidate_id': ID,
               'input_manifest_sha256': MANIFEST_SHA256, 'code_sha256': code_sha256,
               'validation_status': 'exploratory_only', 'summary': summary,
               'limitations': ['Revised survivor-selected history; original known-at unavailable.',
                               'Fractional total-return units and daily-close proxies, not executable fills.',
                               'Continuation criterion is not a statistical validation gate.'],
               'calculations': [asdict(r) for r in results]}
    return encoded(payload), summary


def artifact_path(root):
    return root / 'research/reports' / f'{ID}-exploratory.json'


def validate_result(record, reservation, root):
    """Keep normal completion and restart recovery on the same admission path."""
    if (not isinstance(record, dict) or set(record) != set(reservation) | {'exploration'}
            or record.get('attempt_state') != 'completed'
            or record.get('verdict') != 'exploratory_only'
            or any(record.get(k) != v for k, v in reservation.items()
                   if k not in ('attempt_state', 'verdict'))):
        raise ValueError('ETF completion does not match its reservation')
    summary = record['exploration']
    path = artifact_path(root)
    if (not isinstance(summary, dict) or summary.get('artifact') != str(path.relative_to(root))
            or summary.get('validated') is not False
            or summary.get('monthly_observations') != MONTHLY_COUNT
            or not isinstance(summary.get('continuation_criterion_met'), bool)):
        raise ValueError('Invalid ETF exploratory result')
    raw = read_file(path, 8_000_000)
    if digest(raw) != summary.get('artifact_sha256'):
        raise ValueError('ETF exploratory artifact hash mismatch')
    payload = json.loads(raw)
    if (not isinstance(payload, dict) or payload.get('evaluation_kind') != KIND or payload.get('candidate_id') != ID
            or payload.get('input_manifest_sha256') != MANIFEST_SHA256
            or payload.get('code_sha256') != reservation['code_sha256']
            or payload.get('validation_status') != 'exploratory_only'
            or payload.get('summary') != {k: v for k, v in summary.items()
                                          if k not in ('artifact', 'artifact_sha256')}):
        raise ValueError('ETF artifact does not match completion')
    return record
