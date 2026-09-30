# C0.0 Deep history: implementation contract

Status: **implemented in [PR #89](https://github.com/imizik/TradeJournal/pull/89)**.
Priority and completion live in the [roadmap](charts-roadmap.md#status-board).
This document records C0.0's implementation contract; it does not authorize
other roadmap items.

## Outcome and scope

A stock/ETF intraday chart can scroll six months back without losing its view,
while today's Tradier data continues updating. Completed minute sessions are
fetched from Alpaca SIP once and retained on disk across API restarts/deploys.
All existing chart interactions remain available on desktop and at 390px.

Keep the single Tradier WebSocket, 15-second REST reconciliation, in-place
latest-bar updates, source labels, fill markers, countdown states, linked
ranges and full screen. Do not implement C0.1's calendar, C0.2's general state
refactor, drawings, alerts, replay, server-saved layouts or journal enrichment.
Daily/weekly depth and price adjustments are C0.6/C0.7; their present behavior
stays intact and is disclosed. SPX is an index, outside this stock/ETF contract.

## Ownership and starting points

Read `AGENTS.md`, `CLAUDE.md`, this contract, the roadmap and workspace document.
Read the relevant agent verification/environment docs before running anything.

| Responsibility | Existing owner |
|---|---|
| Shared provider reads, pacing and workspace assembly | `backend/app/engine/chart_feed.py` |
| Pure normalization, sessions, resampling and studies | `backend/app/engine/chart_math.py` |
| Private routes and journal markers | `backend/app/routers/charts.py` |
| Single upstream connection | `backend/app/engine/chart_stream.py` — preserve |
| Types, requests, live overlay and bar-change detection | `frontend/lib/charts.ts` |
| Refresh lifecycle and panel data | `frontend/components/charts/ChartWorkspace.tsx` |
| Series updates, viewport and range-link events | `frontend/components/charts/PriceChart.tsx` |
| Fixture coverage | `backend/tests/test_charts.py`, `backend/tests/test_chart_stream.py`, `frontend/e2e/charts.spec.ts` |

A small chart-owned historical adapter/cache module is appropriate. Keep pure
math separate from file/network access and include any new pure module in the
existing import-boundary checks. Do not introduce a microservice or database
migration for this file cache.

Another session is changing journal feed selection in `alpaca.py`,
`alpaca_enricher.py` and `trade_path.py`. Fetch current `origin/main` before
starting and again before touching shared functions. Pass the chart feed
explicitly; never change or temporarily mutate `ALPACA_DATA_FEED`. Prefer
chart-owned request/cache code with the existing credential configuration over
refactoring the shared client. Its current 403-to-empty behavior is not a safe
definition of successful chart history.

## Source and session contract

- Dates mean `America/New_York` dates, converted with `zoneinfo`, not UTC dates.
  A history session must be strictly earlier than today's New York date.
- Request Alpaca `1Min` bars with **`feed=sip` and `adjustment=raw` on every
  HTTP request**, including pagination/retries. The requested end must be at
  least 15 minutes before the current UTC time. Validate this before dispatch.
  No fallback to IEX, quotes, synthetic candles or another provider.
- Fetch the whole supported 04:00–20:00 ET window, store minutes whose starts
  are in `[04:00, 20:00)`, and apply regular/extended selection in chart math.
  The Alpaca API has an inclusive end; explicitly exclude any 20:00-start bar.
  DST changes the UTC boundaries, not the session's local clock hours.
- Today remains Tradier REST plus its existing stream. Every normalized bar,
  including streamed new candles and resampled output, carries a stable source
  value (`alpaca_sip` or `tradier`) and the hover legend displays its meaning.
  Daily/weekly bars remain labeled Tradier. Keep freshness separate from source.
- At New York midnight, replace the newly completed day's Tradier bars with
  its complete SIP session atomically. Do not merge providers by timestamp
  inside that day. If SIP is unavailable, disclose the gap; do not report a
  successful historical replacement using leftover Tradier minutes.
- Successful empty sessions and legitimate no-trade minutes are possible.
  Preserve gaps; "no missing minutes" in tests means no loss of fixture source
  bars, not a demand to manufacture one candle per clock minute.
- Label intraday history as raw/unadjusted. Keep daily adjustment limitations
  visible and do not claim matching prices/indicators across a split. Adjustment
  transforms and corporate-action UX belong to C0.6, not this PR.

The [Alpaca FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) confirms
delayed historical SIP access. Its [bar endpoint](https://docs.alpaca.markets/us/reference/stockbarsingle-1)
defines inclusive boundaries and pagination; a short page alone does not prove
completion. Check `next_page_token` until exhausted.

## Persistent cache and provider budget

Use a versioned **chart-owned** namespace under persistent `backend/data/`,
separated by feed, price basis, symbol and New York session date. An example is
`chart_history/v1/stocks/1Min/sip/raw/{symbol}/{date}.json`. Do not treat legacy
journal cache files as complete chart sessions or write chart state into them.
Validate symbols before using them in paths.

A cache record includes its schema version, symbol/date, provider/feed,
adjustment, covered window, fetch time, complete status and normalized minutes.
Publish it with an atomic file replace only after all response pages succeed
and structural validation passes. On failure, discard that day's incomplete
candidate; already completed days in the same batch remain usable. Preserve a
successful empty result as an explicitly completed empty session. Authentication
errors, malformed responses and timeouts are not empty sessions.

Validated completed records have no TTL and cost **zero provider calls**, also
after restarting the feed object or API. Normal navigation never refreshes them.
A corrupt/incompatible file is an explicit cache error, not trusted data; any
repair/invalidation must be deliberate and observable. Immutable cache means
the first successfully retrieved provider snapshot, not a promise that upstream
vendors never revise history. Verify the directory follows the existing
deployment data symlink and backup policy; do not store it in a release directory.

Use a separate Alpaca chart budget of **30 actual HTTP attempts per rolling
60 seconds**, including provider pages and retries, shared across chart panels
and tabs in the supported single API process. This leaves headroom under Basic's
200/min allowance for journal work; it is not a global cross-process limiter.
Honor 429/Retry-After, expose a retryable history state and do not retry in a tight
loop. Tradier's cap/cooldown stays independent. Coalesce duplicate session
misses and use atomic files to prevent interrupted or concurrent writes.

Bound each history work batch to at most **8 HTTP attempts and 10 seconds**
(timeouts use the remaining deadline). Keep completed sessions and return
resumable progress if more work remains. Never hold Tradier's read lock while
fetching history or sleeping for Alpaca. Today must remain usable while cold
history or higher-interval warmup loads. Test the independent paths with a
blocked historical provider, not just by counting requests.

Loading the workspace must not eagerly backfill 1,200 candles plus years of
warmup for all five intervals. Render available current data first, prioritize
the panel the user is navigating, and fetch older pages on demand. Coarser
intervals may show an explicit indicator-warmup state while bounded batches run.

## History API and panel lifecycle

Add private `GET /charts/history`, using the same symbol/session validation as
the workspace. Initial and older intraday pages share the same data path.

- Request identity: symbol, interval (`1m` through `4h`), session, and an
  exclusive `before` UTC candle-start timestamp. The default page size is
  1,200 returned candles; reject or clamp larger client limits consistently.
- The response identifies that request and returns sorted, unique normalized
  bars, markers for the returned window, an older cursor, exhaustion state,
  source/price-basis metadata, warmup status and any issue/retry information.
  Use bounded read-only marker queries with the existing truncation disclosure.
- Cursors must progress across empty weekends/holidays and missing-data dates.
  Stop at the documented history floor (2016 for Alpaca), or an earlier-stop
  boundary supported by actual instrument metadata. A failed request or one
  empty day is not proof of exhaustion. Unsupported daily/weekly pagination
  must not silently hit the minute endpoint.
- If the work budget expires, use an explicit pending result with a validated
  continuation and retry time. A continuation is bound to its symbol, interval,
  session and requested window; never accept arbitrary paths from it. Specify
  the concrete JSON/types in the implementation and fixture them together.
  Already completed sessions may display while additional sessions are pending;
  unresolved indicators remain null and labeled.
- Load the prior page when the visible logical range is within 100 candles of
  the loaded left edge. Allow one in-flight request per panel/request identity;
  debounce range events, deduplicate overlap by timestamp, and ignore aborted
  or stale responses after symbol, session or interval changes.
- Preserve the visible time anchors, bar spacing and fractional viewport
  offset when prepending or evicting. A data-driven range restoration must not
  initiate range-link feedback or cascading duplicate fetches in other panels.
- The 15-second workspace response reconciles the current tail; it must not
  replace the panel's accumulated historical pages. Stream updates target the
  live tail, not whichever older candle is currently rightmost on screen.
- Cap retained normalized data at **12,000 candles per panel**, including any
  separate retained live tail. Evict data away from the visible range; never
  evict the visible window to make space for an offscreen refresh. Evicted pages
  can be reread from disk without new provider calls. Raw minutes and indicator
  warmup prefixes stay on the server. Bound temporary responses as well.
  If the visible range itself fills the ceiling, pause further prefetch and
  explain the limit instead of silently moving or truncating the view.
- "Latest candles" restores current data even after the newer history has been
  evicted. History failure leaves already displayed bars and current updates
  intact and offers retry; it must not turn a live countdown stale solely
  because an older-page request failed.

## Indicator warmup and page seams

Compute in `chart_math.py` after resampling and session filtering. Use at least
**1,400 preceding candles at the requested interval** as the EMA warmup prefix,
then discard the prefix from the visible page. EMA-200's seed influence after
1,400 recurrence steps is `(199/201)^1400 < 1e-6`. This bounds seed influence,
not absolute dollar error; test against a longer continuous reference with an
explicit price-scaled tolerance. Warmup is not 1,400 source minutes for all
intervals. RSI uses the same prefix and its existing Wilder convention.

For VWAP and partially loaded resampling buckets, fetch the complete source
session from its beginning; a mid-session page boundary must not reset VWAP or
truncate its first candle. Ensure enough pre-page data for the selected session
mode. When listing inception/history exhaustion prevents full warmup, expose
insufficient-history metadata and withhold indicators whose warmup requirement
cannot be met. During bounded cold loading, distinguish pending from exhausted.

Compare overlapping page results against a continuous reference and retain
stable indicator values on already displayed candles within the documented
tolerance. Copy the implemented rule and any limitations to
`docs/charts-workspace.md` when C0.0 ships, not during this planning change.

## Required evidence

| Test | What must be established |
|---|---|
| Source stitching | Multiple SIP days plus Tradier today preserve every valid fixture minute exactly once; no mixed-provider day; regular/extended, DST and New York midnight rollover |
| Request spy | Every initial, paginated and retried historical call has SIP/raw and a safe explicit end, even when the global feed is IEX |
| Cache lifecycle | Warm load and a new feed instance make zero historical calls; empty success, interrupted pagination, malformed data, corrupt cache and simultaneous misses remain distinguishable |
| Budget isolation | Actual attempts stay under the Alpaca cap; 429 backs off; pending work resumes; a blocked history call does not block Tradier refresh |
| Numerical reference | 1m, 5m, 1h and 4h pages agree with continuous resampling/EMA/RSI/VWAP references within stated tolerance; mid-session boundaries and insufficient history are covered |
| Six-month browser journey | Real chart navigation through fixture pages at 5m; assert visible timestamps and pixel/bar-spacing stability as pages, live ticks and REST corrections arrive |
| Bounded navigation | Scroll beyond the 12,000-candle ceiling, navigate both directions, return live, switch symbols during a delayed request, retry failures, link ranges, and preserve old fill markers |
| Phone and regressions | Repeat scroll-back at 390px with a touch path; verify no horizontal overflow; retain stream, countdown, fullscreen, symbol-link and marker tests |

Run targeted tests while developing, then `bash scripts/verify.sh`. Inspect the
actual rendered desktop and phone charts. Existing test-only chart instrumentation
may inspect viewport/series state; a passing canvas-count assertion alone is
not scroll-back evidence. Fixture tests do not establish live account access.

Before merging the implementation, make a small read-only historical SIP probe
using the configured account and record dates/feed/results without credentials.
Sample a returned chart page against that data. After CI and Deployment package
checks pass, use the repository's normal PR/merge/release workflow. Respect
market-hours deployment deferral; do not add `deploy-now` merely to finish sooner.
After installation observe the release version, `GET /health`, Charts loading,
an older page loading on scroll, and the stream connection. Distinguish a
connected stream from an observed market-hours trade. Report unavailable or
deferred checks honestly; never use a fixture screenshot as production proof.

C0.0's implementation is PR #89; the roadmap marks C0.1 next. The workspace
and feature map document the implemented behavior and its verification boundaries.

## Handoff prompt

> Implement exactly C0.0 in TradeJournal. Read AGENTS.md, CLAUDE.md,
> docs/charts-workspace.md, docs/charts-roadmap.md and
> docs/charts-deep-history.md first. Fetch current origin/main and start a fresh
> branch containing these planning documents. Follow C0.0's contract and test
> matrix; preserve the existing chart/live behavior and concurrent enrichment
> work. Do not implement the other roadmap items or change the global Alpaca
> feed. Run scripts/verify.sh, inspect desktop and phone rendering, update the
> required docs, open a concise PR, and merge only after CI and Deployment
> package checks pass. Verify the installed release and live chart behavior
> through the normal deployment workflow, reporting only actual observations.
