"""Every Jo-facing Check tool's exported input schema accepts ordinary arguments.

On October 20 the ChatGPT connector full-matched an exported nonblank `\\S`
pattern and refused a scheduled brief before it reached Check (#354). These
payloads are validated against the tools/list schemas the way a strict client
would: JSON Schema 2020-12 with formats checked and patterns full-matched.
Generated tokens and disposable directories only.
"""
import re
import uuid

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError, validators
import pytest

from tests.test_cloud_mcp_check import harness, signing_key, rpc  # noqa: F401

SCOPES = "check:read check:run check:note shadow:decide market:read market:submit jo:read jo:submit"


def fullmatch_pattern(validator, pattern, instance, schema):
    if validator.is_type(instance, "string") and not re.fullmatch(pattern, instance):
        yield ValidationError(f"{instance!r} does not fully match {pattern!r}")


Strict = validators.extend(Draft202012Validator, {"pattern": fullmatch_pattern})


def errors(schema, arguments):
    validator = Strict(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [e.message for e in validator.iter_errors(arguments)]


def ids(prefix=""):
    return prefix + str(uuid.uuid4())


# Ordinary prose Jo writes: typographic quotes, a dash, a newline, edge spaces.
PROSE = "Wait for APLD’s reclaim of $14.20 — two 1m closes above it.\nSkip if it loses $13.85. "
NOTE = "Jo"


def brief_item(**changes):
    return {"symbol": "NBIS", "what_matters": PROSE, "why_personal": "You hold 12 shares.",
        "what_changed": "Gap up 4% pre-market.", "contrary_evidence": "Volume is thin.",
        "watch_out": "Recheck at 10:00 ET.", "evidence_ids": ["position-1", "quote-2"], **changes}


def read(view="down", probability=.62, **changes):
    return {"operation_id": "mw-scheduled-v1:2026-10-20:09:50", "input_id": ids("mwi_"), "view": view,
        "main": {"text": PROSE, "supporting_refs": ["/indices/SPY"], "contradicting_refs": []},
        "alternative": {"text": "Opening-range bounce.", "supporting_refs": [], "contradicting_refs": ["/indices/QQQ"]},
        "invalidation": {"text": "SPY reclaims VWAP.", "evidence_refs": ["/indices/SPY/vwap"]},
        "change_summary": "First read today.", "forecasts": [{"horizon": h, "predicate": "spy_return_lt_zero",
            "probability": probability, **({"abstention_reason": "Stale QQQ bars."} if probability is None else {})}
            for h in ("30m", "60m", "close")], "message_intent": "none", "prompt_version": "mw-scheduled-v1",
        **changes}


PAYLOADS = {
    "jo_morning_context": [{}],
    "jo_context": [{"packet_id": ids()}],
    "jo_memory_propose": [
        {"packet_id": ids(), "memory": {"operation_id": "jo-memory:2026-10-20:apld", "kind": "thesis",
            "original_text": "I’d rather wait for confirmation on APLD.", "source": "jo_proposal"}},
        {"packet_id": ids(), "memory": {"operation_id": "jo-memory.1", "memory_id": None, "base_revision": 0,
            "kind": "preference", "symbol": "BRK.B", "original_text": " Smaller size on Fridays.\n",
            "interpretation": NOTE, "source": "jo_proposal", "source_reference": "chat 2026-10-20 10:05 ET",
            "status": "proposed", "owner_confirmed": False}},
    ],
    "jo_briefing_submit": [
        {"briefing": {"operation_id": "morning-roth-2026-10-20", "packet_id": ids(), "author": NOTE,
            "prompt_version": "jo-morning-v2", "summary": "Review APLD’s calls.", "summary_evidence_ids": [],
            "items": [], "limitations": ["No comparison is available."]}},
        {"briefing": {"operation_id": "morning-roth-2026-10-20:fix_1", "packet_id": ids(), "author": "\nJo\n",
            "prompt_version": "jo-morning-v2", "model_id": "gpt-5", "summary": PROSE,
            "summary_evidence_ids": ["quote-2"], "items": [brief_item(), brief_item(symbol=None)],
            "limitations": ["Option marks missing.", "Prices are 15 minutes stale."], "supersedes_id": ids()}},
    ],
    "jo_receipt": [{"operation_id": "morning-roth-2026-10-20"}, {"operation_id": "jo-memory:2026-10-20:apld"}],
    "pre_trade_check": [
        {"ticker": "spy", "side": "long", "instrument": "stock", "horizon": "intraday"},
        {"ticker": "BRK.B", "side": "short", "instrument": "stock", "horizon": "swing", "entry": 471.25,
            "stop": 476.5, "free_text": PROSE, "operation_id": ids()},
        {"ticker": "NBIS", "side": "long", "instrument": "option", "horizon": "intraday", "option_type": "call",
            "expiration": "2026-10-24", "strike": 112.5, "entry": 2.35, "stop": 1.4, "free_text": None,
            "operation_id": None},
    ],
    "attach_model_verdict": [{"check_id": ids("chk_"), "verdict": v, "summary": PROSE}
        for v in ("go", "wait", "pass", "insufficient_data")],
    "review_checks": [{}, {"day": "2026-10-20"}, {"day": None}],
    "grade_checks": [{}, {"days": 30}, {"days": None}],
    "position_check": [{}, {"ticker": "nbis"}, {"ticker": "APLD", "stop": 13.85}],
    "preopen_watchlist": [{}, {"tickers": ["SPY", "qqq", "BRK.B"]}],
    "get_notes": [{}, {"ticker": "APLD"}],
    "candles": [{"symbol": "spy", "interval": "1m"}, {"symbol": "NBIS", "interval": "5m", "bars": 120}],
    "shadow_setup": [{"candidate_id": ids()}],
    "shadow_decide": [{"candidate_id": ids(), "decision": d, "reason": PROSE} for d in ("take", "skip")],
    "stock_alert": [{"alert_id": ids("sta_")}],
    "stock_alert_submit": [
        {"alert_id": ids("sta_"), "stance": "watch", "summary": PROSE, "invalidation": "Close below $13.85.",
            "notify": True},
        {"alert_id": ids("sta_"), "stance": "no_view", "summary": "Too few bars.", "invalidation": "n/a",
            "notify": False},
    ],
    "market_watch_snapshot": [{}],
    "market_watch_submit": [read(), read(view="no_view", probability=None, previous_read_id=ids("mwr_")),
        read(message_intent="correction", correction_of_read_id=ids("mwr_"), model_id=None)],
    "conditional_plan_create": [
        {"operation_id": "jo-plan:2026-10-20:nbis", "source_kind": "check", "source_id": ids("chk_"),
            "direction": "long", "trigger_price": 112.5, "invalidation_price": 108, "confirm_bars": 2,
            "expires_at": "2026-10-20T15:30:00-04:00", "rationale": PROSE},
        {"operation_id": ids(), "source_kind": "stock_alert", "source_id": ids("sta_"), "direction": "short",
            "trigger_price": 13.85, "invalidation_price": 14.2, "confirm_bars": 1,
            "expires_at": "2026-10-20T19:30:00Z", "rationale": "Loses the morning low."},
    ],
    "conditional_plan_status": [{"plan_id": ids("cpl_")}],
    "conditional_plan_list": [{}],
    "conditional_plan_cancel": [{"plan_id": ids("cpl_")}],
}


@pytest.fixture
def catalog(harness, tmp_path):  # noqa: F811
    snapshots, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    # Every optional Jo tool group the Check connector can register.
    harness.configure(jo_briefing_enabled=True, conditional_plan_enabled=True,
        market_watch_snapshots_dir=str(snapshots), market_watch_outbox_dir=str(outbox))
    with TestClient(harness.server().streamable_http_app()) as client:
        tools = rpc(client, "", {}, harness.token(scope=SCOPES), "tools/list").json()["result"]["tools"]
    return {tool["name"]: tool["inputSchema"] for tool in tools}


def test_every_registered_tool_has_ordinary_payloads(catalog):
    # A new Check tool must add realistic arguments here before it ships.
    assert set(catalog) == set(PAYLOADS)


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_exported_schema_accepts_ordinary_arguments_under_strict_validation(catalog, name):
    Draft202012Validator.check_schema(catalog[name])
    for arguments in PAYLOADS[name]:
        assert errors(catalog[name], arguments) == [], (name, arguments)


def test_strict_validator_reproduces_the_october_20_refusal(catalog):
    schema = catalog["jo_briefing_submit"]
    body = PAYLOADS["jo_briefing_submit"][0]
    author = schema["$defs"]["BriefingSave"]["properties"]["author"]
    old = {**schema, "$defs": {**schema["$defs"], "BriefingSave": {**schema["$defs"]["BriefingSave"],
        "properties": {**schema["$defs"]["BriefingSave"]["properties"], "author": {**author, "pattern": r"\S"}}}}}
    assert errors(old, body) and not errors(schema, body)
    # Constraints still refuse genuinely invalid arguments.
    for name, arguments in (("jo_briefing_submit", {"briefing": {**body["briefing"], "author": " "}}),
            ("pre_trade_check", {**PAYLOADS["pre_trade_check"][0], "ticker": "SPY 1"}),
            ("jo_context", {"packet_id": "not-a-uuid"}),
            ("attach_model_verdict", {**PAYLOADS["attach_model_verdict"][0], "extra": 1})):
        assert errors(catalog[name], arguments), name


@pytest.mark.parametrize("enabled", [False, True])
def test_instructions_name_only_a_visible_monitoring_mechanism(harness, tmp_path, enabled):  # noqa: F811
    snapshots, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    harness.configure(conditional_plan_enabled=enabled,
        market_watch_snapshots_dir=str(snapshots), market_watch_outbox_dir=str(outbox))
    text = harness.server().instructions
    assert "pre_trade_check and attach_model_verdict before you answer" in text
    assert "ChatGPT tasks or reminders you create are invisible to TradeJournal" in text
    assert ("I can't monitor this" in text) is not enabled
    assert ("conditional plan that conditional_plan_status reports as monitoring" in text) is enabled
