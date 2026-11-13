"""The copilot's instructions by job (docs/copilot-lab.md § Jobs): each job's assembled prompt, tools and shape reminder,
the contradictions they removed, and the cached prefix. Offline: a recording adapter, nothing reaches Anthropic."""
import asyncio
import copy
import re

import pytest

from app.ai import copilot, copilot_answer, copilot_prompt, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from tests.test_copilot import NOW, _cfg

JOBS = copilot_prompt.JOBS


class Recording:
    """Answers each round with fixed content and records the system prompt, tools and messages it was sent."""
    model = "claude-sonnet-5-5"

    def __init__(self, *rounds):
        self.rounds, self.calls = list(rounds), []

    async def stream_round(self, system, messages, tools, allow_tools=True):
        self.calls.append({"system": system, "tools": [t["name"] for t in tools], "messages": copy.deepcopy(messages)})
        content = self.rounds.pop(0) if self.rounds else [{"type": "text", "text": "done"}]
        stop = "tool_use" if any(b.get("type") == "tool_use" for b in content) else "end_turn"
        yield "final", copilot.Round(content, stop, copilot._zero_usage(), self.model)


def run(job, adapter, question="What matters this morning?", symbol=None):
    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": question}], symbol, _cfg(), adapter,
                                                  FixtureEvidence(), NOW, job=job)]
    return asyncio.run(collect())


def test_every_job_shares_the_core_and_states_its_own_format():
    for job in JOBS:
        prompt = copilot_prompt.PROMPTS[job]
        for core in ("working hypotheses", "1. Thesis", "4. The decision now", "untrusted third-party data",
                     "Never reveal or guess account numbers", "SIMULATED", "You cannot place orders"):
            assert core in prompt, (job, core)
        assert copilot_prompt.FORMAT[job] in prompt and prompt.count("Answer format") == 1, job
    assert copilot.SYSTEM_PROMPT == copilot_prompt.PROMPTS["desk"]


def test_the_desk_keeps_its_format_and_the_others_drop_the_parts_they_contradicted():
    desk, prep = copilot_prompt.PROMPTS["desk"], copilot_prompt.PROMPTS["prep"]
    for part in ("Compare: <A> | <B>", "Read:", "at most three one-sentence bullets", "Changes if: <that thing>"):
        assert part in desk
    # The brief: plain lines, never the desk's Verdict / Read / bullets / Against shape.
    assert "Verdict: <word>" not in prep and "Compare:" not in prep and "Keep answers short" not in prep
    assert "no Verdict, Read, Against or Changes if line" in prep
    # Telegram: the Verdict line, but no Read line and no compare rows.
    telegram = copilot_prompt.PROMPTS["telegram"]
    assert "Verdict: <word> — <headline>" in telegram and "No Read line" in telegram and 'no "Compare:" block' in telegram
    # The companion follows the shape its message gives.
    assert "exactly the shape the message gives" in copilot_prompt.PROMPTS["companion"]
    # Only the desk and Telegram are told about follow-up evidence, memories or plan cards; the brief no web-deeper-read.
    for job in ("prep", "companion", "week_review"):
        assert "propose_plan kind=memory" not in copilot_prompt.PROMPTS[job], job
    assert "Earlier evidence" not in telegram


def test_no_job_prompt_carries_an_example_answer_or_the_audit_figures():
    for job in JOBS:
        prompt = copilot_prompt.PROMPTS[job]
        for copied in ("The thesis has not broken", "Thesis holds · Timing early", "10/30 vs 11/6", "1,528", "15,304"):
            assert copied not in prompt, (job, copied)


def test_each_job_is_offered_only_its_tools_in_a_stable_order():
    order = [t["name"] for t in copilot_tools.TOOLS]
    assert "get_memories" not in order
    for job in JOBS:
        names = [t["name"] for t in copilot_prompt.TOOLS[job]]
        assert names == [n for n in order if n in names], job  # TOOLS order: the cached prefix never reshuffles
    every = len(copilot_tools.TOOLS) - len(copilot_prompt.JOB_ONLY)  # the check's facts tool is its own job's alone
    assert len(copilot_prompt.TOOLS["desk"]) == every == len(copilot_prompt.TOOLS["telegram"])
    assert set(n["name"] for n in copilot_prompt.TOOLS["prep"]) == set(copilot_prompt.PREP_TOOLS)
    assert "propose_plan" not in {t["name"] for t in copilot_prompt.TOOLS["prep"]} | {t["name"] for t in copilot_prompt.TOOLS["companion"]}
    assert {"get_week_review", "propose_plan"} <= {t["name"] for t in copilot_prompt.TOOLS["week_review"]}
    for job in ("prep", "companion", "week_review"):
        assert len(copilot_prompt.PROMPTS[job]) < len(copilot_prompt.PROMPTS["desk"]) / 2, job


