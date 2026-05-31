"""
Dump the most recent webull_raw_event rows with fully decoded payloads.

Run after placing a Webull trade to see exactly what the gRPC stream
delivered. Used to drive option metadata resolution.
"""
import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    db = Path(__file__).resolve().parent.parent / "data" / "trade_journal.db"
    conn = sqlite3.connect(db)

    rows = conn.execute(
        "SELECT event_id, scene_type, order_status, category, normalized, "
        "normalize_reason, normalize_error, fill_id, received_at, payload_json "
        "FROM webull_raw_event "
        "ORDER BY received_at DESC LIMIT ?",
        (args.limit,),
    ).fetchall()

    out = []
    for r in rows:
        try:
            payload = json.loads(r[9])
        except Exception:
            payload = r[9]
        out.append({
            "event_id": r[0],
            "scene_type": r[1],
            "order_status": r[2],
            "category": r[3],
            "normalized": bool(r[4]),
            "normalize_reason": r[5],
            "normalize_error": r[6],
            "fill_id": r[7],
            "received_at": r[8],
            "payload": payload,
        })

    print(f"Found {len(out)} event(s).\n")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
