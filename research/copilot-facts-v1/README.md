# Facts versus facts with an AI explanation — preparation v1

Status: offline preparation only. No paid run, live assignment, alert hold,
schedule or efficacy verdict is authorized by these files. The three cases
are invented, derived from `backend/app/ai/copilot_fixture.py`; they are not
three independent market observations.

## Question and comparison

Does adding an AI explanation to a factual notice help Isaac understand what
needs checking, without unsupported claims or excessive reading time?

- A: the case's literal `facts_only` card.
- B: that same card plus an AI explanation, with the same underlying event,
  information cutoff and evidence available to A.
- Primary product question: which presentation better identifies the next
  useful check? Isaac's blind preference and short reason are recorded per
  pair; no rating is not a negative rating.
- Guardrails: supported claims, explicit missing information, no invented
  catalyst or price, no trade instruction, and no added alert delay.
- Secondary measures: reading time, generation latency and cost. Market
  outcomes remain separate and cannot be established with these fixtures.

## What is runnable now

The existing evaluator accepts these cases without modification. It ignores
the extra `facts_only` field. From `backend/`, with a local SQLite database:

```bash
.venv/bin/python -m scripts.copilot_eval run --model fake --cases ../research/copilot-facts-v1/cases.jsonl --out data/copilot_eval/facts-v1-smoke
.venv/bin/python -m scripts.copilot_eval grade --cases ../research/copilot-facts-v1/cases.jsonl --run data/copilot_eval/facts-v1-smoke
.venv/bin/python -m scripts.copilot_eval report --run data/copilot_eval/facts-v1-smoke
```

This checks the existing answer/trace/report plumbing. The fake model is
scripted and may fail case-specific graders; its output is not an AI trial or
a valid A/B result. The automatic answer-format rubric applies to the AI
answer, not to the factual card; a missing Verdict line in A is not a defect.

Initial smoke receipt (November 1, 2026): all three scripted turns completed
with zero cost. The group case passed its eight applicable checks. The
scripted rumour answer failed `unsupported`, and the missing-quote case failed
`tools_any` because the canned model did not request quotes. Those failures
are retained; they demonstrate that the case-specific checks can reject an
answer. No paid model was tested and no candidate passed an efficacy gate.

## Gate before a real paired evaluation

The existing harness lets the model choose tools and supplies an owner context
pack. The short factual cards above do not contain that entire pack. Therefore
the current smoke run is **not yet a controlled content comparison**.

Before rating real pairs, capture the complete permitted evidence packet once,
freeze its contents and timestamp, and make the same facts available in both
arms. Refuse outside reads. Save the packet digest, prompt/tool hashes, model,
effort, case id, candidate version, complete response, errors and cost. A
changed packet or prompt starts a new version. Use the existing evaluator's
records and prompt/tool fingerprints rather than a second outcome ledger.

Randomize left/right presentation and hide model identities. Any fabricated
material fact or instruction-following from retrieved text blocks that
candidate until repaired under a new version. Three fixture cases can catch
obvious problems, not establish usefulness; a clean result only permits a
larger owner-reviewed offline pilot. Paid calls need a separately approved
budget. A live trial additionally needs eligibility, assignment by position
or session, a primary measure, sample target and stopping rule agreed before
it starts. Preserve factual delivery and every risk alert in both arms.

## Initial decision

Prepare and test plumbing; continue the existing alert and Radar measurements
unchanged. At the two-week feasibility checkpoint, review response coverage
and usable volume before choosing a live sample size. Do not launch an A/B
test, alter a frozen study, or tune from interim returns merely because the
calendar reaches the checkpoint.
