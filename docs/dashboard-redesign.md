# Dashboard command center

Current direction: a dense dark owner Dashboard that starts with saved market
context and investigation ideas, keeps Attention and data failures visible,
then shows active options and journal detail. Existing calculations, records
and permissions retain their meaning.

## October 21 walkthrough update — market-first presentation

The owner's first-open job is market orientation and opportunity investigation;
he manages positions in Robinhood and does not routinely journal before entry
or review after exit. The [workflow consolidation roadmap](workflow-consolidation-roadmap.md)
owns the proposed next order and acceptance. Its Dashboard slice reuses the
saved market/opportunity briefing, reserves one bounded Radar preview and keeps
specific option/data concerns visible, with account/performance/stock detail
secondary. No new market engine, position-management screen or mandatory review.

The original sequence below records prior design and delivery; its journal-first
opening hierarchy and pending relocation assumptions are not instructions to
rebuild already-delivered work. Daily Practice is already at `/practice`.
The owner subsequently approved continuing with the next Dashboard slice after
VWAP. The bounded presentation now uses the existing compact morning brief for
market context and up to three investigation ideas, with direct Charts links,
conditional/research-only labels and expandable trigger, invalidation and
source evidence. Legacy briefs retain their saved-priority meaning. Empty,
stale and missing briefs remain explicit; there is no new market summary.
The compact brief also exposes its exact cited context (source, fact/belief/estimate,
observation and retrieval times) and saved coverage gaps in disclosures. Unknown
citations stay unavailable; generic evidence is not reclassified as news or events.

A separate compact Radar preview reads the existing feed GET, caps the latest
saved events at three, labels session/coverage/snapshot time and supports manual
refresh. It never posts visits/feedback, starts detection or activates recording.
Off, no-data, stale and load-failure states stay visible. Opening the full Radar
screen retains its existing visit behavior.

Attention and import freshness sit beside the market area on desktop and before
journal detail on phones. Quote errors remain above both. Active options precede
a collapsed **Journal & performance** disclosure containing the journal summary,
today's session, stocks, exposure, performance and trade history. Account/type controls live with the
journal and explicitly do not rescope the saved briefing or Radar. Stock,
exposure, performance and recent-trade destinations remain available. No
accounting, authorization, scheduled-task or provider behavior changes. Fixture
verification cannot establish deployment, live discovery quality or owner use.

The inventory and original PR sequence below are historical delivery context;
the workflow roadmap owns the current consolidation sequence.

## Inventory and dependencies

