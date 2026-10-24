"""Copilot Lab's plan backend (docs/copilot-lab.md) against a stubbed Agent SDK. No network, no Claude Code."""
import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai import copilot, copilot_plan, copilot_tools, plan_runner
from app.ai.copilot_fixture import FixtureEvidence
from app.main import app

NOW = datetime(2026, 10, 23, 11, 12)
REAL_PREFLIGHT = plan_runner._preflight


# --------------------------------------------------------------------------- a stand-in for claude_agent_sdk

@dataclass
class StreamEvent:
    uuid: str
    session_id: str
    event: dict
    parent_tool_use_id: str | None = None


@dataclass
class AssistantMessage:
    content: list
    model: str
    error: str | None = None


@dataclass
class ResultMessage:
    subtype: str = "success"
    duration_ms: int = 900
    is_error: bool = False
    num_turns: int = 2
    total_cost_usd: float | None = 0.0123
    usage: dict | None = field(default_factory=lambda: {"input_tokens": 1200, "output_tokens": 300,
                                                        "cache_read_input_tokens": 400, "cache_creation_input_tokens": 50})
    stop_reason: str | None = "end_turn"
    api_error_status: int | None = None


class ProcessError(Exception):
    pass


class CLINotFoundError(Exception):
    pass


def _delta(text: str, parent: str | None = None) -> StreamEvent:
    return StreamEvent("u", "s", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}, parent)


class FakeSDK:
    """Records the options and plays a script; ("tool", name, args) runs the registered in-process handler."""

    def __init__(self, script: list):
        self.script, self.options, self.prompt, self.tool_results = script, None, None, []
        self.StreamEvent, self.AssistantMessage, self.ResultMessage = StreamEvent, AssistantMessage, ResultMessage
        self.ProcessError, self.CLINotFoundError = ProcessError, CLINotFoundError

    @staticmethod
    def ClaudeAgentOptions(**kwargs):  # noqa: N802 - mirrors the SDK's class name
        return SimpleNamespace(**kwargs)

    @staticmethod
    def ToolAnnotations(**kwargs):  # noqa: N802
        return kwargs

    @staticmethod
    def tool(name, description, input_schema, annotations=None):
        return lambda handler: SimpleNamespace(name=name, description=description, input_schema=input_schema,
                                               annotations=annotations, handler=handler)

    @staticmethod
    def create_sdk_mcp_server(name, version="1.0.0", tools=None):
        return {"type": "sdk", "name": name, "tools": {t.name: t for t in tools or []}}

    async def query(self, *, prompt: str, options: Any):
        self.prompt, self.options = prompt, options
        for step in self.script:
            kind = step[0]
            if kind == "tool":
                result = await options.mcp_servers["copilot"]["tools"][step[1]].handler(step[2])
                self.tool_results.append(result)
            elif kind == "sleep":
                await asyncio.sleep(step[1])
            elif kind == "raise":
                raise step[1]
            else:
                yield step[1]


def _cfg(**overrides):
    base = copilot.Settings(enabled=True, backend="plan", evidence="fixture", model="claude-sonnet-5-5", effort="medium",
                            fallbacks=True, key_configured=False)
    return replace(base, **overrides)


