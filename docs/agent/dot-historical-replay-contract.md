# Jo's weekend historical market replay

Selected after Jo saved/reopened real-data MU/NBIS SKIPs. This isolated-demo
increment uses retrospectively retrieved raw Alpaca bars for a past regular
session and its next verified session. Jo chooses source-linked TAKE/WAIT/SKIP
before any continuation is exposed. It is an assisted historical exercise,
not contemporaneous source observation, a blind comparison or a live watcher.

## Two clocks and sealed evidence

Retain original minute timestamps, the actual provider retrieval time and the
actual decision receipt time. `simulated_as_of` is the historical information
cutoff; it is never substituted for actual retrieval/receipt metadata. Only
completed minutes at/before that cutoff enter the public packet and source
facts. The chart uses that cutoff. The real exercise deadline is twenty hours
after import. Plan/WAIT expiry is on the historical clock, at/before the end
of the second verified session. Freshness is checked at the fixed simulated
cutoff only in the separate historical policy. Live-market freshness rules
remain unchanged. Provider history may contain subsequent corrections; this
does not prove what the provider actually published at the historical cutoff.

Historical expiry entry uses explicit `YYYY-MM-DD HH:mm` Eastern wall time,
independent of the browser timezone. WAIT and TAKE have no default expiry:
the writer enters a valid date after the cutoff and no later than the historical
maximum, then confirms its ET/UTC preview matches the condition or plan.
Changing the expiry or condition clears confirmation. Invalid dates and DST
gaps/folds are refused rather than shifted. Existing immutable records, including
Jo's October 7 condition saved with an October 8 expiry, are not rewritten.

The new schema is `practice-historical-replay-long-15m-v1`; the execution
contract is `historical-paper-replay-v2`. It supports MU/NBIS long shares,
source-linked trigger/stop/target, regular-session complete 15-minute close
confirmation, an entry guard, two-session maximum and `p0-cost-v1`. The public
packet has at most sixty pre-cutoff minutes. Coverage reports minutes without
supplied bars and partial intervals, separately from provider/input failures.
Never assume a missing IEX bar means a broken provider or fill it forward.

The operator seals the later original bars with a random nonce before publishing
the public context. Neither run/list/decision/card nor cloud read tools expose
the continuation before the actor's own saved TAKE starts its replay. WAIT/SKIP
produce no replay or paper entry. This is a bounded sample-account replay action;
the generic arm/paper routes and live watcher refuse the historical schema.

Replay reuses the pure existing paper reducer with original epoch times.
Each complete post-cutoff fifteen-minute bucket is detected two seconds after
its close. Entry uses the first full minute beginning after that detection.
Missing confirmation intervals are never considered complete. Missing required
entry/hold minutes are unresolved, and insufficient continuation for a complete
two-session hold is unresolved rather than a fabricated exit. Stop-first,
reference entry guard, costs, planned-R denominator and three-times costs keep
the existing reducer semantics. Save the entire receipt atomically once; exact
retries/read/restart return it without recomputation or changing the decision.

This capture does not supply frozen split-coverage evidence. V2 evaluates only
the first historical session: an open position or pending trigger needing the
next session becomes unresolved at the first close, even if next-session bars
are available. A split must never look like an economic gap-stop loss, and raw
prices are never adjusted silently. Same-session stop/target outcomes and
within-session expiry remain evaluable. A verified overnight basis is a later
data prerequisite, not an inferred absence of splits. Original v1 receipts are
readable snapshots, but no new v1 replay can start; use a fresh v2 exercise and
identity without replacing prior evidence/keys.

## Isolation and operations

Use a new own-run identity with `market_decision_write=true` and
`historical_replay=true`; no journal, ordinary sample writer/replay or other
session access. Require authentication, marked trial, existing market writer
flag and explicit `TJ_HISTORICAL_REPLAY_ENABLED=true`, with the isolated factory
state. Grant create/reset and every restricted read match the frozen assigned
actor. Serialize saves/replay against current sessions, grants and revocation.
Strict bodies/CSRF/budgets remain. Ordinary market-role accounts cannot start
historical replay and historical accounts cannot start the old sample replay.

