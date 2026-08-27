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
    "identity": "ep-prod-x9y8z7.us-east-2.aws.neon.tech/tradejournal",
    "is_local": false,
    "destructive_requires_confirmation": true
  }
}
```

`identity` is redacted — host and database name only, never the username or
password, because it appears in API responses, job rows and logs. Each Neon
branch gets its own endpoint hostname, so a dev branch and production are
visibly different strings.

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
{"confirm": "ep-prod-x9y8z7.us-east-2.aws.neon.tech/tradejournal"}
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
3. **Point a worktree at it** in `backend/.env`:
   ```
   DATABASE_URL=postgresql+psycopg://.../dbname?sslmode=require
   APP_ENV=dev
   ```
4. **Confirm before doing anything:**
   ```bash
   curl -s localhost:8080/health | python3 -m json.tool
   ```
   Check `identity` names the dev branch, not production. This is the step
   that makes the rest safe.

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