def test_a_prep_turn_reads_no_owner_block_and_ends_with_the_brief_shape_not_the_desk_one():
    adapter = Recording([{"type": "tool_use", "id": "t1", "name": "get_quotes", "input": {"symbols": ["SPY"]}}])
    events = run("prep", adapter)
    first, second = adapter.calls
    assert first["system"] == copilot_prompt.PROMPTS["prep"] and first["tools"] == [t["name"] for t in copilot_prompt.TOOLS["prep"]]
    message = first["messages"][-1]["content"]
    assert message.endswith(copilot_answer.PREP_SHAPE) and copilot_answer.ANSWER_SHAPE not in message
    assert "Owner context" not in message and not any(e.get("name") == "owner_context" for e in events)
    # After the tool results the reminder is the brief's again.
    assert second["messages"][-1]["content"][-1] == {"type": "text", "text": copilot_answer.PREP_SHAPE}
    assert events[-1]["metrics"]["job"] == "prep"


@pytest.mark.parametrize("job,shape", [("desk", copilot_answer.ANSWER_SHAPE), ("telegram", copilot_answer.TELEGRAM_SHAPE),
                                       ("companion", copilot_answer.COMPANION_SHAPE), ("week_review", copilot_answer.WEEK_SHAPE)])
def test_each_job_reads_the_owner_block_and_gets_its_own_shape(job, shape):
    adapter = Recording()
    events = run(job, adapter, "Is NBIS lagging its group?", "NBIS")
    message = adapter.calls[0]["messages"][-1]["content"]
    assert message.endswith("\n\n" + shape) and adapter.calls[0]["system"] == copilot_prompt.PROMPTS[job]
    assert events[0]["name"] == "owner_context"
    assert copilot_answer.without_shape(message).endswith("Is NBIS lagging its group?")


def test_a_tool_outside_the_job_is_refused_and_never_runs():
    adapter = Recording([{"type": "tool_use", "id": "t1", "name": "propose_plan",
                          "input": {"kind": "revisit", "question": "Still lagging?", "horizon_days": 1}}])
    events = run("companion", adapter, "Review this position.", "NBIS")
    [row] = [e for e in events if e.get("name") == "propose_plan" and e.get("status") != "running"]
    assert row["status"] == "error" and "not offered" in row["summary"]
    assert not [e for e in events if e["type"] == "proposal"]


def test_job_for_follows_what_the_callers_already_pass():
    assert copilot_prompt.job_for(None, "desk") == copilot_prompt.job_for(None, "charts") == "desk"
    assert copilot_prompt.job_for(None, "telegram") == "telegram"
    assert copilot_prompt.job_for("prep", "prep") == "prep"
    assert copilot_prompt.job_for("companion", "companion") == "companion"
    assert copilot_prompt.job_for("week_review", "week_review") == "week_review"
    with pytest.raises(ValueError):
        copilot_prompt.system_prompt("nope")


def test_the_request_caches_the_jobs_fixed_prefix_and_still_the_tail():
    cfg = _cfg(backend="anthropic")
    adapter = copilot.AnthropicAdapter(cfg, client=object())
    for job in JOBS:
        kwargs = adapter.request(copilot_prompt.PROMPTS[job], [{"role": "user", "content": "x"}], copilot_prompt.TOOLS[job], True)
        assert kwargs["system"] == [{"type": "text", "text": copilot_prompt.PROMPTS[job], "cache_control": {"type": "ephemeral"}}]
        assert kwargs["cache_control"] == {"type": "ephemeral"}  # the moving point on the conversation tail
        assert [t["name"] for t in kwargs["tools"]] == [t["name"] for t in copilot_prompt.TOOLS[job]]
        # Nothing volatile in the cached prefix: built once, identical every turn.
        assert copilot_prompt.system_prompt(job) == copilot_prompt.PROMPTS[job] and "ET]" not in copilot_prompt.PROMPTS[job]


def test_a_jobs_prompt_names_only_the_tools_it_is_offered():
    """A rule naming a tool the job is not offered spends a round on a refused call (review of 2026-11-10)."""
    every = {t["name"] for t in copilot_tools.TOOLS}
    for job in JOBS:
        named = set(re.findall(r"\b(get_[a-z_]+|propose_plan)\b", copilot_prompt.PROMPTS[job])) & (every | {"get_memories"})
        offered = {t["name"] for t in copilot_prompt.TOOLS[job]}
        assert named <= offered, (job, sorted(named - offered))
    assert "get_week_review" in copilot_prompt.PROMPTS["telegram"]  # a typed "review my week" keeps its rules


def test_the_three_book_reads_are_offered_only_where_a_job_needs_them():
    """#730 dropped get_memories (the owner block carries them); the rest reach beyond the block, so desk and Telegram keep
    all three, the companion and week review keep get_trades, the brief, the desk read and the research jobs none."""
    names = {job: {t["name"] for t in copilot_prompt.TOOLS[job]} for job in JOBS}
    reads = {"get_positions", "get_trades", "get_owner_context", "get_memories"}
    assert {job: reads & n for job, n in names.items()} == {
        "desk": {"get_positions", "get_trades", "get_owner_context"}, "telegram": {"get_positions", "get_trades", "get_owner_context"},
        "prep": set(), "companion": {"get_trades"}, "week_review": {"get_trades"}, "check_call": {"get_trades"},
        "desk_read": set()}
    assert len(copilot_tools.TOOLS) == 26  # 25 and the check job's own get_call_facts


@pytest.mark.parametrize("job,deep", [("desk", False), ("telegram", False), ("prep", False), ("companion", True), ("week_review", True)])
def test_only_the_review_jobs_start_with_the_deeper_turn_cap(job, deep):
    assert (job in copilot.DEEP_JOBS) is deep
