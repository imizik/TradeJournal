# Scanner and shadow build plan

Written October 13, 2026 by the Claude session that built scanner S1. It turned
the [setup scanner contract](setup-scanner-contract.md),
[shadow S1 contract](shadow-s1-contract.md) and [shadow trader design](shadow-trader-design.md)
into ordered work packages. The contracts own scope and acceptance; this file
owns sequencing. Update the status column as packages land.

SC-1, SH-1 through SH-6, candle access and S2 have landed. Their package specs
were removed once merged; the code, its tests and the S1 contract are the record.
This file keeps the frozen file formats both services depend on, the invariants
those packages fixed, the check-service upgrade and rollback sequence, and the
remaining packages.

## Status and order

| # | Package | Tier | Depends on | Status |
|---|---|---|---|---|
| SC-0 | Daily scanner health check (ops, no code) | — | live | Scheduled — weekday 16:30 America/New_York in the lead chat; October 13 baseline; ten full acceptance sessions from October 14 |
| SC-1 | Quote reads off the monitor loop's critical path | 1 | — | Merged — [PR #302](https://github.com/imizik/TradeJournal/pull/302) (`tradier.get_quotes_once`) |
| SH-1–SH-3 | Check ledger, `shadow_setup`/`shadow_decide`, setup handoff and outbox wiring | 2 | — | Merged — [PR #296](https://github.com/imizik/TradeJournal/pull/296) |
| SH-4–SH-5 | Backend setups/decisions/shadow paper trade; Scanner page | 1 | SH-1–SH-3 interfaces | Merged — [PR #297](https://github.com/imizik/TradeJournal/pull/297) |
| Candle access | Frozen v2 packet + rolling/direct candle tool | 2 | SH-3/SH-4 | Merged — [PR #309](https://github.com/imizik/TradeJournal/pull/309); rollout steps [below](#candle-v2-rollout--after-merge-only) |
| SH-6 | Activation runbook and first live session | 2 | SH-1…5 merged | Done — pipeline accepted on October 16 evidence, owner closeout October 17 ([S1 acceptance](shadow-s1-contract.md#acceptance)) |
| SC-2 | Ten-session scanner acceptance write-up | 0 | 10 sessions | Oct 27 earliest |
| S2 | Isaac's trades linked to setups; three-way scorecard | 1 | S1 live | Built — display-only links and day/cumulative comparisons ([PR #304](https://github.com/imizik/TradeJournal/pull/304)) |
| SC-3 | 50-trade evaluation report | 0 | 50 resolved trades | Later |
| S3 | Independence research (MCP Events, separate Dot) | 2 | S1 live | Research-gated |
| S4 | Shadow chooses contract and exits | 1 | S2 evidence | Later |

## Frozen interfaces (both services code against these)

**Setup file** `/var/lib/tradejournal-shadow/setups/setup-<candidate_id>.json`,
written by the API with an atomic rename, mode 0640, group `tj-check`:

```json
{"format": "shadow-setup-v2", "candidate_id": "<uuid>", "scanner_version": "s1-v1",
 "params_hash": "<64 hex>", "session_date": "YYYY-MM-DD", "symbol": "SPY",
 "setup": "orb|fade", "direction": "long|short", "bar_start": "<ISO UTC Z>",
 "bar_end": "<ISO UTC Z>", "detected_at": "<ISO UTC Z>", "expires_at": "<ISO UTC Z>",
 "stop": 0.0, "target": 0.0, "flags": [], "facts": {}, "contract": {},
 "content_sha256": "<sha256 of the canonical JSON without this field>"}
```

`facts` and `contract` are copied unchanged from `scanner_candidate`. The check
service rejects a file whose hash, name or `format` disagree.

New v2 files additionally carry `candles`, `candles_as_of`, and an explicit
`candles_unavailable` reason when detection bars were not persisted. `candles`
contains `source`, `feed`, `last_bar_time`, `1m` (last 60) and `5m` (session).
Rows are completed and frozen with the candidate. Existing v1 files/decision
hashes remain supported. Rolling `scanner-candles-v1` files beside setups carry
up to 120 one-minute bars and the session five-minute bars; `enable-shadow-exchange` provisions the
same API-owner/check-reader setgid permissions, and the scanner publishes each pass.

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

## Invariants the merged packages fixed

Kept here because they are easy to break in a later change and are not all
restated in the S1 contract:

- Every check tool call is logged right after authentication, before the tool
  does any work. If the log insert fails the call is refused: a missing log
  row must never let `clean_order` read true.
- The check service re-execs with a cleaned environment and refuses ambient
  provider or database credentials. New settings go through its config file,
  never environment variables. It never imports journal storage or calls the
  private API.
- The rules-only scanner trade's behaviour, event keys and fields are
  unchanged by the shadow trade, which uses the same enter/watch/exit code
  under a `shadow_` event-key prefix. A shadow TAKE's entry uses a quote updated
  at or after the backend stored the decision.
- `check_control.py upgrade` refuses a bundle that changes check units; the
  shadow exchange keeps the check units unchanged. Ledger `received_at` strings
  are ISO UTC: compare datetimes, not strings.

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

## SH-6 — activation and first live session (lead with Isaac)

Done; kept as the record of the activation and as the procedure for later
check-service upgrades and rollback. Isaac-only steps are marked ⚑.

1. ⚑ Auth0: add `shadow:decide` to the check API's permissions and to the
   check client's grant.
2. Merge the backend/UI PR (#297), let it autodeploy. Merge the check-service PR (#296), then on the VPS: `check_control.py
   upgrade` with the exact manifest approval; `enable-shadow-exchange`; add the
   two config paths on both sides; restart the check service and API outside
   market hours.
3. ⚑ In ChatGPT: reconnect the check connection to grant the new scope and
   press **Refresh tools**.
4. ⚑ Replace Jo's Gmail task instructions with: "For each `TJ Setup:` email
   still before its stale time: first call `shadow_setup` with the setup ID,
   use its frozen packet candles (or explicitly note they are unavailable),
   then `shadow_decide` with take or skip and one reason. Use `candles` only
   after committing, never the hosted Alpaca connector. Do not call any other
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
Historical selection practice is scoped in the [scanner replay section](dot-historical-replay-contract.md#scanner-replay--historical-selection-benchmark-v0); actual Jo completed/resumed the first practice session on October 13 ET. The generation-frequency, sparse-bucket and cutoff-history follow-up precedes a five-session practice batch; no exam is frozen, and practice does not replace live S1/SC-3 proof.

Report per setup type and direction: count, win rate, mean and median per
contract, the 2× spread view, by exit reason; then the holdout comparison
(the September 14 → October holdout was never examined). No tuning on the
evaluation period. Small groups say "not enough evidence".

### S3 — independence, later, research-gated
1. Probe MCP Events on a disposable connector: `mcp` 2.x serves protocol
   `2026-07-28` but has no event helpers, so `events/list`, `events/subscribe`,
   `events/unsubscribe`, callback verification and Standard Webhooks signing
   are custom. Observe one delivered event start a Dot task.
2. Establish whether a second Dot or identity without same-day memory exists
   on Isaac's plan.
Only with both can a shadow result drop `independence-unverified`.

### S4 — shadow chooses contract and exits
A new versioned policy where `shadow_decide` may pick strike/expiration within
the contract rule's limits and its own stop/target. Needs S2 evidence first.


### Candle v2 rollout — after merge only

This change is not activated by the PR. Schedule the merge/autodeploy and all
operator work outside **09:25–16:15 America/New_York**. Follow the existing
release sequence above: successful exact-main deployment package, verified
hashes, stage, `check_control.py upgrade` with its exact manifest approval.
Rerun the idempotent `enable-shadow-exchange` to create the `candles` sibling
(mode 2750, API owner, tj-check group). Legacy exchange receipts upgrade in
place; unknown ACLs/ownership still refuse. The API's existing optional
`ReadWritePaths=-/var/lib/tradejournal-shadow` covers both directories; no new
socket, route, database role, OAuth grant or credential is needed. Then restart
under the normal outside-market-hours procedure and check health.

Verify in the actual service mount namespaces: API can write rolling files,
tj-check can read but cannot write them, files are 0640 with group tj-check,
and API still cannot read the check ledger. Verify fresh scanner provenance,
stale-file insufficient-data responses (IEX fallback removed October 20), and tool call logging
using approved non-decision checks. Do not manufacture live shadow decisions.

**Owner handoff:** Refresh tools in ChatGPT and confirm `candles` is listed.
Apply the task-text suggestion above separately: packet candles for decisions,
`candles` only after commit, Go-only alerts unchanged. Record the rollout cutoff
for SC-0 and report pre-v2/post-v2 sessions separately. No live task or deployment
is changed by this implementation PR.
