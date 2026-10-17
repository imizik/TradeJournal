"""Offline checks of saved Jo evidence. No model, provider or application DB imports.

Hashes establish internal consistency, not independent source authenticity.
Literal claims are checked; unparsed prose and discretionary judgments are not
graded. Outcomes enter only through a separately supplied revealed comparison.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import hashlib
import json
import math
import re
import statistics
import uuid
from zoneinfo import ZoneInfo

VERSION = "jo-decision-audit-v1"
MAX_ROWS = 2000
DECISIONS = {"take", "skip", "insufficient_data"}
NUMBER = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
LIMITS = [
    "Literal numeric checks do not establish sound judgment or trading skill.",
    "Unparsed, ambiguous and missing claims remain unverified, never counted as passes.",
    "Hashes check supplied evidence consistency; they are not an independent source attestation.",
    "Historical underlying R is not an options return or an executable portfolio return.",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite numeric evidence required")
    if positive and value <= 0:
        raise ValueError("Positive price required")
    return value


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Explicit timestamp offset required")
    return result.astimezone(timezone.utc)


def hash_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("SHA256 required")
    return value


def rounded_equal(text, expected):
    """Honor the precision actually quoted, including scientific notation."""
    quoted = Decimal(text)
    tolerance = Decimal(5).scaleb(quoted.as_tuple().exponent - 1)
    return abs(quoted - Decimal(str(expected))) <= tolerance + Decimal("1e-12")


def supported_literal(text):
    try:
        value = Decimal(text)
        return value.is_finite() and abs(value.as_tuple().exponent) <= 308 and abs(value.adjusted()) <= 308
    except DecimalException:
        return False


def card_facts(card):
    cutoff = timestamp(card["simulated_as_of"])
    entry, stop = finite(card["entry_reference"], positive=True), finite(card["stop"], positive=True)
    target = finite(card["target_reference"], positive=True)
    side = card["candidate"]["side"]
    if side not in (-1, 1) or type(side) is not int or (entry - stop) * side <= 0 or (target - entry) * side <= 0:
        raise ValueError("Invalid directional geometry")
    features = card["features"]
    values = {k: None if features.get(k) is None else finite(features[k])
              for k in ("day_move", "trend", "rvol", "vol_ratio")}
    bars = card["candles"]
    if not isinstance(bars, list) or not 1 <= len(bars) <= 500:
        raise ValueError("Bounded pre-cutoff candles required")
    last = None
    for bar in bars:
        start, end = timestamp(bar["start"]), timestamp(bar["end"])
        if not start < end <= cutoff or (last is not None and start < last):
            raise ValueError("Future or overlapping candle")
        o, h, lo, c = (finite(bar[k], positive=True) for k in ("open", "high", "low", "close"))
        if not lo <= min(o, c) <= max(o, c) <= h or finite(bar["volume"]) < 0:
            raise ValueError("Invalid candle evidence")
        last = end
    if last != cutoff or not math.isclose(bars[-1]["close"], entry, rel_tol=1e-9):
        raise ValueError("Entry/cutoff does not match frozen candle")
    median = statistics.median(b["volume"] for b in bars[-6:-1]) if len(bars) >= 6 else None
    day, trend = values["day_move"], values["trend"]
    category = ("unknown" if day is None or trend is None else "aligned" if day >= 0 and trend >= 0
                else "adverse" if day < 0 and trend < 0 else "mixed")
    return {**values, "entry": entry, "stop": stop, "risk": abs(entry - stop),
            "cost_r": finite(card["estimated_round_trip_cost_r"]),
            "bar_volume_ratio": bars[-1]["volume"] / median if median else None,
            "context": category,
            "volume_reference_crosses_session": any(timestamp(b["start"]).astimezone(ZoneInfo("America/New_York")).date()
                != timestamp(bars[-1]["start"]).astimezone(ZoneInfo("America/New_York")).date() for b in bars[-6:-1])}


def claims(reason, facts):
    """Parse only explicit labels; never infer a number's meaning from proximity."""
    quoted, unsupported = defaultdict(list), set()
    for match in re.finditer(r"C=\[\s*" + NUMBER + r"\s*[,/]\s*" + NUMBER + r"\s*;", reason, re.I):
        quoted["day_move"].append(match[1])
        quoted["trend"].append(match[2])
    # Only a delimited scalar is verified. Free prose, ranges and unsupported
    # units remain unverified, including when another occurrence looks valid.
    for field, label in (("risk", "risk"), ("cost_r", "cost"), ("rvol", "rvol"),
                         ("vol_ratio", "vol_ratio"), ("entry", "entry(?: reference)?"), ("stop", "stop")):
        pattern = r"\b" + label + r"\s*[:=@]?\s*\$?" + NUMBER
        for match in re.finditer(pattern, reason, re.I):
            tail = reason[match.end():]
            unit = (r"\s*R\b" if field == "cost_r" else
                    r"\s+(?:USD|dollars?)\b" if field in {"entry", "stop", "risk"} else None)
            unit_match = re.match(unit, tail, re.I) if unit else None
            if unit_match:
                tail = tail[unit_match.end():]
            if (field == "cost_r" and not unit_match or
                    re.match(r"\s*[,;:]?\s*(?:[-–—/+±]|(?:to|or|through|and)\b\s*[-+\d.])", tail, re.I) or
                    re.match(r",\d", tail) or
                    not re.match(r"(?:\s*(?:$|[,;\]\)]))|(?:\.(?:\s|$))", tail)):
                unsupported.add(field)
            else:
                quoted[field].append(match[1])
    for body in re.findall(r"V=\[([^\]]*)\]", reason, re.I):
        # Consume the WHOLE bracket. Only the frozen rubric's known suffixes
        # are accepted; punctuation must not hide an alternative scalar.
        match = re.fullmatch(r"\s*" + NUMBER + r"\s*[x×]\s*(?:preceding[- ]five median)?\s*(?:;\s*rvol\s*" + NUMBER + r")?\s*", body, re.I)
        if not match:
            unsupported.add("bar_volume_ratio")
        else:
            quoted["bar_volume_ratio"].append(match[1])
    result = []
    for field in ("day_move", "trend", "entry", "stop", "risk", "cost_r", "rvol", "vol_ratio", "bar_volume_ratio"):
        texts, expected = quoted[field], facts[field]
        state = ("missing_evidence" if expected is None else "unparsed" if not all(supported_literal(t) for t in texts)
                 else "ambiguous" if texts and field in unsupported else "unparsed" if not texts
                 else "ambiguous" if len(set(texts)) != 1 else "match" if rounded_equal(texts[0], expected) else "mismatch")
        result.append({"field": field, "quoted": texts, "expected": expected, "status": state})
    categories, category_unsupported = [], False
    for body in re.findall(r"C=\[([^\]]*)\]", reason, re.I):
        match = re.fullmatch(r"[^;]*;\s*(aligned|mixed|adverse|unknown)\s*(?:;(.*))?", body, re.I)
        if not match or re.match(r"\s*(?:or|and|to|through)\b", match[2] or "", re.I):
            category_unsupported = True
        else:
            categories.append(match[1].lower())
    state = ("missing_evidence" if facts["context"] == "unknown" else "unparsed" if not categories else "ambiguous" if category_unsupported or len(set(categories)) != 1
             else "match" if categories[0] == facts["context"] else "mismatch")
    result.append({"field": "context", "quoted": categories, "expected": facts["context"], "status": state})
    return result