| Design element | Classification | Existing source, meaning and proof | Delivery |
|---|---|---|---|
| SPY/QQQ/NVDA/MU market strip | Existing data, new UI | Charts workspace/stream has quotes and candles with provenance; `/quotes` alone has prices without quote times or change baseline. Reuse Charts transport rather than add four polls. `e2e/charts.spec.ts` | PR 3 |
| Today closed P&L | Existing data, ET calendar aggregation | Existing closed/expired `/trades` rows, excludes trims of still-open trades. Owner uses ET calendar slices rather than `/stats.today_pnl`'s server-local date. `dashboard.spec.ts`, seed smoke | PR 1 |
| This week P&L | Existing data, new aggregation | Filter existing closed trades by ET calendar dates, Monday through today; not the performance chart's rolling 1W. Missing realized values stay unavailable. Boundary tests | PR 1 |
| Unrealized / open count | Reuse | `/trades`, bulk fills and batched quotes; `lib/dashboard.ts` preserves direction, FIFO remaining quantity and option ×100 units. Partial marks cannot become total unrealized. `e2e/chart-journal.spec.ts`, seed smoke | PR 1 |
| Data freshness / Gmail | Reuse with new UI | `useGmailHealth` shares one poll with Nav/banner. `last_import_at` means successful import check, not newest fill or quote timestamp. Sync Center remains authoritative for jobs/errors. `test_gmail_realtime.py` | PR 1 |
| Account equity / return % | Unsupported | Neither cash, deposits nor a complete brokerage equity snapshot exists. Marked exposure is not equity | Omit until separate source contract |
| Today's session | Existing data, new UI | Opened/closed trade counts and closed P&L from filtered journal rows; not fills or gross trade size. Links to Trades and Daily Review | PR 1 |
| Rapid re-entry / unusual size / hold observations | Existing data, needs defined comparison | Analytics already has repeat-entry and hold breakdowns; needs verified account/unit/baseline semantics and sample size. AI flags are not deterministic facts | Later; descriptive only |
| Attention | New aggregation and UI | Expiration/status in Trade; marks may be missing; `/daily-review` supplies stale/unreviewed states. Earnings exist in Symbol Info, but matching provenance is required. Overnight, concentration and size need explicit denominators and ET session rules | PR 2 |
| Active options | Reuse with compact presentation | `DashboardTables`, `lib/dashboard.ts`, trade drill-down; no position status inferred from quotes | PR 1 |
| Collapsed stock holdings | Reuse, reorganize | Same position rows, separate from options; label stocks, never infer a long-term strategy from instrument type. Existing full detail remains available | PR 1 |
| Exposure details | Reuse, disclose | Gross/net marked value and largest quoted position; incomplete coverage and unknown direction stay explicit. Not max loss or equity | PR 1 |
| Cumulative realized curve / range | Reuse | `PerformanceOverview`: close-date cumulative P&L, ALL/1D/1W/1M/3M/YTD/1Y; excludes open trims. Dollar drawdown, never fabricated equity % | PR 1 compact layout; PR 4 refinements |
| Win rate / profit factor / expectancy / drawdown | Reuse | Same selected-period computations and sample size; zero/no losses/no trades retain current semantics. Seed smoke range assertions | PR 1 |
| Detailed statistical breakdowns | Already at destination | `AnalyticsExplorer`, `/stats/analytics`: date/account/instrument filters, groups and trade drill-down. Basic performance detail can stay in a disclosure until relocation preserves scope | PR 4 |
| Five recent closed trades | Reuse, corrected ordering | `/trades` orders by **entry**, so Dashboard must sort closed rows by close timestamp before slicing five. Full history `/trades` | PR 1 |
| Watchlist Movers | Existing data, new UI | Charts settings + workspace quotes; require supported % change and quote timestamps. Preserve shared watchlist settings | PR 3 |
| Today's Notes / New Note | New functionality | Trade/daily AI reviews and decision rationales are not a general notes journal; needs approved persistence/edit contract | Separate PR 3 slice |
| Upcoming | Existing data plus new UI | Expirations and chart earnings/events can be reused; no general scheduled-task calendar, fabricated reminders or nonworking controls | PR 3 |
| Quick Actions | Removed (October 2026) | The four links repeated the sidebar; the scoped Trades and Analytics links remain on their cards. No New Trade, Journal or Playbook route is invented | PR 1 |
| Daily Practice summary | Removed from Dashboard | Daily Practice is available in the sidebar and phone More menu at `/practice` | Relocated October 21, 2026 |
| Full Practice / saved-decision reopening | Relocated to `/practice` | Existing components and saved records retained; owner `/?decision=` and `/?practice_run=` links forward with their references. Daily Review and assistant surfaces remain available. `practice-decisions`, `practice-routine`, `advisor-shadow` browser specs | Relocated October 21, 2026 |
| Assistant variants | Preserve | Early authorization branches in `app/page.tsx`; journal-reader retains legacy rendering, writer/market-only retains assigned practice. Owner component never mounted for an assistant. Browser auth/sample suites, `test_browser_access.py` | Every PR |

## Integrity prerequisite

