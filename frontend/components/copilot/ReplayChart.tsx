"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { PaperPosition } from "@/lib/paperBook";
import type { ReplayBar, ReplayTrade, ReplayView } from "@/lib/paperReplay";

// The replay's chart (DeskReplay.tsx), in its own module so the chart library loads only when a replay is opened.

// --- the chart -------------------------------------------------------------------------------------------------------

const clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

type Parts = { chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">; markers: ISeriesMarkersPluginApi<Time>; lines: IPriceLine[] };

/** The replayed candles (only bars that ended by the clock), volume, his replay fills and his stop, target and limit lines. */
export function ReplayChart({ symbol, bars, positions, closed, orders }: {
  symbol: string; bars: ReplayBar[]; positions: PaperPosition[]; closed: ReplayTrade[]; orders: ReplayView["orders"];
}) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const drawn = useRef<{ first: number | null; count: number }>({ first: null, count: 0 });

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10 },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderColor: "#27272a", secondsVisible: false, rightOffset: 6,
        // One day on the axis: clock times only.
        tickMarkFormatter: (time: Time) => typeof time === "number" ? clockFmt.format(time * 1000) : null },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? `${clockFmt.format(time * 1000)} ET` : "" },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      kineticScroll: { mouse: false, touch: false },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    parts.current = { chart, candles, volume, markers: createSeriesMarkers(candles, []), lines: [] };
    drawn.current = { first: null, count: 0 };
    return () => { parts.current = null; chart.remove(); };
  }, []);

  // Bars only ever grow while the clock runs: append them (the view follows the newest bar); a new day redraws.
  useEffect(() => {
    const p = parts.current;
    if (!p) return;
    const candle = (b: ReplayBar) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
    const vol = (b: ReplayBar) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a455" : "#ee617a55" });
    const first = bars[0]?.time ?? null;
    if (first !== drawn.current.first || bars.length < drawn.current.count) {
      p.candles.setData(bars.map(candle));
      p.volume.setData(bars.map(vol));
      if (bars.length) p.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 150), to: bars.length + 6 });
    } else {
      for (const b of bars.slice(drawn.current.count)) { p.candles.update(candle(b)); p.volume.update(vol(b)); }
    }
    drawn.current = { first, count: bars.length };
  }, [bars]);

  // His replay fills as arrows; his stop, target and working limits as lines.
  useEffect(() => {
    const p = parts.current;
    if (!p) return;
    const minute = (t: number) => (Math.floor(t / 60) * 60) as UTCTimestamp;
    const last = bars.length ? bars[bars.length - 1].time : 0;
    const marks: SeriesMarker<Time>[] = [];
    for (const pos of [...positions, ...closed]) {
      if (pos.symbol !== symbol) continue;
      marks.push({ time: minute(pos.opened_at), position: "belowBar", shape: "arrowUp", color: "#ddd6fe", text: `P ${pos.quantity}` });
      for (const exit of pos.exits ?? []) marks.push({ time: minute(exit.at), position: "aboveBar", shape: "arrowDown", color: "#c4b5fd", text: `P ${exit.quantity}` });
    }
    p.markers.setMarkers(marks.filter(m => (m.time as number) <= last).sort((a, b) => (a.time as number) - (b.time as number)));
    for (const line of p.lines) p.candles.removePriceLine(line);
    p.lines = [];
    const add = (price: number, color: string, title: string, dashed = false) =>
      p.lines.push(p.candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title }));
    for (const pos of positions) {
      if (pos.symbol !== symbol) continue;
      if (pos.stop != null) add(pos.stop, "#fca5a5", "stop");
      if (pos.target != null) add(pos.target, "#86efac", "target");
    }
    // An option's limit is a premium, not a stock price: only share limits are drawn on the stock's chart.
    for (const o of orders) if (o.symbol === symbol && o.instrument === "stock") add(o.limit, "#a78bfa", `limit ${o.side === "close" ? "sell" : "buy"}`, true);
  }, [bars, positions, closed, orders, symbol]);

  return <div ref={host} data-testid="replay-chart" role="img" aria-label={`${symbol} replayed one-minute candles up to the replay clock`}
    className="h-[300px] w-full overflow-hidden rounded-md border sm:h-[420px]" />;
}

