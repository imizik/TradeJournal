"""Run one Copilot Lab research job by hand and print its cited assessment (docs/copilot-lab.md § Research job).

Owner-only and manual: no scheduler, wake-up or notification. Research only; it saves no plan, watch or alert.
``RESEARCH_AUTH=plan`` (default, local database only) or ``api_key``; ``RESEARCH_BUDGET_USD`` caps the job (0.50).

    python scripts/run_research_job.py "Why are neoclouds weak today?" --symbols NBIS,CRWV,APLD \\
        [--evidence fixture|live|replay] [--replay-store /abs/radar.sqlite --replay-at 2026-10-23T11:12] [--out job.json]
        [--no-save]

A finished job is saved as an open saved investigation (source research_job) unless --no-save is given.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# This checkout's backend first, as seed_dev_data.py does: a shared or editable-installed
# virtualenv must never resolve `app` to another checkout (and its .env files).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.environment import load_env_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--symbols", default="", help="comma-separated tickers")
    parser.add_argument("--evidence", choices=("fixture", "live", "replay"), default="live")
    parser.add_argument("--replay-store")
    parser.add_argument("--replay-at")
    parser.add_argument("--out", type=Path, help="also write the result JSON here")
    parser.add_argument("--no-save", action="store_true", help="do not save the result as a saved investigation")
    args = parser.parse_args()
    load_env_files()

    from app.ai import copilot, copilot_tools, research_job
    from app.engine.chart_math import ET
    try:
        tickers = [s for s in args.symbols.split(",") if s]
        symbols = copilot_tools.validate("get_quotes", {"symbols": tickers})["symbols"] if tickers else []
    except copilot_tools.ToolInputError as exc:
        parser.error(str(exc))
    cfg = copilot.Settings(enabled=True, backend="plan", evidence=args.evidence, model=copilot.DEFAULT_MODEL, effort="medium",
                           fallbacks=False, key_configured=False, replay_store=args.replay_store or "", replay_at=args.replay_at or "")
    try:
        evidence = copilot.evidence_for(cfg)
        result = research_job.run(args.question, symbols, evidence, datetime.now(ET), save=not args.no_save)
    except (copilot.CopilotError, research_job.ResearchError) as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
