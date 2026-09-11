# Roadmap

Where the engineering foundation stands and what comes next. This is a
planning document, not a specification — reorder it freely. The principle
throughout: **raise agent autonomy only as fast as the verification layer
earns trust.**

## Where we are

Phase 1 (reproducibility and verification) is done. A fresh clone with no
credentials can be set up, verified, and run:

```bash
bash scripts/setup.sh && bash scripts/verify.sh && bash startdev.sh
```

CI runs the same checks on every pull request. What that currently proves,
and what it does not, is in [verification.md](verification.md).

## Phase 2 — Frontend verification (done)

Was the weakest link: typecheck, lint and build all pass on a React component
that is broken at runtime, and nothing proved a page renders.

Now in place: `backend/scripts/seed_dev_data.py` builds a deterministic
dataset through the real reconstructor, and `frontend/e2e/` asserts that its
values reach the DOM on the dashboard, trades list, trade detail, fills and
analytics. `scripts/verify.sh --e2e` runs them and CI has a Browser job.
Details and the traps involved are in [verification.md](verification.md).

Still shallow on purpose: these are smoke tests. Filtering, sorting, forms,
editing and Strategy Lab workflows are not covered, and there is no
component-level unit coverage. Deepen when a regression justifies it.

What it took, worth knowing before extending it:

1. **The fixture must be calendar-anchored.** An option's status depends on
   whether its expiration has passed, so hard-coded dates make a fixture whose
   meaning drifts: positions seeded as open silently become expired, taking
   their asserted P&L with them. Dates are offsets from the run date.
2. **CORS is load-bearing.** Client components fetch the API from the browser,
   so the e2e frontend origin has to be allowed or those pages hang on a
   loading state while server-rendered pages still pass.
3. **Never reuse servers.** A leftover server serves a stale build, which
   makes broken code pass.

## Phase 3 — Environments

Neon already hosts the database, so environment isolation should use Neon
branches rather than a second platform.

1. ~~**A dedicated `dev` Neon branch.**~~ Done. `GET /health` reports which
   database a process is connected to, `resync-all` refuses on any hosted
   database unless the request names the target, and the branch exists and is
   migrated to head. `backend/scripts/check_database.py` is the read-only
   preflight for pointing a worktree at it.

2. ~~**Alembic as the only schema authority.**~~ Done, and it was not on this
   list. Startup called `create_all()`, so the app repaired its own database on
   every boot. That is why the dev branch turned up stamped at `a4b5c6d7e8f9`
   with later tables already present — a state no migration produces and no
   clean container reproduces, where `upgrade` and `stamp` are both plausible.
   It also taxed every migration from `f1a2b3c4d5e6` on with `_table_exists`
   guards, cost `scripts/setup.sh` ~70 lines of stamp-or-upgrade logic, and
   blocked separate database roles outright — an app that issues DDL at startup
   cannot run as a DML-only role. Removing it immediately exposed a
   test-isolation leak that had been absorbed silently for as long as it
   existed.
3. ~~**CI migrates a `create_all`-built database.**~~ Done.
   `test_postgres_migration_paths.py` builds the states a real database is
   found in — unstamped and `create_all`-built, stamped part-way then extended,
   stamped at head, empty — and asserts what the migration chain and
   `check_database.py` do with each. The middle one is the shape the Neon dev
   branch was actually in and the one CI never had; it holds only because
   migrations from `f1a2b3c4d5e6` guard every object with `_table_exists`, and
   removing one of those guards was verified to fail the test. Still an
   ephemeral container, still no secret.

