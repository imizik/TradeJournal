# Scanner and shadow build plan (for Codex)

Written October 13, 2026 by the Claude session that built scanner S1, for
Codex to execute. It turns the [setup scanner contract](setup-scanner-contract.md),
[shadow S1 contract](shadow-s1-contract.md) and [shadow trader design](shadow-trader-design.md)
into ordered work packages with owners, model choices, parallel lanes, exact
files, tests and traps. The contracts own scope and acceptance; this file owns
sequencing. Update the status column as packages land.

## How to use this plan

- Read [CLAUDE.md](../../CLAUDE.md), then this file, then only the contract and
  files the package names. Do not read the whole docs tree.
- One accountable lead session (Sol). It owns decisions, interfaces,
  integration, PRs and the final word. Workers get one package each, a frozen
  interface and a file list; one writer per file.
- `.codex/config.toml` allows two concurrent threads: the lead plus one
  worker. Lanes below are designed for exactly that.
- The owner merges. Push and open PRs; never merge or enable auto-merge
  unless Isaac says so in the chat.

## Model guide

Names as configured in `.codex/` and [review policy](pr-review.md).

| Use | Model, effort | Why |
|---|---|---|
| Lead for security, auth, deployment, cross-service or anything touching the check service | **Sol, high** | Isolation rules, OAuth scopes and install tooling are easy to get subtly wrong; this is where depth pays |
| Lead for ordinary backend integration in the private app | Sol, medium | Bounded logic in a well-tested area |
| Worker: pure functions, tests from a written spec, UI against a frozen API shape | **Luna, medium** | The default worker; give it the exact interface and test list |
| Worker: mechanical edits (docs links, renames, fixture data) | Luna, low | No judgement required |
| Tier 2 general review (anything in the check service, deploy, scopes) | **Astra, high** (`risk-reviewer`) | Required by review policy |
| Tier 1 review, or a focused tier 2 recheck | Sol, medium (`reviewer`) | Required by review policy |
| Statistics or evaluation reports | Sol, high | Honest small-sample handling matters more than code volume |

Escalate a Luna worker to Sol only when it fails twice on the same issue;
send the evidence, not a retry.

## Status and order

