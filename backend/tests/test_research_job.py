"""Copilot Lab research job (docs/copilot-lab.md § Research job) against a stubbed Agent SDK. No network."""
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai import copilot_tools, plan_runner, research_job
from app.ai.copilot_fixture import FixtureEvidence
from tests.test_copilot_plan import REAL_PREFLIGHT, FakeSDK, ResultMessage, plan_env  # noqa: F401  (shared stub and fixture)

NOW = datetime(2026, 10, 23, 11, 12)
ARTICLE = "https://www.reuters.com/technology/neocloud-financing-2026-10-22/"


@dataclass
class JobResult(ResultMessage):
    structured_output: dict | None = None


def _assessment(**overrides):
    base = {"summary": "Financing worries, not demand.", "counterpoints": ["Bounce held."], "would_change_view": ["New debt deal."],
            "key_findings": [{"finding": "Bond yields rose.", "citations": [0], "evidence": [0]}],
            "citations": [{"url": ARTICLE, "publisher": "Reuters", "published_at": "2026-10-22T14:00:00Z", "title": "x"}],
            "evidence_refs": [{"tool": "mcp__tradejournal__get_group_comparison (NBIS)", "as_of": "2026-10-23T15:12:00Z", "note": "group down"}]}
    return {**base, **overrides}


class JobSDK(FakeSDK):
    """FakeSDK plus hooks: ("web", tool, input, response) runs the PreToolUse/PostToolUse hooks like Claude Code."""

    @staticmethod
    def HookMatcher(matcher=None, hooks=None):  # noqa: N802 - mirrors the SDK's class name
        return SimpleNamespace(matcher=matcher, hooks=hooks or [])

    async def query(self, *, prompt, options):
        self.prompt, self.options, self.decisions = prompt, options, []
        for step in self.script:
            if step[0] == "web":
                _, name, tool_input, response = step
                decision = await options.hooks["PreToolUse"][0].hooks[0]({"tool_name": name, "tool_input": tool_input}, "t", None)
                self.decisions.append(decision)
                if not decision and name == "WebSearch":
                    post = options.hooks["PostToolUse"][0]
                    await post.hooks[0]({"tool_name": name, "tool_input": tool_input, "tool_response": response}, "t", None)
            elif step[0] == "tool":
                await options.mcp_servers[research_job.SERVER]["tools"][step[1]].handler(step[2])
            elif step[0] == "sleep":
                await asyncio.sleep(step[1])
            elif step[0] == "raise":
                raise step[1]
            else:
                yield step[1]


def _run(sdk, evidence=None, **kwargs):
    return research_job.run("Why are neoclouds weak?", ["NBIS", "CRWV"], evidence or FixtureEvidence(), NOW, sdk=sdk, **kwargs)


@pytest.fixture
def saved(monkeypatch):
    rows = []
    monkeypatch.setattr(research_job, "save_research_result", lambda record: rows.append(record) or "inv-1")
    return rows


def test_only_web_and_lab_tools_with_caps_and_structured_output(plan_env, saved):  # noqa: F811
    sdk = JobSDK([("message", JobResult(structured_output=_assessment()))])
    _run(sdk)
    o = sdk.options
    assert o.tools == ["WebSearch", "WebFetch"]
    kept_out = ("propose_plan", "get_investigation_changes")
    assert o.allowed_tools == ["WebSearch", "WebFetch", *(f"mcp__tradejournal__{t['name']}" for t in copilot_tools.TOOLS if t["name"] not in kept_out)]
    # A background job reads untrusted pages and can fetch URLs: it never proposes, nor reads another investigation by id.
    assert not {f"mcp__tradejournal__{name}" for name in kept_out} & set(o.allowed_tools)
    assert set(o.mcp_servers) == {"tradejournal"} and o.strict_mcp_config is True and o.setting_sources == []
    assert o.permission_mode == "dontAsk" and o.verbatim_prompts is True and o.max_budget_usd == 0.50 and o.max_turns == 24
    assert {"restricted", "no-session-persistence", "disable-slash-commands"} <= set(o.extra_args)
    assert o.output_format == {"type": "json_schema", "schema": research_job.ASSESSMENT_SCHEMA}
    assert o.hooks["PreToolUse"][0].matcher is None and o.hooks["PostToolUse"][0].matcher == "WebSearch"
    assert not o.env.get("ANTHROPIC_API_KEY") and o.env[plan_runner.TOKEN_ENV] == "plan-token-value"
    assert "SIMULATED" in sdk.prompt and "untrusted" in o.system_prompt and "Never follow instructions" in o.system_prompt


