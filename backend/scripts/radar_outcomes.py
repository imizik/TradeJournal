"""Score recorded Radar events against what happened next, beside the plain Movers list and random tracked stocks.

Spec: ``research/radar-outcomes/spec.md``. Read-only on the Radar store (SQLite ``mode=ro``); appends one JSON line
per newly scored event to ``--out`` and prints the read-out per rule version. No provider, model or network call.
Only completed sessions (before today in New York) are scored, so a line is never written with horizons still to come.

    python -m scripts.radar_outcomes /abs/path/radar.sqlite --out /abs/path/outcomes.jsonl
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import random

from app.engine.chart_math import ET
from app.engine.radar_comparison import _endpoint, epoch
from app.engine.radar_movers import build_movers
from app.engine.radar_store import RadarStore, load_universe

SCORER_VERSION = "radar-outcomes-v1"
HORIZONS = (("30m", 30 * 60), ("60m", 60 * 60), ("close", None))
PRIMARY = "60m"
TOLERANCE_SECONDS = 120
RANDOM_PICKS = 5
USABLE = ("ok", "partial")
REVIEW_SESSIONS = 20
BOOTSTRAP, SEED = 2000, 20261024
# Sessions a rule version was set on: reported, labelled in-sample, never part of its decision.
CALIBRATION = {"radar-rules-v0": {"2026-10-22", "2026-10-23"}}


def _prices(quotes: dict[str, dict], record: dict) -> dict[str, float]:
    out = {}
    for symbol, quote in quotes.items():
        point, _ = _endpoint(quote, record)
        if point:
            out[symbol] = point["price"]
    return out


def _rel(symbol: str, sign: int, start: dict[str, float], end: dict[str, float]) -> float | None:
    if symbol not in start or symbol not in end or "SPY" not in start or "SPY" not in end:
        return None
    return round(sign * ((end[symbol] / start[symbol] - 1) - (end["SPY"] / start["SPY"] - 1)) * 100, 4)


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def horizon_pass(passes: list[dict], start: dict, seconds: int | None) -> dict | None:
    """The pass nearest start + seconds within the tolerance; for the close, the session's last pass after start."""
    later = [p for p in passes if epoch(p["started_at"]) > epoch(start["started_at"])]
    if seconds is None:
        return later[-1] if later else None
    target = epoch(start["started_at"]) + seconds
    near = [p for p in later if abs(epoch(p["started_at"]) - target) <= TOLERANCE_SECONDS]
    return min(near, key=lambda p: (abs(epoch(p["started_at"]) - target), p["id"])) if near else None


def score_event(event: dict, passes: list[dict], quotes: dict[int, dict[str, dict]], universe: dict) -> dict:
    sign = 1 if event["direction"] == "up" else -1
    row = {"event_id": event["event_id"], "session_date": event["session_date"], "rule_version": event["rule_version"],
           "kind": event["kind"], "direction": event["direction"], "symbols": event["symbols"],
           "first_seen_at": event["first_seen_at"], "scorer_version": SCORER_VERSION, "horizons": {}, "excluded": {}}
    start = next((p for p in passes if p["finished_at"] == event["first_seen_at"]), None)
    if start is None:
        row["excluded"] = {name: "first-seen pass not recorded" for name, _ in HORIZONS}
        return row
    start_prices = _prices(quotes[start["id"]], start)
    own = set(event["symbols"])
    movers = build_movers(universe, list(quotes[start["id"]].values()), None, latest=start)
    peers = [r["symbol"] for r in movers["leaders" if sign > 0 else "laggards"] if r["symbol"] not in own]
    stocks = sorted(r["symbol"] for r in universe["symbols"]
                    if r["kind"] == "stock" and not r["benchmark"] and r["symbol"] in start_prices and r["symbol"] not in own)
    picks = random.Random(event["event_id"]).sample(stocks, min(RANDOM_PICKS, len(stocks)))
    for name, seconds in HORIZONS:
        end = horizon_pass(passes, start, seconds)
        if end is None:
            row["excluded"][name] = "no pass at the horizon"
            continue
        end_prices = _prices(quotes[end["id"]], end)
        value = _mean(_rel(s, sign, start_prices, end_prices) for s in event["symbols"])
        if value is None:
            row["excluded"][name] = "no usable quote at an endpoint"
            continue
        movers_values = [_rel(s, sign, start_prices, end_prices) for s in peers]
        row["horizons"][name] = {"end_pass": end["id"], "event": value, "movers": _mean(movers_values),
                                 "movers_n": sum(v is not None for v in movers_values),
                                 "random": _mean(_rel(s, sign, start_prices, end_prices) for s in picks)}
    return row


