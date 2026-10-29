"""Claude forecaster for the opening lab: one packet in, one validated forecast out.

Two backends share one record shape (see ``ClaudeForecaster.forecast``):

* ``api``  - the official ``anthropic`` SDK, Messages API. Structured outputs
  (``output_config.format`` with a JSON schema) make the reply schema-shaped;
  the system prompt carries a prompt-caching breakpoint; the client is built
  with the official base URL so a stray ``ANTHROPIC_BASE_URL`` cannot reroute it.
* ``cli``  - ``claude -p`` on the owner's Claude plan (no API billing): no tools,
  no MCP, no session persistence, API-key/base-url env stripped.

``forecast`` never raises for provider or parse failures; it returns a record
with ``status`` of ``ok`` / ``invalid`` / ``error`` / ``timeout``. Completed
records (``ok`` and ``invalid``) are cached on disk, keyed by everything that
shapes the answer; errors and timeouts are never cached.

Nothing here makes a model call at import time or in ``__init__``.
"""

import copy
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .contract import FORECAST_SCHEMA, validate_forecast

OFFICIAL_BASE_URL = "https://api.anthropic.com"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "model"
DEFAULT_ENV_FILES = (
    Path("/Users/user/TradeJournal/backend/.env"),
    Path(__file__).resolve().parents[2] / "backend" / ".env",
)
CLAUDE_BIN_FALLBACK = "/Users/user/.local/node/bin/claude"
RAW_TEXT_LIMIT = 4000
CACHE_KEY_VERSION = 1

# USD per million tokens: (input, output, cache_read). Cache write (5-minute TTL)
# is 1.25x input. Source: claude-api skill "Current Models" table (cached
# 2026-10-06) and shared/prompt-caching.md. Cache-read values marked (a) are the
# standard 0.1x rule, not individually quoted by the skill. Haiku 5.5 is the
# <=100K-token-prompt tier ($0.50/$2.50 beyond; packets are far below that).
PRICING = {
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),  # (a)
    "claude-opus-4-8": (5.00, 25.00, 0.50),  # (a)
    "claude-opus-4-7": (5.00, 25.00, 0.50),  # (a)
    "claude-opus-4-6": (5.00, 25.00, 0.50),  # (a)
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),  # (a)
    "claude-haiku-5-5": (0.10, 0.50, 0.01),  # (a)
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
CACHE_WRITE_MULTIPLIER = 1.25

# Models that reject ``budget_tokens`` (adaptive thinking only).
_ADAPTIVE_PREFIXES = (
    "claude-fable-", "claude-mythos-", "claude-opus-5", "claude-opus-4-8",
    "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-haiku-5",
)
# Models where thinking cannot be switched off with {"type": "disabled"}.
_NO_DISABLE_PREFIXES = ("claude-fable-", "claude-mythos-", "claude-opus-5-5")

_UNSET = object()
_SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def api_schema():
    """FORECAST_SCHEMA in the subset structured outputs accept.

    Structured outputs reject numeric/string bounds and (to be safe) type
    arrays, so bounds are dropped and re-checked client-side by
    ``validate_forecast``; the 400-character limit moves into a description.
    """
    schema = copy.deepcopy(FORECAST_SCHEMA)
    props = schema["properties"]
    for key in ("spy_p_up", "qqq_p_up"):
        props[key] = {"type": "number", "description": "Probability between 0 and 1."}
    props["symbol"] = {
        "anyOf": [{"type": "string", "enum": ["SPY", "QQQ"]}, {"type": "null"}],
        "description": "SPY or QQQ for LONG/SHORT; null when action is WAIT.",
    }
    props["reason"] = {"type": "string", "description": "At most 400 characters."}
    return schema


def prompt_sha(prompt_text):
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def compute_cost_usd(model, usage):
    """USD cost from a usage dict, or None for an unknown model / unknown usage."""
    prices = PRICING.get(model)
    if prices is None or not usage:
        return None
    in_p, out_p, read_p = prices
    total = (
        usage["input_tokens"] * in_p
        + usage["output_tokens"] * out_p
        + usage["cache_read_input_tokens"] * read_p
        + usage["cache_creation_input_tokens"] * in_p * CACHE_WRITE_MULTIPLIER
    )
    return total / 1_000_000


def _redact(text, limit=300):
    return _SECRET_RE.sub("[redacted]", str(text))[:limit]


def _usage_dict(usage):
    """Normalise SDK usage (object) or CLI usage (dict) to four ints, or None."""
    if usage is None:
        return None

    def get(name):
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        return int(value or 0)

    return {
        "input_tokens": get("input_tokens"),
        "output_tokens": get("output_tokens"),
        "cache_read_input_tokens": get("cache_read_input_tokens"),
        "cache_creation_input_tokens": get("cache_creation_input_tokens"),
    }


