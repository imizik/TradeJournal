# Charts epic: roadmap

**The goal: replace TradingView.** This app becomes the user's primary charting
environment for stocks and ETFs. The chart has to be as good to use as
TradingView's, with this journal's own knowledge drawn on and beside it. Not a
chart embedded in a journal, and not a companion to keep beside TradingView. Every
item below is judged by whether it moves the user closer to never opening
TradingView for normal chart work.

**What this is.** The working plan for that goal. Codex and Claude both work
from this file. It owns priorities, dependencies and acceptance criteria.
`docs/charts-workspace.md` describes what is built today. C0.0's focused
implementation contract is [charts-deep-history.md](charts-deep-history.md).
That contract supplies C0.0's detail; do not maintain a competing task list there.

**Two layers, kept independent.** Rendering uses normalized candles and source
metadata, never provider response shapes. Market data (Tradier, Alpaca, our own
stored bars, and any future provider) is normalized in the backend before
anything draws it. Drawings,
indicators and levels work on normalized bars only.

**Scope.** Chart UX first. Market intelligence (levels, options positioning,
your own trades) belongs here only where it appears **on or beside the chart**.
Journal analytics pages, options-flow feeds and AI move explanations are listed
under [Later](#later-not-this-epic) and stay out of scope until this epic's core
phases have shipped.

**Last reviewed:** 2026-09-30 against `origin/main` at `8fe2141` (PR #87).
The implementation-readiness review moved everyday chart workflows earlier
and clarified data correctness. The status board distinguishes shipped work
from planned work.

## How to work from this file

1. Take the first item in the [status board](#status-board) whose status is
   `next`. Board order is execution order; phase numbers and IDs are stable
   topic labels, not the build sequence. Do not skip ahead unless the user asks.
2. One pull request per item ID. Keep the scope inside that item's
   **Done when** list. When something extra looks worth doing, add it to the
   board as a new row instead of building it.
3. Every interaction needs a browser test in `frontend/e2e/charts.spec.ts` (or
   a new spec next to it), and every pure calculation needs a backend test.
   Frontend rendering and live Tradier data are the known gaps; say so in the
   PR, as `docs/agent/verification.md` requires.
4. In the same PR, update that item's row on the board (`done`, the PR number)
   and mark the next item `next`. Update `docs/charts-workspace.md` when behavior
   changes.
5. Follow the [rules](#rules-every-item-follows). They exist because a trader
   will act on what the chart shows.
6. Read the item's dependencies and any linked implementation contract before
   coding. Start a fresh branch from current `origin/main`, preserve concurrent
   work, and keep provider probes separate from fixture tests. Planning changes
   do not mark features done. A completed implementation row links its PR;
   deployment evidence must say whether that PR actually reached production.
7. Use the same requirements with any implementing model. Scope, fixtures and
   acceptance evidence carry the handoff; a model change is not a reason to
   redesign the epic. Stop after the selected item, not after the whole board.

## Status board

| ID | Item | Phase | Status |
|---|---|---|---|
| C0.0 | Deep history: years of stitched minute history, stored locally, loaded as you scroll back | 0 Foundations | done ([PR #89](https://github.com/imizik/TradeJournal/pull/89)) |
| C0.1 | Market calendar: holidays and early closes in the countdown and session logic | 0 Foundations | done ([PR #90](https://github.com/imizik/TradeJournal/pull/90)) |
| C0.2 | Hot path: stop the whole workspace re-rendering every second and every tick | 0 Foundations | done ([PR #91](https://github.com/imizik/TradeJournal/pull/91)) |
| C0.3 | Keep chart instances across symbol and interval switches | 0 Foundations | done ([PR #92](https://github.com/imizik/TradeJournal/pull/92)) |
| C0.4 | Workspace saved on the server, so phone and desktop share levels and layout | 0 Foundations | done ([PR #93](https://github.com/imizik/TradeJournal/pull/93)) |
| C7.1 | Per-panel symbol linking (for example SPY, QQQ and the traded name) | 7 Layouts | done ([PR #95](https://github.com/imizik/TradeJournal/pull/95)) |
| C7.2 | Named saved layouts | 7 Layouts | done ([PR #98](https://github.com/imizik/TradeJournal/pull/98)) |
| C0.5 | Hotkeys: timeframe keys, next/previous symbol, reset scale, back to realtime, `?` help | 0 Foundations | next |
| C0.6 | Explicit, consistent price basis across stock splits and chart intervals | 0 Foundations | done ([PR #101](https://github.com/imizik/TradeJournal/pull/101)) |
| C0.7 | Daily/weekly history pagination beyond the current three-year window | 0 Foundations | todo |
| C4.1 | Options chain adapter and normalized models (Tradier) | 4 Options on the chart | todo |
| C4.3 | Positioning recorder: one daily snapshot, kept | 4 Options on the chart | todo |
| C1.1 | Drawing layer: select, drag, delete, undo/redo; levels become draggable objects | 1 Direct manipulation | todo |
| C1.2 | Tools: horizontal ray, trendline, rectangle zone, text note; magnet to OHLC | 1 Direct manipulation | todo |
| C1.3 | Right-click (long-press on phone) context menu for chart, level and drawing | 1 Direct manipulation | todo |
| C1.4 | Layers panel: show, hide, lock and delete by group | 1 Direct manipulation | todo |
| C2.1 | Level engine: automatic session and structure levels (backend, pure) | 2 Levels | todo |
| C2.2 | Confluence: merge nearby levels into one labeled zone | 2 Levels | todo |
| C2.3 | Levels layer on the chart with hover card and test history | 2 Levels | todo |
| C2.4 | Time-of-day relative volume on the volume pane and legend | 2 Levels | todo |
| C2.5 | Earnings markers and an "earnings in N days" badge | 2 Levels | todo |
| C5.1 | Level alerts delivered to the phone, drawn on the chart | 5 Alerts | todo |
| C3.3 | Historical chart mode: open any past trade on the chart | 3 Journal on the chart | todo |
| C3.1 | Trade card: click a fill arrow for the trade, its P&L, MFE/MAE and entry context | 3 Journal on the chart | todo |
| C3.2 | Position lines: average entry, exits and open P&L on the chart | 3 Journal on the chart | todo |
| G0 | Daily chart replacement acceptance: real market session, desktop and phone | Gate | todo |
| C4.2 | Positioning engine: OI, volume, walls, gamma concentration | 4 Options on the chart | todo |
| C4.4 | Options levels layer with filters | 4 Options on the chart | todo |
| C4.5 | Strike ladder side panel | 4 Options on the chart | todo |
| C6.1 | Replay: hide the future, step, play | 6 Review | todo |
| C6.2 | Trade / no-trade drills compared with the actual trade | 6 Review | todo |

Why this order: history, correct sessions and smooth updates come first; then
shared state and SPY/QQQ/name layouts. Record options snapshots early because
lost days cannot be recovered, but defer their analytical UI. Drawings precede
automatic overlays, and ordinary alerts precede gamma tools and replay.
Historical trade navigation makes the new history useful before rich trade cards.

Dependencies beyond board order: C7.1 needs C0.2/C0.3; C7.2 needs C0.4/C7.1;
C4.3 needs C4.1/C0.1 and the durable job framework, not C4.2; C2.1 needs C0.1
for session boundaries; C2.4 and C3.3 need C0.0; C5.1 needs C1.3/C2.3 plus
durable alert state; C4.4 needs C2.2/C4.2; C6.1 needs C3.3. G0 precedes
advanced analytics, not every possible future feature.

## Ground truth this plan rests on

### How the user trades (reported journal snapshot, 2026-09-30)

The counts below were recorded in the original roadmap; the documentation
review did not rerun that production audit. They motivate priorities, not a
validated trading edge or a guarantee that enrichment is complete.

- 1,589 trades; **1,519 are options** and 70 are stock. SPY is the most-traded
  underlying (184 trades), followed by a long tail of single names (CVNA, AMD,
  GOOG, COIN, MSFT, SNDK, MU, LLY, NVDA, TSLA …).
- Expiry mix at entry: 0DTE 378, 1–3 days 464, 4–7 days 184, 8–30 days 465.
  Short-dated options dominate, so **intraday levels and SPY/QQQ positioning
  matter more than weekly swing tools**.
- The snapshot reports a higher win rate at the open (53% versus 45% midday).
  Win rate alone does not establish profitability or justify a trading rule.
- No futures are traded or watched (confirmed by the user, 2026-09-30). QQQ,
  SPY and SPX are the index charts. No connected provider carries futures, and
  none is needed. SPY/QQQ are ETFs; SPX is an index. C0.0 covers stocks/ETFs,
  not SPX deep history. Index quote, minute-history and stream support need
  separate verification; never substitute SPY prices while labeling them SPX.
- Webull is dormant by the user's choice (2026-09-24). Leave it out of plans
  until they ask.

### What the chart already does well

One private Tradier WebSocket feeds every tab; a 15-second REST refresh keeps
volume and studies honest. There are five linked charts, a linked crosshair and
optional linked time ranges, and the latest candle updates in place without
losing zoom. Also built: the next-bar countdown with named states, full screen,
Cmd/Ctrl+K search with recent symbols, EMA/VWAP/RSI, extended-hours shading,
fill arrows, saved horizontal levels, and a 390px phone layout with tests. The
data labels disclose source, age, delayed and stale states.

### What feels worse than TradingView

| Area | Today | Why it matters |
|---|---|---|
| History depth | About 10 days of minute bars and at most 1,200 candles per panel; you cannot scroll back further | The first thing that sends you back to TradingView |
| Symbol switch | The chart is destroyed and recreated (`chart.remove()` in `frontend/components/charts/PriceChart.tsx`); the workspace blanks to a loading card until all five intervals return | Switching is TradingView's core loop, and it should never flash |
| Re-renders | A one-second clock and every streamed tick set state at the top of `frontend/components/charts/ChartWorkspace.tsx`, re-rendering all five panels | Headroom disappears as soon as overlays are added |
| Levels | Created by a form or a click in draw mode; they cannot be dragged, edited in place, locked or hidden | Direct manipulation is most of what makes a chart feel like a canvas |
| Drawings | Only horizontal levels exist | Trendlines, zones and notes are the daily tools |
| Undo | None | Every destructive action is permanent |
| Context menu | None | Nothing to right-click or long-press |
| Persistence | `localStorage` only, per browser | Levels drawn on the desktop do not exist on the phone |
| Layout | Every panel follows one symbol | SPY + QQQ + the traded name side by side is impossible |
| Market calendar | Clock-only sessions; a holiday reads as "Waiting for bars" | A wrong closed/open state on a holiday |
| Past trades | Tradier holds about 10 days of minute bars, so older trades cannot be opened on the chart | Review happens on the chart or it does not happen |

### What already exists but the chart does not use

- `FillMarketContext` (`backend/app/models.py`) can hold VWAP and
  distance to it, premarket high/low, 5- and 15-minute opening ranges, prior-day
  high/low/close, gap, time-adjusted relative volume, chase and reclaim flags.
  The chart draws none of these levels. **The level engine (C2.1) must reuse
  these definitions** (`backend/app/engine/indicators.py`). Equality requires
  the same input bars, feed, session, calculation version and as-of time.
  A context row or individual values can be missing; old IEX enrichment does
  not become SIP data when the fetch default changes.
- `TradePathMetrics` can hold MFE/MAE, time to each, exit efficiency,
  post-exit continuation and greeks attribution. Rows and fields can be missing
  or stale; C3.1 must preserve those states when displaying them.
- `compute_rvol_time_adjusted()` in `backend/app/engine/indicators.py` already
  computes relative volume by minute of day for fills. The chart shows raw
  volume (C2.4).
- Alpaca news (Benzinga) is fetched by `backend/app/engine/news.py` for reports,
  but never shown on the chart.
- `deploy/alerts.py` already sends phone notifications through ntfy. Chart
  alerts can reuse it (C5.1).
- `ResearchWorkspace` (`research_workspace` table, one JSON document per slug
  with an optimistic-concurrency revision, served by
  `backend/app/routers/research.py`) is an existing server-side store for
  editable UI state. C0.4 can reuse the pattern without a new table.

### Chart library: stay on Lightweight Charts

`lightweight-charts` 5.2.1 is locked in the frontend. It provides panes, custom
primitives and interactive scales. Prefer **series primitives** for drawings
anchored to candle time/price; pane primitives suit pane-wide decorations.
Selection, handles, touch gestures and undo remain application work, not a
built-in drawing framework or a reliable "few hundred lines" estimate.
See the [official plugin guide](https://tradingview.github.io/lightweight-charts/docs/plugins/intro).

It is the free Apache-2.0 library, not a TradingView website subscription or
Advanced Charts. Keep the existing TradingView link, attribution notice and
license files; see [license and data costs](charts-workspace.md#license-and-data-costs).
**Do not migrate.** Reconsider only if a primitive cannot meet a demonstrated need.

## Data this plan can rely on

The original roadmap records production-account probes on 2026-09-30 after
hours. These are historical observations, not checks repeated by each reader.
Recheck the access a feature needs before shipping; rows marked *unverified*
must not be treated as established capability.

| Data | Tradier | Alpaca (free, IEX) | Polygon (Basic) | Use |
|---|---|---|---|---|
| Live equity trades | WebSocket, consolidated; one session per token (live since #82) | IEX only: one venue, wide quotes | — | Tradier |
| Intraday candles | About 10 days of minutes | IEX live; **historical SIP** back to 2016 (not the latest 15 minutes) | 5 calls/min | Tradier for today and live; Alpaca SIP for every earlier session, stored locally (C0.0) |
| Daily candles | Years; split-adjusted as observed (NVDA, 2026-10-01), checked per split; dividends not adjusted | Yes | Yes, cached for enrichment | Tradier (already) |
| Market calendar | `/v1/markets/calendar`: holidays and early closes (Thanksgiving closed, 11/27 closes 13:00), back to 2016; next year returns HTTP 400 until published | `/v2/calendar` | — | Tradier (C0.1) |
| Option chain | One call per expiration: bid/ask/sizes, last, **volume, open interest**, greeks; about 200 ms. SPY nearest expiry: 638 contracts, OI on 498 | Snapshots on the indicative feed, **no open interest** | EOD only | **Tradier** |
| Expirations | SPY 32, QQQ 30, NVDA 24, SPX 55 (with SPXW); SPY has 14 within 45 days | — | — | Tradier |
| Greeks / IV | ORATS, **hourly**; `updated_at` read 20:00 the previous evening after hours. Gamma is non-zero on only 120 of 638 SPY contracts (far strikes round to 0) | Indicative | — | Tradier IV; **recompute gamma locally** from live spot (C4.2) |
| Open interest history | Current only; OCC publishes once overnight | — | — | **Record our own** (C4.3); it cannot be backfilled |
| Option minute history | `timesales` on an OCC symbol returned `series: null` | Option bars (already used by `trade_path.py`) | — | Alpaca, when ever needed |
| Option trades stream | Streams OCC symbols per docs; whether trade events carry bid/ask is *unverified* | Indicative | — | Later (flow is out of scope) |
| Earnings dates | `/beta/markets/fundamentals/calendars` returns NVDA earnings events; accuracy of upcoming dates *unverified* | — | — | Tradier (C2.5) |
| Macro events (CPI, FOMC, NFP) | — | — | — | None; a hand-kept yearly file if ever wanted |
| News | — | Benzinga, already in `news.py` | — | Alpaca (Later) |
| Futures, Level 2, footprint | — | — | — | **Not available** |

Rate budget, per Tradier token (120 requests/minute, documented and seen in
response headers): the chart feed keeps its 60/minute cap in
`backend/app/engine/chart_feed.py`; options positioning gets at most
**30/minute**; position quotes stay under 10; the rest is headroom. Fetch a whole
expiration once and derive everything from it. Never poll individual strikes.

## Data gaps

What is missing, what it blocks, and the cheapest fix. Check here before
proposing a new provider.

| Gap | Blocks | Cheapest fix | Where |
|---|---|---|---|
| Intraday history beyond about 10 days | Scroll-back, past trades on the chart, relative-volume baseline, replay | Alpaca free historical SIP, stored locally: $0 | C0.0 |
| Open-interest history | Any comparison of positioning over time | Record our own daily snapshots: $0; cannot be backfilled, so start early | C4.3 |
| Session calendar | Correct holiday and early-close states | Tradier market calendar: $0, verified | C0.1 |
| Price adjustment consistency | Reliable multi-year indicators, drawings and cross-interval comparison across splits | Define and test one explicit display basis; keep raw cache provenance | C0.6 |
| Daily/weekly depth beyond the current request | Multi-year daily/weekly navigation | Page existing historical daily data; do not aggregate extended minutes into daily bars | C0.7 |
| SPX index history and live compatibility | Claiming index-chart replacement | Probe index support separately; disclose unsupported coverage | Separate scope decision before including SPX in G0 |
| Upcoming earnings accuracy | Earnings markers | Tradier corporate calendar, checked against company announcements | C2.5 |
| Macro events (CPI, FOMC, NFP) | Event markers | A small hand-kept yearly file | Later |
| Streamed option trades with bid/ask | Options flow | A regular-hours probe of the existing Tradier stream | Later |
| Futures (NQ, ES), footprint, depth of book | Nothing the user needs | Not needed: no futures are traded or watched | Not building |

The stock/ETF plan targets existing free access; no paid upgrade is authorized
or currently identified as necessary. That is not an entitlement guarantee for
unverified feeds or indices. Today's one-symbol chart normally uses about nine
Tradier requests/minute; multi-symbol panels and alerts need new aggregate
budget tests. Alpaca chart history gets a separate conservative budget, with
headroom for journal workers sharing the account.

## Rules every item follows

- **Label what a number is.** Options and level numbers are one of: *observed*
  (a provider field, shown with its timestamp), *calculated* (a formula over
  observed data), *inferred* (a heuristic, such as a wall or a test), or
  *assumed* (for example a dealer-side sign for GEX). The hover card or panel
  says which. An estimate is never shown as a fact.
- **Progressive disclosure.** The default chart is candles, VWAP, the user's
  levels, trade arrows and volume. Everything else is a layer that is off or
  collapsed until asked for: hover shows more, click shows more, and a side
  panel shows the most. A new feature adds one layer or one badge, never a
  permanent block of numbers.
- **Provider data stops at the adapter.** Tradier field names live in
  `backend/app/engine/` adapter modules only. Everything above them uses the
  normalized models. Calculation modules stay pure (no network, no database),
  like `backend/app/engine/chart_math.py`;
  `backend/tests/test_import_boundaries.py` enforces this.
- **The hot path stays lean.** Streamed prices update one series point. No
  calculation over whole arrays inside React render. Each panel subscribes to
  only its own data.
- **Context, not signals.** Nothing on the chart says buy or sell.
- **Navigation uses cached data where available.** Search suggestions, drawing
  edits and layer toggles make no provider calls. Selecting a symbol, interval
  or session, loading an uncached scroll page, or opening a historical trade may
  load data through bounded shared caches. No per-candle or per-strike requests.
- **Mobile is a requirement.** Every interaction has a touch path (long-press
  for the context menu, tap to select, drag handles at least 24px) and a
  390px-wide test.
- **Price basis and missingness are explicit.** Do not mix adjusted and raw
  prices without labeling the distinction, fill absent minutes with invented
  candles, or turn missing/stale journal metrics into zeroes.

## Phases

The sections group related work. Execute in status-board order, which deliberately
pulls layouts, recording and alerts forward without renumbering existing IDs.

### Phase 0 — Foundations (do first)

**C0.0 Deep history (done in PR #89).** The required API, cache,
warmup, pagination, concurrency and test behavior is in
[the C0.0 implementation contract](charts-deep-history.md). In brief:

- **Completed sessions** (every day before today) come from Alpaca historical
  minute bars with `feed=sip` passed explicitly on every request. Production's
  global `ALPACA_DATA_FEED` may be `iex` or may change in concurrent journal
  work; **IEX bars must never reach the chart**. Use a chart-owned SIP/raw cache
  with complete-session metadata; do not change global feed behavior or assume
  that an existing journal cache file proves complete retrieval. A successfully
  completed cached session is reused across reloads and restarts without calls.
- **Today and live** stay on Tradier (REST, then the stream), as now. Alpaca's
  free tier refuses the latest 15 minutes of SIP data anyway.
- **Each session comes from one provider**, never mixed within a day, and every
  bar carries its source so the hover legend can say where it came from.
- **Scroll-back:** when the visible range nears the left edge, the panel asks
  `GET /charts/history` for the previous page (resampled by `chart_math.py` to the
  panel's interval) and prepends it without moving the view. The 1,200-candle cap
  becomes a page size, with a memory ceiling per panel.
- **Indicators on older pages** are computed with a warmup prefix long enough for
  EMA 200 to converge at the panel's resampled interval. The contract defines
  the numerical rule; document implemented behavior in `docs/charts-workspace.md`.
- **Budget:** Alpaca historical calls get their own cap in `chart_feed.py`,
  separate from Tradier's. Backfill must not hold up live reconciliation.
- Daily/weekly provider, depth and adjustment behavior remain as documented
  today; C0.6/C0.7 address those separately. C0.0 explicitly labels raw intraday
  prices and does not claim corporate-action-adjusted parity.

*Done when:*

- A 5m chart scrolls back six months through fixture pages without its visible
  timestamps or zoom changing when history arrives, REST refreshes or ticks run.
  The same navigation works at 390px; eviction and return-to-live are covered.
- A backend test stitches Alpaca fixture days with a Tradier "today" and finds no
  duplicate, missing or overlapping minute at the boundary.
- A test asserts every Alpaca history request carries `feed=sip` and never asks
  for the latest 15 minutes.
- A cached completed session costs zero provider calls on the next load.
- The contract's matrix passes, including page seams, midnight rollover,
  failures, warmup, concurrent misses and stale navigation responses. The
  single stream, countdown states, markers, linked ranges and full screen pass
  regression tests. Report fixture, visual, live-provider and deployment
  observations separately; missing live evidence is not silently called passed.

C2.4's baseline, C3.3 and C6.1 should read history from here instead
of fetching their own.

**C0.1 Market calendar (done in PR #90).** Cache Tradier calendar results by the covered dates,
refresh the current calendar daily, and send today's session hours with the
workspace response. `barClock()` in `frontend/lib/charts.ts`, backend resampling
and stream buckets use the same session definition. Historical pages need the
calendar for their dates as well; avoid a today-only fix that leaves historical
half-day VWAP and bucket ends wrong. Calendar access remains bounded/shared.
*Done when:* a holiday reads "Market closed", an early-close day ends the regular
session at 13:00 and the last bar's countdown respects it, and browser tests
cover both with a fixture calendar. Backend tests cover an older half day and
regular/extended classification; unavailable calendar data is disclosed.

**C0.2 Hot path (done in PR #91).** Move the one-second clock into a small component each
countdown owns. Move streamed ticks into a store outside React (a
`useSyncExternalStore` module such as `frontend/lib/chartStore.ts`) that panels
subscribe to individually. Apply ticks per panel instead of rebuilding every
interval's bar array in `overlayLiveTicks`. *Done when:* a browser test counts
renders and shows a tick re-renders only the panels whose bars changed, and the
clock re-renders no chart.

**C0.3 Keep charts alive (done in PR #92).** Create each chart once per panel. A symbol, interval
or RSI change swaps data and panes in place. While new data loads, keep the old
frame visible, dimmed and labeled "Loading NVDA…". *Done when:* switching symbols
never shows the empty loading card after the first load, and a test proves the
chart instance survives a switch.

**C0.4 Server-saved workspace (done in PR #93).** Save `ChartSettings` (levels, watchlist,
intervals, indicators, layout, drawings once they exist) through a
workspace-style JSON endpoint modeled on `backend/app/routers/research.py`.
Use a revision check and keep `localStorage` as an offline fallback. On first
load, migrate any existing `localStorage` state. *Done when:* a level saved in
one browser context appears in another, and a stale revision is refused rather
than silently overwritten.

**C0.5 Hotkeys.** Numeric interval entry (`1`, `3`, `5`, `15`, `30`) commits on
Enter, so typing `15` does not first select `1m`. `H` (1h), `4` (4h), `D` and `W`
are immediate interval shortcuts; `Space` and `Shift+Space` step through the
watchlist; `Alt+R` resets scales; `End` returns to realtime; `?` shows a cheat sheet. Hotkeys are
ignored while typing in an input. *Done when:* each has a browser test and the
cheat sheet lists exactly the bindings that exist, including numeric entry and
Escape to cancel it. Buttons retain equivalent phone access.

**C0.6 Price basis (done; built as documented in [Price basis](charts-workspace.md#price-basis-c06)).** Establish consistent split handling for supported
stocks/ETFs before calling multi-year charts comparable across intervals. Keep
raw source caches immutable; any adjustment is a versioned display transform
with dated corporate-action evidence. Choose and document the supported basis
(raw and/or split-adjusted), including volume, indicators, drawings and journal
marker coordinates. Do not adjust the journal's actual fills or P&L. Dividend
adjustment remains explicitly labeled if unsupported. Reuse existing corporate
action inputs only after checking their coverage; a missing factor must not be
guessed. *Done when:* a known split fixture shows consistent minute/daily/weekly
prices and markers in the selected basis, saved drawings remain meaningful,
and a missing action produces an explicit limitation. A live split example is
compared and its provider/as-of recorded.

**C0.7 Daily/weekly depth.** Extend the history-page contract to provider daily
bars and weekly resampling without constructing daily bars from extended-hour
minutes. Honor C0.6's price basis and the same memory, warmup and viewport rules.
*Done when:* a fixture daily chart scrolls ten years (or to listing inception)
and weekly page boundaries agree with a continuous reference. New listings and
provider history exhaustion terminate honestly. This work does not expand
C0.0's intraday-only scope.

### Phase 1 — Direct manipulation

**C1.1 Drawing layer.** A series-primitive layer on the candle series renders
drawings and hit-tests the pointer. Selecting a drawing shows its handles; dragging moves it;
`Delete` or `Backspace` removes it; `Cmd/Ctrl+Z` and `Shift+Cmd/Ctrl+Z` undo and
redo. Drawings are anchored to **time and price**, never to pixels or bar index,
so they stay put across zoom, intervals and the five panels. Existing saved
levels become drawings of the kind "horizontal level". *Done when:* drag, delete
and undo work with a mouse and by touch, a level dragged on the 5m chart moves on
the 1h chart, and nothing is lost on reload.

**C1.2 Tools.** Horizontal ray, trendline (with extend left/right), rectangle
zone and text note. Magnet mode (hold `Cmd/Ctrl` or toggle) snaps anchors to the
nearest open, high, low or close. Each tool remembers its last style. *Done when:*
each tool can be drawn, edited and deleted in a browser test, and the magnet
snaps to OHLC in a test with known bars. No fib, pitchfork, Gann or other
geometry tools.

**C1.3 Context menu.** Right-click, or long-press on touch, on empty chart: add
level here, copy price, reset scale, toggle layers. On a level or drawing: edit
label and color inline, lock, hide, duplicate, delete, and (after C5.1) create
alert. *Done when:* both menus work by mouse and by touch.

**C1.4 Layers panel.** A collapsible list grouped as My levels, Drawings, Auto
levels, Options, Journal and Indicators. Each group and item can be hidden,
locked or deleted, and a click jumps the chart to it. *Done when:* hiding a
group hides it on all five panels, the state persists, and the panel works as a
bottom sheet on a phone.

### Phase 2 — Levels that draw themselves

**C2.1 Level engine** (new pure module, for example
`backend/app/engine/chart_levels.py`, fed by the bars `chart_feed.py` already
loads, so no new provider calls). Levels: prior-day high/low/close, premarket
high/low, overnight high/low, 5- and 15-minute opening ranges, prior-week
high/low, round numbers scaled to price, and recent swing highs/lows from daily
bars. Each level carries its type, source, timeframe and the time it formed.
Where `indicators.py` already defines a level for fill context, call that code
rather than re-deriving it. *Done when:* unit tests pin each level on fixture
bars, including a DST day and a half day, and a test proves chart and
fill-context levels agree on the same bars.

**C2.2 Confluence.** Levels closer than a threshold merge into one zone. The
threshold is a fraction of ATR, not a fixed price, so it scales from SPY to
CVNA. The zone is labeled by its members ("PDH + 21,500 + OR15 high") and spans
the members' actual prices, never more precise than they are. The score is the
count of **independent** sources, so two levels derived from the same bar count
once. *Done when:* unit tests cover merging, non-merging and the
independent-source rule.

**C2.3 Levels layer.** Auto levels appear as thin labeled lines, and confluence
zones as shaded bands, behind candles and dimmer than the user's own levels. Only
the nearest few above and below price show by default. Hovering shows the level
card: type, source, when it formed, and how price has **interacted** with it
today:

- *untested*
- *tested*: price came within the tolerance band and moved away
- *broken*: a close beyond the band
- *reclaimed*: broken, then a close back through

Each event is defined on closed bars of the panel's interval with the same
tolerance band, and the definitions are written in `docs/charts-workspace.md`.
*Done when:* a browser test hovers a level and reads its card, and unit tests pin
each interaction event on fixture bars.

**C2.4 Relative volume.** A baseline of average cumulative volume by minute of
day over the last 20 sessions, computed nightly per watchlist symbol from the
deep-history store (C0.0); about 390 numbers per symbol per day. Volume
bars are shaded by relative volume, and the legend reads "RVol 2.6× for 10:17".
Until the baseline exists, say so rather than guessing. *Done when:* the
calculation matches `compute_rvol_time_adjusted()` on the same inputs, and the
chart labels which sessions the baseline covers.

**C2.5 Earnings.** Earnings dates from Tradier's corporate calendar, cached
daily per watchlist symbol. The chart shows a marker on the date and a badge
("Earnings in 3 days"), since earnings drive option IV. Verify the accuracy of
upcoming dates against the company's announcement before shipping, and label the
source. *Done when:* markers render from a fixture, and an unknown date shows
nothing rather than a guess.

### Phase 3 — The journal on the chart

**C3.1 Trade card.** Clicking a fill arrow opens a card for that trade: the
contract, entries and exits, realized or open P&L, MFE/MAE, and exit efficiency
from `TradePathMetrics`. It also shows the entry context from `FillMarketContext`
(VWAP distance, relative volume, chase and reclaim flags, level distances), plus
links to the fill and trade pages. Hovering an arrow shows a one-line summary.
*Done when:* the card renders seeded trade data in a browser test, missing and
stale metrics remain labeled, and option premiums are never drawn as underlying
prices. Expose source/as-of differences rather than claiming old enrichment
must equal today's chart calculation.

**C3.2 Position lines.** Stock positions use their share-weighted average-entry
price on the stock chart. For options, show the contract and premium/P&L in a
card; an optional chart annotation uses the observed **underlying price at the
option entry**, labeled as such and omitted when unavailable. An option premium
is never an underlying entry or break-even line. Partial exits appear as markers.
*Done when:* stock scale-ins/outs and option entries have fixture coverage,
including absent underlying context and stale option marks, with correct units.

**C3.3 Historical chart mode.** "Open on chart" from a trade or fill page opens
`/charts` scrolled to that date and time, with the trade's arrows on its candles.
Candles come from the deep-history store (C0.0). A banner shows the date with a
"Back to live" button.
*Done when:* a trade from months ago opens with its arrows on the right candles,
and no Alpaca IEX (single-venue) bars ever mix into consolidated candles.

### Phase 4 — Options positioning on the chart

**C4.1 Chain adapter.** A Tradier adapter (for example
`backend/app/engine/options_chain.py`) fetches one expiration per call and
returns normalized, provider-independent contracts: underlying, expiration,
strike, call/put, bid, ask, last, volume, open interest, IV and the provider's
timestamps. *Done when:* unit tests parse a recorded fixture, and nothing outside
the adapter reads a Tradier field name.

**C4.2 Positioning engine** (pure). Per strike and expiration, and in aggregate:
call and put OI, call and put volume, put/call ratios and volume/OI. Then:

- **Call OI wall and put OI wall:** the highest-OI strike on each side within
  the chosen expirations. This is *calculated*, and the card shows OI, today's
  volume, distance from spot and rank.
- **Gamma concentration:** per-strike Σ gamma × OI × 100 × S² × 0.01 (dollar
  gamma for a 1% move). Gamma is recomputed locally with Black-Scholes from live
  spot and the provider's IV. Live spot does not make hourly IV fresh: display
  the IV/OI as-of times and document expiry time, rates, dividend and model
  assumptions, especially for 0DTE. Missing inputs remain unavailable.
  This is *calculated*, and unsigned by default.
- **Signed GEX, as an option only:** it needs an explicitly selected dealer-side
  convention, for example dealers long calls and short puts; OI does not reveal
  the actual holders or their hedge direction. That makes it *assumed*. The
  assumption appears in the label, the card and the code, and it is off by
  default.
- **Gamma flip, SPY/QQQ/SPX only:** signed GEX recomputed across hypothetical
  spot prices, with the zero crossing labeled "model estimate". Do not show it
  for single names, where open interest is too thin for the number to mean
  anything.

*Done when:* formulas are unit-tested against hand-computed fixtures, and the
assumptions are written in `docs/charts-workspace.md`.

**C4.3 Recorder.** Each trading session after the calendar's open, snapshot OI and volume per
strike for SPY, QQQ and SPX, plus the underlyings of open positions and the
top ten watchlist names (decided 2026-09-30), for expirations within 45 days. Store one row per
(underlying, expiration, day) with the strikes packed in a JSON array: about
1 GB per year at this scope, versus about 11 million rows if every strike were
its own row (planning estimates, to be measured on actual payloads). Store the
capture time and available provider as-of times separately: morning volume is
not full-day volume and current OI is not a live position count. This is a background job under the rules in
`docs/agent/background-jobs.md`, and it requires an Alembic revision. **Start
this early:** open-interest history cannot be backfilled, and every later
feature that compares positioning over time depends on it. *Done when:* the job
runs within its API budget, holidays are skipped, and restarting mid-run resumes
idempotently. A missed historical snapshot is recorded as unavailable, never
backfilled with today's chain under yesterday's date. This item runs immediately
after C4.1 in board order, before the positioning engine or UI.

**C4.4 Options levels layer.** Draws the call wall, the put wall and the top
gamma strikes as levels on the price chart. Filters: nearest N (default 3 per
side), 0DTE only / this week / all within 45 days, and a mode of OI, volume or
gamma. Hovering shows the strike's card with its *calculated* or *assumed* label.
Intraday refresh is at most the charted symbol's nearest 3 expirations every 60
seconds, plus SPY and QQQ 0DTE. It reuses the confluence engine, so a wall at
PDH becomes one zone. *Done when:* the layer respects every filter in a browser
test, and its request count stays inside the 30-per-minute budget in a backend
test.

**C4.5 Strike ladder.** A side panel, collapsible and off by default, centered
on spot: put OI and volume to the left of each strike, calls to the right, and
gamma as a bar. Clicking a strike highlights it on the chart. *Done when:* it
renders from a fixture on desktop and as a bottom sheet on a phone.

### Phase 5 — Alerts on the chart

**C5.1 Level alerts.** Create an alert from a level, drawing or auto level
through the context menu: "crosses", "touches" or "closes beyond" on a chosen
interval. Evaluate touches/crossings on validated upstream events before the
one-second browser coalescing can discard a crossing; evaluate "closes beyond"
on reconciled closed bars with an explicit lateness/recovery rule. Alerts
change the stream from demand-driven to "subscribed while the symbol has an
active alert" and add durable evaluation/delivery state; keep subscriptions inside the
single upstream connection. Alerts deliver through the existing ntfy topic and
appear on the chart as a bell glyph on the level, grayed once fired. *Done when:*
a fixture stream records one durable event per crossing, restart/reconnect does
not duplicate that event, and notification retry does not lose it. Test closed-bar
conditions and hidden/closed browsers, not only an open chart tab. Document
transport delivery semantics separately from event deduplication. The phone
message names the symbol, level, price and event time, and a live phone delivery
is observed before claiming it works. Alert subscriptions and REST recovery must
share the existing token budget with up to three visible symbols.
Compound conditions ("and relative volume above 2×") wait until users ask for
them.

### Phase 6 — Review on the chart

**C6.1 Replay.** Pick a date and time; candles after it are hidden. Step with
arrow keys or play at 1×–10×. Indicators and levels are computed only from
visible bars (no lookahead). Built on historical chart mode (C3.3).
*Done when:* step/play/pause and return-to-live work on desktop and phone, and
tests prove candles, levels, earnings information and options snapshots cannot
reveal information from after replay time. Hide unavailable historical overlays
rather than overlaying today's values on a past session.

**C6.2 Trade / no-trade drills.** At chosen moments, or automatically before
each of the user's real entries that day, replay pauses and asks: Trade, No
trade or Wait, and, for Trade, the direction, entry, stop and target. After the
reveal it compares the drill to the real trade and the actual path. It reports
facts ("entered 4 minutes later than in the drill"), never psychology it cannot
support. Drill results are stored so later reviews can compare them.
*Done when:* a seeded drill survives reload, conceals the future until reveal,
and compares the recorded decision with the actual trade using correct units.

### Phase 7 — Layouts

**C7.1 Per-panel symbol link groups (done in PR #95).** Each panel follows the main symbol or
holds its own (for example SPY, QQQ and the traded name). Crosshair and time
range stay linked by time. Each extra symbol costs its own chart-feed loads, so
cap it at three distinct symbols.
*Done when:* SPY, QQQ and a stock remain independent through symbol switches,
range/crosshair linking, pause/resume and scroll-back in browser tests. A backend
test proves tabs/panels share one upstream WebSocket and stay within aggregate
REST budgets. Depends on C0.2/C0.3; comes early in execution order.

**C7.2 Named layouts (done in PR #98).** Save and switch layouts such as "0DTE SPY" (1m | 5m |
15m) or "Names" (SPY | QQQ | ticker). Stored with the workspace (C0.4).
*Done when:* saving, renaming, switching and deleting layouts works across two
browser contexts without losing symbol groups, intervals or levels, including
revision-conflict handling and phone controls.
As built: a layout is the arrangement of the existing five panels (chart mode,
the five intervals, held symbols, small-chart height, linked time ranges). A
variable panel count is not part of it. The main symbol, levels, watchlist,
session and indicators stay workspace-wide, and switching changes the shared
intervals and held symbols, so the other device's panels follow.

### G0 — Daily chart replacement acceptance

This is an evidence checkpoint after the preceding board items, before advanced
options analytics and replay. It is not permission to implement missing features
under a catch-all PR. If a necessary capability is still missing, name a bounded
follow-up item and leave the gate open.

*Done when:*

- Record an actual market-hours desktop session and a phone session: switch
  symbols/intervals, view SPY + QQQ + a stock, draw/edit/undo, save/reload, scroll
  months back, open a historical trade and return live. No unexplained viewport
  jumps, stale-symbol candles or lost saved work.
- Sample candles, volume, EMA and VWAP against source responses and, when
  available, the user's TradingView view with matched interval/session/basis.
  Explain feed, adjustment or calculation differences; do not promise pixel or
  numerical parity without matching inputs.
- Observe disconnect/reconnect, REST recovery, session states and a delivered
  level alert while no chart tab is open. Record versions, timestamps and what
  was actually observed; fixture tests remain a separate column of evidence.
- The user confirms the stock/ETF workflow covers ordinary chart use. SPX
  remains an explicit coverage question unless its separate data paths were
  verified. Advanced options estimates and replay are not prerequisites.
- State the remaining TradingView dependency: this epic does not port the Pine
  scripts or replace the existing TradingView-to-Signals alert loop. Passing G0
  does not by itself justify canceling a subscription used for that separate loop.

## Later (not this epic)

Worth doing once the phases above have shipped, in roughly this order:

- **Extension and regime badge**: one subtle badge ("Extended: VWAP +3.1σ") from
  VWAP deviation, ATR distance and relative volume. Build it only after checking
  in the journal that these inputs actually separate good trades from bad.
- **Context filters on journal analytics**: expectancy and MFE/MAE by entry
  context. The fill-context data to power this already exists; it is a journal
  page, not chart UX.
- **Options-position context captured at fill**: nearest wall and gamma distance
  stored with each new fill, possible only once the recorder (C4.3) runs.
- **News markers** from the Alpaca feed already used by reports.
- **Options flow** from streamed option trades, with at-bid/at-ask inference
  labeled *inferred*. First verify, in regular hours, that streamed option trades
  carry the bid and ask.
- **"Why did this move?"** over a selected chart range: evidence synthesis that
  labels each contributor observed, likely, possible or unknown.
- **Similar days** for SPY/QQQ from Alpaca historical minute bars.
- **Cross-market strip**: relative strength of the charted name against SPY, QQQ
  and its sector ETF.

## Not building

- A drawing-tool zoo: fib retracements, pitchforks, Gann, Elliott labels,
  patterns.
- An indicator marketplace or a Pine runtime. The fixed studies stay: EMA
  9/20/50/200, VWAP, RSI and volume. Parameter editing only if the user asks.
- Futures charts, Level 2, footprint or order-flow charts: the user neither
  trades nor watches futures (decided 2026-09-30), and equity depth of book is
  not needed for options trading.
- Dealer positioning presented as fact, "bullish/bearish flow" scores, and a
  gamma flip for single names.
- Polling individual option strikes, or a second Tradier stream session.
- Mixing Alpaca IEX (single-venue) bars into consolidated candles.
- A chart-library migration.
- Buy/sell signals on the chart, and any automated trading.
- Webull data, while it is dormant.
- Separate microservices. Every engine above is a module in the existing backend.

## Decisions

Settled with the user on 2026-09-30. Do not reopen them without the user.

1. **Drawings (Phase 1) come before automatic levels (Phase 2).** Every later
   layer reuses the drawing layer's selection, hover and hide/lock machinery.
2. **Options recorder scope (C4.3):** SPY, QQQ and SPX, plus the underlyings of
   open positions and the top ten watchlist names.
3. **Per-panel symbols (C7.1) come after shared workspace foundations.** This
   supersedes the original "stay last" decision in the user-authorized planning
   revision. Everyday SPY/QQQ/name layouts precede specialist analytics.
4. **The goal is to replace TradingView** as the primary chart for stocks and
   ETFs. The epic is judged against that.
5. **No NQ or other futures.** The user does not trade or watch them. No futures
   feed, Webull futures investigation or Databento-style subscription.
6. **Deep history (C0.0) came first.** Scroll-back is what replacing TradingView
   needs soonest, and three later items reuse it.
7. **Daily-use readiness comes before advanced analytics.** Level alerts and
   historical trade navigation precede G0; options capture starts early, while
   gamma tools and replay follow the gate. C0.0 remained a single scoped PR.