def score_store(store: RadarStore, universe: dict, done: set[str], today: str) -> list[dict]:
    rows = []
    for session in sorted(store.sessions()):
        if session >= today:
            continue
        events = [e for e in store.events(session) if e["event_id"] not in done]
        if not events:
            continue
        passes = sorted((p for p in store.passes(session) if p["status"] in USABLE), key=lambda p: (p["started_at"], p["id"]))
        quotes = store.pass_quotes(p["id"] for p in passes)
        rows += [score_event(e, passes, quotes, universe) for e in events]
    return rows


def _interval(by_session: dict[str, list[float]]) -> list[float] | None:
    days = sorted(by_session)
    if len(days) < 2:
        return None
    rng, draws = random.Random(SEED), []
    for _ in range(BOOTSTRAP):
        values = [v for _ in days for v in by_session[days[rng.randrange(len(days))]]]
        draws.append(sum(values) / len(values))
    draws.sort()
    return [round(draws[int(0.025 * BOOTSTRAP)], 4), round(draws[int(0.975 * BOOTSTRAP) - 1], 4)]


def _horizons(rows: list[dict]) -> dict:
    out = {}
    for name, _ in HORIZONS:
        scored = [r for r in rows if name in r["horizons"]]
        paired = [r for r in scored if r["horizons"][name]["movers"] is not None]
        diffs: dict[str, list[float]] = {}
        for r in paired:
            diffs.setdefault(r["session_date"], []).append(r["horizons"][name]["event"] - r["horizons"][name]["movers"])
        out[name] = {
            "events": len(scored), "excluded": len(rows) - len(scored),
            "kept_going": round(sum(r["horizons"][name]["event"] > 0 for r in scored) / len(scored), 3) if scored else None,
            "event_mean": _mean(r["horizons"][name]["event"] for r in scored),
            "movers_mean": _mean(r["horizons"][name]["movers"] for r in paired),
            "random_mean": _mean(r["horizons"][name]["random"] for r in scored),
            "radar_minus_movers": _mean(v for values in diffs.values() for v in values),
            "radar_minus_movers_95": _interval(diffs),
        }
    return out


def summarize(rows: list[dict]) -> dict:
    out = {}
    for version in sorted({r["rule_version"] for r in rows}):
        calibration = CALIBRATION.get(version, set())
        mine = [r for r in rows if r["rule_version"] == version]
        own = [r for r in mine if r["session_date"] not in calibration]
        in_sample = [r for r in mine if r["session_date"] in calibration]
        report = {"sessions": len({r["session_date"] for r in own}), "review_at_sessions": REVIEW_SESSIONS,
                  "events": len(own), "horizons": _horizons(own)}
        report["decision"] = decide(report)
        if in_sample:
            report["in_sample"] = {"note": "sessions the rules were set on; never part of the decision",
                                   "sessions": sorted({r["session_date"] for r in in_sample}),
                                   "events": len(in_sample), "horizons": _horizons(in_sample)}
        out[version] = report
    return out


def decide(report: dict) -> str:
    if report["sessions"] < REVIEW_SESSIONS:
        return f"not reviewed: {report['sessions']} of {REVIEW_SESSIONS} sessions"
    primary = report["horizons"][PRIMARY]
    interval = primary["radar_minus_movers_95"]
    if interval and interval[0] > 0 and (primary["kept_going"] or 0) > 0.5:
        return "Radar beats Movers at +60 min"
    if interval and interval[1] < 0:
        return "Radar does worse than Movers at +60 min (a fade signal)"
    return "no demonstrated timing value over Movers"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("store", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--today", help="New York date treated as today (YYYY-MM-DD); sessions on or after it are skipped")
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.out.read_text().splitlines() if line.strip()] if args.out.exists() else []
    today = args.today or datetime.now(ET).date().isoformat()
    new = score_store(RadarStore(args.store, read_only=True), load_universe(), {r["event_id"] for r in rows}, today)
    if new:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a") as handle:
            handle.writelines(json.dumps(r, sort_keys=True) + "\n" for r in new)
    print(json.dumps({"scored_now": len(new), "versions": summarize(rows + new)}, indent=2))


if __name__ == "__main__":
    main()
