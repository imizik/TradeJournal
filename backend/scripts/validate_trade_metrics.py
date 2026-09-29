"""Validate an explicitly supplied journal snapshot and cache, without DB/network.

python scripts/validate_trade_metrics.py --snapshot snapshot.json --cache-dir PATH --feed iex --output report.json

This writes only the named report and its .md/.html companions. Source records and
cache files are read-only; missing history is never fetched. A mismatch returns
exit 1; malformed inputs return exit 2. Stale/unavailable metrics are reported,
not counted as matches. Broker reconciliation is never implied by this report.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.metric_validation import CachedBars, build_report  # noqa: E402
from app.engine.metric_report import html_report  # noqa: E402


def markdown(report):
    counts = report["counts"]
    lines = ["# Trade metric validation", "", f"Snapshot: {report.get('snapshot_at')}",
             f"Reference: `{report['reference_revision']}`; stock feed: `{report['feed']}`.",
             f"Canonical-record SHA256: `{report['snapshot_sha256']}`.", "",
             "**Broker verification: not performed.** Agreement proves internal accounting or reproducibility on cached inputs, not source truth.",
             "", f"Trades: {report['trade_count']}; fills: {report['fill_count']}; unlinked fills: {len(report['unlinked_fill_ids'])}.",
             "", "| Check status | Count |", "| --- | ---: |"]
    lines.extend(f"| {status} | {counts.get(status, 0)} |" for status in ("matched", "mismatch", "stale", "unavailable", "error"))
    lines.extend(["", "## Internal accounting", "", str(report["accounting_counts"]), "",
                  "Gross values only. Fees and broker lot-selection conventions require separate reconciliation.", "",
                  "## Fields needing attention", "", "| Field | Mismatch | Stale | Unavailable | Error |", "| --- | ---: | ---: | ---: | ---: |"])
    fields = {}
    for trade in report["trades"]:
        for check in trade["checks"]:
            fields.setdefault(check["field"], Counter())[check["status"]] += 1
    for field, totals in sorted(fields.items()):
        if any(totals[s] for s in ("mismatch", "stale", "unavailable", "error")):
            lines.append(f"| {field} | {totals['mismatch']} | {totals['stale']} | {totals['unavailable']} | {totals['error']} |")
    lines.extend(["", "## Manual review sample", "", "This is a deterministic, diverse hard-case sample, not a representative statistical sample.", "",
                  f"Categories: {', '.join(report['sample_categories'])}.", ""])
    selected = set(report["review_sample_ids"])
    for trade in report["trades"]:
        if trade["trade_id"] in selected:
            totals = Counter(c["status"] for c in trade["checks"])
            lines.append(f"- {trade.get('ticker')}: `{trade['trade_id']}` — {dict(totals)}")
    lines.extend(["", "## Limits", "", "- Minute extrema are observed estimates, not executable bid/ask quotes.",
                  "- Entry comparisons use completed bars; final revised bars cannot prove exactly what arrived live at entry.",
                  "- Missing cache history stays unavailable; old calculation versions stay stale.",
                  "- Option caches do not record a reliable feed identity. Same-cache agreement cannot establish OPRA provenance.",
                  "- Coverage excludes hourly context, RVOL, Greeks, chase/sequence scores, underlying efficiency and post-exit metrics.",
                  "- Setup scores are heuristics. This report does not validate a trading edge.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--feed", choices=("iex", "sip"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=30)
    args = parser.parse_args()
    if args.output.suffix != ".json" or args.output.resolve() == args.snapshot.resolve():
        parser.error("--output must be a separate .json report file")
    if args.output.resolve().is_relative_to(args.cache_dir.resolve()):
        parser.error("--output must be outside the read-only cache")
    if args.sample_size < 0:
        parser.error("--sample-size must be nonnegative")
    try:
        data = json.loads(args.snapshot.read_text())
        report = build_report(data, CachedBars(args.cache_dir, args.feed), sample_size=args.sample_size)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Validation input error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str))
    args.output.with_suffix(".md").write_text(markdown(report))
    args.output.with_suffix(".html").write_text(html_report(report))
    print(json.dumps({k: report[k] for k in ("trade_count", "fill_count", "counts", "accounting_counts", "broker_verification")}, indent=2))
    return 1 if report["counts"].get("mismatch") or report["counts"].get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
