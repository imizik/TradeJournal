# Codex workflow

Follow [CLAUDE.md](../../CLAUDE.md) for task sizing, verification and delivery.
Work directly with the user's selected model. Do not create a Sol/Luna management
layer, switch models automatically or start a new chat for each small item.

## When to delegate

Delegate only an independent, bounded task when it saves more work than briefing
and integration cost. State the outcome, owned files, constraints and focused
checks. Workers must preserve others' edits; one writer owns each file or module.
Do not duplicate a worker's exploration or delegate routine review fixes.

The owner keeps product decisions, integration and final accountability. If a
worker finds ambiguity or fails twice on the same issue, send the evidence and
the decision needed in a few sentences; continue unblocked work. No fixed-format
escalation or completion report is required. Resume useful existing context.

## Verification and review

Use [focused checks](verification.md) for ordinary work. No worker or reviewer is
mandatory for that path. [Review policy](pr-review.md) owns the requirements for
broad and consequential changes; optional delegation does not add review gates.
Report what changed, checks and remaining blockers briefly.

Own ordinary PRs through CI, bounded repairs and automatic squash merge under
the shared [PR completion rules](pr-review.md#automatic-repair-and-merge).
Broad and consequential PRs retain the user's approval and merge.
