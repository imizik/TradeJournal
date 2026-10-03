"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode, LineStyle, TickMarkType, createSeriesMarkers } from "lightweight-charts";
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, Time, UTCTimestamp } from "lightweight-charts";
import { Expand, Link2, LocateFixed, Maximize2, Minimize2, Pin, Timer } from "lucide-react";
import { INTERVALS, INTERVAL_SECONDS, barAt, barChange, barClock, countdown, etTime, gapSeconds, intradayInterval, price, staleCandles } from "@/lib/charts";
import type { ChartBar, ChartCommand, ChartCommands, ChartJump, ChartPanelData, CrosshairLink, Indicators, Interval, MarketDay, PriceLevel, RangeLink } from "@/lib/charts";
import { useClock, useLivePanel } from "@/lib/chartStore";
import { DRAG_START, DrawingLayer, drawingShape, levelShape, MOUSE_SLOP, moveHandle, POINTS, roundPrice, shiftPoints, Timeline, TOUCH_SLOP } from "@/lib/drawings";
import type { Anchor, Drawing, DrawingKind, DrawingPatch, Shown, Tool, ToolStyle } from "@/lib/drawings";
import SelectionBar from "./SelectionBar";
import type { MenuRequest } from "./ChartMenu";
import type { LiveFeed } from "@/lib/chartStore";

const COLORS = { ema9: "#67d5eb", ema20: "#f4c66b", ema50: "#b494f5", ema200: "#ee86bd", vwap: "#f5e6a1" };
const tickFormats = {
  [TickMarkType.Year]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric" }),
  [TickMarkType.Month]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short" }),
  [TickMarkType.DayOfMonth]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }),
};
type Overlay = keyof typeof COLORS;
const MIN_BAR_SPACING = 2;
const NO_DRAWINGS: Drawing[] = [];
const CLOCK_TEXT = { paused: "Paused", delayed: "Delayed data", stale: "Stale data", closed: "Market closed", waiting: "Waiting for bars" };
// Whitespace alone still joins line segments in Lightweight Charts. Hide the
// outgoing segment at the session boundary. RTH timestamps always lie within
// one UTC date, even across New York DST changes.
function linePoint(bars: ChartBar[], index: number, name: Overlay) {
  const b = bars[index];
  if (b[name] === null) return { time: b.time as UTCTimestamp };
  const next = bars[index + 1];
  const gapAfter = name === "vwap" && next && (next.vwap === null || Math.floor(next.time / 86400) !== Math.floor(b.time / 86400));
  return { time: b.time as UTCTimestamp, value: b[name] as number, ...(gapAfter ? { color: "transparent" } : {}) };
}
const candlePoint = (b: ChartBar) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
const volumePoint = (b: ChartBar) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a43d" : "#ee617a3d" });
const shadePoint = (b: ChartBar) => ({ time: b.time as UTCTimestamp, value: 1, color: b.extended ? "#6b84bd10" : "transparent" });
const rsiPoint = (b: ChartBar) => b.rsi === null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: b.rsi };
/**
 * Reset: the latest candles at the opening zoom, every pane's price scale back
 * to automatic (dragging an axis turns it off). Realtime: the latest candle at
 * the current zoom.
 */
function moveView(chart: IChartApi, bars: number, main: boolean, command: ChartCommand) {
  const scale = chart.timeScale();
  if (command === "reset") {
    chart.panes().forEach((_, pane) => chart.priceScale("right", pane).applyOptions({ autoScale: true }));
    scale.setVisibleLogicalRange({ from: Math.max(0, bars - (main ? 110 : 65)), to: bars + 4 });
    return;
  }
  const range = scale.getVisibleLogicalRange();
  const width = range ? range.to - range.from : main ? 114 : 69;
  scale.setVisibleLogicalRange({ from: bars + 4 - width, to: bars + 4 });
}
/** Browser tests register a map here to inspect chart ranges; production never defines it. */
type ChartRegistry = Map<string, IChartApi>;
/** Browser tests register a map here to count each chart's committed renders; production never defines it. */
type RenderCounts = Map<string, number>;
/** Browser tests register a map here to read where drawings are drawn; production never defines it. */
type LayerRegistry = Map<string, DrawingLayer>;
/** What the chart says while a tool waits for a click; `second` is a two-point tool's second click. */
const PLACE_TEXT: Record<Tool, string> = { level: "Click a price to save a level", ray: "Click where the ray starts", trend: "Click the first point of the line",
  zone: "Click one corner of the zone", note: "Click where the note goes" };
const SECOND_TEXT: Partial<Record<Tool, string>> = { trend: "Click the second point", zone: "Click the opposite corner" };
/** A finger held this long without moving opens the chart menu (C1.3); moving further than `HOLD_SLOP` first is a pan or a crosshair scrub. */
const LONG_PRESS = 500;
const HOLD_SLOP = 10;
/** A jump to an item drawn before the loaded candles (C1.4) loads at most this many older pages, and gives up after this long. */
const JUMP_PAGES = 20;
const JUMP_MS = 20_000;
/** What the countdown needs besides the clock and the candles. */
export type ClockFeed = { session: "regular" | "extended"; market?: MarketDay | null; paused: boolean; delayed: boolean; failed: boolean; fetched?: number };

/**
 * The next-bar countdown owns the one-second clock, so a second passing
 * re-renders this label and never the chart around it.
 */
