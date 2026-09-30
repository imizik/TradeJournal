# Charts workspace

The private `/charts` page is a stock/ETF chart workspace backed by Tradier.
It uses TradingView's Apache-licensed Lightweight Charts, not the restricted
Advanced Charts library. No TradingView subscription or paid data upgrade is
required by this feature. The Tradier account still needs production market-data
access. Keys remain on the private backend.

## Provider decision (2026-09-29)

The user has free API plans. A read-only market-hours probe at 10:57 ET returned:

| Provider | Evidence | Decision |
|---|---|---|
| Tradier | HTTP 200 for MRVL/SPY quotes, 4,424 MRVL minute candles over seven calendar days, and 276 daily candles over 400 days. Quote timestamps were current within seconds. Response headers confirmed 120 requests/minute. | Use for this first version. |
| Webull | The existing app key's v3 stock snapshot request returned HTTP 401: the request IP did not match its configured settings. | This proves an IP restriction, not missing market-data entitlement. No allowlist or account settings were changed. |
| Alpaca Basic | Existing client defaults to IEX; free real-time coverage is a single venue. | Keep its existing journal/research role. Do not silently substitute IEX into consolidated chart history. |
| Polygon/Massive Basic | Five calls/minute and end-of-day availability. | Keep historical enrichment; unsuitable as this page's live source. |

