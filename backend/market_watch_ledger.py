"""Opt-in append-only market-watch records in the isolated check ledger.

No providers, app database, delivery or evaluator are imported here. The MW-2
read notice is a sealed copy of one read's public fields, handed to the app
through a write-once outbox file; the app delivers any message, never this process.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from cloud_mcp_check_ledger import Conflict, NotFound
from market_watch_common import canonical, digest, seal, verify, validate_snapshot, parse_time

HORIZONS = ('30m', '60m', 'close')
TABLES = ('market_watch_input', 'market_watch_read', 'market_watch_comparator', 'market_watch_message_event')
DAILY_DISCRETIONARY_INTENTS = 3


class FullMarketRequired(ValueError):
    """A live Jo request cannot create a new read under the frozen IEX protocol."""


class MessageBudgetExceeded(ValueError):
    """The actor already reserved its discretionary messages for this session."""


def identifier(prefix):
    return prefix + '_' + str(uuid.uuid4())


def actor_valid(actor):
    if not isinstance(actor, str) or not re.fullmatch(r'check_[0-9a-f-]{36}', actor):
        raise ValueError('Invalid authenticated actor')
    if str(uuid.UUID(actor[6:])) != actor[6:]:
        raise ValueError('Invalid authenticated actor')


def text(value, name, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid ' + name)


def pointer(snapshot, ref):
    if ref == '':
        return
    if not isinstance(ref, str) or not ref.startswith('/') or len(ref) > 500:
        raise ValueError('Invalid evidence reference')
    node = snapshot
    try:
        for raw in ref[1:].split('/'):
            if re.search(r'~(?![01])', raw):
                raise ValueError('Invalid pointer escape')
            key = raw.replace('~1', '/').replace('~0', '~')
            if isinstance(node, list):
                if not re.fullmatch(r'0|[1-9][0-9]*', key):
                    raise ValueError('Invalid list pointer')
                node = node[int(key)]
            else:
                node = node[key]
    except (KeyError, IndexError, TypeError):
        raise ValueError('Evidence reference does not exist') from None


def validate_request(req, snapshot):
    required = {'operation_id', 'input_id', 'view', 'main', 'alternative', 'invalidation',
                'change_summary', 'forecasts', 'message_intent', 'prompt_version'}
    optional = {'previous_read_id', 'correction_of_read_id', 'model_id'}
    if not isinstance(req, dict) or not required <= req.keys() or req.keys() - required - optional:
        raise ValueError('Invalid submit fields')
    if len(canonical(req)) > 16384:
        raise ValueError('Submit exceeds 16 KiB')
    for key in ('operation_id', 'input_id', 'prompt_version'):
        text(req[key], key, 200)
    for key in optional:
        if req.get(key) is not None:
            text(req[key], key, 200)
    if req['view'] not in ('up', 'down', 'mixed', 'no_view') or req['message_intent'] not in ('none', 'update', 'correction'):
        raise ValueError('Invalid view or message intent')
    text(req['change_summary'], 'change_summary')
    for key, lists in [('main', ('supporting_refs', 'contradicting_refs')),
                       ('alternative', ('supporting_refs', 'contradicting_refs')),
                       ('invalidation', ('evidence_refs',))]:
        body = req[key]
        if not isinstance(body, dict) or set(body) != {'text', *lists}:
            raise ValueError('Invalid thesis fields')
        text(body['text'], key)
        for name in lists:
            if not isinstance(body[name], list) or len(body[name]) > 10:
                raise ValueError('Invalid evidence references')
            for ref in body[name]:
                pointer(snapshot, ref)
    forecasts = req['forecasts']
    if not isinstance(forecasts, list) or len(forecasts) != 3 or {f.get('horizon') for f in forecasts if isinstance(f, dict)} != set(HORIZONS):
        raise ValueError('Require exactly three forecast horizons')
    for f in forecasts:
        if set(f) - {'horizon', 'predicate', 'probability', 'abstention_reason'} or not {'horizon', 'predicate', 'probability'} <= f.keys() or f['predicate'] != 'spy_return_lt_zero':
            raise ValueError('Invalid forecast')
        p = f['probability']
        if p is None:
            text(f.get('abstention_reason'), 'abstention_reason')
        elif type(p) not in (int, float) or not 0 <= p <= 1 or f.get('abstention_reason') is not None:
            raise ValueError('Invalid probability')


def quality(snapshot, now):
    flags = ['independence-unverified']
    age = (now - parse_time(snapshot['collection_finished_at'])).total_seconds()
    if age < 0:
        raise ValueError('Future snapshot')
    if age > 180:
        flags.append('snapshot-stale')
    if not snapshot.get('session_open_at') or not snapshot.get('session_close_at') or not parse_time(snapshot['session_open_at']) <= now < parse_time(snapshot['session_close_at']):
        flags.append('not-rth-eligible')
    for name, group in list(snapshot['indices'].items()) + [(k, snapshot[k]) for k in ('volatility', 'calendar', 'headlines')]:
        if group.get('status') != 'fresh':
            flags.append(name + ':' + str(group.get('status', 'missing')))
        stamp = group.get('retrieved_at') if name == 'headlines' else group.get('observed_at')
        limit = {'SPY': 180, 'QQQ': 180, 'volatility': 3600, 'headlines': 1800}.get(name)
        if stamp and limit and (now - parse_time(stamp)).total_seconds() > limit and name + ':stale' not in flags:
            flags.append(name + ':stale')
        if name in ('SPY', 'QQQ'):
            for field in ('price', 'prior_close', 'session_open', 'vwap', 'or15_high', 'or15_low'):
                if group.get(field, {}).get('status') != 'fresh':
                    flags.append(name + '.' + field + ':' + str(group.get(field, {}).get('status', 'missing')))
    return flags


def comparator(snapshot, read, now):
    values = {}
    reasons = []
    for symbol in ('SPY', 'QQQ'):
        group = snapshot['indices'][symbol]
        bar = group.get('bar_1m')
        values[symbol] = {'close': bar.get('close') if bar else None,
                          **{k: group.get(k) for k in ('vwap', 'or15_high', 'or15_low')}}
        if group.get('status') != 'fresh' or not bar or (now - parse_time(bar['end'])).total_seconds() > 180:
            reasons.append(symbol + ':stale-or-missing')
        for key in (('vwap', 'or15_high', 'or15_low') if symbol == 'SPY' else ('vwap',)):
            item = group.get(key)
            if not isinstance(item, dict) or item.get('status') != 'fresh' or item.get('value') is None:
                reasons.append(symbol + ':' + key + ':unavailable')
    signal = 'unavailable'
    if not reasons:
        spy, qqq = values['SPY'], values['QQQ']
        if all(v['close'] < v['vwap']['value'] for v in (spy, qqq)) and spy['close'] < spy['or15_low']['value']:
            signal = 'down'
        elif all(v['close'] > v['vwap']['value'] for v in (spy, qqq)) and spy['close'] > spy['or15_high']['value']:
            signal = 'up'
        else:
            signal = 'neutral'
    return seal({'comparator_id': identifier('mwc'), 'read_id': read['read_id'], 'protocol_id': 'mw-v1',
                 'snapshot_sha256': snapshot['content_sha256'], 'computed_at': now.isoformat(),
                 'created_at': now.isoformat(), 'version': 'price-check-v1', 'signal': signal,
                 'inputs': values, 'reasons': reasons,
                 'probabilities': {h: {'down': .65, 'up': .35, 'neutral': .5}.get(signal) for h in HORIZONS}})


class MarketWatchLedger:
    def __init__(self, ledger):
        self.ledger = ledger
        with self.connection() as db:
            for table in TABLES:
                db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, actor TEXT NOT NULL, operation_id TEXT, request_sha256 TEXT, record_json TEXT NOT NULL, UNIQUE(actor, operation_id))')
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id OR (actor=NEW.actor AND operation_id=NEW.operation_id)) BEGIN SELECT RAISE(ABORT, 'market watch records are immutable'); END")
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'market watch records are immutable'); END")

    @contextmanager
    def connection(self):
        db = self.ledger._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def insert(db, table, record, key, operation=None, request_hash=None):
        db.execute(f'INSERT INTO {table} VALUES (?, ?, ?, ?, ?)',
                   (record[key], record['actor'], operation, request_hash, canonical(record).decode()))

    @staticmethod
    def rows(db, table, actor):
        result = [json.loads(r[0]) for r in db.execute(f'SELECT record_json FROM {table} WHERE actor=? ORDER BY rowid', (actor,))]
        for record in result:
            verify(record)
        return result

    def _context(self, db, actor, session_date):
        reads = [r for r in self.rows(db, TABLES[1], actor) if r['session_date'] == session_date]
        by_id = {r['read_id']: r for r in reads}
        intents = [m for m in self.rows(db, TABLES[3], actor)
                   if m['kind'] == 'intent' and m['read_id'] in by_id]
        used = sum(not m['is_correction'] for m in intents)
        latest_intent = intents[-1] if intents else None
        return {'session_date': session_date, 'latest_read': reads[-1] if reads else None,
                'latest_message_intent': ({'message_id': latest_intent['message_id'],
                    'is_correction': latest_intent['is_correction'],
                    'read': by_id[latest_intent['read_id']]} if latest_intent else None),
                'discretionary_intents_used': used,
                'discretionary_intents_remaining': max(0, DAILY_DISCRETIONARY_INTENTS - used),
                'delivery_status': 'unverified'}

    def context(self, actor, clock):
        """Own current-session records only; never exposes checks or another actor."""
        actor_valid(actor)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            session_date = clock().astimezone(ZoneInfo('America/New_York')).date().isoformat()
            return self._context(db, actor, session_date)

    def serve(self, actor, snapshot, clock):
        actor_valid(actor)
        validate_snapshot(snapshot)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            now = clock()
            if snapshot['session_date'] != now.astimezone(ZoneInfo('America/New_York')).date().isoformat():
                raise ValueError('Snapshot is not current session')
            flags = quality(snapshot, now)
            record = seal({'input_id': identifier('mwi'), 'actor': actor, 'snapshot_id': snapshot['snapshot_id'],
                           'snapshot_sha256': snapshot['content_sha256'], 'snapshot_json': snapshot,
                           'served_at': now.isoformat(), 'created_at': now.isoformat()})
            self.insert(db, TABLES[0], record, 'input_id')
            context = self._context(db, actor, snapshot['session_date'])
        return {'input_id': record['input_id'], 'served_at': record['served_at'], 'snapshot_id': snapshot['snapshot_id'],
                'snapshot_sha256': snapshot['content_sha256'], 'snapshot': snapshot, 'quality_flags': flags,
                'context': context}

    def submit(self, actor, request, clock, *, full_market_only=False):
        actor_valid(actor)
        request_hash = digest(request)
        if len(canonical(request)) > 16384:
            raise ValueError('Submit exceeds 16 KiB')
        text(request.get('operation_id'), 'operation_id', 200)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT request_sha256, record_json FROM market_watch_read WHERE actor=? AND operation_id=?', (actor, request['operation_id'])).fetchone()
            if prior:
                if prior[0] != request_hash:
                    raise Conflict('Operation already committed with different content')
                read = json.loads(prior[1])
                verify(read)
                return self.receipt(db, read, True)
            if full_market_only:
                # This ledger's immutable MW-1 protocol is IEX. Historical/offline
                # evaluation stays reproducible; already committed retries still recover.
                raise FullMarketRequired("MW-1 does not supply full-market evidence")
            now = clock()  # Only after lock; retries deliberately precede age/session checks.
            inputs = self.rows(db, TABLES[0], actor)
            inp = next((i for i in inputs if i['input_id'] == request.get('input_id')), None)
            if inp is None:
                raise NotFound('Input unavailable for actor')
            snapshot = inp['snapshot_json']
            validate_snapshot(snapshot)
            validate_request(request, snapshot)
            if snapshot['session_date'] != now.astimezone(ZoneInfo('America/New_York')).date().isoformat():
                raise ValueError('Input is not current session')
            reads = [r for r in self.rows(db, TABLES[1], actor) if r['session_date'] == snapshot['session_date']]
            if request.get('previous_read_id') != (reads[-1]['read_id'] if reads else None):
                raise Conflict('Latest parent required')
            correction = request.get('correction_of_read_id')
            if correction and not any(r['read_id'] == correction for r in reads):
                raise ValueError('Correction must reference earlier same-session read')
            prior_message = next((m for m in self.rows(db, TABLES[3], actor) if m['read_id'] == correction and m['kind'] == 'intent'), None) if correction else None
            if request['message_intent'] == 'correction' and not prior_message:
                raise ValueError('Message correction requires an earlier intent')
            if request['message_intent'] == 'update' and not self._context(db, actor, snapshot['session_date'])['discretionary_intents_remaining']:
                raise MessageBudgetExceeded('Daily discretionary message-intent budget exhausted')
            read_id = identifier('mwr')
            read = seal({**request, 'read_id': read_id, 'actor': actor, 'request_sha256': request_hash,
                         'received_at': now.isoformat(), 'created_at': now.isoformat(),
                         'session_date': snapshot['session_date'], 'protocol_id': 'mw-v1',
                         'snapshot_id': snapshot['snapshot_id'], 'snapshot_sha256': snapshot['content_sha256'],
                         'previous_read_id': request.get('previous_read_id'),
                         'model_id': request.get('model_id'), 'correction_of_read_id': correction,
                         'forecasts': [{**f, 'forecast_id': read_id + ':' + f['horizon']} for f in request['forecasts']],
                         'quality_flags': quality(snapshot, now)})
            comp = comparator(snapshot, read, now)
            comp = seal({**comp, 'actor': actor})
            self.insert(db, TABLES[1], read, 'read_id', request['operation_id'], request_hash)
            self.insert(db, TABLES[2], comp, 'comparator_id')
            if request['message_intent'] != 'none':
                message = seal({'event_id': identifier('mwe'), 'message_id': identifier('mwm'), 'actor': actor,
                                'read_id': read_id, 'kind': 'intent', 'channel': 'none', 'source': 'system',
                                'is_correction': request['message_intent'] == 'correction',
                                'corrects_message_id': prior_message['message_id'] if request['message_intent'] == 'correction' else None,
                                'text': request['main']['text'], 'text_sha256': digest(request['main']['text']),
                                'occurred_at': now.isoformat(), 'recorded_at': now.isoformat(), 'created_at': now.isoformat(),
                                'transport_receipt_id': None, 'error_code': None, 'rating': None})
                self.insert(db, TABLES[3], message, 'event_id')
            return self.receipt(db, read, False)

    def receipt(self, db, read, replayed):
        comp = next(c for c in self.rows(db, TABLES[2], read['actor']) if c['read_id'] == read['read_id'])
        intent = next((m for m in self.rows(db, TABLES[3], read['actor']) if m['read_id'] == read['read_id'] and m['kind'] == 'intent'), None)
        return {k: read[k] for k in ('read_id', 'received_at', 'snapshot_id', 'snapshot_sha256', 'content_sha256', 'quality_flags')} | {
            'comparator_id': comp['comparator_id'], 'message_id': intent['message_id'] if intent else None, 'replayed': replayed}

    def read_notice(self, actor, read_id):
        """Deterministic MW-2 notice for one committed read; identical on every replay."""
        actor_valid(actor)
        with self.connection() as db:
            read = next((r for r in self.rows(db, TABLES[1], actor) if r['read_id'] == read_id), None)
            if read is None:
                raise NotFound('Read unavailable for actor')
            intent = next((m for m in self.rows(db, TABLES[3], actor) if m['read_id'] == read_id and m['kind'] == 'intent'), None)
        return read_notice(read, intent)

    def append_market_watch_message_event(self, message_id, operation_id, event, *, clock=lambda: datetime.now(timezone.utc)):
        """Internal owner/transport boundary only; never exposed through MCP."""
        text(operation_id, 'operation_id', 200)
        allowed = {'kind', 'source', 'channel', 'occurred_at', 'transport_receipt_id', 'error_code', 'rating'}
        if not isinstance(event, dict) or event.keys() - allowed or not {'kind', 'source', 'channel', 'occurred_at'} <= event.keys():
            raise ValueError('Invalid event fields')
        kind, source, channel = (event[k] for k in ('kind', 'source', 'channel'))
        if kind not in ('attempt', 'accepted', 'delivered', 'failed', 'unknown', 'rated') or source not in ('transport', 'owner_report') or channel not in ('email', 'push', 'none'):
            raise ValueError('Invalid event')
        if kind in ('attempt', 'accepted', 'delivered', 'failed') and (source != 'transport' or channel == 'none'):
            raise ValueError('Transport evidence required')
        if kind in ('accepted', 'delivered'):
            text(event.get('transport_receipt_id'), 'transport receipt', 200)
        if kind == 'rated':
            if source != 'owner_report' or event.get('rating') not in ('useful', 'not_useful'):
                raise ValueError('Owner rating required')
        elif event.get('rating') is not None:
            raise ValueError('Rating only belongs to rated event')
        for field in ('transport_receipt_id', 'error_code'):
            if event.get(field) is not None:
                text(event[field], field, 200)
        request_hash = digest({'message_id': message_id, 'event': event})
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            records = [json.loads(r[0]) for r in db.execute('SELECT record_json FROM market_watch_message_event')]
            intent = next((m for m in records if m['message_id'] == message_id and m['kind'] == 'intent'), None)
            if intent is None:
                raise NotFound('Message intent unavailable')
            verify(intent)
            prior = db.execute('SELECT request_sha256,record_json FROM market_watch_message_event WHERE actor=? AND operation_id=?', (intent['actor'], operation_id)).fetchone()
            if prior:
                if prior[0] != request_hash:
                    raise Conflict('Event operation conflicts')
                result = json.loads(prior[1])
                verify(result)
                return result
            now = clock()
            occurred = parse_time(event['occurred_at'])
            if occurred > now or occurred < parse_time(intent['occurred_at']):
                raise ValueError('Invalid event time')
            result = seal({**intent, **event, 'event_id': identifier('mwe'), 'operation_id': operation_id,
                           'occurred_at': occurred.isoformat(), 'created_at': now.isoformat(), 'recorded_at': now.isoformat()})
            self.insert(db, TABLES[3], result, 'event_id', operation_id, request_hash)
            return result

    @staticmethod
    def export(path, actor):
        """Read-only owner invocation. No schema creation or private table reads."""
        from pathlib import Path
        actor_valid(actor)
        path = Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError('Require owner ledger file')
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            collections = {key: MarketWatchLedger.rows(db, table, actor) for key, table in zip(('inputs', 'reads', 'comparators', 'messages'), TABLES)}
        # Deterministic envelope makes repeated exports byte-identical.
        stamp = max((r['created_at'] for rows in collections.values() for r in rows), default='1970-01-01T00:00:00+00:00')
        return seal({'export_id': 'mwx_' + digest(collections), 'actor': actor, 'protocol_id': 'mw-v1', 'created_at': stamp, **collections})


NOTICE_VERSION = 'mw-read-notice-v1'


def read_notice(read, intent):
    verify(read)
    if intent is not None:
        verify(intent)
    return seal({'notice_version': NOTICE_VERSION, 'read_id': read['read_id'], 'actor': read['actor'],
                 'received_at': read['received_at'], 'created_at': read['received_at'],
                 'session_date': read['session_date'], 'protocol_id': read['protocol_id'],
                 'snapshot_id': read['snapshot_id'], 'snapshot_sha256': read['snapshot_sha256'],
                 'read_sha256': read['content_sha256'], 'previous_read_id': read.get('previous_read_id'),
                 'view': read['view'], 'message_intent': read['message_intent'],
                 'message_id': intent['message_id'] if intent else None,
                 'is_correction': bool(intent and intent['is_correction']),
                 'corrects_message_id': intent['corrects_message_id'] if intent else None,
                 'correction_of_read_id': read.get('correction_of_read_id'),
                 'main_text': read['main']['text'], 'alternative_text': read['alternative']['text'],
                 'invalidation_text': read['invalidation']['text'], 'change_summary': read['change_summary'],
                 'forecasts': [{'horizon': f['horizon'], 'probability': f['probability']} for f in read['forecasts']],
                 'quality_flags': read['quality_flags']})


def write_read_notice(directory, notice):
    """Write once; an existing identical file recovers, a different one refuses."""
    verify(notice)
    if not re.fullmatch(r'mwr_[0-9a-f-]{36}', notice.get('read_id', '')):
        raise ValueError('Invalid read notice identity')
    destination = Path(directory) / f"read-{notice['read_id']}.json"
    body = canonical(notice)
    import fcntl
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        try:
            fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            fd = None
        if fd is not None:
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(body) or os.read(fd, len(body) + 1) != body:
                    raise ValueError('Market-watch ledger and outbox disagree')
            finally:
                os.close(fd)
            return
        fd, temporary = tempfile.mkstemp(prefix='.read-', dir=directory)
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.fsync(directory_fd)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        os.close(directory_fd)
