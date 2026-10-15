"""Export the frozen Mac pilot as one private isolated-replay handoff.

Stdlib only; no app/database/provider imports, generation or model calls.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scanner_replay_operator import private_json, write_private_report


def export(pilot_root, output):
    if (
        not pilot_root.is_absolute()
        or pilot_root.is_symlink()
        or pilot_root.resolve() != pilot_root
    ):
        raise ValueError("Canonical pilot directory required")
    manifest = private_json(
        pilot_root / "operator-private/manifest.json", 20 * 1024 * 1024
    )
    outcomes = private_json(
        pilot_root / "operator-private/outcomes.json", 20 * 1024 * 1024
    )
    encoded = json.dumps(
        outcomes, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if hashlib.sha256(encoded).hexdigest() != manifest["sealed_outcomes_sha256"]:
        raise ValueError("Frozen outcome seal mismatch")
    body = {
        "format": "opportunity-replay-import-v1",
        "manifest": manifest,
        "outcomes": outcomes,
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode()) > 20 * 1024 * 1024:
        raise ValueError("Handoff exceeds import bound")
    write_private_report(output, text + "\n")
    return {
        "cards": len(manifest["cards"]),
        "manifest_sha256": hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.pilot_root, args.output)))
    except Exception:
        raise SystemExit(
            "Opportunity export refused; check private source, seal and fresh output"
        ) from None
