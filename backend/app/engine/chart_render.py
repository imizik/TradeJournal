"""A small chart picture for a phone ping: minute bars plus a few labelled marks, as PNG bytes.

Pure and deterministic: it takes data and returns bytes, with no network, clock or font file. It draws with
numpy into a palette image and encodes the PNG with zlib, so it needs no image library; text is a built-in
5x7 pixel font drawn large, upper case, which reads well on a lock screen at thumbnail size.

A ``Chart`` is one of three pictures:

- **bars** (``bars``): candles for up to ``CANDLE_LIMIT`` bars, a close line beyond that, plotted by bar order
  (gaps between sessions close up). ``levels`` are horizontal lines labelled in the right gutter
  (invalidation, trigger, a reference price), ``marks`` are points at a time and price (a stock fill, the
  latest price) and ``times`` are vertical lines at a time (an option's entry or peak, a time stop).
- **series** (``series``): lines of percent change over time, each labelled at its end, e.g. a stock
  against SPY over a Radar event's window.
- **rows** (``rows``): horizontal bars, one per line, e.g. open positions by days to expiry.

``render`` is cached by a content hash, so a ping's retries reuse its picture. ``layout`` returns where
everything was placed, for tests and for checking that nothing fell off the picture.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import struct
import zlib

import numpy as np

from app.engine.chart_math import ET

WIDTH, HEIGHT = 720, 360
CANDLE_LIMIT = 180
CACHE_SIZE = 64

# The app's dark theme (frontend/app/globals.css and the chart's candle colours).
PALETTE = {
    "bg": (18, 21, 28), "grid": (37, 43, 55), "text": (226, 230, 235), "muted": (125, 139, 160),
    "up": (43, 201, 164), "down": (238, 97, 122), "amber": (245, 176, 65), "blue": (106, 167, 232),
    "violet": (178, 140, 240), "panel": (24, 28, 37),
}
NAMES = tuple(PALETTE)
INDEX = {name: i for i, name in enumerate(NAMES)}
TONES = frozenset(NAMES) - {"bg", "grid", "panel"}

# 5x7 glyphs, rows top to bottom; lower case is drawn as upper case and anything else as "?".
_GLYPHS = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 10001 01010 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
    ",": "00000 00000 00000 00000 01100 00100 01000", ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000", "+": "00000 00100 00100 11111 00100 00100 00000",
    "%": "11000 11001 00010 00100 01000 10011 00011", "/": "00000 00001 00010 00100 01000 10000 00000",
    "(": "00010 00100 01000 01000 01000 00100 00010", ")": "01000 00100 00010 00010 00010 00100 01000",
    "$": "00100 01111 10100 01110 00101 11110 00100", "'": "01100 00100 01000 00000 00000 00000 00000",
    "?": "01110 10001 00001 00010 00100 00000 00100", "!": "00100 00100 00100 00100 00100 00000 00100",
    "#": "01010 01010 11111 01010 11111 01010 01010", "&": "01100 10010 10100 01000 10101 10010 01101",
    "<": "00010 00100 01000 10000 01000 00100 00010", ">": "01000 00100 00010 00001 00010 00100 01000",
    "=": "00000 00000 11111 00000 11111 00000 00000", "*": "00000 00100 10101 01110 10101 00100 00000",
    "_": "00000 00000 00000 00000 00000 00000 11111", "·": "00000 00000 00000 01100 01100 00000 00000",
    "→": "00000 00100 00010 11111 00010 00100 00000", "↑": "00100 01110 10101 00100 00100 00100 00100",
    "↓": "00100 00100 00100 00100 10101 01110 00100",
}
_SAME = {"−": "-", "–": "-", "—": "-", "×": "X", "…": ".", "’": "'", "‘": "'"}
_FONT = {ch: np.array([[c == "1" for c in row] for row in rows.split()], dtype=bool) for ch, rows in _GLYPHS.items()}


@dataclass(frozen=True)
class Level:
    price: float
    label: str  # short, e.g. "INV 101.50"
    tone: str = "muted"
    dashed: bool = True


@dataclass(frozen=True)
class Mark:
    time: int  # epoch seconds
    price: float
    label: str = ""
    tone: str = "text"


@dataclass(frozen=True)
class Time:
    time: int  # epoch seconds
    label: str  # e.g. "ENTRY", "OUT 15:30"
    tone: str = "muted"


@dataclass(frozen=True)
class Series:
    label: str  # e.g. "LAD"
    points: tuple[tuple[int, float], ...]  # (epoch seconds, percent)
    tone: str = "blue"


@dataclass(frozen=True)
class Row:
    label: str  # e.g. "NBIS 100C"
    value: str  # e.g. "3D"
    fraction: float  # bar length, 0..1
    tone: str = "blue"


@dataclass(frozen=True)
class Chart:
    title: str
    note: str = ""  # right of the title, smaller, e.g. "NOW +5%"
    bars: tuple[dict, ...] = ()  # {"time", "open", "high", "low", "close"}
    levels: tuple[Level, ...] = ()
    marks: tuple[Mark, ...] = ()
    times: tuple[Time, ...] = ()
    series: tuple[Series, ...] = ()
    rows: tuple[Row, ...] = ()
    empty: str = "NO CHART DATA"  # said in the plot when there is nothing to draw

    def key(self) -> str:
        data = asdict(self)
        data["bars"] = [[b.get("time"), b.get("open"), b.get("high"), b.get("low"), b.get("close")] for b in self.bars]
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


_cache: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()


def render(chart: Chart) -> bytes:
    """The chart as PNG bytes; the same chart returns the same bytes (from the cache after the first time)."""
    return _drawn(chart)[0]


def layout(chart: Chart) -> dict:
    """Where the picture placed things: ``plot`` (x0, y0, x1, y1), ``mode``, and each label's box and colour."""
    return _drawn(chart)[1]


