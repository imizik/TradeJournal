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
from app.engine.radar_store import RadarStore
from app.engine.radar_evidence import census

SCORER_VERSION = "radar-outcomes-v2"
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
    receipts, configs = store.detection_evidence()
    for session in sorted(store.sessions()):
        if session >= today:
            continue
        events = [e for e in store.events(session) if e["event_id"] not in done]
        if not events:
            continue
        passes = sorted((p for p in store.passes(session) if p["status"] in USABLE), key=lambda p: (p["started_at"], p["id"]))
        quotes = store.pass_quotes(p["id"] for p in passes)
        for event in events:
            matches = [r for r in receipts.values() if event["event_id"] in r["event_ids"]]
            receipt = matches[0] if len(matches) == 1 else None
            config = configs.get(receipt["config_digest"]) if receipt else None
            start = next((p for p in passes if receipt and p["id"] == receipt["pass_id"]), None)
            verified = bool(receipt and config and start and receipt["origin"] == "live" and receipt["status"] == "ok"
                            and event["first_seen_at"] == start["finished_at"]
                            and event["universe_version"] == config["universe"]["version"]
                            and event["rule_version"] == config["rules"]["version"])
            if verified:
                row = score_event(event, passes, quotes, config["universe"])
            else:
                row = {k: event[k] for k in ("event_id", "session_date", "rule_version", "kind", "direction", "symbols", "first_seen_at")}
                row.update(horizons={}, excluded={name: "unverified live provenance" for name, _ in HORIZONS},
                           scorer_version=SCORER_VERSION)
            row.update(record_type="event", evidence_verified=verified,
                       config_digest=receipt["config_digest"] if receipt else None)
            rows.append(row)
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
    sessions = [r for r in rows if r.get("record_type") == "session"]
    events = [r for r in rows if "event_id" in r]
    out = {}
    for version in sorted({r["rule_version"] for r in rows}):
        calibration = CALIBRATION.get(version, set())
        recorded = [r for r in sessions if r["rule_version"] == version and r["session_date"] not in calibration]
        verified = [r for r in recorded if r["verified"]]
        review_window = sorted(verified, key=lambda r: r["session_date"])[:REVIEW_SESSIONS]
        configs = {r["config_digest"] for r in review_window}
        # Same label with altered rules/universe is not one frozen experiment.
        mixed = len(configs) > 1
        eligible = {r["session_date"]: r["config_digest"] for r in review_window} if not mixed else {}
        mine = [r for r in events if r["rule_version"] == version]
        own = [r for r in mine if r.get("evidence_verified") and r["session_date"] in eligible
               and r.get("config_digest") == eligible[r["session_date"]]]
        report = {"sessions": len(eligible), "review_at_sessions": REVIEW_SESSIONS,
                  "recorded_sessions": len(recorded), "verified_sessions_available": len(verified), "unverified_sessions": [r for r in recorded if not r["verified"]],
                  "mixed_configuration": mixed, "events": len(own), "excluded_events": len(mine) - len(own),
                  "horizons": _horizons(own)}
        report["decision"] = "not reviewed: mixed frozen configurations" if mixed else decide(report)
        in_sample = [r for r in mine if r["session_date"] in calibration]
        if in_sample:
            report["in_sample"] = {"note": "calibration; excluded from decision",
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
    parser.add_argument("--census-only", action="store_true", help="print outcome-blind session metadata; write nothing")
    parser.add_argument("--today", help="New York date treated as today (YYYY-MM-DD); sessions on or after it are skipped")
    args = parser.parse_args(argv)
    today = args.today or datetime.now(ET).date().isoformat()
    store = RadarStore(args.store, read_only=True)
    sessions = census(store, today)
    if args.census_only:
        print(json.dumps({"sessions": sessions}, indent=2))
        return
    rows = [json.loads(line) for line in args.out.read_text().splitlines() if line.strip()] if args.out.exists() else []
    new = score_store(store, None, {r["event_id"] for r in rows if "event_id" in r}, today)
    saved_sessions = {r["session_date"] for r in rows if r.get("record_type") == "session"}
    new += [r for r in sessions if r["session_date"] not in saved_sessions]
    if new:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a") as handle:
            handle.writelines(json.dumps(r, sort_keys=True) + "\n" for r in new)
    print(json.dumps({"scored_now": sum("event_id" in r for r in new), "versions": summarize(rows + new)}, indent=2))


if __name__ == "__main__":
    main()
