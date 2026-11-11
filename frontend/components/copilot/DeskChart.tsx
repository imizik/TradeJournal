"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineStyle, TickMarkType, createChart, createSeriesMarkers,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type IPrimitivePaneRenderer, type IPrimitivePaneView, type ISeriesApi, type ISeriesMarkersPluginApi,
  type ISeriesPrimitive, type Logical, type SeriesAttachedParameter, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { SessionShade } from "@/lib/sessionShade";
import type { ChartBar } from "@/lib/charts";
import { getDeskChart, type DeskChartData, type DeskChartMark, type DeskTimeframe } from "@/lib/desk";

/*
 * The cockpit centre's chart (docs/copilot-lab.md § The desk): the selected symbol's candles from the desk's chart read
 * (`GET /copilot/desk/{id}/chart`) on the library the Charts workspace uses, with the plan's entry and invalidation as
 * labelled lines, the owner's fills, today's phone pings and Radar hits as marks, and a time stop still ahead as a
 * dashed vertical line. Crosshair, wheel or pinch zoom, drag to pan, Reset. It reads again each minute while bars can
 * still change; no stream. A glance-and-hover chart: drawing, studies and the rest live in Charts.
 */

const ET = "America/New_York";
const REFRESH_MS = 60_000;
const COLOR = { fill: "#e9a23b", ping: "#a78bfa", radar: "#60a5fa", entry: "#7db3f0", invalidation: "#fca5a5", stop: "#a1a1aa" };
const KIND_WORD: Record<DeskChartMark["kind"], string> = { fill: "Fill", ping: "Ping", radar: "Radar" };
/** A plan line further than this from the last price does not stretch the price scale; the row above still names it. */
const LEVEL_REACH = 0.1;
/** Candles of room kept past the last one; more when the time stop is ahead (up to ``STOP_ROOM``). */
const RIGHT_ROOM = 4;
const STOP_ROOM = 120;
/** Pixels from a mark within which the pointer shows what it was. */
const HOVER_PX = 10;

const clock = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" });
const tickFormats = {
  [TickMarkType.Year]: new Intl.DateTimeFormat("en-US", { timeZone: ET, year: "numeric" }),
  [TickMarkType.Month]: new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short" }),
  [TickMarkType.DayOfMonth]: dayFmt,
};
/** "10:05 ET" today, "Oct 20 10:05 ET" another day, "Oct 20" on daily candles. */
export function nyWhen(seconds: number, daily = false, now = Date.now() / 1000): string {
  const at = seconds * 1000;
  if (daily) return dayFmt.format(at);
  const sameDay = dayFmt.format(at) === dayFmt.format(now * 1000);
  return `${sameDay ? "" : `${dayFmt.format(at)} `}${clock.format(at)} ET`;
}
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

type Bar = DeskChartData["bars"][number];

/** The candle holding ``at`` (its start at or before, within one step), or undefined. */
function candleOf(bars: Bar[], step: number, at: number): Bar | undefined {
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time <= at) low = mid + 1; else high = mid; }
  const bar = bars[low - 1];
  return bar && at < bar.time + step ? bar : undefined;
}

/** Each mark on its candle, keyed by the candle's time. A mark off the candles shown is left out. */
export function marksByCandle(data: DeskChartData): Map<number, DeskChartMark[]> {
  const out = new Map<number, DeskChartMark[]>();
  for (const mark of data.marks) {
    const bar = candleOf(data.bars, data.step, mark.at);
    if (!bar) continue;
    out.set(bar.time, [...(out.get(bar.time) ?? []), mark]);
  }
  return out;
}

function seriesMarkers(byCandle: Map<number, DeskChartMark[]>): SeriesMarker<Time>[] {
  const out: SeriesMarker<Time>[] = [];
  for (const [time, marks] of [...byCandle.entries()].sort((a, b) => a[0] - b[0])) {
    marks.forEach((mark, i) => {
      const at = time as UTCTimestamp;
      const id = `${mark.kind}:${mark.at}:${i}`;
      if (mark.kind === "fill") {
        const buy = mark.side !== "sell";
        out.push(mark.price != null
          ? { id, time: at, position: "atPriceMiddle", price: mark.price, shape: buy ? "arrowUp" : "arrowDown", color: COLOR.fill }
          : { id, time: at, position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "arrowDown", color: COLOR.fill });
      } else {
        out.push({ id, time: at, position: "aboveBar", shape: mark.kind === "ping" ? "circle" : "square", color: COLOR[mark.kind], size: 0.8 });
      }
    });
  }
  // atPrice and bar positions both sort by time; the library wants them in order.
  return out.sort((a, b) => (a.time as number) - (b.time as number));
}

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

