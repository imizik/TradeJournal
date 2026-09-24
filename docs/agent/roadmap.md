# Roadmap

Where the engineering foundation stands, what is deliberately not being built,
and the decisions worth not relitigating. A planning document, not a
specification. The principle throughout: **raise agent autonomy only as fast
as the verification layer earns trust.**

## Where we are

Reproducibility, verification, environment isolation and deployment are all in
place. What each of them proves is documented where it is enforced, not here.

- **Setup and verification.** A fresh clone with no credentials can be set up,
  verified and run, and CI runs the same checks on every pull request. What
  that covers and what it does not is in [verification.md](verification.md).
- **Rules CI enforces**, rather than documentation an agent can miss.
  `test_import_boundaries.py` holds the public ingress to a module allowlist
  and keeps the pure engine free of network and database imports; `ruff` covers
  the backend for unused and undefined names. Both run ahead of the suite.
- **Frontend verification.** `backend/scripts/seed_dev_data.py` builds a
  deterministic dataset through the real reconstructor and `frontend/e2e/`
  asserts its values reach the DOM. Smoke depth on purpose: filtering,
  sorting, forms, editing and Strategy Lab are not covered, and there is no
  component-level unit coverage. Deepen when a regression justifies it.
- **Environments.** `GET /health` names the database a process is on,
  `resync-all` refuses a hosted database unless the request names it, Alembic
  is the only schema authority, and three database roles separate migration,
  application and TradingView-ingress access. See
  [environments.md](environments.md).
- **Postgres in CI.** `test_postgres_parity.py` and
  `test_postgres_migration_paths.py` run against a `postgres:16` service
  container, with no secret and no hosted branch. Most other modules still
  build their own SQLite engine, so only those two run on Postgres;
  broadening it means a dialect-parametrized engine fixture, worth doing only
  if a dialect bug slips through where they do not look.
- **Deployment.** Native Ubuntu services and timers on a VPS, with PostgreSQL
  on loopback. Installation, rollback and the private-access rules are in
  [the deploy README](../../deploy/README.md).
- **Parallel agents.** Two agents work this repository daily on separate
  branches. Generated artifacts are gitignored so branches do not fight over
  them, and `test_schema_migrations.py` fails on two Alembic heads, which is
  the main way parallel branches collide here.

## Still open

- **Staging.** No persistent staging host. Staging and production must not
  share a database, credentials, webhook tokens, Gmail state or
  external-integration identity (`environments.md`).
- **Review that is required rather than advisory.** An independent reviewer
  exists — the Codex GitHub App reviews pull requests, and
  `.github/workflows/claude-review-fallback.yml` sweeps any head commit it
  leaves alone for twelve minutes — but `main` has no branch protection, so a
  pull request can still merge with no review at all (`verification.md`).
- **A convention for splitting work** so two agents do not both land in
  `reconstructor.py` in the same afternoon.

## Decided, with the reasoning worth keeping

**Same-second FIFO ordering.** Measured and settled in `70e54df`; it is no
longer an open question, but the caveat is.

The reconstructor's final tie-break is `str(fill.id)`, a random UUID — stable
across ordinary rebuilds, not stable across `POST /fills/resync-all`, which
re-imports fills with new ids. Measured against 4,326 real fills and 1,556
trades, it is worth **three cents**, on one open MSFT position: every
candidate ordering (`raw_email_id`, price ascending, price descending)
produces identical realized PnL on every closed or expired trade, and 104 of
the 105 trades in same-timestamp groups reconstruct identically regardless.

Keeping `str(fill.id)` — not because it is principled but because no
alternative is. `raw_email_id` is a Gmail message id: chronological only among
Gmail-sourced fills, arbitrary against a Webull or manual one.

That is a fact about the current data, not about the design. A partial exit
against same-second lots at different prices could move real money at any time
and nothing would flag it, so re-measure with
`backend/scripts/analyze_tiebreak_impact.py` rather than trusting this
paragraph. See
[domain-rules.md](domain-rules.md#known-same-timestamp-ordering-is-arbitrary).

**The app is not stateless**, and any future hosting decision inherits that.
Startup normalizes the Roth account and restores manual fills; background
jobs, the Gmail watch renewer and the TradingView analysis worker all expect a
long-lived process, and the database is a durable queue rather than a task
dispatcher (`architecture.md`). A scale-to-zero platform breaks that model.
The public TradingView ingress is the only process that may be
internet-reachable; the private API has no auth at all, and any host has to
preserve that split. Cost matters more than elasticity for a single-user app.

## Deliberately not doing

- Docker, until something makes it earn its place.
- Kubernetes, ever, for this workload.
- A multi-agent orchestration framework.
- Tests written to raise a coverage number.
