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
    tools = [e for e in first if e["type"] == "tool" and e["status"] != "running"]
    assert {t["name"] for t in tools} == {"get_group_comparison", "get_symbol_news", "get_symbol_events"}
    assert all(t["provenance"]["kind"] == "simulated" and t["provenance"]["as_of"] for t in tools)
    answer = _text(first)
    assert "Simulated model" in answer and "Neoclouds and AI hosting" in answer and "Counterargument" in answer
    assert first[-1]["type"] == "done" and first[-1]["metrics"]["cost_usd"] == 0.0

    history = [{"role": "user", "content": "NBIS looks like it might recover."}, {"role": "assistant", "content": answer},
               {"role": "user", "content": "But CRWV and APLD are recovering too. You're discounting the group strength."}]
    second = _turn(history, copilot.FakeAdapter(0))
    assert {e["name"] for e in second if e["type"] == "tool"} == {"get_group_comparison", "get_peer_moves"}
    assert "CRWV +1.92%" in _text(second) and "lagging" in _text(second)

    history += [{"role": "assistant", "content": _text(second)}, {"role": "user", "content": "Okay, let's make a plan."}]
    third = _turn(history, copilot.FakeAdapter(0))
    # A plan proposes cards and activates nothing: only a price read and propose_plan run.
    assert {e["name"] for e in third if e["type"] == "tool"} == {"get_quotes", "propose_plan"}
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
    ran = [e for e in events if e["type"] == "tool" and e["status"] == "ok"]
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
        assert not [e for e in events if e["type"] == "tool"]


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
    order = [e["type"] for e in events]
    assert order.index("progress") < order.index("tool") < order.index("text")
    assert {t["name"] for t in first["tools"]} == copilot_tools.TOOL_NAMES and all(t["eager_input_streaming"] for t in first["tools"])
    # The thinking block and tool_use go back unchanged within the turn; the tool result follows.
    second = calls[1]["messages"]  # the turn's live list: user, assistant(thinking, tool_use), tool results, ...
    assert second[1]["content"][0]["signature"] == "sig" and second[2]["content"][0]["tool_use_id"] == "u1"
    assert "sk-test" not in json.dumps(calls, default=str) + json.dumps(events)
    metrics = events[-1]["metrics"]
    assert metrics["usage"] == {"input_tokens": 2000, "output_tokens": 1000, "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 0}
    assert metrics["cost_usd"] == pytest.approx((2000 * 2 + 1000 * 10 + 4000 * 0.2) / 1e6)
    assert metrics["first_text_ms"] is not None and metrics["tool_calls"][0]["name"] == "get_group_comparison"
    assert metrics["first_feedback_ms"] == metrics["first_progress_ms"] <= metrics["first_text_ms"]
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
    assert metrics["first_feedback_ms"] == metrics["first_progress_ms"] < 100
    assert metrics["first_text_ms"] >= 200 and metrics["max_silence_ms"] >= 190


def test_turn_stops_at_its_spend_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    calls = []
    asks = [([], [{"type": "tool_use", "id": f"u{i}", "name": "get_quotes", "input": {"symbols": ["SPY"]}}], "tool_use") for i in range(4)]
    cfg = _cfg(backend="anthropic", key_configured=True, turn_budget_usd=0.01)  # each stub round costs ~$0.0074
    events = _turn([{"role": "user", "content": "x"}], copilot.AnthropicAdapter(cfg, client=_client(asks, calls)), cfg=cfg)
    assert len(calls) == 2 and [e["code"] for e in events if e["type"] == "error"] == ["budget"]


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
    assert boundary.public.post("/copilot/chat", json={"messages": [{"role": "user", "content": "NBIS?"}], "symbol": "NBIS"}).status_code == 403
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
            assert client.get("/copilot/status").json()["capabilities"] == {"copilot_alerts": expected}


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
