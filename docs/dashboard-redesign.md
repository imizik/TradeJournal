# Dashboard command center

Approved direction: dense dark owner Dashboard, with today's journal state
first, compact realized performance and clear routes to deeper work. The
reference picture defines hierarchy, not records, prices or new permissions.

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
| Quick Actions | Reuse links | Charts, Trades, Analytics, Daily Review, existing Practice section and Sync drawer. No New Trade, Journal or Playbook route is invented | PR 1 |
| Daily Practice summary | Reuse, new summary | Existing decisions count; anchors to untouched `PracticeRoutine` and `PracticeDecisions`. `/daily` and `/daily/{day}?practice_run=` remain available | PR 1 |
| Full Practice / saved-decision reopening | Needs relocation later | Preserve `/`, `/?decision=`, `/?practice_run=` and all form/arm/reveal capabilities until replacement works. `practice-decisions`, `practice-routine`, `advisor-shadow` browser specs | PR 4 only |
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
