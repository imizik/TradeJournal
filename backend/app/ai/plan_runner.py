"""Ask Claude through Claude Code on the owner's Claude plan, never API credits.

One call is ``claude -p`` with no tools, a system prompt, the message on stdin
and a JSON schema for the answer, as ``scripts/factory_week.sh`` does for the
strategy factory. The plan token is ``CLAUDE_CODE_OAUTH_TOKEN`` (from
``claude setup-token``). It goes to the child process in its environment, never
as an argument, and every setting that would bill an API key or another
provider instead, or send the token elsewhere, is removed for the call. Before
the first call in a process, Claude Code itself must report the plan token as
its sign-in, or nothing is asked.

Settings (all optional except the token):

- ``TJ_CLAUDE_BIN``: the Claude Code binary (default: the release's
  ``bin/claude``, then ``claude`` on PATH, then ``~/.local/node/bin/claude``).
- ``TJ_CLAUDE_CONFIG_DIR``: Claude Code's own state directory, which must be
  writable (production: ``/var/lib/tradejournal/claude``).
- ``TJ_PLAN_REVIEW_MODEL`` (``sonnet``) and ``TJ_PLAN_REVIEW_TIMEOUT``
  (300 seconds) for each call.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 300
# The plan token and nothing that outranks it: an auth token, an API key or a
# cloud provider would bill instead, and another base URL or socket would
# receive it.
_OUTRANKING = (
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD", "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
)
_RELEASE_BIN = Path(__file__).resolve().parents[3] / "bin" / "claude"
_checked: set[tuple[str, str]] = set()
_check_lock = threading.Lock()


class PlanUnavailable(RuntimeError):
    """The plan cannot be used: no binary, no token, or a sign-in other than the plan."""


class PlanCallFailed(RuntimeError):
    """Claude was asked and gave no usable answer (timeout, error, or no structured output)."""


@dataclass(frozen=True)
class PlanAnswer:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    api_equivalent_usd: float
    seconds: float

    @property
    def author(self) -> str:
        return f"{self.model} through claude -p on the Claude plan"


def claude_binary() -> str:
    configured = os.environ.get("TJ_CLAUDE_BIN")
    if configured:
        return configured
    if _RELEASE_BIN.is_file():
        return str(_RELEASE_BIN)
    return shutil.which("claude") or str(Path.home() / ".local/node/bin/claude")


def plan_configured() -> bool:
    return bool(os.environ.get(TOKEN_ENV)) and Path(claude_binary()).is_file()


def _child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _OUTRANKING}
    config = os.environ.get("TJ_CLAUDE_CONFIG_DIR")
    if config:
        Path(config).mkdir(parents=True, exist_ok=True, mode=0o700)
        env["CLAUDE_CONFIG_DIR"] = config
    # No update checks, telemetry or error reports from a scheduled run.
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def _preflight(binary: str, env: dict[str, str]) -> None:
    """Claude Code names the sign-in it would use; anything but the plan token stops here."""
    key = (binary, env.get(TOKEN_ENV, ""))
    with _check_lock:
        if key in _checked:
            return
        try:
            result = subprocess.run([binary, "auth", "status", "--json"], env=env, capture_output=True, text=True, timeout=60)
            status = json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise PlanUnavailable(f"Claude Code could not report its sign-in ({type(exc).__name__}).") from exc
        if not isinstance(status, dict):
            status = {}
        method, provider, api_key = status.get("authMethod"), status.get("apiProvider", "firstParty"), status.get("apiKeySource")
        if method != "oauth_token" or provider != "firstParty" or api_key:
            raise PlanUnavailable(f"Claude Code would not sign in with the plan token ({method}/{provider}{' with an API key' if api_key else ''}).")
        _checked.add(key)


def ask(system: str, message: str, schema: dict, *, model: str | None = None, timeout: float | None = None) -> PlanAnswer:
    """One question, one structured answer, on the plan. Raises PlanUnavailable or PlanCallFailed."""
    binary = claude_binary()
    if not Path(binary).is_file():
        raise PlanUnavailable(f"Claude Code is not installed at {binary} (set TJ_CLAUDE_BIN).")
    if not os.environ.get(TOKEN_ENV):
        raise PlanUnavailable(f"No {TOKEN_ENV}: run `claude setup-token` and add it to the review settings.")
    env = _child_env()
    _preflight(binary, env)
    model = model or os.environ.get("TJ_PLAN_REVIEW_MODEL") or DEFAULT_MODEL
    limit = timeout or float(os.environ.get("TJ_PLAN_REVIEW_TIMEOUT") or DEFAULT_TIMEOUT)
    command = [binary, "-p", "--restricted", "--strict-mcp-config", "--tools", "",
               "--model", model, "--system-prompt", system, "--json-schema", json.dumps(schema),
               "--permission-mode", "dontAsk", "--permission-prompts", "none",
               "--no-session-persistence", "--output-format", "json"]
    try:
        result = subprocess.run(command, input=message, env=env, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as exc:
        raise PlanCallFailed(f"claude -p did not answer within {int(limit)} s.") from exc
    except OSError as exc:
        raise PlanCallFailed(f"claude -p could not start ({exc.strerror or type(exc).__name__}).") from exc
    try:
        run = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise PlanCallFailed(f"claude -p exited {result.returncode} without JSON: {(result.stderr or '').strip()[-300:]}") from exc
    answer = run.get("structured_output") if isinstance(run, dict) else None
    if result.returncode != 0 or not isinstance(run, dict) or run.get("is_error") or run.get("subtype") != "success" or not isinstance(answer, dict):
        detail = run.get("subtype") if isinstance(run, dict) else None
        text = str(run.get("result") or "")[:300] if isinstance(run, dict) else ""
        raise PlanCallFailed(f"claude -p gave no answer ({detail or f'exit {result.returncode}'}): {text or (result.stderr or '').strip()[-300:]}")
    usage = run.get("modelUsage") or {}
    used = max(usage, key=lambda name: usage[name].get("outputTokens", 0)) if usage else model
    return PlanAnswer(
        data=answer,
        model=used,
        input_tokens=sum(int(item.get("inputTokens", 0)) + int(item.get("cacheReadInputTokens", 0)) + int(item.get("cacheCreationInputTokens", 0)) for item in usage.values()),
        output_tokens=sum(int(item.get("outputTokens", 0)) for item in usage.values()),
        api_equivalent_usd=round(float(run.get("total_cost_usd") or 0), 4),
        seconds=round(float(run.get("duration_ms") or 0) / 1000, 1),
    )
