"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, TickMarkType, createChart, createSeriesMarkers,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type IPrimitivePaneRenderer, type IPrimitivePaneView, type ISeriesApi, type ISeriesMarkersPluginApi,
  type ISeriesPrimitive, type LineData, type Logical, type SeriesAttachedParameter, type SeriesMarker, type Time, type UTCTimestamp, type WhitespaceData,
} from "lightweight-charts";
import { SessionShade } from "@/lib/sessionShade";
import type { ChartBar, Interval } from "@/lib/charts";
import { alertText, createAlert, removeAlert, type AlertsPayload } from "@/lib/alerts";
import { CONTEXT_MAX, copilotLabHref, type DrawnPlan } from "@/lib/copilot";
import { Flash } from "@/components/copilot/Ticks";
import { heldReading } from "@/lib/deskTicks";
import { ChartEventMarks, chartEvents, earningsHeader, eventLogical, nyDayOf } from "@/components/copilot/ChartEvents";
import { ChartNewsMarks, newsWhen, useChartNews } from "@/components/copilot/ChartNews";
import { cn } from "@/lib/utils";
import { getDeskChart, signedPct, type DeskChartAlert, type DeskChartData, type DeskChartNews, type DeskChartMark, type DeskStudySeries, type DeskTimeframe } from "@/lib/desk";

/*
 * The cockpit centre's chart (docs/copilot-lab.md § The desk): the selected symbol's candles from the desk's chart read
 * (`GET /copilot/desk/{id}/chart`) on the library the Charts workspace uses, with the plan's entry and invalidation as
 * labelled lines, the owner's fills, today's phone pings and Radar hits as marks, and a time stop still ahead as a
 * dashed vertical line. Crosshair, wheel or pinch zoom, drag to pan, Reset. It reads again each minute while bars can
 * still change; no stream.
 *
 * Studies come with the read (computed on the server with the workspace's math, warmed on earlier candles): VWAP,
 * EMA 9/21, the previous close and pre-market high/low on 2m and 15m, EMA 21 and SMA 50/200 on 1D, and volume in its
 * own pane with RVol. Each has a toggle in the legend row, which shows its value at the crosshair; the choices are kept
 * per timeframe in this browser. The symbol's other armed alerts are thin dotted lines with a chip to remove one (and
 * undo). A tap on the price scale, a long-press or a right-click on the candles opens the level menu: an alert when
 * price crosses there, a plan from there (the copilot's plan form, prefilled, nothing saved), or a question to the
 * copilot about it. Drawing and the rest live in Charts.
 */

const ET = "America/New_York";
const REFRESH_MS = 60_000;
const COLOR = { fill: "#e9a23b", ping: "#a78bfa", radar: "#60a5fa", entry: "#7db3f0", invalidation: "#fca5a5", target: "#86efac", stop: "#a1a1aa",
  alert: "#f4c66bb0", reference: "#9a9aa3a0", pick: "#e4e4e7" };

/** The studies each timeframe offers, in the legend's order; ``levels`` is the previous close and the pre-market high
 * and low; ``news`` the symbol's headlines at their candles (``ChartNews``). All on by default. */
export type StudyKey = "vwap" | "ema9" | "ema21" | "sma50" | "sma200" | "volume" | "levels" | "news";
const LINES = ["vwap", "ema9", "ema21", "sma50", "sma200"] as const;
type LineKey = typeof LINES[number];
export const STUDIES: Record<DeskTimeframe, StudyKey[]> = {
  "2m": ["vwap", "ema9", "ema21", "volume", "levels", "news"], "15m": ["vwap", "ema9", "ema21", "volume", "levels", "news"], "1D": ["ema21", "sma50", "sma200", "volume"],
};
/** The Charts workspace's study colours (EMA 21 takes its EMA 20's, the SMAs its EMA 50's and 200's), thin and faded so
 * the plan's lines stay the boldest thing after price. */
const STUDY: Record<StudyKey, { name: string; color: string }> = {
  vwap: { name: "VWAP", color: "#f5e6a1" }, ema9: { name: "EMA 9", color: "#67d5eb" }, ema21: { name: "EMA 21", color: "#f4c66b" },
  sma50: { name: "SMA 50", color: "#b494f5" }, sma200: { name: "SMA 200", color: "#ee86bd" }, volume: { name: "Vol", color: "#8d8d96" },
  levels: { name: "Prev close · PM high/low", color: "#9a9aa3" }, news: { name: "News", color: "#7dd3fc" },
};
const FADE = "99";
const STUDY_STORE = "desk.chart.studies.v1";
type Shown = Partial<Record<StudyKey, boolean>>;
type Choices = Partial<Record<DeskTimeframe, Shown>>;
const readChoices = (): Choices => {
  try { const saved = JSON.parse(window.localStorage.getItem(STUDY_STORE) ?? "{}"); return saved && typeof saved === "object" ? saved : {}; } catch { return {}; }
};
const saveChoices = (choices: Choices) => { try { window.localStorage.setItem(STUDY_STORE, JSON.stringify(choices)); } catch { /* this visit only */ } };
const isOn = (choices: Choices, timeframe: DeskTimeframe, key: StudyKey) => choices[timeframe]?.[key] ?? true;
const REFERENCE_TITLE = { prev_close: "Prev close", pm_high: "PM high", pm_low: "PM low" } as const;
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const KIND_WORD: Record<DeskChartMark["kind"], string> = { fill: "Fill", ping: "Ping", radar: "Radar" };
/** A plan line further than this from the last price does not stretch the price scale; the row above still names it. */
const LEVEL_REACH = 0.1;
/** Candles of room kept past the last one; more when the time stop is ahead (up to ``STOP_ROOM``). */
const RIGHT_ROOM = 4;
const STOP_ROOM = 120;
/** Daily candles of room for a report ahead (about two weeks of sessions). */
const REPORT_ROOM = 10;
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
/** "3:30 PM" today, "Nov 12 3:30 PM" another day. */
const stopWhen = (seconds: number) => nyWhen(seconds).replace(/ ET$/, "");
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

