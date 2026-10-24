# Delegation

Follow [CLAUDE.md](../../CLAUDE.md). Work directly by default in Claude Code as
in Codex. Use the optional `engineer` only for independent work whose benefit
exceeds briefing and integration cost; do not delegate because a task is large
or a worker is available. Do not duplicate the worker's exploration.

## The brief

State the outcome, owned files, constraints and focused checks in a few sentences.
Use one writer per file/module and at most one migration author at a time.
Workers preserve others' edits and do not spawn more workers. The owner retains
product decisions, integration, pushes and PRs. The owner follows the shared
[PR completion rules](pr-review.md#automatic-repair-and-merge): automatic repair
and merge once required review is clean, user approval and merge for
[user-gated changes](pr-review.md#user-gated-changes).

## Escalation

A worker reports the specific decision or repeated failure with evidence and a
recommendation, then continues unblocked work. No fixed-format packet is needed.
The owner handles small follow-up fixes directly and resumes the worker only
when substantive work remains.

## Review tiers

[pr-review.md](pr-review.md) is the only review policy. Ordinary changes need no
independent reviewer. Broad work gets one; consequential work retains the
stronger general and focused review. Delegation itself does not increase risk.

## Recording it

Report the result, focused checks and any unresolved blocker briefly. No separate
delegation log, transcript or file-by-file completion form is required.
