"""Read the depth recorder's day files into heatmap columns, liquidity levels and a profile.

Used by the loopback bridge (scripts.moomoo_lab_server) for recorded tickers.
Pure aside from reading files: no provider, journal or R2 access. Each day file
is read incrementally, one complete gzip member at a time, so polling costs only
what was appended since the last read. Books are folded into 10-second base
buckets per book kind (sums and sample counts, so wider buckets merge exactly);
nothing is carried forward and a missing side adds nothing.

A liquidity level ("wall") is a price whose displayed size in the recent window
was large compared with that side's typical level and present most of the time.
These are provider-displayed sizes from one book kind, not consolidated or
executable liquidity, and a wall is not a prediction.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import json
from pathlib import Path
from statistics import median
import threading
import zlib

BASE_MS = 10_000
MAX_AGE_MS = 2_000
KINDS = ("arca", "mpid")
# Wall rules, per side over the last WALL_WINDOW_MS: the price's mean size is at least
# WALL_SHARE of the side's mean total displayed size and WALL_MULTIPLE x its median
# level; it showed in WALL_PRESENCE of the buckets in which the side's displayed
# range covered that price (a level outside the visible book cannot show); and the
# newest bucket that covers it still shows at least half that bar (else "pulled").
WALL_WINDOW_MS = 15 * 60_000
WALL_SHARE = 0.08
WALL_MULTIPLE = 4.0
WALL_PRESENCE = 0.6
WALL_PER_SIDE = 3
# A wall that qualified recently but is gone from the latest bucket is "pulled" for this long.
PULLED_MS = 3 * 60_000


@dataclass
class Bucket:
    samples: list[int] = field(default_factory=lambda: [0, 0])
    sides: tuple[dict[int, float], dict[int, float]] = field(default_factory=lambda: ({}, {}))


def key(price: float) -> int:
    return round(price * 10_000)


class DayIndex:
    """One ticker-day file, folded incrementally."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.buckets: dict[str, OrderedDict[int, Bucket]] = {kind: OrderedDict() for kind in KINDS}
        self.latest: dict[str, dict] = {}
        self.last_ms = 0

    def refresh(self) -> None:
        try:
            with self.path.open("rb") as file:
                file.seek(self.offset)
                data = file.read()
        except FileNotFoundError:
            return
        used = 0
        while used < len(data):
            reader = zlib.decompressobj(31)
            try:
                text = reader.decompress(data[used:])
            except zlib.error:
                break
            if not reader.eof:
                break  # the recorder is mid-write; read this member next time
            used = len(data) - len(reader.unused_data)
            for line in text.decode().splitlines():
                self.add(json.loads(line))
        self.offset += used

    def add(self, line: dict) -> None:
        if line.get("t") != "b" or line.get("k") not in KINDS:
            return
        for book in line.get("books", []):
            at, age = book.get("ts"), book.get("age")
            if not at or age is None or not 0 <= age <= MAX_AGE_MS:
                continue  # never placed at a guessed time
            start = at - at % BASE_MS
            buckets = self.buckets[line["k"]]
            bucket = buckets.get(start)
            if bucket is None:
                bucket = buckets[start] = Bucket()
            for side, levels in enumerate((book.get("b", []), book.get("a", []))):
                if not levels:
                    continue
                bucket.samples[side] += 1
                sizes = bucket.sides[side]
                for price, volume, *_ in levels:
                    sizes[key(price)] = sizes.get(key(price), 0.0) + volume
            self.latest[line["k"]] = {"t": at, "b": book.get("b", []), "a": book.get("a", [])}
            self.last_ms = max(self.last_ms, at)

    def columns(self, kind: str, since_ms: int, width_ms: int) -> list[list]:
        """[[start_ms, width_ms, [price, mean size, ...], bid pairs], ...] merged into width_ms buckets.

        Bids come first in the cells; the fourth field counts them so the heatmap can color the sides.
        """
        merged: OrderedDict[int, Bucket] = OrderedDict()
        for start, bucket in self.buckets[kind].items():
            if start < since_ms:
                continue
            wide = start - start % width_ms
            target = merged.get(wide)
            if target is None:
                target = merged[wide] = Bucket()
            for side in (0, 1):
                target.samples[side] += bucket.samples[side]
                for price, total in bucket.sides[side].items():
                    target.sides[side][price] = target.sides[side].get(price, 0.0) + total
        out = []
        for start, bucket in merged.items():
            cells = []
            bids = 0
            for side in (0, 1):
                if bucket.samples[side]:
                    for price, total in bucket.sides[side].items():
                        cells += [price / 10_000, round(total / bucket.samples[side], 2)]
                if side == 0:
                    bids = len(cells) // 2
            out.append([start, width_ms, cells, bids])
        return out

    def profile(self, kind: str) -> dict | None:
        """The latest book of `kind`, sizes summed per price; sides as received (missing stays empty)."""
        book = self.latest.get(kind)
        if not book:
            return None
        def side(levels):
            sizes: dict[int, float] = {}
            for price, volume, *_ in levels:
                sizes[key(price)] = sizes.get(key(price), 0.0) + volume
            return [[price / 10_000, size] for price, size in sorted(sizes.items())]
        return {"t": book["t"], "bids": side(book["b"]), "asks": side(book["a"])}

    def walls(self, kind: str) -> dict:
        """Up to WALL_PER_SIDE current walls per side, plus recently pulled ones."""
        buckets = self.buckets[kind]
        if not buckets:
            return {"bids": [], "asks": []}
        newest = next(reversed(buckets))
        window = [(start, bucket) for start, bucket in buckets.items() if start > newest - WALL_WINDOW_MS]
        result = {}
        for side, name in ((0, "bids"), (1, "asks")):
            present = [(start, bucket) for start, bucket in window if bucket.samples[side] and bucket.sides[side]]
            if not present:
                result[name] = []
                continue
            # Per bucket: mean size per price and the displayed price range.
            frames = [(start, {price: total / bucket.samples[side] for price, total in bucket.sides[side].items()},
                       min(bucket.sides[side]), max(bucket.sides[side])) for start, bucket in present]
            sizes = sorted(size for _, means, _, _ in frames for size in means.values())
            depth = sum(sum(means.values()) for _, means, _, _ in frames) / len(frames)
            bar = max(WALL_SHARE * depth, WALL_MULTIPLE * (median(sizes) or 1.0))
            latest_start = frames[-1][0]
            # The current book bounds what can be a wall now: the latest update's side range.
            current = [key(level[0]) for level in self.latest.get(kind, {}).get("ba"[side], [])]
            if not current:
                result[name] = []
                continue
            now_low, now_high = min(current), max(current)
            walls = []
            for price in {price for _, means, _, _ in frames for price in means}:
                if not now_low <= price <= now_high:
                    continue  # outside the current book: traded through or out of view, not a wall now
                covered = [(start, means.get(price, 0.0)) for start, means, low, high in frames if low <= price <= high]
                shown = [size for _, size in covered if size > 0]
                if not covered or len(shown) / len(covered) < WALL_PRESENCE:
                    continue
                mean = sum(shown) / len(shown)
                if mean < bar:
                    continue
                large = [(start, size) for start, size in covered if size >= bar / 2]
                if not large:
                    continue
                last_seen = large[-1][0]
                since = last_seen  # rested at a large size without a gap, newest first
                for start, size in reversed(covered):
                    if size < bar / 2:
                        break
                    since = start
                pulled = last_seen < latest_start  # still inside the book but no longer large
                if pulled and latest_start - last_seen > PULLED_MS:
                    continue
                walls.append({"price": price / 10_000, "size": round(large[-1][1], 2), "mean": round(mean, 2),
                              "since": since, "last_seen": last_seen + BASE_MS, "pulled": pulled,
                              "share": round(mean / depth, 3)})
            walls.sort(key=lambda wall: (wall["pulled"], -wall["mean"]))
            result[name] = walls[:WALL_PER_SIDE]
        return result


