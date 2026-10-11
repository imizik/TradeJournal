# Chart lens

The first screen must answer, in this order, without the trader parsing
every panel:

1. **Where am I?** Symbol, interval, session, data freshness, last price.
2. **What is happening?** Trend or range, volatility, volume, price vs VWAP.
3. **Where are the decision points?** Levels, prior day high/low/close,
   fills, plan anchors.
4. **What invalidates the idea?** The risk boundary stays readable over
   every overlay.
5. **What next?** Change interval, scrub, draw, review a fill — without
   losing context.

Candles get visual priority. Dense is not bad by itself; the question is
signal-to-noise **for the task**. `docs/charts-roadmap.md` (Progressive
disclosure) says the default should favor candles, VWAP, user levels, fills
and volume; the shipped defaults (`DEFAULT_SETTINGS` in
`frontend/lib/charts.ts`) currently show more. Changing a default only
affects setups without saved settings — the user's own chart keeps its
saved studies. Resetting saved settings changes their data: propose it as a
separate decision, never fold it into a defaults change.

## Tasks to walk (pick 2–3)

- **Intraday orientation (5m/1m):** read interval, session, price, last
  swing, VWAP relation, nearest level; switch timeframe, pan back, return to
  live (End / Alt+R).
- **Opening range / momentum:** find the range, the break, its volume and
  the invalidation; switch 1m↔5m↔15m — no unexplained pan or axis reset.
- **VWAP / mean reversion:** distance to VWAP and bands; is each study's
  period and session clear from its legend?
- **Multi-timeframe:** main chart plus two context charts; switch the active
  panel, compare linked vs independent ranges, come back to the start.
  Should one 5m, one 1h and one daily dominate rather than equal cards?
- **Post-trade review:** open a fill or trade on the chart; exact time,
  underlying vs option price, rationale; leave and come back.
- **Strategy Lab / Research:** hypothesis → parameters → sample count and
  matches → distribution and drawdown → matching candles → back to the
  experiment intact. Caveats (sample size, costs, lookahead, train/test)
  must be as visible as the headline result.

## What to look at

- What grabs the eye first: price, a legend, a color, or panel chrome?
- Is the main chart tall enough to separate overlapping levels? Why does the
  lower row get its current height?
- Do PDH/PDC/PDL, option levels, auto levels and price labels stay
  distinguishable when they nearly coincide?
- Does color mean one thing consistently (direction, average, risk, stale)?
  Color is never the only signal.
- Are values duplicated between the toolbar, each chart header and the dock?
- Are volume and RSI panes tall enough to read, or just occupying space?
- In small panels, do controls crowd the plot? Compact panels
  (`COMPACT_PANEL` in `frontend/lib/charts.ts`) already slim their studies —
  build on that, do not add a second compact mode.
- Is the session (pre/regular/post) obvious and correct after hours?

## Invariants every chart change keeps

- Exchange-time axis, sessions, weekends and holidays; instrument precision.
- Candles, studies, levels, drawings, fills, news and alert markers stay
  anchored through pan, zoom, resize and reload.
- Linked crosshair and ranges stay semantically aligned across panels.
- Reset-to-live, symbol/interval switch, drawing, selection, undo, maximize,
  Focus and saved layouts keep working.
- Price basis chip, split warnings, stale/live state and observed vs
  inferred labels stay visible.
- Changes on the live-update path keep incremental `.update()` vs
  `setData()` resets as they are unless that is the point of the change.

## A chart proposal includes

The baseline picture, the trader consequence (what becomes slower or easier
to misread), the low-risk first step (a default, a height, a tooltip, an
existing layout), the access path to anything hidden, and the scenario that
verifies it at desktop and in one dense-data state. No blanket rules like
"at most two indicators".
