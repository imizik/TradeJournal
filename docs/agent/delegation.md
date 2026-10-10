# Delegation: lead and workers

How a Claude Code session started on Opus splits work with Sonnet workers.
The goal is to spend Opus on judgment, not to minimize total tokens. This is
native subagent definitions and this policy, not an orchestration framework
([roadmap.md](roadmap.md#deliberately-not-doing)). Other coding agents use their own delegation guide and the shared review policy.

| Piece | What it is |
|---|---|
| `.claude/agents/engineer.md` | Sonnet worker: owns one bounded task through implementation and verification, returns a short report or an escalation |
| `.claude/agents/reviewer.md` | Sonnet reviewer: reads a finished diff against the contract and `domain-rules.md`, returns verified findings |
| `.claude/agents/risk-reviewer.md` | Opus reviewer for tier-2 changes, run as separate general and focused invocations |

Profiles explicitly select their model and effort. Other subagents inherit the
client's defaults; the repo no longer forces a global Sonnet override. Reviewer
selection and observed model overrides are governed by [pr-review.md](pr-review.md).
Delegation shares the subscription allowance; measure savings rather than
inferring them from API prices.

## Who does what

**Delegate by default** to `engineer`, in one chunk per outcome:

- a roadmap item whose Done-when is clear, or a clear slice of one
- normal frontend and backend feature work, following existing patterns
- writing or extending tests; running and fixing verification
- mechanical refactors and renames
- routine debugging with a reproducible failure
- exploration whose answer is a conclusion, not a design ("where is X built",
  "which pattern does Y use"): give it to a worker, or to the built-in Explore
  agent when it is pure lookup

**The lead keeps:**

- architecture and data-model decisions, including schema migrations
- product behavior the contract leaves ambiguous (ask the user when it is
  theirs to decide)
- cross-system reasoning: a choice whose consequences span backend, jobs,
  deployment and the UI
- security, exposure and destructive operations: anything under `deploy/`, the
  TradingView ingress, `resync-all`, deleting or rewriting real data
- financial correctness: PnL, FIFO (`backend/app/engine/reconstructor.py`),
  fill import and dedupe, account identity, Gmail parsing, reconciliation
- debugging after a worker has failed twice
- targeted review of high-risk hunks, git push and PRs; the user alone merges

**Do it directly, without a worker,** when spawning costs more than it saves:
a fix of a few lines, a question answerable from one or two files, a follow-up
in an area the lead's context already holds, or a tight debug loop where every
step depends on judging the last output. Rule of thumb: under about ten tool
calls, or when the brief would be longer than the change, do it yourself.

Do not explore before delegating so as to write a perfect spec. If
`feature-map.md`, the roadmap item and `domain-rules.md` constrain the task,
the worker discovers the files. Read code yourself only to make a decision
that must be made before work can start.

Do not run parallel workers on overlapping files, and give at most one worker
an Alembic revision at a time (two heads fail `test_schema_migrations.py`).

## The brief

Short. The worker cannot see the conversation, so anything decided there has
to be in the brief.

```
OUTCOME: what is true when this is done (one or two sentences)
CONTRACT: the roadmap item ID or issue that defines Done-when
DECIDED: decisions already made that the worker must not reopen
DO NOT CHANGE: files, APIs, behaviors out of scope
ESCALATE IF: anything beyond the defaults in engineer.md (often: nothing)
VERIFY: the checks that must pass (default: the verify.sh modes for the layers touched)
COMMIT: yes on this branch / no
```

## Escalation

A worker that reaches a decision it should not make stops only the blocked
part, finishes everything else, and returns the escalation packet defined in
`.claude/agents/engineer.md` (decision, why it matters, existing behavior,
options, recommendation, what continues).

The lead answers the decision, not the exploration: read the packet, open the
cited lines if needed, decide, and **resume the same worker** with SendMessage
so it keeps everything it learned. Starting a fresh worker re-pays the cold
start and the exploration. Escalate to the user only what is theirs: product
behavior, spending, production data.

## Review tiers

Use the shared [native pre-PR review policy](pr-review.md) as the only tier table.
Most changes use a fresh Sonnet `reviewer`. A tier-2 change uses an Opus
`risk-reviewer` plus a focused invocation; the lead reads the risky hunks and
verifies acceptance evidence. The owner fixes findings and gets
them rechecked before publishing ready work. Small UI, test or refactor diffs
are not automatically exempt. CI remains required; the user alone merges.

## Recording it

Include the review evidence required by the shared guide. Also record: `Delegation: worker | direct; escalations: N; review tier: 0/1/2`.
It costs nothing and is what makes the pattern measurable from git history:
how often workers finished without rework, which escalations were real, and
whether tier-0 changes ever needed a fix later.

## Worked example: C4.6

[C4.6](../charts-roadmap.md#delegation-readiness) (open-interest change by
strike) is worker-ready: the item has a Done-when, `feature-map.md` names the
recorder, the ladder and the strike card, and the label rules are in the
roadmap's rules.

1. Lead, without exploring: spawns `engineer` with OUTCOME "C4.6 as specified",
   CONTRACT `C4.6`, DECIDED "read stored snapshot rows only; no provider
   call", DO NOT CHANGE "the recorder's write path and its schedule", VERIFY
   "--backend and --e2e", COMMIT yes.
2. Worker finds the recorder's tables, the ladder route and the e2e spec,
   writes the fixture with a missed session and a new strike, and implements
   the backend change and the ladder column. Suppose (illustrative) it finds a
   session with no rows that the recorder never marked unavailable, while the
   item only defines the marked case. That changes what the user sees, so it
   escalates: options "treat both as unavailable" or "treat a missing session
   as not recorded and compare with the last recorded one", recommending the
   first because the item forbids measuring against an older session. It
   finishes the ladder UI and the tests for the defined case meanwhile.
3. Lead reads the packet, agrees with the recommendation in one line and
   resumes the same worker.
4. Worker finishes, runs verification and reports. Tier 1: the lead spawns
   `reviewer`, reads its findings, pushes and opens the PR.
