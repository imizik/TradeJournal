"use client";

import Link from "next/link";
import { useAppAccess } from "@/components/AccessProvider";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, ChartCandlestick, NotebookPen, Pencil, Check, ChevronDown, ChevronUp, Columns3, Crosshair, Expand, Eye, EyeOff, Info, Keyboard, Layers as LayersIcon, LayoutGrid, Link2, List, ListOrdered, Loader2, Lock, Magnet, MoreHorizontal, MoveRight, Pause, Play, Plus, RectangleHorizontal, Redo2, RefreshCw, Rows3, Search, Slash, SlidersHorizontal, Square, Trash2, Type, Undo2, X } from "lucide-react";
import AlertsPanel from "./AlertsPanel";
import DockSection from "./DockSection";
import TradeCard from "./TradeCard";
import { fetchFillCard, fetchTradeCard, openedOn, parsePastView, pastPageEnd, stockOpenPnl, type ChartPosition, type PastView, type TradeCardData } from "@/lib/chartJournal";
import ChartMenu from "./ChartMenu";
import type { HiddenItem, LayerToggle, MenuAlerts, MenuItem, MenuPatch, MenuRequest } from "./ChartMenu";
import HotkeySheet from "./HotkeySheet";
import LayersPanel from "./LayersPanel";
import type { ItemGroup, LayerGroup, LayerItem } from "./LayersPanel";
import LayoutMenu from "./LayoutMenu";
import Level2Panel, { cleanFlow, DEFAULT_FLOW, FLOW_KEY } from "./Level2Panel";
import type { OrderFlow } from "./Level2Panel";
import OptionsLadder from "./OptionsLadder";
import PlanSheet from "./PlanSheet";
import type { ChartSnapshot } from "./PlanSheet";
import PlanStrip from "./PlanStrip";
import PriceChart from "./PriceChart";
import { beginHistoryLoad, mergePastRvol, type OlderState } from "@/lib/chartHistory";
import Sheet from "./Sheet";
import Splitter from "./Splitter";
import type { SplitDrag } from "./Splitter";
import SymbolPalette from "./SymbolPalette";
import SymbolInfo from "./SymbolInfo";
import type { RadarGroup } from "@/lib/radar";
import { fetchSymbolOverview } from "@/lib/symbolInfo";
import type { NewsFocus } from "./SymbolInfo";
import { useSymbolNews } from "@/lib/newsFeed";
import ToolbarMenu from "./ToolbarMenu";
import { instrumentSettings, isMacroSymbol, instrumentPrice, instrumentTime, supportedIntervals, TECH_RETURN_KEY, readTechReturn, macroArrangement, LAYOUT_PRESETS, cleanIndicatorColors, cleanFillLabels, INDICATOR_COLORS, INTERVAL_SECONDS, indicatorColors, activeLayout, applyLayout, applyPreset, arrangementOf, chartStreamUrl, cleanLevel, cleanOptionsLayer, cleanProportions, COLUMN_MIN, COLUMN_MIN_PX, columnMinPx, createChartCommands, createCrosshairLink, createRangeLink, DEFAULT_PROPORTIONS, DOCK_WIDTH, earlyClose, etTime, fetchChartData, fetchChartHistory, focusPanel, GRID_MIN_PX, heldSymbols, INTERVALS, intradayInterval, layoutWithSizes, INDICATOR_NAMES, levelOnBasis, liveTick, LOWER_SHARE, lowerLimits, marketSessionAt, MAX_HELD_SYMBOLS, MAX_LAYOUTS, mergeBars, nameTaken, OPENING_BARS, optionsQuery, PANEL_OPENING_BARS, parseChartTick, price, quoteChange, retainHistory, sessionChange, shownIndicators, shownPrice, sizesOf, SMALL_HEIGHTS, splitsKey, staleCandles, storeLayout, STUDIES, todayNewYork, validSymbol } from "@/lib/charts";
import { ZOOM_SPEED_NAMES, readZoomSpeed, writeZoomSpeed } from "@/lib/zoomSpeed";
import type { ZoomSpeed } from "@/lib/zoomSpeed";
import type { ColorKey, ChartBar, ChartData, ChartPanelData, ChartQuote, ChartSettings, ChartStreamTick, FillLabels, HiddenGroups, Indicators, Interval, LayoutPreset, MarketDay, OptionsLayer, PanelStudies, PriceLevel, Proportions, SmallChartSize, SplitRecord, SymbolPanels } from "@/lib/charts";
import { autoLevelsShown } from "@/lib/autoLevels";
import { createStreamStore, useClock, useStream } from "@/lib/chartStore";
import { receiveChartTick, startSymbolTiming, useQuoteTiming } from "@/lib/chartPerformance";
import { useChartSettings } from "@/lib/chartSync";
import { alertText, createAlert, rearmAlert, removeAlert } from "@/lib/alerts";
import type { AlertCondition, AlertMark, AlertsPayload, AlertSource, LevelAlert } from "@/lib/alerts";
import { applyEdit, cleanDrawing, drawingOnBasis, editName, editVerb, LEVEL_COLOR, MAX_DRAWINGS, MAX_LEVELS, MAX_UNDO, TOOL_NAMES } from "@/lib/drawings";
import type { Anchor, Drawing, DrawingEdit, DrawingKind, DrawingPatch, ItemEdit, Tool } from "@/lib/drawings";
import type { LiveFeed } from "@/lib/chartStore";
import { readHotkey, stepWatchlist, TYPED_INTERVALS } from "@/lib/hotkeys";
import { addCaptureNote, captureTitle, fetchCaptures, fetchReview, fetchSetup, linkCapture, markNotTaken, outboxAll, retryTranscript, saveTracking, send as sendCapture, unlinkCapture } from "@/lib/captures";
import LinkReview from "./LinkReview";
import type { Capture, CaptureNote, CaptureReview, CaptureSetup, OutboxItem } from "@/lib/captures";
import { summary } from "./SelectionBar";
import { useDepthSession } from "@/components/level2/useDepthSession";
import { DepthHeatmap, heatBookKind, wallLines } from "@/lib/depthHeatmap";
import type { DepthProfile } from "@/lib/depthHeatmap";
import { useRecordedDepth } from "@/components/level2/useRecordedDepth";
import type { RecordedDepth } from "@/components/level2/useRecordedDepth";
import { copyText } from "@/lib/clipboard";

const INDICATORS = Object.entries(INDICATOR_NAMES) as [keyof Indicators, string][];
const SYNC_TEXT = { loading: "Loading saved settings", saving: "Saving…", saved: "Saved", offline: "Saved in this browser · server unavailable" };
/** A bordered button; its height comes with it (`h-8 px-2.5` on a desktop, larger for touch). */
const button = (size = "h-8 px-2.5") => `inline-flex ${size} items-center justify-center gap-1.5 rounded-md border border-slate-700/60 text-xs transition-colors hover:bg-slate-800 disabled:opacity-40`;
/** A borderless toolbar or rail button; `on` is a selected tool or an open panel. */
const plain = (on: boolean, tone = "bg-sky-400/15 text-sky-300") => `inline-flex shrink-0 items-center justify-center gap-1 rounded text-xs transition-colors disabled:opacity-30 ${on ? tone : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`;
/** A symbol at an interval: what one panel draws, and the key its history is kept under. */
type Frame = { symbol: string; interval: Interval };
type Slot = Frame & { index: number };
const frameKey = (frame: Frame) => `${frame.symbol}|${frame.interval}`;
/** A saved level on the adjusted basis; `was` is its saved price when a split moved it. */
type ShownLevel = PriceLevel & { was: number | null };
const NO_LEVELS: ShownLevel[] = [];
const NO_MARKS: AlertMark[] = [];
const NO_DRAWINGS: Drawing[] = [];
const NO_POSITIONS: (ChartPosition & { pnl: number | null })[] = [];
/** The selected level or drawing and the panel it was selected on, which carries its bar. */
type Selection = { symbol: string; id: string; panel: string };
/** An open chart menu (C1.3): where it was asked for, on which panel's symbol, and the item there (`id`) or the price. */
type OpenMenu = { at: { x: number; y: number; touch: boolean }; panel: string; symbol: string; price: number | null; id: string | null; auto: string | null; reset(): void };
/** The chart menu's Layers: the user's own groups first, then fills and the studies. */
const GROUP_NAMES: [keyof HiddenGroups, string][] = [["levels", "My levels"], ["drawings", "Drawings"]];
/** Only the items a chart draws: none of a hidden group, and no item hidden on its own. */
function visible<T extends { hidden?: boolean }>(rows: T[], groupHidden: boolean, none: T[]): T[] {
  if (groupHidden) return none;
  return rows.some((row) => row.hidden) ? rows.filter((row) => !row.hidden) : rows;
}
/** "moving Breakout" or "adding trend line", with the symbol when it is not the one on screen: what Undo or Redo would do. */
const describeEdit = (edit: DrawingEdit, symbol: string) => `${editVerb(edit)} ${editName(edit)}${edit.symbol === symbol || !edit.symbol ? "" : ` (${edit.symbol})`}`;
/**
 * The side dock (C7.3): one panel at a time, the watchlist (with the main
 * symbol's levels and fills) or the layers. Whether it is open, and on which,
 * is this device's choice; a phone's sheet always starts closed.
 */
type DockTab = "watchlist" | "layers" | "options" | "level2";
const DOCK_KEY = "tradejournal.charts.dock.v1";
/** C1.4 remembered only an open layers panel; a device that left it open opens the dock on Layers. */
const LAYERS_OPEN_KEY = "tradejournal.charts.layers.open.v1";
/** The dock's width on this device (C7.4), and whether full screen shows the dock here ("1" or "0"). */
const DOCK_WIDTH_KEY = "tradejournal.charts.dock.width.v1";
const FULL_DOCK_KEY = "tradejournal.charts.dock.fullscreen.v1";
/** Whether the desktop's drawing-tool rail shows on this device ("1" or "0"); hidden, the Draw button brings it back. */
const RAIL_KEY = "tradejournal.charts.rail.v1";
/** Saved plans whose strip was dismissed on this device (C3.4); the plans themselves stay. */
const DISMISSED_PLANS_KEY = "tradejournal.charts.plans.dismissed.v1";
/** A share as a flex-grow weight: thousandths, so the weights of a row always add up to at least 1. */
const grow = (share: number) => Math.round(share * 1000);
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
/** The chart grid's widest dock in a row of this width: the dock may not leave the charts and tool rail less than this. */
const dockMax = (row: number) => Math.max(DOCK_WIDTH.min, Math.min(DOCK_WIDTH.max, row - GRID_MIN_PX - 40));
/**
 * From this width the workspace fills the screen: a toolbar, a tool rail, the
 * charts and the dock. Below it (a phone, a narrow window) the page scrolls, the
 * tools join the toolbar and the dock is a bottom sheet.
 */
const WIDE = 1024;
/** The toolbar's drawing tools, in order (C1.2). */
const TOOLS: [Tool, typeof Crosshair][] = [["level", Crosshair], ["ray", MoveRight], ["trend", Slash], ["zone", RectangleHorizontal], ["note", Type]];
/** Digits typed for the main chart's interval, waiting for Enter (C0.5). */
type Entry = { typed: string; invalid: boolean };
const NO_ENTRY: Entry = { typed: "", invalid: false };

// The pieces of the toolbar and footer that move with every trade or second
// subscribe themselves, so the workspace above them does not re-render.
// The stream also carries symbols that panels hold: the headline reads only the
// main symbol's trades, so a SPY trade never hides the newest MRVL one.
const latestTrade = (ticks: ChartStreamTick[], symbol: string) => ticks.findLast((tick) => tick.symbol === symbol);
function LiveQuote({ live, quote, candle, market }: { live: LiveFeed; quote?: ChartQuote; candle?: ChartBar; market?: MarketDay }) {
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  useQuoteTiming(tick);
  const shown = shownPrice({ tick, quote, candle, scope: live });
  // A premarket or after-hours price is measured from that session's own reference and says
  // which session it is; after hours the regular close stands beside it, as the watchlist shows it.
  const part = shown.source === "Live trade" ? tick?.session ?? null : marketSessionAt(shown.at, market);
  const extended = part === "pre" || part === "post" ? part : null;
  const change = extended ? sessionChange(shown.price, extended, quote)
    : shown.price != null && quote?.previous_close && quote.previous_close > 0 ? (shown.price / quote.previous_close - 1) * 100 : quote?.change_percentage;
  const close = extended === "post" ? quote?.regular_close : extended === "pre" ? quote?.previous_close : null;
  const closeChange = extended === "post" && close != null && quote?.previous_close ? (close / quote.previous_close - 1) * 100 : null;
  const sessionName = extended === "post" ? "After hours" : extended === "pre" ? "Premarket" : null;
  const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  const closeText = close == null ? "" : `${extended === "post" ? "Close" : "Prev close"} ${price(close)}${closeChange == null ? "" : ` ${signed(closeChange)}`}`;
  if (isMacroSymbol(live.symbol)) return <div aria-label="Selected symbol quote" className="flex min-w-0 flex-wrap items-baseline gap-2 font-mono" title={`Tradier · observed ${quote?.trade_time ? instrumentTime(quote.trade_time) : "time unavailable"}`}>
    <span className="text-base text-white">{instrumentPrice(quote?.last, live.symbol)}</span>
    <span className="text-xs text-slate-400">{live.symbol === "US10Y" ? quote?.change_bps == null ? "—" : `${quote.change_bps >= 0 ? "+" : ""}${quote.change_bps.toFixed(1)} bp` : quote?.change == null ? "—" : `${quote.change >= 0 ? "+" : ""}${quote.change.toFixed(2)} pts`}</span>
    <span className="text-[10px] text-slate-500">Observed {quote?.trade_time ? instrumentTime(quote.trade_time) : "time unavailable"}</span>
  </div>;
  return <div className="flex min-w-0 items-baseline gap-2" aria-label="Selected symbol quote" title={[sessionName && `${sessionName} price, change from ${extended === "post" ? "the regular close" : "the previous close"}`, closeText].filter(Boolean).join(". ") || undefined}><span className="sr-only">{live.symbol}</span><span className="font-mono text-base font-medium tracking-tight text-white">{price(shown.price)}</span>
    <span className={`font-mono text-xs ${change != null && change < 0 ? "text-rose-400" : "text-emerald-400"}`}>{change == null ? "—" : signed(change)}</span>
    {sessionName && <span className="hidden whitespace-nowrap text-[10px] text-slate-400 sm:inline">{sessionName}</span>}
    {close != null && <span className="hidden whitespace-nowrap font-mono text-[10px] text-slate-500 lg:inline">· {extended === "post" ? "Close" : "Prev close"} <span className="text-slate-300">{price(close)}</span>{closeChange != null && <span className={closeChange < 0 ? " text-rose-400" : " text-emerald-400"}> {signed(closeChange)}</span>}</span>}
    {/* The status strip names the source too; here it shows where the toolbar has room. */}<span className="sr-only whitespace-nowrap text-[10px] text-slate-500 min-[1800px]:not-sr-only">{shown.source}</span></div>;
}

/**
 * The main symbol's price card atop the dock, like TradingView's: the regular session's price large with its
 * change from the previous close, a premarket or after-hours price on its own line, and today's volume against
 * the 30-day average (Tradier's, from the symbol overview; the bar is left out until that arrives).
 */
function QuoteCard({ live, quote, candle, market, average }: { live: LiveFeed; quote?: ChartQuote; candle?: ChartBar; market?: MarketDay; average: number | null }) {
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  useQuoteTiming(tick);
  const shown = shownPrice({ tick, quote, candle, scope: live });
  const part = shown.source === "Live trade" ? tick?.session ?? null : marketSessionAt(shown.at, market);
  const extended = part === "pre" || part === "post" ? part : null;
  // Outside the regular session the large price is the session it follows: today's close after hours, the previous close before the open.
  const main = extended === "post" ? quote?.regular_close ?? null : extended === "pre" ? quote?.previous_close ?? null : shown.price;
  const base = quote?.previous_close && quote.previous_close > 0 ? quote.previous_close : null;
  const mainChange = extended === "pre" ? null : main != null && base ? main - base : null;
  const extra = extended ? shown.price : null;
  const extraPercent = extended ? sessionChange(extra, extended, quote) : null;
  const signed = (value: number, suffix = "") => `${value >= 0 ? "+" : ""}${value.toFixed(2)}${suffix}`;
  const tone = (value: number | null) => value == null ? "text-slate-500" : value < 0 ? "text-rose-400" : "text-emerald-400";
  const volume = quote?.volume ?? null;
  return <section aria-label={`${live.symbol} price`} className="border-b border-slate-700/40 px-3 py-2.5">
    <div className="flex items-baseline gap-2"><span className="font-mono text-2xl font-medium tracking-tight text-white">{price(main)}</span><span className="text-[10px] text-slate-500">USD</span>
      {mainChange != null && base && <span className={`font-mono text-sm ${tone(mainChange)}`}>{signed(mainChange)} {signed((mainChange / base) * 100, "%")}</span>}</div>
    <p className="text-[10px] text-slate-500">{extended === "post" ? "At close" : extended === "pre" ? "Previous close" : shown.source}</p>
    {extended && <div className="mt-1.5 flex items-baseline gap-2"><span className="font-mono text-base text-slate-200">{price(extra)}</span>
      {extraPercent != null && <span className={`font-mono text-xs ${tone(extraPercent)}`}>{signed(extraPercent, "%")}</span>}
      <span className="text-[10px] text-slate-400">{extended === "post" ? "After hours" : "Premarket"}</span></div>}
    <div className="mt-2 flex items-baseline justify-between text-[10px] text-slate-500"><span>Volume <span className="font-mono text-slate-200">{volume != null ? watchVolume.format(volume) : "—"}</span></span>
      <span title="30-day average volume · Tradier statistics">Avg 30D <span className="font-mono text-slate-200">{average != null ? watchVolume.format(average) : "—"}</span></span></div>
    {volume != null && average != null && average > 0 && <div role="meter" aria-label="Volume against the 30-day average" aria-valuemin={0} aria-valuemax={average * 2} aria-valuenow={volume}
      className="mt-1 h-1 overflow-hidden rounded bg-slate-800"><div className={volume >= average ? "h-full bg-sky-400" : "h-full bg-sky-400/50"} style={{ width: `${Math.min(100, (volume / (average * 2)) * 100)}%` }} /></div>}
  </section>;
}

const watchVolume = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
/** A watchlist row's numbers, like TradingView's: last, the change in dollars (a wide dock), the change in percent and the day's volume. */
function WatchlistQuote({ live, quote, market, paused, wide }: { live: LiveFeed; quote?: ChartQuote; market?: MarketDay; paused: boolean; wide: boolean }) {
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  useQuoteTiming(tick);
  const connected = useStream(live, (_, state) => state.key === live.key && state.status === "connected");
  const now = useClock((stamp) => stamp);
  const tickIsNewest = !!tick && now >= tick.at && tick.at >= (quote?.trade_time ?? 0);
  const shownTick = tickIsNewest ? tick : undefined;
  const tickAge = shownTick ? Math.floor(now - shownTick.at) : null;
  const tickFresh = !!shownTick && tickAge! <= 45;
  const tickIsLive = tickFresh && connected && !paused;
  const quoteSession = marketSessionAt(quote?.trade_time, market);
  const freshQuote = quote?.trade_time != null && now >= quote.trade_time && now - quote.trade_time <= 45 ? quote : undefined;
  const displayPrice = shownTick?.price ?? quote?.last;
  // Nothing fresh: the shown price's own change, dimmed, rather than a dash. A trade older than 45
  // seconds stays shown until a newer one arrives, so it keeps its change; a quote's after the close
  // is the day's closing change.
  const closing = shownTick ? !tickFresh : !freshQuote;
  const change = shownTick ? sessionChange(shownTick.price, shownTick.session, quote)
    : freshQuote ? sessionChange(freshQuote.last, quoteSession, freshQuote) : quoteChange(quote, quoteSession);
  const quoteAge = quote?.trade_time == null || now < quote.trade_time ? null : Math.floor(now - quote.trade_time);
  const source = shownTick
    ? `${tickIsLive ? "Live trade" : paused ? "Paused trade" : tickAge! <= 45 ? "Recent trade" : "Stale streamed trade"} · ${tickAge}s old`
    : quoteAge == null ? "Tradier quote · timestamp unavailable"
      : `${quoteAge <= 45 ? "Tradier quote" : "Stale Tradier quote"} · ${quoteAge}s old`;
  const changeSource = closing && change != null ? `${source} · change as of this ${shownTick ? "trade" : "quote"}` : source;
  if (isMacroSymbol(live.symbol)) {
    const observed = quote?.trade_time ? `Tradier index · observed ${instrumentTime(quote.trade_time)}` : "Tradier index · observation time unavailable";
    const relative = quote?.change_percentage;
    const movement = live.symbol === "US10Y" ? quote?.change_bps : quote?.change;
    return <><span title={observed} className="text-right font-mono text-slate-400">{instrumentPrice(quote?.last, live.symbol)}</span>
      {wide && <span title={observed} className="text-right font-mono text-slate-400">{movement == null ? "—" : `${movement >= 0 ? "+" : ""}${movement.toFixed(1)}${live.symbol === "US10Y" ? "bp" : ""}`}</span>}
      <span title={`${observed} · relative percent change from previous close`} className="text-right font-mono text-slate-400">{relative == null ? "—" : `${relative >= 0 ? "+" : ""}${relative.toFixed(2)}%`}</span>
      <span title="Indices have no traded volume" className="text-right text-slate-500">—</span></>;
  }
  // The dollar change against the same reference the percent uses (the previous close, or today's close after hours).
  const dollars = change != null && displayPrice != null ? displayPrice - displayPrice / (1 + change / 100) : null;
  const tone = change == null ? "text-slate-500" : change < 0 ? "text-rose-400" : "text-emerald-400";
  return <><span title={source} className="text-right font-mono text-slate-300">{price(displayPrice)}</span>
    {wide && <span aria-hidden title={changeSource} className={`text-right font-mono ${tone} ${closing ? "opacity-70" : ""}`}>{dollars == null ? "—" : `${dollars >= 0 ? "+" : ""}${dollars.toFixed(2)}`}</span>}
    <span title={changeSource} aria-label={`${change == null ? "Change unavailable" : `${change >= 0 ? "+" : ""}${change.toFixed(2)} percent`}; ${changeSource}`}
      className={`text-right font-mono ${change == null ? "text-slate-500" : change < 0 ? "text-rose-400" : "text-emerald-400"} ${closing ? "opacity-70" : ""}`}>{change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}</span>
    <span title={quote?.volume != null ? `Today's volume ${quote.volume.toLocaleString("en-US")} · Tradier quote` : "Volume unavailable"} className="text-right font-mono text-slate-500">{quote?.volume != null ? watchVolume.format(quote.volume) : "—"}</span></>;
}