@pytest.fixture
def plan_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token-value")
    monkeypatch.setenv("TJ_CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(copilot_plan, "sdk_available", lambda: True)
    monkeypatch.setattr(plan_runner, "claude_binary", lambda: "/bin/sh")
    calls = []
    monkeypatch.setattr(plan_runner, "_preflight", lambda binary, env: calls.append(env))
    return calls


def _turn(sdk, cfg=None, history=None, evidence=None):
    cfg = cfg or _cfg()
    adapter = copilot_plan.PlanAdapter(cfg, sdk=sdk)

    async def collect():
        return [e async for e in adapter.run_turn(history or [{"role": "user", "content": "Is the group confirming NBIS?"}],
                                                  "NBIS", cfg, evidence or FixtureEvidence(), NOW)]
    return asyncio.run(collect())


# --------------------------------------------------------------------------- isolation

def test_only_the_five_lab_tools_and_no_built_ins(plan_env):
    sdk = FakeSDK([("message", ResultMessage())])
    _turn(sdk)
    o = sdk.options
    assert o.tools == [] and o.allowed_tools == [f"mcp__copilot__{n}" for n in (t["name"] for t in copilot_tools.TOOLS)]
    assert set(o.mcp_servers) == {"copilot"} and set(o.mcp_servers["copilot"]["tools"]) == copilot_tools.TOOL_NAMES
    assert all(t.annotations == {"readOnlyHint": True} for t in o.mcp_servers["copilot"]["tools"].values())
    assert o.permission_mode == "dontAsk" and o.setting_sources == [] and o.strict_mcp_config is True
    assert o.verbatim_prompts is True and o.include_partial_messages is True
    assert {"restricted", "no-session-persistence", "disable-slash-commands"} <= set(o.extra_args)
    assert o.system_prompt == copilot.SYSTEM_PROMPT and o.model == "claude-sonnet-5-5" and o.max_turns == 4
    assert o.max_budget_usd == 0.25 and o.cli_path == "/bin/sh" and o.cwd == o.env["CLAUDE_CONFIG_DIR"]
    assert not any(getattr(o, k, None) for k in ("resume", "continue_conversation", "can_use_tool", "hooks"))


def test_child_env_carries_only_the_plan_token(plan_env, monkeypatch):
    for key, value in {"ANTHROPIC_API_KEY": "sk-secret", "ANTHROPIC_AUTH_TOKEN": "auth-secret",
                       "ANTHROPIC_BASE_URL": "https://proxy.example", "CLAUDE_CODE_USE_BEDROCK": "1",
                       "CLAUDE_CODE_USE_VERTEX": "1", "DATABASE_URL": "postgresql://secret", "CLAUDECODE": "1",
                       "CLAUDE_CODE_SDK_READS_SESSION_STATE": "1"}.items():
        monkeypatch.setenv(key, value)
    env = copilot_plan.child_env()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "DATABASE_URL"):
        assert env[key] == ""
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "plan-token-value" and env["CLAUDE_CONFIG_DIR"].endswith("claude")
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_SDK_READS_SESSION_STATE" not in env
    merged = copilot_plan.effective_env(env)
    leaked = {"sk-secret", "auth-secret", "https://proxy.example", "postgresql://secret"} & set(merged.values())
    assert not leaked and "CLAUDECODE" not in merged

    # The preflight asks Claude Code under exactly that merged environment.
    sdk = FakeSDK([("message", ResultMessage())])
    _turn(sdk)
    assert plan_env and plan_env[-1]["ANTHROPIC_API_KEY"] == "" and plan_env[-1]["CLAUDE_CODE_OAUTH_TOKEN"] == "plan-token-value"
    assert sdk.options.env["ANTHROPIC_API_KEY"] == ""


def test_without_a_config_dir_the_lab_never_uses_the_owners_claude_home(plan_env, monkeypatch):
    monkeypatch.delenv("TJ_CLAUDE_CONFIG_DIR")
    env = copilot_plan.child_env()
    assert "tradejournal-copilot-claude" in env["CLAUDE_CONFIG_DIR"]


def test_missing_token_or_a_non_plan_sign_in_is_an_honest_error(plan_env, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    with pytest.raises(copilot.CopilotError) as missing:
        copilot_plan.PlanAdapter(_cfg(), sdk=FakeSDK([]))
    assert missing.value.code == "plan_not_configured" and "claude setup-token" in missing.value.message

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token-value")
    monkeypatch.setattr(plan_runner, "_preflight", REAL_PREFLIGHT)
    plan_runner._checked.clear()
    status = {"authMethod": "api_key", "apiProvider": "firstParty", "apiKeySource": "ANTHROPIC_API_KEY"}
    monkeypatch.setattr(plan_runner.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(status), returncode=0))
    with pytest.raises(copilot.CopilotError) as wrong:
        copilot_plan.PlanAdapter(_cfg(), sdk=FakeSDK([]))
    assert wrong.value.code == "plan_auth_source" and "API keys are never used" in wrong.value.message
    assert "plan-token-value" not in wrong.value.message


