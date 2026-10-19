"""Non-model collector/scorer. No inference endpoint, CLI, or Jo task dispatch."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import urllib.error
import urllib.parse
import urllib.request

import advisor_forecast as core

CONFIG = Path("/etc/tj-forecast")
STATE = Path("/var/lib/tj-forecast")
OUTCOMES = Path("/var/lib/tj-forecast-outcomes")
BASELINES = Path("/var/lib/tj-forecast-baselines")
RECEIPTS = Path("/var/lib/tj-forecast-receipts")
DATA_URL = "https://api.tradier.com/v1/markets/timesales"


def now():
    return datetime.now(timezone.utc)


def reject_model_credentials():
    if any(value and name.startswith(("OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "TUNNEL_")) for name, value in os.environ.items()):
        raise ValueError("model credentials forbidden")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect refused")


def tradier_bars(ticker, first_day, start, last_day, end):
    """One bounded, non-retrying production market-data GET; no orders/account API."""
    reject_model_credentials()
    key = os.environ.get("TRADIER_API_KEY")
    if not key:
        raise ValueError("dedicated existing Tradier credential absent")
    params = {"symbol": ticker, "interval": "1min", "session_filter": "open",
              "start": f"{first_day} {start[:5]}", "end": f"{last_day} {end[:5]}"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(DATA_URL + "?" + urllib.parse.urlencode(params),
                                     headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError("provider byte budget")
            result = json.loads(body)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        raise ValueError("market-data request failed; no retry, fallback or purchase") from None
    series = result.get("series") if isinstance(result, dict) else None
    if not isinstance(series, dict) or series.get("symbol", ticker) != ticker:
        raise ValueError("missing or mismatched Tradier series")
    values = series.get("data")
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list) or not values or len(values) > 10000:
        raise ValueError("missing or excessive Tradier bars")
    first, last = core.at(first_day, start), core.at(last_day, end)
    bars, previous = [], None
    for row in values:
        # Tradier time is exchange-local, start-labelled; never use the host TZ.
        dt = datetime.fromisoformat(row["time"])
        dt = dt.replace(tzinfo=core.ET) if dt.tzinfo is None else dt.astimezone(core.ET)
        if dt.second or dt.microsecond or not first <= dt <= last or (previous is not None and dt <= previous):
            raise ValueError("out-of-range, unordered or duplicate Tradier minute")
        if row.get("symbol", ticker) != ticker:
            raise ValueError("mismatched Tradier bar symbol")
        clean = {k: core.number(row[field], positive=k != "v")
                 for k, field in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))}
        if clean["v"] < 0 or not clean["l"] <= min(clean["o"], clean["c"]) <= max(clean["o"], clean["c"]) <= clean["h"]:
            raise ValueError("invalid Tradier OHLCV")
        bars.append({"t": dt.isoformat(), **clean})
        previous = dt
    return bars


def fetch_bars(day, start, end, spec):
    # Seven calls in two bounded waves fit the unchanged 30-second capture gate.
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda t: tradier_bars(t, day, start, day, end), spec["tickers"]))
    return dict(zip(spec["tickers"], values))


def fetch_history(prior, spec):
    # One range request per ticker, not 140 calls against a shared account budget.
    # Process one ticker at a time to bound memory for full-session responses.
    history = {}
    for ticker in spec["tickers"]:
        rows = tradier_bars(ticker, prior[0], "09:30:00", prior[-1], "10:59:00")
        windows = {d: [] for d in prior}
        for row in rows:
            dt = core.stamp(row["t"])
            day = dt.date().isoformat()
            if day in windows and 570 <= dt.hour * 60 + dt.minute < 660:
                windows[day].append(row)
        history[ticker] = {d: core.window(d, windows[d], 570, 90) for d in prior}
    return history


def verify_bundle():
    manifest = core.read_json(core.SPEC_DIR / "manifest.json")
    for name, expected in manifest["files"].items():
        path = core.ROOT / name
        if not path.resolve().is_relative_to(core.ROOT.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("frozen bundle changed")
    return manifest


def approval(spec):
    reject_model_credentials()
    verify_bundle()
    if socket.gethostname() != spec["runtime"]["host"]:
        raise ValueError("wrong host")
    path = CONFIG / "approval.json"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("root-owned approval required")
    value = core.read_json(path)
    if value.get("phase") not in ("development", "evaluation") or value != {"spec_hash": core.digest(spec), "owner_confirmed_dry_run": True, "non_model_collection_authorized": True, "phase": value.get("phase")}:
        raise ValueError("owner confirmation absent")
    return value["phase"]


def registration(spec):
    value = core.read_json(CONFIG / "registration.json")
    days, calendar = value["sessions"], value["calendar"]
    all_days = [r["date"] for r in calendar]
    if (value["spec_hash"] != core.digest(spec) or len(days) != 22 or days != sorted(set(days))
            or all_days != sorted(set(all_days)) or any(d not in all_days for d in days)
            or any(r["open"] != "09:30" or r["close"] < "11:00" for r in calendar)
            or len([d for d in all_days if d < days[0]]) < 20
            or core.stamp(value["registered_at"]) >= core.at(days[0], "09:45:00")):
        raise ValueError("invalid prospective registration")
    positions = [all_days.index(d) for d in days]
    if positions != list(range(positions[0], positions[0] + 22)):
        raise ValueError("registration must use consecutive eligible sessions")
    return value


def effective_spec(day, registered, spec):
    if day in registered["sessions"][:2]:
        return core.with_timing(spec, 0)
    selection = core.read_json(CONFIG / "evaluation-timing.json")
    if (selection["spec_hash"] != core.digest(spec)
            or core.stamp(selection["frozen_at"]) >= core.at(registered["sessions"][2], "09:45:00")
            or core.stamp(selection["frozen_at"]) <= core.at(registered["sessions"][1], "11:06:00")):
        raise ValueError("timing selection must follow development and precede evaluation")
    starts = selection["development_task_start_times"]
    if len(starts) != 2 or selection["evidence_source"] != "platform" or not selection.get("both_deliveries_observed"):
        raise ValueError("development timing evidence incomplete")
    shifted = any(core.stamp(value) > core.at(d, "10:00:30") for d, value in zip(registered["sessions"][:2], starts))
    if selection["offset_minutes"] != (5 if shifted else 0):
        raise ValueError("timing choice conflicts with preregistered rule")
    return core.with_timing(spec, selection["offset_minutes"])


def operational_guard(day, registered, spec):
    missing = 0
    for d in registered["sessions"][2:]:
        if d >= day:
            break
        paths = [RECEIPTS / d / f"{t}.json" for t in spec["tickers"]]
        if not all(p.exists() and core.read_json(p).get("status") in ("answered", "abstain") for p in paths):
            missing += 1
    if missing > 3:
        raise ValueError("more than three missing sessions; stop, no extension/restart")


def history_job(day, reg, spec):
    if not core.at(day, "09:45:00") <= core.stamp(now()) < core.at(day, "09:55:00"):
        raise ValueError("history preparation window exceeded")
    prior = [r["date"] for r in reg["calendar"] if r["date"] < day][-20:]
    history = fetch_history(prior, spec)
    for ticker in spec["tickers"]:
        core.history_stats(day, history[ticker], prior, spec)
    core.exclusive_json(STATE / "history" / f"{day}.json", {"sessions": prior, "bars": history, "captured_at": now().isoformat(), "spec_hash": core.digest(spec)})


def snapshot_job(day, reg, spec):
    if not core.at(day, spec["snapshot"]["capture_start"]) <= core.stamp(now()) <= core.at(day, spec["snapshot"]["capture_deadline"]):
        raise ValueError("snapshot collection late")
    history = core.read_json(STATE / "history" / f"{day}.json")
    if history["spec_hash"] != core.digest(spec) or core.stamp(history["captured_at"]) >= core.at(day, "09:55:00"):
        raise ValueError("history integrity mismatch")
    current = fetch_bars(day, "09:30:00", spec["snapshot"]["last_bar_start"], spec)
    captured = now()
    packets = [core.snapshot(day, t, current[t], history["bars"][t], history["sessions"], captured, spec) for t in spec["tickers"]]
    for packet in packets:
        core.exclusive_json(STATE / "snapshots" / day / f"{packet['ticker']}.json", packet)
    core.exclusive_json(STATE / "snapshots" / day / "manifest.json", {p["ticker"]: core.digest(p) for p in packets})


def outcomes_job(day, reg, spec):
    if not core.at(day, "11:05:00") <= core.stamp(now()) <= core.at(day, "11:06:00"):
        raise ValueError("outcome capture late")
    core.exclusive_json(OUTCOMES / day / "attempt.json", {"at": now().isoformat()})
    bars = fetch_bars(day, spec["snapshot"]["capture_start"], "10:59:00", spec)
    captured = now()
    for ticker in spec["tickers"]:
        core.exclusive_json(OUTCOMES / day / f"{ticker}.json", core.outcome(day, ticker, bars[ticker], captured, spec))


def baseline_job(day, reg, spec):
    from datetime import timedelta
    cutoff = core.at(day, spec["snapshot"]["submission_deadline"])
    if not cutoff <= core.stamp(now()) <= cutoff + timedelta(seconds=30):
        raise ValueError("baseline collection late")
    core.exclusive_json(BASELINES / day / "attempt.json", {"at": now().isoformat()})
    last_bar = (cutoff - timedelta(minutes=1)).time().isoformat()
    current = fetch_bars(day, "09:30:00", last_bar, spec)
    captured = now()
    hashes = {}
    for ticker in spec["tickers"]:
        path = STATE / "snapshots" / day / f"{ticker}.json"
        if path.exists():
            baseline = core.deadline_baseline(core.read_json(path), current[ticker], captured, spec)
            core.exclusive_json(BASELINES / day / f"{ticker}.json", baseline)
            hashes[ticker] = core.digest(baseline)
    core.exclusive_json(BASELINES / day / "manifest.json", hashes)


def job(action, spec):
    phase = approval(spec)
    reg = registration(spec)
    day = core.stamp(now()).date().isoformat()
    if day not in reg["sessions"]:
        return {"status": "outside_registered_sessions"}
    if phase == "development" and day not in reg["sessions"][:2]:
        return {"status": "evaluation_not_authorized"}
    effective = effective_spec(day, reg, spec)
    if action in ("snapshot", "baseline"):
        minute = core.stamp(now()).hour * 60 + core.stamp(now()).minute
        expected, _ = core.timing(effective)
        shift = 2 if action == "baseline" else 0
        if minute in (600 + shift, 605 + shift) and minute != expected + shift:
            return {"status": "other_preregistered_snapshot_slot"}
    if action != "outcomes":
        operational_guard(day, reg, spec)
    {"history": history_job, "snapshot": snapshot_job, "baseline": baseline_job, "outcomes": outcomes_job}[action](day, reg, effective)
    return {"status": "non_model_job_complete", "action": action, "session": day}


def final_score(spec):
    if approval(spec) != "evaluation":
        raise ValueError("evaluation not authorized")
    reg = registration(spec)
    days = reg["sessions"][2:]
    if core.stamp(now()) < core.at(days[-1], "11:06:00"):
        raise ValueError("interim scoring prohibited")
    effective = effective_spec(days[-1], reg, spec)
    report_path = OUTCOMES / "final-score.json"
    if report_path.exists():
        raise ValueError("already scored; read immutable report")
    records = []
    for day in days:
        audit_path = CONFIG / "audits" / f"{day}.json"
        audit = core.read_json(audit_path) if audit_path.exists() else None
        if audit and audit.get("synthetic_fixture"):
            raise ValueError("synthetic audit in real run")
        for ticker in spec["tickers"]:
            item = {"session": day, "ticker": ticker, "audit": audit}
            for kind, root in (("snapshot", STATE / "snapshots"), ("receipt", RECEIPTS), ("baseline", BASELINES), ("outcome", OUTCOMES)):
                path = root / day / f"{ticker}.json"
                if path.exists():
                    item[kind] = core.read_json(path)
                    if kind == "baseline" and core.read_json(BASELINES / day / "manifest.json").get(ticker) != core.digest(item[kind]):
                        raise ValueError("baseline manifest mismatch")
            records.append(item)
    result = core.score(days, records, effective, now())
    core.exclusive_json(report_path, result)
    return {"status": "scored_once", "report": str(report_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["history", "snapshot", "baseline", "outcomes", "score", "verify"])
    args = parser.parse_args()
    spec = core.read_json(core.SPEC_DIR / "spec.json")
    try:
        if args.action == "verify":
            reject_model_credentials()
            verify_bundle()
            result = {"bundle": "verified", "approval_present": (CONFIG / "approval.json").exists(), "model_calls": 0}
        else:
            result = final_score(spec) if args.action == "score" else job(args.action, spec)
        print(json.dumps(result))
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(2, "Study refused: approval, timing, integrity or provider prerequisite failed.\n")


if __name__ == "__main__":
    main()