def _canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _record(status, *, forecast=None, error=None, latency_s=0.0, usage=None, cost_usd=None,
            model=None, model_reported=None, backend=None, cache_hit=False, raw_text=""):
    return {
        "status": status,
        "forecast": forecast,
        "error": error,
        "latency_s": round(float(latency_s), 4),
        "usage": usage,
        "cost_usd": cost_usd,
        "model": model,
        "model_reported": model_reported,
        "backend": backend,
        "cache_hit": cache_hit,
        "raw_text": (raw_text or "")[:RAW_TEXT_LIMIT],
    }


def parse_forecast_text(text, validate=validate_forecast):
    """Turn model text into (status, forecast, error). Tolerates code fences."""
    body = (text or "").strip()
    if not body:
        return "invalid", None, "empty_response"
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", body).strip()
    try:
        value = json.loads(body)
    except ValueError:
        start, end = body.find("{"), body.rfind("}")
        try:
            value = json.loads(body[start:end + 1]) if 0 <= start < end else None
        except ValueError:
            value = None
        if value is None:
            return "invalid", None, "json_parse"
    try:
        return "ok", validate(value), None
    except ValueError as exc:
        return "invalid", None, str(exc)[:80]


def _thinking_params(model, budget, max_tokens):
    """Messages-API ``thinking`` for the requested budget, or None to omit it.

    None -> omit (model default). 0 -> off where the model allows it.
    >0 -> ``enabled`` + ``budget_tokens`` on legacy models; on adaptive-only
    models (``budget_tokens`` is a 400 there) -> ``{"type": "adaptive"}``, with
    depth steered by ``effort``.
    """
    if budget is None:
        return None
    adaptive_only = model.startswith(_ADAPTIVE_PREFIXES)
    if budget == 0:
        if model.startswith(_NO_DISABLE_PREFIXES):
            return None
        if model.startswith("claude-sonnet-5-5"):
            return {"type": "between_tools"}
        return {"type": "disabled"}
    if adaptive_only:
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": int(budget)}


