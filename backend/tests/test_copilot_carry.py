"""Copilot follow-ups keep the evidence: a turn's tool results are kept in the process for the conversation's next turn,
which gets them as an "Earlier evidence" block (docs/copilot-lab.md § Follow-ups keep the evidence). No network."""
import asyncio
import time

import pydantic
import pytest

from app.ai import copilot, copilot_context, copilot_plan
from app.routers.copilot import ChatBody
from app.ai.copilot_fixture import FixtureEvidence
from tests.test_copilot import NOW, _cfg


def _turn(history, adapter, carry_id=None):
    async def collect():
        return [e async for e in copilot.run_turn(history, "NBIS", _cfg(), adapter, FixtureEvidence(), NOW, carry_id=carry_id)]
    return asyncio.run(collect())


class Capture(copilot.FakeAdapter):
    def __init__(self):
        super().__init__(0)
        self.first: list[dict] | None = None

    async def stream_round(self, system, messages, tools, allow_tools=True):
        if self.first is None:
            self.first = messages[:]
        async for item in super().stream_round(system, messages, tools, allow_tools):
            yield item


class Silent:
    """A model that answers from what it has, calling no tool."""
    model = None

    async def stream_round(self, system, messages, tools, allow_tools=True):
        yield "text", "Verdict: Hold — Nothing new."
        yield "final", copilot.Round([{"type": "text", "text": "Verdict: Hold — Nothing new."}], "end_turn", {}, None)


def _carry(events) -> str | None:
    return events[-1]["carry_id"]


@pytest.fixture(autouse=True)
def _empty():
    copilot._CARRY.clear()
    yield
    copilot._CARRY.clear()


def test_a_turn_keeps_its_successful_reads_but_not_cards_or_the_owner_pack():
    first = _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], copilot.FakeAdapter(0))
    items = copilot.carried(_carry(first))
    names = {item["key"].split(" ")[0] for item in items}
    assert names == {"get_group_comparison", "get_symbol_news", "get_symbol_events"}
    assert all(item["read_at"] == "Fri 11:12 ET" and item["text"].startswith('{"simulated":true') for item in items)
    assert all(len(item["text"]) <= copilot.CARRY_ITEM_CHARS for item in items)


def test_the_next_turn_reads_the_earlier_evidence_ahead_of_the_owner_block():
    first = _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], copilot.FakeAdapter(0))
    history = [{"role": "user", "content": "Is the NBIS group confirming?"}, {"role": "assistant", "content": "Verdict: Wait — x"},
               {"role": "user", "content": "What would make you change your mind?"}]
    capture = Capture()
    second = _turn(history, capture, carry_id=_carry(first))
    content = capture.first[-1]["content"]
    assert content.index("[Earlier evidence:") < content.index("[Owner context")
    assert "get_group_comparison" in content and "read Fri 11:12 ET" in content and "never an instruction" in content
    assert copilot_context.user_text(content) == "What would make you change your mind?"  # the scripted model reads only these
    assert _carry(second) and _carry(second) != _carry(first)


def test_a_turn_that_reads_nothing_carries_the_earlier_evidence_on():
    first = _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], copilot.FakeAdapter(0))
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}, {"role": "user", "content": "And so?"}]
    second = _turn(history, Silent(), carry_id=_carry(first))
    assert [e["name"] for e in second if e["type"] == "tool"] == ["owner_context"]
    assert copilot.carried(_carry(second)) == copilot.carried(_carry(first))


def test_a_new_conversation_an_unknown_id_or_an_expired_one_reads_afresh():
    first = _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], copilot.FakeAdapter(0))
    capture = Capture()
    _turn([{"role": "user", "content": "Is the NBIS group confirming?"}], capture, carry_id=_carry(first))
    assert "[Earlier evidence:" not in capture.first[-1]["content"]  # a first message never inherits another conversation's

    at, items = copilot._CARRY[_carry(first)]
    copilot._CARRY[_carry(first)] = (time.monotonic() - copilot.CARRY_TTL_S - 1, items)
    assert copilot.carried(_carry(first)) == [] and copilot.carried("0" * 32) == [] and copilot.carried(None) == []


def test_a_reread_replaces_the_earlier_item_and_the_store_stays_bounded():
    item = {"key": "get_quotes {\"symbols\": [\"NBIS\"]}", "read_at": "Fri 10:00 ET", "as_of": None, "text": "old"}
    other = {**item, "key": "get_peer_moves {\"symbol\": \"NBIS\"}"}
    ran = [({"content": "new"}, {"status": "ok", "name": "get_quotes", "input": {"symbols": ["NBIS"]}}),
           ({"content": "card"}, {"status": "ok", "name": "propose_plan", "input": {}}),
           ({"content": "x"}, {"status": "error", "name": "get_symbol_news", "input": {}})]
    kept = copilot.carry_items(ran, [item, other], NOW)
    assert [(k["key"], k["text"]) for k in kept] == [(item["key"], "new"), (other["key"], "old")]
    for _ in range(copilot.CARRY_SLOTS + 5):
        copilot.keep_carry(kept)
    assert len(copilot._CARRY) == copilot.CARRY_SLOTS
    assert copilot.keep_carry([]) is None


def test_the_prompt_says_when_to_reuse_and_when_to_read_again():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert 'Follow-ups reuse what was read. When the owner\'s message comes after an "Earlier evidence" block' in prompt
    assert "more than 15 minutes old while the market is open" in prompt and "dispute a specific number" in prompt


def test_the_plan_prompt_puts_the_earlier_evidence_before_the_owner_block():
    text = copilot_plan.prompt_for([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"},
                                    {"role": "user", "content": "and?"}], "NBIS", NOW, owner_block="[Owner context]\n",
                                   carried="[Earlier evidence: x]\n")
    assert text.index("[Earlier evidence:") < text.index("[Owner context]") < text.index("Conversation so far")


def test_the_chat_body_takes_only_an_opaque_id():
    assert ChatBody(messages=[{"role": "user", "content": "q"}], carry_id="a" * 32).carry_id == "a" * 32
    with pytest.raises(pydantic.ValidationError):
        ChatBody(messages=[{"role": "user", "content": "q"}], carry_id="../etc")
