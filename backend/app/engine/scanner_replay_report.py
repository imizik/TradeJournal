"""Operator-only Markdown view of a sealed scanner selection run.

Isaac's optional trade snapshot is supplied privately at report time. It is
never loaded from the journal or added to Jo's frozen setup packets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import html
import json
import math
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

from app.engine import scanner_replay

ET = ZoneInfo("America/New_York")
REQUIRED_TRADE_KEYS = frozenset({"id", "ticker", "instrument_type", "option_type", "opened_at"})


def escape(value: object) -> str:
    """One-line Markdown table cell from untrusted model or snapshot text."""
    if value is None:
        return "—"
    text = html.escape(str(value), quote=True).replace("\\", "\\\\")
    text = text.replace("|", "\\|").replace("`", "&#96;")
    return " / ".join(part.strip() for part in text.replace("\r", "\n").split("\n") if part.strip()) or "—"


def _ny(moment: str) -> datetime:
    parsed = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Candidate timestamp must include timezone")
    return parsed.astimezone(ET)


def _trade_snapshot(rows: list[dict]) -> list[SimpleNamespace]:
    trades = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not REQUIRED_TRADE_KEYS <= row.keys():
            raise ValueError("Isaac snapshot row is missing required fields")
        identity = uuid.UUID(str(row["id"]))
        if identity in seen:
            raise ValueError("Isaac snapshot contains a duplicate trade")
        seen.add(identity)
        if (("active_account" in row and row["active_account"] is not True)
                or str(row.get("broker", "")).lower() == "webull"):
            continue
        opened = datetime.fromisoformat(str(row["opened_at"]).replace("Z", "+00:00"))
        if opened.tzinfo is not None:
            opened = opened.astimezone(ET).replace(tzinfo=None)
        if row["instrument_type"] != "option" or row["option_type"] not in ("call", "put"):
            continue
        if row.get("contracts") is not None and (not isinstance(row["contracts"], (int, float))
                                                  or not math.isfinite(row["contracts"]) or row["contracts"] < 0):
            raise ValueError("Invalid snapshot contracts")
        if row.get("realized_pnl") is not None and (not isinstance(row["realized_pnl"], (int, float))
                                                     or not math.isfinite(row["realized_pnl"])):
            raise ValueError("Invalid snapshot P&L")
        trades.append(SimpleNamespace(id=identity, ticker=str(row["ticker"]).upper(),
            instrument_type="option", option_type=row["option_type"], opened_at=opened,
            contracts=row.get("contracts"), status=row.get("status"), realized_pnl=row.get("realized_pnl")))
    return trades


def link_snapshot(setups: list[dict], rows: list[dict]) -> dict[str, list[SimpleNamespace]]:
    """Reuse S2's latest candidate within 15 minutes matching without a journal read."""
    from app.engine.setup_scanner import link_isaac_trades

    candidates = []
    for item in setups:
        candidate = item["candidate"]
        candidates.append(SimpleNamespace(id=uuid.UUID(candidate["candidate_id"]), symbol=candidate["symbol"],
            direction=candidate["direction"],
            detected_at=_ny(candidate["detected_at"]).astimezone(UTC).replace(tzinfo=None)))
    linked = link_isaac_trades(candidates, _trade_snapshot(rows))
    return {str(key): value for key, value in linked.items()}