/** The plan's time stop still ahead: a dashed vertical line at its time past the last candle, labelled; past the right
 * edge, the label sits at the edge with an arrow. Outside the price scale's fit. */
class TimeStopLine implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private requestUpdate: (() => void) | null = null;
  private x: number | null = null;
  private stop: { at: number; text: string } | null = null;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "top", renderer: () => this.renderer }];

  constructor(private readonly bars: () => Bar[], private readonly step: () => number) {}

  attached({ chart, requestUpdate }: SeriesAttachedParameter<Time>) { this.chart = chart; this.requestUpdate = requestUpdate; }
  detached() { this.chart = null; this.requestUpdate = null; }
  set(stop: { at: number; text: string } | null) { this.stop = stop; this.requestUpdate?.(); }

  updateAllViews() {
    this.x = null;
    const bars = this.bars();
    const scale = this.chart?.timeScale();
    if (!this.stop || !scale || !bars.length) return;
    const last = bars[bars.length - 1];
    const logical = (bars.length - 1) + (this.stop.at - last.time) / this.step();
    this.x = scale.logicalToCoordinate(logical as Logical);
  }

  paneViews() { return this.views; }

  private draw(target: Target) {
    const { x, stop } = this;
    if (x === null || !stop) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const label = `Time stop ${clock.format(stop.at * 1000)}`;
      context.font = "11px ui-sans-serif, system-ui, -apple-system, sans-serif";
      context.fillStyle = COLOR.stop;
      if (x > mediaSize.width) {
        context.textAlign = "right";
        context.fillText(`${label} →`, mediaSize.width - 4, 14);
        return;
      }
      context.strokeStyle = COLOR.stop;
      context.setLineDash([4, 4]);
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(Math.round(x) + 0.5, 0);
      context.lineTo(Math.round(x) + 0.5, mediaSize.height);
      context.stroke();
      context.setLineDash([]);
      const room = context.measureText(label).width + 8;
      context.textAlign = x + room > mediaSize.width ? "right" : "left";
      context.fillText(label, x + (context.textAlign === "right" ? -4 : 4), 14);
    });
  }
}

type Parts = {
  chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">; markers: ISeriesMarkersPluginApi<Time>;
  shade: SessionShade; stop: TimeStopLine; lines: IPriceLine[];
};
type Hover = { bar: Bar; marks: DeskChartMark[]; x: number; width: number };

/** The default view: every candle, plus room on the right for a time stop still ahead. */
function defaultRange(parts: Parts, data: DeskChartData) {
  const last = data.bars.length - 1;
  const ahead = data.time_stop && data.timeframe !== "1D" ? Math.ceil((data.time_stop.at - data.bars[last].time) / data.step) : 0;
  const room = ahead > 0 ? Math.min(ahead, STOP_ROOM) + RIGHT_ROOM : RIGHT_ROOM;
  parts.chart.priceScale("right").applyOptions({ autoScale: true });
  parts.chart.timeScale().setVisibleLogicalRange({ from: -1, to: last + room });
}

type Read = { key: string; data: DeskChartData } | { key: string; error: string };
/** What the chart shows now, for the crosshair and the primitives; ``applied`` is the key last painted. */
type Painted = { shown: DeskChartData | null; byCandle: Map<number, DeskChartMark[]>; applied: string | null };

