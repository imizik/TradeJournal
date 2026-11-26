"""Load model-written trade tags into ``trade_ai_tag`` (insert or replace by anchor).

Run from backend/ against the database in DATABASE_URL:
    python scripts/load_trade_ai_tags.py tags_for_load.json [--dry-run]

The file is {"model": ..., "batch_id": ..., "rows": [{account_id, source_key, trade_id, tag, facts}, ...]}.
Writes only ``trade_ai_tag``; never a trade, fill or money value.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from app.database import engine  # noqa: E402
from app.engine import trade_ai_tags  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = json.load(open(a.path))
    print(f"{len(data['rows'])} rows, model {data['model']}, batch {data.get('batch_id')}")
    if a.dry_run:
        return
    with Session(engine) as db:
        added, updated = trade_ai_tags.upsert(db, data["rows"], model=data["model"], batch_id=data.get("batch_id"))
    print(f"added {added}, updated {updated}")


if __name__ == "__main__":
    main()
