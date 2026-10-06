# Codex delegation workflow

This is the repository's one policy for bounded Codex implementation work.
`CLAUDE.md` gives the short trigger; `AGENTS.md` remains a pointer to that
working agreement. Keep task-specific implementation contracts in their
feature docs, not duplicated here.

## When to delegate

For a non-trivial, bounded implementation request, Sol leads and assigns one
Luna worker. The worker owns focused exploration, implementation, ordinary
debugging, and the task's deterministic checks through completion. This avoids
paying Sol to rediscover the same code while keeping one owner accountable for
the result.

Sol first reads only enough to identify the requested scope, its prerequisite
and its risk. Do not do a broad code investigation before delegating. The
handoff names one outcome, one roadmap ID when applicable, the boundary, and
the acceptance evidence already specified in the repository. Luna inspects the
relevant code and tests, makes the smallest change within that boundary, runs
the appropriate checks, and reports the result.

For a trivial, sequential edit, the active agent should do it directly;
spawning a worker would cost more coordination than it saves. Use one writer
for a shared file or subsystem; workers do not spawn nested workers by default.
Assign the existing checkout to that owner; use an isolated worktree only for
independent concurrent work, not a new checkout for each command.
Delegate fact gathering or mechanical execution even when Sol keeps the
decision, if that makes the task safer or faster.

Start a fresh Codex chat for each bounded item so it has a clean scope and
history. Spawn with `fork_turns=none` where supported and provide a short,
self-contained assignment that points to the repository agreement and contract.
Avoid a full-history fork for routine implementation: it inherits Sol's model
and can defeat the intended cost boundary. Close or stop a finished worker
where the client supports it; do not delete its history or create a scheduled
monitor by default.

## Model and configuration

The intended defaults are Sol (`gpt-6.1-sol`, medium) as lead and Luna
(`gpt-6-luna`, medium) as the single worker. Repo-local configuration enables
supported subagents and caps spawned threads at two, excluding the lead;
these values are defaults, not an automatic scheduler. A trusted repository
and a fresh chat are required for repo configuration to apply, and the
Desktop model picker can override the selected model. Check the active chat's
available subagents before promising delegation.

Codex discovers supported subagents from the session and delegates through
its agent tools. See the official [subagents guide](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
for supported configuration and client behavior. Do not claim that a model
default alone forces every task onto Luna.

## Sol's decision boundary

Sol retains decisions where ambiguity or consequence matters: architecture,
PnL and FIFO semantics, fill deduplication, account identity, time and price
provenance, nullable-data correctness, migrations, security, and production
actions. Applying an established rule is ordinary execution; changing or
inventing the rule needs Sol. Sol can delegate inspection, evidence collection,
isolated test fixtures, documentation mechanics, and execution after resolving
the decision.
The handoff must say which parts are decided and which are delegated; the
worker must not turn an unresolved semantic choice into an implementation
assumption.

Roadmap work follows the selected item's status and contract. Do not reorder
the board or implement adjacent items by implication. For example, C4.6 is a
future eligible bounded item: implement only the open-interest change described
in its [Done-when contract](../charts-roadmap.md#phase-4--options-positioning-on-the-chart),
and preserve the unavailable-session and no-provider-request requirements.
This example does not promote it or change execution order. C5.2 remains
blocked on observing C5.1 deliver a live phone alert; it also removes a
production ingress and needs Sol's production review. Do not start it from the
roadmap label alone.

A representative assignment, once the user selects C4.6: "Read the working
agreement and C4.6 contract. Own stored-snapshot comparisons, the ladder/card
display, tests and required docs. Keep provider polling, recorder behavior,
migrations and adjacent items out of scope. Escalate undefined treatment of
a new strike rather than assuming a missing baseline is zero. Return the
completion report below." Sol answers that specific question if raised;
Luna then continues implementation and verification in the same worker.

## Escalation

The worker escalates immediately when it finds unresolved semantics, a risk
outside the assigned boundary, or a conflict between the request, code and
repository contract. It also escalates after two distinct failed fixes for
the same issue. A missing local dependency or unavailable external service is
a blocker to report, not a failed fix.

The escalation is at most 250 words: state the decision needed, give the
focused file/section references and observed evidence, list viable options,
recommend one, and say what work can safely continue. Sol resolves only that
decision, then resumes the same worker with `followup_task`; do not discard
useful context or silently change the scope. If the user must decide, present
the concrete options and keep dependent work paused.

## Verification and review

Run deterministic checks before any separate review. Follow
[`verification.md`](verification.md) and the selected feature's acceptance
criteria; use `scripts/verify.sh --fast` during work and the normal full suite
before reporting completion when required by the repository agreement. A
frontend interaction needs its specified browser evidence. A fixture, browser,
live-provider, deployment and user-observed result are separate evidence
layers; report only the layers actually observed. Never replace a required
check with an informal review.

Do not start a separate reviewer automatically. For ordinary work, Sol checks
scope, the completion report and acceptance evidence; inspect only the necessary
diff when a discrepancy warrants it. A focused Luna review is useful only when a
specific independent question remains after checks. Sol personally reviews
high-consequence changes and unresolved semantic risk. The hosted GitHub
reviewer is a separate service with independent routing; do not promise that
it will select Luna or treat it as a required check.

## Completion report

Report in at most 300 words:

- the outcome and the files changed;
- commands run and their actual results;
- acceptance evidence observed and any unverified layer;
- remaining blocker or risk, if one exists.

Keep it concise and omit raw logs. Do not claim that work is merged, deployed,
or live unless that state was directly verified. Stop when the assigned item
and its required documentation are complete; do not add adjacent cleanup.

## Check whether it saves usage

Compare several similarly scoped completed tasks using allowance before/after,
not API prices or raw token totals. Note other account activity and resets.
Track rework, escapes and how often Sol must repeat exploration or rewrite the
worker's change. If those dominate, tighten the boundary or let Sol own that
class of work. Short summaries and fewer Sol turns are useful signals, not
proof of subscription savings. See [current plan usage](https://learn.chatgpt.com/docs/pricing).