def validate_run(run):
    manifest = run["manifest"]
    if (manifest["kind"] != "opportunity_feed" or manifest["exam_count"] != 0
            or set(manifest["phases"].values()) != {"practice"}
            or run["run_id"] not in manifest["run_ids"].values()
            or digest(manifest) != run["policy_hash"]):
        raise ValueError("Practice assignment integrity failed")
    hash_string(manifest["source_manifest_sha256"])
    if not isinstance(manifest["prompt_text"], str) or not 1 <= len(manifest["prompt_text"]) <= 32000:
        raise ValueError("Bounded frozen prompt required")
    uuid.UUID(run["run_id"])
    rows = run["rows"]
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("Too many saved decisions")
    seen = set()
    for row in rows:
        receipt, packet = row["receipt"], row["evidence"]
        if (digest(receipt) != row["receipt_sha256"] or digest(packet) != row["evidence_sha256"]
                or receipt["context_sha256"] != row["evidence_sha256"]
                or receipt["policy_hash"] != run["policy_hash"]
                or receipt["prompt_version"] != manifest["prompt_version"]
                or receipt["run_id"] != run["run_id"] or row["actor"] != "agent:" + manifest["actor"]
                or receipt["opportunity_id"] != packet["opportunity_id"]
                or receipt["candidate_id"] != packet["candidate"]["candidate_id"]
                or receipt["decision"] not in DECISIONS):
            raise ValueError("Receipt/evidence/assignment binding failed")
        card = packet["opportunity"]
        key = card["id"]
        candidate_id = str(uuid.uuid5(uuid.UUID(run["run_id"]), key))
        if receipt["candidate_id"] != candidate_id or receipt["opportunity_id"] != str(uuid.uuid5(uuid.UUID(run["run_id"]), candidate_id)):
            raise ValueError("Saved receipt belongs to a different source card")
        if key in seen:
            raise ValueError("Duplicate saved card")
        seen.add(key)
        if not isinstance(receipt["reason"], str) or not 1 <= len(receipt["reason"]) <= 1000:
            raise ValueError("Bounded saved rationale required")
        elapsed = (timestamp(receipt["committed_at"]) - timestamp(receipt["served_at"])).total_seconds()
        if elapsed < 0 or not math.isclose(finite(receipt["wall_seconds"]), elapsed, abs_tol=1e-5):
            raise ValueError("Receipt timing mismatch")
        card_facts(card)


