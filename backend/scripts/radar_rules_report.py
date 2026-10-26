"""Compare Radar rule versions on a store snapshot and write a Markdown report.

Read-only and offline: opens the file in SQLite read-only mode, replays every recorded session through each
rule version (``radar_rules.VERSIONS``; default all of them) with the current tracked list, and writes:

- per session and version, events by rule (vs SPY up/down, vs sector, group up/down), revisions, and two
  outcome counts: ``quick fade`` (faded or reversed within 15 minutes of the first sighting, the noise
  proxy) and ``extended`` (grew at least once);
- for each version other than v0, every threshold it changes and that change's effect alone;
- the distribution of 30-minute readings near each threshold, and how many held on 2 or 3 passes in a row;
- the events each version adds or drops relative to v0 (matched by kind, symbol or group, direction and
  count), and how much earlier or later the shared ones fire;
- when the store holds ratings, how events rated useful and not useful fall under each version: an event
  survives a version when that version fires the same kind, subject and direction within 30 minutes.

The output depends only on the snapshot and the code (no clock, no network). ``--try field=value[,...]``
adds an ad hoc variant of v0 to the comparison.

    python scripts/radar_rules_report.py /abs/snapshot.sqlite [--rules v0 --rules v1] [--try spy_relative_pct=3.5]
        [--session 2026-10-26] [--out reports/radar_rules_v1_2026-10-26.md]
"""
import argparse
from collections import Counter
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from statistics import median

from app.engine import radar_rules
from app.engine.chart_math import ET, REGULAR_CLOSE
from app.engine.radar_store import RadarStore, load_universe

QUICK_MINUTES = 15
SURVIVE_MINUTES = 30
SPY_BINS = (3.0, 3.5, 4.0, 4.5, 5.0, 6.0)
SECTOR_BINS = (3.0, 3.5, 4.0, 4.5, 5.0)
GROUP_BINS = (1.5, 1.75, 2.0, 2.5, 3.0)
NOT_USEFUL = ("already_knew", "too_late", "irrelevant")
KINDS = ("relative_to_spy", "relative_to_sector", "group_move")


def _short(version: str) -> str:
    return version.removeprefix("radar-rules-")


def _time(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ET).strftime("%H:%M")


def _minutes(a: str, b: str) -> float:
    return (radar_rules._epoch(b) - radar_rules._epoch(a)) / 60


def subject(event: dict) -> str:
    return event["group"] if event["kind"] == "group_move" else event["symbols"][0]


def match_key(event: dict) -> str:
    """The event id without its version prefix: session, kind, subject, direction and count."""
    return event["event_id"].split("-", 1)[1]


def outcome(event: dict, revisions: list[dict]) -> str:
    for r in revisions:
        if r["status"] in ("faded", "reversed"):
            late = _minutes(event["first_seen_at"], r["recorded_at"]) > QUICK_MINUTES
            return f"{r['status']} {_time(r['recorded_at'])}" if late else f"quick {r['status']} {_time(r['recorded_at'])}"
    ext = sum(r["status"] == "extended" for r in revisions)
    return f"extended ×{ext}" if ext else "no revision"


def variant(spec: str) -> radar_rules.Thresholds:
    types = {f.name for f in fields(radar_rules.Thresholds)} - {"version"}
    values = {}
    for item in spec.split(","):
        name, _, raw = item.partition("=")
        if name not in types:
            raise SystemExit(f"unknown threshold {name!r}; one of {', '.join(sorted(types))}")
        current = getattr(radar_rules.V0, name)
        values[name] = tuple(int(v) for v in raw.split("/")) if isinstance(current, tuple) else type(current)(raw)
    return replace(radar_rules.V0, version=f"{radar_rules.RULE_VERSION}+{spec}", **values)


def changes(t: radar_rules.Thresholds) -> list[tuple[str, object, object]]:
    return [(f.name, getattr(radar_rules.V0, f.name), getattr(t, f.name)) for f in fields(t)
            if f.name != "version" and getattr(t, f.name) != getattr(radar_rules.V0, f.name)]


