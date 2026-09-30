"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode, LineStyle, TickMarkType, createSeriesMarkers } from "lightweight-charts";
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, IPriceLine, Time, UTCTimestamp } from "lightweight-charts";
import { Expand, LocateFixed } from "lucide-react";
import { INTERVALS, barAt, etTime, price } from "@/lib/charts";
import type { ChartBar, ChartPanelData, CrosshairLink, Indicators, Interval, PriceLevel } from "@/lib/charts";

const COLORS = { ema9: "#67d5eb", ema20: "#f4c66b", ema50: "#b494f5", ema200: "#ee86bd", vwap: "#f5e6a1" };
const tickFormats = {
  [TickMarkType.Year]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric" }),
  [TickMarkType.Month]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short" }),
  [TickMarkType.DayOfMonth]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }),
};
type Overlay = keyof typeof COLORS;
type Bundle = {
  chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">;
  shade: ISeriesApi<"Histogram">; rsi?: ISeriesApi<"Line">;
  lines: Record<Overlay, ISeriesApi<"Line">>; markers: ISeriesMarkersPluginApi<Time>; levels: IPriceLine[];
};

export default function PriceChart({ id, symbol, interval, panel, indicators, levels, link, main = false, drawing = false, onDraw, onInterval, onFocus }: {
  id: string; symbol: string; interval: Interval; panel?: ChartPanelData; indicators: Indicators; levels: PriceLevel[];
  link: CrosshairLink; main?: boolean; drawing?: boolean; onDraw(price: number): void;
  onInterval(interval: Interval): void; onFocus?(): void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const bundle = useRef<Bundle | null>(null);
  const barsRef = useRef<ChartBar[]>([]);
  const actions = useRef({ drawing, onDraw });
  const initial = useRef(true);
  const [hover, setHover] = useState<ChartBar | null>(null);
  useEffect(() => { actions.current = { drawing, onDraw }; }, [drawing, onDraw]);

  useEffect(() => {
    if (!container.current) return;
    setHover(null);
    barsRef.current = [];
    const daily = interval === "1D" || interval === "1W";
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#10151e" }, textColor: "#8593a9", fontSize: 10,
        attributionLogo: true, panes: { separatorColor: "#27303d", separatorHoverColor: "#46576b" } },
      grid: { vertLines: { color: "#1b2532" }, horzLines: { color: "#1b2532" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#75859b", labelBackgroundColor: "#34455a" }, horzLine: { color: "#75859b", labelBackgroundColor: "#34455a" } },
      rightPriceScale: { borderColor: "#263141", minimumWidth: main ? 66 : 54, scaleMargins: { top: 0.10, bottom: 0.23 } },
      timeScale: { borderColor: "#263141", timeVisible: !daily, secondsVisible: false, rightOffset: 4, minBarSpacing: 2,
        tickMarkFormatter: (time: Time, kind: TickMarkType) => {
          if (typeof time !== "number") return null;
          return kind <= TickMarkType.DayOfMonth ? tickFormats[kind as keyof typeof tickFormats].format(time * 1000) : etTime(time);
        } },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? `${etTime(time, true)} ${daily ? "" : etTime(time) + " ET"}` : "" },
    });
    const shade = chart.addSeries(HistogramSeries, { priceScaleId: "sessions", priceLineVisible: false, lastValueVisible: false,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }) });
    shade.priceScale().applyOptions({ scaleMargins: { top: 0, bottom: 0 } });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const lines = {} as Bundle["lines"];
    for (const name of Object.keys(COLORS) as Overlay[]) lines[name] = chart.addSeries(LineSeries, { color: COLORS[name], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    let rsi: Bundle["rsi"];
    if (indicators.rsi) {
      rsi = chart.addSeries(LineSeries, { color: "#b494f5", lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
      rsi.createPriceLine({ price: 70, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
      rsi.createPriceLine({ price: 30, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
      chart.panes()[1].setHeight(main ? 85 : 60);
    }
    const markers = createSeriesMarkers(candles, []);
    bundle.current = { chart, candles, volume, shade, rsi, lines, markers, levels: [] };
    initial.current = true;
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
    chart.subscribeClick((event) => {
      if (!actions.current.drawing || !event.point || (event.paneIndex ?? 0) !== 0) return;
      const value = candles.coordinateToPrice(event.point.y);
      if (value !== null && value > 0) actions.current.onDraw(Math.round(value * 100) / 100);
    });
    return () => { stopLink(); markers.detach(); chart.remove(); bundle.current = null; };
  }, [id, symbol, interval, indicators.rsi, link, main]);

  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    const bars = panel?.bars ?? [];
    barsRef.current = bars;
    const range = current.chart.timeScale().getVisibleRange();
    const logical = current.chart.timeScale().getVisibleLogicalRange();
    const following = !logical || logical.to >= (current.candles.data().length - 3);
    current.candles.setData(bars.map((b) => ({ ...b, time: b.time as UTCTimestamp })));
    current.volume.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a43d" : "#ee617a3d" })));
    current.volume.applyOptions({ visible: indicators.volume });
    current.shade.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, value: 1, color: b.extended ? "#6b84bd10" : "transparent" })));
    for (const name of Object.keys(COLORS) as Overlay[]) {
      current.lines[name].setData(bars.map((b, index) => {
        if (b[name] === null) return { time: b.time as UTCTimestamp };
        const next = bars[index + 1];
        // Whitespace alone still joins line segments in Lightweight Charts.
        // Hide the outgoing segment at the session boundary. RTH timestamps
        // always lie within one UTC date, even across New York DST changes.
        const gapAfter = name === "vwap" && next && (next.vwap === null || Math.floor(next.time / 86400) !== Math.floor(b.time / 86400));
        return { time: b.time as UTCTimestamp, value: b[name] as number, ...(gapAfter ? { color: "transparent" } : {}) };
      }));
      current.lines[name].applyOptions({ visible: indicators[name] });
    }
    current.rsi?.setData(bars.map((b) => b.rsi === null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: b.rsi }));
    current.markers.setMarkers(indicators.fills ? (panel?.markers ?? []).map((m) => ({ time: m.time as UTCTimestamp,
      position: m.buy ? "belowBar" as const : "aboveBar" as const, shape: m.buy ? "arrowUp" as const : "arrowDown" as const,
      color: m.buy ? "#67d5eb" : "#f4c66b", text: main ? m.label : "", id: m.id })) : []);
    if (bars.length && initial.current) {
      current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - (main ? 110 : 65)), to: bars.length + 4 });
      initial.current = false;
    } else if (bars.length && following && logical) {
      const width = logical.to - logical.from;
      current.chart.timeScale().setVisibleLogicalRange({ from: bars.length + 4 - width, to: bars.length + 4 });
    } else if (range) current.chart.timeScale().setVisibleRange(range);
  }, [panel, indicators, symbol, interval, main]);

  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    current.levels.forEach((line) => current.candles.removePriceLine(line));
    current.levels = levels.map((level) => current.candles.createPriceLine({ price: level.price, title: main ? level.label : "", color: "#659ef0", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true }));
  }, [levels, symbol, interval, indicators.rsi, main]);

  const bar = (hover && barAt(panel?.bars ?? [], hover.time)) || panel?.bars.at(-1);
  return (
    <section aria-label={`${symbol} ${interval} chart`} className={`relative min-w-0 overflow-hidden rounded-lg border bg-[#10151e] ${main ? "border-slate-600/60" : "border-slate-700/50"}`}>
      <div className="flex h-10 items-center justify-between gap-2 border-b border-slate-700/40 px-3">
        <div className="flex items-center gap-2 text-xs"><span className="font-semibold tracking-wide text-slate-200">{symbol}</span>
          <select aria-label={`${main ? "Main" : id} interval`} value={interval} onChange={(e) => onInterval(e.target.value as Interval)} className="rounded border-0 bg-slate-800 px-1.5 py-1 text-[11px] text-slate-300">
            {INTERVALS.map((i) => <option key={i}>{i}</option>)}
          </select>
          {main && <span className="hidden text-[10px] text-slate-500 sm:inline">{interval === "1D" || interval === "1W" ? "REGULAR SESSION" : "NEW YORK"}</span>}
        </div>
        <div className="flex items-center gap-1">
          <button title="Go to latest candles" aria-label={`Latest candles ${id}`} onClick={() => { const current = bundle.current; if (current) { const n = barsRef.current.length; current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (main ? 110 : 65)), to: n + 4 }); } }} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><LocateFixed size={13} /></button>
          {onFocus && <button title="Make main chart" aria-label={`Focus ${interval} chart`} onClick={onFocus} className="rounded p-1.5 text-slate-500 hover:bg-slate-800 hover:text-slate-200"><Expand size={13} /></button>}
        </div>
      </div>
      <div className="flex h-6 items-center gap-2 overflow-hidden whitespace-nowrap px-3 font-mono text-[10px] text-slate-500" aria-label={`${id} candle values`}>
        {bar ? <>{main && <><span>O <span className="text-slate-300">{price(bar.open)}</span></span><span>H <span className="text-slate-300">{price(bar.high)}</span></span><span>L <span className="text-slate-300">{price(bar.low)}</span></span></>}<span>C <span className={bar.close >= bar.open ? "text-emerald-400" : "text-rose-400"}>{price(bar.close)}</span></span>{!main && <span>Vol {bar.volumePending ? "pending" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(bar.volume)}</span>}</> : <span>No candles in this window</span>}
      </div>
      {main && <div className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-1 font-mono text-[10px]">
        {(Object.keys(COLORS) as Overlay[]).filter((key) => indicators[key]).map((key) => <span key={key} style={{ color: COLORS[key] }}>{key.toUpperCase()} {price(bar?.[key])}</span>)}
        {indicators.rsi && <span className="text-violet-300">RSI {price(bar?.rsi)}</span>}
      </div>}
      <div ref={container} data-testid={`canvas-${id}`} className={`${main ? "h-[410px]" : "h-[245px]"} ${drawing ? "cursor-crosshair" : ""}`} />
      {!panel?.bars.length && <div className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-sm text-slate-500">No candles available</div>}
      {drawing && <div className="pointer-events-none absolute left-3 top-24 rounded bg-blue-500/90 px-3 py-1.5 text-xs text-white">Click a price to save a level</div>}
    </section>
  );
}
