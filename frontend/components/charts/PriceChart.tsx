"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, ColorType, CrosshairMode, LineStyle, TickMarkType } from "lightweight-charts";
import type { IChartApi, ISeriesApi, Time, UTCTimestamp } from "lightweight-charts";
import { Expand, Eye, EyeOff, Link2, LocateFixed, Maximize2, Minimize2, NotebookPen, Pin, SlidersHorizontal, Timer } from "lucide-react";
import { isMacroSymbol, macroIndicators, instrumentPrice, instrumentTime, supportedIntervals, INDICATOR_COLORS, COMPACT_OPENING_BARS, COMPACT_PANEL, INDICATOR_NAMES, INTERVAL_SECONDS, OPENING_BARS, PANEL_OPENING_BARS, STUDIES, barAt, barChange, barClock, countdown, earningsMarks, etTime, gapSeconds, intradayInterval, price, nyDay, rvolCoverage, rvolText, slimIndicators, staleCandles, volumeAlpha } from "@/lib/charts";
import type { ColorKey, AutoLevels, ChartBar, ChartCommand, ChartCommands, ChartJump, ChartPanelData, CrosshairLink, EarningsMark, FillLabels, Indicators, Interval, LevelInteraction, MarketDay, PanelStudies, PriceLevel, RangeLink, RvolBaseline } from "@/lib/charts";
import type { Earnings, NewsArticle } from "@/lib/symbolInfo";
import { newsMarks, newsTip } from "@/lib/newsMarkers";
import type { NewsCluster } from "@/lib/newsMarkers";
import { groupFills, MarkLayer } from "@/lib/chartMarks";
import type { FillGroup } from "@/lib/chartMarks";
import { chartCommitted } from "@/lib/chartPerformance";
import { useClock, useLivePanel } from "@/lib/chartStore";
import { DRAG_START, DrawingLayer, drawingShape, levelShape, MOUSE_SLOP, moveHandle, POINTS, roundPrice, shiftPoints, Timeline, TOUCH_SLOP } from "@/lib/drawings";
import type { Anchor, Drawing, DrawingKind, DrawingPatch, Shown, Tool, ToolStyle } from "@/lib/drawings";
import { AutoLevelLayer, chartLabel, isOption, isRange, shownZones } from "@/lib/autoLevels";
import { AlertLayer } from "@/lib/alerts";
import { SessionShade } from "@/lib/sessionShade";
import { DepthHeatLayer, DepthProfileLayer, WALL_COLORS, WallLayer } from "@/lib/depthHeatmap";
import type { DepthHeatmap, DepthProfile, HeatBookKind, WallLine } from "@/lib/depthHeatmap";
import type { AlertMark } from "@/lib/alerts";
import EarningsBadge from "./EarningsBadge";
import LevelCard from "./LevelCard";
import { positionLineTitle, type ChartPosition } from "@/lib/chartJournal";
import SelectionBar from "./SelectionBar";
import ToolbarMenu from "./ToolbarMenu";
import type { MenuRequest } from "./ChartMenu";
import type { LiveFeed } from "@/lib/chartStore";
import { ZOOM_SPEEDS, readZoomSpeed } from "@/lib/zoomSpeed";

const OVERLAYS = ["ema9", "ema20", "ema50", "ema200", "vwap"] as const;
const tickFormats = {
  [TickMarkType.Year]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric" }),
  [TickMarkType.Month]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short" }),
  [TickMarkType.DayOfMonth]: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }),
};
type Overlay = typeof OVERLAYS[number];
const MIN_BAR_SPACING = 2;
const NO_DRAWINGS: Drawing[] = [];
const NO_ALERTS: AlertMark[] = [];
const NO_POSITIONS: (ChartPosition & { pnl?: number | null })[] = [];
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
/** The range bands' VWAP bands (C2.7): VWAP plus and minus one and two of the session's standard deviations. */
const VWAP_BANDS = [2, 1, -1, -2] as const;
/** A VWAP band is the VWAP color at a faint alpha, the nearer bands stronger. */
const bandColor = (vwap: string, k: number) => vwap + (Math.abs(k) === 1 ? "70" : "45");
type VwapBand = typeof VWAP_BANDS[number];
function bandPoint(bars: ChartBar[], index: number, k: VwapBand) {
  const b = bars[index];
  if (b.vwap === null || b.vwap_sd == null) return { time: b.time as UTCTimestamp };
  const next = bars[index + 1];
  const gapAfter = next && (next.vwap === null || next.vwap_sd == null || Math.floor(next.time / 86400) !== Math.floor(b.time / 86400));
  return { time: b.time as UTCTimestamp, value: b.vwap + k * b.vwap_sd, ...(gapAfter ? { color: "transparent" } : {}) };
}
const candlePoint = (b: ChartBar) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
// Up or down by the candle, brighter with its relative volume (C2.4).
const volumePoint = (b: ChartBar) => ({ time: b.time as UTCTimestamp, value: b.volume, color: (b.close >= b.open ? "#2bc9a4" : "#ee617a") + volumeAlpha(b.rvol) });
const rsiPoint = (b: ChartBar) => b.rsi === null ? { time: b.time as UTCTimestamp } : { time: b.time as UTCTimestamp, value: b.rsi };
/**
 * The opening zoom: the latest `count` candles. Fewer candles than that
 * (today's first premarket minutes, before the history pages arrive) sit at the
 * right with room to their left, so the history fills in at this zoom instead of
 * stretching the first few candles across the chart.
 */
const openingRange = (bars: number, count: number) => ({ from: bars - count, to: bars + 4 });
/**
 * Reset: the latest candles at the opening zoom, every pane's price scale back
 * to automatic (dragging an axis turns it off). Realtime: the latest candle at
 * the current zoom.
 */
function moveView(chart: IChartApi, bars: number, opening: number, command: ChartCommand) {
  const scale = chart.timeScale();
  if (command === "reset") {
    chart.panes().forEach((_, pane) => chart.priceScale("right", pane).applyOptions({ autoScale: true }));
    scale.setVisibleLogicalRange(openingRange(bars, opening));
    return;
  }
  const range = scale.getVisibleLogicalRange();
  const width = range ? range.to - range.from : opening + 4;
  scale.setVisibleLogicalRange({ from: bars + 4 - width, to: bars + 4 });
}
/** Browser tests register a map here to inspect chart ranges; production never defines it. */
type ChartRegistry = Map<string, IChartApi>;
/** Browser tests register a map here to count each chart's committed renders; production never defines it. */
type RenderCounts = Map<string, number>;
/** Browser tests register a map here to read where drawings are drawn; production never defines it. */
type LayerRegistry = Map<string, DrawingLayer>;
/** Browser tests register a map here to read which automatic levels are drawn, and where; production never defines it. */
type AutoRegistry = Map<string, AutoLevelLayer>;
/** An automatic level's open card: hovered, or kept open by a tap or click (`pinned`), beside the pointer's height. */
type Card = { id: string; pinned: boolean; y: number; above: boolean };
/** What the chart says while a tool waits for a click; `second` is a two-point tool's second click. */
const PLACE_TEXT: Record<Tool, string> = { level: "Click a price to save a level", ray: "Click where the ray starts", trend: "Click the first point of the line",
  zone: "Click one corner of the zone", note: "Click where the note goes" };
const SECOND_TEXT: Partial<Record<Tool, string>> = { trend: "Click the second point", zone: "Click the opposite corner" };
/** A finger held this long without moving opens the chart menu (C1.3); moving further than `HOLD_SLOP` first is a pan or a crosshair scrub. */
const LONG_PRESS = 500;
const HOLD_SLOP = 10;
/**
 * Room for the candles: the price scale leaves this fraction of the pane above and below the candles, and volume is a thin strip along the
 * bottom (drawn from `VOLUME_TOP` down, a little under the lowest candles, faint enough to read through) instead of a band the candles must clear.
 */
