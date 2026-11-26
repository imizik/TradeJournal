"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { ReplayEvent, TradeReplay } from "@/lib/tradeReplay";

// The trade page's replay chart (TradeReplay.tsx), in its own module so the chart library loads only with a replay.
// Every bar of the trade's days is on the time axis from the start; bars after the playhead are blank, so the axis
// stays put while the candles, VWAP and the option's price fill in bar by bar.

const clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
const TONE: Record<ReplayEvent["tone"], string> = { buy: "#2bc9a4", sell: "#ee617a", ping: "#f4c66b", muted: "#6b7280", rule: "#a78bfa" };

type Parts = { chart: IChartApi; candles: ISeriesApi<"Candlestick">; vwap: ISeriesApi<"Line">; option: ISeriesApi<"Line"> | null;
  markers: ISeriesMarkersPluginApi<Time>; lines: IPriceLine[] };

function marker(event: ReplayEvent, time: number): SeriesMarker<Time> {
  const color = TONE[event.tone];
  if (event.kind === "fill") {
    const size = event.label.match(/ ([\d.]+) @/)?.[1] ?? "";
    return { time: time as UTCTimestamp, position: event.tone === "buy" ? "belowBar" : "aboveBar", shape: event.tone === "buy" ? "arrowUp" : "arrowDown",
      color, text: `${event.tone === "buy" ? "B" : "S"}${size}` };
  }
  if (event.kind === "ping") return { time: time as UTCTimestamp, position: "aboveBar", shape: "circle", color, text: "ping" };
  return { time: time as UTCTimestamp, position: "aboveBar", shape: "square", color, text: event.kind === "cut" ? "cut" : "line" };
}

export default function TradeReplayChart({ replay, events, index }: { replay: TradeReplay; events: ReplayEvent[]; index: number }) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const bars = useMemo(() => replay.bars ?? [], [replay]);
  const multiplier = replay.multiplier ?? 1;
  const hasOption = (replay.option_bars?.length ?? 0) > 0;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const multiDay = new Set(bars.map(b => dayFmt.format(b.time * 1000))).size > 1;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10, panes: { separatorColor: "#27272a" } },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderColor: "#27272a", secondsVisible: false, rightOffset: 2, shiftVisibleRangeOnNewBar: false,
        tickMarkFormatter: (time: Time) => typeof time === "number" ? (multiDay && clockFmt.format(time * 1000) === "9:30 AM" ? dayFmt.format(time * 1000) : clockFmt.format(time * 1000)) : null },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? `${multiDay ? `${dayFmt.format(time * 1000)} ` : ""}${clockFmt.format(time * 1000)} ET` : "" },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      kineticScroll: { mouse: false, touch: false },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const vwap = chart.addSeries(LineSeries, { color: "#f5e6a1", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "VWAP" });
    const option = hasOption ? chart.addSeries(LineSeries, { color: "#67d5eb", lineWidth: 2, priceLineVisible: false, title: "Option" }, 1) : null;
    if (option) {
      const panes = chart.panes();
      panes[0].setStretchFactor(0.62);
      panes[1].setStretchFactor(0.38);
    }
    parts.current = { chart, candles, vwap, option, markers: createSeriesMarkers(candles, []), lines: [] };
    return () => { parts.current = null; chart.remove(); };
    // The chart is built once per replay; the playhead effect below fills it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replay]);

  // Bars after the playhead are whitespace: the axis keeps the whole trade, the candles stop at the playhead.
  const fitted = useRef<TradeReplay | null>(null);
  useEffect(() => {
    const p = parts.current;
    if (!p || !bars.length) return;
    const blank = (time: number) => ({ time: time as UTCTimestamp });
    p.candles.setData(bars.map((b, i) => i <= index ? { time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close } : blank(b.time)));
    p.vwap.setData(bars.map((b, i) => i <= index && b.vwap != null ? { time: b.time as UTCTimestamp, value: b.vwap } : blank(b.time)));
    if (p.option) {
      const byTime = new Map((replay.option_bars ?? []).map(o => [o.time, o.close]));
      p.option.setData(bars.map((b, i) => i <= index && byTime.has(b.time) ? { time: b.time as UTCTimestamp, value: byTime.get(b.time)! } : blank(b.time)));
    }
    // The cut line and the open lots' average cost sit on the traded instrument's own price: the option pane, or the
    // candles for a stock. An option with no minute prices has nowhere to draw them.
    const priced = p.option ?? (replay.instrument_type === "stock" ? p.candles : null);
    for (const line of p.lines) priced?.removePriceLine(line);
    p.lines = [];
    if (priced) {
      if (replay.cut_line) p.lines.push(priced.createPriceLine({ price: replay.cut_line.price / multiplier, color: TONE.rule, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "cut line" }));
      const avg = bars[index]?.avg_cost;
      if (avg != null) p.lines.push(priced.createPriceLine({ price: avg / multiplier, color: "#a1a1aa", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: "avg" }));
    }
    const shown = events.filter(e => e.index <= index).map(e => marker(e, bars[e.index].time));
    p.markers.setMarkers(shown.sort((a, b) => (a.time as number) - (b.time as number)));
    // First view: the whole trade on a wide screen, about 150 bars around the playhead on a phone. After that the
    // view is his to pan and zoom; it only moves when the playhead runs off either edge.
    const scale = p.chart.timeScale();
    const range = scale.getVisibleLogicalRange();
    if (fitted.current !== replay || !range) {
      fitted.current = replay;
      const width = (host.current?.clientWidth ?? 0) < 640 ? Math.min(150, bars.length) : bars.length;
      const from = width >= bars.length ? 0 : Math.max(0, Math.min(bars.length - width, index - width * 0.6));
      scale.setVisibleLogicalRange({ from: from - 1, to: from + width + 1 });
    } else if (index > range.to - 1 || index < range.from + 1) {
      const width = range.to - range.from;
      scale.setVisibleLogicalRange({ from: index - width * 0.7, to: index + width * 0.3 });
    }
  }, [replay, bars, events, index, multiplier]);

  return <div ref={host} data-testid="trade-replay-chart" className={`w-full ${hasOption ? "h-[22rem] sm:h-[26rem]" : "h-64 sm:h-80"}`} />;
}
