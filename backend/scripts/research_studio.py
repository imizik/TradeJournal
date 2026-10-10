"""Read-only R1 population preview; no outcomes, provider calls or saved runs.

Usage: python scripts/research_studio.py --cache-root /approved/stocks/1Min/sip
       --definition /tmp/event-definition.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import Observations, parse_definition  # noqa: E402
from app.engine.research_studio_data import DiscoveryCache  # noqa: E402


def read_definition(path: Path) -> bytes:
    """Open a resolved external config through no-follow directory descriptors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            limit = 1024 * 1024
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("definition must be a bounded regular file")
            payload = handle.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("definition exceeded byte bound")
            return payload
    finally:
        os.close(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True, help="explicit operator-approved SIP minute root")
    parser.add_argument("--definition", type=Path, required=True, help="versioned R1 input JSON")
    args = parser.parse_args()
    try:
        source = DiscoveryCache(args.cache_root)
        definition_path = args.definition.resolve(strict=True)
        if definition_path.is_relative_to(source.root):
            raise ValueError("definition input must be outside the source cache")
        definition = parse_definition(json.loads(read_definition(definition_path)))
        snapshot = source.snapshot(definition.universe, through=definition.end)
        preview = Observations(snapshot).preview(definition)
        print(json.dumps(preview, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"R1 preview refused: {exc}\n")


if __name__ == "__main__":
    main()
