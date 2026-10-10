# Journal coach snapshot gateway

2026-10-09 — first separately scoped journal-coaching slice. Code and fixture
verification do not authorize sharing Isaac's journal, deploying the gateway,
registering OAuth scopes, creating a database role or enabling a schedule.

## Boundary

The independent Practice reader and historical demo stay unchanged. This is a
personal coach that can see explicitly shared journal summaries; it is not a
blind comparator. The standalone `backend/cloud_mcp_journal.py` process has no
database credentials, application imports, provider calls or model calls. It
serves an operator-approved, hash-bound export file through offline OAuth and a
systemd listening Unix socket only. No TCP serving fallback exists. Its two
tools are `get_journal_summary` and `list_journal_trades(offset=0)`.

Both discovery and calls require `d0:profile` and the new `journal:read` scope,
the selected issuer/audience/client and one enabled configured subject. Existing
demo consent does not grant the new scope. The legacy opaque `d0_` profile ID is
only an identity binding; no synthetic profile tool is exposed. Offline key
expiry and current local revocation apply on every call. Identity, export path,
inclusive date window and real/fixture class are pinned until restart. A new
approved digest may refresh the export in that same scope. Recheck authorization
after loading the snapshot; concurrent revocation or refresh refuses that call.

## Selected data

An export includes only closed/expired trades whose `closed_at` falls in an
explicit account selection and at most 31 inclusive Eastern calendar dates.
It refuses more than 500 rows instead of silently truncating statistics.
Serving reads at most 1 MiB, rejects invalid schemas/hashes and future/stale
exports older than one hour, and pages at most 50 trades. Every response names
its export and read times, date window, digest, source and `sample_data` class.
No live quote, position, paper result or trading-performance inference exists.

Trade fields are ID, ticker, instrument type, quantity, recorded realized P&L,
closed/expired status and entry/exit timestamps. Quantity is shares for stocks,
contracts for options. Entry/exit timestamps retain the database's naive Eastern
wall-clock convention; export/read timestamps are aware UTC. No account or
broker identity, option-contract details, fills, reviews, notes, source emails,
attachments, credentials or arbitrary text is exported. Unknown fields are
rejected. No regular journal/browser read grant is widened.

P&L and quantity are finite decimal strings within the database's DECIMAL(18,6)
range. Statistics use recorded P&L only, without recomputing FIFO or inferring
missing P&L. Counts distinguish known/missing values, wins, losses and breakeven.
Total P&L is null when no values are known. Win rate is a six-decimal ratio over
known-P&L trades, including breakeven, and null when that denominator is zero.
No planned risk or R-multiple is inferred from these journal rows.

## Export and activation

`backend/scripts/export_journal_coach.py` requires its own
`JOURNAL_EXPORT_DATABASE_URL`, explicit account UUIDs, dates and an output path.
It never falls back to `DATABASE_URL`. Only PostgreSQL/psycopg is accepted.
A read-only transaction and dedicated non-owner role are mandatory. Superuser,
BYPASSRLS, database/role creation, other role memberships, schema creation or
ownership, and table write/ownership privileges fail closed. Even benign role
membership requires a different dedicated role. Queries select only the fixed
projection with bound account/date parameters. Connections roll back and close;
there is no application startup, migration, backfill or context creation.

Export installation is private (0600), atomic and no-clobber unless the operator
explicitly selects replacement. Output reports only digest, time and row count.
The serving process receives only its dedicated OAuth configuration, public-key
snapshot and approved export, never the export role's URL or production secrets.
Deployment must provide read-only mounts, a separate OS identity, AF_UNIX-only
networking and a separately authenticated HTTPS proxy, as in the proven demo
transport. This slice installs or exposes none of them automatically.

Before real activation: select the exact accounts/dates/fields with Isaac,
review native packaging and database-role permissions, refresh and verify the
production restore point, separately approve real-data transmission and OAuth
registration/consent, then prove actual Jo reads, data exclusions, revocation,
expiry, restart and no-write/no-network boundaries. Manual export is the only
refresh mechanism in this slice; no scheduling or background subscription exists.

## Acceptance

Fixture tests cover strict projection, exact sums and missing values, bounded
windows/rows/bytes, hash/freshness/time checks, SQL role refusal and parameterized
account filtering, signed OAuth scope/identity/audience/client denial, pinned
scope changes, revocation during export loading, read-only tool discovery,
pagination and unknown/write arguments. Existing D0/D1/D2/historical tests must
remain green. Native PostgreSQL privilege enforcement, installed isolation and
actual Jo real-data acceptance remain separate deployment gates.