type Bar = DeskChartData["bars"][number];

/** The candle holding ``at`` (its start at or before, within one step), or undefined. */
function candleOf(bars: Bar[], step: number, at: number): Bar | undefined {
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time <= at) low = mid + 1; else high = mid; }
  const bar = bars[low - 1];
  return bar && at < bar.time + step ? bar : undefined;
}

/** The candle a mark sits on: the one holding its time, else the nearest one (a thin pre-market minute with no
 * trade, an extended-hours fill on the regular-session 15m candles, a pre-market fill on a daily candle stamped at the
 * open, a fill in the minute still forming). A mark before or after the candles shown by more than a step is left off. */
export function markCandle(bars: Bar[], step: number, at: number): Bar | undefined {
  if (!bars.length || at < bars[0].time - step || at >= bars[bars.length - 1].time + 2 * step) return undefined;
  const holding = candleOf(bars, step, at);
  if (holding) return holding;
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time <= at) low = mid + 1; else high = mid; }
  const before = bars[low - 1], after = bars[low];
  if (!before) return after;
  if (!after) return before;
  return at - (before.time + step) <= after.time - at ? before : after;
}

/** Each mark on its candle, keyed by the candle's time. A mark off the candles shown is left out. */
export function marksByCandle(data: DeskChartData): Map<number, DeskChartMark[]> {
  const out = new Map<number, DeskChartMark[]>();
  for (const mark of data.marks) {
    const bar = markCandle(data.bars, data.step, mark.at);
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
        if (mark.side === null) { out.push({ id, time: at, position: "belowBar", shape: "circle", color: COLOR.fill, size: 0.8 }); return; }
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
      const label = `Time stop ${stopWhen(stop.at)}`;
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
  chart: IChartApi; candles: ISeriesApi<"Candlestick">; volume: ISeriesApi<"Histogram"> | null; markers: ISeriesMarkersPluginApi<Time>;
  shade: SessionShade; stop: TimeStopLine; lines: IPriceLine[]; studies: Record<LineKey, ISeriesApi<"Line">>;
};
type Hover = { bar: Bar; marks: DeskChartMark[]; x: number; width: number };

/** Pixels kept clear at each end of the default view: more than half a time label ("10:00 AM"), so the first and last
 * labels on the axis draw whole at any width instead of being cut at the edge. */
const EDGE_PX = 30;
/** The thinnest candle by default: a whole 2m day fits a desktop; zoom in for candles. */
const MIN_BAR_SPACING = 0.5;

/** The default view: every candle, plus room on the right for a time stop still ahead, and ``EDGE_PX`` clear at both
 * ends. Reports where the first and last candles sit (``data-edges``) for the browser test. */
function defaultRange(parts: Parts, data: DeskChartData, host: HTMLElement | null) {
  const last = data.bars.length - 1;
  const ahead = data.time_stop && data.timeframe !== "1D" ? Math.ceil((data.time_stop.at - data.bars[last].time) / data.step) : 0;
  // On daily candles a report in the next couple of weeks is kept in view, so its chip sits on the axis.
  const report = data.timeframe === "1D" && data.events?.earnings?.next ? eventLogical(data, data.events.earnings.next.date) : null;
  const toReport = report !== null && report - last <= REPORT_ROOM ? report - last + 2 : 0;
  const room = Math.max(ahead > 0 ? Math.min(ahead, STOP_ROOM) + RIGHT_ROOM : RIGHT_ROOM, toReport);
  parts.chart.priceScale("right").applyOptions({ autoScale: true });
  const scale = parts.chart.timeScale();
  const width = scale.width();
  // Bars that make EDGE_PX at the spacing the whole view will have (a little more than needed, never less). A whole
  // 2m day on a phone needs candles thinner than the usual minimum to fit between the margins: allow just that.
  const edge = width > 4 * EDGE_PX ? EDGE_PX * (last + 1 + room) / (width - 2 * EDGE_PX) : 1;
  if (width > 4 * EDGE_PX)
    parts.chart.applyOptions({ timeScale: { minBarSpacing: Math.max(0.1, Math.min(MIN_BAR_SPACING, (width - 2 * EDGE_PX) / (last + 1 + room + 2 * edge))) } });
  scale.setVisibleLogicalRange({ from: -Math.max(1, edge), to: last + Math.max(room, edge) });
  if (host) requestAnimationFrame(() => { // once the chart has applied the range
    const first = scale.logicalToCoordinate(0 as Logical), end = scale.logicalToCoordinate(last as Logical);
    if (first !== null && end !== null) host.dataset.edges = `${Math.round(first)},${Math.round(scale.width() - end)}`;
  });
}

/** ``at``: when the read was asked for (ms), so a local alert change made after it is not undone by its answer. */
type Read = { key: string; at?: number; data: DeskChartData } | { key: string; at?: number; error: string };
const good = (read: Read) => "data" in read && read.data.state === "ok" && read.data.bars.length > 0;
/** What the chart shows now, for the crosshair and the primitives; ``applied`` is the key last painted. */
type Painted = { shown: DeskChartData | null; byCandle: Map<number, DeskChartMark[]>; applied: string | null };

/** One study's points: a gap where it has no value, and none drawn across a session's end (VWAP starts again each day). */
function studyPoints(bars: Bar[], values: (number | null)[] | undefined, key: LineKey): (LineData<Time> | WhitespaceData<Time>)[] {
  const day = (time: number) => Math.floor((time - 4 * 3600) / 86400);  // a New York date for any time 04:00–20:00 ET
  return bars.map((bar, i) => {
    const value = values?.[i];
    if (value == null) return { time: bar.time as UTCTimestamp };
    const next = bars[i + 1];
    const cut = key === "vwap" && next && (values?.[i + 1] == null || day(next.time) !== day(bar.time));
    return { time: bar.time as UTCTimestamp, value, ...(cut ? { color: "transparent" } : {}) };
  });
}

/** Volume in its own pane under the price, made when shown and removed when not. */
function setVolume(current: Parts, data: DeskChartData | null, on: boolean) {
  if (!on || !data) {
    if (current.volume) { current.chart.removeSeries(current.volume); current.volume = null; }
    if (current.chart.panes().length > 1) current.chart.removePane(1);
    return;
  }
  if (!current.volume) {
    current.volume = current.chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
    current.volume.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } });
    const panes = current.chart.panes();
    panes[0].setStretchFactor(4);
    panes[1]?.setStretchFactor(1);
  }
  current.volume.setData(data.bars.map(b => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "#2bc9a466" : "#ee617a66" })));
}

