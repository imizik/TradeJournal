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

## Symbol info panel

The section below the watchlist in the Watchlist dock tab follows the main
chart's underlying. On a phone it lives inside the Watchlist bottom sheet. Its
**You** tab reads all accounts' journal history through
`GET /charts/symbol/{symbol}/you`, independently of candles or the stream.
It shows completed-trade count, realized P&L, win rate, average stored hold
time, best/worst trades, the latest actual fill time, separate open trades,
and five recent records with links. Closed and expired trades count as
completed; partial-exit P&L on open trades stays separate. Missing P&L makes
the total and win rate unavailable, and missing hold times are excluded with
the sample count on hover. Results sum stored FIFO P&L without reconstructing
it. Account names accompany each record; positions are not merged across
accounts. The source and read time are shown, with calculated/observed labels.

Its **Events** tab (T1.4) reads `GET /charts/symbol/{symbol}/events`: the
next earnings date with Tradier's status (*Confirmed*, or *Estimated*: Tradier's
estimate, which the company has not announced), days away in New York calendar
days, the fiscal quarter, and "Time of day not published", because Tradier's
calendar has dates only; then the last eight confirmed report dates, the next
announced and the last ex-dividend date with amount and pay date, and splits
in the last two years. Each block names its source and when Tradier was read,
and degrades on its own: an ETF's calendar reads "Tradier lists no earnings",
a failed read shows why and any older copy. No upcoming date reads "Not
announced"; nothing is guessed. The backend keeps Tradier's normalized rows
in memory and under `backend/data/symbol_info/v1/tradier/` for 12 hours
(calendar) or 24 (dividends, splits) and reads Tradier at most 10 times a
minute, apart from the chart feed's budget and cooldowns; a cold symbol costs
three requests, a warm one none.

Its **Forecast** tab (T2.1) reads `GET /charts/symbol/{symbol}/forecast`
with the chart's latest price: the implied move, the at-the-money straddle's
mid (*calculated*) for the nearest expiration, the nearest Friday, and the
first expiration strictly after the next report (from the Events cache; the
report's time of day is unknown, so an expiration on its date may close before
it). Each row shows ±$ and ±% of the price, the strike, both legs' bid and
ask, the IV and the staler leg's quote time. The strike is the one nearest the
price listing both a call and a put; a leg with no bid or ask, a crossed
quote, or a spread wider than its own mid reads "Market too wide" with the
reason, never a number. Chains come through the chart's option feed (below),
60 seconds fresh, and the tab reads again each minute while it is open; until
the chart has a price it waits for one.

Overview and News are placeholders for the
[symbol info roadmap](symbol-info-roadmap.md). The chosen tab is remembered
on this device. Only an expanded You, Events or Forecast tab fetches, once after the
ticker settles for 300 ms; old requests are cancelled. The panel starts
collapsed below 1024 px and follows the watchlist's visibility in full-screen
mode. There are no new tables or migrations for this panel.

## License and data costs

