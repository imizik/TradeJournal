"""Copilot Lab: bounded read-only tool loop, stubbed Claude client, owner-only routes. No network."""
import asyncio
import json
import logging
import uuid
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import copilot, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.main import app
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

NOW = datetime(2026, 10, 23, 11, 12)


def _cfg(**overrides):
    base = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="claude-sonnet-5-5", effort="medium",
                            fallbacks=True, key_configured=False)
    return replace(base, **overrides)


def _turn(history, adapter, evidence=None, cfg=None, symbol="NBIS"):
    async def collect():
        return [e async for e in copilot.run_turn(history, symbol, cfg or _cfg(), adapter, evidence or FixtureEvidence(), NOW)]
    return asyncio.run(collect())


def _text(events):
    return "".join(e["delta"] for e in events if e["type"] == "text")


# --------------------------------------------------------------------------- tool allowlist

@pytest.mark.parametrize("name,args", [
    ("run_shell", {"cmd": "ls"}),
    ("get_quotes", {"symbols": []}),
    ("get_quotes", {"symbols": [f"T{i}" for i in range(9)]}),
    ("get_symbol_news", {"symbol": "NBIS", "limit": True}),
    ("get_symbol_news", {"symbol": "NBIS", "limit": 50}),
    ("get_peer_moves", {"symbol": "../etc"}),
    ("get_peer_moves", {"symbol": "NBIS", "account": "x"}),
    ("get_group_comparison", "NBIS"),
])
def test_tool_inputs_outside_the_allowlist_are_refused(name, args):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate(name, args)


def test_tool_inputs_are_normalized():
    assert copilot_tools.validate("get_quotes", {"symbols": ["nbis", "NBIS", "crwv"]}) == {"symbols": ["NBIS", "CRWV"]}
    assert copilot_tools.validate("get_symbol_news", {"symbol": "nbis"}) == {"symbol": "NBIS", "limit": 6}
    assert all(t["input_schema"]["additionalProperties"] is False for t in copilot_tools.TOOLS)


def test_large_results_are_bounded():
    assert len(copilot_tools.bounded({"x": "y" * 50_000})) < copilot_tools.MAX_RESULT_CHARS + 50


# --------------------------------------------------------------------------- the representative conversation

def test_representative_conversation_with_simulated_model_and_evidence():
    first = _turn([{"role": "user", "content": "NBIS looks like it might recover. Is the whole neocloud group confirming?"}],
                  copilot.FakeAdapter(0))
    assert [e["text"] for e in first if e["type"] == "progress"] == ["Checking group comparison, symbol news, symbol events for NBIS."]
    tools = [e for e in first if e["type"] == "tool" and e["status"] != "running" and e["name"] != "owner_context"]
    assert {t["name"] for t in tools} == {"get_group_comparison", "get_symbol_news", "get_symbol_events"}
    assert all(t["provenance"]["kind"] == "simulated" and t["provenance"]["as_of"] for t in tools)
    answer = _text(first)
    assert "Simulated model" in answer and "Neoclouds and AI hosting" in answer and "Counterargument" in answer
    assert first[-1]["type"] == "done" and first[-1]["metrics"]["cost_usd"] == 0.0

    history = [{"role": "user", "content": "NBIS looks like it might recover."}, {"role": "assistant", "content": answer},
               {"role": "user", "content": "But CRWV and APLD are recovering too. You're discounting the group strength."}]
    second = _turn(history, copilot.FakeAdapter(0))
    assert {e["name"] for e in second if e["type"] == "tool"} == {"owner_context", "get_group_comparison", "get_peer_moves"}
    assert "CRWV +1.92%" in _text(second) and "lagging" in _text(second)

    history += [{"role": "assistant", "content": _text(second)}, {"role": "user", "content": "Okay, let's make a plan."}]
    third = _turn(history, copilot.FakeAdapter(0))
    # A plan proposes cards and activates nothing: only a price read and propose_plan run.
    assert {e["name"] for e in third if e["type"] == "tool"} == {"owner_context", "get_quotes", "propose_plan"}
    proposals = [e for e in third if e["type"] == "proposal"]
    assert [p["kind"] for p in proposals] == ["watch", "revisit"]
    assert proposals[0] | {"id": None} == {"type": "proposal", "id": None, "kind": "watch", "symbol": "NBIS", "condition": "crosses",
                                           "price": 92.46, "interval": None, "label": "NBIS 2% below the last price",
                                           "why": "A break here would mean the bounce failed.", "last": 94.35,
                                           "as_of": "2026-10-23T15:12:00Z"}
    assert proposals[1]["question"] == "Is NBIS still lagging its group?" and proposals[1]["horizon_days"] == 1
    assert "Nothing is saved or active until you confirm a card below." in _text(third)


def test_context_reaches_only_the_latest_user_message():
    seen = {}

    class Capture(copilot.FakeAdapter):
        async def stream_round(self, system, messages, tools, allow_tools=True):
            seen.setdefault("messages", messages[:])
            async for item in super().stream_round(system, messages, tools, allow_tools):
                yield item

    _turn([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "plan it"}], Capture(0))
    assert seen["messages"][0]["content"] == "a"
    assert seen["messages"][-1]["content"].startswith("[Copilot Lab context: selected symbol: NBIS; server time 2026-10-23 11:12 ET; SIMULATED")


def test_fixture_evidence_is_marked_simulated_to_the_model():
    seen = {}

    class Capture(copilot.FakeAdapter):
        async def stream_round(self, system, messages, tools, allow_tools=True):
            seen.setdefault("system", system)
            seen["messages"] = messages[:]
            async for item in super().stream_round(system, messages, tools, allow_tools):
                yield item

    _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], Capture(0))
    assert "SIMULATED" in seen["system"] and "not real market data" in seen["system"]
    assert "SIMULATED market data — not real prices" in seen["messages"][0]["content"]
    results = [b for m in seen["messages"] if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]
    assert results and all(b["content"].startswith('{"simulated":true,"note":"SIMULATED') for b in results)
    assert all(json.loads(b["content"])["simulated"] is True for b in results)


def test_live_context_and_results_carry_no_simulated_marker():
    class Live(FixtureEvidence):
        label = "live"

    line = copilot.context_line("NBIS", NOW)
    assert "SIMULATED" not in line and line.startswith("[Copilot Lab context: selected symbol: NBIS; server time")
    result, _ = asyncio.run(copilot._run_tool(Live(), {"id": "u1", "name": "get_quotes", "input": {"symbols": ["NBIS"]}}, _cfg()))
    assert "simulated" not in json.loads(result["content"])


# --------------------------------------------------------------------------- limits and failures

class Greedy:
    """A model that asks for three tools every round and never answers on its own."""
    model = "greedy"

    def __init__(self):
        self.allowed = []

    async def stream_round(self, system, messages, tools, allow_tools=True):
        self.allowed.append(allow_tools)
        if not allow_tools:
            yield "text", "done"
            yield "final", copilot.Round([{"type": "text", "text": "done"}], "end_turn", copilot._zero_usage())
            return
        n = len(messages)
        content = [{"type": "tool_use", "id": f"t{n}_{i}", "name": "get_quotes", "input": {"symbols": ["SPY"]}} for i in range(3)]
        yield "final", copilot.Round(content, "tool_use", copilot._zero_usage())


def test_tool_calls_and_rounds_are_capped():
    greedy = Greedy()
    events = _turn([{"role": "user", "content": "go"}], greedy, cfg=_cfg(max_tool_calls=5, max_rounds=4))
    ran = [e for e in events if e["type"] == "tool" and e["status"] == "ok" and e["name"] != "owner_context"]
    assert len(ran) == 5
    assert greedy.allowed[-1] is False and len(greedy.allowed) <= 4
    assert events[-1]["metrics"]["rounds"] == len(greedy.allowed)


def test_provider_failure_and_timeout_become_honest_missing_evidence():
    class Broken(FixtureEvidence):
        def get_quotes(self, symbols):
            raise RuntimeError("provider exploded with secret detail")

        def get_peer_moves(self, symbol):
            import time
            time.sleep(0.5)
            return {}

    class Asks:
        model = "asks"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            if isinstance(messages[-1]["content"], list):
                yield "final", copilot.Round([{"type": "text", "text": json.dumps(messages[-1]["content"])}], "end_turn", copilot._zero_usage())
                return
            yield "final", copilot.Round([{"type": "tool_use", "id": "a", "name": "get_quotes", "input": {"symbols": ["SPY"]}},
                                          {"type": "tool_use", "id": "b", "name": "get_peer_moves", "input": {"symbol": "NBIS"}}],
                                         "tool_use", copilot._zero_usage())

    events = _turn([{"role": "user", "content": "x"}], Asks(), Broken(), cfg=_cfg(tool_timeout_s=0.05))
    done = {e["id"]: e for e in events if e["type"] == "tool" and e["status"] != "running"}
    assert done["a"]["summary"] == "unavailable" and done["b"]["summary"] == "timed out"
    assert "secret detail" not in json.dumps(events)
    assert events[-1]["type"] == "done"


def test_refusal_and_truncated_tool_input_never_run_tools():
    class Says:
        def __init__(self, stop):
            self.stop, self.model = stop, "s"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            yield "final", copilot.Round([{"type": "tool_use", "id": "x", "name": "get_quotes", "input": {"symbols": ["SPY"]}}], self.stop, copilot._zero_usage())

    for stop, code in (("refusal", "refusal"), ("max_tokens", "truncated")):
        events = _turn([{"role": "user", "content": "x"}], Says(stop))
        assert [e["code"] for e in events if e["type"] == "error"] == [code]
        assert not [e for e in events if e["type"] == "tool" and e["name"] != "owner_context"]


