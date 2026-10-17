# Setup scanner S1 — candidates and a rules-only options baseline

Selected by Isaac on October 12, 2026 as build step 2 of the
[shadow trader design](shadow-trader-design.md#build-order-after-dots-steps-35).
**Built and enabled on the VPS October 12, 2026** (see build status). S1 has
no model, no connector and no real order; its only outbound message is the
optional setup email below. It produces the setup feed that the
co-pilot and the shadow trader will later consume, plus the rules-only paper
baseline they are judged against.

## Why these rules

From Isaac's 1,525 closed option trades (July 2025 – October 9, 2026, both
accounts, entry context saved at each first fill; analysis run October 12 and
not stored in the repo):

- Entries against the move toward VWAP (call below VWAP, put above it) earned
  about +$11.1k, profit factor 1.68 — his strongest setup.
- 15-minute opening-range breaks earned about +$2.4k; calls did better than puts.
- Trades closed within 60 minutes earned about +$35k; trades held 1–6 hours
  lost about −$17.6k and overnight holds about −$4.6k.
- 0DTE earned about +$17.4k; 1–2 DTE lost about −$9.5k.
- Leaks: puts in the first 15 minutes (−$5.3k), puts chasing an extended move
  (−$5.2k), and a sixth-or-later entry in a day (slightly negative).

Setup tags were approximate rules over saved context, so these figures choose
starting rules; they are not evidence that the rules have an edge.

## Universe and session

The default remains `AAPL AMZN GOOGL META SPY QQQ NBIS MU CRDO MRVL LLY AMD`.
The owner can add/remove any US stock or ETF ticker on `/scanner`, up to 12
at once, and explicitly save the selection. `GET/PUT /scanner/settings`
stores it separately from chart settings in the existing `chart_settings`
table's `scanner-universe` row, with revision checks to reject stale saves.
The monitor reads the selection each scan pass; no restart is needed. An empty
list pauses new setups. Saving never enables the scanner, modifies past setups,
or stops monitoring existing rules/shadow paper trades. Ticker syntax is checked;
provider data and qualifying options are still required for a paper entry.

The original universe retains `s1-v1`; a different universe is `s1-v2`, with
the sorted selection included in its parameter hash. New candidates freeze the
selected universe and settings revision in their facts. Restoring the default
restores the baseline identity; cooldowns, duplicate checks, daily caps and
open-trade protection span both versions. Historical replays retain their fixed
baseline universe. Day/cumulative results include prior selections; each setup
keeps its original identity. MSFT, NVDA and TSLA remain absent from the default,
but the owner may now explicitly include them.

Regular session only, scanning completed
5-minute underlying bars from 09:45 ET. No new candidate after 15:00 ET.

## Setups (scanner `s1-v1`)

Prices are underlying prices from completed bars. Daily ATR is the 14-day ATR
as of the prior close. Parameters are versioned; `s1-v2` changes only the
selected universe, with the same setup and paper-trade rules.

**VWAP fade (calls and puts).** Long version (call): price has been at least
0.35 daily ATR below session VWAP, then a completed 5-minute bar closes above
the previous 5-minute bar's high while still below VWAP. Stop: the session low
reached during the stretch, minus 0.05 daily ATR. Target: session VWAP at
detection. Require target distance ≥ stop distance. The put version mirrors it
above VWAP. At most two fade candidates per symbol per day.

**Opening-range break (calls only).** The first completed 5-minute bar of the
day to close above the 09:30–09:45 high, closing by 10:45 ET, above VWAP, with
volume at least the average of the three opening-range bars. Stop: the
opening-range midpoint. Target: entry plus twice the stop distance. One per
symbol per day.

**Cooldown and duplicates.** No new candidate on a symbol while one of its
paper trades is open, and none within 30 minutes of that symbol's last
candidate. A repeated detection of the same bar is the same candidate.

