import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time, UTCTimestamp } from "lightweight-charts";
import type { ChartBar, EarningsMark, FillLabels, FillMarker } from "./charts";
import { clusterNews } from "./newsMarkers";
import type { NewsCluster, NewsMark } from "./newsMarkers";

/**
 * The marks a chart draws on and around its candles: fills, report dates and news.
 *
 * The library's own markers (arrows, squares, text) cannot be made slim, cannot merge, and stack without limit,
 * so these are drawn here. Nothing is hidden by merging: a candle's fills are one chevron with a count, and the
 * hover or tap lists every one of them. The glyphs sit a few pixels off the wick (buys under the low, sells over
 * the high), thin enough that the candle stays the picture. News lives in a quiet strip along the bottom of the
 * pane, never on the candles. None of it takes part in the price scale's fit.
 */

const BUY = "#2bc9a4";
const SELL = "#ee617a";
const REPORT = "#a78bfa";
const NEWS = "#8da0b8";
const INK = "#10151e";
const FONT = "ui-sans-serif, system-ui, -apple-system, sans-serif";
/** Pixels between a candle's wick and the glyph's tip. */
const GAP = 5;
/** Pixels from the pane's bottom edge to the news strip's centre. */
const STRIP_FROM_BOTTOM = 8;
/** Markers closer than this many pixels join into one news marker. */
export const NEWS_CLUSTER_PX = 30;

/** One candle's fills on one side: the merged marker. */
export type FillGroup = { id: string; time: number; buy: boolean; fills: FillMarker[] };

/** Fills grouped by candle and side, oldest first (buys before sells on one candle). Every fill stays in its group. */
export function groupFills(fills: FillMarker[]): FillGroup[] {
  const groups = new Map<string, FillGroup>();
  for (const fill of fills) {
    const key = `${fill.time}:${fill.buy ? "buy" : "sell"}`;
    const held = groups.get(key);
    if (held) held.fills.push(fill); else groups.set(key, { id: key, time: fill.time, buy: fill.buy, fills: [fill] });
  }
  return [...groups.values()].sort((a, b) => a.time - b.time || Number(b.buy) - Number(a.buy));
}

/** The groups that get a text label: none, those on the newest candle with fills, or all. */
export function labelled(groups: FillGroup[], mode: FillLabels): Set<string> {
  if (mode === "off" || !groups.length) return new Set();
  if (mode === "all") return new Set(groups.map((group) => group.id));
  const newest = groups.reduce((latest, group) => Math.max(latest, group.time), 0);
  return new Set(groups.filter((group) => group.time === newest).map((group) => group.id));
}

/** The text a labelled group carries: its fill's own label, or the words its fills share ("buy to open") with several. */
export function groupLabel(group: FillGroup): string {
  if (group.fills.length === 1) return group.fills[0].label;
  const words = group.fills.map((fill) => fill.label.split(" ").slice(0, 3).join(" "));
  return words.every((text) => text === words[0]) ? words[0] : group.buy ? "buy" : "sell";
}

export type MarkHit = { kind: "fill"; group: FillGroup } | { kind: "news"; cluster: NewsCluster };
type PlacedFill = { group: FillGroup; x: number; tip: number; label: string | null; count: boolean; half: number };
type PlacedLabel = { text: string; x: number; y: number; width: number; buy: boolean };
type PlacedReport = { mark: EarningsMark; x: number; y: number };
type PlacedNews = { cluster: NewsCluster; x: number; y: number };
type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

export type MarkSet = { fills: FillGroup[]; labels: FillLabels; reports: EarningsMark[]; news: NewsMark[]; small: boolean };

