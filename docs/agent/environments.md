# Environments

Which database a process talks to, how to tell, and what is safe where.

## The environments

| Environment | Database | Credentials | Safe to destroy |
|---|---|---|---|
| **Worktree** (default) | `backend/data/trade_journal.db` (SQLite) | none | yes — it is a file |
| **CI** | ephemeral SQLite; a `postgres:16` container for parity tests | none | yes — thrown away every run |
| **Dev** | a hosted branch you point a worktree at | that branch's role | yes — that is what it is for |
| **Production** | PostgreSQL on the Ubuntu VPS, `127.0.0.1:5432/tradejournal` | restricted `tj_app` role | **no** |

Production moved to the VPS on 2026-09-23. The Neon project is the retained
pre-cutover source, not a live production writer; a Mac worktree may still
contain Neon URLs, and must not be run as a second production API or worker.
Check the active database with the private `GET /health` before any operation
that changes data. The cutover and its recovery path are in
[the deploy README](../../deploy/README.md).

An ordinary worktree needs no hosted database and no integration credentials:
leave `DATABASE_URL` unset, keep the integration autostarts off, and use
fixtures. `scripts/setup.sh` sets this up. Two agents in two worktrees get two
separate SQLite files automatically, because the path is inside the worktree.

## Telling them apart

`GET /health` reports the database the running process is connected to:

```json
{
  "status": "ok",
  "environment": {
    "name": "production",
    "backend": "postgresql",
    "identity": "127.0.0.1:5432/tradejournal",
    "is_local": false,
    "destructive_requires_confirmation": true
  }
}
```

`identity` is redacted — host and database name only, never the username or
password, because it appears in API responses, job rows and logs.

Two hosted databases are always **different** strings, so a confirmation
copied from one will not unlock the other. They are not **self-describing**:
nothing in a Neon endpoint name (`ep-restless-cell-a1b2c3`) says "dev" or
"production", and every branch of a project shares a database name. So
`identity` answers "is this the same database I confirmed against?" on its
own, and "which environment is this?" only by comparison with the host's
console.

`APP_ENV` sets `name`. It is a **label only** for a human reader and never
changes what is allowed.

Real-time Gmail import has one owner. Only the host running
`tradejournal-worker@gmail` may set `GMAIL_LISTENER_ENABLED=true` or register a
Gmail watch: a second listener on the same Pub/Sub subscription would take
some notifications, and a second watch would replace the first. A laptop that
points at the production database keeps both off.

## Destructive operations

Two endpoints delete fills the application cannot rebuild from itself:

- `POST /fills/resync-all`
- `POST /sync/advanced/resync-all`

Both are one-click buttons in the UI. Against a **local SQLite** database they
run unchanged. Against **any hosted database** they refuse unless the request
names the target:

```json
{"confirm": "127.0.0.1:5432/tradejournal"}
```

The UI asks for this when it is required, showing the identity and environment
name. The 400 response also spells out exactly what to send.

`POST /sync/advanced/rebuild-all` is **not** guarded. It calls the normal
`_rebuild_trades` path with `preserve_path_metrics=True`; rebuilding derived
trades is routine (`domain-rules.md`) and gating it would be friction with no
benefit. Only resync deletes fills.

### Why confirmation is per-request and not a setting

An `ALLOW_DESTRUCTIVE=1` in `.env`, or an `APP_ENV=dev` that unlocks deletion,
authorizes destruction *forever* — including after `DATABASE_URL` is repointed
at something precious. This repository hit that exact failure twice in the
parity-test guard (`verification.md` → Postgres parity): first a check that
inspected one representative table, then a marker table that kept authorizing
long after the database it described had been repurposed.

So nothing ambient grants permission. The confirmation names the live target,
which means repointing the database changes the expected value with it. A
stale confirmation cannot exist.

## Pointing a worktree at a hosted database

1. **Use the SQLAlchemy driver form** — `postgresql+psycopg://`, not
   `postgres://`. On Neon use the **direct** endpoint, not the one with
   `-pooler` in the hostname: the pooled endpoint is PgBouncer in transaction
   mode, which conflicts with psycopg3 prepared statements (`prepared
   statement "_pg3_0" already exists`), and Alembic is where that usually
   surfaces.
2. **Set it in `backend/.env`** with `APP_ENV` as a label for readers.
3. **Confirm what you are connected to, before anything writes:**
   ```bash
   cd backend && .venv/bin/python scripts/check_database.py
   ```
   Use the venv interpreter, not `python`. Script docstrings in this
   repository are written as `python scripts/...`, which assumes an activated
   virtualenv; macOS has no `python` on PATH at all, and a bare `python3`
   lacks psycopg. If `backend/.venv` does not exist yet, run
   `scripts/setup.sh` from the repository root.

   It is read-only — it never creates, alters or drops. It prints the
   identity, compares the live schema against the models, reads
   `alembic_version`, and names the command to run next. Check the identity
   against the host's console; the endpoint name will not tell you on its own.

