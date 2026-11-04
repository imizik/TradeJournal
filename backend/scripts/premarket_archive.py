"""Reconstruct session archives and export private scorecard baselines."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path

from dotenv import dotenv_values
import httpx

from app.engine.premarket_archive import ET, ROOT, Market, at, baseline, reconstruct, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baselines", type=Path, required=True)
    parser.add_argument("--credentials", type=Path)
    args = parser.parse_args()
    if args.start > args.end or at(args.end, 9) > datetime.now(ET):
        parser.error("Expected a completed 09:00 cutoff")
    repository = Path(__file__).resolve().parents[2]
    if args.root.resolve().is_relative_to(repository) and args.root.resolve() != ROOT.resolve():
        parser.error("Archive inside the repository must use the ignored app data directory")
    if args.baselines.resolve().is_relative_to(args.root.resolve()):
        parser.error("Keep the export separate from write-once daily files")
    if args.baselines.resolve().is_relative_to(repository):
        parser.error("Keep the scorecard input outside git")
    os.umask(0o077)
    config = dotenv_values(args.credentials) if args.credentials else os.environ
    with httpx.Client(timeout=60) as client:
        market = Market(client, config)
        days = market.calendar(args.start - timedelta(days=14), args.end)
        output = {}
        for prior, day in zip(days, days[1:]):
            if day < args.start:
                continue
            path = args.root / f"{day}.json"
            if path.exists():
                record = json.loads(path.read_text())
            else:
                symbols = market.symbols(day)
                record = save(args.root, day, reconstruct(market, day, prior, symbols))
            if (record.get("source") not in ("contemporaneous", "reconstructed-sip")
                    or record.get("as_of") != at(day, 9).isoformat() or record.get("feed") != "sip"
                    or record.get("whole_market") is not True or record.get("ranking_basis") != "pct_vs_prior_regular_close"):
                raise ValueError(f"Invalid saved 09:00 archive for {day}")
            output[day.isoformat()] = baseline(record)
            print(f"{day}: {record['source']}, {record['universe_size']} listings, {record['eligible']} eligible", flush=True)
    args.baselines.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.baselines.write_text(json.dumps(output))
    args.baselines.chmod(0o600)


if __name__ == "__main__":
    main()