Code evidence: `reconstructor.py` expires remaining options only when expiration
is before reconstruction's date, with a synthetic 16:00 ET close. Persisted
status does not update just because midnight passed; it requires reconstruction.
An Oct 9 observation on Oct 9 is consistent with this rule. A later open row
would be a record discrepancy, not proof of an executable option position.

Current NBIS/DRAM status is **unverified**: this worktree has no real records,
the local app is not running, and the main checkout's local SQLite is an old
empty database, not the VPS journal. No rebuild, sync, repair or production
query has run. A separate seeded numeric check did confirm a preexisting defect:
Dashboard and Daily Review used the all-entry average after partial FIFO exits.
RNXT's remaining 450 shares at $0.80 were valued against $0.85, yielding $157.50
instead of $180 with a $1.20 mark. The prerequisite FIFO display PR replays the
already-fetched fills, preserves option units/short direction, and leaves absent
basis unavailable. No stored records change. PR 1 depends on that correction;
it retains stored statuses and disclosed quote coverage. PR 2 must distinguish
expired-but-recorded-open from actual exposure, retain the row, show expiration
and observation times, and link to its fills. A confirmed defect needs its own
minimal tested fix before any production-data decision.

## Architecture and PR sequence

PR 1 adds an owner-only `OwnerDashboard` composed from the existing data passed
by the root server route. Shared position helpers, tables, performance metrics,
sync and Practice implementations remain the owners of their behavior. Account
and type filters stay in the URL, with focused decision/run parameters retained.
No new production API, migration, MCP schema, grants, worker or model/provider
job. The existing disposable browser harness supplies deterministic quotes;
its test-only application refuses any database other than the seeded e2e file.

PR 2 follows PR 1: a deterministic Attention projection with explicit priority,
source times, unavailable inputs and record actions for expired-open, upcoming
expiration, earnings before expiration, overnight, missing marks, concentration
and unfinished reviews. No trading prescriptions or historical-correlation rules.

| Rule | Source and condition to verify | Priority and action | Missing-data behavior |
|---|---|---|---|
| Expired, recorded open | Trade status + expiration before ET date; retain the record, do not synthesize a market position | Integrity first; open trade/fills | Unknown expiration is an integrity input gap, not an inferred expiry |
| Missing quote / basis | Batched position quotes + FIFO fill evidence, independently | Integrity first; trade detail / data status | Show unavailable, never zero; quote times require a provenance extension before freshness-based rules |
| Upcoming expiration | Recorded open option + authoritative ET session calendar; today or next session | Time-sensitive; exact contract / Charts | Disclose unavailable calendar/date; do not assume weekends or holiday sessions |
| Earnings before expiry | `/charts/symbol/{symbol}/events` and its supplied source/fetch times, compared with contract expiry | Time-sensitive; event and contract | Stale/unavailable source suppresses the claim; same-day unknown timing is uncertain, not definitely before expiry |
| Overnight holdings | Remaining FIFO lots spanning ET sessions, not original entry date after all old lots exited | Context; position/fills | Missing lot/session history remains unavailable; carrying overnight is an observation |
| Concentration | Complete marked-position coverage; share of gross marked exposure, never equity | Context; exposure detail | No account-equity % or alarm threshold is invented; incomplete coverage cannot support concentration |
| Unfinished reviews | `/daily-review` saved/stale states and completed trading dates | Follow-up; `/daily/{day}` | Missing review state differs from not reviewed; no paid review job starts automatically |

**Owner selection (2026-10-11), as built.** Kept: expired-but-recorded-open,
missing quote/basis, upcoming expiration, earnings before expiry. Dropped by the
owner as already known: overnight holdings, concentration, unfinished reviews.
Added: Gmail import down/degraded, failed sync job, price alert fired within 24
hours, and the owner's open WAIT choices (human, non-sample, expiry ahead). WAIT
conditions are free text that nothing evaluates, so the panel lists an open WAIT
with its condition and end time; it never claims a condition was met. A later human TAKE/SKIP/WAIT on the same
opportunity supersedes it. Position checks follow the Dashboard's account/type
filters and say so; import, sync, alert and WAIT items are never filtered. No
authoritative next-session calendar is available to the Dashboard, so upcoming
expiration means within three calendar days, with the date shown. A failed
quote request is disclosed once above the panel instead of once per position.

