"""model.py tests: every provider is a fake; no network, no subprocess to a model."""

import json
import os
import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from research.opening_lab import model as M
from research.opening_lab.contract import FORECAST_SCHEMA

GOOD = {"spy_p_up": 0.55, "qqq_p_up": 0.6, "action": "LONG", "symbol": "QQQ", "reason": "trend"}
PACKET = {"checkpoint_et": "09:35", "symbols": {"SPY": {"last": 1.0}}}
PROMPT = "You forecast SPY and QQQ."


def usage(i=100, o=50, cr=0, cw=0):
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr,
                           cache_creation_input_tokens=cw)


def response(payload=GOOD, *, stop="end_turn", text=None, u=None, model="claude-sonnet-5-5",
             blocks=None, details=None):
    body = json.dumps(payload) if text is None else text
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=body)]
    return SimpleNamespace(content=content, stop_reason=stop, usage=u or usage(), model=model,
                           stop_details=details)


class FakeClient:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self._result, self._exc = result, exc
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._result


def make(client, tmp_path, **kw):
    kw.setdefault("cache_dir", tmp_path / "cache")
    kw.setdefault("model", "claude-sonnet-5-5")
    return M.ClaudeForecaster(prompt_text=PROMPT, client=client, **kw)


def req():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


# -- api backend ---------------------------------------------------------------
def test_api_success_request_shape_and_record(tmp_path):
    client = FakeClient(response(u=usage(1000, 200, 5000, 300)))
    rec = make(client, tmp_path).forecast(PACKET)
    assert rec["status"] == "ok" and rec["forecast"] == GOOD
    assert rec["error"] is None and rec["cache_hit"] is False
    assert rec["model"] == "claude-sonnet-5-5" and rec["model_reported"] == "claude-sonnet-5-5"
    assert rec["backend"] == "api" and rec["latency_s"] >= 0
    assert rec["usage"] == {"input_tokens": 1000, "output_tokens": 200,
                            "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 300}
    assert json.loads(rec["raw_text"]) == GOOD
    (call,) = client.calls
    assert call["system"] == [{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user",
                                 "content": json.dumps(PACKET, separators=(",", ":"), sort_keys=True)}]
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "thinking" not in call and "temperature" not in call and "tool_choice" not in call
    assert call["timeout"] == 40.0


def test_api_schema_has_no_unsupported_constraints():
    text = json.dumps(M.api_schema())
    for banned in ("minimum", "maximum", "maxLength", '"type": ["string"'):
        assert banned not in text
    assert set(M.api_schema()["required"]) == set(FORECAST_SCHEMA["required"])


def test_cost_math_with_cache_pricing(tmp_path):
    # sonnet 5.5: $2 in, $10 out, $0.20 cache read, $2.50 cache write per MTok
    rec = make(FakeClient(response(u=usage(1_000_000, 100_000, 2_000_000, 400_000))), tmp_path
               ).forecast(PACKET)
    assert rec["cost_usd"] == pytest.approx(2.0 + 1.0 + 0.4 + 1.0)
    assert M.compute_cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 0,
                                                  "cache_read_input_tokens": 0,
                                                  "cache_creation_input_tokens": 0}) == pytest.approx(4.0)


def test_unknown_model_cost_is_none(tmp_path):
    rec = make(FakeClient(response(model="mystery")), tmp_path, model="mystery").forecast(PACKET)
    assert rec["status"] == "ok" and rec["cost_usd"] is None and rec["usage"] is not None


@pytest.mark.parametrize("payload,label", [
    ({**GOOD, "spy_p_up": 1.5}, "forecast_spy_p_up"),
    ({**GOOD, "action": "WAIT"}, "forecast_wait_symbol"),
    ({"spy_p_up": 0.5}, "forecast_fields"),
])
def test_schema_invalid_output(tmp_path, payload, label):
    rec = make(FakeClient(response(payload)), tmp_path).forecast(PACKET)
    assert rec["status"] == "invalid" and rec["forecast"] is None and rec["error"] == label


def test_non_json_and_empty_text_invalid(tmp_path):
    assert make(FakeClient(response(text="not json")), tmp_path).forecast(PACKET)["error"] == "json_parse"
    rec = make(FakeClient(response(blocks=[])), tmp_path).forecast({"x": 1})
    assert rec["status"] == "invalid" and rec["error"] == "empty_response"


def test_fenced_json_is_accepted(tmp_path):
    rec = make(FakeClient(response(text="```json\n" + json.dumps(GOOD) + "\n```")), tmp_path).forecast(PACKET)
    assert rec["status"] == "ok"


