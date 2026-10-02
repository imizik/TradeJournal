"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode, LineStyle, TickMarkType, createSeriesMarkers } from "lightweight-charts";
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, Time, UTCTimestamp } from "lightweight-charts";
import { Expand, Link2, LocateFixed, Maximize2, Minimize2, Pin, Timer, Trash2, X } from "lucide-react";
import { INTERVALS, INTERVAL_SECONDS, barAt, barChange, barClock, countdown, etTime, gapSeconds, intradayInterval, price, staleCandles } from "@/lib/charts";
import type { ChartBar, ChartCommand, ChartCommands, ChartPanelData, CrosshairLink, Indicators, Interval, MarketDay, PriceLevel, RangeLink } from "@/lib/charts";
import { useClock, useLivePanel } from "@/lib/chartStore";
import { DRAG_START, DrawingLayer, MOUSE_SLOP, TOUCH_SLOP } from "@/lib/drawings";
import type { LiveFeed } from "@/lib/chartStore";

const COLORS = { ema9: "#67d5eb", ema20: "#f4c66b", ema50: "#b494f5", ema200: "#ee86bd", vwap: "#f5e6a1" };
const tickFormats = {
  [TickMarkType.Year]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric" }),
  [TickMarkType.Month]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short" }),
  [TickMarkType.DayOfMonth]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }),
};
type Overlay = keyof typeof COLORS;
const MIN_BAR_SPACING = 2;
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
  lines: Record<Overlay, ISeriesApi<"Line">>; markers: ISeriesMarkersPluginApi<Time>; drawings: DrawingLayer;
  /** The symbol and interval now drawn; a new one opens on its latest candles. */
  frame: string;
};