Alembic owns the schema and startup refuses to boot a database that is behind.
A database built by the old startup `create_all()` needs `alembic stamp head`
rather than `upgrade` when `alembic_version` is empty, because `001_initial`
creates tables unguarded; `check_database.py` reads the version and names the
right one, and refuses to recommend a stamp when it finds schema drift.
`test_postgres_migration_paths.py` holds every one of those states.

## Database roles

The application issues no DDL — Alembic owns the schema — so it runs as a role
that cannot create or drop anything. Three roles:

| Role | Used by | Can |
|---|---|---|
| **owner** (`tj_owner`) | `alembic` | everything; owns the schema |
| **app** (`tj_app`) | the private API and workers | SELECT/INSERT/UPDATE/DELETE, no DDL |
| **ingress** (`tj_ingress`) | the TradingView ingress (port 8090) | `tradingview_alert` only |

The ingress is the one that matters: port 8090 is the only tunnelable port and
is meant to be internet-facing, while 8080 is localhost-only by hard
constraint. The other two bound what an application-level bug can reach — the
difference between a bad `SELECT` and a `DROP TABLE`.

### Configuration

```
DATABASE_URL=postgresql+psycopg://tj_app:...@host/db
MIGRATION_DATABASE_URL=postgresql+psycopg://tj_owner:...@host/db
```

`alembic` uses `MIGRATION_DATABASE_URL` when set and `DATABASE_URL` otherwise,
so a single-role setup keeps working untouched. `backend/.env.tradingview` gets
`TRADINGVIEW_DATABASE_URL` with the ingress role, and nothing else — no keys,
no owner credentials (`architecture.md`).

Anything that migrates a *named* database out of process must set both
variables. `MIGRATION_DATABASE_URL` takes precedence inside Alembic, so one
left in the environment would silently migrate somewhere else;
`seed_dev_data.py` and the test helpers set both deliberately, and a test
covers it.

### Doing it

```bash
cd backend
.venv/bin/python scripts/setup_roles.py --confirm-host <host>            # create and verify
.venv/bin/python scripts/setup_roles.py --confirm-host <host> --verify   # re-check later
```

`--confirm-host` must equal the host inside the owner URL — the target is
named rather than inferred, for the same reason `resync-all` refuses a hosted
database it was not asked for by name.

The script creates the roles, grants `USAGE` on `public` plus the four DML
verbs the application actually issues (no `TRUNCATE`, no DDL, no sequence
grant — every key is a UUID), and sets `ALTER DEFAULT PRIVILEGES` so future
migrations do not produce tables the application cannot read. That last line
is the easy one to omit and the expensive one: the failure appears long after
the migration ran.

Then it checks the result two ways, and neither alone is the check. It asks
the server through `has_table_privilege` what each role can do to **every**
table in `public`, which accounts for privilege reached through role
membership; then it connects as each role and tries what must be refused,
which a catalog query cannot prove. A sampled probe list once passed a role
holding `SELECT` on `trade`, because `trade` was not one of the samples. Only
SQLSTATE `42501` counts as a refusal — an `INSERT` into a table with eighteen
`NOT NULL` columns fails on a constraint, which a naive probe reads as
"denied". Passwords are generated, printed once, and not stored.

`--verify` is the one to re-run after switching databases, editing `.env`, or
anything that moves which database is in play.

**On Neon, create roles in SQL, never in the console.** A console-created role
is a member of `neon_superuser` and inherits everything the owner can do —
verified on a real branch, where the ingress role read every fill with no
direct privilege on it — and the owner holds no admin option, so it cannot be
narrowed, re-passworded or dropped from SQL afterwards. Only the console can
delete it, and only after the owner revokes its grants. `setup_roles.py`
creates roles in SQL and its `--release` flag frees console-created ones.

### What still does not exist

- **Staging.** No persistent staging host has been provisioned. The
  [Ubuntu package](../../deploy/README.md) is tested on a disposable CI host.
  Staging and production must not share a database, credentials, webhook
  tokens, Gmail state or external-integration identity.
- **A separate worker role.** Background workers share the application role.
  A fourth role is real configuration complexity, and there is no threat it
  addresses that the app role does not — worth splitting when a worker needs
  privileges the API should not have, not before.
- **Per-PR database branches.** CI uses an ephemeral `postgres:16` container
  instead, which catches dialect problems without needing a secret.

## Test databases

Tests never use any of the above. `backend/tests/conftest.py` pins the suite
to a throwaway SQLite file before `app.database` is imported, so an exported
`DATABASE_URL` — including a hosted one — is ignored. The Postgres parity
tests opt in through a separate `TEST_DATABASE_URL` and refuse any database
that is not empty. Details in [verification.md](verification.md).
