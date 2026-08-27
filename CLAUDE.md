# CLAUDE.md

Working agreement for Claude in this repository. Durable knowledge about the
system lives in `docs/agent/` so that Claude and Codex read the same facts;
this file says how to work here, not what the system is.

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
| `docs/agent/feature-map.md` | Which file owns a feature |

Read what the task needs, not all four. The repository is the source of truth;
if a document disagrees with the code, the code wins and the document gets
fixed in the same change.

## Verification is not optional

```bash
bash scripts/verify.sh --fast   # while working
bash scripts/verify.sh          # before saying it works
```

Do not report a change as working on the strength of reading the diff. If a
change lands somewhere the suite does not cover — any frontend rendering, any
live external integration — say so explicitly and describe what you did verify
instead. `docs/agent/verification.md` lists the gaps honestly; use it.

CI runs the same checks on every pull request.

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

## Hard constraints

- Never expose or tunnel the private API (8080/8000). It has no auth. Only
  port 8090, the TradingView ingress, is safe to tunnel.
- Never put private API keys or unrestricted database credentials in
  `backend/.env.tradingview`.
- Never weaken the database pin in `backend/tests/conftest.py`. Without it the
  test suite writes to whatever `DATABASE_URL` resolves to, which is the
  hosted Neon database on a normally configured machine.
- A `DATABASE_URL` pointing at Neon is a real database. Destructive operations
  (`resync-all`, `rebuild-all`) belong on a branch database.
- Keep `CLAUDE.md`, `AGENTS.md`, and `docs/agent/` consistent when scope
  changes materially.