**Flags (recorded, not filtered).** `put_extended` (more than
1.5% beyond VWAP or 0.8% beyond EMA9 in the trade direction), and `sixth_plus_entry`
(Isaac's sixth or later entry that day, filled in at review, never visible to
the scanner or a later shadow before commit). Puts in the first 15 minutes
cannot occur because scanning starts with the 09:45 bar, so that leak is
measured on Isaac's own trades, not flagged here.

## Contract choice

A fixed rule picks the contract at detection from the Tradier chain already
used by [`options_chain.py`](../../backend/app/engine/options_chain.py):

- Expiration: same day if listed; otherwise the nearest with 3–7 days to
  expiry. Never 1–2 days to expiry.
- Delta 0.25–0.45, closest to 0.35; call for long setups, put for short.
- Open interest ≥ 500, day volume ≥ 100, bid > 0, spread ≤ 10% of mid.
- No qualifying contract: the candidate is saved as `no_contract` and has no
  paper trade.

## Candidate record

Append-only, one row per candidate: ID, scanner version and parameter hash,
symbol, setup, direction, flags, detection time, source bar start/close times,
frozen facts (last bar OHLCV, VWAP, opening range, daily ATR, EMA9),
underlying stop and target, chosen contract with its quote time, bid, ask,
delta, open interest and volume, and a hard expiry 10 minutes after detection.
The later co-pilot and shadow read this frozen record; nothing edits it.

## Rules-only paper trade

Every candidate with a contract gets one simulated contract, priced from
option quotes and never backdated:

- **Entry:** the ask of the first quote taken after the candidate is saved.
- **Exits, all judged on the underlying and priced at the bid of the first
  option quote after detection:** stop, target, a 60-minute time stop, and a
  flat-by time of 15:45 ET for same-day contracts or 15:50 ET otherwise.
  Nothing is held overnight.
- **Missing quotes:** if no quote arrives within 2 minutes of an entry or exit
  decision, the trade is `unresolved` rather than filled at a guessed price.
- Commission $0.65 per contract per side, disclosed.

Results report per-contract dollars and return on premium, by setup, symbol,
direction, flag and expiry bucket. A second view applies 2× the observed
spread as a pessimistic cost check.

## Storage, service and safety

