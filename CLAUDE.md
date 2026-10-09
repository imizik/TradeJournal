# CLAUDE.md

Working agreement for coding agents in this repository — Claude Code, Codex,
anything else. `AGENTS.md` points here instead of restating it, so there is
one copy of the agreement and no second one to drift. Durable knowledge about
the system lives in `docs/agent/`; this file says how to work here, not what
the system is.

## What this is

A local-first trade journal and reconciliation system for Robinhood and Webull
trading history. It ingests fills, rebuilds FIFO trades, tracks open positions,
enriches fills and trades with market context, supports AI review, and produces
reconciliation and market-report artifacts. It also carries two separate
domains: Strategy Lab (version-controlled Pine research) and a TradingView
live-alert loop. Stocks and options, multiple accounts, no auth, single user.

## Read before changing things

| File | For |
|---|---|
| `docs/agent/architecture.md` | Processes, data flow, persistence, cost constraints |
| `docs/agent/domain-rules.md` | Invariants — read before touching PnL, FIFO, fill import, enrichment, Strategy Lab, TradingView, the strategy factory, chart price basis |
| `docs/agent/verification.md` | How to prove a change works |
| `docs/agent/pr-review.md` | Automatic cross-provider review, bounded repair loop, readiness and subscription setup |
| `docs/agent/codex-workflow.md` | Sol-led substantial work, bounded Luna assignments, escalation, and completion reports |
| `docs/agent/environments.md` | Which database you are on; destructive-operation rules |
| `docs/agent/background-jobs.md` | Job ownership, worker processes, restart recovery |
| `deploy/README.md` | Ubuntu services, private access, release installation and rollback |
| `docs/agent/feature-map.md` | Which file owns a feature, how to reach it in the UI, what proves it |
| `docs/agent/delegation.md` | Claude Code on Opus: what to hand to the Sonnet `engineer` and `reviewer` subagents, the brief, escalation and review tiers |
| `docs/product-roadmap.md` | Future trading-improvement workflow: reflections, weekly commitments, playbooks, planned risk and evidence-gated experiments; preserves active feature-roadmap priorities |
| `docs/charts-roadmap.md` | The Charts epic: what to build next on `/charts`, in order, and what not to build |
| `docs/agentic-trading-roadmap.md` | Proposed agentic practice track: frozen decisions, alerts, paper outcomes, daily routine and later research gates; first three bounded slices |
| `docs/agent/a3-implementation-contract.md` | A3 daily routine, isolation, benchmark, disabled scheduling and live acceptance gates |
| `docs/agent/practice-policy.md` | Selected P0 practice contract, synthetic plan/outcome, and observed source time/units |
| `docs/agent/dots-integration.md` | Future Dots handoff: local A1 tools, scoped roles and independent-runner isolation, proposed follow-through capabilities, authentication gates and the private API boundary |
| `docs/agent/cloud-browser-auth-contract.md` | Proposed cloud-browser authentication and permissions: preserve owner Tailscale access, separate restricted assistant login, sample-data browser trial and live exposure gates; private implementation, public access disabled |
| `docs/charts-deep-history.md` | C0.0's history/cache/API/warmup contract and its required evidence (shipped; the code and `docs/charts-workspace.md` are current) |
| `docs/symbol-info-roadmap.md` | The symbol info panel beside the chart (news, earnings, stats, forecast): probed data sources, budgets, build order |
| `docs/swing-strategy-roadmap.md` | Swing families (1–16 sessions) in the factory, the after-close practice loop (signal, phone, Take/Skip, shadow trade), the setups board and confluence scan, macro/news/earnings as-of rules, stages from research to live |
| `docs/strategy-workbench-roadmap.md` | A later interactive page over the factory: explore on discovery data only, the exploration log, freezing candidates |

Read what the task needs. The repository is the source of truth;
if a document disagrees with the code, the code wins and the document gets
fixed in the same change.

In Codex, prefer Sol as the main agent for substantial features, refactors,
difficult debugging, and deployment changes. Sol owns scope, consequential
decisions, integration, and final verification; delegate clear, bounded work to
Luna when it helps. Use Luna directly for small tasks with clear requirements.
Delegation is optional: Sol can complete a feature itself. Follow
[`docs/agent/codex-workflow.md`](docs/agent/codex-workflow.md), including its
fallback when a substantial task has already started on Luna.