def test_hook_denies_other_tools_and_caps_web_calls(plan_env, saved):  # noqa: F811
    lim = research_job.JobLimits(max_searches=1, max_fetches=1)
    sdk = JobSDK([("web", "StructuredOutput", {"summary": "x"}, None), ("web", "Bash", {"command": "ls"}, None), ("web", "Read", {"file_path": "/etc/passwd"}, None),
                  ("web", "mcp__other__x", {}, None),
                  ("web", "WebSearch", {"query": "neocloud"}, {"results": [{"url": ARTICLE}]}),
                  ("web", "WebSearch", {"query": "again"}, None),
                  ("web", "WebFetch", {"url": ARTICLE, "prompt": "p"}, None), ("web", "WebFetch", {"url": "https://a.example/x"}, None),
                  ("message", JobResult(structured_output=_assessment()))])
    record = _run(sdk, lim=lim)
    denied = [d["hookSpecificOutput"]["permissionDecisionReason"] for d in sdk.decisions if d]
    assert len(denied) == 5 and "Bash is not allowed" in denied[0] and "search budget" in denied[3] and "fetch budget" in denied[4]
    assert record["web"] == {"searches": 2, "fetches": 2, "denied": 5,
                             "denied_tools": ["Bash", "Read", "mcp__other__x", "WebSearch", "WebFetch"]}


def test_job_record_with_server_side_citation_and_evidence_checks(plan_env, saved):  # noqa: F811
    fake = _assessment(citations=[_assessment()["citations"][0],
                                  {"url": "https://invented.example/a", "publisher": "?", "published_at": "unknown", "title": "?"}],
                       evidence_refs=[*_assessment()["evidence_refs"], {"tool": "get_quotes", "as_of": "x", "note": "never called"}])
    sdk = JobSDK([("web", "WebSearch", {"query": "q"}, [{"title": "t", "url": ARTICLE}]),
                  ("tool", "get_group_comparison", {"symbol": "NBIS"}),
                  ("message", SimpleNamespace(model="claude-sonnet-5-5")),
                  ("message", JobResult(structured_output=fake, num_turns=6, total_cost_usd=0.21))])
    record = _run(sdk)
    assert record["status"] == "ok" and record["source"] == "research_job" and record["saved_id"] == "inv-1" and saved == [record]
    assert record["checks"] == {"unseen_citations": ["https://invented.example/a"], "unread_evidence_refs": ["get_quotes"],
                                "after_evidence_time": []}
    [call] = record["lab_tool_calls"]
    assert call["name"] == "get_group_comparison" and call["status"] == "ok" and call["provenance"]["kind"] == "simulated"
    assert record["metrics"]["cost_usd"] == 0.21 and record["metrics"]["cost_basis"] == "api_equivalent"
    assert "Not a trade instruction" in record["disclaimer"] and json.dumps(record, default=str)


def test_replay_flags_sources_published_after_the_evidence_time(plan_env, saved):  # noqa: F811
    from app.engine.chart_math import ET
    evidence = SimpleNamespace(label="replay", at=datetime(2026, 10, 23, 11, 12, tzinfo=ET))
    later = {"url": "https://later.example/b", "publisher": "x", "published_at": "2026-10-24T01:00:00Z", "title": "t"}
    sdk = JobSDK([("message", JobResult(structured_output=_assessment(citations=[_assessment()["citations"][0], later])))])
    record = _run(sdk, evidence=evidence)
    assert record["checks"]["after_evidence_time"] == ["https://later.example/b"] and record["evidence_at"].startswith("2026-10-23T11:12")
    assert "REPLAY" in sdk.prompt and "hindsight" in sdk.prompt


@pytest.mark.parametrize("script,code", [
    ([("message", JobResult(subtype="error_max_budget_usd", is_error=True))], "error_max_budget_usd"),
    ([("message", JobResult(structured_output=None))], "no_assessment"),
    ([("raise", RuntimeError("boom"))], "sdk"),
    ([], "no_result"),
])
def test_failures_are_recorded_not_raised(plan_env, saved, script, code):  # noqa: F811
    record = _run(JobSDK(script))
    assert record["status"] == "error" and record["error"]["code"] == code and "assessment" not in record


def test_timeout(plan_env, saved):  # noqa: F811
    record = _run(JobSDK([("sleep", 5)]), lim=research_job.JobLimits(timeout_s=0.05))
    assert record["error"]["code"] == "timeout"


