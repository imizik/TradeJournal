# Working agreement

Shared by Codex, Claude Code and other coding agents. `AGENTS.md` points here.
TradeJournal is a single-user trade journal, reconciliation system, charting
workspace and bounded research/practice environment. The repository is the
source of truth; fix relevant documentation when behavior changes.

## Current product priority

On October 22, 2026 the owner set [TradeJournal's end goal](docs/product-roadmap.md#end-goal--october-22-2026):
first prove that position alerts and Radar help, then connect the loop. Weigh
new work against it.

The owner selected **Dots functionality first on October 11, 2026**. Before
selecting new roadmap work, read [the shared priorities](docs/product-roadmap.md#selected-priorities--october-11-2026)
and [Dots delivery board](docs/agent/dots-integration.md#current-delivery-board);
the board holds current status and next work, so it is not restated here.
Detailed feature contracts still own scope and acceptance; this priority does
not activate services or broaden grants.

## Work directly; look up only what you need

Read the affected code and tests first. Use [the documentation index](docs/agent/README.md)
only to find a relevant contract or unfamiliar subsystem; it is not a reading
checklist. Read the relevant domain rules before changing financial semantics,
and environment/deployment guidance before acting on real data or services.

Do the work yourself unless independent pieces clearly justify delegation.
No automatic Sol/Luna handoff, model escalation, new chat or completion template.
The current owner remains responsible for scope and completion; use the user's
selected model. [Codex](docs/agent/codex-workflow.md) and
[Claude](docs/agent/delegation.md) have short optional delegation notes.

## Choose the process by consequence

Classify the actual behavior and blast radius, not file count or the fact this
is a trading app. [Review policy](docs/agent/pr-review.md) supplies the detail.

- **Ordinary, bounded work:** localized fixes, UI tweaks, routine tests and
  documentation. Make the smallest change, run focused checks, push/update the
  PR, repair actionable failures and finish through passing CI and automatic
  merge. No mandatory subagent, independent review or full local suite.
- **Broad work:** cross-system features or refactors need relevant integration
  coverage and one independent reviewer. Broader tests follow affected behavior,
  not every layer in the system.
- **Consequential work:** money/FIFO/fills/account correctness, destructive or
  real-data mutation, auth/security, migrations, deployment, and verification,
  review or CI policy/tooling retain the stronger review and full applicable
  verification in the shared guides. Small diffs are not an exemption here.

For changed UI, inspect the affected screen in a running app and exercise any
changed interaction. For a bug, use a focused reproducer/regression when useful.
Do not prove unrelated providers, deployments or user habits. Preserve applicable
feature-specific safety and acceptance gates; fixture proof is not live proof.
[Verification](docs/agent/verification.md) is a reference, not a mandatory read.

## Keep the change small

- Prefer the existing pattern and the most straightforward fix.
- No new abstraction, config flag, dependency, contract document or speculative
  future-proofing unless requested or necessary for the current outcome. Explain
  a necessary addition briefly; do not add it just to anticipate future work.
- No adjacent cleanup or workflow redesign. After repeated failed fixes, revisit
  the diagnosis instead of adding layers or restarting the same repair loop.
- Batch independent reads/checks. Reuse passing evidence when inputs are unchanged.
- Freeze a complete candidate before CI. Do not catch up to unrelated main changes
  unless conflicts, changed dependencies or branch requirements make it necessary.
- Communicate meaningful findings, blockers and completion briefly. Skip routine
  command narration and repeated unchanged waiting updates.

## Delivery

Develop on a branch, never directly on `main`. Pushes, PR updates and bounded
repairs are authorized for both Codex and Claude Code. Ordinary (tier 0) PRs
are authorized for automatic repair and squash merge under the
[PR completion rules](docs/agent/pr-review.md#automatic-repair-and-merge).
Broad (tier 1) and consequential (tier 2) PRs still require the user's approval
and merge; never merge or enable auto-merge for them. This policy change is
itself tier 2 and must be left for the user to merge.
CI remains enabled for every PR; only call work merge-ready after required checks
pass on its final head and any required review is complete. Keep owning ordinary
PRs while CI is pending; if interrupted or blocked, report that state honestly.
Do not rerun a failure until it passes without diagnosing it, weaken tests, or
conceal missing proof.

Use `bash scripts/setup.sh` when dependencies are missing, `bash startdev.sh`
to run the app, and the focused commands in the verification reference for
ordinary work. Full `bash scripts/verify.sh` is for broad/consequential coverage
when appropriate; CI can provide that coverage without duplicating it locally.

**Merging to main can deploy to production.** See
[automatic deployment](deploy/README.md#automatic-deployment) before release or
schema work. Preserve its backup, migration and market-hours safeguards.

## Hard constraints

- Never expose or tunnel the production private API (8080/8000). Its default
  profile has no auth and production remains private. A separately approved
  isolated sample trial may publish only its authenticated assistant frontend;
  see the cloud-browser contract for its data and namespace boundaries.
- Never weaken the database pin in `backend/tests/conftest.py`. Without it the
  test suite writes to whatever `DATABASE_URL` resolves to, including the
  production VPS database.
- A `DATABASE_URL` pointing at a hosted Postgres is a real database.
  `resync-all` deletes fills; against any hosted database it refuses unless
  the request names the target. Check `GET /health` to see which database you
  are on. (`rebuild-all` only recreates derived trades and is not destructive.)
- Keep `docs/agent/` true when scope changes materially.
  `backend/tests/test_docs_links.py` fails when a document names a file or a
  heading that no longer exists, and `backend/tests/test_docs_freshness.py`
  warns (does not fail) when the drift pass is overdue. Neither can see a
  sentence that is merely no longer true — that pass is
  `.claude/skills/docs-drift/SKILL.md`. A daily cloud routine runs it and opens
  a pull request, so do not stop other work to run it.