def _drawn(chart: Chart) -> tuple[bytes, dict]:
    key = chart.key()
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
        return hit
    canvas = _Canvas()
    placed = _draw(canvas, chart)
    result = (_png(canvas.pixels), placed)
    _cache[key] = result
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result


# ------------------------------------------------------------------ drawing


class _Canvas:
    def __init__(self):
        self.pixels = np.full((HEIGHT, WIDTH), INDEX["bg"], dtype=np.uint8)
        self.labels: list[dict] = []

    def rect(self, x0: float, y0: float, x1: float, y1: float, tone: str) -> None:
        a, b = sorted((int(round(x0)), int(round(x1))))
        c, d = sorted((int(round(y0)), int(round(y1))))
        a, b, c, d = max(a, 0), min(b, WIDTH - 1), max(c, 0), min(d, HEIGHT - 1)
        if a <= b and c <= d:
            self.pixels[c:d + 1, a:b + 1] = INDEX[tone]

    def hline(self, x0: float, x1: float, y: float, tone: str, width: int = 2, dashed: bool = False) -> None:
        if not dashed:
            self.rect(x0, y - width // 2, x1, y - width // 2 + width - 1, tone)
            return
        x = int(x0)
        while x < x1:
            self.rect(x, y - width // 2, min(x + 9, x1), y - width // 2 + width - 1, tone)
            x += 16

    def vline(self, x: float, y0: float, y1: float, tone: str, width: int = 2, dashed: bool = False) -> None:
        if not dashed:
            self.rect(x - width // 2, y0, x - width // 2 + width - 1, y1, tone)
            return
        y = int(y0)
        while y < y1:
            self.rect(x - width // 2, y, x - width // 2 + width - 1, min(y + 7, y1), tone)
            y += 12

    def polyline(self, points: list[tuple[float, float]], tone: str, width: int = 3) -> None:
        if not points:
            return
        xs, ys = [], []
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
            t = np.linspace(0.0, 1.0, steps + 1)
            xs.append(x0 + (x1 - x0) * t)
            ys.append(y0 + (y1 - y0) * t)
        if not xs:
            xs, ys = [np.array([points[0][0]])], [np.array([points[0][1]])]
        px, py = np.rint(np.concatenate(xs)).astype(int), np.rint(np.concatenate(ys)).astype(int)
        half = width // 2
        for dx in range(-half, width - half):
            for dy in range(-half, width - half):
                x, y = px + dx, py + dy
                keep = (x >= 0) & (x < WIDTH) & (y >= 0) & (y < HEIGHT)
                self.pixels[y[keep], x[keep]] = INDEX[tone]

    def dot(self, x: float, y: float, radius: int, tone: str) -> None:
        yy, xx = np.ogrid[:HEIGHT, :WIDTH]
        self.pixels[(xx - x) ** 2 + (yy - y) ** 2 <= radius * radius] = INDEX[tone]

    def text(self, x: float, y: float, text: str, tone: str, scale: int = 2, *, kind: str = "text", backdrop: bool = False) -> dict:
        """Draw ``text`` with its top-left at (x, y); returns the label's placed box."""
        text = "".join(_SAME.get(ch, ch) for ch in text.upper())
        width, height = text_width(text, scale), 7 * scale
        x, y = int(round(x)), int(round(y))
        if backdrop:
            self.rect(x - 3, y - 3, x + width + 2, y + height + 2, "bg")
        for i, ch in enumerate(text):
            glyph = _FONT.get(ch, _FONT["?"])
            block = np.kron(glyph, np.ones((scale, scale), dtype=bool))
            gx = x + i * 6 * scale
            y0, y1, x0, x1 = max(y, 0), min(y + 7 * scale, HEIGHT), max(gx, 0), min(gx + 5 * scale, WIDTH)
            if y0 >= y1 or x0 >= x1:
                continue
            region = self.pixels[y0:y1, x0:x1]
            region[block[y0 - y:y1 - y, x0 - gx:x1 - gx]] = INDEX[tone]
        box = {"kind": kind, "text": text, "tone": tone, "box": (x, y, x + width, y + height)}
        self.labels.append(box)
        return box


def text_width(text: str, scale: int) -> int:
    return max(0, len(text) * 6 * scale - scale)


def fit(text: str, scale: int, room: int) -> str:
    """``text`` cut with ".." so it fits ``room`` pixels."""
    text = "".join(_SAME.get(ch, ch) for ch in text.upper())
    if text_width(text, scale) <= room:
        return text
    keep = max(0, (room + scale) // (6 * scale) - 2)
    return text[:keep].rstrip() + ".."


TOP, BOTTOM, LEFT = 50, HEIGHT - 30, 12
GUTTER = 168  # right of the plot: the level and series labels
PLOT = (LEFT, TOP, WIDTH - GUTTER, BOTTOM)


def _draw(canvas: _Canvas, chart: Chart) -> dict:
    x0, y0, x1, y1 = PLOT
    note = fit(chart.note, 2, 300) if chart.note else ""
    note_w = text_width(note, 2)
    room = WIDTH - 2 * LEFT - (note_w + 16 if note else 0)
    title_scale = 3 if text_width(fit(chart.title, 3, room), 3) == text_width(chart.title, 3) else 2
    title = fit(chart.title, title_scale, room)
    canvas.text(LEFT, 14 if title_scale == 3 else 18, title, "text", title_scale, kind="title")
    if note:
        canvas.text(WIDTH - LEFT - note_w, 18, note, "muted", 2, kind="note")
    canvas.hline(0, WIDTH - 1, 44, "grid", 1)
    if chart.rows:
        mode = "rows"
        _rows(canvas, chart.rows)
    elif chart.series and any(s.points for s in chart.series):
        mode = "series"
        _series(canvas, chart)
    elif chart.bars:
        mode = "candles" if len(chart.bars) <= CANDLE_LIMIT else "line"
        _bars(canvas, chart, mode)
    else:
        mode = "empty"
        msg = fit(chart.empty, 3, x1 - x0)
        canvas.text((x0 + x1 - text_width(msg, 3)) / 2, (y0 + y1) / 2 - 10, msg, "muted", 3, kind="empty")
    return {"size": (WIDTH, HEIGHT), "plot": PLOT, "mode": mode, "labels": canvas.labels}


def _scale(lo: float, hi: float):
    if hi - lo < 1e-9:
        pad = abs(hi) * 0.01 or 1.0
        lo, hi = lo - pad, hi + pad
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    top, bottom = PLOT[1] + 6, PLOT[3] - 6
    return lambda price: bottom - (price - lo) / (hi - lo) * (bottom - top)


def _clock(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%H:%M")


def _gutter(canvas: _Canvas, wanted: list[tuple[float, str, str]], kind: str) -> None:
    """Labels at the right of the plot near their y, pushed apart so none overlap and none leave the plot."""
    x = PLOT[2] + 10
    height, gap = 14, 6
    order = sorted(wanted, key=lambda w: w[0])
    placed: list[float] = []
    for y, _, _ in order:
        top = max(y - height / 2, PLOT[1])
        if placed and top < placed[-1] + height + gap:
            top = placed[-1] + height + gap
        placed.append(top)
    overflow = placed[-1] + height - PLOT[3] if placed else 0
    if overflow > 0:
        placed = [max(PLOT[1], p - overflow) for p in placed]
        for i in range(1, len(placed)):  # still in order after the shift; re-space from the top if crowded
            placed[i] = max(placed[i], placed[i - 1] + height + gap)
    for (_, text, tone), top in zip(order, placed):
        canvas.text(x, top, fit(text, 2, GUTTER - 16), tone, 2, kind=kind)


def _time_axis(canvas: _Canvas, first: int, last: int) -> None:
    y = PLOT[3] + 10
    canvas.text(PLOT[0], y, _clock(first), "muted", 2, kind="axis")
    end = _clock(last)
    canvas.text(PLOT[2] - text_width(end, 2), y, end, "muted", 2, kind="axis")


def _bars(canvas: _Canvas, chart: Chart, mode: str) -> None:
    x0, y0, x1, y1 = PLOT
    bars = sorted(chart.bars, key=lambda b: b["time"])
    times = np.array([b["time"] for b in bars])
    prices = [p for b in bars for p in (b["low"], b["high"])]
    prices += [lv.price for lv in chart.levels] + [m.price for m in chart.marks]
    y_of = _scale(min(prices), max(prices))
    n = len(bars)
    step = (x1 - x0 - 8) / max(n, 1)

    def x_of_index(i: float) -> float:
        return x0 + 4 + step * (i + 0.5)

    def x_of_time(stamp: int) -> float:
        i = int(np.searchsorted(times, stamp, side="right")) - 1
        return x_of_index(min(max(i, 0), n - 1))

    for level in chart.levels:
        canvas.hline(x0, x1, y_of(level.price), level.tone, 2, level.dashed)
    for when in chart.times:
        canvas.vline(x_of_time(when.time), y0, y1, when.tone, 2, dashed=True)
    if mode == "candles":
        body = max(1, int(step * 0.7))
        for i, b in enumerate(bars):
            tone = "up" if b["close"] >= b["open"] else "down"
            cx = x_of_index(i)
            canvas.rect(cx, y_of(b["high"]), cx, y_of(b["low"]), tone)
            canvas.rect(cx - body // 2, y_of(max(b["open"], b["close"])), cx - body // 2 + body - 1, y_of(min(b["open"], b["close"])), tone)
    else:
        canvas.polyline([(x_of_index(i), y_of(b["close"])) for i, b in enumerate(bars)], "blue", 2)
    for when in chart.times:  # labels after the candles so they stay readable
        x = x_of_time(when.time)
        text = fit(when.label, 2, 200)
        left = min(max(x + 6, x0), x1 - text_width(text, 2))
        canvas.text(left, y0 + 4 + 20 * (chart.times.index(when) % 2), text, when.tone, 2, kind="time", backdrop=True)
    for mark in chart.marks:
        x, y = x_of_time(mark.time), y_of(mark.price)
        canvas.dot(x, y, 7, "bg")
        canvas.dot(x, y, 5, mark.tone)
        if mark.label:
            text = fit(mark.label, 2, 200)
            below = y < y0 + 40
            left = min(max(x - text_width(text, 2) / 2, x0), x1 - text_width(text, 2))
            canvas.text(left, y + 12 if below else y - 26, text, mark.tone, 2, kind="mark", backdrop=True)
    _gutter(canvas, [(y_of(lv.price), lv.label, lv.tone) for lv in chart.levels], "level")
    _time_axis(canvas, int(times[0]), int(times[-1]))


def _series(canvas: _Canvas, chart: Chart) -> None:
    x0, y0, x1, y1 = PLOT
    lines = [s for s in chart.series if s.points]
    stamps = [t for s in lines for t, _ in s.points]
    values = [v for s in lines for _, v in s.points] + [0.0]
    first, last = min(stamps), max(stamps)
    y_of = _scale(min(values), max(values))
    span = max(last - first, 1)

    def x_of(stamp: int) -> float:
        return x0 + 4 + (stamp - first) / span * (x1 - x0 - 8)

    canvas.hline(x0, x1, y_of(0.0), "grid", 2, dashed=True)
    for line in reversed(lines):  # the first series (the subject) on top
        canvas.polyline([(x_of(t), y_of(v)) for t, v in sorted(line.points)], line.tone, 4 if line is lines[0] else 2)
    ends = [(y_of(sorted(s.points)[-1][1]), f"{s.label} {sorted(s.points)[-1][1]:+.1f}%", s.tone) for s in lines]
    _gutter(canvas, ends, "series")
    _time_axis(canvas, first, last)


def _rows(canvas: _Canvas, rows: tuple[Row, ...]) -> None:
    x0, y0, x1, _ = PLOT
    shown = rows[:6]
    label_w = 12 * 19
    for i, row in enumerate(shown):
        y = y0 + 8 + i * 44
        canvas.text(LEFT, y + 6, fit(row.label, 2, label_w), "text", 2, kind="row")
        bar_x0 = LEFT + label_w + 14
        length = (WIDTH - LEFT - 96 - bar_x0) * min(max(row.fraction, 0.0), 1.0)
        canvas.rect(bar_x0, y, bar_x0 + max(length, 4), y + 25, row.tone)
        canvas.text(bar_x0 + max(length, 4) + 10, y + 6, fit(row.value, 2, 84), row.tone, 2, kind="row_value")
    if len(rows) > len(shown):
        canvas.text(LEFT, y0 + 8 + len(shown) * 44, f"+{len(rows) - len(shown)} MORE", "muted", 2, kind="row")


# ------------------------------------------------------------------ PNG


def _png(pixels: np.ndarray) -> bytes:
    """An 8-bit palette PNG; no timestamps or text chunks, so the bytes depend only on the pixels."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    height, width = pixels.shape
    raw = np.hstack([np.zeros((height, 1), dtype=np.uint8), pixels]).tobytes()
    palette = b"".join(bytes(PALETTE[name]) for name in NAMES)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", palette)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
