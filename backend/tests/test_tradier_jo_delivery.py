"""Actual Jo tool flows with recorded-shape Tradier HTTP, never live providers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from tradier_stock_data import TradierStockData, TradierDataError, ET
from tests.test_cloud_mcp_check import harness as harness, signing_key as signing_key, call, IDEA, RECEIPT, FIXTURE
from tests.test_market_watch_snapshot import fixture_snapshot, NOW
from market_watch_common import TRADIER_PROTOCOL, digest, seal, validate_snapshot
from app.engine.market_watch_snapshot import publish_snapshot


def tradier_fixture(request):
    assert request.url.host == 'api.tradier.com'
    assert request.headers['authorization'] == 'Bearer invented'
    params = request.url.params
    symbols = params.get('symbols', params.get('symbol', '')).split(',')
    if request.url.path.endswith('/quotes'):
        rows = []
        for symbol in symbols:
            snap = FIXTURE['snapshots'][symbol]
            day = snap['dailyBar']
            rows.append({'symbol': symbol, 'last': snap['latestTrade']['p'],
                'trade_date': datetime.fromisoformat(snap['latestTrade']['t'].replace('Z', '+00:00')).timestamp()*1000,
                'prevclose': snap['prevDailyBar']['c'], 'open': day['o'], 'high': day['h'], 'low': day['l'], 'volume': day['v']})
        return httpx.Response(200, json={'quotes': {'quote': rows}})
    kind = 'minute_bars' if request.url.path.endswith('/timesales') else 'daily_bars'
    rows = []
    for bar in FIXTURE[kind].get(symbols[0], []):
        at = datetime.fromisoformat(bar['t'].replace('Z', '+00:00'))
        rows.append({'timestamp': at.timestamp(), 'date': at.astimezone(ET).date().isoformat(),
            **{k: bar[v] for k, v in [('open', 'o'), ('high', 'h'), ('low', 'l'), ('close', 'c'), ('volume', 'v')]}})
    container, key = ('series', 'data') if kind == 'minute_bars' else ('history', 'day')
    return httpx.Response(200, json={container: {key: rows}})


def source(handler=tradier_fixture):
    return TradierStockData('invented', transport=httpx.MockTransport(handler), clock=lambda: RECEIPT)


def test_pretrade_works_on_tradier_without_iex_or_old_volume_cache(harness, monkeypatch):
    from app.engine import scalper
    harness.configure(provider_feed='iex')
    attempts = []
    def forbidden(*args):
        attempts.append(True)
        raise AssertionError('No Alpaca RVOL cache may contaminate Tradier')
    monkeypatch.setattr(scalper, '_cached_cum_volume', forbidden)
    with TestClient(harness.server(tradier_source=source()).streamable_http_app()) as client:
        result = call(client, 'pre_trade_check', IDEA, harness.token())['structuredContent']
    assert result['live']['price'] is not None
    assert result['verdict'] != 'insufficient_data'
    assert any('Tradier full_market' in note for note in result['caveats'])
    assert any('dividend adjustment' in note for note in result['caveats'])
    assert not attempts
    assert all('/stocks/' not in r.url.path for r in harness.requests)


def test_missing_scanner_file_refreshes_completed_tradier_candles(harness):
    reads = []
    def handler(request):
        reads.append(request)
        return tradier_fixture(request)
    with TestClient(harness.server(tradier_source=source(handler)).streamable_http_app()) as client:
        args = {'symbol': 'SPY', 'interval': '1m', 'bars': 60}
        first = call(client, 'candles', args, harness.token())['structuredContent']
        second = call(client, 'candles', args, harness.token())['structuredContent']
    assert first == second and first['feed'] == 'full_market'
    assert first['delivery'] == 'direct_refresh' and first['candles']
    assert all(row['end_time'] <= RECEIPT.timestamp() for row in first['candles'])
    assert len(reads) == 1 and not harness.requests


@pytest.mark.parametrize('status,reason', [(429, 'provider_rate_limited'), (403, 'provider_access_denied'), (500, 'provider_http_error')])
def test_provider_failures_report_cause_without_fallback(harness, status, reason):
    with TestClient(harness.server(tradier_source=source(lambda _: httpx.Response(status))).streamable_http_app()) as client:
        result = call(client, 'candles', {'symbol': 'SPY', 'interval': '1m'}, harness.token())['structuredContent']
    assert result['status'] == 'insufficient_data' and result['candles_unavailable'] == reason
    assert not harness.requests


def test_concurrent_identical_reads_coalesce_and_one_symbol_failure_isolated():
    reads = []
    gate = threading.Event()
    def handler(request):
        reads.append(request.url.params['symbol'])
        gate.wait(.1)
        if request.url.params['symbol'] == 'QQQ':
            raise httpx.ReadTimeout('secret URL must not be exposed')
        return tradier_fixture(request)
    provider = source(handler)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(provider.minutes, 'SPY', RECEIPT.date()) for _ in range(3)]
        gate.set()
        assert all(job.result() for job in jobs)
    assert reads == ['SPY']
    with pytest.raises(TradierDataError, match='provider_timeout'):
        provider.minutes('QQQ', RECEIPT.date())
    assert provider.minutes('SPY', RECEIPT.date())


def full_market_snapshot():
    packet = fixture_snapshot()
    packet['protocol_id'] = TRADIER_PROTOCOL['protocol_id']
    packet['protocol_sha256'] = TRADIER_PROTOCOL['content_sha256']
    for group in packet['indices'].values():
        group['source'] = 'Tradier full_market'
    for item in packet['input_manifest']:
        if item.get('provider') == 'Alpaca':
            item.update(provider='Tradier', feed='full_market', adjustment='provider_reported')
    packet.pop('content_sha256')
    packet.pop('snapshot_id')
    packet['snapshot_id'] = 'mws_' + digest(packet)[:32]
    return seal(packet)


def test_full_market_snapshot_read_submit_and_notice_work(harness, tmp_path):
    from tests.test_market_watch_ledger import request
    from app.engine.market_watch_wakes import validate_notice
    public, outbox = tmp_path / 'public', tmp_path / 'outbox'
    outbox.mkdir()
    packet = full_market_snapshot()
    validate_snapshot(packet)
    publish_snapshot(public, packet)
    harness.configure(market_watch_snapshots_dir=str(public), market_watch_outbox_dir=str(outbox))
    scope = 'check:read market-watch:read market-watch:submit'
    with TestClient(harness.server(now=NOW).streamable_http_app()) as client:
        inp = call(client, 'market_watch_snapshot', {}, harness.token(scope=scope))['structuredContent']
        assert inp['snapshot']['indices']['SPY']['price']['value'] is not None
        receipt = call(client, 'market_watch_submit', request(inp['input_id']), harness.token(scope=scope))['structuredContent']
    notice = json.loads((outbox / f"read-{receipt['read_id']}.json").read_text())
    assert notice['protocol_id'] == 'mw-tradier-v2'
    assert validate_notice(notice, public, NOW + timedelta(seconds=1))


def test_market_watch_producer_reads_tradier_and_preserves_full_session_metrics():
    from app.engine.market_watch_snapshot import build_snapshot
    from tests.test_market_watch_snapshot import _sources, OPEN
    bars, daily = _sources()
    reads = []
    def handler(request):
        reads.append(request)
        symbol = request.url.params['symbol']
        if request.url.path.endswith('/timesales'):
            rows = [{'timestamp': datetime.fromisoformat(b['t'].replace('Z', '+00:00')).timestamp(),
                     **{k: b[v] for k, v in [('open', 'o'), ('high', 'h'), ('low', 'l'), ('close', 'c'), ('volume', 'v')]}}
                    for b in bars[symbol]]
            return httpx.Response(200, json={'series': {'data': rows}})
        rows = [{'date': b['t'][:10], 'open': b['c'], 'high': b['c'], 'low': b['c'], 'close': b['c'], 'volume': 1000}
                for b in daily[symbol]]
        return httpx.Response(200, json={'history': {'day': rows}})
    provider = TradierStockData('invented', transport=httpx.MockTransport(handler), clock=lambda: NOW)
    packet = build_snapshot(NOW, stock_source=provider,
        vix_reader=lambda: None,
        calendar_reader=lambda *_: fixture_snapshot()['calendar'],
        news_reader=lambda *_: fixture_snapshot()['headlines'],
        bounds_reader=lambda _: (OPEN, OPEN + timedelta(hours=6, minutes=30)))
    validate_snapshot(packet)
    assert packet['protocol_id'] == 'mw-tradier-v2'
    assert len(reads) == 4 and all(r.url.host == 'api.tradier.com' for r in reads)
    for symbol in ('SPY', 'QQQ'):
        group = packet['indices'][symbol]
        assert group['price']['status'] == 'fresh'
        assert group['vwap']['value'] is not None and group['or15_high']['value'] is not None
        assert len(group['bars_5m']) == 6
        assert group['source'] == 'Tradier full_market'
    assert all(m.get('feed') != 'iex' for m in packet['input_manifest'])


def test_failure_backoff_expires_and_does_not_return_stale_data(monkeypatch):
    import tradier_stock_data as module
    elapsed = [10.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: elapsed[0])
    reads = []
    def handler(request):
        reads.append(request)
        return httpx.Response(503) if len(reads) == 1 else tradier_fixture(request)
    provider = source(handler)
    for _ in range(2):
        with pytest.raises(TradierDataError, match='provider_http_error'):
            provider.minutes('SPY', RECEIPT.date())
    assert len(reads) == 1
    elapsed[0] += 6
    assert provider.minutes('SPY', RECEIPT.date()) and len(reads) == 2
    assert not provider.pending


def test_five_minute_refresh_excludes_partial_bucket(harness):
    with TestClient(harness.server(tradier_source=source()).streamable_http_app()) as client:
        result = call(client, 'candles', {'symbol': 'SPY', 'interval': '5m'}, harness.token())['structuredContent']
    assert result['candles']
    assert all(row['end'] - row['start'] == 300 and row['end'] <= RECEIPT.timestamp() for row in result['candles'])


def test_market_export_keeps_legacy_and_tradier_cohorts_separate(tmp_path):
    from cloud_mcp_check_ledger import Ledger
    from market_watch_ledger import MarketWatchLedger
    from tests.test_market_watch_ledger import ACTOR, request
    from app.engine.market_watch_evaluation import MarketWatchOutcomeStore
    ledger = MarketWatchLedger(Ledger(tmp_path / 'ledger.db'))
    old = ledger.serve(ACTOR, fixture_snapshot(), lambda: NOW)
    ledger.submit(ACTOR, request(old['input_id']), lambda: NOW)
    fresh = ledger.serve(ACTOR, full_market_snapshot(), lambda: NOW)
    ledger.submit(ACTOR, request(fresh['input_id'], operation_id='v2'), lambda: NOW, full_market_only=True)
    current = ledger.export(ledger.ledger.path, ACTOR)
    legacy = ledger.export(ledger.ledger.path, ACTOR, 'mw-v1')
    assert current['protocol_id'] == 'mw-tradier-v2' and legacy['protocol_id'] == 'mw-v1'
    assert len(current['reads']) == len(legacy['reads']) == 1
    store = MarketWatchOutcomeStore(tmp_path / 'outcomes.db')
    assert store.import_export(current) is False
    assert store.import_export(legacy) is False


def test_stale_scanner_file_recovers_through_tradier(harness, tmp_path):
    setups = tmp_path / 'setups'
    setups.mkdir()
    candles = tmp_path / 'candles'
    candles.mkdir()
    (candles / 'SPY.json').write_text(json.dumps({'format': 'scanner-candles-v1',
        'symbol': 'SPY', 'source': 'tradier_timesales_1min', 'feed': 'full_market',
        'last_bar_time': (RECEIPT - timedelta(minutes=10)).isoformat(), '1m': [], '5m': []}))
    harness.configure(shadow_setups_dir=str(setups))
    with TestClient(harness.server(tradier_source=source()).streamable_http_app()) as client:
        result = call(client, 'candles', {'symbol': 'SPY', 'interval': '1m'}, harness.token())['structuredContent']
    assert result['delivery'] == 'direct_refresh' and result['candles']
    assert not harness.requests


def test_tradier_credential_requires_private_regular_file(tmp_path):
    from cloud_mcp_check import read_credentials
    path = tmp_path / 'tradier-api-key'
    path.write_text('invented')
    path.chmod(0o600)
    assert read_credentials(str(tmp_path), ('tradier-api-key',)) == ('invented',)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        read_credentials(str(tmp_path), ('tradier-api-key',))


def test_tradier_daily_provenance_cannot_be_iex():
    packet = full_market_snapshot()
    packet['input_manifest'] = [m for m in packet['input_manifest'] if not m['group'].endswith('prior_daily_bar')]
    packet['input_manifest'].append({'group': 'indices.SPY.prior_daily_bar',
        'provider': 'Tradier', 'feed': 'iex', 'adjustment': 'provider_reported'})
    packet.pop('content_sha256')
    packet.pop('snapshot_id')
    packet['snapshot_id'] = 'mws_' + digest(packet)[:32]
    with pytest.raises(ValueError, match='Tradier source manifest'):
        validate_snapshot(seal(packet))


def test_cached_partial_minute_never_becomes_completed_without_refresh(monkeypatch):
    import tradier_stock_data as module
    stamp = [RECEIPT.replace(second=59)]
    elapsed = [10.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: elapsed[0])
    reads = []
    start = stamp[0].replace(second=0)
    def handler(request):
        reads.append(request)
        return httpx.Response(200, json={'series': {'data': [{'timestamp': start.timestamp(),
            'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 10}]}})
    provider = TradierStockData('invented', transport=httpx.MockTransport(handler), clock=lambda: stamp[0])
    assert provider.minutes('SPY', stamp[0].date()) == []
    stamp[0] += timedelta(seconds=2)
    assert provider.minutes('SPY', stamp[0].date()) == [] and len(reads) == 1
    elapsed[0] += 11
    assert provider.minutes('SPY', stamp[0].date()) and len(reads) == 2


def test_review_batches_more_than_eight_pending_tickers(harness):
    import copy
    from cloud_mcp_check_ledger import Ledger
    from tests.test_cloud_mcp_check import SUBJECT
    with TestClient(harness.server(tradier_source=source()).streamable_http_app()) as client:
        saved = call(client, 'pre_trade_check', IDEA, harness.token())['structuredContent']
    config = json.loads(harness.config_path.read_text())
    ledger = Ledger(config['ledger_file'])
    original = ledger.get(SUBJECT, saved['check_id'])
    symbols = ['AAPL', 'AMD', 'GOOG', 'IBM', 'META', 'MSFT', 'NVDA', 'TSLA']
    for index, symbol in enumerate(symbols):
        record = copy.deepcopy(original)
        record.update(check_id=f'chk_fixture_{index}', operation_id=f'batch-{index}', request_sha256=str(index))
        record['idea']['ticker'] = symbol
        ledger.insert(record)
    reads = []
    def handler(request):
        reads.append(request.url.params['symbol'])
        return httpx.Response(200, json={'series': {'data': []}})
    harness.configure(provider_feed='iex')
    with TestClient(harness.server(tradier_source=source(handler)).streamable_http_app()) as client:
        result = call(client, 'review_checks', {}, harness.token())['structuredContent']
    assert len(result['checks']) == 9
    assert set(reads) == set(symbols + ['SPY'])
