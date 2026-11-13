"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker,
  type Time, type UTCTimestamp, type WhitespaceData, type LineData,
} from "lightweight-charts";
import { nyWhen } from "@/components/copilot/DeskChart";
import { getDeskContract, type DeskContractData, type DeskContractFill, type DeskOrder, type DeskThread } from "@/lib/desk";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

/*
 * A held option's own chart on the desk (docs/copilot-lab.md § The desk): with a held single-leg option selected, the
 * centre chart's header offers Stock / Contract, remembered per contract in this browser. Contract shows the option's
 * price for its latest session with trades (``GET /copilot/desk/contract``: Tradier's minute trades, as 2-minute candles
 * when they are dense, else a line through the prints), its mark (bid/ask midpoint) as a dotted line where the desk's
 * live prices saw it, his fills as lines at their premium (Robinhood's not-yet-emailed fills marked provisional), and at
 * the cursor: the price and which it is, his P&L in dollars for his size, and the stock's price at that moment.
 *
 * One read when the row is selected (so the toggle only shows when there is something to draw), then once a minute
 * while the Contract view is shown, visible and the market can move; the mark moves with the shared live prices in
 * between. No history: no toggle, never an invented line.
 */

const OCC = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/;
const VIEW_STORE = "desk.chart.contract.v1";
const REFRESH_MS = 60_000;
const COLOR = { trade: "#e4e4e7", mark: "#7dd3fc", fill: "#e9a23b", provisional: "#e9a23b99" };
/** Two marks further apart than this are not joined: the desk was not open to see between them. */
const MARK_GAP = 10 * 60;
/** A fill line further than this from the last price does not stretch the price scale. */
const FILL_REACH = 0.6;
const MAX_FILL_LINES = 6;
const ET = "America/New_York";
const NO_ORDERS: DeskOrder[] = [];
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" });
const nyDate = new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" });
const premium = (value: number) => value.toFixed(2);
const usd = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

export type HeldContract = {
  occ: string; symbol: string; label: string;
  /** The book's P&L terms (``book.tick``): cost a contract, contracts, side. */
  cost: number; quantity: number; sign: 1 | -1; scale: number;
  orders: DeskOrder[];
};

/** The selected row as a held single-leg option the Contract view can draw, or null: a stock, a row without the book's
 * quote terms, a hidden ticker, or one leg of a structure (another option on the ticker held the other way). */
export function heldContract(row: DeskThread | null | undefined, rows: readonly DeskThread[] = []): HeldContract | null {
  const book = row?.book, tick = book?.tick, option = book?.option;
  if (!row || row.hidden || !row.symbol || !book || !tick || !option || tick.scale !== 100 || !OCC.test(tick.quote) || !(tick.cost > 0) || !(tick.quantity > 0)) return null;
  const legs = rows.filter(r => r !== row && r.key !== row.key && r.symbol === row.symbol && r.book?.option);
  if (legs.some(r => r.book?.option?.direction !== option.direction)) return null;
  const what = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
  return { occ: tick.quote, symbol: row.symbol, label: what.startsWith(`${row.symbol} `) ? what : `${row.symbol} ${what}`,
    cost: tick.cost, quantity: tick.quantity, sign: tick.sign, scale: tick.scale, orders: book.orders ?? NO_ORDERS };
}

/** His P&L in dollars at a per-share premium, by the book's own formula (``tickedBook``). */
export const pnlAt = (held: Pick<HeldContract, "cost" | "quantity" | "sign" | "scale">, price: number) =>
  Math.round(held.sign * (price * held.scale - held.cost) * held.quantity * 100) / 100;

/** Robinhood's fills on this contract today that the journal does not have yet (#776's order lines), as fill lines. */
export function provisionalFills(orders: readonly DeskOrder[]): DeskContractFill[] {
  return orders.filter(o => o.instrument === "option" && o.filled > 0 && o.filled_at && o.avg && o.pairing === "provisional" && o.price_kind !== "net")
    .map(o => {
      const side = o.action.toLowerCase().startsWith("buy") ? "buy" as const : "sell" as const;
      return { at: o.filled_at!, side, opening: o.action.toLowerCase().endsWith("open"), contracts: o.filled, price: o.avg!, provisional: true,
        text: `${side === "buy" ? "Bought" : "Sold"} ${o.filled} at ${premium(o.avg!)} (Robinhood, provisional)` };
    });
}