def test_unexpected_failures_still_end_with_an_error_and_done():
    class Crashes:
        model = "crash"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            yield "text", "partial "
            raise KeyError("internal detail")

    events = _turn([{"role": "user", "content": "x"}], Crashes())
    assert [e["type"] for e in events][-2:] == ["error", "done"] and "internal detail" not in json.dumps(events)


# --------------------------------------------------------------------------- the real adapter, stubbed

class _Block:
    def __init__(self, data):
        self.data = data

    def model_dump(self, **_):
        return self.data


class _Stream:
    def __init__(self, rounds, calls):
        self.rounds, self.calls = rounds, calls

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        texts, content, stop = self.rounds.pop(0)
        outer = self

        class Manager:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def __aiter__(self):
                async def gen():
                    for t in texts:
                        yield SimpleNamespace(type="text", text=t) if isinstance(t, str) else t
                return gen()

            async def get_final_message(self):
                usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=2000, cache_creation_input_tokens=0)
                return SimpleNamespace(content=[_Block(c) for c in content], stop_reason=stop, usage=usage, model=outer.model)
        return Manager()

    model = "claude-sonnet-5-5"


def _client(rounds, calls):
    return SimpleNamespace(beta=SimpleNamespace(messages=_Stream(rounds, calls)))


def test_anthropic_adapter_streams_bounded_tools_and_reports_cost(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    calls = []
    note = [SimpleNamespace(type="thinking", thinking="", snapshot=""),  # an empty reasoning block shows nothing
            SimpleNamespace(type="thinking", thinking="Checking ", snapshot="Checking "),
            SimpleNamespace(type="thinking", thinking="the group.", snapshot="Checking the group.")]
    rounds = [(note, [{"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "tool_use", "id": "u1", "name": "get_group_comparison", "input": {"symbol": "NBIS"}}], "tool_use"),
              (["NBIS ", "lags ", "CRWV."], [{"type": "text", "text": "NBIS lags CRWV."}], "end_turn")]
    cfg = _cfg(backend="anthropic", key_configured=True)
    adapter = copilot.AnthropicAdapter(cfg, client=_client(rounds, calls))
    events = _turn([{"role": "user", "content": "Is the group confirming?"}], adapter, cfg=cfg)
    assert _text(events) == "NBIS lags CRWV."
    first = calls[0]
    assert first["model"] == "claude-sonnet-5-5" and first["thinking"] == {"type": "adaptive", "display": "updates"}
    assert first["output_config"] == {"effort": "medium"} and "tool_choice" not in first
    assert first["betas"] == [copilot.PROGRESS_BETA, "server-side-fallback-2026-07-01"]
    assert first["extra_body"] == {"fallbacks": "default"}
    assert [e["text"] for e in events if e["type"] == "progress"] == ["Checking ", "Checking the group."]
    order = [e["type"] for e in events if e.get("name") != "owner_context"]  # the pack's row precedes the model
    assert order.index("progress") < order.index("tool") < order.index("text")
    assert {t["name"] for t in first["tools"]} == copilot_tools.TOOL_NAMES and all(t["eager_input_streaming"] for t in first["tools"])
    # The thinking block and tool_use go back unchanged within the turn; the tool result follows.
    second = calls[1]["messages"]  # the turn's live list: user, assistant(thinking, tool_use), tool results, ...
    assert second[1]["content"][0]["signature"] == "sig" and second[2]["content"][0]["tool_use_id"] == "u1"
    assert "sk-test" not in json.dumps(calls, default=str) + json.dumps(events)
    metrics = events[-1]["metrics"]
    assert metrics["usage"] == {"input_tokens": 2000, "output_tokens": 1000, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}
    assert metrics["cost_usd"] == pytest.approx((2000 * 2 + 1000 * 10 + 4000 * 0.2) / 1e6)
    assert metrics["first_text_ms"] is not None and [t["name"] for t in metrics["tool_calls"]] == ["owner_context", "get_group_comparison"]
    # The pack's row is the first thing the trader sees, then the progress note, then text: equal only when both land
    # in the same millisecond (as they did on #470's CI run), so order, not equality.
    assert metrics["first_feedback_ms"] <= metrics["first_progress_ms"] <= metrics["first_text_ms"]
    assert 0 <= metrics["max_silence_ms"] <= metrics["total_ms"]


def test_without_fallbacks_only_the_progress_beta_is_sent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    adapter = copilot.AnthropicAdapter(_cfg(backend="anthropic", key_configured=True, fallbacks=False), client=object())
    kwargs = adapter.request("s", [], [], True)
    assert kwargs["betas"] == [copilot.PROGRESS_BETA] and "extra_body" not in kwargs


def test_silence_is_measured_between_visible_events():
    class Slow:
        model = "slow"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            if isinstance(messages[-1]["content"], str):
                yield "progress", "Looking."
                yield "final", copilot.Round([{"type": "tool_use", "id": "q", "name": "get_quotes", "input": {"symbols": ["SPY"]}}],
                                             "tool_use", copilot._zero_usage())
                return
            await asyncio.sleep(0.2)  # hidden reasoning after the tool result: nothing visible
            yield "text", "Answer."
            yield "final", copilot.Round([{"type": "text", "text": "Answer."}], "end_turn", copilot._zero_usage())

    metrics = _turn([{"role": "user", "content": "x"}], Slow())[-1]["metrics"]
    # The turn's opening pack event is the first visible moment; the progress note follows within the same few
    # milliseconds, so the two stamps may differ by rounding on a loaded runner.
    assert metrics["first_feedback_ms"] <= metrics["first_progress_ms"] < 100
    assert metrics["first_text_ms"] >= 200 and metrics["max_silence_ms"] >= 190


def test_turn_stops_at_its_spend_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    calls = []
    asks = [([], [{"type": "tool_use", "id": f"u{i}", "name": "get_quotes", "input": {"symbols": ["SPY"]}}], "tool_use") for i in range(4)]
    cfg = _cfg(backend="anthropic", key_configured=True, turn_budget_usd=0.01)  # each stub round costs ~$0.0074
    events = _turn([{"role": "user", "content": "x"}], copilot.AnthropicAdapter(cfg, client=_client(asks, calls)), cfg=cfg)
    assert len(calls) == 2 and [e["code"] for e in events if e["type"] == "error"] == ["budget"]


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "1e999", "0", "-1", "lots"])
def test_turn_budget_from_the_environment_must_be_positive_and_finite(monkeypatch, caplog, raw):
    monkeypatch.setenv("COPILOT_TURN_BUDGET_USD", raw)  # "inf" would otherwise switch the spend cap off
    assert copilot.settings().turn_budget_usd == 0.25
    assert "COPILOT_TURN_BUDGET_USD" in caplog.text
    monkeypatch.setenv("COPILOT_TURN_BUDGET_USD", "0.5")
    assert copilot.settings().turn_budget_usd == 0.5


def test_anthropic_errors_are_mapped_without_secrets(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (anthropic.AuthenticationError("bad key sk-secret", response=httpx.Response(401, request=request), body=None), "api_auth"),
        (anthropic.BadRequestError("Your credit balance is too low", response=httpx.Response(400, request=request), body=None), "api_billing"),
        (anthropic.RateLimitError("slow", response=httpx.Response(429, request=request), body=None), "api_rate_limit"),
        (anthropic.APIConnectionError(request=request), "api_unreachable"),
    ]
    for error, code in cases:
        class Failing:
            def stream(self, **kwargs):
                raise error
        cfg = _cfg(backend="anthropic", key_configured=True)
        adapter = copilot.AnthropicAdapter(cfg, client=SimpleNamespace(beta=SimpleNamespace(messages=Failing())))
        events = _turn([{"role": "user", "content": "x"}], adapter, cfg=cfg)
        errors = [e for e in events if e["type"] == "error"]
        assert [e["code"] for e in errors] == [code] and "sk-secret" not in errors[0]["message"]


# --------------------------------------------------------------------------- routes

def _frames(body: str):
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def test_routes_are_off_by_default(monkeypatch):
    monkeypatch.delenv("COPILOT_ENABLED", raising=False)
    with TestClient(app) as client:
        assert client.get("/copilot/status").json()["enabled"] is False
        assert client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 503


def test_chat_streams_and_validates(monkeypatch, caplog):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    real = copilot.adapter_for
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0) if cfg.backend == "fake" else real(cfg))
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        status = client.get("/copilot/status").json()
        assert status["backend"] == "fake" and status["evidence"] == "fixture" and status["model"] == "claude-sonnet-5-5"
        assert "ANTHROPIC_API_KEY" not in json.dumps(status)
        secret = "my account number is 12345 and NBIS looks good"
        response = client.post("/copilot/chat", json={"messages": [{"role": "user", "content": secret}], "symbol": "NBIS"})
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        frames = _frames(response.text)
        assert frames[-1]["type"] == "done" and any(f["type"] == "tool" for f in frames)
        assert secret not in caplog.text and "copilot turn backend=fake" in caplog.text
        bad = [{"role": "assistant", "content": "x"}], [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        for messages in bad:
            assert client.post("/copilot/chat", json={"messages": messages}).status_code == 422
        assert client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "x"}], "symbol": "nb is"}).status_code == 422


