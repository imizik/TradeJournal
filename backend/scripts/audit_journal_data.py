"""D0: explicit read-only snapshot capture and offline exploratory analysis.

Never imports app.database, loads dotenv, rebuilds trades, or fetches providers.
Only a new output directory is written. See docs/d0-data-audit.md for definitions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine import metric_reference as ref  # noqa: E402
from app.engine.metric_versions import CONTEXT_VERSION, PATH_VERSION  # noqa: E402
from app.models import Fill, FillMarketContext, TradePathMetrics  # noqa: E402

TABLES = {"accounts": "account", "fills": "fill", "trades": "trade",
          "links": "tradefill", "contexts": "fill_market_context", "paths": "trade_path_metrics"}
PRIVATE = {"email_subject", "email_body_text", "ai_review", "broker_account_id", "last4"}
DIMENSIONS = {
    "entry_time": ("premarket", "open", "mid", "close", "afterhours"),
    "repeat_entry": ("first", "repeat"),
    "after_close": ("after_loss", "after_nonloss", "no_prior_close"),
}
UNITS = {"realized_pnl": "USD, recorded gross", "pnl_pct": "fraction of cumulative entry cost/premium",
         "entry_vs_vwap_pct": "underlying percent versus completed-minute VWAP",
         "is_trend_aligned": "nullable 0/1 heuristic",
         "underlying_mfe_pct": "underlying favorable percent estimate",
         "underlying_mae_pct": "underlying adverse percent estimate",
         "option_mfe_pct": "option favorable percent of contemporaneous open cost basis",
         "option_peak_total_pnl": "USD, realized plus remaining-position estimate",
         "option_giveback_from_peak": "USD, estimated peak total minus final realized",
         "option_exit_efficiency": "percent, 100 * realized / estimated peak total"}


class InputError(ValueError):
    """Only fixed, credential-free diagnostic messages may use this exception."""


def postgres_url(value):
    """Validate before connecting; libpq parse errors can contain secrets."""
    from psycopg import ProgrammingError
    from psycopg.conninfo import conninfo_to_dict
    if not value:
        raise InputError("The named PostgreSQL URL variable is unset.")
    value = value.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    message = "Invalid PostgreSQL URL. Enter only the complete postgres:// or postgresql:// URL, with encoded credentials and the intended tunnel port; omit quotes and export commands."
    if not value.startswith(("postgres://", "postgresql://")):
        raise InputError(message)
    try:
        conninfo_to_dict(value)
    except ProgrammingError:
        raise InputError(message) from None
    return value


def encode(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def sha(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=encode).encode()).hexdigest()


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def wall(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Missing or invalid timestamp")
    return ref.timestamp(value).astimezone(ref.ET).replace(tzinfo=None)


def same_identity(left, right):
    for key in ("account_id", "ticker", "instrument_type", "option_type", "strike", "expiration"):
        if key == "strike" and left.get(key) is not None and right.get(key) is not None:
            if ref.number(left[key]) != ref.number(right[key]):
                return False
        elif str(left.get(key)) != str(right.get(key)):
            return False
    return True


def capture(connection, *, postgres=False):
    """Pin one database view before reading any journal rows; rollback always."""
    cursor = connection.cursor()
    data = {}
    try:
        cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" if postgres else "BEGIN")
        for key, table in TABLES.items():
            if postgres:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
                columns = [r[0] for r in cursor.fetchall()]
            else:
                cursor.execute(f'PRAGMA table_info("{table}")')
                columns = [r[1] for r in cursor.fetchall()]
            if not columns:
                if key in ("contexts", "paths"):
                    data[key] = []
                    continue
                raise ValueError(f"Missing required table: {table}")
            selected = [c for c in columns if c not in PRIVATE]
            quoted = [f'"{c.replace(chr(34), chr(34)*2)}"' for c in selected]
            if key == "fills":
                payload = [c for c in columns if c in ("email_subject", "email_body_text")]
                if payload:
                    quoted.append("(" + " OR ".join(f'"{c}" IS NOT NULL' for c in payload) + ") AS has_source_payload")
                    selected.append("has_source_payload")
            cursor.execute(f'SELECT {", ".join(quoted)} FROM "{table}"')
            data[key] = sorted([dict(zip(selected, row)) for row in cursor.fetchall()], key=lambda r: str(r.get("id", r.get("fill_id", r.get("trade_id")))))
        data["snapshot_at"] = datetime.now(timezone.utc).isoformat()
        data["capture"] = {"backend": "postgresql" if postgres else "sqlite", "consistent_transaction": True,
                           "source_completeness": "not_verified", "private_payloads": "omitted"}
        # Normalize decimals/datetimes identically for capture and later replay.
        return json.loads(json.dumps(data, default=encode))
    finally:
        connection.rollback()
        cursor.close()


def indexed(rows, field):
    result = {}
    for row in rows:
        key = str(row[field])
        if key in result:
            raise ValueError(f"Duplicate {field}: {key}")
        result[key] = row
    return result


def source_kind(fill):
    source = fill.get("raw_email_id")
    if not source:
        return "missing"
    if source.startswith("manual:"):
        return "manual"
    if source.startswith("webull:"):
        return "webull"
    return "gmail_reference_unverified"


def summarize(rows):
    pnl = [r["pnl"] for r in rows]
    returns = [r["return_pp"] for r in rows if r["return_pp"] is not None]
    return {"trades": len(rows), "days": len({r["day"] for r in rows}),
            "total_pnl_usd": sum(pnl), "mean_pnl_usd": statistics.mean(pnl) if pnl else None,
            "win_rate_pct": 100 * sum(v > 0 for v in pnl) / len(pnl) if pnl else None,
            "return_observations": len(returns), "mean_return_pct": statistics.mean(returns) if returns else None,
            "median_return_pct": statistics.median(returns) if returns else None,
            "trade_ids": [r["id"] for r in rows]}


def comparisons(rows, *, draws, seed):
    """Same-stratum cohort-vs-rest; joint day-cluster bootstrap max deviation."""
    panels = []
    strata = sorted({r["stratum"] for r in rows})
    days = sorted({r["day"] for r in rows})
    for stratum in strata:
        pool = [r for r in rows if r["stratum"] == stratum]
        for dimension, labels in DIMENSIONS.items():
            known = [r for r in pool if r[dimension] in labels]
            for label in labels:
                members = [r for r in known if r[dimension] == label]
                rest = [r for r in known if r[dimension] != label]
                a, b = summarize(members), summarize(rest)
                complete_a = [r for r in members if r["return_pp"] is not None]
                complete_b = [r for r in rest if r["return_pp"] is not None]
                supported = min(len(complete_a), len(complete_b)) >= 20 and min(
                    len({r["day"] for r in complete_a}), len({r["day"] for r in complete_b})) >= 10
                effect = a["mean_return_pct"] - b["mean_return_pct"] if complete_a and complete_b else None
                panels.append({"stratum": stratum, "dimension": dimension, "cohort": label,
                               "cohort_summary": a, "baseline_summary": b,
                               "dimension_unavailable": len(pool) - len(known),
                               "effect_return_pp": effect,
                               "effect_mean_pnl_usd": a["mean_pnl_usd"] - b["mean_pnl_usd"] if members and rest else None,
                               "status": "exploratory" if supported else "insufficient_evidence",
                               "simultaneous_interval_pp": None,
                               "_a": complete_a, "_b": complete_b})
    supported = [p for p in panels if p["status"] == "exploratory"]
    vectors = []
    for p in supported:
        sums = []
        for group in (p["_a"], p["_b"]):
            by_day = defaultdict(lambda: [0.0, 0])
            for r in group:
                by_day[r["day"]][0] += r["return_pp"]
                by_day[r["day"]][1] += 1
            sums.append([by_day[d] for d in days])
        vectors.append(sums)
    rng = random.Random(seed)
    samples = [[] for _ in supported]
    for _ in range(draws if supported else 0):
        weights = Counter(rng.randrange(len(days)) for _ in days)
        for column, (a, b) in enumerate(vectors):
            means = []
            for group in (a, b):
                count = sum(group[i][1] * w for i, w in weights.items())
                means.append(sum(group[i][0] * w for i, w in weights.items()) / count if count else None)
            samples[column].append(means[0] - means[1] if all(m is not None for m in means) else None)
    # Simultaneous 95% intervals across all supported contrasts in this period,
    # rather than declaring significance from many separate 95% intervals.
    scales = [statistics.stdev([x for x in col if x is not None]) for col in samples]
    maxima = []
    for i in range(draws if supported else 0):
        if all(col[i] is not None for col in samples):
            maxima.append(max((abs(col[i] - p["effect_return_pp"]) / scale if scale else 0)
                              for col, p, scale in zip(samples, supported, scales)))
    if len(maxima) >= draws * 0.95:
        critical = sorted(maxima)[min(len(maxima) - 1, math.ceil(0.95 * len(maxima)) - 1)]
        for p, scale in zip(supported, scales):
            if scale:
                p["simultaneous_interval_pp"] = [p["effect_return_pp"] - critical * scale, p["effect_return_pp"] + critical * scale]
            else:
                p["status"] = "insufficient_evidence"
    else:
        for p in supported:
            p["status"] = "insufficient_evidence"
    for p in panels:
        del p["_a"], p["_b"]
    return {"comparisons_attempted": len(panels), "interval_family_size": len(supported), "panels": panels}


def coverage(rows, fields, version=None):
    output = {}
    for field in sorted(fields):
        values = [r.get(field) for r in rows]
        output[field] = {"rows": len(rows), "present": sum(v is not None for v in values),
                         "null_or_absent": sum(v is None for v in values),
                         "obsolete_version_present": sum(r.get(field) is not None and r.get("calculation_version") != version for r in rows) if version else None,
                         "unit": UNITS.get(field, "schema field; coverage only, not interpreted"),
                         "source_validated": False}
    return output


def analyze(snapshot, *, holdout_start=None, draws=1000, seed=1729):
    if draws < 200:
        raise ValueError("At least 200 bootstrap draws required")
    as_of = wall(snapshot["snapshot_at"])
    fills = indexed(snapshot["fills"], "id")
    trades = indexed(snapshot["trades"], "id")
    accounts = indexed(snapshot.get("accounts", []), "id")
    contexts = indexed(snapshot.get("contexts", []), "fill_id")
    paths = indexed(snapshot.get("paths", []), "trade_id")
    linked = defaultdict(list)
    owners = defaultdict(set)
    dangling = []
    for link in snapshot["links"]:
        tid, fid = str(link["trade_id"]), str(link["fill_id"])
        if tid not in trades or fid not in fills:
            dangling.append(link)
        else:
            linked[tid].append((fills[fid], link["role"]))
            owners[fid].add(tid)
    raw_ids = Counter(f.get("raw_email_id") for f in fills.values() if f.get("raw_email_id"))
    timestamp_groups = defaultdict(list)
    source_audit = []
    for f in fills.values():
        issues = []
        try:
            executed = wall(f.get("executed_at"))
            if executed > as_of:
                issues.append("future_execution_time")
            clock = executed.isoformat()
        except (ValueError, TypeError):
            issues.append("missing_or_invalid_execution_time")
            clock = str(f.get("executed_at"))
        if finite(f.get("contracts")) is None or finite(f.get("contracts")) <= 0 or finite(f.get("price")) is None or finite(f.get("price")) < 0:
            issues.append("invalid_quantity_or_price")
        if not f.get("raw_email_id") or raw_ids[f["raw_email_id"]] > 1:
            issues.append("missing_or_duplicate_source_reference")
        if accounts and str(f.get("account_id")) not in accounts:
            issues.append("missing_account")
        key = tuple(str(f.get(k)) for k in ("account_id", "ticker", "instrument_type", "option_type", "strike", "expiration", "side")) + (clock,)
        timestamp_groups[key].append(str(f["id"]))
        source_audit.append({"fill_id": str(f["id"]), "source_kind": source_kind(f), "issues": issues,
                             "linked_trade_ids": sorted(owners.get(str(f["id"]), set()))})
    ambiguous_ids = {fid for group in timestamp_groups.values() if len(group) > 1 for fid in group}
    records, audit = [], []
    for tid, t in sorted(trades.items()):
        reasons = []
        fs = [f for f, _ in linked[tid]]
        accounting = []
        entry = None
        opened = closed = None
        try:
            opened = wall(t["opened_at"])
            closed = wall(t["closed_at"]) if t.get("closed_at") else None
            if opened > as_of or (closed and (closed < opened or closed > as_of)):
                reasons.append("invalid_or_future_trade_time")
            entry = min((f for f in fs if f["side"] in ref.OPEN_SIDES), key=lambda f: (wall(f["executed_at"]), str(f["id"])))
            if wall(entry["executed_at"]) != opened:
                reasons.append("entry_time_disagrees_with_fill")
            for f, role in linked[tid]:
                allowed_sides = ("buy", "sell") if f.get("instrument_type") == "stock" else ("buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close")
                if f.get("instrument_type") not in ("stock", "option") or f.get("side") not in allowed_sides:
                    reasons.append("invalid_instrument_or_side")
                if not same_identity(f, t):
                    reasons.append("fill_identity_conflict")
                if role != ("entry" if f["side"] in ref.OPEN_SIDES else "exit"):
                    reasons.append("fill_role_conflict")
                when = wall(f["executed_at"])
                if when < opened or when > as_of or (closed and when > closed):
                    reasons.append("fill_outside_trade_interval")
                if not f.get("raw_email_id") or raw_ids[f["raw_email_id"]] > 1:
                    reasons.append("missing_or_duplicate_source_reference")
                if len(owners[str(f["id"])]) > 1:
                    reasons.append("shared_fill_allocation_unverifiable")
                if str(f["id"]) in ambiguous_ids:
                    reasons.append("same_timestamp_order_ambiguous")
            if len({str(f["id"]) for f in fs}) != len(fs):
                reasons.append("duplicate_tradefill_link")
            if accounts and str(t["account_id"]) not in accounts:
                reasons.append("missing_account")
            if t["status"] == "closed" and closed and max(wall(f["executed_at"]) for f in fs) != closed:
                reasons.append("close_time_disagrees_with_fill")
            accounting = ref.compare_values(t, ref.position_ledger(t, fs)["values"], kind="internal_accounting")
            if any(c["status"] == "mismatch" for c in accounting):
                reasons.append("accounting_mismatch")
        except (ValueError, KeyError, TypeError, ArithmeticError):
            reasons.append("invalid_linked_accounting_or_time")
        if any(str(link.get("trade_id")) == tid for link in dangling):
            reasons.append("dangling_fill_link")
        pnl = finite(t.get("realized_pnl"))
        if t.get("status") not in ("closed", "expired") or closed is None:
            reasons.append("not_dated_closed_or_expired")
        if pnl is None:
            reasons.append("missing_or_nonfinite_pnl")
        audit.append({"trade_id": tid, "account_id": str(t.get("account_id")), "ticker": t.get("ticker"),
                      "excluded_reasons": sorted(set(reasons)), "accounting_checks": accounting,
                      "fill_ids": [str(f["id"]) for f in fs], "entry_fill_id": str(entry["id"]) if entry else None})
        if not reasons:
            minute = opened.hour * 60 + opened.minute
            bucket = "premarket" if minute < 570 else "open" if minute < 630 else "mid" if minute < 900 else "close" if minute < 960 else "afterhours"
            ret = finite(t.get("pnl_pct"))
            # Missing recorded return stays unavailable even if recomputable.
            records.append({"id": tid, "account_id": str(t["account_id"]), "ticker": t["ticker"],
                            "opened": opened.isoformat(), "closed": closed.isoformat(), "day": opened.date().isoformat(),
                            "pnl": pnl, "return_pp": ret * 100 if ret is not None else None,
                            "stratum": "/".join((str(t["account_id"]), t["instrument_type"], str(t.get("option_type") or "stock"), entry["side"])),
                            "entry_time": bucket, "repeat_entry": None, "after_close": None, "minutes_since_close": None})
    # Use all trade history, including open/excluded records, before selecting cohorts.
    earliest = {}
    close_batches = defaultdict(lambda: defaultdict(list))
    valid_ids = {r["id"] for r in records}
    for tid, t in trades.items():
        try:
            opened = wall(t["opened_at"])
            key = (str(t["account_id"]), t["ticker"], opened.date().isoformat())
            earliest[key] = min(earliest.get(key, opened), opened)
            if t.get("closed_at") and t.get("status") in ("closed", "expired"):
                closed = wall(t["closed_at"])
                close_batches[(str(t["account_id"]), closed.date().isoformat())][closed].append(finite(t.get("realized_pnl")) if tid in valid_ids else None)
        except (ValueError, KeyError, TypeError):
            pass
    for r in records:
        opened = wall(r["opened"])
        r["repeat_entry"] = "first" if opened == earliest[(r["account_id"], r["ticker"], r["day"])] else "repeat"
        prior = [(when, values) for when, values in close_batches[(r["account_id"], r["day"])].items() if when < opened]
        if opened in close_batches[(r["account_id"], r["day"])]:
            r["after_close"] = None
        elif not prior:
            # A simultaneous close cannot establish what was known before entry.
            r["after_close"] = "no_prior_close"
        else:
            when, values = max(prior, key=lambda pair: pair[0])
            r["minutes_since_close"] = (opened - when).total_seconds() / 60
            if all(v is not None for v in values):
                r["after_close"] = "after_loss" if sum(values) < 0 else "after_nonloss"
    days = sorted({r["day"] for r in records})
    split = holdout_start or (days[min(len(days) - 1, max(1, int(len(days) * 0.7)))] if len(days) >= 2 else None)
    if split:
        split = datetime.fromisoformat(split).date().isoformat()
    discovery = [r for r in records if not split or (r["day"] < split and r["closed"][:10] < split)]
    later = [r for r in records if split and r["day"] >= split]
    crossing = [r["id"] for r in records if split and r["day"] < split and r["closed"][:10] >= split]
    fill_range = []
    for f in fills.values():
        try:
            fill_range.append(wall(f["executed_at"]).isoformat())
        except (ValueError, KeyError, TypeError):
            pass
    context_fields = set(FillMarketContext.model_fields) - {"fill_id", "data_source", "fetched_at", "calculation_version", "entry_context_as_of"}
    path_fields = set(TradePathMetrics.model_fields) - {"trade_id", "data_source", "fetched_at", "calculation_version", "inputs_fingerprint", "market_inputs_fingerprint"}
    freshness = Counter()
    for fid, ctx in contexts.items():
        if fid not in fills:
            freshness["orphan_context"] += 1
            continue
        if ctx.get("calculation_version") != CONTEXT_VERSION:
            freshness["obsolete_context_version"] += 1
        try:
            age = (wall(fills[fid]["executed_at"]) - wall(ctx["entry_context_as_of"])).total_seconds() / 60
            freshness["context_future_as_of" if age < 0 else "context_proxy_over_5_minutes_old" if age > 5 else "context_timing_within_5_minutes"] += 1
        except (ValueError, KeyError, TypeError):
            freshness["context_timing_unknown"] += 1
    for tid, path in paths.items():
        freshness["obsolete_path_version" if path.get("calculation_version") != PATH_VERSION else "current_path_version_inputs_unverified"] += 1
        if tid not in trades:
            freshness["orphan_path"] += 1
    market_leads = []
    audit_by_id = {a["trade_id"]: a for a in audit}
    for field in UNITS:
        if field in ("realized_pnl", "pnl_pct"):
            continue
        values, ids = [], []
        eligible_for_metric = [r for r in records if not field.startswith("option_") or trades[r["id"]]["instrument_type"] == "option"]
        for r in eligible_for_metric:
            if field in context_fields:
                source = contexts.get(audit_by_id[r["id"]]["entry_fill_id"]) or {}
                current = source.get("calculation_version") == CONTEXT_VERSION
            else:
                source = paths.get(r["id"]) or {}
                current = source.get("calculation_version") == PATH_VERSION
            value = finite(source.get(field))
            if current and value is not None:
                values.append(value)
                ids.append(r["id"])
        market_leads.append({"field": field, "unit": UNITS[field], "current_version_present": len(values),
                             "eligible_trade_denominator": len(eligible_for_metric), "median_stored_estimate": statistics.median(values) if values else None,
                             "trade_ids": ids, "status": "requires_frozen_cache_validation",
                             "reason": "Version and presence do not prove unchanged inputs, correct calculations, feed provenance or historical availability"})
    activity = []
    for label in ("after_loss", "after_nonloss"):
        members = [r for r in records if r["after_close"] == label]
        minutes = [r["minutes_since_close"] for r in members]
        activity.append({"label": label, "observed_eligible_entries": len(members),
                         "entries_within_30_minutes": sum(m <= 30 for m in minutes),
                         "median_minutes_since_close": statistics.median(minutes) if minutes else None,
                         "trade_ids": [r["id"] for r in members]})
    discovery_result = comparisons(discovery, draws=draws, seed=seed)
    later_result = comparisons(later, draws=draws, seed=seed + 1)
    later_panels = {(p["stratum"], p["dimension"], p["cohort"]): p for p in later_result["panels"]}
    questions = []
    for p in discovery_result["panels"]:
        other = later_panels.get((p["stratum"], p["dimension"], p["cohort"]))
        if not other:
            continue
        ci, later_ci = p["simultaneous_interval_pp"], other["simultaneous_interval_pp"]
        if ci and later_ci and ((ci[0] > 0 and later_ci[0] > 0) or (ci[1] < 0 and later_ci[1] < 0)):
            questions.append({"stratum": p["stratum"], "dimension": p["dimension"], "cohort": p["cohort"],
                              "discovery_effect_pp": p["effect_return_pp"], "later_effect_pp": other["effect_return_pp"],
                              "status": "retrospective_question_for_prospective_check_only"})
    return {"analysis_revision": "d0-v1", "snapshot_at": snapshot["snapshot_at"], "snapshot_sha256": sha(snapshot),
            "dataset_label": snapshot.get("capture", {}).get("dataset_label", "unspecified; verify provenance before interpreting"),
            "snapshot_consistency": snapshot.get("capture", {}).get("consistent_transaction", "unverified_supplied_snapshot"),
            "accounts": snapshot.get("accounts", []), "fill_date_range_et": [min(fill_range), max(fill_range)] if fill_range else None,
            "counts": {"fills": len(fills), "trades": len(trades), "contexts": len(contexts), "paths": len(paths), "eligible": len(records), "excluded": len(audit) - len(records),
                       "unlinked_fills": len(set(fills) - set(owners)), "dangling_links": len(dangling)},
            "source_reference_counts": dict(Counter(source_kind(f) for f in fills.values())),
            "source_issue_counts": dict(Counter(issue for item in source_audit for issue in item["issues"])),
            "source_audit": source_audit,
            "source_payload_present": sum(bool(f.get("has_source_payload")) for f in fills.values()),
            "source_payload_presence_unknown": sum("has_source_payload" not in f for f in fills.values()),
            "unlinked_fill_ids": sorted(set(fills) - set(owners)), "dangling_links": dangling,
            "exclusion_counts": dict(Counter(reason for a in audit for reason in a["excluded_reasons"])),
            "accounting_check_counts": dict(Counter(c["status"] for a in audit for c in a["accounting_checks"])),
            "eligible_summary": summarize(records),
            "account_summaries": {aid: summarize([r for r in records if r["account_id"] == aid]) for aid in sorted({str(t["account_id"]) for t in trades.values()})},
            "coverage": {"fill_enrichment": coverage(list(fills.values()), {k for k in Fill.model_fields if k.endswith("_at_fill")}),
                         "context": coverage(list(contexts.values()), context_fields, CONTEXT_VERSION),
                         "path": coverage(list(paths.values()), path_fields, PATH_VERSION)},
            "freshness": dict(freshness), "market_leads": market_leads, "activity_after_closes": activity,
            "holdout_start_et": split, "boundary_crossing_trade_ids": crossing,
            "method": {"seed": seed, "bootstrap_draws": draws, "cluster": "New York entry date across accounts",
                       "minimum_display_policy": "20 return observations and 10 days in each cohort and its complement",
                       "interval": "Approximate simultaneous 95% day-cluster bootstrap max-deviation intervals within each period",
                       "baseline": "All other known categories for the dimension in the same account/instrument/option-type/opening-side stratum",
                       "period_policy": "First 70% of entry dates for discovery, remaining dates for later checks unless explicit split; discovery excludes closes on/after split"},
            "discovery": discovery_result, "later_check": later_result, "prospective_questions": questions,
            "records": records, "trade_audit": audit,
            "limits": ["Broker completeness and source execution timestamps are not independently verified; naive times follow the repository New York convention.",
                       "Accounting agreement is internal, gross of unstored fees, and does not reconcile broker lot selection.",
                       "PnL, win rate and return are journal trade outcomes, not account equity, planned risk or R-multiples.",
                       "Returns use cumulative entry cost/premium; short-option premium is not capital at risk. Strata must not be pooled as equivalent risk.",
                       "Excluded/open trades can change apparent activity. Counts are eligible entries, not an exposure-adjusted entry rate or motivation diagnosis.",
                       "After-loss means most recent strictly prior same-account same-day final-close batch had negative verified total PnL; partial exits and earlier-day losses are not classified.",
                       "Later checks are retrospective and approximate; all dimensions remain exploratory, with no causal or future-edge claim.",
                       "Intervals handle within-day clustering and the displayed family within each period, not serial day dependence, hidden research trials or confounding by size/regime.",
                       "Entry extension, trend alignment and path outcomes remain investigation leads until frozen provider caches validate timing, inputs and values.",
                       "Underlying moves and option-premium outcomes are distinct. Minute extrema and hindsight MFE are estimates, not executable exits."]}


def markdown(report):
    def fmt(value):
        return "unavailable" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value)
    lines = ["# D0 journal data audit", "", f"Dataset: {report['dataset_label']}.",
             f"Snapshot: {report['snapshot_at']}; consistency: {report['snapshot_consistency']}.",
             f"Canonical snapshot SHA256: `{report['snapshot_sha256']}`.",
             f"Fill range (New York): {report['fill_date_range_et']}. Accounts: " + ", ".join(f"{a.get('name', 'unnamed')} (`{a['id']}`)" for a in report['accounts']),
             "", "**Exploratory internal evidence. Broker completeness, execution-time source truth and market inputs remain unverified.**", "",
             f"Available/excluded: {report['counts']}. Exclusion reasons overlap: {report['exclusion_counts']}.",
             f"Internal accounting check statuses: {report['accounting_check_counts']}.",
             f"Source references: {report['source_reference_counts']}; payload-present flags: {report['source_payload_present']} (not source reconciliation).", "",
             f"Source-row issue counts, including unlinked fills: {report['source_issue_counts']}.", "",
             "## Account outcome coverage", "", "| Account ID | Eligible trades | Entry days | Recorded returns | Gross PnL $ | Mean entry-cost return % |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for aid, summary in report["account_summaries"].items():
        lines.append(f"| {aid} | {summary['trades']} | {summary['days']} | {summary['return_observations']} | {fmt(summary['total_pnl_usd'])} | {fmt(summary['mean_return_pct'])} |")
    lines += ["",
             "## Metric availability and freshness", "", f"Timing/version flags: {report['freshness']}.",
             "All field coverage is in report.json. Denominators below inventory stored rows and can include inapplicable instrument fields; absent entire context/path rows are additional missing observations. Entry/path leads below use applicable eligible trades.", "",
             "| Metric | Unit | Present / stored rows | Obsolete version present |", "| --- | --- | ---: | ---: |"]
    for group in report["coverage"].values():
        for field, c in group.items():
            if field in UNITS:
                lines.append(f"| {field} | {c['unit']} | {c['present']} / {c['rows']} | {fmt(c['obsolete_version_present'])} |")
    lines += ["", "## Personal-pattern comparisons", "", f"Later period starts {report['holdout_start_et']}; discovery boundary exclusions: {len(report['boundary_crossing_trade_ids'])}.",
              report["method"]["baseline"] + ".", report["method"]["interval"] + ".",
              "Return effects are percentage points of cumulative entry-cost return. Mean PnL effects are USD. Breakevens count in win-rate denominators.",
              "Small cohorts remain insufficient evidence; the display threshold does not establish an edge."]
    for phase in ("discovery", "later_check"):
        family = report[phase]
        lines += ["", f"### {phase}", "", f"Comparisons attempted: {family['comparisons_attempted']}; interval family: {family['interval_family_size']}.", "",
                  "| Account/instrument/type/side | Dimension: cohort | n / baseline n | Return n / baseline n | Days / baseline days | Unknown dimension n | Mean return % / baseline % | Win % / baseline % | Mean PnL effect $ | Return effect pp | Simultaneous interval pp | Status | Records |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
        for p in family["panels"]:
            a, b = p["cohort_summary"], p["baseline_summary"]
            anchors = " ".join(f"[trade](records.md#trade-{tid})" for tid in a["trade_ids"][:3]) or "none"
            interval = p["simultaneous_interval_pp"]
            interval_text = f"[{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "unavailable"
            lines.append(f"| {p['stratum']} | {p['dimension']}: {p['cohort']} | {a['trades']} / {b['trades']} | {a['return_observations']} / {b['return_observations']} | {a['days']} / {b['days']} | {p['dimension_unavailable']} | {fmt(a['mean_return_pct'])} / {fmt(b['mean_return_pct'])} | {fmt(a['win_rate_pct'])} / {fmt(b['win_rate_pct'])} | {fmt(p['effect_mean_pnl_usd'])} | {fmt(p['effect_return_pp'])} | {interval_text} | {p['status']} | {anchors} |")
    lines += ["", "## Activity after closes", "", "Counts use all eligible finished trades. They omit open and excluded entries; they cannot establish a change in entry rate.", ""]
    for row in report["activity_after_closes"]:
        lines.append(f"- {row['label']}: {row['observed_eligible_entries']} entries, {row['entries_within_30_minutes']} within 30 minutes; median gap {fmt(row['median_minutes_since_close'])} minutes.")
    lines += ["", "## Entry/path questions needing better evidence", ""]
    for lead in report["market_leads"]:
        lines.append(f"- `{lead['field']}`: {lead['current_version_present']} / {lead['eligible_trade_denominator']} eligible trades have a current-version value; median stored estimate {fmt(lead['median_stored_estimate'])} {lead['unit']}. Requires frozen-cache validation before comparing outcomes.")
    lines += ["", "## Questions for prospective checking", ""]
    if report["prospective_questions"]:
        for q in report["prospective_questions"]:
            lines.append(f"- {q['stratum']} / {q['dimension']} / {q['cohort']}: discovery {q['discovery_effect_pp']:.2f} pp, later {q['later_effect_pp']:.2f} pp. Both retrospective intervals share direction; resolve remaining data/confounding issues before a prospective check.")
    else:
        lines.append("No comparison has a supported simultaneous interval with the same nonzero direction in both periods. No pattern is ready to promote from this report.")
    lines += ["", "Investigate extension versus completed-minute VWAP, independently defined trend alignment, and option capture/giveback only after those input checks. Missing planned risk, intent and reflection cannot be reconstructed from results.",
              "No pattern is promoted to a rule or UI feature. A later-period direction agreement is a candidate for prospective J5 checking, subject to remaining data limitations.", "", "## Limits", ""]
    lines += [f"- {limit}" for limit in report["limits"]]
    lines += ["", "[Contributing records and exclusions](records.md). Every cohort and complement has its full trade ID list in report.json. Source fills are in snapshot.json.", ""]
    return "\n".join(lines)


def record_markdown(report):
    by_id = {r["id"]: r for r in report["records"]}
    lines = ["# D0 contributing records", ""]
    for a in report["trade_audit"]:
        tid = a["trade_id"]
        lines += [f'<a id="trade-{tid}"></a>', f"## {a['ticker']} — {tid}", "",
                  f"Account: `{a['account_id']}`. Fills: " + ", ".join(f"`{fid}`" for fid in a["fill_ids"]) + ".",
                  f"Exclusions: {a['excluded_reasons'] or 'none'}.",
                  "Eligible observation: " + json.dumps(by_id.get(tid), sort_keys=True), ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--sqlite", type=Path)
    source.add_argument("--postgres-url-env", help="Explicit environment variable containing PostgreSQL URL; no dotenv or ambient DATABASE_URL lookup")
    parser.add_argument("--output-dir", type=Path, required=True, help="New private directory; existing paths are refused")
    parser.add_argument("--holdout-start", help="New York date YYYY-MM-DD")
    parser.add_argument("--bootstrap-draws", type=int, default=1000)
    args = parser.parse_args(argv)
    stage = "source input"
    try:
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; use a new directory")
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text())
        elif args.sqlite:
            with sqlite3.connect(args.sqlite.resolve().as_uri() + "?mode=ro", uri=True) as db:
                db.execute("PRAGMA query_only=ON")
                snapshot = capture(db)
        else:
            import psycopg
            url = postgres_url(os.environ.get(args.postgres_url_env))
            stage = "PostgreSQL connection"
            with psycopg.connect(url, autocommit=True, connect_timeout=10) as db:
                stage = "read-only PostgreSQL snapshot"
                snapshot = capture(db, postgres=True)
        stage = "offline snapshot analysis"
        report = analyze(snapshot, holdout_start=args.holdout_start, draws=args.bootstrap_draws)
        stage = "local report output"
        args.output_dir.mkdir(parents=True, mode=0o700)
        for name, content in (("snapshot.json", json.dumps(snapshot, indent=2)), ("report.json", json.dumps(report, indent=2)),
                              ("report.md", markdown(report)), ("records.md", record_markdown(report))):
            with (args.output_dir / name).open("x") as output:
                output.write(content)
        print(json.dumps({"output_dir": str(args.output_dir.resolve()), "counts": report["counts"], "snapshot_sha256": report["snapshot_sha256"]}))
        return 0
    except InputError as exc:
        print(f"D0 input error: {exc} No source writes were requested.", file=sys.stderr)
        return 2
    except Exception as exc:
        # Driver errors can include credentials/hosts; never print their text.
        state = getattr(exc, "sqlstate", None)
        diagnostic = f"; SQLSTATE {state}" if isinstance(state, str) and len(state) == 5 and state.isalnum() else ""
        print(f"D0 failed during {stage} ({type(exc).__name__}{diagnostic}); verify explicit source, schema and output path. No source writes were requested.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
