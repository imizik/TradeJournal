"""Explicit owner-only MW-1 commands. No daemon, grants, delivery or activation.

Snapshot collection is an app-side command; export is a read-only check-ledger
command. Never install this as an MCP tool or expose it through the private API.
"""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    snapshot = commands.add_parser('snapshot', help='Manually collect and publish public SPY/QQQ evidence')
    snapshot.add_argument('--directory', required=True)
    export = commands.add_parser('export', help='Read one actor’s market-watch records; write canonical JSON to stdout')
    export.add_argument('--ledger', required=True)
    export.add_argument('--actor', required=True)
    args = parser.parse_args(argv)
    if args.command == 'snapshot':
        from app.engine.market_watch_snapshot import build_snapshot, publish_snapshot
        directory = Path(args.directory)
        if not directory.is_absolute():
            parser.error('Require an absolute operator-owned publication directory')
        record = build_snapshot()
        publish_snapshot(directory, record)
        print(json.dumps({'snapshot_id': record['snapshot_id'], 'content_sha256': record['content_sha256']}))
    else:
        from market_watch_common import canonical
        from market_watch_ledger import MarketWatchLedger
        print(canonical(MarketWatchLedger.export(args.ledger, args.actor)).decode())


if __name__ == '__main__':
    main()
