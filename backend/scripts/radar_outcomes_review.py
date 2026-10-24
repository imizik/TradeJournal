"""Ask the Copilot Lab research job, on the Claude plan, what set apart the Radar events that kept going from those that reversed.

Reads the scorer's output (``scripts/radar_outcomes.py``), picks the events that went furthest each way at +60 min
over the chosen sessions, and runs one research job (``app.ai.research_job``) with ``RESEARCH_AUTH=plan`` only: the
owner's subscription token, never an API key; any other auth setting is refused before anything runs. The job runs
where the plan mode allows it (a local database) and saves nothing; the review goes to ``--out``.

It sees outcomes, so it is hindsight: ideas for a later rule version, never a change to the current one or its
decision (``research/radar-outcomes/spec.md``).

    python scripts/radar_outcomes_review.py /abs/outcomes.jsonl --since 2026-10-27 [--until 2026-10-31] --out review.json [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.environment import load_env_files  # noqa: E402

PER_SIDE = 4
HORIZON = "60m"
MAX_SYMBOLS = 8  # copilot_tools.MAX_SYMBOLS


def _line(row: dict) -> str:
    h = row["horizons"][HORIZON]
    movers = "n/a" if h["movers"] is None else f"{h['movers']:+.2f}"
    seen = datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    return (f"- {row['session_date']} first seen {seen:%H:%M} ET ({row['first_seen_at']}): {row['kind']} {row['direction']} "
            f"{', '.join(row['symbols'][:4])} ({row['rule_version']}); +60 min vs SPY in its direction {h['event']:+.2f} "
            f"points, Movers at that minute {movers}")


def question_for(rows: list[dict], since: str, until: str | None) -> tuple[str, list[str]] | None:
    """The question and its symbols, or None when no event in the range has a +60 min score."""
    chosen = [r for r in rows if since <= r["session_date"] <= (until or "9999") and HORIZON in r["horizons"]]
    if not chosen:
        return None
    ranked = sorted(chosen, key=lambda r: (-r["horizons"][HORIZON]["event"], r["event_id"]))
    kept = [r for r in ranked if r["horizons"][HORIZON]["event"] > 0][:PER_SIDE]
    reversed_ = [r for r in reversed(ranked) if r["horizons"][HORIZON]["event"] < 0][:PER_SIDE]
    symbols = []
    for r in kept + reversed_:
        if r["symbols"] and r["symbols"][0] not in symbols:
            symbols.append(r["symbols"][0])
    text = "\n".join([
        f"Review of Radar events from {since} to {until or 'the latest scored session'} ({len(chosen)} scored). "
        "These are past, recorded events; their outcomes are already known, so this is hindsight review.",
        "", "Kept going most at +60 min:", *([_line(r) for r in kept] or ["- none"]),
        "", "Reversed most at +60 min:", *([_line(r) for r in reversed_] or ["- none"]),
        "", "What set the ones that kept going apart from the ones that reversed? Check the news timing for each "
        "(published before or after first seen), whether the stock's sector or group moved with it, and the time of day. "
        "Cite sources. End with at most two specific, testable ideas for a later Radar rule version, each stated as a "
        "condition the recorder could check at the first-seen minute. No trade ideas and no change to the current rules.",
    ])
    return text, symbols[:MAX_SYMBOLS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("outcomes", type=Path)
    parser.add_argument("--since", required=True, help="first session (YYYY-MM-DD)")
    parser.add_argument("--until", help="last session (YYYY-MM-DD), default the latest")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the question; no research job")
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.outcomes.read_text().splitlines() if line.strip()]
    built = question_for(rows, args.since, args.until)
    if built is None:
        print("No scored events in that range.", file=sys.stderr)
        return 1
    question, symbols = built
    if args.dry_run:
        print(json.dumps({"question": question, "symbols": symbols}, indent=2))
        return 0
    load_env_files()
    if os.environ.get("RESEARCH_AUTH", "plan").strip().lower() != "plan":
        print("refused: this review runs only on the Claude plan (RESEARCH_AUTH=plan), never an API key.", file=sys.stderr)
        return 2
    from app.ai import copilot, copilot_tools, research_job
    from app.engine.chart_math import ET
    try:
        result = research_job.run(question, symbols, copilot_tools.LiveEvidence(), datetime.now(ET), mode="plan", save=False,
                                  title=f"Radar outcomes review {args.since}..{args.until or 'latest'}")
    except (copilot.CopilotError, research_job.ResearchError) as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    if result.get("auth") != "plan":  # belt and braces: the record states the sign-in it actually used
        print("refused: the job did not run on the plan.", file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