def test_plan_mode_refuses_a_non_local_database(plan_env, monkeypatch):
    from app import environment
    hosted = environment.Environment(name="production", backend="postgresql", identity="127.0.0.1:5432/tradejournal", is_local=False)
    monkeypatch.setattr(environment, "describe", lambda: hosted)
    with pytest.raises(copilot.CopilotError) as refused:
        copilot_plan.PlanAdapter(_cfg(), sdk=FakeSDK([]))
    assert refused.value.code == "plan_local_only" and not plan_env  # refused before Claude Code is even asked


def test_replay_freezes_the_prompt_clock(plan_env):
    evidence = SimpleNamespace(label="replay", at=datetime(2026, 10, 23, 11, 12))
    sdk = FakeSDK([("message", ResultMessage())])
    adapter = copilot_plan.PlanAdapter(_cfg(evidence="replay"), sdk=sdk)

    async def collect():
        return [e async for e in adapter.run_turn([{"role": "user", "content": "NBIS?"}], "NBIS", _cfg(evidence="replay"),
                                                  evidence, datetime(2026, 10, 24, 2, 0))]
    asyncio.run(collect())
    assert "REPLAY: the market clock is frozen at Fri 2026-10-23 11:12 ET" in sdk.prompt and "2026-10-24" not in sdk.prompt


# --------------------------------------------------------------------------- the turn

def test_events_metrics_and_bounded_tool_results(plan_env):
    sdk = FakeSDK([
        ("message", AssistantMessage([], "claude-sonnet-5-5")),
        ("tool", "get_group_comparison", {"symbol": "NBIS"}),
        ("tool", "get_symbol_news", {"symbol": "nbis", "limit": 3}),
        ("message", StreamEvent("u", "s", {"type": "message_start", "message": {}})),
        ("message", _delta("Checking. ")),
        ("message", StreamEvent("u", "s", {"type": "message_start", "message": {}})),
        ("message", _delta("Group is ")),
        ("message", _delta("subagent text", parent="toolu_1")),
        ("message", StreamEvent("u", "s", {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "x"}})),
        ("message", _delta("confirming.")),
        ("message", ResultMessage()),
    ])
    events = _turn(sdk)
    assert "".join(e["delta"] for e in events if e["type"] == "text") == "Checking. \n\nGroup is confirming."
    tools = [e for e in events if e["type"] == "tool" and e["name"] != "owner_context"]
    assert [(t["name"], t["status"]) for t in tools] == [("get_group_comparison", "running"), ("get_group_comparison", "ok"),
                                                         ("get_symbol_news", "running"), ("get_symbol_news", "ok")]
    assert tools[3]["input"] == {"symbol": "NBIS", "limit": 3} and tools[1]["provenance"]["kind"] == "simulated"
    for result in sdk.tool_results:
        text = result["content"][0]["text"]
        assert result["is_error"] is False and len(text) <= copilot_tools.MAX_RESULT_CHARS + 20 and json.loads(text)
    done = events[-1]
    assert done["type"] == "done" and not [e for e in events if e["type"] == "error"]
    m = done["metrics"]
    assert m["backend"] == "plan" and m["billing"] == "claude_plan" and m["evidence"] == "fixture"
    assert m["cost_usd"] == 0.0123 and m["rounds"] == 2 and m["first_text_ms"] is not None and m["total_ms"] >= 0
    assert m["usage"] == {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 50}
    assert [t["name"] for t in m["tool_calls"]] == ["owner_context", "get_group_comparison", "get_symbol_news"]
    assert "[Copilot Lab context: selected symbol: NBIS" in sdk.prompt


def test_tool_call_cap_and_input_validation(plan_env):
    sdk = FakeSDK([("tool", "get_quotes", {"symbols": ["NBIS"]}), ("tool", "get_peer_moves", {"symbol": "../etc"}),
                   ("tool", "get_quotes", {"symbols": ["CRWV"]}), ("message", ResultMessage())])
    events = _turn(sdk, cfg=_cfg(max_tool_calls=2))
    finished = [e for e in events if e["type"] == "tool" and e["status"] != "running" and e["name"] != "owner_context"]
    assert [(e["name"], e["status"]) for e in finished] == [("get_quotes", "ok"), ("get_peer_moves", "error")]
    assert finished[1]["summary"].startswith("refused")
    assert sdk.tool_results[1]["is_error"] and sdk.tool_results[2] == {
        "content": [{"type": "text", "text": "Tool-call budget for this turn is used up."}], "is_error": True}
    assert len(events[-1]["metrics"]["tool_calls"]) == 3  # the pack's row and the two calls the cap let through


