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

### A database from before Alembic owned the schema

Startup no longer calls `create_all()` (`app/schema.py`) — the app checks that
the database is at head and refuses to start otherwise. Databases created
before that change still have tables that no migration ran, and which command
fixes them depends on what `alembic_version` says. Both cases verified on
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

## Database roles

The application no longer issues DDL — Alembic owns the schema — so it can run
as a role that cannot create or drop anything. Three roles:

| Role | Used by | Can |
|---|---|---|
| **owner** (`neondb_owner` on Neon) | `alembic` | everything; owns the schema |
| **app** | the private API and workers | SELECT/INSERT/UPDATE/DELETE, no DDL |
| **ingress** | the TradingView ingress (port 8090) | `tradingview_alert` only |

The ingress is the one that matters. Port 8090 is the only tunnelable port and
is meant to be internet-facing; 8080 is localhost-only by hard constraint. The
launchers already refuse to start when `DATABASE_URL` is set and
`TRADINGVIEW_DATABASE_URL` is blank, so the ingress must be pointed somewhere
explicitly — but until these roles exist, the only thing to point it at is the
schema owner. The remaining two are hygiene.

### Configuration

```
DATABASE_URL=postgresql+psycopg://tj_app:...@host/db?sslmode=require
MIGRATION_DATABASE_URL=postgresql+psycopg://neondb_owner:...@host/db?sslmode=require
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
python scripts/setup_roles.py --confirm-host <host>            # create and verify
python scripts/setup_roles.py --confirm-host <host> --verify   # re-check later
python scripts/setup_roles.py --confirm-host <host> --release  # free console roles
```

`--confirm-host` must equal the host inside the owner URL. Neon branch names
are random words and a dev branch is indistinguishable from production at a
glance, so the target is named rather than inferred — the same reason
`resync-all` refuses a hosted database it was not asked for by name.

The script creates the roles, applies the grants below, and then checks them
two ways. It asks the server, through `has_table_privilege`, what each role can
do to **every** table in `public` — which accounts for privilege reached
through role membership, the case that made the first Neon setup decorative.
Then it connects as each role and tries what it must not be allowed to do,
which a catalog query cannot prove. Neither alone is the check: a sampled probe
list passed a role holding `SELECT` on `trade` because `trade` was not one of
the samples. Passwords are generated,
printed once, and not stored; Neon cannot show a SQL-created role's password
either, so a copy kept anywhere else would go stale.

`--verify` is the one to re-run — after switching branches, editing `.env`, or
anything that moves which database is in play. It probes whatever `.env` and
`.env.tradingview` currently point at.

The rest of this section is what the script does and why, for when it has to be
done by hand or the result needs explaining.

### Grants

Run as the owner, connected to the application database. Verified on
PostgreSQL 16 — every row of the table below was executed, not assumed.

On Neon, create the two roles in SQL rather than in the console before running
these; a console-created role arrives with privileges these grants cannot take
away, and cannot be repaired afterwards. See below.

```sql
GRANT USAGE ON SCHEMA public TO tj_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tj_app;
-- Without this, the next migration creates a table the app cannot read.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tj_app;

GRANT USAGE ON SCHEMA public TO tj_ingress;
GRANT SELECT, INSERT, UPDATE ON tradingview_alert TO tj_ingress;
```

Those four verbs are the whole of what the application issues. It runs no
`TRUNCATE` (which `DELETE` would not cover anyway), no DDL, and needs no
sequence grant — every key is a UUID and the schema has no sequences.
`resync-all` deletes through the ORM, so it needs nothing beyond `DELETE`.

`ALTER DEFAULT PRIVILEGES` is the line that is easy to omit and expensive to
omit: without it every future migration produces a table the application
cannot read, and the failure appears long after the migration ran.

What was verified, each as the role named:

| Attempt | Result |
|---|---|
| app writes any table | allowed |
| app `CREATE TABLE` | `permission denied for schema public` |
| app `DROP TABLE fill` | `must be owner of table fill` |
| app runs `alembic upgrade` | `InsufficientPrivilege` |
| owner runs `alembic upgrade` | applies |
| app reads `alembic_version` | allowed — startup's check needs it |
| ingress writes an alert through its own engine | allowed |
| ingress reads `fill` / `account` | `permission denied` |
| a table created *after* the grants | app can read and write it; ingress cannot |

### Neon: the grants alone are not enough

**A role created through the Neon console is a member of `neon_superuser`**,
and through it inherits everything the schema owner can do. The grants above
still apply exactly as written — the role simply has a second, wider source of
privilege that overrides the intent.

