"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker,
  type Time, type UTCTimestamp, type WhitespaceData, type LineData,
} from "lightweight-charts";
import { nyWhen } from "@/components/copilot/DeskReading";
import {
  COLOR, FILL_REACH, MARK_GAP, MAX_FILL_LINES, atOrBefore, dayFmt, mergedMarks, nyDate, pnlAt, premium, priceAt, provisionalFills, usd,
  type HeldContract, type Hover,
} from "@/components/copilot/DeskContract";
import type { DeskContractData, DeskContractFill } from "@/lib/desk";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";

// The Contract view's chart (DeskContract.tsx), in its own module so the chart library loads only when a chart is drawn.

/** The contract's chart for ``held`` from ``data`` (``useContractView``). */
export function ContractChart({ held, data }: { held: HeldContract; data: DeskContractData }) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<{ chart: IChartApi; candles: ISeriesApi<"Candlestick">; line: ISeriesApi<"Line">; marks: ISeriesApi<"Line">;
    clock: ISeriesApi<"Line">; markers: ISeriesMarkersPluginApi<Time>[]; lines: { series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">; line: IPriceLine }[] } | null>(null);
  const shown = useRef<{ fills: number[]; last: number | null }>({ fills: [], last: null });
  const fitted = useRef<string | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const ticks = useDeskTicks([held.occ]);
  const live = tickFor(ticks, held.occ);
  const step = data.step ?? 120;
  const bars = useMemo(() => data.bars ?? [], [data]);
  const style = data.style ?? "line";
  const marks = useMemo(() => mergedMarks(data.marks ?? [], live ? { last: live.last, at: live.at, stale: live.stale } : null, data.day, step),
    [data, live?.last, live?.at, live?.stale, step]); // eslint-disable-line react-hooks/exhaustive-deps -- the tick's values, not its object
  const fills = useMemo(() => {
    const today = data.as_of != null && nyDate.format(data.as_of * 1000) === data.day;
    return [...(data.fills ?? []), ...(today ? provisionalFills(held.orders) : [])].sort((a, b) => a.at - b.at);
  }, [data, held.orders]);
  const stock = useMemo(() => data.stock ?? [], [data]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10 },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" }, horzLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" } },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.1, bottom: 0.08 } },
      timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false, rightOffset: 4,
        tickMarkFormatter: (time: Time) => typeof time === "number" ? nyWhen(time, false, time).replace(/ ET$/, "") : null },
      localization: { timeFormatter: (time: Time) => typeof time === "number" ? nyWhen(time) : "", priceFormatter: (p: number) => p.toFixed(2) },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
      kineticScroll: { mouse: false, touch: false },
    });
    // His fill prices near the price stay in view; one far off is named in the legend instead of crushing the price.
    const withFills = (original: () => AutoscaleInfo | null) => {
      const found = original();
      const { fills: prices, last } = shown.current;
      if (!found?.priceRange || last === null) return found;
      const near = prices.filter(p => Math.abs(p - last) / last <= FILL_REACH);
      return near.length ? { ...found, priceRange: { minValue: Math.min(found.priceRange.minValue, ...near), maxValue: Math.max(found.priceRange.maxValue, ...near) } } : found;
    };
    const clock = chart.addSeries(LineSeries, { visible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false,
      priceLineVisible: false, autoscaleInfoProvider: withFills });
    const line = chart.addSeries(LineSeries, { color: COLOR.trade, lineWidth: 2, pointMarkersVisible: true, pointMarkersRadius: 2, priceLineVisible: false,
      crosshairMarkerVisible: false, autoscaleInfoProvider: withFills });
    const marks = chart.addSeries(LineSeries, { color: COLOR.mark + "b0", lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false,
      crosshairMarkerVisible: false, autoscaleInfoProvider: withFills });
    parts.current = { chart, candles, line, marks, clock, markers: [], lines: [] };
    chart.subscribeCrosshairMove(event => {
      if (!event.point || typeof event.time !== "number") { setHover(null); return; }
      setHover({ time: event.time, x: event.point.x, width: element.clientWidth });
    });
    return () => { parts.current = null; chart.remove(); };
  }, []);

  useEffect(() => {
    const current = parts.current;
    if (!current) return;
    const { chart, candles, line, marks: markLine, clock } = current;
    const candlesOn = style === "candles" && bars.length > 0;
    candles.setData(candlesOn ? bars.map(b => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })) : []);
    line.setData(!candlesOn ? bars.map(b => ({ time: b.time as UTCTimestamp, value: b.close })) : []);
    // A mark line breaks where the desk was not open to see the price, rather than drawing across the gap.
    const markPoints: (LineData<Time> | WhitespaceData<Time>)[] = [];
    marks.forEach((m, i) => {
      const before = marks[i - 1];
      if (before && m.time - before.time > MARK_GAP) markPoints.push({ time: (before.time + step) as UTCTimestamp });
      markPoints.push({ time: m.time as UTCTimestamp, value: m.price });
    });
    markLine.setData(markPoints);
    // Every 2-minute slot of the session on the time axis, so a gap between prints is as wide as the time it took.
    const times = [...bars.map(b => b.time), ...marks.map(m => m.time)];
    const first = times.length ? Math.min(...times) : null, end = times.length ? Math.max(...times) : null;
    const slots: WhitespaceData<Time>[] = [];
    if (first !== null && end !== null) {
      for (let t = first - (first % step); t <= end && slots.length < 1000; t += step) slots.push({ time: t as UTCTimestamp });
    }
    clock.setData(slots);
    const primary = candlesOn ? candles : bars.length ? line : markLine;
    for (const { series, line: priceLine } of current.lines) series.removePriceLine(priceLine);
    current.lines = [];
    // His fills: one line a price (the newest few), solid for the journal's, dashed for Robinhood's provisional ones.
    const byPrice = new Map<string, DeskContractFill[]>();
    for (const fill of fills) {
      const id = `${fill.provisional ? "p" : "j"}${fill.side}${premium(fill.price)}`;
      byPrice.set(id, [...(byPrice.get(id) ?? []), fill]);
    }
    const groups = [...byPrice.values()].sort((a, b) => b[b.length - 1].at - a[a.length - 1].at).slice(0, MAX_FILL_LINES);
    for (const group of groups) {
      const f = group[group.length - 1];
      const count = group.reduce((n, g) => n + g.contracts, 0);
      current.lines.push({ series: primary, line: primary.createPriceLine({
        price: f.price, color: f.provisional ? COLOR.provisional : COLOR.fill, lineWidth: 1, lineStyle: f.provisional ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true, title: `${f.side === "buy" ? "Buy" : "Sell"} ${count} ${premium(f.price)}${f.provisional ? " prov." : ""}`,
      }) });
    }
    const last = priceAt(bars, marks, Infinity)?.price ?? null;
    shown.current = { fills: groups.map(g => g[0].price), last };
    // Arrows where each fill on the shown day happened, on the nearest slot of the price drawn.
    for (const plugin of current.markers) plugin.detach();
    const drawnTimes = (candlesOn || bars.length ? bars.map(b => b.time) : marks.map(m => m.time));
    const arrows: SeriesMarker<Time>[] = [];
    for (const fill of fills) {
      const near = drawnTimes.reduce<number | null>((best, t) => best === null || Math.abs(t - fill.at) < Math.abs(best - fill.at) ? t : best, null);
      if (near === null || Math.abs(near - fill.at) > 30 * 60) continue;
      arrows.push({ time: near as UTCTimestamp, position: fill.side === "buy" ? "belowBar" : "aboveBar", shape: fill.side === "buy" ? "arrowUp" : "arrowDown",
        color: fill.provisional ? COLOR.provisional : COLOR.fill });
    }
    current.markers = [createSeriesMarkers(primary, arrows.sort((a, b) => (a.time as number) - (b.time as number)))];
    const key = `${held.occ}|${data.day}`;
    if (fitted.current !== key && slots.length) { chart.timeScale().fitContent(); fitted.current = key; }
    chart.priceScale("right").applyOptions({ autoScale: true });
  }, [bars, marks, fills, style, step, held.occ, data.day]);

  const latest = priceAt(bars, marks, Infinity);
  const at = hover ? priceAt(bars, marks, hover.time) : null;
  const stockAt = hover ? atOrBefore(stock, hover.time) : null;
  const fillsAt = hover ? fills.filter(f => f.at >= hover.time && f.at < hover.time + step) : [];
  const today = data.as_of != null && nyDate.format(data.as_of * 1000) === data.day;
  const earlier = data.day && !today ? dayFmt.format(new Date(`${data.day}T12:00:00Z`)) : null;
  const pnlNow = latest ? pnlAt(held, latest.price) : null;
  const size = `${held.quantity} contract${held.quantity === 1 ? "" : "s"}`;
  const far = fills.filter(f => latest && Math.abs(f.price - latest.price) / latest.price > FILL_REACH);

  return (
    <div className="space-y-1.5" data-testid="desk-contract">
      <p className="min-h-4 text-xs leading-4 tabular-nums text-muted-foreground sm:h-4 sm:truncate" data-testid="desk-contract-readout">
        {latest && <>
          <span className="sr-only">{held.label} · </span>{latest.kind === "trade" ? "Last trade" : "Mark"} <span className="text-foreground">{premium(latest.price)}</span> {nyWhen(latest.time)}
          {pnlNow !== null && <> · <span className={pnlNow > 0 ? "text-emerald-300" : pnlNow < 0 ? "text-rose-300" : undefined}>{usd(pnlNow)}</span> on {size}</>}
          {earlier && <> · {earlier}, the last session with trades</>}
        </>}
      </p>
      <div className="relative">
        <div ref={host} role="img" data-testid="desk-contract-canvas" data-style={style} data-bars={bars.length} data-marks={marks.length} data-fills={fills.length}
          aria-label={`${held.label} ${earlier ?? "today"}: ${style === "candles" ? "2-minute candles" : "a line"} from its trades${marks.length ? ", its mark where the desk saw it" : ""}, and your fills`}
          style={{ WebkitTouchCallout: "none", WebkitUserSelect: "none", userSelect: "none" }}
          className="h-[320px] w-full overflow-hidden rounded border sm:h-[420px] lg:h-[var(--desk-candles,420px)]" />
        {hover && at && (
          <div role="tooltip" data-testid="desk-contract-tip"
            className="pointer-events-none absolute top-2 z-10 max-w-[min(18rem,85%)] rounded border bg-popover/95 px-2 py-1.5 text-xs tabular-nums shadow"
            style={hover.x > hover.width / 2 ? { right: `${Math.max(8, hover.width - hover.x + 12)}px` } : { left: `${hover.x + 12}px` }}>
            <p className="text-muted-foreground">{nyWhen(hover.time)}</p>
            <p><span className="text-foreground">{premium(at.price)}</span>{" "}
              <span className="text-muted-foreground">{at.kind === "trade" ? "trade" : "mark"}{at.time + step <= hover.time ? `, ${nyWhen(at.time)}` : ""}</span></p>
            <p data-testid="desk-contract-tip-pnl" className={pnlAt(held, at.price) > 0 ? "text-emerald-300" : pnlAt(held, at.price) < 0 ? "text-rose-300" : undefined}>
              {usd(pnlAt(held, at.price))} on {size}</p>
            {stockAt && hover.time - stockAt.time <= 10 * 60 && <p data-testid="desk-contract-tip-stock" className="text-muted-foreground">{held.symbol} <span className="text-foreground">{stockAt.price.toFixed(2)}</span></p>}
            {fillsAt.map((f, i) => <p key={i} style={{ color: COLOR.fill }}>{f.text}</p>)}
          </div>
        )}
      </div>
      <p aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" data-testid="desk-contract-legend">
        <span><span style={{ color: COLOR.trade }}>{style === "candles" ? "▮" : "—•"}</span> trades</span>
        {marks.length > 0 && <span><span style={{ color: COLOR.mark }}>┈</span> mark (bid/ask mid, else last) while the desk was open</span>}
        {fills.length > 0 && <span><span style={{ color: COLOR.fill }}>▲▼</span> your fills{fills.some(f => f.provisional) ? " (dashed: Robinhood, provisional)" : ""}</span>}
        {far.length > 0 && <span>{far.map(f => `${f.side === "buy" ? "Buy" : "Sell"} ${premium(f.price)}`).join(", ")} off the chart</span>}
      </p>
    </div>
  );
}
