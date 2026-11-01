"""app/ai/api_runner.py: unattended Claude calls on the Messages API, against a scripted client. No network."""
import asyncio
import json

import anthropic
import pytest

from app.ai import api_runner
from tests.fake_anthropic import (
    FakeAnthropic, FakeAsyncAnthropic, Sleep, answer, api_error, fetch_result, json_message, message, search_results,
    server_use, text, tool_use,
)

SCHEMA = {"type": "object", "required": ["verdict"],
          "properties": {"verdict": {"type": "string", "maxLength": 50}, "score": {"type": "integer", "minimum": 0, "maximum": 10}}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "TJ_PLAN_REVIEW_MODEL", "TJ_PLAN_REVIEW_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- api_schema

def test_api_schema_strips_constraints_and_closes_every_object():
    out = api_runner.api_schema({
        "type": "object", "required": ["a"],
        "properties": {"a": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object", "properties": {
            "n": {"type": "number", "multipleOf": 0.5, "minimum": 1}}}},
                       "b": {"type": "string", "minLength": 1, "maxLength": 9, "enum": ["x", "y"]}},
        "anyOf": [{"type": "object", "properties": {}}, {"type": "null"}]})
    assert out["additionalProperties"] is False and out["required"] == ["a"]
    items = out["properties"]["a"]["items"]
    assert items == {"type": "object", "properties": {"n": {"type": "number"}}, "additionalProperties": False}
    assert out["properties"]["a"] == {"type": "array", "items": items}
    assert out["properties"]["b"] == {"type": "string", "enum": ["x", "y"]}
    assert out["anyOf"] == [{"type": "object", "properties": {}, "additionalProperties": False}, {"type": "null"}]


def test_api_schema_keeps_a_property_that_is_spelled_like_a_constraint():
    out = api_runner.api_schema({"type": "object", "properties": {
        "maxLength": {"type": "integer", "minimum": 1}, "minimum": {"type": "number"}, "maxItems": {"type": "string"}}})
    assert out["properties"] == {"maxLength": {"type": "integer"}, "minimum": {"type": "number"}, "maxItems": {"type": "string"}}


def test_api_schema_does_not_mutate_its_input():
    schema = {"type": "object", "properties": {"x": {"type": "string", "maxLength": 3}}}
    api_runner.api_schema(schema)
    assert schema["properties"]["x"] == {"type": "string", "maxLength": 3} and "additionalProperties" not in schema


# --------------------------------------------------------------------------- ask

