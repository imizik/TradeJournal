"""Offline depth recorder and uploader checks; no provider, R2 or credential access."""
import asyncio
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from scripts import depth_upload as up
from scripts import moomoo_depth_recorder as rec
from tests.test_moomoo_diagnostic import FakeSocket

NY = ZoneInfo("America/New_York")
KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def book(symbol, mpid="ARCA", bids=None, asks=None, source_ms=0):
    return {"type": "ORDER_BOOK", "symbol": symbol, "data": {"exchange_data_time_ms": source_ms, "exchange": "",
            "bid_list": [{"price": 100.01, "volume": 300, "order_count": 3, "mpid": mpid}] if bids is None else bids,
            "ask_list": [{"price": 100.02, "volume": 200, "mpid": mpid}] if asks is None else asks}}


def lines(path):
    with gzip.open(path, "rt") as file:
        return [json.loads(line) for line in file]


def test_watchlist_accepts_plain_tickers_only():
    assert rec.watchlist(None) == ["SPY", "MU", "NBIS", "SNDK", "NVDA"]
    assert rec.watchlist(" aapl ".upper() + ",BRK.B,AAPL") == ["AAPL", "BRK.B"]
    for raw in ["aapl", "US.AAPL", "SPXW240119C00450000", " , ", ",".join(f"A{chr(65 + i)}" for i in range(21))]:
        with pytest.raises(ValueError):
            rec.watchlist(raw)


def test_window_is_premarket_through_after_hours_on_weekdays():
    monday = datetime(2026, 10, 12, 3, 59, tzinfo=NY)
    assert rec.window(monday) is None
    assert rec.next_open(monday) == datetime(2026, 10, 12, 4, 0, tzinfo=NY)
    start, end = rec.window(monday + timedelta(minutes=1))
    assert (start.hour, end.hour) == (4, 20)
    assert rec.window(datetime(2026, 10, 12, 20, 0, tzinfo=NY)) is None
    assert rec.next_open(datetime(2026, 10, 16, 20, 0, tzinfo=NY)) == datetime(2026, 10, 19, 4, 0, tzinfo=NY)  # Friday close -> Monday
    assert rec.window(datetime(2026, 10, 17, 10, 0, tzinfo=NY)) is None  # Saturday


def test_book_line_keeps_sides_independent_and_allowlists_fields():
    line = rec.book_line(book("US.NVDA", asks=None, bids=[]), 1_000, None, "US.NVDA")
    assert line["k"] == "arca" and line["books"][0]["b"] == [] and line["books"][0]["a"] == [[100.02, 200, None, "ARCA"]]
    assert rec.book_line(book("US.AAPL"), 1_000, None, "US.NVDA") is None
    other = rec.book_line(book("US.NVDA", mpid="NSDQ"), 1_000, None, "US.NVDA")
    assert other["k"] == "mpid"


def test_trade_lines_keep_direction_and_drop_bad_prints():
    message = {"type": "TICKER", "symbol": "US.NVDA", "data": {"ticker_list": [
        {"price": 100.5, "volume": 10, "direction": "BUY", "time_ms": 5, "sequence": 7, "type": "NORMAL"},
        {"price": 100.5, "volume": 1, "direction": "DO-NOT-STORE", "type": "bad type!"},
        {"price": 0, "volume": 1}, "not a tick"]}}
    out = rec.trade_lines(message, 9, "US.NVDA")
    assert out == [{"t": "x", "ts": 5, "rx": 9, "p": 100.5, "v": 10, "d": "BUY", "q": 7, "y": "NORMAL"},
                   {"t": "x", "ts": None, "rx": 9, "p": 100.5, "v": 1, "d": None, "q": None, "y": None}]
    assert rec.trade_lines(message, 9, "US.AAPL") == []


def test_store_appends_readable_members_and_pauses_on_low_disk(tmp_path, monkeypatch):
    store = rec.Store(tmp_path)
    store.add("2026-10-12", "NVDA", {"a": 1})
    assert store.flush()
    store.add("2026-10-12", "NVDA", {"a": 2})
    assert store.flush()
    assert lines(tmp_path / "2026-10-12/NVDA.jsonl.gz") == [{"a": 1}, {"a": 2}]
    monkeypatch.setattr(rec, "MIN_FREE_BYTES", 10 ** 18)
    store.add("2026-10-12", "NVDA", {"a": 3})
    assert not store.flush() and not store.pending
    assert lines(tmp_path / "2026-10-12/NVDA.jsonl.gz") == [{"a": 1}, {"a": 2}]


