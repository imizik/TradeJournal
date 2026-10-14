"""Build pre-session replay aggregates beside the existing approved feature snapshot.

Run on the publisher host. Only aggregate cards leave this process: no trade
rows, fill keys, account fields, positions, captures or database access.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timezone
import json
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.pretrade_check import history_card  # noqa: E402
from pretrade_features import read_current  # noqa: E402
from scripts.scanner_replay_operator import private_json, write_private_report  # noqa: E402

ET = ZoneInfo("America/New_York")
FORMAT = "scanner-replay-cutoff-history-v1"


def aggregate(document, features):
    if (not isinstance(document, dict) or set(document) != {"format", "requests"}
            or document["format"] != "scanner-replay-history-requests-v1"
            or not isinstance(document["requests"], list) or not 1 <= len(document["requests"]) <= 1500):
        raise ValueError("Require bounded setup-feature requests")
    if features["state"] not in {"fresh", "stale"} or features["rows"] is None:
        raise ValueError("Existing approved trade-feature snapshot is unavailable")
    cards = {}
    for request in document["requests"]:
        if set(request) != {"candidate_id", "session_date", "history_cutoff", "features"}:
            raise ValueError("Unexpected request fields")
        key = request["candidate_id"]
        if str(uuid.UUID(key)) != key or key in cards:
            raise ValueError("Require unique canonical candidate IDs")
        day = datetime.strptime(request["session_date"], "%Y-%m-%d").date()
        cutoff = datetime.combine(day, time(), ET)
        idea = request["features"]
        if (request["history_cutoff"] != cutoff.isoformat()
                or set(idea) != {"underlying", "side", "time_bucket", "vwap_bucket"}
                or idea["side"] not in {"call", "put"}
                or idea["time_bucket"] not in {"open", "mid", "close"}
                or idea["vwap_bucket"] not in {"below", "at", "above"}):
            raise ValueError("Invalid frozen cohort features/cutoff")
        prior = []
        for row in features["rows"]:
            closed = datetime.fromisoformat(row["closed_at"])
            closed = closed.replace(tzinfo=ET) if closed.tzinfo is None else closed.astimezone(ET)
            if closed < cutoff:
                prior.append({**row, "closed_at": closed.replace(tzinfo=None).isoformat()})
        card = history_card(prior, idea, cutoff.astimezone(timezone.utc))
        card.pop("source_fill_keys", None)
        card.update(as_of_ny=cutoff.isoformat(), available=True, source_state=features["state"])
        cards[key] = {"features": idea, "history_cutoff": cutoff.isoformat(), "history": card}
    return {"format": FORMAT, "source_state": features["state"],
            "source_sha256": features["features_sha256"], "generated_at": features["generated_at"], "cards": cards}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--features-pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    document = private_json(args.requests, 2 * 1024 * 1024)
    features = read_current(args.features_pointer, max_age_seconds=36 * 3600)
    result = aggregate(document, features)
    write_private_report(args.output, json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    print(json.dumps({"cards": len(result["cards"]), "source_state": result["source_state"],
                      "source_sha256": result["source_sha256"], "output": str(args.output)}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Replay history aggregation refused; check private requests and approved snapshot") from None