def test_a_turn_can_pick_an_offered_model(monkeypatch):
    """GET /status lists the models a turn may pick (COPILOT_MODEL first); POST /chat takes one of them as ``model``;
    anything else is refused before an adapter is built."""
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    monkeypatch.delenv("COPILOT_MODEL", raising=False)
    monkeypatch.setenv("COPILOT_MODELS", " claude-opus-5-5 ,claude-fable-5-1, claude-sonnet-5-5,,Bad Model!")
    seen: list[str] = []
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: seen.append(cfg.model) or copilot.FakeAdapter(0))
    with TestClient(app) as client:
        status = client.get("/copilot/status").json()
        assert status["model"] == "claude-sonnet-5-5"
        assert status["models"] == ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]  # default first, junk dropped
        turn = {"messages": [{"role": "user", "content": "x"}]}
        assert client.post("/copilot/chat", json={**turn, "model": "claude-fable-5-1"}).status_code == 200 and seen[-1] == "claude-fable-5-1"
        assert client.post("/copilot/chat", json=turn).status_code == 200 and seen[-1] == "claude-sonnet-5-5"
        refused = client.post("/copilot/chat", json={**turn, "model": "gpt-9"})
        assert refused.status_code == 422 and "not one of the models" in refused.json()["detail"] and seen[-1] == "claude-sonnet-5-5"
        assert client.post("/copilot/chat", json={**turn, "model": "Bad Model"}).status_code == 422
    monkeypatch.delenv("COPILOT_MODELS")
    assert copilot.settings().models == ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")
    monkeypatch.setenv("COPILOT_MODELS", "")
    assert copilot.settings().models == ("claude-sonnet-5-5",)
    monkeypatch.setenv("COPILOT_MODEL", "claude-opus-5-5")
    assert copilot.settings().models[0] == "claude-opus-5-5" and "models" in copilot.settings().public()


def test_anthropic_backend_without_key_is_an_honest_unavailable_state(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(app) as client:
        assert client.get("/copilot/status").json()["key_configured"] is False
        response = client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "x"}]})
        assert response.status_code == 503 and "ANTHROPIC_API_KEY is not set" in response.json()["detail"]


def test_assistant_sessions_cannot_reach_the_lab(boundary):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    assert boundary.owner.get("/copilot/status").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/status").status_code == 403
    assert boundary.owner.get("/copilot/threads").status_code == 200
    assert boundary.public.get("/copilot/threads").status_code == 403
    assert boundary.public.post("/copilot/chat", json={"messages": [{"role": "user", "content": "NBIS?"}], "symbol": "NBIS"}).status_code == 403
    what_changed = "What changed? Use get_investigation_changes for investigation 33333333-3333-4333-8333-333333333333."
    assert boundary.public.post("/copilot/chat", json={"messages": [{"role": "user", "content": what_changed}]}).status_code == 403
    assert boundary.public.get("/copilot/investigations").status_code == 403
    assert boundary.public.post("/copilot/investigations", json={"title": "x"}).status_code == 403


# --------------------------------------------------------------------------- saved investigations

def test_investigations_save_resume_and_refuse_stale_or_unknown(monkeypatch):
    monkeypatch.delenv("COPILOT_ENABLED", raising=False)
    with TestClient(app) as client:
        assert client.get("/copilot/investigations").status_code == 503
        monkeypatch.setenv("COPILOT_ENABLED", "true")
        transcript = [{"role": "user", "content": "Is NBIS confirming?"}, {"role": "assistant", "content": "Not yet."}]
        evidence = [{"tool": "get_group_comparison", "as_of": "2026-10-23T15:12:00Z", "kind": "simulated", "message": 1}]
        made = client.post("/copilot/investigations", json={"title": "NBIS bounce", "symbol": "NBIS",
                                                            "transcript": transcript, "evidence": evidence})
        assert made.status_code == 201
        saved = made.json()
        assert saved["revision"] == 1 and saved["status"] == "open" and saved["transcript"] == transcript
        assert saved["evidence"] == evidence and saved["message_count"] == 2

        listed = client.get("/copilot/investigations").json()["investigations"]
        assert listed[0]["id"] == saved["id"] and "transcript" not in listed[0] and "evidence" not in listed[0]

        update = {"title": "NBIS bounce", "symbol": "NBIS", "status": "closed", "conclusion": "  Lagging its group.  ",
                  "transcript": transcript + [{"role": "user", "content": "Plan?"}, {"role": "assistant", "content": "Draft."}],
                  "evidence": evidence, "revision": 1}
        put = client.put(f"/copilot/investigations/{saved['id']}", json=update)
        assert put.status_code == 200 and put.json()["revision"] == 2 and put.json()["conclusion"] == "Lagging its group."
        resumed = client.get(f"/copilot/investigations/{saved['id']}").json()
        assert resumed["status"] == "closed" and resumed["message_count"] == 4 and resumed["updated_at"] >= saved["updated_at"]

        assert client.put(f"/copilot/investigations/{saved['id']}", json=update).status_code == 409  # stale revision 1
        assert client.get("/copilot/investigations/not-a-uuid").status_code == 404
        assert client.get(f"/copilot/investigations/{uuid.uuid4()}").status_code == 404
        assert saved["source"] == "copilot" and saved["findings"] is None
        for bad in ({"title": "x", "evidence": [{"tool": "Run Shell"}]}, {"title": "x", "source": "research_job"}, {"title": "x", "evidence": [{"tool": "get_quotes", "data": {}}]},
                    {"title": "x", "status": "watching"}, {"title": ""}, {"title": "x", "symbol": "nb is"}):
            assert client.post("/copilot/investigations", json=bad).status_code == 422, bad


WATCH_CARD = {"id": "toolu_w1", "kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 95.9, "interval": None,
              "label": "NBIS reclaim", "why": "Where the bounce failed.", "last": 94.35, "as_of": "2026-10-24T14:00:00Z",
              "client_id": "0123456789abcdef0123456789abcdef"}
PLAN_CARD = {"id": "toolu_p1", "kind": "trade_plan", "symbol": "NBIS", "direction": "long", "instrument": "stock", "contract": None,
             "thesis": "Reclaims the level with its group.", "entry_trigger": {"condition": "crosses", "price": 95.9, "interval": None},
             "invalidation": {"condition": "crosses", "price": 92.3, "interval": None}, "time_stop": None, "size_note": None,
             "last": 94.35, "as_of": 1729778400, "client_id": "fedcba9876543210fedcba9876543210"}


def _with_cards(*cards):
    return [{"role": "user", "content": "Plan NBIS"}, {"role": "assistant", "content": "Two drafts.", "proposals": list(cards)}]


