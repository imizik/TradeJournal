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
    for word in VERDICTS:
        assert f"{word} (" in prompt, word
    assert '"Changes if: <that thing>"' in prompt and "Nothing goes ahead of the Verdict line" in prompt
    assert "never give an order" in prompt  # Broken says what the plan says, not what to do


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