def audit_export(snapshot):
    if snapshot["format"] != "jo-decision-evidence-v1" or not 1 <= len(snapshot["runs"]) <= 20:
        raise ValueError("Unsupported evidence export")
    timestamp(snapshot["exported_at"])
    rows, runs, contrasts, seen = [], [], [], set()
    for run in snapshot["runs"]:
        validate_run(run)
        if run["run_id"] in seen:
            raise ValueError("Duplicate run")
        seen.add(run["run_id"])
        manifest = run["manifest"]
        local, groups = [], defaultdict(list)
        for saved in run["rows"]:
            receipt, card = saved["receipt"], saved["evidence"]["opportunity"]
            facts = card_facts(card)
            checks = claims(receipt["reason"], facts)
            warnings = []
            if re.search(r"\bvolume[- ]ratio\b", receipt["reason"], re.I):
                warnings.append("Review the meaning of 'volume ratio': vol_ratio is daily ATR5/ATR20, not trading volume. This phrase alone does not prove a factual error.")
            if facts["volume_reference_crosses_session"]:
                warnings.append("The preceding five candle volumes cross a session boundary; this reference is not same-session participation.")
            row = {"run_id": run["run_id"], "source_card_id": card["id"], "opportunity_id": receipt["opportunity_id"],
                   "symbol": card["candidate"]["ticker"], "family": card["family"], "side": card["candidate"]["side"],
                   "cutoff": card["simulated_as_of"], "decision": receipt["decision"], "reason": receipt["reason"],
                   "prompt_version": manifest["prompt_version"], "receipt_sha256": saved["receipt_sha256"],
                   "evidence_sha256": saved["evidence_sha256"], "facts": facts, "checks": checks, "warnings": warnings,
                   "wall_seconds": receipt["wall_seconds"], "resumed": receipt.get("resumed", False)}
            row["mismatches"] = sum(c["status"] == "mismatch" for c in checks)
            local.append(row)
            groups[(row["symbol"], row["family"], row["side"], facts["context"])].append(row)
        for key, group in sorted(groups.items()):
            group.sort(key=lambda r: (timestamp(r["cutoff"]), r["source_card_id"]))
            take = next((r for r in group if r["decision"] == "take"), None)
            skip = next((r for r in group if r["decision"] == "skip"), None)
            if take and skip:
                contrasts.append({"run_id": run["run_id"], "group": list(key),
                                  "take": take["opportunity_id"], "skip": skip["opportunity_id"],
                                  "meaning": "Same symbol, family, side and context category; timestamps and other conditions differ. Review pair, not proof of inconsistency."})
        counts = Counter(c["status"] for r in local for c in r["checks"])
        runs.append({"run_id": run["run_id"], "actor": manifest["actor"], "status": run["status"],
                     "prompt_version": manifest["prompt_version"], "prompt_sha256": hashlib.sha256(manifest["prompt_text"].encode()).hexdigest(),
                     "source_manifest_sha256": manifest["source_manifest_sha256"], "saved_decisions": len(local),
                     "claims": dict(counts), "timing": timing(local)})
        rows.extend(local)
    return {"format": VERSION, "kind": "facts", "source_sha256": digest(snapshot), "exported_at": snapshot["exported_at"],
            "scope": "Saved opportunity decisions only; no outcome fields queried or scored, no claim of complete-run coverage.",
            "limits": LIMITS, "runs": runs, "rows": rows, "contrasts": contrasts,
            "claims": dict(Counter(c["status"] for r in rows for c in r["checks"]))}