def test_store_cuts_a_partial_member_before_appending(tmp_path):
    path = tmp_path / "2026-10-12" / "NVDA.jsonl.gz"
    store = rec.Store(tmp_path)
    store.add("2026-10-12", "NVDA", {"a": 1})
    store.flush()
    whole = path.read_bytes()
    partial = gzip.compress(b'{"a":2}\n' * 500)
    path.write_bytes(whole + partial[: len(partial) // 2])  # a crash in the middle of a flush
    restarted = rec.Store(tmp_path)
    restarted.add("2026-10-12", "NVDA", {"a": 3})
    restarted.flush()
    assert lines(path) == [{"a": 1}, {"a": 3}]


def test_prune_never_deletes_once_an_uploader_has_run(tmp_path):
    for day in ("2026-09-01", "2026-10-11"):
        (tmp_path / day).mkdir()
    rec.Store(tmp_path).prune(datetime(2026, 10, 12).date())
    assert not (tmp_path / "2026-09-01").exists() and (tmp_path / "2026-10-11").exists()
    (tmp_path / "2026-09-02").mkdir()
    (tmp_path / ".uploader").touch()
    rec.Store(tmp_path).prune(datetime(2026, 10, 12).date())
    assert (tmp_path / "2026-09-02").exists()


def test_unhashable_direction_is_dropped_not_fatal():
    message = {"type": "TICKER", "symbol": "US.NVDA", "data": {"ticker_list": [{"price": 1, "volume": 1, "direction": ["BUY"]}]}}
    assert rec.trade_lines(message, 1, "US.NVDA")[0]["d"] is None


def test_backoff_restarts_after_a_connection_that_recorded(tmp_path, monkeypatch):
    waits = []
    attempts = iter(["recording", "recording", "fail", "fail", "recording"])

    async def fake_window(appkey, key, tickers, until, store, status, connector):
        if next(attempts) == "recording":
            status["state"] = "recording"
        raise rec.diagnostic.DiagnosticError("dropped")

    async def fake_sleep(seconds):
        waits.append(seconds)
        if len(waits) == 5:
            raise asyncio.CancelledError

    monkeypatch.setattr(rec, "record_window", fake_window)
    monkeypatch.setattr(rec, "window", lambda now: (now, now + timedelta(hours=1)))
    monkeypatch.setattr(rec.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(rec.random, "uniform", lambda a, b: 0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(rec.run(["NVDA"], loader=lambda: ("fixture", KEY), root=tmp_path))
    assert waits == [15, 15, 30, 60, 15]  # doubles while failing, starts over after one that recorded


def test_record_window_snapshots_latest_book_per_kind_and_every_trade(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "SNAPSHOT_SECONDS", 0.2)
    monkeypatch.setattr(rec, "FLUSH_SECONDS", 0.2)
    monkeypatch.setattr(rec, "REFRESH_SECONDS", 0.3)

    class Socket(FakeSocket):
        async def send(self, raw):
            frame = json.loads(raw)
            if frame["action"] == "refresh":
                self.sent.append(frame)
                return await self.queue.put(json.dumps({"id": frame["id"], "session_id": "DO-NOT-ECHO"}))
            return await super().send(raw)

    async def scenario():
        socket = Socket()
        for n in range(5):  # five quick ARCA updates in one window: only the last is kept
            await socket.queue.put(json.dumps(book("US.NVDA", bids=[{"price": 100 + n / 100, "volume": n + 1, "mpid": "ARCA"}])))
        await socket.queue.put(json.dumps(book("US.NVDA", mpid="NSDQ")))
        await socket.queue.put(json.dumps({"type": "TICKER", "symbol": "US.MU", "data": {"ticker_list": [{"price": 90, "volume": 5, "direction": "SELL"}]}}))
        await socket.queue.put(json.dumps(book("US.TSLA")))  # not watched: ignored
        status = {"state": "", "last_book_ms": {}, "last_trade_ms": {}}
        until = datetime.now(timezone.utc) + timedelta(seconds=1)
        await rec.record_window("fixture", KEY, ["NVDA", "MU"], until, rec.Store(tmp_path), status, lambda *a, **k: socket)
        return socket, status

    socket, status = asyncio.run(scenario())
    subscribes = [frame for frame in socket.sent if frame["action"] == "subscribe"]
    assert subscribes == [{"id": "sub-order_book", "action": "subscribe", "order_book": ["US.NVDA", "US.MU"]},
                          {"id": "sub-ticker", "action": "subscribe", "ticker": ["US.NVDA", "US.MU"]}]
    assert any(frame["action"] == "refresh" for frame in socket.sent)
    assert socket.sent[-1]["action"] == "unsubscribe" and socket.close_code == 1000
    day = datetime.now(NY).date().isoformat()
    nvda = lines(tmp_path / day / "NVDA.jsonl.gz")
    assert sorted(line["k"] for line in nvda) == ["arca", "mpid"]
    assert next(line for line in nvda if line["k"] == "arca")["books"][0]["b"] == [[100.04, 5, None, "ARCA"]]
    assert lines(tmp_path / day / "MU.jsonl.gz")[0]["d"] == "SELL"
    assert not (tmp_path / day / "TSLA.jsonl.gz").exists()
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "recording"
    assert "DO-NOT-ECHO" not in (tmp_path / "status.json").read_text()


def test_record_window_raises_on_refused_subscription(tmp_path):
    async def scenario():
        socket = FakeSocket(subscribe_fail="sub-ticker")
        status = {"state": "", "last_book_ms": {}, "last_trade_ms": {}}
        with pytest.raises(rec.diagnostic.DiagnosticError):
            await rec.record_window("fixture", KEY, ["NVDA"], datetime.now(timezone.utc) + timedelta(seconds=5), rec.Store(tmp_path), status, lambda *a, **k: socket)
        return socket
    socket = asyncio.run(scenario())
    assert socket.sent[-1]["action"] == "unsubscribe" and socket.close_code == 1000


def test_sigv4_matches_aws_published_example():
    # AWS S3 SigV4 documentation example: GET Object with a Range header.
    headers = up.sign("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {"Range": "bytes=0-9"}, up.EMPTY_SHA256,
                      "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                      datetime(2013, 5, 24, tzinfo=timezone.utc), region="us-east-1")
    assert headers["authorization"].endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in headers["authorization"]


def test_config_requires_account_endpoint_and_scoped_key():
    good = {"TJ_DEPTH_R2_ENDPOINT": "https://abc123.r2.cloudflarestorage.com", "TJ_DEPTH_R2_BUCKET": "trade-journal-depth",
            "TJ_DEPTH_R2_ACCESS_KEY_ID": "id", "TJ_DEPTH_R2_SECRET_ACCESS_KEY": "secret"}
    assert up.config(good)["host"] == "abc123.r2.cloudflarestorage.com"
    for change in [{"TJ_DEPTH_R2_ENDPOINT": "https://abc123.r2.cloudflarestorage.com/trade-journal"},
                   {"TJ_DEPTH_R2_ENDPOINT": "http://abc123.r2.cloudflarestorage.com"}, {"TJ_DEPTH_R2_ENDPOINT": "https://evil.example"},
                   {"TJ_DEPTH_R2_BUCKET": "Bad_Bucket"}, {"TJ_DEPTH_R2_SECRET_ACCESS_KEY": ""}]:
        with pytest.raises(up.UploadError) as error:
            up.config({**good, **change})
        assert "secret" not in str(error.value)


def test_upload_confirms_size_marks_day_and_removes_only_confirmed_old_days(tmp_path):
    for day in ("2026-10-05", "2026-10-09", "2026-10-12"):
        (tmp_path / day).mkdir()
        (tmp_path / day / "NVDA.jsonl.gz").write_bytes(gzip.compress(day.encode()))
    stored = {}

    def handler(request):
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=id/")
        if request.method == "PUT":
            assert request.headers["x-amz-content-sha256"] == hashlib.sha256(request.content).hexdigest()
            stored[request.url.path] = request.content
            return httpx.Response(200)
        return httpx.Response(200, headers={"content-length": str(len(stored[request.url.path]))})

    settings = {"host": "abc.r2.cloudflarestorage.com", "bucket": "trade-journal-depth", "key_id": "id", "secret": "s"}
    client = httpx.Client(transport=httpx.MockTransport(handler))
    # 2026-10-12 at 19:00 New York: today is still recording and is not touched.
    result = up.run(tmp_path, settings, client, datetime(2026, 10, 12, 19, 0, tzinfo=NY))
    assert sorted(stored) == ["/trade-journal-depth/depth/v1/NVDA/2026/2026-10-05.jsonl.gz", "/trade-journal-depth/depth/v1/NVDA/2026/2026-10-09.jsonl.gz"]
    assert result == {"uploaded": 2, "days": 2, "removed": 1} and (tmp_path / ".uploader").exists()
    assert not (tmp_path / "2026-10-05").exists() and (tmp_path / "2026-10-09/.uploaded").exists()
    assert not (tmp_path / "2026-10-12/.uploaded").exists()
    up.run(tmp_path, settings, client, datetime(2026, 10, 12, 20, 30, tzinfo=NY))
    assert "/trade-journal-depth/depth/v1/NVDA/2026/2026-10-12.jsonl.gz" in stored


def test_upload_that_does_not_verify_keeps_the_day(tmp_path):
    (tmp_path / "2026-10-01").mkdir()
    (tmp_path / "2026-10-01/NVDA.jsonl.gz").write_bytes(b"x")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-length": "999"})))
    with pytest.raises(up.UploadError):
        up.run(tmp_path, {"host": "a.r2.cloudflarestorage.com", "bucket": "trade-journal-depth", "key_id": "i", "secret": "s"},
               client, datetime(2026, 10, 12, 21, 0, tzinfo=NY))
    assert (tmp_path / "2026-10-01/NVDA.jsonl.gz").exists() and not (tmp_path / "2026-10-01/.uploaded").exists()