Webull's [marketing page](https://www.webull.com/open-api) advertises free Level 1
quotes, while its [developer permission table](https://developer.webull.com/apis/docs/market-data-api/overview/)
and [getting-started guide](https://developer.webull.com/apis/docs/market-data-api/getting-started/)
require an OpenAPI data subscription for stock/ETF bars. App/desktop subscriptions
do not transfer. The evidence does not establish whether this user's account has
a free/grandfathered OpenAPI entitlement. Probe from its already-allowed host if
evaluating Webull further; don't open or alter its IP allowlist for chart testing.

Tradier's [market data](https://docs.tradier.com/docs/market-data) is consolidated;
[API access](https://docs.tradier.com/docs/faq) is included for brokerage account
holders. [Historical limits](https://docs.tradier.com/docs/historical-data) are
short for intraday bars, especially with extended hours. The UI states the
requested history window instead of promising TradingView history depth.
On 2026-09-29 the production token created a market-stream session (HTTP 200)
and connected to Tradier's separate WebSocket endpoint with an SPY subscription.
The session response's URL was for HTTP streaming, not WebSocket streaming.
A market-hours tick has not yet been observed through the new browser relay.

Recheck actual access without booting the API or touching the database:

```bash
cd backend
.venv/bin/python -m scripts.check_chart_feed --symbol MRVL
# Optional: --env-file /path/to/backend/.env (reads provider credentials only)
```

## Implemented behavior

- One main chart and four smaller linked charts, or one focused chart.
- Intervals: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1D and 1W. Select a smaller chart to
  make it the main one; all panels follow the selected symbol and crosshair.
- EMA 9/20/50/200, regular-session VWAP, volume and Wilder RSI(14).
- Extended-session shading and regular/extended hours selection. Daily and
  weekly charts always use the provider's daily bars, never extended-hours
  aggregates. Tradier does not guarantee dividend adjustment.
- A 30-symbol watchlist, saved horizontal price levels, and journal fill arrows.
  Levels, watchlist, indicators and intervals persist in **this browser** via
  versioned localStorage. This is not cross-device synchronization.
- A click on **Draw price level** arms the main chart. Click a price to save it,
  or enter a labeled level in the side panel. Levels appear on every timeframe
  of that symbol and can be deleted individually.
- Fill arrows describe buy/sell execution and instrument type. Option premiums
  never become an underlying stock price. Recent fills link to their records.
- One private API-owned Tradier WebSocket market stream serves all visible chart
  tabs. Valid trade prices are batched to at most one event per second and sent
  to each tab through private server-sent events. Symbol changes update that
  single upstream subscription. Hidden or paused tabs disconnect; the stream
  reconnects after provider or network failures.
- The 15-second visible-tab REST refresh remains the source of truth for volume,
  indicators, fill markers, and recovery after missed stream events. Live prices
  move the selected intraday candles between refreshes; volume and studies may
  lag by up to one refresh. Daily and weekly candles stay on REST history.
- The selected price says whether it is a streamed trade, an extended-hours
  candle, or a Tradier quote. The watchlist keeps its batched provider quotes,
  which can show regular-session closes after hours.
- Streamed trades and REST refreshes that only change the newest candle (or add
  one) go through Lightweight Charts' `series.update`, so zoom, scroll and the
  crosshair stay where they are. A full `setData` reset happens when the symbol,
  interval or session changes, when older history changes (a REST correction),
  or when the 1,200-candle window slides. `barChange` in `lib/charts.ts` decides.
- Intraday charts show a **next-bar countdown** computed from the browser clock
  and the same session-anchored buckets the backend uses (`nySession`/`barClock`
  mirror `session_part`); it adds no provider calls. It shows a number only while
  updates are running, data is not delayed or stale (refresh within 45 seconds,
  no error or partial refresh), the clock is inside the selected session, and
  the newest candle belongs to the current session segment. Otherwise it says
  Paused, Delayed data, Stale data, Market closed, or Waiting for bars. There is
  no holiday calendar: a holiday reads as Waiting for bars, not as closed.
- **Full screen** covers the app navigation, hides the side panels (the
  watchlist can be toggled back), and gives the main chart the screen height
  below a sticky toolbar with an Exit button; Escape also exits. Smaller charts
  have a saved S/M/L height and a per-chart expand toggle.
- **Symbol search** (Cmd/Ctrl+K) lists the typed ticker, the last eight symbols
  and the watchlist; arrows move, Enter charts, Escape closes. Watchlist rows
  take Up/Down/Home/End, and Alt+Up/Down steps the charted symbol through the
  watchlist. Intervals are workspace settings and carry over. Search never calls
  a provider; only the resulting symbol change loads data.
- **Link time ranges** (off by default) makes panning or zooming one chart set
  the same visible *time* window on the other four. Coarser charts keep at least
  a dozen candles around that moment; finer charts that cannot fit the span at
  their minimum bar spacing center on it. The chart being moved owns the link
  for 250 ms and programmatic range changes are not re-broadcast, which prevents
  feedback loops.

## Data and calculation boundaries

`backend/app/routers/charts.py` exposes private `GET /charts/workspace`. It reads
only the necessary journal marker columns after provider calls finish. It never
writes fills, derived trades, enrichment or signals. At most the newest 1,000
fills in the requested history are returned, with truncation disclosed.
Private `GET /charts/stream` holds an SSE response. Only the backend uses the
Tradier token and upstream WebSocket. There is one upstream market connection
per API process; the supported deployment runs one API process. The stream is
demand-driven and bounded to the symbol each tab is viewing.

`backend/app/engine/chart_feed.py` loads the previous nine calendar days of minute
history (30-minute memory TTL), today's candles (15-second TTL), daily bars
(60-second TTL), and a single batch of watchlist quotes (15-second TTL). All five
panels share these reads. A lock coalesces concurrent misses; a bounded 96-entry
cache and a 60-request/minute chart budget leave headroom under Tradier's 120/min
token allowance. A visible five-chart workspace on one stable symbol normally
uses about nine upstream requests per minute after its four-request first load.
A 429 stops upstream chart calls for a minute. The existing
position-quote client remains separate and can still share the token's allowance.
These are single-API-process caches, matching the current deployment.
Each panel returns at most the latest 1,200 candles after calculating indicators
on all fetched history. There is no older-history pagination in this version.

No partial intraday data enters the persistent enrichment caches. No feed
fallback mixes IEX or unofficial quotes into these charts. A failed refresh may
retain last-known bars with their original fetch timestamps and an explicit
warning. Missing credentials/data produces an empty setup state, never sample
prices. Sandbox data is labeled delayed. Last-trade age is displayed separately
from refresh time; a successful HTTP call is not proof that a quote is fresh.

`backend/app/engine/chart_math.py` is pure. Provider Unix timestamps identify
minute bars; daily dates map to 09:30 America/New_York. Resampling anchors each
regular session at 09:30 and keeps premarket (04:00–09:30) and postmarket
(16:00–20:00) separate. DST conversion uses zoneinfo. This is clock-session
alignment, not a full exchange holiday/early-close calendar; actual bars still
come from Tradier. Weekly bars combine daily data with Monday alignment.

VWAP uses minute HLC3 × volume, resets each regular session, and is absent outside
09:30–16:00. It is a bar-based estimate, not trade-level VWAP. EMAs use the first
close as a seed and remain absent until the length has elapsed. RSI uses Wilder
averages with 14 changes of warmup. These calculations are chart-only and do not
change the journal's versioned indicator conventions. Indicators can differ from
TradingView because of feed, warmup, session, or adjustment differences.

Fill markers convert the journal's naive New York execution time to UTC and only
attach to an actual containing candle. They never snap a missing/out-of-session
execution onto an earlier candle. Historical source timestamp uncertainty still
applies; rendering a marker does not revalidate the original execution time.

## Verification and remaining scope

`backend/tests/test_charts.py` covers DST/session resampling, minute-weighted
VWAP, a numeric Wilder RSI reference, malformed bars, shared caches, cooldown,
stale timestamps, access failure, private routes and option fill markers.
`frontend/e2e/charts.spec.ts` verifies rendered canvases, linked symbols, saved
levels, streamed price/candle updates, hidden/paused polling, non-overlapping slow refreshes, errors, missing
credentials and phone layout using stubbed provider responses and a disposable
SQLite backend. It also drives a fake clock through the countdown and each of
its named states, checks that ticks update in place without resetting zoom
while a corrected older bar does reset, pans linked charts and checks they
settle on the same time window, and exercises full screen on desktop and phone
and keyboard symbol navigation. A canvas comparison checks that VWAP does not paint across an
extended-hours gap while still drawing within the regular session.
`backend/tests/test_chart_stream.py` checks session buckets, invalid event
filters, and a single upstream subscription shared across tabs.

Live-provider probes establish actual Tradier access; stubbed browser tests do
not. Neither establishes full TradingView parity. This version has no Pine
runtime, raw tick tape, trendline/fibonacci tools, replay, volume profile,
server-side chart alerts or cross-device layout persistence. The existing
TradingView-to-Signals loop still runs separately. Keep TradingView while
comparing the required indicators and sessions side by side.
