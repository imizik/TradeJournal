# Codex delegation workflow

This is the repository's one policy for Codex model roles and delegation.
`CLAUDE.md` gives the short trigger; `AGENTS.md` remains a pointer to that
working agreement. Keep task-specific implementation contracts in their
feature docs, not duplicated here.

## Choose the main agent

Prefer **Sol as the main agent for substantial work**: new features,
refactors, difficult debugging, deployment changes, and work spanning several
subsystems. Sol owns understanding the request, setting scope, resolving
consequential decisions, integrating results, and checking completion. Keep
that context with Sol throughout the task; do not depend solely on Luna
recognizing when it needs stronger reasoning.

Use **Luna directly for small tasks with clear requirements**, such as a
localized fix, mechanical edit, or focused lookup. A clear feature contract
can make implementation suitable for a Luna worker without making Luna the
preferred main agent for the whole feature.

These are workflow preferences, not an automatic model switch. If substantial
work has already started on Luna, involve an available Sol subagent before
committing to the scope or consequential decisions, and have Sol review the
result. Continue settled work in the same chat. If Sol cannot be spawned,
provide a concise handoff for the user to switch the main chat to Sol or
continue in a Sol chat; do not claim the selected model changed.

## When to delegate

Sol may finish a feature directly. Delegate when a meaningful piece has a
clear outcome and boundary, or independent investigation can improve speed
or keep noisy output out of the main context. Do not spawn workers merely
because a task is substantial. When delegation helps, assign one accountable
Luna worker per bounded outcome. The worker owns focused exploration,
implementation, ordinary debugging, and its deterministic checks through
completion.

Sol first reads enough to identify the requested scope, its prerequisites,
and its risk, and to settle decisions needed before implementation. Avoid
duplicating the worker's routine exploration. The handoff names one outcome,
one roadmap ID when applicable, the boundary, and
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

The recommended main model is Sol for substantial work and Luna for small,
clear tasks. The project does not pin its lead model: new chats inherit the
user's `~/.codex/config.toml` default, and the Desktop model picker can choose another
model. When Sol is selected, spawned agents default to Luna at medium effort;
the project caps spawned threads at two, excluding the lead. These are
defaults, not an automatic scheduler. A trusted repository is required for
project agent settings to apply. Check the active chat's available subagents
before promising delegation.

Codex discovers supported subagents from the session and delegates through
its agent tools. See the official [subagents guide](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
for supported configuration and client behavior. Do not claim that a model
default alone forces every task onto Luna.

## Sol's decision boundary

When Sol is the active lead, Sol retains decisions where ambiguity or
consequence matters: architecture, PnL and FIFO semantics, fill deduplication,
account identity, time and price provenance, nullable-data correctness,
migrations, security, and production actions. Applying an established rule is
ordinary execution; changing or inventing the rule needs Sol. Sol can delegate
inspection, evidence collection, isolated test fixtures, documentation
mechanics, and execution after resolving the decision. If Luna is the active
lead and one of these decisions is unclear, pause dependent work and consult
an available Sol subagent using the escalation packet below. Request a manual
model switch or a Sol chat only if that capability is unavailable. Continue
independent work; do not imply Codex switches the active model by itself.
The handoff must say which parts are decided and which are delegated; the
worker must not turn an unresolved semantic choice into an implementation
assumption.

Roadmap work follows the selected item's status and contract. Do not reorder
the board or implement adjacent items by implication. C4.6 is a historical
example of a bounded item: implement only the open-interest change described
in its [Done-when contract](../charts-roadmap.md#phase-4--options-positioning-on-the-chart),
and preserve the unavailable-session and no-provider-request requirements.
This example does not promote it or change execution order. C5.2 illustrates
work requiring Sol's review: removing production ingress requires approval of
the removal list and deployment changes, plus the C5.1 live phone prerequisite.
Check the current roadmap state rather than starting from the item label alone.

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
useful context or silently change the scope. If Luna is the active lead,
send the same packet to an available Sol subagent and apply its decision in
the current chat. If no Sol subagent is available, give the packet to the user
for a manual model switch or a Sol chat. If the user must decide, present the
concrete options and keep dependent work paused.

## Verification and review

Run deterministic checks before any separate review. Follow
[`verification.md`](verification.md) and the selected feature's acceptance
criteria; use `scripts/verify.sh --fast` during work and the normal full suite
before reporting completion when required by the repository agreement. A
frontend interaction needs its specified browser evidence. A fixture, browser,
live-provider, deployment and user-observed result are separate evidence
layers; report only the layers actually observed. Never replace a required
check with an informal review.

Do not start a separate reviewer automatically. Sol remains accountable for
the integrated result: check scope, the relevant diff, the completion report,
and acceptance evidence. Read enough code to evaluate correctness rather than
accepting the worker's summary alone; avoid repeating its entire exploration.
A focused Luna review is useful only when a specific independent question
remains after checks. Sol personally reviews
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