class Session:
    def __init__(self, store: RadarStore, universe: dict, day: str):
        self.day, self.universe = day, universe
        self.passes = radar_rules.session_passes(store.passes(day), day)
        self.quotes: dict[int, dict[str, dict]] = {}
        for row in store.quotes(session_date=day):
            self.quotes.setdefault(row["pass_id"], {})[row["symbol"]] = row
        self.recorded = store.events(day)
        self._replays: dict[radar_rules.Thresholds, list] = {}

    def replay(self, t: radar_rules.Thresholds) -> list[tuple[dict, list[dict]]]:
        if t not in self._replays:
            self._replays[t] = radar_rules.replay(self.universe, self.passes, self.quotes, t) if self.passes else []
        return self._replays[t]

    @property
    def label(self) -> str:
        if not self.passes:
            return f"{self.day} (no usable passes)"
        last = datetime.fromtimestamp(radar_rules._epoch(self.passes[-1]["started_at"]), ET)
        if last.hour * 60 + last.minute < REGULAR_CLOSE - 2:
            return f"{self.day} (partial, to {last:%H:%M} ET)"
        return self.day

    def readings(self) -> dict[str, list[tuple[int, str, float]]]:
        """Every 30-minute reading with the own-move floor held: (pass index, subject, |relative|) per kind."""
        loose = replace(radar_rules.V0, spy_relative_pct=min(SPY_BINS), sector_relative_pct=min(SECTOR_BINS),
                        group_relative_pct=min(GROUP_BINS))
        out: dict[str, list] = {k: [] for k in KINDS}
        for i in range(len(self.passes)):
            for w in loose.windows:
                for r in radar_rules._readings(self.universe, self.passes, i, w, self.quotes, loose):
                    out[r.kind].append((i, f"{r.subject} {r.direction}", abs(r.relative)))
        return out

    def longest_runs(self, rows: list[tuple[int, str, float]], level: float) -> dict[str, int]:
        """Per subject, the longest run of consecutive passes (no gap over 150 s) at or above ``level``."""
        hits: dict[str, list[int]] = {}
        for i, name, value in rows:
            if value >= level:
                hits.setdefault(name, []).append(i)
        best = {}
        for name, idx in hits.items():
            run = top = 1
            for a, b in zip(idx, idx[1:]):
                gap = radar_rules._epoch(self.passes[b]["started_at"]) - radar_rules._epoch(self.passes[a]["started_at"])
                run = run + 1 if b == a + 1 and gap <= radar_rules.MAX_PASS_GAP_SECONDS else 1
                top = max(top, run)
            best[name] = top
        return best


def _counts(saved) -> dict:
    c = Counter((e["kind"], e["direction"]) for e, _ in saved)
    outcomes = [outcome(e, r) for e, r in saved]
    return {"events": len(saved),
            "spy": f"{c['relative_to_spy', 'up']} / {c['relative_to_spy', 'down']}",
            "sector": f"{c['relative_to_sector', 'up']} / {c['relative_to_sector', 'down']}",
            "group": f"{c['group_move', 'up']} / {c['group_move', 'down']}",
            "revisions": sum(len(r) for _, r in saved),
            "quick": sum(o.startswith("quick") for o in outcomes),
            "extended": sum(o.startswith("extended") for o in outcomes)}


def _diff(base, other) -> tuple[list, list, list[float]]:
    """(added, dropped, minutes earlier for shared events) of ``other`` against ``base``."""
    b = {match_key(e): (e, r) for e, r in base}
    o = {match_key(e): (e, r) for e, r in other}
    added = [o[k] for k in o if k not in b]
    dropped = [b[k] for k in b if k not in o]
    earlier = [_minutes(o[k][0]["first_seen_at"], b[k][0]["first_seen_at"]) for k in o if k in b]
    return added, dropped, earlier


def _event_line(e: dict, revisions: list[dict]) -> str:
    return f"| {_time(e['first_seen_at'])} | {e['kind']} | {subject(e)} {e['direction']} | {e['summary']} | {outcome(e, revisions)} |"


def survives(event: dict, saved) -> bool:
    return any(e["kind"] == event["kind"] and subject(e) == subject(event) and e["direction"] == event["direction"]
               and abs(_minutes(e["first_seen_at"], event["first_seen_at"])) <= SURVIVE_MINUTES for e, _ in saved)