New tables for candidates and paper events, added by an Alembic migration.
That makes S1 consequential under the [review policy](pr-review.md): full
verification, an independent review, and the deployment backup and
market-hours rules in the [deploy guide](../../deploy/README.md#automatic-deployment).
The scanner runs inside the existing backend job system, off by default
behind one environment flag, uses existing Alpaca and Tradier credentials,
and sends nothing except the optional setup emails below. Restart recovery resumes open paper trades from
saved events; a monitoring gap longer than 2 minutes on an open trade marks it
`unresolved`.

## Before switching it on

1. **Historical fire-rate check** (done, results above). Replay the rules over completed sessions
   to confirm a manageable candidate count (target 3–15 a day in total) and
   to catch rule bugs. Use stock minute bars only, with no option prices and
   no profit tuning. Keep the most recent four weeks untouched as a holdout.
2. **Owner approval to enable on the VPS**, then 10 live sessions forward.
   Forward results decide whether the rules stay; nothing is tuned on them
   until 50 resolved paper trades exist.

## Historical fire-rate check (October 12, 2026)

Replayed over 135 sessions (March 2 – September 11, 2026) of Alpaca SIP
split-adjusted 5-minute bars; September 14 onward is held out and was not
examined. Counts and exit types only; no option prices and no profit figures.
The script lives outside the repo.

| Rule set | Setups per session | Note |
|---|---|---|
| Fade 0.25 ATR, opening-range break any time, no volume check | 18.1 | Above the 3–15 target; the break fired on 58% of symbol-days |
| Break by 10:45 + volume ≥ opening-range average | 12.9 | Break cut from 691 to 108 |
| **Above + fade 0.35 ATR (adopted as `s1-v1`)** | **8.8** | 1,193 setups: 601 fade puts, 484 fade calls, 108 break calls; 1 session had none, busiest had 24 |
| Above + fade 0.5 ATR | 4.3 | 11 sessions with none |

Every symbol produced setups and no session had missing data. In the adopted
set, 57% of underlying exits were the 60-minute time stop, 32% stops, 9% targets
and 2% the flat-by time: the VWAP target is usually farther than an hour away.
This is a property of the rules to watch forward, not a reason to tune them.

## Build status (October 12, 2026)

Built October 12; enabled on the VPS the same day. `app/engine/scanner_rules.py` holds the rules and
`app/engine/setup_scanner.py` runs them inside the level alert monitor's
pass when `SETUP_SCANNER_ENABLED=true` (default off, and level alerts must
also be running). Migration `a7c3e9f1b2d4` adds `scanner_candidate` and
`scanner_event`. The owner page is `/scanner` (`GET /scanner/day`).

Implementation choices within this contract: session VWAP uses each
minute's typical price; daily ATR is the simple mean of 14 true ranges from
Tradier daily bars; the scanner judges only the newest completed 5-minute
bar and skips one noticed more than two minutes late; stop and target are
judged on completed 1-minute bars that start after the entry minute, the stop
winning a bar that touches both. Same-day contracts are flat by 15:45 and
others by 15:50 (or 10 minutes before an early close).

An entry or exit is priced only from a quote read within two minutes of its
decision whose bid and ask were both updated at or after the decision;
otherwise the trade is `unresolved`, even if a usable quote arrives later.
A gap in watching an open trade ends it `unresolved` only when an exit
condition fell inside the gap: the minute bars cover the rest of the gap, so
nothing is backdated. The review-time `sixth_plus_entry` flag counts trades
opened that day, not fills.

Budget when enabled: each 5-minute bar reads 12 one-minute series from the
chart feed's shared 60-per-minute allowance (plus 12 daily series once a
day), and each open trade re-reads its symbol about three times a minute. A
symbol whose read is refused is retried on later passes while the bar is
still within two minutes. Scanner option quotes make one Tradier request per
read, with no retry sleep on a rate limit or transport failure. The request
still uses the existing 10-second timeout and runs synchronously; the scanner
retries on later monitor passes within the same two-minute pricing window.
Other callers retain their existing quote retries. Watch for `rate_limited`
chart reads during the first live sessions.