The private VPS host capture uses only the existing provider credentials and
finite fixed calendar/minute GETs. No app/database imports, paid model calls,
feed upgrades, proxies, redirects or unbounded pagination. Import only a
root-owned private bounded file with verified consecutive session calendars,
strict symbols/source/OHLC/timestamps and original retrieval metadata. Retain
identical files/runs/keys; refuse replacement or implicit login rotation. No
provider/model secrets enter the isolated runtime. Production/network rules,
prior sample/market rows/credentials and D1 activation remain unchanged.

Native proof uses a separate run/account, never Jo's decisions, then revokes
that account. Verify source/cutoff/chart/coverage, a conditional TAKE with replay,
WAIT/SKIP refusal, hidden continuation, ownership/integrity/clock denials, exact
numeric outcomes, atomic concurrent retries, service restart and prior-record
preservation. Full verification, Postgres/Ubuntu CI and tier-two native reviews
are required. Actual Jo use and laptop-off observation remain separate gates.

Operator commands are `deploy/dot_historical_capture.py --day YYYY-MM-DD
--cutoff HH:MM` on the host, then `deploy/dot_historical_import.py` with the same
day/cutoff in the pinned trial virtualenv. The capture requests a calendar range
of at most eight dates, retains its first two verified past sessions and makes
four stock-bar GETs (two symbols by two sessions), each bounded to one response
and ten seconds. Root-owned 0600 handoffs stay under
`/etc/tradejournal-dot-trial/historical-handoff-YYYY-MM-DDTHHMM.json`.
The explicit updater option is `--enable-historical-replay`; its selected
selected source files include the historical modules and the
existing D2 choice modules, with no
test fixture, dependency, market data or credential in the archive.

## Scanner replay — historical selection benchmark v0

`practice-scanner-replay-v1` is a separate sequential exercise in the isolated
historical demo. It measures Jo's selection of **underlying price paths** under
frozen S1 scanner rules; it does not estimate executable options returns. The
capture operator reads bounded Alpaca SIP raw minutes, prior daily bars and
verified regular-session calendars without importing the app or a database.
September 14, 2026 onward is SC-3 holdout and is refused unless the operator
explicitly passes `--allow-holdout` at capture and preparation. The frozen
universe, scanner version and parameter hash never change.
Capture verifies at least fifteen distinct prior daily sessions for every
symbol in a bounded ninety-day lookback; missing ATR14 blocks preparation.

The generator streams completed minutes through unchanged `scanner_rules.scan`,
using caller cooldown, taken/fade limits and a rules-only underlying proxy for
open-trade suppression. Jo's choices never affect this shared stream. Alpaca
SIP replaces live Tradier timesales/daily ATR; unavailable option eligibility,
quote failures and actual monitoring latency cannot be reconstructed. Missing
minutes follow live sparse-bucket selection: aggregate only supplied completed
minutes, evaluate occupied partial five-minute buckets, skip an empty current
bucket and resume at later occupied buckets. No missing minute is synthesized
or treated as proof of no trades. Strict v1 selection is retained only for the
generation-frequency comparison; reports disclose coverage and count changes.
Coverage counts supplied/expected/absent regular minutes, first missing minute,
partial/empty five-minute buckets, scan symbol-minutes lost to empty eligible
buckets, blocked scan slots, emitted setups and strict-v1 count deltas per
symbol/session. The actual lost setup count is unknowable
without source bars; scan slots are not fabricated setups or provider outages.
The proxy uses the non-same-day flat rule because historical expiry is unknown.
Raw prior daily ATR can straddle corporate actions without verified basis
coverage, so every result carries `basis-unverified`.

