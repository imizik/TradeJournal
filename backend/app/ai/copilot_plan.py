"""Copilot Lab on the owner's Claude plan through the Claude Agent SDK (docs/copilot-lab.md).

``COPILOT_BACKEND=plan`` runs the same read-only research turn as the
``anthropic`` backend, but through Claude Code (``claude-agent-sdk``) signed in
with the plan token from ``claude setup-token``, so it never spends API
credits. The SDK runs its own model/tool loop, so this replaces ``run_turn`` as
a whole and yields the same UI events (text, tool, error, done).

Local development and testing only: Anthropic directs products built on the
Agent SDK to API-key authentication, and plan (OAuth) credentials are meant for
ordinary individual use (docs/copilot-lab.md). So, like replay, it refuses to
run unless the backend's database is local.

Isolation, beyond what ``plan_runner`` already does for ``claude -p``:

- No built-in tools (``--tools ""``, ``--restricted``), no slash commands, no
  ``@path`` expansion (``verbatim_prompts``), no settings files, no other MCP
  servers, no session persistence. Only the five lab tools, served in-process
  as SDK MCP tools and auto-approved; ``dontAsk`` denies anything else.
- The SDK merges ``env`` over the backend's whole environment, so every
  inherited variable other than ``plan_runner``'s short allowlist is blanked:
  no API key, auth token, base URL, cloud provider, database URL or provider
  key reaches Claude Code. Claude Code then reports its sign-in under that
  exact environment before the first turn; anything but the plan token stops.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from app.ai import copilot, copilot_tools, plan_runner

log = logging.getLogger(__name__)

SERVER = "copilot"
ALLOWED = [f"mcp__{SERVER}__{t['name']}" for t in copilot_tools.TOOLS]
# Set by the SDK transport itself; blanking it would stop the SDK from setting it.
_SDK_OWNED = ("CLAUDE_CODE_SDK_READS_SESSION_STATE", "CLAUDE_AGENT_SDK_VERSION")
_DONE = object()


def sdk_available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def configured() -> bool:
    return plan_runner.plan_configured() and sdk_available()


def child_env() -> dict[str, str]:
    """The ``env`` for ClaudeAgentOptions: plan_runner's allowlist, with every other inherited variable blanked."""
    env = plan_runner._child_env()
    if "CLAUDE_CONFIG_DIR" not in env:
        # Never the owner's own ~/.claude: a private state directory for the lab only.
        config = Path(tempfile.gettempdir()) / "tradejournal-copilot-claude"
        config.mkdir(parents=True, exist_ok=True, mode=0o700)
        env["CLAUDE_CONFIG_DIR"] = str(config)
    blanks = {key: "" for key in os.environ if key not in env and key not in _SDK_OWNED and key != "CLAUDECODE"}
    return {**blanks, **env, "CLAUDE_CODE_ENTRYPOINT": "sdk-py"}


def effective_env(options_env: dict[str, str]) -> dict[str, str]:
    """What the SDK transport will actually hand Claude Code (its merge rule), for the preflight."""
    inherited = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    return {**inherited, "CLAUDE_CODE_ENTRYPOINT": "sdk-py", **options_env}


def preflight(env: dict[str, str]) -> str:
    """The Claude Code binary, once it has reported the plan token as its sign-in. Raises CopilotError."""
    if not sdk_available():
        raise copilot.CopilotError("plan_not_installed", "claude-agent-sdk is not installed: pip install -e '.[copilot-plan]' in backend/.")
    if not env.get(plan_runner.TOKEN_ENV):
        raise copilot.CopilotError("plan_not_configured", f"No {plan_runner.TOKEN_ENV}: run `claude setup-token` and add the token to the private backend environment.")
    binary = plan_runner.claude_binary()
    if not Path(binary).is_file():
        raise copilot.CopilotError("plan_not_installed", f"Claude Code is not installed at {binary} (set TJ_CLAUDE_BIN).")
    try:
        plan_runner._preflight(binary, effective_env(env))
    except plan_runner.PlanUnavailable as exc:
        raise copilot.CopilotError("plan_auth_source", f"{exc} Run `claude setup-token` and set {plan_runner.TOKEN_ENV}; API keys are never used.")
    return binary


def prompt_for(history: list[dict], symbol: str | None, now: datetime, replay: bool = False, owner_block: str = "") -> str:
    """One prompt: Claude Code takes a single user message, so earlier text-only turns are quoted into it. The owner
    context block (``copilot.owner_context``) follows the context line, before the quoted conversation."""
    *earlier, last = history
    text = copilot.context_line(symbol, now, replay) + owner_block
    if earlier:
        text += ("Conversation so far (text only; re-check evidence with the tools rather than trusting earlier numbers):\n\n"
                 + "\n\n".join(f"{'Trader' if m['role'] == 'user' else 'Copilot'}: {m['content']}" for m in earlier)
                 + "\n\nThe trader's new message:\n\n")
    return text + last["content"]


