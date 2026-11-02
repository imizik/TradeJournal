"""A scripted stand-in for ``anthropic.Anthropic`` / ``AsyncAnthropic``: just ``client.beta.messages.stream(...)``.

Each call to ``stream`` consumes the next scripted step and records the request's keyword arguments (deep-copied, since
``run_agent`` keeps appending to its ``messages`` list). A step is one of

* a message built with ``message(...)`` / ``answer(...)``: returned by ``get_final_message()``;
* an exception (instance or class): raised by ``get_final_message()``;
* ``Sleep(seconds)``: waits, then the next step decides what the call does (so a sleep alone makes a call hang).

The messages mimic the SDK's: ``.content`` blocks with ``model_dump(mode="json", exclude_none=True)`` and attribute
access, ``.stop_reason``, ``.model`` and ``.usage`` (with ``.server_tool_use.web_search_requests``). No network.
"""
from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx

MODEL = "claude-sonnet-5-5"
_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class Block:
    """One content block: attribute access over a plain dict, plus the SDK's ``model_dump``."""

    def __init__(self, **data):
        self.data = data

    def __getattr__(self, name):
        try:
            return self.__dict__["data"][name]
        except KeyError:
            raise AttributeError(name) from None

    def model_dump(self, mode="python", exclude_none=False):
        data = copy.deepcopy(self.data)
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data


_ids = iter(range(1, 10**6))


def text(value: str) -> Block:
    return Block(type="text", text=value)


def tool_use(name: str, input: dict | None = None, id: str | None = None) -> Block:  # noqa: A002
    return Block(type="tool_use", id=id or f"toolu_{next(_ids)}", name=name, input=input or {})


def server_use(name: str, input: dict | None = None, id: str | None = None) -> Block:  # noqa: A002
    return Block(type="server_tool_use", id=id or f"srvtoolu_{next(_ids)}", name=name, input=input or {})


def search_results(*urls: str, snippet: str | None = None, id: str = "srvtoolu_s") -> Block:
    """A web_search_tool_result; ``snippet`` is page text carried next to the first result (never a url field)."""
    results = [{"type": "web_search_result", "url": url, "title": "t", "page_age": None,
                "encrypted_content": snippet or "x"} for url in urls]
    return Block(type="web_search_tool_result", tool_use_id=id, content=results)


def fetch_result(url: str, ok: bool = True, id: str = "srvtoolu_f") -> Block:
    content = ({"type": "web_fetch_result", "url": url, "content": {"type": "document"}} if ok
               else {"type": "web_fetch_tool_error", "error_code": "url_not_accessible"})
    return Block(type="web_fetch_tool_result", tool_use_id=id, content=content)


def message(*blocks: Block, stop_reason: str = "end_turn", model: str = MODEL, input_tokens: int = 1000,
            output_tokens: int = 100, cache_read: int = 0, cache_write: int = 0, searches: int = 0) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=cache_read,
                            cache_creation_input_tokens=cache_write,
                            server_tool_use=SimpleNamespace(web_search_requests=searches))
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, model=model, usage=usage)


def json_message(data: Any, **kwargs) -> SimpleNamespace:
    """What ``ask`` reads: one text block of JSON."""
    import json
    return message(text(data if isinstance(data, str) else json.dumps(data)), **kwargs)


def answer(data: dict, *, id: str = "toolu_answer", **kwargs) -> SimpleNamespace:  # noqa: A002
    """The last round of an agent run: a submit_answer call."""
    return message(tool_use("submit_answer", data, id=id), stop_reason="tool_use", **kwargs)


@dataclass
class Sleep:
    seconds: float


def api_error(kind: type = anthropic.InternalServerError, status: int = 500, body: str = "boom") -> Exception:
    """An ``anthropic`` status error of the given class (``APIConnectionError`` ignores the status)."""
    if kind is anthropic.APIConnectionError:
        return kind(request=_REQUEST)
    return kind(body, response=httpx.Response(status, request=_REQUEST), body=None)


class _Script:
    def __init__(self, script, default=None):
        """``default``: what every call after the script gets (a message or an exception); without one, running out of
        script fails the test."""
        self.script, self.requests, self.default = list(script), [], default

    def next_step(self) -> list:
        """The sleeps before the step that decides this call, then that step."""
        steps = []
        while True:
            if not self.script and self.default is not None:
                return [*steps, self.default]
            if not self.script:
                raise AssertionError("the fake Anthropic script ran out: more requests than scripted rounds")
            step = self.script.pop(0)
            steps.append(step)
            if not isinstance(step, Sleep):
                return steps

    @staticmethod
    def outcome(step):
        if isinstance(step, BaseException) or (isinstance(step, type) and issubclass(step, BaseException)):
            raise step
        return step


class _SyncStream:
    def __init__(self, steps):
        self.steps = steps

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        for step in self.steps[:-1]:
            time.sleep(step.seconds)
        return _Script.outcome(self.steps[-1])


class _AsyncStream:
    def __init__(self, steps):
        self.steps = steps

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        for step in self.steps[:-1]:
            await asyncio.sleep(step.seconds)
        return _Script.outcome(self.steps[-1])


class _Client(_Script):
    stream_class: type

    def __init__(self, *script, default=None):
        super().__init__(script[0] if len(script) == 1 and isinstance(script[0], (list, tuple)) else script, default)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.stream_class(self.next_step())

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def last(self) -> dict:
        return self.requests[-1]


class FakeAnthropic(_Client):
    """For ``ask``: ``with client.beta.messages.stream(...) as s: s.get_final_message()``."""
    stream_class = _SyncStream

    def close(self):
        pass


class FakeAsyncAnthropic(_Client):
    """For ``run_agent``: ``async with client.beta.messages.stream(...) as s: await s.get_final_message()``."""
    stream_class = _AsyncStream

    async def close(self):
        pass