The frontend lockfile selects **Lightweight Charts 5.2.1**, distributed under
Apache License 2.0 with a no-charge, royalty-free license grant. Using this
library in TradeJournal requires no TradingView account, subscription or chart
license payment. See the version's [LICENSE](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/LICENSE)
and [attribution instructions](https://github.com/tradingview/lightweight-charts/tree/v5.2.1#license).

Preserve the upstream notices and license. The current source enables
`attributionLogo` in `PriceChart.tsx`, links TradingView and its notice in the
workspace's status strip (in the toolbar's More menu on a phone, in full screen
too), and ships `frontend/public/lightweight-charts-NOTICE.txt`
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
| Alpaca Basic | The journal client may default to IEX; its setting is independent of Charts. | Completed intraday sessions request historical SIP with raw adjustment explicitly, stored raw; the chart adjusts for splits at display time (C0.6). Alpaca corporate actions supply the split records. No IEX fallback. |
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
- **Workspace shell (C7.3).** On a screen at least 1024px wide `/charts` fills
  the browser window like TradingView: no page padding and no page scrolling.
  The journal navigation is an icon rail (`frontend/components/Nav.tsx`; each
  page a named link with a tooltip, sync state and the Sync drawer at the
  bottom) that **Expand navigation** widens to the full sidebar, remembered on
  the device; other pages keep the sidebar and their padding
  (`frontend/components/AppMain.tsx`), and an actionable Gmail banner still
  sits above the charts. One toolbar row holds the symbol field, the quote,
  the main chart's intervals, the session, **Indicators** (a menu of the
  studies and fill arrows), **Layouts**, Focus, **Link time ranges**, pause,
  refresh, shortcuts, full screen, and the dock's two tabs, **Watchlist** and
  **Layers**; below about 1280px it wraps to a
  second row rather than hiding anything. Undo, redo and the drawing tools
  are a slim rail left of the charts. The dock on the right shows one panel at
  a time: the watchlist with the symbol info panel, the main symbol's levels
  and latest fills under it, or the layers panel. Pressing the open tab's
  button closes the dock;
  whether it is open, and on which tab, is remembered on the device (a device
  that had left the C1.4 layers panel open opens it on Layers). A status strip
  at the foot keeps the feed state, holiday or early-close label, price basis,
  the newest minute candle and the shown price's age, the settings save state,
  an **About chart data** note and the Lightweight Charts attribution in view
  however dense the charts get; data warnings sit as one-line banners under
  the toolbar. The charts are sized by the browser from the space left (CSS
  flex and each chart's `autoSize`), not from a viewport estimate, in the
  proportions the dividers set (C7.4, below). When the main chart's and the
  smaller row's minimums do not both fit (a window about 540px tall) the chart
  grid scrolls inside itself and the page never does; Focus gives one chart
  the whole grid. Opening and closing the dock or the
  navigation and resizing the window keep every chart instance, the selection,
  a scrolled-back view and the stream, and fetch nothing. The Indicators menu
  is not modal (hotkeys keep working); Escape closes it before it puts a tool
  away or leaves full screen. Below 1024px the page scrolls as before: the
  toolbar wraps into rows of 44px controls (the intervals scroll sideways in
  theirs), the drawing tools are a toolbar row, the link, pause, refresh and
  shortcut controls, the smaller charts' S/M/L height, the data note and the
  attribution move into a **More chart controls** menu, and the dock is a
  bottom sheet over the charts (charting a symbol from it closes it; the
  arrows keep it open).
- **Dividers and maximize (C7.4).** On a screen at least 1024px wide the
  four-pixel gaps of the five-chart grid are dividers: one between the main
  chart and the smaller row, one between each pair of smaller charts, and
  the dock's left edge (`frontend/components/charts/Splitter.tsx`). Drag one
  with a mouse, pen or finger, or focus it (Tab reaches each, in the order
  of the charts they sit between) and use the arrow keys (Shift for steps of
  10%, or 64px for the dock), Home and End for its limits; Enter or a
  double-click resets it, and Escape during a drag puts it back without
  saving. **Reset chart sizes** in the Layouts menu resets all of them. A
  drag moves the boxes directly, re-rendering no chart, and is saved once
  when the button is released. The main chart and the smaller row share the
  height by the smaller row's share (15% to 60%; 37.8% by default, which is
  C7.3's medium height in a 1440×900 window), the smaller charts the row's
  width by four shares (none under 10%), and on screen the main chart keeps
  at least 320px, each smaller chart at least 180px with its header and
  160px of width; a row too narrow for four of those (a 1024px window with
  the navigation expanded) scrolls sideways inside the grid, and a narrow
  chart clips its symbol and interval, never its header buttons. A window
  too small for a saved proportion shows it clamped
  and keeps it unchanged for a larger one: nothing is saved by resizing the
  window. The proportions are a shared setting (`proportions`), so another
  computer opens at the same split; a phone ignores them and keeps the S/M/L
  height in its More menu. Settings saved before C7.4 have none, and the
  share then follows the S/M/L size (27.5%, 37.8% or 51.8%), which is the
  height that size had in a 1440×900 window. The dock is 200 to 480px wide
  (256px by default), never leaving the charts less than 640px, and its width
  is this device's only. Every chart header has **Maximize**: the chart
  covers the whole grid while the others stay mounted at their size beneath
  it, hidden, still receiving the stream; **Restore charts** (or Escape,
  after a menu, a tool and a selection, and before full screen) puts the grid
  back exactly, with every chart's view, selection and drawings unchanged.
  Maximizing is this device's, for the moment: it lasts through a symbol or
  interval change, the dock and full screen, and ends on reload, a layout
  switch, Focus, or making that chart the main one. On a phone a maximized
  chart is the only one shown, 410px tall (the whole screen in full screen).
- Intervals: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1D and 1W. Select a smaller chart to
  make it the main one; all panels follow the selected symbol and crosshair.
- EMA 9/20/50/200, regular-session VWAP, volume and Wilder RSI(14). Today's
  regular-session volume bars are shaded by relative volume (C2.4; see
  [Relative volume](#relative-volume-c24)).
- Earnings (C2.5): an **E** below each report date's candle and an
  "Earnings in 5 d" badge in the header (see [Earnings](#earnings-c25)).
- Level alerts (C5.1): set from the menu on a level, a horizontal ray or an
  automatic level; a bell at each price, gray once fired, and the Alerts list
  in the dock (see [Level alerts](#level-alerts-c51)).
- Options levels (C4.4), off until shown from Layers: call and put walls and
  the strikes ranked by open interest, volume or gamma, merged with the
  automatic levels, and the strike ladder (C4.5) in the dock (see
  [Options levels](#options-levels-c44) and [Strike ladder](#strike-ladder-c45)),
  with max pain (C4.7).
- Range bands (C2.7), off until shown from Layers: today's and Friday's
  expected move from the at-the-money straddle, priced five minutes after the
  open and fixed for the session, and VWAP ±1σ/±2σ (see
  [Range bands](#range-bands-c27)).
- Extended-session shading and regular/extended hours selection. Daily and
  weekly charts always use the provider's daily bars, never extended-hours
  aggregates. Prices are split-adjusted (see Price basis below); dividends are not adjusted.
- A 30-symbol watchlist, saved horizontal price levels, and journal fill arrows.
- Levels, drawings, watchlist, intervals, session, indicators, layout and named layouts are saved on the
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
- **Drawing layer (C1.1).** Levels are drawn by one series primitive per chart
  (`frontend/lib/drawings.ts`) instead of library price lines, anchored to
  price, so a level is at the same price on every panel of its symbol at any
  zoom. A mouse press on a level selects it and dragging moves it; the level
  moves by the drag (it does not jump to the pointer) and the chart does not
  pan underneath. On touch, a tap within 14px selects a level and only a
  selected level drags, so panning across a level never moves it, and the page
  does not scroll during the drag. A selected level is solid with a round
  handle on every panel of its symbol; the panel it was selected on shows a
  small bar with its name, price, **Delete** and **Deselect**. A click or tap on
  empty chart space or Esc deselects, and Esc during a drag puts the level back.
  A drop saves the price under the pointer (rounded to cents) dated that New
  York day. Delete or Backspace removes the selected level. Adding, moving and
  deleting levels can be undone with ⌘Z / Ctrl+Z and redone with ⇧⌘Z /
  Ctrl+Shift+Z, or the Undo and Redo buttons beside **Draw price level**, whose
  hover text names the step. Undo is per tab, 100 steps, and replays item by
  item onto the levels as they are now, so another device's levels are left
  alone. Levels are still saved in the same `levels` shape, so a tab running
  an older build keeps reading and merging them.
- **Drawing tools (C1.2).** Beside Undo and Redo: price level, horizontal ray,
  trend line, rectangle zone and text note, then **Magnet**. A tool arms the
  main chart and shows what a click would place under the pointer; a ray or a
  note takes one click, a trend line two points and a zone two opposite
  corners (the hint names the next click; Esc puts the tool away). Anchors are
  a time and a price: each click lands in the middle of the nearest bar, so a
  5m anchor sits inside the right 1h bar and a moment between sessions on the
  boundary between bars; past the last bar the axis continues one interval per
  bar. The magnet (toggle, or hold ⌘/Ctrl for one click or drag) snaps the
  price to that bar's open, high, low or close, whichever is drawn nearest; a
  drawing dragged whole snaps the anchor nearest where it was grabbed and moves
  the others with it.
  Drawings select, drag (a mouse drags any; a finger only the selected one),
  delete and undo like levels: a handle moves one anchor (a zone has one at
  every corner), and the body moves the whole drawing by whole bars and any
  price. The selected drawing's bar names it with its prices; a note's text is
  edited there (a new note opens with the text ready), and **Style** unfolds
  color, line width (ray, trend line) and extend left/right (trend line). A
  color or width becomes that tool's style for the next drawing. Drawings are
  saved per symbol in a `drawings` field of the shared settings (40 per symbol),
  with `toolStyles` and `magnet`, and merge item by item like levels. A save
  never drops a field it leaves out, so an open tab on an older build cannot
  erase drawings. Like levels, each drawing keeps the date it was drawn and
  moves with a later split.
- **Context menu (C1.3).** Right-click a chart, or hold a finger still on it
  for half a second, for its menu (`frontend/components/charts/ChartMenu.tsx`).
  A mouse opens it at the pointer; a finger opens it as a bottom sheet with
  44px rows, closed by its backdrop. The sheet opens under the held finger, and
  that finger's lift presses nothing: until a new touch starts, a click is
  dropped. On empty chart space it offers **Add level
  at** and **Copy price** for the price under the pointer (to the cent; the
  magnet applies, as it does to a placed level), **Reset chart scale** for that
  chart alone, and **Layers**: show or hide My levels, Drawings, Auto levels,
  My fills and each study on every chart, plus a **Show** for each of the symbol's items
  hidden one by one. On a price scale, a time scale or the RSI pane there is no
  price, so only the reset and Layers appear. On a level or drawing it selects
  the item and offers its label (a level's name, a note's text) and color
  inline, **Lock**, **Hide**, **Duplicate** and **Delete**. A locked item still
  selects, restyles, hides and deletes, but never drags: a press on it pans
  the chart, it shows no handles, and its selection bar carries a lock that
  unlocks it. A hidden item leaves every chart and cannot be selected; the side
  list shows a hidden level dimmed with a Show button. A duplicate sits at the
  same place, unlocked and shown, and is selected so the next drag moves the
  copy. Each item change is one undo step named in the Undo button ("Undo
  hiding Pivot"); group visibility is a setting, not an undo step. Adding a
  level or placing a drawing while its group is hidden shows the group again,
  so nothing is saved out of sight. A level's color is saved only when it is
  not the default blue, and `hidden`/`locked` only when set, so untouched
  levels keep their old shape; the hidden groups are a `hiddenGroups` settings
  field that merges key by key. A tab still running a build from before C1.3
  drops these per-item flags if it saves levels or drawings, so reload old tabs
  after deploying. With a tool armed, right-click (or Esc) only puts the tool
  away. The browser's own menu never opens over a chart, and the chart's
  hotkeys are off while the menu is open (Esc closes it; arrow keys move
  between its rows). A label typed in the menu is saved when the menu closes,
  unless Esc closed it.
- **Layers panel (C1.4).** The **Layers** button at the end of the toolbar
  opens `frontend/components/charts/LayersPanel.tsx`: the dock's Layers tab on
  a screen at least 1024px wide (C7.3), and a bottom sheet with 44px targets
  below that, closed by its backdrop, its close button or Esc. Groups: **My levels** and **Drawings** (the
  items of every symbol on screen, under a symbol heading when there is more
  than one), **Journal** (the fill arrows) and **Indicators** (each study).
  Every group hides on all five charts. Levels and drawings also **lock all**
  (or unlock all, once every one is locked) and **delete all** after a
  confirmation, each one undo step ("Undo deleting 2 levels" puts them back
  where they sat), and each item hides, locks and deletes on its own. Groups
  fold; which are folded is remembered on the device. A click on an item
  brings the first panel showing its symbol to it and selects it: a drawing's
  bars are centred at the current zoom (widened to fit a long one), and a
  price off the scale widens the price scale to include it. A drawing older
  than the loaded candles loads the pages before them, at most 20, and then
  centres; a new symbol or interval on that panel, or 20 seconds, cancels the
  wait. On a phone the sheet closes so the chart shows. Hidden items can't be
  gone to. The Indicators group is a `studiesHidden` settings field of its own
  rather than a `hiddenGroups` key, because a tab on an older build saves
  `hiddenGroups` whole and would drop a key it does not know, while the server
  keeps a top-level field a save leaves out. While it is hidden no study draws, each keeps its own setting for when the group shows
  again, and the studies in the toolbar's Indicators menu read off beside an
  **Indicators hidden · Show** chip. Turning one study on (Indicators menu,
  chart menu or panel) shows the group again, so
  the studies that were on come back with it. **Auto levels** (C2.3) sits
  between Drawings and Journal: it hides the automatic levels on every chart
  (an `autoLevelsHidden` field of its own, for the same reason) and lists any
  levels the main symbol is missing and why. Options join when their layer
  exists (C4.4).
- **Automatic levels (C2.3).** Every chart draws the
  [automatic levels](#automatic-levels-c21) of its symbol behind the candles,
  dimmer than the user's own: a lone level as a thin dotted line, a confluence
  zone as a shaded band, named at the left on the main chart (three names at
  most, then "+2"). Only the nearest three zones above and below the latest
  price show, plus any price is inside; they follow the price as it streams.
  Hovering one (not on the user's own level or drawing) opens its card beside
  the pointer in that chart only; linked crosshairs never open cards in other
  charts. The card shows the members, each with its price, what it is, whether
  it is observed, calculated or inferred, its source and when it formed, the number
  of landmarks, and how price met the visible zone on closed candles: approaches,
  contacts/departures and directional closes, confirmed at candle end. It names
  the session, history start and last closed candle instead of claiming where
  the live price is now. A tap, or a click, keeps the card open until the next tap or its
  **Close**, or that chart changes symbol, interval or session. A daily or weekly
  chart draws the same levels; its card says interactions are read on intraday
  charts. The levels arrive with each 15-second workspace refresh; nothing here
  reads a provider.
- Fill arrows describe buy/sell execution and instrument type. Option premiums
  never become an underlying stock price. Recent fills link to their records.
- **Layouts** (toolbar button) saves the current arrangement under a name, such
  as "0DTE SPY" (1m | 5m | 15m ...) or "Names" (the traded name beside SPY and QQQ),
  and switches to it in one click or tap. A layout is the chart mode (five
  charts or one), the five intervals, the symbols panels hold, the phone's
  small-chart height, the dividers' proportions (C7.4) and linked time ranges.
  The proportions are kept beside the saved list, by layout id
  (`layoutProportions`), not inside it: a tab on an older build rebuilds each
  layout from the keys it knows and saves the list whole, while the server
  keeps a top-level field a save leaves out. A layout saved before C7.4 opens
  at the proportion of its S/M/L size, and a layout's proportions go when it
  is deleted. The main symbol, levels, watchlist, session
  and indicators belong to the workspace, so switching never moves them. The
  button shows the layout the panels are arranged as right now; after a panel
  is edited or a divider moved no layout is in use until one is replaced with **Update**. Rows
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
  candle hover legend says **SIP** or **Tradier**. Today's forming bars and
  the live stream remain Tradier; daily/weekly bars remain Tradier and page
  back through the symbol's whole daily history (see Daily and weekly depth).
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
- **Full screen** is the same workspace over the app navigation and the Gmail
  banner, with an **Exit** button in the toolbar (on a phone a highlighted
  close button); Escape also exits, after it has closed a menu, put a tool
  away or dropped a selection and restored a maximized chart. It keeps its
  own choice of dock, closed until asked for, on each device since C7.4 (a
  device without one starts from the `immersiveWatchlist` setting C7.3
  shared, which stays in the settings for older tabs). On a phone the main
  chart fills the screen under the toolbar and the smaller charts scroll
  below it.
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

`backend/app/engine/chart_feed.py` loads today's candles (15-second TTL), a
ten-day daily tail (60-second TTL) joined to the whole daily series that
`chart_daily.py` reads once per symbol per New York date, and a single batch of
watchlist quotes (15-second TTL).
All five panels share these reads. A lock coalesces concurrent misses; a bounded
96-entry cache and a 60-request/minute chart budget leave headroom under
Tradier's 120/min token allowance. A visible five-chart workspace on one stable
symbol normally uses about nine upstream requests per minute after its
three-request first load; with SPY and QQQ held by panels it uses about 19
(their automatic levels read each held symbol's daily bars once a minute, as a
daily panel would), and a second tab with the same layout adds none.
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
15 minutes. Alpaca answers a symbol or day without a single minute (an index
such as SPX, or a stock before it listed; seen 2026-10-03) with `"bars": null`;
that is reported as *Alpaca has no minute bars for SPX on 2026-10-02* and not
stored, so scroll-back never walks an index's empty days back to 2016. The frontend keeps at most 12,000 normalized candles per panel,
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
fallback mixes IEX or unofficial quotes into these charts. A failed refresh may
retain last-known bars with their original fetch timestamps and an explicit
warning. Missing credentials/data produces an empty setup state, never sample
prices. Sandbox data is labeled delayed. Last-trade age is displayed separately
from refresh time; a successful HTTP call is not proof that a quote is fresh.

### Daily and weekly depth (C0.7)

A 1D or 1W chart scrolls back through everything Tradier holds for the symbol
(SPY: 7,999 daily bars from 1994-12-16), loading older pages as the view nears
the left edge, exactly like intraday pages.

- **One series per symbol per New York date.** `backend/app/engine/chart_daily.py`
  reads `/v1/markets/history` (daily, start 1970-01-01, end yesterday) once,
  through the chart feed so it shares Tradier's 60/minute budget and cooldown,
  and keeps the adjusted bars in a memory LRU of 8 symbols (about 3 MB each).
  There is deliberately no disk copy: the provider rewrites adjusted history
  after every split. A new date, or a new split set, reads once more. Paging
  ten years costs no further Tradier calls. Daily bars are never built from
  minutes, Alpaca or Tradier's weekly interval.
- **Pages are slices.** Indicators are computed over the whole series
  (`chart_bars`, about 9 ms for 1D and 14 ms for 1W over SPY's 7,972 bars,
  measured 2026-10-01) and a page is `chart_math.daily_page`'s slice of the result,
  so there are no warmup prefixes and page seams cannot disagree. Weekly bars
  are the Monday-dated resample of the whole daily series, sliced whole, never
  resampled from a daily slice. EMA-200 is null for the first 199 bars.
- **A split effective today in raw provider bars.** The series ends yesterday and
  cannot show the split, so the tail settles it: if the tail's bars still jump by
  the ratio, the whole series is re-scaled before the join, and history pages
  read the tail the same way, so a page and the workspace never disagree.
- **Workspace join.** The 1D/1W panels join a ten-day tail (60-second TTL) to
  the series by date, the tail winning where they overlap (today's forming bar),
  then return the last 1,200 bars. The workspace tail and the first history page
  therefore agree on every shared completed bar, indicators included. If the
  series cannot be read, the daily panels are empty with a warning, never a
  ten-day chart standing in for the history; intraday panels still load.
- **API.** `GET /charts/history?interval=1D|1W` takes `before` (exclusive candle
  start) and `limit` (at most 1,200); `session` is accepted and ignored.
  `continuation` is always null and `warmup` always `ready`. `exhausted` is true
  only for the page holding the first bar (its `older_cursor` is then null) and
  `history_start` is the date of the earliest Tradier bar, not the listing date
  (SPY listed in 1993). Failures are 503 with `rate_limited`, `access_denied` or
  `provider_unavailable` and are never reported as exhausted. Every response
  carries the C0.6 `price_basis` and `adjustment`.
- **Browser.** An exhausted daily or weekly panel says `Tradier daily history
  starts {date}` in its status row. The gap detector asks for missing history
  across steps over 5 days (intraday), 10 (1D) or 21 (1W).
- **Live evidence.** 2026-10-01, production Tradier account: SPY daily from
  1970 returned 7,999 rows (1994-12-16 to 2026-09-30, 775 KB, 0.45 s); NVDA
  2024-06-05 to 06-12 showed split-adjusted prices and volume; CRWV returned 379
  rows from its 2025-03-28 listing.

### Price basis (C0.6)

Every chart is on one basis: **split-adjusted**. Prices before a split's
ex-date are divided by its ratio and volume is multiplied by it, so a 10-for-1
split (NVDA, ex-date 2024-06-10) leaves no cliff and EMAs, VWAP, volume, saved
levels and journal arrows agree across minute, daily and weekly charts. There
is no raw toggle: the stored bars stay raw, and a one-line chip in the toolbar
(`Split-adjusted · 1 split`, hover for each split and its source) states the
basis. Dividends are **not** adjusted, and the hover text says so.

- **Where splits come from.** `backend/app/engine/chart_splits.py` reads
  Alpaca's corporate-actions endpoint (`/v1/corporate-actions`, forward and
  reverse splits from 2016, ratio = `new_rate / old_rate`), one call per symbol
  per New York date, cached in `backend/data/chart_splits/v1/alpaca/{symbol}.json`
  with the fetch time. These calls sit apart from the 30-attempt history
  budget. A split applies from its ex-date; announced future splits wait.
  A failed refresh keeps the last copy (`stale`); with no copy the symbol is
  `unknown`. An unknown symbol shows raw prices as supplied, an amber chip and
  a banner saying a split would appear as a cliff. A split is never inferred.
- **Display layer.** `backend/app/engine/chart_adjust.py` (pure) adjusts copies of
  bars. Minute sessions are adjusted before resampling and indicators, per New
  York date, so a page's EMAs, RSI and VWAP are computed on adjusted prices. The
  Alpaca session cache is untouched (`adjustment: raw`) and is not keyed by
  basis. Fills and P&L never pass through it; arrow positions are timestamps,
  so they cannot move.
- **Tradier daily/weekly.** Tradier's daily bars were observed already
  split-adjusted (NVDA, checked 2026-10-01). Each recorded split is still
  verified against the bars: if the close-to-open jump across the ex-date is
  still about the ratio, the bars are adjusted here (`adjusted_here`);
  otherwise the provider's adjustment is kept (`provider_adjusted`); a split
  with no bar after it is `unverified` and warned about. Weekly bars are built
  from the adjusted daily bars.
- **Possible unrecorded splits.** A close-to-open jump within 4% of a common
  split ratio, in a symbol with no matching record, adds a warning with its
  dates (in the panel's status line for older pages, so the page does not
  shift). Prices are never changed on that evidence.
- **Saved levels.** A level stores the price the user saw and the New York
  date it was drawn (`drawn_on`). On the adjusted basis it is shown at
  `price / (product of ratios of splits after drawn_on)`, the same factor the
  candles got, and the side list shows `was $…` when it moved. Levels drawn
  after the split are unchanged. Levels saved before C0.6 have no date and are
  shown as saved. A split never rewrites the saved record; dragging a level
  (C1.1) saves the price it was dropped at, on today's basis, with today's date.
- **A split recorded while a tab is open.** Older pages loaded before it are on
  the old basis, so once a refresh brings the new split set they are dropped
  and scrolling back rereads them adjusted. A history page whose split set
  differs from the candles on screen is refused (with a retry), never merged.
  A damaged split cache file is refetched, not trusted.
- **Not covered.** Dividends, spin-offs and stock dividends; options and SPX.
- **Live evidence.** `scripts/check_chart_splits.py` is the read-only probe.
  2026-10-01 20:05 ET, NVDA 10-for-1 (ex-date 2024-06-10), Alpaca corporate
  actions and SIP, Tradier daily: the 2024-06-07 final minute close of 1,208.65
  adjusted to 120.865 against Alpaca's split-adjusted daily close of 120.89 and
  Tradier's 120.88; the ex-date session needed no adjustment (121.65 minute,
  121.79 daily on both providers).

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

### Option chains (C4.1)

`backend/app/engine/options_chain.py` is the Tradier option chain adapter.
The recorder (C4.3) and the chart's option feed (C4.4, C4.5, T2.1) call it. It
turns `/v1/markets/options/expirations` (every root included, so SPXW dates
appear) and `/v1/markets/options/chains` (one request per expiration, with
greeks) into the provider-independent `OptionChain` and `OptionContract` of
`backend/app/engine/options_models.py`, a pure module. Nothing outside the
Tradier adapters names a Tradier option field.

- **Roots stay apart.** One SPX date can list SPX (AM-settled) and SPXW
  (PM-settled) contracts at the same strikes: 1,060 and 938 on 2026-10-16. Every
  contract keeps its root, and nothing that aggregates may merge them.
- **Observed values only.** Bid/ask/sizes, last, volume, open interest, IV and
  greeks are the provider's. Tradier's "never traded" trade time of 0 and its
  uncomputed IV of 0 become unavailable; real zeros (no open interest, no
  volume, a zero bid) stay zero. A missing contract size stays unknown rather
  than assumed to be 100.
- **As-of times.** Bid, ask and trade times are provider event times in UTC.
  The greeks' `updated_at` is kept verbatim because Tradier does not document
  its time zone (recorded values, `2026-10-01 20:00:06` after a 16:00 New York
  close, read as UTC). Open interest is OCC's overnight figure. `fetched_at` is
  this process's capture time, not a provider as-of.
- **Whole chains or nothing.** A row whose strike, side, expiration or root
  disagrees with its OCC symbol or the request, or a contract listed twice,
  makes the chain `malformed`: a chain missing strikes would misstate
  positioning. A date with nothing listed is an empty chain.
- **Budget.** Option reads share 30 requests per rolling minute in one API
  process, separate from the chart feed's 60. Each request takes a slot whether
  or not it succeeds, nothing is retried, and a 429 or an access refusal pauses
  option reads for a minute. A background caller passes `wait=True` to sleep
  for a slot; any other caller is refused at once with `rate_limited`.

### Options snapshots (C4.3)

`backend/app/engine/options_recorder.py` keeps, once per trading session, the
open interest and volume of every contract in each in-scope underlying's
expirations within 45 days. Scope: SPY, QQQ and SPX; the underlyings of open
positions (Webull is dormant and left out; an SPXW root counts as SPX); the
first ten names of the shared chart watchlist; then the strategy factory's core
universe (`CORE_UNIVERSE` in `factory_rules.py`), last so the names traded live
are recorded first if the window runs short. Each name is recorded once, at its
first place in that order. Nothing on the chart reads the snapshots yet.

- **Storage.** One `option_chain_snapshot` row per (session, underlying,
  expiration) holds the capture time, the chain's newest trade time and every
  contract packed as `[root, "C"|"P", strike, open_interest, volume]`, null
  where Tradier gave nothing. A live dry run on 2026-10-01 stored SPY, QQQ
  and SPX (58 expirations, 21,140 contracts) in 522 KB of packed JSON, so the
  scope before the factory's names was roughly 1 MB a day. The 18 factory
  names (added 2026-10-02) add about 200 requests a night; their storage is not
  measured yet. One `option_snapshot_day` row per (session,
  underlying) says `recorded`, `partial` (with what is missing) or
  `unavailable`.
- **Capture window.** From 15 minutes after the regular close (16:15, or 13:15
  after a 13:00 close) to 20:00 New York, so volume covers the whole session;
  other times record nothing. Later is refused because SPX's overnight session
  opens at 20:15: at 21:38 on 2026-10-01, 728 SPX contracts that had traded that
  day showed volume 0. Open interest is OCC's overnight figure for the previous
  close. Holidays and weekends follow the market calendar; without a calendar
  nothing is recorded.
- **Never backfilled.** A snapshot is written only for the session in progress
  and never replaced. A later run marks an open session with no rows at all as
  `unavailable` for the underlyings the session before it held (looking back 31
  days). A day the calendar cannot describe waits for a later run.
- **Resume.** Each expiration commits on its own and every underlying is marked
  `partial` until it finishes. A rerun skips stored expirations and complete
  underlyings, so a complete session costs no request.
- **Budget and schedule.** Reads use the C4.1 adapter with `wait=True` and sleep
  for the 30-per-minute options budget. That dry run made 61 requests for SPY,
  QQQ and SPX (15, 15 and 28 expirations plus a list each) in 121 seconds,
  never more than 30 in a minute; each single name adds about eight, so a full
  run takes several minutes. It is the
  `options_snapshot` job in the sync lane, queued at 16:20 and 19:20 New York on
  weekdays by `tradejournal-options-snapshot.timer` or from the Sync Center.
  When anything in scope is still missing, the job fails with that first, so
  the phone alert names it; what was recorded stays.

### Options positioning (C4.2)

`backend/app/engine/options_positioning.py` is pure: it computes on the
normalized chains it is handed, the underlying's price and a time. For one
root over a set of expirations it gives each strike's call and put open
interest and volume, call and put dollar gamma, and in aggregate the put/call
ratios of open interest and volume and each side's volume over its open
interest (unavailable over a zero). Run on one expiration it is the
per-expiration breakdown.

| Number | Kind | Definition |
|---|---|---|
| Open interest, volume | *observed* | The provider's fields summed per strike; open interest is OCC's overnight figure for the previous close, volume the session's so far. A side with nothing listed is unavailable; a real zero stays zero. |
| Call wall, put wall | *calculated* | The strike with the most call (put) open interest across the chosen expirations; in volume mode, the most traded. A tie goes to the strike nearer the price, then the lower. |
| Rank | *calculated* | A strike's place by the measure; for a card, also its place by each side's open interest and volume. |
| Dollar gamma | *calculated* | Black-Scholes gamma × open interest × shares per contract × S² × 0.01: the change in the shares' dollar delta for a 1% move. Unsigned. |
| Signed gamma | *assumed* | Calls' dollar gamma less puts': dealers taken as long calls and short puts. Open interest does not say who holds a contract. Off unless asked for. |
| Gamma flip | *assumed*, model estimate | Where signed dollar gamma changes sign nearest the price, searched within 5% either way on a 41-point grid and then bisected, each strike's IV and the time held. SPY, QQQ and SPX only. |
| Max pain (C4.7) | *inferred* | For one expiration, the listed strike K minimising what its open contracts would pay at expiry: call open interest × (K − strike) below K plus put open interest × (strike − K) above it, times the contract size. A tie goes to the lower strike; none without open interest. The arithmetic is exact; that price drifts to it is folklore. |

Model assumptions, for every contract alike:

- **Rate and dividends** are zero. Over 45 days at most, a 4% rate moves an
  at-the-money gamma by well under 1%.
- **Time** runs in calendar years (365 days) to the contract's expiry: 16:00
  New York, the calendar's close on an early close (13:00), or 09:30 for an
  AM-settled index root (SPX, NDX, RUT). An expired contract has no gamma;
  its open interest and volume still count for the session.
- **Volatility** is the provider's mid IV, else its smoothed-surface IV
  (ORATS, refreshed hourly, `greeks_updated_at` shown verbatim). The
  provider's own gamma is never used: gamma is recomputed at the chart's
  latest price, which does not make the IV fresher.
- **0DTE.** A same-day contract's gamma grows without bound near its strike
  as the close nears, and ends at expiry. That is the model's behaviour, not
  an error; the card shows when the chains and the IV were read.
- **Missing inputs** (no IV, no open interest, a contract size the provider
  did not give) leave that contract without gamma, counted in `missing`;
  nothing is assumed to be 100 shares.
- **Roots.** One positioning reads one root. SPX's chart reads SPXW (its
  dailies and weeklies); AM-settled SPX contracts and adjusted roots after a
  corporate action (`NVDA1`) are counted in `excluded`, never merged.

### Options levels (C4.4)

Off by default. Layers → Options levels (or the chart menu's Layers) shows it
on every chart, with its filters saved in the shared workspace
(`optionsLayer`):

- **Measure.** *Open interest*: the call and put walls, then the ten strikes
  with the most open interest on both sides together. *Volume*: the volume
  walls ("Call vol wall", "Put vol wall") and the most traded strikes.
  *Gamma*: the open-interest walls and the strikes with the most dollar gamma;
  with **Signed gamma and flip (assumed)** the ranks use net signed gamma and
  SPY, QQQ and SPX add the gamma flip. Each strike appears once; both walls on
  one strike are two members of one zone.
- **Expirations.** *0DTE / nearest*: the next to expire, labelled 0DTE when
  it is today's and "Next expiration … (no 0DTE today)" otherwise. *This
  week*: the nearest one's Monday-to-Friday week (default). *Within 45
  days*: every one. Expired ones are gone from 16:00 (09:30 AM-settled).
- **Strikes each side** (1–5, default 3): the option zones nearest the price
  on each side. Walls, the flip and max pain always draw. Changing it reads nothing.

**Max pain** (C4.7) is computed for the scope's nearest expiration (today's
on SPY and QQQ with *0DTE / nearest*) and draws as an *inferred* level, tinted
orange. Its card names the expiration and says it is a reference, not a
target; like the walls, it holds still through a session. Unknown open interest
or size on a relevant nonzero contract suppresses the calculation rather than
silently dropping that contract; the options footer says why it is unavailable.

The workspace request carries the choice (`options=oi.week.0`: measure,
scope, signed; `auto=0` when the automatic levels are hidden). The backend
adds the strikes to the automatic levels before confluence (C2.2), so a call
wall at the prior day's high is one zone, "PDH + Call wall", whose card shows
both and whose interactions (C2.3) are read like any zone's. Open-interest
strikes hold still through a session; volume and gamma strikes are
`developing` and read "moves during the session". A zone with an option member
is tinted: calls teal, puts rose, other strikes violet, the flip amber.
Hovering or tapping one shows each strike's call and put open interest and
volume with their ranks, its dollar gamma (signed ones say *assumed side*),
its rank by the measure and its distance from the price, then the scope, when
the chains were read, that open interest is the prior close's, the IV stamp,
the price gamma was computed at, and anything missing or left out. A panel
holding its own symbol (C7.1) shows that symbol's nearest expiration only.

Chains come from `backend/app/engine/options_feed.py`, never inside the
workspace request: the workspace reads memory and starts a background refresh
of what is stale, and the page asks again after four seconds while a symbol's
chains are still loading. The scope's expirations must all be in memory
before anything draws ("Loaded 6 of 14 expirations"); a chain read on an
earlier New York date is not used. Cadence per symbol: the nearest three
unexpired expirations at most every 60 seconds, farther ones every 10 minutes,
the expiration list every 30 minutes, at most six chains per pass, nearest
first. The feed takes at most 24 of the options budget's 30 reads a minute
whatever asks (layer, ladder, Forecast), leaving room for the recorder's
catch-up run; a refused read keeps the older copy with its time, and an
access refusal or rate limit stops reads for a minute. A simulated hour of
polling (SPY on 45 days, QQQ and IWM held, ladder and Forecast open) peaks at
19 reads in a minute and settles near 8.

An alert made from an option zone keeps its price like any alert. When that
zone is no longer there (a volume wall moved), its row in the Alerts list
says so and the alert stays where it was.

### Strike ladder (C4.5)

The side dock's third tab (Strike ladder), closed until opened; on a phone
it opens from the More menu (the top row keeps its height for the chart) as a
bottom sheet. It reads `GET /charts/options/{symbol}/ladder?scope=&signed=&spot=`
with the chart's latest price, over the options layer's expirations and gamma
sign (changing them here changes the layer's too), every minute while the page
is visible. It shows 25 strikes each side of the price, which sits between the
strikes around it, and opens scrolled to it inside the panel. Each row: put
volume and put open interest left of the strike, call open interest and volume
right, open interest shaded by its size, and dollar gamma as the bar under the
strike (green and red by sign when signed). The open-interest walls are bold
and named. A click or tap marks the strike on every chart of the symbol as a
solid "Strike …" line and brings it onto the main chart's price scale; a
second click clears it, and charting another symbol drops it. On a phone the
tap also closes the sheet so the chart shows.

### Range bands (C2.7)

Off by default. Layers → Range bands (or the chart menu's Layers) shows them
on every chart, saved in the shared workspace (`rangeBandsHidden`):

- **Expected move.** For the nearest expiration (0DTE on SPY and QQQ) and the
  nearest Friday, the at-the-money straddle's mid (T2.1's rule: the strike
  nearest the price listing both legs; a leg without a bid or ask, crossed,
  or wider than its own mid gives no number) is drawn as "EM 0DTE high/low"
  and "EM Fri high/low": the price at that moment plus and minus the
  straddle. One expiration that is both reads once. It is *calculated* and
  draws blue; its card gives the strike, the straddle's price and percent,
  the IV, when it was priced and the price it was centred on, and says it is
  what the options market charged for a move either way, not a forecast.
- **When.** A band is priced once a New York session, on the first workspace
  request at least five minutes after the calendar's open (09:35 on a normal
  day) with a chain read after that time, all four option bid/ask event times
  known and within the preceding minute, and a live price (today's newest
  minute, no older than two minutes; a layout of daily and weekly charts alone reads no minutes, so it
  prices nothing and reads no chains), and is then fixed for the day:
  nothing more is read for it. After the close the session's bands stay
  drawn and nothing new is priced (today's 0DTE has expired, and later quotes
  are not the session's). Fresh fetches containing stale, missing or future
  quote times cannot freeze a new band. Before 09:35, on a closed day, or with the
  calendar unavailable, nothing draws and the Layers panel says why. A wide
  market is not captured and is tried on the next read. A capture lives in
  the API process's memory, so the first look at a symbol after 09:35, or a
  restart, prices it later; the card's time says when.
- **VWAP bands.** On intraday charts, VWAP ±1σ (dashed) and ±2σ (dotted),
  where σ is the regular session's volume-weighted standard deviation of the
  same minute HLC3 prices VWAP uses (`vwap_sd` on each candle). None outside
  the regular session or on daily and weekly charts.

The workspace request carries `ranges=1` (and `auto=0` when the automatic
levels are hidden). The expected-move levels join the automatic levels before
confluence, so "262 + EM Fri high" is one zone whose interactions are read
and from which an alert can be made; every expected-move level draws while the
switch is on, however far from the price. Chains come through the options feed
and its budget: the nearest and the Friday chain until both are captured, then
none. Panels holding their own symbol (SPY, QQQ) get their own bands.

### Automatic levels (C2.1)

`backend/app/engine/chart_levels.py` computes the session and structure levels
for one New York session from bars it is handed, merges nearby ones into
zones (C2.2) and reads how price has met each zone (C2.3). It is pure (no
provider calls, no database). `compute_levels(day, minutes, daily, as_of,
calendar)` returns the levels known at `as_of`, the daily ATR(14) and, by
group, why any are missing. Only bars complete by `as_of` count.

| Level | Label | Definition | Formed at |
|---|---|---|---|
| Prior day high, low, close | PDH, PDL, PDC | The last daily bar before the session (`indicators.get_previous_day_data`, as fill context uses) | That session's close (13:00 on a half day) |
| Prior week high, low | PWH, PWL | Highest high and lowest low of the previous Monday–Friday week's daily bars | That week's last close |
| Premarket high, low | PMH, PML | 04:00–09:30 minutes (`indicators.analyze_minute_bars`, as fill context uses) | 09:30; shown as developing before |
| Overnight high, low | ONH, ONL | The previous session's postmarket (from its close, 13:00 after a half day, to four hours later) and this session's premarket, from the calendar | The regular open; shown as developing before |
| 5- and 15-minute opening ranges | OR5 high/low, OR15 high/low | 09:30–09:35 and 09:30–09:45 minutes (`analyze_minute_bars`) | 09:35 and 09:45; absent until then |
| Swing highs and lows | Swing high/low | Daily pivots in the last 60 completed sessions: a high above the two sessions before it and at least as high as the two after (equal highs mark the first); lows mirrored | Close of the second session after it |
| Round numbers | 600, 21,500 | Multiples of 1 or 5 × 10^k, whichever is nearest by ratio to 1% of the last completed close (SPY near 660 steps by 5, NVDA near 180 by 1); three at or below it and three above | — |

- **Same as fill context.** The premarket range, opening ranges and prior day
  call the fill-context functions, so on the same bars the chart and a fill's
  stored context agree. Those definitions are clock hours: on a day the
  calendar opens at another time they are listed as missing, not shifted.
- **What each level carries.** Kind, label, price, `evidence` (*observed* for
  the prior day's provider fields, *calculated* for ranges and round numbers,
  *inferred* for swings), the bars' `timeframe` (`1m` or `1D`), the `source` of
  the bar that set it (`tradier` or `alpaca_sip`), that bar's start
  (`bar_time`), `formed_at`, and `developing` while its window is still open.
  One bar can set several levels (a premarket high is often the overnight
  high); `bar_time` lets confluence count it once. Round numbers have no bar,
  source or formation time.
- **Missing stays missing.** A session the calendar (or, without one, the clock)
  says traded but that has no daily bar removes what depends on it: the prior
  day and swings when it is the latest session, the prior week when it falls
  in that week. Nothing older is relabeled as "prior". Without the calendar a
  holiday therefore reads as a missing bar.
  The overnight range needs the previous session's minutes loaded, since an
  absent postmarket cannot be told from a quiet one. A closed day has no
  session levels; its prior-day, prior-week and swing levels remain.

**The band.** A tenth of prior daily ATR(14) scales the maximum zone width
and a separate proximity buffer. Neither pads an actual contact or crossing.
Under 15 daily bars, or with a missing trading session anywhere in the daily
tail, ATR is unavailable: exact-price levels still merge but no interactions
are read. Interior gaps also suppress swings, with missing-input reasons.
The workspace resolves calendar months across the ordinary daily tail so known
holidays are not mistaken for missing trading sessions. Calendar reads are
capped at 150 days: sparse/stale symbols do not fetch years of calendars;
older unresolved dates use the existing clock fallback.

**Confluence zones (C2.2).** Nearest-pair complete-link clustering merges
adjacent clusters by their smallest combined span, ties to the lower cluster.
The total span must be strictly less than one band: a chain of individually
close levels cannot create an arbitrarily wide zone. A zone spans its members'
own prices, never padded or rounded, and names members highest first with
repeated names counted. The card counts **landmarks**, not independent evidence
or strength. The retained API `score` counts distinct bar origins (`timeframe`,
`bar_time`), or kind/price rules; aliases from the same bar count once there.
A lone level is a zone of one; its id is its members' kinds and prices.

**Interactions (C2.3).** Closed intraday candles on the session's date count
only after the **latest** confirmation/observation of the current combination.
The card shows `since`; earlier bars are excluded rather than attributed to
bounds that were not yet known. This is a scan of the current confirmed
combination, not a persistent log of earlier versions. Any developing member
makes the combination `developing` with no fixed history. Fixed option levels
start when first observed in this API process; refresh preserves that time,
while restart/new-session/new-scope observation starts again.

The prior close, or first candle's open, initializes the side relative to the
visible bounds. Unknown side does not fabricate contact. Actual candle ranges
must intersect the displayed zone for contact:

- *touched*: contact observed, departure not yet completed.
- *tested*: after contact, a later candle lies wholly outside on the current
  side. The card says **Touched; left above/below**, without claiming reaction
  strength. A retest after a crossing counts too.
- *approached*: an outer-buffer-only visit, pending or followed by departure.
  Approaches are separate from contacts. The card states the nearby bounds,
  one band beyond each visible edge.
- *broken*: a close across the visible zone onto the other side, including a
  gap. The card says **Closed above/below**. A close inside breaks nothing.
- *reclaimed*: a later close back onto the original side, shown as **Returned
  above/below**. It can be downward and implies no bullish diagnosis.

State retains the last crossing/return, else pending contact/proximity, else
the latest departure or no interaction. Events carry `direction`, candle start
`bar_time`, and confirmation `time` at candle **end**. Cards mark times as
confirmed and name regular/extended hours. `at_level` means the last closed
candle intersected the visible zone, not that the live quote is there; the
card displays that candle's close/time. Daily/weekly panels read no interactions.

**Delivery.** `GET /charts/workspace` sends `auto_levels` for the main symbol
and each held symbol (`day`, `as_of`, `atr`, `band`, `zones`, `missing`), and
each intraday panel's `level_events` by zone id. The session is today when it
trades, otherwise the next one. The previous session's minutes come only from
the completed-session cache on disk (`ChartHistory.stored`); until a history
page has stored them, the overnight range is missing for a refresh or two.
Today's minutes and the daily bars are the reads the workspace makes anyway;
a layout without a daily panel now reads the daily bars too, and a failure
there is the levels' to report, not a chart issue. The calendar covers three
weeks back and ten days ahead (months not yet published read as clock hours).

### Relative volume (C2.4)

A candle's RVol is today's cumulative regular-session volume through that
candle over the average cumulative volume through the same minute of day in
the 20 sessions before today. `backend/app/engine/chart_rvol.py` (pure) is fill
context's `indicators.compute_rvol_time_adjusted` evaluated at every minute:
on the same bars a candle's RVol equals the fill-context RVol of a fill at the
end of that candle.

- **What counts.** Volume counts from 09:30 New York by the clock. A session
  counts toward a minute once it has traded at or after 09:30 by then, and a
  minute that fewer than five sessions had reached has no RVol. A half day in
  the window counts its whole session for the minutes after its 13:00 close,
  as fill context does. Only today's regular-session candles have an RVol:
  premarket, postmarket, older sessions (history pages) and daily and weekly
  charts have none. On a day whose regular session opens at another time
  there is none either, since its minutes cannot be compared.
- **Through which minute.** A completed candle counts through its last minute
  (a 5m candle at 10:15 through 10:19). A candle still forming counts through
  the newest minute bar, so its volume so far is set against the baseline so
  far. A candle's RVol therefore changes only while it forms.
- **The baseline.** 390 numbers per symbol per day, one for each minute from
  09:30 through 15:59, over the market calendar's 20 sessions before today.
  They are read from the completed SIP sessions on disk
  (`ChartHistory.volume_profile` reads each file once per process and keeps
  its profile), multiplied by every split from that session up to today, so
  they are on today's basis. Every one of the 20 must be stored: until then
  there is no baseline (`building`, listing what is missing), never one over
  fewer sessions. A session stored empty (the symbol did not trade, for
  example before it listed) stays in the window and adds nothing; with fewer
  than five sessions that traded the state is `insufficient`. Without the
  market calendar it is `unavailable`. A workspace refresh makes no provider
  request for any of this.
- **Storing the sessions.** Charting a symbol stores its sessions as its older
  candles load (C0.0). `backend/app/engine/rvol_history.py` stores them ahead
  of time for every name on the shared chart watchlist: it is the
  `rvol_history` job in the sync lane, queued at 06:00 and 08:40 New York on
  weekdays by `tradejournal-rvol-history.timer` or from the Sync Center. It
  uses the chart history's Alpaca budget in its own process (30 requests a
  minute), sleeps when that is spent, and stops after ten minutes; the next
  run continues. A stored session is never fetched again, so after the first
  run each morning costs one request per name. Sessions are fetched newest
  first. A day Alpaca has no minutes for (an index such as SPX, or a stock
  before it listed) is not stored, so that name has no baseline until it has
  20 sessions; the job notes it and moves on without failing. Refused
  credentials stop it; a session that fails otherwise is named in the job's
  error after the rest are stored, so the phone alert says which.
- **On the chart.** Volume bars keep their up/down color and brighten with
  RVol: faint under 0.5×, as before up to 1.5×, brighter to 2.5× and
  brightest beyond; a candle without RVol keeps the plain shade. The main
  chart's study row reads *RVol 2.6× for 10:17 AM* for the hovered (or latest)
  candle and names the sessions the baseline covers (*RVol vs 20 sessions
  Sep 4 – Oct 1*, or *vs 18 of 20* when two never traded), or says *RVol
  baseline not built yet* or *RVol unavailable* with the reason on hover. A
  regular-session candle of today without a value reads *RVol —*, with why on
  hover. A smaller chart's row is too tight beside its countdown, so there a
  candle with RVol shows *RVol 2.6×* in place of its volume, and the volume,
  candle time and sessions are on hover. Hiding Volume hides RVol too.
- **Delivery.** `GET /charts/workspace` sends `rvol` for the main symbol and
  each held symbol (`state`, `day`, `sessions`, `traded`, `missing`,
  `message`; null on a day without a session), and every intraday candle of
  today carries `rvol`, null where there is none. The forming candle's RVol
  updates with the 15-second refresh, as its volume does; a streamed new
  candle has none until then.

### Earnings (C2.5)

Report dates come from Tradier's corporate calendar through the same cache as
the Events tab ([Symbol info panel](#symbol-info-panel)); the normalizing and
its traps are in the [symbol info roadmap](symbol-info-roadmap.md#data-traps-the-probes-found).

- **Markers.** Every chart marks each report date it has a candle for with a
  violet **E** below the candle: past confirmed reports and the next date
  alike, through every page of older history. A daily or weekly candle holds
  the date. On an intraday chart the date's first candle carries it, because
  the report's time of day (before the open or after the close) is not
  published. An estimated date's marker reads **E?**. A date without a
  candle, such as the next report before its day, has no marker; the badge
  covers it. Earnings markers do not follow the Journal (fills) layer.
- **Badge.** From 14 days before the next report through its day, the main
  chart's header reads *Earnings in 5 d*, *Earnings tomorrow* or *Earnings
  today*, with *· est.* when Tradier's date is an estimate. Days are New York
  calendar days and turn at New York's midnight. The quarter, the date, the
  status and the source are on hover. A smaller chart holding its own symbol
  shows the short form (*E 5 d?*) on its canvas, where its header has no room;
  on a phone the main chart uses the short form too. No upcoming date, or one
  more than 14 days out, shows nothing.
- **Delivery.** `GET /charts/workspace` sends `earnings` for the main symbol
  and each held symbol (`state`: `ready`, `none` for an ETF or index, `loading`
  or `unavailable`; `next`, every past report, `source`, `fetched_at`,
  `message`). It answers from the cache only. Symbols whose copy is missing or
  older than 12 hours, the watchlist's included, are read on a background
  thread in one batched request per ten symbols, so a chart never waits on
  Tradier's fundamentals; the next 15-second refresh carries them.

### Level alerts (C5.1)

An alert watches one price for one symbol and sends a phone message when it
fires, whether or not any chart is open. It fires once; **Re-arm** arms it
again from the current price.

- **Making one.** Right-click (long-press on a phone) a saved level, a
  horizontal ray or an automatic level: *Alert when price touches*, *Alert
  when price crosses*, or *Alert on a 5m close beyond*, with the candle of the
  chart the menu opened on (5m from a daily or weekly chart). The chart's
  newest streamed trade, else its newest candle, else the quote, says which
  side the alert waits on; price exactly at the level is refused. An
  automatic zone's alert watches its edge nearest the price (its middle from
  inside it). The alert keeps its own price: dragging or deleting the level
  leaves it, and a split after the day it was made moves it as it moves a
  saved level. It counts the trades and candles of the chart's session setting
  when it was made: regular hours only, or extended. At most 20 are active,
  on 5 symbols, so their reads stay inside the shared Tradier allowance.
  Trendlines, rectangles and notes take no alert.
- **When it fires.** *Touches*: a trade at the level or beyond it.
  *Crosses*: a trade beyond it by any amount. Both are judged on each trade
  the stream validates, before the browser's one-second coalescing. *Closes
  beyond*: a candle of the chosen interval, closing after the alert was made,
  closes beyond the level. A candle is judged 30 seconds after it closes, on
  the close Tradier's 1-minute bars then hold; a later correction is not
  judged again.
- **No chart open, restarts and outages.** The monitor
  (`backend/app/engine/level_alert_monitor.py`) runs in the API process. While
  any session could trade (04:00–20:00 New York on weekdays) it adds the
  alerted symbols to the one upstream stream's subscription, beside the
  symbols visible charts follow. The stream records when it carried each
  symbol. At least every 20 seconds a sweep reads today's 1-minute bars
  through the chart feed's shared, cached and budgeted request (an open chart
  of the symbol makes the same request) for two cases: closes-beyond alerts,
  and touch or cross alerts over minutes the stream did not carry, such as a
  restart, a reconnect or an outage. A bar's high or low then stands in for
  the trades, and the event says it came from 1-minute bars. A symbol the
  stream carried throughout costs no read, and nothing is read on a closed
  day (weekends and the calendar's holidays), before an alert's session or
  once its last candle has been judged. A minute without trades counts as
  judged. Each alert stores how far it has been judged, so a restart resumes
  where it stopped.
- **Recorded once.** Each firing is one `level_alert_event` row, unique per
  alert and arming. A reconnect, a restart, the sweep and the stream finding
  the same firing, or a second API process can therefore not record a second
  one; an alert removed or re-armed while its firing waited records nothing.
  A firing the database could not save stays in memory and is saved on the
  next pass; its alert is not judged again meanwhile.
- **Delivered at least once.** Delivery is an outbox on that row, separate
  from deduplication. A pass claims a pending event with an update only one
  process can win, sends it through ntfy (the topic in
  `/etc/tradejournal/alerts.env`, which the API now reads) and marks it sent.
  A failure is retried after 30 s, 1, 2, 5 and then every 15 minutes. A claim
  older than two minutes (a crash mid-send) is put back, so the phone may
  then get the same message twice; it never gets none while the server runs.
  An event not delivered within six hours expires rather than arriving that
  late. Without `NTFY_URL` events wait, retried every five minutes, and the
  chart says phone alerts are not set up.
- **The phone message** names the symbol, the level, the price and when:
  *SPY crossed above 581.20*, *Crossed at 581.24 (trade), 10:42:13 AM ET.
  Alert on PDH.* A closes-beyond message names the candle; one noticed more
  than two minutes late says so.
- **On the chart.** A bell at each alert's price, at the pane's right edge just
  below the line, on every chart of the symbol: amber while armed, gray once
  fired. The menu on the level lists its alerts, with *Re-arm* and *Remove*.
  The **Alerts** list in the dock (in the Watchlist sheet on a phone) shows
  every alert for any symbol: what it waits for, when it fired and at what
  price, and whether the phone message was sent, is being retried (the error
  on hover) or expired.
- **Delivery to the browser.** `GET /charts/workspace` carries `alerts`
  (every alert, newest firing first, and `phone`: whether this server can
  send). `GET`, `POST /charts/alerts`, `POST /charts/alerts/{id}/rearm` and
  `DELETE /charts/alerts/{id}` return the same list and wake the monitor.

### Pre-trade capture (C3.4, C3.5)

**Plan trade** records what you are taking and your plan before you enter. It
never recommends a trade and never sends an order.

- **Opening it.** Use the **Plan trade** button in the toolbar (on a phone,
  **Plan** in the main chart's own bar) or **Alt+P**. Alt+P matches the key's position, so
  Option+P works on a Mac. It does nothing while you type in a field, while
  another dialog is open or on a key repeat. A desktop opens a compact sheet
  at the right; a phone opens a bottom sheet.
- **The four actions.** Open; choose **Buy calls**, **Buy puts** or **Buy
  stock** (**More** adds Short stock, Sell calls and Sell puts); tap a
  template, whose full wording stays visible; then **Save plan** or Enter. The
  ticker and account are fixed when the sheet opens and shown at its top.
  Switching the chart's symbol never moves them. **Change** and the account
  menu are the only ways to change them. **Discretionary / no explicit plan**
  is always offered, and so are a short note and optional strike, expiration
  and quantity. Nothing else is required.
- **Setup.** The gear in the sheet holds the default account (or *choose each
  time*) and up to three favorite templates: a setup name and your own
  invalidation or exit wording. Editing a template raises its revision. A
  saved plan keeps the wording it was saved with. A save from a sheet showing
  an older revision is refused instead of being swapped for the new wording.
- **What is frozen.** At the moment of saving, the sheet records the main
  chart's interval, session, visible range, last candle, the shown price with
  its source and staleness, the price basis and splits, and the visible
  levels, drawings and automatic zones. It reads these from what the page
  already holds and makes no market-data request. It also makes a JPEG of the
  main chart's canvas, at most 1600 px wide. Labels drawn over the canvas as
  page elements are not in the image, and the plan says so. A plan whose
  symbol the main chart is not showing gets no snapshot and records why. A
  failed image saves the plan anyway and says *The chart image could not be
  made*. An image that fails to upload waits in the browser for **Retry
  image**; the server accepts only that frozen picture, once.
- **Saved means saved.** Only the server's answer shows *Saved*. Each sheet
  has its own request ID, so a double tap, a retried request or a lost answer
  never makes a second plan. A plan the server turns down keeps the sheet open
  with the reason. A plan that cannot reach the server waits in this browser's
  IndexedDB, audio included, and the sheet locks to that exact request. After
  a reload the strip shows *Not saved* with **Retry**. When the browser cannot
  store it, the sheet says to keep the tab open.
- **The strip.** It sits between the toolbar and the charts and shows the
  newest plan from the last day: ticker, side, setup and wording, and when the
  server received it. Its details show the account, the snapshot, the image,
  the recording and transcript, and later notes. **Did not take trade** keeps
  the plan as a record. The ✕ hides the strip on this device only. A plan sent
  from the outbox shows the device's time as unverified beside the server's.
- **Voice.** Choose the side, then press and hold **Hold to record**. Release
  saves the clip. A short press, the keyboard, or a microphone prompt that
  took the press switches to **Stop & save**. The browser asks for the
  microphone only then. Clips stop at 30 seconds and offer **Save recording**
  or **Discard**. A cancelled press, a hidden tab or a lost device does the
  same. Closing the sheet discards an unsaved clip. A template is optional. A
  denied or missing microphone leaves the click path working.
- **Transcription.** The server saves the whole recording before the plan
  counts. Its receipt time is the plan's time, and a later transcript never
  moves it. A `capture_transcribe` job in the `capture` lane then runs Whisper
  (`base.en`, faster-whisper) on the server. The audio never leaves
  TradeJournal. The strip shows *Recording saved — transcribing*, then the
  literal text, with *No speech was recognized* for an empty result. It
  checks every 3 seconds only while a transcript is pending. A failure or an
  interrupted worker shows the error with **Retry transcript**; nothing
  retries by itself. With `CAPTURE_TRANSCRIBER=off` or the engine missing,
  the plan says *Not transcribed* and plays back. **Correct transcript** and
  **Add a later note** append notes marked *Corrected later* or *Added later*
  beside the original. The plan itself is never edited.
- **Storage.** `trade_capture`, `trade_capture_note`, `capture_template` and
  `capture_profile` are user records, separate from fills and rebuildable
  trades. Audio (WebM, Ogg, MP4 or WAV, checked by their bytes, 1 KB to 3 MB)
  and images (PNG, JPEG or WebP, at most 1.5 MB) live under
  `CAPTURE_STORAGE_DIR`, by default `backend/data/captures`. Each file is
  written and flushed before its row commits. Only the private API serves
  them: `GET /charts/captures/{id}/audio` and `/image`.
- **Routes.** `GET`/`PUT /charts/captures/setup`;
  `POST /charts/captures/templates`; `PUT` and `DELETE
  /charts/captures/templates/{id}`; `GET`/`POST /charts/captures`;
  `POST /charts/captures/voice` (multipart `meta` and `audio`); and
  `POST /charts/captures/{id}/image`, `/not-taken`, `/notes` and `/transcribe`.

Linking a plan to the trade it became, and counting captures (C3.6), are not
built.

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
D and W, stay off in fields, selects, dialogs and the Sync drawer (whose backdrop
must be the topmost element everywhere beside it: each chart is an `isolate`d
stacking context because the chart library gives its pane-resize handle
`z-index: 50`, which otherwise rose above the backdrop's 40), step the watchlist with
Space and Shift+Space from a clicked button while a Tabbed-to button keeps
Space, reset every chart's range and price scales with Alt+R, return each
chart to its latest candle at the same zoom with End (also with linked
ranges), compare the `?` sheet with the exact binding list, and do the same
by touch at 390px. Drawing-layer tests drag a level with the mouse on the 5m
chart and read it at the same price on the 1h chart and in the side list, with
the chart's range unchanged; cancel a drag with Esc; deselect by clicking empty
space; delete with Delete (Backspace with nothing selected deletes nothing);
undo and redo by key and button; reload to the dropped price and date; undo
an add without touching a level another device added meanwhile; and at 390px
check that a finger on an unselected level leaves it, a tap selects it, a
finger then drags it without scrolling the page, and Delete and Undo work by
tap with 24px targets. Those tests read the prices handed to the layer; what
the canvas paints (dash, handle, label) is checked by screenshot review only.
Context-menu tests (C1.3) right-click at a known price and read it in the
menu, copy it to the clipboard, add a level there on all five charts, reset
one chart's range and price scales while another keeps its own, find no price
on the price scale, close by click and Esc, put an armed tool away, move
between rows by arrow key, and hide My levels and Volume through a reload.
On a level they rename it and recolor it inline, drop an unsaved label on Esc,
lock it (a drag then pans and saves nothing) and unlock it from the selection
bar, duplicate and undo, hide it and show it again from the side list's
button and from Layers, and delete and undo it; on drawings they recolor (the
tool's style follows), lock against handle and body drags, hide one and the
Drawings group, show the group again by placing a note, and edit a note's
text inline. At 390px a swipe and a tap open nothing, a held finger opens
the chart menu and a level's menu as bottom sheets with 44px rows and swatches,
a held finger on a selected level opens its menu without moving it, and the
backdrop closes the sheet.
Range-band and max-pain tests turn the range bands on from Layers, read the
expected-move levels on all five charts (one merged with a round number), the
VWAP bands on intraday charts and none on the daily chart, an expected-move
card, the request's `ranges=1` and `auto=0`, the saved switch through a reload
and its menu toggle; and read max pain far below the price among the options
levels with its *inferred* card. Backend tests pin max pain and the VWAP
standard deviation by hand and the capture rule with a fake clock; live chains
at 09:35 are not exercised.
Workspace-shell tests (C7.3) measure the page and the chart grid at 1440×900
and 1920×1080 with the dock open and closed (no page scrolling, all five
charts in view, and with the dock closed a grid at least 80% of the window's
height and 90% of its width) and save screenshots; at 1280×720 five charts
fit, taller smaller charts keep the main chart at its minimum and scroll the
grid instead of the page, and Focus fills it; with Gmail disconnected the
Reconnect banner stays above the toolbar and the page still does not scroll
(the measurements pin the Gmail state, because the e2e backend has no Gmail
and reports it disconnected). They expand, collapse and
reload the navigation rail, close and switch the dock, resize the window and
enter full screen while a level is selected and the main chart is scrolled
back, checking the same five chart instances, selection, range and stream
and no requests beyond the 15-second refresh, then move the quote with a
streamed trade and drag the level. At 1024px the toolbar does not overflow,
the Indicators menu keeps pressed states and Escape closes it before an
armed tool, and Tab runs toolbar, tool rail, charts, dock. At 390px every
toolbar button is at least 44px, nothing scrolls sideways, the More menu holds
the secondary controls and the attribution, and the watchlist sheet (44px
targets) overlays the chart without shrinking it and closes by Esc, backdrop
or charting a symbol. Measurements are of the stubbed fixture, not a live
session.
Divider tests (C7.4), at 1440×900 against the stubbed fixture: the default
smaller row is C7.3's 311px; a drag of the main divider moves it by the
dragged pixels and saves the share once; the arrow keys step 2% and 10%,
Home, End and a drag past the end stop at the limits (the main chart never
under 320px), and Enter, a double-click and **Reset chart sizes** reset;
Escape mid-drag restores the sizes and saves nothing, and End and Enter on a
divider move neither the charts' view nor a typed interval. The column
dividers move only their two charts and stop at 160px; the dock's edge stops
at 200 and 480px, keeps the grid at least 640px wide, survives a reload and
never reaches the server. During a twenty-step drag of each divider no chart
renders and nothing is saved; on release one save follows (none for the
dock), with the same five chart instances, the same stream and no requests
beyond the 15-second refresh. Each of the five charts is maximized and
restored while the main chart and Panel 2 are scrolled back and a level is
selected: it covers the grid, the others are hidden, and afterwards every
box is within a pixel and every visible range is the same; it takes a
streamed trade, survives a symbol, interval and dock change, ends on a
layout switch, Focus and making it the main chart, and Escape drops the
selection, then restores it, then leaves full screen. Shrinking a 1920×1080
window with dragged dividers to 1280×720, 1024×768 and 1100×600 keeps both
minimums, the page unscrolled and the saved shares untouched; with the
navigation expanded at 1024×768 the smaller row keeps 160px charts and
scrolls sideways inside the grid; and growing the window back gives the same
boxes. Layouts saved before C7.4 open within 8px of their
S/M/L height, unusable or orphaned layout proportions are dropped, the saved
list keeps exactly C7.2's keys, and seven kinds of malformed proportions
(strings, null, out-of-range shares, three columns, zero and lopsided
columns) load as the nearest proportions the dividers could make, with no
page error. Two browsers on the e2e server share the proportions but not the
dock's width, a save refused as stale keeps the other browser's interval and
this one's divider, a save without the new fields (as an older build makes)
leaves them on the server, and a layout an older tab deletes loses its
proportions on the next save. At 390px there are no dividers, S/M/L stays in
the More menu, and Maximize shows one 410px chart (the screen in full
screen) and restores the others at their heights.
Layers-panel tests (C1.4) hide My levels and Drawings from the panel and read
them gone on all five charts, still gone (panel still open) after a reload,
and back; hide and show one level; lock all as one undo step and lock one;
go to a level above every candle (the price scale widens to it) and to a
trend line scrolled away (its bars come back into view), both selected; hide
the Indicators group (the RSI pane and EMA legend go, the chips read off,
each study's own setting is kept) and show it again by turning on one study;
hide the Journal; cancel and confirm delete all, then undo it in order; and
fold a group and close the panel for good. A drawing two pages older than
the loaded 5m candles is reached through the history stub. At 390px the
panel is a full-width bottom sheet whose every button is 44px tall; it hides
a group, goes to an item (closing the sheet, item selected) and closes from
its backdrop.
A canvas comparison checks that VWAP does not paint across an
extended-hours gap while still drawing within the regular session.
`backend/tests/test_chart_splits.py` pins the basis: a NVDA-shaped split gives
matching minute, daily and weekly prices whether Tradier's daily bars are
adjusted or raw, the raw cache stays raw, a missing or stale split source
warns, a split-like jump with no record only warns, and the provider request
and daily refresh are fixtured. The browser suite checks the basis chip, a
level drawn before a split moving with it, new levels recording their date, and
the missing-split banner.
`backend/tests/test_chart_stream.py` checks session buckets, invalid event
filters, and a single upstream subscription shared across tabs.
`backend/tests/test_chart_levels.py` pins every automatic level on fixture
bars: a DST Monday (Friday's postmarket in EST, Monday's premarket and opening
ranges in EDT, read in UTC), the session after a 13:00 half day and the half
day itself across Thanksgiving, a late open, a closed day, developing and
still-forming bars, missing daily and minute bars, swing confirmation and
lookback, and round-number spacing. It also feeds the same bars to the
fill-context functions at four fill times and checks that the chart's
premarket, opening-range and prior-day levels equal them. Confluence tests
cover bounded clustering, threshold edges, order invariance and shared origins.
Interactions pin visible contacts, near misses, unknown-side gaps, one event
per departure, candle-end confirmation and latest-member formation. Daily-tail
tests cover interior missing sessions and known holidays. A workspace test checks the levels, the
stored previous session and each panel's interactions in the response.
Browser tests (C2.3) stub the response: every chart draws exactly the nearest
three zones each side, hovering a zone on the 5m chart reads its card (members,
sources, evidence, formation, landmark count, approach/contact/cross direction,
confirmation times, history start and session), a daily chart's card defers interactions to intraday charts, moving
off closes it, the Layers group lists what is missing, hides the levels on all
five charts through a reload, and the chart menu shows them again. A card
kept open by a click gives way to hovering once a symbol switch removes its
level. At 390px a tap opens a card that stays until its 32px Close. What the canvas paints is
checked by screenshot review only.
`backend/tests/test_chart_rvol.py` builds twenty sessions across Labor Day
(one that traded only premarket, one stored empty, one that starts at 09:47
with every third minute missing, one that stops at 13:00) and a morning with
two missing minutes, and checks that every 1m, 5m and 1h candle's RVol equals
`compute_rvol_time_adjusted` for a fill at that candle's end (the forming
candle at the newest minute). It also pins the five-session minimum per minute,
the calendar window, today's regular candles only, the workspace values and
states (ready, building, insufficient, unavailable, a closed day, a late open),
a split inside the window, the profile read once per process and one session
fetched once for the job. `backend/tests/test_rvol_history.py` covers the job's
scope, a rerun that costs nothing, a weekend run, waiting out the budget,
refused credentials, a failed session named after the rest are stored, the
ten-minute stop and resume, a missing calendar and the Sync Center job; the
timer is in `backend/tests/test_deployment.py`. Browser tests (C2.4) stub the
response: the main chart names the sessions and reads the latest candle's RVol,
the volume colors follow each candle's RVol, hovering reads a candle's own value
and *RVol —* with its reason, a 1m smaller chart shows *RVol 1.1×* in place of
its volume without clipping and gives the candle and sessions on hover, a daily
chart shows none, a baseline still building says so and shades nothing, and at
390px the main chart's RVol and sessions wrap into view. What the canvas paints
is checked by screenshot review only.
`backend/tests/test_symbol_info_events.py` runs the normalizers on recorded,
trimmed Tradier responses (`tests/fixtures/tradier/fundamentals_2026-10-04.json`):
CVNA's confirmed and estimated rows for one quarter resolve to the confirmed
date and the leftover estimate never becomes a second report, NVDA's next date
stays *estimated*, conference calls and conferences are not reports, an ETF
has no calendar, no upcoming row gives no date, rows come from one share class,
and dividends and splits read every table shape. It also covers the cache: the
chart never waits, one batched call covers the watchlist, the 12-hour refresh,
the disk copy after a restart, a failure's cooldown with the older copy kept,
10 reads a minute and a missing key, and the Events route's blocks. Browser
tests (C2.5) stub the workspace: an **E** lands on the date's first 5m and 15m
candle and on the daily candle, a 1m session without a report and a symbol
without dates have none, and with a fixed clock the badge is absent 15 days out,
appears at 14, turns *tomorrow* at 23:30 New York though UTC has turned, reads
*today*, and is gone the day after; an estimated date held by a smaller chart
reads *E 10 d?*, and at 390px the short form stays in the header. The Events
tab's browser tests stub its route. The live calendar was read on 2026-10-04 for
twelve watchlist names; what the canvas paints is checked by screenshot review
only.
`backend/tests/test_level_alerts.py` feeds Tradier-shaped trades through the
real stream parser. A touch is not a cross, the crossing trade fires one event
before coalescing, and later trades add none. A restarted monitor and a second
detector record nothing more, and the database refuses a second row for one
arming. A reconnect gap is judged on 1-minute bars while covered minutes are
not, and a covered stream costs no read and saves its progress. A
closes-beyond alert with no browser or stream waits for its candle to be final,
skips one that closed before it was armed, and reads once per minute. Nothing
is read after the session's last candle, on a Saturday or on a calendar
holiday, and a firing the database failed to save is saved on the next pass.
Extended
trades count only for an extended alert. Delivery tests show that a failed send
is retried after its backoff and never lost or repeated once sent, that a stale
claim is put back while a fresh one is left alone, and that without ntfy an
event waits and then expires. The running loop records and sends a streamed
firing at once. The routes create, refuse (at the level, a duplicate, a sixth
symbol, a daily close), re-arm as a new generation and remove. Browser tests
(C5.1) stub the alert routes: a level's menu sets a crossing alert with the
chart's price as the side, bells appear on both charts of the symbol, a fired
alert's bell turns gray and the list reads its time, price and sent message,
Re-arm and Remove call the server. An automatic zone's menu sets a close-beyond
alert on that chart's interval at the zone's near edge and says when phone
alerts are not set up. At 390px the list sits in the Watchlist sheet with
44px buttons. A message reaching a real phone is not covered by any test.
`backend/tests/test_options_positioning.py` pins the C4.2 formulas to
hand-worked numbers: at-the-money Black-Scholes gamma, dollar gamma for a 1%
move, gamma at six hours to the close, expiry at the close, an early close and
an AM-settled root, and a gamma flip whose crossing has a closed form
(√(105 × 95) × e^(−σ²T/2)). It also covers sums across expirations with roots
kept apart, missing values kept missing and counted, ratios over zero, walls
and ties, chart levels for each measure (each strike once, assumed labels for
signed gamma and the flip), the merge of a wall with the prior day's high, and
the three scopes before and after a close. `backend/tests/test_options_feed.py`
drives the feed with a fake chain client and clock: background loading over
polls, a held symbol's single expiration, a refused read served from the older
copy with a cooldown, yesterday's chains not used, the ladder centred on the
price, the straddle choice and its refusals, the earnings expiration, and an
hour of polling that never exceeds 30 reads in a minute.
`backend/tests/test_charts.py` shows strikes merging with the automatic levels
in `ChartFeed._levels` (and alone when those are hidden) and the routes'
validation. Browser tests stub the chains: the layer's every filter, the
request it makes, a merged zone's card, signed gamma's flip, hiding the
automatic levels, a reload and the chart menu's toggle; the ladder centred on
the price, a strike marked on all five charts and cleared, its scope and sign
shared with the layer, and at 390px a bottom sheet with 44px rows whose tap
marks the strike and shows the chart; the Forecast tab's rows, its refusal and
the price it sends. A live read on 2026-10-04 (SPY and NVDA, 11 requests)
returned walls, a flip and straddles; intraday behaviour with a moving price is
not covered by a test.
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
three-symbol layout from two tabs to 17 upstream requests a minute without
automatic levels and 19 with them, and
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

`backend/tests/test_options_chain.py` parses recorded production SPY and SPX
expiration and chain responses (2026-10-01, rows verbatim), including SPX and
SPXW at one strike, placeholders, contract sizes, malformed rows and shapes,
the 30-per-minute budget, the pause after a 429 and coded failures, and checks
that no module outside the Tradier adapters names a Tradier option field.
`backend/scripts/check_options_chain.py` reads live chains (read-only, two
requests per symbol); on 2026-10-01 after the close it listed 342 SPY, 602 SPXW
and 160 NVDA contracts for 2026-10-02.
`backend/tests/test_options_recorder.py` covers the scope, packing with roots
and missing values, the capture window (weekend, holiday, during the session,
early close, after 20:00), an unavailable calendar, a restart that fetches only
what was missed, a snapshot another run stored first, partial sessions and
their retry, a refused token, the window closing mid-run, missed sessions
marked unavailable (never on holidays, and only after the recorder first ran),
the real adapter's budget across 63 requests, and the Sync Center job. The
timer and its automation are in `backend/tests/test_deployment.py`. The live
dry run above (after hours, its clock pinned to 16:30, into a throwaway
database) recorded all three fixed underlyings completely; the first scheduled
run after deployment is the production evidence.

Live-provider probes establish actual Tradier access; stubbed browser tests do
not. Neither establishes full TradingView parity. This version has no Pine
runtime, raw tick tape, fibonacci or other geometry tools, replay, volume profile
or server-side chart alerts. The existing
TradingView-to-Signals loop still runs separately. Keep TradingView while
comparing the required indicators and sessions side by side.
