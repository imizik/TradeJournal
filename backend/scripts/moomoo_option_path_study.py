"""Manual fixed-cohort option-history study. No app imports, caches or DB writes.

Run from backend: python -m scripts.moomoo_option_path_study
Only bounded numeric summaries go to stdout; raw bars remain in memory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from datetime import date, datetime, time as day_time, timedelta
from decimal import Decimal
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pandas as pd

from scripts import moomoo_history_options_diagnostic as h

ROOT = Path(__file__).resolve().parents[2]
# Fixed independent candidates, not symbol discovery or retries of chain errors.
COHORTS = tuple(
    {"root": root, "expiry": date.fromisoformat(expiry), "day": date.fromisoformat(day),
     "side": side, "strike": strike,
     "code": f"US.{root}{date.fromisoformat(expiry):%y%m%d}{side}{strike * 1000}",
     "occ": f"{root}{date.fromisoformat(expiry):%y%m%d}{side}{strike * 1000:08d}"}
    for root, expiry, day, strike in (
        ("NVDA", "2025-12-19", "2025-12-18", 175),
        ("NVDA", "2026-03-20", "2026-03-19", 180),
        ("NVDA", "2026-09-18", "2026-09-17", 220),
        ("SPY", "2026-10-09", "2026-10-08", 774),
    ) for side in ("C", "P")
)
FIELDS = ("option_mfe_pct", "option_mae_pct", "option_peak_unrealized_pnl",
          "option_worst_unrealized_pnl", "option_peak_total_pnl",
          "option_giveback_from_peak", "option_exit_efficiency", "option_giveback_pct",
          "time_to_option_mfe_minutes")


class Reader(h.Reader):
    def __init__(self, client, appkey, key):
        super().__init__(client, h.DEFAULT_DAY, appkey, key)
        h.ALLOWED.update(("moomoo", "GET", "webapi.moomoo.com",
                          f"/api/v1.0/quote/{c['code']}/history-kline") for c in COHORTS)

    def read(self, *args, **kwargs):
        payload = super().read(*args, **kwargs)
        # Do not continue after documented permission/quote-quota refusal.
        if args[1] == "moomoo" and self.records[args[0]].get("ret_code") in (1, -9):
            self.blocked.add("moomoo")
        return payload


def local_path_function():
    """Extract only trusted pure source functions; avoid application initialization."""
    ns = {"pd": pd, "math": math, "Decimal": Decimal, "datetime": datetime,
          "timedelta": timedelta, "ET": h.ET, "UTC": h.timezone.utc,
          "_ENTRY_SIDES": ("buy_to_open", "sell_to_open", "buy")}
    hashes = {}
    for name, wanted in (("indicators.py", {"bars_to_df", "_f"}),
                         ("trade_path.py", {"option_position_path"})):
        path = ROOT / "backend/app/engine" / name
        source = path.read_text()
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        if len(nodes) != len(wanted):
            raise h.DiagnosticError("Pure option-path extraction failed.")
        # Annotation names are intentionally unevaluated, like this module.
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns["option_position_path"], hashes


def parse_session(raw, provider, cohort, shift=0, precision=None):
    """Reject malformed/duplicate intervals; retain zero-volume bars explicitly."""
    day = cohort["day"]
    close = day_time(16, 15) if cohort["root"] == "SPY" else day_time(16)
    start_ms = int(datetime.combine(day, day_time(9, 30), h.ET).timestamp() * 1000)
    end_ms = int(datetime.combine(day, close, h.ET).timestamp() * 1000)
    bars, duplicates = {}, set()
    stats = {"returned_rows": len(h.items(raw)), "invalid_rows": 0, "outside_session": 0,
             "duplicate_rows": 0, "shift_ms": shift, "expected_clock_minutes": (end_ms - start_ms) // 60000}
    for item in h.items(raw):
        row = h.mapping(item)
        at = h.timestamp(row.get("time_key")) if provider == "moomoo" else h.iso_ms(row.get("t"))
        values = {k: h.number(row.get(v)) for k, v in zip(
            ("o", "h", "l", "c"), ("open", "high", "low", "close") if provider == "moomoo" else ("o", "h", "l", "c"))}
        volume = h.option_quantity(row.get("volume" if provider == "moomoo" else "v"))
        if at is None or at % 60000 or any(v is None or v <= 0 for v in values.values()) or volume is None:
            stats["invalid_rows"] += 1
            continue
        at += shift
        if not values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]:
            stats["invalid_rows"] += 1
            continue
        if not start_ms <= at < end_ms:
            stats["outside_session"] += 1
            continue
        if at in bars or at in duplicates:
            stats["duplicate_rows"] += 1
            duplicates.add(at)
            bars.pop(at, None)
            continue
        values["v"] = volume / 10**precision if provider == "moomoo" and type(precision) is int and 0 <= precision <= 9 else volume if provider == "alpaca" else None
        bars[at] = values
    stats.update(valid_rows=len(bars), first_ms=min(bars) if bars else None,
                 last_ms=max(bars) if bars else None,
                 zero_volume_rows=sum(b["v"] == 0 for b in bars.values()),
                 volume_units_verified=False,
                 missing_clock_minutes=stats["expected_clock_minutes"] - len(bars))
    return bars, stats


def profile_matches(row, cohort):
    row = h.mapping(row)
    return (row.get("code") == cohort["code"] and row.get("stock_owner") == "US." + cohort["root"]
            and row.get("stock_type") == "DRVT"
            and type(row.get("lot_size")) is int and row["lot_size"] == 100
            and type(row.get("contract_size")) is int and row["contract_size"] == 100)


def scenario_specs(root):
    specs = {
        "long_morning": [("09:45:20", "buy_to_open", 1), ("10:45:40", "sell_to_close", 1)],
        "short_morning": [("09:45:20", "sell_to_open", 1), ("10:45:40", "buy_to_close", 1)],
        "long_afternoon": [("14:00:20", "buy_to_open", 1), ("15:45:40", "sell_to_close", 1)],
        "long_scale": [("09:45:20", "buy_to_open", 2), ("10:00:20", "buy_to_open", 1),
                       ("10:15:20", "sell_to_close", 1), ("10:45:40", "sell_to_close", 2)],
    }
    if root == "SPY":
        specs["long_late_session"] = [("16:00:20", "buy_to_open", 1), ("16:10:40", "sell_to_close", 1)]
    return specs


def make_scenario(cohort, spec, baseline):
    """Hypothetical premiums use completed Alpaca closes; never executed prices."""
    fills, lots, realized = [], [], Decimal(0)
    sign = 1 if spec[0][1] == "buy_to_open" else -1
    for i, (clock, side, qty) in enumerate(spec):
        wall = datetime.combine(cohort["day"], day_time.fromisoformat(clock))
        minute = int(wall.replace(second=0, tzinfo=h.ET).timestamp() * 1000)
        anchor = baseline.get(minute - 60000)
        if anchor is None:
            return None
        price = Decimal(str(anchor["c"])) * 100
        fill = SimpleNamespace(id=str(i), executed_at=wall, side=side, contracts=Decimal(qty), price=price)
        fills.append(fill)
        if side in ("buy_to_open", "sell_to_open"):
            lots.append([Decimal(qty), price])
        else:
            remaining = Decimal(qty)
            while remaining and lots:
                used = min(remaining, lots[0][0])
                realized += sign * (price - lots[0][1]) * used
                remaining -= used
                lots[0][0] -= used
                if not lots[0][0]:
                    lots.pop(0)
            if remaining:
                raise h.DiagnosticError("Hypothetical allocation is invalid.")
    trade = SimpleNamespace(opened_at=fills[0].executed_at, closed_at=fills[-1].executed_at,
                            status="closed", realized_pnl=realized)
    return trade, fills


def eligibility(bars, trade, fills):
    opened = int(trade.opened_at.replace(tzinfo=h.ET).timestamp() * 1000)
    closed = int(trade.closed_at.replace(tzinfo=h.ET).timestamp() * 1000)
    fill_minutes = {int(f.executed_at.replace(second=0, tzinfo=h.ET).timestamp() * 1000) for f in fills}
    expected = set(range((opened + 59999) // 60000 * 60000, closed // 60000 * 60000, 60000)) - fill_minutes
    present = expected & bars.keys()
    return {"expected_eligible_clock_minutes": len(expected), "observed_eligible_minutes": len(present),
            "missing_eligible_minutes": len(expected - bars.keys()),
            "zero_volume_eligible_minutes": sum(bars[t]["v"] == 0 for t in present),
            "excluded_fill_minutes_present": len(fill_minutes & bars.keys())}


def compute_scenario(function, scenario, bars):
    trade, fills = scenario
    rows = [dict(t=datetime.fromtimestamp(t / 1000, h.timezone.utc).isoformat(), **b) for t, b in sorted(bars.items())]
    result = function(trade, fills, rows)
    return {"quality": result["option_path_quality"],
            "metrics": {k: result.get(k) for k in FIELDS}, "coverage": eligibility(bars, trade, fills)}


def metric_delta(left, right):
    return {k: round(left["metrics"][k] - right["metrics"][k], 6)
            if left["metrics"][k] is not None and right["metrics"][k] is not None else None for k in FIELDS}


def comparisons(cohort, baseline, shifted, raw, function, comparable):
    result = {}
    for name, spec in scenario_specs(cohort["root"]).items():
        scenario = make_scenario(cohort, spec, baseline)
        if scenario is None:
            result[name] = {"status": "hypothetical_anchor_unavailable"}
            continue
        trade, fills = scenario
        out = {"status": "observed_comparison" if comparable else "source_incomplete_or_unresolved",
               "hypothetical_fills": [{"at_et": f.executed_at.isoformat(), "side": f.side,
                                       "contracts": float(f.contracts), "premium_dollars_per_contract": float(f.price)} for f in fills],
               "hypothetical_final_pnl": float(trade.realized_pnl),
               "alpaca": compute_scenario(function, scenario, baseline),
               "moomoo_shifted": compute_scenario(function, scenario, shifted),
               "moomoo_raw_label_sensitivity": compute_scenario(function, scenario, raw)}
        # Incomplete source observations cannot become matches.
        out["shifted_minus_alpaca"] = metric_delta(out["moomoo_shifted"], out["alpaca"]) if comparable else None
        positive = {t: b for t, b in shifted.items() if b["v"] is not None and b["v"] > 0}
        if len(positive) != len(shifted):
            out["moomoo_positive_volume_sensitivity"] = compute_scenario(function, scenario, positive)
        result[name] = out
    return result


def run(reader, config):
    function, hashes = local_path_function()
    report = {"captured_at_utc": datetime.now(h.timezone.utc).isoformat(), "formula_source_sha256": hashes,
              "market_hours_test": "deferred; no WebSocket", "raw_history_retained": False,
              "option_history_feed": "endpoint default, matching existing fetch_option_bars; no override",
              "timestamp_basis": "Moomoo raw and empirical -60000 ms diagnostic sensitivity; Alpaca interval start",
              "contracts": {}}
    clock = reader.read("clock", "moomoo", "GET", h.HOST + h.TIME_PATH)
    at = h.mapping(clock).get("server_time_ms")
    if isinstance(at, str) and re.fullmatch(r"[0-9]{1,14}", at):
        reader.offset = int(at) - reader.records["clock"]["received_at_ms"] + reader.records["clock"]["round_trip_ms"] / 2
    payload = reader.read("profiles", "moomoo", "POST", h.HOST + h.BASIC_PATH,
                          body={"code_list": [c["code"] for c in COHORTS]}, headers={"Content-Type": "application/json"})
    profiles = {r["code"]: r for r in h.items(h.mapping(h.mapping(payload).get("data")).get("basic_list"))
                if isinstance(r, dict) and r.get("code") in {c["code"] for c in COHORTS}}
    headers = {"APCA-API-KEY-ID": config.get("ALPACA_API_KEY", ""), "APCA-API-SECRET-KEY": config.get("ALPACA_API_SECRET", "")}
    for c in COHORTS:
        verified = profile_matches(profiles.get(c["code"]), c)
        out = report["contracts"][c["code"]] = {"occ": c["occ"], "session": str(c["day"]),
                  "profile_present": c["code"] in profiles, "identity_and_100_share_profile_verified": verified}
        raw, shifted, baseline = {}, {}, {}
        moo_success = alp_success = False
        if verified:
            label = "moomoo_" + c["occ"]
            p = reader.read(label, "moomoo", "GET", h.HOST + f"/api/v1.0/quote/{c['code']}/history-kline",
                            params={"start": str(c["day"]), "end": str(c["day"] + timedelta(days=1)),
                                    "ktype": 1, "autype": 0, "num": 370, "extended_time": 0})
            data = h.mapping(h.mapping(p).get("data"))
            precision = data.get("volume_precision", h.mapping(p).get("volume_precision"))
            if isinstance(precision, str) and re.fullmatch("[0-9]", precision):
                precision = int(precision)
            raw, out["moomoo_raw"] = parse_session(data.get("kline_list"), "moomoo", c, precision=precision)
            shifted, out["moomoo_shifted"] = parse_session(data.get("kline_list"), "moomoo", c, -60000, precision)
            cursor = data.get("next_time", h.mapping(p).get("next_time"))
            out["moomoo_next_time_present"] = cursor not in (None, 0, "0", "")
            out["moomoo_volume_precision"] = precision if type(precision) is int and 0 <= precision <= 9 else None
            moo_success = reader.records[label]["status"] == "success" and not out["moomoo_next_time_present"]
        if all(headers.values()):
            label = "alpaca_" + c["occ"]
            close = day_time(16, 15) if c["root"] == "SPY" else day_time(16)
            p = reader.read(label, "alpaca", "GET", "https://data.alpaca.markets/v1beta1/options/bars",
                            params={"symbols": c["occ"], "timeframe": "1Min",
                                    "start": datetime.combine(c["day"], day_time(9, 30), h.ET).isoformat(),
                                    "end": datetime.combine(c["day"], close, h.ET).isoformat(), "limit": 1000, "sort": "asc"}, headers=headers)
            baseline, out["alpaca"] = parse_session(h.mapping(h.mapping(p).get("bars")).get(c["occ"]), "alpaca", c)
            out["alpaca_next_page_present"] = bool(h.mapping(p).get("next_page_token"))
            alp_success = reader.records[label]["status"] == "success" and not out["alpaca_next_page_present"]
        out["shared_minutes"] = len(shifted.keys() & baseline.keys())
        extra = shifted.keys() - baseline.keys()
        out["coverage_difference"] = {"moomoo_only_minutes": len(extra),
                "moomoo_only_positive_volume_minutes": sum(shifted[t]["v"] is not None and shifted[t]["v"] > 0 for t in extra),
                "moomoo_only_zero_volume_minutes": sum(shifted[t]["v"] == 0 for t in extra),
                "alpaca_only_minutes": len(baseline.keys() - shifted.keys())}
        comparable = verified and moo_success and alp_success and bool(shifted) and bool(baseline)
        out["scenarios"] = comparisons(c, baseline, shifted, raw, function, comparable)
        out["comparison_eligible"] = comparable
    report.update(requests=reader.records, request_count=reader.count,
                  elapsed_seconds=round(time.monotonic() - reader.started, 3), status="completed_bounded_study")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-env", type=Path, default=Path.home() / "TradeJournal/backend/.env")
    args = parser.parse_args()
    try:
        if any(n == "app" or n.startswith("app.") for n in sys.modules):
            raise h.DiagnosticError("Unexpected application import.")
        appkey = h.secure_read(h.KEY_DIR / "appkey").decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", appkey):
            raise h.DiagnosticError("Invalid AppKey.")
        key = serialization.load_pem_private_key(h.secure_read(h.KEY_DIR / "phase1-ed25519.pem"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise h.DiagnosticError("Ed25519 required.")
        with h.quiet_logging(), httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            report = run(Reader(client, appkey, key), h.settings(args.baseline_env))
        if any(n == "app" or n.startswith("app.") for n in sys.modules):
            raise h.DiagnosticError("Unexpected application import.")
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (h.DiagnosticError, OSError, ValueError, TypeError, UnicodeError):
        print("Option-path study stopped safely; credentials and raw response details withheld.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
