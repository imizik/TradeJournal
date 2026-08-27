# Environments

Which database a process talks to, how to tell, and what is safe where.

## The environments

| Environment | Database | Credentials | Safe to destroy |
|---|---|---|---|
| **Worktree** (default) | `backend/data/trade_journal.db` (SQLite) | none | yes — it is a file |
| **CI** | ephemeral SQLite; a `postgres:16` container for parity tests | none | yes — thrown away every run |
| **Dev** | a Neon branch | dev branch role | yes — that is what it is for |
| **Production** | the Neon primary | production role | **no** |

An ordinary worktree needs no Neon and no integration credentials: leave
`DATABASE_URL` unset, keep the integration autostarts off, and use fixtures.
`scripts/setup.sh` sets this up. Two agents in two worktrees get two separate
SQLite files automatically, because the path is inside the worktree.

## Telling them apart

`GET /health` reports the database the running process is connected to:

```json
{
  "status": "ok",
  "environment": {
    "name": "production",
    "backend": "postgresql",
    "identity": "ep-restless-cell-a1b2c3.c-4.us-east-1.aws.neon.tech/neondb",
    "is_local": false,
    "destructive_requires_confirmation": true
  }
}
```

`identity` is redacted — host and database name only, never the username or
password, because it appears in API responses, job rows and logs.

Each Neon branch gets its own endpoint hostname, so two branches are always
**different** strings — a confirmation copied from one will not unlock the
other. But they are not **self-describing**: Neon names endpoints with random
words (`ep-restless-cell-a1b2c3`), and every branch of a project shares the
same database name. Nothing in the identity says "dev" or "production".

So `identity` answers "is this the same database I confirmed against?" on its
own, and "which environment is this?" only by comparison with the Neon
console. `APP_ENV` carries that second answer for a human reader — which is
why it is worth setting, and why it is still only a label the guard ignores.

`APP_ENV` sets `name`. It is a **label only** and never changes what is
allowed; see below.

## Destructive operations

Two endpoints delete fills the application cannot rebuild from itself:

- `POST /fills/resync-all`
- `POST /sync/advanced/resync-all`

Both are one-click buttons in the UI. Against a **local SQLite** database they
run unchanged. Against **any hosted database** they refuse unless the request
names the target:

```json
{"confirm": "ep-restless-cell-a1b2c3.c-4.us-east-1.aws.neon.tech/neondb"}
```

The UI asks for this when it is required, showing the identity and environment
name. The 400 response also spells out exactly what to send.

`POST /sync/advanced/rebuild-all` is **not** guarded. It calls the normal
`_rebuild_trades` path with `preserve_path_metrics=True`; rebuilding derived
trades is routine (`domain-rules.md`) and gating it would be friction with no
benefit. `CLAUDE.md` groups it with resync as "destructive" — that overstates
it; only resync deletes fills.

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

## Creating the Neon dev branch

Run this yourself — it needs Neon credentials, which no agent worktree has.

1. **Neon console → your project → Branches → Create branch.** Branch from
   `main` (or `production`). Name it `dev`. Branching is copy-on-write, so it
   starts as a full copy of production data at that moment and costs almost
   nothing until it diverges.
2. **Copy its connection string.** Convert it to the SQLAlchemy driver form
   this app uses — `postgresql+psycopg://`, not `postgres://`:
   ```
   postgresql+psycopg://USER:PASSWORD@ep-....neon.tech/DBNAME?sslmode=require
   ```
   Use the **direct** endpoint, not the one with `-pooler` in the hostname.
   The pooled endpoint is PgBouncer in transaction mode, which conflicts with
   psycopg3 prepared statements (`prepared statement "_pg3_0" already
   exists`), and Alembic is where that usually surfaces. Pooling buys a
   single-user app nothing.
3. **Point a worktree at it** in `backend/.env`:
   ```
   DATABASE_URL=postgresql+psycopg://.../dbname?sslmode=require
   APP_ENV=dev
   ```
4. **Confirm what you are connected to, before anything writes:**
   ```bash
   cd backend && .venv/bin/python scripts/check_database.py
   ```
   Use the venv interpreter, not `python`. Script docstrings in this
   repository are written as `python scripts/...`, which assumes an activated
   virtualenv; macOS has no `python` on PATH at all, and a bare `python3`
   lacks psycopg. `scripts/verify.sh` resolves the same path. If
   `backend/.venv` does not exist yet, run `scripts/setup.sh` from the
   repository root.

   Read-only — it never creates, alters or drops. It prints the identity,
   compares the live schema against the models, reads `alembic_version`, and
   names the command to run next. Check the identity against the Neon console;
   the endpoint name will not tell you on its own (see above).

### Alembic and `create_all` both build this schema

`app/database.py` calls `create_all()` at startup, so tables can exist that no
migration ever ran. Which command is correct depends on what
`alembic_version` says, and the two cases differ — both verified on
Postgres 16:

| `alembic_version` | `alembic upgrade head` | Run |
|---|---|---|
| empty (never stamped) | **fails** — `DuplicateTable: relation "account" already exists` | `alembic stamp head` |
| behind head | **succeeds** | `alembic upgrade head` |

The difference is the migrations themselves. `001_initial` calls
`op.create_table` unguarded, so it collides with anything `create_all` already
made. Migrations from `f1a2b3c4d5e6` (`add_strategy_lab`) onward wrap each
object in `if not _table_exists(...)`, precisely so Alembic can follow
`create_all` — the comment in `2e6f9a1b4c7d` says so. So a database stamped
part-way through and then extended by `create_all` upgrades cleanly, while one
that was never stamped at all does not.

`check_database.py` reads `alembic_version` and names the right one. It also
refuses to recommend a stamp when it finds drift: stamping records "this
database is at revision X", which is a lie if the schema is not what X
produces. `create_all` and a full migration run were compared directly and
produce the same 19 tables, differing only in `trade.ai_review` (`VARCHAR` vs
`TEXT` — the same type in Postgres), which is what makes a stamp honest when
the schema matches.

Refresh the branch from production by deleting and re-creating it in the
console; nothing in this repository depends on a dev branch's identity being
stable.

### What still does not exist

- **Staging.** Deferred with deployment (`roadmap.md` Phase 4). Staging and
  production must not share a database, credentials, webhook tokens, Gmail
  state or external-integration identity.
- **Separate database roles.** Everything currently connects as one role. The
  eventual split is a migration/schema owner, a private API role, a worker
  role, and the restricted TradingView ingress role that
  `architecture.md` already describes.
- **Per-PR Neon branches.** CI uses an ephemeral `postgres:16` container
  instead, which catches dialect problems without needing a secret. Per-PR
  branches earn their place when a PR needs a deploy preview or
  Neon-specific connection behavior.

## Test databases

Tests never use any of the above. `backend/tests/conftest.py` pins the suite
to a throwaway SQLite file before `app.database` is imported, so an exported
`DATABASE_URL` — including a hosted one — is ignored. The Postgres parity
tests opt in through a separate `TEST_DATABASE_URL` and refuse any database
that is not empty. Details in [verification.md](verification.md).