function Countdown({ label, main, interval, bars, feed }: { label: string; main: boolean; interval: Interval; bars: ChartBar[] | undefined; feed: ClockFeed }) {
  const { failed, fetched, ...rest } = feed;
  // Seconds while live, otherwise the named state: primitives, so an unchanged value skips the render.
  const value = useClock((now) => {
    const clock = barClock({ now, interval, bars, ...rest, stale: failed || staleCandles(now, fetched) });
    return clock?.state === "live" ? clock.remaining : clock?.state ?? null;
  });
  if (value === null) return null;
  const live = typeof value === "number";
  return <span role="timer" aria-label={`${label} next bar`} title={live ? "Time until this candle closes" : undefined}
    className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] ${main ? "mr-1" : "ml-auto"} ${live ? "bg-sky-400/10 text-sky-300" : value === "closed" || value === "paused" ? "bg-slate-800 text-slate-400" : "bg-amber-400/10 text-amber-300"}`}>
    <Timer size={11} />{live ? countdown(value) : CLOCK_TEXT[value]}</span>;
}

type Bundle = {
  chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">;
  shade: ISeriesApi<"Histogram">; rsi?: ISeriesApi<"Line">;
  lines: Record<Overlay, ISeriesApi<"Line">>; markers: ISeriesMarkersPluginApi<Time>; layer: DrawingLayer;
  /** The symbol and interval now drawn; a new one opens on its latest candles. */
  frame: string;
};

export default function PriceChart({ id, symbol, follows, onPickSymbol, interval, session, panel: rest, pending, notice, live, indicators, levels, drawings = NO_DRAWINGS, link, rangeLink, commands, linkRange = false, clock, height, main = false, tool = null, magnet = false, toolStyle, maximized, history, selected = null, showSelection = false, fresh = null, onNeedHistory, onRetryHistory, onVisibleRange, onDraw, onPlace, onSelect, onMove, onEditDrawing, onDelete, onMenu, onUnlock, onInterval, onFocus, onMaximize }: {
  id: string; symbol: string; interval: Interval; session: string; panel?: ChartPanelData; live: LiveFeed; indicators: Indicators; levels: PriceLevel[];
  /** This symbol's drawings on the chart's basis. */
  drawings?: Drawing[];
  /** A smaller chart either follows the main symbol or holds its own; the symbol opens a picker. */
  follows?: boolean; onPickSymbol?(): void;
  /** Set while this panel's next candles load ("Loading NVDA…"): the previous frame stays drawn, dimmed, until they arrive. */
  pending?: string | null;
  /** A limitation of what this chart shows, such as capped fill markers. */
  notice?: string | null;
  link: CrosshairLink; rangeLink: RangeLink; linkRange?: boolean; clock: ClockFeed;
  /** The canvas height. Without one the chart fills the box it is placed in (C7.3), and follows that box as it resizes. */
  height?: number;
  /** Alt+R and End from the workspace: every chart moves its own view. */
  commands: ChartCommands;
  main?: boolean;
  /** This chart covers the grid (C7.4); its button restores every chart. */
  maximized?: boolean;
  /** The tool the next click places with (the main chart only), the magnet, and the armed tool's style. */
  tool?: Tool | null; magnet?: boolean; toolStyle?: ToolStyle;
  onDraw(price: number): void;
  /** A drawing placed by click: its anchors on the chart's basis. */
  onPlace?(kind: DrawingKind, points: Anchor[]): void;
  /** The selected level or drawing, if it is this symbol's; every panel of the symbol highlights it. */
  selected?: string | null;
  /** The panel the item was selected on carries its bar (Delete, and a drawing's style). */
  showSelection?: boolean;
  /** A note just placed: its bar opens with the text ready to type. */
  fresh?: string | null;
  /** Pressing (mouse) or tapping (touch) an item selects it; empty chart space selects nothing. */
  onSelect?(id: string | null): void;
  /** A dragged level, dropped at a price on the chart's basis. */
  onMove?(id: string, price: number): void;
  /** A drawing dragged (new points, on the chart's basis) or restyled from its bar. */
  onEditDrawing?(id: string, patch: DrawingPatch): void;
  onDelete?(id: string): void;
  /** Right-click, or a long press on touch: the menu for the item there, or for the chart (C1.3). */
  onMenu?(request: MenuRequest): void;
  /** The selection bar's lock, on a locked item. */
  onUnlock?(id: string): void;
  history?: { loading: boolean; exhausted: boolean; warmup: string; issue: string | null; calendarNote?: string | null; adjustmentNote?: string | null; historyStart?: string | null };
  onNeedHistory?(before?: number): void; onRetryHistory?(): void; onVisibleRange?(range: { from: number; to: number }): void;
  onInterval(interval: Interval): void; onFocus?(): void; onMaximize?(): void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const bundle = useRef<Bundle | null>(null);
  const barsRef = useRef<ChartBar[]>([]);
  const resets = useRef(0);
  const linking = useRef(linkRange);
  // Programmatic range changes (data resets, applying a linked range) must not
  // be re-broadcast; only user pans and zooms drive the other charts.
  const quietUntil = useRef(0);
  const quiet = () => { quietUntil.current = performance.now() + 60; };
  const requestedGaps = useRef(new Set<number>());
  const actions = useRef({ tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, interval, pending: !!pending, selected, onSelect, onMove, onEditDrawing, onMenu, exhausted: !!history?.exhausted });
  // A jump waiting for older candles retries when they arrive (set by the chart's effect below).
  const retryJump = useRef<() => void>(() => {});
  // A two-point tool's first click, kept until the second; `second` re-renders the hint.
  const placing = useRef<{ kind: DrawingKind; first: Anchor } | null>(null);
  const [second, setSecond] = useState(false);
  const initial = useRef(true);
  const [hover, setHover] = useState<ChartBar | null>(null);
  // `rest` is the REST snapshot plus older history; streamed trades are applied
  // here, per panel, so a tick re-renders only the charts whose candles moved.
  const panel = useLivePanel(live, interval, rest);
  useEffect(() => {
    const renders = (window as typeof window & { __tjRenders?: RenderCounts }).__tjRenders;
    renders?.set(id, (renders.get(id) ?? 0) + 1);
  });
  const exhausted = !!history?.exhausted;
  useEffect(() => { actions.current = { tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, interval, pending: !!pending, selected, onSelect, onMove, onEditDrawing, onMenu, exhausted }; }, [tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, interval, pending, selected, onSelect, onMove, onEditDrawing, onMenu, exhausted]);
  useEffect(() => { linking.current = linkRange; }, [linkRange]);

  // One chart for the panel's lifetime. Symbol, interval, session and RSI
  // changes swap data and panes in place (below), so switching never blanks.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#10151e" }, textColor: "#8593a9", fontSize: 10,
        attributionLogo: true, panes: { separatorColor: "#27303d", separatorHoverColor: "#46576b" } },
      grid: { vertLines: { color: "#1b2532" }, horzLines: { color: "#1b2532" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#75859b", labelBackgroundColor: "#34455a" }, horzLine: { color: "#75859b", labelBackgroundColor: "#34455a" } },
      rightPriceScale: { borderColor: "#263141", minimumWidth: main ? 66 : 54, scaleMargins: { top: 0.10, bottom: 0.23 } },
      timeScale: { borderColor: "#263141", secondsVisible: false, rightOffset: 4, minBarSpacing: MIN_BAR_SPACING,
        tickMarkFormatter: (time: Time, kind: TickMarkType) => {
          if (typeof time !== "number") return null;
          return kind <= TickMarkType.DayOfMonth ? tickFormats[kind as keyof typeof tickFormats].format(time * 1000) : etTime(time);
        } },
    });
    const shade = chart.addSeries(HistogramSeries, { priceScaleId: "sessions", priceLineVisible: false, lastValueVisible: false,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }) });
    shade.priceScale().applyOptions({ scaleMargins: { top: 0, bottom: 0 } });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const lines = {} as Bundle["lines"];
    for (const name of Object.keys(COLORS) as Overlay[]) lines[name] = chart.addSeries(LineSeries, { color: COLORS[name], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const markers = createSeriesMarkers(candles, []);
    const timeline = new Timeline(() => barsRef.current, () => INTERVAL_SECONDS[actions.current.interval]);
    const layer = new DrawingLayer(timeline);
    candles.attachPrimitive(layer);
    bundle.current = { chart, candles, volume, shade, lines, markers, layer, frame: "" };
    const layers = (window as typeof window & { __tjDrawings?: LayerRegistry }).__tjDrawings;
    layers?.set(id, layer);
    // The magnet is on, or Cmd/Ctrl is held for this click or move.
    const magnetOn = (held: boolean) => actions.current.magnet || held;
    const modifier = (event?: { metaKey: boolean; ctrlKey: boolean }) => !!(event?.metaKey || event?.ctrlKey);
    const ghost = (kind: Tool, points: Anchor[]) => {
      const style = actions.current.toolStyle;
      layer.setPreview(kind === "level" ? levelShape({ id: "placing", price: points[0].price, label: "" })
        : { id: "placing", kind, points, label: kind === "note" ? "Note" : "", color: style?.color ?? "#9cc2ff", width: style?.width ?? 1 });
    };
    let syncing = false;
    const stopLink = link.listen((time, source) => {
      if (source === id || syncing) return;
      syncing = true;
      const bar = time === null ? undefined : barAt(barsRef.current, time);
      if (bar) chart.setCrosshairPosition(bar.close, bar.time as UTCTimestamp, candles);
      else chart.clearCrosshairPosition();
      setHover(bar ?? null);
      syncing = false;
    });
    chart.subscribeCrosshairMove((event) => {
      if (syncing) return;
      const time = typeof event.time === "number" ? event.time : null;
      setHover(time === null ? null : barAt(barsRef.current, time) ?? null);
      link.emit(time, id);
      // An armed tool previews what a click would place, where the magnet would put it.
      const kind = actions.current.tool;
      if (!kind || !main) return;
      const point = event.point && (event.paneIndex ?? 0) === 0 ? layer.anchorAt(event.point.x, event.point.y, magnetOn(modifier(event.sourceEvent))) : null;
      if (placing.current) { if (point) ghost(placing.current.kind, [placing.current.first, point]); }
      else if (point && kind !== "trend" && kind !== "zone") ghost(kind, [point]);
      else layer.setPreview(null);
    });
    // Levels and drawings drag in front of the chart: a press on one never
    // reaches the library, so the chart does not pan under it. A mouse drags
    // any item; a finger drags only the selected one, so panning across a
    // drawing never moves it. A tap selects (the click handler below). A press
    // on a selected drawing's handle moves that anchor; anywhere else on it
    // moves the whole drawing by whole bars, and with the magnet the anchor
    // nearest the press (`anchor`) snaps. `offset` keeps a level where it
    // was grabbed, so it moves by the drag instead of jumping to the pointer.
    type Drag = { id: string; handle: number | null; anchor: number; touch: number | null; from: { x: number; y: number }; base: Shown; offset: number; result: Shown | null; moved: boolean };
    let drag: Drag | null = null;
    let lastTouch = -Infinity;
    const local = (clientX: number, clientY: number) => { const box = element.getBoundingClientRect(); return { x: clientX - box.left, y: clientY - box.top }; };
    const onPlot = (x: number, y: number) => x >= 0 && x <= chart.timeScale().width() && y >= 0 && y <= chart.panes()[0].getHeight();
    const inPane = (y: number) => Math.max(0, Math.min(chart.panes()[0].getHeight(), y));
    const priceAt = (y: number) => {
      const value = candles.coordinateToPrice(inPane(y));
      return value === null || roundPrice(value) <= 0 ? null : roundPrice(value);
    };
    const grab = (x: number, y: number, touch: number | null) => {
      const now = actions.current;
      if (now.tool || now.pending || !onPlot(x, y)) return false;
      const hit = touch === null ? layer.hit(x, y, MOUSE_SLOP) : now.selected ? layer.hit(x, y, TOUCH_SLOP, now.selected) : null;
      const base = hit && layer.item(hit.id);
      // A locked item selects (the click handler) but never drags: the press pans the chart.
      if (!hit || !base || base.locked || !(base.kind === "level" ? now.onMove : now.onEditDrawing)) return false;
      const at = base.kind === "level" ? layer.y(hit.id) : y;
      if (at === null) return false;
      const near = (layer.anchors(hit.id) ?? []).reduce<{ index: number; distance: number }>((best, point, index) => {
        const distance = point ? Math.hypot(point.x - x, point.y - y) : Infinity;
        return distance < best.distance ? { index, distance } : best;
      }, { index: 0, distance: Infinity });
      drag = { id: hit.id, handle: hit.handle, anchor: near.index, touch, from: { x, y }, base, offset: at - y, result: null, moved: false };
      if (touch === null) now.onSelect?.(hit.id);
      window.addEventListener("keydown", onEscape, true);
      return true;
    };
    const follow = (x: number, y: number, held: boolean) => {
      if (!drag) return;
      if (!drag.moved && Math.hypot(x - drag.from.x, y - drag.from.y) < DRAG_START) return;
      drag.moved = true;
      const { base } = drag;
      const magnet = magnetOn(held);
      let points: Anchor[] | null = null;
      if (base.kind === "level") {
        const value = magnet ? layer.anchorAt(x, inPane(y + drag.offset), true)?.price ?? priceAt(y + drag.offset) : priceAt(y + drag.offset);
        points = value === null ? null : [{ time: 0, price: value }];
      } else if (drag.handle !== null) {
        const to = layer.anchorAt(x, inPane(y), magnet);
        points = to && moveHandle(base.points, base.kind, drag.handle, to);
      } else {
        const [from, to] = [layer.logicalAt(drag.from.x), layer.logicalAt(x)];
        const [was, now] = [candles.coordinateToPrice(drag.from.y), candles.coordinateToPrice(inPane(y))];
        if (from !== null && to !== null && was !== null && now !== null) {
          const bars = Math.round(to - from);
          const grabbed = base.points[drag.anchor];
          const at = timeline.toLogical(grabbed.time);
          // The magnet lands the grabbed anchor on its new bar's nearest open, high, low or close; the rest move with it.
          const snapped = magnet && at !== null ? layer.snapPrice(at + bars, grabbed.price + now - was) : null;
          points = shiftPoints(base.points, timeline, bars, snapped === null ? now - was : snapped - grabbed.price);
          if (points && snapped !== null) points[drag.anchor] = { ...points[drag.anchor], price: snapped };
        }
      }
      // A position with no valid (positive) price keeps the last one.
      if (!points) return;
      drag.result = { ...base, points };
      layer.setPreview(drag.result);
    };
    const finish = (commit: boolean) => {
      const done = drag;
      drag = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("keydown", onEscape, true);
      if (!done?.moved) return;
      // A drag that never reached a valid price saves nothing.
      if (!commit || !done.result) { layer.setPreview(null); return; }
      // The preview holds the new position until the saved item comes back as a prop.
      if (done.base.kind === "level") actions.current.onMove?.(done.id, done.result.points[0].price);
      else actions.current.onEditDrawing?.(done.id, { points: done.result.points });
      window.setTimeout(() => { if (!drag) layer.setPreview(null); }, 1000);
    };
    const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && drag) { event.preventDefault(); event.stopPropagation(); finish(false); } };
    // An armed tool reads its own clicks and taps. The library holds back a
    // second click that follows the first within its double-click time, which
    // would lose a quick second point of a trend line or zone. A press that
    // moves is a pan, not a placement.
    let press: { x: number; y: number; touch: number | null; held: boolean } | null = null;
    const place = (x: number, y: number, held: boolean) => {
      const now = actions.current;
      const kind = now.tool;
      if (!kind) return;
      // Placed at the middle of the nearest bar, or with the magnet at its nearest open, high, low or close.
      const point = layer.anchorAt(x, y, magnetOn(held));
      if (kind === "level") { const value = point?.price ?? priceAt(y); if (value !== null) now.onDraw(value); return; }
      if (!point) return;
      if (POINTS[kind] === 1) { now.onPlace?.(kind, [point]); return; }
      const first = placing.current?.kind === kind ? placing.current.first : null;
      if (!first) { placing.current = { kind, first: point }; setSecond(true); ghost(kind, [point, point]); return; }
      if (first.time === point.time && first.price === point.price) return; // a second click on the first point
      placing.current = null;
      setSecond(false);
      layer.setPreview(null);
      now.onPlace?.(kind, [first, point]);
    };
    const pressTool = (x: number, y: number, touch: number | null, held: boolean) => {
      if (!actions.current.tool || actions.current.pending || !onPlot(x, y)) return false;
      press = { x, y, touch, held };
      return true;
    };
    const release = (x: number, y: number, slop: number) => {
      const done = press;
      press = null;
      if (done && Math.hypot(x - done.x, y - done.y) < slop) place(done.x, done.y, done.held);
    };
    const onPlaceUp = (event: MouseEvent) => {
      window.removeEventListener("mouseup", onPlaceUp);
      const at = local(event.clientX, event.clientY);
      if (event.button === 0) release(at.x, at.y, DRAG_START);
    };
    // The chart menu (C1.3): the item under the pointer, or the chart with the
    // price there (the magnet applies, as it does to a placed level). A press
    // on a price or time scale, or the RSI pane, has no price.
    const openMenu = (clientX: number, clientY: number, touch: boolean) => {
      const now = actions.current;
      if (now.pending || !now.onMenu) return;
      const at = local(clientX, clientY);
      const plot = onPlot(at.x, at.y);
      const hit = plot && !now.tool ? layer.hit(at.x, at.y, touch ? TOUCH_SLOP : MOUSE_SLOP) : null;
      const value = plot ? layer.anchorAt(at.x, at.y, now.magnet)?.price ?? priceAt(at.y) : null;
      now.onMenu({ clientX, clientY, touch, price: value, id: hit?.id ?? null, reset: () => { quiet(); moveView(chart, barsRef.current.length, main, "reset"); } });
    };
    // A finger held still: its own timer, since browsers differ on whether a
    // long press fires `contextmenu` (Android does, iOS does not; whichever
    // comes first opens the menu). The library's own long tap (a crosshair
    // scrub) starts sooner and still works by moving before this fires; once
    // the menu opens, the lift is not a tap.
    let hold: { touch: number; x: number; y: number; timer: number } | null = null;
    let tapsOffUntil = 0;
    const dropHold = () => { if (hold) window.clearTimeout(hold.timer); hold = null; };
    const fireHold = () => {
      const done = hold;
      dropHold();
      if (!done) return;
      finish(false); // a selected item pressed for its menu does not drag
      tapsOffUntil = Infinity;
      openMenu(done.x, done.y, true);
    };
    const startHold = (touch: Touch) => {
      dropHold();
      if (actions.current.tool || actions.current.pending || !actions.current.onMenu) return;
      hold = { touch: touch.identifier, x: touch.clientX, y: touch.clientY, timer: window.setTimeout(fireHold, LONG_PRESS) };
    };
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault(); // never the browser's menu over the chart
      if (performance.now() - lastTouch < 1000) { fireHold(); return; }
      if (!drag) openMenu(event.clientX, event.clientY, false);
    };
    const onMouseMove = (event: MouseEvent) => { const at = local(event.clientX, event.clientY); follow(at.x, at.y, modifier(event)); };
    const onMouseUp = () => finish(true);
    const onMouseDown = (event: MouseEvent) => {
      if (event.button !== 0 || drag) return;
      const at = local(event.clientX, event.clientY);
      if (pressTool(at.x, at.y, null, modifier(event))) { window.addEventListener("mouseup", onPlaceUp); return; }
      if (!grab(at.x, at.y, null)) return;
      event.stopPropagation();
      event.preventDefault();
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    };
    const onTouchStart = (event: TouchEvent) => {
      lastTouch = performance.now();
      tapsOffUntil = 0;
      if (drag || event.touches.length !== 1) { dropHold(); if (drag) finish(false); return; }
      const touch = event.touches[0];
      startHold(touch);
      const at = local(touch.clientX, touch.clientY);
      if (pressTool(at.x, at.y, touch.identifier, false)) return;
      if (grab(at.x, at.y, touch.identifier)) event.stopPropagation();
    };
    const ours = (event: TouchEvent) => drag?.touch != null && [...event.changedTouches].find((touch) => touch.identifier === drag!.touch);
    const onTouchMove = (event: TouchEvent) => {
      const held = hold && [...event.changedTouches].find((touch) => touch.identifier === hold!.touch);
      if (held && Math.hypot(held.clientX - hold!.x, held.clientY - hold!.y) > HOLD_SLOP) dropHold();
      const touch = ours(event);
      if (!touch) return;
      event.preventDefault(); // the page must not scroll under a dragged item
      event.stopPropagation();
      const at = local(touch.clientX, touch.clientY);
      follow(at.x, at.y, false);
    };
    const onTouchEnd = (event: TouchEvent) => {
      lastTouch = performance.now();
      dropHold();
      if (tapsOffUntil === Infinity) tapsOffUntil = performance.now() + 500;
      const tapped = press?.touch != null && [...event.changedTouches].find((touch) => touch.identifier === press!.touch);
      if (tapped) { const at = local(tapped.clientX, tapped.clientY); if (event.type === "touchend") release(at.x, at.y, 10); else press = null; }
      if (ours(event)) { event.stopPropagation(); finish(event.type === "touchend"); }
    };
    element.addEventListener("mousedown", onMouseDown, true);
    element.addEventListener("touchstart", onTouchStart, { capture: true, passive: true });
    element.addEventListener("touchmove", onTouchMove, { capture: true, passive: false });
    element.addEventListener("touchend", onTouchEnd, true);
    element.addEventListener("touchcancel", onTouchEnd, true);
    element.addEventListener("contextmenu", onContextMenu, true);
    chart.subscribeClick((event) => {
      const now = actions.current;
      if (now.tool) return; // placing reads its own clicks (above)
      if (performance.now() < tapsOffUntil) return; // the lift after a long press
      if (!event.point || (event.paneIndex ?? 0) !== 0) { now.onSelect?.(null); return; }
      const touch = performance.now() - lastTouch < 1000;
      now.onSelect?.(layer.hit(event.point.x, event.point.y, touch ? TOUCH_SLOP : MOUSE_SLOP)?.id ?? null);
    });
    const stopRange = rangeLink.listen(id, (range) => {
      if (!linking.current || !barsRef.current.length) return;
      const step = INTERVAL_SECONDS[actions.current.interval];
      // Sync by time. A coarser chart keeps a readable minimum of candles
      // around the same moment instead of collapsing to one bar.
      const middle = (range.from + range.to) / 2;
      const half = Math.max((range.to - range.from) / 2, step * 6);
      const scale = chart.timeScale();
      const index = (t: number) => scale.timeToIndex(Math.round(t) as UTCTimestamp, true);
      const [from, centre, to] = [index(middle - half), index(middle), index(middle + half)];
      if (from === null || centre === null || to === null) return;
      // A fine interval on a narrow chart cannot always fit the whole span
      // (minimum bar spacing); it then shows as much as fits around the same
      // moment rather than snapping to its right edge.
      const width = Math.max(4, Math.min(to - from, scale.width() / MIN_BAR_SPACING));
      quiet();
      scale.setVisibleLogicalRange({ from: centre - width / 2, to: centre + width / 2 });
    });
    const onRange = (range: { from: Time; to: Time } | null) => {
      if (!linking.current || !range || performance.now() < quietUntil.current) return;
      if (typeof range.from === "number" && typeof range.to === "number") rangeLink.emit({ from: range.from, to: range.to }, id);
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(onRange);
    let rangeTimer: number | undefined;
    const onLogical = (range: { from: number; to: number } | null) => {
      // A frame waiting for its next candles never asks for older ones.
      if (!range || performance.now() < quietUntil.current || !barsRef.current.length || actions.current.pending) return;
      if (rangeTimer) window.clearTimeout(rangeTimer);
      rangeTimer = window.setTimeout(() => {
        const scale = chart.timeScale();
        const times = scale.getVisibleRange();
        if (times && typeof times.from === "number" && typeof times.to === "number")
          actions.current.onVisibleRange?.({ from: times.from, to: times.to });
        if (range.from < 100) actions.current.onNeedHistory?.();
        const bars = barsRef.current;
        for (let i = Math.max(0, Math.floor(range.from) - 100); i < Math.min(bars.length - 1, Math.ceil(range.to) + 100); i++) {
          if (bars[i + 1].time - bars[i].time > gapSeconds(actions.current.interval) && !requestedGaps.current.has(bars[i + 1].time)) {
            requestedGaps.current.add(bars[i + 1].time);
            actions.current.onNeedHistory?.(bars[i + 1].time);
            break;
          }
        }
      }, 120);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onLogical);
    // Each chart moves itself; a linked range must not carry one chart's reset to the others.
    const stopCommands = commands.listen((command) => {
      if (!barsRef.current.length) return;
      quiet();
      moveView(chart, barsRef.current.length, main, command);
    });
    // A jump from the layers panel (C1.4): centre the item's moments at the
    // current zoom (widened to fit a long drawing), then widen the price
    // scale if its prices are off it. One drawn before the loaded candles
    // asks for the page before them and tries again when it arrives.
    let jump: { target: ChartJump; pages: number; until: number; frame: string } | null = null;
    const fitPrices = (prices: number[]) => {
      const height = chart.panes()[0]?.getHeight() ?? 0;
      const [top, bottom] = [candles.coordinateToPrice(0), candles.coordinateToPrice(height)];
      if (!prices.length || top === null || bottom === null) return;
      const [low, high] = [Math.min(...prices), Math.max(...prices)];
      if (low >= bottom && high <= top) return;
      const pad = Math.max(high - low, top - bottom) * 0.08;
      candles.priceScale().setVisibleRange({ from: Math.min(bottom, low - pad), to: Math.max(top, high + pad) });
    };
    const tryJump = () => {
      const pending = jump;
      if (!pending || !barsRef.current.length) return;
      // A jump expires, and a new symbol or interval on the panel cancels it.
      if (performance.now() > pending.until || bundle.current?.frame !== pending.frame) { jump = null; return; }
      const { target } = pending;
      const scale = chart.timeScale();
      if (target.times.length) {
        const spots = target.times.map((time) => timeline.toLogical(time)).filter((spot): spot is number => spot !== null);
        if (!spots.length) return;
        const [first, last] = [Math.min(...spots), Math.max(...spots)];
        const range = scale.getVisibleLogicalRange();
        const width = range ? range.to - range.from : main ? 114 : 69;
        quiet();
        if (first < -0.5 && !actions.current.exhausted && pending.pages < JUMP_PAGES) {
          pending.pages += 1;
          scale.setVisibleLogicalRange({ from: -0.5, to: width - 0.5 });
          actions.current.onNeedHistory?.();
          return;
        }
        const span = Math.max(width, (last - first) * 1.4 + 8);
        const centre = (first + last) / 2;
        scale.setVisibleLogicalRange({ from: centre - span / 2, to: centre + span / 2 });
      }
      jump = null;
      // The price scale settles on the new candles over the next frames; then the prices must fit on it.
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => fitPrices(target.prices)));
    };
    retryJump.current = tryJump;
    const stopJumps = commands.listenJump((target) => {
      if (target.panel !== id) return;
      jump = { target, pages: 0, until: performance.now() + JUMP_MS, frame: bundle.current?.frame ?? "" };
      tryJump();
    });
    const registry = (window as typeof window & { __tjCharts?: ChartRegistry }).__tjCharts;
    registry?.set(id, chart);
    return () => {
      stopLink(); stopRange(); stopCommands(); stopJumps(); retryJump.current = () => {}; chart.timeScale().unsubscribeVisibleLogicalRangeChange(onLogical); if (rangeTimer) window.clearTimeout(rangeTimer); registry?.delete(id); layers?.delete(id);
      finish(false); dropHold();
      window.removeEventListener("mouseup", onPlaceUp); element.removeEventListener("contextmenu", onContextMenu, true);
      element.removeEventListener("mousedown", onMouseDown, true); element.removeEventListener("touchstart", onTouchStart, true); element.removeEventListener("touchmove", onTouchMove, true);
      element.removeEventListener("touchend", onTouchEnd, true); element.removeEventListener("touchcancel", onTouchEnd, true);
      markers.detach(); candles.detachPrimitive(layer); chart.remove(); bundle.current = null; barsRef.current = [];
    };
  }, [id, link, rangeLink, commands, main]);

  // RSI lives in a second pane, added and removed in place; the pane goes with its series.
  useEffect(() => {
    const current = bundle.current;
    if (!current || indicators.rsi === !!current.rsi) return;
    if (current.rsi) { current.chart.removeSeries(current.rsi); current.rsi = undefined; return; }
    const rsi = current.chart.addSeries(LineSeries, { color: "#b494f5", lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
    rsi.createPriceLine({ price: 70, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    rsi.createPriceLine({ price: 30, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    current.chart.panes()[1].setHeight(main ? 85 : 60);
    rsi.setData(barsRef.current.map(rsiPoint));
    current.rsi = rsi;
  }, [indicators.rsi, main]);

  useEffect(() => {
    const range = bundle.current?.chart.timeScale().getVisibleRange();
    if (main && linkRange && range) rangeLink.emit({ from: range.from as number, to: range.to as number }, id);
  }, [main, linkRange, rangeLink, id]);

  // A new symbol or interval opens on its latest candles, as a new chart would;
  // a session change keeps the viewport where it can. Both reset through setData.
  const dataKey = `${symbol}|${interval}|${session}`;
  const drawnKey = useRef("");
  useEffect(() => {
    const current = bundle.current;
    // While the next candles load, the previous frame stays drawn under the label.
    if (!current || pending) return;
    const bars = panel?.bars ?? [];
    const frame = `${symbol}|${interval}`;
    if (current.frame !== frame) {
      current.frame = frame;
      initial.current = true;
      requestedGaps.current.clear();
      const daily = !intradayInterval(interval);
      current.chart.applyOptions({ timeScale: { timeVisible: !daily },
        localization: { timeFormatter: (time: Time) => typeof time === "number" ? `${etTime(time, true)} ${daily ? "" : etTime(time) + " ET"}` : "" } });
    }
    if (container.current) {
      container.current.dataset.bars = String(bars.length);
      container.current.dataset.markers = String(panel?.markers.length ?? 0);
    }
    const prior = barsRef.current;
    barsRef.current = bars;
    const change = drawnKey.current === dataKey && current.candles.data().length ? barChange(prior, bars) : "reset";
    drawnKey.current = dataKey;
    if (change === "same") return;
    if (change !== "reset") {
      // Latest-bar path: series.update keeps zoom, scroll and crosshair, and
      // follows the live edge only when the user is already looking at it.
      const last = bars.length - 1;
      if (change === "append") for (const name of Object.keys(COLORS) as Overlay[]) current.lines[name].update(linePoint(bars, last - 1, name));
      current.candles.update(candlePoint(bars[last]));
      current.volume.update(volumePoint(bars[last]));
      current.shade.update(shadePoint(bars[last]));
      for (const name of Object.keys(COLORS) as Overlay[]) current.lines[name].update(linePoint(bars, last, name));
      current.rsi?.update(rsiPoint(bars[last]));
      return;
    }
    resets.current += 1;
    if (container.current) container.current.dataset.resets = String(resets.current);
    const range = current.chart.timeScale().getVisibleRange();
    const logical = current.chart.timeScale().getVisibleLogicalRange();
    const following = !logical || logical.to >= (current.candles.data().length - 3);
    const anchorIndex = logical ? Math.max(0, Math.min(prior.length - 1, Math.ceil(logical.from))) : 0;
    const anchorTime = prior[anchorIndex]?.time;
    const movedTo = anchorTime === undefined ? -1 : bars.findIndex((b) => b.time === anchorTime);
    const moved = movedTo - anchorIndex;
    quiet();
    current.candles.setData(bars.map(candlePoint));
    current.volume.setData(bars.map(volumePoint));
    current.shade.setData(bars.map(shadePoint));
    for (const name of Object.keys(COLORS) as Overlay[]) current.lines[name].setData(bars.map((_, index) => linePoint(bars, index, name)));
    current.rsi?.setData(bars.map(rsiPoint));
    if (bars.length && (initial.current || !prior.length)) {
      current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - (main ? 110 : 65)), to: bars.length + 4 });
      initial.current = false;
    } else if (bars.length && following && logical) {
      const width = logical.to - logical.from;
      current.chart.timeScale().setVisibleLogicalRange({ from: bars.length + 4 - width, to: bars.length + 4 });
    } else if (logical && movedTo >= 0) current.chart.timeScale().setVisibleLogicalRange({ from: logical.from + moved, to: logical.to + moved });
    else if (bars.length && range) current.chart.timeScale().setVisibleRange(range);
    retryJump.current();
  }, [panel, pending, dataKey, symbol, interval, main]);

  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    current.volume.applyOptions({ visible: indicators.volume });
    for (const name of Object.keys(COLORS) as Overlay[]) current.lines[name].applyOptions({ visible: indicators[name] });
  }, [indicators]);

  const markers = panel?.markers;
  useEffect(() => {
    if (pending) return;
    bundle.current?.markers.setMarkers(indicators.fills ? (markers ?? []).map((m) => ({ time: m.time as UTCTimestamp,
      position: m.buy ? "belowBar" as const : "aboveBar" as const, shape: m.buy ? "arrowUp" as const : "arrowDown" as const,
      color: m.buy ? "#67d5eb" : "#f4c66b", text: main ? m.label : "", id: m.id })) : []);
  }, [markers, pending, indicators.fills, main]);

  useEffect(() => {
    const current = bundle.current;
    if (!current || pending) return; // the next symbol's levels and drawings wait for its candles
    current.layer.set([...levels.map(levelShape), ...drawings.map(drawingShape)], selected, main);
    if (container.current) {
      container.current.dataset.levels = levels.map((level) => level.price.toFixed(2)).join(",");
      container.current.dataset.drawings = drawings.map((drawing) => drawing.kind).join(",");
    }
  }, [levels, drawings, pending, main, selected]);
  // Arming, switching or dropping a tool forgets a half-placed drawing.
  useEffect(() => {
    bundle.current?.layer.setInteractive(!tool);
    if (!placing.current && !tool) return;
    placing.current = null;
    setSecond(false);
    bundle.current?.layer.setPreview(null);
  }, [tool]);

  const bar = (hover && barAt(panel?.bars ?? [], hover.time)) || panel?.bars.at(-1);
  const chosenLevel = selected ? levels.find((level) => level.id === selected) : undefined;
  const chosenDrawing = selected ? drawings.find((drawing) => drawing.id === selected) : undefined;
  // Main chart: in the header. Smaller charts: end of the values row, so the
  // header keeps room for its controls at quarter width.
  const timer = !pending && intradayInterval(interval) && <Countdown label={main ? "Main" : id} main={main} interval={interval} bars={panel?.bars} feed={clock} />;
  return (
    // isolate: the chart library gives its pane-resize handle z-index 50. Without a stacking
    // context here that handle outranks the app's overlays (the Sync drawer's backdrop is 40).
    <section aria-label={`${symbol} ${interval} chart`} className={`relative isolate min-w-0 overflow-hidden rounded-lg border bg-[#10151e] ${height === undefined ? "flex min-h-0 flex-1 flex-col" : ""} ${main ? "border-slate-600/60" : "border-slate-700/50"}`}>
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-slate-700/40 px-3">
        {/* A narrow chart (C7.4's dividers allow 160px) clips its symbol and interval, never its buttons. */}
        <div className="flex min-w-0 items-center gap-2 overflow-hidden text-xs">{onPickSymbol
          ? <button aria-label={`${id} symbol`} title={follows ? "Follows the main symbol. Choose a symbol for this chart." : "Holds its own symbol. Change it, or follow the main symbol."} onClick={onPickSymbol}
            className={`-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 font-semibold tracking-wide hover:bg-slate-800 ${follows ? "text-slate-200" : "text-sky-200"}`}>
            {symbol}{follows ? <Link2 size={11} className="text-slate-500" aria-hidden /> : <Pin size={11} className="text-sky-300" aria-hidden />}</button>
          : <span className="font-semibold tracking-wide text-slate-200">{symbol}</span>}
          <select aria-label={`${main ? "Main" : id} interval`} value={interval} onChange={(e) => onInterval(e.target.value as Interval)} className="rounded border-0 bg-slate-800 px-1.5 py-1 text-[11px] text-slate-300">
            {INTERVALS.map((i) => <option key={i}>{i}</option>)}
          </select>
          {main && <span className="hidden text-[10px] text-slate-500 sm:inline">{interval === "1D" || interval === "1W" ? "REGULAR SESSION" : "NEW YORK"}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {main && timer}
          <button title="Latest candles, automatic price scale (Alt+R does every chart)" aria-label={`Latest candles ${id}`} onClick={() => { if (bundle.current) moveView(bundle.current.chart, barsRef.current.length, main, "reset"); }} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><LocateFixed size={13} /></button>
          {onMaximize && <button title={maximized ? "Restore every chart (Esc)" : "Maximize this chart for now; Esc restores"} aria-label={maximized ? "Restore charts" : `Maximize ${interval} chart`} onClick={onMaximize} className={`rounded p-1.5 hover:bg-slate-800 hover:text-slate-200 ${maximized ? "text-sky-300" : "text-slate-500"}`}>{maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button>}
          {onFocus && <button title="Make main chart" aria-label={`Focus ${interval} chart`} onClick={onFocus} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><Expand size={13} /></button>}
        </div>
      </div>
      <div className="flex h-6 min-w-0 shrink-0 items-center gap-2 whitespace-nowrap px-3 font-mono text-[10px] text-slate-500">
        <div className="flex min-w-0 items-center gap-2 overflow-hidden" aria-label={`${id} candle values`}>
        {pending ? null : bar ? <>{main && <><span>O <span className="text-slate-300">{price(bar.open)}</span></span><span>H <span className="text-slate-300">{price(bar.high)}</span></span><span>L <span className="text-slate-300">{price(bar.low)}</span></span></>}<span>C <span className={bar.close >= bar.open ? "text-emerald-400" : "text-rose-400"}>{price(bar.close)}</span></span>{!main && <span>Vol {bar.volumePending ? "pending" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(bar.volume)}</span>}<span title={bar.source === "alpaca_sip" ? "Alpaca SIP minutes, stored raw. The price basis chip says how splits are shown." : "Tradier"}>{bar.source === "alpaca_sip" ? "SIP" : "Tradier"}</span></> : <span>No candles in this window</span>}
        </div>
        {!main && timer}
      </div>
      {main && <div className="flex min-h-5 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-1 font-mono text-[10px]">
        {(Object.keys(COLORS) as Overlay[]).filter((key) => indicators[key]).map((key) => <span key={key} style={{ color: COLORS[key] }}>{key.toUpperCase()} {price(bar?.[key])}</span>)}
        {indicators.rsi && <span className="text-violet-300">RSI {price(bar?.rsi)}</span>}
      </div>}
      <div className={height === undefined ? "relative min-h-0 flex-1" : "relative"}>
        <div ref={container} data-testid={`canvas-${id}`} data-pending={pending ? "" : undefined} data-selected={selected ?? undefined} style={height === undefined ? undefined : { height }} className={`select-none transition-opacity [-webkit-touch-callout:none] ${height === undefined ? "absolute inset-0" : ""} ${tool ? "cursor-crosshair" : ""} ${pending ? "opacity-40" : ""}`} />
        {(chosenLevel || chosenDrawing) && showSelection && !pending && <SelectionBar key={`${selected}|${chosenDrawing?.text ?? ""}`} panel={id} level={chosenLevel} drawing={chosenDrawing} focusText={fresh === selected}
          onDelete={() => onDelete?.(selected!)} onDeselect={() => onSelect?.(null)} onEdit={(patch) => onEditDrawing?.(selected!, patch)} onUnlock={() => onUnlock?.(selected!)} />}
      </div>
      {history && (history.loading || history.issue || history.warmup === "insufficient" || history.calendarNote || history.adjustmentNote || (history.exhausted && history.historyStart)) && <div className="flex shrink-0 items-center gap-2 px-3 py-1 text-[10px] text-amber-300" role="status">
        {history.loading ? "Loading older candles and indicator warmup…" : history.issue ? history.issue : history.warmup === "insufficient" ? "Earlier indicator history is insufficient." : [history.exhausted && history.historyStart ? `Tradier daily history starts ${history.historyStart}.` : null, history.calendarNote, history.adjustmentNote].filter(Boolean).join(" ")}
        {history.issue && <button className="underline" onClick={onRetryHistory}>Retry history</button>}
      </div>}
      {notice && !pending && <p className="shrink-0 px-3 py-1 text-[10px] text-amber-300">{notice}</p>}
      {pending ? <div role="status" className="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center"><span className="rounded-md border border-slate-700/60 bg-[#10151e]/90 px-3 py-1.5 text-sm text-slate-200">{pending}</span></div>
        : !panel?.bars.length && <div className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-sm text-slate-500">No candles available</div>}
      {tool && <div role="status" aria-label="Drawing tool" className="pointer-events-none absolute left-3 top-24 rounded bg-blue-500/90 px-3 py-1.5 text-xs text-white">{(second && SECOND_TEXT[tool]) || PLACE_TEXT[tool]}</div>}
    </section>
  );
}
