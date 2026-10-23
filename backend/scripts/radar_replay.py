"""Replay a Radar store's recorded sessions through the alert rules and print what they would have written.

Read-only: opens the file in SQLite read-only mode and writes nothing. Uses the current tracked list
(``app/data/radar_universe.json``) for stock kinds, sectors and groups. ``--set name=value`` overrides one
``radar_rules.V0`` threshold for this run only (e.g. ``--set spy_relative_pct=3.5 --set windows=15,30``);
frozen rules change only with a new rule version.

    python scripts/radar_replay.py /abs/path/radar.sqlite [--session 2026-10-22] [--set ...] [--quiet]
"""
import argparse
from collections import Counter
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path

from app.engine import radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore, load_universe


def _thresholds(overrides: list[str]) -> radar_rules.Thresholds:
    types = {f.name: f.type for f in fields(radar_rules.Thresholds)}
    values = {}
    for item in overrides:
        name, _, raw = item.partition("=")
        if name not in types:
            raise SystemExit(f"unknown threshold {name!r}; one of {', '.join(types)}")
        current = getattr(radar_rules.V0, name)
        if isinstance(current, tuple):
            values[name] = tuple(int(v) for v in raw.split(","))
        else:
            values[name] = type(current)(raw)
    return replace(radar_rules.V0, **values)


def _time(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ET).strftime("%H:%M")


def replay_session(store: RadarStore, universe: dict, session: str, thresholds) -> list[tuple[dict, list[dict]]]:
    passes = radar_rules.session_passes(store.passes(session), session)
    quotes: dict[int, dict[str, dict]] = {}
    for row in store.quotes(session_date=session):
        quotes.setdefault(row["pass_id"], {})[row["symbol"]] = row
    return radar_rules.replay(universe, passes, quotes, thresholds)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("store", type=Path)
    parser.add_argument("--session", action="append", help="YYYY-MM-DD; repeatable; default every session")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--quiet", action="store_true", help="counts only")
    args = parser.parse_args()
    thresholds = _thresholds(args.set)
    store = RadarStore(args.store.resolve(), read_only=True)
    universe = load_universe()
    print(f"{radar_rules.RULE_VERSION} {thresholds}")
    for session in sorted(args.session or store.sessions()):
        saved = replay_session(store, universe, session, thresholds)
        counts = Counter(f"{e['kind']}/{e['direction']}" for e, _ in saved)
        recorded = len(radar_rules.session_passes(store.passes(session), session))
        print(f"\n{session}: {len(saved)} events over {recorded} passes  "
              + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if args.quiet:
            continue
        for event, revisions in saved:
            later = ", ".join(f"{r['status']} {_time(r['recorded_at'])}" for r in revisions)
            print(f"  {_time(event['first_seen_at'])}  {event['kind']:<18} {event['summary']}"
                  + (f"\n         later: {later}" if later else ""))


if __name__ == "__main__":
    main()
