"""Read-only validation orchestration. Cache reads never fetch or create files."""
import hashlib
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from app.engine import metric_reference as reference
from app.engine.metric_versions import CONTEXT_VERSION, PATH_VERSION

CONTEXT_FIELDS = (
    "entry_underlying_price", "entry_vwap", "entry_vs_vwap_pct", "entry_volume", "cumulative_volume_at_entry",
    "entry_day_high_so_far", "entry_day_low_so_far", "entry_day_range_used_pct", "entry_context_as_of",
    "premarket_high", "premarket_low", "opening_range_5m_high", "opening_range_5m_low",
    "opening_range_15m_high", "opening_range_15m_low",
)
OPTION_FIELDS = (
    "option_mfe_pct", "option_mae_pct", "option_peak_unrealized_pnl", "option_worst_unrealized_pnl",
    "option_peak_total_pnl", "option_giveback_from_peak", "option_exit_efficiency", "option_giveback_pct",
    "option_max_price_seen", "option_min_price_seen", "time_to_option_mfe_minutes",
)
UNDERLYING_FIELDS = ("underlying_mfe_pct", "underlying_mae_pct", "time_to_underlying_mfe_minutes",
                     "time_to_underlying_mae_minutes", "moved_in_favor_first")


def record(model):
    return json.loads(model.model_dump_json(exclude={"email_subject", "email_body_text"}, warnings=False))


class CachedBars:
    def __init__(self, root: Path, feed: str):
        self.root, self.feed = Path(root), feed

    @lru_cache(maxsize=512)
    def read(self, path):
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            raise ValueError("Bar cache is not an array")
        return data

    def minute(self, ticker, day):
        return self.read(self.root / "stocks" / "1Min" / self.feed / ticker / f"{day}.json")

    def daily(self, ticker):
        return self.read(self.root / "stocks" / "1Day" / self.feed / f"{ticker}.json")

    def window(self, trade):
        if not trade.get("closed_at"):
            return []
        start = reference.timestamp(trade["opened_at"]).astimezone(reference.ET).date()
        end = reference.timestamp(trade["closed_at"]).astimezone(reference.ET).date()
        if (end - start).days + 1 > 10:
            return []
        bars = []
        for offset in range((end - start).days + 1):
            bars.extend(self.minute(trade["ticker"], start + timedelta(days=offset)))
        return bars

    def option(self, trade):
        if not all(trade.get(k) is not None for k in ("expiration", "option_type", "strike", "closed_at")):
            return []
        # OCC identity is serialization, not a shared financial calculation.
        from app.engine.occ import occ_symbol
        symbol = occ_symbol(trade["ticker"], reference.timestamp(f"{trade['expiration']}T00:00:00").date(),
                            trade["option_type"], float(trade["strike"]))
        start = reference.timestamp(trade["opened_at"]).astimezone(reference.ET)
        end = reference.timestamp(trade["closed_at"]).astimezone(reference.ET)
        def key(t):
            return t.isoformat().replace(":", "").replace("+", "")
        # Read only the exact intraday window, never substitute daily bars.
        return self.read(self.root / "options" / "1Min" / symbol / f"{key(start)}_{key(end)}.json")


def evidence(call):
    """Keep malformed/missing market evidence separate from accounting."""
    try:
        return call()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"values": {}, "reason": f"Invalid cached evidence: {exc}", "error": True}


