"""Read-only morning-brief research. Never imports the app or opens a writable DB.

See research/notes/morning-brief-scorecard.md for definitions and rerun commands.
Raw inputs and per-symbol results must stay in a private directory outside git.
"""
import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SYMBOL = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z])?$")
FIELDS = ("summary", "what_matters", "why_personal", "what_changed", "contrary_evidence", "watch_out", "entry_trigger", "invalidation", "timeframe")


def brief_key(brief):
    return hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()


def visible_text(body):
    items = [item for key in ("items", "opportunities", "urgent_positions") for item in body.get(key, [])]
    return " ".join([*(str(obj.get(key, "")) for obj in [body, *items] for key in FIELDS), *body.get("limitations", [])])


def stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def at(day, clock):
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(clock), ET)


def read_briefs(host, start, end):
    # Date objects, a fixed query and a read-only transaction; no app startup/migrations.
    query = f"""BEGIN READ ONLY;
    SELECT json_build_object('day',p.day,'saved_at',r.created_at,'body',r.body_json::json,
      'redacted',r.redacted_at IS NOT NULL OR p.redacted_at IS NOT NULL,
      'evidence',(SELECT coalesce(json_agg(e),'[]'::json)
        FROM json_array_elements(p.body_json::json->'evidence') e
        WHERE e->>'id' ~ '^(discovery-|market-|headline-)'))
    FROM morning_briefing_record r JOIN morning_briefing_packet p ON p.id=r.packet_id
    WHERE p.day >= DATE '{date.fromisoformat(start)}' AND p.day <= DATE '{date.fromisoformat(end)}'
    ORDER BY p.day,r.created_at,r.id; COMMIT;"""
    remote = shlex.join(["sudo", "-n", "-u", "postgres", "psql", "-X", "-qAt", "-d", "tradejournal",
                         "-v", "ON_ERROR_STOP=1", "-c", query])
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote],
                            capture_output=True, text=True, check=True)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def mentions(brief):
    """Explicit item symbols plus prose mentions from public packet market/news names.

    Do not infer ticker names from arbitrary all-caps English words or personal evidence.
    """
    body = brief["body"]
    items = [item for key in ("items", "opportunities", "urgent_positions") for item in body.get(key, [])]
    text = visible_text(body)
    names = {i["symbol"] for i in items if i.get("symbol") and SYMBOL.fullmatch(i["symbol"])}
    candidates = set(re.findall(r"\$([A-Z]{1,6}(?:\.[A-Z])?)\b", text))
    for row in brief.get("evidence", []):
        key = row["id"]
        if key.startswith(("market-", "discovery-")) and SYMBOL.fullmatch(key.split("-", 1)[1]):
            candidates.add(key.split("-", 1)[1])
        elif key.startswith("headline-"):
            candidates.update(s.strip() for s in row["text"].split(" — ")[0].split(",") if SYMBOL.fullmatch(s.strip()))
    names.update(s for s in candidates if re.search(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])", text))
    return sorted(names)


class Minutes:
    def __init__(self, root, cache=None, credentials=None):
        self.root, self.cache, self.credentials = Path(root), cache, credentials
        if cache and (Path(cache).name != "sip" or Path(cache).parent.name != "1Min"):
            raise ValueError("Existing minute cache must be stocks/1Min/sip")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.errors = {}

    def load(self, day, symbols):
        result, missing = {}, []
        for symbol in sorted(set(symbols)):
            if not SYMBOL.fullmatch(symbol):
                raise ValueError("Invalid symbol")
            local = self.root / f"{day}-{symbol}.json"
            cached = Path(self.cache) / symbol / f"{day}.json" if self.cache else None
            if local.exists():
                data = json.loads(local.read_text())
                if data.get("feed") != "sip" or data.get("adjustment") != "raw":
                    raise ValueError("Unverified minute provenance")
                result[symbol] = data["bars"]
            elif cached and cached.exists():
                # Existing alpaca_cache/stocks/1Min/sip contract is SIP/raw.
                result[symbol] = json.loads(cached.read_text())
            else:
                missing.append(symbol)
        if missing and self.credentials:
            import httpx
            from dotenv import dotenv_values
            config = dotenv_values(self.credentials)
            headers = {"APCA-API-KEY-ID": config.get("ALPACA_API_KEY", ""),
                       "APCA-API-SECRET-KEY": config.get("ALPACA_API_SECRET", "")}
            if not all(headers.values()):
                raise ValueError("Existing Alpaca credentials unavailable")
            params = dict(symbols=",".join(missing), timeframe="1Min", feed="sip", adjustment="raw", asof=day,
                          start=at(day, "09:30").isoformat(), end=at(day, "16:00").isoformat(), limit=10000, sort="asc")
            fetched = {s: [] for s in missing}
            tokens = set()
            for _ in range(100):
                response = httpx.get("https://data.alpaca.markets/v2/stocks/bars", headers=headers, params=params, timeout=30)
                if response.status_code != 200:
                    self.errors[day] = f"SIP HTTP {response.status_code}; no fallback or subscription change"
                    raise RuntimeError(self.errors[day])
                payload = response.json()
                for symbol, bars in payload["bars"].items():
                    if symbol in fetched:
                        fetched[symbol].extend(bars)
                token = payload.get("next_page_token")
                if not token:
                    break
                if token in tokens:
                    raise ValueError("Repeated pagination token")
                tokens.add(token)
                params["page_token"] = token
            else:
                raise ValueError("Minute pagination bound exceeded")
            for symbol, bars in fetched.items():
                if bars:
                    result[symbol] = bars
                    target = self.root / f"{day}-{symbol}.json"
                    target.write_text(json.dumps(dict(feed="sip", adjustment="raw", bars=bars)))
                    target.chmod(0o600)
        return result


