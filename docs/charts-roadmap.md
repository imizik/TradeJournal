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

**Last reviewed:** 2026-10-01 against `origin/main` at `f314a35` (PR #101), with C0.7 (PR #102) on top.
The implementation-readiness review moved everyday chart workflows earlier
and clarified data correctness. The status board distinguishes shipped work
from planned work.

**Screen-space planning update (2026-10-02):** C7.3 and C7.4 were added from the
user's TradingView screenshot and the current layout code. They run **after
C1.2, C1.3 and C1.4**, before automatic overlays. This update plans future work only.

**Pre-trade capture planning update (2026-10-03):** C3.4–C3.6 add a five-second
template path, short voice recordings with transcription, and execution linking
with capture-adherence tracking. They are planned after G0 and before options
analytics; they do not change the order of the items before G0. See [the capture specification](#pre-trade-capture-contract-c34c36).
These rows describe future work, not implemented recording or broker controls.

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
| C0.5 | Hotkeys: timeframe keys, next/previous symbol, reset scale, back to realtime, `?` help | 0 Foundations | done ([PR #99](https://github.com/imizik/TradeJournal/pull/99)) |
| C0.6 | Explicit, consistent price basis across stock splits and chart intervals | 0 Foundations | done ([PR #101](https://github.com/imizik/TradeJournal/pull/101)) |
| C0.7 | Daily/weekly history pagination beyond the current three-year window | 0 Foundations | done ([PR #102](https://github.com/imizik/TradeJournal/pull/102)) |
| C4.1 | Options chain adapter and normalized models (Tradier) | 4 Options on the chart | done ([PR #104](https://github.com/imizik/TradeJournal/pull/104)) |
| C4.3 | Positioning recorder: one daily snapshot, kept | 4 Options on the chart | done ([PR #105](https://github.com/imizik/TradeJournal/pull/105)) |
| C1.1 | Drawing layer: select, drag, delete, undo/redo; levels become draggable objects | 1 Direct manipulation | done ([PR #106](https://github.com/imizik/TradeJournal/pull/106)) |
| C1.2 | Tools: horizontal ray, trendline, rectangle zone, text note; magnet to OHLC | 1 Direct manipulation | done ([PR #111](https://github.com/imizik/TradeJournal/pull/111)) |
| C1.3 | Right-click (long-press on phone) context menu for chart, level and drawing | 1 Direct manipulation | done ([PR #112](https://github.com/imizik/TradeJournal/pull/112)) |
| C1.4 | Layers panel: show, hide, lock and delete by group | 1 Direct manipulation | done ([PR #113](https://github.com/imizik/TradeJournal/pull/113)) |
| C7.3 | Viewport-filling chart workspace: compact controls, collapsible navigation and side dock | 7 Layouts | done ([PR #116](https://github.com/imizik/TradeJournal/pull/116)) |
| C7.4 | Resizable chart grid and side dock; maximize any panel and restore saved proportions | 7 Layouts | done ([PR #118](https://github.com/imizik/TradeJournal/pull/118)) |
| C2.1 | Level engine: automatic session and structure levels (backend, pure) | 2 Levels | done ([PR #121](https://github.com/imizik/TradeJournal/pull/121)) |
| C2.2 | Confluence: merge nearby levels into one labeled zone | 2 Levels | done ([PR #122](https://github.com/imizik/TradeJournal/pull/122)) |
| C2.3 | Levels layer on the chart with hover card and test history | 2 Levels | done ([PR #122](https://github.com/imizik/TradeJournal/pull/122)) |
| C2.4 | Time-of-day relative volume on the volume pane and legend | 2 Levels | done ([PR #123](https://github.com/imizik/TradeJournal/pull/123)) |
| C2.5 | Earnings markers and an "earnings in N days" badge | 2 Levels | next |
| C5.1 | Level alerts delivered to the phone, drawn on the chart | 5 Alerts | todo |
| C5.2 | Retire the TradingView alert loop once in-house alerts reach the phone | 5 Alerts | todo |
| C3.3 | Historical chart mode: open any past trade on the chart | 3 Journal on the chart | todo |
| C3.1 | Trade card: click a fill arrow for the trade, its P&L, MFE/MAE and entry context | 3 Journal on the chart | todo |
| C3.2 | Position lines: average entry, exits and open P&L on the chart | 3 Journal on the chart | todo |
| G0 | Daily chart replacement acceptance: real market session, desktop and phone | Gate | todo |
| C3.4 | Pre-trade capture: five-second template path and frozen chart context | 3 Journal on the chart | todo |
| C3.5 | Voice capture: save the recording, transcribe asynchronously | 3 Journal on the chart | todo |
| C3.6 | Link captures to entries; show missed captures and adherence | 3 Journal on the chart | todo |
| C4.2 | Positioning engine: OI, volume, walls, gamma concentration | 4 Options on the chart | todo |
| C4.4 | Options levels layer with filters | 4 Options on the chart | todo |
| C4.5 | Strike ladder side panel | 4 Options on the chart | todo |
| C6.1 | Replay: hide the future, step, play | 6 Review | todo |
| C6.2 | Trade / no-trade drills compared with the actual trade | 6 Review | todo |
| C2.6 | Relative volume on older sessions, from each session's own baseline | 2 Levels | todo |

Why this order: history, correct sessions and smooth updates come first; then
shared state and SPY/QQQ/name layouts. Record options snapshots early because
lost days cannot be recovered, but defer their analytical UI. Drawings precede
automatic overlays, and ordinary alerts precede gamma tools and replay.
Historical trade navigation makes the new history useful before rich trade cards.
After the drawing tools, context menu and layers panel settle, reclaim screen
space before automatic levels add more controls. C7.3 establishes the shell;
C7.4 adds resizing to that shell. Both precede G0, options analytics and replay.
Once G0 is satisfied, capture the user's intent before execution, through both
click and voice paths, before expanding options analytics. This does not add
pre-trade capture to G0's acceptance requirements.

Dependencies beyond board order: C7.1 needs C0.2/C0.3; C7.2 needs C0.4/C7.1;
C4.3 needs C4.1/C0.1 and the durable job framework, not C4.2; C2.1 needs C0.1
for session boundaries; C7.3 needs C0.2/C0.3/C1.2/C1.3/C1.4;
C7.4 needs C7.3/C7.2/C0.4; C2.4 and C3.3 need C0.0; C5.1 needs C1.3/C2.3 plus
durable alert state; C4.4 needs C2.2/C4.2; C6.1 needs C3.3. G0 precedes
advanced analytics, not every possible future feature.
C3.4 reuses C0.4's persistence patterns and C7.3's chart shell; C3.5 needs C3.4;
C3.6 needs C3.4/C3.5 and C3.1's trade-card surface. These are three separate
implementation slices, in that order, not permission to implement all three
when asked for one.
C2.6 needs C2.4; each history page's sessions need their own 20-session baselines.

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
| Daily candles | The whole history in one call (SPY: 7,999 bars from 1994-12-16, 0.45 s); split-adjusted as observed (NVDA, 2026-10-01), checked per split; dividends not adjusted | Yes | Yes, cached for enrichment | Tradier (already) |
| Market calendar | `/v1/markets/calendar`: holidays and early closes (Thanksgiving closed, 11/27 closes 13:00), back to 2016; next year returns HTTP 400 until published | `/v2/calendar` | — | Tradier (C0.1) |
| Option chain | One call per expiration: bid/ask/sizes, last, **volume, open interest**, greeks; about 200 ms. SPY nearest expiry: 638 contracts, OI on 498 | Snapshots on the indicative feed, **no open interest** | EOD only | **Tradier** |
| Expirations | SPY 32, QQQ 30, NVDA 24, SPX 55 (with SPXW); SPY has 14 within 45 days | — | — | Tradier |
| Greeks / IV | ORATS, **hourly**; `updated_at` read 20:00 the previous evening after hours. Gamma is non-zero on only 120 of 638 SPY contracts (far strikes round to 0) | Indicative | — | Tradier IV; **recompute gamma locally** from live spot (C4.2) |
| Open interest history | Current only; OCC publishes once overnight | — | — | **Record our own** (C4.3); it cannot be backfilled |
| Option minute history | `timesales` on an OCC symbol returned `series: null` | Option bars (already used by `trade_path.py`) | — | Alpaca, when ever needed |
| Option trades stream | Streams OCC symbols per docs; whether trade events carry bid/ask is *unverified* | Indicative | — | Later (flow is out of scope) |
| Earnings dates | `/beta/markets/fundamentals/calendars` returns NVDA earnings events; accuracy of upcoming dates *unverified* | — | — | Tradier (C2.5) |
| Macro events (CPI, FOMC, NFP) | — | — | — | None; a hand-kept yearly file if ever wanted |
| News | — | Benzinga, already in `news.py` | — | Alpaca ([symbol info panel](symbol-info-roadmap.md)) |
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
| Open interest before 2026-10-01 | Testing walls or positioning as a strategy-factory feature, whose history starts July 2023 | Buy end-of-day open interest by strike (ThetaData and ORATS sell it; price it first), or wait two to three years of our own snapshots | Strategy factory, not this epic |
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

**C0.5 Hotkeys (done in PR #99).** Numeric interval entry (`1`, `3`, `5`, `15`, `30`) commits on
Enter, so typing `15` does not first select `1m`. `H` (1h), `4` (4h), `D` and `W`
are immediate interval shortcuts; `Space` and `Shift+Space` step through the
watchlist; `Alt+R` resets scales; `End` returns to realtime; `?` shows a cheat sheet. Hotkeys are
ignored while typing in an input. *Done when:* each has a browser test and the
cheat sheet lists exactly the bindings that exist, including numeric entry and
Escape to cancel it. Buttons retain equivalent phone access.
As built: interval keys act on the main chart; Alt+R and End act on every
chart. A button reached with Tab keeps Space; after a click Space steps the
watchlist. The existing Alt+Up/Down watchlist steps stay. Touch equivalents
are the interval buttons, new up/down arrows in the watchlist header, and each
chart's latest-candles button, which now also restores automatic price scales.

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

**C0.7 Daily/weekly depth (done; built as documented in [Daily and weekly depth](charts-workspace.md#daily-and-weekly-depth-c07)).** Extend the history-page contract to provider daily
bars and weekly resampling without constructing daily bars from extended-hour
minutes. Honor C0.6's price basis and the same memory, warmup and viewport rules.
*Done when:* a fixture daily chart scrolls ten years (or to listing inception)
and weekly page boundaries agree with a continuous reference. New listings and
provider history exhaustion terminate honestly. This work does not expand
C0.0's intraday-only scope.

### Phase 1 — Direct manipulation

**C1.1 Drawing layer (done in PR #106).** A series-primitive layer on the candle series renders
drawings and hit-tests the pointer. Selecting a drawing shows its handles; dragging moves it;
`Delete` or `Backspace` removes it; `Cmd/Ctrl+Z` and `Shift+Cmd/Ctrl+Z` undo and
redo. Drawings are anchored to **time and price**, never to pixels or bar index,
so they stay put across zoom, intervals and the five panels. Existing saved
levels become drawings of the kind "horizontal level". *Done when:* drag, delete
and undo work with a mouse and by touch, a level dragged on the 5m chart moves on
the 1h chart, and nothing is lost on reload.
As built ([Implemented behavior](charts-workspace.md#implemented-behavior)): `frontend/lib/drawings.ts`
holds the primitive and item-level undo edits. A finger drags only a selected
level, so panning is never taken for a drag. Levels keep their saved `levels`
shape, so an open tab on an older build still reads and merges them. C1.2's new
kinds needed a new settings field, which an older tab's save would have dropped;
C1.2 made the server keep fields a save leaves out.

**C1.2 Tools (done in PR #111).** Horizontal ray, trendline (with extend left/right), rectangle
zone and text note. Magnet mode (hold `Cmd/Ctrl` or toggle) snaps anchors to the
nearest open, high, low or close. Each tool remembers its last style. *Done when:*
each tool can be drawn, edited and deleted in a browser test, and the magnet
snaps to OHLC in a test with known bars. No fib, pitchfork, Gann or other
geometry tools.
As built ([Implemented behavior](charts-workspace.md#implemented-behavior)): drawings live in a
`drawings` settings field beside `levels`, and the server now keeps any
top-level field a save leaves out, so an older tab cannot erase them. Anchors
are bar-middle times mapped by each chart's own bars, and placement reads its
own clicks because the library holds back a quick second click. The selection
bar folds its style controls behind **Style** so it stays one row on a phone;
C1.3's inline label and color editing can reuse it.

**C1.3 Context menu (done in PR #112).** Right-click, or long-press on touch, on empty chart: add
level here, copy price, reset scale, toggle layers. On a level or drawing: edit
label and color inline, lock, hide, duplicate, delete, and (after C5.1) create
alert. *Done when:* both menus work by mouse and by touch.
As built ([Implemented behavior](charts-workspace.md#implemented-behavior)): the menu is
`frontend/components/charts/ChartMenu.tsx`, a popup at the pointer for a mouse
and a bottom sheet for a finger held still for 500 ms. Lock stops dragging
only; a locked item still selects, restyles, hides and deletes. Hidden items
and hidden groups are left out of the layer entirely, so they neither draw nor
select. Levels gained optional `color`, `hidden` and `locked`, and drawings
`hidden` and `locked`, each saved only when set; "toggle layers" is a
`hiddenGroups` setting for My levels and Drawings plus the existing fills and
study toggles. C1.4 builds its panel on these flags. Labels exist only where
items already had text (a level's name, a note); rays, trend lines and zones
take a color but no label. A tab on a pre-C1.3 build drops the per-item flags
when it saves levels or drawings, because the server keeps only top-level
fields a save leaves out.

**C1.4 Layers panel (done in PR #113).** A collapsible list grouped as My levels, Drawings, Auto
levels, Options, Journal and Indicators. Each group and item can be hidden,
locked or deleted, and a click jumps the chart to it. *Done when:* hiding a
group hides it on all five panels, the state persists, and the panel works as a
bottom sheet on a phone.
As built ([Implemented behavior](charts-workspace.md#implemented-behavior)): `frontend/components/charts/LayersPanel.tsx`,
opened from a **Layers** button after the drawing tools, sits in the side
column on screens 1024px and wider and is a bottom sheet below that. It has
My levels, Drawings, Journal and Indicators; Auto levels and Options are
added by C2.3 and C4.4, since an empty group is noise. Lock and delete apply
to levels and drawings (fills and studies have neither). A group lock is not
a separate flag: it locks or unlocks every item as one undo step, so the
chart menu and selection bar never disagree with it, and a level added later
starts unlocked. Group deletes are also one undo step (a new `batch` edit).
Group hiding is the C1.3 `hiddenGroups` setting for levels and drawings and a
top-level `studiesHidden` field for Indicators (a new `hiddenGroups` key would be
dropped by a pre-C1.4 tab's save); the Journal group is the existing fills toggle. Jumps reuse the history loader to
reach drawings older than the loaded candles. The panel lists items of every
symbol on screen (main and held), each going to the first panel showing it.

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
As built ([Automatic levels](charts-workspace.md#automatic-levels-c21)):
`backend/app/engine/chart_levels.py` is pure; C2.3 calls it from the workspace.
C2.2 and C2.3 shipped together in one PR at the user's request. The premarket range, opening ranges and prior day call
`analyze_minute_bars` and `get_previous_day_data`. Overnight is the previous
session's postmarket plus this premarket, from the calendar. Round numbers step
by 1 or 5 × 10^k near 1% of price; swings are two-session daily pivots over 60
sessions. For C2.2, each level carries `bar_time`, the bar that set it: the
independent-source rule counts levels that share a bar once. Its `evidence`
says observed, calculated or inferred. A level the bars cannot support is
absent with a reason, never taken from an older session.

**C2.2 Confluence.** Levels closer than a threshold merge into one zone. The
threshold is a fraction of ATR, not a fixed price, so it scales from SPY to
CVNA. The zone is labeled by its members ("PDH + 21,500 + OR15 high") and spans
the members' actual prices, never more precise than they are. The score is the
count of **independent** sources, so two levels derived from the same bar count
once. *Done when:* unit tests cover merging, non-merging and the
independent-source rule.
As built ([Automatic levels](charts-workspace.md#automatic-levels-c21)): the
threshold is a tenth of the daily ATR(14), the same band C2.3 tests with.
Merging is single-linkage by price, so a run of close levels merges whole and
the zone spans exactly its members. Without an ATR only same-price levels merge.

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
As built ([Implemented behavior](charts-workspace.md#implemented-behavior)): the
backend computes levels, zones and each intraday panel's interactions with
every 15-second workspace refresh (`auto_levels`, `level_events`). The
previous session comes only from the history cache on disk. The nearest three
zones each side show by default, on every chart. A tap or click keeps a card
open. Levels show by default because this item says "by default". The
**Auto levels** group (Layers panel and chart menu) hides them and lists
what is missing. Daily and weekly charts draw the levels but read no
interactions. With levels on, a held symbol without a daily panel reads its
daily bars once a minute: 19 requests a minute for a three-symbol layout
instead of 17.

**C2.4 Relative volume.** A baseline of average cumulative volume by minute of
day over the last 20 sessions, computed nightly per watchlist symbol from the
deep-history store (C0.0); about 390 numbers per symbol per day. Volume
bars are shaded by relative volume, and the legend reads "RVol 2.6× for 10:17".
Until the baseline exists, say so rather than guessing. *Done when:* the
calculation matches `compute_rvol_time_adjusted()` on the same inputs, and the
chart labels which sessions the baseline covers.
As built ([Relative volume](charts-workspace.md#relative-volume-c24)):
`backend/app/engine/chart_rvol.py` is pure, and every 1m, 5m and 1h candle's
RVol equals `compute_rvol_time_adjusted` for a fill at the candle's end on the
same bars. What runs nightly is the storing, not the arithmetic: the
`rvol_history` job (06:00 and 08:40 New York on weekdays) stores the 20 SIP
sessions before today for each watchlist name, and the workspace builds the
390-number baseline from those files, read once per process, so it costs no
provider request and is on today's split basis. Any charted symbol whose
sessions are stored gets one, not only watchlist names. Only today's
regular-session candles have RVol; older sessions keep plain volume colors
(C2.6). A live probe found that Alpaca answers a day without minutes (SPX, or
CRWV before it listed) with `"bars": null`, which C0.0 called malformed; it now
reads "no minute bars" and is still not stored, and the job notes such names
instead of failing. The main chart's study row reads "RVol 2.6× for 10:17 AM" and names the
sessions; a smaller chart shows "RVol 2.6×" in place of its volume, because
its row beside the countdown has no room for both.

**C2.5 Earnings.** Earnings dates from Tradier's corporate calendar, cached
daily per watchlist symbol. The chart shows a marker on the date and a badge
("Earnings in 3 days"), since earnings drive option IV. Verify the accuracy of
upcoming dates against the company's announcement before shipping, and label the
source. The data adapter is built as T1.4 of the
[symbol info roadmap](symbol-info-roadmap.md), which records the calendar's
duplicate rows and the missing time of day; C2.5 draws the markers from it.
*Done when:* markers render from a fixture, and an unknown date shows
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

#### Pre-trade capture contract (C3.4–C3.6)

**Product goal.** Capture intent before a new trade without asking the user to
write a journal entry. The normal path takes four actions and targets five
seconds after initial setup. Voice is an equally supported alternative when a
template does not express the thought. Neither path recommends a trade or
submits an order. Capturing intent and evaluating its quality are separate.

**Scope.** The first version covers the initial entry of a reconstructed journal
trade, including stocks and options, with partial opening fills treated as one
trade for adherence. Separate plans for scale-ins, exits, multi-leg strategies,
order routing and broker-enforced gates are later work. Broker execution still
happens outside TradeJournal; the app cannot guarantee capture before every
order. No new broker integration, analytics overhaul, AI coaching, sentiment
scoring, inferred rationale or experiment tracker is part of these items.

**Shared capture and provenance rules:**

- A capture is its own durable user record, not a field on a rebuildable trade
  or part of the chart-settings JSON. Use additive Alembic migrations. Keep
  raw captures, templates and execution links separate from derived journal
  rows; rebuilding trades must not erase or change what the user recorded.
- Store an idempotent client capture ID, server receipt timestamps in UTC,
  account, underlying, explicit instrument/side, capture mode, immutable
  submitted text/template copy or original audio, and the chart-context
  snapshot. Templates have revisions; changing one never edits old captures.
- Freeze symbol, account and panel identity when the capture sheet opens. Show
  them prominently. A chart symbol switch must not silently retarget an open
  capture or recording. Let the user explicitly change them before submission.
- Snapshot the selected chart's interval, session, visible time range, price
  basis/split metadata, displayed price and its source/as-of/stale state, and
  visible levels/drawings. Freeze this data at submission. Save a bounded image
  of that chart as a supporting artifact, disclosing any omitted overlays. Do
  not screenshot other apps or invent missing indicators/context. Use existing
  chart state; capture must not trigger market-data provider requests.
- Image upload is independent of saving intent. Failure leaves an explicit
  image-unavailable state and a retry for the original frozen image, never a
  screenshot of the later market labeled as the original. Historical/replay
  captures are review records and cannot count as live pre-entry captures.
- The qualifying capture time is when the server durably receives the complete
  intent: submitted template/text, or the complete original audio file. Opening
  the sheet, starting a recording, receiving an empty placeholder, or a client
  clock timestamp is not proof of a completed pre-entry capture. Preserve client
  capture times separately for delayed/offline uploads, labeled unverified.
- Store immutable originals plus timestamped corrections/reflections. Later
  transcript corrections, template edits or linking cannot backdate intent.
  A corrected transcript displays alongside the original provider result and
  audio. Later additions are visibly retrospective.
- Show distinct saving, saved, pending upload and failed states. Only server
  acknowledgement may say "Saved". Retain pending text/audio locally for
  explicit retry where browser storage permits; disclose storage failure.
  Repeated taps, requests and retries must not duplicate a capture or job.
- Audio and images live in private durable storage outside release directories,
  with database metadata and inclusion in backup/restore. Access uses the
  existing private application boundary, never the public TradingView ingress
  or public artifact URLs. Bound file sizes and validate uploads. Archiving a
  capture does not erase the historical adherence record.

**C3.4 Five-second capture (planned).** Add a persistent **Plan trade** button
beside the main chart, plus **Alt+P** registered in the existing hotkey system
and help sheet. Use the physical key code on Mac; ignore repeats, typing and
other open dialogs. The button remains reachable with the side dock collapsed
and at 390px. Desktop uses a compact sheet; phone uses a bottom sheet.

One-time setup, outside the trading path: select a default journal account and
save up to three favorite templates. Each template bundles a setup label with
the user's own invalidation/exit-plan wording. Names such as "Reclaim" and
"Pullback" may be examples, but no trading rule is silently adopted. Editing
templates and changing the default account remain accessible later.

The normal click path is:

1. Open **Plan trade** (or Alt+P). Show the chart ticker and the saved account.
2. Select instrument/side. Show favorite explicit choices, such as **Buy calls**,
   **Buy puts**, **Buy stock**, with other supported opening sides under More.
   Do not infer buy/sell exposure from call/put alone or silently reuse a side.
3. Tap a template. Its full saved wording stays visible before confirmation.
4. Tap **Save plan** (or Enter when enabled). Close after acknowledgement and
   show the saved plan in a compact, dismissible strip beside the chart.

No mandatory paragraph, mood rating, confidence score, quantity, strike,
expiration, stop price or price target. Exact contract and sizing fields are
optional; capture matching must tolerate their absence without guessing.
Provide **Discretionary / no explicit plan** as an honest alternative and an
optional short text field. Record this as captured intent with plan detail
unspecified, not as a complete exit plan. Users without configured favorites
can use that path or write a short note; setup never blocks capture.

The saved strip shows ticker, side, setup/wording and capture time, with an
expand action and **Did not take trade**. Unexecuted plans are valid records.
Do not treat a saved plan as an actual position until journal evidence exists.

*Done when:*

- The configured route takes exactly open, side, template, save; a human
  walkthrough measures the five-second target separately from fixture tests
  and reports network save latency separately. No extra confirmation dialog.
- Desktop and 390px browser tests cover template and discretionary/text paths, keyboard/input isolation,
  changing symbols while open, snapshot failure, rejected saves, reload and
  duplicate submission. Saved records are available across browser contexts.
- SQLite/Postgres migration coverage, immutable template copies and append-only
  corrections are tested. Existing chart hotkeys, drawings and settings remain
  intact. No source fills, P&L or enrichment rows are modified.

**C3.5 Voice capture and transcription (planned).** The same sheet offers a
clearly labeled microphone action alongside templates. Retain explicit account,
ticker and instrument/side selection; a template is optional for voice.
An optional prompt reads: "What am I taking, why here, and what would change
my mind?" It is guidance, not three mandatory answers.

- Support hold-to-record/release-to-save and an accessible tap-to-start,
  **Stop & save** alternative. Explain that saving also requests transcription.
  Request microphone permission only after the user activates recording.
- Limit clips to 30 seconds with a visible timer. At the limit stop and offer
  Save or Discard. Pointer cancellation, tab hiding or device interruption stops
  recording and offers recovery; do not silently keep recording or upload a
  discarded clip. First-time permission handling must not lose the gesture.
- Persist original audio first. Show "Recording saved — transcribing" after
  durable server acknowledgement. The user can return to execution immediately;
  transcription never blocks saving intent or pins the sheet open.
- Use a backend speech-to-text adapter with one configured provider. Provider
  credentials stay server-side. At implementation, verify the chosen API's
  current audio formats/limits and available configuration; existing Claude
  review credentials are not assumed to provide speech transcription. State
  the provider and that audio leaves the app before first use, without a
  repeated per-clip confirmation. No new paid plan is assumed authorized.
- Persist transcription work and status using the existing durable job
  framework. Give it execution capacity independent of long broker/enrichment
  jobs; include any worker/deployment configuration in this item's scope.
  Do not rely on an untracked request thread. Use bounded provider timeouts,
  deduplicated jobs and an explicit retry after failure/interruption; an
  uncertain provider response must not trigger unlimited paid retries.
- Show pending, transcribing, ready, failed and not-configured states. A provider
  outage never loses a saved recording. Playback and retry remain available.
  Transcription stays literal: no generated rationale, plan scoring or automatic
  changes to ticker/account/side. Unclear speech may remain unclear.
- Permission denial, unsupported recording or unavailable private microphone
  access leaves the click/text path usable. Verify microphone access on the
  actual private desktop/phone origin; do not expose the unauthenticated API
  to make recording work. Do not claim real-device support from a fake stream.

*Done when:* real desktop and phone recording, playback and one live provider
transcription are reported separately from browser/provider fixtures. Fixtures
cover both gestures, cancellation, the time limit, silence/invalid uploads,
permission denial, save failures, pending-upload recovery, provider failure,
restart, retry dedupe and later transcript correction. Audio acknowledged
before an entry remains pre-entry evidence when its transcript arrives later;
audio only uploaded after entry remains late/unverified regardless of when
recording started. Backup/restore preserves playable attachments and metadata.

**C3.6 Execution links and capture adherence (planned).** Surface the saved
intent beside its linked trade in C3.1 and trade detail, with the original
snapshot/audio/transcript accessible. Add a compact **Needs linking** view
reachable from the saved strip; do not build a new analytics dashboard.

- Suggest, but do not silently confirm, matches using exact account, underlying,
  compatible opening side and first entry execution time. The initial candidate
  window is the ten minutes after the qualifying capture time. If supplied,
  exact contract fields must also agree. Multiple possibilities require an
  explicit choice; absence of a contract is not permission to pick one.
- One capture links to one reconstructed trade; multiple partial opening fills
  within that trade do not consume multiple plans. A re-entry is a new trade
  and needs its own capture. Later scale-ins are excluded from this version's
  adherence claim. Do not infer order/decision counts from raw fill count.
- Allow manual linking outside the suggestion window and corrections/unlinking
  with history. Linking a post-entry note is allowed but labeled retrospective;
  changing the link does not alter the original capture timestamp.
- Anchor links in stable source-fill identity (account plus source dedupe key),
  resolving current trade membership through fill links. A trade UUID alone is
  insufficient because trades are rebuilt. Retain the recorded source identity
  even across resync; missing or ambiguous resolutions become unresolved, never
  cascaded deletion or a silent link to a different trade. Revalidate timing and
  membership after reconstruction or source-time corrections.
- Compare server UTC receipt against the first entry's execution time converted
  from the journal's America/New_York convention, not import time. Unknown,
  coarse/tied or ambiguous execution times are timing-unverified. Only clearly
  earlier, complete intent qualifies as confirmed pre-entry evidence.
- Enable tracking from an explicit activation timestamp and selected accounts.
  For eligible new trades since then, show **X of Y recorded trades have a
  confirmed pre-entry capture**, plus counts for needs-linking, no capture,
  retrospective and timing-unverified. The denominator is recorded trades with
  reliable entry times in that scope, including pending matches; show excluded
  trades separately. Never claim coverage of executions missing from ingestion.
- A delayed import is evaluated by execution time. Refresh after import/rebuild
  through existing refresh mechanisms, not per-trade polling. Resolve pending
  suggestions before calling them missed captures; show a quiet reminder after
  refresh and a persistent count. No modal blocks, repeated nags, fake broker
  lockout, streak penalties or new phone-notification infrastructure.
- Keep the strip useful during a position: show the user's original intent.
  Do not claim compliance with exit rules or assess plan quality. Captured
  discretionary intent is distinguishable from an explicit template/voice plan;
  the adherence number measures capture, not trading discipline or profitability.

*Done when:* tests cover delayed ingestion, same-ticker ambiguous options,
account/side mismatch, partial opening fills, re-entry, scale-ins, DST/tied
times, late uploads, late transcripts, manual linking, unexecuted plans,
activation boundaries, pending/excluded denominators, and rebuild/resync with
stable and missing source identities. A browser scenario captures a plan,
introduces a fixture fill, confirms a suggested link, then reads the preserved
intent and correctly labeled adherence. A late reflection cannot become a
pre-entry plan through editing or linking.

### Phase 4 — Options positioning on the chart

**C4.1 Chain adapter (done in PR #104).** A Tradier adapter (for example
`backend/app/engine/options_chain.py`) fetches one expiration per call and
returns normalized, provider-independent contracts: underlying, expiration,
strike, call/put, bid, ask, last, volume, open interest, IV and the provider's
timestamps. *Done when:* unit tests parse a recorded fixture, and nothing outside
the adapter reads a Tradier field name.
As built ([Option chains](charts-workspace.md#option-chains-c41)): the models
are a separate pure module (`options_models.py`) so C4.2 and C4.3 can read them
without the client. One SPX date can carry both SPX and SPXW contracts, so
every contract keeps its root. The adapter owns the 30/minute options budget;
a background caller may wait for a slot.

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

**C4.3 Recorder (done in PR #105).** Each trading session after the calendar's open, snapshot OI and volume per
strike for SPY, QQQ and SPX, plus the underlyings of open positions and the
top ten watchlist names (decided 2026-09-30), then the strategy factory's core
universe (added 2026-10-02), for expirations within 45 days. Store one row per
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
As built ([Options snapshots](charts-workspace.md#options-snapshots-c43)): the
snapshot is taken after the close, from 16:15 to 20:00 New York, not in the
morning. That way volume covers the whole session and SPX's overnight session,
whose volume Tradier reports from 20:15, never leaks in. A weekday timer queues
it at 16:20 with a 19:20 catch-up. Each underlying gets a per-session status
row, so a missed session is an explicit `unavailable`. A live dry run stored
SPY, QQQ and SPX in 522 KB, so the whole scope is about 1 MB a day, below the
1 GB-a-year planning estimate. The factory's 18 names were added on 2026-10-02
so option positioning can one day be tested as a factory feature on the names
the factory trades: about 200 more chain requests a night (roughly seven
minutes at 30 a minute), recorded last so the names traded live come first.
Their storage is not measured yet.

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
them. An alert made from an options wall (C4.4) is pinned to that wall's strike
when it is created. Open-interest walls hold still through a session, but a
volume wall can move to another strike, and a level moving under an alert
confuses more than it helps: when the wall moves, the chart says so and the
alert stays where it was. A wall alert is a level alert and claims no edge.

**C5.2 Retire the TradingView alert loop** (decided 2026-10-02). Alerts move
into the app, and Pine stops being a path for anything. Once C5.1 has
delivered a live alert to the phone, remove the TradingView webhook ingress
(port 8090, the only internet-reachable process): its service and deploy unit,
the webhook-only router and the Pine file. Mark the `v=1` contract retired and
bring `docs/agent/` up to date in the same PR. Stored `tradingview_alert` rows
and the Signals pages that read them stay, read-only; deleting the rows and
dropping the ingress database role wait for the user. *Done when:* a fresh
deployment starts no ingress service, nothing listens on 8090, the Signals
pages still render stored rows, and the import-boundary and deploy checks pass
without the ingress.

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

**C7.3 Viewport-filling chart workspace (done in PR #116).** Make `/charts` use the
available browser content area in ordinary use, like the supplied TradingView
view: a compact top toolbar, narrow tool rail, chart grid and optional right
dock. Keep the existing one-large-plus-four-small arrangement and single-chart
mode. Browser tabs and the address bar are outside the app's control; optional
browser fullscreen is an enhancement, not a prerequisite for this item.

Current code to replace: `frontend/app/layout.tsx` adds desktop page padding,
`frontend/components/Nav.tsx` owns the journal sidebar, and
`frontend/components/charts/ChartWorkspace.tsx` stacks a page heading, quote and
control rows, indicators and fixed-height charts. Its main canvas is 410px in
normal mode; immersive mode estimates available height as viewport height minus
260px and fits the lower row only on sufficiently tall screens. Adding another
fullscreen button will not address those layout constraints.

Implementation plan:

- Give `/charts` a route-aware shell: fill the available viewport, collapse
  journal navigation to an accessible rail/menu, remove the duplicate page
  heading and outer card padding. Keep navigation, sync status and actionable
  Gmail warnings reachable; other journal pages retain their current shell.
- Put symbol/search, interval/session, indicators, layout, pause and workspace
  controls in one desktop toolbar. Move drawing tools and undo/redo into a
  slim rail using the C1.2 actions. Put secondary settings in menus/overflow;
  retain keyboard access, tooltips and visible selected-tool state.
- Use a collapsible right dock for watchlist and the C1.4 layers panel, with
  tabs/sections rather than more full-width rows above the chart. Accommodate
  the [symbol info panel](symbol-info-roadmap.md) and future C4.5 strike ladder
  when built; do not implement their content in this item. Symbol info may
  still hide in immersive mode as T1.1 specifies. On phone, use a drawer/sheet.
- Size the chart grid from its actual remaining container with CSS grid/flex,
  `minmax(0, 1fr)` and container measurement. Remove the hardcoded viewport
  subtraction. Let `PriceChart`'s existing `autoSize` follow its container;
  account for chart headers, scales, RSI/volume, warnings and safe areas.
- Keep a compact status strip for provider/source, freshness, delayed/stale,
  pause/error and price-basis warnings; preserve attribution. Density must
  not hide data truth. Full-screen mode reuses this shell, keeps an obvious
  exit and follows existing Escape/dialog/drawing cancellation precedence.

*Done when:*

- At 1440×900 and 1920×1080 browser content viewports, the default five-chart
  arrangement fits without document scrolling with the dock open or closed.
  With the dock closed, the grid (including panel headers/scales/study panes)
  occupies at least 80% of viewport height and 90% of viewport width. Measure
  DOM bounds and save screenshots; these are layout targets, not observations.
- At 1280×720, usable minimum panel sizes take priority over forcing all five
  charts into view: offer single-panel focus or a contained lower-row scroller.
  At 390px, controls remain reachable with 44px touch targets, safe-area padding
  and no horizontal document overflow. Phone sheets do not shrink the canvas
  into an unusable sliver, and can be dismissed accessibly.
- Browser tests cover dock/navigation toggles, toolbar overflow, focus order,
  chart interactions after container/window resize, dialogs and fullscreen
  entry/exit. Resizing/toggling preserves instances, drawings, selection,
  scroll-back position and live updates; it creates no extra data fetches or
  stream connections. Existing drawing, hotkey and phone regressions pass.

As built (`docs/charts-workspace.md` has the detail): the shell applies from
1024px wide; below that the page scrolls as before, with 44px controls, the
drawing tools as a toolbar row, a **More chart controls** menu for the
secondary controls, the data note and the attribution, and the dock as a
bottom sheet. The dock shows one panel at a time; its tabs (**Watchlist**,
**Layers**) are the toolbar's last buttons rather than a separate right rail,
which keeps the closed-dock grid above 90% of a 1440px window. The watchlist
tab carries the main symbol's levels form and latest fills under the list,
where the [symbol info panel](symbol-info-roadmap.md) can join it. Dock state
and navigation collapse are per device; full screen keeps the shared
`immersiveWatchlist` as its own dock choice until C7.4 moves it to local view
state. The studies became an **Indicators** menu. The main chart's minimum is
320px; the smaller charts keep their S/M/L heights until C7.4's dividers
replace them. The desktop toolbar wraps to a second row below about 1280px
instead of collapsing into an overflow menu. Browser fullscreen (the
Fullscreen API) is not used.

**C7.4 Resizable chart grid and dock (done in PR #118).** Let the user distribute space
within C7.3's shell: drag the main/lower-row divider, the dividers between the
four lower charts and the right dock's edge. Start with the existing five panel
slots; arbitrary docking, variable panel counts and a new layout library are
outside this item. Existing volume/RSI pane resizing stays independent.

Implementation plan:

- Store bounded proportions for the main/lower split and lower-chart columns,
  with sensible minimum sizes. Separators support mouse and keyboard with
  accessible names/values; touch resizing is offered only where enough space
  exists. Double-click or an explicit reset restores defaults. Clamp on resize
  and use C7.3's small-screen fallback rather than crushing scales and labels.
- Maximize any chart in place, then restore the exact prior arrangement.
  Treat this as temporary view state, preserving interval, held/follow symbol,
  crosshair/range linking, drawings, selection and historical viewport. Keep
  the existing Focus action's symbol/slot semantics explicit; do not silently
  swap panel identities just to enlarge one chart.
- Extend C7.2's saved arrangements with normalized chart split proportions.
  Update `frontend/lib/charts.ts` validation/defaults, layout save/apply/match,
  and `frontend/lib/chartSync.ts` conflict handling together. Old layouts with
  S/M/L heights remain readable and get equivalent defaults. Proportions sync;
  dock width/visibility, navigation collapse and temporary maximization stay
  per device, so desktop geometry never forces an unusable phone layout.
  Migrate the currently shared `immersiveWatchlist` preference to local view
  state without losing the device's prior choice or breaking older clients.
- Update container geometry during dragging without remounting charts or
  resetting time/price scales. Persist on completion, not on every pointer
  move; keep geometry changes separate from the tick/clock hot path.

*Done when:* browser tests resize and reset every separator, maximize/restore
each panel, shrink/enlarge the viewport, reload and switch named layouts with
ticks and REST reconciliation running while scrolled back. Keyboard controls
and phone fallback work; malformed ratios and old saved layouts normalize
safely. Two browser contexts prove saved proportions and conflict handling,
while dock geometry stays local. Chart instances and viewport state survive;
resize operations issue no additional provider requests. Record desktop/phone
screenshots and bounded size measurements separately from live-session proof.

As built (`docs/charts-workspace.md` has the detail): the shared setting is
`proportions` (the smaller row's share of the height, 0.15–0.6, and four
column shares, each at least 0.1), and each saved layout's proportions are a
top-level `layoutProportions` map by layout id rather than a key inside the
layout, because a tab on an older build rebuilds layouts from the keys it
knows and the server keeps only top-level fields a save leaves out. Saved
layouts keep exactly C7.2's keys, including a valid `smallSize`, so an older
build never drops one. Settings and layouts without proportions follow their
S/M/L size: 0.275, 0.378 and 0.518 reproduce C7.3's 226, 311 and 426px rows
in a 1440×900 window. On screen the main chart keeps 320px, a smaller chart
180px with its header and 160px of width (a row too narrow for four scrolls
sideways inside the grid); a smaller window clamps the view and saves nothing. The S/M/L buttons left the desktop toolbar (the divider
replaced them) and stay in the phone's More menu. Dragging a divider counts
as editing the layout, like an interval change. Maximize replaced the smaller
charts' Expand toggle and is on the main chart too: the chart is placed over
the grid while the others stay mounted at their size, hidden. The dock is
200–480px (256px by default) and never leaves the charts under 640px; its
width and full screen's dock choice are stored per device, the latter seeded
once from the shared `immersiveWatchlist`, which stays for older tabs.

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
- Use C7.3/C7.4's compact workspace, collapse/reopen the dock, resize the grid
  and maximize/restore a panel during that session without losing chart state.
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
- **News markers**: moved to T3.5 of the [symbol info roadmap](symbol-info-roadmap.md).
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

Settled with the user on 2026-09-30, and items 8–10 on 2026-10-02. Do not
reopen them without the user.

1. **Drawings (Phase 1) come before automatic levels (Phase 2).** Every later
   layer reuses the drawing layer's selection, hover and hide/lock machinery.
2. **Options recorder scope (C4.3):** SPY, QQQ and SPX, plus the underlyings of
   open positions and the top ten watchlist names, then (widened with the user
   on 2026-10-02) the strategy factory's core universe.
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
8. **Alerts live in the app, and the TradingView alert loop retires (C5.2)**
   after C5.1 has reached the phone. No Pine runtime, no Pine port.
9. **Strategy signal alerts are not chart alerts.** An alert that a strategy's
   setup fired belongs to the strategy factory's paper-trading step, runs that
   family's own code, and exists only for a candidate that passed the factory
   (`docs/strategy-factory.md`). This epic's alerts are levels and claim no edge.
10. **Use more screen space after the current drawing work.** The user requested
    a TradingView-like use of the available screen while Claude works on C1.2.
    C7.3/C7.4 are future `todo` items after C1.4; they do not change C1.2 or
    start its implementation. The compact shell precedes resizable geometry.
