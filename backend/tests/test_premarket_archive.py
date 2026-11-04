"""Synthetic market and API fixtures. No remote services."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.engine import premarket_archive as arch
from app.engine import premarket_archive_job as job
from app.routers import premarket_archive as route
from tests.test_browser_access import boundary as boundary, signin

DAY, PRIOR = date(2026, 11, 2), date(2026, 10, 30)
CUT = arch.at(DAY, 9)


def bar(when, close, size, vw):
    return {"t": when.isoformat(), "c": close, "v": size, "vw": vw}


class FixtureMarket:
    def __init__(self):
        self.symbols = ["GAIN", "LOSS", "CHEAP", "SMALL", "IPO"]
        self.calls = []

    def splits(self, day):
        return {"LOSS": Decimal(2)}

    amounts = {"GAIN": (8, 150_000, 4), "LOSS": (2, 300_000, 2), "CHEAP": (1.99, 500_000, 2),
               "SMALL": (8, 149_999, 4), "IPO": (3, 200_000, 3)}

    def snapshots(self, symbols):
        return {s: {"minuteBar": bar(CUT - timedelta(minutes=1), *self.amounts[s]),
                    "latestTrade": {"p": 100, "t": (CUT + timedelta(seconds=3)).isoformat()}}
                for s in symbols}

    def bars(self, group, timeframe, start, end, asof):
        self.calls.append((set(group), timeframe, start, end, asof))
        for symbol in group:
            if timeframe == "1Day":
                if symbol != "IPO":
                    yield symbol, [{"t": arch.at(PRIOR, 0).isoformat(), "c": 4}]
                continue
            rows = [bar(arch.at(DAY, 4), 4, 100_000, 4), bar(CUT - timedelta(minutes=1), *self.amounts[symbol])]
            yield symbol, [row for row in rows if start <= arch.timestamp(row) <= end]

    def warmup(self):
        return arch.inputs(self, DAY, PRIOR, self.symbols, CUT - timedelta(minutes=16))


def test_snapshot_and_reconstruction_agree_on_boundaries_and_split(tmp_path):
    m = FixtureMarket()
    historical = arch.reconstruct(m, DAY, PRIOR, m.symbols)
    live = job.capture(DAY, m.symbols, *m.warmup(), m, tmp_path, clock=lambda: CUT)
    assert historical["source"] == "reconstructed-sip" and live["source"] == "contemporaneous"
    assert live["gainers"] == historical["gainers"] == [
        dict(symbol="GAIN", price=8, prior_regular_close=4, volume=250_000, dollar_volume=1_000_000, pct_change=100)]
    assert live["losers"] == historical["losers"] == [
        dict(symbol="LOSS", price=2, prior_regular_close=8, volume=400_000, dollar_volume=1_000_000, pct_change=-75)]
    assert live["missing_prior_close"] == 1 and live["universe_size"] == 5
    assert [(start, end, asof) for _, frame, start, end, asof in m.calls if frame == "1Min"] == [
        (arch.at(DAY, 4), CUT - timedelta(minutes=1), DAY),
        (arch.at(DAY, 4), CUT - timedelta(minutes=16), DAY),
        (CUT - timedelta(minutes=15), CUT - timedelta(minutes=1), DAY)]
    assert CUT.utcoffset() != arch.at(PRIOR, 9).utcoffset()
    assert arch.save(tmp_path, DAY, historical) == live


def test_no_late_partial_or_failed_snapshot(tmp_path):
    m = FixtureMarket()
    assert job.capture(DAY, m.symbols, *m.warmup(), m, tmp_path, lambda: CUT + timedelta(minutes=1)) is None
    for instants in ([CUT, CUT + timedelta(minutes=1), CUT + timedelta(minutes=1)],
                     [CUT, CUT, CUT + timedelta(minutes=1)]):
        times = iter(instants)
        with pytest.raises(ValueError, match="expired"):
            job.capture(DAY, m.symbols, *m.warmup(), m, tmp_path, lambda: next(times))
    m.snapshots = lambda symbols: {}
    with pytest.raises(ValueError, match="does not confirm"):
        job.capture(DAY, m.symbols, *m.warmup(), m, tmp_path, lambda: CUT)
    assert list(tmp_path.iterdir()) == []


def test_write_once_concurrent_and_read_only_route(tmp_path, monkeypatch):
    with ThreadPoolExecutor(max_workers=6) as pool:
        saved = list(pool.map(lambda n: arch.save(tmp_path, DAY, {"winner": n}), range(12)))
    assert all(row == saved[0] for row in saved)
    assert len(list(tmp_path.iterdir())) == 1
    monkeypatch.setattr(route, "ROOT", tmp_path)
    api = FastAPI()
    api.include_router(route.router)
    client = TestClient(api)
    assert client.get(f"/premarket/archive/{DAY}").json() == saved[0]
    assert client.get(f"/premarket/archive/{PRIOR}").status_code == 404
    assert client.get("/premarket/archive/nonsense").status_code == 422
    assert client.post(f"/premarket/archive/{DAY}").status_code == 405


def test_market_pages_keep_date_feed_and_credential_origin(monkeypatch):
    monkeypatch.setattr(arch, "BATCH", 1)
    requests = []
    def respond(request):
        url = request.url
        requests.append(url)
        p = url.params
        if url.host == "api.polygon.io":
            assert "APCA-API-SECRET-KEY" not in request.headers
            symbol = "DELISTED" if p.get("type") == "CS" else "ETF" if p.get("type") == "ETF" else "SECOND"
            data = {"status": "OK", "results": [dict(ticker=symbol, type="ETF" if symbol == "ETF" else "CS",
                                                   market="stocks", active=True, locale="us")]}
            if "cursor" not in p:
                assert p["date"] == DAY.isoformat() and p["active"] == "true"
            if symbol == "DELISTED":
                data["next_url"] = "https://untrusted.invalid/ignored?cursor=second"
        elif url.path.endswith("snapshots"):
            assert "Authorization" not in request.headers and p["feed"] == "sip"
            data = {p["symbols"]: {"minuteBar": None}}
        else:
            assert "Authorization" not in request.headers and p["adjustment"] == "raw" and p["asof"] == DAY.isoformat()
            data = {"bars": {"SECOND": []}, "next_page_token": None if "page_token" in p else "two"}
        return httpx.Response(200, json=data)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        m = arch.Market(client, dict(POLYGON_API_KEY="p", ALPACA_API_KEY="a", ALPACA_API_SECRET="s"))
        symbols = m.symbols(DAY)
        assert symbols == ["DELISTED", "ETF", "SECOND"]
        assert sorted(m.snapshots(symbols)) == symbols
        assert len(list(m.bars(["SECOND"], "1Min", arch.at(DAY, 4), CUT-timedelta(minutes=1), DAY))) == 2
    assert len(requests) == 8


def test_baseline_exports_scorecard_shape_and_rejects_short_sides():
    record = dict(feed="sip", source="reconstructed-sip", whole_market=True, as_of=CUT.isoformat(),
                  ranking_basis="pct_vs_prior_regular_close")
    sides = {side: [{"symbol": prefix + chr(65+i)} for i in range(25)]
             for side, prefix in (("gainers", "G"), ("losers", "L"))}
    out = arch.baseline(record | sides)
    assert out == record | {side: [r["symbol"] for r in rows[:10]] for side, rows in sides.items()}
    with pytest.raises(ValueError, match="Fewer than ten"):
        arch.baseline(record | sides | {"losers": []})


def test_refuses_later_or_duplicate_minutes():
    rows = [bar(CUT, 4, 2, 4)]
    m = SimpleNamespace(bars=lambda *args: [("X", rows)])
    with pytest.raises(ValueError, match="outside"):
        arch.read_minutes(m, ["X"], arch.at(DAY, 4), CUT - timedelta(minutes=1), {})
    rows[:] = [bar(arch.at(DAY, 8), 4, 2, 4)] * 2
    with pytest.raises(ValueError, match="unordered"):
        arch.read_minutes(m, ["X"], arch.at(DAY, 4), CUT - timedelta(minutes=1), {})


def test_disabled_by_default_and_in_trial(monkeypatch):
    from app.main import _maybe_start_premarket_archive
    monkeypatch.setitem(sys.modules, "app.engine.premarket_archive_job", None)
    monkeypatch.delenv("PREMARKET_ARCHIVE_ENABLED", raising=False)
    assert _maybe_start_premarket_archive() is None
    monkeypatch.setenv("PREMARKET_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert _maybe_start_premarket_archive() is None


def test_prepare_only_on_confirmed_exchange_session(monkeypatch):
    class HolidayMarket:
        def __init__(self, *args):
            pass
        def calendar(self, start, end):
            return [PRIOR]
        def symbols(self, day):
            pytest.fail("Must not fetch a holiday universe")
    monkeypatch.setattr(job, "Market", HolidayMarket)
    assert job.prepare(DAY) is None


def test_snapshot_minute_supplies_price_only_inside_matching_cutoff():
    when = CUT - timedelta(minutes=1)
    totals = {"UP": arch.MinuteTotal(when, Decimal("11"), 100_000, Decimal("10"), 100_000, Decimal("1000000"))}
    matching = {"UP": {"minuteBar": bar(when, 11, 100_000, 10)}}
    assert arch.rank_inputs(DAY, ["UP"], {"UP": Decimal("9")}, totals, matching)["gainers"][0]["price"] == 11
    for stale_or_late in (when - timedelta(minutes=1), CUT):
        matching["UP"]["minuteBar"] = bar(stale_or_late, 12, 100_000, 10)
        with pytest.raises(ValueError, match="does not confirm|outside the checkpoint"):
            arch.rank_inputs(DAY, ["UP"], {"UP": Decimal("9")}, totals, matching)


@pytest.mark.parametrize("missing,offset,size,vwap,price", [
    (True, 0, 100_000, 11, 11),     # Snapshot-only $1.1M.
    (False, -1, 2_000, 10, 10),     # A new $20k minute after $990k.
    (False, 0, 100_000, 10, 10),    # Same minute, corrected volume.
    (False, 0, 99_000, 11, 10),     # Same volume, corrected VWAP.
    (False, 0, 99_000, 10, 12),     # Same volume and VWAP, corrected close.
])
def test_conflicting_snapshot_before_floor_filter_withholds_rank(missing, offset, size, vwap, price):
    when = CUT - timedelta(minutes=1)
    totals = {"UP": arch.MinuteTotal(when, Decimal(12), 100_000, Decimal(12), 100_000, Decimal(1_200_000))}
    if not missing:
        totals["SMALL"] = arch.MinuteTotal(when + timedelta(minutes=offset), Decimal(10), 99_000,
                                           Decimal(10), 99_000, Decimal(990_000))
    snaps = {"UP": {"minuteBar": bar(when, 12, 100_000, 12)},
             "SMALL": {"minuteBar": bar(when, price, size, vwap)}}
    with pytest.raises(ValueError, match="does not confirm"):
        arch.rank_inputs(DAY, ["UP", "SMALL"], {"UP": Decimal(10), "SMALL": Decimal(5)}, totals, snaps)


def test_assistant_refused_and_owner_reads_frozen_day(boundary, tmp_path, monkeypatch):
    monkeypatch.setattr(route, "ROOT", tmp_path)
    arch.save(tmp_path, DAY, {"fixture": True})
    path = f"/premarket/archive/{DAY}"
    assert boundary.owner.get(path).json() == {"fixture": True}
    assert signin(boundary).status_code == 200
    assert boundary.public.get(path).status_code == 403