def excess(bars, spy, day, end):
    """Open-to-end return minus SPY return, in percentage points. No fill-forward."""
    start, last = at(day, "09:30"), at(day, end) - timedelta(minutes=1)
    def prices(rows):
        indexed = {}
        for row in rows:
            when = stamp(row["t"])
            if when in indexed:
                raise ValueError("Duplicate minute")
            indexed[when] = row
        opening, closing = indexed.get(start), indexed.get(last)
        if not opening or not closing:
            return None
        values = [Decimal(str(opening["o"])), Decimal(str(closing["c"]))]
        if any(not v.is_finite() or v <= 0 for v in values):
            raise ValueError("Invalid price")
        # Classify exact rational returns: Decimal division alone can round an
        # exact 3pp difference just below 3 when prices have repeating quotients.
        return (Fraction(values[1]) / Fraction(values[0]) - 1) * 100
    own, benchmark = prices(bars), prices(spy)
    return None if own is None or benchmark is None else own - benchmark


def score(briefs, minutes, sessions, baselines, reviewed_mentions=None):
    results = []
    for brief in briefs:
        day = brief["day"]
        names = [] if brief.get("redacted") else mentions(brief)
        if reviewed_mentions is not None and not brief.get("redacted"):
            names = reviewed_mentions[brief_key(brief)]
            if len(set(names)) != len(names) or any(not SYMBOL.fullmatch(s) for s in names):
                raise ValueError("Invalid reviewed symbol list")
            names = sorted(names)
        baseline = baselines.get(day)
        if baseline:
            # Historical reconstructions retain distinct provenance in the public report.
            if (baseline["feed"] != "sip" or baseline["whole_market"] is not True
                    or stamp(baseline["as_of"]) != at(day, "09:00")
                    or not baseline.get("source")
                    or baseline.get("ranking_basis") != "pct_vs_prior_regular_close"
                    or len(baseline["gainers"]) != 10 or len(baseline["losers"]) != 10
                    or len(set(baseline["gainers"] + baseline["losers"])) != 20
                    or any(not SYMBOL.fullmatch(s) for s in baseline["gainers"] + baseline["losers"])):
                raise ValueError("Invalid 09:00 whole-market baseline")
        baseline_names = list(dict.fromkeys(baseline["gainers"] + baseline["losers"])) if baseline else []
        bars = minutes.load(day, names + baseline_names + ["SPY"]) if names or baseline_names else {}
        close = sessions.get(day)
        values = {s: [excess(bars.get(s, []), bars.get("SPY", []), day, end) if end else None
                      for end in ("10:30", close)] for s in names + baseline_names}
        results.append(dict(day=day, saved_at=brief["saved_at"], redacted=bool(brief.get("redacted")),
                            eligible=stamp(brief["saved_at"]) < at(day, "09:30"),
                            values={s: values[s] for s in names}, baseline={s: values[s] for s in baseline_names},
                            baseline_source=(baseline["source"] if baseline["source"] in ("contemporaneous", "reconstructed-sip")
                                             else "archived") if baseline else None,
                            overlap=len(set(names) & set(baseline_names)),
                            error=minutes.errors.get(day), session=close))
    return results