def timing(rows):
    values = sorted(finite(r["wall_seconds"]) for r in rows)
    def quantile(q):
        at = (len(values) - 1) * q
        lower = int(at)
        return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (at - lower)
    return {"median_seconds": quantile(.5) if values else None, "p95_seconds": quantile(.95) if values else None,
            "resumed": sum(bool(r.get("resumed")) for r in rows),
            "meaning": "Service-to-commit elapsed time includes interruptions and tool latency; not live execution latency."}


def stats(rows):
    values = [finite(r["outcome"]["r"]) for r in rows if r["outcome"]["resolved"]]
    missing = len(rows) - len(values)
    return {"selected": len(rows), "resolved": len(values), "unresolved": missing,
            "total_r": math.fsum(values) if not missing else None,
            "resolved_only_total_r": math.fsum(values) if values or not rows else None,
            "mean_resolved_r": math.fsum(values) / len(values) if values else None}


def compare_revealed(data, expected_arms, control="control"):
    """Consume an owner-exported, ALREADY revealed study; never open a DB/seal here."""
    timestamp(data["revealed_at"])
    names = [a["assignment"]["arm"] for a in data["arms"]]
    if (not 2 <= len(names) <= 10 or len(set(names)) != len(names) or set(names) != set(expected_arms)
            or len(expected_arms) != len(set(expected_arms)) or control not in names):
        raise ValueError("Require every expected comparison arm exactly once")
    arms = {a["assignment"]["arm"]: a for a in data["arms"]}
    shared, sources, policies, run_ids = {}, set(), set(), set()
    for name, arm in arms.items():
        assignment, rows = arm["assignment"], arm["rows"]
        count = assignment["cards"]
        if type(count) is not int or not 1 <= count <= MAX_ROWS or len(rows) != count:
            raise ValueError("Incomplete comparison; every assigned card must be committed")
        sources.add(hash_string(assignment["source_manifest_sha256"]))
        policies.add(hash_string(assignment["policy_sha256"]))
        hash_string(assignment["prompt_sha256"])
        if assignment["run_id"] in run_ids:
            raise ValueError("Arms must have distinct runs")
        run_ids.add(assignment["run_id"])
        uuid.UUID(assignment["run_id"])
        by_id, receipt_policies, opportunities = {}, set(), set()
        for row in rows:
            receipt, outcome, cid = row["receipt"], row["outcome"], row["source_card_id"]
            candidate_id = str(uuid.uuid5(uuid.UUID(assignment["run_id"]), cid))
            if receipt["candidate_id"] != candidate_id or receipt["opportunity_id"] != str(uuid.uuid5(uuid.UUID(assignment["run_id"]), candidate_id)):
                raise ValueError("Comparison receipt belongs to a different source card")
            if cid in by_id or row["decision"] not in DECISIONS:
                raise ValueError("Duplicate or uncommitted comparison card")
            if (receipt["decision"] != row["decision"] or receipt["reason"] != row["reason"]
                    or receipt["run_id"] != assignment["run_id"]
                    or receipt["prompt_version"] != assignment["prompt_version"]
                    or timestamp(receipt["committed_at"]) > timestamp(data["revealed_at"])):
                raise ValueError("Comparison receipt binding mismatch")
            hash_string(receipt["policy_hash"])
            receipt_policies.add(receipt["policy_hash"])
            if receipt["opportunity_id"] in opportunities or not isinstance(row["reason"], str) or not 1 <= len(row["reason"]) <= 1000:
                raise ValueError("Duplicate opportunity or invalid rationale")
            opportunities.add(receipt["opportunity_id"])
            elapsed = (timestamp(receipt["committed_at"]) - timestamp(receipt["served_at"])).total_seconds()
            if elapsed < 0 or not math.isclose(finite(receipt["wall_seconds"]), elapsed, abs_tol=1e-5):
                raise ValueError("Comparison timing mismatch")
            if type(outcome["resolved"]) is not bool:
                raise ValueError("Explicit outcome resolution required")
            if outcome["resolved"]:
                finite(outcome["r"])
            elif outcome["r"] is not None:
                raise ValueError("Unresolved R must be null")
            timestamp(row["simulated_as_of"])
            for key in ("entry_reference", "stop", "target_reference"):
                finite(row[key], positive=True)
            # Shared immutable market/economic facts must agree across arms.
            fact = {k: row[k] for k in ("candidate", "features", "outcome", "simulated_as_of", "entry_reference",
                                         "stop", "target_reference", "target_r", "max_minutes", "estimated_round_trip_cost_r", "family", "setup", "session")}
            if cid in shared and shared[cid] != fact:
                raise ValueError("Comparison arms saw different facts or outcomes")
            shared[cid] = fact
            by_id[cid] = row
        if len(receipt_policies) != 1:
            raise ValueError("Mixed receipt policies within one arm")
        arm = {**arm, "by_id": by_id}
        arms[name] = arm
    if len(sources) != 1 or len(policies) != 1 or any(set(a["by_id"]) != set(shared) for a in arms.values()):
        raise ValueError("Comparison source, scoring policy or card sets differ")
    base = arms[control]["by_id"]
    summaries, changed = {}, []
    for name, arm in arms.items():
        rows = sorted(arm["rows"], key=lambda r: (timestamp(r["simulated_as_of"]), r["source_card_id"]))
        selected = [r for r in rows if r["decision"] == "take"]
        added = [r for r in selected if base[r["source_card_id"]]["decision"] != "take"]
        removed = [r for r in rows if r["decision"] != "take" and base[r["source_card_id"]]["decision"] == "take"]
        def delta(add, remove):
            return (math.fsum(r["outcome"]["r"] for r in add) - math.fsum(r["outcome"]["r"] for r in remove)
                    if all(r["outcome"]["resolved"] for r in add + remove) else None)
        daily = [{"session": day, **stats([r for r in selected if r["session"] == day]),
                  "delta_r": delta([r for r in added if r["session"] == day], [r for r in removed if r["session"] == day])}
                 for day in sorted({r["session"] for r in rows})]
        summaries[name] = {"assignment": arm["assignment"], **stats(selected), "counts": dict(Counter(r["decision"] for r in rows)),
                           "available": len(rows), "delta_r": delta(added, removed), "added": stats(added), "removed": stats(removed),
                           "timing": timing([r["receipt"] for r in rows]), "by_session": daily}
        for row in added + removed:
            b = base[row["source_card_id"]]
            changed.append({"arm": name, "source_card_id": row["source_card_id"], "symbol": row["candidate"]["ticker"],
                            "family": row["family"], "cutoff": row["simulated_as_of"], "change": "added" if row["decision"] == "take" else "removed",
                            "control_decision": b["decision"], "decision": row["decision"], "control_reason": b["reason"],
                            "reason": row["reason"], "outcome": row["outcome"]})
    all_rows = list(base.values())
    fixed = [r for r in all_rows if all(r["features"].get(k) is not None and finite(r["features"][k]) >= 0 for k in ("day_move", "trend"))]
    return {"format": VERSION, "kind": "comparison", "source_sha256": digest(data), "revealed_at": data["revealed_at"],
            "control": control, "expected_arms": expected_arms, "arms": summaries, "take_all": stats(all_rows), "fixed_filter": stats(fixed),
            "changes": changed, "limits": LIMITS + [
                "Owner-supplied already-revealed export; cross-arm consistency checked, outcome seals and frozen cohort not independently attested.",
                "Expected arms are supplied by the operator; this command cannot discover an omitted arm from the source study.",
                "Correlated sessions and overlapping signals; descriptive comparisons, no significance or trading-edge claim.",
                "Unresolved selected outcomes make complete totals unknown; paired differences use only changed selections and are unknown if any changed outcome is unresolved.",
            ]}