function FeedStatus({ live, paused, delayed, hasData, failed, loading, sample = false }: { live: LiveFeed; paused: boolean; delayed: boolean; hasData: boolean; failed: boolean; loading: boolean; sample?: boolean }) {
  const stale = useClock((now) => staleCandles(now, live.fetched));
  const streaming = useStream(live, (_, state) => state.key === live.key && state.status === "connected");
  return <div className="flex shrink-0 items-center gap-1.5 text-slate-400" role="status">
    <span className={`h-1.5 w-1.5 rounded-full ${paused || failed || stale || delayed ? "bg-amber-400" : hasData ? "bg-sky-400" : "bg-slate-600"}`} />
    {sample ? "Simulated chart snapshot" : paused ? "Updates paused" : delayed ? "Tradier sandbox · delayed" : isMacroSymbol(live.symbol) ? "Tradier index observations · 60s polling" : streaming ? "Tradier stream · studies refresh 15s" : "Tradier · 15s refresh"}
    {loading && <Loader2 size={12} className="animate-spin" />}
  </div>;
}

/** The status strip's freshness: the newest minute candle (left out when `brief`, on a phone in full screen) and the shown price's age. */
function LiveFooter({ live, quote, candle, market, asOf, brief = false }: { live: LiveFeed; quote?: ChartQuote; candle?: ChartBar; market?: MarketDay; asOf?: number | null; brief?: boolean }) {
  const minute = useStream(live, (ticks) => asOf === undefined ? 0
    : ticks.reduce((latest, tick) => liveTick(tick, live) ? Math.max(latest, tick.minute) : latest, asOf ?? 0));
  const tick = useStream(live, (ticks) => latestTrade(ticks, live.symbol));
  const shown = shownPrice({ tick, quote, candle, scope: live });
  const age = useClock((now) => shown.at ? Math.max(0, Math.floor(now - shown.at)) : null);
  // Outside every session no candle is forming; without the calendar it may be.
  const closed = useClock((now) => !!market && marketSessionAt(now, market) === null);
  return <>
    {!brief && <span className="min-w-0 truncate">{minute ? `Last minute candle ${etTime(minute, true)} ${etTime(minute)} ET${closed ? "" : " · latest candle may be forming"}` : "New York time"}</span>}
    <span className="shrink-0">{age !== null ? `${shown.source} ${age < 60 ? `${age}s` : `${Math.floor(age / 60)}m`} ago` : "No price timestamp"}</span>
  </>;
}