def validate_fill(fill, stored, cache):
    day = reference.timestamp(fill["executed_at"]).astimezone(reference.ET).date()
    intraday = evidence(lambda: reference.entry_context(fill, cache.minute(fill["ticker"], day)))
    daily = evidence(lambda: reference.daily_indicators(cache.daily(fill["ticker"]), fill["executed_at"]))
    expected = {key: intraday["values"].get(key) for key in CONTEXT_FIELDS}
    source_reason = "Stored feed differs from selected cache feed" if stored and stored.get("data_source") != f"alpaca_{cache.feed}" else None
    checks = reference.compare_values(stored or {}, expected,
        stale=bool(stored and stored.get("calculation_version") != CONTEXT_VERSION), unavailable_reason=source_reason or intraday["reason"])
    if intraday.get("error"):
        for check in checks:
            check["status"] = "error"
    if daily["values"]:
        daily_expected = {k: v for k, v in daily["values"].items() if k != "previous_day_close"}
        if intraday["values"]:
            op = intraday["values"].get("today_open")
            prev = daily["values"].get("previous_day_close")
            daily_expected["entry_gap_pct"] = reference.percent(reference.number(op) if op is not None else None, reference.number(prev) if prev is not None else None)
        checks.extend(reference.compare_values(stored or {}, daily_expected,
            stale=bool(stored and stored.get("calculation_version") != CONTEXT_VERSION), unavailable_reason=source_reason))
    else:
        checks.append({"field": "daily_indicators", "status": "error" if daily.get("error") else "unavailable", "reason": daily["reason"], "kind": "observed_estimate"})
    if intraday["values"]:
        flags = reference.context_flags(fill, intraday["values"], daily["values"])
        checks.extend(reference.compare_values(stored or {}, flags,
            stale=bool(stored and stored.get("calculation_version") != CONTEXT_VERSION), unavailable_reason=source_reason))
    if stored and stored.get("setup_quality_score") is not None:
        checks.append({"field": "setup_quality_score", "stored": stored["setup_quality_score"], "status": "unavailable",
                       "reason": "Heuristic score; this report does not independently validate its weighting or predictive value", "kind": "heuristic"})
    return {"fill_id": str(fill["id"]), "checks": checks, "intraday": intraday, "daily": daily}


def validate_trade(trade, fills, contexts, path, cache, include_samples=False):
    checks = []
    ledger = reference.position_ledger(trade, fills)
    checks.extend(reference.compare_values(trade, ledger["values"], kind="internal_accounting"))
    entry = min((f for f in fills if f["side"] in reference.OPEN_SIDES),
                key=lambda f: (reference.timestamp(f["executed_at"]), str(f["id"])))
    fill_reports = [validate_fill(f, contexts.get(str(f["id"])), cache) for f in fills]
    for report in fill_reports:
        checks.extend({**check, "fill_id": report["fill_id"]} for check in report["checks"])
    underlying = option = None
    if trade.get("closed_at"):
        ctx = contexts.get(str(entry["id"])) or {}
        anchor = ctx.get("entry_underlying_price") or entry.get("underlying_price_at_fill")
        if anchor is None and trade["instrument_type"] == "stock":
            anchor = ledger["values"]["avg_entry_premium"]
        underlying = evidence(lambda: reference.underlying_path(trade, entry, cache.window(trade), anchor))
        checks.extend(reference.compare_values(path or {}, {k: underlying["values"].get(k) for k in UNDERLYING_FIELDS},
            stale=bool(path and path.get("calculation_version") != PATH_VERSION), unavailable_reason=underlying["reason"] or ("Stored path feed differs from selected cache feed" if path and not str(path.get("data_source", "")).startswith(f"alpaca_{cache.feed}") else None)))
        if trade["instrument_type"] == "option":
            option = evidence(lambda: reference.option_path(trade, fills, cache.option(trade)))
            checks.extend(reference.compare_values(path or {}, {k: option["values"].get(k) for k in OPTION_FIELDS},
                stale=bool(path and path.get("calculation_version") != PATH_VERSION), unavailable_reason=option["reason"]))
    for result, fields in ((underlying, UNDERLYING_FIELDS), (option, OPTION_FIELDS)):
        if result and result.get("error"):
            for check in checks:
                if check["field"] in fields and "fill_id" not in check:
                    check["status"] = "error"
    if not include_samples:
        for result in (underlying, option):
            if result:
                result.pop("samples", None)
    # Source verification is always separate: these inputs have no broker export.
    return {"trade_id": str(trade["id"]), "ticker": trade["ticker"], "checks": checks,
            "broker_verification": "not_performed", "accounting": ledger["values"],
            "fills": fill_reports, "underlying": underlying, "option": option,
            "limits": ["Same cached provider inputs; agreement is not independent source verification",
                       "Minute-bar extrema are estimates, not executable quotes", "Fees are not stored in this fill schema",
                       "Underlying entry anchors are supplied evidence, not independently verified fills",
                       "Coverage excludes hourly context, RVOL, Greeks, chase/sequence scores, underlying efficiency and post-exit metrics"]}