def test_thinking_blocks_are_ignored(tmp_path):
    blocks = [SimpleNamespace(type="thinking", thinking="hmm"),
              SimpleNamespace(type="text", text=json.dumps(GOOD))]
    assert make(FakeClient(response(blocks=blocks)), tmp_path).forecast(PACKET)["status"] == "ok"


def test_refusal_is_error_and_not_cached(tmp_path):
    details = SimpleNamespace(category="cyber")
    client = FakeClient(response(text="", stop="refusal", details=details))
    fc = make(client, tmp_path)
    rec = fc.forecast(PACKET)
    assert rec["status"] == "error" and rec["error"] == "refusal:cyber" and rec["forecast"] is None
    fc.forecast(PACKET)
    assert len(client.calls) == 2
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").glob("*.json"))


def test_max_tokens_truncation_is_invalid(tmp_path):
    rec = make(FakeClient(response(text='{"spy_p_up": 0.5', stop="max_tokens")), tmp_path).forecast(PACKET)
    assert rec["status"] == "invalid" and rec["error"] == "max_tokens"


def test_odd_stop_reason_with_valid_json_is_invalid(tmp_path):
    rec = make(FakeClient(response(stop="pause_turn")), tmp_path).forecast(PACKET)
    assert rec["status"] == "invalid" and rec["error"] == "stop_pause_turn"


def test_timeout_status(tmp_path):
    rec = make(FakeClient(exc=anthropic.APITimeoutError(request=req())), tmp_path).forecast(PACKET)
    assert rec["status"] == "timeout" and rec["error"] == "timeout" and rec["forecast"] is None


def test_http_error_redacts_and_never_raises(tmp_path):
    resp = httpx.Response(429, request=req())
    exc = anthropic.RateLimitError("slow down sk-ant-api03-SECRETSECRET", response=resp, body=None)
    rec = make(FakeClient(exc=exc), tmp_path).forecast(PACKET)
    assert rec["status"] == "error" and rec["error"] == "http_429"
    assert "SECRET" not in rec["raw_text"]
    conn = make(FakeClient(exc=anthropic.APIConnectionError(request=req())), tmp_path).forecast(PACKET)
    assert conn["error"] == "connection"


def test_unexpected_exception_is_a_status(tmp_path):
    rec = make(FakeClient(exc=RuntimeError("boom")), tmp_path).forecast(PACKET)
    assert rec["status"] == "error" and rec["error"] == "exception:RuntimeError"


def test_raw_text_truncated(tmp_path):
    rec = make(FakeClient(response(text="x" * 9000)), tmp_path).forecast(PACKET)
    assert len(rec["raw_text"]) == 4000


@pytest.mark.parametrize("model,budget,expected", [
    ("claude-sonnet-5-5", None, None),
    ("claude-sonnet-5-5", 0, {"type": "between_tools"}),
    ("claude-sonnet-5-5", 8000, {"type": "adaptive"}),
    ("claude-opus-5-5", 0, None),
    ("claude-opus-5-5", 3000, {"type": "adaptive"}),
    ("claude-opus-4-8", 0, {"type": "disabled"}),
    ("claude-haiku-4-5", 2000, {"type": "enabled", "budget_tokens": 2000}),
])
def test_thinking_mapping(model, budget, expected):
    assert M._thinking_params(model, budget, 4096) == expected


def test_thinking_param_sent_and_effort(tmp_path):
    client = FakeClient(response())
    make(client, tmp_path, thinking_budget=2000, effort="low", max_tokens=4096).forecast(PACKET)
    call = client.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "low"
    assert call["max_tokens"] == 4096


def test_legacy_budget_validated_against_max_tokens(tmp_path):
    with pytest.raises(ValueError):
        make(FakeClient(), tmp_path, model="claude-haiku-4-5", thinking_budget=4096, max_tokens=4096)
    with pytest.raises(ValueError):
        make(FakeClient(), tmp_path, model="claude-haiku-4-5", thinking_budget=500)


# -- credentials and base url --------------------------------------------------
def test_missing_api_key_is_status_not_raise(tmp_path):
    fc = M.ClaudeForecaster("claude-sonnet-5-5", PROMPT, cache_dir=tmp_path / "c",
                            env_file=tmp_path / "absent.env")
    rec = fc.forecast(PACKET)
    assert rec["status"] == "error" and rec["error"] == "no_api_key"


def test_api_key_from_env_file_and_official_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.invalid")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test-123456789\n")
    fc = M.ClaudeForecaster("claude-sonnet-5-5", PROMPT, cache_dir=None, env_file=env,
                            timeout_s=12.0, max_retries=1)
    client = fc._get_client()
    assert str(client.base_url).rstrip("/") == M.OFFICIAL_BASE_URL
    assert client.api_key == "sk-ant-test-123456789"
    assert client.timeout == 12.0 and client.max_retries == 1
    assert "ANTHROPIC_API_KEY" not in os.environ  # dotenv_values does not pollute the process