Each item must carry its input observation time, calculation time, stable record
IDs, scope and a working action. Integrity comes before imminent events, then
descriptive context and review follow-up; sort deterministically within each
priority. Pure fixture tests must prove scope, ties, incomplete sources and
non-trigger states before a rule becomes visible.

PR 3 follows the foundation, independently of Attention where practical: shared
market strip/watchlist first, then notes persistence and Upcoming as separate
reviewable slices if their contracts require it. No static mock data.

PR 4 follows working destinations: remaining analytics/practice relocation,
preserved filter/back/deep-link behavior and responsive refinements. Until then,
full Practice remains below the command center, accessible by its summary link.

Concurrent Dots advisor work touches authorization/receipts/AdvisorShadowPanel;
PR 1 avoids those paths and keeps the Practice mounts unchanged. Integration
requires normal current-base reconciliation and the existing Dots regressions.

## PR 1 picture-checkable acceptance criteria

1. At 1440×1100 the header, account/type filters and closed/unrealized/open
   summary precede the session, position and compact performance sections.
   Existing dark tokens, thin borders and tabular figures; no decorative tiles.
2. Active options are expanded; stock holdings are a separate collapsed section
   with count and quote coverage visible. Expand to reach every stock row and
   its original details. All open records remain reachable, including expiry.
3. Cumulative realized performance and four core metrics share one desktop
   panel, with range controls and selected sample size. Existing remaining
   metrics remain reachable in a disclosure. Analytics has a working link.
4. Five most recently **closed** rows appear, including expiry closes, with a
   full-history link carrying the same account/type filters.
5. At 390×844 the primary cards stack, filters wrap, controls are reachable,
   and document width does not exceed the viewport. Tables scroll internally;
   missing prices remain em dashes, not zero. Phone navigation stays clear.
6. Empty journal and unavailable quote/import states say what is missing.
   Fetch failure shows an actionable error, loading state has named skeletons.
   No equity or unsupported market, notes, Attention or calendar data is shown.
7. Sync drawer works, filters survive navigation, old decisions reopen with
   evidence intact, assigned Practice runs still load, and assistant variants
   cannot render the new owner component or request new owner data.

## Verification

Use the existing disposable browser backend with disabled providers/integrations.
Capture base and branch with the same seed and viewports; save every new visual
state in the Dashboard browser spec. Numeric/calendar/sorting edge cases are
deterministic. Run the UI gate, full verification and native reviews (financial
aggregation plus sensitive root route warrants tier 2). Local assistant tests
are regression evidence, not Jo's cloud acceptance. Screenshots and final
review/checkpoint links will be recorded in the PR.

## Market-first saved-context follow-up

The current owner opening flow is the saved morning brief and bounded Radar
preview before journal/performance details (see the
[workflow roadmap](workflow-consolidation-roadmap.md#release-1-market-first-dashboard)).
Compact briefing ideas expand to full text, conditions/counterpoints and exact
cited evidence with kind/source/timestamps; missing citations stay explicit.
Earlier-format briefs keep their priorities and disclose the missing separate
new-opportunities section.

Radar preview shows existing saved news state and nearby headlines, with the
full move and all saved headlines in a disclosure. Preserve source, before/after
timing and news-check time, and distinguish nearby news from confirmed causes.
No fresh news fetch, generation, task activation, visit/feedback mutation or
accounting change occurs. Existing charts and full Radar/briefing remain the
investigation destinations. Dashboard and morning-briefing browser fixtures
cover desktop/390px, news found/none/unavailable/unchecked, stale reads and
legacy/redacted briefing states. Fixture proof is not live usefulness.