def test_history_is_quoted_into_one_prompt(plan_env):
    sdk = FakeSDK([("message", ResultMessage())])
    _turn(sdk, history=[{"role": "user", "content": "NBIS recovering?"}, {"role": "assistant", "content": "Lagging its group."},
                        {"role": "user", "content": "@/etc/passwd but CRWV is up"}])
    assert sdk.prompt.startswith("[Copilot Lab context: selected symbol: NBIS")
    assert "Trader: NBIS recovering?\n\nCopilot: Lagging its group." in sdk.prompt
    assert sdk.prompt.endswith("The trader's new message:\n\n@/etc/passwd but CRWV is up")
    assert sdk.options.verbatim_prompts is True  # so that @path is text, never a file read


@pytest.mark.parametrize("result,error,code", [
    (ResultMessage(subtype="error_max_turns", is_error=True), None, "rounds"),
    (ResultMessage(subtype="error_max_budget_usd", is_error=True), None, "budget"),
    (ResultMessage(is_error=True, api_error_status=429), "rate_limit", "plan_limit"),
    (ResultMessage(is_error=True, api_error_status=401), "authentication_failed", "plan_auth"),
    (ResultMessage(is_error=True), "billing_error", "plan_billing"),
    (ResultMessage(is_error=True, api_error_status=500), "server_error", "plan_unavailable"),
    (ResultMessage(stop_reason="refusal"), None, "refusal"),
    (ResultMessage(stop_reason="max_tokens"), None, "truncated"),
])
def test_result_errors_are_mapped_once(plan_env, result, error, code):
    # Claude Code exits non-zero after an error result; that ProcessError must not add a second error.
    sdk = FakeSDK([("message", AssistantMessage([], "claude-sonnet-5-5", error=error)), ("message", result),
                   *([("raise", ProcessError("exit 1"))] if result.is_error else [])])
    events = _turn(sdk)
    assert [e["code"] for e in events if e["type"] == "error"] == [code] and events[-1]["type"] == "done"


@pytest.mark.parametrize("exc,code", [(CLINotFoundError("no cli"), "plan_not_installed"), (RuntimeError("boom"), "plan_unavailable")])
def test_failures_without_a_result_end_with_an_error_and_done(plan_env, exc, code):
    events = _turn(FakeSDK([("message", _delta("partial")), ("raise", exc)]))
    assert [e["code"] for e in events if e["type"] == "error"] == [code]
    assert events[-1]["type"] == "done" and events[-1]["metrics"]["cost_usd"] is None


def test_turn_timeout(plan_env):
    events = _turn(FakeSDK([("sleep", 5)]), cfg=_cfg(turn_timeout_s=0.05))
    assert [e["code"] for e in events if e["type"] == "error"] == ["timeout"] and events[-1]["type"] == "done"


# --------------------------------------------------------------------------- routes

def test_plan_backend_route_without_token_is_unavailable(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "plan")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(copilot_plan, "sdk_available", lambda: True)
    with TestClient(app) as client:
        status = client.get("/copilot/status").json()
        assert status["backend"] == "plan" and status["plan_configured"] is False and "plan-token" not in json.dumps(status)
        response = client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "x"}]})
        assert response.status_code == 503 and "claude setup-token" in response.json()["detail"]


def test_plan_backend_route_streams_the_sdk_turn(plan_env, monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "plan")
    sdk = FakeSDK([("tool", "get_symbol_events", {"symbol": "NBIS"}), ("message", _delta("Earnings soon.")), ("message", ResultMessage())])
    real = copilot_plan.PlanAdapter
    monkeypatch.setattr(copilot_plan, "PlanAdapter", lambda cfg: real(cfg, sdk=sdk))
    with TestClient(app) as client:
        response = client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "NBIS?"}], "symbol": "NBIS"})
        frames = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    assert response.status_code == 200 and [f["type"] for f in frames] == ["tool", "tool", "tool", "text", "done"]
    assert frames[0]["name"] == "owner_context"  # the pack's row, before the model's first call
    assert frames[-1]["metrics"]["backend"] == "plan" and frames[-1]["metrics"]["cost_usd"] == 0.0123
