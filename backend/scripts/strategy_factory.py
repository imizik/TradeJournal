"""
The strategy factory: judge candidate strategies automatically and record them.

A candidate is a JSON spec (a family of entry rules from
`app/engine/factory_rules.py` plus its settings, exits, costs and filters,
and optionally a learned filter). `run` puts one through the gates in
`app/engine/factory_gates.py` (a screen on the discovery period, confirmation
on later data with a bar that rises with every candidate tried, a one-time
exam on the locked holdout) and appends the result to `research/ledger.jsonl`.
`week` is the weekly loop: the idea model proposes up to three candidates from
a brief (`app/engine/factory_brief.py`), they are judged, and the week's
report goes to `research/reports/`; `notify` sends its summary to the phone.
The idea model is Claude through the API, or, with `--answer`, a Claude Code
session that answered the brief `--dry-run` wrote (`/factory-week`).
See docs/strategy-factory.md.

The live ledger is on branch factory/ledger, in the factory checkout
(`scripts/factory_week.sh` runs there weekly); `run` and `week` refuse to write
the default ledger from any other branch. Bars are Alpaca SIP minute bars from
the local cache: `prepare` fills it and needs the Alpaca key, `week` calls
Claude and needs the Anthropic key (not with `--answer`), `notify` needs
FACTORY_NTFY_URL, and `run` and `ledger` never touch the network.

Usage:
    python scripts/strategy_factory.py prepare
    python scripts/strategy_factory.py run ../research/specs/recovery_swing_v0.1.json
    python scripts/strategy_factory.py week [--dry-run [--brief-out FILE]] [--answer FILE] [--budget N]
    python scripts/strategy_factory.py notify
    python scripts/strategy_factory.py ledger
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
import os
import pickle
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.factory_brief import (  # noqa: E402
    IDEAS_SCHEMA,
    answer_problem,
    LESSON_WEEKS,
    SYSTEM_PROMPT,
    WEEKLY_BUDGET,
    brief,
    evidence,
    lessons_from,
    review,
    spec_file,
    weekly_report,
)
from app.engine.factory_data import FEATURES, Series, session_bars  # noqa: E402
from app.engine.factory_gates import (  # noqa: E402
    Evaluation,
    discovery_forward,
    evaluate,
    ledger_record,
    period_of,
    prior_candidates,
    report,
    required_t,
    signal_day,
)
from app.engine.factory_rules import (  # noqa: E402
    CORE_UNIVERSE,
    FAMILIES,
    MARKET,
    Spec,
    Trade,
    from_canonical,
    parse_spec,
    spec_id,
)
from app.engine.market_map import ET, Bar, bars_from_alpaca, resample  # noqa: E402

RESEARCH = REPO_ROOT / "research"
LEDGER = RESEARCH / "ledger.jsonl"
FACTORY_BRANCH = "factory/ledger"
DATA_START = date(2023, 6, 1)
CACHE_VERSION = 1
# The engine code discovery evidence depends on; a change to any of it recomputes the evidence.
EVIDENCE_MODULES = ("factory_data", "factory_rules", "factory_gates", "factory_brief", "market_map")
DEFAULT_OUT = BACKEND_ROOT / "data" / "factory"
IDEA_MODEL = "claude-opus-5"


class MinuteSource(Protocol):
    """Where minute bars come from: Alpaca's cache, or a stub in tests."""

    feed: str

    def days(self, ticker: str) -> list[date]: ...

    def minute_bars(self, ticker: str, day: date) -> list[dict]: ...


class AlpacaCache:
    """The minute bars `app.engine.alpaca` has cached on disk. Reads only."""

    def __init__(self) -> None:
        from app.engine import alpaca

        self.alpaca = alpaca
        self.feed = alpaca.ALPACA_DATA_FEED
        self.root = alpaca.CACHE_DIR / "stocks" / "1Min" / self.feed

    def days(self, ticker: str) -> list[date]:
        folder = self.root / ticker
        if not folder.is_dir():
            return []
        return sorted(date.fromisoformat(path.stem) for path in folder.glob("*.json"))

    def minute_bars(self, ticker: str, day: date) -> list[dict]:
        return self.alpaca.fetch_minute_bars_for_date([ticker], day, cache_only=True).get(ticker, [])