## Verification is not optional

```bash
bash scripts/setup.sh           # clean clone -> runnable
bash scripts/verify.sh --fast   # while working
bash scripts/verify.sh          # before saying it works
bash startdev.sh                # run the app
```

Do not report a change as working on the strength of reading the diff. If a
change lands somewhere the suite does not cover — any frontend rendering, any
live external integration — say so explicitly and describe what you did verify
instead. `docs/agent/verification.md` lists the gaps honestly; use it.

CI also checks Postgres migration paths/roles and the native Ubuntu deployment;
the local verification script does not run those checks.

A Claude Code cloud session starts from a bare clone with no `backend/.venv`
or `frontend/node_modules`. Run `bash scripts/setup.sh` before any check, or
every check fails on missing tools rather than on the change.

**Merging to `main` deploys to production.** Once CI and the Deployment
package pass on the merge commit, the VPS installs it by itself within about
10 minutes. On weekdays between 09:25 and 16:15 New York time it waits for the
close unless the PR carries the `deploy-now` label. Schema changes wait for a
person. A PR is ready to merge only when it is ready to go live; see
[automatic deployment](deploy/README.md#automatic-deployment).

## Independent review before ready work

When implementation and required checks are ready, commit the feature branch
and run the [shared independent review loop](docs/agent/pr-review.md).
Codex uses Claude Code CLI; Claude uses Codex CLI. Keep the owning session
active: inspect findings, fix valid issues, verify, commit and re-review.
Three reviewer passes are the automatic limit. A human may explicitly authorize
one additional pass through the documented extension; preserve all attempts. Authentication, quota,
missing evidence and unresolved disputes are explicit incomplete outcomes.
Never reset the budget or switch billing/providers to get a clean result.

After clean review, push the feature branch, open/update a draft PR, publish
its receipt and wait for CI through the runner's `finish` command. The user
has authorized these branch pushes, PR updates and review repairs as the
normal workflow. Merge and auto-merge remain the user's actions.
Completion hooks enforce pending work for newly started/trusted local sessions;
existing sessions must follow the same command workflow explicitly.

## Operating style

- Read only what the task needs. Use these docs to orient rather than
  exploring.
- Batch searches, file reads, and cheap checks instead of many tiny commands.
- Avoid repeated `git status`, broad tree walks, and unrelated spelunking.
- Find the root cause first, then make the smallest safe fix.
- Do not ask obvious follow-ups when the fix is local and low-risk.
- Keep narration minimal; do not explain routine shell and file operations.
- Prefer cheap targeted validation unless the blast radius requires more.
- Avoid unrelated refactors, formatting churn, and duplicated UI/table logic.
- Final summaries stay brief: what changed, what was verified, what risk remains.
- In a Claude Code session on Opus, act as the lead: hand bounded execution to
  the Sonnet `engineer` subagent and keep judgment, high-risk review and pushes
  (`docs/agent/delegation.md`). Do small, sequential work directly.

## Extra care required

PnL math, FIFO reconstruction, Gmail/email parsing, fill dedupe, account
identity, reconciliation outputs, nullable enrichment fields, and frontend
data-fetch patterns that can create N+1 calls. When PnL looks wrong, start at
`backend/app/engine/reconstructor.py` and the fill history — not at the UI.

## Parallel work

Develop on a branch, never directly on `main`. Generated artifacts
(`.next/`, `*.tsbuildinfo`, `next-env.d.ts`, `backend/data/`) are gitignored so
parallel branches do not fight over them. Alembic revisions are the one place
parallel work collides: two branches each adding a revision creates two heads,
and `test_schema_migrations.py` fails on that deliberately.

## Hard constraints

- Never expose or tunnel the private API (8080/8000). It has no auth. There is
  no public application ingress in the current deployment.
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
  fails when the drift pass is overdue. Neither can see a sentence that is
  merely no longer true — that pass is `.claude/skills/docs-drift/SKILL.md`,
  and running it is what clears the freshness test.