Confirmed on a real Neon branch, where the ingress role read every fill despite
having **no direct privilege on `fill` at all**:

```
=== roles tj_ingress belongs to ===
  neon_superuser

=== who has privileges on fill ===
  neondb_owner | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
  tj_app       | DELETE, INSERT, SELECT, UPDATE
```

**A console-created role cannot be narrowed from SQL.** The owner holds no
admin option on it, so every statement that would restrict it is refused.
Reproduced on PostgreSQL 16 against a fixture with Neon's membership shape —
all five, not just the first:

| Run as `neondb_owner` | Result |
|---|---|
| `REVOKE neon_superuser FROM tj_app` | `permission denied to revoke role "neon_superuser"` |
| `ALTER ROLE tj_app NOCREATEROLE NOCREATEDB` | `permission denied to alter role` |
| `ALTER ROLE tj_app NOINHERIT` | `permission denied to alter role` |
| `DROP ROLE tj_app` | `permission denied to drop role` |
| `ALTER ROLE tj_app PASSWORD '...'` | `permission denied to alter role` |

Run them in one transaction and only the first error is a privilege error; the
rest report `current transaction is aborted`, which reads like a cascade from
one fixable problem. They are five independent refusals. Use autocommit when
probing what a role may do.

`NOINHERIT` would not have been a fix in any case: membership still permits
`SET ROLE neon_superuser`, so it stops accidents and not an attacker.

### So create the roles in SQL, not in the console

A role the owner creates is one the owner keeps the admin option on, and it
gets no `neon_superuser` membership:

```sql
CREATE ROLE tj_app     LOGIN PASSWORD '...' NOCREATEDB NOCREATEROLE;
CREATE ROLE tj_ingress LOGIN PASSWORD '...' NOCREATEDB NOCREATEROLE;
```

Then apply the grants above. Neon does not store the password of a SQL-created
role and cannot show it in the console, so keep it wherever the rest of the
connection string lives.

**If the roles already exist from the console**, delete them there — the
control plane can, the owner cannot — but revoke their privileges first, or the
delete fails with `role "tj_app" cannot be dropped because some objects depend
on it`. The owner granted these, so the owner can take them back:

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  REVOKE ALL ON TABLES FROM tj_app;
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM tj_app, tj_ingress;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM tj_app, tj_ingress;
REVOKE ALL ON SCHEMA public FROM tj_app, tj_ingress;
```

That list is what a `DROP ROLE` needs cleared; it was verified by dropping a
role that the owner *could* drop, which failed on `privileges for schema
public` until every line above had run.

### Then verify, rather than assume

Both directions, because a role that can do nothing looks the same as a role
that is correctly restricted. Connected **as the ingress role**:

```sql
SELECT count(*) FROM fill;               -- must fail: permission denied
SELECT count(*) FROM tradingview_alert;  -- must return a number
```

And as the application role: `fill` readable, `CREATE TABLE` refused,
`DROP TABLE fill` refused, and

```sql
SET ROLE neondb_owner;  -- must fail: permission denied to set role
```

That last line is the one that separates a boundary from a speed bump. A role
that inherits nothing but may still `SET ROLE` into the owner is not
restricted; it is one statement away from unrestricted.

If the check is scripted, classify the failure rather than catching every
exception: `INSERT` into a table with eighteen `NOT NULL` columns raises a
constraint violation, and a probe that treats any error as "denied" reports
that as a working restriction. Only SQLSTATE `42501` is a privilege refusal.
Run each probe inside a transaction and roll it back, so a probe that is
wrongly *allowed* — `DROP TABLE fill` — still changes nothing.

This check is the only thing that distinguishes a working split from a
decorative one. It was written expecting to pass, and it failed on the first
real Neon branch it ran against — every grant correct, every privilege
inherited around them.

### Diagnosing it

Read-only, as the owner:

```sql
SELECT r.rolname FROM pg_auth_members m
  JOIN pg_roles r ON r.oid = m.roleid
  JOIN pg_roles u ON u.oid = m.member
 WHERE u.rolname = 'tj_ingress';

SELECT grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type)
  FROM information_schema.table_privileges
 WHERE table_name = 'fill' GROUP BY grantee;
```

A role appearing in the first result with nothing in the second is inheriting
its access, not being granted it.

### What still does not exist

- **Staging.** Deferred with deployment (`roadmap.md` Phase 4). Staging and
  production must not share a database, credentials, webhook tokens, Gmail
  state or external-integration identity.
- **A separate worker role.** Background workers share the application role.
  A fourth role is real configuration complexity, and there is no threat it
  addresses that the app role does not — worth splitting when a worker needs
  privileges the API should not have, not before.
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