export class MarkLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private set_: MarkSet = { fills: [], labels: "off", reports: [], news: [], small: false };
  private fills: PlacedFill[] = [];
  private texts: PlacedLabel[] = [];
  private reports: PlacedReport[] = [];
  private strip: PlacedNews[] = [];
  private paneHeight = 0;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "top", renderer: () => this.renderer }];

  constructor(private readonly bars: () => ChartBar[]) {}

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.chart = null; this.series = null; this.requestUpdate = null; }
  set(next: MarkSet) { this.set_ = next; this.updateAllViews(); this.requestUpdate?.(); }
  /** The candles or the scale changed: measure again on the next frame. */
  update() { this.requestUpdate?.(); }
  paneViews() { return this.views; }

  /** What is drawn, for hover, taps and tests. */
  drawnLabels() { return this.texts.map((text) => text.text); }
  clusters() { return this.strip.map(({ cluster, x, y }) => ({ time: cluster.time, last: cluster.last, count: cluster.articles.length, x, y })); }
  fillBoxes() { return this.fills.map(({ group, x, tip, half }) => ({ id: group.id, buy: group.buy, count: group.fills.length, x, y: tip, half })); }

  private sizes() {
    const { small } = this.set_;
    return { height: small ? 3.2 : 4.6, line: small ? 1.2 : 1.7, stripR: small ? 2.6 : 3.4, bigR: small ? 5 : 6.4 };
  }

  updateAllViews() {
    this.fills = []; this.texts = []; this.reports = []; this.strip = [];
    const { chart, series } = this;
    if (!chart || !series) return;
    const scale = chart.timeScale();
    const width = scale.width();
    const pane = chart.panes()[0];
    this.paneHeight = pane?.getHeight() ?? 0;
    const bars = this.bars();
    if (!bars.length || !width || !this.paneHeight) return;
    const byTime = (time: number) => {
      let low = 0, high = bars.length - 1;
      while (low <= high) { const mid = (low + high) >>> 1; if (bars[mid].time === time) return bars[mid]; if (bars[mid].time < time) low = mid + 1; else high = mid - 1; }
      return undefined;
    };
    const at = (time: number) => { const x = scale.timeToCoordinate(time as UTCTimestamp); return x !== null && x > -40 && x < width + 40 ? x : null; };
    const { small, labels } = this.set_;
    const { height } = this.sizes();
    const spacing = scale.options().barSpacing;
    const half = Math.max(2.4, Math.min(small ? 3.2 : 4.6, spacing * 0.5));
    const wantText = small ? new Set<string>() : labelled(this.set_.fills, labels);

    // Fills: a chevron per candle per side, off the wick.
    const placed: PlacedFill[] = [];
    const lowBuy = new Set<number>();
    for (const group of this.set_.fills) {
      const [x, bar] = [at(group.time), byTime(group.time)];
      if (x === null || !bar) continue;
      const edge = series.priceToCoordinate(group.buy ? bar.low : bar.high);
      if (edge === null) continue;
      if (group.buy) lowBuy.add(group.time);
      placed.push({ group, x, tip: group.buy ? edge + GAP : edge - GAP, label: wantText.has(group.id) ? groupLabel(group) : null, count: group.fills.length > 1 && !small, half });
    }
    // A count beside a chevron gives way when the next one on that side is too close to leave it room.
    const rows = { buy: placed.filter((item) => item.group.buy), sell: placed.filter((item) => !item.group.buy) };
    for (const row of [rows.buy, rows.sell]) row.forEach((item, i) => {
      const next = row[i + 1];
      if (item.count && next && next.x - next.half < item.x + item.half + 3 + 8 + 2) item.count = false;
    });
    this.fills = placed;

    // Text labels: under a buy, over a sell, kept clear of each other (a crowded one is left to the hover).
    if (wantText.size) {
      const measure = typeof document === "undefined" ? null : document.createElement("canvas").getContext("2d");
      if (measure) measure.font = `500 9px ${FONT}`;
      const boxes: { l: number; r: number; t: number; b: number }[] = [];
      for (const item of placed) {
        if (!item.label || !measure) continue;
        const w = measure.measureText(item.label).width;
        const y = item.group.buy ? item.tip + height + 11 : item.tip - height - 11;
        const box = { l: item.x - w / 2 - 2, r: item.x + w / 2 + 2, t: y - 6, b: y + 6 };
        if (box.l < 0 || box.r > width || boxes.some((o) => o.l < box.r && o.r > box.l && o.t < box.b && o.b > box.t)) continue;
        boxes.push(box);
        this.texts.push({ text: item.label, x: item.x, y, width: w, buy: item.group.buy });
      }
    }

    // Report dates: a ring with an E, under the candle (and under its buy chevron when it has one).
    for (const mark of this.set_.reports) {
      const [x, bar] = [at(mark.time), byTime(mark.time)];
      const low = bar ? series.priceToCoordinate(bar.low) : null;
      if (x === null || low === null) continue;
      this.reports.push({ mark, x, y: low + GAP + (lowBuy.has(mark.time) ? height + 5 : 0) + (small ? 5 : 7) });
    }

    // News: along the bottom of the pane, clustered by how close they land at this zoom.
    const stripY = this.paneHeight - STRIP_FROM_BOTTOM;
    const onScreen: { mark: NewsMark; x: number }[] = [];
    for (const mark of this.set_.news) { const x = at(mark.time); if (x !== null) onScreen.push({ mark, x }); }
    this.strip = clusterNews(onScreen, NEWS_CLUSTER_PX).map((cluster) => ({ cluster, x: cluster.x, y: stripY }));
  }

  /** The fill chevron or news marker at a point (pane pixels), nearest first; `slop` widens the reach (a finger). */
  hit(x: number, y: number, slop: number): MarkHit | null {
    const { height, bigR, stripR } = this.sizes();
    let best: { hit: MarkHit; d: number } | null = null;
    for (const item of this.fills) {
      const [top, bottom] = item.group.buy ? [item.tip - 3, item.tip + height + 4] : [item.tip - height - 4, item.tip + 3];
      const dx = Math.abs(item.x - x), dy = y < top ? top - y : y > bottom ? y - bottom : 0;
      if (dx > item.half + 2 + slop || dy > slop) continue;
      const d = Math.hypot(dx, dy);
      if (!best || d < best.d) best = { hit: { kind: "fill", group: item.group }, d };
    }
    if (best) return best.hit;
    for (const item of this.strip) {
      const r = item.cluster.articles.length > 1 ? bigR : stripR;
      const dx = Math.abs(item.x - x), dy = Math.abs(item.y - y);
      if (dx > r + 3 + slop || dy > r + 6 + slop) continue;
      const d = Math.hypot(dx, dy);
      if (!best || d < best.d) best = { hit: { kind: "news", cluster: item.cluster }, d };
    }
    return best?.hit ?? null;
  }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context: c, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      const { height, line, stripR, bigR } = this.sizes();
      const small = this.set_.small;
      c.save();
      c.lineCap = "round"; c.lineJoin = "round";
      const halo = (text: string, x: number, y: number) => { c.lineWidth = 3 * h; c.strokeStyle = INK; c.strokeText(text, x * h, y * v); c.fillText(text, x * h, y * v); };

      // News strip first, so the candles' own marks sit above it.
      for (const { cluster, x, y } of this.strip) {
        const many = cluster.articles.length > 1;
        const r = many ? bigR : stripR;
        c.beginPath(); c.arc(x * h, y * v, r * h, 0, Math.PI * 2);
        c.fillStyle = INK; c.fill();
        c.lineWidth = (many ? 1.2 : 1.3) * h; c.strokeStyle = NEWS; c.globalAlpha = many ? 0.85 : 0.75; c.stroke(); c.globalAlpha = 1;
        if (many) {
          c.font = `600 ${(small ? 7 : 8) * v}px ${FONT}`; c.textAlign = "center"; c.textBaseline = "middle"; c.fillStyle = NEWS;
          c.fillText(cluster.articles.length > 9 ? "9+" : String(cluster.articles.length), x * h, (y + 0.4) * v);
        }
      }

      // Report dates.
      for (const { mark, x, y } of this.reports) {
        const r = small ? 4 : 5.2;
        c.beginPath(); c.arc(x * h, y * v, r * h, 0, Math.PI * 2);
        c.fillStyle = INK; c.fill();
        c.lineWidth = 1.3 * h; c.strokeStyle = REPORT; c.globalAlpha = mark.estimated ? 0.6 : 1; c.setLineDash(mark.estimated ? [2 * h, 2 * h] : []); c.stroke(); c.setLineDash([]);
        c.font = `700 ${(small ? 6.5 : 7.5) * v}px ${FONT}`; c.textAlign = "center"; c.textBaseline = "middle"; c.fillStyle = REPORT;
        c.fillText("E", x * h, (y + 0.4) * v); c.globalAlpha = 1;
      }

      // Fills: slim open chevrons on the big chart, dots on the small ones.
      for (const { group, x, tip, half } of this.fills) {
        const color = group.buy ? BUY : SELL;
        if (small) {
          const r = group.fills.length > 1 ? 2.9 : 2.1;
          c.beginPath(); c.arc(x * h, (tip + (group.buy ? 1 : -1) * r) * v, r * h, 0, Math.PI * 2);
          c.fillStyle = color; c.globalAlpha = 0.95; c.fill(); c.lineWidth = 1 * h; c.strokeStyle = INK; c.stroke(); c.globalAlpha = 1;
          continue;
        }
        // Always one chevron per candle per side; a merged one is a touch heavier and brighter (its count, when there is room, sits beside it).
        const merged = group.fills.length > 1;
        const apex = tip, base = tip + (group.buy ? height : -height);
        c.beginPath(); c.moveTo((x - half) * h, base * v); c.lineTo(x * h, apex * v); c.lineTo((x + half) * h, base * v);
        c.lineWidth = (line + 2) * h; c.strokeStyle = INK; c.globalAlpha = 1; c.stroke(); // a thin dark edge keeps it apart from a wick behind it
        c.lineWidth = (line + (merged ? 0.5 : 0)) * h; c.strokeStyle = color; c.globalAlpha = merged ? 1 : 0.8; c.stroke();
        c.globalAlpha = 1;
      }

      // Counts beside a merged chevron, and the optional text labels.
      c.textBaseline = "middle";
      for (const item of this.fills) {
        if (!item.count) continue;
        c.font = `600 ${9.5 * v}px ${FONT}`; c.textAlign = "left"; c.fillStyle = item.group.buy ? BUY : SELL;
        halo(String(item.group.fills.length), item.x + item.half + 3, item.tip + (item.group.buy ? height : -height) / 2 + (item.group.buy ? 0.5 : -0.5));
      }
      c.font = `500 ${9 * v}px ${FONT}`; c.textAlign = "center";
      for (const text of this.texts) { c.fillStyle = text.buy ? BUY : SELL; c.globalAlpha = 0.85; halo(text.text, text.x, text.y); c.globalAlpha = 1; }
      c.restore();
    });
  }
}