def test_investigations_keep_each_answers_cards_and_what_was_done_with_them(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with TestClient(app) as client:
        made = client.post("/copilot/investigations", json={"title": "NBIS plan", "transcript": _with_cards(WATCH_CARD, PLAN_CARD)})
        assert made.status_code == 201
        saved = made.json()
        assert saved["transcript"][1]["proposals"] == [WATCH_CARD, PLAN_CARD]  # back exactly, nothing armed or saved
        assert "proposals" not in saved["transcript"][0]
        url = f"/copilot/investigations/{saved['id']}"

        confirmed = {"state": "confirmed", "parts": {"plan": {"state": "done", "text": "Saved."}, "entry": {"state": "failed", "text": "Stale quote."}},
                     "fields": {"thesis": "Reclaims the level.", "entry": "96", "invalidation": "92.3"}}
        put = client.put(f"{url}/proposals/toolu_p1/outcome", json=confirmed)
        assert put.status_code == 200 and put.json()["revision"] == 1  # a recorded result, not an edit
        plan = put.json()["transcript"][1]["proposals"][1]
        assert plan["outcome"]["state"] == "confirmed" and plan["outcome"]["parts"]["entry"]["state"] == "failed"
        assert plan["outcome"]["fields"]["time_stop"] == ""

        # A window that had not seen the Confirm saves its copy (no outcomes): the confirmed card stays confirmed, and a
        # dismiss from it cannot hide what was made.
        stale_copy = {"title": "NBIS plan", "revision": 1, "transcript": _with_cards(WATCH_CARD, {**PLAN_CARD, "outcome": {"state": "dismissed"}})}
        again = client.put(url, json=stale_copy).json()
        assert again["revision"] == 2 and again["transcript"][1]["proposals"][1]["outcome"] == plan["outcome"]
        assert client.put(f"{url}/proposals/toolu_p1/outcome", json={"state": "dismissed"}).json()["transcript"][1]["proposals"][1]["outcome"]["state"] == "confirmed"
        # A dismissed card stays dismissed, and a later Confirm (another window) wins over it.
        assert client.put(f"{url}/proposals/toolu_w1/outcome", json={"state": "dismissed"}).json()["transcript"][1]["proposals"][0]["outcome"] == {"state": "dismissed"}
        kept = client.put(url, json={**stale_copy, "revision": 2}).json()["transcript"][1]["proposals"][0]
        assert kept["outcome"] == {"state": "dismissed"}
        done = client.put(f"{url}/proposals/toolu_w1/outcome", json={"state": "confirmed", "note": "Alert set."}).json()
        assert done["transcript"][1]["proposals"][0]["outcome"] == {"state": "confirmed", "note": "Alert set."}

        assert client.put(f"{url}/proposals/nope/outcome", json={"state": "dismissed"}).status_code == 404
        assert client.put(f"/copilot/investigations/{uuid.uuid4()}/proposals/toolu_w1/outcome", json={"state": "dismissed"}).status_code == 404
        for bad in ({"state": "armed"}, {"state": "confirmed", "note": "x" * 501}, {"state": "confirmed", "parts": {"exit": {"state": "done"}}},
                    {"state": "confirmed", "data": {}}):
            assert client.put(f"{url}/proposals/toolu_w1/outcome", json=bad).status_code == 422, bad


@pytest.mark.parametrize("card", [
    {**WATCH_CARD, "kind": "order"},
    {**WATCH_CARD, "symbol": "nb is"},
    {**WATCH_CARD, "price": -1},
    {**WATCH_CARD, "quantity": 100},  # a field no proposal has
    {**WATCH_CARD, "id": ""},
    {**WATCH_CARD, "client_id": "short"},
    {**WATCH_CARD, "last": 0},
    {**WATCH_CARD, "outcome": {"state": "confirmed", "alert_id": "a1"}},
    {**PLAN_CARD, "invalidation": {"condition": "crosses", "price": 99.0, "interval": None}},  # above a long's entry
    {"id": "toolu_m1", "kind": "memory", "memory_kind": "statement", "symbol": None, "text": "x" * 401},
])
def test_investigation_cards_are_validated_like_the_proposals_they_were(card, monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with TestClient(app) as client:
        assert client.post("/copilot/investigations", json={"title": "x", "transcript": _with_cards(card)}).status_code == 422


def test_investigation_cards_are_capped_and_old_records_read_as_before(monkeypatch):
    from app.engine import copilot_investigations as investigations
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with TestClient(app) as client:
        five = [{**WATCH_CARD, "id": f"toolu_{i}"} for i in range(5)]
        assert client.post("/copilot/investigations", json={"title": "x", "transcript": _with_cards(*five)}).status_code == 422
        twice = client.post("/copilot/investigations", json={"title": "x", "transcript": _with_cards(WATCH_CARD, WATCH_CARD)})
        assert twice.status_code == 422
        across = client.post("/copilot/investigations", json={"title": "x", "transcript": _with_cards(WATCH_CARD) + _with_cards(WATCH_CARD)})
        assert across.status_code == 422  # an outcome is recorded by card id, so it is unique in the investigation
        practice = {"id": "week-review-practice", "kind": "practice", "text": "Exit at my invalidation", "measure": "exit_at_invalidation",
                    "label": "exit at my invalidation", "target": 1.0, "why": "Two of three held past it."}
        memory = {"id": "toolu_m1", "kind": "memory", "memory_kind": "lesson", "symbol": None, "text": "Wait for the close.",
                  "client_id": "0123456789abcdef", "outcome": {"state": "confirmed", "text": "Wait for the 5m close.", "note": "Remembered."}}
        revisit = {"id": "toolu_r1", "kind": "revisit", "question": "Did the group confirm?", "horizon_days": 2}
        ok = client.post("/copilot/investigations", json={"title": "x", "transcript": _with_cards(practice, memory, revisit)})
        assert ok.status_code == 201, ok.text
        cards = ok.json()["transcript"][1]["proposals"]
        assert [c["id"] for c in cards] == ["week-review-practice", "toolu_m1", "toolu_r1"] and cards[1]["outcome"]["text"] == "Wait for the 5m close."
        monkeypatch.setattr(investigations, "MAX_TRANSCRIPT_CHARS", 3000)  # cards count toward the size cap
        big = [{**PLAN_CARD, "id": f"toolu_{i}", "thesis": "t" * 300} for i in range(8)]
        transcript = _with_cards(*big[:4]) + _with_cards(*big[4:])
        assert client.post("/copilot/investigations", json={"title": "x", "transcript": transcript}).status_code == 413

    # A record saved before cards were kept reads exactly as it was stored, and saves again unchanged.
    from sqlmodel import Session
    from app.database import engine
    from app.models import CopilotInvestigation
    old = [{"role": "user", "content": "Is NBIS confirming?"}, {"role": "assistant", "content": "Not yet."}]
    with Session(engine) as db:
        row = CopilotInvestigation(source="copilot", title="Old", transcript_json=json.dumps(old), evidence_json="[]")
        db.add(row)
        db.commit()
        db.refresh(row)
        saved_id = row.id
    read = investigations.get(saved_id)
    assert read["transcript"] == old
    again = investigations.update(saved_id, investigations.InvestigationFields(title="Old", transcript=read["transcript"]), read["revision"])
    assert again["transcript"] == old
    with Session(engine) as db:
        assert json.loads(db.get(CopilotInvestigation, saved_id).transcript_json) == old


# --------------------------------------------------------------------------- replay (no hindsight)

def _replay_store(path, *, with_future: bool):
    from app.engine.radar_comparison import iso
    from app.engine.radar_store import RadarStore, load_universe
    from app.engine.chart_math import ET as NY
    version = load_universe()["version"]
    store = RadarStore(path)
    base = datetime(2026, 10, 23, 11, 12, tzinfo=NY).timestamp()
    symbols = ["NBIS", "CRWV", "APLD", "IREN", "CIFR", "WULF", "ORCL", "QQQ", "SPY"]
    moments = [(base - 900, 100.0), (base, 101.0)] + ([(base + 600, 777.0)] if with_future else [])
    for at, price in moments:
        rows = [{"symbol": s, "last": price, "prev_close": 99, "open": 100, "high": 101, "low": 98, "volume": 1000,
                 "bid": price, "ask": price, "trade_time_ms": int(at * 1000), "retrieved_at": iso(at)} for s in symbols]
        store.append_pass({"session_date": "2026-10-23", "started_at": iso(at), "finished_at": iso(at),
                           "universe_version": version, "status": "ok", "symbols_requested": 9, "symbols_returned": 9,
                           "unmatched": [], "requests_used": 1, "error": None, "skip_reason": None}, rows)
    return path


def test_replay_never_reads_past_the_frozen_moment(tmp_path, monkeypatch):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine import symbol_info_news_feed
    at = parse_at("2026-10-23T11:12")
    full = ReplayEvidence(str(_replay_store(tmp_path / "full.sqlite", with_future=True)), at)
    cut = ReplayEvidence(str(_replay_store(tmp_path / "cut.sqlite", with_future=False)), at)
    for name, args in (("get_group_comparison", ("NBIS",)), ("get_quotes", (["NBIS", "CRWV", "TSLA"],))):
        assert json.dumps(getattr(full, name)(*args), sort_keys=True) == json.dumps(getattr(cut, name)(*args), sort_keys=True)
    quotes = full.get_quotes(["NBIS", "TSLA"])
    assert quotes["prices"] == {"NBIS": 101.0, "TSLA": None} and quotes["not_recorded"] == ["TSLA"]
    assert "777" not in json.dumps(full.get_group_comparison("NBIS"))
    assert full.get_peer_moves("NBIS")["state"] == "unavailable"

    monkeypatch.setattr(symbol_info_news_feed.symbol_news, "view", lambda symbol: {"symbol": symbol, "as_of": "2026-10-24T06:00:00Z",
        "sources": [{"label": "Alpaca", "state": "ok"}], "articles": [
            {"headline": "after the replay", "published_at": "2026-10-23T18:00:00Z"},
            {"headline": "before the replay", "published_at": "2026-10-23T14:00:00Z"},
            {"headline": "no time", "published_at": None}]})
    news = full.get_symbol_news("NBIS", 6)
    assert [a["headline"] for a in news["articles"]] == ["before the replay"] and news["filtered_out_after_replay"] == 2

    from app.engine import symbol_info_tradier
    monkeypatch.setattr(symbol_info_tradier.symbol_events, "events", lambda symbol, today: {"symbol": symbol, "today": today.isoformat(),
        "earnings": {"next": {"date": "2026-11-12"}, "reports": [{"date": "2026-11-12"}, {"date": "2026-08-07"}],
                     "state": "ready", "fetched_at": 1793000000}})
    events = full.get_symbol_events("NBIS")
    assert events["fetched_at"] == "2026-10-23T11:12-04:00" and events["recent_reports"] == [{"date": "2026-08-07"}]


def test_replay_is_local_only_and_honest_when_the_time_is_not_recorded(tmp_path, monkeypatch):
    from app.ai import copilot_replay
    from app import environment
    path = str(_replay_store(tmp_path / "r.sqlite", with_future=False))
    cfg = _cfg(evidence="replay", replay_store=path, replay_at="2026-10-22T11:00")
    with pytest.raises(copilot.CopilotError, match="no recorded passes"):
        copilot.evidence_for(cfg)
    monkeypatch.setattr(environment, "describe", lambda: SimpleNamespace(is_local=False))
    with pytest.raises(copilot.CopilotError) as exc:
        copilot.evidence_for(replace(cfg, replay_at="2026-10-23T11:12"))
    assert exc.value.code == "replay_local_only"
    with pytest.raises(copilot_replay.ReplayUnavailable):
        copilot_replay.parse_at("yesterday")


def test_replay_turn_freezes_the_models_clock(tmp_path):
    seen = {}

    class Capture(copilot.FakeAdapter):
        async def stream_round(self, system, messages, tools, allow_tools=True):
            seen.setdefault("first", messages[-1]["content"])
            async for item in super().stream_round(system, messages, tools, allow_tools):
                yield item

    from app.ai.copilot_replay import ReplayEvidence, parse_at
    evidence = ReplayEvidence(str(_replay_store(tmp_path / "r.sqlite", with_future=True)), parse_at("2026-10-23T11:12"))
    events = _turn([{"role": "user", "content": "Is NBIS confirming?"}], Capture(0), evidence)
    assert "REPLAY: the market clock is frozen at Fri 2026-10-23 11:12 ET" in seen["first"]
    assert all(e["provenance"]["kind"] == "replay" for e in events if e["type"] == "tool" and e.get("status") == "ok")


def test_an_unknown_group_name_lists_the_groups_that_contain_the_symbol(tmp_path):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine.radar_store import load_universe
    expected = [g["name"] for g in load_universe()["groups"] if "NBIS" in g["members"]]
    replay = ReplayEvidence(str(_replay_store(tmp_path / "r.sqlite", with_future=False)), parse_at("2026-10-23T11:12"))
    for evidence in (copilot_tools.LiveEvidence(), replay):
        out = evidence.get_group_comparison("NBIS", "neocloud")
        assert out["state"] == "error" and out["groups_containing_symbol"] == expected and expected
    assert replay.get_group_comparison("NBIS", expected[0])["group"] == expected[0]
    assert "Omit `group`" in copilot_tools.TOOLS[0]["description"]


def test_research_jobs_save_cited_findings_in_process_and_the_copilot_keeps_them():
    from pydantic import ValidationError
    from app.engine import copilot_investigations as inv
    symbol = "ZZRJ"  # unique to this test: the suite shares one database
    findings = {"summary": "Financing stress drives the group.", "key_findings": ["CRWV downgraded"],
                "counterpoints": ["NBIS has a new facility"], "what_would_change": ["CRWV reclaims its low"],
                "citations": [{"url": "https://example.com/a", "publisher": "Wire", "published_at": "2026-10-22T20:00:00Z"}]}
    saved = inv.save_research_result(title="Neocloud financing", symbol=symbol, findings=findings,
                                     evidence=[{"tool": "web_search", "as_of": "2026-10-24T06:00:00Z", "kind": "fetched"}])
    assert saved["source"] == "research_job" and saved["status"] == "open" and saved["findings"]["citations"][0]["publisher"] == "Wire"
    assert inv.list_investigations(symbol=symbol, source="research_job")[0]["id"] == saved["id"]
    assert inv.list_investigations(symbol=symbol, source="copilot") == []
    assert inv.list_investigations(symbol=symbol, before=datetime(2026, 1, 1)) == []

    # A copilot-style save without findings keeps them, and the source never changes.
    kept = inv.update(saved["id"], inv.InvestigationFields(title="Neocloud financing", symbol=symbol, status="closed"), 1)
    assert kept["findings"] == saved["findings"] and kept["source"] == "research_job" and kept["status"] == "closed"
    with pytest.raises(inv.InvestigationError) as stale:
        inv.update(saved["id"], inv.InvestigationFields(title="x"), 1)
    assert stale.value.code == "stale"

    for bad in ({**findings, "citations": [{"url": "javascript:alert(1)"}]}, {**findings, "raw_data": {}},
                {**findings, "key_findings": ["x" * 501]}, {"summary": ""}):
        with pytest.raises(ValidationError):
            inv.save_research_result(title="bad", symbol=symbol, findings=bad)


def test_saved_research_tool_is_bounded_labelled_and_never_reads_past_a_replay(tmp_path):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine import copilot_investigations as inv
    symbol = "ZZSR"  # unique to this test: the suite shares one database
    for i in range(7):
        inv.save_research_result(title=f"Research {i}", symbol=symbol,
                                 findings={"summary": "s" * 900, "key_findings": [f"k{j}" for j in range(9)],
                                           "citations": [{"url": f"https://example.com/{j}", "publisher": "Wire"} for j in range(6)]})
    assert copilot_tools.validate("get_saved_research", {"symbol": "zzsr"}) == {"symbol": "ZZSR", "limit": 3}
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("get_saved_research", {"symbol": symbol, "limit": 6})

    out = copilot_tools.LiveEvidence().get_saved_research(symbol, 5)
    assert [i["title"] for i in out["items"]] == [f"Research {i}" for i in (6, 5, 4, 3, 2)]
    first = out["items"][0]
    assert first["source"] == "research_job" and first["created_at"].endswith("Z")
    assert len(first["findings"]["summary"]) == 600 and len(first["findings"]["key_findings"]) == 5
    assert len(first["findings"]["citations"]) == 4 and "transcript" not in first
    assert copilot_tools.provenance("get_saved_research", out, "live")["kind"] == "saved"

    replay = ReplayEvidence(str(_replay_store(tmp_path / "r.sqlite", with_future=False)), parse_at("2026-10-23T11:12"))
    assert replay.get_saved_research(symbol)["items"] == []  # all saved after the frozen moment
    assert FixtureEvidence().get_saved_research(symbol)["items"] == []


def test_news_keeps_a_bounded_citable_url():
    raw = {"symbol": "NBIS", "sources": [{"label": "Alpaca", "state": "ok"}], "articles": [
        {"headline": "a", "url": "https://example.com/a", "published_at": "2026-10-23T14:00:00Z"},
        {"headline": "b", "url": "javascript:alert(1)"}, {"headline": "c", "url": "https://x.com/" + "y" * 600}, {"headline": "d"}]}
    assert [a["url"] for a in copilot_tools.compact_news(raw, 8)["articles"]] == ["https://example.com/a", None, None, None]


def test_saved_research_returns_copilot_and_research_records_with_provenance():
    from app.engine import copilot_investigations as inv
    symbol = "ZZBO"  # unique to this test
    inv.save_research_result(title="Job", symbol=symbol, findings={"summary": "From a job."})
    inv.create(inv.InvestigationFields(title="Chat", symbol=symbol, conclusion="Lagging",
                                       transcript=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]))
    items = copilot_tools.LiveEvidence().get_saved_research(symbol)["items"]
    assert [(i["source"], i["title"]) for i in items] == [("copilot", "Chat"), ("research_job", "Job")]
    assert items[0]["conclusion"] == "Lagging" and "findings" not in items[0] and items[1]["findings"]["summary"] == "From a job."
    assert all(i["created_at"].endswith("Z") for i in items)


def test_replay_sees_saved_research_by_the_moment_its_evidence_describes(tmp_path):
    from pydantic import ValidationError
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    from app.engine import copilot_investigations as inv
    symbol = "ZZEA"  # unique to this test
    inv.save_research_result(title="At 15:55", symbol=symbol, findings={"summary": "s"}, evidence_at="2026-10-23T15:55:00-04:00")
    inv.save_research_result(title="At 15:56", symbol=symbol, findings={"summary": "s"}, evidence_at="2026-10-23T19:56:00Z")
    inv.save_research_result(title="Live", symbol=symbol, findings={"summary": "s"})  # no evidence time: created now
    store = str(_replay_store(tmp_path / "r.sqlite", with_future=False))

    def titles(at):
        return [i["title"] for i in ReplayEvidence(store, parse_at(at)).get_saved_research(symbol, 5)["items"]]
    assert titles("2026-10-23T15:55") == ["At 15:55"]
    assert titles("2026-10-23T15:54") == []
    assert titles("2026-10-23T15:56") == ["At 15:56", "At 15:55"]
    item = ReplayEvidence(store, parse_at("2026-10-23T15:55")).get_saved_research(symbol)["items"][0]
    assert item["evidence_at"] == "2026-10-23T15:55:00-04:00"
    assert [i["title"] for i in copilot_tools.LiveEvidence().get_saved_research(symbol, 5)["items"]] == ["Live", "At 15:56", "At 15:55"]
    for bad in ("yesterday", "2026-10-23T15:55"):  # unreadable, or no offset
        with pytest.raises(ValidationError):
            inv.save_research_result(title="bad", symbol=symbol, findings={"summary": "s"}, evidence_at=bad)


@pytest.mark.parametrize("model", ["claude-sonnet-5-5-20260901", "some-future-model"])
def test_spend_cap_holds_for_dated_or_unpriced_model_ids(monkeypatch, model):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    calls = []
    asks = [([], [{"type": "tool_use", "id": f"u{i}", "name": "get_quotes", "input": {"symbols": ["SPY"]}}], "tool_use") for i in range(4)]
    stub = _client(asks, calls)
    stub.beta.messages.model = model  # the API reports this id back
    cfg = _cfg(backend="anthropic", key_configured=True, turn_budget_usd=0.01)
    events = _turn([{"role": "user", "content": "x"}], copilot.AnthropicAdapter(cfg, client=stub), cfg=cfg)
    assert [e["code"] for e in events if e["type"] == "error"] == ["budget"] and events[-1]["metrics"]["cost_usd"] > 0


def test_malformed_budget_env_falls_back_instead_of_failing(monkeypatch):
    monkeypatch.setenv("COPILOT_TURN_BUDGET_USD", "lots")
    assert copilot.settings().turn_budget_usd == 0.25


# --------------------------------------------------------------------------- proposals (confirm-a-plan)

@pytest.mark.parametrize("args", [
    {"kind": "order", "symbol": "NBIS"},
    {"kind": "watch", "symbol": "../x", "condition": "crosses", "price": 90, "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "near", "price": 90, "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 0, "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": True, "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 90, "label": "x" * 61, "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 90, "label": "l", "why": " "},
    {"kind": "watch", "symbol": "NBIS", "condition": "closes_beyond", "price": 90, "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 90, "interval": "5m", "label": "l", "why": "w"},
    {"kind": "watch", "symbol": "NBIS", "condition": "crosses", "price": 90, "label": "l", "why": "w", "horizon_days": 2},
    {"kind": "revisit", "question": "q", "horizon_days": 31},
    {"kind": "revisit", "question": "x" * 501},
    {"kind": "revisit", "question": "q", "symbol": "NBIS"},
])
def test_proposals_outside_the_contract_are_refused(args):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("propose_plan", args)


def test_a_proposal_is_validated_needs_a_real_price_and_writes_nothing():
    watch = copilot_tools.validate("propose_plan", {"kind": "watch", "symbol": "nbis", "condition": "closes_beyond", "price": 92.4,
                                                    "interval": "5m", "label": "  Session   low ", "why": "The bounce fails below it."})
    assert watch == {"kind": "watch", "symbol": "NBIS", "condition": "closes_beyond", "price": 92.4, "interval": "5m",
                     "label": "Session low", "why": "The bounce fails below it."}
    assert copilot_tools.validate("propose_plan", {"kind": "revisit", "question": "Still lagging?"})["horizon_days"] == 1
    shown = copilot_tools.call(FixtureEvidence(), "propose_plan", watch)
    assert shown["proposal"]["last"] == 94.35 and "Nothing is saved or active" in shown["note"]
    with pytest.raises(copilot_tools.ToolInputError, match="no current price for ZZZZ"):
        copilot_tools.call(FixtureEvidence(), "propose_plan", {**watch, "symbol": "ZZZZ"})

    class Asks(copilot.FakeAdapter):
        """Proposes a made-up ticker: refused to the model, and no card reaches the owner."""
        async def stream_round(self, system, messages, tools, allow_tools=True):
            if isinstance(messages[-1]["content"], str):
                yield "final", copilot.Round([{"type": "tool_use", "id": "p1", "name": "propose_plan", "input": {**watch, "symbol": "ZZZZ"}}],
                                             "tool_use", copilot._zero_usage())
                return
            yield "final", copilot.Round([{"type": "text", "text": "ok"}], "end_turn", copilot._zero_usage())

    events = _turn([{"role": "user", "content": "plan"}], Asks(0))
    assert not [e for e in events if e["type"] == "proposal"]
    assert [e["summary"] for e in events if e["type"] == "tool" and e.get("status") == "error"] == ["refused: no current price for ZZZZ, so it cannot be watched"]


def test_status_says_whether_alerts_from_the_lab_are_accepted(monkeypatch):
    from app.routers import level_alerts
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    # The alerts route's own request model decides, so the answer follows that route whether or not it accepts copilot yet.
    from pydantic import Field

    class Refuses(level_alerts.AlertCreate):
        source_kind: str = Field(pattern="^(level|drawing|auto)$")

    class Accepts(level_alerts.AlertCreate):
        source_kind: str = Field(pattern="^(level|drawing|auto|copilot)$")
    with TestClient(app) as client:
        for model, expected in ((Refuses, False), (Accepts, True)):
            monkeypatch.setattr(level_alerts, "AlertCreate", model)
            assert client.get("/copilot/status").json()["capabilities"]["copilot_alerts"] is expected


def test_quote_for_confirming_is_fresh_only_when_recent_and_priced(monkeypatch):
    import time as clock
    from app.engine.chart_feed import chart_feed
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    reads = {"rows": [{"symbol": "NBIS", "last": 94.1, "trade_time": 1790000000}], "at": clock.time() - 5, "issue": None}
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: (reads["rows"], reads["at"], reads["issue"]))
    with TestClient(app) as client:
        fresh = client.get("/copilot/quote?symbol=NBIS").json()
        assert fresh["fresh"] is True and fresh["last"] == 94.1 and fresh["trade_time"] == 1790000000
        reads.update(at=clock.time() - 300, issue="Tradier unavailable; showing a kept copy")
        assert client.get("/copilot/quote?symbol=NBIS").json()["fresh"] is False
        reads.update(rows=[], at=clock.time(), issue=None)
        assert client.get("/copilot/quote?symbol=NBIS").json() | {"fetched_at": None} == {
            "symbol": "NBIS", "last": None, "trade_time": None, "fetched_at": None, "age_s": 0.0, "issue": None, "fresh": False}
        assert client.get("/copilot/quote?symbol=nb is").status_code == 422


def test_a_plan_turn_under_live_evidence_still_saves(monkeypatch):
    """Under live evidence propose_plan's provenance kind stays "proposal" (fixture evidence relabels it "simulated",
    which hid this). The lab leaves proposals out of saved evidence, and a page that still sends one saves too."""
    class Live(FixtureEvidence):
        label = "live"

    history = [{"role": "user", "content": "NBIS, let's make a plan."}]
    events = _turn(history, copilot.FakeAdapter(0), evidence=Live())
    tools = [e for e in events if e["type"] == "tool" and e.get("status") == "ok"]
    assert {t["name"]: t["provenance"]["kind"] for t in tools} == {"owner_context": "saved", "get_quotes": "fetched", "propose_plan": "proposal"}
    answer = _text(events)
    lab = [t for t in tools if t["name"] != "propose_plan"]  # what frontend/lib/copilot.ts toSaved sends
    as_sent_before = tools  # what a page from before the fix sent
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with TestClient(app) as client:
        for refs in (lab, as_sent_before):
            body = {"title": "NBIS plan", "symbol": "NBIS", "transcript": [*history, {"role": "assistant", "content": answer}],
                    "evidence": [{"tool": t["name"], "as_of": t["provenance"]["as_of"], "kind": t["provenance"]["kind"], "message": 1} for t in refs]}
            made = client.post("/copilot/investigations", json=body)
            assert made.status_code == 201, made.text
            saved = made.json()
            put = client.put(f"/copilot/investigations/{saved['id']}", json={**body, "revision": saved["revision"]})
            assert put.status_code == 200, put.text


# --------------------------------------------------------------------------- what changed (reopen)

def _changes_world():
    """A saved investigation with a fired and an armed copilot alert, another source's alert, and linked jobs."""
    import time as clock
    from sqlmodel import Session, delete
    from app.database import engine
    from app.engine import copilot_investigations as inv
    from app.engine import research_queue as q
    from app.engine.level_alert_monitor import create_alert
    from app.models import LevelAlert, LevelAlertEvent, ResearchJob
    with Session(engine) as db:
        db.exec(delete(LevelAlertEvent))
        db.exec(delete(LevelAlert))
        db.exec(delete(ResearchJob))
        db.commit()
    saved = inv.create(inv.InvestigationFields(
        title="NBIS bounce", symbol="NBIS", conclusion="Lagging its group",
        transcript=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        evidence=[{"tool": "get_group_comparison", "as_of": f"2026-10-23T15:{m:02d}:00Z", "kind": "recorded", "message": 1} for m in range(10)]
        + [{"tool": "get_symbol_news", "as_of": "2026-10-23T15:05:00Z", "kind": "fetched", "message": 1}] * 300))
    now = clock.time()
    with Session(engine) as db:
        fired = create_alert(db, symbol="NBIS", price=92.46, reference=94.0, condition="crosses", interval=None, session="regular",
                             source_kind="copilot", source_id=saved["id"], label="2% below", now=now)
        create_alert(db, symbol="NBIS", price=99.0, reference=94.0, condition="touches", interval=None, session="regular",
                     source_kind="copilot", source_id=saved["id"], label="breakout", now=now)
        create_alert(db, symbol="NBIS", price=90.0, reference=94.0, condition="touches", interval=None, session="regular",
                     source_kind="level", source_id="lvl", label="not this one", now=now)
        fired.state, fired.fired_at = "fired", datetime.utcfromtimestamp(now + 60)
        db.add(LevelAlertEvent(alert_id=fired.id, generation=fired.generation, level=92.46, price=92.4, source="stream",
                               event_at=datetime.utcfromtimestamp(now + 60)))
        db.commit()
    result = inv.save_research_result(title="Deeper on NBIS", symbol="NBIS", findings={"summary": "Financing stress. " * 60})
    for i in range(12):
        q.enqueue_question(f"Question {i}?", ["NBIS"], from_investigation=saved["id"])
    done, _ = q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=saved["id"])
    with Session(engine) as db:
        row = db.get(ResearchJob, uuid.UUID(done["id"]))
        row.status, row.finished_at, row.investigation_id, row.cost_usd = "done", datetime.utcnow(), uuid.UUID(result["id"]), 0.31
        db.commit()
    return saved


