"""Bounded full-market stock reads shared by Jo and Market Watch.

No environment, database, account or order access. Only fixed production market
endpoints can receive the supplied credential; every price retains its source time.
"""
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import copy
import math
import re
import threading
import time
from zoneinfo import ZoneInfo

import httpx

ET = ZoneInfo('America/New_York')
UTC = timezone.utc
SYMBOL = re.compile(r'^[A-Z]{1,6}(\.[A-Z])?$')


class TradierDataError(ValueError):
    pass


class DailyBars(list):
    """Usable suffix plus request-local quality evidence (never shared state)."""

    def __init__(self, bars, rejected_dates):
        super().__init__(bars)
        self.rejected_dates = sorted(rejected_dates)


class TradierStockData:
    source = 'Tradier full_market'

    def __init__(self, token, *, timeout=3, transport=None, clock=None):
        self.client = httpx.Client(base_url='https://api.tradier.com', timeout=timeout,
            transport=transport, follow_redirects=False, trust_env=False,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.pending = {}
        self.calls = deque()
        self.cooldown = 0.0
        self.errors = OrderedDict()

    def get(self, path, params, ttl, *, with_time=False):
        if path not in {'/v1/markets/timesales', '/v1/markets/history', '/v1/markets/quotes'}:
            raise TradierDataError('unsupported_market_endpoint')
        key = (path, tuple(sorted(params.items())))
        with self.lock:
            entry = self.pending.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        lock = entry[0]
        if not lock.acquire(timeout=3):
            with self.lock:
                entry[1] -= 1
                if entry[1] == 0:
                    self.pending.pop(key, None)
            raise TradierDataError('request_in_progress')
        try:
            now = time.monotonic()
            with self.lock:
                cached = self.cache.get(key)
                if cached and now - cached[0] < ttl:
                    self.cache.move_to_end(key)
                    return (copy.deepcopy(cached[1]), cached[2]) if with_time else copy.deepcopy(cached[1])
                failed = self.errors.get(key)
                if failed and now - failed[0] < 5:
                    raise TradierDataError(failed[1])
                while self.calls and now - self.calls[0] >= 60:
                    self.calls.popleft()
                if now < self.cooldown:
                    raise TradierDataError('provider_rate_limited')
                if len(self.calls) >= 30:
                    raise TradierDataError('local_request_budget')
                self.calls.append(now)
            requested_at = self.clock().astimezone(UTC)
            try:
                with self.client.stream('GET', path, params=params) as response:
                    if response.status_code == 429:
                        with self.lock:
                            self.cooldown = now + 60
                        raise TradierDataError('provider_rate_limited')
                    if response.status_code in (401, 403):
                        raise TradierDataError('provider_access_denied')
                    if response.status_code != 200:
                        raise TradierDataError('provider_http_error')
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024 or time.monotonic() - now > 4:
                            raise TradierDataError('provider_response_limit')
                import json
                payload = json.loads(body)
                if not isinstance(payload, dict) or payload.get('fault') or payload.get('errors'):
                    raise TradierDataError('provider_invalid_response')
            except httpx.TimeoutException:
                raise TradierDataError('provider_timeout') from None
            except httpx.HTTPError:
                raise TradierDataError('provider_transport_error') from None
            except (ValueError, UnicodeError) as exc:
                if isinstance(exc, TradierDataError):
                    raise
                raise TradierDataError('provider_invalid_response') from None
            with self.lock:
                self.cache[key] = (time.monotonic(), payload, requested_at)
                while len(self.cache) > 96:
                    self.cache.popitem(last=False)
                self.errors.pop(key, None)
            return (copy.deepcopy(payload), requested_at) if with_time else copy.deepcopy(payload)
        except TradierDataError as exc:
            with self.lock:
                # Preserve the original failure deadline: polling cannot extend it.
                previous = self.errors.get(key)
                if not previous or time.monotonic() - previous[0] >= 5:
                    self.errors[key] = (time.monotonic(), str(exc))
                while len(self.errors) > 96:
                    self.errors.popitem(last=False)
            raise
        finally:
            lock.release()
            with self.lock:
                entry[1] -= 1
                if entry[1] == 0:
                    self.pending.pop(key, None)

    @staticmethod
    def symbols(symbols):
        if not 1 <= len(symbols) <= 8 or any(not SYMBOL.fullmatch(s) for s in symbols):
            raise TradierDataError('unsupported_stock_symbols')
        return list(dict.fromkeys(symbols))

    def _batch(self, symbols, read):
        def one(symbol):
            try:
                return symbol, read(symbol)
            except (TradierDataError, ValueError, TypeError, KeyError, OverflowError):
                return symbol, []
        with ThreadPoolExecutor(max_workers=3) as pool:
            return dict(pool.map(one, self.symbols(symbols)))

    def minutes(self, symbol, day):
        self.symbols([symbol])
        cutoff = self.clock().astimezone(UTC)
        if day > cutoff.astimezone(ET).date():
            raise TradierDataError('future_session')
        payload, requested_at = self.get('/v1/markets/timesales', {'symbol': symbol, 'interval': '1min',
            'start': f'{day} 04:00', 'end': f'{day} 20:00', 'session_filter': 'all'}, 10, with_time=True)
        cutoff = min(cutoff, requested_at)  # Cached partial minutes must never mature into completed bars.
        rows = _rows(payload.get('series'), 'data')
        result = []
        for row in rows:
            at = datetime.fromtimestamp(float(row['timestamp']), UTC)
            if at.second or at.microsecond:
                raise TradierDataError('unaligned_minute')
            if at.astimezone(ET).date() == day and at + timedelta(minutes=1) <= cutoff:
                result.append(_bar(row, at))
        return _ordered(result)

    def fetch_minute_bars_live(self, symbols, day):
        return self._batch(symbols, lambda s: self.minutes(s, day))

    def fetch_daily_bars(self, symbols, start, end):
        def read(symbol):
            payload = self.get('/v1/markets/history', {'symbol': symbol, 'interval': 'daily',
                'start': start.isoformat(), 'end': end.isoformat()}, 3600)
            valid, rejected, seen = {}, set(), set()
            for row in _rows(payload.get('history'), 'day'):
                # An unplaceable row cannot establish a safe suffix.
                if not isinstance(row, dict):
                    raise TradierDataError('invalid_daily_date')
                label = row.get('date')
                if not isinstance(label, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', label):
                    raise TradierDataError('invalid_daily_date')
                at = datetime.fromisoformat(label).replace(tzinfo=ET)
                if not start <= at.date() < end:
                    continue
                if label in seen:
                    rejected.add(label)
                    continue
                seen.add(label)
                try:
                    valid[label] = _bar(row, at)
                except (ValueError, TypeError, KeyError, OverflowError):
                    rejected.add(label)
            # Never compress a known missing session into an indicator window.
            boundary = max(rejected, default='')
            return DailyBars([valid[d] for d in sorted(valid) if d > boundary], rejected)
        return self._batch(symbols, read)

    def fetch_snapshots(self, symbols):
        symbols = self.symbols(symbols)
        payload = self.get('/v1/markets/quotes', {'symbols': ','.join(symbols)}, 10)
        result = {}
        for row in _rows(payload.get('quotes'), 'quote'):
            if row.get('symbol') not in symbols:
                continue
            at = datetime.fromtimestamp(float(row['trade_date']) / 1000, UTC)
            if at > self.clock() or not _positive(row.get('last')):
                continue
            result[row['symbol']] = {'latestTrade': {'p': row['last'], 't': at.isoformat()},
                'prevDailyBar': {'c': row.get('prevclose')},
                'dailyBar': {'t': at.isoformat(), 'o': row.get('open'), 'h': row.get('high'),
                    'l': row.get('low'), 'c': row['last'], 'v': row.get('volume')}}
        return result


def _rows(container, key):
    rows = container.get(key) if isinstance(container, dict) else None
    return rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else []


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _bar(row, at):
    prices = [row[key] for key in ('open', 'high', 'low', 'close')]
    volume = row['volume']
    if (not all(_positive(v) for v in prices) or type(volume) not in (int, float)
            or not math.isfinite(volume) or volume < 0
            or not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']):
        raise TradierDataError('invalid_ohlcv')
    return {'t': at.isoformat(), **dict(zip(('o', 'h', 'l', 'c'), prices)), 'v': volume}


def _ordered(rows):
    rows.sort(key=lambda row: row['t'])
    if len({row['t'] for row in rows}) != len(rows):
        raise TradierDataError('duplicate_bar')
    return rows