export default function PriceChart({ id, symbol, follows, onPickSymbol, interval, session, panel: rest, pending, notice, live, indicators, levels, link, rangeLink, commands, linkRange = false, clock, height, main = false, drawing = false, expanded, history, selected = null, showSelection = false, onNeedHistory, onRetryHistory, onVisibleRange, onDraw, onSelect, onMove, onDelete, onInterval, onFocus, onExpand }: {
  id: string; symbol: string; interval: Interval; session: string; panel?: ChartPanelData; live: LiveFeed; indicators: Indicators; levels: PriceLevel[];
  /** A smaller chart either follows the main symbol or holds its own; the symbol opens a picker. */
  follows?: boolean; onPickSymbol?(): void;
  /** Set while this panel's next candles load ("Loading NVDA…"): the previous frame stays drawn, dimmed, until they arrive. */
  pending?: string | null;
  /** A limitation of what this chart shows, such as capped fill markers. */
  notice?: string | null;
  link: CrosshairLink; rangeLink: RangeLink; linkRange?: boolean; clock: ClockFeed; height: number;
  /** Alt+R and End from the workspace: every chart moves its own view. */
  commands: ChartCommands;
  main?: boolean; drawing?: boolean; expanded?: boolean; onDraw(price: number): void;
  /** The selected level, if it is this symbol's; every panel of the symbol highlights it. */
  selected?: string | null;
  /** The panel the level was selected on carries its Delete bar. */
  showSelection?: boolean;
  /** Pressing (mouse) or tapping (touch) a level selects it; empty chart space selects nothing. */
  onSelect?(id: string | null): void;
  /** A dragged level, dropped at a price on the chart's basis. */
  onMove?(id: string, price: number): void;
  onDelete?(id: string): void;
  history?: { loading: boolean; exhausted: boolean; warmup: string; issue: string | null; calendarNote?: string | null; adjustmentNote?: string | null; historyStart?: string | null };
  onNeedHistory?(before?: number): void; onRetryHistory?(): void; onVisibleRange?(range: { from: number; to: number }): void;
  onInterval(interval: Interval): void; onFocus?(): void; onExpand?(): void;
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
  const actions = useRef({ drawing, onDraw, onNeedHistory, onVisibleRange, interval, pending: !!pending, selected, onSelect, onMove });
  const initial = useRef(true);
  const [hover, setHover] = useState<ChartBar | null>(null);
  // `rest` is the REST snapshot plus older history; streamed trades are applied
  // here, per panel, so a tick re-renders only the charts whose candles moved.
  const panel = useLivePanel(live, interval, rest);
  useEffect(() => {
    const renders = (window as typeof window & { __tjRenders?: RenderCounts }).__tjRenders;
    renders?.set(id, (renders.get(id) ?? 0) + 1);
  });
  useEffect(() => { actions.current = { drawing, onDraw, onNeedHistory, onVisibleRange, interval, pending: !!pending, selected, onSelect, onMove }; }, [drawing, onDraw, onNeedHistory, onVisibleRange, interval, pending, selected, onSelect, onMove]);
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
    const drawings = new DrawingLayer();
    candles.attachPrimitive(drawings);
    bundle.current = { chart, candles, volume, shade, lines, markers, drawings, frame: "" };
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
    });
    // Levels drag in front of the chart: a press on one never reaches the
    // library, so the chart does not pan under it. A mouse drags any level; a
    // finger drags only the selected one, so panning across a level never
    // moves it. A tap selects (the click handler below). `offset` keeps the
    // line where it was grabbed, so it moves by the drag instead of jumping to the pointer.
    let drag: { id: string; touch: number | null; from: number; offset: number; price: number | null; moved: boolean } | null = null;
    let lastTouch = -Infinity;
    const local = (clientX: number, clientY: number) => { const box = element.getBoundingClientRect(); return { x: clientX - box.left, y: clientY - box.top }; };
    const onPlot = (x: number, y: number) => x >= 0 && x <= chart.timeScale().width() && y >= 0 && y <= chart.panes()[0].getHeight();
    const level = (y: number) => {
      const value = candles.coordinateToPrice(Math.max(0, Math.min(chart.panes()[0].getHeight(), y)));
      return value === null || value <= 0 ? null : Math.round(value * 100) / 100;
    };
    const grab = (x: number, y: number, touch: number | null) => {
      const now = actions.current;
      if (now.drawing || now.pending || !now.onMove || !onPlot(x, y)) return false;
      const id = touch === null ? drawings.hit(y, MOUSE_SLOP) : now.selected ? drawings.hit(y, TOUCH_SLOP, now.selected) : null;
      const at = id === null ? null : drawings.y(id);
      if (id === null || at === null) return false;
      drag = { id, touch, from: y, offset: at - y, price: null, moved: false };
      if (touch === null) now.onSelect?.(id);
      window.addEventListener("keydown", onEscape, true);
      return true;
    };
    const follow = (y: number) => {
      if (!drag) return;
      if (!drag.moved && Math.abs(y - drag.from) < DRAG_START) return;
      drag.moved = true;
      const value = level(y + drag.offset);
      if (value !== null) { drag.price = value; drawings.setPreview({ id: drag.id, price: value }); }
    };
    const finish = (commit: boolean) => {
      const done = drag;
      drag = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("keydown", onEscape, true);
      if (!done?.moved) return;
      // A drag that never reached a valid (positive) price saves nothing.
      if (!commit || done.price === null) { drawings.setPreview(null); return; }
      // The preview holds the new price until the saved level comes back as a prop.
      actions.current.onMove?.(done.id, done.price);
      window.setTimeout(() => { if (!drag) drawings.setPreview(null); }, 1000);
    };
    const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && drag) { event.preventDefault(); event.stopPropagation(); finish(false); } };
    const onMouseMove = (event: MouseEvent) => follow(local(event.clientX, event.clientY).y);
    const onMouseUp = () => finish(true);
    const onMouseDown = (event: MouseEvent) => {
      if (event.button !== 0 || drag) return;
      const at = local(event.clientX, event.clientY);
      if (!grab(at.x, at.y, null)) return;
      event.stopPropagation();
      event.preventDefault();
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    };
    const onTouchStart = (event: TouchEvent) => {
      lastTouch = performance.now();
      if (drag || event.touches.length !== 1) { if (drag) finish(false); return; }
      const touch = event.touches[0];
      const at = local(touch.clientX, touch.clientY);
      if (grab(at.x, at.y, touch.identifier)) event.stopPropagation();
    };
    const ours = (event: TouchEvent) => drag?.touch != null && [...event.changedTouches].find((touch) => touch.identifier === drag!.touch);
    const onTouchMove = (event: TouchEvent) => {
      const touch = ours(event);
      if (!touch) return;
      event.preventDefault(); // the page must not scroll under a dragged level
      event.stopPropagation();
      follow(local(touch.clientX, touch.clientY).y);
    };
    const onTouchEnd = (event: TouchEvent) => { if (ours(event)) { event.stopPropagation(); finish(event.type === "touchend"); } };
    element.addEventListener("mousedown", onMouseDown, true);
    element.addEventListener("touchstart", onTouchStart, { capture: true, passive: true });
    element.addEventListener("touchmove", onTouchMove, { capture: true, passive: false });
    element.addEventListener("touchend", onTouchEnd, true);
    element.addEventListener("touchcancel", onTouchEnd, true);
    chart.subscribeClick((event) => {
      const now = actions.current;
      if (!event.point || (event.paneIndex ?? 0) !== 0) { if (!now.drawing) now.onSelect?.(null); return; }
      if (now.drawing) {
        const value = candles.coordinateToPrice(event.point.y);
        if (value !== null && value > 0) now.onDraw(Math.round(value * 100) / 100);
        return;
      }
      const touch = performance.now() - lastTouch < 1000;
      now.onSelect?.(drawings.hit(event.point.y, touch ? TOUCH_SLOP : MOUSE_SLOP));
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
    const registry = (window as typeof window & { __tjCharts?: ChartRegistry }).__tjCharts;
    registry?.set(id, chart);
    return () => {
      stopLink(); stopRange(); stopCommands(); chart.timeScale().unsubscribeVisibleLogicalRangeChange(onLogical); if (rangeTimer) window.clearTimeout(rangeTimer); registry?.delete(id);
      finish(false);
      element.removeEventListener("mousedown", onMouseDown, true); element.removeEventListener("touchstart", onTouchStart, true); element.removeEventListener("touchmove", onTouchMove, true);
      element.removeEventListener("touchend", onTouchEnd, true); element.removeEventListener("touchcancel", onTouchEnd, true);
      markers.detach(); candles.detachPrimitive(drawings); chart.remove(); bundle.current = null; barsRef.current = [];
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
    if (!current || pending) return; // the next symbol's levels wait for its candles
    current.drawings.set(levels.map(({ id, price, label }) => ({ id, price, label })), selected, main);
    if (container.current) container.current.dataset.levels = levels.map((level) => level.price.toFixed(2)).join(",");
  }, [levels, pending, main, selected]);
  useEffect(() => { bundle.current?.drawings.setInteractive(!drawing); }, [drawing]);

  const bar = (hover && barAt(panel?.bars ?? [], hover.time)) || panel?.bars.at(-1);
  const chosen = selected ? levels.find((level) => level.id === selected) : undefined;
  // Main chart: in the header. Smaller charts: end of the values row, so the
  // header keeps room for its controls at quarter width.
  const timer = !pending && intradayInterval(interval) && <Countdown label={main ? "Main" : id} main={main} interval={interval} bars={panel?.bars} feed={clock} />;
  return (
    // isolate: the chart library gives its pane-resize handle z-index 50. Without a stacking
    // context here that handle outranks the app's overlays (the Sync drawer's backdrop is 40).
    <section aria-label={`${symbol} ${interval} chart`} className={`relative isolate min-w-0 overflow-hidden rounded-lg border bg-[#10151e] ${main ? "border-slate-600/60" : "border-slate-700/50"}`}>
      <div className="flex h-10 items-center justify-between gap-2 border-b border-slate-700/40 px-3">
        <div className="flex items-center gap-2 text-xs">{onPickSymbol
          ? <button aria-label={`${id} symbol`} title={follows ? "Follows the main symbol. Choose a symbol for this chart." : "Holds its own symbol. Change it, or follow the main symbol."} onClick={onPickSymbol}
            className={`-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 font-semibold tracking-wide hover:bg-slate-800 ${follows ? "text-slate-200" : "text-sky-200"}`}>
            {symbol}{follows ? <Link2 size={11} className="text-slate-500" aria-hidden /> : <Pin size={11} className="text-sky-300" aria-hidden />}</button>
          : <span className="font-semibold tracking-wide text-slate-200">{symbol}</span>}
          <select aria-label={`${main ? "Main" : id} interval`} value={interval} onChange={(e) => onInterval(e.target.value as Interval)} className="rounded border-0 bg-slate-800 px-1.5 py-1 text-[11px] text-slate-300">
            {INTERVALS.map((i) => <option key={i}>{i}</option>)}
          </select>
          {main && <span className="hidden text-[10px] text-slate-500 sm:inline">{interval === "1D" || interval === "1W" ? "REGULAR SESSION" : "NEW YORK"}</span>}
        </div>
        <div className="flex min-w-0 items-center gap-1">
          {main && timer}
          <button title="Latest candles, automatic price scale (Alt+R does every chart)" aria-label={`Latest candles ${id}`} onClick={() => { if (bundle.current) moveView(bundle.current.chart, barsRef.current.length, main, "reset"); }} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><LocateFixed size={13} /></button>
          {onExpand && <button title={expanded ? "Shrink chart" : "Expand chart"} aria-label={`${expanded ? "Shrink" : "Expand"} ${interval} chart`} aria-pressed={!!expanded} onClick={onExpand} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200">{expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button>}
          {onFocus && <button title="Make main chart" aria-label={`Focus ${interval} chart`} onClick={onFocus} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><Expand size={13} /></button>}
        </div>
      </div>
      <div className="flex h-6 min-w-0 items-center gap-2 whitespace-nowrap px-3 font-mono text-[10px] text-slate-500">
        <div className="flex min-w-0 items-center gap-2 overflow-hidden" aria-label={`${id} candle values`}>
        {pending ? null : bar ? <>{main && <><span>O <span className="text-slate-300">{price(bar.open)}</span></span><span>H <span className="text-slate-300">{price(bar.high)}</span></span><span>L <span className="text-slate-300">{price(bar.low)}</span></span></>}<span>C <span className={bar.close >= bar.open ? "text-emerald-400" : "text-rose-400"}>{price(bar.close)}</span></span>{!main && <span>Vol {bar.volumePending ? "pending" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(bar.volume)}</span>}<span title={bar.source === "alpaca_sip" ? "Alpaca SIP minutes, stored raw. The price basis chip says how splits are shown." : "Tradier"}>{bar.source === "alpaca_sip" ? "SIP" : "Tradier"}</span></> : <span>No candles in this window</span>}
        </div>
        {!main && timer}
      </div>
      {main && <div className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-1 font-mono text-[10px]">
        {(Object.keys(COLORS) as Overlay[]).filter((key) => indicators[key]).map((key) => <span key={key} style={{ color: COLORS[key] }}>{key.toUpperCase()} {price(bar?.[key])}</span>)}
        {indicators.rsi && <span className="text-violet-300">RSI {price(bar?.rsi)}</span>}
      </div>}
      <div className="relative">
        <div ref={container} data-testid={`canvas-${id}`} data-pending={pending ? "" : undefined} data-selected={selected ?? undefined} style={{ height }} className={`transition-opacity ${drawing ? "cursor-crosshair" : ""} ${pending ? "opacity-40" : ""}`} />
        {chosen && showSelection && !pending && <div role="toolbar" aria-label={`Selected level on ${id}`} className="absolute left-2 top-2 z-10 flex max-w-[calc(100%-5rem)] items-center gap-1 rounded-md border border-slate-600 bg-[#121924]/95 py-0.5 pl-2 pr-0.5 text-[11px] shadow-lg">
          <span className="h-0.5 w-3 shrink-0 bg-[#9cc2ff]" /><span className="min-w-0 truncate text-slate-300">{chosen.label}</span><span className="font-mono text-[#9cc2ff]">{price(chosen.price)}</span>
          <button aria-label="Delete selected level" title="Delete (Delete or Backspace)" onClick={() => onDelete?.(chosen.id)} className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-800 hover:text-rose-300"><Trash2 size={13} /></button>
          <button aria-label="Deselect level" title="Deselect (Esc)" onClick={() => onSelect?.(null)} className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200"><X size={13} /></button>
        </div>}
      </div>
      {history && (history.loading || history.issue || history.warmup === "insufficient" || history.calendarNote || history.adjustmentNote || (history.exhausted && history.historyStart)) && <div className="flex items-center gap-2 px-3 py-1 text-[10px] text-amber-300" role="status">
        {history.loading ? "Loading older candles and indicator warmup…" : history.issue ? history.issue : history.warmup === "insufficient" ? "Earlier indicator history is insufficient." : [history.exhausted && history.historyStart ? `Tradier daily history starts ${history.historyStart}.` : null, history.calendarNote, history.adjustmentNote].filter(Boolean).join(" ")}
        {history.issue && <button className="underline" onClick={onRetryHistory}>Retry history</button>}
      </div>}
      {notice && !pending && <p className="px-3 py-1 text-[10px] text-amber-300">{notice}</p>}
      {pending ? <div role="status" className="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center"><span className="rounded-md border border-slate-700/60 bg-[#10151e]/90 px-3 py-1.5 text-sm text-slate-200">{pending}</span></div>
        : !panel?.bars.length && <div className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-sm text-slate-500">No candles available</div>}
      {drawing && <div className="pointer-events-none absolute left-3 top-24 rounded bg-blue-500/90 px-3 py-1.5 text-xs text-white">Click a price to save a level</div>}
    </section>
  );
}
