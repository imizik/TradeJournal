"""The copilot's answer format: a Verdict line first, then the body, then an optional Changes if line.

The desk parses it (frontend/lib/copilot.ts ``answerParts``); the scripted model writes it so the browser path is
exercised without an API call. See docs/copilot-lab.md § How the copilot reasons."""
import asyncio
from datetime import date
import re

from app.ai import copilot
from app.engine import premarket_prep, week_review_auto
from app.models import PremarketPrep
from tests.test_copilot import _text, _turn

# The fixed set, kept in step with VERDICTS in frontend/lib/copilot.ts.
VERDICTS = ("Hold", "Wait", "Pass", "Focus", "Draft", "Pattern", "Broken", "Unclear")
VERDICT_LINE = re.compile(rf"^Verdict: ({'|'.join(VERDICTS)}) — [^\n*]+$")


def _lines(text: str) -> list[str]:
    return text.split("\n")


def test_the_prompt_asks_for_the_verdict_line_the_fixed_words_and_changes_if():
    prompt = copilot.SYSTEM_PROMPT
    assert '"Verdict: <word> — <headline>"' in prompt and '"Verdict: Hold — The thesis has not broken."' in prompt
    assert "for market reads, trade ideas, position reviews, plans" in prompt
    assert "answer directly in natural prose without a Verdict line" in prompt
    assert "Do not force an action word such as Pass onto an informational answer" in prompt
    for word in VERDICTS:
        assert f"{word} (" in prompt, word
    assert '"Changes if: <that thing>"' in prompt and "When using the Verdict format, nothing goes ahead of that line" in prompt
    assert "never give an order" in prompt  # Broken says what the plan says, not what to do


def test_the_prompt_keeps_answers_short_unless_more_is_asked_for():
    # After a tool result the whole answer is generated before any of it streams, so length is the wait.
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert "This is a hard limit, not a target" in prompt and "the whole answer stays under 120 words" in prompt
    assert "The body is at most three bullets, each one sentence" in prompt
    assert "Then the body: at most three one-sentence bullets (the length rule above)." in prompt
    assert "do not repeat them in the text" in prompt
    assert 'when they ask for more ("more", "why", "go deeper") or for a trade review or a week review' in prompt


def test_the_prompt_asks_for_the_read_line_the_case_against_and_unsupported_claims():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert '"Read: Thesis <word> · Timing <word> · Contract <word>"' in prompt
    assert '"Against: <the strongest case against your verdict, with its number or source>"' in prompt
    assert "never a strawman" in prompt and '"Against: nothing in the evidence" only when that is true' in prompt
    assert '"Unsupported: <the claim> — <what would support it>" instead of reasoning from it' in prompt
    assert '"Changes if: <that thing>", after any Against line' in prompt


def test_a_scripted_group_read_carries_the_read_line_and_the_case_against_before_changes_if():
    answer = copilot.scripted("Wait", "Not yet.", "The body.", "a longer window agrees.", against="the window is short.",
                              read="Thesis unclear · Timing early · Contract n/a")
    lines = [line for line in _lines(answer) if line]
    assert lines == ["Verdict: Wait — Not yet.", copilot.SCRIPTED_NOTE, "Read: Thesis unclear · Timing early · Contract n/a",
                     "The body.", "Against: the window is short.", "Changes if: a longer window agrees."]


def test_every_scripted_answer_leads_with_a_verdict_and_keeps_the_simulated_note():
    fake = copilot.FakeAdapter
    answers = [
        fake._moment({}), fake._changes({}), fake._review({}), fake._week({}), fake._options({}),
        fake._trade_plan_text("NBIS", {}), fake._write("NBIS", "", {"propose_plan": {"proposal": {"kind": "memory"}}}),
        fake._write("NBIS", "plan it", {}), fake._write("NBIS", "", {}),
        fake._changes({"state": "ok", "investigation": {"updated_at": "2026-10-27T15:00:00Z", "title": "NBIS bounce", "conclusion": None},
                       "alerts": [{"symbol": "NBIS", "fired": {"price": 92.1, "at": "10:31"}}], "research_jobs": []}),
    ]
    for answer in answers:
        first, blank, note = _lines(answer)[:3]
        assert VERDICT_LINE.match(first), first
        assert blank == "" and note == copilot.SCRIPTED_NOTE
    assert _lines(answers[-1])[0] == "Verdict: Focus — 1 linked alert fired since you last looked."
    assert answers[-1].endswith("\n\nChanges if: a fresh read of the group or the level disagrees with the saved conclusion.")


def test_a_streamed_turn_is_in_the_format_end_to_end():
    first = _turn([{"role": "user", "content": "NBIS looks like it might recover. Is the whole neocloud group confirming?"}],
                  copilot.FakeAdapter(0))
    answer = _text(first)
    assert VERDICT_LINE.match(_lines(answer)[0])
    assert re.search(r"\n\nChanges if: [^\n]+$", answer)
    pushback = _turn([{"role": "user", "content": "NBIS looks like it might recover."}, {"role": "assistant", "content": answer},
                      {"role": "user", "content": "But CRWV and APLD are recovering too."}], copilot.FakeAdapter(0))
    assert _lines(_text(pushback))[0] == "Verdict: Wait — The group is confirming; NBIS is lagging it."