/** The read's candles, lines and marks onto the chart, with the studies ``shown``; the view resets only for a new symbol
 * or timeframe. ``alerts`` (the symbol's other armed alerts) and ``pick`` (the level menu's price) are thin lines. */
function paint(current: Parts, read: Read, state: Painted, host: HTMLElement | null, shown: (key: StudyKey) => boolean,
  alerts: DeskChartAlert[], pick: number | null) {
  const fresh = read.key !== state.applied;
  const next = "data" in read && read.data.state === "ok" && read.data.bars.length ? read.data : null;
  state.shown = next;
  state.byCandle = next ? marksByCandle(next) : new Map();
  state.applied = next ? read.key : null;  // after an empty read, the next good one opens on the default view
  for (const line of current.lines) current.candles.removePriceLine(line);
  current.lines = [];
  const offers = (key: StudyKey) => !!next && STUDIES[next.timeframe].includes(key) && shown(key);
  for (const key of LINES) {
    current.studies[key].setData(next && offers(key) ? studyPoints(next.bars, next.studies?.[key as DeskStudySeries], key) : []);
  }
  setVolume(current, next, offers("volume"));
  if (!next) {
    current.candles.setData([]);
    current.markers.setMarkers([]);
    current.stop.set(null);
    return;
  }
  current.candles.setData(next.bars.map(b => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
  // Faint context first, then the alerts, then the plan's lines on top: the boldest thing on the chart after price.
  if (offers("levels")) {
    current.lines.push(...(next.reference ?? []).map(line => current.candles.createPriceLine({
      price: line.price, color: COLOR.reference, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: REFERENCE_TITLE[line.key],
    })));
  }
  current.lines.push(...alerts.map(alert => current.candles.createPriceLine({
    price: alert.price, color: COLOR.alert, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: false, title: "Alert",
  })));
  current.lines.push(...next.levels.map(level => current.candles.createPriceLine({
    price: level.price, color: COLOR[level.role], lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: level.label,
  })));
  if (pick !== null) {
    current.lines.push(current.candles.createPriceLine({ price: pick, color: COLOR.pick, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" }));
  }
  current.markers.setMarkers(seriesMarkers(state.byCandle));
  current.shade.update();
  current.stop.set(next.timeframe === "1D" ? null : next.time_stop);  // a clock time has no place on daily candles
  // Clock ticks on the intraday candles, dates on the daily ones.
  current.chart.applyOptions({ timeScale: { timeVisible: next.timeframe !== "1D" } });
  if (fresh) defaultRange(current, next, host);
}

/** What the level menu's Plan and Ask hand to the desk: a desk link to follow in place (the plan form, prefilled), and
 * a question's context line for the copilot, scoped to the symbol (its own conversation when it has one). */
export type DeskChartActions = { go(href: string): void; ask(symbol: string, text: string): void };

type Menu = { price: number; x: number; y: number; plan: boolean };
type Status = { text: string; tone: "ok" | "error"; undo?: () => void } | null;
type Press = { x: number; y: number; price: number; axis: boolean; clientX: number; clientY: number; at: number; timer: number | null };

const cents = (value: number) => Math.round(value * 100) / 100;
const MENU_W = 240;
const LONG_PRESS_MS = 500;
const SLOP_PX = 8;
const DESK_LABEL = "From the desk";

/** The alerts in an alerts listing that this chart draws: the symbol's armed ones other than the plan's own lines. */
export function chartAlerts(listing: AlertsPayload, symbol: string, planIds: Set<string>): DeskChartAlert[] {
  return listing.alerts.filter(a => a.symbol === symbol && a.state === "active" && !planIds.has(a.id))
    .sort((a, b) => a.price - b.price)
    .map(a => ({ id: a.id, price: a.price, text: alertText(a, a.price), label: a.label || null, removable: !a.plan_role,
      condition: a.condition, interval: a.interval, session: a.session }));
}

const lastText = (last: number | null) => last === null ? "" : `, last ${last.toFixed(2)}`;

/** "Plan from here": the copilot's plan form for ``symbol`` with ``level`` as the entry trigger or the invalidation,
 * the owner's choice, in its unsent message (and, for an invalidation, as the drawn plan the card compares with, a
 * long below the price and a short above it). Nothing is saved or sent. */
export function planFromHere(symbol: string, timeframe: DeskTimeframe, last: number | null, level: number, role: "entry" | "invalidation"): string {
  const head = `Plan a trade: ${symbol} from the desk's ${timeframe} chart${lastText(last)}.`;
  if (role === "entry") {
    const text = `${head} Entry trigger ${level.toFixed(2)} (a level I picked on the chart). Draft the invalidation, a target if there is an honest one, and the plan around it; argue if it is wrong.`;
    return copilotLabHref(symbol, text.slice(0, CONTEXT_MAX), { kind: "chart", ref: null });
  }
  const side: DrawnPlan["side"] = last !== null && level > last ? "short" : "long";
  const text = `${head} Invalidation ${level.toFixed(2)} (a level I picked on the chart), a ${side}. Draft the entry trigger, a target if there is an honest one, and the plan around it; argue if it is wrong.`;
  return copilotLabHref(symbol, text.slice(0, CONTEXT_MAX), { kind: "chart", ref: null }, { side, trigger: null, invalidation: cents(level) });
}

/** The context line for "Ask the copilot about this level": the level, where price is against it and when. */
export function askAboutLevel(symbol: string, timeframe: DeskTimeframe, level: number, data: DeskChartData | null): string {
  const reading = data?.reading;
  const where = reading ? ` Last ${reading.last.toFixed(2)} at ${nyWhen(reading.at, reading.daily)}, ${Math.abs((reading.last - level) / level * 100).toFixed(1)}% ${reading.last >= level ? "above" : "below"} it.` : "";
  return `${symbol} ${level.toFixed(2)}, a level I picked on the desk's ${timeframe} chart.${where}`.slice(0, CONTEXT_MAX);
}

/**
 * The reading line under the symbol: the newest price, the day's change against the previous close, the distance from
 * VWAP and from the plan's invalidation, and volume against usual for the time of day, with their as-of. A part with
 * nothing behind it is left out. ``fallback`` is the book's change today when the read has no previous close. The line
 * holds what it last showed for ``symbol`` rather than blank or step back (``heldReading``).
 */
export function ReadingLine({ symbol, data, fallback = null, live = null }: {
  symbol: string; data: DeskChartData | null; fallback?: { pct: number; at: number } | null;
  /** The desk's live price (``lib/deskTicks.ts``): newer than the chart's last minute, it is the reading's price and time. */
  live?: { last: number; at: number; stale: boolean } | null;
}) {
  const read = data?.state === "ok" && data.symbol === symbol ? data.reading : null;
  const fresh = !!(read && live && !read.daily && live.at > read.at);
  const next = read ? {
    reading: fresh ? { ...read, last: live!.last, at: live!.at } : read,
    invalidation: data?.levels.find(level => level.role === "invalidation")?.price ?? null, ticked: fresh,
  } : null;
  const held = heldReading(symbol, next);
  if (!held) return <p data-testid="desk-reading" className="h-4" />;
  const { reading, invalidation } = held;
  const ticked = held.ticked && !!live;
  const { last, at, daily } = reading;
  // VWAP and RVol are the regular session's: after the close or before the open their time is not the price's.
  const sessionAt = reading.vwap_at !== null && !daily && Math.abs(reading.vwap_at - at) > 90 ? reading.vwap_at : null;
  const change = reading.prev_close ? (last / reading.prev_close - 1) * 100 : null;
  const parts: { key: string; text: string; tone?: number; title?: string }[] = [];
  if (change !== null) parts.push({ key: "change", text: `${signedPct(change, 2)} vs prev close`, tone: change, title: `Previous close ${price(reading.prev_close!)}` });
  else if (fallback) parts.push({ key: "change", text: `${signedPct(fallback.pct, 2)} today (book, ${nyWhen(fallback.at)})`, tone: fallback.pct });
  if (reading.vwap) {
    const away = (last / reading.vwap - 1) * 100;
    parts.push({ key: "vwap", text: `${signedPct(away, 2)} vs VWAP ${price(reading.vwap)}` });
  }
  if (invalidation) {
    const away = (last - invalidation) / last * 100;
    parts.push({ key: "invalidation", text: `${Math.abs(away).toFixed(1)}% ${away >= 0 ? "above" : "below"} invalidation ${price(invalidation)}` });
  }
  if (reading.rvol) parts.push({ key: "rvol", text: `vol ${reading.rvol.toFixed(1)}× usual` });
  return (
    // One line that scrolls sideways on a phone; two at most beside the book, so a new minute rarely moves the chart.
    <p data-testid="desk-reading" className="overflow-x-auto whitespace-nowrap text-xs leading-4 tabular-nums text-muted-foreground [scrollbar-width:none] sm:min-h-8 sm:whitespace-normal">
      <span data-testid="desk-reading-last" className={cn("text-foreground", ticked && live!.stale && "opacity-50")}><Flash value={last}>{price(last)}</Flash></span>
      {parts.map(part => (
        <span key={part.key} data-part={part.key} title={part.title}>
          {" · "}<span className={part.tone === undefined || part.tone === 0 ? undefined : part.tone > 0 ? "text-emerald-300" : "text-rose-300"}>{part.text}</span>
        </span>
      ))}
      <span> · as of {nyWhen(at, daily)}{sessionAt !== null ? ` (VWAP${reading.rvol ? ", vol" : ""} ${nyWhen(sessionAt)})` : ""}</span>
    </p>
  );
}

/** The News toggle's tooltip: why there are none, or from when the markers are complete. */
const newsTitle = (news: DeskChartNews): string =>
  news.state !== "ok" ? news.reason ?? "Hide News"
    : news.complete_from ? `Hide News. Only the newest headlines were read: any before ${newsWhen(news.complete_from, news.as_of)} are not marked.` : "Hide News";

/** The chart for ``id`` (a thread, ``symbol:X`` or ``market``) on ``timeframe``. ``refreshKey`` reads it again. ``onRead``
 * hears each read shown (the reading line); ``actions`` lets the level menu's Plan and Ask reach the desk. */
export function DeskChart({ id, timeframe, refreshKey = 0, label, onRead, actions, live: now = null }: {
  id: string; timeframe: DeskTimeframe; refreshKey?: number; label: string; onRead?(data: DeskChartData | null): void; actions?: DeskChartActions;
  /** The desk's live price: it moves the last candle (and the price line) between the minute reads. */
  live?: { last: number; at: number; stale: boolean } | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const parts = useRef<Parts | null>(null);
  const painted = useRef<Painted>({ shown: null, byCandle: new Map(), applied: null });
  const latest = useRef<Read | null>(null);
  const [read, setRead] = useState<Read | null>(null);
  const [tick, setTick] = useState(0);
  const [hover, setHover] = useState<Hover | null>(null);
  const [chartApi, setChartApi] = useState<IChartApi | null>(null);  // for the event chips over the chart
  const [choices, setChoices] = useState<Choices>({});
  const [menu, setMenu] = useState<Menu | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [listed, setListed] = useState<{ key: string; at: number; alerts: DeskChartAlert[] } | null>(null);
  const press = useRef<Press | null>(null);
  const menuBox = useRef<HTMLDivElement>(null);
  const key = `${id}|${timeframe}`;
  useEffect(() => { setChoices(readChoices()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration

  // One chart for the component's life; a new symbol or timeframe swaps the data in place, so switching never blanks.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e0e10" }, textColor: "#8d8d96", fontSize: 10, panes: { separatorColor: "#27272a", separatorHoverColor: "#3a3a40" } },
      grid: { vertLines: { color: "#1b1b1e" }, horzLines: { color: "#1b1b1e" } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" }, horzLine: { color: "#77777f", labelBackgroundColor: "#3a3a40" } },
      rightPriceScale: { borderColor: "#27272a", scaleMargins: { top: 0.1, bottom: 0.08 }, entireTextOnly: true },
      timeScale: { borderColor: "#27272a", secondsVisible: false, rightOffset: RIGHT_ROOM, minBarSpacing: MIN_BAR_SPACING,
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
    // Thin, faded and outside the price scale's fit: a far-off average never squeezes the candles.
    const studies = Object.fromEntries(LINES.map(name => [name, chart.addSeries(LineSeries, {
      color: STUDY[name].color + FADE, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      autoscaleInfoProvider: () => null,
    })])) as Record<LineKey, ISeriesApi<"Line">>;
    const markers = createSeriesMarkers(candles, []);
    const shade = new SessionShade(() => (painted.current.shown?.bars ?? []) as unknown as ChartBar[]);
    candles.attachPrimitive(shade);
    const stop = new TimeStopLine(() => painted.current.shown?.bars ?? [], () => painted.current.shown?.step ?? 60);
    candles.attachPrimitive(stop);
    parts.current = { chart, candles, volume: null, markers, shade, stop, lines: [], studies };
    setChartApi(chart);
    painted.current.applied = null;  // a new chart starts from the default view
    if (latest.current) paint(parts.current, latest.current, painted.current, host.current, () => true, [], null);
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
    return () => { parts.current = null; setChartApi(null); chart.remove(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // A refresh that fails or comes back empty keeps the chart already shown for this symbol and timeframe.
    const settle = (next: Read) => setRead(prev => !good(next) && prev && prev.key === next.key && good(prev) ? prev : next);
    const at = Date.now();
    getDeskChart(id, timeframe, controller.signal)
      .then(data => { if (!controller.signal.aborted) settle({ key, at, data }); })
      .catch(failure => { if (!controller.signal.aborted) settle({ key, at, error: failure instanceof Error ? failure.message : "Unavailable right now." }); });
    return () => controller.abort();
  }, [id, timeframe, key, refreshKey, tick]);

  const data = read && read.key === key && good(read) && "data" in read ? read.data : null;
  const live = !!data?.live;
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [live, key]);
  useEffect(() => { onRead?.(data); }, [data, onRead]);
  // A new read is the server's word on the alerts; another symbol or timeframe closes the menu and its message.
  // (A read asked for before the change answers with the alerts as they were: the local list stands until a later one.)
  useEffect(() => { setListed(prev => prev && read?.at !== undefined && read.at < prev.at ? prev : null); }, [read]); // eslint-disable-line react-hooks/set-state-in-effect -- the read replaces the local list
  useEffect(() => { setMenu(null); setStatus(null); }, [key]); // eslint-disable-line react-hooks/set-state-in-effect -- a new chart starts clean

  const alerts = useMemo(() => listed && listed.key === key ? listed.alerts : data?.alerts ?? [], [listed, key, data]);
  const shownKey = STUDIES[timeframe].map(k => isOn(choices, timeframe, k) ? 1 : 0).join("");
  const pick = menu?.price ?? null;
  const news = useChartNews(id, timeframe, data, isOn(choices, timeframe, "news"));
  const headlines = news?.state === "ok" ? news.groups.reduce((n, g) => n + g.count, 0) : 0;
  // The read onto the chart (and onto a chart built again, e.g. after a hot reload, from the last read), with the
  // studies chosen for its timeframe, the alerts and the level the menu is open on.
  useEffect(() => {
    latest.current = read;
    const tf = read && "data" in read ? read.data.timeframe : timeframe;
    if (parts.current && read) paint(parts.current, read, painted.current, host.current, k => isOn(choices, tf, k), alerts, pick);
  }, [read, choices, alerts, pick, shownKey, timeframe]);

  // The live price onto the candle still forming: its close, and its high or low when it goes past them. A price after
  // that candle waits for the next read (a new candle needs its volume and studies); a stale one is left off.
  const forming = useRef<{ key: string; time: number; high: number; low: number } | null>(null);
  useEffect(() => {
    const current = parts.current, shown = read && read.key === key && "data" in read ? read.data : null;
    if (!current || !shown || !now || now.stale || shown.timeframe === "1D" || !shown.bars.length) return;
    const bar = shown.bars[shown.bars.length - 1];
    if (now.at < bar.time || now.at >= bar.time + shown.step) return;
    const held = forming.current && forming.current.key === key && forming.current.time === bar.time ? forming.current : { key, time: bar.time, high: bar.high, low: bar.low };
    forming.current = { ...held, high: Math.max(held.high, bar.high, now.last), low: Math.min(held.low, bar.low, now.last) };
    current.candles.update({ time: bar.time as UTCTimestamp, open: bar.open, high: forming.current.high, low: forming.current.low, close: now.last });
  }, [now, read, key, choices, alerts, pick]);

  const toggle = (study: StudyKey) => setChoices(prev => {
    const next = { ...prev, [timeframe]: { ...prev[timeframe], [study]: !isOn(prev, timeframe, study) } };
    saveChoices(next);
    return next;
  });

  // ---- the level menu: a tap on the price scale, a long-press or a right-click on the candles
  const at = useCallback((clientX: number, clientY: number): Omit<Press, "clientX" | "clientY" | "at" | "timer"> | null => {
    const current = parts.current, element = host.current;
    if (!current || !element || !painted.current.shown) return null;
    const box = element.getBoundingClientRect();
    const x = clientX - box.left, y = clientY - box.top;
    const main = current.chart.panes()[0]?.getHeight() ?? 0;
    if (y < 0 || y > main || x < 0) return null;
    const value = current.candles.coordinateToPrice(y);
    if (value === null || !Number.isFinite(value) || value <= 0) return null;
    return { x, y, price: cents(value), axis: x > current.chart.timeScale().width() };
  }, []);
  const openMenu = useCallback((spot: { x: number; y: number; price: number; axis: boolean }) => {
    const width = host.current?.clientWidth ?? 360;
    const pane = parts.current?.chart.timeScale().width() ?? width;
    const x = spot.axis ? pane - MENU_W - 6 : spot.x > width / 2 ? spot.x - MENU_W - 12 : spot.x + 12;
    const height = host.current?.clientHeight ?? 320;
    setMenu({ price: spot.price, x: Math.max(4, Math.min(width - MENU_W - 4, x)), y: Math.max(4, Math.min(spot.y - 20, height - 190)), plan: false });
    setStatus(null);
  }, []);
  const clearPress = () => { if (press.current?.timer) window.clearTimeout(press.current.timer); press.current = null; };
  const onPointerDown = (event: ReactPointerEvent) => {
    clearPress();
    // Only a first finger or the mouse: a second finger is a pinch.
    if (!event.isPrimary || event.button !== 0 || (menuBox.current && menuBox.current.contains(event.target as Node))) return;
    if ((event.target as HTMLElement).closest?.('[data-testid="desk-chart-event"], [data-desk-news]')) return;  // an event chip or a headline: its own tooltip
    const spot = at(event.clientX, event.clientY);
    if (!spot) return;
    press.current = { ...spot, clientX: event.clientX, clientY: event.clientY, at: Date.now(),
      timer: spot.axis ? null : window.setTimeout(() => { press.current = null; openMenu(spot); }, LONG_PRESS_MS) };
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    const held = press.current;
    if (held && Math.hypot(event.clientX - held.clientX, event.clientY - held.clientY) > SLOP_PX) clearPress();
  };
  const onPointerUp = () => {
    const held = press.current;
    if (held?.axis && Date.now() - held.at < 600) openMenu(held);
    clearPress();
  };
  useEffect(() => {
    if (!menu) return;
    const away = (event: PointerEvent) => { if (menuBox.current && !menuBox.current.contains(event.target as Node)) setMenu(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setMenu(null); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", escape); };
  }, [menu]);
  useEffect(() => () => clearPress(), []);

  const planIds = useMemo(() => new Set((data?.levels ?? []).map(level => level.id).filter((x): x is string => !!x)), [data]);
  const lastPrice = data ? data.reading?.last ?? data.bars[data.bars.length - 1].close : null;
  const show = useCallback((listing: AlertsPayload, symbol: string) => setListed({ key, at: Date.now(), alerts: chartAlerts(listing, symbol, planIds) }), [key, planIds]);
  const fail = (failure: unknown) => setStatus({ text: failure instanceof Error ? failure.message : "That did not work. Try again.", tone: "error" });
  const undoCreate = (symbol: string, alertId: string) => {
    setStatus({ text: "Removing the alert…", tone: "ok" });
    removeAlert(alertId).then(listing => { show(listing, symbol); setStatus({ text: "Alert removed.", tone: "ok" }); }).catch(fail);
  };
  const alertHere = (level: number) => {
    if (!data || lastPrice === null) return;
    const symbol = data.symbol;
    setMenu(null);
    setStatus({ text: "Setting the alert…", tone: "ok" });
    createAlert({ symbol, price: level, reference: lastPrice, condition: "crosses", interval: null, session: "regular", source_kind: "level", source_id: "desk", label: DESK_LABEL })
      .then(listing => {
        show(listing, symbol);
        const made = listing.alerts.filter(a => a.symbol === symbol && a.state === "active" && a.source_id === "desk" && Math.abs(a.price - level) < 1e-6)
          .sort((a, b) => b.armed_at - a.armed_at)[0];
        const what = made ? alertText(made, made.price).toLowerCase() : `crosses ${level.toFixed(2)}`;
        setStatus({ text: `Alert set: ${symbol} ${what}, regular hours.${listing.phone ? "" : " Phone alerts are not set up on this server."}`, tone: "ok",
          undo: made ? () => undoCreate(symbol, made.id) : undefined });
      }).catch(fail);
  };
  const removeOne = (alert: DeskChartAlert) => {
    if (!data || lastPrice === null) return;
    const symbol = data.symbol, reference = lastPrice;
    setStatus({ text: "Removing the alert…", tone: "ok" });
    removeAlert(alert.id).then(listing => {
      show(listing, symbol);
      setStatus({ text: `Alert removed: ${alert.text}.`, tone: "ok", undo: () => {
        setStatus({ text: "Setting it again…", tone: "ok" });
        createAlert({ symbol, price: alert.price, reference, condition: alert.condition, interval: alert.condition === "closes_beyond" ? alert.interval as Interval : null,
          session: alert.session, source_kind: "level", source_id: "desk", label: alert.label ?? DESK_LABEL })
          .then(again => {
            show(again, symbol);
            // Which side it waits on is judged again from the price now: say what was armed, not what was removed.
            const made = again.alerts.filter(a => a.symbol === symbol && a.state === "active" && Math.abs(a.price - alert.price) < 1e-6)
              .sort((a, b) => b.armed_at - a.armed_at)[0];
            setStatus({ text: `Alert set again: ${made ? alertText(made, made.price) : alert.text}.`, tone: "ok" });
          }).catch(fail);
      } });
    }).catch(fail);
  };
  const planHere = (level: number, role: "entry" | "invalidation") => {
    if (!data) return;
    setMenu(null);
    actions?.go(planFromHere(data.symbol, data.timeframe, lastPrice, level, role));
  };
  const askHere = (level: number) => {
    if (!data) return;
    setMenu(null);
    actions?.ask(data.symbol, askAboutLevel(data.symbol, data.timeframe, level, data));
  };

  const reset = () => { if (parts.current && painted.current.shown) defaultRange(parts.current, painted.current.shown, host.current); };
  const switching = !!read && read.key !== key;
  const unavailable = read && read.key === key ? ("error" in read ? read.error : read.data.state !== "ok" || !read.data.bars.length ? (read.data.reason ?? "No bars came back.") : null) : null;
  const daily = data?.timeframe === "1D";
  const byCandle = useMemo(() => data ? marksByCandle(data) : new Map<number, DeskChartMark[]>(), [data]);
  const allMarks = useMemo(() => [...byCandle.values()].flat(), [byCandle]);
  const index = useMemo(() => new Map((data?.bars ?? []).map((bar, i) => [bar.time, i])), [data]);
  const lastBar = data ? data.bars[data.bars.length - 1] : null;
  const readout = hover?.bar ?? lastBar;
  const at_i = readout ? index.get(readout.time) ?? null : null;
  const offScale = useMemo(() => {
    if (!data || !lastBar) return new Set<string>();
    return new Set(data.levels.filter(l => Math.abs(l.price - lastBar.close) / lastBar.close > LEVEL_REACH).map(l => l.role));
  }, [data, lastBar]);
  const value = (study: StudyKey): string => {
    if (!data || at_i === null) return "";
    if (study === "levels") return "";
    if (study === "news") return headlines ? String(headlines) : "";
    if (study === "volume") {
      const rvol = data.studies?.rvol?.[at_i];
      const vol = compact.format(data.bars[at_i].volume);
      return rvol == null ? vol : `${vol} · ${rvol.toFixed(1)}×${daily ? " 30d" : ""}`;
    }
    const found = data.studies?.[study as DeskStudySeries]?.[at_i];
    return found == null ? "—" : price(found);
  };
  const drawn = data ? LINES.filter(k => STUDIES[data.timeframe].includes(k) && isOn(choices, data.timeframe, k) && data.studies?.[k]?.some(v => v != null)) : [];

  return (
    <div className="space-y-1.5">
      <div data-testid="desk-chart-lines" className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
        {data?.levels.map(level => (
          <span key={level.role} style={{ color: COLOR[level.role] }}>{level.label}{offScale.has(level.role) ? " (off the chart)" : ""}</span>
        ))}
        {data && !data.levels.length && id !== "market" && <span>no plan lines saved</span>}
        {data?.time_stop && <span style={{ color: COLOR.stop }}>Time stop {stopWhen(data.time_stop.at)}</span>}
        {data && earningsHeader(data.events, data.as_of) && <span data-testid="desk-chart-earnings" className="text-sky-200">{earningsHeader(data.events, data.as_of)}</span>}
        <button type="button" onClick={reset} disabled={!data}
          className="ml-auto min-h-11 rounded border border-transparent px-2 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0 sm:py-0.5">
          Reset
        </button>
      </div>
      {data && alerts.length > 0 && (
        <div data-testid="desk-chart-alerts" aria-label="Alerts on this symbol" className="flex flex-wrap items-center gap-1 text-xs tabular-nums">
          {alerts.map(alert => alert.removable ? (
            <button key={alert.id} type="button" onClick={() => removeOne(alert)} aria-label={`Remove alert: ${alert.text}`}
              title={`${alert.text}${alert.label ? ` · ${alert.label}` : ""}. Remove it (you can undo).`}
              className="inline-flex min-h-11 items-center gap-1 rounded border border-amber-300/30 px-1.5 text-amber-200/90 hover:border-amber-300/60 sm:min-h-0 sm:py-0.5">
              <span aria-hidden>🔔</span>{alert.text}<span aria-hidden className="text-muted-foreground">×</span>
            </button>
          ) : (
            <span key={alert.id} title={`${alert.label ?? "A plan's alert"}: remove it from its plan.`}
              className="inline-flex items-center gap-1 rounded border border-transparent px-1.5 text-amber-200/70 sm:py-0.5">
              <span aria-hidden>🔔</span>{alert.text}
            </span>
          ))}
        </div>
      )}
      {status && (
        <p role="status" data-testid="desk-chart-status" className={`flex flex-wrap items-center gap-x-2 text-xs ${status.tone === "error" ? "text-rose-300" : "text-foreground"}`}>
          <span>{status.text}</span>
          {status.undo && <button type="button" onClick={status.undo} className="min-h-11 rounded px-1 text-xs text-muted-foreground underline hover:text-foreground sm:min-h-0">Undo</button>}
        </p>
      )}
      {/* One line that never wraps (it scrolls sideways on a phone), so values changing under the pointer never move the chart. */}
      <div role="group" aria-label="Studies" data-testid="desk-chart-studies"
        className="flex items-center gap-0.5 overflow-x-auto whitespace-nowrap text-xs tabular-nums [scrollbar-width:none]">
        {STUDIES[timeframe].map(study => {
          const on = isOn(choices, timeframe, study);
          return (
            <button key={study} type="button" aria-pressed={on} onClick={() => toggle(study)} data-testid={`desk-study-${study}`}
              title={study === "news" && on && news ? newsTitle(news) : `${on ? "Hide" : "Show"} ${STUDY[study].name}`}
              className={`min-h-11 shrink-0 rounded px-1.5 hover:bg-secondary sm:min-h-0 sm:py-0.5 ${on ? "" : "text-muted-foreground/60 line-through"}`}
              style={on ? { color: STUDY[study].color } : undefined}>
              {STUDY[study].name}{on && value(study) ? <span className="text-foreground/80"> {value(study)}</span> : null}
            </button>
          );
        })}
      </div>
      {/* One line that never wraps, so moving the pointer never moves the chart. */}
      <p className="h-4 truncate text-xs leading-4 tabular-nums text-muted-foreground" data-testid="desk-chart-readout">
        {readout && <>
          {nyWhen(readout.time, daily)} · O {price(readout.open)} H {price(readout.high)} L {price(readout.low)} C <span className="text-foreground">{price(readout.close)}</span>
          {readout.extended && <> · {readout.time < (data?.bars.find(b => !b.extended)?.time ?? Infinity) ? "pre-market" : "after hours"}</>}
        </>}
      </p>
      <div className="relative" onPointerDownCapture={onPointerDown} onPointerMoveCapture={onPointerMove} onPointerUpCapture={onPointerUp}
        onPointerCancelCapture={clearPress} onContextMenu={(event) => {
          if (menuBox.current?.contains(event.target as Node)) { event.preventDefault(); return; }
          if ((event.target as HTMLElement).closest?.("[data-desk-news]")) return;  // a headline keeps the browser's menu (copy link)
          const spot = at(event.clientX, event.clientY);
          if (!spot) return;  // the volume pane and the time axis keep the browser's own menu
          event.preventDefault();
          clearPress();
          openMenu(spot);
        }}>
        <div ref={host} role="img" aria-label={label} data-testid="desk-chart-canvas" data-timeframe={data?.timeframe ?? ""}
          data-bars={data?.bars.length ?? 0} data-marks={allMarks.length} data-studies={drawn.join(",")}
          data-volume={data && STUDIES[data.timeframe].includes("volume") && isOn(choices, data.timeframe, "volume") ? "on" : "off"}
          data-reference={data && isOn(choices, data.timeframe, "levels") && STUDIES[data.timeframe].includes("levels") ? (data.reference ?? []).length : 0}
          data-alerts={alerts.length} data-news={!isOn(choices, timeframe, "news") ? "off" : news?.state === "ok" ? news.groups.length : news?.state ?? "loading"}
          style={{ WebkitTouchCallout: "none", WebkitUserSelect: "none", userSelect: "none" }}
          className="h-[320px] w-full overflow-hidden rounded border sm:h-[420px]" />
        {!unavailable && !switching && <ChartEventMarks chart={chartApi} data={data} />}
        {!unavailable && !switching && data && <ChartNewsMarks chart={chartApi} news={news} symbol={data.symbol} timeframe={data.timeframe}
          onAsk={actions ? (text) => actions.ask(data.symbol, text) : undefined} />}
        {hover && hover.marks.length > 0 && !menu && (
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
        {menu && data && (
          <div ref={menuBox} role="menu" aria-label={`At ${price(menu.price)}`} data-testid="desk-level-menu"
            className="absolute z-20 rounded-md border bg-popover/95 p-1 text-xs shadow-lg"
            style={{ left: menu.x, top: menu.y, width: MENU_W }}>
            <p className="flex items-center justify-between px-2 py-1 tabular-nums text-muted-foreground">
              <span>{data.symbol} <span className="text-foreground">{price(menu.price)}</span>{lastPrice !== null ? ` · ${signedPct((menu.price / lastPrice - 1) * 100, 1)} from last` : ""}</span>
              <button type="button" aria-label="Close" onClick={() => setMenu(null)} className="min-h-11 min-w-11 rounded text-muted-foreground hover:text-foreground sm:min-h-6 sm:min-w-6">×</button>
            </p>
            {!menu.plan ? <>
              <button type="button" role="menuitem" onClick={() => alertHere(menu.price)}
                className="block min-h-11 w-full rounded px-2 text-left hover:bg-secondary sm:min-h-8">Alert when price crosses here</button>
              {actions && <button type="button" role="menuitem" onClick={() => setMenu({ ...menu, plan: true })}
                className="block min-h-11 w-full rounded px-2 text-left hover:bg-secondary sm:min-h-8">Plan from here…</button>}
              {actions && <button type="button" role="menuitem" onClick={() => askHere(menu.price)}
                className="block min-h-11 w-full rounded px-2 text-left hover:bg-secondary sm:min-h-8">Ask the copilot about this level</button>}
            </> : <>
              <p className="px-2 pb-1 text-muted-foreground">Plan from {price(menu.price)} as the… (nothing is saved)</p>
              <button type="button" role="menuitem" onClick={() => planHere(menu.price, "entry")}
                className="block min-h-11 w-full rounded px-2 text-left hover:bg-secondary sm:min-h-8">Entry trigger</button>
              <button type="button" role="menuitem" onClick={() => planHere(menu.price, "invalidation")}
                className="block min-h-11 w-full rounded px-2 text-left hover:bg-secondary sm:min-h-8">Invalidation</button>
            </>}
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
          {(data.reference ?? []).map(line => <li key={line.key}>{line.label}</li>)}
          {alerts.map(alert => <li key={alert.id}>Alert · {alert.text}</li>)}
          {allMarks.map((mark, i) => <li key={i}>{KIND_WORD[mark.kind]} · {mark.text} · {nyWhen(mark.at)}</li>)}
          {data.time_stop && <li>Time stop {stopWhen(data.time_stop.at)} · {data.time_stop.text}</li>}
          {chartEvents(data.events, nyDayOf(data.as_of)).map(e => <li key={e.key}>{e.lines.join(" ")}</li>)}
          {news?.state === "ok" && news.groups.flatMap(g => g.items.map(item => <li key={item.url}>Headline · {item.source} · {newsWhen(item.at, news.as_of)} · {item.headline}</li>))}
        </ul>
      )}
    </div>
  );
}
