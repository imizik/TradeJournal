"""Recorded depth reader and the bridge's /depth endpoint; synthetic files only."""
import gzip
import json

from fastapi.testclient import TestClient

from scripts import depth_history as dh
from scripts import moomoo_lab_server as lab

TOKEN = "invented-loopback-token-00000000000000"
AUTH = {"Authorization": "Bearer " + TOKEN}
T0 = 1_791_820_800_000  # 2026-10-12 14:00 UTC, a weekday afternoon


def book(t, bids, asks, kind="arca", age=50):
    mpid = "ARCA" if kind == "arca" else "NSDQ"
    return {"t": "b", "rx": t + age, "k": kind, "books": [{"ex": "", "ts": t, "age": age,
            "b": [[p, v, 1, mpid] for p, v in bids], "a": [[p, v, 1, mpid] for p, v in asks]}]}


def ladder(mid, wall_bid=None, wall_ask=None):
    bids = [(round(mid - 0.01 * n, 2), 50) for n in range(1, 31)]
    asks = [(round(mid + 0.01 * n, 2), 50) for n in range(1, 31)]
    if wall_bid:
        bids = [(p, wall_bid[1] if p == wall_bid[0] else v) for p, v in bids]
    if wall_ask:
        asks = [(p, wall_ask[1] if p == wall_ask[0] else v) for p, v in asks]
    return bids, asks


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as file:
        file.write(gzip.compress("".join(json.dumps(line) + "\n" for line in lines).encode()))


def test_walls_need_size_presence_and_the_current_book(tmp_path):
    lines = []
    for n in range(90):  # 15 minutes of 10-second buckets
        t = T0 + n * 10_000
        # A 5,000-share bid at 99.90 throughout; a 3,000-share ask at 100.20 pulled for the last minute.
        bids, asks = ladder(100.0, (99.9, 5000), (100.2, 3000 if n < 84 else 40))
        lines.append(book(t, bids, asks))
    lines.append(book(T0, [(101.5, 90000)], [], age=5000))  # unusable clock: never counted
    write(tmp_path / "NVDA.jsonl.gz", lines)
    index = dh.DayIndex(tmp_path / "NVDA.jsonl.gz")
    index.refresh()
    walls = index.walls("arca")
    assert [(wall["price"], wall["pulled"]) for wall in walls["bids"]] == [(99.9, False)]
    assert walls["bids"][0]["since"] == T0 and walls["bids"][0]["size"] == 5000
    assert [(wall["price"], wall["pulled"]) for wall in walls["asks"]] == [(100.2, True)]
    assert index.walls("mpid") == {"bids": [], "asks": []}  # kinds never mix
    profile = index.profile("arca")
    assert profile["bids"][-1] == [99.99, 50] and profile["asks"][0] == [100.01, 50]


def test_a_level_price_traded_through_is_not_a_wall(tmp_path):
    lines = [book(T0 + n * 10_000, *ladder(100.0, (99.9, 5000))) for n in range(60)]
    lines += [book(T0 + (60 + n) * 10_000, *ladder(99.5)) for n in range(6)]  # price fell through 99.90
    write(tmp_path / "NVDA.jsonl.gz", lines)
    index = dh.DayIndex(tmp_path / "NVDA.jsonl.gz")
    index.refresh()
    assert all(wall["price"] != 99.9 for wall in index.walls("arca")["bids"])


def test_missing_side_adds_nothing_and_columns_merge_exactly(tmp_path):
    write(tmp_path / "NVDA.jsonl.gz", [book(T0, [(99.0, 100)], [(101.0, 10)]), book(T0 + 5_000, [(99.0, 300)], []),
                                       book(T0 + 10_000, [(99.0, 50)], [(101.0, 30)])])
    index = dh.DayIndex(tmp_path / "NVDA.jsonl.gz")
    index.refresh()
    first, second = index.columns("arca", 0, 10_000)
    assert first == [T0, 10_000, [99.0, 200.0, 101.0, 10.0], 1]  # ask mean over the one sample that had asks; one bid pair
    assert second[2] == [99.0, 50.0, 101.0, 30.0]
    assert index.columns("arca", 0, 30_000)[0][2] == [99.0, 150.0, 101.0, 20.0]


def test_incremental_read_waits_for_a_complete_member(tmp_path):
    path = tmp_path / "NVDA.jsonl.gz"
    write(path, [book(T0, [(99.0, 100)], [(101.0, 10)])])
    index = dh.DayIndex(path)
    index.refresh()
    member = gzip.compress((json.dumps(book(T0 + 10_000, [(99.0, 300)], [(101.0, 10)])) + "\n").encode())
    with path.open("ab") as file:
        file.write(member[:10])  # the recorder is mid-write
    index.refresh()
    assert len(index.buckets["arca"]) == 1
    with path.open("ab") as file:
        file.write(member[10:])
    index.refresh()
    assert len(index.buckets["arca"]) == 2


def test_concurrent_queries_never_double_count_the_file_offset(tmp_path):
    import threading
    path = tmp_path / "2026-10-12" / "NVDA.jsonl.gz"
    for n in range(40):
        write(path, [book(T0 + n * 10_000, *ladder(100.0))])
    history = dh.History(tmp_path)
    start = threading.Barrier(8)
    def query():
        start.wait()
        history.query("NVDA", "2026-10-12", "arca", 0, 10_000)
    threads = [threading.Thread(target=query) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    index = history.indexes[("NVDA", "2026-10-12")]
    assert index.offset == path.stat().st_size and len(index.buckets["arca"]) == 40
    write(path, [book(T0 + 400_000, *ladder(100.0))])
    assert history.query("NVDA", "2026-10-12", "arca", 0, 10_000)["last_ms"] == T0 + 400_000


def test_bridge_depth_endpoint_validates_and_reads_only_recorded_files(tmp_path):
    write(tmp_path / "2026-10-12" / "NVDA.jsonl.gz", [book(T0 + n * 10_000, *ladder(100.0, (99.9, 5000))) for n in range(30)])
    (tmp_path / "status.json").write_text(json.dumps({"state": "recording", "tickers": ["NVDA", "MU"], "last_book_ms": {"NVDA": T0 + 300_000}}))

    def loader():
        raise AssertionError("credentials must not be read")
    app = lab.create_app(token=TOKEN, loader=loader, depth_root=tmp_path, clock=lambda: (T0 + 310_000) / 1000)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        body = client.get("/depth?symbol=NVDA&kind=arca&minutes=10&bucket=30", headers=AUTH).json()
        assert body["recorded"] and body["recording"] and body["bucket_ms"] == 30_000
        assert body["walls"]["bids"][0]["price"] == 99.9 and body["profile"]["asks"][0] == [100.01, 50]
        assert client.get("/depth?symbol=MU", headers=AUTH).json() == {"symbol": "MU", "recorded": False, "watched": True}
        for query in ["symbol=nvda", "symbol=NVDA&kind=x", "symbol=NVDA&minutes=0", "symbol=NVDA&bucket=5", "symbol=NVDA&x=1", "symbol=../NVDA"]:
            assert client.get("/depth?" + query, headers=AUTH).status_code == 400
        assert client.get("/depth?symbol=NVDA").status_code == 403
