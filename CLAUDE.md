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
| `docs/agent/domain-rules.md` | Invariants — read before touching PnL, FIFO, fill import, enrichment, Strategy Lab, TradingView |
| `docs/agent/verification.md` | How to prove a change works |
| `docs/agent/environments.md` | Which database you are on; destructive-operation rules |
| `docs/agent/background-jobs.md` | Job ownership, worker processes, restart recovery |
| `deploy/README.md` | Ubuntu services, private access, release installation and rollback |
| `docs/agent/feature-map.md` | Which file owns a feature, how to reach it in the UI, what proves it |

Read what the task needs. The repository is the source of truth;
if a document disagrees with the code, the code wins and the document gets
fixed in the same change.

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
15 minutes. On weekdays between 09:25 and 16:15 New York time it waits for the
close unless the PR carries the `deploy-now` label. Schema changes wait for a
person. A PR is ready to merge only when it is ready to go live; see
[automatic deployment](deploy/README.md#automatic-deployment).

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

- Never expose or tunnel the private API (8080/8000). It has no auth. Only
  port 8090, the TradingView ingress, is safe to tunnel — and it only runs when
  `TRADINGVIEW_INGRESS_ENABLED=true` is set for the launcher.
- Never put private API keys or unrestricted database credentials in
  `backend/.env.tradingview` or the VPS `/etc/tradejournal/tradingview.env`.
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