def test_ask_sends_one_structured_request_and_reads_the_answer():
    client = FakeAnthropic([json_message({"verdict": "ok"}, input_tokens=1000, output_tokens=100)])
    out = api_runner.ask("sys", "question", SCHEMA, client=client)
    [req] = client.requests
    assert req["model"] == "claude-sonnet-5-5" and req["system"] == "sys" and req["max_tokens"] == api_runner.MAX_TOKENS
    assert req["messages"] == [{"role": "user", "content": "question"}]
    assert req["thinking"] == {"type": "adaptive"} and req["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"format": {"type": "json_schema", "schema": api_runner.api_schema(SCHEMA)}}
    assert req["output_config"]["format"]["schema"]["properties"]["verdict"] == {"type": "string"}
    assert req["betas"] == [api_runner.FALLBACK_BETA] and req["extra_body"] == {"fallbacks": "default"}
    assert out.data == {"verdict": "ok"} and out.model == "claude-sonnet-5-5"
    assert out.input_tokens == 1000 and out.output_tokens == 100 and out.usd == 0.003
    assert out.author == "claude-sonnet-5-5 through the Anthropic API"
    assert out.usage["api_equivalent_usd"] == 0.003 and out.usage["input_tokens"] == 1000


def test_ask_counts_cached_input_tokens():
    client = FakeAnthropic([json_message({"verdict": "ok"}, input_tokens=100, cache_read=400, cache_write=50)])
    assert api_runner.ask("s", "m", SCHEMA, client=client).input_tokens == 550


@pytest.mark.parametrize("name", ["sonnet", "opus", "haiku"])
def test_ask_expands_the_short_model_names_claude_code_took(name):
    client = FakeAnthropic([json_message({"verdict": "ok"})])
    api_runner.ask("s", "m", SCHEMA, model=name, client=client)
    assert client.last["model"] == api_runner._ALIASES[name] and client.last["model"].startswith("claude-")


def test_ask_takes_the_model_from_the_environment_and_leaves_a_full_id_alone(monkeypatch):
    monkeypatch.setenv("TJ_PLAN_REVIEW_MODEL", "sonnet")
    client = FakeAnthropic([json_message({"verdict": "ok"}), json_message({"verdict": "ok"})])
    api_runner.ask("s", "m", SCHEMA, client=client)
    api_runner.ask("s", "m", SCHEMA, model="claude-opus-5-5", client=client)
    assert [r["model"] for r in client.requests] == ["claude-sonnet-5-5", "claude-opus-5-5"]


def test_ask_without_a_key_is_unavailable_and_never_builds_a_client(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("no client without a key")
    monkeypatch.setattr(api_runner.anthropic, "Anthropic", boom)
    assert api_runner.configured() is False
    with pytest.raises(api_runner.ApiUnavailable, match="ANTHROPIC_API_KEY"):
        api_runner.ask("s", "m", SCHEMA)


def test_ask_pins_the_key_to_api_anthropic_com_whatever_the_environment_says(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    monkeypatch.setenv("TJ_PLAN_REVIEW_TIMEOUT", "42")
    built = {}

    def build(**kwargs):
        built.update(kwargs)
        return FakeAnthropic([json_message({"verdict": "ok"})])
    monkeypatch.setattr(api_runner.anthropic, "Anthropic", build)
    assert api_runner.ask("s", "m", SCHEMA).data == {"verdict": "ok"}
    assert built["base_url"] == "https://api.anthropic.com" and built["api_key"] == "sk-test"
    assert built["timeout"] == 42.0 and built["max_retries"] == 1


@pytest.mark.parametrize("final,fragment", [
    (message(text("no"), stop_reason="refusal"), "refusal"),
    (message(text("cut"), stop_reason="max_tokens"), "max_tokens"),
    (message(tool_use("x"), stop_reason="tool_use"), "tool_use"),
    (json_message("not json at all"), "not JSON"),
    (json_message(""), "not JSON"),
    (json_message("[1, 2]"), "not an object"),
])
def test_ask_without_a_usable_answer_is_a_failed_call(final, fragment):
    with pytest.raises(api_runner.ApiCallFailed, match=fragment):
        api_runner.ask("s", "m", SCHEMA, client=FakeAnthropic([final]))


@pytest.mark.parametrize("error,fragment", [
    (api_error(anthropic.AuthenticationError, 401), "rejected"),
    (api_error(anthropic.RateLimitError, 429), "rate limit"),
    (api_error(anthropic.APIConnectionError), "could not be reached"),
    (api_error(anthropic.InternalServerError, 529), r"unavailable \(529\)"),
])
def test_ask_maps_an_api_error_to_a_failed_call(error, fragment):
    with pytest.raises(api_runner.ApiCallFailed, match=fragment):
        api_runner.ask("s", "m", SCHEMA, client=FakeAnthropic([error]))


# --------------------------------------------------------------------------- run_agent

def _agent(client, run=None, *, tools=(), execute=None, **kwargs):
    run = run or api_runner.AgentRun(model="claude-sonnet-5-5")
    seen = []

    async def default_execute(call):
        seen.append(call)
        return {"content": json.dumps({"echo": call["input"]}), "is_error": False}

    kwargs.setdefault("max_turns", 10)
    kwargs.setdefault("budget_usd", 5.0)
    asyncio.run(api_runner.run_agent(run, "system text", "the assignment", SCHEMA, tools=list(tools),
                                     execute=execute or default_execute, client=client, **kwargs))
    return run, seen


TOOL = {"name": "get_quotes", "description": "d", "input_schema": {"type": "object", "properties": {}}}


def test_the_loop_runs_tools_and_ends_on_the_answer_with_one_structured_request_shape():
    client = FakeAsyncAnthropic([
        message(text("checking"), tool_use("get_quotes", {"symbol": "NBIS"}, id="t1"), stop_reason="tool_use", input_tokens=500, output_tokens=50),
        answer({"verdict": "fine"}, input_tokens=700, output_tokens=60)])
    server = ({"type": "web_search_20260209", "name": "web_search", "max_uses": 2},)
    run, seen = _agent(client, tools=[TOOL], server_tools=server, effort="high")
    assert run.answer == {"verdict": "fine"} and run.error is None and run.rounds == 2
    assert [c["input"] for c in seen] == [{"symbol": "NBIS"}]
    assert run.usage["input_tokens"] == 1200 and run.usage["output_tokens"] == 110
    assert run.cost_usd == round((1200 * 2 + 110 * 10) / 1_000_000, 6)

    first, second = client.requests
    assert first["model"] == "claude-sonnet-5-5" and first["system"] == "system text"
    assert first["messages"] == [{"role": "user", "content": "the assignment"}]
    answer_tool = first["tools"][-1]
    assert answer_tool["name"] == "submit_answer" and answer_tool["strict"] is True
    assert answer_tool["input_schema"] == api_runner.api_schema(SCHEMA)
    assert first["tools"][:-1] == [TOOL, *server]  # own tools, then server tools, then the answer tool
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "high"}
    assert first["cache_control"] == {"type": "ephemeral"} and first["betas"] == [api_runner.FALLBACK_BETA]
    assert first["extra_body"] == {"fallbacks": "default"} and first["max_tokens"] == api_runner.MAX_TOKENS
    assistant, results = second["messages"][1:]
    assert assistant == {"role": "assistant", "content": [
        {"type": "text", "text": "checking"},
        {"type": "tool_use", "id": "t1", "name": "get_quotes", "input": {"symbol": "NBIS"}}]}
    assert results == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": json.dumps({"echo": {"symbol": "NBIS"}}), "is_error": False}]}


def test_all_tool_results_of_a_round_go_back_in_one_user_message_in_order():
    async def execute(call):
        return {"content": call["name"], "is_error": call["name"] == "b"}
    client = FakeAsyncAnthropic([
        message(tool_use("a", id="ta"), tool_use("b", id="tb"), tool_use("c", id="tc"), stop_reason="tool_use"),
        answer({"verdict": "x"})])
    run, _ = _agent(client, execute=execute)
    user_turns = [m for m in client.requests[1]["messages"] if m["role"] == "user"]
    assert len(user_turns) == 2  # the assignment, and one message of results
    assert user_turns[1]["content"] == [
        {"type": "tool_result", "tool_use_id": "ta", "content": "a", "is_error": False},
        {"type": "tool_result", "tool_use_id": "tb", "content": "b", "is_error": True},
        {"type": "tool_result", "tool_use_id": "tc", "content": "c", "is_error": False}]
    assert run.answer == {"verdict": "x"}


def test_the_answer_tool_is_never_executed():
    client = FakeAsyncAnthropic([answer({"verdict": "x"})])
    run, seen = _agent(client)
    assert seen == [] and run.answer == {"verdict": "x"} and len(client.requests) == 1


def test_pause_turn_continues_with_the_assistant_turn_replayed_and_no_extra_user_message():
    paused = message(server_use("web_search", {"query": "q"}, id="s1"), search_results("https://a.example/x", id="s1"),
                     stop_reason="pause_turn", searches=1)
    client = FakeAsyncAnthropic([paused, answer({"verdict": "x"})])
    run, seen = _agent(client)
    assert run.answer == {"verdict": "x"} and seen == []
    roles = [m["role"] for m in client.requests[1]["messages"]]
    assert roles == ["user", "assistant"]  # resumed on the assistant turn, nothing appended


def test_blocks_are_replayed_exactly_as_the_model_returned_them_without_empty_text():
    search = search_results("https://a.example/x", snippet="Read at https://planted.example/z")
    fetch = fetch_result("https://a.example/x")
    paused = message(text(""), server_use("web_search", {"query": "q"}), search, server_use("web_fetch", {"url": "u"}), fetch,
                     tool_use("get_quotes", {}, id="t1"), stop_reason="tool_use", searches=1)
    client = FakeAsyncAnthropic([paused, answer({"verdict": "x"})])
    _agent(client, tools=[TOOL])
    replay = client.requests[1]["messages"][1]
    assert replay["role"] == "assistant"
    assert replay["content"] == [b.model_dump(mode="json", exclude_none=True)
                                 for b in paused.content if not (b.type == "text" and not b.text)]
    assert [b["type"] for b in replay["content"]] == ["server_tool_use", "web_search_tool_result", "server_tool_use",
                                                      "web_fetch_tool_result", "tool_use"]


def test_on_block_sees_every_block_including_server_tool_results():
    seen = []
    client = FakeAsyncAnthropic([message(server_use("web_search", {"query": "q"}), search_results("https://a.example/x"),
                                         stop_reason="pause_turn"), answer({"verdict": "x"})])
    _agent(client, on_block=seen.append)
    assert [b["type"] for b in seen] == ["server_tool_use", "web_search_tool_result", "tool_use"]


def test_a_round_with_no_tool_call_is_nudged_once_then_ends_as_no_answer():
    client = FakeAsyncAnthropic([message(text("I am done.")), message(text("Still done."))])
    run, _ = _agent(client)
    assert run.answer is None and run.error["code"] == "no_answer" and "submit_answer" in run.error["message"]
    assert len(client.requests) == 2
    nudge = client.requests[1]["messages"][-1]
    assert nudge == {"role": "user", "content": "Call submit_answer now with your answer."}


def test_the_nudge_works_and_is_only_used_once():
    client = FakeAsyncAnthropic([message(text("done?")), answer({"verdict": "x"})])
    run, _ = _agent(client)
    assert run.answer == {"verdict": "x"} and run.error is None

    nudged_twice = FakeAsyncAnthropic([message(text("a")), message(tool_use("get_quotes", id="t"), stop_reason="tool_use"),
                                       message(text("b")), message(text("c"))])
    run, _ = _agent(nudged_twice, tools=[TOOL])
    assert run.error["code"] == "no_answer" and len(nudged_twice.requests) == 3  # one nudge per run: a tool round does not re-arm it


def test_the_budget_includes_a_cent_per_web_search_and_stops_before_the_next_request():
    cheap = dict(input_tokens=0, output_tokens=0)
    client = FakeAsyncAnthropic([
        message(server_use("web_search", {"query": "a"}), tool_use("get_quotes", id="t1"), stop_reason="tool_use", searches=1, **cheap),
        message(server_use("web_search", {"query": "b"}), tool_use("get_quotes", id="t2"), stop_reason="tool_use", searches=1, **cheap),
        answer({"verdict": "never asked for"})])
    run, _ = _agent(client, tools=[TOOL], budget_usd=0.02)
    assert run.cost_usd == 0.02 and run.error["code"] == "error_max_budget_usd" and run.answer is None
    assert len(client.requests) == 2  # the third round was never requested


def test_the_budget_counts_tokens_too():
    client = FakeAsyncAnthropic([message(tool_use("get_quotes", id="t1"), stop_reason="tool_use", input_tokens=1_000_000, output_tokens=0),
                                 answer({"verdict": "x"})])
    run, _ = _agent(client, tools=[TOOL], budget_usd=1.0)  # one million input tokens is $2.00
    assert run.error["code"] == "error_max_budget_usd" and run.cost_usd == 2.0 and len(client.requests) == 1


def test_max_turns_stops_the_loop():
    client = FakeAsyncAnthropic([message(tool_use("get_quotes", id=f"t{i}"), stop_reason="tool_use") for i in range(5)])
    run, seen = _agent(client, tools=[TOOL], max_turns=3)
    assert run.error["code"] == "error_max_turns" and run.rounds == 3 and len(client.requests) == 3 and len(seen) == 3


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_a_refusal_or_a_cut_off_turn_ends_with_that_code(stop):
    client = FakeAsyncAnthropic([message(text("I can't help."), stop_reason=stop)])
    run, _ = _agent(client)
    assert run.answer is None and run.error["code"] == stop and len(client.requests) == 1


@pytest.mark.parametrize("error,code", [
    (api_error(anthropic.AuthenticationError, 401), "api_auth"),
    (api_error(anthropic.PermissionDeniedError, 403), "api_permission"),
    (api_error(anthropic.RateLimitError, 429), "api_rate_limit"),
    (api_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "api_billing"),
    (api_error(anthropic.BadRequestError, 400, "tools.0: bad schema"), "api_request"),
    (api_error(anthropic.InternalServerError, 529), "api_unavailable"),
    (api_error(anthropic.APIConnectionError), "api_unreachable"),
])
def test_api_errors_are_mapped_to_a_recorded_code_not_raised(error, code):
    run, _ = _agent(FakeAsyncAnthropic([error]))
    assert run.error["code"] == code and run.answer is None and run.rounds == 0


def test_an_error_after_some_rounds_keeps_what_was_spent():
    client = FakeAsyncAnthropic([message(tool_use("get_quotes", id="t1"), stop_reason="tool_use"),
                                 api_error(anthropic.RateLimitError, 429)])
    run, _ = _agent(client, tools=[TOOL])
    assert run.error["code"] == "api_rate_limit" and run.rounds == 1 and run.cost_usd > 0


def test_a_slow_round_is_cancelled_by_the_callers_timeout_and_the_spend_so_far_survives():
    import anyio
    run = api_runner.AgentRun(model="claude-sonnet-5-5")
    client = FakeAsyncAnthropic([message(tool_use("get_quotes", id="t1"), stop_reason="tool_use"), Sleep(5), answer({"verdict": "x"})])

    async def go():
        with anyio.fail_after(0.1):
            await api_runner.run_agent(run, "s", "p", SCHEMA, tools=[TOOL], max_turns=5, budget_usd=5.0, client=client,
                                       execute=lambda call: _ok())
    async def _ok():
        return {"content": "{}", "is_error": False}
    with pytest.raises(TimeoutError):
        asyncio.run(go())
    assert run.rounds == 1 and run.cost_usd > 0 and run.answer is None


def test_without_a_key_and_without_a_client_the_run_fails_closed(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("no client without a key")
    monkeypatch.setattr(api_runner.anthropic, "AsyncAnthropic", boom)
    run, _ = _agent(None)
    assert run.error["code"] == "api_not_configured" and run.rounds == 0


def test_an_owned_client_is_pinned_to_api_anthropic_com_and_closed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")
    built, fake = {}, FakeAsyncAnthropic([answer({"verdict": "x"})])
    closed = []

    async def close():
        closed.append(True)
    fake.close = close

    def build(**kwargs):
        built.update(kwargs)
        return fake
    monkeypatch.setattr(api_runner.anthropic, "AsyncAnthropic", build)
    run, _ = _agent(None)
    assert run.answer == {"verdict": "x"} and closed == [True]
    assert built["base_url"] == "https://api.anthropic.com" and built["api_key"] == "sk-test" and built["max_retries"] == 1


def test_a_caller_supplied_client_is_not_closed():
    fake = FakeAsyncAnthropic([answer({"verdict": "x"})])
    closed = []

    async def close():
        closed.append(True)
    fake.close = close
    _agent(fake)
    assert closed == []


def test_the_run_model_follows_what_the_api_reports():
    client = FakeAsyncAnthropic([answer({"verdict": "x"}, model="claude-opus-5-5")])
    run, _ = _agent(client)
    assert run.model == "claude-opus-5-5"