def ratio(values, horizon):
    complete = [v[horizon] for v in values.values() if v[horizon] is not None]
    return f"{sum(abs(v) >= 3 for v in complete)}/{len(complete)}" if complete else "unavailable"


def render_week(week, results, sessions, start, end):
    rows = [r for r in results if week <= r["day"] <= (date.fromisoformat(week) + timedelta(days=6)).isoformat()]
    cutoff = min(end, (date.fromisoformat(week) + timedelta(days=4)).isoformat())
    eligible = [r for r in rows if r["eligible"] and not r["redacted"]]
    pooled = {f"{i}/{s}": v for i, r in enumerate(eligible) for s, v in r["values"].items()}
    lines = [f"## Week of {week} (through {cutoff})", "", f"{len(rows)} saved versions; {len(eligible)} available before 09:30. Late versions are descriptive only.",
             f"Morning-available ticker mentions: ≥3pp first hour {ratio(pooled, 0)}; session {ratio(pooled, 1)}. Repeated mentions across days count separately.", "",
             "| Day / version | Saved ET | Morning eligible | Named | ≥3pp first hour | ≥3pp session | Baseline hour / session | Gappers mentioned / catalyst assessment |",
             "|---|---|---|---:|---|---|---|---|"]
    counts = {}
    for r in rows:
        day = r["day"]
        counts[day] = counts.get(day, 0) + 1
        saved = stamp(r["saved_at"]).astimezone(ET).strftime("%H:%M:%S")
        baseline = f"{ratio(r['baseline'], 0)} / {ratio(r['baseline'], 1)}" if r["baseline"] else "unavailable"
        if r["baseline"]:
            baseline += f" ({r['baseline_source']})"
        coverage = f"{r['overlap']}/20 / unavailable" if r["baseline"] else "unavailable"
        lines.append(f"| {day} / {counts[day]} | {saved} | {'redacted' if r['redacted'] else 'yes' if r['eligible'] else 'late'} | {len(r['values'])} | {ratio(r['values'], 0)} | {ratio(r['values'], 1)} | {baseline} | {coverage} |")
    missing = [d for d in sessions if week <= d <= min(end, (date.fromisoformat(week) + timedelta(days=6)).isoformat())
               and d >= start and d not in counts]
    lines.extend(["", "No saved brief on confirmed sessions: " + (", ".join(missing) or "none") + "."])
    gaps = sorted({r['error'] for r in rows if r['error']})
    if any(not r["session"] for r in rows):
        gaps.append("Session close unavailable; full-session scores withheld.")
    if any(not r["baseline"] for r in rows):
        gaps.append("Archived whole-market 09:00 SIP top-10 gainers AND top-10 losers unavailable: baseline, gapper coverage and catalyst coverage unscored.")
    lines.extend(["", *[f"- Gap: {g}" for g in gaps], ""])
    return "\n".join(lines)


def append_weeks(output, results, sessions, start, end):
    existing = output.read_text() if output.exists() else "# Morning brief scorecard\n\n"
    week = date.fromisoformat(start)
    week -= timedelta(days=week.weekday())
    while week <= date.fromisoformat(end):
        label = week.isoformat()
        section = render_week(label, results, sessions, start, end)
        cutoff = min(end, (week + timedelta(days=4)).isoformat())
        heading = f"## Week of {label} (through {cutoff})\n"
        if heading in existing:
            old = existing.split(heading, 1)[1].split("\n## ", 1)[0]
            if (heading + old).strip() != section.strip():
                raise ValueError(f"Week {label} already exists with different evidence; preserve it and append an explicitly reviewed correction")
        else:
            existing = existing.rstrip() + "\n\n" + section
        week += timedelta(days=7)
    output.write_text(existing)


