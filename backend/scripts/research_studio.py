"""Read-only R1 population preview; no outcomes, provider calls or saved runs.

Usage: python scripts/research_studio.py --cache-root /approved/stocks/1Min/sip
       --definition /tmp/event-definition.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import Observations, parse_definition  # noqa: E402
from app.engine.research_studio_data import DiscoveryCache  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True, help="explicit operator-approved SIP minute root")
    parser.add_argument("--definition", type=Path, required=True, help="versioned R1 input JSON")
    args = parser.parse_args()
    try:
        root = args.cache_root.resolve(strict=True)
        definition_path = args.definition.resolve(strict=True)
        if definition_path.is_relative_to(root):
            raise ValueError("definition input must be outside the source cache")
        definition = parse_definition(json.loads(definition_path.read_bytes()))
        snapshot = DiscoveryCache(root).snapshot(definition.universe, through=definition.end)
        preview = Observations(snapshot).preview(definition)
        print(json.dumps(preview, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"R1 preview refused: {exc}\n")


if __name__ == "__main__":
    main()