| # | Package | Lane | Model | Tier | Depends on | Status |
|---|---|---|---|---|---|---|
| SC-0 | Daily scanner health check (ops, no code) | ops | Lead chat (inherited) | — | live | Scheduled — weekday 16:30 America/New_York in this lead chat; October 13 baseline recorded; first full acceptance session October 14 |
| SC-1 | Quote reads off the monitor loop's critical path | lead | Sol | 1 | — | Implemented — one-attempt scanner quote reads and failure/recovery tests; combined SC-0/SC-1 PR pending merge/deploy |
| SH-1 | Check ledger: call log and shadow decisions | A | Sol, high | 2 | — | Merged — [PR #296](https://github.com/imizik/TradeJournal/pull/296) |
| SH-2 | Check tools `shadow_setup`, `shadow_decide` | A | Sol, high | 2 | SH-1 | Merged — [PR #296](https://github.com/imizik/TradeJournal/pull/296) |
| SH-3 | Setup handoff and decision outbox wiring (deploy) | A | Sol, high | 2 | SH-2 | Merged — [PR #296](https://github.com/imizik/TradeJournal/pull/296) |
| SH-4 | Backend: write setups, read decisions, shadow paper trade | B | Luna, high (Sol, medium reviews) | 1 | interface below | Merged — [PR #297](https://github.com/imizik/TradeJournal/pull/297) |
| SH-5 | Scanner page: email status, shadow columns, scorecard | B | Luna, medium | 1 | SH-4 | Merged — [PR #297](https://github.com/imizik/TradeJournal/pull/297) |
| SH-6 | Activation runbook and first live session | lead + Isaac | Sol, high | 2 | SH-1…5 merged | In progress — VPS exchange and SMTP active at `23b7c6c`; self-sent Gmail wake-up repaired with a tested owner-account relay; enabled v4 production task restored; actual Jo decision and first-session acceptance pending |
| SC-2 | Ten-session scanner acceptance write-up | lead | Sol, medium | 0 | 10 sessions | Oct 27 earliest |
| S2 | Isaac's trades linked to setups; three-way scorecard | — | Sol, medium + Luna, medium | 1 | S1 live | Built — display-only links and day/cumulative comparisons |
| SC-3 | 50-trade evaluation report | — | Sol, high | 0 | 50 resolved trades | Later |
| S3 | Independence research (MCP Events, separate Dot) | — | Sol, high | 2 | S1 live | Research-gated |
| S4 | Shadow chooses contract and exits | — | Sol, high | 1 | S2 evidence | Later |

**Parallel lanes for shadow S1** (two PRs):

- **Lane A, lead (Sol, high): SH-1 → SH-2 → SH-3** in `backend/cloud_mcp_check*.py`,
  `deploy/check_control.py`, `deploy/systemd/tradejournal-api.service`, and their
  tests. Tier 2 PR: one Astra/high general review, then a Sol/medium focused
  recheck on the fixes.
- **Lane B, worker (Luna, high for SH-4, then medium for SH-5): SH-4 → SH-5** in
  `backend/app/engine/setup_scanner.py`, a new module backend/app/engine/shadow_exchange.py
  (new), `backend/app/routers/scanner.py`, `frontend/app/scanner/page.tsx`,
  `frontend/lib/api.ts` and their tests. Tier 1 PR, Sol/medium review. It codes
  against the frozen file formats below using fixture files, so it never waits
  on Lane A.
- SC-1 is a small separate Lane B PR before or after SH-4; it touches
  `setup_scanner.py`, so do not run it at the same time as SH-4.

## Frozen interfaces (both lanes code against these)

**Setup file** `/var/lib/tradejournal-shadow/setups/setup-<candidate_id>.json`,
written by the API with an atomic rename, mode 0640, group `tj-check`:

```json
{"format": "shadow-setup-v1", "candidate_id": "<uuid>", "scanner_version": "s1-v1",
 "params_hash": "<64 hex>", "session_date": "YYYY-MM-DD", "symbol": "SPY",
 "setup": "orb|fade", "direction": "long|short", "bar_start": "<ISO UTC Z>",
 "bar_end": "<ISO UTC Z>", "detected_at": "<ISO UTC Z>", "expires_at": "<ISO UTC Z>",
 "stop": 0.0, "target": 0.0, "flags": [], "facts": {}, "contract": {},
 "content_sha256": "<sha256 of the canonical JSON without this field>"}
```

`facts` and `contract` are copied unchanged from `scanner_candidate`. The check
service rejects a file whose hash, name or `format` disagree.

**Decision file** `/var/lib/tradejournal-check/shadow-outbox/decision-<candidate_id>.json`,
written by the check service with an atomic rename:

```json
{"format": "shadow-decision-v1", "decision_id": "shd_<uuid>", "candidate_id": "<uuid>",
 "actor": "<check profile id>", "decision": "take|skip", "reason": "...",
 "committed_at": "<ISO UTC Z>", "timing": "on_time|late", "clean_order": true,
 "labels": ["informed-by-history", "independence-unverified"],
 "setup_sha256": "<the setup file's content_sha256>", "content_sha256": "<sha256>"}
```

The backend ignores a decision whose `setup_sha256` differs from the saved
candidate's, and records it as `shadow_unresolved` with that reason.

Canonical JSON everywhere: `json.dumps(value, sort_keys=True, separators=(",", ":"))`,
matching `cloud_mcp_check_ledger.digest`.

## SC-0 — daily scanner health check (ops)

After each close for the first ten sessions, from a machine on the tailnet:
`ssh ubuntu@100.121.251.15 'curl -s localhost:8080/scanner/day'` and
`sudo journalctl -u tradejournal-api --since today | grep -iE "rate_limited|Setup scanner|Scanner trade"`.
Report: setups, trades, unresolved and why, emails sent, any `rate_limited`
chart reads during the session. Read-only; never restart services for this.
Append one dated line per session to the scanner contract's acceptance notes.

The owner requested SC-0 and SC-1 together in one PR on October 13. The
**Scanner daily health check** is an active local heartbeat in the lead chat,
weekdays at 16:30 **America/New_York**. The Mac and Codex app must be running
and the tailnet/SSH connection available. It checks API/scanner availability,
setup and paper-trade counts, email dispositions/delivery, Jo's saved shadow
decisions or no-response, and relevant provider/scanner failures. Go-only
silence is not evidence of a failed task. It records a dated session receipt
and stays quiet unless there is a new actionable failure, required owner action
or completion of the ten-session evidence. Missing access is reported as missing
proof, not as scanner failure. It never restarts/deploys, mutates production
data, calls check MCP tools or submits decisions/orders. If source-note editing
would touch `main` or conflict with another writer, retain the receipt privately
for later reconciliation instead. October 13 is an activation baseline, not
one of the ten full acceptance sessions; counting starts October 14.

## SC-1 — quotes off the critical path

**Problem.** `tradier.get_quotes` → `tradier._post` sleeps on a 429 (Retry-After,
default 20 s) up to three times inside the level alert monitor pass, delaying
level-alert delivery and Practice paper judging.

**Do.** Give `setup_scanner._quote` a non-sleeping read: a small function in
`app/engine/tradier.py` that makes one attempt and raises `TradierError` on 429
or transport failure (no retry). The scanner's two-minute window already
retries on later passes. Do not change `get_quotes` behaviour for its other
callers.

**Tests.** `tests/test_setup_scanner.py`: a 429 produces no event and no sleep
(patch `time.sleep` to fail the test if called); the next pass inside the
window prices it. Check: `pytest tests/test_setup_scanner.py tests/test_level_alerts.py`.

## SH-1 — check ledger: call log and shadow decisions (Sol, high)

**Files.** `backend/cloud_mcp_check_ledger.py`, `backend/tests/test_cloud_mcp_check.py`
(or a new test module beside it).

**Do.**
1. Add two tables to the ledger `SCHEMA` (created idempotently, like the
   existing ones, with `BEFORE UPDATE/DELETE` abort triggers):
   `tool_call(id INTEGER PRIMARY KEY, actor, tool, called_at)` and
   `shadow_decision(decision_id PRIMARY KEY, actor, candidate_id, decision,
   reason, committed_at, timing, clean_order, setup_sha256, content_sha256,
   UNIQUE(actor, candidate_id))`.
2. `Ledger.log_call(actor, tool)`; `Ledger.decide(actor, setup, decision,
   reason, now)` that, inside one `BEGIN IMMEDIATE` transaction, returns the
   existing row for an identical retry, raises `Conflict` for different
   content, computes `timing` (`late` when `now >= expires_at`) and
   `clean_order` (no `tool_call` row for this actor with a tool other than
   `shadow_setup`/`shadow_decide` and `called_at` in `[detected_at, now]`), and
   inserts.
3. Existing databases must upgrade in place: the schema is applied on open,
   so new `CREATE TABLE IF NOT EXISTS` statements suffice. Do not alter the
   existing tables or triggers.

**Tests.** Identical retry returns the same row; changed reason conflicts;
late at exactly `expires_at`; `clean_order` false when `position_check` was
logged after `detected_at`, true when it was logged before; update/delete
refused; an existing ledger file created by the current code opens and gains
the tables without touching existing rows (compare row hashes).

**Trap.** `received_at` strings in this ledger are ISO UTC from `now_utc()`;
compare datetimes, not strings with different offsets.

## SH-2 — tools `shadow_setup` and `shadow_decide` (Sol, high)

**Files.** `backend/cloud_mcp_check.py`, `backend/cloud_mcp_check_common.py`,
`backend/app/engine/pretrade_check.py` only if a cutoff parameter is needed,
tests.

**Do.**
1. Scope `SHADOW_SCOPE = "shadow:decide"` in `_common`. Extend `scopes(name)`
   so both shadow tools need `check:read` + `shadow:decide`; add both to
   `TOOL_ARGUMENTS`; they must not be in `READ_ONLY_TOOLS`.
2. Log every tool call (all tools, including the existing ones) with
   `ledger.log_call` right after authentication succeeds, before the tool
   does any work. If that insert fails, refuse the call: a missing log row
   must never let `clean_order` read true.
3. `CheckConfig` gains optional `shadow_setups_dir` and `shadow_outbox_dir`
   (absolute, distinct, default `None`: shadow tools then answer "shadow not
   enabled"). Add them to `CheckVerifier.active_config`'s fixed keys.
4. `shadow_setup(candidate_id)`: read and verify the setup file (format, name,
   hash, and `session_date` is today in New York). Reading after `expires_at`
   is allowed but the answer says `expired: true`. Build `live` with the same
   packet code `pre_trade_check` uses for that ticker, option and contract.
   Build `history` from the feature rows **filtered to `closed_at` before the
   setup day's 00:00 New York** before any aggregation. Return labels and
   `history_cutoff`.
5. `shadow_decide(candidate_id, decision, reason)`: verify the setup file the
   same way, call `ledger.decide`, then write the decision file atomically
   (temp file, fsync, rename, fsync dir) into `shadow_outbox_dir`. Writing the
   file is idempotent: rewrite only if absent; if present with different
   content, refuse loudly (that would mean ledger and outbox disagree).
6. Tool descriptions must tell Jo the order: call `shadow_setup`, then
   `shadow_decide`, before any other check tool for that setup.

**Tests** (extend the existing generated-token fixtures): missing
`shadow:decide` refused for both tools; another profile's token refused;
forged candidate ID, tampered hash, yesterday's setup refused; after expiry the
decision is saved `late`; a feature row closed on the setup day is absent from
`history` while one closed the previous day is present; a `position_check`
before the commit gives `clean_order=false`; the outbox file matches the
ledger row; a restart (new server object on the same files) returns the same
decision.

**Traps.** The service re-execs with a cleaned environment and refuses
ambient provider or database credentials: never add environment variables;
everything comes through the config file. It must still never import journal
storage or call the private API.

## SH-3 — setup handoff and decision outbox wiring (Sol, high)

**Facts this relies on** (verified October 13 in the repository):
`deploy/cloud-mcp-check/tradejournal-check.service` has `ProtectSystem=strict`,
`ReadWritePaths=/var/lib/tradejournal-check` and an `InaccessiblePaths` list that
includes `/var/lib/tradejournal` but not `/var/lib/tradejournal-shadow`.
`deploy/systemd/tradejournal-api.service` runs as `tradejournal` with
`ReadWritePaths=/var/lib/tradejournal`. `check_control.py upgrade` refuses a
bundle that changes check units, so the plan keeps the check units unchanged.

**Do.**
1. API unit: add `ReadWritePaths=-/var/lib/tradejournal-shadow` (optional until activation,
   so ordinary releases still start before the operator creates the directory). This ships
   with the normal release (autodeploy). Update `backend/tests/test_deployment.py`
   expectations.
2. A new `check_control.py enable-shadow-exchange` command (root, idempotent,
   refuses unknown state): creates `/var/lib/tradejournal-shadow/setups`
   (`tradejournal:tj-check`, 2750) and `/var/lib/tradejournal-check/shadow-outbox`
   (`tj-check:tj-check`, 0750) and grants the `tradejournal` user ACL
   traverse-only (`--x`) on `/var/lib/tradejournal-check` and read on the
   outbox (plus a default ACL so new files are readable). Verify afterwards that
   `tradejournal` cannot read the ledger file (`sudo -u tradejournal test -r` must
   fail) and record the result. `disable-shadow-exchange` removes the ACLs. The host needs the Ubuntu `acl`
   package; commands require the existing private check ledger and refuse unknown
   identities, symlinks, directory ownership/modes or ACL grants. The permission
   receipt is `/opt/tradejournal-check/shadow-exchange.json`.
3. Config: the operator adds `shadow_setups_dir` and `shadow_outbox_dir` to
   `/etc/tradejournal-check/config.json`; the backend reads
   `SHADOW_SETUPS_DIR` and `SHADOW_OUTBOX_DIR` from
   `/etc/tradejournal/backend.env`. Both are off when unset.
4. Ship the check-service code with `check_control.py upgrade` (exact manifest
   approval), never by hand-copying files. Extend
   `deploy/cloud-mcp-check/smoke.py` to run the exchange end to end on the
   disposable Ubuntu job: API-user write → check read → decision → API-user
   read, and `tradejournal` refused on the ledger.

**Tests.** `backend/tests/test_check_deployment.py` for the command's
idempotence and refusals; the Ubuntu smoke for real permissions.

## SH-4 — backend: setups out, decisions in, shadow paper trade (Luna, high)

**Files.** A new module backend/app/engine/shadow_exchange.py (write setup files, read
decision files; pure I/O with the formats above), `backend/app/engine/setup_scanner.py`,
`backend/app/routers/scanner.py` (`day_view` additions), `backend/tests/test_setup_scanner.py`
(or a new test module beside it).

**Do.**
1. After a candidate with a contract is committed, write its setup file when
   `SHADOW_SETUPS_DIR` is set (atomic rename; never block or fail the scan on
   a write error: log it and retry on the next pass while fresh, the same way
   setup emails do; record a `shadow_handoff` event with `written` or
   `expired`).
2. Each pass, when `SHADOW_OUTBOX_DIR` is set, read decision files for today's
   candidates that lack a `shadow_decision` event; validate format, hash and
   `setup_sha256`; store `shadow_decision`.
3. Shadow paper trade for `take` + `on_time`: generalise `_enter`, `_watch`
   and `_exit` with an event-key prefix (`""` for rules-only, `"shadow_"` for
   shadow) instead of copying them. The decision time for the entry window is
   when the backend stored `shadow_decision` (it cannot see Jo's commit any
   sooner), and the quote must be updated at or after that. Same exits as the
   rules trade, computed independently. `status_of` stays rules-only; add
   `shadow_status_of`.
4. `day_view`: per candidate `shadow` = decision, timing, clean_order, labels,
   status, entry/exit, result; totals for the S1 scorecard in the contract,
   with `evidence: "not enough"` under 30 decisions.

**Tests** (fixture files written by the test, no check service): the setup
file round-trips and its hash verifies; a tampered decision is
`shadow_unresolved`; `skip`, `late` and no-decision cases price nothing; a
`take` entry uses a quote updated after the stored decision; the shadow trade
exits independently of the rules trade; restart idempotence; all existing
scanner tests still pass unchanged.

**Trap.** Keep the rules-only trade's behaviour byte-for-byte: the refactor in
step 3 must not change any existing event key or field.

## SH-5 — Scanner page (Luna, medium)

Add, from `day_view` only: email status per setup (sent, expired, capped),
the shadow columns (decision with reason on hover or expand, timing,
`clean_order`, result) and a scorecard row (rules-only all setups vs Shadow
Isaac TAKEs vs rules trades it skipped, with counts and "not enough
evidence"). Keep the page usable at 375 px: the table already scrolls in its
container; do not let the page scroll sideways. Verify in a running app with a
seeded database: a separate SQLite file migrated with `alembic upgrade head`,
the API started with that `DATABASE_URL`, `LEVEL_ALERTS_AUTOSTART=false` and an
empty `TRADIER_API_KEY` on a spare port, and the frontend pointed at it with
`API_INTERNAL_URL` and `NEXT_PUBLIC_API_URL`. Client-side navigation did not
work in that setup during PR #279 on any page; open day links by URL. Run the
frontend typecheck and lint.

## SH-6 — activation and first live session (lead with Isaac)

Isaac-only steps are marked ⚑.

1. ⚑ Auth0: add `shadow:decide` to the check API's permissions and to the
   check client's grant.
2. Merge Lane B, let it autodeploy. Merge Lane A, then on the VPS: `check_control.py
   upgrade` with the exact manifest approval; `enable-shadow-exchange`; add the
   two config paths on both sides; restart the check service and API outside
   market hours.
3. ⚑ In ChatGPT: reconnect the check connection to grant the new scope and
   press **Refresh tools**.
4. ⚑ Replace Jo's Gmail task instructions with: "For each `TJ Setup:` email
   still before its stale time: first call `shadow_setup` with the setup ID,
   then `shadow_decide` with take or skip and one reason. Do not call any other
   tool before that. Then run `pre_trade_check` with the JSON inputs and
   `attach_model_verdict`. Message me only when your co-pilot verdict is Go."
5. First session: confirm every setup has a decision or no-response, at least
   one `clean_order=true`, shadow trades priced after their decisions, and the
   history spot check. Record the evidence in the S1 contract.

### Operator sequence and owner handoffs

Use the newest **successful** main `Deployment package` run whose commit
contains both merged PRs; a newer cancelled or unfinished run is not a release.
Verify `SHA256SUMS` and the archive's generated release-metadata commit, then extract only
the offline wheels needed by `check_control.py stage`. Stage from that exact
source commit, retain its manifest SHA-256, and copy the bundle plus
`git archive <commit> deploy backend/advisor_key_state.py` to a new root-private
`/root/deploy-<sha>/` directory. Run retained-host commands as
`sudo bash -c 'cd /root && ...'`; the controller is under that directory's
`src/deploy/`, and the installed Python is
`/opt/tradejournal-check/backend/.venv/bin/python`.

Before changing live state, run the retained `check_control.py check` and
inspect `/opt/tradejournal-check/installation.json`. Compare the staged units
and pinned SQL with that record. The existing `context-views.sql` and
`market-view.sql` remain pinned; pass `--approve-sql` only for a reviewed new
additive file, never to force a changed existing file. Preserve root-private
backups of the installation record, check config and API environment, and
record the current API release and active check-unit set without printing
credentials. Check available disk and the existing `acl` package.

Wait until outside the weekday 09:25–16:15 New York deployment hold. Let the
merged application release autodeploy and verify that the running release
contains both PRs and its API unit has the optional shadow writable path.
If autodeploy is held for another reason, diagnose it before forcing a switch.
Install `acl` if absent. Stop all check units with `check_control.py stop`,
upgrade using `--bundle` and the exact `--approve-upgrade` manifest SHA-256,
then run `enable-shadow-exchange`. No new database migration is needed by S1.

Add these two fields to the existing check config, preserving all identity,
credential and provider settings:

```json
"shadow_setups_dir": "/var/lib/tradejournal-shadow/setups",
"shadow_outbox_dir": "/var/lib/tradejournal-check/shadow-outbox"
```

Add the matching API settings to `/etc/tradejournal/backend.env`:

```dotenv
SHADOW_SETUPS_DIR=/var/lib/tradejournal-shadow/setups
SHADOW_OUTBOX_DIR=/var/lib/tradejournal-check/shadow-outbox
```

Validate the updated check config with the upgraded runtime. Restore the
previously active check units, refresh keys before serving requests, restart
the API, and rerun `check`. Verify service health, directory owners/modes/ACLs,
API outbox readability and API ledger denial. Keep only the newest check
`previous-runtime` directory and newest `/root/deploy-*` after a successful
upgrade; never prune trial recovery directories or the v1 advisor.

Only then stop for **⚑ 3**: reconnect the newest working **TradeJournal Check**
plugin and Refresh tools. Preserve its User-Defined OAuth client, base scope
`offline_access`, disabled OIDC and access-token lifetime at most 300 seconds.
Use the refreshed plugin/@mention to confirm both shadow tools are available;
issued scope and tool access remain unverified until the new connection works.
Stop for **⚑ 4** to replace the Gmail task instructions with the text above.
Do not recreate the connection or edit the owner's task as an operator shortcut.

For the first full regular session after activation, compare the Scanner day
view with the immutable setup/decision files and ledger. Check every published
setup's disposition, both labels, at least one actual Jo decision with
`clean_order=true`, and every on-time TAKE's entry timestamp/quote freshness or
explicit unresolved reason. For one setup, compare the live `shadow_setup`
history with the published features filtered strictly before that session's
New York midnight; record eligible/excluded counts and cutoff, not raw fills.
If no setups, no clean decision or no on-time TAKE occurs, retain partial
evidence and carry the missing proof to the next session. Never manufacture a
live setup/decision or claim fixture evidence as live acceptance.

Rollback deactivates only the shadow exchange: stop check units, restore the
two backed-up configs, run `disable-shadow-exchange`, then restore healthy
check/API operation outside market hours. Preserve the ledger and all setup,
decision and scanner events. An interrupted, uncommitted runtime swap uses
the controller's documented interruption recovery. If the upgrade completed
but its runtime fails to start, stop all check units, retain the failed
backend separately, and restore the previous backend **together with its
backed-up installation record**. For this activation, no SQL is added or
changed: verify the old record still matches the pinned SQL and units, then
run `check` to prove the restored inventory before restarting. Restoring only
the backend under a new installation record causes inventory drift. A later
upgrade with SQL/unit changes needs its own recovery review; this rollback
does not authorize reverting those changes.

## Later packages (outline only)

### S2 — built: Isaac in the scorecard

The owner Scanner page links active-account option trades by underlying,
call/long or put/short direction and an inclusive 15-minute window after
UTC detection, interpreting trade timestamps as New York wall clock. A trade
belongs to the latest eligible candidate (lowest candidate ID breaks ties);
the earliest linked trade is primary and extra trades remain listed. Webull
is excluded using the existing dormant broker convention; S1's sixth-entry
flag retains its original account scope. Strike/expiration differences are
informational. These reads never reach Shadow's inputs or mutate journal data.

Day and cumulative scorecards show rules, Shadow and Isaac, plus on-time
TAKE/SKIP disagreements. Missing, late and unpublished decisions are not
passes. All linked closed/expired trades contribute their realized dollars
and separately normalized `realized_pnl / contracts`; open trades count as
traded but contribute no P&L. Setups with any sent email strictly before a
linked entry count as assisted. The independent-only comparison excludes
those setups altogether, rather than inventing a pass. This label means no
prior setup email, not proven independence or proof that an email was read.
Every group retains the 30-count evidence warning, with priced counts shown.
Different actual contracts and exits limit the comparison.

A durable `shadow_handoff` event with status `written` proves publication;
absent/expired handoffs with no evaluation are `not_published`, counted
separately and excluded from Shadow denominators. Actual decisions and paper
events remain authoritative when a marker is missing, preserving management
and evaluated results; the handoff provenance is disclosed separately. A published setup that expires without a decision
is `no_response`. Publication and email-send status do not prove Jo received
or read the setup. Groups without priced outcomes show “No evaluated trades”.

### SC-3 — 50-trade evaluation
Report per setup type and direction: count, win rate, mean and median per
contract, the 2× spread view, by exit reason; then the holdout comparison
(the September 14 → October holdout was never examined). No tuning on the
evaluation period. Sol, high; small groups say "not enough evidence".

### S3 — independence, later, research-gated
1. Probe MCP Events on a disposable connector: `mcp` 2.x serves protocol
   `2026-07-28` but has no event helpers, so `events/list`, `events/subscribe`,
   `events/unsubscribe`, callback verification and Standard Webhooks signing
   are custom. Observe one delivered event start a Dot task.
2. Establish whether a second Dot or identity without same-day memory exists
   on Isaac's plan.
Only with both can a shadow result drop `independence-unverified`. Sol, high.

### S4 — shadow chooses contract and exits
A new versioned policy where `shadow_decide` may pick strike/expiration within
the contract rule's limits and its own stop/target. Needs S2 evidence first.