class BarStore:
    """Session bars per ticker and timeframe, built once from the minute cache
    and kept as a pickle under `data/factory/bars/`, rebuilt when the minute
    cache has newer days. `load` cuts them at a day and builds the `Series`."""

    def __init__(self, source: MinuteSource, root: Path, progress: Callable[[str], None] = lambda _: None):
        self.source = source
        self.root = root / "bars" / source.feed
        self.progress = progress
        self.memory: dict[tuple[str, int], list[Bar]] = {}
        self.requests: list[tuple[str, int, date | None]] = []

    def _bars(self, ticker: str, timeframe: int) -> list[Bar]:
        key = (ticker, timeframe)
        if key in self.memory:
            return self.memory[key]
        days = [day for day in self.source.days(ticker) if day >= DATA_START]
        path = self.root / f"{ticker}_{timeframe}m.pkl"
        through = days[-1] if days else None
        rows = None
        if path.exists():
            with path.open("rb") as handle:
                cached = pickle.load(handle)
            if cached.get("version") == CACHE_VERSION and cached.get("through") == through:
                rows = cached["bars"]
        if rows is None:
            self.progress(f"  building {ticker} {timeframe}-minute bars from {len(days)} days of minute bars")
            minutes = []
            for day in days:
                minutes += session_bars(bars_from_alpaca(self.source.minute_bars(ticker, day)))
            bars = resample(minutes, timeframe)
            rows = [(bar.time.timestamp(), bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                pickle.dump({"version": CACHE_VERSION, "through": through, "bars": rows}, handle)
        bars = [Bar(datetime.fromtimestamp(row[0], timezone.utc), *row[1:]) for row in rows]
        if timeframe >= 5:
            self.memory[key] = bars
        return bars

    def last_day(self, ticker: str) -> date | None:
        days = self.source.days(ticker)
        return days[-1] if days else None

    def load(self, ticker: str, timeframe: int, through: date | None) -> Series | None:
        self.requests.append((ticker, timeframe, through))
        bars = self._bars(ticker, timeframe)
        if through is not None:
            bars = [bar for bar in bars if bar.time.astimezone(ET).date() <= through]
        return Series.build(ticker, bars, timeframe) if bars else None


# --- the ledger and the repository -----------------------------------------------


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_ledger(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=False) + "\n")


def _git(*command: str) -> str:
    return subprocess.run(["git", *command], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def code_version() -> str:
    try:
        head = _git("rev-parse", "--short", "HEAD")
        dirty = _git("status", "--porcelain", "--", "backend/app/engine", "backend/scripts/strategy_factory.py")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("-dirty" if dirty else "")


def check_live_ledger(args: argparse.Namespace) -> None:
    """The live ledger is on the factory branch. Main keeps an older copy, and
    writing to it from anywhere else would fork the count the bar rests on."""
    if args.ledger != LEDGER:
        return
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        branch = ""
    if branch != FACTORY_BRANCH:
        raise SystemExit(
            f"The live ledger is on branch {FACTORY_BRANCH}, in the factory checkout "
            f"(docs/strategy-factory.md); this checkout is on {branch or 'no branch'}. "
            f"Run there, or pass --ledger for a scratch ledger."
        )


def github_url(path: Path, branch: str = FACTORY_BRANCH) -> str | None:
    """The GitHub page of a file in this repository on `branch`, or None when
    the file is outside the repository or origin is not on GitHub."""
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
        remote = _git("remote", "get-url", "origin")
    except (ValueError, OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
    return f"https://github.com/{match.group(1)}/blob/{branch}/{relative}" if match else None


def trades_csv(trades: list[Trade]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    names = list(FEATURES)
    writer.writerow(["ticker", "period", "side", "signal_time", "entry_time", "entry_price", "stop", "target",
                     "exit_time", "exit_price", "exit_reason", "r", "sessions_held", *names])
    for t in sorted(trades, key=lambda t: (t.entry_time, t.ticker)):
        writer.writerow([
            t.ticker, period_of(signal_day(t)), "long" if t.side == 1 else "short",
            t.signal_time.astimezone(ET).isoformat(), t.entry_time.astimezone(ET).isoformat(), t.entry_price,
            t.stop, t.target, t.exit_time.astimezone(ET).isoformat() if t.exit_time else "", t.exit_price,
            t.exit_reason, round(t.r, 4), t.sessions_held,
            *[round(t.features.get(name, float("nan")), 4) for name in names],
        ])
    return out.getvalue()


def load_spec(path: Path) -> Spec:
    return parse_spec(json.loads(path.read_text()))


# --- judging ----------------------------------------------------------------------


def run_one(spec: Spec, store: BarStore, ledger: Path, out: Path, exam: bool,
            progress: Callable[[str], None], batch: str | None = None) -> tuple[Evaluation, dict, Path]:
    records = read_ledger(ledger)
    ev = evaluate(spec, store.load, prior_candidates(records, excluding=spec_id(spec)), exam=exam, progress=progress)
    now = datetime.now(ET)
    record = ledger_record(ev, now, code_version(), store.last_day(MARKET), batch)
    append_ledger(ledger, record)
    run_dir = out / "runs" / f"{now:%Y%m%d-%H%M%S}-{ev.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.txt").write_text(report(ev) + "\n")
    # One file per period, so mining for ideas can keep to the discovery trades.
    for period in ("discovery", "confirm", "holdout"):
        chosen = [t for t in ev.trades if (period_of(signal_day(t)) or "").startswith(period)]
        if chosen:
            (run_dir / f"trades_{period}.csv").write_text(trades_csv(chosen))
    return ev, record, run_dir


def command_run(args: argparse.Namespace, store: BarStore, progress: Callable[[str], None]) -> int:
    check_live_ledger(args)
    spec = load_spec(args.spec)
    records = read_ledger(args.ledger)
    # Hand-research lines share an id with the spec they describe, so a spec
    # tried by hand still runs here once; it is counted once either way.
    known = {record["id"]: record for record in records if record.get("source") == "factory"}
    queue = [spec]
    parent = spec.parent()
    if parent is not None and spec_id(parent) not in known:
        # The model learns from the rules without it, and looking at those
        # rules is a trial of its own, so they are judged and counted first.
        queue.insert(0, parent)
    for candidate in queue:
        identifier = spec_id(candidate)
        if identifier in known and not args.rerun:
            print(f"{identifier} ({candidate.name}) is already in the ledger: {known[identifier]['verdict']}. "
                  f"Use --rerun to run it again.")
            continue
        progress(f"{candidate.name} ({identifier})")
        ev, _, run_dir = run_one(candidate, store, args.ledger, args.out, not args.no_exam, progress)
        print(report(ev))
        print(f"\nWrote {run_dir} and a line in {args.ledger}", file=sys.stderr)
    count = prior_candidates(read_ledger(args.ledger))
    print(f"\nThe ledger counts {count} candidates at confirmation; the next one there needs "
          f"t >= {required_t(count + 1):.2f}.")
    return 0


# --- the weekly loop -----------------------------------------------------------------

Proposer = Callable[[str, str], tuple[dict[str, Any], str]]


def claude_proposer(system: str, text: str) -> tuple[dict[str, Any], str]:
    """Ask the idea model for this week's candidates; returns its answer and a usage note."""
    import anthropic

    model = os.environ.get("FACTORY_MODEL", IDEA_MODEL)
    client = anthropic.Anthropic()
    try:
        # Streaming, because adaptive thinking on a long brief can outlast a plain request.
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=system,
            messages=[{"role": "user", "content": text}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": IDEAS_SCHEMA}},
            # A policy decline is re-run on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise SystemExit(f"The Anthropic key was refused: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise SystemExit(f"The Anthropic API is rate-limiting this key; try again later: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise SystemExit(f"The Anthropic API returned {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise SystemExit(f"Could not reach the Anthropic API: {exc}") from exc
    if message.stop_reason == "refusal":
        category = getattr(message.stop_details, "category", None) if message.stop_details else None
        raise SystemExit(f"The idea model declined this week's brief (category {category}); nothing was run.")
    if message.stop_reason == "max_tokens":
        raise SystemExit("The idea model ran out of room before answering; nothing was run.")
    answer = json.loads(next(block.text for block in message.content if block.type == "text"))
    usage = message.usage
    return answer, f"{message.model}, {usage.input_tokens:,} tokens in and {usage.output_tokens:,} out"


def answer_file(path: Path, author: str) -> Proposer:
    """The idea model's answer from a file a Claude Code session wrote after
    reading the brief (`/factory-week`), instead of one asked for through the API."""

    def propose(system: str, text: str) -> tuple[dict[str, Any], str]:
        try:
            answer = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Could not read the answer in {path}: {exc}") from exc
        problem = answer_problem(answer)
        if problem:
            raise SystemExit(f"The answer in {path} does not fit the format: {problem}. Nothing was run.")
        return answer, f"{author} in a Claude Code session, no API call"

    return propose


def week_start(day: date) -> date:
    """The Sunday a day's week starts on. The factory's weeks run Sunday to
    Saturday, so each Sunday run opens a new one."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def used_this_week(records: list[dict], day: date) -> int:
    """Candidates the weekly runs added in `day`'s week. Lines from before the
    weeks started on Sunday carry their Monday, which falls in the same week."""
    start = week_start(day)
    return sum(1 for record in records
               if record.get("batch") and start <= date.fromisoformat(record["batch"]) < start + timedelta(days=7))


def report_stem(reports: Path, day: date) -> str:
    """A run's report name: its day, then b, c and on for more runs that day, so none is overwritten."""
    stem, letters = day.isoformat(), iter("bcdefghijklmnopqrstuvwxyz")
    while (reports / f"{stem}.md").exists():
        stem = day.isoformat() + next(letters)
    return stem


def engine_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in EVIDENCE_MODULES:
        digest.update(Path(importlib.import_module(f"app.engine.{name}").__file__).read_bytes())
    return digest.hexdigest()[:10]


def gather_evidence(records: list[dict], store: BarStore, out: Path,
                    progress: Callable[[str], None]) -> dict[str, dict]:
    """Discovery evidence for each family at its defaults and for the three most
    recent ideas the factory judged. Discovery data never changes, so it is
    cached by id and by the engine code that computed it."""
    wanted: dict[str, Spec] = {name: parse_spec({"family": name}) for name in FAMILIES}
    judged = [r for r in records if r.get("source") == "factory" and not (r.get("spec") or {}).get("model")]
    defaults = {spec_id(spec) for spec in wanted.values()}
    recent: dict[str, dict] = {}
    for record in reversed(judged):
        if record["id"] not in defaults and record["id"] not in recent:
            recent[record["id"]] = record
        if len(recent) == 3:
            break
    for identifier, record in reversed(list(recent.items())):
        wanted[identifier] = from_canonical(record["spec"], record["name"])
    found: dict[str, dict] = {}
    fingerprint = engine_fingerprint()
    for key, spec in wanted.items():
        identifier = spec_id(spec)
        path = out / "evidence" / f"{identifier}-{fingerprint}.json"
        if path.exists():
            found[key] = json.loads(path.read_text())
            continue
        progress(f"  discovery evidence for {key}")
        trades, forward = discovery_forward(spec, store.load)
        found[key] = {"name": spec.name, **evidence(trades), "forward": forward}
        path.parent.mkdir(parents=True, exist_ok=True)
        for stale in path.parent.glob(f"{identifier}-*.json"):
            stale.unlink()
        path.write_text(json.dumps(found[key], indent=1))
    return found


def recent_lessons(reports: Path, weeks: int = LESSON_WEEKS) -> list[tuple[str, str]]:
    lessons = []
    for path in sorted(reports.glob("*.md"))[-weeks:]:
        text = lessons_from(path.read_text())
        if text:
            lessons.append((path.stem, text))
    return lessons


def command_week(args: argparse.Namespace, store: BarStore, progress: Callable[[str], None],
                 proposer: Proposer) -> int:
    check_live_ledger(args)
    today = datetime.now(ET).date()
    batch = week_start(today).isoformat()
    records = read_ledger(args.ledger)
    budget = WEEKLY_BUDGET - used_this_week(records, today) if args.budget is None else args.budget
    if budget <= 0:
        print(f"This week's budget of {WEEKLY_BUDGET} candidates is already used; nothing to do. "
              "`week --budget N` runs N more anyway.")
        return 0
    progress("gathering discovery evidence")
    found = gather_evidence(records, store, args.out, progress)
    count = prior_candidates(records)
    text = brief(today, records, found, recent_lessons(args.reports), budget, required_t(count + 1), count)
    if args.dry_run:
        if args.brief_out is not None:
            args.brief_out.write_text(SYSTEM_PROMPT + "\n\n" + text)
            print(f"The brief for up to {budget} candidates is in {args.brief_out}.")
        else:
            print(SYSTEM_PROMPT + "\n\n" + text)
        return 0

    progress(f"asking the idea model for up to {budget} candidates")
    answer, usage = proposer(SYSTEM_PROMPT, text)
    proposals = review(answer, {record["id"] for record in records}, budget)
    run_records: dict[str, dict] = {}
    stem = report_stem(args.reports, today)
    spec_dir = args.specs / stem
    for proposal in proposals:
        if proposal.spec is None:
            progress(f"refused: {proposal.title}: {proposal.problem}")
            continue
        name, data = spec_file(proposal)
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / name).write_text(json.dumps(data, indent=2) + "\n")
        parent = proposal.spec.parent()
        queue = ([parent] if parent is not None and spec_id(parent) not in {r["id"] for r in read_ledger(args.ledger)}
                 else []) + [proposal.spec]
        for candidate in queue:
            progress(f"judging {candidate.name} ({spec_id(candidate)})")
            try:
                _, record, _ = run_one(candidate, store, args.ledger, args.out, True, progress, batch=batch)
            except Exception as exc:  # one candidate that cannot be judged must not stop the week
                proposal.problem = f"it could not be judged: {type(exc).__name__}: {exc}"
                progress(proposal.problem)
                break
            run_records[record["id"]] = record
    after = read_ledger(args.ledger)
    count = prior_candidates(after)
    ledger_note = (f"The ledger holds {len({r['id'] for r in after})} ideas; {count} have reached confirmation, "
                   f"so the next one there needs t >= {required_t(count + 1):.2f}.")
    footer = f"Idea model: {usage}. Code {code_version()}; bars through {store.last_day(MARKET)}."
    markdown, summary = weekly_report(today, proposals, run_records, answer, ledger_note, footer)
    args.reports.mkdir(parents=True, exist_ok=True)
    (args.reports / f"{stem}.md").write_text(markdown)
    passed = any(record["verdict"] in ("passed", "awaiting_exam", "passed_confirmation") for record in run_records.values())
    (args.reports / f"{stem}.json").write_text(json.dumps(
        {"day": today.isoformat(), "summary": summary, "passed": passed, "answer": answer}, indent=2) + "\n")
    print(markdown)
    return 0


def publish(url: str, token: str | None, title: str, message: str, click: str | None, priority: int,
            tags: list[str]) -> None:
    """ntfy's JSON form, the way deploy/alerts.py sends the server's alerts."""
    target = urlsplit(url)
    body: dict[str, Any] = {"topic": target.path.strip("/"), "title": title, "message": message,
                            "priority": priority, "tags": tags}
    if click:
        body["click"] = click
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{target.scheme}://{target.netloc}/", data=json.dumps(body).encode(), headers=headers,
                      method="POST")
    with urlopen(request, timeout=15):
        pass


def command_notify(args: argparse.Namespace, sender: Callable[..., None] = publish) -> int:
    url = os.environ.get("FACTORY_NTFY_URL")
    if not url:
        raise SystemExit("FACTORY_NTFY_URL is not set (backend/.env); nothing was sent.")
    token = os.environ.get("FACTORY_NTFY_TOKEN") or None
    if args.failure:
        sender(url, token, "Strategy factory: the weekly run failed", args.failure, None, 4, ["warning"])
        return 0
    latest = sorted(args.reports.glob("*.json"))
    if not latest:
        raise SystemExit(f"No weekly report in {args.reports}; nothing was sent.")
    week = json.loads(latest[-1].read_text())
    report_path = latest[-1].with_suffix(".md")
    sender(url, token, f"Strategy factory, week of {week['day']}", week["summary"], github_url(report_path),
           5 if week["passed"] else 3, ["tada"] if week["passed"] else ["chart_with_upwards_trend"])
    return 0


# --- other commands ------------------------------------------------------------------


def command_ledger(args: argparse.Namespace) -> int:
    records = read_ledger(args.ledger)
    for record in records:
        periods = record.get("periods") or {}
        numbers = []
        for name in ("discovery", "confirm", "holdout"):
            stats = periods.get(name)
            if stats and stats.get("n"):
                edge_t = stats.get("edge_t")
                numbers.append(f"{name} {stats['n']} trades {stats['mean_r']:+.3f}R"
                               + (f" t={edge_t:.2f}" if edge_t is not None else ""))
        print(f"{record['id']:20s} {record['verdict']:20s} {record['name']}")
        if numbers or record.get("summary"):
            print(f"{'':20s} {'; '.join(numbers) or record.get('summary')}")
    count = prior_candidates(records)
    print(f"\n{len(records)} lines, {len({r['id'] for r in records})} distinct ideas, {count} reached confirmation; "
          f"the next one there needs t >= {required_t(count + 1):.2f}.")
    return 0


def days_to_fetch(cached: dict[str, list[date]], through: date) -> dict[date, list[str]]:
    """The tickers missing each weekday up to `through`.

    A ticker that listed after DATA_START (NBIS) starts at its first cached
    day. A weekday inside the market's cached range with no market bars was a
    holiday: nothing is cached for it, so without this it would be asked for
    again every week.
    """
    market = set(cached.get(MARKET, []))
    market_last = max(market) if market else None
    wanted: dict[date, list[str]] = {}
    for ticker, days in cached.items():
        have = set(days)
        day = min(have) if have else DATA_START
        while day <= through:
            closed = market_last is not None and day <= market_last and day not in market
            if day.weekday() < 5 and day not in have and not closed:
                wanted.setdefault(day, []).append(ticker)
            day += timedelta(days=1)
    return dict(sorted(wanted.items()))


def command_prepare(args: argparse.Namespace, progress: Callable[[str], None]) -> int:
    from app.engine import alpaca

    if not alpaca.alpaca_configured():
        raise SystemExit("ALPACA_API_KEY and ALPACA_API_SECRET are not set; prepare fetches bars and needs them.")
    cache = AlpacaCache()
    through = args.through or (datetime.now(ET).date() - timedelta(days=1))
    wanted = days_to_fetch({ticker: cache.days(ticker) for ticker in dict.fromkeys([*args.tickers, MARKET])}, through)
    progress(f"{len(wanted)} days to fetch, {sum(map(len, wanted.values()))} ticker-days")
    for index, (day, tickers) in enumerate(wanted.items(), start=1):
        alpaca.fetch_minute_bars_for_date(tickers, day)  # one request per day for every ticker missing it
        if index % 20 == 0:
            progress(f"  {index}/{len(wanted)}")
    return 0


def _at_least_one(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(
    argv: list[str] | None = None,
    source_factory: Callable[[], MinuteSource] | None = None,
    proposer: Proposer | None = None,
    sender: Callable[..., None] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--feed", choices=("iex", "sip"), default="sip", help="the Alpaca feed (default sip)")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reports", type=Path, default=RESEARCH / "reports")
    parser.add_argument("--specs", type=Path, default=RESEARCH / "specs", help="where the weekly run saves its specs")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="judge a spec and record it in the ledger")
    run.add_argument("spec", type=Path)
    run.add_argument("--rerun", action="store_true", help="run a spec that is already in the ledger again")
    run.add_argument("--no-exam", action="store_true", help="stop after confirmation, holdout untouched")
    week = sub.add_parser("week", help="the weekly loop: propose, judge, report (asks Claude through the API "
                                       "unless given --answer)")
    week.add_argument("--dry-run", action="store_true", help="print the brief the idea model would get, and stop")
    week.add_argument("--brief-out", type=Path, help="with --dry-run, write the brief to this file instead")
    week.add_argument("--answer", type=Path, help="the idea model's answer as JSON, written by a Claude Code "
                                                  "session from the brief (/factory-week); no API call")
    week.add_argument("--answer-by", default="Claude", help="who wrote --answer, for the report")
    week.add_argument("--budget", type=_at_least_one, help="candidates this run may add, in place of what is left "
                                                            "of this week's three (a run you ask for)")
    notify = sub.add_parser("notify", help="send the latest weekly summary to the phone (needs FACTORY_NTFY_URL)")
    notify.add_argument("--failure", help="send this failure message instead")
    sub.add_parser("ledger", help="list the ledger and the current bar")
    prepare = sub.add_parser("prepare", help="fetch the minute bars the factory needs (needs the Alpaca key)")
    prepare.add_argument("--tickers", nargs="+", default=[*CORE_UNIVERSE, MARKET])
    prepare.add_argument("--through", type=date.fromisoformat)
    args = parser.parse_args(argv)

    os.environ["ALPACA_DATA_FEED"] = args.feed
    asks_the_api = proposer is None and not getattr(args, "dry_run", False) and getattr(args, "answer", None) is None
    real_run = {"prepare": True, "week": asks_the_api, "notify": sender is None}.get(args.command, False)
    if real_run:
        # Keys and the ntfy topic live in backend/.env. Tests inject a proposer
        # and a sender instead, so they never read it.
        from app.environment import load_env_files

        load_env_files()

    def progress(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    if args.command == "ledger":
        return command_ledger(args)
    if args.command == "prepare":
        return command_prepare(args, progress)
    if args.command == "notify":
        return command_notify(args, sender or publish)
    store = BarStore((source_factory or AlpacaCache)(), args.out, progress)
    if args.command == "week":
        chosen = proposer or (answer_file(args.answer, args.answer_by) if args.answer else claude_proposer)
        return command_week(args, store, progress, chosen)
    return command_run(args, store, progress)


if __name__ == "__main__":
    raise SystemExit(main())