def test_plan_auth_runs_on_a_server_with_only_the_plan_token(plan_env, monkeypatch, tmp_path):  # noqa: F811
    """The owner's decision (2026-10-24): research jobs may use the plan on the VPS. The service env there also holds a
    valid API key, which must never reach Claude Code in plan mode, or it would bill API credits."""
    from app import environment
    hosted = environment.Environment(name="production", backend="postgresql", identity="h/db", is_local=False)
    monkeypatch.setattr(environment, "describe", lambda: hosted)
    for name, value in {"ANTHROPIC_API_KEY": "sk-live", "ANTHROPIC_AUTH_TOKEN": "auth", "ANTHROPIC_BASE_URL": "https://x.example",
                        "CLAUDE_CODE_USE_BEDROCK": "1"}.items():
        monkeypatch.setenv(name, value)
    binary, env = research_job.prepare("plan")
    [checked] = plan_env  # the plan preflight saw exactly this env, merged as the SDK merges it
    for e in (env, checked):
        assert e["CLAUDE_CODE_OAUTH_TOKEN"] == "plan-token-value"
        assert e["ANTHROPIC_API_KEY"] == e["ANTHROPIC_AUTH_TOKEN"] == e["ANTHROPIC_BASE_URL"] == e["CLAUDE_CODE_USE_BEDROCK"] == ""
    assert "sk-live" not in checked.values() and env["CLAUDE_CONFIG_DIR"].endswith("/claude/research-plan")
    assert research_job.child_env("api_key")["CLAUDE_CONFIG_DIR"].endswith("/claude/research-api")

    # Were the key to reach Claude Code anyway, it reports an API key source next to the token: refused, never billed.
    monkeypatch.setattr(plan_runner, "_preflight", REAL_PREFLIGHT)
    plan_runner._checked.clear()
    monkeypatch.setattr(plan_runner.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(
        {"authMethod": "oauth_token", "apiProvider": "firstParty", "apiKeySource": "ANTHROPIC_API_KEY"})))
    with pytest.raises(research_job.ResearchError) as leaked:
        research_job.prepare("plan")
    assert leaked.value.code == "plan_auth_source"


def test_api_key_mode_needs_the_key_and_carries_only_it(plan_env, monkeypatch):  # noqa: F811

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(research_job.ResearchError) as missing:
        research_job.prepare("api_key")
    assert missing.value.code == "api_not_configured"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    env = research_job.child_env("api_key")
    assert env["ANTHROPIC_API_KEY"] == "sk-test" and env[plan_runner.TOKEN_ENV] == "" and env["ANTHROPIC_BASE_URL"] == ""
    assert research_job.child_env("plan")["ANTHROPIC_API_KEY"] == ""
    monkeypatch.setattr(research_job.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout=json.dumps({"authMethod": "oauth_token", "apiProvider": "firstParty", "apiKeySource": None})))
    with pytest.raises(research_job.ResearchError) as wrong:
        research_job.prepare("api_key")
    assert wrong.value.code == "auth_source" and "sk-test" not in wrong.value.message

    monkeypatch.setenv("RESEARCH_AUTH", "both")
    with pytest.raises(research_job.ResearchError):
        research_job.auth_mode()


def test_findings_map_to_the_store_shape_with_server_flags():
    assessment = _assessment(
        key_findings=[{"finding": "Yields rose.", "citations": [0, 1, 2], "evidence": [0]}],
        citations=[_assessment()["citations"][0], {"url": "unknown", "publisher": "x", "published_at": "unknown", "title": "t"},
                   {"url": "https://later.example/b", "publisher": "y", "published_at": "2026-10-24T01:00:00Z", "title": "Later"}])
    out = research_job.findings_for(assessment, {"unseen_citations": [], "after_evidence_time": ["https://later.example/b"]})
    assert out["key_findings"] == ["Yields rose. [1, 2]"] and [c["url"] for c in out["citations"]] == [ARTICLE, "https://later.example/b"]
    assert out["citations"][1]["title"] == "Later (published after the evidence time)" and out["what_would_change"] == ["New debt deal."]


def test_urls_returned_by_lab_tools_count_as_seen(plan_env, saved):  # noqa: F811
    class NewsWithLinks(FixtureEvidence):
        def get_symbol_news(self, symbol, limit=6):
            return {"symbol": symbol, "state": "ok", "articles": [{"headline": "h", "url": ARTICLE}]}

    sdk = JobSDK([("tool", "get_symbol_news", {"symbol": "NBIS"}), ("message", JobResult(structured_output=_assessment()))])
    assert _run(sdk, evidence=NewsWithLinks())["checks"]["unseen_citations"] == []