def default_runner(argv, *, input_text, env, cwd, timeout_s):
    """Run ``argv``; return (returncode, stdout, stderr). Kills the process group
    and raises ``subprocess.TimeoutExpired`` at the timeout."""
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, cwd=cwd, text=True, start_new_session=True,
    )
    try:
        out, err = proc.communicate(input_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        raise
    return proc.returncode, out, err


def cli_env(environ=None):
    """Environment for ``claude -p``: plan login only (no API key / proxy / token)."""
    drop = {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"}
    return {k: v for k, v in (os.environ if environ is None else environ).items() if k not in drop}


class ClaudeForecaster:
    """Forecast a packet with Claude. See module docstring for the record shape."""

    def __init__(self, model, prompt_text, *, backend="api", thinking_budget=None,
                 max_tokens=4096, timeout_s=40.0, max_retries=0, cache_dir=_UNSET,
                 api_key=None, client=None, runner=None, effort=None, env_file=None,
                 claude_bin=None, schema=None, validate=None):
        """``schema`` (structured-output schema) and ``validate`` replace the
        forecast shape, e.g. for trade decisions; default: the forecast contract."""
        if backend not in ("api", "cli"):
            raise ValueError("backend must be 'api' or 'cli'")
        if (backend == "api" and thinking_budget and not model.startswith(_ADAPTIVE_PREFIXES)
                and not 1024 <= thinking_budget < max_tokens):
            raise ValueError("thinking_budget must be >= 1024 and < max_tokens")
        self.model = model
        self.prompt_text = prompt_text
        self.backend = backend
        self.thinking_budget = thinking_budget
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.cache_dir = DEFAULT_CACHE_DIR if cache_dir is _UNSET else (
            Path(cache_dir) if cache_dir is not None else None)
        self.effort = effort
        self._api_key = api_key
        self._client = client
        self._runner = runner or default_runner
        self._env_file = env_file
        self._claude_bin = claude_bin
        self._prompt_sha = prompt_sha(prompt_text)
        self.schema = schema
        self._validate = validate or validate_forecast

    # -- cache ---------------------------------------------------------------
    def cache_key(self, packet):
        return hashlib.sha256(_canonical({
            "v": CACHE_KEY_VERSION,
            "model": self.model,
            # api and cli answers are separate observations (latency, harness).
            "backend": self.backend,
            "thinking_budget": self.thinking_budget,
            "effort": self.effort,
            "max_tokens": self.max_tokens,
            "prompt_sha": self._prompt_sha,
            "schema": hashlib.sha256(_canonical(self.schema or FORECAST_SCHEMA).encode()).hexdigest(),
            "packet": packet,
        }).encode("utf-8")).hexdigest()

    def _cache_path(self, key):
        return self.cache_dir / f"{key}.json" if self.cache_dir else None

    def _cache_read(self, key):
        path = self._cache_path(key)
        if path is None or not path.is_file():
            return None
        try:
            rec = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(rec, dict) or rec.get("status") not in ("ok", "invalid"):
            return None
        rec["original_cost_usd"] = rec.get("cost_usd")
        rec["cost_usd"] = 0.0
        rec["cache_hit"] = True
        return rec

    def _cache_write(self, key, rec):
        path = self._cache_path(key)
        if path is None:
            return
        tmp_name = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp",
                                             delete=False, encoding="utf-8") as tmp:
                tmp_name = tmp.name
                json.dump(rec, tmp, sort_keys=True)
            os.replace(tmp_name, path)
        except OSError:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    # -- public --------------------------------------------------------------
    def forecast(self, packet):
        key = self.cache_key(packet)
        hit = self._cache_read(key)
        if hit is not None:
            return hit
        start = time.monotonic()
        try:
            rec = self._call_cli(packet) if self.backend == "cli" else self._call_api(packet)
        except Exception as exc:  # last resort: callers rely on never raising
            rec = _record("error", error=f"exception:{type(exc).__name__}", raw_text=_redact(exc))
        rec["latency_s"] = round(time.monotonic() - start, 4)
        rec["model"] = self.model
        rec["backend"] = self.backend
        if rec["status"] in ("ok", "invalid"):
            self._cache_write(key, rec)
        return rec

    # -- api backend ---------------------------------------------------------
    def _resolve_api_key(self):
        if self._api_key:
            return self._api_key
        from dotenv import dotenv_values  # at call time, never at import

        files = [Path(self._env_file)] if self._env_file else list(DEFAULT_ENV_FILES)
        for path in files:
            try:
                value = dotenv_values(path).get("ANTHROPIC_API_KEY")
            except OSError:
                value = None
            if value:
                return value
        return None

    def _get_client(self):
        if self._client is None:
            key = self._resolve_api_key()
            if not key:
                return None
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=key, base_url=OFFICIAL_BASE_URL,
                timeout=self.timeout_s, max_retries=self.max_retries,
            )
        return self._client

    def _api_kwargs(self, packet):
        output_config = {"format": {"type": "json_schema", "schema": self.schema or api_schema()}}
        if self.effort:
            output_config["effort"] = self.effort
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": self.prompt_text,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": _canonical_packet(packet)}],
            "output_config": output_config,
            "timeout": self.timeout_s,
        }
        thinking = _thinking_params(self.model, self.thinking_budget, self.max_tokens)
        if thinking is not None:
            kwargs["thinking"] = thinking
        return kwargs

    def _call_api(self, packet):
        import anthropic

        client = self._get_client()
        if client is None:
            return _record("error", error="no_api_key")
        try:
            resp = client.messages.create(**self._api_kwargs(packet))
        except anthropic.APITimeoutError:
            return _record("timeout", error="timeout")
        except anthropic.APIStatusError as exc:
            return _record("error", error=f"http_{exc.status_code}", raw_text=_redact(exc))
        except anthropic.APIConnectionError as exc:
            return _record("error", error="connection", raw_text=_redact(exc))
        usage = _usage_dict(getattr(resp, "usage", None))
        reported = getattr(resp, "model", None)
        common = dict(usage=usage, cost_usd=compute_cost_usd(self.model, usage),
                      model_reported=reported if isinstance(reported, str) else None)
        text = "".join(b.text for b in (getattr(resp, "content", None) or [])
                       if getattr(b, "type", None) == "text" and isinstance(getattr(b, "text", None), str))
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None)
            label = f"refusal:{category}" if isinstance(category, str) else "refusal"
            return _record("error", error=label, raw_text=text, **common)
        status, forecast, error = parse_forecast_text(text, self._validate)
        if status == "invalid" and stop == "max_tokens":
            error = "max_tokens"
        elif status == "ok" and stop not in (None, "end_turn", "stop_sequence"):
            status, forecast, error = "invalid", None, f"stop_{stop}"
        return _record(status, forecast=forecast, error=error, raw_text=text, **common)

    # -- cli backend ---------------------------------------------------------
    def _cli_argv(self):
        binary = self._claude_bin or shutil.which("claude") or CLAUDE_BIN_FALLBACK
        argv = [
            binary, "-p", "--output-format", "json",
            "--json-schema", json.dumps(self.schema or api_schema(), separators=(",", ":")),
            "--system-prompt", self.prompt_text,
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence", "--safe-mode", "--disable-slash-commands",
        ]
        if self.effort:
            argv += ["--effort", self.effort]
        return argv

    def _call_cli(self, packet):
        with tempfile.TemporaryDirectory(prefix="opening_lab_cli_") as cwd:
            try:
                code, out, err = self._runner(
                    self._cli_argv(), input_text=_canonical_packet(packet),
                    env=cli_env(), cwd=cwd, timeout_s=self.timeout_s)
            except subprocess.TimeoutExpired:
                return _record("timeout", error="timeout")
            except FileNotFoundError:
                return _record("error", error="cli_not_found")
        payload = _cli_result(out)
        if payload is None:
            label = "cli_bad_output" if code == 0 else f"cli_exit_{code}"
            return _record("error", error=label, raw_text=_redact(err or out))
        usage = _usage_dict(payload.get("usage"))
        cost = payload.get("total_cost_usd")
        model_usage = payload.get("modelUsage")
        reported = next(iter(model_usage), None) if isinstance(model_usage, dict) and model_usage else None
        common = dict(usage=usage, model_reported=reported,
                      cost_usd=float(cost) if isinstance(cost, (int, float)) else None)
        if payload.get("is_error") or code != 0:
            return _record("error", error=f"cli_{payload.get('subtype') or 'error'}"[:60],
                           raw_text=_redact(payload.get("result") or err), **common)
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            text = json.dumps(structured)
        else:
            text = payload.get("result") if isinstance(payload.get("result"), str) else ""
        status, forecast, error = parse_forecast_text(text, self._validate)
        return _record(status, forecast=forecast, error=error, raw_text=text, **common)


