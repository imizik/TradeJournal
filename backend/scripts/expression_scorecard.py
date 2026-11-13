"""The expression recorder's scorecard: each alternative against the owner's contract, priced the same way.

Reads the recorder's own SQLite file (``app/engine/expression_recorder.py``); writes nothing. Only closed positions
whose every snapshot was recorded within ``LATE_SECONDS`` of its fill count. For each alternative, over the positions
where it could be built: its dollars, his contract's dollars by the same quote rules, the paired difference, the
difference per dollar of his premium, and how often the alternative did better. Split by same session against
held past the entry session. Personal: print it, do not commit it.

Run from backend:
    python -m scripts.expression_scorecard [--db /path/to/expression_recorder.sqlite3]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.engine import expression_recorder as er


def card(scored: list[dict]) -> dict:
    out = {}
    for alt in er.ALTERNATIVES[1:]:
        rows = [s for s in scored if alt in s["pnl"] and "as_traded" in s["pnl"]]
        premium = sum(s["premium"] for s in rows)
        diff = sum(s["pnl"][alt] - s["pnl"]["as_traded"] for s in rows)
        out[alt] = {"positions": len(rows), "alternative": round(sum(s["pnl"][alt] for s in rows), 2),
                    "as_traded": round(sum(s["pnl"]["as_traded"] for s in rows), 2), "difference": round(diff, 2),
                    "difference_per_premium_pct": round(diff / premium * 100, 2) if premium else None,
                    "alternative_did_better": sum(1 for s in rows if s["pnl"][alt] > s["pnl"]["as_traded"])}
    return out


def scorecard(store: er.Store) -> dict:
    results = [er.score(p, store.snapshots(p["key"])) for p in store.positions()]
    counted = [r for r in results if r["complete"] and not r["late"]]
    groups = {h: [r for r in counted if r["held"] == h] for h in ("same session", "past the entry session")}
    return {"positions": len(results), "counted": len(counted),
            "left_out": {"still open or incomplete": sum(1 for r in results if not r["complete"]),
                         "a snapshot too far from its fill": sum(1 for r in results if r["complete"] and r["late"])},
            "actual": round(sum(r["actual"] for r in counted), 2),
            "as_traded": round(sum(r["pnl"].get("as_traded", 0) for r in counted), 2),
            "premium": round(sum(r["premium"] for r in counted), 2),
            "all": card(counted), **{h: {"positions": len(rows), **card(rows)} for h, rows in groups.items()}}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    path = args.db or er.store_path()
    if not path.exists():
        raise SystemExit(f"no recorder file at {path}")
    print(json.dumps(scorecard(er.Store(path)), indent=2))


if __name__ == "__main__":
    sys.exit(main())