const CANDLE_MARGINS = { top: 0.10, bottom: 0.12 };
const VOLUME_TOP = 0.88;
/** How far from a fill chevron or news marker the pointer still counts as on it (the marker layer widens it for a finger). */
const MARK_SLOP = 3;
/** A jump to an item drawn before the loaded candles (C1.4) loads at most this many older pages, and gives up after this long. */
const JUMP_PAGES = 20;
const JUMP_MS = 20_000;
/** When a news marker's stories were published: its candle, or the first and last of the candles it joins. */
function newsSpan(mark: NewsCluster, interval: Interval) {
  const day = (t: number) => etTime(t, true);
  if (!intradayInterval(interval)) return mark.last === mark.time ? `${day(mark.time)} session` : `${day(mark.time)} – ${day(mark.last)} sessions`;
  if (mark.last === mark.time) return `${day(mark.time)} ${etTime(mark.time)} ET candle`;
  return day(mark.time) === day(mark.last) ? `${day(mark.time)} ${etTime(mark.time)} – ${etTime(mark.last)} ET candles` : `${day(mark.time)} ${etTime(mark.time)} – ${day(mark.last)} ${etTime(mark.last)} ET`;
}
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
  // Closed reads the same on every chart: the main chart says it once.
  if (value === null || (!main && value === "closed")) return null;
  const live = typeof value === "number";
  return <span role="timer" aria-label={`${label} next bar`} title={live ? "Time until this candle closes" : undefined}
    className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 font-mono text-[10px] ${main ? "mr-1" : "ml-auto"} ${live ? "bg-sky-400/10 text-sky-300" : value === "closed" || value === "paused" ? "bg-slate-800 text-slate-400" : "bg-amber-400/10 text-amber-300"}`}>
    <Timer size={11} />{live ? countdown(value) : CLOCK_TEXT[value]}</span>;
}

const compactVolume = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

type HoverStore = ReturnType<typeof hoverStore>;
/** The candle under a chart's crosshair, by time; followers of a linked crosshair set theirs too. */
function hoverStore() {
  let time: number | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => time,
    set(next: number | null) { if (next === time) return; time = next; listeners.forEach((fn) => fn()); },
    subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  };
}

/**
 * The candle values row: the hovered candle's, else the latest. Its own component, so a crosshair move renders only this row.
 * From a tablet's width, like TradingView's legend, it sits over the top of the candles under the title line, so it costs the
 * chart no height; there a click or right-click on it reaches the chart beneath (the EMA and VWAP items take the pointer for their explanations). A phone's
 * row wraps to several lines, so there it stays above the candles.
 */
function CandleValues({ id, symbol, main, pending, bars, hover, interval, indicators, colors, vwapBands, rvol: today, pastRvol, showRvol, timer }: {
  id: string; symbol: string; main: boolean; pending: boolean; bars: ChartBar[] | undefined; hover: HoverStore; interval: Interval;
  indicators: Indicators; colors: Record<ColorKey, string>; vwapBands: boolean; rvol: RvolBaseline | null; pastRvol?: Record<string, RvolBaseline>; showRvol: boolean; timer: React.ReactNode;
}) {
  const formatPrice = (value: number | null | undefined) => instrumentPrice(value, symbol);
  const time = useSyncExternalStore(hover.subscribe, hover.get, hover.get);
  const bar = (time !== null && barAt(bars ?? [], time)) || bars?.at(-1);
  // An older session's own baseline from its history page (C2.6); otherwise today's, from the workspace.
  const rvol = (bar && pastRvol?.[nyDay(bar.time)]) || today;
  // The main chart's study row says it in full. A smaller chart's row is already tight beside its
  // countdown, so there RVol takes the volume's place, with the volume and the rest on hover.
  const volumeText = bar ? compactVolume.format(bar.volume) : "";
  const rvolValue = showRvol && bar && bar.rvol !== undefined && !bar.extended ? (typeof bar.rvol === "number"
    ? <span className="text-slate-400" title={`${main ? "" : `Vol ${volumeText}. `}RVol ${rvolText(bar.rvol)} for ${etTime(bar.time)}. ${rvol ? rvolCoverage(rvol) : "RVol"}: regular-session volume through this candle over their average through the same minute. A candle still forming counts its volume so far.`}>
      RVol <span className="text-slate-300">{rvolText(bar.rvol)}</span>{main && <> for {etTime(bar.time)}</>}</span>
    : main ? <span className="text-slate-400" title={rvol && rvol.state !== "ready" && rvol.message ? rvol.message : "Fewer than five of the baseline sessions had traded by this minute."}>RVol —</span> : null) : null;
  const emas = (["ema9", "ema20", "ema50", "ema200"] as const).filter((key) => indicators[key]);
  // Why a candle has no VWAP, from how the backend builds it (chart_math.chart_bars): regular-session minutes only, never daily or weekly.
  const vwapWhy = interval === "1D" || interval === "1W" ? "VWAP is an intraday study: daily and weekly candles have none."
    : bar?.extended ? "VWAP covers the regular session only: this candle is in extended hours."
    : "VWAP starts with the session's first regular-hours trade: none has traded yet.";
  return (
    <div className={`relative z-10 flex min-w-0 shrink-0 md:pointer-events-none md:absolute md:inset-x-0 md:top-7 items-center gap-2 whitespace-nowrap px-3 font-mono text-[10px] text-slate-500 ${main ? "min-h-6 flex-wrap gap-y-0.5 pb-1 md:pr-20" : "h-6 md:pr-16"}`}>
      <div className="-ml-1 flex min-w-0 items-center gap-2 overflow-hidden rounded bg-[#10151e]/90 px-1" aria-label={`${id} candle values`}>
      {pending ? null : bar ? <>{main && <><span>O <span className="text-slate-300">{formatPrice(bar.open)}</span></span><span>H <span className="text-slate-300">{formatPrice(bar.high)}</span></span><span>L <span className="text-slate-300">{formatPrice(bar.low)}</span></span></>}<span>C <span className={bar.close >= bar.open ? "text-emerald-400" : "text-rose-400"}>{formatPrice(bar.close)}</span></span>{!main && !isMacroSymbol(symbol) && (rvolValue && !bar.volumePending ? rvolValue : <span>Vol {bar.volumePending ? "pending" : volumeText}</span>)}{/* The status strip names Tradier for every chart; a smaller chart names its source only when it differs. */}
        {(main || bar.source === "alpaca_sip") && <span title={bar.source === "alpaca_sip" ? "Alpaca SIP minutes, stored raw. The price basis chip says how splits are shown." : "Tradier"}>{bar.source === "alpaca_sip" ? "SIP" : "Tradier"}</span>}</> : <span>No candles in this window</span>}
      </div>
      {!main && timer}
      {main && <div aria-label={`${id} study values`} className="flex min-w-0 max-w-full flex-wrap items-center gap-x-3 rounded bg-[#10151e]/90 px-1 gap-y-0.5 whitespace-normal font-mono text-[10px]">
        {indicators.vwap && <span style={{ color: colors.vwap }} title={bar && bar.vwap == null ? vwapWhy : undefined}>VWAP {price(bar?.vwap)}</span>}
        {vwapBands && <span className="pointer-events-auto" style={{ color: colors.vwap }} title={bar?.vwap == null ? vwapWhy : bar.vwap_sd == null ? "VWAP band data is unavailable for this candle." : `RTH VWAP bands: ±1σ ${price(bar.vwap - bar.vwap_sd)}–${price(bar.vwap + bar.vwap_sd)}; ±2σ ${price(bar.vwap - 2 * bar.vwap_sd)}–${price(bar.vwap + 2 * bar.vwap_sd)}. Volume-weighted HLC3 dispersion since 9:30 ET.`}>VWAP bands {bar?.vwap != null && bar.vwap_sd != null ? "±1σ / ±2σ" : "—"}</span>}
        {indicators.rsi && <span className="text-violet-300">RSI {price(bar?.rsi)}</span>}
        {/* A phone shows the EMA values in the row; a desktop folds them into one item that opens on hover or focus. */}
        {emas.map((key) => <span key={key} className="md:hidden" style={{ color: colors[key] }}>{key.toUpperCase()} {formatPrice(bar?.[key])}</span>)}
        {emas.length > 0 && <span tabIndex={0} role="group" aria-label="EMA values" aria-describedby={`${id}-ema-values`} className="group pointer-events-auto relative hidden cursor-default rounded outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60 md:inline">
          <span className="text-slate-300">EMA</span>{emas.map((key) => <span key={key} aria-hidden style={{ background: colors[key] }} className="ml-1 inline-block h-1.5 w-1.5 rounded-full align-middle" />)}
          <span id={`${id}-ema-values`} role="tooltip" data-ema-values className="absolute left-0 top-full z-30 mt-1 hidden gap-x-3 rounded border border-slate-600/60 bg-[#141b26] px-2 py-1 shadow-lg group-hover:flex group-focus:flex">
            {emas.map((key) => <span key={key} style={{ color: colors[key] }}>{key.toUpperCase()} {formatPrice(bar?.[key])}</span>)}</span>
        </span>}
        {rvolValue}
        {showRvol && rvol && <span role="note" aria-label="Relative volume baseline" title={rvol.message ?? undefined} className={rvol.state === "ready" ? "text-slate-400" : "text-amber-300/80"}>
          {rvol.state === "ready" ? rvolCoverage(rvol) : rvol.state === "building" ? "RVol baseline not built yet" : "RVol unavailable"}</span>}
      </div>}
    </div>
  );
}

type Bundle = {
  chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram">;
  shade: SessionShade; rsi?: ISeriesApi<"Line">;
  lines: Record<Overlay, ISeriesApi<"Line">>; bands: Record<VwapBand, ISeriesApi<"Line">>; marks: MarkLayer; layer: DrawingLayer; auto: AutoLevelLayer; bells: AlertLayer;
  /** The symbol and interval now drawn; a new one opens on its latest candles. */
  frame: string;
};

export default function PriceChart({ id, symbol, indexAsOf = null, follows, onPickSymbol, interval, session, panel: rest, pending, notice, live, indicators: requested, colors = INDICATOR_COLORS, ownStudies = null, onStudies, studiesHidden = false, levels, drawings = NO_DRAWINGS, autoLevels = null, levelEvents, optionsNearest = null, rangeBands = false, vwapBands = false, highlight = null, rvol = null, earnings = null, news = null, newsSmall = false, fillLabels = "off", onNews, alerts = NO_ALERTS, link, rangeLink, commands, linkRange = false, clock, height, main = false, tool = null, magnet = false, toolStyle, maximized, history, selected = null, showSelection = false, fresh = null, onNeedHistory, onRetryHistory, onVisibleRange, onUserMove, onDraw, onPlace, onSelect, onMove, onEditDrawing, onDelete, onMenu, onUnlock, onInterval, onFocus, onMaximize, onPlan, positions = NO_POSITIONS, onFill, depth = null, liquidity = null }: {
  indexAsOf?: number | null;
  id: string; symbol: string; interval: Interval; session: string; panel?: ChartPanelData; live: LiveFeed; indicators: Indicators; levels: PriceLevel[];
  /** The studies' line colors (the user's choices over the defaults). */
  colors?: Record<ColorKey, string>;
  /**
   * A smaller chart's own studies, from its header menu, already in `indicators`; null follows the workspace's,
   * slimmed while the chart is compact. `onStudies` sets them (null: follow again); `studiesHidden` is the Indicators group hidden everywhere.
   */
  ownStudies?: PanelStudies | null; onStudies?(next: PanelStudies | null): void; studiesHidden?: boolean;
  /** This symbol's drawings on the chart's basis. */
  drawings?: Drawing[];
  /** This symbol's automatic levels (C2.3), null while hidden, and this chart's interactions with them. */
  autoLevels?: AutoLevels | null; levelEvents?: Record<string, LevelInteraction>;
  /** With the options layer on (C4.4), how many option zones each side of the price draw besides the walls; null while it is off. */
  optionsNearest?: number | null;
  /** Expected-move levels (C2.7), independently of VWAP bands. */
  rangeBands?: boolean;
  /** RTH VWAP ±1σ/±2σ; workspace visibility, independent of expected move. */
  vwapBands?: boolean;
  /** A strike chosen on the ladder (C4.5), drawn as a solid line. */
  highlight?: number | null;
  /** This symbol's relative-volume baseline for today (C2.4), null on a day without a session. */
  rvol?: RvolBaseline | null;
  /** This symbol's earnings (C2.5): markers on report dates, and the header badge. */
  earnings?: Earnings | null;
  /** The main chart's news markers (T3.5): the symbol's articles, or null while the layer is off. Only Focused articles are marked. */
  news?: { symbol: string; articles: NewsArticle[] } | null;
  /** A smaller chart marks news too (Layers, News markers: News on small charts); off, only the main chart does. */
  newsSmall?: boolean;
  /** Which fills the main chart labels with text (Layers, Journal): none, the newest candle's, or all. Smaller charts never label. */
  fillLabels?: FillLabels;
  /** A click on a news marker (a tap's popover button on touch): the ids of the articles on that candle. */
  onNews?(ids: string[]): void;
  /** This symbol's level alerts (C5.1), on the chart's basis: a bell at each price. */
  alerts?: AlertMark[];
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
  history?: { loading: boolean; exhausted: boolean; warmup: string; issue: string | null; calendarNote?: string | null; adjustmentNote?: string | null; historyStart?: string | null; rvol?: Record<string, RvolBaseline> };
  onNeedHistory?(before?: number): void; onRetryHistory?(): void; onVisibleRange?(range: { from: number; to: number }): void;
  /** The trader moved this chart's view themself (a drag, the wheel, a touch, Latest candles). */
  onUserMove?(): void;
  onInterval(interval: Interval): void; onFocus?(): void; onMaximize?(): void;
  /** Plan trade (C3.4) in the main chart's own bar, where a phone's toolbar has no room left. */
  onPlan?(): void;
  /** Open trades on this symbol (C3.2), on the chart's basis: a line where `line` is set. */
  positions?: (ChartPosition & { pnl?: number | null })[];
  /** A click on a fill arrow (C3.1): its fill id. */
  onFill?(id: string): void;
  /** A Level 2 heatmap drawn behind the candles (owner, NVDA); memory only. */
  depth?: { map: DepthHeatmap; kind: HeatBookKind } | null;
  /** Order flow from the depth recorder or a live session: wall lines and the latest book profile (owner). */
  liquidity?: { walls: WallLine[]; profile: DepthProfile | null; stale: boolean } | null;
}) {
  const macro = isMacroSymbol(symbol);
  const given = useMemo(() => macro ? macroIndicators(requested) : requested, [macro, requested]);
  const container = useRef<HTMLDivElement>(null);
  const colorsRef = useRef(colors);
  const box = useRef<HTMLElement>(null);
  // A smaller chart under `COMPACT_PANEL` is compact; the ref is read where the chart opens or resets its view.
  const [compact, setCompact] = useState(false);
  const compactNow = useRef(false);
  useLayoutEffect(() => {
    const element = box.current;
    if (!element || main) return;
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      if (!width && !height) return; // a panel hidden on a phone keeps what it was
      compactNow.current = width < COMPACT_PANEL.width || height < COMPACT_PANEL.height;
      setCompact(compactNow.current);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [main]);
  const openingBars = () => main ? OPENING_BARS : compactNow.current ? COMPACT_OPENING_BARS : PANEL_OPENING_BARS;
  const indicators = useMemo(() => compact && !ownStudies ? slimIndicators(given) : given, [compact, ownStudies, given]);
  const bundle = useRef<Bundle | null>(null);
  const barsRef = useRef<ChartBar[]>([]);
  const resets = useRef(0);
  const linking = useRef(linkRange);
  // Programmatic range changes (data resets, applying a linked range) must not
  // be re-broadcast; only user pans and zooms drive the other charts.
  const quietUntil = useRef(0);
  const quiet = () => { quietUntil.current = performance.now() + 60; };
  const requestedGaps = useRef(new Set<number>());
  const actions = useRef({ tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, onUserMove, interval, pending: !!pending, selected, onSelect, onMove, onEditDrawing, onMenu, onFill, onNews, exhausted: !!history?.exhausted });
  // The fill chevron under the pointer: its fills, listed (C3.1). A tap, or a click on several, pins the list so a fill can be picked from it.
  const [fillTip, setFillTip] = useState<{ group: FillGroup; x: number; y: number; width: number; pinned: boolean } | null>(null);
  // A news marker's headlines (T3.5), hovered or pinned by a tap; a pinned one opens the News tab from its button.
  // Dragging the price axis turns the price scale's automatic fit off (the candles can then leave the pane); the Auto chip turns it back on.
  const [manualScale, setManualScale] = useState<{ top: number } | null>(null);
  const autoScale = useRef<() => void>(() => {});
  const [newsOpen, setNewsOpen] = useState<{ mark: NewsCluster; x: number; y: number; width: number; height: number; pinned: boolean } | null>(null);
  // A jump waiting for older candles retries when they arrive (set by the chart's effect below).
  const retryJump = useRef<() => void>(() => {});
  // A two-point tool's first click, kept until the second; `second` re-renders the hint.
  const placing = useRef<{ kind: DrawingKind; first: Anchor } | null>(null);
  const [second, setSecond] = useState(false);
  const initial = useRef(true);
  // After Reset or Latest, candles that arrive keep the latest in view until the user moves the chart:
  // the range asked for applies on the chart's next frame, so a read before then is the old one.
  const pinnedLive = useRef(false);
  // The chart is created by a later effect, which applies the heatmap the first time.
  const heatRef = useRef<DepthHeatLayer | null>(null);
  const depthRef = useRef(depth);
  useEffect(() => { depthRef.current = depth; heatRef.current?.set(depth?.map ?? null, depth?.kind ?? "arca"); }, [depth]);
  const profileRef = useRef<DepthProfileLayer | null>(null);
  const wallRef = useRef<WallLayer | null>(null);
  const liquidityRef = useRef(liquidity);
  useEffect(() => { liquidityRef.current = liquidity; profileRef.current?.set(liquidity?.profile ?? null, !!liquidity?.stale); }, [liquidity]);
  // The crosshair's candle, outside React state: a move re-renders only the readout row, not the chart.
  const [hover] = useState(hoverStore);
  const [card, setCard] = useState<Card | null>(null);
  // A new frame dismisses cards until the next pointer input, while its crosshair readout still updates.
  const cardHoverEnabled = useRef(false);
  // `rest` is the REST snapshot plus older history; streamed trades are applied
  // here, per panel, so a tick re-renders only the charts whose candles moved.
  const panel = useLivePanel(live, interval, rest);
  useEffect(() => {
    const renders = (window as typeof window & { __tjRenders?: RenderCounts }).__tjRenders;
    renders?.set(id, (renders.get(id) ?? 0) + 1);
  });
  const exhausted = !!history?.exhausted;
  useEffect(() => { actions.current = { tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, onUserMove, interval, pending: !!pending, selected, onSelect, onMove, onEditDrawing, onMenu, onFill, onNews, exhausted }; }, [tool, magnet, toolStyle, onDraw, onPlace, onNeedHistory, onVisibleRange, onUserMove, interval, pending, selected, onSelect, onMove, onEditDrawing, onMenu, onFill, onNews, exhausted]);
  useEffect(() => { linking.current = linkRange; }, [linkRange]);

  // One chart for the panel's lifetime. Symbol, interval, session and RSI
  // changes swap data and panes in place (below), so switching never blanks.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#10151e" }, textColor: "#8593a9", fontSize: 10,
        // The status strip credits the library on every layout; one logo, on the main chart, is enough.
        attributionLogo: main, panes: { separatorColor: "#27303d", separatorHoverColor: "#46576b" } },
      grid: { vertLines: { color: "#1b2532" }, horzLines: { color: "#1b2532" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#75859b", labelBackgroundColor: "#34455a" }, horzLine: { color: "#75859b", labelBackgroundColor: "#34455a" } },
      // entireTextOnly: a price cut off at a pane's edge is left out rather than printed against the next pane's.
      rightPriceScale: { borderColor: "#263141", minimumWidth: main ? 66 : 54, scaleMargins: { top: CANDLE_MARGINS.top, bottom: CANDLE_MARGINS.bottom }, entireTextOnly: true },
      timeScale: { borderColor: "#263141", secondsVisible: false, rightOffset: 4, minBarSpacing: MIN_BAR_SPACING,
        tickMarkFormatter: (time: Time, kind: TickMarkType) => {
          if (typeof time !== "number") return null;
          return kind <= TickMarkType.DayOfMonth ? tickFormats[kind as keyof typeof tickFormats].format(time * 1000) : etTime(time);
        } },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#2bc9a4", downColor: "#ee617a", wickUpColor: "#2bc9a4", wickDownColor: "#ee617a", borderVisible: false });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "volume", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: true });
    volume.priceScale().applyOptions({ scaleMargins: { top: VOLUME_TOP, bottom: 0 } });
    const lines = {} as Bundle["lines"];
    for (const name of OVERLAYS) lines[name] = chart.addSeries(LineSeries, { color: colorsRef.current[name], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const bands = {} as Bundle["bands"];
    for (const k of VWAP_BANDS) bands[k] = chart.addSeries(LineSeries, { color: bandColor(colorsRef.current.vwap, k), lineWidth: 1,
      lineStyle: Math.abs(k) === 1 ? LineStyle.Dashed : LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, visible: false });
    // Fills, report dates and news are one primitive (`lib/chartMarks.ts`): the price scale ignores it, so a mark never shrinks the candles.
    const marks = new MarkLayer(() => barsRef.current);
    candles.attachPrimitive(marks);
    const shade = new SessionShade(() => barsRef.current);
    candles.attachPrimitive(shade);
    const timeline = new Timeline(() => barsRef.current, () => INTERVAL_SECONDS[actions.current.interval]);
    const heat = new DepthHeatLayer(timeline);
    candles.attachPrimitive(heat);
    heat.set(depthRef.current?.map ?? null, depthRef.current?.kind ?? "arca");
    heatRef.current = heat;
    const profile = new DepthProfileLayer();
    candles.attachPrimitive(profile);
    profile.set(liquidityRef.current?.profile ?? null, !!liquidityRef.current?.stale);
    profileRef.current = profile;
    const wallLayer = new WallLayer(timeline);
    candles.attachPrimitive(wallLayer);
    wallLayer.set(liquidityRef.current?.walls ?? []);
    wallRef.current = wallLayer;
    const layer = new DrawingLayer(timeline);
    candles.attachPrimitive(layer);
    const autoLayer = new AutoLevelLayer();
    candles.attachPrimitive(autoLayer);
    const bells = new AlertLayer();
    candles.attachPrimitive(bells);
    bundle.current = { chart, candles, volume, shade, lines, bands, marks, layer, auto: autoLayer, bells, frame: "" };
    const layers = (window as typeof window & { __tjDrawings?: LayerRegistry }).__tjDrawings;
    layers?.set(id, layer);
    (window as typeof window & { __tjMarks?: Map<string, MarkLayer> }).__tjMarks?.set(id, marks);
    const autoLayers = (window as typeof window & { __tjAutoLevels?: AutoRegistry }).__tjAutoLevels;
    autoLayers?.set(id, autoLayer);
    // An automatic level's card: hovering one shows it (unless the user's own level or drawing is
    // there); a tap or click keeps it open until the next one. It opens above the pointer in the lower half.
    const opened = (zone: string, y: number, pinned: boolean): Card => ({ id: zone, pinned, y, above: y > element.clientHeight / 2 });
    // A kept card gives way once its zone is no longer drawn (another symbol, a level that moved).
    const hoverCard = (zone: string | null, y: number) => setCard((open) => (open?.pinned && autoLayer.shown().includes(open.id)) || (open?.id ?? null) === zone ? open : zone ? opened(zone, y, false) : null);
    const tapCard = (zone: string | null, y: number) => setCard(zone ? opened(zone, y, true) : null);
    // The magnet is on, or Cmd/Ctrl is held for this click or move.
    const magnetOn = (held: boolean) => actions.current.magnet || held;
    const modifier = (event?: { metaKey: boolean; ctrlKey: boolean }) => !!(event?.metaKey || event?.ctrlKey);
    const ghost = (kind: Tool, points: Anchor[]) => {
      const style = actions.current.toolStyle;
      layer.setPreview(kind === "level" ? levelShape({ id: "placing", price: points[0].price, label: "" })
        : { id: "placing", kind, points, label: kind === "note" ? "Note" : "", color: style?.color ?? "#9cc2ff", width: style?.width ?? 1 });
    };
    let syncing = false;
    let ownsPointer = false;
    const releasePointer = () => { ownsPointer = false; };
    element.addEventListener("pointerleave", releasePointer);
    const stopLink = link.listen((time, source) => {
      if (source === id || syncing) return;
      ownsPointer = false;
      syncing = true;
      const bar = time === null ? undefined : barAt(barsRef.current, time);
      if (bar) chart.setCrosshairPosition(bar.close, bar.time as UTCTimestamp, candles);
      else chart.clearCrosshairPosition();
      hover.set(bar?.time ?? null);
      syncing = false;
    });
    chart.subscribeCrosshairMove((event) => {
      // Redraws report source-less positions for both local and linked crosshairs. The chart
      // owning the pointer must refresh its readout and card; followers must not open cards.
      if (syncing) return;
      if (event.sourceEvent) { ownsPointer = !!event.point; cardHoverEnabled.current = ownsPointer; }
      else if (event.point && !ownsPointer) return;
      if (!event.point) ownsPointer = false; // leaving the plot for an axis also releases it
      if (event.point && !event.sourceEvent) {
        // The redraw event arrives before primitives paint their new coordinates.
        layer.updateAllViews();
        autoLayer.updateAllViews();
      }
      const time = typeof event.time === "number" ? event.time : null;
      hover.set(time === null ? null : barAt(barsRef.current, time)?.time ?? null);
      link.emit(time, id);
      const at = event.point && cardHoverEnabled.current && (event.paneIndex ?? 0) === 0 && !actions.current.tool ? event.point : null;
      // A fill chevron under the pointer lists its fills (C3.1); a news marker, its headlines (T3.5). A list a tap or click pinned stays until the next one.
      const over = at ? marks.hit(at.x, at.y, MARK_SLOP) : null;
      const fill = over?.kind === "fill" ? over.group : undefined;
      setFillTip((open) => open?.pinned ? open : fill ? (open?.group.id === fill.id && open.group.fills.length === fill.fills.length ? open : { group: fill, x: at!.x, y: at!.y, width: element.clientWidth, pinned: false }) : null);
      const story = over?.kind === "news" ? over.cluster : undefined;
      setNewsOpen((open) => open?.pinned ? open : story ? (open?.mark.id === story.id ? open : { mark: story, x: at!.x, y: at!.y, width: element.clientWidth, height: element.clientHeight, pinned: false }) : null);
      hoverCard(at && !layer.hit(at.x, at.y, MOUSE_SLOP) ? autoLayer.hit(at.y, MOUSE_SLOP) : null, at?.y ?? 0);
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
      // An automatic level under the pointer, when no level or drawing of the user's is (C5.1 alerts on it).
      const auto = plot && !hit && !now.tool ? autoLayer.hit(at.y, touch ? TOUCH_SLOP : MOUSE_SLOP) : null;
      const value = plot ? layer.anchorAt(at.x, at.y, now.magnet)?.price ?? priceAt(at.y) : null;
      now.onMenu({ clientX, clientY, touch, price: value, id: hit?.id ?? null, auto, reset: () => { quiet(); pinnedLive.current = true; moveView(chart, barsRef.current.length, openingBars(), "reset"); } });
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
    // lightweight-charts zooms by deltaY / 100 per wheel event with no speed option, so a trackpad's small deltas crawl.
    // Re-send the event with deltaY scaled by this device's Zoom speed; deltaX (the pan) and the cursor anchor are untouched.
    const scaled = new WeakSet<Event>();
    const onWheel = (event: WheelEvent) => {
      const factor = ZOOM_SPEEDS[readZoomSpeed()];
      if (scaled.has(event) || factor === 1 || event.deltaY === 0) return;
      event.preventDefault(); event.stopPropagation();
      const again = new WheelEvent("wheel", { bubbles: true, cancelable: true, composed: true, view: window, clientX: event.clientX, clientY: event.clientY, screenX: event.screenX, screenY: event.screenY,
        deltaX: event.deltaX, deltaY: event.deltaY * factor, deltaZ: event.deltaZ, deltaMode: event.deltaMode, ctrlKey: event.ctrlKey, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey });
      scaled.add(again);
      (event.target as Element).dispatchEvent(again);
    };
    element.addEventListener("wheel", onWheel, { capture: true, passive: false });
    const unpin = () => { pinnedLive.current = false; actions.current.onUserMove?.(); };
    for (const type of ["mousedown", "touchstart", "wheel"]) element.addEventListener(type, unpin, { capture: true, passive: true });
    chart.subscribeClick((event) => {
      const now = actions.current;
      if (now.tool) return; // placing reads its own clicks (above)
      if (performance.now() < tapsOffUntil) return; // the lift after a long press
      if (!event.point || (event.paneIndex ?? 0) !== 0) { now.onSelect?.(null); tapCard(null, 0); setNewsOpen(null); setFillTip(null); return; }
      const touch = performance.now() - lastTouch < 1000;
      const slop = touch ? TOUCH_SLOP : MOUSE_SLOP;
      const hit = layer.hit(event.point.x, event.point.y, slop)?.id ?? null;
      // The marks are drawn by `marks`, and a finger finds one by where it is drawn: the library reports no hovered object for a tap.
      const over = hit ? null : marks.hit(event.point.x, event.point.y, touch ? TOUCH_SLOP : MARK_SLOP);
      // A fill chevron opens its trade's card (C3.1); one that holds several fills lists them first, to pick from. The user's own levels and drawings win where they overlap.
      if (over?.kind === "fill" && now.onFill) {
        now.onSelect?.(null); tapCard(null, 0); setNewsOpen(null);
        if (over.group.fills.length === 1) { setFillTip(null); now.onFill(over.group.fills[0].id); }
        else setFillTip({ group: over.group, x: event.point.x, y: event.point.y, width: element.clientWidth, pinned: true });
        return;
      }
      // A news marker (T3.5): a click opens the articles in the News tab; a tap shows their headlines first.
      if (over?.kind === "news") {
        now.onSelect?.(null); tapCard(null, 0); setFillTip(null);
        if (touch) setNewsOpen({ mark: over.cluster, x: event.point.x, y: event.point.y, width: element.clientWidth, height: element.clientHeight, pinned: true });
        else { setNewsOpen(null); now.onNews?.(over.cluster.articles.map((article) => article.id)); }
        return;
      }
      setFillTip(null);
      setNewsOpen(null);
      now.onSelect?.(hit);
      tapCard(hit ? null : autoLayer.hit(event.point.y, slop), event.point.y);
    });
    const stopRange = rangeLink.listen(id, (range) => {
      if (!linking.current || !barsRef.current.length) return;
      pinnedLive.current = false;
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
          if (bars[i + 1].time - bars[i].time <= gapSeconds(actions.current.interval)) continue;
          // A gap whose older side is in view (a past trade's day, C3.3) fills from that side, one
          // page's span at a time, toward the present; otherwise from its newer side, as before.
          const step = INTERVAL_SECONDS[actions.current.interval];
          const before = i >= Math.floor(range.from) - 1
            ? Math.min(bars[i + 1].time, bars[i].end_time + Math.max(gapSeconds(actions.current.interval), 1200 * step)) : bars[i + 1].time;
          if (!requestedGaps.current.has(before)) {
            requestedGaps.current.add(before);
            actions.current.onNeedHistory?.(before);
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
      pinnedLive.current = true;
      moveView(chart, barsRef.current.length, openingBars(), command);
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
        const width = range ? range.to - range.from : openingBars() + 4;
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
      pinnedLive.current = false;
      jump = { target, pages: 0, until: performance.now() + JUMP_MS, frame: bundle.current?.frame ?? "" };
      tryJump();
    });
    const stopSnapshot = commands.provideSnapshot(id, () => barsRef.current.length ? chart.takeScreenshot() : null);
    // Whether the candle pane's price scale still fits itself: read after anything that can change it (a drag, the wheel, a double click, a reset, a jump).
    let disposed = false;
    const syncScale = () => !disposed && setManualScale((now) => {
      if (candles.priceScale().options().autoScale) return now ? null : now;
      const top = Math.max(0, (chart.panes()[0]?.getHeight() ?? 0) - 22);
      return now && now.top === top ? now : { top };
    });
    const afterScale = () => { window.setTimeout(syncScale, 0); window.setTimeout(syncScale, 120); };
    autoScale.current = () => { candles.priceScale().applyOptions({ autoScale: true }); syncScale(); };
    for (const type of ["pointerup", "mouseup", "touchend", "dblclick", "wheel"]) window.addEventListener(type, afterScale, { capture: true, passive: true });
    const scaleWatch = new ResizeObserver(syncScale);
    scaleWatch.observe(element);
    const stopScale = commands.listen(afterScale);
    const stopScaleJump = commands.listenJump(afterScale);
    const registry = (window as typeof window & { __tjCharts?: ChartRegistry }).__tjCharts;
    registry?.set(id, chart);
    return () => {
      disposed = true;
      for (const type of ["pointerup", "mouseup", "touchend", "dblclick", "wheel"]) window.removeEventListener(type, afterScale, true);
      scaleWatch.disconnect(); stopScale(); stopScaleJump(); autoScale.current = () => {};
      stopLink(); stopRange(); stopCommands(); stopJumps(); stopSnapshot(); retryJump.current = () => {}; chart.timeScale().unsubscribeVisibleLogicalRangeChange(onLogical); if (rangeTimer) window.clearTimeout(rangeTimer); registry?.delete(id); (window as typeof window & { __tjMarks?: Map<string, MarkLayer> }).__tjMarks?.delete(id); layers?.delete(id); autoLayers?.delete(id);
      finish(false); dropHold();
      element.removeEventListener("pointerleave", releasePointer);
      window.removeEventListener("mouseup", onPlaceUp); element.removeEventListener("contextmenu", onContextMenu, true);
      element.removeEventListener("mousedown", onMouseDown, true); element.removeEventListener("touchstart", onTouchStart, true); element.removeEventListener("touchmove", onTouchMove, true);
      element.removeEventListener("touchend", onTouchEnd, true); element.removeEventListener("touchcancel", onTouchEnd, true);
      for (const type of ["mousedown", "touchstart", "wheel"]) element.removeEventListener(type, unpin, true);
      element.removeEventListener("wheel", onWheel, true);
      candles.detachPrimitive(marks); candles.detachPrimitive(layer); candles.detachPrimitive(autoLayer); candles.detachPrimitive(bells); candles.detachPrimitive(shade); candles.detachPrimitive(heat); heatRef.current = null; candles.detachPrimitive(profile); profileRef.current = null; candles.detachPrimitive(wallLayer); wallRef.current = null; chart.remove(); bundle.current = null; barsRef.current = [];
    };
  }, [id, link, rangeLink, commands, main]); // eslint-disable-line react-hooks/exhaustive-deps -- `openingBars` reads `main` and a ref

  // RSI lives in a second pane, added and removed in place; the pane goes with its series.
  useEffect(() => {
    const current = bundle.current;
    if (!current || indicators.rsi === !!current.rsi) return;
    if (current.rsi) { current.chart.removeSeries(current.rsi); current.rsi = undefined; return; }
    const rsi = current.chart.addSeries(LineSeries, { color: colorsRef.current.rsi, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
    // Keep 100 and 0 clear of the divider, so they never sit against the price pane's bottom label.
    rsi.priceScale().applyOptions({ scaleMargins: { top: 0.24, bottom: 0.18 } });
    rsi.createPriceLine({ price: 70, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    rsi.createPriceLine({ price: 30, color: "#655781", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    current.chart.panes()[1].setHeight(main ? 64 : 60);
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
    if (drawnKey.current !== dataKey) { cardHoverEnabled.current = false; setCard(null); }
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
      if (change === "append") {
        for (const name of OVERLAYS) current.lines[name].update(linePoint(bars, last - 1, name));
        for (const k of VWAP_BANDS) current.bands[k].update(bandPoint(bars, last - 1, k));
      }
      current.candles.update(candlePoint(bars[last]));
      current.volume.update(volumePoint(bars[last]));
      current.shade.update();
      for (const name of OVERLAYS) current.lines[name].update(linePoint(bars, last, name));
      for (const k of VWAP_BANDS) current.bands[k].update(bandPoint(bars, last, k));
      current.rsi?.update(rsiPoint(bars[last]));
      return chartCommitted(symbol, live.store.get(symbol).ticks.at(-1), main);
    }
    resets.current += 1;
    if (container.current) container.current.dataset.resets = String(resets.current);
    const range = current.chart.timeScale().getVisibleRange();
    const logical = current.chart.timeScale().getVisibleLogicalRange();
    const following = pinnedLive.current || !logical || logical.to >= (current.candles.data().length - 3);
    const anchorIndex = logical ? Math.max(0, Math.min(prior.length - 1, Math.ceil(logical.from))) : 0;
    const anchorTime = prior[anchorIndex]?.time;
    const movedTo = anchorTime === undefined ? -1 : bars.findIndex((b) => b.time === anchorTime);
    const moved = movedTo - anchorIndex;
    quiet();
    current.candles.setData(bars.map(candlePoint));
    current.volume.setData(bars.map(volumePoint));
    current.shade.update();
    for (const name of OVERLAYS) current.lines[name].setData(bars.map((_, index) => linePoint(bars, index, name)));
    for (const k of VWAP_BANDS) current.bands[k].setData(bars.map((_, index) => bandPoint(bars, index, k)));
    if (container.current) container.current.dataset.vwapBands = String(bars.filter((bar) => bar.vwap !== null && bar.vwap_sd != null).length);
    current.rsi?.setData(bars.map(rsiPoint));
    if (bars.length && (initial.current || !prior.length)) {
      current.chart.timeScale().setVisibleLogicalRange(openingRange(bars.length, openingBars()));
      initial.current = false;
    } else if (bars.length && following && logical) {
      const width = logical.to - logical.from;
      current.chart.timeScale().setVisibleLogicalRange({ from: bars.length + 4 - width, to: bars.length + 4 });
    } else if (logical && movedTo >= 0) current.chart.timeScale().setVisibleLogicalRange({ from: logical.from + moved, to: logical.to + moved });
    else if (bars.length && range) current.chart.timeScale().setVisibleRange(range);
    retryJump.current();
    if (bars.length) return chartCommitted(symbol, undefined, main);
  }, [panel, pending, dataKey, symbol, interval, main, live.store]); // eslint-disable-line react-hooks/exhaustive-deps -- `openingBars` reads `main` and a ref

  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    current.volume.applyOptions({ visible: indicators.volume });
    for (const name of OVERLAYS) current.lines[name].applyOptions({ visible: indicators[name] });
  }, [indicators]);
  // A chosen color reaches the lines, the VWAP bands (at their own alpha) and the RSI line in place.
  useEffect(() => {
    colorsRef.current = colors;
    const current = bundle.current;
    if (!current) return;
    for (const name of OVERLAYS) current.lines[name].applyOptions({ color: colors[name] });
    for (const k of VWAP_BANDS) current.bands[k].applyOptions({ color: bandColor(colors.vwap, k) });
    current.rsi?.applyOptions({ color: colors.rsi });
  }, [colors]);
  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    for (const k of VWAP_BANDS) current.bands[k].applyOptions({ visible: vwapBands });
    if (container.current) container.current.dataset.vwapBandsShown = vwapBands ? "true" : "false";
  }, [vwapBands]);

  const markers = panel?.markers;
  // Earnings dates (C2.5) as text, so a tick that leaves them on the same candles changes nothing.
  const earningsKey = useMemo(() => JSON.stringify(earningsMarks(panel?.bars ?? [], earnings, interval)), [panel?.bars, earnings, interval]);
  // News markers (T3.5): the main chart's Focused articles, each on the candle that holds its time. A tick that leaves them on the same candles changes nothing.
  const newsList = (main || newsSmall) && news && news.symbol === symbol ? news.articles : null;
  const marked = useMemo(() => newsList ? newsMarks(panel?.bars ?? [], newsList, interval) : [], [panel?.bars, newsList, interval]);
  const newsKey = marked.map((mark) => `${mark.time}:${mark.articles.map((article) => article.id).join(",")}`).join("|");
  // Fills merge by candle and side (`groupFills`); the key stands for them, so a poll that changes nothing leaves a pinned list open.
  const groups = useMemo(() => indicators.fills ? groupFills(markers ?? []) : [], [markers, indicators.fills]);
  const fillKey = groups.map((group) => `${group.id}:${group.fills.map((fill) => fill.id).join(",")}`).join("|");
  const reports = useMemo(() => JSON.parse(earningsKey) as EarningsMark[], [earningsKey]);
  useEffect(() => {
    if (pending) return;
    bundle.current?.marks.set({ fills: groups, labels: main ? fillLabels : "off", reports, news: marked, small: !main });
    if (container.current) {
      container.current.dataset.earnings = reports.map((m) => `${m.date}@${m.time}`).join(",");
      container.current.dataset.fillMarks = groups.map((group) => `${group.time}:${group.buy ? "buy" : "sell"}:${group.fills.length}`).join(",");
      container.current.dataset.fillLabels = main ? fillLabels : "off";
      container.current.dataset.news = marked.map((m) => `${m.time}:${m.articles.length}`).join(",");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- the keys stand for `groups` and `marked`
  }, [fillKey, reports, newsKey, fillLabels, pending, main]);
  useEffect(() => { queueMicrotask(() => setFillTip(null)); }, [fillKey, pending]);
  // A popover closes when its markers change, not when a poll rebuilds the fill list under it.
  useEffect(() => { queueMicrotask(() => setNewsOpen(null)); }, [newsKey, pending]);

  useEffect(() => {
    const current = bundle.current;
    if (!current || pending) return; // the next symbol's levels and drawings wait for its candles
    current.layer.set([...levels.map(levelShape), ...drawings.map(drawingShape)], selected, main);
    if (container.current) {
      container.current.dataset.levels = levels.map((level) => level.price.toFixed(2)).join(",");
      container.current.dataset.drawings = drawings.map((drawing) => drawing.kind).join(",");
    }
  }, [levels, drawings, pending, main, selected]);
  useEffect(() => {
    if (pending) return; // the next symbol's alerts wait for its candles
    bundle.current?.bells.set(alerts);
    if (container.current) container.current.dataset.alerts = alerts.map((mark) => `${mark.price.toFixed(2)}:${mark.fired ? "fired" : "active"}`).join(",");
  }, [alerts, pending]);
  // Open positions (C3.2): a stock's average cost, solid; an option's underlying at entry, dashed. Never a premium.
  useEffect(() => {
    const current = bundle.current;
    if (!current || pending) return;
    const drawn = positions.filter((position) => position.line !== null && Number.isFinite(position.line));
    const lines = drawn.map((position) => current.candles.createPriceLine({ id: `position:${position.trade_id}`, price: position.line!,
      color: position.instrument === "stock" ? "#a3e635" : "#c4b5fd", lineWidth: 1, lineStyle: position.instrument === "stock" ? LineStyle.Solid : LineStyle.Dashed,
      axisLabelVisible: true, title: main ? positionLineTitle(position) : "" }));
    if (container.current) container.current.dataset.positions = drawn.map((position) => `${position.instrument}:${position.line!.toFixed(2)}`).join(",");
    return () => { for (const line of lines) current.candles.removePriceLine(line); };
  }, [positions, pending, main]);
  // Liquidity levels (order flow): time-anchored dotted segments (WallLayer) plus a colored price-axis tag
  // from a line-less price line; bids blue, asks orange, a pulled wall grey. Hidden while candles load.
  useEffect(() => {
    const current = bundle.current;
    const element = container.current;
    const walls = pending ? [] : liquidity?.walls ?? [];
    wallRef.current?.set(walls);
    if (!current || !walls.length) return;
    const lines = walls.map((wall) => current.candles.createPriceLine({ id: `wall:${wall.side}:${wall.price}`, price: wall.price,
      color: wall.pulled || wall.stale ? WALL_COLORS.pulled : WALL_COLORS[wall.side], lineVisible: false, axisLabelVisible: true, title: "" }));
    if (element) element.dataset.walls = walls.map((wall) => `${wall.side}:${wall.price.toFixed(2)}${wall.pulled ? ":pulled" : ""}${wall.stale ? ":stale" : ""}`).join(",");
    return () => { for (const line of lines) current.candles.removePriceLine(line); if (element) delete element.dataset.walls; };
  }, [liquidity?.walls, pending]);
  // Automatic levels: the nearest few above and below the latest price, moving with it, and option strikes with the layer on.
  const lastClose = panel?.bars.at(-1)?.close;
  const zones = useMemo(() => shownZones(autoLevels?.zones ?? [], lastClose, optionsNearest, rangeBands), [autoLevels, lastClose, optionsNearest, rangeBands]);
  useEffect(() => {
    const current = bundle.current;
    if (!current || pending) return; // the next symbol's levels wait for its candles
    current.auto.set(zones, main, lastClose, compact);
    setCard((open) => open && !zones.some((zone) => zone.id === open.id) ? null : open);
    if (container.current) {
      container.current.dataset.compact = compact ? "true" : "false";
      container.current.dataset.autoLevels = zones.map((zone) => zone.id).join(",");
      container.current.dataset.optionLevels = zones.filter((zone) => zone.members.some(isOption)).map((zone) => zone.label).join(",");
      container.current.dataset.rangeLevels = zones.filter((zone) => zone.members.some(isRange)).map((zone) => zone.label).join(",");
    }
  }, [zones, pending, main, lastClose, compact]);
  useEffect(() => {
    bundle.current?.auto.setHighlight(pending ? null : highlight);
    if (container.current) container.current.dataset.highlight = highlight === null || pending ? "" : String(highlight);
  }, [highlight, pending]);
  const cardZone = card && !pending ? zones.find((zone) => zone.id === card.id) : undefined;
  useEffect(() => { bundle.current?.auto.setHovered(cardZone?.id ?? null); }, [cardZone]);
  // Arming, switching or dropping a tool forgets a half-placed drawing.
  useEffect(() => {
    bundle.current?.layer.setInteractive(!tool);
    if (!placing.current && !tool) return;
    placing.current = null;
    setSecond(false);
    bundle.current?.layer.setPreview(null);
  }, [tool]);

  useEffect(() => {
    const b = bundle.current;
    if (!b) return;
    const format = symbol === "US10Y"
      ? { type: "custom" as const, minMove: 0.001, formatter: (v: number) => `${v.toFixed(3)}%` }
      : { type: "price" as const, precision: 2, minMove: 0.01 };
    b.candles.applyOptions({ priceFormat: format });
    Object.values(b.lines).forEach((line) => line.applyOptions({ priceFormat: format }));
  }, [symbol]);
  // Relative volume (C2.4) beside a regular-session candle of today: its value, or why it has none.
  // A compact chart keeps the readout, which costs no room, while it leaves out the volume bars.
  const showRvol = given.volume && intradayInterval(interval);
  const chosenLevel = selected ? levels.find((level) => level.id === selected) : undefined;
  const chosenDrawing = selected ? drawings.find((drawing) => drawing.id === selected) : undefined;
  // Main chart: in the header. Smaller charts: end of the values row, so the
  // header keeps room for its controls at quarter width.
  // A compact chart's header buttons sit closer, so its symbol and interval keep their room.
  const button = compact ? "p-1" : "p-1.5";
  const timer = !macro && !pending && intradayInterval(interval) && <Countdown label={main ? "Main" : id} main={main} interval={interval} bars={panel?.bars} feed={clock} />;
  return (
    // isolate: the chart library gives its pane-resize handle z-index 50. Without a stacking
    // context here that handle outranks the app's overlays (the Sync drawer's backdrop is 40).
    <section ref={box} aria-label={`${symbol} ${interval} chart`} data-compact={main ? undefined : compact ? "true" : "false"} data-quiet-chrome={main ? undefined : ""} className={`relative isolate min-w-0 overflow-hidden rounded-lg border bg-[#10151e] ${height === undefined ? "flex min-h-0 flex-1 flex-col" : ""} ${main ? "border-slate-600/60" : "border-slate-700/50"}`}>
      {/* From a tablet's width, like TradingView, the title line sits over the top of the chart rather than above it; only its controls take the pointer, so a click or right-click on its text reaches the chart. */}
      <div className="relative z-20 flex h-10 shrink-0 items-center justify-between gap-2 border-b border-slate-700/40 pl-3 pr-1 md:pointer-events-none md:absolute md:inset-x-0 md:top-0 md:h-7 md:border-b-0">
        {/* A narrow chart (C7.4's dividers allow 160px) clips its symbol and interval, never its buttons. */}
        <div className="-ml-1 flex min-w-0 items-center gap-2 overflow-hidden rounded bg-[#10151e]/90 px-1 text-xs md:[&_button]:pointer-events-auto md:[&_select]:pointer-events-auto">{onPickSymbol
          ? <button aria-label={`${id} symbol`} title={follows ? "Follows the main symbol. Choose a symbol for this chart." : "Holds its own symbol. Change it, or follow the main symbol."} onClick={onPickSymbol}
            className={`-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 font-semibold tracking-wide hover:bg-slate-800 ${follows ? "text-slate-200" : "text-sky-200"}`}>
            {symbol}{follows ? <Link2 size={11} className="text-slate-500" aria-hidden /> : <Pin size={11} className="text-sky-300" aria-hidden />}</button>
          : <span className="font-semibold tracking-wide text-slate-200">{symbol}</span>}
          <select aria-label={`${main ? "Main" : id} interval`} value={interval} onChange={(e) => onInterval(e.target.value as Interval)} className="rounded border-0 bg-slate-800 px-1.5 py-1 text-[11px] text-slate-300">
            {supportedIntervals(symbol).map((i) => <option key={i}>{i}</option>)}
          </select>
          {macro && <span className="text-[9px] text-slate-400" title="Tradier index observations; 4h clock buckets start at New York midnight">{symbol === "US10Y" ? "Yield %" : "Index pts"}</span>}
          {!macro && main && <span className="hidden text-[10px] text-slate-500 sm:inline">{interval === "1D" || interval === "1W" ? "REGULAR SESSION" : "NEW YORK"}</span>}
          {!pending && main && <EarningsBadge earnings={earnings} />}
        </div>
        <div className={`pointer-events-auto flex shrink-0 items-center rounded bg-[#10151e]/90 ${compact ? "gap-0" : "gap-1"}`}>
          {onPlan && !macro && <button aria-label="Plan trade" aria-haspopup="dialog" title="Plan trade: what you are taking and your plan, before you enter" onClick={onPlan}
            className="inline-flex h-7 items-center gap-1 rounded border border-sky-500/40 px-2 text-[11px] text-sky-200 hover:bg-sky-500/15"><NotebookPen size={12} />Plan</button>}
          {main && timer}
          <span data-quiet-controls={main ? undefined : ""} className={`flex items-center ${compact ? "gap-0" : "gap-1"}`}>
          {onStudies && <ToolbarMenu floating label={`${id} studies`} title={ownStudies ? "This chart's own studies" : compact ? "Studies: slimmed while this chart is small" : "Studies: same as every chart"}
            className={`rounded ${button} hover:bg-slate-800 hover:text-slate-200 ${ownStudies ? "text-sky-300" : "text-slate-500"}`}
            content={() => <div className="flex w-52 flex-col gap-0.5 text-[11px]">
              <button aria-pressed={!ownStudies} onClick={() => onStudies(null)} className={`rounded px-2 py-1 text-left hover:bg-slate-800 ${ownStudies ? "text-slate-400" : "text-slate-200"}`}>
                Automatic<span className="block text-[10px] text-slate-500">{macro ? "Same as every chart; only EMA 9 while this chart is small" : "Same as every chart; only EMA 9 and VWAP while this chart is small"}</span></button>
              <p className="mt-1 px-2 text-[10px] uppercase tracking-wide text-slate-500">This chart only</p>
              {studiesHidden && <p className="px-2 text-[10px] text-amber-300">Indicators are hidden on every chart.</p>}
              {STUDIES.filter((key) => !macro || !["volume", "vwap"].includes(key)).map((key) => <button key={key} aria-pressed={indicators[key]} disabled={studiesHidden} onClick={() => onStudies({ ...Object.fromEntries(STUDIES.map((k) => [k, macro ? (ownStudies?.[k] ?? requested[k]) : indicators[k]])) as PanelStudies, [key]: !indicators[key] })}
                className={`flex min-h-7 items-center justify-between gap-2 rounded px-2 text-left hover:bg-slate-800 disabled:opacity-50 ${indicators[key] ? "text-slate-200" : "text-slate-500"}`}>{INDICATOR_NAMES[key]}{indicators[key] ? <Eye size={12} aria-hidden /> : <EyeOff size={12} aria-hidden />}</button>)}
            </div>}><SlidersHorizontal size={13} aria-hidden /><span className="sr-only">{`${id} studies`}</span></ToolbarMenu>}
          <button title="Latest candles, automatic price scale (Alt+R does every chart)" aria-label={`Latest candles ${id}`} onClick={() => { if (bundle.current) { actions.current.onUserMove?.(); pinnedLive.current = true; moveView(bundle.current.chart, barsRef.current.length, openingBars(), "reset"); } }} className={`rounded ${button} text-slate-500 hover:bg-slate-800 hover:text-slate-200`}><LocateFixed size={13} /></button>
          {onMaximize && <button title={maximized ? "Restore every chart (Esc)" : "Maximize this chart for now; Esc restores"} aria-label={maximized ? "Restore charts" : `Maximize ${interval} chart`} onClick={onMaximize} className={`rounded ${button} hover:bg-slate-800 hover:text-slate-200 ${maximized ? "text-sky-300" : "text-slate-500"}`}>{maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button>}
          {onFocus && <button title="Make main chart" aria-label={`Focus ${interval} chart`} onClick={onFocus} className={`rounded ${button} text-slate-500 hover:bg-slate-800 hover:text-slate-200`}><Expand size={13} /></button>}
          </span>
        </div>
      </div>
      <CandleValues id={id} symbol={symbol} main={main} pending={!!pending} bars={panel?.bars} hover={hover} interval={interval} indicators={indicators} colors={colors} vwapBands={vwapBands} rvol={rvol} pastRvol={history?.rvol} showRvol={showRvol} timer={!main && timer} />
      {macro && <p className="shrink-0 px-3 text-[9px] text-slate-400 md:absolute md:top-12 md:z-10 md:max-w-[calc(100%-4.5rem)] md:rounded md:bg-[#10151e]/90" title="Provider observations, not trades. No volume/VWAP; recent intraday history only.">Tradier · {indexAsOf ? `observed ${instrumentTime(indexAsOf)}` : interval === "1D" && panel?.bars.length ? `daily through ${nyDay(panel.bars[panel.bars.length - 1].time)}` : "observation time unavailable"} · polling</p>}
      <div className={height === undefined ? "relative min-h-0 flex-1" : "relative"}>
        {/* Keep the library's pane-resize handle below sibling cards and selection controls. */}
        <div ref={container} data-testid={`canvas-${id}`} data-pending={pending ? "" : undefined} data-selected={selected ?? undefined} style={height === undefined ? undefined : { height }} className={`isolate select-none transition-opacity [-webkit-touch-callout:none] ${height === undefined ? "absolute inset-0" : ""} ${tool ? "cursor-crosshair" : ""} ${pending ? "opacity-40" : ""}`} />
        {/* TradingView's "A": shown only once the price axis has been dragged (the candles may be off the pane); one click fits the candles again. */}
        {manualScale && !pending && <button type="button" data-testid={`${id}-price-auto`} aria-label="Auto price scale: fit the candles again" title="Fit the price scale to the candles"
          onClick={() => autoScale.current()} style={{ top: manualScale.top }}
          className="absolute right-1 z-10 h-[18px] rounded border border-sky-400/50 bg-[#141b26]/90 px-1.5 text-[10px] font-semibold leading-none text-sky-300 hover:bg-sky-400/10 focus-visible:outline focus-visible:outline-1 focus-visible:outline-sky-400">Auto</button>}
        {/* A smaller chart's header has no room: its badge, only when it holds a symbol of its own, sits on the canvas. */}
        {!pending && !main && follows === false && <EarningsBadge earnings={earnings} compact className="absolute left-2 top-1 z-10 md:top-14" />}
        {cardZone && card && compact && !card.pinned ? <div role="tooltip" aria-label="Level" className="pointer-events-none absolute left-2 z-10 max-w-[calc(100%-1rem)] truncate rounded border border-slate-600/60 bg-[#141b26] px-2 py-0.5 font-mono text-[10px] text-slate-200 shadow-lg"
          style={card.above ? { top: Math.max(2, Math.round(card.y) - 26) } : { top: Math.round(card.y) + 8 }}>
          {chartLabel(cardZone)} {cardZone.low === cardZone.high ? price(cardZone.low) : `${price(cardZone.low)}–${price(cardZone.high)}`}<span className="text-slate-500"> · click for more</span></div>
        : cardZone && autoLevels && card && <LevelCard zone={cardZone} auto={autoLevels} interaction={levelEvents?.[cardZone.id]} interval={interval} pinned={card.pinned}
          // Never past the chart's edge: a long card (an option strike's numbers) scrolls once kept open.
          style={card.above ? { bottom: `calc(100% - ${Math.round(card.y) - 12}px)`, maxHeight: Math.max(80, Math.round(card.y) - 20) }
            : { top: Math.round(card.y) + 12, maxHeight: `max(80px, calc(100% - ${Math.round(card.y) + 20}px))` }} onClose={() => setCard(null)} />}
        {fillTip && !pending && (() => {
          const { group } = fillTip;
          const when = `${etTime(group.time, true)} ${intradayInterval(interval) ? `${etTime(group.time)} ET candle` : ""}`;
          const place = { left: Math.max(4, Math.min(fillTip.x + 10, fillTip.width - 240)), top: Math.max(4, fillTip.y - (group.fills.length > 1 ? 30 + group.fills.length * 18 : 30)) };
          const frame = "absolute z-10 max-w-[calc(100%-1rem)] rounded border border-slate-600/60 bg-[#141b26] px-2 py-1 text-[11px] text-slate-200 shadow-lg";
          // One fill reads on a line; several are listed, and a pinned list's rows each open their own trade.
          if (group.fills.length === 1) return <div role="tooltip" aria-label="Fill summary" className={`pointer-events-none truncate ${frame}`} style={place}>
            {group.fills[0].label} · {when}{onFill ? " · click for the trade" : ""}</div>;
          return <div role={fillTip.pinned ? "dialog" : "tooltip"} aria-label="Fill summary" data-fill-tip={group.id} className={`${frame} w-56 ${fillTip.pinned ? "" : "pointer-events-none"}`} style={place}>
            <p className="text-[10px] text-slate-400">{group.fills.length} {group.buy ? "buys" : "sells"} · {when}</p>
            <ul className="mt-0.5">{group.fills.map((fill) => <li key={fill.id}>{fillTip.pinned && onFill
              ? <button onClick={() => { setFillTip(null); onFill(fill.id); }} className="flex min-h-9 w-full items-center text-left text-sky-300 hover:text-sky-200">{fill.label}</button>
              : <span className="block truncate leading-[18px]">{fill.label}</span>}</li>)}</ul>
            {!fillTip.pinned && onFill && <p className="text-[10px] text-sky-300">Click to pick a trade</p>}
            {fillTip.pinned && <button onClick={() => setFillTip(null)} className="mt-0.5 min-h-9 w-full rounded border border-slate-700 text-slate-300">Close</button>}</div>;
        })()}
        {newsOpen && !pending && <div role={newsOpen.pinned ? "dialog" : "tooltip"} aria-label="News headlines" data-news-tip={newsOpen.mark.time}
          className={`absolute z-10 w-64 max-w-[calc(100%-1rem)] space-y-1 rounded border border-slate-600/60 bg-[#141b26] px-2 py-1.5 text-[11px] text-slate-200 shadow-lg ${newsOpen.pinned ? "" : "pointer-events-none"}`}
          style={{ left: Math.max(4, Math.min(newsOpen.x + 10, newsOpen.width - 264)), top: Math.max(4, Math.min(newsOpen.y + 14, newsOpen.height - 40 - newsTip(newsOpen.mark).lines.length * 34)) }}>
          <p className="text-[10px] text-slate-400">{newsSpan(newsOpen.mark, interval)} · {newsOpen.mark.articles.length} {newsOpen.mark.articles.length === 1 ? "headline" : "headlines"}</p>
          <ul className="space-y-1">{newsTip(newsOpen.mark).lines.map((line, index) => <li key={index} className="line-clamp-2">{line}</li>)}</ul>
          {newsTip(newsOpen.mark).more > 0 && <p className="text-[10px] text-slate-400">+{newsTip(newsOpen.mark).more} more</p>}
          {newsOpen.pinned ? <div className="flex gap-2 pt-1">
            {onNews && <button onClick={() => { const ids = newsOpen.mark.articles.map((article) => article.id); setNewsOpen(null); onNews(ids); }} className="min-h-11 flex-1 rounded border border-sky-400/50 px-2 text-sky-300">Read in News</button>}
            <button onClick={() => setNewsOpen(null)} className="min-h-11 rounded border border-slate-700 px-3 text-slate-300">Close</button></div>
            : onNews && <p className="text-[10px] text-sky-300">Click to read in News</p>}</div>}
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