def _canonical_packet(packet):
    return json.dumps(packet, separators=(",", ":"), sort_keys=True)


def _cli_result(stdout):
    """The result object from ``claude -p --output-format json`` stdout, or None."""
    try:
        value = json.loads(stdout or "")
    except ValueError:
        return None
    if isinstance(value, list):  # verbose/stream-style arrays: take the result event
        value = next((v for v in reversed(value)
                      if isinstance(v, dict) and v.get("type") == "result"), None)
    return value if isinstance(value, dict) else None


# -- fakes for tests and dry runs ---------------------------------------------
class FunctionForecaster:
    """Wrap ``fn(packet) -> forecast dict`` in the forecaster interface (no model)."""

    def __init__(self, fn, *, name="function", backend="fake"):
        self._fn = fn
        self.model = name
        self.backend = backend

    def forecast(self, packet):
        start = time.monotonic()
        try:
            status, forecast, error = "ok", validate_forecast(self._fn(packet)), None
        except ValueError as exc:
            status, forecast, error = "invalid", None, str(exc)[:80]
        except Exception as exc:
            status, forecast, error = "error", None, f"exception:{type(exc).__name__}"
        return _record(status, forecast=forecast, error=error,
                       latency_s=time.monotonic() - start, cost_usd=0.0,
                       model=self.model, model_reported=self.model, backend=self.backend,
                       raw_text=json.dumps(forecast) if forecast else "")


def forecast_from_function(fn, *, name="function"):
    return FunctionForecaster(fn, name=name)


def _hash_forecast(packet, seed=0):
    digest = hashlib.sha256(f"{seed}:{_canonical_packet(packet)}".encode()).digest()
    spy_p = 0.40 + 0.20 * digest[0] / 255
    qqq_p = 0.40 + 0.20 * digest[1] / 255
    pick = digest[2] % 3
    if pick == 0:
        return {"spy_p_up": spy_p, "qqq_p_up": qqq_p, "action": "WAIT", "symbol": None,
                "reason": "fake: no edge"}
    symbol = "SPY" if digest[3] % 2 == 0 else "QQQ"
    action = "LONG" if (spy_p if symbol == "SPY" else qqq_p) >= 0.5 else "SHORT"
    return {"spy_p_up": spy_p, "qqq_p_up": qqq_p, "action": action, "symbol": symbol,
            "reason": f"fake: {action.lower()} {symbol}"}


class FakeForecaster(FunctionForecaster):
    """Deterministic forecast derived from a hash of the packet (same packet, same answer)."""

    def __init__(self, *, seed=0, name="fake"):
        super().__init__(lambda packet: _hash_forecast(packet, seed), name=name)
