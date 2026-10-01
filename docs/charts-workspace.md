# Charts workspace

What is built. What comes next, and in what order, is in
[charts-roadmap.md](charts-roadmap.md).

C0.0 deep history follows the [implementation contract](charts-deep-history.md).
The [roadmap](charts-roadmap.md#status-board) keeps the next item in order.

The private `/charts` page is a stock/ETF chart workspace backed by Tradier for
today and Alpaca historical SIP for completed intraday sessions.
It uses TradingView's Apache-licensed Lightweight Charts, not the restricted
Advanced Charts library. No TradingView subscription or paid data upgrade is
required by this feature. The Tradier account still needs production market-data
access. Keys remain on the private backend.

## License and data costs

The frontend lockfile selects **Lightweight Charts 5.2.1**, distributed under
Apache License 2.0 with a no-charge, royalty-free license grant. Using this
library in TradeJournal requires no TradingView account, subscription or chart
license payment. See the version's [LICENSE](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/LICENSE)
and [attribution instructions](https://github.com/tradingview/lightweight-charts/tree/v5.2.1#license).

Preserve the upstream notices and license. The current source enables
`attributionLogo` in `PriceChart.tsx`, links TradingView and its notice in the
workspace footer, and ships `frontend/public/lightweight-charts-NOTICE.txt`
and `frontend/public/lightweight-charts-LICENSE.txt`. Keep attribution available
in full screen and on phone layouts when those views change.

This library renders data supplied by our backend; it does not include
TradingView market data, Pine execution or the TradingView website's complete
drawing/alert product. Tradier/Alpaca access has separate account/data terms.
The existing TradingView-to-Signals loop also remains separate: free chart
rendering alone does not replace a subscription used to run Pine alerts there.

## Provider decision (2026-09-29)

The user has free API plans. A read-only market-hours probe at 10:57 ET returned:

| Provider | Evidence | Decision |
|---|---|---|
| Tradier | HTTP 200 for MRVL/SPY quotes, 4,424 MRVL minute candles over seven calendar days, and 276 daily candles over 400 days. Quote timestamps were current within seconds. Response headers confirmed 120 requests/minute. | Today, quotes, daily/weekly bars and the live stream. |
| Webull | The existing app key's v3 stock snapshot request returned HTTP 401: the request IP did not match its configured settings. | This proves an IP restriction, not missing market-data entitlement. No allowlist or account settings were changed. |
| Alpaca Basic | The journal client may default to IEX; its setting is independent of Charts. | Completed intraday sessions request historical SIP with raw adjustment explicitly. No IEX fallback. |
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
short for intraday bars, especially with extended hours. Charts use the 2016
Alpaca history floor; actual coverage depends on entitlement and available bars.
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
- Levels, watchlist, intervals, session, indicators, layout and named layouts are saved on the
  server (`GET`/`PUT /charts/settings`, table `chart_settings`), so the phone
  and the desktop share them. The symbol on screen and the recent symbols stay
  per device. Each save names the revision it was based on and the server
  refuses an older one (HTTP 409) instead of overwriting it; the device then
  re-applies its own changes on top of the newer copy (levels and the watchlist
  item by item) and saves again, and the toolbar says it merged. Browser
  storage keeps a full copy: when the server cannot be reached the charts use
  it, say *Saved in this browser · server unavailable*, and push the changes
  when the page regains focus. Other devices' saves arrive on focus and every
  30 seconds while visible. On the first visit after this shipped, settings
  saved only in a browser merge into the server copy rather than replacing it.
- A click on **Draw price level** arms the main chart. Click a price to save it,
  or enter a labeled level in the side panel. Levels appear on every timeframe
  of that symbol and can be deleted individually.
- Fill arrows describe buy/sell execution and instrument type. Option premiums
  never become an underlying stock price. Recent fills link to their records.
- **Layouts** (header button) saves the current arrangement under a name, such
  as "0DTE SPY" (1m | 5m | 15m ...) or "Names" (the traded name beside SPY and QQQ),
  and switches to it in one click or tap. A layout is the chart mode (five
  charts or one), the five intervals, the symbols panels hold, the small-chart
  height and linked time ranges. The main symbol, levels, watchlist, session
  and indicators belong to the workspace, so switching never moves them. The
  button shows the layout the panels are arranged as right now; after a panel
  is edited no layout is in use until one is replaced with **Update**. Rows
  rename, replace with the current arrangement, and delete after a
  confirmation. Names are single-spaced, up to 30 characters and unique
  ignoring case, and twelve layouts can be saved. A saved layout whose
  arrangement is not one the page could have saved (a wrong number of
  intervals, a third held symbol, an unknown mode or size) is dropped whole
  when read, never repaired into an arrangement nobody made. Layouts are part of the saved
  settings: another device sees them on focus or within 30 seconds, and a save
  refused as stale merges layout by layout (a layout saved, renamed or deleted
  here is re-applied on the other device's copy; if both devices changed one
  layout, this device's version wins; two layouts that end up with one name
  become "Name" and "Name (2)"; if both devices save one at the limit, both are
  kept, the menu reads 13/12 and asks for a deletion before another save).
  Switching changes the shared intervals and
  held symbols, so the other device's panels follow. The menu is a centered
  dialog on a desktop and a bottom sheet on a phone, also in full screen;
  Escape closes it without leaving full screen, and symbol search (Cmd/Ctrl+K)
  stays closed while it is open. Layouts make no provider calls
  beyond the workspace request the new intervals and symbols need.
- One private API-owned Tradier WebSocket market stream serves all visible chart
  tabs. Valid trade prices are batched to at most one event per second and sent
  to each tab through private server-sent events. Symbol changes update that
  single upstream subscription. Hidden or paused tabs disconnect; the stream
  reconnects after provider or network failures.
- The 15-second visible-tab REST refresh remains the source of truth for volume,
  indicators, fill markers, and recovery after missed stream events. Live prices
  move the selected intraday candles between refreshes; volume and studies may
  lag by up to one refresh. Daily and weekly candles stay on REST history.
- Streamed trades and the one-second clock stay out of the workspace's React
  state. `frontend/lib/chartStore.ts` holds the stream for the current
  request, and each chart applies the new trades to its own panel
  (`applyTicks` in `lib/charts.ts`). A trade re-renders only the charts whose
  candles it moved, plus the quote. The countdowns, the status dot and the
  price age read a shared one-second clock themselves, so a second passing
  re-renders those labels and no chart.
- Each panel creates its chart once. A new symbol, interval, session or RSI
  setting swaps data and panes on the same chart. Until a new symbol's or
  session's candles arrive, every chart keeps its previous frame, dimmed and
  labeled (*Loading NVDA…*); the full loading card appears only on the first
  load. A request that fails clears the charts instead of leaving another
  symbol's candles under the new name. Candles depend only on the symbol and
  session, so moving an interval into the main chart or editing the watchlist
  redraws from candles already loaded, and each interval's older history
  survives the move.
- Each smaller chart follows the main symbol or holds its own: click its
  symbol to pick one from the symbol search, or to follow again. A pin marks a
  held symbol and a link icon a follower. Charts show three symbols at most
  (the main one and two held), so SPY, QQQ and the traded name fit side by
  side; a fourth is refused with a message. Switching the main symbol moves
  only the followers. **Focus** on a chart holding SPY makes SPY the main
  symbol and leaves that panel holding the previous one. Held symbols are part
  of the saved layout, shared across devices; the main symbol stays per device.
  One workspace request carries every symbol (`extras=SPY:5m.1h,QQQ:15m`;
  held symbols skip the quote read), and one stream carries their trades
  (`/charts/stream?symbols=…`). History, retries and day rollover are kept per
  symbol and interval, and crosshair and time-range links match charts by time.
  Drawing a level still arms the main chart.
- The selected price says whether it is a streamed trade, an extended-hours
  candle, or a Tradier quote. The watchlist keeps its batched provider quotes,
  which can show regular-session closes after hours.
- Intraday charts load older SIP/raw pages when the visible range nears the
  loaded left edge. A 5m chart can navigate six months through pages. The
  candle hover legend says **SIP raw** or **Tradier**. Today's forming bars and
  the live stream remain Tradier; daily/weekly bars remain Tradier.
- When today has no intraday bars (before 04:00, weekends, holidays), each
  intraday panel opens on the latest completed SIP sessions instead of an
  empty chart.
- On a New York date rollover, the refresh removes the completed Tradier day
  and requests its SIP replacement for the displayed intraday panels without
  waiting for a pan. A pending or failed replacement is disclosed as history
  loading or an error; the two providers are never merged within that day.
- Streamed trades and REST refreshes that only change the newest candle (or add
  one) go through Lightweight Charts' `series.update`, so zoom, scroll and the
  crosshair stay where they are. A full `setData` reset happens when the symbol,
  interval or session changes, or when an older bar changes. Prepending or
  evicting historical pages preserves the visible logical range, including its
  fractional offset. `barChange` in `lib/charts.ts` decides the update path.
- Intraday charts show a **next-bar countdown** computed from the browser clock
  and the session windows the workspace response sends as `market` (the same
  `session_windows` the backend resamples and streams with); it adds no
  provider calls. It shows a number only while
  updates are running, data is not delayed or stale (refresh within 45 seconds,
  no error or partial refresh), the clock is inside the selected session, and
  the newest candle belongs to the current session segment. Otherwise it says
  Paused, Delayed data, Stale data, Market closed, or Waiting for bars. A
  holiday reads Market closed, and on an early-close day the regular session
  and its last buckets end at 13:00. Only unusual days get a label beside the
  quote: *Early close 1:00 PM ET*, the closure's name on a weekday holiday, or
  a warning that clock hours apply because the calendar is unavailable.
- **Full screen** covers the app navigation, hides the side panels (the
  watchlist can be toggled back), and gives the main chart the screen height
  below a sticky toolbar with an Exit button; Escape also exits. Smaller charts
  have a saved S/M/L height and a per-chart expand toggle.
- **Symbol search** (Cmd/Ctrl+K) lists the typed ticker, the last eight symbols
  and the watchlist; arrows move, Enter charts, Escape closes. Watchlist rows
  take Up/Down/Home/End, and Alt+Up/Down steps the charted symbol through the
  watchlist. Intervals are workspace settings and carry over. Search never calls
  a provider; only the resulting symbol change loads data.
- **Hotkeys** (`frontend/lib/hotkeys.ts`; `?` or the keyboard button opens the
  list). Typed minutes (`1`, `3`, `5`, `15`, `30`) show in a small box over the
  chart and change the main chart's interval only on Enter, so typing 15 never
  loads 1m first; Backspace erases a digit, Escape or a click elsewhere cancels,
  and a number with no interval (7) is refused in the box. `H`, `4`, `D` and
  `W` switch the main chart to 1h, 4h, 1D and 1W at once (4 is a typed digit
  only after another digit). Space and Shift+Space step through the watchlist,
  wrapping at both ends; a button reached with Tab still takes Space, but one
  that was clicked does not, so Space keeps stepping after a click. Alt+R
  (Option+R) resets every chart to its opening view of the latest candles with
  automatic price scales; End moves every chart to its latest candle at the
  current zoom. Neither carries one chart's range to the others when time
  ranges are linked. Hotkeys are off while focus is in a field or a dialog is
  open, including the app's Sync drawer and phone menu (marked modal while
  open), and Ctrl/Cmd combinations other than Cmd/Ctrl+K are left to the
  browser. The cheat sheet is drawn from the same table as the keys. By touch,
  the interval buttons, the watchlist's up/down arrows and each chart's
  latest-candles button (which now also restores the automatic price scale)
  do the same things.
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
demand-driven and bounded to the symbols each tab is viewing (three at most).

`backend/app/engine/chart_feed.py` loads today's candles (15-second TTL), daily
bars (60-second TTL), and a single batch of watchlist quotes (15-second TTL).
All five panels share these reads. A lock coalesces concurrent misses; a bounded
96-entry cache and a 60-request/minute chart budget leave headroom under
Tradier's 120/min token allowance. A visible five-chart workspace on one stable
symbol normally uses about nine upstream requests per minute after its
three-request first load; with SPY and QQQ held by panels it uses about 17,
and a second tab with the same layout adds none.
A 429 stops upstream chart calls for a minute. The existing
position-quote client remains separate and can still share the token's allowance.
These are single-API-process caches, matching the current deployment.
The private `GET /charts/history` returns up to 1,200 older intraday candles per
page, with an exclusive `before` timestamp, older cursor, exhaustion,
source/price basis, markers, warmup state and retryable issue. Its opaque
continuation is bound to the request and expires after 10 minutes in the
single API process. A cold batch uses at most eight Alpaca HTTP attempts and
10 seconds; the frontend resumes pending batches. History errors leave today's
Tradier countdown and already displayed bars intact.

`backend/app/engine/chart_history.py` keeps complete 04:00–20:00 New York
sessions in `backend/data/chart_history/v1/stocks/1Min/sip/raw/`, under the
deployment's persistent data symlink and state backup. Records are validated
and published atomically only after every provider page succeeds. A completed
record, including an empty session, has no TTL and costs zero provider calls
across API restarts. Corrupt records require deliberate repair. The separate
Alpaca chart budget is 30 actual HTTP attempts per rolling minute in one API
process; a 429 honors Retry-After. No Alpaca request targets the latest
15 minutes. The frontend keeps at most 12,000 normalized candles per panel,
including the current tail, and rereads evicted pages from this disk cache.

`backend/app/engine/chart_calendar.py` adapts Tradier's `/v1/markets/calendar`
(one request per month, available back to 2016) into normalized open/closed
days with regular hours. A month fetched after it ended is final and saved in
`backend/data/chart_calendar/v1/tradier/`, so each past month costs one request
per deployment; a damaged copy is refetched. The current month is refetched
once per New York date, and a failed refresh keeps the previous copy. Requests
share the chart feed's 60/minute Tradier budget and back off 60 seconds per
month after a failure. Only past and current months are requested; Tradier
rejects unpublished years. Its premarket/postmarket times (07:00, 19:55) are
Tradier's order hours, not the consolidated tape, and are not used. The
workspace sends today's windows as `market`. History pages resample each
session with its own date's hours and skip calendar-closed dates without an
Alpaca request. The stream reads only the in-memory copy, never the provider.
Without a calendar, clock hours apply and `market.note` or the page's
`calendar_note` discloses it.

No partial intraday data enters the persistent enrichment caches. No feed
fallback mixes IEX or unofficial quotes into these charts. Intraday SIP prices
are raw/unadjusted, so a split may create a discontinuity; daily adjustment
is still not guaranteed. A failed refresh may
retain last-known bars with their original fetch timestamps and an explicit
warning. Missing credentials/data produces an empty setup state, never sample
prices. Sandbox data is labeled delayed. Last-trade age is displayed separately
from refresh time; a successful HTTP call is not proof that a quote is fresh.

`backend/app/engine/chart_math.py` is pure. Provider Unix timestamps identify
minute bars; daily dates map to 09:30 America/New_York. Resampling anchors each
regular session at 09:30 and keeps premarket (04:00–09:30) and postmarket
(16:00–20:00) separate. With calendar data the regular session is the day's
calendar hours and postmarket runs from the close to four hours after it
(17:00 after a 13:00 early close; consolidated SIP minutes end there too); a
closed date has no session. Without calendar data, weekdays use the clock hours
above and responses say so. DST conversion uses zoneinfo. Actual bars come from
the selected provider. Weekly bars combine Tradier daily data with Monday
alignment.

VWAP uses minute HLC3 × volume, resets each regular session, and is absent outside
the regular session (09:30–16:00, or 09:30–13:00 on a half day). It is a bar-based estimate, not trade-level VWAP. EMAs use the first
close as a seed and remain absent until the length has elapsed. RSI uses Wilder
averages with 14 changes of warmup. Historical pages use 1,400 preceding
**resampled candles at the selected interval** as the indicator prefix, then
discard it from the returned page. This bounds EMA-200 seed influence below
`(199/201)^1400 < 1e-6`; it does not bound absolute dollar error. VWAP always
uses the complete source session. During cold loading, unresolved EMA/RSI
values are null and marked pending; at the 2016 floor, insufficient prefix
keeps them null. These calculations are chart-only and do not
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
and keyboard symbol navigation. Hotkey tests type 1 then 5 then Enter and check
that no request asked for 1m on the way to 15m, refuse 7, erase with Backspace,
cancel with Escape (staying in full screen) and with a click, switch with H, 4,
D and W, stay off in fields, selects, dialogs and the Sync drawer, step the watchlist with
Space and Shift+Space from a clicked button while a Tabbed-to button keeps
Space, reset every chart's range and price scales with Alt+R, return each
chart to its latest candle at the same zoom with End (also with linked
ranges), compare the `?` sheet with the exact binding list, and do the same
by touch at 390px. A canvas comparison checks that VWAP does not paint across an
extended-hours gap while still drawing within the regular session.
`backend/tests/test_chart_stream.py` checks session buckets, invalid event
filters, and a single upstream subscription shared across tabs.
`backend/tests/test_chart_calendar.py` covers Tradier calendar parsing,
malformed and incomplete months, completed months on disk, daily refresh,
failure backoff and the shared budget. The chart tests pin an older half day's
regular/extended classification, VWAP and buckets, early-close stream buckets,
holiday skipping in history and the unavailable-calendar disclosure. The
browser suite drives a fixture holiday, a 13:00 early close in both session
modes, a missing calendar, and a day with no intraday bars.
`backend/tests/test_chart_history.py` covers SIP/raw request parameters,
pagination and retries, completed/empty caches, corrupt data, the
30-attempt and eight-attempt budgets, concurrency, source stitching and
requested-interval numerical references. The browser suite scrolls a 5m chart
six months, checks range stability under pages, a tick and REST refreshes,
then exercises 12,000-candle eviction, gap refill, retry, stale navigation and
390px touch paging. These are fixture results, not live Alpaca entitlement.
A render-count test (through a test-only `window.__tjRenders` map) shows that
clock seconds re-render no chart, a price change re-renders the four intraday
charts but not the daily one, a new minute's first trade at an unchanged price
re-renders only the 1m chart, and a repeated trade re-renders none.
A keep-alive test holds the provider response mid-switch and checks that all
five chart instances survive symbol, interval, session and RSI changes, that
the old frame stays dimmed under its label, that the loading card never
appears, and that a failed symbol clears the charts. Per-panel symbol tests
hold SPY and QQQ beside the traded name through a main-symbol switch (the held
chart is neither recreated nor redrawn), route each streamed trade to its own
symbol's chart, pause and resume all three, keep linked time ranges, refuse a
fourth symbol, scroll a held chart back through its own history, and focus a
held chart into the main one. `backend/tests/test_charts.py` bounds a
three-symbol layout from two tabs to 17 upstream requests a minute, and
`backend/tests/test_chart_stream.py` routes several symbols per tab over one
upstream subscription. Settings tests save a
level in one browser context and read it in a second one through the e2e
backend, check that a stale save is refused, and use a fake settings server for
a merged conflict, the first-visit merge of browser-only settings, and an
unreachable server. `backend/tests/test_charts.py` covers the revision rule,
malformed and oversized saves, and that a refused save returns another
device's layouts whole. Layout tests save, switch, rename, replace, refuse a
duplicate name and delete layouts through the menu, and check that switching
restores intervals, held symbols, chart height and range linking while the main
symbol, levels and watchlist stay put (and that the server copy has them). They
save a layout in one browser context and use it from a second one through the
e2e backend, merge a stale save (a layout deleted and one saved offline beside
another device's rename, addition and same-named layout), keep both layouts when
two devices each save a twelfth, drop each kind of malformed saved layout whole,
keep Cmd/Ctrl+K from opening symbol search behind the dialog, and open the 390px
bottom sheet by touch, in full screen too.

Live-provider probes establish actual Tradier access; stubbed browser tests do
not. Neither establishes full TradingView parity. This version has no Pine
runtime, raw tick tape, trendline/fibonacci tools, replay, volume profile
or server-side chart alerts. The existing
TradingView-to-Signals loop still runs separately. Keep TradingView while
comparing the required indicators and sessions side by side.