def evidence_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def build_report(snapshot, cache, *, sample_size=30):
    from collections import Counter, defaultdict
    fills = {str(f["id"]): f for f in snapshot["fills"]}
    contexts = {str(c["fill_id"]): c for c in snapshot.get("contexts", [])}
    paths = {str(p["trade_id"]): p for p in snapshot.get("paths", [])}
    grouped = defaultdict(list)
    linked = set()
    for link in snapshot["links"]:
        grouped[str(link["trade_id"])].append(fills[str(link["fill_id"])])
        linked.add(str(link["fill_id"]))
    reports = []
    for trade in snapshot["trades"]:
        try:
            reports.append(validate_trade(trade, grouped[str(trade["id"])], contexts, paths.get(str(trade["id"])), cache))
        except (ValueError, KeyError, TypeError) as exc:
            reports.append({"trade_id": str(trade["id"]), "ticker": trade.get("ticker"),
                            "checks": [{"field": "input_integrity", "status": "error", "reason": str(exc), "kind": "internal_accounting"}]})
    counts = Counter(check["status"] for report in reports for check in report["checks"])
    accounting = Counter(check["status"] for report in reports for check in report["checks"] if check.get("kind") == "internal_accounting")
    # Deliberately prioritize diverse hard cases for manual review, then stable
    # ids for reproducibility. Selection is not a representative random sample.
    by_id = {str(t["id"]): t for t in snapshot["trades"]}
    def categories(report):
        t = by_id[report["trade_id"]]
        fs = grouped[report["trade_id"]]
        opening = [f for f in fs if f["side"] in reference.OPEN_SIDES]
        closing = [f for f in fs if f["side"] not in reference.OPEN_SIDES]
        kinds = {t.get("instrument_type"), t.get("option_type"), t.get("status")}
        if len(opening) > 1:
            kinds.add("scale_in")
        if len(closing) > 1:
            kinds.add("scale_out")
        if t.get("closed_at") and str(t["opened_at"])[:10] != str(t["closed_at"])[:10]:
            kinds.add("overnight")
        if opening and reference.timestamp(opening[0]["executed_at"]).astimezone(reference.ET).hour == 9:
            kinds.add("near_open")
        return kinds - {None}
    remaining = sorted(reports, key=lambda r: r["trade_id"])
    sample, covered = [], set()
    while remaining and len(sample) < sample_size:
        best = max(remaining, key=lambda r: (len(categories(r) - covered), any(c["status"] == "mismatch" for c in r["checks"])))
        covered |= categories(best)
        sample.append(best["trade_id"])
        remaining.remove(best)
    review = []
    for trade_id in sample:
        t = by_id[trade_id]
        try:
            detail = validate_trade(t, grouped[trade_id], contexts, paths.get(trade_id), cache, include_samples=True)
            detail["source_fills"] = sorted(grouped[trade_id], key=lambda f: (reference.timestamp(f["executed_at"]), f["side"] not in reference.OPEN_SIDES, str(f["id"])))
            detail["categories"] = sorted(categories(detail))
            review.append(detail)
        except (ValueError, KeyError, TypeError) as exc:
            review.append({"trade_id": trade_id, "ticker": t.get("ticker"), "error": str(exc)})
    return {"reference_revision": reference.REFERENCE_REVISION, "generated_at": datetime.now(reference.UTC).isoformat(),
            "snapshot_at": snapshot.get("snapshot_at"), "snapshot_sha256": evidence_hash(snapshot), "feed": cache.feed,
            "broker_verification": "not_performed", "trade_count": len(reports), "fill_count": len(fills),
            "unlinked_fill_ids": sorted(set(fills) - linked), "counts": dict(counts), "accounting_counts": dict(accounting),
            "review_samples": review, "review_sample_ids": sample, "sample_categories": sorted(covered), "trades": reports}
