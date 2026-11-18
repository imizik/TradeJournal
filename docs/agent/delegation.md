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

## Cheaper hands

Before starting a worker, use the cheapest one whose output a check can verify.
The owner chose (2026-11-17) to let Google-plan Hydrogen work in this repo on
the same footing as Codex; briefs still never paste secrets or real data.

- **Hydrogen builder** (Google plan, its own throwaway worktree): it runs its
  own lint/typecheck/test loop, then the owner reads the full patch, reruns the
  checks and opens a normal PR. It moves up one level after three clean patches
  at the current one (merged without the owner rewriting them), and drops back
  a level after one that had to be rewritten or reverted:
  1. tests, copy, renames, docs fixes;
  2. small features and multi-file refactors that existing tests cover;
  3. first drafts of larger features that the owner finishes.

  Every level stays within the never-delegate list below. A new session starts
  at level 1 unless the PR records show otherwise.
- **Hydrogen reader:** read-only surveys and second opinions, checked against
  the code before use; never a required review.
- **Sonnet worker:** bounded UI work. Opus is for design, integration and
  consequential work. Codex Luna or Sol are backups when the Google quota is
  spent, on the Codex allowance.

Never hand to Hydrogen or a cheap worker: money/FIFO/fills, Robinhood access,
auth, secrets, deployment, migrations, CI or verification tooling, agent rules
or settings, test safeguards such as the database pin, copilot tool lists,
destructive data changes, or real data. Delegation does not lower the review
tier; worker PRs get the review their tier needs, and delegation adds no extra
review.

## Review tiers

[pr-review.md](pr-review.md) is the only review policy. Ordinary changes need no
independent reviewer. Broad work gets one; consequential work retains the
stronger general and focused review. Delegation itself does not increase risk.

## Recording it

Report the result, focused checks and any unresolved blocker briefly. No separate
delegation log, transcript or file-by-file completion form is required.