def build_report(store: RadarStore, versions: list[radar_rules.Thresholds], sessions: list[str] | None = None,
                 universe: dict | None = None, title: str = "Radar rules report") -> str:
    universe = universe or load_universe()
    days = sorted(sessions or store.sessions())
    data = [Session(store, universe, d) for d in days]
    base = radar_rules.V0
    if base not in versions:
        versions = [base] + versions
    ratings = store.latest_ratings()
    names = [_short(t.version) for t in versions]
    out = [f"# {title}", ""]
    last = max((s.passes[-1]["started_at"] for s in data if s.passes), default=None)
    out += [f"Store snapshot: {len(days)} sessions ({', '.join(s.label for s in data)}), last recorded pass "
            f"{_time(last) + ' ET' if last else 'none'}, {sum(len(s.passes) for s in data)} usable passes; "
            f"tracked list `{universe['version']}`; ratings recorded: {len(ratings)}.",
            "", f"Generated by `scripts/radar_rules_report.py`; replays only (no live event is changed). "
            f"Quick fade = faded or reversed within {QUICK_MINUTES} minutes of the first sighting.", ""]

    out += ["## Versions", "", "| Version | Thresholds |", "| --- | --- |"]
    for t in versions:
        diff = changes(t)
        text = ", ".join(f"{n} {old} → {new}" for n, old, new in diff) if diff else (
            f"30-min window; vs SPY {t.spy_relative_pct}, vs sector {t.sector_relative_pct}, own move "
            f"{t.own_move_floor_pct}%; group median {t.group_relative_pct} with {t.group_min_members}+ members at "
            f"{t.group_agreement:.0%}; {t.persist_passes} consecutive passes; cooldown {t.cooldown_minutes} min")
        out.append(f"| {_short(t.version)} | {text} |")
    out.append("")

    out += ["## Events per session", "",
            "| Session | Version | Events | vs SPY up / down | vs sector up / down | Group up / down | Revisions | Quick fade | Extended |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    totals = {n: Counter() for n in names}
    for s in data:
        for t, n in zip(versions, names):
            c = _counts(s.replay(t))
            totals[n].update({k: c[k] for k in ("events", "revisions", "quick", "extended")})
            out.append(f"| {s.label} | {n} | {c['events']} | {c['spy']} | {c['sector']} | {c['group']} | {c['revisions']} "
                       f"| {c['quick']} | {c['extended']} |")
    for n in names:
        t = totals[n]
        out.append(f"| **All** | {n} | {t['events']} | | | | {t['revisions']} | {t['quick']} | {t['extended']} |")
    out.append("")

    for t, n in zip(versions, names):
        diff = changes(t)
        if not diff:
            continue
        out += [f"## What {n} changes", "", "| Change | Alone: events (vs v0) | Added | Dropped | Quick fade among added |"
                " Extended among added |", "| --- | --- | --- | --- | --- | --- |"]
        rows = [(f"{name} {old} → {new}", replace(base, **{name: new})) for name, old, new in diff]
        if len(diff) > 1:
            rows.append(("all together", t))
        b_total = sum(len(s.replay(base)) for s in data)
        for label, variant_t in rows:
            added = dropped = total = quick = ext = 0
            for s in data:
                a, d, _ = _diff(s.replay(base), s.replay(variant_t))
                total += len(s.replay(variant_t))
                added += len(a)
                dropped += len(d)
                quick += sum(outcome(e, r).startswith("quick") for e, r in a)
                ext += sum(outcome(e, r).startswith("extended") for e, r in a)
            out.append(f"| {label} | {total} ({total - b_total:+d}) | {added} | {dropped} | {quick} | {ext} |")
        out.append("")

    out += ["## 30-minute readings near the thresholds", "",
            "Stock × pass readings with the 2% own-move floor held, before the sector rule skips readings an SPY event "
            "already covers; groups need 4+ members with data and 60% agreement. "
            "Each cell: readings / subjects (symbol or group and direction) / subjects held on 2+ passes in a row / on 3+.", ""]
    readings = {s.day: s.readings() for s in data}
    for kind, bins, label in (("relative_to_spy", SPY_BINS, "Stock vs SPY ≥"), ("relative_to_sector", SECTOR_BINS, "Stock vs sector ≥"),
                              ("group_move", GROUP_BINS, "Group median vs SPY ≥")):
        out += [f"| {label} | " + " | ".join(s.label for s in data) + " |", "| --- |" + " --- |" * len(data)]
        for level in bins:
            cells = []
            for s in data:
                rows = [r for r in readings[s.day][kind] if r[2] >= level]
                runs = s.longest_runs(rows, level)
                cells.append(f"{len(rows)} / {len(runs)} / {sum(v >= 2 for v in runs.values())} / {sum(v >= 3 for v in runs.values())}")
            out.append(f"| {level} | " + " | ".join(cells) + " |")
        out.append("")

    for t, n in zip(versions, names):
        if t == base:
            continue
        out += [f"## {n} against v0, event by event", ""]
        for s in data:
            added, dropped, earlier = _diff(s.replay(base), s.replay(t))
            shift = (f"; the {len(earlier)} shared fire a median {median(earlier):.0f} min earlier "
                     f"(range {min(earlier):+.0f} to {max(earlier):+.0f})") if earlier else ""
            out.append(f"**{s.label}:** {len(added)} added, {len(dropped)} dropped{shift}.")
            out.append("")
            if added or dropped:
                out += ["| | First seen (ET) | Kind | Subject | Summary | Then |", "| --- | --- | --- | --- | --- | --- |"]
                out += [f"| added {_event_line(e, r)}" for e, r in added]
                out += [f"| dropped {_event_line(e, r)}" for e, r in dropped]
                out.append("")

    out += ["## Ratings by version", ""]
    rated = [(s, e) for s in data for e in s.recorded if e["event_id"] in ratings]
    if not rated:
        out += ["No recorded event has a rating yet, so this section is empty. It fills in from the store's feedback "
                "(the phone's Useful / Not useful taps and the feed) on the next run.", ""]
    else:
        out += [f"An event survives a version when that version fires the same kind, subject and direction within "
                f"{SURVIVE_MINUTES} minutes of the rated event's first sighting.", "",
                "| Rating | Rated | " + " | ".join(f"Survive {n}" for n in names) + " |", "| --- | --- |" + " --- |" * len(names)]
        groups = [("useful", ("useful",)), ("not useful (all)", NOT_USEFUL)] + [(f"  {r}", (r,)) for r in NOT_USEFUL]
        for label, which in groups:
            mine = [(s, e) for s, e in rated if ratings[e["event_id"]] in which]
            cells = [str(sum(survives(e, s.replay(t)) for s, e in mine)) for t in versions]
            out.append(f"| {label} | {len(mine)} | " + " | ".join(cells) + " |")
        out += ["", "| Session | First seen (ET) | Event | Rule version | Rating | " + " | ".join(names) + " |",
                "| --- | --- | --- | --- | --- |" + " --- |" * len(names)]
        for s, e in sorted(rated, key=lambda x: (x[0].day, x[1]["first_seen_at"], x[1]["event_id"])):
            marks = ["fires" if survives(e, s.replay(t)) else "—" for t in versions]
            out.append(f"| {s.day} | {_time(e['first_seen_at'])} | {e['kind']} {subject(e)} {e['direction']} | "
                       f"{e['rule_version']} | {ratings[e['event_id']]} | " + " | ".join(marks) + " |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("store", type=Path)
    parser.add_argument("--rules", action="append", help="v0, v1, ...; repeatable; default every version")
    parser.add_argument("--try", dest="tries", action="append", default=[], metavar="FIELD=VALUE[,FIELD=VALUE]",
                        help="an ad hoc variant of v0 (tuples as 15/30)")
    parser.add_argument("--session", action="append", help="YYYY-MM-DD; repeatable; default every session")
    parser.add_argument("--title", default="Radar rules report")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    args = parser.parse_args()
    try:
        versions = [radar_rules.thresholds_for(n) for n in args.rules] if args.rules else list(radar_rules.VERSIONS.values())
    except KeyError as exc:
        raise SystemExit(f"unknown rule version {exc}; one of {', '.join(radar_rules.VERSIONS)}")
    versions += [variant(spec) for spec in args.tries]
    store = RadarStore(args.store.resolve(), read_only=True)
    text = build_report(store, versions, args.session, title=args.title)
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