def test_investigation_changes_are_bounded_linked_and_need_a_saved_investigation():
    saved = _changes_world()
    out = copilot_tools.call(copilot_tools.LiveEvidence(), "get_investigation_changes",
                             copilot_tools.validate("get_investigation_changes", {"investigation_id": saved["id"].upper()}))
    assert out["state"] == "ok" and out["investigation"]["conclusion"] == "Lagging its group"
    assert out["evidence_as_of"] == [{"tool": "get_group_comparison", "as_of": "2026-10-23T15:09:00Z", "kind": "recorded"},
                                     {"tool": "get_symbol_news", "as_of": "2026-10-23T15:05:00Z", "kind": "fetched"}]
    assert {a["label"]: bool(a["fired"]) for a in out["alerts"]} == {"2% below": True, "breakout": False}  # only this investigation's
    fired = next(a for a in out["alerts"] if a["fired"])
    assert fired["fired"]["price"] == 92.4 and fired["fired"]["at"].endswith("Z")
    assert len(out["research_jobs"]) == copilot_tools.CHANGE_JOBS and out["research_jobs"][0]["status"] == "done"
    assert out["research_jobs"][0]["since_last_update"] is True and out["research_jobs"][0]["cost_usd"] == 0.31
    assert out["results"][0]["title"] == "Deeper on NBIS" and len(out["results"][0]["summary"]) == 160
    assert len(json.dumps(out)) < copilot_tools.MAX_RESULT_CHARS  # bounded before the 6,000-character cut
    assert copilot_tools.provenance("get_investigation_changes", out, "live")["kind"] == "saved"

    with pytest.raises(copilot_tools.ToolInputError, match="UUID"):
        copilot_tools.validate("get_investigation_changes", {"investigation_id": "../etc"})
    with pytest.raises(copilot_tools.ToolInputError, match="no saved investigation"):
        copilot_tools.call(copilot_tools.LiveEvidence(), "get_investigation_changes", {"investigation_id": str(uuid.uuid4())})
    assert FixtureEvidence().get_investigation_changes(saved["id"])["state"] == "unavailable"