4. ~~**Separate database roles.**~~ Done, as three roles rather than four: a
   migration owner, an application role that cannot issue DDL, and the
   TradingView ingress restricted to `tradingview_alert`. Background workers
   share the application role — a fourth is real configuration complexity
   against no threat the app role does not already cover, and earns its place
   when a worker needs privileges the API should not have.

   `alembic` uses `MIGRATION_DATABASE_URL` when set and `DATABASE_URL`
   otherwise, so a single-role setup is untouched.
   `backend/scripts/setup_roles.py` creates the roles and then proves they are
   limited two ways: `has_table_privilege` across every table in `public`,
   which accounts for privilege reached through role membership, and
   connection probes that try what each role must be refused.

   Both checks were necessary, and each caught what the other missed. On the
   first real Neon branch every grant was correct and the ingress still read
   all 4,326 fills — through `neon_superuser`, which a console-created role
   belongs to and which the owner cannot revoke; such a role can only be
   deleted and recreated in SQL (`environments.md`). And a probe list naming
   `fill` and `account` passed a role holding `SELECT` on `trade`, because
   `trade` was not one of the samples.

   Applied and verified on the dev branch. On production the two halves are
   not deferrable on the same terms, and treating them as one is a mistake:

   The **application** role is worth having on production on its own merits,
   and is deferred here as sequencing rather than because it defends nothing.
   It bounds what an application-level bug can do: an injection or a vulnerable
   endpoint executes as whatever role the API connects with, and the difference
   between that being the schema owner and a DML-only role is the difference
   between `DROP TABLE` and a bad `SELECT`. None of that depends on where the
   API runs.

   Being localhost-only changes who can reach the API, not what a bug can do
   once reached. Nor does reaching it hand anyone the credential: `/health`
   drops the username, password and query string, and no route exposes
   `DATABASE_URL` — reading it takes OS access to the host, which is a
   different capability from talking to port 8080.

   The **ingress** role cannot, and `README.md` already requires it: port 8090
   is the only tunnelable port and is meant to be internet-facing, so an owner
   credential there is exposed whatever the private API does. The condition is
   not "once the API is hosted" but *before `TRADINGVIEW_DATABASE_URL` on
   production would otherwise hold the owner credential*. It is absent there
   only because the ingress is not pointed at production; pointing it there
   means running `setup_roles.py` against that branch first.

5. **Branch-per-PR** for migration testing: create a Neon branch from
   production schema, run `alembic upgrade head` against it, tear it down.
   This is where CI first needs a secret, so it is also where secret handling
   gets designed. Item 3 covers most of the migration-testing value without
   one; this earns its place when a PR needs a deploy preview or
   Neon-specific connection behaviour.
6. ~~**A Postgres CI run.**~~ Done. `test_postgres_parity.py` runs against a
   `postgres:16` service container in CI and covers the full Alembic chain,
   `ExactDecimal`'s NUMERIC path, and constraint enforcement. It immediately
   found two revisions that broke `alembic upgrade head` on Postgres — the
   documented Neon provisioning path did not work. See
   [verification.md](verification.md#postgres-parity).

   Still open: most test modules build their own SQLite engine, so only the
   targeted parity module runs on Postgres. Broadening that means a shared
   dialect-parametrized engine fixture, which is a wide refactor — worth doing
   only if a dialect bug slips through in an area the parity module misses.

## Phase 4 — Deployment

Deliberately unspecified. Choose the host when there is something to deploy
and real constraints to judge against. Decision criteria worth holding onto:

- **The app is not stateless.** Startup runs migrations-ish work
  (`create_all`, Roth normalization, manual-fill restore), and background
  jobs, the Gmail watch renewer and the TradingView analysis worker all expect
  a long-lived process. A scale-to-zero platform breaks the worker model —
  `docs/agent/architecture.md` notes the database is a durable queue, not a
  task dispatcher.
- **Two processes must stay separated.** The public TradingView ingress is the
  only thing that may be internet-reachable; the private API has no auth at
  all. Any hosting choice has to preserve that boundary.
- **Cost matters more than elasticity** for a single-user app. Neon egress is
  metered, which is why `FILL_LIGHT`/`FillOut` and batched job commits exist.
- Kubernetes is not warranted. Do not add it.

Sequence when you get here: staging deploy → smoke-verify staging → merge →
production deploy. Staging verification should reuse the Phase 2 Playwright
tests pointed at the staging URL.

## Phase 5 — Parallel agents

Only after one agent is reliably trustworthy. Groundwork already in place:
generated artifacts are gitignored so branches do not fight over them, and
`test_schema_migrations.py` fails on two Alembic heads, which is the main way
parallel branches collide in this repo.

Still needed: a convention for splitting work so two agents do not both touch
`reconstructor.py`, and a reviewer role that reads diffs rather than trusting
the implementer's own report.

## Open decision

This sits in a highest-risk area and is a judgment call, not a cleanup.

**Same-second FIFO ordering.** The reconstructor's final tie-break is
`str(fill.id)`, a random UUID. Stable across ordinary rebuilds, but
`POST /fills/resync-all` re-imports fills with new ids, so realized PnL
attribution for same-second fills can change after a resync. Multiple prints
of one order within a second are common. A deterministic tie-break (broker
sequence, `raw_email_id`, or import order) would fix it, but changing it
changes reported PnL on existing trades. See
[domain-rules.md](domain-rules.md#known-same-timestamp-ordering-is-arbitrary).
Run `backend/scripts/analyze_tiebreak_impact.py` against the target database
before making that decision.

## Deliberately not doing

- Docker, until deployment makes it earn its place.
- Kubernetes, ever, for this workload.
- A multi-agent orchestration framework.
- Tests written to raise a coverage number.
