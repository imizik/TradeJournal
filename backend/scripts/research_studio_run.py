"""Manual R2 discovery jobs. Explicit research store/cache roots; no services."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.research_studio import parse_definition  # noqa: E402
from app.engine.research_studio_data import DiscoveryCache  # noqa: E402
from app.engine.research_studio_store import ResearchStore  # noqa: E402
from scripts.research_studio import read_definition  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True, help="existing, separate owner-controlled local directory")
    commands = parser.add_subparsers(dest="command", required=True)
    enqueue = commands.add_parser("enqueue", help="snapshot discovery inputs; does not expose outcomes")
    enqueue.add_argument("--definition", type=Path, required=True)
    enqueue.add_argument("--operation-id", required=True, help="UUID reused only for an identical request")
    commands.add_parser("work-once", help="foreground isolated worker; execute at most one queued run")
    for name in ("status", "result", "cancel", "retry"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        if name != "status":
            command.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    try:
        source = DiscoveryCache(args.cache_root)
        store = ResearchStore(args.store_root, source_root=source.root)
        if args.command == "enqueue":
            path = args.definition.resolve(strict=True)
            if path.is_relative_to(source.root) or path.is_relative_to(store.root):
                raise ValueError("definition must be outside source cache and research store")
            definition = parse_definition(json.loads(read_definition(path)))
            snapshot = source.snapshot(definition.universe, through=definition.end)
            result = store.enqueue(snapshot, definition, args.operation_id)
        elif args.command == "work-once":
            result = store.work_once()
        elif args.command == "status":
            result = store.status(args.run_id)
        elif args.command == "result":
            result = store.result(args.run_id, args.operation_id)
        else:
            result = store.control(args.run_id, args.command, args.operation_id)
        print(json.dumps(result, indent=2, allow_nan=False))
        if result.get("status") == "failed":
            parser.exit(1, "R2 run failed; inspect status before an explicit retry\n")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        parser.exit(2, f"R2 request refused: {exc}\n")


if __name__ == "__main__":
    main()