def test_replay_shows_no_change_after_its_frozen_moment(tmp_path):
    from app.ai.copilot_replay import ReplayEvidence, parse_at
    saved = _changes_world()
    replay = ReplayEvidence(str(_replay_store(tmp_path / "r.sqlite", with_future=False)), parse_at("2026-10-23T11:12"))
    assert replay.get_investigation_changes(saved["id"])["state"] == "unavailable"  # saved after that moment


def test_what_changed_runs_through_the_owner_chat_route(monkeypatch):
    saved = _changes_world()
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_EVIDENCE", "live")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    prompt = f"What changed? Use get_investigation_changes for investigation {saved['id']}, then compare it with fresh evidence."
    with TestClient(app) as client:
        frames = _frames(client.post("/copilot/chat", json={"messages": [{"role": "user", "content": prompt}], "symbol": "NBIS"}).text)
    tool = next(f for f in frames if f["type"] == "tool" and f.get("status") == "ok" and f["name"] != "owner_context")
    assert tool["name"] == "get_investigation_changes" and tool["summary"] == "2 alerts (1 fired), 5 research jobs"
    text = "".join(f["delta"] for f in frames if f["type"] == "text")
    assert "Alerts: 2 linked, 1 fired; NBIS at 92.4" in text and "1 result(s) finished since the last update" in text


