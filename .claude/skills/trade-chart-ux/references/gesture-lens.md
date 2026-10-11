# Gesture lens: lag, zoom, pan, scroll, crosshair

"Zoom feels worse than TradingView" is strong evidence of friction, not of a
cause. Separate input mapping, chart-library behavior, render work, network
and live updates before proposing anything.

## What the agent can and cannot test

- **Can:** synthetic mouse/wheel/drag in Playwright or the browser pane,
  performance traces, React profiling, listener inspection, A/B toggles.
- **Cannot:** a physical Mac trackpad — two-finger pan inertia, pinch, the
  OS's gesture feel. A synthetic `mouse.wheel()` (used in
  `e2e/charts.spec.ts`) only proves wheel handling. Say so; do not imply
  more.
- `frontend/lib/chartPerformance.ts` (opt-in with
  `localStorage["tj:chart-performance"]="1"`, read
  `window.__tjChartPerformance.summary()`) times quotes, candles and symbol
  switches. It does not measure gesture-to-pixel latency, and a
  `requestAnimationFrame` timestamp is a paint opportunity, not a paint.

## A/B before any fix

Change one variable at a time; repeat each gesture 5–10 times. Time on the
production build (a browser test using `realisticPanels()`), not on the
sandbox's `next dev`; use the sandbox to reproduce what the user feels.

| Compare | Isolates |
|---|---|
| Focus (1 chart) vs five charts, same data and studies | Multi-chart render and sync fan-out |
| Linked ranges on vs off | Range propagation, recursive adjustments |
| Studies, auto levels, drawings sparse vs dense | Overlay and primitive painting |
| Live stream paused vs running | Updates competing with input |
| Shallow vs deep history | Data prep, history paging, `setData` resets |
| Mouse wheel vs real trackpad (user) | Event mapping vs native feel |

Read the result:

- One chart smooth, five janky → multi-chart work: sync fan-out, React
  commits across panels, resize, hidden panels.
- Both smooth but feels wrong → event mapping: scroll/scale options of the
  pinned `lightweight-charts` version, cursor anchoring, sensitivity.
- Both janky → main-thread trace: long tasks, series update path, overlays.
- Only historical pan → history paging, cache merge, logical range kept.
- Only crosshair scrub → crosshair broadcast and primitive hit-testing.
- Only with live data → update scheduling, not design.

Never ship a homegrown wheel or pinch engine first: test the library's own
options, then specify both trackpad and mouse regressions. Instrumentation,
if the user authorizes it, stays opt-in, local and removable.

## What the user tests (keep it to one short list)

When a change touches gestures, end with at most five steps the user can do
on the trackpad in a minute, each with what "good" looks like, e.g.:

1. Two-finger swipe left/right on the 5m chart: pans smoothly, page does not
   scroll.
2. Pinch in and out over a candle: zooms around that candle, no jump.
3. Pan far back until older bars load: the view does not jump.
4. Scrub the crosshair across all five charts: no stutter.
5. Same four steps in Focus: compare.

Record the answers as user-observed; they settle what synthetic tests
cannot.