Packets retain the `shadow_setup` candidate/live/history field names and units,
with historical contract/quote/liquidity information explicitly unavailable.
Only completed candles at/before detection enter the last sixty minute bars and
session-to-date five-minute bars, with original timestamps and feed. The existing
history cohort builder includes only trades closed strictly before that day's
New York midnight and removes fill keys. For real history,
`backend/scripts/scanner_replay_history.py` runs beside the existing approved
feature publisher: trade rows remain there; only sanitized aggregates leave.
Preparation binds each card to its candidate, cohort dimensions and exact
pre-session cutoff, freezes the aggregate input/source hashes and refuses a
missing or mismatched card. `history.available` and `history.source_state`
distinguish missing inputs from available but zero matching trades. Packets
carry `informed-by-history` only when a cohort actually contains prior trades;
otherwise they say `prior-trade-history-unavailable` or
`history-available-no-matching-trades`. No new journal grant is needed. Provider retrieval time, simulated
detection cutoff, first packet service time and actual commit time stay distinct.

The operator prepares a frozen batch before any choices/results, recording the
random split seed, practice/exam dates, full instruction text, `prompt_version`,
scoring policy/hash and source hashes. One run is one historical session. The
existing practice tools use explicit `exercise_kind=scanner_replay`; an absent
date on `list_practice_runs` starts/resumes the next practice run, then exam run.
Only `next_setup` is exposed, followed by one immutable TAKE, SKIP or
INSUFFICIENT_DATA with a reason of at most 1000 characters. Exact retries recover
the same receipt; different content conflicts. Wall time runs from first packet
service to commit and includes interruptions. Historical deadlines never expire
a scanner run; current credential expiry/revocation still applies.
On an interrupted, already-started run Jo explicitly calls
`get_practice_run(run_id, resume=true)`. The next uncommitted setup receives one
durable resume timestamp, copied into its immutable choice. Normal repeated
reads are not resumes; terminal receipts cannot acquire later markers. Reports
include wall seconds and a resumed-setup column. Full default instructions use
`tj-shadow-selection-v3`, including explicit inspection of the history fields.

Each continuation is sealed with a random nonce and a public commitment. No
explicit outcome feedback is exposed during a run. Practice results reveal
together only after commitment or operator abandonment. Exam results remain
sealed until **every exam session in the batch is committed**; abandoning an
exam permanently withholds that batch. Generic browser practice projections
refuse scanner runs, including for the owner; the operator report uses the same
gate. No tool abandons, replaces, arms, fetches data or calls a paid model.
The separate `scanner_replay=true` grant requires the existing historical and
market writer flags, the isolated historical factory, `journal_read=false`, no
ordinary sample grants and the entire frozen actor-bound batch (maximum thirty
sessions, scanner-universe symbols). Existing MU/NBIS grants are unchanged.
Merging does not activate, rebind or publish any connection or service.

Scoring is deterministic and same-session only. Rules enter at the open of the
first full minute strictly after detection; Jo's delayed view enters strictly
after detection plus the frozen delay (default sixty seconds). Selection is
also scored on Jo's TAKEs at the rules entry time. Stop/target checks start with
the minute after entry, matching the live scanner's entry-minute exclusion.
Reports explicitly list **entry-minute stop not checked (optimistic)**.
Stop wins a bar touching both; a gap through stop fills at the adverse open,
and favorable target gaps are capped at the target. The sixty-minute time stop
runs from each actual proxy entry; clock exits use the first eligible minute
open at/after time stop or `scanner_rules.flat_at(..., same_day=False)`.
An entry open at/beyond stop or target is invalidated, with no entry or invented
P&L. Missing required entry/hold/exit bars are unresolved, never forward-filled.
Adverse slippage in basis points and per-share-per-side costs are frozen,
default zero and labelled. R uses the same frozen detection-close-to-rule-stop
distance for baseline and delayed views; dollars use one hundred shares.
`scanner-selection-replay-v2` versions the frozen policy hash and includes fixed
$0.02/share/side sensitivity. Both cost views use identical raw fills, times and
resolved cohorts; fees change net R/dollars, not entry eligibility, busy state
or the candidate stream. Invalid frozen stop/target geometry is counted as a
live signal but invalidated without a proxy entry or P&L; it cannot fabricate
open-trade suppression. A hold made uncertain by missing entry/exit minutes
conservatively suppresses until the planned baseline entry plus sixty minutes
or flat deadline, then releases selection; its monetary result stays unresolved.
This deterministic proxy deadline can differ from actual live close latency. Legacy v0/v1 snapshots and exact choice retries remain
readable; only v2 accepts new choices/generation. V1 retained scoring remains
readable/recomputable, while v0 score recomputation is refused. Corrected
display labels do not rewrite prior contexts, choices or receipts.