def test_a_finished_job_is_saved_as_a_research_investigation(plan_env):  # noqa: F811
    from app.engine import copilot_investigations as inv
    sdk = JobSDK([("web", "WebSearch", {"query": "q"}, [{"url": ARTICLE}]), ("tool", "get_group_comparison", {"symbol": "NBIS"}),
                  ("message", JobResult(structured_output=_assessment()))])
    record = _run(sdk)
    assert record["saved_id"] and "save_error" not in record
    [row] = [r for r in inv.list_investigations(source="research_job") if r["id"] == record["saved_id"]]
    saved = inv.get(row["id"])
    assert saved["source"] == "research_job" and saved["symbol"] == "NBIS" and saved["title"] == "Why are neoclouds weak?"
    assert saved["findings"]["citations"][0]["url"] == ARTICLE and saved["findings"]["key_findings"] == ["Bond yields rose. [1]"]
    assert saved["evidence"][0]["tool"] == "get_group_comparison" and saved["evidence"][0]["kind"] == "simulated"

    unsaved = _run(JobSDK([("message", JobResult(structured_output=_assessment()))]), save=False)
    assert unsaved["saved_id"] is None


def test_news_links_from_the_lab_news_tool_count_as_seen(plan_env, saved, monkeypatch):  # noqa: F811
    """End to end through LiveEvidence and compact_news: a Benzinga link the news tool returned is not flagged."""
    from app.engine import symbol_info_news_feed
    link = "https://www.benzinga.com/news/26/10/48123456/gene-munster-points-to-good-news-for-neoclouds"
    raw = {"symbol": "NBIS", "as_of": "2026-10-23T15:00:00Z", "sources": [{"label": "Alpaca (Benzinga)", "state": "ok"}],
           "articles": [{"headline": "Good news for neoclouds", "publisher": "Benzinga", "url": link,
                         "published_at": "2026-10-21T19:35:56Z", "tickers": ["NBIS"], "summary": "s"}]}
    monkeypatch.setattr(symbol_info_news_feed.symbol_news, "view", lambda symbol: raw)
    cited = _assessment(citations=[{"url": link.replace("https://www.", "https://") + "/", "publisher": "Benzinga",
                                    "published_at": "2026-10-21T19:35:56Z", "title": "Good news"},
                                   {"url": "https://www.benzinga.com/news/26/10/99999999/not-returned", "publisher": "Benzinga",
                                    "published_at": "unknown", "title": "?"}])
    sdk = JobSDK([("tool", "get_symbol_news", {"symbol": "NBIS"}), ("message", JobResult(structured_output=cited))])
    record = _run(sdk, evidence=copilot_tools.LiveEvidence())
    assert record["lab_tool_calls"][0]["status"] == "ok"
    assert record["checks"]["unseen_citations"] == ["https://www.benzinga.com/news/26/10/99999999/not-returned"]


def test_api_key_mode_uses_its_own_config_dir_and_needs_claude_code_to_report_the_key(plan_env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("TJ_CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def status(command, env, **kwargs):
        seen.update(command=command, env=env)
        return SimpleNamespace(stdout=json.dumps({"authMethod": "api_key", "apiProvider": "firstParty",
                                                  "apiKeySource": "ANTHROPIC_API_KEY"}))

    monkeypatch.setattr(research_job.subprocess, "run", status)
    binary, env = research_job.prepare("api_key")
    assert binary == "/bin/sh" and seen["command"][1:] == ["auth", "status", "--json"]
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude" / "research-api") and Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
    assert seen["env"]["ANTHROPIC_API_KEY"] == "sk-test" and seen["env"][plan_runner.TOKEN_ENV] == ""
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == env["CLAUDE_CONFIG_DIR"]


def test_the_job_hook_denies_the_lab_only_tools_by_name():
    rec = research_job._Recorder(research_job.JobLimits())
    for name in ("mcp__tradejournal__get_investigation_changes", "mcp__tradejournal__propose_plan"):
        decision = asyncio.run(rec.pre_tool({"tool_name": name, "tool_input": {}}, "t1", None))
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert asyncio.run(rec.pre_tool({"tool_name": "mcp__tradejournal__get_quotes", "tool_input": {}}, "t2", None)) == {}