class History:
    """A few day indexes, most recently used kept, read from the recorder's state directory.

    One lock serializes reading and querying: requests run in worker threads, and
    two refreshes of one index at once would double-count its file offset.
    """

    def __init__(self, root: Path, keep: int = 6):
        self.root = root
        self.keep = keep
        self.indexes: OrderedDict[tuple[str, str], DayIndex] = OrderedDict()
        self.lock = threading.Lock()

    def query(self, ticker: str, day: str, kind: str, since_ms: int, width_ms: int) -> dict | None:
        """Refresh and read one ticker-day under the lock; None when nothing is recorded."""
        with self.lock:
            index = self.index(ticker, day)
            if index is None:
                return None
            return {"last_ms": index.last_ms, "columns": index.columns(kind, since_ms, width_ms),
                    "walls": index.walls(kind), "profile": index.profile(kind)}

    def index(self, ticker: str, day: str) -> DayIndex | None:
        path = self.root / day / f"{ticker}.jsonl.gz"
        if not path.is_file():
            return None
        found = self.indexes.pop((ticker, day), None) or DayIndex(path)
        self.indexes[(ticker, day)] = found
        while len(self.indexes) > self.keep:
            self.indexes.popitem(last=False)
        found.refresh()
        return found

    def status(self) -> dict:
        try:
            return json.loads((self.root / "status.json").read_text())
        except (OSError, ValueError):
            return {}