Reports separate practice/exam, per-run/cumulative and setup-type rows, with
TAKE/SKIP/INSUFFICIENT_DATA counts, resolved/unresolved/invalidated coverage,
session counts, selection and delayed-entry R, skipped results, win rates and
take-all/skip-all/seeded-random baselines. Unknown contract eligibility is never
called `no_contract`; the eligibility cohort comparison is omitted when all
eligibility is unknown. The existing S2 linker links owner-supplied actual trade
snapshots; Isaac's realized options P&L is separately labelled and never included
in the comparable underlying ranking. Thirty decisions is a display warning
threshold, not proof of an edge; within-session setups are correlated.
Decision counts render as plain TAKE / SKIP / INSUFFICIENT_DATA text.

The scanner parameters were selected using March–September 2026 data. An exam
therefore tests Jo's selection conditional on those rules, not an untouched
scanner test. Later candles can reveal earlier price paths, and Jo's memory can
contain later information: sessions are sequential simulations, not independent
blind questions. Labels include `model-memory-unverified`, `no-historical-news`,
`underlying-scored`, the applicable history label and `independence-unverified`.
Provider corrections, no historical news/Level 2, unknown option eligibility
and raw-basis limits remain disclosed.

Start with a practice-only batch. Required acceptance is **actual Jo** completing
one full session through the demo connector, resuming at the next uncommitted
setup after interruption, then reading the end-of-run scorecard. Signed fixture
proof does not substitute. Actual Jo completed the August 25 session through D0 on October 13 ET after
an interruption and whole isolated-service restart: one immutable SKIP, explicit
resume marker and terminal scorecard were read back. Its history field was
`available=false`, `source_state=missing`; the original unconditional informed
label was incorrect and is preserved only in immutable old evidence. Frozen
multi-session exam evaluation follows practice; no exam is currently prepared.
Real-data generation proof on October 13, 2026: August 25 SIP/raw capture returned
62 distinct prior daily sessions through August 24 for all twelve symbols; all
had positive ATR14. It supplied 4,672 of 4,680 expected regular symbol-minutes:
CRDO lacked seven and LLY one. The original strict-v1 prefix guard lost 196 scan
symbol-minutes and blocked forty scan slots; one setup was emitted. That
coverage is retained as original evidence; v2 no longer blocks all later slots
for an isolated missing minute. The actual lost setup count is unknowable.
No Jo decisions, database writes, service activation or model calls occurred.
Generation-only follow-up covers all 135 regular sessions March 2–September 11:
1,172 v2 setups (mean 8.68, median 8, range 0–24), versus strict-v1 1,169.
All twelve symbols have prior-session daily ATR in every capture. Sparse parity
adds three LLY fade-long setups. The earlier split-adjusted five-minute
calibration had 1,193; raw-minute/proxy generation is 1.8% lower. Live since
enablement has zero stored candidates October 12 and fourteen October 13;
October 13 is an activation baseline, not a full SC-2 acceptance session, and
source errors prevent an uninterrupted-exposure claim. One candidate-bearing
live date does not establish a systematic frequency deficit. Scanner parameters
were not tuned. `backend/scripts/scanner_replay_frequency.py` produces the
zero-inclusive per-session/symbol/type report and strict-versus-parity counts.
The next practice-only sample uses uniform calendar sampling with seed 305:
May 4 (6 setups), May 6 (14), June 12 (5), July 24 (8), September 10 (4).
No profit results or Jo choices selected these dates. All 37 packets have
cutoff-bound history aggregates; nine have no matching trades. Actual Jo's
five-session completion and combined scorecard remain pending; exam count is zero.
Operator commands are `backend/scripts/scanner_replay_capture.py` for private
capture and `backend/scripts/scanner_replay_operator.py` for prepare/report/abandon
on the marked isolated database. Live scanner/shadow ledgers, SC-0, production
journal access, VPS activation, options pricing and paid inference are unchanged.