def test_an_image_note_goes_under_the_verdict_line_in_the_stream_and_the_final_text():
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "A" * 4096}}
    messages = [{"role": "user", "content": "Remember that NBIS reclaims 90 on volume.", "images": [image]}]

    async def collect():
        return [pair async for pair in copilot.FakeAdapter(0).stream_round("", messages, [], allow_tools=False)]
    events = asyncio.run(collect())
    streamed = "".join(value for kind, value in events if kind == "text")
    final = next(value for kind, value in events if kind == "final").content[0]["text"]
    assert streamed == final
    first, _, note = _lines(final)[:3]
    assert VERDICT_LINE.match(first) and note.startswith("_(Simulated: received 1 image (3 KB)")


def test_the_lock_screen_drops_the_verdict_label_and_the_saved_answer_keeps_it():
    assert week_review_auto.answer_lines("Verdict: Pattern — 6 trades, +$120.\n\n- Planned 4")[:2] == ["Pattern — 6 trades, +$120.", "Planned 4"]
    row = PremarketPrep(day=date(2026, 10, 28), body="Verdict: Focus — NBIS 95C expires today.\nNBIS 2% from its trigger.")
    _, body, _ = premarket_prep.message(row)
    assert body == "Focus — NBIS 95C expires today.\nNBIS 2% from its trigger."
    assert premarket_prep.unlabelled("**Verdict:** Hold — Nothing expires today.") == "Hold — Nothing expires today."  # the saved conclusion too


def test_the_prompt_asks_for_a_compare_block_when_two_choices_are_weighed():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert "When the owner asks you to compare two choices (A vs B, A or B, which of two" in prompt
    assert 'the body is a compare block instead of the bullets, under the same length limit: a line "Compare: <A> | <B>"' in prompt
    assert '"Needs: <what A needs> | <what B needs>", "Risks: … | …", "Breaks if: … | …", and, when a contract is involved, "Costs: … | …"' in prompt
    assert "from get_option_candidates, never estimated" in prompt
    assert "the Verdict headline says which side the evidence favours, or that it is a coin flip" in prompt
    assert "never a contract recommended as advice" in prompt


def test_a_scripted_compare_names_both_sides_and_keeps_the_row_order():
    answer = _text(_turn([{"role": "user", "content": "Which: NBIS 10/30 vs 11/6 calls?"}], copilot.FakeAdapter(0)))
    lines = [line for line in _lines(answer) if line]
    assert VERDICT_LINE.match(lines[0]) and lines[1] == copilot.SCRIPTED_NOTE
    assert lines[2] == "Read: Thesis unclear · Timing unclear · Contract unclear"
    assert lines[3] == "Compare: NBIS 10/30 | 11/6 calls"
    assert [line.split(":")[0] for line in lines[4:]] == ["Needs", "Risks", "Breaks if", "Costs", "Against", "Changes if"]
    assert all(line.count(" | ") == 1 for line in lines[3:8])
    plain = copilot.FakeAdapter._compare("Which is better, enter now or wait for 95.9?")
    assert "Compare: enter now | wait for 95.9\n" in plain and "Costs:" not in plain and "Contract n/a" in plain


# --------------------------------------------------------------------------- the length rule where the answer is written

def test_the_word_budgets_add_up_under_the_limit_and_both_rule_statements_quote_them():
    from app.ai import copilot_answer, copilot_graders
    budgets = (copilot_answer.HEADLINE_WORDS, copilot_answer.BULLET_WORDS, copilot_answer.AGAINST_WORDS, copilot_answer.CHANGES_WORDS)
    assert budgets[0] + 3 * budgets[1] + budgets[2] + budgets[3] < copilot_answer.MAX_WORDS == 120
    assert copilot_graders.MAX_WORDS is copilot_answer.MAX_WORDS  # the eval's length check measures the rule the prompt states
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    assert (f"the headline at most {budgets[0]} words, each bullet at most {budgets[1]}, Against at most {budgets[2]}, "
            f"Changes if at most {budgets[3]}") in prompt
    assert "The same shape is repeated after each tool result" in prompt
    shape = copilot_answer.ANSWER_SHAPE
    assert shape.startswith("[Answer shape: under 120 words in all") and shape.endswith("]")
    for n in budgets:
        assert f"at most {n} words" in shape
    assert copilot_answer.word_count(shape) <= copilot_answer.MAX_WORDS  # the reminder costs less than the answer it bounds
    assert '"more", "why", "go deeper"' in shape and "trade or week review" in shape  # the long_ok exceptions stay


def test_the_answer_shape_reminder_ends_the_owner_message_and_follows_every_tool_result():
    from app.ai import copilot_answer, copilot_context
    from tests.test_copilot_adversarial import Scripted, _say, _use
    adapter = Scripted([_use("get_quotes", {"symbols": ["NBIS"]})], [_use("get_peer_moves", {"symbol": "NBIS"}, 1)],
                       [_say("Verdict: Hold — Fine.")])
    events = _turn([{"role": "user", "content": "Is NBIS holding?"}], adapter)
    assert _text(events) == "Verdict: Hold — Fine." and len(adapter.seen) == 3
    first = adapter.seen[0]["messages"][-1]["content"]
    assert first.endswith("Is NBIS holding?\n\n" + copilot_answer.ANSWER_SHAPE)
    assert copilot_context.user_text(first) == "Is NBIS holding?"  # the scripted model reads only the owner's words
    for round_no in (1, 2):
        blocks = adapter.seen[round_no]["messages"][-1]["content"]
        assert blocks[-1] == {"type": "text", "text": copilot_answer.ANSWER_SHAPE}
        assert blocks and all(b["type"] == "tool_result" for b in blocks[:-1])  # the API wants the results first
    assert adapter.seen[2]["messages"][-1]["content"][0]["tool_use_id"] == "s_get_peer_moves_1"