def test_investigation_changes_fit_whole_at_every_cap():
    """The largest answer the caps allow still fits, so bounded() never cuts it mid-string into broken JSON."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine import copilot_investigations as inv
    from app.engine import research_queue as q
    from app.engine.level_alert_monitor import create_alert
    from app.models import LevelAlertEvent, ResearchJob
    import time as clock
    saved = _changes_world()
    # Every market tool that can carry an as_of (propose_plan has none; the owner context rows are the book, left out
    # below), on the longest symbol a ticker can be.
    tools = [t["name"] for t in copilot_tools.TOOLS if t["name"] != "propose_plan" and t["name"] not in copilot_tools.NOT_CURRENT_TOOLS]
    symbol = "ABCDEFGHIJ"
    inv.update(saved["id"], inv.InvestigationFields(
        title="T" * 120, symbol=symbol, conclusion="C" * 280, findings={"summary": "S" * 2000},
        evidence=[{"tool": t, "as_of": "2026-10-23T15:59:59.999999+00:00", "kind": "recorded", "message": 1}
                  for t in (*tools, "owner_context", "get_owner_context", "get_moment")]), 1)
    now = clock.time()
    with Session(engine) as db:
        for i, price in enumerate((10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5)):
            alert = create_alert(db, symbol=symbol, price=price, reference=price - 1, condition="closes_beyond", interval="15m",
                                 session="extended", source_kind="copilot", source_id=saved["id"], label="L" * 60, now=now)
            db.add(LevelAlertEvent(alert_id=alert.id, generation=alert.generation, level=price, price=price + 0.123456,
                                   source="closed_bar", event_at=datetime.utcfromtimestamp(now + 1)))
        db.commit()
    for i in range(8):
        result = inv.save_research_result(title="R" * 120, symbol="NBIS", conclusion="K" * 280, findings={"summary": "F" * 2000})
        job, _ = q.enqueue_question(f"{i}" + "Q" * 1999, ["NBIS"], from_investigation=saved["id"])
        with Session(engine) as db:
            row = db.get(ResearchJob, uuid.UUID(job["id"]))
            row.status, row.finished_at, row.investigation_id, row.cost_usd = "done", datetime.utcnow(), uuid.UUID(result["id"]), 123.456789
            db.commit()
    out = copilot_tools.investigation_changes(saved["id"])
    assert (len(out["alerts"]), len(out["research_jobs"]), len(out["results"])) == (
        copilot_tools.CHANGE_ALERTS, copilot_tools.CHANGE_JOBS, copilot_tools.CHANGE_RESULTS)
    assert len(out["evidence_as_of"]) == len(tools) <= copilot_tools.CHANGE_EVIDENCE
    assert not {e["tool"] for e in out["evidence_as_of"]} & copilot_tools.NOT_CURRENT_TOOLS
    text = copilot_tools.bounded(out)
    assert len(text) <= copilot_tools.MAX_RESULT_CHARS - 200, len(text)  # headroom for longer ids or times
    assert json.loads(text) == json.loads(json.dumps(out, default=str))


def test_replay_hides_whatever_happened_to_an_investigation_after_its_moment():
    """Alerts armed or fired, jobs queued or finished, and edits made after the frozen moment are all hindsight."""
    from datetime import UTC, timedelta
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import CopilotInvestigation, LevelAlert, LevelAlertEvent, ResearchJob
    saved = _changes_world()
    moment = datetime.now(UTC) + timedelta(hours=1)
    before, after = (moment - timedelta(days=2)).replace(tzinfo=None), (moment + timedelta(hours=2)).replace(tzinfo=None)
    with Session(engine) as db:
        row = db.get(CopilotInvestigation, uuid.UUID(saved["id"]))
        row.created_at, row.updated_at = before, after  # created before the moment, edited after it
        alerts = sorted(db.exec(select(LevelAlert).where(LevelAlert.source_id == saved["id"])).all(), key=lambda a: a.label)
        alerts[0].armed_at = before  # "2% below": armed before, fired after (below)
        alerts[1].armed_at = after   # "breakout": armed after the moment
        for event in db.exec(select(LevelAlertEvent)).all():
            event.event_at = after
        for job in db.exec(select(ResearchJob)).all():
            job.created_at = before if job.status == "done" else after  # the done one was queued before, finished after
            job.finished_at = after if job.status == "done" else None
        db.commit()
    out = copilot_tools.investigation_changes(saved["id"], before=moment)
    assert out["investigation"]["later_state"].startswith("Updated after the replay moment")
    assert not {"conclusion", "updated_at", "messages", "status", "summary"} & set(out["investigation"])
    assert [(a["label"], a["fired"]) for a in out["alerts"]] == [("2% below", None)]  # armed then, not yet fired
    assert [(j["status"], j["finished_at"]) for j in out["research_jobs"]] == [("running", None)]
    assert out["results"] == []
    assert out["evidence_as_of"]  # its evidence predates the moment


# --------------------------------------------------------------------------- trade plan proposals

PLAN = {"kind": "trade_plan", "symbol": "nbis", "direction": "long", "instrument": "calls", "contract": "Nov 21 100C",
        "thesis": "  Neoclouds   turn and NBIS reclaims the prior-day low. ",
        "entry_trigger": {"condition": "closes_beyond", "price": 95.9, "interval": "5m"},
        "invalidation": {"condition": "crosses", "price": 92.3}, "time_stop": "out by 15:30", "size_note": "one starter"}


@pytest.mark.parametrize("change", [
    {"direction": "sideways"}, {"instrument": "futures"},
    {"instrument": "puts"},                                                            # puts are a short view
    {"direction": "short", "instrument": "calls"},
    {"thesis": " "}, {"thesis": "x" * 301}, {"contract": "x" * 41}, {"time_stop": "x" * 81}, {"size_note": "x" * 121},
    {"entry_trigger": {"condition": "closes_beyond", "price": 95.9}},                  # no interval
    {"entry_trigger": {"condition": "crosses", "price": float("inf")}},
    {"entry_trigger": {"condition": "crosses", "price": 0}},
    {"entry_trigger": 95.9},
    {"entry_trigger": {"condition": "crosses", "price": 95.9, "label": "x"}},
    {"invalidation": {"condition": "crosses", "price": 96.0}},                         # a long's stop above its entry
    {"direction": "short", "instrument": "stock"},                                     # a short's stop below its entry
    {"label": "x"},                                                                    # a watch's key
])
def test_trade_plans_outside_the_contract_are_refused(change):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("propose_plan", {**PLAN, **change})


def test_a_trade_plan_is_normalized_needs_a_price_on_the_live_side_and_writes_nothing():
    plan = copilot_tools.validate("propose_plan", PLAN)
    assert plan == {"kind": "trade_plan", "symbol": "NBIS", "direction": "long", "instrument": "calls", "contract": "Nov 21 100C",
                    "thesis": "Neoclouds turn and NBIS reclaims the prior-day low.",
                    "entry_trigger": {"condition": "closes_beyond", "price": 95.9, "interval": "5m"},
                    "invalidation": {"condition": "crosses", "price": 92.3, "interval": None},
                    "time_stop": "out by 15:30", "size_note": "one starter"}
    short = copilot_tools.validate("propose_plan", {**PLAN, "direction": "short", "instrument": "puts", "contract": None,
                                                    "entry_trigger": {"condition": "crosses", "price": 92.3},
                                                    "invalidation": {"condition": "touches", "price": 95.9}})
    assert (short["contract"], short["time_stop"]) == (None, "out by 15:30")
    shown = copilot_tools.call(FixtureEvidence(), "propose_plan", plan)
    assert shown["proposal"]["last"] == 94.35 and "Nothing is saved or armed until they confirm" in shown["note"]
    assert copilot._summary("propose_plan", shown) == "proposed plan: NBIS long calls, entry 95.9, invalidation 92.3"
    with pytest.raises(copilot_tools.ToolInputError, match="no current price for ZZZZ"):
        copilot_tools.call(FixtureEvidence(), "propose_plan", {**plan, "symbol": "ZZZZ"})
    with pytest.raises(copilot_tools.ToolInputError, match="already past the invalidation"):
        copilot_tools.call(FixtureEvidence(), "propose_plan", {**plan, "entry_trigger": {**plan["entry_trigger"], "price": 99.0},
                                                               "invalidation": {**plan["invalidation"], "price": 95.0}})


def test_plan_a_trade_reads_the_chart_and_proposes_one_plan_card_that_saves_nothing():
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import LevelAlert, TradeCapture
    with Session(engine) as db:
        before = (len(db.exec(select(TradeCapture)).all()), len(db.exec(select(LevelAlert)).all()))
    events = _turn([{"role": "user", "content": "Context: Plan a trade: yolo NBIS calls"}], copilot.FakeAdapter(0))
    assert {e["name"] for e in events if e["type"] == "tool"} == {"owner_context", "get_quotes", "get_chart_context", "get_level_history", "propose_plan"}
    [card] = [e for e in events if e["type"] == "proposal"]
    assert (card["kind"], card["symbol"], card["direction"], card["instrument"]) == ("trade_plan", "NBIS", "long", "calls")
    # Levels drafted from the 5m chart: a close above the level overhead, out through the level below.
    assert card["entry_trigger"] == {"condition": "closes_beyond", "price": 95.9, "interval": "5m"}
    assert card["invalidation"] == {"condition": "crosses", "price": 92.3, "interval": None} and card["last"] == 94.35
    assert "Nothing is saved or armed until you confirm it." in _text(events)
    with Session(engine) as db:
        assert (len(db.exec(select(TradeCapture)).all()), len(db.exec(select(LevelAlert)).all())) == before


def test_the_prompt_pressure_tests_a_trade_before_one_plan_card():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    for phrase in ('carries the "Plan a trade:" context', "pressure-test the idea", "Ask only for what is missing",
                   "do not interrogate them: draft concrete levels from get_chart_context", "exactly one propose_plan kind=trade_plan",
                   "counts toward the two proposals an answer may make", "nothing exists until they confirm it"):
        assert phrase in prompt, phrase


# --------------------------------------------------------------------------- memory proposals and the prompt's frame

@pytest.mark.parametrize("args", [
    {"kind": "memory", "text": "t"},                                                     # no memory_kind
    {"kind": "memory", "memory_kind": "rule", "text": "t"},                              # not a store kind
    {"kind": "memory", "memory_kind": "lesson", "text": "   "},                          # blank
    {"kind": "memory", "memory_kind": "lesson", "text": "x" * 401},                      # over the cap
    {"kind": "memory", "memory_kind": "lesson", "text": "t", "symbol": "BRK.B1"},        # not the store's symbol form
    {"kind": "memory", "memory_kind": "lesson", "text": "t", "interpretation": "i" * 301},
    {"kind": "memory", "memory_kind": "lesson", "text": "t", "price": 90},               # a watch's key
])
def test_memory_proposals_outside_the_contract_are_refused(args):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("propose_plan", args)


def test_a_memory_proposal_is_normalized_needs_no_price_and_writes_nothing():
    memory = copilot_tools.validate("propose_plan", {"kind": "memory", "memory_kind": "thesis", "symbol": "nbis",
                                                     "text": "  NBIS is a two-year  infrastructure thesis for me. ",
                                                     "interpretation": "Ask whether a weekly call fits that horizon."})
    assert memory == {"kind": "memory", "memory_kind": "thesis", "symbol": "NBIS", "text": "NBIS is a two-year infrastructure thesis for me.",
                      "interpretation": "Ask whether a weekly call fits that horizon."}
    assert copilot_tools.validate("propose_plan", {"kind": "memory", "memory_kind": "lesson", "text": "t"}) == {
        "kind": "memory", "memory_kind": "lesson", "symbol": None, "text": "t"}

    class Dead(FixtureEvidence):
        def get_quotes(self, symbols):
            raise AssertionError("a memory needs no price")
    shown = copilot_tools.call(Dead(), "propose_plan", memory)
    assert shown["proposal"] == memory and "Nothing is remembered until they confirm" in shown["note"]
    assert copilot._summary("propose_plan", shown) == "proposed memory (thesis, NBIS): NBIS is a two-year infrastructure thesis for me."


def test_remember_proposes_a_memory_card_in_the_owners_words_and_saves_nothing():
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import JoMemoryRevision
    with Session(engine) as db:
        before = len(db.exec(select(JoMemoryRevision)).all())
    events = _turn([{"role": "user", "content": "Remember that NBIS is a two-year infrastructure thesis for me, not a weekly trade."}],
                   copilot.FakeAdapter(0))
    [card] = [e for e in events if e["type"] == "proposal"]
    assert card["kind"] == "memory" and card["memory_kind"] == "statement" and card["symbol"] == "NBIS"
    assert card["text"] == "NBIS is a two-year infrastructure thesis for me, not a weekly trade."
    tool = next(e for e in events if e["type"] == "tool" and e["name"] == "propose_plan" and e["status"] == "ok")
    assert tool["provenance"]["kind"] == "simulated" and tool["summary"].startswith("proposed memory (statement, NBIS)")
    assert "nothing is remembered until you do" in _text(events)
    with Session(engine) as db:
        assert len(db.exec(select(JoMemoryRevision)).all()) == before  # a card only; the owner's Confirm writes


def test_the_confirmed_memory_shape_is_what_the_store_accepts():
    """What the card's Confirm sends (frontend/lib/copilot.ts saveMemory): the owner's edited words as their own statement,
    active and confirmed, with the investigation as reference. The route is the existing owner-only POST /jo/memories."""
    from jo_briefing_common import MemorySave
    body = MemorySave(operation_id="3f1c2b9a-0d4e-4f6a-9b8c-7d6e5f4a3b2c", kind="thesis", symbol="NBIS",
                      original_text="NBIS is a two-year infrastructure thesis for me.", interpretation="Ask whether a weekly call fits.",
                      source="owner_statement", source_reference="copilot:33333333-3333-4333-8333-333333333333",
                      status="active", owner_confirmed=True)
    assert body.status == "active" and body.source == "owner_statement"
    with pytest.raises(ValueError):
        MemorySave(operation_id="op", kind="thesis", original_text="t", source="owner_statement", status="active")  # no owner_confirmed


def test_the_prompt_frames_the_owner_the_four_questions_and_memory_without_rules_or_diagnoses():
    prompt = copilot.SYSTEM_PROMPT
    for phrase in ("working hypotheses", "never a diagnosis", "exits, not entries", "associations in past trades, not rules",
                   "rejected all three mechanical exits", "1. Thesis", "2. Setup", "3. Instrument", "4. The decision now",
                   "no implied volatility or Greeks", "\"Nothing here changes the plan\"", "propose_plan kind=memory",
                   "nothing is remembered", "never one that characterizes their psychology",
                   "you cannot create alerts or research jobs yourself", "never turn a measured count into a judgement"):
        assert phrase in prompt, phrase
    assert "always exit" not in prompt.lower() and "you must sell" not in prompt.lower()


def test_investigations_keep_an_answers_rating_and_metrics(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    metrics = {"first_text_ms": 900, "total_ms": 4200, "rounds": 2, "model": "fake", "backend": "fake", "tools": ["get_quote"]}
    turns = [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A", "rating": "helped", "metrics": metrics}]
    with TestClient(app) as client:
        made = client.post("/copilot/investigations", json={"title": "Rated", "transcript": turns})
        assert made.status_code == 201
        saved = made.json()
        assert saved["transcript"][1]["rating"] == "helped" and saved["transcript"][1]["metrics"] == metrics
        url = f"/copilot/investigations/{saved['id']}"
        # Switched, then cleared, without a revision.
        assert client.put(f"{url}/messages/1/rating", json={"rating": "didnt"}).json()["transcript"][1]["rating"] == "didnt"
        assert "rating" not in client.put(f"{url}/messages/1/rating", json={"rating": None}).json()["transcript"][1]
        assert client.put(f"{url}/messages/1/rating", json={"rating": "helped"}).status_code == 200
        # A window that had not seen the rating saves its copy: the rating stays.
        stale = [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}]
        again = client.put(url, json={"title": "Rated", "revision": 1, "transcript": stale}).json()
        assert again["transcript"][1]["rating"] == "helped"
        # Not an answer, out of range, or a bad value.
        assert client.put(f"{url}/messages/0/rating", json={"rating": "helped"}).status_code == 404
        assert client.put(f"{url}/messages/9/rating", json={"rating": "helped"}).status_code == 404
        assert client.put(f"{url}/messages/1/rating", json={"rating": "great"}).status_code == 422


def test_investigations_without_a_rating_or_metrics_still_load_and_bad_ones_are_refused(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    with TestClient(app) as client:
        plain = client.post("/copilot/investigations", json={"title": "Old", "transcript": [{"role": "assistant", "content": "A"}]})
        assert plain.status_code == 201 and "rating" not in plain.json()["transcript"][0] and "metrics" not in plain.json()["transcript"][0]
        for bad in ({"rating": "meh"}, {"metrics": {"total_ms": -1}}, {"metrics": {"model": "x" * 200}}, {"metrics": {"extra": 1}}):
            r = client.post("/copilot/investigations", json={"title": "Bad", "transcript": [{"role": "assistant", "content": "A", **bad}]})
            assert r.status_code == 422, bad
