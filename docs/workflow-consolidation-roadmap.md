# Workflow consolidation roadmap

Planning date: October 21, 2026. Requested after an owner walkthrough of the
current app and review of Claude's critique. **Planning only:** this document
authorizes no implementation, production writes, new grants, activation,
provider subscription, model calls, deployment or merge for future releases.
Each next slice needs Isaac's approval. Existing separately authorized work
retains its scope. Isaac explicitly approved publishing the completed VWAP fix
with this roadmap and automatically repairing/merging that bounded PR after
passing checks; that approval does not implement the roadmap's future slices.

The desired routine is:

**Understand the market → investigate charts → trade/manage in Robinhood →
return when TradeJournal has useful information.**

Measure success by less hunting, clearer evidence and voluntary use. A smaller
feature count, more alerts, more trades or a profitable example is not proof of
success. Existing features remain available unless a later decision explicitly
changes them.

## What the walkthrough established

These are owner-reported preferences and behaviors, not inferred analytics:

- At first open, he wants market direction, news, opportunities and important
  levels. Lifetime P&L and stock-holdings commentary do not answer that need.
  Open-option concerns can be relevant.
- He starts with a macro chart layout, then scans familiar tech/AI names.
  TradingView is his reference workspace. TradeJournal stock scanning felt a
  little slower but usable; speed is not currently the main blocker.
- VWAP is important. Its bands were difficult to find and confused with
  option-implied expected-move levels.
- For a recovery idea, he notices a strong rebound candle after a sharp drop,
  checks whether chip/AI peers are rebounding together and applies his macro
  understanding. A day-change watchlist alone cannot show that confirmation.
- He takes relief scalps, intraday recovery ideas and one-to-two-week swings.
  Intended duration sometimes changes after entry. A mandatory pre-entry plan
  form does not fit his normal behavior.
- He watches charts and the option price in Robinhood on his phone. Chart-based
  position management/review is unfamiliar, not proven unwanted or broken.
- He sometimes adds to losing options, panics at large exposure, or extends a
  short trade until it expires worthless. He expects he would dismiss a generic
  warning but thinks peer/market deterioration and exposure could matter.
- He mostly moves on after closing. Daily reflection is not an established
  habit. Review should remain available without becoming an obligation.
- Retail attention/narratives interest him. Institutional sentiment, a useful
  source and a valid measurement have not been defined.

The preferred recovery setup being his "best play" and the belief that most
positions recover if held remain hypotheses. Do not encode them as profitable
rules, justify averaging down with them, or derive a probability of profit.

## Assessment of Claude's critique

| Point | Verdict and consequence |
|---|---|
| Put dashboard simplification before/alongside VWAP | Agree with the product priority. Avoiding agent collisions was not a user benefit. VWAP is already implemented locally, so close that bounded slice and make the dashboard the next proposed consolidation implementation; do not reopen the order just to abandon finished work. |
| Make peer co-movement a main Charts benefit from Radar | Agree. Give it its own acceptance gate below. Curated groups are in Radar's scope, but metadata and an event kind are not a functioning detector. |
| Check VWAP meanings before declaring the change bounded | Agree; the check is complete for the affected paths. Chart VWAP/bands have explicit numerical tests. Other paths use different sources, aggregation and cutoffs. No demonstrated calculation defect justifies a broad VWAP refactor. TradingView parity remains unverified. |
| Park macro until a checklist exists | Agree. Draft the checklist now; validate instruments and data before choosing a grid or claiming support. |
| Check position follow-through against existing alerts | Agree. Reuse give-back/expiry and explicit price watches. Peer/macro thesis deterioration and increasing exposure are genuine gaps, but usefulness and timely position data are unproven. |

## Baseline and evidence boundaries