Fixture tests cover the rules, duplicate suppression across a restarted
process, entry and exit pricing, missing quotes, late exits and the
review-time flag. A seeded local page was checked at desktop and 375px
widths. The first live session (October 13) is recorded under
[daily health acceptance notes](#daily-health-acceptance-notes).

## Setup emails for Jo (co-pilot trial)

Isaac chose on October 12, 2026 to try Jo on live setups before the forward
trial finishes. Off unless `SCANNER_EMAIL_TO`, `SCANNER_SMTP_USER` and
`SCANNER_SMTP_PASSWORD` are set in the server's private environment.
`app/engine/scanner_mail.py` sends one plain-text email per setup that has a
contract, from Isaac's Gmail to his own `+tjsetups` address using a Google app
password (separate from the read-only Gmail OAuth token that imports fills).
At most 15 a day; a setup past its 10-minute expiry is never sent; a failed
send is retried each pass while fresh. Each send is a `ScannerEvent` with key
`email` (`sent`, `expired` or `skipped_daily_cap`).
Gmail's iPhone app cannot notify for one label, so each sent email is also
pushed once to the phone through ntfy (`app/engine/ntfy.py`, the topic in
`alerts.env`; tapping opens `/scanner`). The push is best effort and not
retried: the `email` event records `push` as `sent`, `failed` or `off`, and a
failed push never holds back the email.

Subject: `TJ Setup: <SYMBOL> <CALL|PUT> <setup> <HH:MM> ET`. The body holds
only market facts and rule output (no journal data) and one JSON line with
the exact `pre_trade_check` inputs, using the candidate ID as `operation_id`
so a repeated check returns the original. Jo's Gmail event task watches for
that subject prefix, runs `pre_trade_check`, saves `attach_model_verdict`,
and messages Isaac only on agreed criteria. The rules-only paper trade is
unaffected either way. Jo's ratings are assisted advice, not Shadow Isaac:
Jo reads Isaac's history through the pre-trade check.

## Acceptance

- Candidates appear with correct frozen facts and source times on a live
  session, and duplicates are suppressed across a restart.
- Every paper trade has an entry and exit quote time after its decision time,
  or is `unresolved`.
- One API restart with an open paper trade leaves exactly one entry and one exit.
- The owner can see the day's candidates and paper results in the app.

## Daily health acceptance notes

SC-0 runs weekdays at 16:30 America/New_York in the lead Codex chat, checking
service/scanner availability, setup/trade/email dispositions, actual saved Jo
decisions and failures. Local scheduling requires the Mac/app and tailnet access.
One dated receipt is recorded per regular session; ten full sessions start
October 14. A zero-setup day is not automatically a failure, and an absent Go
message is not automatically a missing decision. Delivery diagnostics do not
count as live decision/entry evidence.

- **2026-10-13 — activation baseline, excluded from ten-session count:**
  scanner/API available; 14 candidates, four no-contract, ten rules entries,
  nine resolved and one unresolved (`monitoring gap: exit condition noticed late`);
  four setup emails sent and six expired before email activation; zero recorded
  Jo decisions. Sent setups preceded the successful incoming-event relay repair.
  No chart `rate_limited`, scanner quote or email/shadow failure matched the
  session's inspected logs. Actual Jo decision/entry acceptance remains pending.

## Out of scope

Co-pilot alerts, Dot wake-ups, shadow decisions, real orders, intraday
re-entry rules and any change to Isaac's own trade records.

## Selected-stock awareness, separate from option eligibility

Owner-selected October 15, 2026 after NBIS's large rebound received no Jo setup
review. Two saved NBIS short-fade candidates were `no_contract`: October 16 was
1 DTE and October 23 was 8 DTE. Both original email and shadow handoff paths
required a selected contract. This was a stock-awareness coverage failure;
absence of a Jo decision did not mean Jo reviewed and rejected the move.

The 0-or-3–7-DTE policy remains only the original rules-only paper baseline.
Its motivating aggregate journal results above do not establish a causal DTE
edge or justify suppressing stock observations. The new advisory path does not
change that baseline's contract choice, entry/exit pricing, cooldowns, replay
identity, eligibility, or Shadow Isaac TAKE/SKIP records.

With `STOCK_WATCH_ENABLED=true` (default off and independent of the paper
scanner enable flag), [stock_watch.py](../../backend/app/engine/stock_watch.py):

- Captures a stock setup **before** option selection and before the baseline's
  open-trade/cooldown gates. Option errors or no qualifying option cannot erase
  this input. The frozen record says option eligibility is `not_evaluated` by
  this advisory path; it grants no trade authority.
- Monitors the same explicitly saved selected tickers once per minute through
  the exchange calendar's regular-session close, independently of the paper
  scanner's 15:00 cutoff. Empty selection pauses new stock alerts; removed
  tickers receive no new stock email/push. Existing selected settings and
  original paper monitoring retain their semantics.
- Detects a completed 15-minute move of at least max(1%, 0.35 prior daily ATR),
  or a rebound/drawdown from an **observed** session extreme of at least
  max(3%, 0.5 ATR). It requires 16 contiguous completed minute bars for the
  recent window, valid prices, prior ATR and source/bar freshness within 180 s.
  No missing-minute filling, future bars, retrospective backfill or implicit
  paid-feed fallback. It reads the existing shared Tradier minute/daily data.
- Uses a 30-minute per-symbol email cooldown and bounds stock-only email wakes
  to four per ticker and fifteen per session. A same-direction subsequent move
  must additionally differ from its sent/reviewed anchor by max(1%, 0.25 ATR).
  Shadow-pending setup guards take priority. Budget/cooldown/guard/source gaps
  are recorded as immutable stock status, not disguised as a Jo assessment.
- Publishes immutable, bounded `stock-alert-v1` files beside the existing public
  market snapshots, and appends stock records to the existing explicitly
  configured MW-2 store. The frozen selection/revision, evidence and hard
  ten-minute expiry survive retries/restarts. Interrupted publication recovers
  the original input, never extends its expiry.
- Sends stock-only mail through the existing scanner/Outlook relay:
  `TJ Setup: STOCK SYMBOL sta_UUID`, body only `Stock alert ID: sta_UUID`.
  Eligible paper candidates retain their single original setup email, with the
  separate stock-alert ID appended. The saved Jo task must use the
  [stock branch](../../deploy/market-watch/jo-stock-task.md), with its existing
  source checks and shadow-first ordering, before activation.
- Exposes `stock_alert` / `stock_alert_submit` on the existing isolated Check
  service under existing market-watch read/submit scopes. Public stock inputs
  only; no journal/position access or provider calls. Actor-bound input
  receipts and one immutable assessment per alert live in additive SQLite
  `stock_watch_input` / `stock_watch_review` tables, separate from shadow
  decisions and SPY forecast records. Exact retries recover a receipt; changed
  retries conflict. Expired new assessments refuse.
- Passes sealed reviews through the existing private outbox to the app.
  `watch`/`avoid` with `notify=true` may deliver one phone update; `no_view`
  stays quiet. New paper eligibility and TAKE/SKIP cannot be granted here.
  Phone messages explicitly separate stock awareness from option eligibility.
  Source expiry also bounds phone delivery; accepted or uncertain sends are
  never resent. Receipt IDs prove ntfy acceptance, not owner-observed display.

Activation and acceptance: merge reviewed green source, deploy normally, perform
its controlled code-only Check upgrade (new root helper modules included), and
preserve existing credentials, scopes, pinned SQL/units and original records.
The two additive Check SQLite tables appear on startup; PostgreSQL needs no
migration. Prepare/read back the native Jo stock branch while the flag is off,
then enable the flag in the existing private API environment and restart only
through the authorized service procedure. Never publish unreviewed runtime code
or weaken a source check to make a test pass.

After deployment, an explicit owner command
`stock_watch_owner.py delivery-diagnostic --symbol NBIS --code STK-...` creates
one labelled invented-data input for a selected ticker. The normal email relay
must wake the actual saved Jo task, which reads the frozen diagnostic, commits
its labelled assessment, and lets the app/ntfy deliver it. No typed replacement
submission counts as wake proof. Match input/review IDs and hashes through the
original native task history, isolated ledger, app notice, transport receipt and
owner's phone confirmation. Distinguish that full-flow diagnostic from a natural
market-session acceptance. Never relabel historical NBIS bars as live.

Implementation is under review; no new stock watcher, native task branch or
live phone acceptance is claimed here yet.

## Conditional price-plan follow-through

Selected by Isaac October 17, 2026 after the Jo weekly review. This bounded
personal-coach capability is separate from S1 selection, its immutable decisions,
option eligibility, and the independent shadow comparator. It is implemented by
[the conditional-plan monitor](../../backend/app/engine/conditional_plans.py), with
actor-bound Check receipts in
[`conditional_plan_ledger.py`](../../backend/conditional_plan_ledger.py).
The [Jo instructions and activation checklist](../../deploy/market-watch/jo-conditional-plans.md)
are prepared instructions, not evidence of an activated responsibility.

### Saved responsibility

Jo saves a numeric trigger, numeric invalidation, long/short direction, one to
three confirming completed one-minute closes, rationale, and explicit expiry.
A fresh own pre-trade check or previously served real stock alert anchors the
source ID, digest, price and cutoff. Only currently selected scanner tickers are
eligible. Readiness requires the app monitor's heartbeat within 90 seconds and
verified regular-session hours. Plans expire within four hours and no later
than that session's actual close, including early closes. No overnight plan or
unverified calendar fallback is accepted. Up to 24 new plans per actor/session
are accepted; reaching that bound refuses new saves explicitly and never drops
an already accepted plan's alerts.

The authenticated grant supplies ownership; the caller cannot supply an actor.
Pre-trade checks are subject-owned and stock inputs profile-owned; both must
match the verified identity. New records are append-only. Exact operation-key
retries recover the same plan/export even after expiry; changed content conflicts.
Changing a plan means cancelling it and saving a new, explicitly explained plan
from fresh evidence. No historical receipt or S1 rule is rewritten.

### Conditions and state

- Long: N consecutive completed minute closes strictly above the trigger;
  invalidation is one close strictly below the invalidation level. Short reverses
  both comparisons. Equality satisfies neither condition; a nonqualifying close
  resets the confirmation count. Invalidation is evaluated first.
- Only full minutes beginning at or after commitment may count. Expiry is
  exclusive. A forming candle, pre-commitment move, intrabar touch, natural-language
  pattern or later revised source cannot establish a trigger.
- `pending_activation` is a saved request, not monitoring proof. The app records
  `watching` only after accepting fresh source evidence. `triggered` continues
  monitoring for invalidation until expiry; it does not imply an entry or Go.
- `invalidated`, `expired`, `cancelled` and `unavailable` stop the plan. Missing
  minutes, a monitoring gap beyond three minutes, stale/unavailable source or an
  unknown session produces `unavailable`, never an invented price invalidation.
  Recovery requires a new plan; a failed plan does not resume silently.
- Cancellation is durable and acknowledged on the next monitor pass. Removing
  a ticker cancels its plans. A cancellation cannot recall a send already in
  flight. Disabling the running monitor cancels its loaded active plans; stopping
  the process leaves an explicitly stale heartbeat, not claimed active coverage.

### Monitoring and notification

The existing scanner pass checks accepted plans before discretionary stock-alert
work, reuses its minute cache and shared provider budget, and finishes observing
plans before phone delivery. No new scanner, email subscription, paid model call,
options call, paper exchange or broker action is introduced. Missing cached data
uses the same selected-symbol minute reader already used by stock awareness.
The explicit app flag requires stock awareness to be enabled.

Transitions and each evaluated bar are immutable records in the existing private
market-watch wake store. Derived atomic status publications let Jo read her own
conditions, timeline, last evaluated bar and delivery attempts using
`conditional_plan_status` or the bounded latest-50 `conditional_plan_list`.
These tools make no provider calls. The status never labels an unacknowledged
plan, stale heartbeat, terminal state or elapsed expiry as actively monitored.

Trigger, invalidation, monitoring failure and expiry notifications use the
existing ntfy transport directly; no additional Dot turn is needed for delivery.
Each message identifies the saved condition, observation time and plan. A queued
trigger superseded by invalidation/expiry/failure is suppressed. Three-minute
freshness, three bounded attempts and existing unknown-outcome handling apply:
an uncertain send is never blindly repeated. Accepted provider delivery is not
phone-display proof. No discretionary stock wake quota suppresses a plan event.
A global file lock prevents overlapping plan workers from duplicating sends.

### Activation and acceptance

Default off: app `CONDITIONAL_PLAN_ENABLED=false`; Check
`conditional_plan_enabled=false`. Enabling Check tools requires the existing
explicit market-watch publication/outbox paths; calls reuse `check:read` and
`market-watch:read`, with `market-watch:submit` additionally required for save
and cancel. No OAuth grant, identity, native task, production flag or service is
changed merely by merging this implementation. Deployment must include the three
new Check runtime modules. An opt-in change requires the normal authorized
service restart; disabled/rebound grants refuse old calls.

Before live acceptance, verify one actual Jo save against an observed fresh
source, an app acknowledgement, a natural future trigger or invalidation, matching
immutable evidence and one owner-confirmed phone notification. Verify cancellation
and restart without duplicate transitions/accepted pushes. Monitor failure and
unknown delivery stay visible. Fixture tests do not establish these live gates
or trading edge. Coordination: the selected-stock wake-cap/coverage owner keeps
its repair and passive acceptance; the pilot-study owner keeps rubric/factory
work. This slice adds no changes to those decision rules or experiments.
