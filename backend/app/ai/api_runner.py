"""Unattended Claude calls through the Anthropic Messages API, on API credits.

``ask`` is one question with one structured answer (the daily, monthly and trade reviews). ``run_agent`` is a bounded
tool loop ending in one structured answer (research jobs, shadow-book decisions): it only offers the tools it is given,
stops at ``max_turns`` or ``budget_usd``, and returns what happened instead of raising. The key is
``ANTHROPIC_API_KEY``, sent only to api.anthropic.com whatever the environment's base URL says.

Settings for ``ask``: ``TJ_PLAN_REVIEW_MODEL`` (``claude-sonnet-5-5``) and ``TJ_PLAN_REVIEW_TIMEOUT`` (300 seconds).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import anthropic

from app.ai import copilot

KEY_ENV = "ANTHROPIC_API_KEY"
BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT = 300
ANSWER_TOOL = "submit_answer"
MAX_TOKENS = 16000
WEB_SEARCH_USD = 0.01  # per search, on top of tokens
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_UNSUPPORTED = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum", "multipleOf"}


class ApiUnavailable(RuntimeError):
    """The API cannot be used: no key."""


class ApiCallFailed(RuntimeError):
    """Claude was asked and gave no usable answer (timeout, error, refusal, or no structured output)."""


@dataclass(frozen=True)
class ApiAnswer:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    seconds: float

    @property
    def author(self) -> str:
        return f"{self.model} through the Anthropic API"

    @property
    def usage(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "api_equivalent_usd": self.usd, "seconds": self.seconds}


def configured() -> bool:
    return bool(os.environ.get(KEY_ENV))


def api_schema(schema):
    """``schema`` as structured outputs take it: no length, count or range constraints, and every object closed. The
    SDK's own transform refuses the nullable types and bare enums the review schemas use."""
    if isinstance(schema, list):
        return [api_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "properties":  # field names, one of which could be spelled like a constraint
            out[key] = {name: api_schema(item) for name, item in value.items()}
        elif key not in _UNSUPPORTED:
            out[key] = api_schema(value)
    if schema.get("type") == "object" or "properties" in schema:
        out["additionalProperties"] = False
    return out


def zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _usage_of(message) -> dict:
    u = message.usage
    return {key: getattr(u, key, 0) or 0 for key in zero_usage()}


def _api_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, anthropic.AuthenticationError):
        return "api_auth", "The Anthropic API key was rejected."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "api_permission", "This Anthropic account is not permitted to use the configured model."
    if isinstance(exc, anthropic.NotFoundError):
        return "api_request", "The Anthropic API does not know the configured model (404)."
    if isinstance(exc, anthropic.RateLimitError):
        return "api_rate_limit", "The Anthropic API rate limit was reached."
    if isinstance(exc, anthropic.BadRequestError):
        text = str(getattr(exc, "message", "")).lower()
        if "credit" in text or "billing" in text:
            return "api_billing", "The Anthropic account is out of API credits."
        return "api_request", f"The Anthropic API refused the request (400): {str(getattr(exc, 'message', ''))[:200]}"
    if isinstance(exc, anthropic.APIStatusError):
        return "api_unavailable", f"The Anthropic API is unavailable ({exc.status_code})."
    return "api_unreachable", "The Anthropic API could not be reached."


