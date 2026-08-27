# Verification

How to prove a change works in this repository. The standard is evidence, not
"this should work".

## The commands

```bash
bash scripts/setup.sh          # clean clone -> runnable (idempotent)
bash scripts/verify.sh         # everything CI runs
bash scripts/verify.sh --fast  # tests + typecheck, no builds (inner loop)
bash scripts/verify.sh --backend
bash scripts/verify.sh --frontend
bash scripts/verify.sh --e2e   # browser smoke tests only (slowest)
```

`verify.sh` runs every check even after one fails, so one run reports every
problem. It exits non-zero if any check failed.

On Windows, run these through Git Bash or WSL. `startdev.ps1` remains the
native PowerShell launcher for the app itself.

## What each check covers

| Check | Command | Catches |
|---|---|---|
| Backend tests | `cd backend && pytest -q` | FIFO reconstruction, email parsing, routes, Strategy Lab, TradingView contract/persistence/analysis, Webull, schema drift |
| Frontend typecheck | `cd frontend && npm run typecheck` | Type errors across app/, components/, lib/ |
| Frontend lint | `cd frontend && npm run lint` | React Hooks defects, dead code, Next anti-patterns |
| Frontend build | `cd frontend && npm run build` | Server-component and route errors typecheck alone misses |
| Browser smoke | `cd frontend && npm run e2e` | Whether pages actually render real data |

CI (`.github/workflows/ci.yml`) runs the same checks on every pull request, in
two parallel jobs. Agent verification is not the only signal.

## Credentials and data: none required

Tests need no API keys and touch no real data.

- `backend/tests/conftest.py` pins the whole session to a throwaway SQLite
  database **before** anything imports `app.database`. An exported
  `DATABASE_URL` — including a hosted Neon one — is ignored.
- Every external integration (Gmail, Polygon, Alpaca, Anthropic, Webull,
  TradingView) is opt-in and dormant when its variables are unset.

This matters more than it looks. Several tests drive the real `app.main:app`
through `TestClient`, and that app's lifespan runs `create_db_and_tables()`,
`_cleanup_orphaned_jobs()`, `_seed_and_normalize_roth_account()` (which can
move fills between accounts and trigger a full trade rebuild) and
`restore_manual_fills_from_backup()`. Before `conftest.py` existed, running
`pytest` on a normally configured machine performed those writes against the
developer's real database. **Do not remove or weaken that pin.**

## Writing tests here

Follow what the suite already does:

- Build an explicit in-memory or `tmp_path` SQLite engine, or override
  `get_session` on a test-local `FastAPI` app.
- Never reach the network. Stub at the boundary (`_get_service`,
  `_fetch_all_message_ids`, `httpx` callers), the way `test_gmail_poller.py`
  and `test_scalper.py` do.
- **Fix your ids.** The reconstructor's final sort tie-break is `str(fill.id)`,
  so random `uuid4()` ids make any same-timestamp case non-deterministic.
  `test_reconstructor.py` uses a monotonic `_next_id()` for exactly this
  reason; it flaked ~33% of runs before that.
- Don't add low-value tests to raise the count. The highest-value coverage is
  PnL math, FIFO reconstruction, fill dedupe, account identity, and parsers.

Collection is scoped to `backend/tests` by `[tool.pytest.ini_options]`.
`backend/scripts/` holds ad hoc analysis utilities that do real work at import
time; pytest must not walk them.

## Browser tests

`frontend/e2e/` holds Playwright smoke tests. They exist because typecheck,
lint and build all pass on a component that is broken at runtime -- verified:
a one-character change making the dashboard render every dollar figure 100x
too small passes all three, and fails the browser tests.

How a run works:

1. `backend/scripts/seed_dev_data.py` builds a throwaway database
   (`backend/data/e2e_seed.db`) from fixed fills.
2. The backend starts against it on port 8099, the frontend is rebuilt and
   started on 3099. Dedicated ports so a dev session on 8080/3000 is untouched.
3. Tests assert that seeded values reach the DOM.

Notes that will save you time:

- **Servers are never reused** (`reuseExistingServer: false`). `NEXT_PUBLIC_*`
  is baked at build time and the backend's seed and CORS origin come from the
  Playwright config, so a leftover server serves a stale build against a stale
  database -- tests then pass on code that is broken.
- **The frontend origin must be in the backend's CORS allowlist.** The config
  passes `FRONTEND_PUBLIC_URL`. Without it, client components' fetches are
  blocked by the browser and those pages sit on a loading state forever, while
  server-rendered pages still pass.
- **A sandbox with a preinstalled browser** whose build does not match this
  Playwright version can point at it:
  `PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium npm run e2e`.
- Asserted numbers come from `EXPECTED` in `seed_dev_data.py`, which
  `backend/tests/test_seed_dev_data.py` independently verifies the
  reconstructor still produces. If the fixture changes, that test fails first,
  in the fast run.

## Schema changes

`backend/tests/test_schema_migrations.py` fails when a SQLModel field has no
matching Alembic revision. This drift is invisible locally — startup calls
`create_all()`, so a fresh SQLite file always looks correct — and only
surfaces on a migrated database like Neon. The same test asserts a single
Alembic head, which two branches adding revisions in parallel can otherwise
break.

After changing a model:

```bash
cd backend
alembic revision -m "describe the change"   # then edit the generated file
alembic upgrade head
pytest tests/test_schema_migrations.py -q
```

## What is NOT covered yet

Be honest about this when reporting work:

- **No component-level frontend tests.** The browser smoke tests prove pages
  render real data, but there is no unit coverage of individual components,
  so a broken edge case inside a working page goes unnoticed.
- **The browser tests are smoke depth, not feature depth.** They assert that
  seeded values reach the DOM on the main pages. Filtering, sorting, forms,
  editing and Strategy Lab workflows are not exercised.
- **No integration tests against live Gmail/Polygon/Alpaca/Webull.** Those
  paths are only covered where they are stubbed. The browser tests run with no
  market-data credentials, so quote-dependent UI shows its empty state.
- **No load, migration-rollback, or Postgres-specific testing.** The suite runs
  on SQLite; dialect differences would not be caught.

If a change lands in one of these areas, say so and describe what you did
verify instead — for example, driving the endpoint through `TestClient` and
showing the response, or running the app and exercising the page.

## Running the app

```bash
bash startdev.sh                                  # backend 8080, frontend 3000
TRADINGVIEW_INGRESS_ENABLED=true bash startdev.sh # also ingress on 8090
```

The TradingView ingress is opt-in; ordinary work does not need it. Everything
binds to `127.0.0.1`. Only ever tunnel `8090`; the private API has no auth.
