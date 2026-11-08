"""The Python reading of the copilot's answer format (``app.ai.copilot_answer``), kept in step with ``answerParts`` in
frontend/lib/copilot.ts. Offline."""
import pytest

from app.ai import copilot
from app.ai.copilot_answer import answer_parts, figures_in, word_count


def test_a_scripted_answer_parses_into_its_parts():
    text = copilot.scripted("Wait", "Not yet.", "- The group is up 0.84% in 15 minutes.\n- NBIS lags CRWV by 1.08 points.",
                            "a longer window agrees.", against="the window is short.", read="Thesis unclear · Timing early · Contract n/a")
    parts = answer_parts(text)
    assert parts.verdict == "Wait" and parts.headline == "Not yet."
    assert parts.read == (("Thesis", "unclear"), ("Timing", "early"), ("Contract", "n/a"))
    assert parts.against == "the window is short." and parts.changes_if == "a longer window agrees."
    assert "NBIS lags CRWV" in parts.body and "Against" not in parts.body and copilot.SCRIPTED_NOTE in parts.body
    assert copilot.SCRIPTED_NOTE not in parts.prose() and "Read:" not in parts.prose()


@pytest.mark.parametrize("line", ["Verdict: Hold — The thesis holds.", "**Verdict**: Hold - The thesis holds.", "Verdict: hold: The thesis holds.",
                                  "verdict: **Hold** – **The thesis holds.**", "Verdict: Hold. The thesis holds."])
def test_the_verdict_line_tolerates_bold_every_dash_and_a_full_stop(line):
    parts = answer_parts(line + "\n\nBody.")
    assert parts is not None and parts.verdict == "Hold" and parts.headline == "The thesis holds." and parts.body == "Body."


@pytest.mark.parametrize("text", ["Hold — no verdict label.", "Verdict: Maybe — an unknown word.", "Verdict: Watch — not in the set.", "Verdict: Hold.", "",
                                  "Just prose.\nVerdict: Hold — late."])
def test_text_without_the_structure_is_none(text):
    assert answer_parts(text) is None


def test_note_lines_ahead_of_the_verdict_stay_in_the_body():
    parts = answer_parts("_(Simulated: received 1 image.)_\nVerdict: Focus — Look here.\n\nBody.")
    assert parts.verdict == "Focus" and parts.body.startswith("_(Simulated") and parts.body.endswith("Body.")


def test_a_read_line_needs_all_three_parts():
    assert answer_parts("Verdict: Hold — H.\nRead: Thesis holds · Timing early\nBody.").read is None
    parts = answer_parts("Verdict: Hold — H.\nRead: Thesis holds | Timing early ; Contract mismatch\nBody.")
    assert parts.read == (("Thesis", "holds"), ("Timing", "early"), ("Contract", "mismatch")) and parts.body == "Body."


def test_only_the_closing_lines_are_against_and_changes_if():
    parts = answer_parts("Verdict: Hold — H.\n\n- Against: an early mention stays put.\n- Second bullet.\n\nAgainst: the real one.\n\nChanges if: SPY rolls.")
    assert parts.against == "the real one." and parts.changes_if == "SPY rolls." and "early mention" in parts.body
    assert answer_parts("Verdict: Hold — H.\n\nBody.\n\nChanges if: X.\n\nAgainst: late.").changes_if is None  # order matters: Changes if closes


def test_a_compare_block_needs_two_rows():
    text = ("Verdict: Unclear — A coin flip.\n\nCompare: 10/30 calls | 11/6 calls\nNeeds: a move this week | a move within two weeks\n"
            "Risks: expiring first | paying more time value\nCosts: $1.90 | $3.10\n\nAgainst: nothing in the evidence.")
    parts = answer_parts(text)
    assert parts.compare.a == "10/30 calls" and parts.compare.b == "11/6 calls"
    assert [r[0] for r in parts.compare.rows] == ["Needs", "Risks", "Costs"] and parts.body == ""
    one_row = answer_parts("Verdict: Unclear — H.\n\nCompare: A | B\nNeeds: x | y\n")
    assert one_row.compare is None and "Compare: A | B" in one_row.body


def test_figures_skip_times_dates_expiries_and_ids_and_keep_precision():
    figures = figures_in("NBIS 94.35 at 10:40 ET, down 2.95% on 2026-10-23; the 10/30 calls, $1,528 risk, ATR 4.1, id 00000000-0000-4000")
    assert [(f.value, f.decimals) for f in figures] == [(94.35, 2), (2.95, 2), (1528.0, 0), (4.1, 1)]
    assert figures_in("5m bars, 1D chart, Q3 2026") == [] or [f.value for f in figures_in("5m bars, 1D chart, Q3 2026")] == [2026.0]
    assert word_count("one two  three\nfour") == 4


def test_figures_glued_to_units_are_skipped_and_ranges_give_both_ends():
    assert figures_in("a 12.5x multiple, 10.5K shares, 94.35x") == []
    assert [f.value for f in figures_in("a 5-10 point gap over 5-minute bars")] == [5.0, 10.0, 5.0]
    assert [f.value for f in figures_in("from 95.6–95.9, then -2.95 and +3.2%")] == [95.6, 95.9, -2.95, 3.2]
