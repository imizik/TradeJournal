import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { Timeline } from "./drawings";

/** One column of the heatmap covers this much source time. */
export const HEAT_BUCKET_MS = 2_000;
/** Columns older than this behind the newest are dropped; the heatmap is memory only. */
export const HEAT_RETAIN_MS = 4 * 3600_000;
/** An update whose estimated age at receipt is outside 0..this is left out, never placed at a guessed time. */
export const HEAT_MAX_AGE_MS = 2_000;

/**
 * moomoo alternates two NVDA books on one subscription: an ARCA-labelled book
 * (one row per price) and a book of other market-maker IDs (NSDQ, NASD, ETMM…,
 * possibly several rows per price). They are never merged; one is shown.
 */
export type HeatBookKind = "arca" | "mpid";
export const HEAT_BOOK_LABELS: Record<HeatBookKind, string> = { arca: "ARCA-labelled book", mpid: "Other market-maker book" };

type HeatLevel = { price: number; volume: number; mpid: string | null };
export type HeatBook = { exchange: string; source_time_ms: number | null; estimated_age_ms: number | null; bids: HeatLevel[]; asks: HeatLevel[] };

/** A book with any MPID other than ARCA is the market-maker book; an MPID-less book follows its exchange field. */
export function heatBookKind(book: HeatBook): HeatBookKind | null {
  let arca = false;
  for (const level of [...book.bids, ...book.asks]) {
    if (level.mpid === null) continue;
    if (level.mpid !== "ARCA") return "mpid";
    arca = true;
  }
  if (arca || book.exchange === "ARCA") return "arca";
  return book.exchange === "NASDAQ" ? "mpid" : null;
}

/** A finished or forming column: [price, mean size, …] over the samples where that side was present. */
export type HeatColumn = { start: number; cells: Float64Array };

type Building = { start: number; sides: [Map<number, number>, Map<number, number>]; samples: [number, number] };

const priceKey = (price: number) => Math.round(price * 10_000);

/**
 * The heatmap's memory: a bounded series of 2-second columns per book. Each
 * update is placed at its own source time; a side missing from an update adds
 * nothing (no carrying older levels forward), an update without a usable
 * clock is skipped, and a gap with no updates stays blank, which is not zero.
 */
export class DepthHeatmap {
  version = 0;
  accepted = 0;
  skipped = 0;
  private readonly done: Record<HeatBookKind, HeatColumn[]> = { arca: [], mpid: [] };
  private readonly open: Record<HeatBookKind, Building | null> = { arca: null, mpid: null };
  private readonly listeners = new Set<() => void>();

  add(books: HeatBook[]) {
    let changed = false;
    for (const book of books) {
      const kind = heatBookKind(book);
      const at = book.source_time_ms;
      const age = book.estimated_age_ms;
      if (!kind || !at || age === null || age < 0 || age > HEAT_MAX_AGE_MS) { this.skipped++; continue; }
      const start = at - (at % HEAT_BUCKET_MS);
      let column = this.open[kind];
      if (column && start < column.start) { this.skipped++; continue; } // out of order: never rewrite a past column
      if (!column || start > column.start) {
        if (column) this.close(kind, column);
        column = this.open[kind] = { start, sides: [new Map(), new Map()], samples: [0, 0] };
      }
      [book.bids, book.asks].forEach((levels, side) => {
        if (!levels.length) return;
        column!.samples[side]++;
        const sizes = column!.sides[side];
        for (const level of levels) sizes.set(priceKey(level.price), (sizes.get(priceKey(level.price)) ?? 0) + level.volume);
      });
      this.accepted++;
      changed = true;
    }
    if (changed) this.changed();
  }

  /** The book's columns, oldest first, including the forming one. */
  columns(kind: HeatBookKind): HeatColumn[] {
    const forming = this.open[kind];
    return forming ? [...this.done[kind], this.finish(forming)] : this.done[kind];
  }

  clear() {
    this.done.arca = []; this.done.mpid = [];
    this.open.arca = null; this.open.mpid = null;
    this.accepted = this.skipped = 0;
    this.changed();
  }

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private changed() {
    this.version++;
    for (const listener of this.listeners) listener();
  }

  private close(kind: HeatBookKind, column: Building) {
    const list = this.done[kind];
    list.push(this.finish(column));
    const oldest = column.start - HEAT_RETAIN_MS;
    let drop = 0;
    while (drop < list.length && list[drop].start < oldest) drop++;
    if (drop) list.splice(0, drop);
  }

  private finish(column: Building): HeatColumn {
    const cells: number[] = [];
    column.sides.forEach((sizes, side) => {
      const samples = column.samples[side];
      if (samples) for (const [key, total] of sizes) cells.push(key / 10_000, total / samples);
    });
    return { start: column.start, cells: Float64Array.from(cells) };
  }
}

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

/** Dark blue through cyan and amber to near white, faint at the low end so the candles stay readable. */
const STOPS: [number, number, number, number][] = [[30, 64, 175, 0.18], [14, 165, 233, 0.32], [250, 204, 21, 0.5], [255, 247, 237, 0.7]];
const SHADES = 24;
const PALETTE = Array.from({ length: SHADES }, (_, index) => {
  const t = (index + 1) / SHADES * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(t));
  const f = t - i;
  const [a, b] = [STOPS[i], STOPS[i + 1]];
  const mix = (k: number) => a[k] + (b[k] - a[k]) * f;
  return `rgba(${Math.round(mix(0))},${Math.round(mix(1))},${Math.round(mix(2))},${mix(3).toFixed(3)})`;
});
/** The price step one cell spans; NVDA quotes in cents. */
const TICK = 0.01;