const readViews = (): Record<string, "contract"> => {
  try { const saved = JSON.parse(window.localStorage.getItem(VIEW_STORE) ?? "{}"); return saved && typeof saved === "object" ? saved : {}; } catch { return {}; }
};

export type ContractView = { available: boolean; view: "stock" | "contract"; pick(view: "stock" | "contract"): void; data: DeskContractData | null };

/** The selected contract's read and the remembered Stock / Contract choice for it. */
export function useContractView(held: HeldContract | null): ContractView {
  const occ = held?.occ ?? null, symbol = held?.symbol ?? null;
  const [read, setRead] = useState<DeskContractData | null>(null);
  const [views, setViews] = useState<Record<string, "contract">>({});
  const [tick, setTick] = useState(0);
  useEffect(() => { setViews(readViews()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  useEffect(() => {
    if (!occ || !symbol) return;
    const controller = new AbortController();
    getDeskContract(symbol, occ, controller.signal)
      // A failed or empty refresh keeps the chart already shown for this contract.
      .then(data => { if (!controller.signal.aborted) setRead(prev => data.state !== "ok" && prev?.state === "ok" && prev.occ === occ && data.state === "unavailable" ? prev : { ...data, occ }); })
      .catch(() => { if (!controller.signal.aborted) setRead(prev => prev?.occ === occ ? prev : null); });
    return () => controller.abort();
  }, [occ, symbol, tick]);
  const data = read && occ && read.occ === occ ? read : null;
  const available = data?.state === "ok";
  const view = available && occ && views[occ] === "contract" ? "contract" : "stock";
  const live = !!data?.live;
  useEffect(() => {
    if (view !== "contract" || !live) return;
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [view, live, occ]);
  const pick = (next: "stock" | "contract") => {
    if (!occ) return;
    setViews(prev => {
      const out = { ...prev };
      if (next === "contract") out[occ] = "contract"; else delete out[occ];
      try { window.localStorage.setItem(VIEW_STORE, JSON.stringify(out)); } catch { /* this visit only */ }
      return out;
    });
  };
  return { available, view, pick, data: available ? data : null };
}

/** Stock / Contract, beside the timeframes in the chart header. */
export function ChartViewToggle({ view, onPick }: { view: "stock" | "contract"; onPick(view: "stock" | "contract"): void }) {
  return (
    <div role="group" aria-label="Chart of" data-testid="desk-chart-view" className="flex gap-1">
      {(["stock", "contract"] as const).map(item => (
        <button key={item} type="button" aria-pressed={view === item} onClick={() => onPick(item)}
          className={cn("min-h-11 rounded border px-2 text-xs sm:min-h-0 sm:py-0.5",
            view === item ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {item === "stock" ? "Stock" : "Contract"}
        </button>
      ))}
    </div>
  );
}

type Point = { time: number; price: number };
type Hover = { time: number; x: number; width: number };

/** The newest of ``points`` at or before ``at`` (sorted by time), or undefined. */
function atOrBefore<T extends { time: number }>(points: readonly T[], at: number): T | undefined {
  let low = 0, high = points.length;
  while (low < high) { const mid = (low + high) >>> 1; if (points[mid].time <= at) low = mid + 1; else high = mid; }
  return points[low - 1];
}

/** Server marks plus the live one in its 2-minute slot (today only, never a stale one). */
export function mergedMarks(marks: readonly Point[], live: { last: number; at: number; stale: boolean } | null, day: string | null | undefined, step: number): Point[] {
  if (!live || live.stale || !day || nyDate.format(live.at * 1000) !== day) return [...marks];
  const slot = live.at - (live.at % step);
  return [...marks.filter(m => m.time < slot), { time: slot, price: live.last }];
}

/** What the cursor reads at ``at``: the trade or mark in its slot, else the newest one before it (with its time). */
export function priceAt(bars: readonly { time: number; close: number }[], marks: readonly Point[], at: number):
  { price: number; kind: "trade" | "mark"; time: number } | null {
  const trade = atOrBefore(bars, at), mark = atOrBefore(marks, at);
  if (!trade && !mark) return null;
  if (trade && (!mark || trade.time >= mark.time)) return { price: trade.close, kind: "trade", time: trade.time };
  return { price: mark!.price, kind: "mark", time: mark!.time };
}

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
          className="h-[320px] w-full overflow-hidden rounded border sm:h-[420px]" />
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