export default function ChartWorkspace() {
  // Loaded from and saved to the server (lib/chartSync.ts); browser storage is the offline copy.
  const { settings: storedSettings, setSettings, ready, sync, merged, stored } = useChartSettings();
  const settings = useMemo(() => instrumentSettings(storedSettings), [storedSettings]);
  const { owner, grants } = useAppAccess();
  const allowedSymbols = (grants.symbols ?? []).join(",");
  const initialLinkSymbol = useRef<string | null | undefined>(undefined);
  // Plain symbol links and subsequent selection use the same browser URL.
  // Preserve Next's history state and historical trade parameters on entry.
  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    if (initialLinkSymbol.current === undefined) {
      const linked = url.searchParams.get("symbol")?.toUpperCase();
      initialLinkSymbol.current = linked && validSymbol(linked) && (owner || allowedSymbols.split(",").includes(linked)) ? linked : null;
    }
    const linked = initialLinkSymbol.current;
    initialLinkSymbol.current = null;
    if (linked && linked !== settings.symbol) {
      setSettings(current => ({ ...current, symbol: linked }));
      return;
    }
    if (url.searchParams.get("symbol") === settings.symbol) return;
    if (url.searchParams.has("symbol")) for (const name of ["from", "to", "trade", "fill"]) url.searchParams.delete(name);
    url.searchParams.set("symbol", settings.symbol);
    window.history.replaceState(window.history.state, "", url);
  }, [ready, settings.symbol, setSettings, owner, allowedSymbols]);
  const [response, setResponse] = useState<{ key: string; session: ChartSettings["session"]; data: ChartData } | null>(null);
  const [older, setOlder] = useState<OlderState>({ key: "", panels: {} });
  const [rollover, setRollover] = useState<{ key: string; before: number; pending: string[] } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const [symbolInput, setSymbolInput] = useState("");
  const [symbolError, setSymbolError] = useState("");
  // The tool the main chart's next click places with; null when not drawing.
  const [tool, setTool] = useState<Tool | null>(null);
  // On a phone the drawing tools wait behind the Draw button, so the chart starts higher; a chosen tool keeps them open.
  const [drawOpen, setDrawOpen] = useState(false);
  // A desktop's rail beside the charts, unless this device put it away for the width; a chosen tool still brings it out.
  const [railShown, setRailShown] = useState(true);
  // A note just placed, whose text field opens ready to type.
  const [fresh, setFresh] = useState<string | null>(null);
  const [drawError, setDrawError] = useState("");
  const [levelPrice, setLevelPrice] = useState("");
  const levelPriceInput = useRef<HTMLInputElement>(null);
  const [levelLabel, setLevelLabel] = useState("");
  const [levelError, setLevelError] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [menu, setMenu] = useState<OpenMenu | null>(null);
  const [dock, setDock] = useState<{ open: boolean; tab: DockTab }>({ open: true, tab: "watchlist" });
  // A phone's dock: a sheet over the charts, closed until asked for.
  const [sheet, setSheet] = useState(false);
  // A short message after a menu action ("Copied 256.12"), cleared after a moment.
  const [notice, setNotice] = useState("");
  // Level alerts (C5.1) as an alert change returned them, until a workspace refresh newer than that change arrives.
  const [alertEdit, setAlertEdit] = useState<{ at: number; data: AlertsPayload } | null>(null);
  // Level and drawing edits made in this tab, for undo and redo (C1.1, C1.2).
  const [edits, setEdits] = useState<{ undo: DrawingEdit[]; redo: DrawingEdit[] }>({ undo: [], redo: [] });
  const [immersive, setImmersive] = useState(false);
  // The panel the symbol search chooses for: 0 is the main symbol.
  const [palette, setPalette] = useState<number | null>(null);
  const [layoutMenu, setLayoutMenu] = useState(false);
  const [help, setHelp] = useState(false);
  const [entry, setEntry] = useState<Entry>(NO_ENTRY);
  // The chart maximized over the grid (C7.4), by slot: this device's view for the moment, never saved.
  const [maximized, setMaximized] = useState<number | null>(null);
  // A strike chosen on the ladder (C4.5), marked on that symbol's charts until chosen again.
  const [strike, setStrike] = useState<{ symbol: string; price: number } | null>(null);
  // The dock's width, and full screen's own choice of showing it: this device's (C7.4).
  const [dockWidth, setDockWidth] = useState<number>(DOCK_WIDTH.default);
  const [fullDock, setFullDock] = useState<boolean | null>(null);
  const [width, setWidth] = useState(1280);
  // Pre-trade capture (C3.4, C3.5): the open sheet (its symbol frozen when opened), the setup, recent plans and what waits in this browser.
  const [plan, setPlan] = useState<{ symbol: string; key: number } | null>(null);
  const [captureSetup, setCaptureSetup] = useState<CaptureSetup | null>(null);
  const [setupError, setSetupError] = useState("");
  const [captures, setCaptures] = useState<Capture[]>([]);
  // Needs linking (C3.6): the count rides on the captures refresh; the view loads when opened.
  const [needsLinking, setNeedsLinking] = useState(0);
  const [linkView, setLinkView] = useState<{ data: CaptureReview | null; loading: boolean; error: string } | null>(null);
  const [outbox, setOutbox] = useState<OutboxItem[]>([]);
  const [dismissedPlans, setDismissedPlans] = useState<string[]>([]);
  // A fill arrow's trade card (C3.1); `key` drops a slower answer to an earlier click.
  const [tradeCard, setTradeCard] = useState<{ key: string; data: TradeCardData | null; loading: boolean; error: string } | null>(null);
  // A past trade opened from its trade or fill page (C3.3), until Back to live; `started` once its candles were asked for.
  const [past, setPast] = useState<(PastView & { started: boolean }) | null>(null);
  // The frames still to centre on the past trade once its page arrives.
  const pastJumps = useRef(new Set<string>());
  const link = useMemo(() => createCrosshairLink(), []);
  const rangeLink = useMemo(() => createRangeLink(), []);
  const commands = useMemo(() => createChartCommands(), []);
  const stream = useMemo(() => createStreamStore(), []);
  const root = useRef<HTMLDivElement>(null);
  // The boxes the dividers resize (C7.4): the main chart's, the smaller row's, each smaller chart's and the dock.
  const mainBox = useRef<HTMLDivElement>(null);
  const lowerBox = useRef<HTMLDivElement>(null);
  const columnBoxes = useRef<(HTMLDivElement | null)[]>([]);
  const dockBox = useRef<HTMLElement>(null);
  const inFlight = useRef(false);
  const refreshNow = useRef<() => void>(() => {});
  const lastRequest = useRef("");
  // History, its requests and visible ranges belong to a frame: a symbol at an interval.
  // Failure is visible to queued callbacks before React commits the issue.
  const failedHistory = useRef(new Set<string>());
  const historyFlights = useRef(new Map<string, AbortController>());
  const visibleTimes = useRef(new Map<string, { from: number; to: number }>());
  const lastWorkspaceDay = useRef<{ key: string; day: string } | null>(null);
  const { symbol, session } = settings;
  // Each visible panel's interval and symbol: its own, or the main one it follows.
  const slots = useMemo<Slot[]>(() => (settings.layout === "single" ? [0] : [0, 1, 2, 3, 4]).map((index) => ({
    index, interval: settings.intervals[index], symbol: (index && settings.panelSymbols[index]) || settings.symbol,
  })), [settings.layout, settings.intervals, settings.panelSymbols, settings.symbol]);
  // The intervals each symbol needs, main symbol first; five symbols at most.
  const wanted = useMemo(() => {
    const map = new Map<string, Interval[]>([[symbol, []]]);
    for (const slot of slots) {
      const frames = map.get(slot.symbol) ?? [];
      if (!frames.includes(slot.interval)) frames.push(slot.interval);
      map.set(slot.symbol, frames);
    }
    return map;
  }, [slots, symbol]);
  const intervalKey = (wanted.get(symbol) ?? []).join(",");
  const extrasKey = [...wanted].filter(([name]) => name !== symbol).sort(([a], [b]) => a.localeCompare(b))
    .map(([name, frames]) => `${name}:${frames.join(".")}`).join(",");
  const symbolsKey = [...wanted.keys()].sort().join(",");
  const framesKey = [...new Set(slots.map(frameKey))].sort().join(",");
  const watchlistKey = settings.watchlist.join(",");
  // The options layer (C4.4) asks the workspace for its strikes; with it on, hidden automatic levels are left out of the zones there.
  const optionsKey = optionsQuery(settings.optionsLayer);
  const optionsOn = optionsKey !== null;
  // The range bands (C2.7) ask the workspace for every shown symbol's expected-move levels; the VWAP bands need nothing new.
  const rangesOn = !settings.rangeBandsHidden;
  const vwapBandsOn = !settings.vwapBandsHidden && !settings.studiesHidden;
  const autoParam = !(optionsOn || rangesOn) || !settings.autoLevelsHidden;
  const requestKey = `${symbol}|${session}|${intervalKey}|${extrasKey}|${watchlistKey}|${optionsKey ?? ""}|${rangesOn}|${autoParam}`;
  // Market trades survive symbol/session/layout changes; each consumer selects
  // its symbol and session. Reconnect only when the subscribed union changes.
  const streamKey = "market";
  const subscriptionKey = [...new Set([...symbolsKey.split(","), ...watchlistKey.split(",").filter(Boolean)])].filter((s) => !isMacroSymbol(s)).sort().join(",");
  const data = response?.key === requestKey ? response.data : null;
  // Candles depend only on the symbol and session. While a request for a new
  // symbol, layout or watchlist loads, a panel keeps the newest response that
  // has its symbol, so reordered intervals and held symbols keep their candles.
  const feedFor = useCallback((name: string): SymbolPanels | undefined => {
    if (!response || response.session !== session) return undefined;
    return response.data.symbol === name ? response.data : response.data.extras?.[name];
  }, [response, session]);
  const current = response && response.session === session && response.data.symbol === symbol ? response.data : null;
  // The newest response of any request, for what is not about one symbol
  // (watchlist quotes, market hours, notes).
  const latest = response?.data;
  const sampleChart = latest?.sample_data === true;
  const streamReady = !!latest;
  const requestFailed = error?.key === requestKey;
  const currentOlder = useMemo(() => older.key === session ? older.panels : {}, [older, session]);
  const hasData = !!current;
  const lives = useMemo(() => new Map([...wanted.keys()].map((name) => [name, {
    store: stream, key: streamKey, symbol: name, session, fetched: feedFor(name)?.fetched_at.intraday ?? 0,
  } satisfies LiveFeed])), [wanted, stream, streamKey, session, feedFor]);
  const live = lives.get(symbol)!;
  // Today's REST candles joined to older history, per frame. Streamed trades are
  // not in here: each chart applies them to its own panel (lib/chartStore.ts).
  const panels = useMemo(() => {
    const merged = new Map<string, ChartPanelData>();
    for (const slot of slots) {
      const key = frameKey(slot);
      const tail = feedFor(slot.symbol)?.panels[slot.interval];
      const past = currentOlder[key];
      if (!tail || merged.has(key)) continue;
      if (!past?.bars.length) { merged.set(key, tail); continue; }
      const bars = mergeBars(retainHistory(past.bars, tail.bars, visibleTimes.current.get(key) ?? null), tail.bars);
      const times = new Set(bars.map((bar) => bar.time));
      merged.set(key, { bars, markers: [...new Map([...past.markers, ...tail.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()] });
    }
    return merged;
  }, [slots, feedFor, currentOlder]);
  const selected = latest?.quotes.find((q) => q.symbol === symbol);
  // Saved levels on the chart's split-adjusted basis: a level drawn before a split moves with the candles.
  const splitsBySymbol = JSON.stringify([...wanted.keys()].map((name) => [name, feedFor(name)?.adjustment?.splits ?? []]));
  const shownLevels = useMemo(() => {
    const splits = new Map(JSON.parse(splitsBySymbol) as [string, SplitRecord[]][]);
    return new Map([...wanted.keys()].map((name) => [name, (settings.levels[name] ?? NO_LEVELS).map((level) => {
      const on = levelOnBasis(level, splits.get(name) ?? []);
      return { ...level, price: on.price, was: on.moved ? level.price : null };
    })]));
  }, [splitsBySymbol, wanted, settings.levels]);
  const levels = shownLevels.get(symbol) ?? NO_LEVELS;
  // Drawings on the same basis: every anchor moves with a split after the drawing's date.
  const shownDrawings = useMemo(() => {
    const splits = new Map(JSON.parse(splitsBySymbol) as [string, SplitRecord[]][]);
    return new Map([...wanted.keys()].map((name) => [name, (settings.drawings[name] ?? NO_DRAWINGS).map((drawing) => drawingOnBasis(drawing, splits.get(name) ?? []))]));
  }, [splitsBySymbol, wanted, settings.drawings]);
  // Open positions (C3.2) on the same basis, a stock's with its open P&L at the latest quote; the Journal group hides them with the arrows.
  const quoteKey = JSON.stringify((latest?.quotes ?? []).map((quote) => [quote.symbol, quote.last]));
  const shownPositions = useMemo(() => {
    const splits = new Map(JSON.parse(splitsBySymbol) as [string, SplitRecord[]][]);
    const lasts = new Map(JSON.parse(quoteKey) as [string, number | null][]);
    return new Map([...wanted.keys()].map((name) => [name, (feedFor(name)?.positions ?? []).map((position) => {
      const on = position.line === null ? null : levelOnBasis({ id: position.trade_id, price: position.line, label: "", drawn_on: openedOn(position.opened_at) }, splits.get(name) ?? []).price;
      const basis = position.avg_cost === null || position.line === null || on === null ? position : { ...position, avg_cost: position.instrument === "stock" ? on : position.avg_cost };
      return { ...basis, line: on, pnl: stockOpenPnl(basis, lasts.get(name)) };
    })]));
  }, [splitsBySymbol, quoteKey, wanted, feedFor]);
  const positionsFor = (name: string) => settings.indicators.fills ? shownPositions.get(name) ?? NO_POSITIONS : NO_POSITIONS;
  const openCard = useCallback((key: string, load: () => Promise<TradeCardData>) => {
    setTradeCard({ key, data: null, loading: true, error: "" });
    load().then((data) => setTradeCard((open) => open?.key === key ? { key, data, loading: false, error: "" } : open),
      (err) => setTradeCard((open) => open?.key === key ? { key, data: null, loading: false, error: err instanceof Error ? err.message : "The journal could not be read." } : open));
  }, []);
  const openFill = useCallback((id: string) => openCard(`fill:${id}`, () => fetchFillCard(id)), [openCard]);
  // Automatic levels (C2.3) and option strikes (C4.4) as the backend merged them, on the chart's basis already; only the groups shown.
  const autoFor = (name: string) => autoLevelsShown(feedFor(name)?.auto_levels, !settings.autoLevelsHidden, optionsOn, rangesOn);
  // Level alerts (C5.1): every alert, each one's price on the chart's basis where its symbol is on screen, and a bell for each chart.
  const alertData = alertEdit && (!latest?.alerts || alertEdit.at >= latest.checked_at) ? alertEdit.data : latest?.alerts ?? alertEdit?.data ?? null;
  const alertPrices = useMemo(() => {
    const splits = new Map(JSON.parse(splitsBySymbol) as [string, SplitRecord[]][]);
    return new Map((alertData?.alerts ?? []).map((alert) => [alert.id,
      levelOnBasis({ id: alert.id, price: alert.price, label: "", drawn_on: alert.created_on }, splits.get(alert.symbol) ?? []).price]));
  }, [alertData, splitsBySymbol]);
  const alertMarks = useMemo(() => {
    const marks = new Map<string, AlertMark[]>();
    for (const alert of alertData?.alerts ?? []) marks.set(alert.symbol, [...marks.get(alert.symbol) ?? [], { id: alert.id, price: alertPrices.get(alert.id) ?? alert.price, fired: alert.state === "fired" }]);
    return marks;
  }, [alertData, alertPrices]);
  // An alert made from an option strike keeps its price; once that strike no longer carries the level (a volume wall moved), its row says so.
  const movedWalls = new Set((alertData?.alerts ?? []).filter((alert) => {
    const levels = optionsOn ? feedFor(alert.symbol)?.auto_levels : undefined;
    return alert.source_kind === "auto" && /(wall|options_[a-z]+|gamma_flip)@/.test(alert.source_id ?? "") && levels?.options?.state === "ready"
      && !levels.zones.some((zone) => zone.id === alert.source_id);
  }).map((alert) => alert.id));
  // Which side an alert waits on: the newest streamed trade, else the newest candle, else the quote.
  const referenceFor = (name: string): number | null => {
    const state = stream.get(name);
    const tick = state.key === streamKey ? state.ticks.findLast((row) => row.symbol === name) : undefined;
    const slot = slots.find((row) => row.symbol === name);
    return tick?.price ?? (slot && panels.get(frameKey(slot))?.bars.at(-1)?.close) ?? latest?.quotes.find((quote) => quote.symbol === name)?.last ?? null;
  };
  const changeAlerts = (work: Promise<AlertsPayload>, done: string) => {
    work.then((data) => { setAlertEdit({ at: Date.now() / 1000, data }); setNotice(done); }).catch((error: Error) => setNotice(error.message));
  };
  const makeAlert = (target: string, source: AlertSource, condition: AlertCondition, interval: Interval) => {
    const reference = referenceFor(target);
    if (reference == null) { setNotice(`No ${target} price yet, so the alert cannot tell which side to wait on.`); return; }
    const direction = reference < source.price ? "up" as const : "down" as const;
    changeAlerts(createAlert({ symbol: target, price: source.price, reference, condition, interval: condition === "closes_beyond" ? interval : null, session,
      source_kind: source.kind, source_id: source.id, label: source.label }), `Alert set: ${target} ${alertText({ condition, interval, direction }, source.price)}`);
  };
  const rearm = (alert: LevelAlert) => {
    const reference = referenceFor(alert.symbol);
    if (reference == null) { setNotice(`Chart ${alert.symbol} to re-arm its alert from the current price.`); return; }
    changeAlerts(rearmAlert(alert.id, alertPrices.get(alert.id) ?? alert.price, reference), `Alert armed again: ${alert.symbol}`);
  };
  const dropAlert = (alert: LevelAlert) => changeAlerts(removeAlert(alert.id), `Alert removed: ${alert.symbol}`);
  // The studies the charts draw: none while the Indicators group is hidden (C1.4).
  const indicators = useMemo(() => shownIndicators(settings.indicators, settings.studiesHidden), [settings.indicators, settings.studiesHidden]);
  // Each smaller chart's: its own studies when it has them, fill arrows and the hidden group as everywhere.
  const panelIndicators = useMemo(() => settings.panelStudies.map((own) => own && !settings.studiesHidden ? { ...indicators, ...own } : indicators), [settings.panelStudies, settings.studiesHidden, indicators]);
  const setPanelStudies = (index: number, next: PanelStudies | null) => setSettings((s) => ({ ...s, panelStudies: s.panelStudies.map((own, i) => i === index ? next : own) }));
  // What the charts draw: hidden items and hidden groups (C1.3) are left out, so they neither draw nor select.
  const visibleLevels = useMemo(() => new Map([...shownLevels].map(([name, rows]) => [name, visible(rows, settings.hiddenGroups.levels, NO_LEVELS)])), [shownLevels, settings.hiddenGroups.levels]);
  const visibleDrawings = useMemo(() => new Map([...shownDrawings].map(([name, rows]) => [name, visible(rows, settings.hiddenGroups.drawings, NO_DRAWINGS)])), [shownDrawings, settings.hiddenGroups.drawings]);
  // An item deleted or hidden here or on another device is no longer selected.
  const picked = selection && ((visibleLevels.get(selection.symbol) ?? NO_LEVELS).some((level) => level.id === selection.id)
    || (visibleDrawings.get(selection.symbol) ?? NO_DRAWINGS).some((drawing) => drawing.id === selection.id)) ? selection : null;

  useEffect(() => {
    historyFlights.current.forEach((controller) => controller.abort());
    historyFlights.current.clear();
    failedHistory.current.clear();
    visibleTimes.current.clear();
    setOlder({ key: session, panels: {} });
    setRollover(null);
  }, [session]);
  // History survives a frame moving between panels; a frame no longer shown lets its history go.
  useEffect(() => {
    const shown = new Set<string>(framesKey.split(","));
    historyFlights.current.forEach((controller, key) => { if (!shown.has(key)) { controller.abort(); historyFlights.current.delete(key); } });
    visibleTimes.current.forEach((_, key) => { if (!shown.has(key)) visibleTimes.current.delete(key); });
    failedHistory.current.forEach((key) => { if (!shown.has(key)) failedHistory.current.delete(key); });
    setOlder((state) => Object.keys(state.panels).every((key) => shown.has(key)) ? state
      : { ...state, panels: Object.fromEntries(Object.entries(state.panels).filter(([key]) => shown.has(key))) });
  }, [framesKey]);

  // A split recorded while the tab is open changes the basis of candles already loaded. Those are dropped,
  // never mixed with newer pages; scrolling back rereads them on the new basis.
  const feedBasis = JSON.stringify([...wanted.keys()].map((name) => { const a = feedFor(name)?.adjustment; return [name, a ? splitsKey(a) : null]; }));
  useEffect(() => {
    const now = new Map(JSON.parse(feedBasis) as [string, string | null][]);
    const stale = new Set(slots.filter((slot) => {
      const loaded = older.panels[frameKey(slot)]?.adjustment;
      const target = now.get(slot.symbol);
      return loaded && target != null && splitsKey(loaded) !== target;
    }).map(frameKey));
    if (!stale.size) return;
    stale.forEach((key) => { historyFlights.current.get(key)?.abort(); historyFlights.current.delete(key); visibleTimes.current.delete(key); failedHistory.current.delete(key); });
    setOlder((state) => ({ ...state, panels: Object.fromEntries(Object.entries(state.panels).filter(([key]) => !stale.has(key))) }));
  }, [feedBasis, older.panels, slots]);

  const loadOlder = useCallback(async (frame: Frame, beforeOverride?: number, retry = false) => {
    const key = frameKey(frame);
    const feed = feedFor(frame.symbol);
    if (historyFlights.current.has(key) || !feed) return;
    const past = currentOlder[key];
    if ((past?.exhausted || past?.issue || failedHistory.current.has(key)) && !retry && beforeOverride === undefined) return;
    failedHistory.current.delete(key);
    const before = beforeOverride ?? past?.bars[0]?.time ?? feed.panels[frame.interval]?.bars[0]?.time ?? Math.floor(Date.now() / 1000);
    const controller = new AbortController();
    historyFlights.current.set(key, controller);
    setOlder((state) => beginHistoryLoad(state, session, key));
    let continuation: string | null = null;
    try {
      while (!controller.signal.aborted) {
        const page = await fetchChartHistory({ symbol: frame.symbol, interval: frame.interval, session, before, continuation, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (splitsKey(page.adjustment) !== splitsKey(feed.adjustment)) {
          // The page and the candles on screen disagree about splits; accepting it would mix two price bases.
          setOlder((state) => state.key !== session ? state : ({ ...state, panels: { ...state.panels, [key]: {
            ...(state.panels[key] ?? { bars: [], markers: [], exhausted: false, warmup: "pending" }), loading: false,
            issue: "A split was recorded while these charts were open. Older candles reload after the next refresh." } } }));
          break;
        }
        setOlder((state) => {
          if (state.key !== session) return state;
          const prior = state.panels[key];
          const live = feed.panels[frame.interval]?.bars ?? [];
          const past = mergePastRvol(prior?.rvol, page);
          const combined = mergeBars(prior?.bars ?? [], past.bars);
          const retained = retainHistory(combined, live, visibleTimes.current.get(key) ?? null);
          if (retained.length + live.length > 12000) return { ...state, panels: { ...state.panels, [key]: {
            ...(prior ?? { bars: [], markers: [], exhausted: false, warmup: "pending", loading: false }),
            issue: "Visible candles fill the 12,000-candle limit. Zoom in before loading more.", loading: false } } };
          const times = new Set(retained.map((bar) => bar.time));
          const markers = [...new Map([...(prior?.markers ?? []), ...page.markers].filter((m) => times.has(m.time)).map((m) => [`${m.id}:${m.time}`, m])).values()];
          return { ...state, panels: { ...state.panels, [key]: { bars: retained, markers,
            calendarNote: page.calendar_note ?? prior?.calendarNote ?? null, adjustment: page.adjustment, rvol: past.rvol, historyStart: page.history_start ?? prior?.historyStart ?? null,
            // Notes the workspace banner does not already carry (for example a jump that looks like an unrecorded split in older candles).
            adjustmentNote: page.adjustment.warnings.filter((note) => !feed.adjustment?.warnings.includes(note)).join(" ") || prior?.adjustmentNote || null,
            exhausted: page.exhausted, warmup: page.warmup, issue: page.issue?.code === "pending" ? null : page.issue?.message ?? null,
            loading: !!page.continuation && (!page.issue || page.issue.code === "pending" || page.issue.code === "rate_limited") } } };
        });
        if (!page.continuation || (page.issue && !["pending", "rate_limited"].includes(page.issue.code))) break;
        continuation = page.continuation;
        const delay = Math.max(250, Math.min(60_000, ((page.issue?.retry_at ?? Math.floor(Date.now() / 1000) + 1) * 1000) - Date.now()));
        await new Promise<void>((resolve) => {
          const timer = window.setTimeout(resolve, delay);
          controller.signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
        });
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        failedHistory.current.add(key);
        setOlder((state) => state.key !== session ? state : ({ ...state, panels: { ...state.panels,
        [key]: { bars: state.panels[key]?.bars ?? [], markers: state.panels[key]?.markers ?? [],
          exhausted: false, warmup: state.panels[key]?.warmup ?? "pending",
          issue: err instanceof Error ? err.message : "Older candles could not load.", loading: false } } }));
      }
    } finally {
      if (historyFlights.current.get(key) === controller) historyFlights.current.delete(key);
      // A load replaced by another (a past trade's page) leaves the new one's state alone.
      if (!historyFlights.current.has(key)) setOlder((state) => state.key !== session || !state.panels[key] ? state : ({ ...state,
        panels: { ...state.panels, [key]: { ...state.panels[key], loading: false } } }));
    }
  }, [feedFor, currentOlder, session]);
  // Before 04:00, on weekends and on holidays today has no intraday bars yet, and early in the
  // day (always on 15m and coarser) it has fewer than the chart opens on: open on the latest
  // completed sessions too, instead of an empty or nearly empty chart.
  useEffect(() => {
    if (!data) return;
    for (const slot of slots) {
      const tail = (slot.symbol === data.symbol ? data : data.extras?.[slot.symbol])?.panels[slot.interval];
      if (!intradayInterval(slot.interval) || !tail || tail.bars.length >= (slot.index ? PANEL_OPENING_BARS : OPENING_BARS) || currentOlder[frameKey(slot)]) continue;
      void loadOlder(slot, data.checked_at);
    }
  }, [data, slots, currentOlder, loadOlder]);
  useEffect(() => {
    if (!rollover || rollover.key !== session || !data) return;
    const available = rollover.pending.filter((key) => !historyFlights.current.has(key));
    if (!available.length) return;
    available.forEach((key) => { const slot = slots.find((s) => frameKey(s) === key); if (slot) void loadOlder(slot, rollover.before); });
    setRollover((current) => current === rollover ? { ...current, pending: current.pending.filter((key) => !available.includes(key)) } : current);
  }, [rollover, session, data, older, slots, loadOlder]);

  // Historical chart mode (C3.3): `/charts?symbol=NVDA&from=…&to=…&trade=…` from a trade or fill page.
  useEffect(() => {
    const view = parsePastView(window.location.search);
    if (view) setPast({ ...view, started: false });
  }, []);
  // The symbol on screen before a past trade took over; Back to live returns to it.
  const beforePast = useRef<string | null>(null);
  // Once the shared settings are in, chart the trade's symbol (the symbol on screen is this device's own).
  useEffect(() => {
    if (ready && past && !past.started && settings.symbol !== past.symbol) {
      beforePast.current = settings.symbol;
      setSettings((s) => s.symbol === past.symbol ? s : ({ ...s, symbol: past.symbol, recent: [s.symbol, ...s.recent.filter((r) => r !== s.symbol && r !== past.symbol)].slice(0, 8) }));
    }
  }, [ready, past, settings.symbol, setSettings]);
  // With its candles on screen: load the stored history page that holds the trade into every
  // chart of the symbol, centre each on the trade's arrows, and open the trade's card.
  useEffect(() => {
    if (!past || past.started || !ready || current?.symbol !== past.symbol) return;
    setPast({ ...past, started: true });
    const targets = slots.filter((s) => s.symbol === past.symbol);
    pastJumps.current = new Set(targets.map(frameKey));
    for (const slot of targets) {
      // A load from today may be in flight (today's candles are few before the open, and on 15m and coarser
      // early in the day); it would walk back from today first, so the trade's page replaces it.
      historyFlights.current.get(frameKey(slot))?.abort();
      historyFlights.current.delete(frameKey(slot));
      // Older candles are trimmed around what is in view; until the user pans, that is the trade.
      visibleTimes.current.set(frameKey(slot), { from: past.from - 3600, to: past.to + 3600 });
      void loadOlder(slot, pastPageEnd(past, slot.interval));
    }
    if (past.fill) openFill(past.fill);
    else if (past.trade) { const trade = past.trade; openCard(`trade:${trade}`, () => fetchTradeCard(trade)); }
  }, [past, ready, current, slots, loadOlder, openFill, openCard]);
  // Each chart centres on the trade once its candles reach the trade's start: a jump before that would page back
  // from today instead. Older candles and indicator warmup may still be loading; waiting for them could move the
  // chart minutes later, after the trader has moved it (a chart they move drops its jump, `onUserMove`).
  useEffect(() => {
    if (!past?.started || !pastJumps.current.size) return;
    for (const slot of slots) {
      const key = frameKey(slot);
      const loaded = currentOlder[key];
      const first = loaded?.bars[0]?.time;
      if (!pastJumps.current.has(key) || !loaded || (loaded.loading && (first === undefined || first > past.from))) continue;
      pastJumps.current.delete(key);
      commands.jump({ panel: slot.index === 0 ? "main" : `Panel ${slot.index + 1}`, times: [past.from, past.to], prices: [] });
    }
  }, [past, currentOlder, slots, commands]);
  // Another symbol leaves the past trade behind.
  useEffect(() => { if (past?.started && symbol !== past.symbol) setPast(null); }, [past, symbol]);
  const backToLive = () => {
    // The trade's pages leave with it: live charts start from today's candles as on any visit.
    const keys = new Set(slots.filter((slot) => slot.symbol === past?.symbol).map(frameKey));
    keys.forEach((key) => { historyFlights.current.get(key)?.abort(); historyFlights.current.delete(key); visibleTimes.current.delete(key); });
    setOlder((state) => ({ ...state, panels: Object.fromEntries(Object.entries(state.panels).filter(([key]) => !keys.has(key))) }));
    pastJumps.current.clear();
    liveAgain.current = true;
    setPast(null);
    window.history.replaceState(null, "", "/charts");
    const previous = beforePast.current;
    beforePast.current = null;
    if (previous && previous !== past?.symbol) setSettings((s) => s.symbol === past?.symbol ? { ...s, symbol: previous } : s);
  };
  // Back to the latest candles once the charts have dropped the trade's pages (their effects run before this one).
  const liveAgain = useRef(false);
  useEffect(() => {
    if (!liveAgain.current) return;
    liveAgain.current = false;
    commands.emit("realtime");
  }, [older, commands]);
  useEffect(() => {
    const measure = () => setWidth(window.innerWidth);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(DOCK_KEY) ?? "null") as { open?: unknown; tab?: unknown } | null;
      if (saved && typeof saved.open === "boolean") setDock({ open: saved.open, tab: saved.tab === "layers" || saved.tab === "options" || (saved.tab === "level2" && owner) ? saved.tab : "watchlist" });
      else if (localStorage.getItem(LAYERS_OPEN_KEY) === "1") setDock({ open: true, tab: "layers" });
      const wide = Number(localStorage.getItem(DOCK_WIDTH_KEY));
      if (Number.isFinite(wide) && wide > 0) setDockWidth(clamp(Math.round(wide), DOCK_WIDTH.min, DOCK_WIDTH.max));
      if (localStorage.getItem(RAIL_KEY) === "0") setRailShown(false);
    } catch { /* open on the watchlist, at the default width */ }
  }, [owner]);
  // Full screen's dock was shared until C7.4: a device without its own choice yet starts from the shared one, once loaded.
  useEffect(() => {
    if (!ready || fullDock !== null) return;
    let own: boolean | null = null;
    try { const saved = localStorage.getItem(FULL_DOCK_KEY); if (saved === "1" || saved === "0") own = saved === "1"; } catch { /* use the shared choice */ }
    if (own === null) {
      own = settings.immersiveWatchlist;
      try { localStorage.setItem(FULL_DOCK_KEY, own ? "1" : "0"); } catch { /* remembered for this visit only */ }
    }
    setFullDock(own);
  }, [ready, fullDock, settings.immersiveWatchlist]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 2500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!immersive) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prior; };
  }, [immersive]);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    let busy = false;
    let recoveryPending = false;
    let controller: AbortController | null = null;
    const extras = Object.fromEntries(extrasKey.split(",").filter(Boolean).map((part) => {
      const [name, frames] = part.split(":");
      return [name, frames.split(".") as Interval[]];
    }));
    // Options levels still loading (a first look reads its chains in the background) are asked for again soon.
    let soon: number | undefined;
    const load = async () => {
      if (!alive || busy || document.hidden) return;
      busy = true;
      inFlight.current = true;
      controller = new AbortController();
      setLoading(true);
      try {
        const result = await fetchChartData({ symbol, session, intervals: intervalKey.split(",") as Interval[],
          watchlist: watchlistKey ? watchlistKey.split(",") : [], extras, options: optionsKey, ranges: rangesOn, auto: autoParam }, controller.signal);
        if (alive) {
          const day = new Date(result.checked_at * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
          if (lastWorkspaceDay.current?.key === session && lastWorkspaceDay.current.day !== day) {
            setRollover({ key: session, before: result.checked_at,
              pending: framesKey.split(",").filter((key) => intradayInterval(key.split("|")[1] as Interval)) });
          }
          lastWorkspaceDay.current = { key: session, day };
          setResponse({ key: requestKey, session, data: result }); setError(null);
          const waiting = [result.auto_levels, ...Object.values(result.extras ?? {}).map((other) => other.auto_levels)].some((levels) => levels?.options?.state === "loading" || levels?.ranges?.state === "loading");
          if (waiting && soon === undefined) soon = window.setTimeout(() => { soon = undefined; void load(); }, 4000);
        }
      } catch (err) {
        if (alive && !controller.signal.aborted) setError({ key: requestKey, message: err instanceof Error ? err.message : "Unable to refresh charts." });
      } finally {
        busy = false;
        if (alive) {
          inFlight.current = false; setLoading(false);
          if (recoveryPending) { recoveryPending = false; void load(); }
        }
      }
    };
    refreshNow.current = () => { if (busy) recoveryPending = true; else void load(); };
    if (!paused || lastRequest.current !== requestKey) void load();
    else setLoading(false);
    lastRequest.current = requestKey;
    const onVisible = () => { if (!paused && !document.hidden) void load(); };
    const timer = paused ? undefined : window.setInterval(load, 15_000);
    document.addEventListener("visibilitychange", onVisible);
    return () => { alive = false; controller?.abort(); inFlight.current = false; if (timer) window.clearInterval(timer); window.clearTimeout(soon); document.removeEventListener("visibilitychange", onVisible); };
  }, [ready, symbol, session, intervalKey, extrasKey, watchlistKey, framesKey, requestKey, paused, optionsKey, rangesOn, autoParam]);

  useEffect(() => {
    stream.onGap(() => refreshNow.current());
    return () => stream.dispose();
  }, [stream]);

  // One stream for every symbol on screen; each chart applies only its own symbol's trades.
  useEffect(() => {
    if (!ready || !streamReady || paused || sampleChart || !subscriptionKey) return;
    let alive = true;
    let source: EventSource | null = null;
    let recovering = false;
    const symbols = subscriptionKey.split(",");
    stream.retain(symbols);
    const status = (value: "connecting" | "connected" | "fallback") => { if (alive) stream.status(streamKey, value); };
    const connect = () => {
      if (document.hidden || source) return;
      status("connecting");
      source = new EventSource(chartStreamUrl(symbols));
      source.addEventListener("status", (event) => {
        try {
          const message = JSON.parse((event as MessageEvent).data);
          const connected = message.state === "connected";
          status(connected ? "connected" : message.state === "connecting" ? "connecting" : "fallback");
          if (message.resync === true || (connected && recovering)) refreshNow.current();
          // Initial subscription sends connecting then connected; it is not a
          // recovery and must not add a second workspace/provider read.
          if (connected) recovering = false;
          else if (message.state === "fallback" || message.resync === true) recovering = true;
        }
        catch { status("fallback"); }
      });
      source.addEventListener("tick", (event) => {
        try {
          const tick = parseChartTick(JSON.parse((event as MessageEvent).data));
          if (!alive || !tick || !symbols.includes(tick.symbol)) return;
          stream.tick(streamKey, receiveChartTick(tick));
        } catch { /* A malformed event cannot replace the last good REST snapshot. */ }
      });
      source.onerror = () => { recovering = true; status("fallback"); };
    };
    const visibility = () => {
      if (document.hidden) { source?.close(); source = null; status("fallback"); }
      else connect();
    };
    connect();
    document.addEventListener("visibilitychange", visibility);
    return () => { alive = false; source?.close(); stream.flush(); document.removeEventListener("visibilitychange", visibility); };
  }, [ready, streamReady, paused, sampleChart, subscriptionKey, streamKey, stream]);

  const setIntervalAt = (index: number, value: Interval) => setSettings((s) => ({ ...s, intervals: s.intervals.map((v, i) => i === index ? (supportedIntervals((index && s.panelSymbols[index]) || s.symbol).includes(value) ? value : "4h") : v) }));
  // Intervals are workspace settings, not per-symbol, so they carry over.
  const [comparisonGroup, setComparisonGroup] = useState<RadarGroup | null>(null);
  const chooseSymbol = (symbol: string) => {
    if (settings.symbol !== symbol) startSymbolTiming(symbol);
    setSettings((s) => s.symbol === symbol ? s : ({ ...s, symbol, intervals: s.intervals.map((v, i) => ((!i || !s.panelSymbols[i]) && !supportedIntervals(symbol).includes(v)) ? "4h" : v), recent: [s.symbol, ...s.recent.filter((r) => r !== s.symbol && r !== symbol)].slice(0, 8) }));
    setTool(null); setSelection(null); setMenu(null); setSymbolInput(""); setSymbolError(""); setLevelPrice(""); setPalette(null); setStrike(null);
  };
  // A panel holds its own symbol (null: follow the main one). Four held symbols at most.
  const choosePanelSymbol = (index: number, held: string | null) => {
    const next = settings.panelSymbols.map((other, i) => i === index ? held : other);
    if (heldSymbols(next).length > MAX_HELD_SYMBOLS) {
      setSymbolError(`Charts show up to five symbols. Set another panel to follow ${settings.symbol} before adding ${held}.`);
      setPalette(null);
      return;
    }
    setSettings((s) => ({ ...s, panelSymbols: s.panelSymbols.map((other, i) => i === index ? held : other), intervals: s.intervals.map((v, i) => i === index && !supportedIntervals(held || s.symbol).includes(v) ? "4h" : v) }));
    setSymbolError(""); setPalette(null);
  };
  const [techReturn, setTechReturn] = useState<ReturnType<typeof readTechReturn>>(null);
  useEffect(() => { try { setTechReturn(readTechReturn(localStorage.getItem(TECH_RETURN_KEY))); } catch { /* Storage unavailable. */ } }, []);
  const backToTech = () => {
    if (!techReturn) return;
    const arrangement = { ...arrangementOf(techReturn), symbol: techReturn.symbol };
    setSettings((s) => ({ ...s, ...arrangement }));
    const next = { ...techReturn, active: false };
    setTechReturn(next);
    try { localStorage.setItem(TECH_RETURN_KEY, JSON.stringify(next)); } catch { /* Session return still works. */ }
    setMaximized(null); setLayoutMenu(false); setTool(null); setSelection(null);
  };
  const choosePreset = (preset: LayoutPreset) => {
    if (preset.id === "macro" && !techReturn?.active) {
      const snapshot = { ...arrangementOf(settings), symbol: settings.symbol, active: true };
      setTechReturn(snapshot);
      try { localStorage.setItem(TECH_RETURN_KEY, JSON.stringify(snapshot)); } catch { /* Session return still works. */ }
    }
    setSettings((s) => applyPreset(s, preset));
    // The dock is per device: a preset opens or closes it here only, and a phone's sheet is left as it is.
    if (!narrow) showDock(preset.dock ? dock.tab : null);
    setMaximized(null); setSymbolError(""); setLayoutMenu(false);
  };
  // Named layouts (C7.2) are arrangements saved in the shared settings: they
  // move intervals, held symbols, chart height and linked ranges, never the
  // main symbol, levels or watchlist.
  // The chart grid's proportions (C7.4) are part of a layout too.
  const inUse = activeLayout(settings);
  const chooseLayout = (id: string) => {
    setSettings((s) => { const layout = s.layouts.find((other) => other.id === id); return layout ? applyLayout(s, layout) : s; });
    setMaximized(null); setSymbolError(""); setLayoutMenu(false);
  };
  const saveLayout = (name: string) => setSettings((s) => s.layouts.length >= MAX_LAYOUTS || nameTaken(s.layouts, name) ? s
    : { ...s, ...storeLayout(s, crypto.randomUUID(), name) });
  const renameLayout = (id: string, name: string) => setSettings((s) => ({ ...s, layouts: s.layouts.map((layout) => layout.id === id ? { ...layout, name } : layout) }));
  const updateLayout = (id: string) => setSettings((s) => { const layout = s.layouts.find((other) => other.id === id); return layout ? { ...s, ...storeLayout(s, id, layout.name) } : s; });
  const deleteLayout = (id: string) => setSettings((s) => ({ ...s, layouts: s.layouts.filter((layout) => layout.id !== id),
    layoutProportions: Object.fromEntries(Object.entries(s.layoutProportions).filter(([other]) => other !== id)) }));
  // Every change to a level or drawing goes through here, so it can be undone.
  const editItems = (edit: DrawingEdit) => {
    setSettings((s) => applyEdit(s, edit, "after") ?? s);
    setEdits((h) => ({ undo: [...h.undo, edit].slice(-MAX_UNDO), redo: [] }));
    setLevelError(""); setDrawError("");
  };
  /** Undo (`before`) or redo (`after`) the latest edit, onto whatever the levels and drawings are now. */
  const replay = (side: "before" | "after") => {
    const edit = (side === "before" ? edits.undo : edits.redo).at(-1);
    if (!edit) return;
    if (!applyEdit(settings, edit, side)) {
      if ((edit.layer === "batch" ? edit.edits[0]?.layer : edit.layer) === "levels") setLevelError(`Remove a ${edit.symbol} level first: ${MAX_LEVELS} per symbol.`);
      else setDrawError(`Remove a ${edit.symbol} drawing first: ${MAX_DRAWINGS} per symbol.`);
      return;
    }
    setSettings((s) => applyEdit(s, edit, side) ?? s);
    setEdits((h) => side === "before" ? { undo: h.undo.slice(0, -1), redo: [...h.redo, edit] } : { undo: [...h.undo, edit], redo: h.redo.slice(0, -1) });
    setLevelError(""); setDrawError("");
  };
  const deleteItem = (target: string, id: string) => {
    const levels = settings.levels[target] ?? [];
    const drawings = settings.drawings[target] ?? [];
    const level = levels.findIndex((row) => row.id === id);
    const drawing = drawings.findIndex((row) => row.id === id);
    if (level >= 0) editItems({ symbol: target, layer: "levels", before: levels[level], after: null, index: level });
    else if (drawing >= 0) editItems({ symbol: target, layer: "drawings", before: drawings[drawing], after: null, index: drawing });
    else return;
    if (selection?.id === id) setSelection(null);
  };
  /** A drawing placed on a chart: the tool's last style, dated today (its anchors are on today's basis), then selected. */
  const placeDrawing = (target: string, kind: DrawingKind, points: Anchor[], panel: string) => {
    if (isMacroSymbol(target)) return;
    const existing = settings.drawings[target] ?? NO_DRAWINGS;
    setTool(null);
    if (existing.length >= MAX_DRAWINGS) { setDrawError(`Remove a ${target} drawing before adding another (${MAX_DRAWINGS} per symbol).`); return; }
    const style = settings.toolStyles[kind];
    const drawing = cleanDrawing({ id: crypto.randomUUID(), kind, points, color: style.color, width: style.width, drawn_on: todayNewYork(), text: "Note" });
    if (!drawing) return;
    editItems({ symbol: target, layer: "drawings", before: null, after: drawing, index: existing.length });
    showGroup("drawings"); // a new drawing is never placed out of sight
    setSelection({ symbol: target, id: drawing.id, panel });
    setFresh(kind === "note" ? drawing.id : null);
  };
  /**
   * A drawing dragged (new points, on the chart's basis, so dated today) or
   * restyled. A new color or width is what that tool draws with next.
   */
  const editDrawing = (target: string, id: string, patch: DrawingPatch) => {
    const rows = settings.drawings[target] ?? [];
    const index = rows.findIndex((row) => row.id === id);
    if (index < 0) return;
    const before = rows[index];
    const after = cleanDrawing({ ...before, ...patch, ...(patch.points ? { drawn_on: todayNewYork() } : {}) });
    if (!after || JSON.stringify(after) === JSON.stringify(before)) return;
    editItems({ symbol: target, layer: "drawings", before, after, index });
    if (patch.color || patch.width) setSettings((s) => ({ ...s, toolStyles: { ...s.toolStyles, [after.kind]: { color: after.color, width: after.width } } }));
  };
  /**
   * A level's label, color, hidden or locked flag (C1.3), as one undo step.
   * The default blue is saved as no color, so an untouched level keeps its shape.
   */
  const editLevel = (target: string, id: string, patch: MenuPatch) => {
    const rows = settings.levels[target] ?? [];
    const index = rows.findIndex((row) => row.id === id);
    if (index < 0) return;
    const before = rows[index];
    const next: Partial<PriceLevel> = { ...before, ...patch, label: patch.label ?? before.label };
    if (patch.color === LEVEL_COLOR) delete next.color;
    const after = cleanLevel(next);
    if (!after || JSON.stringify(after) === JSON.stringify(cleanLevel(before))) return;
    editItems({ symbol: target, layer: "levels", before, after, index });
  };
  /** A change from the chart menu or the selection bar's lock: a level's label, or a note's text. */
  const editItem = (target: string, id: string, patch: MenuPatch) => {
    if ((settings.levels[target] ?? []).some((row) => row.id === id)) editLevel(target, id, patch);
    else { const { label, ...rest } = patch; editDrawing(target, id, label === undefined ? rest : { ...rest, text: label }); }
    if (patch.hidden && selection?.id === id) setSelection(null);
    if (patch.hidden === false) showGroup((settings.levels[target] ?? []).some((row) => row.id === id) ? "levels" : "drawings");
  };
  /** A copy in the same place, unlocked and shown, then selected, so a drag moves the copy. */
  const duplicateItem = (target: string, id: string, panel: string) => {
    const levels = settings.levels[target] ?? [];
    const drawings = settings.drawings[target] ?? [];
    const level = levels.findIndex((row) => row.id === id);
    const drawing = drawings.findIndex((row) => row.id === id);
    const copy = crypto.randomUUID();
    if (level >= 0) {
      if (levels.length >= MAX_LEVELS) { setNotice(`Remove a ${target} level before adding another (${MAX_LEVELS} per symbol).`); return; }
      editItems({ symbol: target, layer: "levels", before: null, after: cleanLevel({ ...levels[level], id: copy, hidden: false, locked: false })!, index: level + 1 });
    } else if (drawing >= 0) {
      if (drawings.length >= MAX_DRAWINGS) { setNotice(`Remove a ${target} drawing before adding another (${MAX_DRAWINGS} per symbol).`); return; }
      editItems({ symbol: target, layer: "drawings", before: null, after: cleanDrawing({ ...drawings[drawing], id: copy, hidden: false, locked: false })!, index: drawing + 1 });
    } else return;
    setSelection({ symbol: target, id: copy, panel }); setFresh(null);
  };
  const showGroup = (group: keyof HiddenGroups) => setSettings((s) => s.hiddenGroups[group] ? { ...s, hiddenGroups: { ...s.hiddenGroups, [group]: false } } : s);
  const toggleGroup = (group: keyof HiddenGroups) => {
    const hiding = !settings.hiddenGroups[group];
    setSettings((s) => ({ ...s, hiddenGroups: { ...s.hiddenGroups, [group]: hiding } }));
    const rows: { id: string }[] = (group === "levels" ? settings.levels : settings.drawings)[selection?.symbol ?? ""] ?? [];
    if (hiding && rows.some((row) => row.id === selection?.id)) setSelection(null);
  };
  /** A study or fill arrows on or off as the charts show them; turning a study on shows the Indicators group again. */
  const toggleIndicator = (key: keyof Indicators) => {
    const on = indicators[key];
    setSettings((s) => ({ ...s, indicators: { ...s.indicators, [key]: !on },
      studiesHidden: !on && key !== "fills" ? false : s.studiesHidden }));
  };
  const colors = useMemo(() => indicatorColors(settings.indicatorColors), [settings.indicatorColors]);
  const setColor = (key: ColorKey, color: string) => setSettings((s) => ({ ...s, indicatorColors: cleanIndicatorColors({ ...s.indicatorColors, [key]: color }) }));
  const [zoomSpeed, setZoomSpeed] = useState<ZoomSpeed>(readZoomSpeed);
  const toggleStudies = () => setSettings((s) => ({ ...s, studiesHidden: !s.studiesHidden }));
  const toggleAuto = () => setSettings((s) => ({ ...s, autoLevelsHidden: !s.autoLevelsHidden }));
  const setOptions = (patch: Partial<OptionsLayer>) => setSettings((s) => ({ ...s, optionsLayer: cleanOptionsLayer({ ...s.optionsLayer, ...patch }) }));
  const toggleOptions = () => setOptions({ hidden: !settings.optionsLayer.hidden });
  const toggleRanges = () => setSettings((s) => ({ ...s, rangeBandsHidden: !s.rangeBandsHidden }));
  const toggleVwapBands = () => setSettings((s) => ({ ...s, vwapBandsHidden: vwapBandsOn, studiesHidden: vwapBandsOn ? s.studiesHidden : false }));
  const toggleNews = () => setSettings((s) => ({ ...s, newsHidden: !s.newsHidden }));
  const setFillLabels = (fillLabels: FillLabels) => setSettings((s) => ({ ...s, fillLabels: cleanFillLabels(fillLabels) }));
  const setNewsSmall = (newsOnSmall: boolean) => setSettings((s) => ({ ...s, newsOnSmall }));
  // News markers (T3.5): the main symbol's news is read while the layer is on, shared with the News tab so the two never ask twice.
  const newsOn = !settings.newsHidden;
  const newsFeed = useSymbolNews(settings.symbol, newsOn && ready && !isMacroSymbol(settings.symbol)); // not before the saved symbol is known: the default one is not worth a read
  const newsMarkers = useMemo(() => newsFeed.data ? { symbol: settings.symbol, articles: newsFeed.data.articles } : null, [newsFeed.data, settings.symbol]);
  // A click on a marker opens the dock's symbol info on the News tab and lights that candle's articles; a phone's sheet opens for it.
  const [newsFocus, setNewsFocus] = useState<NewsFocus | null>(null);
  const newsClicks = useRef(0);
  const openNews = (ids: string[]) => { setNewsFocus({ symbol: settings.symbol, ids, n: ++newsClicks.current }); showDock("watchlist"); };
  /** A strike chosen on the ladder: marked on its symbol's charts and brought onto the main chart's price scale; chosen again, unmarked. */
  const chooseStrike = (value: number) => {
    if (strike?.symbol === symbol && strike.price === value) { setStrike(null); return; }
    setStrike({ symbol, price: value });
    commands.jump({ panel: "main", times: [], prices: [value] });
    if (narrow) setSheet(false);
  };
  /**
   * Lock, unlock or delete every listed level or drawing at once (C1.4): one
   * undo step. Deletions are recorded last-first, so undo puts each back
   * where it sat.
   */
  const editGroup = (layer: ItemGroup, ids: Set<string>, change: { locked: boolean } | "delete") => {
    const edits: ItemEdit[] = [];
    for (const name of wanted.keys()) {
      if (layer === "levels") {
        const rows = settings.levels[name] ?? [];
        for (let index = rows.length - 1; index >= 0; index--) if (ids.has(rows[index].id))
          edits.push({ symbol: name, layer, before: rows[index], after: change === "delete" ? null : cleanLevel({ ...rows[index], locked: change.locked }), index });
      } else {
        const rows = settings.drawings[name] ?? [];
        for (let index = rows.length - 1; index >= 0; index--) if (ids.has(rows[index].id))
          edits.push({ symbol: name, layer, before: rows[index], after: change === "delete" ? null : cleanDrawing({ ...rows[index], locked: change.locked }), index });
      }
    }
    if (!edits.length) return;
    const symbols = new Set(edits.map((edit) => edit.symbol));
    editItems(edits.length === 1 ? edits[0] : { symbol: symbols.size === 1 ? edits[0].symbol : "", layer: "batch", edits, name: `${edits.length} ${layer}` });
  };
  /** Right-click or long press on a panel: with a tool armed it only puts the tool away, as Esc does. */
  const openMenu = (target: string, panel: string) => (request: MenuRequest) => {
    if (tool) { setTool(null); return; }
    setEntry(NO_ENTRY);
    if (request.id) { setSelection({ symbol: target, id: request.id, panel }); setFresh(null); }
    setMenu({ at: { x: request.clientX, y: request.clientY, touch: request.touch }, panel, symbol: target, price: request.price, id: request.id, auto: request.auto ?? null, reset: request.reset });
  };
  const copyPrice = async (value: number) => {
    const text = value.toFixed(2);
    setNotice(await copyText(text) ? `Copied ${text}` : `Could not copy. The price is ${text}.`);
  };
  const select = (target: string, panel: string) => (id: string | null) => { setSelection(id ? { symbol: target, id, panel } : null); setFresh(null); };
  const chooseTool = (next: Tool) => { if (isMacroSymbol(symbol)) return; setTool((current) => current === next ? null : next); setSelection(null); setDrawError(""); };
  // A dragged level saves the price it was dropped at, dated today: that is the basis the chart shows.
  const moveLevel = (target: string, id: string, value: number) => {
    const rows = settings.levels[target] ?? [];
    const index = rows.findIndex((row) => row.id === id);
    const shown = shownLevels.get(target)?.find((level) => level.id === id);
    if (index < 0 || !shown || !Number.isFinite(value) || value <= 0 || Math.abs(shown.price - value) < 0.005) return;
    editItems({ symbol: target, layer: "levels", before: rows[index], after: cleanLevel({ ...rows[index], price: value, drawn_on: todayNewYork() })!, index });
  };
  const actions = useRef({ choose: chooseSymbol, interval: (value: Interval) => setIntervalAt(0, value), replay, deleteItem, plan: () => {} });
  // A maximized chart counts only while five charts show.
  const shown = settings.layout === "multi" ? maximized : null;
  const keys = useRef({ palette: palette !== null, layoutMenu, help, immersive, maximized: shown !== null, watchlist: settings.watchlist, symbol: settings.symbol, typed: entry.typed, selected: picked, tool, menu: !!menu });
  useEffect(() => {
    actions.current = { choose: chooseSymbol, interval: (value: Interval) => setIntervalAt(0, value), replay, deleteItem, plan: openPlan };
    keys.current = { palette: palette !== null, layoutMenu, help, immersive, maximized: shown !== null, watchlist: settings.watchlist, symbol: settings.symbol, typed: entry.typed, selected: picked, tool, menu: !!menu };
  });
  // Hotkeys (lib/hotkeys.ts, listed by the ? sheet). They act on the main
  // chart's interval, the watchlist and every chart's view.
  useEffect(() => {
    // Space presses a control reached with the keyboard. One focused by a click
    // or tap does not keep it, so Space steps the watchlist after a click.
    let pointer = false;
    let keyboardFocus: EventTarget | null = null;
    const onPointer = () => { pointer = true; };
    const onKeyboard = () => { pointer = false; };
    const onFocus = (event: FocusEvent) => { keyboardFocus = pointer ? null : event.target; };
    const onKey = (event: KeyboardEvent) => {
      const state = keys.current;
      // An app overlay over the charts (the Sync drawer, the phone menu) owns every key, as does an open chart menu (it closes on Esc).
      if ([...document.querySelectorAll('[aria-modal="true"]')].some((dialog) => !root.current?.contains(dialog))) return;
      if (state.menu) return;
      // One dialog at a time: with the layouts dialog or the shortcuts open, symbol search stays closed.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!state.layoutMenu && !state.help) { setEntry(NO_ENTRY); setPalette((v) => v === null ? 0 : null); }
        return;
      }
      if (state.palette || state.layoutMenu) return;
      if (state.help) {
        if (event.key === "?" || event.key === "Escape") { event.preventDefault(); setHelp(false); }
        return;
      }
      // A watchlist row moving focus has already used this key.
      if (event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      const typing = !!target?.closest("input, textarea, select, [contenteditable=true]");
      const hotkey = typing ? null : readHotkey(event, state.typed);
      if (!hotkey) {
        if (event.key === "Escape" && state.tool) setTool(null);
        else if (event.key === "Escape" && state.selected) setSelection(null);
        else if (event.key === "Escape" && state.maximized) setMaximized(null);
        else if (event.key === "Escape" && state.immersive) setImmersive(false);
        return;
      }
      if (event.key === " " && target === keyboardFocus && target?.closest("button, a[href], [role=button], summary")) return;
      event.preventDefault();
      if (event.repeat) return;
      if (hotkey.kind === "type") { setEntry({ typed: hotkey.typed, invalid: false }); return; }
      if (hotkey.kind === "commit") {
        const interval = TYPED_INTERVALS[state.typed];
        if (interval) { actions.current.interval(interval); setEntry(NO_ENTRY); }
        else setEntry({ typed: state.typed, invalid: true });
        return;
      }
      // Any other hotkey ends a typed interval.
      setEntry(NO_ENTRY);
      if (hotkey.kind === "interval") actions.current.interval(hotkey.interval);
      else if (hotkey.kind === "step") { const next = stepWatchlist(state.watchlist, state.symbol, hotkey.by); if (next) actions.current.choose(next); }
      else if (hotkey.kind === "reset" || hotkey.kind === "realtime") { pastJumps.current.clear(); commands.emit(hotkey.kind); }
      else if (hotkey.kind === "help") setHelp(true);
      else if (hotkey.kind === "undo" || hotkey.kind === "redo") actions.current.replay(hotkey.kind === "undo" ? "before" : "after");
      else if (hotkey.kind === "delete" && state.selected) actions.current.deleteItem(state.selected.symbol, state.selected.id);
      else if (hotkey.kind === "plan") actions.current.plan();
    };
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("keydown", onKeyboard, true);
    window.addEventListener("focusin", onFocus);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer, true); window.removeEventListener("keydown", onKeyboard, true);
      window.removeEventListener("focusin", onFocus); window.removeEventListener("keydown", onKey);
    };
  }, [commands]);
  // A click or focus elsewhere drops typed digits, so a later Enter is not taken for them.
  useEffect(() => {
    if (!entry.typed) return;
    const cancel = () => setEntry(NO_ENTRY);
    window.addEventListener("pointerdown", cancel);
    window.addEventListener("focusin", cancel);
    return () => { window.removeEventListener("pointerdown", cancel); window.removeEventListener("focusin", cancel); };
  }, [entry.typed]);
  const watchKey = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const rows = [...(event.currentTarget.closest("section")?.querySelectorAll<HTMLButtonElement>("[data-watch-row]") ?? [])];
    const index = rows.indexOf(event.currentTarget);
    const to = event.key === "ArrowDown" ? index + 1 : event.key === "ArrowUp" ? index - 1 : event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : null;
    if (to === null || !rows.length) return;
    event.preventDefault();
    rows[Math.max(0, Math.min(rows.length - 1, to))].focus();
  };
  const submitSymbol = (event: React.FormEvent) => {
    event.preventDefault();
    const symbol = symbolInput.trim().toUpperCase();
    if (!validSymbol(symbol)) { setSymbolError("Enter a US stock or ETF ticker, such as MRVL."); return; }
    chooseSymbol(symbol);
  };
  // Levels belong to a symbol: one drawn on a panel holding SPY is an SPY level.
  const addLevel = (value: number, target = symbol) => {
    if (isMacroSymbol(target)) return;
    const existing = settings.levels[target] ?? NO_LEVELS;
    if (!Number.isFinite(value) || value <= 0) { setLevelError("Enter a positive price."); return; }
    if (existing.length >= MAX_LEVELS) { setLevelError(`Remove a ${target} level before adding another (${MAX_LEVELS} per symbol).`); return; }
    const level = cleanLevel({ id: crypto.randomUUID(), price: value, label: levelLabel.trim().slice(0, 30) || `Level ${existing.length + 1}`, drawn_on: todayNewYork() })!;
    editItems({ symbol: target, layer: "levels", before: null, after: level, index: existing.length });
    setTool(null); setLevelPrice(""); setLevelLabel("");
    showGroup("levels"); // a new level is never saved out of sight
  };
  const failed = requestFailed || !!current?.issues.length;
  // A newer extended-hours candle can outrank the quote. Streamed trades outrank
  // both, so the REST candle (without them) is the one that matters here.
  const quoteSlot = slots.find((slot) => slot.symbol === symbol && intradayInterval(slot.interval));
  const latestCandle = quoteSlot ? panels.get(frameKey(quoteSlot))?.bars.at(-1) : undefined;
  const clockFor = (name: string) => ({ session, market: feedFor(name)?.market ?? latest?.equity_market ?? latest?.market, paused, delayed: !!latest?.delayed,
    failed: requestFailed || !!feedFor(name)?.issues.length, fetched: feedFor(name)?.fetched_at.intraday });
  // Until this request's candles arrive, each chart keeps its last frame under
  // a label naming what is loading. A failed request clears it instead.
  const pendingFor = (frame: Frame) => {
    if (!response || data || requestFailed || panels.has(frameKey(frame))) return null;
    if (response.session !== session) return `Loading ${session === "extended" ? "extended hours" : "regular hours"}…`;
    return `Loading ${feedFor(frame.symbol) ? frame.interval : frame.symbol}…`;
  };
  const heldIssues = [...wanted.keys()].filter((name) => name !== symbol).flatMap((name) => (feedFor(name)?.issues ?? []).map((issue) => `${name}: ${issue}`));
  const issues = [...(current?.issues ?? []), ...heldIssues];
  // Only unusual days get a label: early closes, weekday closures and a missing calendar.
  const market = latest?.market;
  const holiday = market?.status === "closed" && ![0, 6].includes(new Date(`${market.date}T12:00:00Z`).getUTCDay());
  const marketLabel = market?.note ?? earlyClose(market) ?? (holiday ? market?.description || "Market closed today" : null);
  // One price basis for every chart: split-adjusted, with what it rests on and what it cannot see.
  const basis = current?.adjustment ?? null;
  const basisTitle = basis ? [...(basis.splits.length ? basis.splits.map((s) => `${s.label} split, ex-date ${s.ex_date}`) : ["No splits recorded"]),
    basis.status === "unknown" ? "Split data unavailable: prices are as the provider supplied them" : `Alpaca corporate actions${basis.as_of ? `, as of ${new Date(basis.as_of * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York" })}` : ""}`,
    basis.dividends_note].join(" · ") : undefined;
  const basisNotes = [...new Set([...wanted.keys()].flatMap((name) => {
    const own = feedFor(name)?.adjustment;
    return (own?.warnings ?? []).map((note) => `${name}: ${note}`);
  }))];
  // The open menu's item, as the charts show it (on the chart's basis); an item deleted or hidden meanwhile closes the menu.
  const menuLevel = menu?.id ? visibleLevels.get(menu.symbol)?.find((level) => level.id === menu.id) : undefined;
  const menuDrawing = menu?.id && !menuLevel ? visibleDrawings.get(menu.symbol)?.find((drawing) => drawing.id === menu.id) : undefined;
  const menuZone = menu?.auto && !menu.id ? autoFor(menu.symbol)?.zones.find((zone) => zone.id === menu.auto) : undefined;
  const menuItem: MenuItem | null = menuLevel ? { layer: "levels", level: menuLevel } : menuDrawing ? { layer: "drawings", drawing: menuDrawing } : menuZone ? { layer: "auto", zone: menuZone } : null;
  // An alert watches one price: a level's, a horizontal ray's, or an automatic zone's edge nearest the price (its middle from inside it).
  const menuSource = ((): AlertSource | null => {
    if (!menu) return null;
    if (menuLevel) return { kind: "level", id: menuLevel.id, label: menuLevel.label || `Level ${price(menuLevel.price)}`, price: menuLevel.price };
    if (menuDrawing?.kind === "ray") return { kind: "drawing", id: menuDrawing.id, label: menuDrawing.text || "Horizontal ray", price: menuDrawing.points[0].price };
    if (!menuZone) return null;
    const last = referenceFor(menu.symbol);
    const edge = last == null || menuZone.low === menuZone.high ? (menuZone.low + menuZone.high) / 2 : last < menuZone.low ? menuZone.low : last > menuZone.high ? menuZone.high : (menuZone.low + menuZone.high) / 2;
    return { kind: "auto", id: menuZone.id, label: menuZone.label, price: edge };
  })();
  const menuSlot = menu ? slots[menu.panel === "main" ? 0 : Number(menu.panel.replace("Panel ", "")) - 1] : undefined;
  const menuAlerts: MenuAlerts | undefined = menu && menuItem ? {
    source: menuSource, interval: menuSlot && intradayInterval(menuSlot.interval) ? menuSlot.interval : "5m", phone: !!alertData?.phone,
    existing: (alertData?.alerts ?? []).filter((alert) => alert.symbol === menu.symbol && alert.source_id === (menuSource?.id ?? menu.id)).map((alert) => ({ ...alert, shown: alertPrices.get(alert.id) ?? alert.price })),
    onCreate: (condition) => { if (menuSource) makeAlert(menu.symbol, menuSource, condition, menuSlot && intradayInterval(menuSlot.interval) ? menuSlot.interval : "5m"); },
    onRearm: (id) => { const alert = alertData?.alerts.find((row) => row.id === id); if (alert) rearm(alert); },
    onRemove: (id) => { const alert = alertData?.alerts.find((row) => row.id === id); if (alert) dropAlert(alert); },
  } : undefined;
  const layerToggles: LayerToggle[] = [
    ...GROUP_NAMES.map(([group, label]) => ({ key: group, label, on: !settings.hiddenGroups[group], toggle: () => toggleGroup(group) })),
    { key: "auto", label: "Auto levels", on: !settings.autoLevelsHidden, toggle: toggleAuto },
    { key: "options", label: "Options levels", on: optionsOn, toggle: toggleOptions },
    { key: "ranges", label: "Expected move", on: rangesOn, toggle: toggleRanges },
    { key: "vwapBands", label: "VWAP bands ±1σ", on: vwapBandsOn, toggle: toggleVwapBands },
    { key: "news", label: "News markers", on: newsOn, toggle: toggleNews },
    ...[...INDICATORS.slice(-1), ...INDICATORS.slice(0, -1)].map(([key, label]) => ({ key, label, on: indicators[key], toggle: () => toggleIndicator(key) })),
  ];
  // The layers panel (C1.4): the items of every symbol on screen, main symbol first.
  const levelItems: LayerItem[] = [...wanted.keys()].flatMap((name) => (shownLevels.get(name) ?? NO_LEVELS).map((level) => ({ id: level.id, symbol: name,
    name: level.label, detail: price(level.price), color: level.color ?? LEVEL_COLOR, line: true, hidden: !!level.hidden, locked: !!level.locked })));
  const drawingItems: LayerItem[] = [...wanted.keys()].flatMap((name) => (shownDrawings.get(name) ?? NO_DRAWINGS).map((drawing) => ({ id: drawing.id, symbol: name,
    name: drawing.kind === "note" ? `Note: ${drawing.text}` : TOOL_NAMES[drawing.kind], detail: summary(drawing) ?? "", color: drawing.color, line: false,
    hidden: !!drawing.hidden, locked: !!drawing.locked })));
  const layerGroups: LayerGroup[] = [
    { key: "levels", name: "My levels", noun: "levels", hidden: settings.hiddenGroups.levels, items: levelItems },
    { key: "drawings", name: "Drawings", noun: "drawings", hidden: settings.hiddenGroups.drawings, items: drawingItems },
    { key: "auto", name: "Auto levels", hidden: settings.autoLevelsHidden,
      info: "Prior day and week, premarket, overnight, opening ranges, daily swings and round numbers; nearby ones merge into zones. The nearest three above and below price show; only the nearest one each side is shaded, the rest are lines. Names sit in clear space on the main chart; a name with no room shrinks to a short mark at the right edge, and the level is always drawn. Hover or tap one for its card.",
      status: Object.values(feedFor(symbol)?.auto_levels?.missing ?? {}).filter((reason) => !reason.startsWith("Forms at")).map((reason) => `Not shown for ${symbol}: ${reason}`).join(" ") },
    { key: "options", name: "Options levels", hidden: settings.optionsLayer.hidden, filters: settings.optionsLayer,
      info: "The call and put walls (most open interest, or most traded in volume mode) and the strikes ranked by the measure, from Tradier option chains; a strike near another level joins its zone. Hover or tap one for its card. Panels holding their own symbol show its nearest expiration.",
      status: optionsOn ? optionsStatus(symbol) || undefined : undefined },
    { key: "ranges", name: "Expected move", hidden: settings.rangeBandsHidden,
      info: "Expected move: today's (0DTE) and Friday's at-the-money straddle, priced five minutes after the open and drawn above and below the price then, fixed for the session. Hover or tap an expected-move level for its card.",
      status: rangesOn ? rangesStatus(symbol) || undefined : undefined },
    { key: "vwapBands", name: "VWAP bands", hidden: !vwapBandsOn,
      info: "RTH VWAP uses volume-weighted minute HLC3 and resets at 9:30 ET. Bands show ±1σ (dashed) of volume-weighted price dispersion. They are not option-implied expected moves or guaranteed reversal levels. Toggle these independently of Expected move; Indicators hidden also hides VWAP bands.",
      status: vwapBandsOn ? vwapBandsStatus() : undefined },
    { key: "journal", name: "Journal", hidden: !settings.indicators.fills, labels: settings.fillLabels,
      info: "Your fills as slim chevrons on the candles they fall in: a buy under the low, a sell over the high, one per candle per side with a count when several merged. Hover one to list its fills; click for the trade (a merged one lists them to pick from). Fill labels add text beside them on the main chart: none, the newest candle's, or all; smaller charts never show text. Open positions are lines: a stock at its average cost, an option at the underlying price when it was bought." },
    { key: "news", name: "News markers", hidden: settings.newsHidden, small: settings.newsOnSmall,
      info: "A quiet ring along the bottom of the main chart under the candle where each Focused headline for the symbol was published (articles tagging more than three symbols are left out). An article published when the market is closed sits on the next candle. Stories on nearby candles join into one ring with a count. Hover for the headlines; click to read them in the News tab. Smaller charts show none unless News on small charts is checked." },
    { key: "indicators", name: "Indicators", hidden: settings.studiesHidden,
      studies: INDICATORS.filter(([key]) => (STUDIES as readonly string[]).includes(key)).map(([key, label]) => ({ key, label, on: indicators[key] })) },
  ];
  /** A click on an item: the first panel showing its symbol brings it into view and selects it; a phone's sheet closes so the chart shows. */
  const jumpTo = (layer: ItemGroup, item: LayerItem) => {
    const slot = slots.find((other) => other.symbol === item.symbol);
    if (!slot) return;
    const panel = slot.index === 0 ? "main" : `Panel ${slot.index + 1}`;
    const points = layer === "levels" ? (shownLevels.get(item.symbol) ?? NO_LEVELS).filter((level) => level.id === item.id).map((level) => ({ time: null, price: level.price }))
      : (shownDrawings.get(item.symbol) ?? NO_DRAWINGS).find((drawing) => drawing.id === item.id)?.points ?? [];
    if (!points.length) return;
    commands.jump({ panel, times: points.flatMap((point) => point.time === null ? [] : [point.time]), prices: points.map((point) => point.price) });
    setSelection({ symbol: item.symbol, id: item.id, panel }); setFresh(null);
    if (narrow) setSheet(false);
  };
  const lockGroup = (layer: ItemGroup) => {
    const items = layer === "levels" ? levelItems : drawingItems;
    const lock = !items.every((item) => item.locked);
    editGroup(layer, new Set(items.filter((item) => item.locked !== lock).map((item) => item.id)), { locked: lock });
  };
  // Items hidden one by one on a symbol, each with its own Show (one undo step each).
  const hiddenItems = (name: string): HiddenItem[] => [
    ...(shownLevels.get(name) ?? NO_LEVELS).filter((level) => level.hidden).map((level) => ({ id: level.id, name: `${level.label} ${price(level.price)}`, show: () => editItem(name, level.id, { hidden: false }) })),
    ...(shownDrawings.get(name) ?? NO_DRAWINGS).filter((drawing) => drawing.hidden).map((drawing) => ({ id: drawing.id,
      name: drawing.kind === "note" ? `Note: ${drawing.text}` : `${TOOL_NAMES[drawing.kind]} ${summary(drawing)}`, show: () => editItem(name, drawing.id, { hidden: false }) })),
  ];
  /** What the Layers panel says about the main symbol's options levels: their expirations, or why they are not drawn yet. */
  function optionsStatus(name: string): string {
    const info = feedFor(name)?.auto_levels?.options;
    if (!info) return `Loading ${name} option chains…`;
    if (info.state === "ready") return `${name}: ${info.scope_note ?? ""}.`;
    if (info.state === "loading") return `Loading ${name} option chains… ${info.message ?? ""}`.trim();
    return `Not shown for ${name}: ${info.message ?? "no option chains."}`;
  }
  /** What the Layers panel says about the main symbol's expected-move bands: what is drawn, or why nothing is yet. */
  function rangesStatus(name: string): string {
    const info = feedFor(name)?.auto_levels?.ranges;
    if (!info) return `Loading ${name} expected move…`;
    const drawn = info.bands.map((band) => `${band.today ? "0DTE" : new Date(`${band.expiration}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short" })} ±${price(band.move)}`);
    return [drawn.length ? `${name}: ${drawn.join(", ")}.` : `Not shown for ${name}:`, drawn.length && info.state === "ready" ? null : info.message].filter(Boolean).join(" ");
  }
  function vwapBandsStatus(): string {
    if (!intradayInterval(settings.intervals[0])) return "Intraday only: no VWAP bands on daily or weekly charts.";
    const bars = panels.get(frameKey(slots[0]))?.bars;
    if (!bars) return `Loading ${symbol} VWAP bands…`;
    if (!bars.some((bar) => bar.vwap !== null && bar.vwap_sd != null)) return "No regular-session VWAP band data in the loaded candles.";
    return "Shown on regular-session candles only; premarket and after-hours candles have no VWAP bands.";
  }
  const ladderPanel = (sheet: boolean) => isMacroSymbol(symbol) ? <p className="p-3 text-xs text-slate-400">Options are unavailable for these index charts.</p> : <OptionsLadder key={symbol} symbol={symbol} layer={settings.optionsLayer} spot={() => referenceFor(symbol)}
    highlight={strike?.symbol === symbol ? strike.price : null} sheet={sheet} onStrike={chooseStrike} onLayer={setOptions} onClose={() => showDock(null)} />;
  // Level 2 is the owner's: an assistant with a saved Level 2 tab sees the watchlist and starts no request.
  const level2Panel = (sheet: boolean) => isMacroSymbol(symbol) ? <p className="p-3 text-xs text-slate-400">Depth is unavailable for these index charts.</p> : <Level2Panel symbol={symbol} sheet={sheet} session={depthSession} onConnect={connectDepth} heatmap={recorded.heatmap ?? heatmaps.get(symbol) ?? null} flow={flow} onFlow={setFlow} recorded={recorded.state} recording={recorded.recording} heatAllowed={heatAllowed} onClose={() => showDock(null)} />;
  const layersPanel = (sheet: boolean) => <LayersPanel groups={layerGroups} sheet={sheet} onClose={() => showDock(null)}
    onGroupHidden={(key) => { if (key === "journal") toggleIndicator("fills"); else if (key === "indicators") toggleStudies(); else if (key === "auto") toggleAuto(); else if (key === "options") toggleOptions(); else if (key === "ranges") toggleRanges(); else if (key === "vwapBands") toggleVwapBands(); else if (key === "news") toggleNews(); else toggleGroup(key); }} onGroupLock={lockGroup} onOptions={setOptions} onLabels={setFillLabels} onNewsSmall={setNewsSmall}
    onGroupDelete={(layer) => editGroup(layer, new Set((layer === "levels" ? levelItems : drawingItems).map((item) => item.id)), "delete")}
    onJump={jumpTo} onItem={(item, patch) => editItem(item.symbol, item.id, patch)} onDelete={(item) => deleteItem(item.symbol, item.id)}
    onStudy={(key) => toggleIndicator(key as keyof Indicators)} />;
  const menuGone = !!menu?.id && !menuItem;
  useEffect(() => { if (menuGone) setMenu(null); }, [menuGone]);
  const menuAddLevel = (target: string, value: number) => {
    if ((settings.levels[target] ?? []).length >= MAX_LEVELS) { setNotice(`Remove a ${target} level before adding another (${MAX_LEVELS} per symbol).`); return; }
    addLevel(value, target);
  };
  const smallHeight = SMALL_HEIGHTS[settings.smallSize];
  const multi = settings.layout === "multi";
  const narrow = width < WIDE;
  // A desktop and full screen fill their box: the main chart takes the height
  // the smaller charts leave, measured by the browser, not estimated (C7.3).
  const fill = !narrow || immersive;
  const dockShown = narrow ? sheet : immersive ? fullDock ?? settings.immersiveWatchlist : dock.open;
  // Level 2 (owner, NVDA): one manual session for the whole Charts page, so the
  // heatmap behind the candles keeps filling with the dock closed or the page in
  // the background. The service is checked only once the panel has been shown;
  // the provider is contacted only on Connect. Leaving Charts ends it; the
  // heatmap is memory only and starts empty on every visit.
  const [level2Seen, setLevel2Seen] = useState(false);
  const level2Open = owner && !isMacroSymbol(symbol) && dockShown && dock.tab === "level2";
  useEffect(() => { if (level2Open) setLevel2Seen(true); }, [level2Open]);
  // One heatmap per ticker, created on its first Connect, so looking at another
  // symbol never discards what an earlier one collected on this visit.
  const [heatmaps] = useState(() => new Map<string, DepthHeatmap>());
  // Order flow (owner): which layers draw on the main chart, remembered on this device only.
  const [flow, setFlowState] = useState<OrderFlow>(DEFAULT_FLOW);
  useEffect(() => {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(FLOW_KEY) ?? "null");
      if (saved && typeof saved === "object") setFlowState(cleanFlow(saved as Partial<OrderFlow>));
    } catch { /* defaults */ }
  }, []);
  const setFlow = useCallback((next: OrderFlow) => {
    setFlowState(next);
    try { localStorage.setItem(FLOW_KEY, JSON.stringify(next)); } catch { /* remembered for this visit only */ }
  }, []);
  const addBook = useCallback((event: { symbol: string; books: Parameters<DepthHeatmap["add"]>[0] }) => heatmaps.get(event.symbol.slice(3))?.add(event.books), [heatmaps]);
  const depthSession = useDepthSession({ active: owner && !isMacroSymbol(symbol) && level2Seen, onBook: addBook });
  const { connect: startDepth } = depthSession;
  const connectDepth = useCallback((ticker: string) => {
    if (!heatmaps.has(ticker)) heatmaps.set(ticker, new DepthHeatmap());
    startDepth(ticker);
  }, [heatmaps, startDepth]);
  // The session's ticker joins the inputs so the main chart picks up a heatmap created on Connect.
  const depthTicker = depthSession.symbol;
  // The heatmap is drawn only on 1m-5m candles; wider candles turn it into a smear.
  const heatAllowed = !isMacroSymbol(symbol) && (INTERVAL_SECONDS[slots[0]?.interval] ?? Infinity) <= 300;
  // Recorded tickers need no Connect: the recorder's data, about five seconds behind.
  const recorded = useRecordedDepth(symbol, { active: owner && !isMacroSymbol(symbol) && (flow.levels || flow.profile || flow.heatmap), history: flow.heatmap && heatAllowed, kind: flow.kind });
  const liveHere = depthTicker === symbol && depthSession.started;
  const depth = useMemo(() => {
    if (!owner || !flow.heatmap || !heatAllowed) return null;
    const map = recorded.heatmap ?? (liveHere ? heatmaps.get(symbol) : undefined);
    return map ? { map, kind: flow.kind } : null;
  }, [owner, flow, heatAllowed, recorded.heatmap, liveHere, heatmaps, symbol]);
  const liveBook = depthSession.bookEvent;
  // Walls change at most each poll and their tags by the minute: keep one array per content so the
  // chart's price lines are rebuilt only when a wall, its age or the live state actually changes.
  const wallStale = recorded.state === "ready" && !recorded.recording;
  const wallsKey = flow.levels && recorded.state === "ready" ? JSON.stringify([recorded.walls, Math.floor(recorded.lastMs / 60_000) * 60_000, wallStale]) : "";
  const walls = useMemo(() => {
    if (!wallsKey) return [];
    const [found, minute, stale] = JSON.parse(wallsKey) as [RecordedDepth["walls"], number, boolean];
    return wallLines(found, minute, stale);
  }, [wallsKey]);
  const liquidity = useMemo(() => {
    if (!owner) return null;
    let profile: DepthProfile | null = recorded.profile;
    if (!profile && liveHere && liveBook) {
      const book = liveBook.books.find((entry) => heatBookKind(entry) === flow.kind);
      if (book) profile = { t: book.source_time_ms ?? liveBook.received_ms, bids: book.bids.map((level) => [level.price, level.volume]), asks: book.asks.map((level) => [level.price, level.volume]) };
    }
    if (!walls.length && !(flow.profile && profile)) return null;
    return { walls, profile: flow.profile ? profile : null, stale: recorded.state === "ready" ? !recorded.recording : !depthSession.running };
  }, [owner, flow.profile, flow.kind, walls, recorded.profile, recorded.state, recorded.recording, liveHere, liveBook, depthSession.running]);
  /**
   * Open the dock on a tab, or close it (null). A desktop remembers both on
   * this device. Full screen keeps its own choice of showing it, on this
   * device too since C7.4; a phone's sheet is never remembered open.
   */
  const showDock = (tab: DockTab | null) => {
    const open = tab !== null;
    const next = narrow || immersive ? { ...dock, tab: tab ?? dock.tab } : { open, tab: tab ?? dock.tab };
    if (narrow) setSheet(open);
    else if (immersive) {
      setFullDock(open);
      try { localStorage.setItem(FULL_DOCK_KEY, open ? "1" : "0"); } catch { /* remembered for this visit only */ }
    }
    setDock(next);
    try { localStorage.setItem(DOCK_KEY, JSON.stringify(next)); } catch { /* remembered for this visit only */ }
  };
  const toggleDock = (tab: DockTab) => showDock(dockShown && dock.tab === tab ? null : tab);

  // ---- C7.4: dividers and maximize ----
  // A wide screen shares the grid by proportions: the dividers set them, and a
  // phone keeps its S/M/L heights. A drag previews by writing flex weights and
  // widths straight to the boxes; the setting changes once, when it ends.
  const sized = !narrow && multi;
  const sizes = sizesOf(settings);
  // A maximized chart covers the grid; the others stay mounted at their size underneath, hidden.
  const cover = fill && shown !== null;
  const setSizes = (change: (current: Proportions) => Proportions) =>
    setSettings((s) => { const next = cleanProportions(change(sizesOf(s))); return next ? { ...s, proportions: next } : s; });
  /** The height the main chart and the smaller row share, and the smaller row's share of it as shown. */
  const rows = () => {
    const main = mainBox.current?.getBoundingClientRect().height ?? 0;
    const lower = lowerBox.current?.getBoundingClientRect().height ?? 0;
    return { space: main + lower, share: main + lower > 0 ? lower / (main + lower) : sizes.lower };
  };
  const dragRows = (): SplitDrag | null => {
    const main = mainBox.current, lower = lowerBox.current;
    const { space, share: start } = rows();
    const limits = lowerLimits(space);
    if (!main || !lower || !limits) return null;
    const was = [main.style.flexGrow, lower.style.flexGrow];
    let share: number | null = null;
    return {
      move(delta) {
        share = clamp(start - delta / space, limits.min, limits.max);
        main.style.flexGrow = String(grow(1 - share)); lower.style.flexGrow = String(grow(share));
      },
      end(keep) {
        const chosen = share;
        if (keep && chosen !== null) setSizes((current) => ({ ...current, lower: chosen }));
        else [main.style.flexGrow, lower.style.flexGrow] = was;
      },
    };
  };
  // Down (+) gives the main chart more; Home makes it smallest.
  const stepRows = (by: number) => {
    const { space, share } = rows();
    const limits = lowerLimits(space);
    if (limits) setSizes((current) => ({ ...current, lower: clamp(share - by * 0.02, limits.min, limits.max) }));
  };
  const edgeRows = (to: "min" | "max") => {
    const limits = lowerLimits(rows().space);
    if (limits) setSizes((current) => ({ ...current, lower: to === "min" ? limits.max : limits.min }));
  };
  /** The smaller charts' widths on screen, and the narrowest one may be made. */
  const columns = () => {
    const widths = columnBoxes.current.slice(0, 4).map((box) => box?.getBoundingClientRect().width ?? 0);
    const total = widths.reduce((sum, value) => sum + value, 0);
    return { widths, total, least: columnMinPx(total) };
  };
  /** Move the divider after column `index`: `left` is the share of the pair's width the left chart gets. */
  const pairShares = (current: Proportions, index: number, left: number) => {
    const pair = current.columns[index] + current.columns[index + 1];
    return { ...current, columns: current.columns.map((share, i) => i === index ? pair * left : i === index + 1 ? pair * (1 - left) : share) };
  };
  const dragColumn = (index: number): SplitDrag | null => {
    const a = columnBoxes.current[index], b = columnBoxes.current[index + 1];
    const { widths, least } = columns();
    const pair = widths[index] + widths[index + 1];
    if (!a || !b || pair < least * 2) return null;
    const was = [a.style.flexGrow, b.style.flexGrow];
    const weight = sizes.columns[index] + sizes.columns[index + 1];
    let left: number | null = null;
    return {
      move(delta) {
        left = clamp(widths[index] + delta, least, pair - least) / pair;
        a.style.flexGrow = String(grow(weight * left)); b.style.flexGrow = String(grow(weight * (1 - left)));
      },
      end(keep) {
        const chosen = left;
        if (keep && chosen !== null) setSizes((current) => pairShares(current, index, chosen));
        else [a.style.flexGrow, b.style.flexGrow] = was;
      },
    };
  };
  const stepColumn = (index: number, by: number | "min" | "max") => {
    const { widths, total, least } = columns();
    const pair = widths[index] + widths[index + 1];
    if (pair < least * 2) return;
    const left = by === "min" ? least : by === "max" ? pair - least : clamp(widths[index] + by * 0.02 * total, least, pair - least);
    setSizes((current) => pairShares(current, index, left / pair));
  };
  const resetColumns = () => setSizes((current) => ({ ...current, columns: DEFAULT_PROPORTIONS.columns }));
  /** The dock's width: dragged here, kept on this device. */
  const keepDockWidth = (value: number) => {
    const next = clamp(Math.round(value), DOCK_WIDTH.min, DOCK_WIDTH.max);
    setDockWidth(next);
    try { localStorage.setItem(DOCK_WIDTH_KEY, String(next)); } catch { /* remembered for this visit only */ }
  };
  const dockLimit = () => dockMax(dockBox.current?.parentElement?.getBoundingClientRect().width ?? 0);
  const dragDock = (): SplitDrag | null => {
    const box = dockBox.current;
    if (!box) return null;
    const start = box.getBoundingClientRect().width;
    const most = dockLimit();
    const was = box.style.width;
    let next: number | null = null;
    return {
      move(delta) { next = clamp(start - delta, DOCK_WIDTH.min, most); box.style.width = `${next}px`; },
      end(keep) { if (keep && next !== null) keepDockWidth(next); else box.style.width = was; },
    };
  };
  const resetSizes = () => { setSizes(() => DEFAULT_PROPORTIONS); keepDockWidth(DOCK_WIDTH.default); setLayoutMenu(false); };
  /** Maximize a chart, or restore the grid when it is the one maximized. */
  const toggleMaximized = (index: number) => setMaximized((current) => current === index ? null : index);
  /**
   * The others while one chart is maximized: hidden at their size where the
   * grid fills the screen (under the maximized one), and out of the page's
   * flow on a phone, their canvases keeping their fixed heights.
   */
  const slotHidden = (index: number) => shown === null || shown === index ? "" : fill ? "invisible" : "h-0 overflow-hidden invisible";
  /** A chart's box inside its slot: over the whole grid when maximized there, else filling the slot where slots are sized. */
  const slotInner = (index: number, flexed: boolean) => shown === index && fill ? "absolute inset-1 z-20 flex flex-col bg-[#0b1017]" : flexed ? "flex min-h-0 flex-1 flex-col" : "";
  // A phone or a narrow window gets 44px touch targets; a desktop gets compact ones.
  const tap = narrow ? "h-11 w-11" : "h-7 w-7";
  const control = narrow ? "h-11 min-w-11 px-2" : "h-7 min-w-7 px-1.5";
  const sep = <span aria-hidden className="mx-0.5 h-5 shrink-0 border-l border-slate-700/70" />;
  // Text beside a toolbar icon on a wide screen; in a phone's More menu it always shows.
  const label = narrow ? "" : "hidden min-[1800px]:inline";
  // A button's name that shows from 1800px and below it stays the button's name, so the toolbar keeps to one row on a laptop.
  const named = narrow ? "sr-only" : "sr-only min-[1800px]:not-sr-only";
  // The dock's tabs: a press opens that panel, a second press closes the dock. A phone's top row has room for two;
  // its strike ladder opens from the More menu.
  const dockTabs = ([["watchlist", "Watchlist", List, "Watchlist, levels and your latest fills"], ["layers", "Layers", LayersIcon, "Layers: show, hide, lock and delete what the charts draw"],
    ["options", "Strike ladder", Rows3, "Strike ladder: open interest, volume and gamma by strike"], ["level2", "Level 2", ListOrdered, "Level 2: a manual depth session and heatmap"]] as const)
    .filter(([tab]) => (!narrow || (tab !== "options" && tab !== "level2")) && (tab !== "level2" || owner)).map(([tab, name, Icon, hint]) =>
    <button key={tab} aria-label={name} aria-expanded={dockShown && dock.tab === tab} title={hint} onClick={() => toggleDock(tab)} className={`${plain(dockShown && dock.tab === tab)} ${control}`}><Icon size={14} /></button>);
  const level2Button = (close: () => void) => owner && !isMacroSymbol(symbol) && <button aria-label="Level 2" title="Level 2: a manual depth session and heatmap" onClick={() => { close(); showDock("level2"); }}
    className={`${plain(false)} ${control} text-[11px]`}><ListOrdered size={13} /><span>Level 2</span></button>;
  const ladderButton = (close: () => void) => !isMacroSymbol(symbol) && <button aria-label="Strike ladder" title="Strike ladder: open interest, volume and gamma by strike" onClick={() => { close(); showDock("options"); }}
    className={`${plain(false)} ${control} text-[11px]`}><Rows3 size={13} /><span>Strike ladder</span></button>;

  // Linked ranges sit in the toolbar on a desktop; on a phone they and the smaller charts' height are in its More menu, with pause, refresh and the shortcuts.
  const secondary = <>
    <button aria-label="Link time ranges" aria-pressed={settings.linkRange} onClick={() => setSettings((s) => ({ ...s, linkRange: !s.linkRange }))} title="Scroll and zoom every chart to the same time window"
      className={`${plain(settings.linkRange)} ${control} text-[11px]`}><Link2 size={13} /><span className={label}>Link time ranges</span></button>
    {/* On a wide screen the divider above the smaller charts sets their height (C7.4). */}
    {multi && narrow && <div role="group" aria-label="Small chart height" title="Height of the smaller charts" className="flex shrink-0 overflow-hidden rounded border border-slate-700/70 text-[10px]">
      {(["compact", "normal", "tall"] as SmallChartSize[]).map((size) => <button key={size} aria-pressed={settings.smallSize === size} aria-label={`${size} small charts`} onClick={() => setSettings((s) => ({ ...s, smallSize: size }))}
        className={`h-11 min-w-11 px-1.5 ${settings.smallSize === size ? "bg-slate-800 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>{size === "compact" ? "S" : size === "normal" ? "M" : "L"}</button>)}
    </div>}
  </>;
  // One chart or five: in the toolbar on a desktop, in the More menu on a phone.
  const focusButton = (close?: () => void) => <button className={`${plain(false)} ${control} text-[11px]`} onClick={() => { close?.(); setMaximized(null); setSettings((s) => ({ ...s, layout: s.layout === "multi" ? "single" : "multi" })); }} aria-label={settings.layout === "multi" ? "Show single chart" : "Show five charts"} title={settings.layout === "multi" ? "One chart" : "Five charts"}>
          {settings.layout === "multi" ? <Square size={13} /> : <Columns3 size={13} />}{!narrow && <span className={label}>{settings.layout === "multi" ? "Focus" : "Five charts"}</span>}</button>;
  const pauseButton = <button className={`${plain(paused, "bg-amber-400/15 text-amber-300")} ${control} text-[11px]`} onClick={() => setPaused((v) => !v)} aria-label={paused ? "Resume chart updates" : "Pause chart updates"} title={paused ? "Resume updates" : "Pause updates"}>{paused ? <Play size={13} /> : <Pause size={13} />}<span className={label}>{paused ? "Resume" : "Pause"}</span></button>;
  const refreshButton = <button className={`${plain(false)} ${control}`} disabled={loading} aria-label="Refresh charts" title="Refresh now" onClick={() => { if (!inFlight.current) refreshNow.current(); }}><RefreshCw size={13} className={loading ? "animate-spin" : ""} /></button>;
  const keysButton = <button className={`${plain(help)} ${control} hidden sm:inline-flex`} onClick={() => { if (palette === null && !layoutMenu) setHelp(true); }} aria-label="Keyboard shortcuts" aria-haspopup="dialog" aria-expanded={help} title="Keyboard shortcuts (?)"><Keyboard size={13} /></button>;

  // What the data is, and the chart library's attribution: in the status strip on a desktop, in the More menu on a phone.
  const about = <p className="w-72 whitespace-normal text-[11px] leading-5 text-slate-300">{latest?.history_note ?? "US stock and ETF charts powered by Tradier."} RTH VWAP uses minute HLC3 and resets at 9:30 ET. Live trade prices update candles while connected; volume and studies reconcile from Tradier every 15 seconds. Watchlist quotes may show the regular close after hours.</p>;
  const attribution = <span><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="hover:text-slate-300">TradingView Lightweight Charts™</a> <a href="/lightweight-charts-NOTICE.txt" className="hover:text-slate-300">Copyright (с) 2025 TradingView, Inc.</a></span>;
  // Undo, redo and the drawing tools (C1.1, C1.2): a slim rail beside the charts on a desktop, a toolbar row on a phone.
  const tools = <>
    {([["Undo", "before", edits.undo, Undo2, "⌘Z / Ctrl+Z"], ["Redo", "after", edits.redo, Redo2, "⇧⌘Z / Ctrl+Shift+Z"]] as const).map(([name, side, stack, Icon, key]) => <button key={name} aria-label={name} disabled={!stack.length}
      title={stack.length ? `${name} ${describeEdit(stack.at(-1)!, symbol)} (${key})` : `Nothing to ${name.toLowerCase()}`} onClick={() => replay(side)}
      className={`${plain(false)} ${narrow ? "h-11 w-11" : "h-8 w-8"}`}><Icon size={14} /></button>)}
    <span aria-hidden className={narrow ? "mx-0.5 h-5 border-l border-slate-700" : "my-1 w-5 border-t border-slate-700"} />
    <div role="group" aria-label="Drawing tools" className={`flex items-center ${narrow ? "" : "flex-col gap-0.5"}`}>
      {TOOLS.map(([kind, Icon]) => <button key={kind} aria-label={`Draw ${TOOL_NAMES[kind].toLowerCase()}`} aria-pressed={tool === kind} title={tool === kind ? "Cancel drawing (Esc)" : TOOL_NAMES[kind]} onClick={() => chooseTool(kind)}
        className={`${plain(tool === kind, "bg-blue-400/15 text-blue-300")} ${narrow ? "h-11 w-11" : "h-8 w-8"}`}><Icon size={14} /></button>)}
      <button aria-label="Magnet" aria-pressed={settings.magnet} title="Magnet: anchors snap to the nearest open, high, low or close (or hold ⌘/Ctrl)" onClick={() => setSettings((s) => ({ ...s, magnet: !s.magnet }))}
        className={`${plain(settings.magnet, "bg-amber-400/15 text-amber-300")} ${narrow ? "h-11 w-11" : "h-8 w-8"}`}><Magnet size={14} /></button>
    </div>
  </>;

  // The 30-day average volume for the price card: the symbol overview's, cached a day on the server.
  const [averageVolume, setAverageVolume] = useState<{ symbol: string; value: number | null } | null>(null);
  const cardSymbol = settings.symbol;
  useEffect(() => {
    if (isMacroSymbol(cardSymbol) || !(narrow ? sheet : dockShown) || dock.tab !== "watchlist") return;
    const controller = new AbortController();
    // Only the symbol stepped to and left: a quick run through the watchlist reads nothing on the way.
    const timer = setTimeout(() => fetchSymbolOverview(cardSymbol, controller.signal).then((data) => setAverageVolume({ symbol: cardSymbol, value: data.datasets?.statistics?.average_volume_30_day ?? null }))
      .catch(() => { if (!controller.signal.aborted) setAverageVolume({ symbol: cardSymbol, value: null }); }), 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [cardSymbol, narrow, sheet, dockShown, dock.tab]);
  // A dock dragged wider (or a phone's sheet) has room for the dollar change too.
  const watchWide = narrow || dockWidth >= 300;
  // The watchlist tab: the list, then the main symbol's levels and its latest fills, like a details pane under a watchlist.
  const watchlistPanel = <>
    <section aria-label="Watchlist">
      <div className="flex items-center justify-between border-b border-slate-700/40 py-1 pl-3 pr-1"><h2 className="text-xs font-medium text-slate-200">Watchlist <span className="ml-1 text-slate-500">{settings.watchlist.length}</span></h2>
        <div className="flex items-center gap-0.5">
          {([[-1, "Previous", "Shift+Space", ChevronUp], [1, "Next", "Space", ChevronDown]] as const).map(([by, name, key, Icon]) => <button key={name} aria-label={`${name} watchlist symbol`} title={`${name} symbol (${key})`} disabled={!settings.watchlist.length}
            onClick={() => { const next = stepWatchlist(settings.watchlist, settings.symbol, by); if (next) chooseSymbol(next); }} className={`${plain(false)} ${tap}`}><Icon size={14} /></button>)}
          <button aria-label={`Add ${settings.symbol} to watchlist`} title={`Add ${settings.symbol}`} disabled={settings.watchlist.includes(settings.symbol) || settings.watchlist.length >= 30} onClick={() => setSettings((s) => ({ ...s, watchlist: [...s.watchlist, s.symbol] }))} className={`${plain(false)} ${tap}`}><Plus size={14} /></button>
          <button aria-label="Close watchlist" title="Close the side panel" onClick={() => showDock(null)} className={`${plain(false)} ${tap}`}><X size={14} /></button>
        </div></div>
      <div className={`grid ${watchWide ? "grid-cols-[1fr_54px_44px_50px_38px_18px]" : "grid-cols-[1fr_54px_50px_38px_18px]"} gap-1 py-2 pl-3 pr-2 text-[9px] uppercase tracking-wider text-slate-600`}><span>Symbol</span><span className="text-right">Last</span>{watchWide && <span className="text-right">Chg</span>}<span className="text-right">Chg%</span><span className="text-right">Vol</span></div>
      {settings.watchlist.map((symbol) => {
        const quote = latest?.quotes.find((q) => q.symbol === symbol);
        const watchLive = { store: stream, key: streamKey, symbol, session, fetched: 0 } satisfies LiveFeed;
        return <div key={symbol} className={`group flex items-center border-l-2 ${settings.symbol === symbol ? "border-sky-400 bg-sky-400/5" : "border-transparent hover:bg-slate-800/50"}`}>
          {/* On a phone, charting a symbol closes the sheet so the chart shows. */}
          <button data-watch-row onKeyDown={watchKey} onClick={() => { chooseSymbol(symbol); if (narrow) setSheet(false); }} aria-label={`Chart ${symbol}`} aria-current={settings.symbol === symbol || undefined} className={`grid min-w-0 flex-1 ${watchWide ? "grid-cols-[1fr_54px_44px_50px_38px]" : "grid-cols-[1fr_54px_50px_38px]"} items-center gap-1 pl-2.5 pr-1 text-[11px] ${narrow ? "min-h-11 py-2" : "py-2.5"}`}><span className="truncate text-left font-medium text-slate-200">{symbol}</span><WatchlistQuote live={watchLive} quote={quote} market={latest?.equity_market ?? latest?.market} paused={paused} wide={watchWide} /></button>
          <button aria-label={`Remove ${symbol} from watchlist`} className={`inline-flex shrink-0 items-center justify-center rounded text-slate-600 hover:text-rose-300 ${narrow ? "h-11 w-11" : "mr-2 p-0.5"}`} onClick={() => setSettings((s) => ({ ...s, watchlist: s.watchlist.filter((v) => v !== symbol) }))}><X size={12} /></button>
        </div>;
      })}
      {!settings.watchlist.length && <p className="px-3 pb-4 text-xs text-slate-500">Look up a ticker, then use + to add it.</p>}
    </section>
    {!isMacroSymbol(settings.symbol) && <QuoteCard live={live} quote={selected} candle={latestCandle} market={market} average={averageVolume?.symbol === settings.symbol ? averageVolume.value : null} />}
    {!isMacroSymbol(settings.symbol) && <SymbolInfo positions={feedFor(settings.symbol)?.positions} comparisonGroup={comparisonGroup} onComparisonGroup={setComparisonGroup} symbol={settings.symbol} price={() => referenceFor(settings.symbol)} quote={latest?.quotes.find((quote) => quote.symbol === settings.symbol)} quoteFetchedAt={latest?.fetched_at.quotes ?? null} onSelectSymbol={(peer) => { chooseSymbol(peer); if (narrow) setSheet(false); }} focus={newsFocus} onFocusHandled={() => setNewsFocus(null)} />}
    {!isMacroSymbol(settings.symbol) && <><DockSection name="levels" ariaLabel="Saved price levels" title={`${settings.symbol} levels`} count={`${levels.length}/30`} defaultOpen={levels.length > 0} forceOpen={!!levelError} narrow={narrow}

      info="Save support, resistance, or a price you’re watching."
      status={settings.hiddenGroups.levels ? <button onClick={() => showGroup("levels")} title="Levels are hidden on every chart" className={`inline-flex items-center gap-1 rounded px-1 text-[10px] text-amber-300 hover:bg-slate-800 ${narrow ? "min-h-11" : ""}`}><EyeOff size={11} />Hidden · Show</button> : undefined}
      action={(reveal) => <button aria-label="Add level" title={`Add a ${settings.symbol} level`} onClick={() => { reveal(); window.setTimeout(() => levelPriceInput.current?.focus(), 0); }}
        className={`inline-flex shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${narrow ? "h-11 w-11" : "h-6 w-6"}`}><Plus size={13} /></button>}>
      {levels.map((level) => <div key={level.id} className={`mb-2 flex items-center gap-2 text-[11px] ${level.hidden ? "opacity-60" : ""}`}><span className="h-px w-3" style={{ background: level.color ?? "#60a5fa" }} /><span className="min-w-0 flex-1 truncate text-slate-400">{level.label}</span>
        {level.locked && <Lock size={11} className="text-slate-500" aria-label="Locked" />}
        {level.hidden && <button aria-label={`Show ${level.label}`} title="Hidden on the charts. Show it." onClick={() => editItem(settings.symbol, level.id, { hidden: false })} className={`inline-flex items-center justify-center text-slate-500 hover:text-slate-200 ${narrow ? "h-11 w-11" : "p-1"}`}><Eye size={12} /></button>}
        <span className="font-mono text-blue-300" style={level.color ? { color: level.color } : undefined} title={level.was != null ? `Saved as ${price(level.was)} before a split` : undefined}>{price(level.price)}{level.was != null && <span className="ml-1 text-[10px] text-slate-500">was {price(level.was)}</span>}</span><button aria-label={`Delete ${level.label}`} onClick={() => deleteItem(settings.symbol, level.id)} className={`inline-flex items-center justify-center text-slate-600 hover:text-rose-300 ${narrow ? "h-11 w-11" : "p-1"}`}><Trash2 size={12} /></button></div>)}
      <form onSubmit={(e) => { e.preventDefault(); addLevel(Number(levelPrice)); }} className="space-y-2">
        <input aria-label="Level label" placeholder="Label (optional)" value={levelLabel} maxLength={30} onChange={(e) => setLevelLabel(e.target.value)} className={`w-full rounded border border-slate-700 bg-[#10151e] px-2 text-xs outline-none focus:border-sky-600 ${narrow ? "h-11" : "h-8"}`} />
        <div className="flex gap-2"><input ref={levelPriceInput} aria-label="Level price" type="number" step="any" min="0.000001" required placeholder="Price" value={levelPrice} onChange={(e) => setLevelPrice(e.target.value)} className={`min-w-0 flex-1 rounded border border-slate-700 bg-[#10151e] px-2 font-mono text-xs outline-none focus:border-sky-600 ${narrow ? "h-11" : "h-8"}`} /><button type="submit" aria-label="Save price level" className={button(narrow ? "h-11 w-11" : "h-8 px-2.5")}><Plus size={14} /></button></div>
      </form>
      {levelError && <p role="alert" className="mt-2 text-[11px] text-amber-300">{levelError}</p>}
    </DockSection>
    <AlertsPanel data={alertData} prices={alertPrices} moved={movedWalls} narrow={narrow} onRearm={rearm} onRemove={dropAlert} />
    <DockSection name="journal" ariaLabel="Journal executions" title="On your journal" count={current?.fills.length ?? 0} defaultOpen={!!current?.fills.length} narrow={narrow}
      info="Your executions appear as arrows on the underlying chart when they fall inside a displayed candle.">
      {current?.fills.length ? <div className="space-y-3">{current.fills.length > 5 && <p className="text-[10px] text-slate-500">Latest 5 of {current.fills.length}</p>}{current.fills.slice(-5).reverse().map((fill) => <Link key={fill.id} href={`/fills/${fill.id}`} className="block text-[11px]"><span className="text-slate-300 hover:text-sky-300">{fill.label}</span><span className="mt-0.5 block text-[10px] text-slate-600">{etTime(fill.time, true)} · {etTime(fill.time)} ET</span></Link>)}{current.fills_truncated && <p className="text-[10px] text-amber-300">Most recent 1,000 fills shown.</p>}</div> : <p className="text-[11px] leading-5 text-slate-500">No executions on this chart yet.</p>}
    </DockSection></>}
  </>;
  // ---- C3.4, C3.5: pre-trade capture ----
  const refreshCaptures = useCallback(() => {
    fetchCaptures().then((data) => { setCaptures(data.captures); setNeedsLinking(data.needs_linking ?? 0); }).catch(() => { /* the strip keeps what it had */ });
    void outboxAll().then(setOutbox);
  }, []);
  const loadSetup = useCallback(() => fetchSetup().then((data) => { setCaptureSetup(data); setSetupError(""); })
    .catch((failure: Error) => setSetupError(`Accounts and templates could not load: ${failure.message}`)), []);
  useEffect(() => {
    refreshCaptures();
    void loadSetup();
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(DISMISSED_PLANS_KEY) ?? "[]");
      if (Array.isArray(saved)) setDismissedPlans(saved.filter((id): id is string => typeof id === "string").slice(-50));
    } catch { /* every plan's strip shows */ }
  }, [refreshCaptures, loadSetup]);
  // A transcript on its way is checked every few seconds, and only while one is.
  const transcribing = captures.some((row) => row.transcript?.status === "pending" || row.transcript?.status === "transcribing");
  useEffect(() => {
    if (!transcribing) return;
    const timer = window.setInterval(() => { if (!document.hidden) refreshCaptures(); }, 3000);
    return () => window.clearInterval(timer);
  }, [transcribing, refreshCaptures]);
  // A new journal fill on the chart (an import or a rebuild) may be the trade a plan was for (C3.6): re-read the plans then, not on a timer.
  const newestFill = current?.fills.at(-1)?.id ?? "";
  useEffect(() => { if (newestFill) refreshCaptures(); }, [newestFill, refreshCaptures]);
  const openLinks = () => {
    setLinkView({ data: null, loading: true, error: "" });
    void loadSetup();
    fetchReview().then((data) => { setLinkView({ data, loading: false, error: "" }); setNeedsLinking(data.count); },
      (err: Error) => setLinkView({ data: null, loading: false, error: err.message }));
  };
  // A link or tracking change: read the view and the strip again.
  const relink = async (work: Promise<unknown>) => {
    await work;
    const data = await fetchReview();
    setLinkView((open) => open && { data, loading: false, error: "" });
    setNeedsLinking(data.count);
    refreshCaptures();
  };
  // The strip shows the newest plan from the last day until it is dismissed here; dismissing never reveals an older one.
  const newestPlan = captures[0] && captures[0].received_at > Date.now() / 1000 - 86400 ? captures[0] : null;
  const shownPlan = newestPlan && !dismissedPlans.includes(newestPlan.id) ? newestPlan : null;
  const keepPlan = (row: Capture) => setCaptures((rows) => [row, ...rows.filter((other) => other.id !== row.id)].sort((a, b) => b.received_at - a.received_at));
  function openPlan() {
    if (plan || isMacroSymbol(settings.symbol)) return;
    setMenu(null); setEntry(NO_ENTRY);
    setPlan({ symbol: settings.symbol, key: Date.now() });
    // Templates may have changed on another device since the last look.
    void loadSetup();
  }
  /**
   * The main chart as it stands at the moment of saving, from what this page
   * already holds: no market-data request. A plan for another symbol than
   * the chart shows gets no snapshot, and says why.
   */
  const snapshotFor = (target: string): ChartSnapshot => {
    const slot = slots[0];
    const none = (reason: string): ChartSnapshot => ({ context: { state: "unavailable", reason }, canvas: null, imageNote: "" });
    if (slot.symbol !== target) return none(`The main chart showed ${slot.symbol}, not ${target}, when the plan was saved.`);
    const bars = panels.get(frameKey(slot))?.bars ?? [];
    if (!bars.length) return none(`The main chart had no ${target} candles loaded when the plan was saved.`);
    const state = stream.get(target);
    const tick = state.key === streamKey ? latestTrade(state.ticks, target) : undefined;
    const shown = shownPrice({ tick, quote: selected, candle: latestCandle, scope: live });
    const now = Date.now() / 1000;
    const last = bars[bars.length - 1];
    return {
      canvas: commands.snapshot("main"),
      imageNote: "The image is the main chart's canvas as drawn: candles, studies, fill arrows and the lines on it. Labels and cards drawn over the chart as page elements are not in it.",
      context: {
        state: "captured", symbol: target, panel: "main", interval: slot.interval, session, visible_range: visibleTimes.current.get(frameKey(slot)) ?? null,
        last_candle: { time: last.time, close: last.close },
        price: { value: shown.price ?? null, source: shown.source, at: shown.at ?? null, stale: staleCandles(now, live.fetched) },
        basis: basis ? { status: basis.status, splits: basis.splits.map((split) => ({ label: split.label, ex_date: split.ex_date })), as_of: basis.as_of } : null,
        levels: (visibleLevels.get(target) ?? NO_LEVELS).map((level) => ({ label: level.label, price: level.price })),
        drawings: (visibleDrawings.get(target) ?? NO_DRAWINGS).map((drawing) => ({ kind: drawing.kind, points: drawing.points.map((point) => ({ time: point.time, price: point.price })),
          ...(drawing.kind === "note" ? { text: drawing.text } : {}) })),
        auto_levels: (autoFor(target)?.zones ?? []).map((zone) => ({ label: zone.label, low: zone.low, high: zone.high })),
        captured_at: now,
      },
    };
  };
  const planSaved = (row: Capture, imageWaiting: boolean) => {
    setPlan(null);
    keepPlan(row);
    void outboxAll().then(setOutbox);
    const said = row.mode === "voice" ? (row.transcript?.status === "pending" ? "Recording saved — transcribing" : "Recording saved") : `Plan saved: ${captureTitle(row)}`;
    setNotice(imageWaiting ? `${said}. The chart image did not upload; retry it from the plan strip.` : said);
  };
  const retryOutbox = (item: OutboxItem) => {
    sendCapture(item).then(({ capture: row, imageWaiting }) => { keepPlan(row); setNotice(imageWaiting ? "Plan saved; the chart image is still waiting." : "Saved"); })
      .catch((failure: Error) => setNotice(`Not saved: ${failure.message}`))
      .finally(() => void outboxAll().then(setOutbox));
  };
  const dismissPlan = (id: string) => {
    const next = [...dismissedPlans.filter((other) => other !== id), id].slice(-50);
    setDismissedPlans(next);
    try { localStorage.setItem(DISMISSED_PLANS_KEY, JSON.stringify(next)); } catch { /* dismissed for this visit only */ }
  };
  const changePlan = (work: Promise<Capture>) => work.then(keepPlan).catch((failure: Error) => setNotice(failure.message));
  const railOut = !isMacroSymbol(symbol) && (railShown || !!tool);
  /** Put the desktop rail away (cancelling a chosen tool) or bring it back, remembered on this device. */
  const toggleRail = () => {
    if (tool) chooseTool(tool);
    const next = !railOut;
    setRailShown(next);
    try { localStorage.setItem(RAIL_KEY, next ? "1" : "0"); } catch { /* remembered for this visit only */ }
  };
  const planButton = !isMacroSymbol(symbol) && <button aria-label="Plan trade" aria-haspopup="dialog" aria-expanded={!!plan} title="Plan trade: what you are taking and your plan, before you enter (Alt+P)" onClick={openPlan}
    className={`${plain(!!plan)} ${control} text-[11px]`}><NotebookPen size={13} /><span className={named}>Plan trade</span></button>;

  const alerts = [
    past && <div key="past" role="status" aria-label="Past trade view" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-sky-500/30 bg-sky-500/5 px-3 py-1.5 text-xs text-sky-100">
      <span>Showing {past.symbol} {etTime(past.from, true)}, {etTime(past.from)}{past.to !== past.from ? `–${etTime(past.to, true) === etTime(past.from, true) ? "" : `${etTime(past.to, true)}, `}${etTime(past.to)}` : ""} ET, on stored consolidated candles.</span>
      <button onClick={backToLive} className="inline-flex min-h-7 items-center rounded border border-sky-400/40 px-2 text-sky-100 hover:bg-sky-500/15">Back to live</button></div>,
    symbolError && <p key="symbol" className="text-xs text-amber-300" role="alert">{symbolError}</p>,
    drawError && <p key="draw" className="text-xs text-amber-300" role="alert">{drawError}</p>,
    requestFailed && <div key="error" role="alert" aria-label="Chart data error" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs text-amber-200">{error.message}{current && <span className="ml-1">Showing the last successful data.</span>}</div>,
    !!issues.length && <div key="issues" role="alert" aria-label="Chart data warning" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs text-amber-200">{sampleChart ? "Simulated data. EMA/RSI use invented bars; VWAP and EMA200 are unavailable in this limited sample history. " : "Refresh incomplete. "}{issues.join(" ")} Check timestamps before using these charts.</div>,
    !!basisNotes.length && <div key="basis" role="status" aria-label="Price basis warning" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs text-amber-200">{basisNotes.join(" ")}</div>,
  ].filter(Boolean);

  return (
    <div ref={root} data-testid="chart-workspace" data-immersive={immersive || undefined} className={`text-slate-300 ${immersive
      ? "fixed inset-0 z-[70] flex flex-col bg-[#0b1017] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      : fill ? "flex min-h-0 flex-1 flex-col bg-[#0b1017]" : "space-y-2"}`}>
      <header aria-label="Chart toolbar" className={`flex flex-wrap items-center gap-1 ${fill ? "shrink-0 border-b border-slate-700/50 bg-[#0e131b] px-2 py-1" : "pb-1"} ${immersive ? "pt-[max(0.25rem,env(safe-area-inset-top))]" : ""}`}>
        <h1 className="sr-only">Charts</h1>
        <form onSubmit={submitSymbol} className={`relative flex shrink-0 items-center rounded-md border border-slate-700 bg-[#10151e] ${narrow ? "h-11" : "h-8"}`}>
          <button type="button" aria-label="Open symbol search" title="Search symbols (⌘K / Ctrl+K)" onClick={() => setPalette(0)} className={`${plain(false)} ${tap}`}><Search size={14} /></button><input aria-label="Chart symbol" value={symbolInput} placeholder={settings.symbol} onChange={(e) => setSymbolInput(e.target.value.toUpperCase())} maxLength={15} className="w-20 bg-transparent px-1 text-sm font-semibold uppercase text-slate-100 outline-none placeholder:text-slate-200" />
          <button type="submit" aria-label="Load symbol" className={`${plain(false)} ${tap}`}><ArrowUpRight size={14} /></button>
        </form>
        <LiveQuote live={live} quote={selected} candle={latestCandle} market={market} />
        {/* A phone keeps the dock's buttons beside the quote; the intervals get a row of their own that scrolls sideways. */}
        {narrow ? <div className="ml-auto flex shrink-0 items-center">{dockTabs}</div> : sep}
        <div role="group" aria-label="Main chart interval" className={`flex items-center ${narrow ? "min-w-0 basis-full overflow-x-auto" : ""}`}>
          {INTERVALS.map((interval) => <button key={interval} onClick={() => setIntervalAt(0, interval)} aria-pressed={settings.intervals[0] === interval} className={`${plain(settings.intervals[0] === interval)} ${control} text-[11px]`}>{interval}</button>)}
        </div>
        {/* A toggle that looks like one: lit while premarket and after-hours candles show. */}
        <button aria-pressed={settings.session === "extended"} title={settings.session === "extended" ? "Showing premarket and after-hours candles. Click for the regular session only." : "Showing the regular session only. Click to add premarket and after-hours candles."} onClick={() => setSettings((s) => ({ ...s, session: s.session === "extended" ? "regular" : "extended" }))} className={`${plain(settings.session === "extended")} ${control} gap-1 whitespace-nowrap text-[11px]`}>{settings.session === "extended" ? <Check size={12} aria-hidden /> : <Square size={11} aria-hidden />}{!narrow && <span aria-hidden className="min-[1800px]:hidden">ETH</span>}<span className={narrow ? "" : named}>Extended hours</span></button>
        {!narrow && sep}
        <ToolbarMenu label="Chart indicators" title="Studies and fill arrows on every chart" className={`${plain(false)} ${control} text-[11px]`}
          content={() => <div className="flex w-56 flex-col">
            {INDICATORS.filter(([key]) => !isMacroSymbol(symbol) || !["vwap", "volume", "fills"].includes(key)).map(([key, name]) => <div key={key} className="flex flex-wrap items-center">
              <button aria-pressed={indicators[key]} onClick={() => toggleIndicator(key)}
                className={`flex min-w-0 flex-1 items-center justify-between gap-2 rounded px-2 text-left text-[11px] hover:bg-slate-800 ${narrow ? "min-h-11" : "min-h-7"} ${indicators[key] ? "text-slate-200" : "text-slate-500"}`}>{name}{indicators[key] ? <Eye size={12} aria-hidden /> : <EyeOff size={12} aria-hidden />}</button>
              {key in INDICATOR_COLORS && <label title={`${name} color`} className={`flex shrink-0 items-center justify-center ${narrow ? "h-11 w-11" : "h-7 w-7"}`}>
                <input type="color" aria-label={`${name} color`} value={colors[key as ColorKey]} onChange={(event) => setColor(key as ColorKey, event.target.value)}
                  className="h-4 w-4 cursor-pointer rounded border border-slate-600 bg-transparent p-0 [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded-[3px] [&::-webkit-color-swatch]:border-0 [&::-moz-color-swatch]:border-0" />
              </label>}
              {key === "vwap" && <button aria-pressed={vwapBandsOn} onClick={toggleVwapBands}
                title="RTH VWAP ±1σ (dashed); regular-session candles only. Independent of option-implied Expected move."
                className={`flex w-full items-center justify-between gap-2 rounded px-2 text-left text-[11px] hover:bg-slate-800 ${narrow ? "min-h-11" : "min-h-7"} ${vwapBandsOn ? "text-slate-200" : "text-slate-500"}`}>VWAP bands ±1σ{vwapBandsOn ? <Eye size={12} aria-hidden /> : <EyeOff size={12} aria-hidden />}</button>}
            </div>)}
            <button onClick={() => setSettings((s) => ({ ...s, indicatorColors: {} }))} disabled={!Object.keys(settings.indicatorColors).length}
              className={`rounded px-2 text-left text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:text-slate-600 disabled:hover:bg-transparent ${narrow ? "min-h-11" : "min-h-7"}`}>Reset colors</button>
            <div role="group" aria-label="Zoom speed" title="How fast the wheel or a trackpad pinch zooms the charts. Remembered on this device." className="mt-1 border-t border-slate-700/60 px-2 pt-1.5">
              <div className="pb-1 text-[10px] text-slate-500">Zoom speed · this device</div>
              <div className="flex overflow-hidden rounded border border-slate-700/70">
                {(Object.keys(ZOOM_SPEED_NAMES) as ZoomSpeed[]).map((speed) => <button key={speed} aria-pressed={zoomSpeed === speed} onClick={() => { writeZoomSpeed(speed); setZoomSpeed(speed); }}
                  className={`flex-1 px-1 text-[11px] ${narrow ? "min-h-11" : "min-h-6"} ${zoomSpeed === speed ? "bg-slate-800 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>{ZOOM_SPEED_NAMES[speed]}</button>)}
              </div>
            </div>
          </div>}><SlidersHorizontal size={13} aria-hidden /><span className={named}>Indicators</span>{!narrow && <ChevronDown size={12} aria-hidden />}</ToolbarMenu>
        {settings.studiesHidden && <button onClick={toggleStudies} title="Indicators are hidden on every chart" className={`${plain(false)} ${control} gap-1 text-[10px] !text-amber-300`}><EyeOff size={11} />Indicators hidden · Show</button>}
        <button className={`${plain(layoutMenu)} ${control} text-[11px]`} onClick={() => { if (palette === null) setLayoutMenu(true); }} aria-haspopup="dialog" aria-expanded={layoutMenu} title="Saved layouts"><LayoutGrid size={13} /><span className={named}>Layouts</span>{inUse && <span className={narrow ? "sr-only" : "max-w-24 truncate text-sky-300"}>{inUse.name}</span>}</button>
        {!narrow && <button className={`${plain(macroArrangement(settings))} ${control} text-[11px]`} aria-label="Macro layout" onClick={() => choosePreset(LAYOUT_PRESETS.find((p) => p.id === "macro")!)}>Macro</button>}
        {techReturn && (!narrow || techReturn.active) && <button className={`${plain(false)} ${control} text-[11px]`} aria-label="Back to Tech" onClick={backToTech}>Tech</button>}
        {!narrow && focusButton()}
        {narrow ? <button aria-label={drawOpen || tool ? "Hide drawing tools" : "Show drawing tools"} aria-expanded={drawOpen || !!tool} title="Drawing tools, undo and redo"
          onClick={() => { if (tool) chooseTool(tool); setDrawOpen((open) => !(open || !!tool)); }} className={`${plain(drawOpen || !!tool, "bg-blue-400/15 text-blue-300")} ${control}`}><Pencil size={14} aria-hidden /></button>
          : <button aria-label={railOut ? "Hide drawing tools" : "Show drawing tools"} aria-expanded={railOut} title={railOut ? "Hide the drawing tools for a wider chart (remembered on this device)" : "Drawing tools, undo and redo"}
            onClick={toggleRail} className={`${plain(railOut, "bg-blue-400/15 text-blue-300")} ${control}`}><Pencil size={13} aria-hidden /></button>}
        {!narrow && secondary}
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {narrow
            // A phone keeps one row of controls: the rest wait in a menu.
            ? <ToolbarMenu label="More chart controls" align="right" title="More chart controls" className={`${plain(false)} ${control}`}
              content={(close) => <div className="flex w-72 flex-wrap items-center gap-1">{focusButton(close)}{secondary}{ladderButton(close)}{level2Button(close)}{pauseButton}{refreshButton}{keysButton}
                <div className="mt-1 w-full space-y-2 border-t border-slate-700/60 pt-2 text-[10px] text-slate-500">{about}{attribution}</div></div>}><MoreHorizontal size={14} aria-hidden /><span className="sr-only">More chart controls</span></ToolbarMenu>
            : <>{planButton}{sep}{pauseButton}{refreshButton}{keysButton}</>}
          {immersive
            ? <button className={`${button(narrow ? "h-11 w-11" : "h-7 px-2.5")} !border-sky-500/60 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25`} onClick={() => setImmersive(false)} aria-label="Exit full-screen charts" title="Exit full screen (Esc)"><X size={14} />{!narrow && "Exit"}</button>
            : <button className={`${plain(false)} ${control}`} onClick={() => setImmersive(true)} aria-label="Enter full-screen charts" title="Full screen: hide the app navigation"><Expand size={13} /></button>}
          {!narrow && <>{sep}{dockTabs}</>}
        </div>
        {narrow && (drawOpen || tool) && <div role="toolbar" aria-label="Drawing" className="flex basis-full flex-wrap items-center">{tools}</div>}
      </header>

      {!!alerts.length && <div className={fill ? "max-h-28 shrink-0 space-y-1 overflow-y-auto px-2 pt-1" : "space-y-2"}>{alerts}</div>}
      <PlanStrip capture={shownPlan} outbox={outbox} narrow={narrow} onRetry={retryOutbox} onDismiss={dismissPlan} onNotTaken={(id) => changePlan(markNotTaken(id))}
        onRetryTranscript={(id) => changePlan(retryTranscript(id))} onNote={(id, kind: CaptureNote["kind"], text) => addCaptureNote(id, kind, text).then(keepPlan)}
        needsLinking={needsLinking} onReview={openLinks} onUnlink={(id) => relink(unlinkCapture(id)).catch((failure: Error) => setNotice(failure.message))} />

      <div className={fill ? "flex min-h-0 flex-1" : ""}>
        {!narrow && railOut && <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 overflow-y-auto border-r border-slate-700/50 py-1">{tools}</div>}
        {/* A maximized chart is placed over this box, outside the grid's scrolling (C7.4). */}
        <div className={fill ? "relative flex min-h-0 min-w-0 flex-1" : "relative"}>
        <div data-testid="chart-grid" data-maximized={shown ?? undefined} className={fill ? `flex min-h-0 min-w-0 flex-1 flex-col ${sized ? "" : "gap-1"} ${cover ? "overflow-hidden" : "overflow-y-auto"} overscroll-contain p-1` : "space-y-2"}>
          {response ? <>
            {/* Desktop: the main chart and the smaller row share the height by the divider between them, each keeping a usable minimum; below that this area scrolls. Phone full screen: the main chart is the screen, the others below it. */}
            {slots.slice(0, 1).map((slot) => <div key={slot.index} ref={mainBox} style={sized ? { flexGrow: grow(1 - sizes.lower), flexBasis: 0 } : undefined}
              className={`${fill ? `flex flex-col ${narrow ? "h-full shrink-0" : multi ? "min-h-[320px]" : "min-h-0 flex-1"}` : ""} ${slotHidden(0)}`}>
              <div className={slotInner(0, fill)}>
              <PriceChart id="main" main symbol={slot.symbol} indexAsOf={feedFor(slot.symbol)?.intraday_as_of} interval={slot.interval} session={session} panel={panels.get(frameKey(slot))} pending={pendingFor(slot)} live={lives.get(slot.symbol)!} indicators={indicators} colors={colors} levels={isMacroSymbol(slot.symbol) ? NO_LEVELS : visibleLevels.get(slot.symbol) ?? NO_LEVELS} drawings={isMacroSymbol(slot.symbol) ? NO_DRAWINGS : visibleDrawings.get(slot.symbol) ?? NO_DRAWINGS} autoLevels={autoFor(slot.symbol)} levelEvents={feedFor(slot.symbol)?.panels[slot.interval]?.level_events} optionsNearest={optionsOn && !isMacroSymbol(slot.symbol) ? settings.optionsLayer.nearest : null} rangeBands={rangesOn && !isMacroSymbol(slot.symbol)} vwapBands={vwapBandsOn && !isMacroSymbol(slot.symbol)} highlight={strike?.symbol === slot.symbol ? strike.price : null} rvol={feedFor(slot.symbol)?.rvol ?? null} earnings={feedFor(slot.symbol)?.earnings ?? null} news={newsMarkers} onNews={openNews} fillLabels={settings.fillLabels} alerts={isMacroSymbol(slot.symbol) ? NO_MARKS : alertMarks.get(slot.symbol) ?? NO_MARKS} positions={isMacroSymbol(slot.symbol) ? NO_POSITIONS : positionsFor(slot.symbol)} onFill={openFill} depth={slot.symbol === symbol ? depth : null} liquidity={slot.symbol === symbol ? liquidity : null} link={link} rangeLink={rangeLink} commands={commands} linkRange={settings.linkRange && multi} clock={clockFor(slot.symbol)} height={fill ? undefined : 410}
                tool={isMacroSymbol(slot.symbol) ? null : tool} magnet={settings.magnet} toolStyle={tool && tool !== "level" ? settings.toolStyles[tool] : undefined} onDraw={addLevel} onPlace={(kind, points) => placeDrawing(slot.symbol, kind, points, "main")} onInterval={(i) => setIntervalAt(0, i)}
                selected={picked?.symbol === slot.symbol ? picked.id : null} showSelection={picked?.panel === "main"} fresh={fresh} onSelect={select(slot.symbol, "main")}
                onMove={(id, value) => moveLevel(slot.symbol, id, value)} onEditDrawing={(id, patch) => editDrawing(slot.symbol, id, patch)} onDelete={(id) => deleteItem(slot.symbol, id)}
                onMenu={isMacroSymbol(slot.symbol) ? undefined : openMenu(slot.symbol, "main")} onUnlock={(id) => editItem(slot.symbol, id, { locked: false })}
                maximized={multi ? shown === 0 : undefined} onMaximize={multi ? () => toggleMaximized(0) : undefined} onPlan={narrow ? openPlan : undefined}
                history={currentOlder[frameKey(slot)]} onNeedHistory={(before) => void loadOlder(slot, before)} onRetryHistory={() => void loadOlder(slot, undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(frameKey(slot), range)} onUserMove={() => pastJumps.current.delete(frameKey(slot))} />
              </div>
            </div>)}
            {sized ? <Splitter key="rows" label="Resize main chart and smaller charts" orientation="horizontal" className={`h-1 ${cover ? "invisible" : ""}`}
              now={Math.round((1 - sizes.lower) * 100)} min={Math.round((1 - LOWER_SHARE.max) * 100)} max={Math.round((1 - LOWER_SHARE.min) * 100)} text={`Main chart ${Math.round((1 - sizes.lower) * 100)}% of the height`}
              onDrag={dragRows} onStep={stepRows} onEdge={edgeRows} onReset={() => setSizes((current) => ({ ...current, lower: DEFAULT_PROPORTIONS.lower }))} /> : null}
            {multi && <div ref={lowerBox} style={sized ? { flexGrow: grow(sizes.lower), flexBasis: 0 } : undefined}
              // Too narrow for four smaller charts at their minimum (a 1024px window with the navigation expanded), the row scrolls sideways inside the grid.
              className={sized ? "flex min-h-[180px] min-w-0 overflow-x-auto overflow-y-hidden overscroll-contain" : "grid min-w-0 shrink-0 grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-4"}>
              {slots.slice(1).flatMap((slot) => { const index = slot.index - 1; return [
                index > 0 && sized ? <Splitter key={`column-${index}`} label={`Resize Panel ${index + 1} and Panel ${index + 2}`} orientation="vertical" className={`w-1 ${cover ? "invisible" : ""}`}
                  now={Math.round(sizes.columns.slice(0, index).reduce((sum, share) => sum + share, 0) * 100)}
                  min={Math.round((sizes.columns.slice(0, index - 1).reduce((sum, share) => sum + share, 0) + COLUMN_MIN) * 100)}
                  max={Math.round((sizes.columns.slice(0, index + 1).reduce((sum, share) => sum + share, 0) - COLUMN_MIN) * 100)}
                  text={`Panel ${index + 1} ${Math.round(sizes.columns[index - 1] * 100)}%, Panel ${index + 2} ${Math.round(sizes.columns[index] * 100)}% of the row`}
                  onDrag={() => dragColumn(index - 1)} onStep={(by) => stepColumn(index - 1, by)} onEdge={(to) => stepColumn(index - 1, to)} onReset={resetColumns} /> : null,
                <div key={slot.index} ref={(box) => { columnBoxes.current[index] = box; }}
                  style={sized ? { flexGrow: grow(sizes.columns[index]), flexBasis: 0, minWidth: COLUMN_MIN_PX } : undefined}
                  className={`${sized ? "flex flex-col" : shown === slot.index && !fill ? "sm:col-span-2 lg:col-span-4" : ""} min-w-0 ${slotHidden(slot.index)}`}>
                <div className={slotInner(slot.index, sized)}>
                <PriceChart id={`Panel ${slot.index + 1}`} symbol={slot.symbol} indexAsOf={feedFor(slot.symbol)?.intraday_as_of} follows={!settings.panelSymbols[slot.index]} onPickSymbol={() => setPalette(slot.index)}
                  notice={slot.symbol !== symbol && settings.indicators.fills && feedFor(slot.symbol)?.fills_truncated ? `Most recent 1,000 ${slot.symbol} fills shown.` : null} interval={slot.interval} session={session} panel={panels.get(frameKey(slot))} pending={pendingFor(slot)} live={lives.get(slot.symbol)!} indicators={panelIndicators[slot.index]} colors={colors} ownStudies={settings.panelStudies[slot.index]} onStudies={(next) => setPanelStudies(slot.index, next)} studiesHidden={settings.studiesHidden} levels={isMacroSymbol(slot.symbol) ? NO_LEVELS : visibleLevels.get(slot.symbol) ?? NO_LEVELS} drawings={isMacroSymbol(slot.symbol) ? NO_DRAWINGS : visibleDrawings.get(slot.symbol) ?? NO_DRAWINGS} autoLevels={autoFor(slot.symbol)} levelEvents={feedFor(slot.symbol)?.panels[slot.interval]?.level_events} optionsNearest={optionsOn && !isMacroSymbol(slot.symbol) ? settings.optionsLayer.nearest : null} rangeBands={rangesOn && !isMacroSymbol(slot.symbol)} vwapBands={vwapBandsOn && !isMacroSymbol(slot.symbol)} highlight={strike?.symbol === slot.symbol ? strike.price : null} rvol={feedFor(slot.symbol)?.rvol ?? null} earnings={feedFor(slot.symbol)?.earnings ?? null} news={settings.newsOnSmall ? newsMarkers : null} newsSmall={settings.newsOnSmall} onNews={openNews} alerts={isMacroSymbol(slot.symbol) ? NO_MARKS : alertMarks.get(slot.symbol) ?? NO_MARKS} positions={isMacroSymbol(slot.symbol) ? NO_POSITIONS : positionsFor(slot.symbol)} onFill={openFill} magnet={settings.magnet} link={link} rangeLink={rangeLink} commands={commands} linkRange={settings.linkRange} clock={clockFor(slot.symbol)}
                  history={currentOlder[frameKey(slot)]} onNeedHistory={(before) => void loadOlder(slot, before)} onRetryHistory={() => void loadOlder(slot, undefined, true)} onVisibleRange={(range) => visibleTimes.current.set(frameKey(slot), range)} onUserMove={() => pastJumps.current.delete(frameKey(slot))}
                  height={sized || (shown === slot.index && fill) ? undefined : shown === slot.index ? 410 : smallHeight} maximized={shown === slot.index}
                  onMaximize={() => toggleMaximized(slot.index)} onDraw={(value) => addLevel(value, slot.symbol)} onInterval={(i) => setIntervalAt(slot.index, i)}
                  selected={picked?.symbol === slot.symbol ? picked.id : null} showSelection={picked?.panel === `Panel ${slot.index + 1}`} fresh={fresh} onSelect={select(slot.symbol, `Panel ${slot.index + 1}`)}
                  onMove={(id, value) => moveLevel(slot.symbol, id, value)} onEditDrawing={(id, patch) => editDrawing(slot.symbol, id, patch)} onDelete={(id) => deleteItem(slot.symbol, id)}
                  onMenu={isMacroSymbol(slot.symbol) ? undefined : openMenu(slot.symbol, `Panel ${slot.index + 1}`)} onUnlock={(id) => editItem(slot.symbol, id, { locked: false })}
                  onFocus={() => { setMaximized(null); setSettings((s) => focusPanel(s, slot.index)); }} />
                </div>
              </div>]; })}
            </div>}
          </> : <div className={`flex flex-col items-center justify-center rounded-lg border border-slate-700/50 bg-[#10151e] px-8 text-center ${fill ? "min-h-0 flex-1" : "min-h-[490px]"}`}>
            {loading ? <Loader2 className="mb-4 animate-spin text-sky-300" size={28} /> : <ChartCandlestick className="mb-4 text-slate-600" size={36} />}
            <p className="text-sm font-medium text-slate-200">{loading ? `Loading ${settings.symbol} candles…` : "Your chart workspace is ready"}</p>
            <p className="mt-2 max-w-md text-xs leading-6 text-slate-500">{loading ? "Loading shared intraday and daily history from Tradier." : "Charts appear when Tradier market data is available. Your watchlist, intervals, and levels are saved to your workspace on every device."}</p>
          </div>}
        </div>
        </div>
        {/* The dock's edge is its divider (C7.4): this device's width, never less than the charts need. */}
        {!narrow && dockShown && <Splitter label="Resize side panel" orientation="vertical" className="w-px bg-slate-700/50"
          now={dockWidth} min={DOCK_WIDTH.min} max={DOCK_WIDTH.max} text={`Side panel ${dockWidth} pixels wide`}
          onDrag={dragDock} onStep={(by) => { const most = dockLimit(); keepDockWidth(clamp((dockBox.current?.getBoundingClientRect().width ?? dockWidth) - by * 16, DOCK_WIDTH.min, most)); }}
          onEdge={(to) => keepDockWidth(to === "min" ? DOCK_WIDTH.min : dockLimit())} onReset={() => keepDockWidth(DOCK_WIDTH.default)} />}
        {!narrow && dockShown && <aside ref={dockBox} aria-label="Side panel" style={{ width: dockWidth, maxWidth: `max(${DOCK_WIDTH.min}px, calc(100% - ${GRID_MIN_PX + 40}px))` }} className="shrink-0 overflow-y-auto overscroll-contain bg-[#121924]">
          {dock.tab === "layers" ? layersPanel(false) : dock.tab === "options" ? ladderPanel(false) : dock.tab === "level2" && owner ? level2Panel(false) : watchlistPanel}
        </aside>}
      </div>

      {/* Provider, freshness, session and price basis stay in view however dense the charts get; attribution too. */}
      <footer aria-label="Chart status" className={`flex items-center gap-x-3 gap-y-1 text-[10px] text-slate-500 ${fill && !narrow ? "h-6 shrink-0 whitespace-nowrap border-t border-slate-700/50 px-2" : fill ? "shrink-0 flex-wrap border-t border-slate-700/50 px-2 py-1" : "flex-wrap px-1 pt-1"}`}>
        <FeedStatus live={live} paused={paused} delayed={!!latest?.delayed} hasData={hasData} failed={failed} loading={loading} sample={sampleChart} />
        {marketLabel && <span aria-label="Market hours" title={market?.description ?? undefined} className={`shrink-0 rounded px-1.5 py-px ${market?.note ? "bg-amber-400/10 text-amber-300" : "bg-slate-800 text-slate-300"}`}>{marketLabel}</span>}
        {basis && <span role="status" aria-label="Price basis" title={basis?.basis === "index_native" ? "Tradier index observations; no split adjustment applies." : basisTitle} className={`shrink-0 rounded px-1.5 py-px ${basisNotes.length ? "bg-amber-400/10 text-amber-300" : "bg-slate-800 text-slate-300"}`}>
          {basis.basis === "index_native" ? (symbol === "US10Y" ? "Yield % · TNX / 10" : "Index points") : basis.status === "unknown" ? "Splits unknown · prices as supplied" : `Split-adjusted${basis.splits.length ? ` · ${basis.splits.length} split${basis.splits.length > 1 ? "s" : ""}` : ""}`}</span>}
        {!isMacroSymbol(symbol) && <LiveFooter live={live} quote={selected} candle={latestCandle} market={market} asOf={current ? current.intraday_as_of : undefined} brief={narrow && immersive} />}
        {owner && depthSession.running && <span role="status" aria-label="Level 2 session" className="flex shrink-0 items-center gap-1 rounded bg-sky-400/10 px-1.5 py-px text-sky-200">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />{depthSession.symbol} Level 2 live
          <button onClick={depthSession.stop} className="ml-1 rounded px-1 text-sky-100 underline-offset-2 hover:underline">Stop</button></span>}
        <div className={`ml-auto flex items-center gap-x-3 gap-y-1 ${fill && !narrow ? "shrink-0" : "min-w-0 flex-wrap"}`}>
          <span role="status" aria-label="Chart settings" className={`flex items-center gap-1 ${sync === "offline" || merged ? "text-amber-300" : ""}`}>{sync === "saving" || sync === "loading" ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}{sync !== "offline" && merged ? "Merged with changes from another device" : SYNC_TEXT[sync]}{sync === "offline" && !stored ? " · browser storage unavailable" : ""}</span>
          {!narrow && <ToolbarMenu label="About chart data" above align="right" title="About this data" className={`${plain(false)} h-5 w-5`} content={() => about}>
            <Info size={12} aria-hidden /><span className="sr-only">About chart data</span></ToolbarMenu>}
          {!narrow && attribution}
        </div>
      </footer>

      {palette !== null && <SymbolPalette current={palette ? slots.find((slot) => slot.index === palette)?.symbol ?? symbol : symbol} recent={settings.recent} watchlist={settings.watchlist} quotes={latest?.quotes ?? []}
        panel={palette ? { name: `Panel ${palette + 1}`, follow: symbol, held: settings.panelSymbols[palette] } : undefined}
        onChoose={(choice) => palette ? choosePanelSymbol(palette, choice) : chooseSymbol(choice)} onFollow={() => { if (palette) choosePanelSymbol(palette, null); }} onClose={() => setPalette(null)} />}
      {help && <HotkeySheet onClose={() => setHelp(false)} />}
      {linkView && (() => {
        const view = <LinkReview review={linkView.data} loading={linkView.loading} error={linkView.error} setup={captureSetup}
          onLink={(id, trade) => relink(linkCapture(id, trade))} onUnlink={(id) => relink(unlinkCapture(id))}
          onTracking={(on, accounts) => relink(saveTracking(on, accounts))} onClose={() => setLinkView(null)} />;
        return narrow ? <Sheet label="Needs linking" onClose={() => setLinkView(null)}>{view}</Sheet>
          : <div role="dialog" aria-label="Needs linking" className="fixed right-3 top-28 z-[70] max-h-[calc(100vh-8.5rem)] w-96 overflow-y-auto overscroll-contain rounded-lg border border-slate-600 bg-[#121924] shadow-2xl">{view}</div>;
      })()}
      {tradeCard && (() => {
        const shownCard = <TradeCard key={tradeCard.key} card={tradeCard.data} loading={tradeCard.loading} error={tradeCard.error}
          last={tradeCard.data?.trade?.ticker === symbol ? selected?.last ?? null : null} onClose={() => setTradeCard(null)}
          onShow={(from, to) => { commands.jump({ panel: "main", times: [from, to], prices: [] }); if (narrow) setTradeCard(null); }} />;
        // A phone: a bottom sheet over the charts. Desktop: a panel over the charts' top right, leaving them live underneath.
        return narrow ? <Sheet label="Trade card" onClose={() => setTradeCard(null)}>{shownCard}</Sheet>
          : <div role="dialog" aria-label="Trade card" className="fixed right-3 top-28 z-[70] max-h-[calc(100vh-8.5rem)] w-80 overflow-y-auto overscroll-contain rounded-lg border border-slate-600 bg-[#121924] shadow-2xl">{shownCard}</div>;
      })()}
      {plan && <PlanSheet key={plan.key} symbol={plan.symbol} chartSymbol={symbol} setup={captureSetup} setupError={setupError} narrow={narrow} snapshot={snapshotFor}
        onSetup={setCaptureSetup} onSaved={planSaved} onQueued={() => void outboxAll().then(setOutbox)} onRejected={() => void loadSetup()} onClose={() => setPlan(null)} />}
      {narrow && sheet && (dock.tab === "layers" ? layersPanel(true) : dock.tab === "options" ? ladderPanel(true) : dock.tab === "level2" && owner ? level2Panel(true) : <Sheet label="Watchlist" onClose={() => showDock(null)}>{watchlistPanel}</Sheet>)}
      {menu && (!menu.id || menuItem) && <ChartMenu key={`${menu.panel}|${menu.id}|${menu.at.x}|${menu.at.y}`} at={menu.at} symbol={menu.symbol} price={menu.price} item={menuItem}
        layers={layerToggles} hidden={hiddenItems(menu.symbol)} alerts={menuAlerts} onAddLevel={(value) => menuAddLevel(menu.symbol, value)} onCopyPrice={(value) => void copyPrice(value)} onReset={menu.reset}
        onEdit={(patch) => { if (menu.id) editItem(menu.symbol, menu.id, patch); }} onDuplicate={() => { if (menu.id) duplicateItem(menu.symbol, menu.id, menu.panel); }}
        onDelete={() => { if (menu.id) deleteItem(menu.symbol, menu.id); }} onClose={() => setMenu(null)} />}
      {notice && <div role="status" aria-label="Chart notice" className="pointer-events-none fixed bottom-[max(1rem,env(safe-area-inset-bottom))] left-1/2 z-[85] max-w-[calc(100%-2rem)] -translate-x-1/2 rounded-md border border-slate-600 bg-[#121924]/95 px-3 py-1.5 text-xs text-slate-200 shadow-xl">{notice}</div>}
      {entry.typed && <div role="status" aria-label="Interval entry" className="pointer-events-none fixed left-1/2 top-1/2 z-[75] min-w-56 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-slate-600 bg-[#121924]/95 px-4 py-3 text-center shadow-2xl">
        <div className="font-mono text-2xl font-medium text-slate-100">{entry.typed}<span className="text-base text-slate-500">m</span></div>
        <p className={`mt-1 text-[11px] ${entry.invalid ? "text-amber-300" : "text-slate-400"}`}>{entry.invalid ? `No ${entry.typed}m interval. Type 1, 3, 5, 15 or 30.` : "Enter to apply · Esc to cancel"}</p>
      </div>}
      {layoutMenu && <LayoutMenu layouts={settings.layouts.map((layout) => layoutWithSizes(settings, layout))} current={arrangementOf(settings)} onApply={chooseLayout} onPreset={choosePreset} onSave={saveLayout} onRename={renameLayout}
        onUpdate={updateLayout} onDelete={deleteLayout} onResetSizes={narrow ? undefined : resetSizes} onClose={() => setLayoutMenu(false)} />}
    </div>
  );
}
