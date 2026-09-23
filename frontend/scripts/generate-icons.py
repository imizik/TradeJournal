#!/usr/bin/env python3
"""Regenerate the home-screen icons in frontend/public/.

    python3 scripts/generate-icons.py

A rising line on the app's dark background: recognizable at 60px on a phone
home screen, and small enough to read as a diff. Written with zlib + struct so
the repo needs no image dependency. iOS masks apple-touch-icon.png itself, so
the artwork stays square and full-bleed.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BACKGROUND = (18, 21, 28)  # --background, hsl(222 20% 9%)
LINE = (52, 211, 153)  # emerald-400, the app's "up" color
PUBLIC = Path(__file__).resolve().parent.parent / "public"

# Chart shape in unit coordinates (0,0 top-left .. 1,1 bottom-right).
POINTS = [(0.14, 0.72), (0.34, 0.54), (0.50, 0.63), (0.70, 0.34), (0.86, 0.26)]


def blend(base: tuple[int, int, int], colour: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return tuple(round(b + (c - b) * alpha) for b, c in zip(base, colour))  # type: ignore[return-value]


def draw(size: int) -> list[list[tuple[int, int, int]]]:
    pixels = [[BACKGROUND for _ in range(size)] for _ in range(size)]
    radius = max(size * 0.035, 1.5)
    points = [(x * size, y * size) for x, y in POINTS]

    # Distance to each segment, so joins stay smooth and edges anti-alias.
    for y in range(size):
        for x in range(size):
            centre = (x + 0.5, y + 0.5)
            best = min(distance_to_segment(centre, start, end) for start, end in zip(points, points[1:]))
            best = min(best, min(distance(centre, point) for point in (points[0], points[-1])))
            coverage = max(0.0, min(1.0, radius + 0.5 - best))
            if coverage:
                pixels[y][x] = blend(pixels[y][x], LINE, coverage)
    return pixels


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def distance_to_segment(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    if not length:
        return distance(point, start)
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length))
    return distance(point, (start[0] + t * dx, start[1] + t * dy))


def write_png(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    size = len(pixels)
    raw = b"".join(b"\x00" + bytes(value for pixel in row for value in pixel) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    PUBLIC.mkdir(exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        write_png(PUBLIC / name, draw(size))
        print(f"wrote public/{name} ({size}x{size})")


if __name__ == "__main__":
    main()