def _number(value: object, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _score_table(card: dict) -> list[str]:
    lines = ["| Cohort | Selected | Resolved | Unresolved | Invalidated | Total R | Mean R | Win rate | Primary P&L / 100 shares | P&L / 100 shares at $0.02/share/side |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, key in (("Rules take all", "rules_take_all"), ("Jo at baseline entry", "jo_baseline_entry"),
                      ("Jo at delayed entry", "jo_delayed_entry"), ("Jo skips, counterfactual", "skipped_setups"),
                      ("Seeded random 50%", "seeded_random_50pct"), ("Skip all", "skip_all")):
        row = card[key]
        win = "—" if row.get("win_rate") is None else f"{100 * row['win_rate']:.1f}%"
        lines.append(f"| {name} | {row['selected']} | {row['resolved']} | {row.get('unresolved', 0)} | {row.get('invalidated', 0)} | {_number(row.get('total_r'))} | "
                     f"{_number(row.get('mean_r'))} | {win} | {_number(row.get('pnl_100'))} | {_number(row.get('pnl_100_cost_sensitivity'))} |")
    return lines


def _result_r(row: dict | None) -> str:
    if row is None:
        return "—"
    if row["resolved"]:
        return _number(row["r"])
    return escape(f"{row['status']}: {row['reason']}")


def render_markdown(db, run, *, isaac_trades: list[dict] | None = None) -> str:
    """Render only after scanner_replay.report has checked the exam seal."""
    result = scanner_replay.report(db, run)
    meta = scanner_replay.metadata(run)
    manifest = meta["manifest"]
    setups = result["setups"]
    links = link_snapshot(setups, isaac_trades) if isaac_trades is not None else None
    prompt_hash = hashlib.sha256(manifest["prompt_text"].encode()).hexdigest()
    policy = manifest["scoring_policy"]
    decisions = result["scorecard"]["decisions"]
    decision_text = "; ".join(f"{name.upper()} {decisions[name]}" for name in ("take", "skip", "insufficient_data"))
    lines = [f"# Scanner selection replay — {escape(run.day.isoformat())}", "",
             f"Run: `{run.id}` · phase: **{escape(meta['phase'])}** · status: **{escape(run.status)}**",
             f"Prompt version: {escape(manifest['prompt_version'])} · prompt SHA-256: `{prompt_hash}`",
             f"Manifest hash: `{run.policy_hash}` · scanner: {escape(manifest['scanner_version'])} "
             f"(`{manifest['params_hash']}`)", "",
             f"Split seed: {manifest['seed']} · exam sessions frozen: {manifest['exam_count']} · retrieved: {escape(meta['retrieved_at'])}", "",
             "Selection and fills are retrospective underlying-share proxies. No historical option contract, quote, delta, spread, "
             "premium fill, or option P&L was inferred. The with/without-contract cohort is omitted because every "
             "historical contract is unknown.",
             "Contract eligibility: " + escape(result["contract_eligibility"]), "",
             f"Primary costs: ${policy['cost_per_share_per_side']:.2f}/share/side; sensitivity: $0.02/share/side, "
             "using the same raw fills, entry/exit times and resolved cohort. Costs do not remove trades or alter the candidate stream. "
             "A dash in a legacy sensitivity column means that frozen snapshot predates this comparison.", "",
             "## Frozen scoring policy", "", "```json", json.dumps(policy, sort_keys=True, indent=2), "```", "",
             "## Session scorecard", ""]
    lines.extend(_score_table(result["scorecard"]))
    lines.extend(["", f"Sessions: {result['scorecard']['sessions']}; decisions: {decision_text}; "
                  f"uncommitted: {result['scorecard']['uncommitted']}.",
                  "Evidence warning: " + escape(result['scorecard']['evidence_warning']),
                  escape(result["scorecard"]["threshold_notice"]),
                  "Thirty decisions only clears a display warning; it does not establish a trading edge. "
                  "Setups within sessions are correlated, and scanner parameters were selected using March–September history.",
                  "", "## Cumulative practice and exam", ""])
    for phase in ("practice", "exam"):
        card = result["cumulative"][phase]
        lines.extend([f"### {phase.title()} ({card['sessions']} revealed sessions)", ""])
        lines.extend(_score_table(card))
        lines.append("")
    lines.extend(["## By setup", ""])
    if not result["by_setup"]:
        lines.extend(["No setups were selected in this session.", ""])
    for kind, card in sorted(result["by_setup"].items()):
        lines.extend([f"### {escape(kind)}", ""])
        lines.extend(_score_table(card))
        lines.append("")
    lines.extend(["## Setup ledger", "",
                  "| Time ET | Symbol | Setup | Jo choice | Jo reason | Wall seconds | Resumed setup | Rules R | Jo baseline R | Jo delayed R | Isaac link |",
                  "| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |"])
    for item in setups:
        c = item["candidate"]
        choice = item.get("choice") or {}
        take = choice.get("decision") == "take"
        link = "snapshot not supplied" if links is None else f"{len(links[c['candidate_id']])} matched option trade(s)"
        lines.append("| " + " | ".join((escape(_ny(c["detected_at"]).strftime("%H:%M")), escape(c["symbol"]),
            escape(c["setup"]), escape(choice.get("decision")), escape(choice.get("reason")),
            _number(choice.get("wall_seconds")), "yes" if choice.get("resumed") else "no" if "resumed" in choice else "—",
            _result_r(item["rules"]), _result_r(item["rules"] if take else None),
            _result_r(item["delayed"] if take else None), escape(link))) + " |")
    lines.extend(["", "## Isaac's actual option trades (separate, not ranked against share R)", ""])
    if links is None:
        lines.extend(["No optional Isaac snapshot was supplied.", ""])
    else:
        matched = [(item["candidate"]["symbol"], trade) for item in setups
                   for trade in links[item["candidate"]["candidate_id"]]]
        priced = [float(t.realized_pnl) for _, t in matched
                  if t.status in ("closed", "expired") and t.realized_pnl is not None]
        lines.extend([f"Matched option trades: {len(matched)}; closed/expired with P&L: {len(priced)}; "
                      f"actual option P&L: {_number(sum(priced)) if priced else '—'}.", "",
                      "| Opened ET | Symbol | Side | Status | Contracts | Realized option P&L |",
                      "| --- | --- | --- | --- | ---: | ---: |"])
        for symbol, trade in matched:
            pnl = trade.realized_pnl if trade.status in ("closed", "expired") else None
            lines.append("| " + " | ".join((escape(trade.opened_at.strftime("%Y-%m-%d %H:%M")),
                escape(symbol), escape(trade.option_type), escape(trade.status),
                _number(trade.contracts, 2), _number(pnl))) + " |")
        if not matched:
            lines.append("| — | — | — | — | — | — |")
        lines.append("")
    lines.extend(["## Coverage and interpretation", "",
                  "The experiment served setups sequentially with only completed pre-detection candles. "
                  "No explicit outcome feedback was served during a run. Later candles can reveal earlier price paths, "
                  "and Jo's existing memory can contain later information; sessions are not independent blind questions. "
                  "Outside news and model memory cannot be verified from these receipts; review the labels below. "
                  "No trade or live order was placed by this report.", "",
                  "Wall seconds measure first packet service to commit, including interruption time. "
                  "Resumed setup is marked only by an explicit resume=true read before that immutable choice; "
                  "a repeated normal read is not labelled a resume.", "",
                  "Labels: " + ", ".join(escape(label) for label in result["labels"]), "",
                  "Differences from live S1:", ""])
    lines.extend(f"- {escape(note)}" for note in meta["differences"])
    lines.extend(["", "Daily ATR coverage:", "",
                  "| Symbol | Prior daily sessions | ATR14 | Source |", "| --- | ---: | ---: | --- |"])
    for symbol, row in sorted(meta.get("daily_atr", {}).items()):
        lines.append(f"| {escape(symbol)} | {row['prior_sessions']} | {_number(row['atr14'], 4)} | {escape(row['source'])} |")
    if "daily_atr" not in meta:
        lines.append("| — | — | — | Legacy snapshot: ATR coverage not recorded |")
    coverage = meta.get("coverage")
    lines.extend(["", "Missing-minute impact:", ""])
    if coverage is None:
        lines.append("Legacy snapshot: symbol-time loss was not recorded.")
    else:
        lines.extend(["| Symbol | Expected minutes | Supplied minutes | Missing minutes | Scan minutes lost | Blocked scan slots | Setups emitted |",
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for symbol, row in sorted(coverage["symbols"].items()):
            lines.append("| " + " | ".join((escape(symbol), str(row["expected_minutes"]), str(row["provided_minutes"]),
                str(row["missing_minutes"]), str(row["scan_minutes_lost"]), str(row["blocked_scan_slots"]),
                str(row["setups_emitted"]))) + " |")
        totals = coverage["totals"]
        completeness = "complete" if totals["missing_minutes"] == 0 else "incomplete"
        lines.extend(["", f"Session data: {completeness}. Session totals: {totals['missing_minutes']} missing symbol-minutes; "
                      f"{totals['scan_minutes_lost']} scan symbol-minutes lost; {totals['blocked_scan_slots']} blocked scan slots; "
                      f"{totals['setups_emitted']} setups emitted.",
                      "Lost setup count is unknowable when bars are absent. Blocked scan slots are opportunities to evaluate "
                      "a signal, not claimed missing setups; a quiet complete session has zero lost symbol-time."])
    lines.extend(["", "Coverage gaps:", ""])
    if meta["coverage_gaps"]:
        lines.extend(f"- {escape(gap.get('symbol'))}: {escape(gap.get('reason'))}"
                     + (f" at {escape(gap['at'])}" if "at" in gap else "") for gap in meta["coverage_gaps"])
    else:
        lines.append("- None reported by the frozen generator.")
    lines.extend(["", "The scanner's original setup and stop/target rules were frozen by version and parameter hash. "
                  "Alpaca SIP raw stock bars, simulated timing and missing historical options limit comparisons with "
                  "live Tradier paper trades and Isaac's option results.", ""])
    return "\n".join(lines)
