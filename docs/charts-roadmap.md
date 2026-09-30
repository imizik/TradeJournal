# Charts epic: roadmap

**What this is.** The working plan for turning `/charts` into the place trading
happens: a chart that feels as good to use as TradingView, with this journal's
own knowledge drawn on and beside it. Codex and Claude both work from this file.
It is a plan, not a specification. `docs/charts-workspace.md` describes what is
built today; this file says what comes next and why.

**Scope.** Chart UX first. Market intelligence (levels, options positioning,
your own trades) belongs here only where it appears **on or beside the chart**.
Journal analytics pages, options-flow feeds and AI move explanations are listed
under [Later](#later-not-this-epic) and stay out of scope until this epic's core
phases have shipped.

**Last reviewed:** 2026-09-30, after PR #83 (countdown, full screen, in-place
candle updates, Cmd/Ctrl+K search, linked time ranges).

## How to work from this file

1. Take the first item in the [status board](#status-board) whose status is
   `next`. Do not skip ahead unless the user asks.
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

## Status board

| ID | Item | Phase | Status |
|---|---|---|---|
| C0.1 | Market calendar: holidays and early closes in the countdown and session logic | 0 Foundations | next |
| C0.2 | Hot path: stop the whole workspace re-rendering every second and every tick | 0 Foundations | todo |
| C0.3 | Keep chart instances across symbol and interval switches | 0 Foundations | todo |
| C0.4 | Workspace saved on the server, so phone and desktop share levels and layout | 0 Foundations | todo |
| C0.5 | Hotkeys: timeframe keys, next/previous symbol, reset scale, back to realtime, `?` help | 0 Foundations | todo |
| C1.1 | Drawing layer: select, drag, delete, undo/redo; levels become draggable objects | 1 Direct manipulation | todo |
| C1.2 | Tools: horizontal ray, trendline, rectangle zone, text note; magnet to OHLC | 1 Direct manipulation | todo |
| C1.3 | Right-click (long-press on phone) context menu for chart, level and drawing | 1 Direct manipulation | todo |
| C1.4 | Layers panel: show, hide, lock and delete by group | 1 Direct manipulation | todo |
| C2.1 | Level engine: automatic session and structure levels (backend, pure) | 2 Levels | todo |
| C2.2 | Confluence: merge nearby levels into one labeled zone | 2 Levels | todo |
| C2.3 | Levels layer on the chart with hover card and test history | 2 Levels | todo |
| C2.4 | Time-of-day relative volume on the volume pane and legend | 2 Levels | todo |
| C2.5 | Earnings markers and an "earnings in N days" badge | 2 Levels | todo |
| C3.1 | Trade card: click a fill arrow for the trade, its P&L, MFE/MAE and entry context | 3 Journal on the chart | todo |
| C3.2 | Position lines: average entry, exits and open P&L on the chart | 3 Journal on the chart | todo |
| C3.3 | Historical chart mode: open any past trade on the chart | 3 Journal on the chart | todo |
| C4.1 | Options chain adapter and normalized models (Tradier) | 4 Options on the chart | todo |
| C4.2 | Positioning engine: OI, volume, walls, gamma concentration | 4 Options on the chart | todo |
| C4.3 | Positioning recorder: one daily snapshot, kept | 4 Options on the chart | todo |
| C4.4 | Options levels layer with filters | 4 Options on the chart | todo |
| C4.5 | Strike ladder side panel | 4 Options on the chart | todo |
| C5.1 | Level alerts delivered to the phone, drawn on the chart | 5 Alerts | todo |
| C6.1 | Replay: hide the future, step, play | 6 Review | todo |
| C6.2 | Trade / no-trade drills compared with the actual trade | 6 Review | todo |
| C7.1 | Per-panel symbol linking (for example SPY, QQQ and the traded name) | 7 Layouts | todo |
| C7.2 | Named saved layouts | 7 Layouts | todo |

## Ground truth this plan rests on

### How the user trades (journal, 2026-09-30)

- 1,589 trades; **1,519 are options** and 70 are stock. SPY is the most-traded
  underlying (184 trades), followed by a long tail of single names (CVNA, AMD,
  GOOG, COIN, MSFT, SNDK, MU, LLY, NVDA, TSLA …).
- Expiry mix at entry: 0DTE 378, 1–3 days 464, 4–7 days 184, 8–30 days 465.
  Short-dated options dominate, so **intraday levels and SPY/QQQ positioning
  matter more than weekly swing tools**.
- The open is the best time bucket (53% win rate against 45% midday).
- No futures are traded, and no connected provider carries futures. **NQ and ES
  are out of reach; QQQ, SPY and SPX stand in for them.**
- Webull is dormant by the user's choice (2026-09-24). Leave it out of plans
  until they ask.

### What the chart already does well

One private Tradier WebSocket feeds every tab; a 15-second REST refresh keeps
volume and studies honest. There are five linked charts, a linked crosshair and
optional linked time ranges, and the latest candle updates in place without
losing zoom. Also built: the next-bar countdown with named states, full screen,
Cmd/Ctrl+K search with recent symbols, EMA/VWAP/RSI, extended-hours shading,
fill arrows, saved horizontal levels, and a 390px phone layout with tests. The
data labels (source, age, delayed, stale) are already stricter than
TradingView's.

### What feels worse than TradingView

| Area | Today | Why it matters |
|---|---|---|
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

- Every fill has a `FillMarketContext` row (`backend/app/models.py`): VWAP and
  distance to it, premarket high/low, 5- and 15-minute opening ranges, prior-day
  high/low/close, gap, time-adjusted relative volume, chase and reclaim flags.
  The chart draws none of these levels. **The level engine (C2.1) must reuse
  these definitions** (`backend/app/engine/indicators.py`), so a level on the
  chart and the level stored with a trade can never disagree.
- Every closed trade has `TradePathMetrics`: MFE/MAE, time to each, exit
  efficiency, post-exit continuation and greeks attribution. The chart shows none
  of it (C3.1).
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

`lightweight-charts` v5 already provides panes, series and pane **primitives**
(custom canvas drawing with hit-testing), price- and time-scale drag,
double-click scale reset, pinch zoom and kinetic scrolling on touch. Everything
in this plan can be drawn with primitives: drawings, level zones, alert glyphs,
replay masks and options levels. What the library does **not** provide is a
drawing-tool framework (selection, handles, undo); C1.1 builds a small one. That
is a few hundred lines of our own code, against rewriting every chart feature on
a new library. TradingView's Advanced Charts library is restricted-license and
out of reason for a private single-user app. **Do not migrate.** Reconsider only
if a primitive cannot do something the user actually needs.

## Data this plan can rely on

Checked against the production account on 2026-09-30 with read-only calls,
after hours. Rows marked *unverified* need a regular-hours probe before any work
depends on them.

| Data | Tradier | Alpaca (free, IEX) | Polygon (Basic) | Use |
|---|---|---|---|---|
| Live equity trades | WebSocket, consolidated; one session per token (live since #82) | IEX only: one venue, wide quotes | — | Tradier |
| Intraday candles | About 10 days of minutes | IEX live; **historical SIP** (older than 15 minutes) | 5 calls/min | Tradier live; Alpaca SIP for history (C3.3, C2.4 baseline) |
| Daily candles | Years; dividend adjustment not guaranteed | Yes | Yes, cached for enrichment | Tradier (already) |
| Market calendar | `/v1/markets/calendar`: holidays and early closes (Thanksgiving closed, 11/27 closes 13:00) | `/v2/calendar` | — | Tradier (C0.1) |
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
- **No provider calls for navigation.** Search, hotkeys and layers never fetch.
  Only a symbol or interval change loads data, through the existing caches.
- **Mobile is a requirement.** Every interaction has a touch path (long-press
  for the context menu, tap to select, drag handles at least 24px) and a
  390px-wide test.

## Phases

Each phase is useful on its own. Stop after any of them and the chart is better.

### Phase 0 — Foundations (small, do first)

**C0.1 Market calendar.** Read Tradier's market calendar once a day in
`backend/app/engine/chart_feed.py`, cache it and send today's session hours with
the workspace response. `barClock()` in `frontend/lib/charts.ts` uses them.
*Done when:* a holiday reads "Market closed", an early-close day ends the regular
session at 13:00 and the last bar's countdown respects it, and browser tests
cover both with a fixture calendar.

**C0.2 Hot path.** Move the one-second clock into a small component each
countdown owns. Move streamed ticks into a store outside React (a
`useSyncExternalStore` module such as `frontend/lib/chartStore.ts`) that panels
subscribe to individually. Apply ticks per panel instead of rebuilding every
interval's bar array in `overlayLiveTicks`. *Done when:* a browser test counts
renders and shows a tick re-renders only the panels whose bars changed, and the
clock re-renders no chart.

**C0.3 Keep charts alive.** Create each chart once per panel. A symbol, interval
or RSI change swaps data and panes in place. While new data loads, keep the old
frame visible, dimmed and labeled "Loading NVDA…". *Done when:* switching symbols
never shows the empty loading card after the first load, and a test proves the
chart instance survives a switch.

**C0.4 Server-saved workspace.** Save `ChartSettings` (levels, watchlist,
intervals, indicators, layout, drawings once they exist) through a
workspace-style JSON endpoint modeled on `backend/app/routers/research.py`.
Use a revision check and keep `localStorage` as an offline fallback. On first
load, migrate any existing `localStorage` state. *Done when:* a level saved in
one browser context appears in another, and a stale revision is refused rather
than silently overwritten.

**C0.5 Hotkeys.** `1`, `3`, `5`, `15`, `30`, `H` (1h), `4` (4h), `D` and `W` set the
main interval; `Space` and `Shift+Space` step through the watchlist; `Alt+R`
resets scales; `End` returns to realtime; `?` shows a cheat sheet. Hotkeys are
ignored while typing in an input. *Done when:* each has a browser test and the
cheat sheet lists exactly the bindings that exist.

### Phase 1 — Direct manipulation

**C1.1 Drawing layer.** One pane primitive per chart renders every drawing and
hit-tests the pointer. Selecting a drawing shows its handles; dragging moves it;
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
day over the last 20 sessions, computed nightly per watchlist symbol from Alpaca
historical SIP minute bars (cached; about 390 numbers per symbol per day). Volume
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
*Done when:* the card renders seeded trade data in a browser test, and option
premiums are never drawn as underlying prices (existing rule).

**C3.2 Position lines.** For an open position in the charted underlying, draw
the average-entry line and label open P&L. Partial exits appear as markers.
*Done when:* scale-ins and scale-outs from seeded fills render as expected.

**C3.3 Historical chart mode.** "Open on chart" from a trade or fill page opens
`/charts` at that date and time with the trade's candles. Candles older than
Tradier's window come from Alpaca historical SIP minute bars through the
existing `backend/app/engine/alpaca.py` caches, labeled with their source. The
live stream is off, and a banner shows the date with a "Back to live" button.
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
  spot and the provider's IV, because the ORATS greeks are hourly and stale at
  the open. This is *calculated*, and unsigned by default.
- **Signed GEX, as an option only:** it needs a dealer-side assumption (the usual
  one: dealers long calls and short puts). That makes it *assumed*. The
  assumption appears in the label, the card and the code, and it is off by
  default.
- **Gamma flip, SPY/QQQ/SPX only:** signed GEX recomputed across hypothetical
  spot prices, with the zero crossing labeled "model estimate". Do not show it
  for single names, where open interest is too thin for the number to mean
  anything.

*Done when:* formulas are unit-tested against hand-computed fixtures, and the
assumptions are written in `docs/charts-workspace.md`.

**C4.3 Recorder.** Each weekday after the open, snapshot OI and volume per
strike for SPY, QQQ and SPX, plus the underlyings of open positions and the
top ten watchlist names (decided 2026-09-30), for expirations within 45 days. Store one row per
(underlying, expiration, day) with the strikes packed in a JSON array: about
1 GB per year at this scope, versus about 11 million rows if every strike were
its own row. This is a background job under the rules in
`docs/agent/background-jobs.md`, and it requires an Alembic revision. **Start
this early:** open-interest history cannot be backfilled, and every later
feature that compares positioning over time depends on it. *Done when:* the job
runs within its API budget, and restarting mid-run neither duplicates nor loses a
day.

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
interval. The backend evaluates alerts from the existing Tradier stream. Alerts
change the stream from demand-driven to "subscribed while the symbol has an
active alert", which is the one architectural change here; keep it inside the
single upstream connection. Alerts deliver through the existing ntfy topic and
appear on the chart as a bell glyph on the level, grayed once fired. *Done when:*
a fixture stream fires an alert exactly once per crossing, a restart does not
re-fire it, and the phone message names the symbol, the level and the price.
Compound conditions ("and relative volume above 2×") wait until users ask for
them.

### Phase 6 — Review on the chart

**C6.1 Replay.** Pick a date and time; candles after it are hidden. Step with
arrow keys or play at 1×–10×. Indicators and levels are computed only from
visible bars (no lookahead). Built on historical chart mode (C3.3).

**C6.2 Trade / no-trade drills.** At chosen moments, or automatically before
each of the user's real entries that day, replay pauses and asks: Trade, No
trade or Wait, and, for Trade, the direction, entry, stop and target. After the
reveal it compares the drill to the real trade and the actual path. It reports
facts ("entered 4 minutes later than in the drill"), never psychology it cannot
support. Drill results are stored so later reviews can compare them.

### Phase 7 — Layouts

**C7.1 Per-panel symbol link groups.** Each panel follows the main symbol or
holds its own (for example SPY, QQQ and the traded name). Crosshair and time
range stay linked by time. Each extra symbol costs its own chart-feed loads, so
cap it at three distinct symbols.

**C7.2 Named layouts.** Save and switch layouts such as "0DTE SPY" (1m | 5m |
15m) or "Names" (SPY | QQQ | ticker). Stored with the workspace (C0.4).

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
- Futures charts, Level 2, footprint or order-flow charts: no provider carries
  them.
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
3. **Per-panel symbols (C7.1) stay last.** All panels follow one symbol until
   Phases 0–6 have shipped.