/** The read's candles, lines and marks onto the chart; the view resets only for a new symbol or timeframe. */
function paint(current: Parts, read: Read, state: Painted) {
  const fresh = read.key !== state.applied;
  const next = "data" in read && read.data.state === "ok" && read.data.bars.length ? read.data : null;
  state.shown = next;
  state.byCandle = next ? marksByCandle(next) : new Map();
  state.applied = read.key;
  for (const line of current.lines) current.candles.removePriceLine(line);
  current.lines = [];
  if (!next) {
    current.candles.setData([]);
    current.volume.setData([]);
    current.markers.setMarkers([]);
    current.stop.set(null);
    return;
  }
  current.candles.setData(next.bars.map(b => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
  current.volume.setData(next.bars.map(b => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a433" : "#ee617a33" })));
  current.lines = next.levels.map(level => current.candles.createPriceLine({
    price: level.price, color: COLOR[level.role], lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: level.label,
  }));
  current.markers.setMarkers(seriesMarkers(state.byCandle));
  current.shade.update();
  current.stop.set(next.timeframe === "1D" ? null : next.time_stop);  // a clock time has no place on daily candles
  // Clock ticks on the intraday candles, dates on the daily ones.
  current.chart.applyOptions({ timeScale: { timeVisible: next.timeframe !== "1D" } });
  if (fresh) defaultRange(current, next);
}

/** The chart for ``id`` (a thread, ``symbol:X`` or ``market``) on ``timeframe``. ``refreshKey`` reads it again. */
export function DeskChart({ id, timeframe, refreshKey = 0, label }: { id: string; timeframe: DeskTimeframe; refreshKey?: number; label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const painted = useRef<Painted>({ shown: null, byCandle: new Map(), applied: null });
  const latest = useRef<Read | null>(null);
  const [read, setRead] = useState<Read | null>(null);
  const [tick, setTick] = useState(0);
  const [hover, setHover] = useState<Hover | null>(null);
  const key = `${id}|${timeframe}`;

  // One chart for the component's life; a new symbol or timeframe swaps the data in place, so switching never blanks.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10 },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" }, horzLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" } },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.1, bottom: 0.2 }, entireTextOnly: true },
      timeScale: { borderColor: "#27272a", secondsVisible: false, rightOffset: RIGHT_ROOM, minBarSpacing: 0.5,  // a whole 2m day fits a phone; zoom in for candles
        tickMarkFormatter: (time: Time, kind: TickMarkType) => typeof time !== "number" ? null
          : kind <= TickMarkType.DayOfMonth ? tickFormats[kind as keyof typeof tickFormats].format(time * 1000) : clock.format(time * 1000) },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? nyWhen(time, painted.current.shown?.timeframe === "1D") : "" },
      // Drag and horizontal swipes pan, the wheel and a pinch zoom; a vertical swipe on a phone still scrolls the page.
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
      kineticScroll: { mouse: false, touch: false },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false,
      // A plan line near the price stays in view; one far off is named in the row above instead of crushing the candles.
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const found = original();
        const data = painted.current.shown;
        if (!found?.priceRange || !data?.bars.length) return found;
        const last = data.bars[data.bars.length - 1].close;
        const near = data.levels.map(l => l.price).filter(p => Math.abs(p - last) / last <= LEVEL_REACH);
        if (!near.length) return found;
        return { ...found, priceRange: { minValue: Math.min(found.priceRange.minValue, ...near), maxValue: Math.max(found.priceRange.maxValue, ...near) } };
      },
    });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const markers = createSeriesMarkers(candles, []);
    const shade = new SessionShade(() => (painted.current.shown?.bars ?? []) as unknown as ChartBar[]);
    candles.attachPrimitive(shade);
    const stop = new TimeStopLine(() => painted.current.shown?.bars ?? [], () => painted.current.shown?.step ?? 60);
    candles.attachPrimitive(stop);
    parts.current = { chart, candles, volume, markers, shade, stop, lines: [] };
    painted.current.applied = null;  // a new chart starts from the default view
    if (latest.current) paint(parts.current, latest.current, painted.current);
    chart.subscribeCrosshairMove((event) => {
      const data = painted.current.shown;
      if (!data || !event.point || typeof event.time !== "number") { setHover(null); return; }
      const bar = candleOf(data.bars, data.step, event.time);
      if (!bar) { setHover(null); return; }
      // A full day of 2m candles is a pixel or two apart: the mark nearest the pointer, within ``HOVER_PX``, answers.
      let near: { time: number; gap: number } | null = null;
      for (const time of painted.current.byCandle.keys()) {
        const x = chart.timeScale().timeToCoordinate(time as UTCTimestamp);
        const gap = x === null ? Infinity : Math.abs(x - event.point.x);
        if (gap <= HOVER_PX && (!near || gap < near.gap)) near = { time, gap };
      }
      setHover({ bar, marks: near ? painted.current.byCandle.get(near.time) ?? [] : [], x: event.point.x, width: element.clientWidth });
    });
    return () => { parts.current = null; chart.remove(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getDeskChart(id, timeframe, controller.signal)
      .then(data => { if (!controller.signal.aborted) setRead({ key, data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ key, error: failure instanceof Error ? failure.message : "Unavailable right now." }); });
    return () => controller.abort();
  }, [id, timeframe, key, refreshKey, tick]);

  const data = read && "data" in read && read.data.state === "ok" && read.data.bars.length ? read.data : null;
  const live = !!data?.live;
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [live, key]);

  // The read onto the chart (and onto a chart built again, e.g. after a hot reload, from the last read).
  useEffect(() => {
    latest.current = read;
    if (parts.current && read) paint(parts.current, read, painted.current);
  }, [read]);

  const reset = () => { if (parts.current && painted.current.shown) defaultRange(parts.current, painted.current.shown); };
  const switching = !!read && read.key !== key;
  const unavailable = read && read.key === key ? ("error" in read ? read.error : read.data.state !== "ok" || !read.data.bars.length ? (read.data.reason ?? "No bars came back.") : null) : null;
  const daily = data?.timeframe === "1D";
  const byCandle = useMemo(() => data ? marksByCandle(data) : new Map<number, DeskChartMark[]>(), [data]);
  const allMarks = useMemo(() => [...byCandle.values()].flat(), [byCandle]);
  const lastBar = data ? data.bars[data.bars.length - 1] : null;
  const readout = hover?.bar ?? lastBar;
  const offScale = useMemo(() => {
    if (!data || !lastBar) return new Set<string>();
    return new Set(data.levels.filter(l => Math.abs(l.price - lastBar.close) / lastBar.close > LEVEL_REACH).map(l => l.role));
  }, [data, lastBar]);

  return (
    <div className="space-y-1.5">
      <div data-testid="desk-chart-lines" className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
        {data?.levels.map(level => (
          <span key={level.role} style={{ color: COLOR[level.role] }}>{level.label}{offScale.has(level.role) ? " (off the chart)" : ""}</span>
        ))}
        {data && !data.levels.length && id !== "market" && <span>no plan lines saved</span>}
        {data?.time_stop && <span style={{ color: COLOR.stop }}>Time stop {clock.format(data.time_stop.at * 1000)}</span>}
        <button type="button" onClick={reset} disabled={!data}
          className="ml-auto min-h-9 rounded border border-transparent px-2 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0 sm:py-0.5">
          Reset
        </button>
      </div>
      {/* One line that never wraps, so moving the pointer never moves the chart. */}
      <p className="h-4 truncate text-xs leading-4 tabular-nums text-muted-foreground" data-testid="desk-chart-readout">
        {readout && <>
          {nyWhen(readout.time, daily)} · O {price(readout.open)} H {price(readout.high)} L {price(readout.low)} C <span className="text-foreground">{price(readout.close)}</span>
          {readout.extended && <> · {readout.time < (data?.bars.find(b => !b.extended)?.time ?? Infinity) ? "pre-market" : "after hours"}</>}
        </>}
      </p>
      <div className="relative">
        <div ref={host} role="img" aria-label={label} data-testid="desk-chart-canvas" data-timeframe={data?.timeframe ?? ""}
          data-bars={data?.bars.length ?? 0} data-marks={allMarks.length}
          className="h-[300px] w-full overflow-hidden rounded border sm:h-[380px]" />
        {hover && hover.marks.length > 0 && (
          <div role="tooltip" data-testid="desk-chart-tip"
            className="pointer-events-none absolute top-2 z-10 max-w-[min(20rem,85%)] rounded border bg-popover/95 px-2 py-1.5 text-xs shadow"
            style={hover.x > hover.width / 2 ? { right: `${Math.max(8, hover.width - hover.x + 12)}px` } : { left: `${hover.x + 12}px` }}>
            {hover.marks.map((mark, i) => (
              <p key={i} className="leading-snug">
                <span style={{ color: COLOR[mark.kind] }}>{KIND_WORD[mark.kind]}</span>
                <span className="text-foreground"> · {mark.text}</span>
                <span className="text-muted-foreground"> · {nyWhen(mark.at)}</span>
              </p>
            ))}
          </div>
        )}
        {(!read || switching) && !unavailable && (
          <div className="absolute inset-0 flex items-center justify-center rounded bg-background/60 text-sm text-muted-foreground">Reading the chart…</div>
        )}
        {unavailable && (
          <div data-testid="desk-chart-empty" className="absolute inset-0 flex flex-col items-center justify-center gap-1 rounded border bg-background px-4 text-center">
            <p className="text-sm text-foreground">No chart data</p>
            <p className="text-xs text-muted-foreground">{unavailable}{timeframe === "2m" ? " 15m and 1D show earlier sessions." : ""}</p>
          </div>
        )}
      </div>
      {data && (
        <ul aria-label="On the chart" className="sr-only" data-testid="desk-chart-marks">
          {data.levels.map(level => <li key={level.role}>{level.label}</li>)}
          {allMarks.map((mark, i) => <li key={i}>{KIND_WORD[mark.kind]} · {mark.text} · {nyWhen(mark.at)}</li>)}
          {data.time_stop && <li>Time stop {clock.format(data.time_stop.at * 1000)} · {data.time_stop.text}</li>}
        </ul>
      )}
    </div>
  );
}
