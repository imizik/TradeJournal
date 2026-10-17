"""Non-model collector/scorer. No inference endpoint, CLI, or Jo task dispatch."""
import argparse
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
RECEIPTS = Path("/var/lib/tj-forecast-receipts")
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"


def now():
    return datetime.now(timezone.utc)


def reject_model_credentials():
    if any(value and name.startswith(("OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "TUNNEL_")) for name, value in os.environ.items()):
        raise ValueError("model credentials forbidden")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect refused")


def fetch_bars(day, start, end, spec):
    reject_model_credentials()
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise ValueError("dedicated existing SIP credentials absent")
    params = {"symbols": ",".join(spec["tickers"]), "timeframe": "1Min", "feed": "sip", "adjustment": "raw", "asof": "-",
              "start": core.at(day, start).isoformat(), "end": core.at(day, end).isoformat(), "sort": "asc", "limit": 10000}
    rows, tokens = {t: [] for t in spec["tickers"]}, set()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for _ in range(4):
        request = urllib.request.Request(DATA_URL + "?" + urllib.parse.urlencode(params), headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        try:
            with opener.open(request, timeout=10) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError("provider byte budget")
                result = json.loads(body)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            raise ValueError("market-data request failed; no fallback or purchase") from None
        if not isinstance(result.get("bars"), dict) or set(result["bars"]) - set(rows):
            raise ValueError("unexpected provider symbols")
        for ticker, values in result["bars"].items():
            if not isinstance(values, list):
                raise ValueError("invalid provider bars")
            rows[ticker].extend(values)
            if len(rows[ticker]) > 90:
                raise ValueError("bar budget exceeded")
        token = result.get("next_page_token")
        if token is None:
            return rows
        if not isinstance(token, str) or len(token) > 2048 or token in tokens:
            raise ValueError("invalid pagination")
        tokens.add(token)
        params["page_token"] = token
    raise ValueError("pagination budget exceeded")


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
    if core.read_json(path) != {"spec_hash": core.digest(spec), "owner_confirmed_dry_run": True, "non_model_collection_authorized": True}:
        raise ValueError("owner confirmation absent")


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
    history = {t: {} for t in spec["tickers"]}
    for d in prior:
        bars = fetch_bars(d, "09:30:00", "10:59:00", spec)
        for ticker in spec["tickers"]:
            history[ticker][d] = core.window(d, bars[ticker], 570, 90)
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


def job(action, spec):
    approval(spec)
    reg = registration(spec)
    day = core.stamp(now()).date().isoformat()
    if day not in reg["sessions"]:
        return {"status": "outside_registered_sessions"}
    effective = effective_spec(day, reg, spec)
    if action == "snapshot":
        minute = core.stamp(now()).hour * 60 + core.stamp(now()).minute
        expected, _ = core.timing(effective)
        if minute in (600, 605) and minute != expected:
            return {"status": "other_preregistered_snapshot_slot"}
    if action != "outcomes":
        operational_guard(day, reg, spec)
    {"history": history_job, "snapshot": snapshot_job, "outcomes": outcomes_job}[action](day, reg, effective)
    return {"status": "non_model_job_complete", "action": action, "session": day}


def final_score(spec):
    approval(spec)
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
            for kind, root in (("snapshot", STATE / "snapshots"), ("receipt", RECEIPTS), ("outcome", OUTCOMES)):
                path = root / day / f"{ticker}.json"
                if path.exists():
                    item[kind] = core.read_json(path)
            records.append(item)
    result = core.score(days, records, effective, now())
    core.exclusive_json(report_path, result)
    return {"status": "scored_once", "report": str(report_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["history", "snapshot", "outcomes", "score", "verify"])
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