def test_explicit_api_key_wins_and_import_has_no_side_effects(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.invalid")
    fc = M.ClaudeForecaster("claude-sonnet-5-5", PROMPT, api_key="sk-explicit-0000000", cache_dir=None)
    assert fc._get_client().base_url != "https://proxy.invalid"


# -- cache ---------------------------------------------------------------------
def test_cache_hit_miss_and_zero_cost(tmp_path):
    client = FakeClient(response())
    fc = make(client, tmp_path)
    first = fc.forecast(PACKET)
    second = fc.forecast(PACKET)
    assert len(client.calls) == 1
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert second["cost_usd"] == 0.0 and second["original_cost_usd"] == first["cost_usd"]
    assert second["forecast"] == first["forecast"] and second["latency_s"] == first["latency_s"]
    fc.forecast({**PACKET, "checkpoint_et": "09:40"})
    assert len(client.calls) == 2


def test_cache_key_depends_on_settings(tmp_path):
    base = make(FakeClient(), tmp_path)
    key = base.cache_key(PACKET)
    assert key == make(FakeClient(), tmp_path).cache_key(PACKET)
    assert key != make(FakeClient(), tmp_path, model="claude-opus-5-5").cache_key(PACKET)
    assert key != make(FakeClient(), tmp_path, thinking_budget=0).cache_key(PACKET)
    assert key != make(FakeClient(), tmp_path, max_tokens=999).cache_key(PACKET)
    other = M.ClaudeForecaster("claude-sonnet-5-5", PROMPT + "!", client=FakeClient(),
                               cache_dir=tmp_path / "cache")
    assert key != other.cache_key(PACKET)
    # api and cli answers never share a cache entry
    cli = M.ClaudeForecaster("claude-sonnet-5-5", PROMPT, backend="cli", cache_dir=tmp_path / "cache")
    assert key != cli.cache_key(PACKET)


def test_invalid_cached_error_not_cached_and_atomic_write(tmp_path, monkeypatch):
    client = FakeClient(response({**GOOD, "qqq_p_up": -1}))
    fc = make(client, tmp_path)
    assert fc.forecast(PACKET)["status"] == "invalid"
    assert fc.forecast(PACKET)["cache_hit"] is True  # completed invalid is cached
    files = list((tmp_path / "cache").iterdir())
    assert [f.suffix for f in files] == [".json"]  # no stray temp files

    replaced = []
    real = os.replace
    monkeypatch.setattr(M.os, "replace", lambda a, b: (replaced.append((a, b)), real(a, b))[1])
    make(FakeClient(response()), tmp_path).forecast({"other": 1})
    (src, dst), = replaced
    assert str(src).endswith(".tmp") and str(dst).endswith(".json")

    err = make(FakeClient(exc=RuntimeError("x")), tmp_path)
    err.forecast({"err": 1})
    assert not (tmp_path / "cache" / f"{err.cache_key({'err': 1})}.json").exists()


def test_corrupt_cache_file_is_ignored(tmp_path):
    client = FakeClient(response())
    fc = make(client, tmp_path)
    path = tmp_path / "cache" / f"{fc.cache_key(PACKET)}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert fc.forecast(PACKET)["status"] == "ok" and len(client.calls) == 1


def test_cache_disabled_with_none(tmp_path):
    client = FakeClient(response())
    fc = make(client, tmp_path, cache_dir=None)
    fc.forecast(PACKET), fc.forecast(PACKET)
    assert len(client.calls) == 2


# -- cli backend ---------------------------------------------------------------
class FakeRunner:
    def __init__(self, stdout="", code=0, stderr="", exc=None):
        self.calls, self.out, self.code, self.err, self.exc = [], stdout, code, stderr, exc

    def __call__(self, argv, *, input_text, env, cwd, timeout_s):
        self.calls.append({"argv": argv, "input": input_text, "env": env, "cwd": cwd,
                           "timeout_s": timeout_s})
        if self.exc:
            raise self.exc
        return self.code, self.out, self.err


def cli_payload(result=GOOD, **extra):
    base = {"type": "result", "subtype": "success", "is_error": False,
            "result": json.dumps(result), "total_cost_usd": 0.0123,
            "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
                      "cache_creation_input_tokens": 40},
            "modelUsage": {"claude-sonnet-5-5": {}}}
    base.update(extra)
    return json.dumps(base)


def make_cli(runner, tmp_path, **kw):
    kw.setdefault("cache_dir", tmp_path / "cache")
    return M.ClaudeForecaster("sonnet", PROMPT, backend="cli", runner=runner, **kw)