def _usage(raw: dict | None) -> dict:
    raw = raw or {}
    return {k: int(raw.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}


def _result_error(result, assistant_error: str | None, cfg: copilot.Settings) -> dict | None:
    status = getattr(result, "api_error_status", None)
    if result.subtype == "error_max_turns":
        return {"code": "rounds", "message": f"Stopped: this turn used its {cfg.max_rounds} model rounds."}
    if result.subtype == "error_max_budget_usd":
        return {"code": "budget", "message": f"Stopped: this turn reached its ${cfg.turn_budget_usd:.2f} API-equivalent cap (no API credits are spent on the plan)."}
    if not result.is_error:
        if result.stop_reason == "refusal":
            return {"code": "refusal", "message": "The model declined to answer this request."}
        if result.stop_reason == "max_tokens":
            return {"code": "truncated", "message": "The answer hit its length limit."}
        return None
    if assistant_error == "authentication_failed" or status in (401, 403):
        return {"code": "plan_auth", "message": "Claude rejected the plan token. Run `claude setup-token` again and update CLAUDE_CODE_OAUTH_TOKEN."}
    if assistant_error == "rate_limit" or status == 429:
        return {"code": "plan_limit", "message": "The Claude plan's usage limit was reached. Try again later."}
    if assistant_error == "billing_error":
        return {"code": "plan_billing", "message": "Claude reported a billing problem for the plan sign-in. This lab never falls back to API credits."}
    return {"code": "plan_unavailable", "message": f"Claude Code could not finish this turn ({result.subtype}{f', HTTP {status}' if status else ''})."}


class PlanAdapter:
    """One turn through the Agent SDK on the Claude plan. ``sdk`` is injectable so tests never start Claude Code."""
    model = None

    def __init__(self, cfg: copilot.Settings, sdk=None, env: dict[str, str] | None = None):
        from app.environment import describe
        if not describe().is_local:
            raise copilot.CopilotError("plan_local_only", "The Claude plan backend is for local development and testing only "
                                       "(the database is not local). Use COPILOT_BACKEND=anthropic with an API key elsewhere.")
        self.env = child_env() if env is None else env
        # Configuration first, so a missing SDK, token or binary is a 503 with its fix, never an ImportError (500).
        self.binary = preflight(self.env)
        if sdk is None:
            import claude_agent_sdk as sdk
        self.cfg, self.sdk = cfg, sdk

    def options(self, server) -> Any:
        cfg = self.cfg
        return self.sdk.ClaudeAgentOptions(
            system_prompt=copilot.SYSTEM_PROMPT, model=cfg.model, effort=cfg.effort, thinking={"type": "adaptive"},
            tools=[], allowed_tools=list(ALLOWED), mcp_servers={SERVER: server}, strict_mcp_config=True,
            permission_mode="dontAsk", setting_sources=[], max_turns=cfg.max_rounds, max_budget_usd=cfg.turn_budget_usd,
            include_partial_messages=True, verbatim_prompts=True, cli_path=self.binary, cwd=self.env["CLAUDE_CONFIG_DIR"],
            env=self.env,
            extra_args={"restricted": None, "no-session-persistence": None, "disable-slash-commands": None,
                        "permission-prompts": "none"},
        )

    def server(self, evidence, queue: asyncio.Queue, state: dict):
        sdk, cfg = self.sdk, self.cfg

        def make(spec: dict):
            name = spec["name"]

            async def handler(args: dict) -> dict:
                if state["calls"] >= cfg.max_tool_calls:
                    return {"content": [{"type": "text", "text": "Tool-call budget for this turn is used up."}], "is_error": True}
                state["calls"] += 1
                block = {"id": f"plan_{state['calls']}", "name": name, "input": args}
                await queue.put(("event", {"type": "tool", "id": block["id"], "name": name, "status": "running"}))
                result, event = await copilot._run_tool(evidence, block, cfg, state)
                await queue.put(("event", event))
                if (proposal := copilot.proposal_event(event)) is not None:
                    await queue.put(("event", proposal))
                return {"content": [{"type": "text", "text": result["content"]}], "is_error": bool(result.get("is_error"))}

            return sdk.tool(name, spec["description"], spec["input_schema"],
                            annotations=sdk.ToolAnnotations(readOnlyHint=True))(handler)

        return sdk.create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=[make(t) for t in copilot_tools.TOOLS])

    async def run_turn(self, history: list[dict], symbol: str | None, cfg: copilot.Settings, evidence,
                       now: datetime) -> AsyncIterator[dict]:
        """Stream one turn as UI events: text, tool, error, done (always last, with metrics)."""
        sdk = self.sdk
        started = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue()
        state = {"calls": 0}
        metrics: dict[str, Any] = {"backend": "plan", "evidence": cfg.evidence, "model": cfg.model,
                                   "first_text_ms": None, "rounds": 0, "tool_calls": []}
        usage = _usage(None)
        cost: float | None = None
        replay = getattr(evidence, "label", "") == "replay"
        if replay:
            now = evidence.at

        def elapsed() -> int:
            return round((time.monotonic() - started) * 1000)

        owner_block, pack_event = await copilot.owner_context(evidence, symbol, cfg)
        metrics["tool_calls"].append({k: pack_event.get(k) for k in ("name", "status", "ms")})
        yield pack_event

        async def produce():
            try:
                import anyio
                # An anyio deadline, so the SDK's shielded close still stops Claude Code on timeout.
                with anyio.fail_after(cfg.turn_timeout_s):
                    async for message in sdk.query(prompt=prompt_for(history, symbol, now, replay, owner_block),
                                                   options=self.options(self.server(evidence, queue, state))):
                        await queue.put(("message", message))
            except TimeoutError:
                await queue.put(("timeout", None))
            except Exception as exc:  # noqa: BLE001 - reported below as an honest error event
                await queue.put(("exception", exc))
            finally:
                await queue.put((_DONE, None))

        task = asyncio.create_task(produce())
        result = None
        assistant_error: str | None = None
        errored = False
        # Text from separate model rounds ("I'll re-check..." then the answer) gets a paragraph break.
        new_round = False
        try:
            while True:
                kind, value = await queue.get()
                if kind is _DONE:
                    break
                if kind == "event":
                    if value.get("type") == "tool" and value.get("status") != "running":
                        metrics["tool_calls"].append({k: value.get(k) for k in ("name", "status", "ms")})
                    yield value
                elif kind == "timeout":
                    errored = True
                    yield {"type": "error", "code": "timeout", "message": f"The turn exceeded {cfg.turn_timeout_s:.0f} seconds."}
                elif kind == "exception":
                    if result is not None and result.is_error and isinstance(value, sdk.ProcessError):
                        continue  # Claude Code exits non-zero after an error result it already reported
                    errored = True
                    if isinstance(value, sdk.CLINotFoundError):
                        yield {"type": "error", "code": "plan_not_installed", "message": "Claude Code could not be started."}
                    else:
                        log.warning("copilot plan turn failed: %s", type(value).__name__)
                        yield {"type": "error", "code": "plan_unavailable", "message": "The Claude plan turn failed unexpectedly."}
                elif isinstance(value, sdk.StreamEvent):
                    event = value.event or {}
                    delta = event.get("delta") or {}
                    if value.parent_tool_use_id is not None:
                        continue
                    if event.get("type") == "message_start":
                        new_round = metrics["first_text_ms"] is not None
                    elif event.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and delta.get("text"):
                        if metrics["first_text_ms"] is None:
                            metrics["first_text_ms"] = elapsed()
                        yield {"type": "text", "delta": ("\n\n" if new_round else "") + delta["text"]}
                        new_round = False
                elif isinstance(value, sdk.AssistantMessage):
                    if value.model:
                        metrics["model"] = value.model
                    assistant_error = value.error or assistant_error
                elif isinstance(value, sdk.ResultMessage):
                    result = value
                    usage = _usage(value.usage)
                    cost = round(float(value.total_cost_usd), 6) if value.total_cost_usd is not None else None
                    metrics["rounds"] = value.num_turns
                    problem = _result_error(value, assistant_error, cfg)
                    if problem and not errored:
                        errored = True
                        yield {"type": "error", **problem}
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001 - the generator is closing; nothing to report to
                    pass
        if result is None and not errored:
            yield {"type": "error", "code": "plan_unavailable", "message": "Claude Code ended without a result."}
        # cost_usd is Claude Code's API-price estimate for the same tokens; the plan is not billed per token.
        metrics.update(total_ms=elapsed(), usage=usage, cost_usd=cost, billing="claude_plan")
        log.info("copilot turn backend=plan model=%s first_text_ms=%s total_ms=%s rounds=%s tools=%s in=%s out=%s cache_read=%s api_equivalent_cost=%s",
                 metrics["model"], metrics["first_text_ms"], metrics["total_ms"], metrics["rounds"],
                 ",".join(t["name"] for t in metrics["tool_calls"]), usage["input_tokens"], usage["output_tokens"],
                 usage["cache_read_input_tokens"], cost)
        yield {"type": "done", "metrics": metrics}