def ask(system: str, message: str, schema: dict, *, model: str | None = None, timeout: float | None = None,
        client=None) -> ApiAnswer:
    """One question, one structured answer. Raises ApiUnavailable or ApiCallFailed."""
    if client is None and not configured():
        raise ApiUnavailable(f"No {KEY_ENV} on the private backend.")
    model = copilot.model_id(model or os.environ.get("TJ_PLAN_REVIEW_MODEL") or DEFAULT_MODEL)
    limit = timeout or float(os.environ.get("TJ_PLAN_REVIEW_TIMEOUT") or DEFAULT_TIMEOUT)
    client = client or anthropic.Anthropic(api_key=os.environ[KEY_ENV], base_url=BASE_URL, max_retries=1, timeout=limit)
    started = time.monotonic()
    try:
        with client.beta.messages.stream(
            model=model, max_tokens=MAX_TOKENS, system=system, messages=[{"role": "user", "content": message}],
            thinking={"type": "adaptive"}, cache_control={"type": "ephemeral"},
            output_config={"format": {"type": "json_schema", "schema": api_schema(schema)}},
            betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"},
        ) as stream:
            final = stream.get_final_message()
    except anthropic.APIError as exc:
        raise ApiCallFailed(_api_error(exc)[1]) from exc
    if final.stop_reason != "end_turn":
        raise ApiCallFailed(f"Claude gave no answer (stopped: {final.stop_reason}).")
    text = next((b.text for b in final.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ApiCallFailed(f"Claude's answer was not JSON: {text[:300]!r}") from exc
    if not isinstance(data, dict):
        raise ApiCallFailed(f"Claude's answer was not an object: {text[:300]!r}")
    usage = _usage_of(final)
    return ApiAnswer(data=data, model=final.model, usd=copilot.cost_usd(final.model, usage),
                     input_tokens=usage["input_tokens"] + usage["cache_read_input_tokens"] + usage["cache_creation_input_tokens"],
                     output_tokens=usage["output_tokens"], seconds=round(time.monotonic() - started, 1))


@dataclass
class AgentRun:
    """What a ``run_agent`` loop did so far; filled in as it goes, so a caller's timeout still sees the spend."""
    model: str
    answer: dict | None = None
    error: dict | None = None
    rounds: int = 0
    usage: dict = field(default_factory=zero_usage)
    cost_usd: float = 0.0


async def run_agent(run: AgentRun, system: str, prompt: str, schema: dict, *, tools: list[dict],
                    execute: Callable[[dict], Awaitable[dict]], server_tools: tuple[dict, ...] = (),
                    on_block: Callable[[dict], None] | None = None, max_turns: int, budget_usd: float,
                    effort: str = "medium", client=None) -> AgentRun:
    """Loop until Claude calls the answer tool, updating ``run``. ``execute`` takes a tool_use block and returns
    ``{"content", "is_error"}``; ``on_block`` sees every block Claude's turn produced, server tool results included."""
    owned = client is None
    if owned:
        if not configured():
            run.error = {"code": "api_not_configured", "message": f"No {KEY_ENV} on the private backend."}
            return run
        client = anthropic.AsyncAnthropic(api_key=os.environ[KEY_ENV], base_url=BASE_URL, max_retries=1, timeout=120.0)
    answer_tool = {"name": ANSWER_TOOL, "description": "Return your finished answer. Call this once, as your last step.",
                   "input_schema": api_schema(schema), "strict": True}
    request: dict[str, Any] = {
        "max_tokens": MAX_TOKENS, "system": system, "tools": [*tools, *server_tools, answer_tool],
        "thinking": {"type": "adaptive"}, "output_config": {"effort": effort}, "cache_control": {"type": "ephemeral"},
        "betas": [FALLBACK_BETA], "extra_body": {"fallbacks": "default"},
    }
    messages: list[dict] = [{"role": "user", "content": prompt}]
    nudged = False
    try:
        while True:
            if run.rounds >= max_turns:
                run.error = {"code": "error_max_turns", "message": f"The turn used all {max_turns} rounds without an answer."}
                return run
            if run.cost_usd >= budget_usd:
                run.error = {"code": "error_max_budget_usd", "message": f"The turn reached its ${budget_usd:.2f} budget without an answer."}
                return run
            async with client.beta.messages.stream(model=run.model, messages=messages, **request) as stream:
                final = await stream.get_final_message()
            run.rounds += 1
            run.model = final.model or run.model
            usage = _usage_of(final)
            run.usage = {key: run.usage[key] + usage[key] for key in usage}
            searches = getattr(getattr(final.usage, "server_tool_use", None), "web_search_requests", 0) or 0
            run.cost_usd = round(run.cost_usd + copilot.cost_usd(run.model, usage) + searches * WEB_SEARCH_USD, 6)
            blocks = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
            blocks = [b for b in blocks if not (b.get("type") == "text" and not b.get("text"))]
            if on_block:
                for block in blocks:
                    on_block(block)
            calls = [b for b in blocks if b.get("type") == "tool_use"]
            submitted = next((b for b in calls if b["name"] == ANSWER_TOOL), None)
            if submitted is not None and final.stop_reason == "tool_use":
                run.answer = submitted["input"]
                return run
            if final.stop_reason in ("refusal", "max_tokens"):
                run.error = {"code": final.stop_reason, "message": f"Claude stopped without an answer ({final.stop_reason})."}
                return run
            messages.append({"role": "assistant", "content": blocks})
            if final.stop_reason == "pause_turn":
                continue
            if calls:
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": call["id"], **(await execute(call))} for call in calls]})
            elif nudged:
                run.error = {"code": "no_answer", "message": f"Claude finished without calling {ANSWER_TOOL}."}
                return run
            else:
                nudged = True
                messages.append({"role": "user", "content": f"Call {ANSWER_TOOL} now with your answer."})
    except anthropic.APIError as exc:
        code, message = _api_error(exc)
        run.error = {"code": code, "message": message}
        return run
    finally:
        if owned:
            await client.close()