def test_cli_success_reports_cost_and_usage(tmp_path):
    runner = FakeRunner(cli_payload())
    rec = make_cli(runner, tmp_path).forecast(PACKET)
    assert rec["status"] == "ok" and rec["forecast"] == GOOD and rec["backend"] == "cli"
    assert rec["cost_usd"] == 0.0123 and rec["model_reported"] == "claude-sonnet-5-5"
    assert rec["usage"] == {"input_tokens": 10, "output_tokens": 20,
                            "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}
    call = runner.calls[0]
    assert call["input"] == json.dumps(PACKET, separators=(",", ":"), sort_keys=True)
    assert call["timeout_s"] == 40.0
    argv = call["argv"]
    assert argv[1] == "-p" and argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--system-prompt") + 1] == PROMPT
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert json.loads(argv[argv.index("--json-schema") + 1])["additionalProperties"] is False


def test_cli_prefers_structured_output_field(tmp_path):
    out = cli_payload(result="prose", structured_output=GOOD)
    assert make_cli(FakeRunner(out), tmp_path).forecast(PACKET)["status"] == "ok"


def test_cli_env_isolation_and_temp_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-000000000")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("HOME", "/home/someone")
    runner = FakeRunner(cli_payload())
    make_cli(runner, tmp_path).forecast(PACKET)
    env = runner.calls[0]["env"]
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        assert name not in env
    assert env["HOME"] == "/home/someone"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-leak-000000000"  # parent untouched
    cwd = runner.calls[0]["cwd"]
    assert "opening_lab_cli_" in cwd and not os.path.exists(cwd)


def test_cli_invalid_output_and_errors(tmp_path):
    bad = make_cli(FakeRunner(cli_payload({**GOOD, "action": "BUY"})), tmp_path).forecast(PACKET)
    assert bad["status"] == "invalid" and bad["error"] == "forecast_action"
    flagged = make_cli(FakeRunner(cli_payload(is_error=True, subtype="error_max_turns", result="no")),
                       tmp_path).forecast({"a": 1})
    assert flagged["status"] == "error" and flagged["error"] == "cli_error_max_turns"
    garbage = make_cli(FakeRunner("not json", code=0), tmp_path).forecast({"b": 1})
    assert garbage["error"] == "cli_bad_output"
    crashed = make_cli(FakeRunner("", code=2, stderr="login required sk-ant-zzzzzzzzzz"),
                       tmp_path).forecast({"c": 1})
    assert crashed["error"] == "cli_exit_2" and "zzzz" not in crashed["raw_text"]


def test_cli_timeout_and_missing_binary(tmp_path):
    timeout = make_cli(FakeRunner(exc=subprocess.TimeoutExpired("claude", 40)), tmp_path).forecast(PACKET)
    assert timeout["status"] == "timeout"
    missing = make_cli(FakeRunner(exc=FileNotFoundError()), tmp_path).forecast({"m": 1})
    assert missing["status"] == "error" and missing["error"] == "cli_not_found"


def test_cli_errors_not_cached_but_ok_is_(tmp_path):
    runner = FakeRunner(cli_payload())
    fc = make_cli(runner, tmp_path)
    fc.forecast(PACKET)
    assert fc.forecast(PACKET)["cache_hit"] is True and len(runner.calls) == 1


def test_default_runner_kills_on_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        M.default_runner(["sleep", "5"], input_text="", env=dict(os.environ), cwd="/", timeout_s=0.2)


# -- fakes ---------------------------------------------------------------------
def test_fake_forecaster_is_deterministic_and_valid():
    fake = M.FakeForecaster()
    a, b = fake.forecast(PACKET), fake.forecast(PACKET)
    assert a["status"] == "ok" and a["forecast"] == b["forecast"]
    assert a["cost_usd"] == 0.0 and a["backend"] == "fake" and a["cache_hit"] is False
    seen = {fake.forecast({"i": i})["forecast"]["action"] for i in range(40)}
    assert seen == {"WAIT", "LONG", "SHORT"}
    assert M.FakeForecaster(seed=1).forecast(PACKET)["forecast"] != a["forecast"]


def test_forecast_from_function():
    ok = M.forecast_from_function(lambda p: GOOD, name="const").forecast(PACKET)
    assert ok["status"] == "ok" and ok["model"] == "const"
    assert M.forecast_from_function(lambda p: {"bad": 1}).forecast(PACKET)["status"] == "invalid"
    def boom(p):
        raise KeyError("k")
    assert M.forecast_from_function(boom).forecast(PACKET)["status"] == "error"


def test_default_timeout_is_inside_the_live_deadline():
    import inspect

    from research.opening_lab.contract import RESPONSE_DEADLINE_SECONDS
    default = inspect.signature(M.ClaudeForecaster.__init__).parameters["timeout_s"].default
    assert default < RESPONSE_DEADLINE_SECONDS
