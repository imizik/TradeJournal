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

1. **A dedicated `dev` Neon branch** separate from whatever holds real trading
   history, so exploratory and destructive work (`resync-all`, `rebuild-all`)
   has an obvious safe target. Today the only safety rail is the test-suite
   pin plus discipline.
2. **Branch-per-PR** for migration testing: create a Neon branch from
   production schema, run `alembic upgrade head` against it, tear it down.
   This is where CI first needs a secret, so it is also where secret handling
   gets designed.
3. **A Postgres CI run** for the backend suite. SQLite passes today, but
   dialect differences (JSON operators, constraint naming, case sensitivity)
   are invisible until they hit Neon.

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