def append_baselines(output, results, start, end):
    """Append an aggregate-only supplement to the original, immutable weekly tables."""
    existing = output.read_text()
    heading = f"## Baseline supplement {start} through {end}"
    lines = [heading, "", "Morning-available versions with a baseline, pooled on the same dates and versions.",
             "Each cell counts hits over tickers with both endpoints. Repeated mentions count again.", "",
             "| Week of | Timely versions compared | Brief first hour | Baseline first hour | Brief session | Baseline session |",
             "|---|---:|---:|---:|---:|---:|"]
    by_week = {}
    for row in results:
        day = date.fromisoformat(row["day"])
        week = day - timedelta(days=day.weekday())
        by_week.setdefault(week, [])
        if row["eligible"] and not row["redacted"] and row["baseline"]:
            by_week[week].append(row)
    for week, rows in sorted(by_week.items()):
        briefs = {(i, s): v for i, row in enumerate(rows) for s, v in row["values"].items()}
        baselines = {(i, s): v for i, row in enumerate(rows) for s, v in row["baseline"].items()}
        lines.append(f"| {week} | {len(rows)} | {ratio(briefs, 0)} | {ratio(baselines, 0)} | "
                     f"{ratio(briefs, 1)} | {ratio(baselines, 1)} |")
    lines.extend(["", "| Day / version | Source | Baseline ≥3pp first hour | Baseline ≥3pp session | Gappers mentioned |",
                  "|---|---|---:|---:|---:|"])
    counts = {}
    for row in results:
        day = row["day"]
        counts[day] = counts.get(day, 0) + 1
        values = row["baseline"]
        source = row["baseline_source"] or "unavailable"
        overlap = f"{row['overlap']}/20" if values and not row["redacted"] else "unavailable"
        lines.append(f"| {day} / {counts[day]} | {source} | {ratio(values, 0)} | {ratio(values, 1)} | {overlap} |")
    section = "\n".join(lines)
    if heading in existing:
        old = existing.split(heading, 1)[1].split("\n## ", 1)[0]
        if (heading + old).strip() != section:
            raise ValueError("Baseline supplement exists with different evidence")
    else:
        output.write_text(existing.rstrip() + "\n\n" + section + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--briefs", type=Path, help="Private JSONL export")
    source.add_argument("--ssh-host", help="Existing production SSH alias, SELECT-only")
    parser.add_argument("--start", default="2026-10-19")
    parser.add_argument("--end", required=True)
    parser.add_argument("--sessions", type=Path, help="JSON {session-date: regular-close-HH:MM}; exchange calendar")
    parser.add_argument("--baselines", type=Path, help="Private JSON keyed by date; archived 09:00 SIP ranking")
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--export-only", action="store_true", help="Save private briefs for a manual ticker audit; no scores or provider calls")
    parser.add_argument("--mentions", type=Path, help="Private JSON: SHA256 of each complete exported brief -> all reviewed visible ticker symbols")
    parser.add_argument("--sip-cache", type=Path, help="Existing alpaca_cache/stocks/1Min/sip root, read-only")
    parser.add_argument("--credentials", type=Path, help="Existing .env; only Alpaca market-data keys are used; enables GETs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--append-baselines", action="store_true", help="Append baseline columns for existing weeks")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("start must not follow end")
    root = args.private_dir.resolve()
    repository = Path(__file__).resolve().parents[2]
    if root.is_relative_to(repository):
        parser.error("Private inputs/results must stay outside the repository")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    briefs = read_briefs(args.ssh_host, args.start, args.end) if args.ssh_host else [json.loads(s) for s in args.briefs.read_text().splitlines() if s.strip()]
    briefs = [b for b in briefs if args.start <= b["day"] <= args.end]
    export = root / f"briefs-{args.start}-{args.end}.jsonl"
    export.write_text("\n".join(json.dumps(b) for b in briefs))
    export.chmod(0o600)
    if args.export_only:
        print(f"Exported {len(briefs)} versions privately; review all visible text and key symbol lists by brief_key().")
        return
    if not args.mentions:
        parser.error("--mentions is required: audit all visible ticker mentions before scoring")
    if not args.sessions or not args.output:
        parser.error("--sessions and --output are required for scoring")
    sessions = json.loads(args.sessions.read_text())
    baselines = json.loads(args.baselines.read_text()) if args.baselines else {}
    minutes = Minutes(root / "sip", args.sip_cache, args.credentials)
    results = score(briefs, minutes, sessions, baselines, json.loads(args.mentions.read_text()))
    private = root / f"scores-{args.start}-{args.end}.json"
    private.write_text(json.dumps(dict(input_sha256=hashlib.sha256(json.dumps(briefs, sort_keys=True).encode()).hexdigest(), results=results), default=str, indent=2))
    private.chmod(0o600)
    if args.append_baselines:
        if not baselines:
            parser.error("--append-baselines requires --baselines")
        append_baselines(args.output, results, args.start, args.end)
    else:
        append_weeks(args.output, results, sessions, args.start, args.end)
    print(f"{len(results)} saved versions scored; {sum(not r['eligible'] for r in results)} late; "
          f"{sum(bool(r['baseline']) for r in results)} with baseline; {len(minutes.errors)} SIP failures")


if __name__ == "__main__":
    main()