Initial review: main `99db02f3` and local VWAP `fcb729ea`.
Current implementation reconciliation (October 22): main `b310155b` includes
VWAP #396/#401, market-first Dashboard #397/#401/#406, Macro/Tech #399,
peer comparison #400 plus Session context #408, read-only holding context #403,
chart-latency instrumentation #405, Radar Movers #407 and its Charts handoff #409. These are merged code,
not evidence of production deployment or live usefulness. Recovery-from-low peer context
below is the newly selected slice in this PR; exact-head CI/merge
receipts own its delivery status.
GitHub metadata checked October 21: morning-opportunities PR
[#388](https://github.com/imizik/TradeJournal/pull/388) is merged. No live deployment audit was performed. The later Macro feasibility probes
verified the configured Tradier index entitlement; see Release 3.
The walkthrough screenshots establish the owner's experience at those moments,
not the health of every current service.

| Capability | Evidence and current boundary |
|---|---|
| Owner dashboard | `frontend/components/dashboard/OwnerDashboard.tsx` already has Jo status, compact briefing, journal summary, session/Attention, active options, collapsed stocks, exposure and performance. Reuse those sections; a new dashboard engine is unnecessary. |
| Opportunity-first briefing | #388 adds bounded news-led outside candidates and separates setups from position concerns. Merged code is not proof the Check catalog/task was upgraded or a natural morning delivered useful content. Preserve legacy briefs. |
| Radar | [Radar contract](radar.md): recorder, durable store, feed/detail/feedback, saved news and plain Movers ranking (#407) are built. This roadmap does not establish activation or live coverage. Provisional detection rules `radar-rules-v0` (screen only, set on two sessions) write events; Movers is not an alert feed. |
| Groups and chart handoff | Curated groups, Movers group summaries and read-only 15-minute/Session comparison APIs are built (#400/#407/#408). The group/origin/return handoff is merged (#409). This PR adds sampled-low context. Historical event-time replay and calibrated detection remain unbuilt. |
| VWAP | `backend/app/engine/chart_math.py` computes RTH minute-HLC3 VWAP and volume-weighted dispersion. `backend/tests/test_charts.py` pins weighting, resets, extended-hour exclusion and interval carry-through. Merged #396 separates controls; formulas are unchanged. |
| Other VWAP contexts | `metric_reference.py` uses fill-cutoff minute history; `scanner_rules.py` uses completed scanner bars; `packets.py` can use provider VWAP. Source, session, bar size and cutoff must match before declaring a discrepancy a defect. |
| Charts | [Workspace](charts-workspace.md) and [roadmap](charts-roadmap.md): five panels, saved arrangements, levels, news, peers, captures and trade review. Merged #399 raises distinct symbols from three to five and adds explicit VIX/TNX yield routing. Crypto and futures chart support remain unverified. |
| Existing position alerts | `backend/app/engine/position_alerts.py`: give-back after an armed gain and last-day expiry reminders. Give-back requires a fresh, sufficiently tight Tradier midpoint; calendar-timed expiry reminders can report missing/thin quotes. Dedupe and restart state exist. Does not monitor every losing position or a sector thesis. |
| Conditional watches | [Scanner contract](agent/setup-scanner-contract.md): explicitly saved numeric triggers/invalidation on eligible selected symbols, with expiry and visible refusal. A promise by Jo is not a saved watch. |
| Position freshness | Journal positions derive from imported Robinhood execution emails and reconstructed fills, not a live broker holdings feed. Fresh market quotes cannot establish that position quantities are current. |
| Optional learning | Day thoughts, Jo's day, trade links, daily/weekly reviews, Practice, Research Studio and Shadow already have their own records/contracts. Preserve them; do not create a competing plan store or change frozen studies. |

## Ownership and working order

This roadmap owns cross-screen workflow and acceptance. Existing domain
contracts own calculations, data, permissions and experiments. Radar's owner
keeps detector, universe, recording and event-lifecycle ownership. This chat
owns consolidation. Use Luna for bounded code exploration as Isaac requested;
the lead implements approved work and retains completion responsibility.
Independent review follows [review policy](agent/pr-review.md), by actual risk.

One implementation slice per owner at a time. Separate worktrees/branches;
read the other owner's current contract before touching shared files. New
user-facing chats are only needed for approved, independently owned work.

The minimal Radar/dashboard agreement is: **Radar owns saved discoveries;
Dashboard displays a bounded read-only preview with source, time and coverage;
Charts consumes explicit event/group context.** No second detector or news
collector, and no implicit activation.

| Order | Release | Owner / dependency | Rough effort |
|---|---|---|---|
| 0 | VWAP clarity | Merged #396/#401, ±1σ display only; live parity remains unverified | Implemented |
| 1 | Market-first Dashboard | Merged #397/#401/#406; saved evidence/news drilldowns included; morning-use acceptance remains open | Implemented |
| 2 | Peer confirmation in Charts | Merged #400/#408: 15-minute and recorded-session comparison; live coverage/usefulness separate | Implemented |
| 2a | Movers → Charts handoff | Merged #409: group selection, dated origin, fresh Session comparison and return to the selected Radar session/group list | Implemented; production acceptance separate |
| 2b | Recovery-from-low peer context | Merged #412: selected-stock sampled-low anchor, shared peer/benchmark window and low-search coverage | Implemented; live usefulness separate |
| Parallel planning | Macro checklist and data feasibility | Five instruments selected; Tradier probes passed; no provider purchase | Complete for the selected slice |
| 3 | Agreed macro layout | Merged #399: SPY/QQQ/IWM/VIX/US10Y and Tech return; production acceptance separate | Implemented |
| 4 | Read-only holding context | Merged #403: recorded option exposure, expiration and linked plans; same-session since-entry comparison merged #417; new alerts deferred | Implemented; usefulness open |
| 5 | Navigation and optional review continuity | Consolidation; actual remaining friction after releases 1–3 | 1–3 days if justified |
| Later experiment | Narrative/attention sources | Radar; identify incremental value and source access first | Time-box assessment to 1–2 days; build not selected |

Estimates include focused tests and review, exclude live observation/approval
waits and are not delivery promises. Target existing subscriptions and no new
automated inference. Measure provider/storage costs before expanded collection.

## Release 0: finish VWAP clarity

Local implementation fcb729ea provides independent VWAP ±1σ/±2σ control in
Indicators/Layers, renames option-based Range bands to Expected move, preserves
saved choices and explains RTH/daily/extended-hour availability. It adds no
anchor, indicator formula, provider call or study preset.

Six focused browser tests, 158 backend/docs tests, typecheck and focused lint
passed; desktop/390px screenshots were inspected. Isaac subsequently approved publishing the VWAP fix and this roadmap in one
PR, with automatic repair and merge after passing checks. The PR's final-head
check results and merge receipt own completion evidence; do not infer deployment
or live TradingView parity from local tests. Do not reopen formula work unless
a reproducible comparison reveals a defect.

Acceptance after approval: passing final-head CI; no expected-move coupling;
legacy/older-tab settings survive; chart menu and per-panel interactions work.
An optional same-symbol/time/source/session TradingView comparison tests parity;
it is not a prerequisite to the control fix or a claim of established parity.

**October 22 follow-up:** the owner selected only the ±1σ upper/lower pair;
the outer ±2σ display is removed without changing VWAP/dispersion calculations
or saved show/hide settings.

## Release 1: market-first Dashboard

**Merged in #397:** after the VWAP/roadmap PR merged, Isaac
selected this next bounded presentation slice. Reuse the saved briefing and
GET-only Radar feed; keep Attention/data failures visible and calculations,
auth, recording activation and providers unchanged. The PR's final-head checks
own implementation proof. Live usefulness and production rollout remain
separate acceptance; this does not authorize releases 2–5.

**October 22 follow-up:** the owner approved one presentation PR with the
single-band VWAP change. Keep Active Options visible; make journal/performance
detail expandable. Make the compact brief's exact cited context and coverage
gaps readable in place, with saved source/timestamps and missing evidence explicit.
No new live market/news feed or brief-generation change is part of this slice.

**Opening-screen evidence follow-up:** compact opportunities and legacy priorities
expand to their full saved text, conditions and exact cited evidence with source,
kind, observation/retrieval times and explicit missing citations. Earlier-format
briefs name the missing separate discovery section. Radar previews reuse their
saved news records, before/after timing and check time, with a full-text
disclosure; nearby headlines are not confirmed causes. This adds no fetch,
provider, task change, recording activation or notification. Live Jo task-format
alignment and real-morning usefulness remain separate work.

Outcome: opening the app answers "What matters and what should I inspect?"

Proposed content order:

1. Compact operational/Jo availability status, with serious import/data failures
   visible. Do not bury an integrity problem to make the page cleaner.
2. Saved market backdrop: direction proxies, dated news/calendar, source ages
   and explicit gaps. The saved morning brief is a morning assessment, not a
   live market regime. Do not fabricate a new live summary while reordering UI.
3. One **Things worth investigating** section. Initially show the existing
   saved briefing's setups/opportunities. When Radar produces valid events,
   add a bounded preview from its existing feed, with Open Radar/Open chart.
4. Specific option concerns from existing Attention/position records.
5. Optional account/performance/stock-holdings detail, still reachable in the
   existing dashboard or scoped Trades/Analytics destinations.

Use the existing compact briefing as the primary market/opportunity surface;
avoid showing the same setups twice in a new card and the old brief. If its
components need separating, extract presentation only. Limit previews to a few
items, preserve stable source identities, and link to the original record.

Filters: clearly label account-scoped journal/option sections. General market
and Radar coverage must not silently change with the selected account. Preserve
account/type query parameters on journal drilldowns and the existing assistant
branches/access boundaries. No new fetching for assistants.

Likely scope: `OwnerDashboard.tsx`, existing `MorningBriefing` presentation,
existing dashboard API helpers only if needed, and `dashboard.spec.ts` plus
morning-briefing tests. Keep accounting/aggregation unchanged. If quote-time or
baseline gaps prevent a live market strip, defer that strip to a source-aware
slice rather than adding another poll.

Acceptance:

- At desktop and 390px, the first substantive content is market context and
  investigation opportunities, before lifetime performance and stock detail.
- In roughly one minute Isaac can describe available context, identify one
  investigation destination, and distinguish stale/missing sources.
- Off/recording/stale/no-event Radar has an honest compact state; no fixture
  events appear as real discoveries. Dashboard has no reason to mark the full
  Radar feed visited or change "new since last visit" semantics.
- Expiry/import/quote warnings, filters, existing stock/performance access and
  assistant separation survive. Empty legacy briefs are usable.
- Works with Radar off and Jo unavailable. No scheduled task changes, new
  detector, activation, model calls or new account-equity meaning.

## Release 2: peer confirmation in Charts

**October 22 implementation approved:** the first slice is an observational
15-minute Group movement view in the existing Peers disclosure, backed by
Radar's shared stored passes. It does not require a calibrated event detector.
The [Radar contract](radar.md#charts-group-movement) defines the implemented
eligibility and coverage rules. Recording activation and live owner acceptance
remain separate. The owner subsequently selected **Session context**: a toggle
beside 15 min shows returns and participation since the first usable recorded
sample, with actual start/end, missing-minute coverage and independently
unavailable states. It reuses the same stored observations and refresh; late
recording cannot be labeled a market-open return. Historical event-context
handoff and sustained-trend detection remain follow-ups; sampled-low context is selected below.

**Merged #409: Movers → Charts handoff.** Movers group links carry the chosen
group, originating stock, recorded session and pass time into Charts. Charts
opens Overview/Peers on Session, validates membership through the existing API,
and labels the origin separately from the newly read comparison. It does not
replay that timestamp, restore event-time peer values or change candle ranges.
Return navigation restores the selected Radar date, expanded group list and
group location. Plain leader/laggard links carry origin without inventing group
membership. Invalid origin parameters are ignored; an unavailable group is not
silently replaced. This slice adds no detector, provider or activation.

**Next selected: recovery-from-low peer context.** Add **From low** beside
15 min/Session in the existing Group movement panel. Use the selected stock's
lowest eligible recorded `last` as one shared anchor for peers and QQQ/SPY;
never compare different per-stock low times as if they were simultaneous.
Show sampled price/time, search coverage (including gaps before the low),
common window and missing rows. An ineligible latest selected-stock price
prevents the comparison; a newest low waits for a one-minute rebound window.
A return to an earlier equal low explicitly says no net rebound. Changing stocks
recalculates the anchor. No new provider, alert, collector or AI call; existing
Radar samples and visible-panel refresh only. Desktop/phone interaction and
backend anchor, gaps, stale, version, missing-price and no-rebound cases are the
acceptance checks. Production coverage and daily usefulness remain unverified;
sustained-trend detection is still deferred.

Primary question: **"Are these names rebounding or weakening together over the
same interval as the stock I am investigating?"** This is the first major
Charts benefit from Radar, ahead of feed decoration or another summary screen.

Scope: a compact read-only peer/group context in the existing symbol-info area
or another established chart disclosure. Show the selected group and membership
source/version; individual member changes over one shared intraday window;
SPY/QQQ or a relevant sector benchmark over that same window; fresh/eligible/
configured counts; observation times; and missing coverage. Allow selecting a
relevant curated group rather than assuming every stock has one correct sector.

Use Radar's recorded observations/derived events. Its current quotes are sampled
last trades, not OHLC candles: do not describe quote-sampled returns as minute
bar confirmations. The Radar owner defines window synchronization, warm-up,
missing/stale exclusions and the derived read model. A calibrated group event
and an observational comparison are different outputs; label which is shown.

The existing Radar comparison API supplies this view. Extend that read model
for any approved future windows, not a Charts-owned background polling universe. No co-movement claim while the
source is off, insufficient, stale or sample-only. No probability-of-profit
score. A stock chart opening must not trigger broad RVol history prefetch.

**Deferred historical event handoff:** preserve event ID, symbol/group, observation window and as-of
context when opening Charts; display detection then versus current values
explicitly. Reuse existing symbol/from/to chart navigation and add event/group
context only as needed; never fabricate a trade or fill ID. Existing chart deep
links remain.

Likely integration: `RadarFeedView.tsx`, `frontend/lib/radar.ts`, Radar router/
read model, `ChartWorkspace.tsx`, existing SymbolInfo components, and their
focused tests. Provider cadence/storage stays owned by Radar.

Acceptance: a seeded recovery and failed recovery show correct same-window
member/benchmark comparisons; partial/stale/ungrouped states are explicit;
opening an old event does not silently substitute today's context; back
navigation preserves the origin; no extra universe collector; Isaac can answer
the peer-confirmation question without cycling through several charts.

## Release 3: macro workspace, after the checklist

**October 21 scope approved:** implement VIX and US10Y (Tradier TNX:CGI ÷ 10),
with the existing five slots showing SPY/QQQ/IWM/VIX/US10Y at 4h and a local
Tech return. Exact units, hours, paging and costs are in the
[Charts contract](charts-workspace.md#macro-layout-vix-and-10-year-yield).
Merged in #399. Identifier and read-only entitlement probes passed; production deployment and
owner use remain unverified. The draft below records the broader wish list;
Bitcoin and oil are deferred, not part of this implementation.

Historical wish list from the screenshot, before the selected slice was settled:

| Item | Question | Current boundary |
|---|---|---|
| SPY and QQQ | Direction, structure, major moving averages and nearby lows/highs | Existing equity/ETF charts; selected default is 4h |
| IWM | Is participation broader than large tech? | Existing ETF path; included in the five-symbol Macro preset |
| VIX | Is volatility rising/falling? | Merged #399 adds explicit Tradier index 4h/1D history; finite intraday retention |
| US10Y | What is the 10-year Treasury yield doing? | Merged #399 uses TNX:CGI ÷ 10; yield percent, observed timestamps, 4h/1D |
| Bitcoin | What is crypto doing alongside equities? | Explicit crypto chart data path unverified |
| Oil exposure | What is oil doing? | Choose actual oil futures/spot versus a named fund such as USO; do not substitute silently |

Isaac selected SPY, QQQ, IWM, VIX and US10Y at 4h, with a quick Tech return. Eight
panels in a screenshot are not automatically the right specification. Do not
add gold/dollar/futures feeds simply to make it look comprehensive.

Feasibility gate: per-instrument identifier/type, price or yield units, source,
permissions, real-time/delay, history, session/calendar, precision, limits/cost
and whether volume-based studies are meaningful. Bond ETF price is not yield;
USO is not oil futures; SPY is not SPX. New costs/access require approval.

Merged #399 retains five slots and raises the distinct-symbol cap to five,
with compatibility, request-budget and interaction coverage. Existing named
layouts and stock study choices are preserved. No giant chart rewrite.

Acceptance: open the agreed Macro layout, inspect its supported instruments and
levels, switch to Tech and back with settings intact; unsupported instruments
are named honestly; common-window navigation and dense labels remain readable;
latency and data load are measured against baseline. Scope tests to actual
approved instruments and viewports.

## Release 4: position context, only if useful

**October 23 approved follow-up:** enrich existing holding alerts with frozen
same-session since-entry peer/QQQ/SPY observations, using the same comparison as
Charts. No new triggers or activation. Missing/stale/overnight context leaves the
original alert intact. Snapshot persistence requires an additive migration and
the consequential review path. Implementation/PR checks, deployment and actual
phone usefulness remain separate; see [the context contract](radar.md#since-entry-context-on-existing-holding-alerts).

Merged #403 implements the owner-approved read-only Charts slice: Overview → Holding
context reuses recorded option positions and the selected chart trade card,
with remaining entry premium, expiration, linked plans and a jump to existing
peer movement. Import completeness, live value and intent remain explicit gaps.
Desktop/phone fixture acceptance does not prove live usefulness. New alerts,
structured intent writes remain deferred. The approved same-session since-entry slice is implemented; deployment and live usefulness remain unverified. See
[the holding contract](charts-workspace.md#holding-context-read-only).

Reuse before adding anything:

- Existing give-back and expiry alerts keep their definitions, transport,
  dedupe, restart state and separate activation/phone-acceptance gates.
- Existing saved price watches monitor only the terms actually saved. Keep
  unsupported symbols/conditions and refused requests visible.
- Robinhood remains the position/execution interface. No new broker execution,
  order controls, forced cooling-off period or second portfolio screen.

Test one voluntarily chosen historical or paper example: original rebound
reason, stock/peer/market deterioration and exposure at a stated time. Identify
whether existing charts/Radar and existing alerts already answer it. Do not
build a generic warning Isaac has said he would dismiss.

If a further slice is justified, separate adverse movement within an intact
thesis from evidence the thesis changed. Show original/added premium committed,
current estimated position value, import and mark times, quote quality and
expiration where reliable. Gross marked exposure is not account equity or a
guaranteed realizable loss; separate realized losses from remaining exposure.
Unknown intent stays unknown. Optional scalp/intraday/swing capture may be tested
after entry, but new input and intent-change notifications are not selected.

Acceptance before any automated position-context alert: timely fills/quantity
proof independently of quote freshness, explicit owner-endorsed conditions,
nonduplicate overlap mapping, correct partial exit/addition/restart behavior,
phone observation and an owner example where the evidence could affect a
decision. Otherwise keep this as chart context and defer alerts. No validated
probability model exists; do not display a made-up chance of profit.

## Release 5 and later: simplify navigation and test optional learning

Selected slice: labeled Peers and Holding context shortcuts in Charts reveal
the existing dock/phone sheet and Overview section, including collapsed sections.
Holding selection stays explicit; navigation within mounted Overview preserves
the chosen contract and comparison group/mode. No new screen, calculations or
alerts. The original routes remain available; deployment/usefulness are separate.

Use the existing destinations: Today for orientation, Radar for discovery,
Charts for investigation, Review for later questions, and current Trades/
Analytics for records/performance. This is a role map, not approval to rename
routes, add four new landing pages or move every sidebar link.

Inspect current navigation first: Labs grouping and the Daily Practice move
already exist. Improve only friction left after the preceding releases. Keep
operational reliability detail reachable without making it a daily task.
A combined "what is monitoring?" view is conditional on confusion remaining
after better links/status; reuse the watches screen rather than create a new
inbox or consolidate distinct detector engines.

Learning remains optional: retain thoughts, captures, trade links, Jo timeline,
daily/weekly reviews and legacy deep links. A question such as "Does this setup
actually work for me?" can use existing review/research. Compare all eligible
cases with source coverage and explicit definitions; don't ask Isaac to adopt
a daily writing routine or claim saved plans equal adherence.

Retail/institutional narrative assessment is later: define attention versus
opinion versus positioning; assess a bounded existing source sample and its
coverage, timestamp, manipulation and access limits. Institutional activity
cannot be inferred from Reddit or news sentiment. Require incremental value
beyond existing news, no composite score, scraping service, paid vendor or
LLM sentiment pipeline before approval/evidence.

Advanced Radar/Research Studio/Jo/Shadow work stays with its own roadmap and
protocol. Do not feed human-selected Radar observations into frozen Shadow or
prospective MU inputs, enable autonomous decisions, or generate endless
strategy variants under the label of consolidation.

## Verification, release and stop rules

- Review-only roadmap now; request approval for one concrete implementation
  slice. Do not treat this document or a quoted critique as approval to deploy.
- Preserve data meanings, auth/grants, studies, saved history and independent
  experiment boundaries. Risk tier follows actual behavior, not file count.
- Use existing disposable fixture/browser harnesses, matching before/after
  desktop and 390px states. Test actual changed navigation/interactions and
  empty/stale/error states; no production settings mutations for screenshots.
- Backend/UI fixture proof, current-head CI, deployed/loaded flags, provider
  entitlements, actual phone receipt and owner usefulness are separate evidence.
- After dashboard and Charts slices, repeat the owner's real opening routine.
  Record what he finds, needs to hunt for, skips or opens elsewhere. Don't turn
  feedback collection itself into a daily chore.
- For Radar, retain unnotified events and coverage; compare novelty/timeliness
  with the saved morning brief and a simple movers baseline. Count unreviewed
  separately from irrelevant. More trades or a few profitable events are not
  acceptance criteria.
- Stop expanding a surface when it does not change the owner's use. Preserve
  working capability; remove redundant presentation only with a demonstrated
  replacement. Prefer fixing a specific failure to another dashboard or agent.
