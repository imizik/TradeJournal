# Shadow Isaac S1 — Jo takes or skips scanner setups for its own paper book

Selected by Isaac on October 12, 2026, when he moved the Dots priority from
the advisor to the shadow trader. Build step 4 of the
[shadow trader design](shadow-trader-design.md#build-order-after-dots-steps-35),
narrowed to the smallest version that produces a comparable record.
Reworked October 13 with Isaac's go-ahead to use the recommended choices.
**The Shadow S1 pipeline is accepted on October 16, 2026 live-session
evidence, with owner closeout on October 17. Natural TAKE execution remains
unproven live, covered by fixtures, and is not an acceptance blocker.** The frozen file
formats, upgrade/rollback sequence and remaining packages are in the [shadow build plan](shadow-build-plan.md).

## Owner decisions (October 13, 2026)

| Question | Decision |
|---|---|
| What Shadow Isaac decides | TAKE or SKIP only. The setup's contract, stop, target, time stop and flat time are fixed, so S1 measures selection skill alone |
| History it may see | Isaac's closed-trade aggregates, cut off at the previous session's close |
| Wake-up | The scanner's existing `TJ Setup:` email through Jo's Gmail task, with every result labelled as below |

## What happens

1. The [scanner](setup-scanner-contract.md) saves a setup, hands it to the
   check service as a file at once and emails it (`TJ Setup:` subject).
2. Jo's Gmail task wakes. **First**, as Shadow Isaac, Jo calls
   `shadow_setup(candidate_id)` and then `shadow_decide(candidate_id,
   decision, reason)`. Only after that may it call `pre_trade_check` or any
   other check-service tool for the co-pilot rating.
3. TradeJournal prices a TAKE as Shadow Isaac's own one-contract paper trade:
   the setup's contract and exits, entered at the ask of the first quote read
   after TradeJournal sees the commit whose bid and ask were both updated at or
   after the commit. A commit at or after the setup's `expires_at` is saved as
   **late** and never entered; no commit by then is **no response**.
4. The Scanner page shows the rules-only result, Shadow Isaac's decision and
   result, and both labels for every setup.

## What Shadow Isaac sees, and what can be proved

`shadow_setup` returns only:

- the frozen setup as saved (facts, rule stop/target, contract, `expires_at`);
- v2 packet candles: the last 60 completed one-minute bars actually scanned and
  session-to-date completed five-minute bars, frozen at detection;
- the live packet the pre-trade check builds for that ticker (price, VWAP,
  opening range, relative volume, levels, option quote), with source times;
- Isaac's closed-trade aggregates from the published feature rows, computed
  only over trades with `closed_at` before the setup day's 00:00 New York.

It never returns open positions, today's trades or fills, saved checks, Jo's
co-pilot verdicts, captures or notes.

**Same Dot, same connection.** Jo's check connection already carries tools
that read open positions, captures and notes (Isaac approved that on October
12; see `deploy/check_scope.py`). Neither tool scopes nor prompts can stop the same Dot from calling them.
S1 therefore records evidence instead of claiming isolation:

- **`clean_order`**: true only when the check service saw no call from this
  actor to any other check tool between the setup's publication and the
  commit. Every tool call (name, actor, time) goes into an append-only call
  log in the check ledger to make this checkable.
- **Labels on every result:** `informed-by-history`, plus
  `independence-unverified`. Jo's Gmail can read broker fill emails, and its
  memory may hold today's conversations; neither is observable here.
- Removing `independence-unverified` needs a non-Gmail wake-up (MCP Events)
  and a Dot or identity without same-day memory. That is
  [shadow S3](shadow-build-plan.md#s3--independence-later-research-gated), not S1.

## Interfaces

**Setup handoff (private backend → check service).** When the scanner saves a
setup with a contract, the private backend writes it at once as a
content-addressed `setup-<candidate_id>.json` (the frozen `scanner_candidate`
fields: ID, symbol, setup, direction, bar times, `detected_at`,
`expires_at`, stop, target, flags, facts, contract, scanner version and
params hash, plus frozen candles in `shadow-setup-v2`) into `/var/lib/tradejournal-shadow/setups/`, written by the API
user and readable by `tj-check`. The check service already reads any path its
unit does not hide, so this needs no database role, view or timer and adds no
publication lag. The API unit gains `ReadWritePaths=-/var/lib/tradejournal-shadow` (optional until activation).

**Tools on `/check/mcp`, new scope `shadow:decide`:**

- `shadow_setup(candidate_id)` → `{schema_version, candidate, live, history,
  history_cutoff, labels, published_at, candles, candles_as_of}`. Read-only, logged.
  v1 remains readable; absent candles return `candles_unavailable` with a reason.
  The returned candles are unchanged from the handoff. No bars are forward-filled.
- `shadow_decide(candidate_id, decision: "take"|"skip", reason ≤ 1000 chars)`
  → `{decision_id, candidate_id, decision, reason, committed_at, timing:
  "on_time"|"late", clean_order, labels, content_sha256}`. One immutable row
  per (actor, candidate); an identical retry returns the original, different
  content conflicts. An unknown or non-today candidate is refused.


**Manual candles, existing `check:read` scope.** `candles(symbol, interval:
"1m"|"5m", bars=60)` accepts 1–120 bars. Use the packet candles for the shadow
decision; use this tool only **after committing**, or for a separate manual
question. It is logged like every other tool. A call between publication and
commit makes `clean_order=false`; no exception is added for candle reads.

Each scanner pass atomically publishes per-symbol rolling files in
`/var/lib/tradejournal-shadow/candles/`, beside setups, with up to 120 completed
one-minute bars and session-to-date completed five-minute bars. Rows have Unix
UTC start/end timestamps; `last_bar_time` is the last completed bar's end in ISO
UTC. Source is `tradier_timesales_1min`, feed `full_market`. The tool uses a file
only when its latest one-minute bar is at most 120 seconds old (never future).
Missing, stale, malformed or wrong-feed files return `status=insufficient_data`
with `candles_unavailable`; there is no provider fallback or IEX request.
Completed rows must have valid finite OHLCV and ordered timestamps, and the
requested interval must itself be fresh. Every response carries source, feed,
last-bar time and age; unavailable data has null time/age. The response deadline
for file work is four seconds, below the 15-second proxy response-header budget.
Up to four reads may remain in flight; a timed-out worker retains its slot until completion.
The hosted ChatGPT caller's budget is not configurable here.

Packet candles are persisted with the candidate before handoff, so a restart
cannot replace them with later observations. Original v1 setup hashes remain
valid for importing old decisions. Candidate facts, detection, rules and email
payloads are unchanged. Missing bars are missing observations, never synthetic.

**Decision export (check service → private backend).** On each commit the
check service also writes the row as `decision-<candidate_id>.json` (atomic
rename, fsynced) in `/var/lib/tradejournal-check/shadow-outbox/`, the only
directory its unit may write. The API user gets read access to that one
directory (traverse-only on its parent) through an operator step; the ledger
and every other check file stay unreadable to it. The scanner watcher reads
new decision files each pass. No socket, route or database credential is
added in either direction, and the check service's units do not change.

**Paper events (private backend).** `ScannerEvent` rows with keys
`shadow_decision` (copied from the outbox, including timing and labels),
`shadow_entry`, `shadow_exit_intent`, `shadow_exit`, `shadow_unresolved`.
The same pricing rules as the rules-only trade apply: a two-minute window from
decision to priced entry or exit, quotes updated at or after the decision, a
late-noticed exit condition ends `shadow_unresolved`. No new table or migration.

## Scorecard (S1 version)

Report sessions before and after the v2 candle rollout separately; they have
different information available to Jo and must not be pooled as equivalent evidence.

Per day and cumulative: setups; Shadow Isaac TAKE / SKIP / late / no response;
rules-only P&L over all priced setups; Shadow Isaac P&L over its priced TAKEs;
the P&L of the rules trades it skipped; counts with `clean_order` true. Any
group under 30 decisions says "not enough evidence".
S2 extends this display with [Isaac trade links and disagreements](shadow-build-plan.md#s2--built-isaac-in-the-scorecard).

## Acceptance

- One live session where every published setup has a decision, late or no
  response, and every on-time TAKE has a priced entry after its commit or is
  `shadow_unresolved`.
- A token without `shadow:decide`, another actor, a forged candidate ID, a
  non-today setup and a commit after expiry are each refused or recorded as
  late, with tests.
- A fixture where a trade closes on the setup day proves `history` excludes it;
  one live spot check repeats this.
- `clean_order` is false in a fixture where `position_check` is called before
  the commit.
- Restarting either service leaves one decision and at most one shadow entry
  and exit per setup.

### Pipeline acceptance — October 16 evidence, owner closeout October 17

The owner accepts S1 as a separately formed decision pipeline for comparison
with Isaac, not as a profit engine. On October 16, all eight published setups
received one on-time Jo SKIP each: seven receipts had `clean_order=true`, and
one retained the conservative false flag. The October 17 read-only audit
matched those eight unique check-ledger receipts to the eight published
scanner candidates. October 15's four no-response dispositions remain in the
record; acceptance does not erase that earlier gap.

Saved October 15 focused verification passed 114 tests with no failures or
errors. It covers missing scope/wrong actor, forged or non-today setup refusal,
late decisions, same-day history exclusion, call-order flags, immutable retry
and restart recovery, and the simulated TAKE entry/exit path. Source-side live
history-cutoff evidence is retained; the original returned-history-card
comparison remains unproven and is not held open as a pipeline blocker by this
owner closeout. Fixture proof is not relabelled as live execution proof.

The natural TAKE lifecycle remains **unproven live** because the scanner has
not produced a setup Jo judged takeable. Do not force a TAKE, replay an expired
setup, change decision thresholds or restart services to manufacture evidence.
This missing natural opportunity does **not** block accepted pipeline status.
A later natural TAKE is observed under the existing rules, not a new experiment.

Private evidence: bounded-closeout-20261017/closeout.json,
shadow-closeout-live-20261017.json, and s1-closeout-quotes-20261017.json in the
October 15 scanner-search task artifacts; saved `jo-shadow-audit/focused-tests.xml`.
No private receipts or journal data are committed here.

At **50 resolved rules-only S1 paper trades** (distinct candidate IDs with an
exit, with unresolved entries reported separately), give the owner per-family
underlying and option results as a **keep/turn-off** decision. Preserve scanner
version, the factual-prompt-change boundary, same-day versus later expiry,
quote timestamps, commissions, observed spread and 2x-spread stress. Report
unavailable underlying entry/exit prices or R as missing rather than inventing
fills or using later bars. This is descriptive forward evidence, not permission
to tune parameters or automatically turn a family off. Keep the factory paused.
Instrument changes are deferred; only if a family later demonstrates underlying
edge should a separately authorized comparison start with stock.

### Activation evidence — October 13, 2026

The application and check runtime are running main `23b7c6c2035516542e5bdd208ab09e4983e073b6`
from successful Deployment package run `38422300117`. Artifact hashes and the
disabled check bundle inventory were verified; upgrade used exact manifest
`88a09855598606549a1bae0f802b382882cea08839fe94cae8af926fc2582377`.
All three existing SQL pins and nine check units matched; no SQL was applied.
Isaac confirmed the Auth0 permission/client grant and explicitly authorized
this activation's market-hours restarts.

The exchange and both config paths are enabled. Fresh keys/features, service
health and the UID network policy passed. Checks inside the actual service
mount namespaces proved API setup-write/outbox-read and check setup-read;
API ledger access and parent listing, check setup-write and API membership
in the check group are denied. Setup directories are 2750 and outbox is 0750.
Root-private recovery backups are retained with the newest previous runtime.

The working Check catalog exposes both shadow tools. At Isaac's explicit
request, the lead set up one enabled **TJ Setup → Jo shadow + co-pilot** task
owned by Trader Jo. The saved prompt preserves shadow-first ordering, paper-only
decisions, both labels and fresh co-pilot Go-only alerts. It does not continuously
monitor candles or promise follow-up events that the scanner has not implemented.

Isaac entered the Gmail app password through a root-only hidden terminal
prompt. At 14:22 Eastern, the lead atomically added only the three scanner SMTP
settings, preserving the current environment and shadow paths with a private
backup, and restarted the API under Isaac's activation timing authorization.
The API health check and loaded settings passed; the check service remained
healthy. The separate `TJ Setup delivery test` reached the owner's inbox and
does not match the task's subject filter. A natural NBIS setup detected at
14:20:49 was emailed at 14:22:35 and reached that same inbox. Previously
expired setups were marked expired rather than emailed. The read-only Gmail
connection remains separate from the SMTP credential.

The v3 post-five-minute readiness check returned `oauth_refresh_token_missing`.
Isaac subsequently created v4 in Jo's conversation; its read-only baseline at
15:04:20, six-minute check at 15:10:29 and 60-minute check at 16:04:29 passed
without reconnecting. The production task now uses that v4 connection. The owner's longer connection
checks remain separate. Access-token lifetimes remain 300 seconds; no Auth0
grant or longer token lifetime was used as a workaround.

The initial natural NBIS, AAPL and AMD emails reached Gmail but produced no
recorded task run or authenticated check call. The task was enabled; its native
inventory initially reported no last run, and exposes no delivery/error log.
Bounded delivery-only tests established a working distinction: self-sent
Gmail messages carried both SENT and INBOX labels and produced no recorded run,
while an independent incoming message from the owner's connected Outlook
account automatically woke the task in 18 seconds. This is observed behavior,
not a claim about undocumented Gmail event filtering rules.

At Isaac's request to fix the route, the lead added one narrow Outlook rule:
only the existing scanner sender **and** `TJ Setup:` in the subject forward to
the original owner Gmail alias. Other rules were preserved; the initial relay
added no delete/move or broad inbox forwarding. A VPS SMTP probe sent at
15:44:35 reached Gmail as an incoming `FW: TJ Setup:` message at 15:44:38; the automatic task
acknowledgement at 15:44:53 identified that exact Gmail message. It used no
candidate ID, financial tool or shadow decision. The lead then changed only
the API's scanner email recipient to the owner's relay inbox, retained a
private environment backup, restarted under the existing timing authorization,
and verified API health, unchanged SMTP credentials/shadow paths and check health.

The full production prompt was restored on the same task at 15:46:47. A fresh
Scheduled editor read-back shows an enabled Gmail new-email trigger with the
relay sender and `^FW: TJ Setup:` filter. Its source guard validates both the
outer relay recipient and the original scanner sender/recipient/subject before
extracting the original UUID, explicit stale time and JSON. Tests and expired
setups remain ignored. A final test through the active API recipient arrived
at 15:47:56; the native task inventory records its automatic production run at
15:48:15. The task stayed silent, and a read-only ledger audit found zero
authenticated check calls or decisions since the relay probe. Delivery proof
is not actual Jo decision or first-session acceptance; that evidence remains pending.

At Isaac's subsequent request to keep the inboxes clear, the Outlook rule gained
a move action to **TradeJournal Setups** after forwarding. A narrow Gmail filter
labels matching owner-relay/scanner messages to the setup alias as
**TradeJournal/Setups** and skips the inbox; existing matching conversations
were filed as well. Nothing was deleted or marked read. A fresh SMTP probe at
16:03:01 reached the Outlook folder and Gmail label at 16:03:08 without an
INBOX label; native task inventory records an automatic run at 16:03:34.
Thus the tested filing configuration preserves the incoming-event wake-up.

A read of a naturally published, already-expired AMD setup succeeded with
`expired=true`; no decision was submitted. Its historical cohorts matched the
published features filtered before that session's New York midnight: 1,584
eligible rows, one same-day row excluded, seven same-setup rows and 38
same-ticker/side rows. Actual Jo `clean_order` and post-decision entry evidence
remain pending. Two scanner setups existed before activation and were never
shadow-published; they are not live shadow acceptance evidence. No synthetic
setup or operator decision was introduced into the live book for this proof.

## Out of scope

Shadow-chosen contracts, sizes or exits; WAIT; MCP Events; a separate Dot;
changes to `pre_trade_check` outputs, the journal export or the fixture
advisor.
