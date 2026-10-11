# Journal coach snapshot gateway

2026-10-09 — first separately scoped journal-coaching slice. Code and fixture
verification do not authorize sharing Isaac's journal, deploying the gateway,
registering OAuth scopes, creating a database role or enabling a schedule.

## Observed continuous journal acceptance

**Accepted October 10, 2026 ET (October 11 UTC), following merged PRs
[#208](https://github.com/imizik/TradeJournal/pull/208) and
[#213](https://github.com/imizik/TradeJournal/pull/213).** The separately approved
activation completed; the original planning warning above is not a claim that
the existing journal connection is still dormant.

The recorded scope is one approved Roth account, closed/expired stock and
option trades over 30 inclusive Eastern dates, with exactly eight shared fields:
ID, ticker, instrument type, quantity, realized P&L, status, opened and closed
times. Publication and public-key maintenance run about every 15 minutes;
these are maintenance timers, not automatic Jo coaching or D3 follow-through.

The retained operator acceptance record observed 27 projected rows matching an
independent scoped SQL read, restricted-role/catalog denials, actual signed-in
Jo summary/pagination equality, timer advancement, stopped-socket refusal,
restart persistence, profile revocation/recovery, public-key expiry/recovery and
stale-export refusal followed by genuine refresh. Login/refresh exchanges were
observed; the full configured seven-day idle/thirty-day maximum lifetimes and
refresh-token reuse attack were not tested. Existing unrelated boundaries were
checked at those checkpoints. This is past operational evidence, not a current
health assertion or a new authorization to activate or broaden anything.

The owner then requested one actual coaching review in the journal integration
chat. Jo used fresh shared-trade reads and returned a concentration/expiry
observation and one question. That closes the first bounded coaching observation;
it does not establish lasting benefit, the user's intent, broker completeness or
trading edge. Writing trade notes is optional and does not reopen integration
acceptance. Raw trade exports, credentials and private operational receipts stay
outside the repository. The [Dots board](dots-integration.md#current-delivery-board)
tracks next work separately from this completed slice.

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
expiry, restart and no-write/no-network boundaries. The original fixed-window
slice uses manual export only. Continuous publication below is a separately
approved increment; installing a plugin alone enables none of its timers.

## Opt-in continuous read-only publication

The rolling mode retains the same two tools, eight trade fields, 500-row/1-MiB
bounds, exact recorded P&L and one-hour refusal. Set `publication_file` and a
strict `rolling_days` count (1–31), instead of fixed `snapshot_file`, digest and
dates. These modes are exclusive. The serving process pins the publication path,
day count, identity and data class until restart. Each read requires the exact
current inclusive Eastern date window; immediately after Eastern midnight, the
prior window refuses until the next successful publication.

`backend/journal_coach_publication.py` installs immutable content-addressed files
and atomically replaces a small strict digest pointer. It checks schema, size,
hash and freshness, rejects symlinks/nonregular files, and retains current plus
two previous generations. Publication changes during a read refuse. Pagination
restarts when response digests differ. Failed refresh leaves the last good pointer
and its original timestamp intact; normal expiry still applies.

`backend/journal_coach_refresh.py` is a separate finite publisher, not an MCP
tool or application startup path. Its private scope selects exactly one account
and rolling day count. Its database credential comes through a systemd credential
file, never the MCP environment. Scoped export requires only the nine source
columns on `public.journal_coach_export_trade`, no base-table or other user-relation
reads, and the existing non-owner/read-only role checks. The no-clobber view from
`deploy/journal_coach_scope.py` enforces the approved account, closed/expired status
and Eastern date bound and narrows the previous source-table grant. The ninth
column is account filtering only and never appears in the export. Do not give the
export role ownership, membership, base-table SELECT or write access.

Private input files normally require mode 0400 or 0600. Systemd may instead
present `LoadCredential` files as root:root 0440 in a root:root 0550 directory.
Accept that mode only directly inside the service's `CREDENTIALS_DIRECTORY`
under `/run/credentials/`, with those exact owners/modes and a read-only
filesystem verified on the opened descriptor. Ordinary group-readable files,
mutable mounts, symlinks and oversized inputs still refuse. This does not
change source credential permissions or grant the gateway credential access.
The disposable journal smoke tests this real systemd delivery with invented
scope/credential bytes and no database connection or publication.

The manually installed export service permits only the local database endpoint
and writes only its publication directory. A separate nftables unit affects only
the two dedicated publisher UIDs: export connects only to localhost TCP 5432;
keys use the exact DNS servers on port 53 and public HTTPS on port 443, with
private/loopback/link-local/Tailscale and host addresses denied except DNS.
Both publishers require this policy unit to start successfully. Native negative
controls must prove private API/frontend access fails, independently of filesystem
or SQL restrictions. Existing host firewall tables are never flushed or replaced.
The serving process keeps its offline AF_UNIX-only
namespace, no database credential and no writable mounts. A separate public-key
publisher uses the existing bounded HTTPS refresh code and cannot read the scope,
database credential or publication. Both optional timers run every 15 minutes
after startup; ordinary app deployment does not enable them. Key maintenance does
not extend OAuth consent/refresh-token lifetimes; selected Auth0 policy may still
require reauthentication.

Before activation, approve ongoing account/date/field sharing, review the role/view
and packaging, verify a fresh production restore point, and retain rollback files.
Observe the installed timer, fresh Jo summary/all pages, scoped exclusions and
restart/revocation/expiry behavior. A stopped publisher must eventually refuse
stale data. Distinguish these observations from local/disposable CI checks. Stop
both new timers and active oneshots to cancel maintenance; remove only the new
UID-specific firewall table when publishers are stopped, and restore the prior
disabled/fixed grant/runtime as needed while preserving receipts/exports privately.
This adds no recurring Jo task, provider/model job, live order, application trade
write or coaching-note writer.

## Fixture setup packaging

`deploy/journal_coach_stage.py` prepares a new private directory containing the
standalone runtime modules, journal socket/service templates, a disabled
configuration, an invented two-trade export and file digests. It accepts only
issuer/resource/client/subject/profile bindings, never an account selection,
database URL or real export. Both the configuration and profile are disabled;
`sample_data=true` is fixed. It does not create an OS user, install units, build
dependencies, publish HTTPS, generate keys, register OAuth or start a service.
Refuse existing destinations and symlinked staging parents. Stage only from
the reviewed source; compare its recorded file digests before installation.
Fixture snapshots expire after one hour and must be freshly staged for a later
test; expiry is never weakened to keep a stale installation working.

The manual templates under `deploy/cloud-mcp-journal/` use a separate
`tj-journal-coach` OS identity, independent runtime under
`/opt/tradejournal-journal/runtime`, configuration under
`/etc/tradejournal-journal` and approved export/public keys under
`/var/lib/tradejournal-journal`. The socket is accessible only to the coach and
Caddy group. The service receives no environment file, uses read-only mounts,
blocks production and demo runtime/configuration/data paths, has a private
network namespace and permits AF_UNIX only. Install no writable paths. Future
manual installation grants this identity read access to its dedicated files,
without reusing production/demo credentials or broadening their memberships.

The deployment CI smoke is root- and disposable-runner-gated, refuses existing
journal users/units/directories, and uses generated local signatures and invented
rows. It exercises the actual socket/service, scope and data denials, bounded
pagination, revocation, refresh and restart. Sandbox checks execute inside that
same unit context and must prove production markers are inaccessible, fixture
files cannot be written, IPv4/IPv6 creation is denied and Unix sockets work.
Outside-sandbox controls first prove the same UID can create IP sockets, read
the harmless production-path marker and write a dedicated harmless probe.
Removing `InaccessiblePaths` or `ProtectSystem` separately must make its probe
fail; ordinary file permissions cannot substitute for these policy checks.
Stopping both units must prevent socket activation. This establishes installed
fixture isolation on disposable Ubuntu, not live HTTPS, Auth0 consent, VPS
installation or actual Jo access.

On the VPS, staging is the next reversible preparation step. Creating the OS
identity, installing/starting units, publishing a new HTTPS route and registering
or extending OAuth access require a concrete separately approved activation.
Keep the existing historical demo connector intact throughout setup. Before
real-data access, the earlier account/date/field, export-role, backup and
transmission gates still apply. Stop and remove only the new dedicated units to
roll back activation; preserve approved exports and receipts privately rather
than rewriting journal or demo rows.

## Acceptance

Fixture tests cover strict projection, exact sums and missing values, bounded
windows/rows/bytes, hash/freshness/time checks, SQL role refusal and parameterized
account filtering, signed OAuth scope/identity/audience/client denial, pinned
scope changes, revocation during export loading, read-only tool discovery,
pagination and unknown/write arguments. Existing D0/D1/D2/historical tests must
remain green. Native PostgreSQL privilege enforcement, installed isolation and actual Jo
real-data checks were separately observed for the bounded continuous activation
above. New deployments or scope changes retain their own applicable gates;
fixture results alone do not establish them.