/**
 * Draws the heatmap behind the candles. The picture is cached and redrawn only
 * when the data, the visible range, the price scale or the size change, so the
 * crosshair and streamed candles stay cheap. Brightness is relative to the
 * 95th percentile size in view (square-root scale), so it shows where displayed
 * size sits, not absolute or executable liquidity.
 */
export class DepthHeatLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private source: DepthHeatmap | null = null;
  private kind: HeatBookKind = "arca";
  private unsubscribe: (() => void) | null = null;
  private pending: ReturnType<typeof setTimeout> | null = null;
  private cache: { key: string; canvas: HTMLCanvasElement } | null = null;
  /** The data version last asked to repaint; newer updates wait for the throttled repaint, not the crosshair. */
  private shown = -1;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "bottom", renderer: () => this.renderer }];

  constructor(private readonly timeline: Timeline) {}

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.set(null, this.kind);
    this.chart = this.series = this.requestUpdate = null;
  }

  /** Show `source`'s `kind` book, or nothing. New data repaints at most once a second. */
  set(source: DepthHeatmap | null, kind: HeatBookKind) {
    if (source === this.source && kind === this.kind) return;
    this.unsubscribe?.();
    this.unsubscribe = null;
    if (this.pending) clearTimeout(this.pending);
    this.pending = null;
    this.source = source;
    this.kind = kind;
    this.cache = null;
    this.shown = source?.version ?? -1;
    if (source) this.unsubscribe = source.subscribe(() => {
      if (!this.pending) this.pending = setTimeout(() => { this.pending = null; this.shown = source.version; this.requestUpdate?.(); }, 1_000);
    });
    this.requestUpdate?.();
  }

  updateAllViews() {}

  paneViews() { return this.views; }

  private draw(target: Target) {
    const { chart, series, source } = this;
    if (!chart || !series || !source) return;
    const columns = source.columns(this.kind);
    if (!columns.length) return;
    const scale = chart.timeScale();
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      const [x0, x1] = [scale.logicalToCoordinate(0 as Logical), scale.logicalToCoordinate(1 as Logical)];
      const reference = columns[columns.length - 1].cells[0] || 1;
      const [y0, y1] = [series.priceToCoordinate(reference), series.priceToCoordinate(reference + 1)];
      if (x0 === null || x1 === null || y0 === null || y1 === null) return;
      const key = [this.shown, this.kind, bitmapSize.width, bitmapSize.height, x0.toFixed(2), x1.toFixed(2), y0.toFixed(2), y1.toFixed(2), this.timeline.count].join("|");
      if (this.cache?.key !== key) this.cache = { key, canvas: this.paint(columns, bitmapSize.width, bitmapSize.height, h, v, Math.abs(y1 - y0) * TICK) };
      context.drawImage(this.cache.canvas, 0, 0);
    });
  }

  private paint(columns: HeatColumn[], width: number, height: number, h: number, v: number, tickHeight: number) {
    const canvas = this.cache?.canvas.width === width && this.cache.canvas.height === height ? this.cache.canvas : Object.assign(document.createElement("canvas"), { width, height });
    const context = canvas.getContext("2d")!;
    context.clearRect(0, 0, width, height);
    const scale = this.chart!.timeScale();
    const series = this.series!;
    // The library converts whole indexes only; fractions are on the line through 0 and 1.
    const [zero, one] = [scale.logicalToCoordinate(0 as Logical)!, scale.logicalToCoordinate(1 as Logical)!];
    const x = (ms: number) => {
      const logical = this.timeline.toLogical(ms / 1000);
      return logical === null ? null : (zero + logical * (one - zero)) * h;
    };
    // Bin into screen pixels before drawing: every column that lands on the same
    // pixel column is averaged, and every price that lands on the same pixel row
    // is summed, so a zoomed-out view never stacks hundreds of translucent cells.
    const cell = Math.max(1, Math.round(tickHeight * v));
    const bins: { left: number; right: number; rows: Map<number, number>; columns: number }[] = [];
    for (const column of columns) {
      const [left, right] = [x(column.start), x(column.start + HEAT_BUCKET_MS)];
      if (left === null || right === null || right <= 0 || left >= width || right - left <= 0) continue;
      const l = Math.floor(left);
      let bin = bins[bins.length - 1];
      if (!bin || bin.left !== l) bins.push(bin = { left: l, right, rows: new Map(), columns: 0 });
      bin.right = Math.max(bin.right, right);
      bin.columns++;
      const cells = column.cells;
      for (let i = 0; i < cells.length; i += 2) {
        const y = series.priceToCoordinate(cells[i]);
        if (y === null) continue;
        const top = Math.floor(y * v / cell) * cell;
        if (top + cell < 0 || top > height) continue;
        bin.rows.set(top, (bin.rows.get(top) ?? 0) + cells[i + 1]);
      }
    }
    const sample: number[] = [];
    for (const bin of bins) for (const total of bin.rows.values()) if (sample.length < 20_000) sample.push(total / bin.columns);
    if (!sample.length) return canvas;
    sample.sort((a, b) => a - b);
    const bright = sample[Math.floor(0.95 * (sample.length - 1))] || 1;
    const shades: [number, number, number][][] = Array.from({ length: SHADES }, () => []);
    bins.forEach((bin, index) => {
      const next = bins[index + 1]?.left ?? Infinity;
      const w = Math.max(1, Math.min(next, Math.ceil(bin.right)) - bin.left);
      for (const [top, total] of bin.rows) {
        const shade = Math.min(SHADES - 1, Math.floor(Math.sqrt(total / bin.columns / bright) * (SHADES - 1)));
        shades[shade].push([bin.left, top, w]);
      }
    });
    shades.forEach((rects, shade) => {
      context.fillStyle = PALETTE[shade];
      for (const [l, t, w] of rects) context.fillRect(l, t, w, cell);
    });
    return canvas;
  }
}
