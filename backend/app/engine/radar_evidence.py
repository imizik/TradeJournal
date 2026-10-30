"""Outcome-blind session census from immutable recorder receipts; no provider reads."""
from datetime import date, datetime, timedelta

from app.engine.chart_math import ET
from app.engine.radar_comparison import epoch
from app.engine.radar_dip import is_dip


def side_receipt(receipt: dict | None, side: str | None) -> dict | None:
    """The receipt as one rule saw it: the trial rules' own (``side`` None), else that side rule's result over the
    pass's shared fields (origin, hours); None when the side rule did not run on the pass."""
    if receipt is None or side is None:
        return receipt
    result = receipt.get(side)
    return None if result is None else {**receipt, **result}


def census(store, today: str, side: str | None = None) -> list[dict]:
    """One row per session for the trial rules, or with ``side="dip"`` for the dip rule (only sessions it ran on)."""
    receipts, configs = store.detection_evidence()
    receipts = {pass_id: side_receipt(r, side) for pass_id, r in receipts.items()}
    sessions = sorted(s for s in store.sessions() if s < today)
    if not sessions:
        return []
    # Missing weekdays are explicit unknown-calendar dates, never inferred sessions.
    days = set(sessions)
    day, end = date.fromisoformat(sessions[0]), date.fromisoformat(today)
    while day < end:
        if day.weekday() < 5:
            days.add(day.isoformat())
        day += timedelta(days=1)
    result = []
    for session in sorted(days):
        passes = store.passes(session)
        events = [e for e in store.events(session) if is_dip(e) == (side == 'dip')]
        own = [receipts.get(p['id']) for p in passes]
        if side is not None and not any(own):
            continue
        digests = {r['config_digest'] for r in own if r}
        versions = {configs[d]['rules']['version'] for d in digests if d in configs}
        if not versions:
            versions = {e['rule_version'] for e in events}
        issues = set()
        if not passes:
            issues.add('no recorded passes; calendar unknown')
        if any(r is None for r in own):
            issues.add('missing detector receipt')
        if len(digests) != 1 or len(versions) != 1:
            issues.add('missing or mixed frozen configuration')
        hours = {(r['hours']['open'], r['hours']['close']) for r in own
                 if r and r.get('hours') and r['hours'].get('status') == 'open'}
        if len(hours) != 1:
            issues.add('missing or inconsistent session hours')
        slots = set()
        claimed = []
        for p, r in zip(passes, own):
            if not r:
                continue
            config = configs.get(r['config_digest'])
            if not config or p['universe_version'] != config['universe']['version']:
                issues.add('universe identity mismatch')
            if r['origin'] != 'live' or r['status'] != 'ok' or p['status'] not in ('ok', 'partial'):
                issues.add('non-live or unsuccessful detection')
            if not r.get('hours') or r['hours'].get('status') != 'open':
                issues.add('calendar unavailable')
            claimed.extend(r['event_ids'])
            # Nearest scheduled minute avoids counting xx:59.999 and xx+1:00
            # as a gap. Every scheduled slot is required; duplicates add nothing.
            t = datetime.fromtimestamp(epoch(p['started_at']), ET)
            minute = t.hour * 60 + t.minute + (t.second + t.microsecond / 1e6) / 60
            slots.add(int(minute + 0.5))
        expected = set(range(*next(iter(hours)))) if len(hours) == 1 else set()
        missing = len(expected - slots)
        if missing:
            issues.add('missing scheduled minute slots')
        by_id = {e['event_id']: e for e in events}
        if len(claimed) != len(set(claimed)) or set(claimed) != set(by_id):
            issues.add('events lack unique live receipt provenance')
        for p, r in zip(passes, own):
            if not r:
                continue
            config = configs.get(r['config_digest'])
            for event_id in r['event_ids']:
                e = by_id.get(event_id)
                if not e or not config or (e['first_seen_at'] != p['finished_at']
                        or e['rule_version'] != config['rules']['version']
                        or e['universe_version'] != config['universe']['version']):
                    issues.add('event receipt identity mismatch')
        result.append({'record_type': 'session', 'session_date': session,
                       'rule_version': next(iter(versions)) if len(versions) == 1 else 'unknown',
                       'config_digest': next(iter(digests)) if len(digests) == 1 else None,
                       'passes': len(passes), 'events': len(events), 'expected_minutes': len(expected),
                       'recorded_minutes': len(expected & slots), 'missing_minutes': missing,
                       'verified': not issues, 'issues': sorted(issues)})
    return result
