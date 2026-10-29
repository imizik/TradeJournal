"""Command line: prefetch, replay, report, live. Run from the repository root with
``backend/.venv/bin/python -m research.opening_lab <command> --help``."""

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .contract import VARIANTS

DEFAULT_MODEL = "claude-sonnet-5-5"
PROMPT = Path(__file__).with_name("prompt.txt")


def _sessions(days, log):
    """Load cached sessions with context; skip (and say) unusable ones."""
    from .context import attach_context
    from .data import load_session

    sessions = {}
    for day in days:
        try:
            sessions[day] = attach_context(load_session(day), fetch=False)
        except Exception as exc:
            log(f"skip {day}: {type(exc).__name__}: {exc}")
    return sessions


def _model(args):
    if args.model == "none":
        return None, None
    if args.fake or args.model == "fake":
        args.fake = True
        from .model import FakeForecaster

        return FakeForecaster(), "fake"
    from .model import ClaudeForecaster

    thinking = 2048 if args.thinking == "adaptive" else 0
    settings = {"model": args.model, "backend": args.backend, "effort": args.effort,
                "thinking": args.thinking, "max_tokens": args.max_tokens,
                "max_retries": args.retries}
    model = ClaudeForecaster(args.model, PROMPT.read_text(), backend=args.backend,
                             thinking_budget=thinking, effort=args.effort,
                             max_tokens=args.max_tokens, max_retries=args.retries)
    model.settings = settings  # pinned in run.json so a run cannot mix configurations
    name = args.model + (f"@{args.effort}" if args.effort else "")
    return model, name if args.backend == "api" else f"{name}+cli"


def _baselines(args):
    if args.baselines == "none":
        return {}
    from .baselines import BASELINES

    if args.baselines == "all":
        return dict(BASELINES)
    return {name: BASELINES[name] for name in args.baselines.split(",")}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opening_lab", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prefetch = commands.add_parser("prefetch", help="Cache SPY/QQQ bars and news for a date range (Alpaca reads only)")
    prefetch.add_argument("--start", required=True)
    prefetch.add_argument("--end", required=True)

    def model_options(p):
        p.add_argument("--model", required=True,
                       help=f"Claude model id (e.g. {DEFAULT_MODEL}); 'fake' for a free dry run; "
                            "'none' for baselines only")
        p.add_argument("--backend", choices=("api", "cli"), default="api",
                       help="api = Anthropic API key (billed); cli = claude -p on the Claude plan")
        p.add_argument("--thinking", choices=("adaptive", "off"), default="adaptive",
                       help="adaptive = the model decides how much to think (a 2,048-token budget "
                            "on older models); off = no thinking where the model allows")
        p.add_argument("--effort", choices=("low", "medium", "high", "max"), default="medium",
                       help="output effort; steers thinking depth on current models")
        p.add_argument("--max-tokens", type=int, default=8000)
        p.add_argument("--retries", type=int, default=2, help="SDK retries on 429/5xx (api backend)")
        p.add_argument("--fake", action="store_true", help="deterministic fake model (no calls)")
        p.add_argument("--baselines", default="all", help="'all', 'none' or a comma list")

    replay = commands.add_parser("replay", help="Replay historical sessions (resumable)")
    replay.add_argument("--run", required=True, type=Path)
    replay.add_argument("--start", required=True)
    replay.add_argument("--end", required=True)
    replay.add_argument("--variants", default=",".join(VARIANTS))
    replay.add_argument("--workers", type=int, default=4)
    replay.add_argument("--max-cost-usd", type=float, default=None,
                        help="cap on the run directory's TOTAL reported spend (required for --backend api)")
    replay.add_argument("--estimate", action="store_true", help="count calls and input size; call nothing")
    model_options(replay)

    report = commands.add_parser("report", help="Score a run directory")
    report.add_argument("--run", required=True, type=Path)

    live = commands.add_parser("live", help="One live morning (start before 09:30 ET)")
    live.add_argument("--run", required=True, type=Path)
    live.add_argument("--date", default=date.today().isoformat())
    live.add_argument("--variant", choices=VARIANTS, default="full")
    live.add_argument("--feed", choices=("sip", "iex"), default="sip")
    model_options(live)

    args = parser.parse_args(argv)
    log = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731

    if args.command == "prefetch":
        from .context import prefetch_news
        from .data import prefetch as prefetch_bars

        print(json.dumps({"bars": prefetch_bars(args.start, args.end),
                          "news": prefetch_news(args.start, args.end)}, indent=2, default=str))
        return 0

    if args.command == "report":
        from .runner import Run, write_report

        config = json.loads((args.run / "run.json").read_text())
        run = Run(args.run, config)
        days = sorted({row["date"] for row in run.rows()})
        if config["kind"] == "live":
            from .data import SessionUnavailable, load_session

            # Outcomes come from the completed session's historical bars.
            try:
                sessions = {d: load_session(d, fetch=True) for d in days}
            except SessionUnavailable as exc:
                parser.error(f"cannot score yet: {exc} (bars are final after 20:00 ET)")
        else:
            sessions = _sessions(days, log)
        print(write_report(run, sessions))
        return 0

    from .data import trading_days
    from .runner import estimate, live as run_live, replay as run_replay, write_report

    model, model_name = _model(args)
    baselines = _baselines(args)

    if args.command == "live":
        if model is None:
            parser.error("live needs a model")
        run_live(args.run, args.date, model=model, model_name=model_name, variant=args.variant,
                 feed=args.feed, baselines=baselines, log=log)
        log("Morning recorded. Score it after the close: report --run " + str(args.run))
        return 0

    variants = [v for v in args.variants.split(",") if v]
    unknown = set(variants) - set(VARIANTS)
    if unknown:
        parser.error(f"unknown variants: {sorted(unknown)}")
    days = trading_days(args.start, args.end)
    sessions = _sessions(days, log)
    days = [d for d in days if d in sessions]
    if not days:
        parser.error("no usable cached sessions in range; run prefetch first")

    paid = model is not None and not args.fake and args.backend == "api"
    if paid and not args.estimate and args.max_cost_usd is None:
        parser.error("a paid API replay needs --max-cost-usd (run --estimate first)")

    if args.estimate:
        if model is None:
            parser.error("--estimate needs a model")
        print(json.dumps({"sessions": len(days), **estimate(days, sessions, variants, model)}, indent=2))
        return 0

    run = run_replay(args.run, days, sessions=sessions, model=model, model_name=model_name,
                     variants=variants if model else [], baselines=baselines, workers=args.workers,
                     max_cost_usd=args.max_cost_usd, log=log)
    print(write_report(run, sessions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
