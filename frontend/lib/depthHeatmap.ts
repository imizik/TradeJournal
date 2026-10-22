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

/**
 * A finished or forming column of `width` ms: [price, mean size, …] over the samples where that side was present,
 * bids first; `bids` counts the bid pairs (null from an older recorder that did not say).
 */
export type HeatColumn = { start: number; width: number; cells: Float64Array; bids: number | null };

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

  /** A price from the book's newest column, without building it: the draw's cache key needs only one. */
  referencePrice(kind: HeatBookKind): number | null {
    const forming = this.open[kind];
    if (forming) for (const sizes of forming.sides) for (const key of sizes.keys()) return key / 10_000;
    const done = this.done[kind];
    return done.length && done[done.length - 1].cells.length ? done[done.length - 1].cells[0] : null;
  }

  /**
   * Replace or extend `kind` with recorded columns from the depth recorder
   * ([start, width, [price, size, …], bid pairs?]), keyed by start: a newer copy
   * of a column replaces the older one. Recorded maps never mix with live updates.
   */
  load(kind: HeatBookKind, columns: [number, number, number[], number?][]) {
    if (!columns.length) return;
    const first = columns[0][0];
    const kept = this.done[kind].filter((column) => column.start < first);
    this.done[kind] = [...kept, ...columns.map(([start, width, cells, bids]) => ({ start, width, cells: Float64Array.from(cells), bids: bids ?? null }))];
    const oldest = this.done[kind][this.done[kind].length - 1].start - HEAT_RETAIN_MS;
    this.done[kind] = this.done[kind].filter((column) => column.start >= oldest);
    this.changed();
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
    let bids = 0;
    column.sides.forEach((sizes, side) => {
      const samples = column.samples[side];
      if (samples) for (const [key, total] of sizes) cells.push(key / 10_000, total / samples);
      if (side === 0) bids = cells.length / 2;
    });
    return { start: column.start, width: HEAT_BUCKET_MS, cells: Float64Array.from(cells), bids };
  }
}

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

/**
 * One ramp per side, matching the depth profile and wall colors: bids blue, asks
 * orange, and amber when an older recorder did not say which side. Each starts
 * nearly transparent and ends near white, so only the largest size stands out.
 */
const SHADES = 24;
const ramp = ([r, g, b]: [number, number, number]) => Array.from({ length: SHADES }, (_, index) => {
  const t = (index + 1) / SHADES;
  const white = Math.max(0, t - 0.7) / 0.3; // the top shades blend toward white
  const mix = (c: number) => Math.round(c + (255 - c) * white * 0.8);
  return `rgba(${mix(r)},${mix(g)},${mix(b)},${(0.08 + 0.72 * t).toFixed(3)})`;
});
const PALETTES = [ramp([56, 189, 248]), ramp([251, 146, 60]), ramp([250, 204, 21])];
/** The price step one cell spans: US stocks over $1 quote in cents; finer sub-dollar steps share a pixel row. */
const TICK = 0.01;
/** Price rows are at least this many CSS pixels tall; zoomed out, neighbouring cents are summed into one row of a round step. */
const MIN_ROW_PX = 3;
const ROW_STEPS = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10];
/** Size at or below this share of the cells in view is not drawn; at or above BRIGHT_SHARE is the brightest shade. */
const FLOOR_SHARE = 0.7;
const BRIGHT_SHARE = 0.98;

/**
 * Draws the heatmap behind the candles. The picture is cached and redrawn only
 * when the data, the visible range, the price scale or the size change, so the
 * crosshair and streamed candles stay cheap. Brightness is relative to the size
 * in view: the smallest 70% of cells are left out and the scale runs linearly up
 * to the 98th percentile, so it shows where displayed size stood out, not
 * absolute or executable liquidity.
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
    const reference = source.referencePrice(this.kind);
    if (reference === null) return;
    const scale = chart.timeScale();
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      const [x0, x1] = [scale.logicalToCoordinate(0 as Logical), scale.logicalToCoordinate(1 as Logical)];
      const [y0, y1] = [series.priceToCoordinate(reference), series.priceToCoordinate(reference + 1)];
      if (x0 === null || x1 === null || y0 === null || y1 === null) return;
      // Hover and streamed candles reuse the picture; only data, range, scale or size repaint it.
      const key = [this.shown, this.kind, bitmapSize.width, bitmapSize.height, x0.toFixed(2), x1.toFixed(2), y0.toFixed(2), y1.toFixed(2), this.timeline.count].join("|");
      if (this.cache?.key !== key) this.cache = { key, canvas: this.paint(source.columns(this.kind), bitmapSize.width, bitmapSize.height, h, v, { reference, y: y0, perDollar: y1 - y0 }) };
      context.drawImage(this.cache.canvas, 0, 0);
    });
  }

  /** The price scale is linear (Charts never sets a log scale), so a price's y is one multiply from a reference. */
  private paint(columns: HeatColumn[], width: number, height: number, h: number, v: number, prices: { reference: number; y: number; perDollar: number }) {
    const canvas = this.cache?.canvas.width === width && this.cache.canvas.height === height ? this.cache.canvas : Object.assign(document.createElement("canvas"), { width, height });
    const context = canvas.getContext("2d")!;
    context.clearRect(0, 0, width, height);
    const scale = this.chart!.timeScale();
    // The library converts whole indexes only; fractions are on the line through 0 and 1.
    const [zero, one] = [scale.logicalToCoordinate(0 as Logical)!, scale.logicalToCoordinate(1 as Logical)!];
    const x = (ms: number) => {
      const logical = this.timeline.toLogical(ms / 1000);
      return logical === null ? null : (zero + logical * (one - zero)) * h;
    };
    // Bin before drawing: every column that lands on the same pixel column is
    // averaged, and every price in the same row step is summed, so a zoomed-out
    // view never stacks hundreds of translucent cells or draws 1-pixel pinstripes.
    const step = ROW_STEPS.find((candidate) => Math.abs(prices.perDollar) * candidate >= MIN_ROW_PX) ?? ROW_STEPS[ROW_STEPS.length - 1];
    const y = (price: number) => (prices.y + (price - prices.reference) * prices.perDollar) * v;
    // Rows per side: bids, asks, and cells from a column that did not say.
    const bins: { left: number; right: number; rows: [Map<number, number>, Map<number, number>, Map<number, number>]; columns: number }[] = [];
    for (const column of columns) {
      const [left, right] = [x(column.start), x(column.start + column.width)];
      if (left === null || right === null || right <= 0 || left >= width || right - left <= 0) continue;
      const l = Math.floor(left);
      let bin = bins[bins.length - 1];
      if (!bin || bin.left !== l) bins.push(bin = { left: l, right, rows: [new Map(), new Map(), new Map()], columns: 0 });
      bin.right = Math.max(bin.right, right);
      bin.columns++;
      const cells = column.cells;
      for (let i = 0; i < cells.length; i += 2) {
        const row = Math.floor((cells[i] + TICK / 2) / step + 1e-6);
        const [top, bottom] = [y(row * step + step - TICK / 2), y(row * step - TICK / 2)];
        if (bottom < 0 || top > height) continue;
        const rows = bin.rows[column.bids === null ? 2 : i / 2 < column.bids ? 0 : 1];
        rows.set(row, (rows.get(row) ?? 0) + cells[i + 1]);
      }
    }
    const sample: number[] = [];
    for (const bin of bins) for (const rows of bin.rows) for (const total of rows.values()) if (sample.length < 20_000) sample.push(total / bin.columns);
    if (!sample.length) return canvas;
    sample.sort((a, b) => a - b);
    const floor = sample[Math.floor(FLOOR_SHARE * (sample.length - 1))];
    const bright = sample[Math.floor(BRIGHT_SHARE * (sample.length - 1))];
    const range = bright - floor || 1;
    const shades: [number, number, number, number][][][] = PALETTES.map(() => Array.from({ length: SHADES }, () => []));
    bins.forEach((bin, index) => {
      const next = bins[index + 1]?.left ?? Infinity;
      const w = Math.max(1, Math.min(next, Math.ceil(bin.right)) - bin.left);
      bin.rows.forEach((rows, side) => {
        for (const [row, total] of rows) {
          const size = total / bin.columns;
          if (size <= floor) continue;
          const shade = Math.min(SHADES - 1, Math.floor((size - floor) / range * (SHADES - 1)));
          const [top, bottom] = [Math.round(y(row * step + step - TICK / 2)), Math.round(y(row * step - TICK / 2))];
          shades[side][shade].push([bin.left, top, w, Math.max(1, bottom - top)]);
        }
      });
    });
    shades.forEach((side, palette) => side.forEach((rects, shade) => {
      context.fillStyle = PALETTES[palette][shade];
      for (const [l, t, w, hgt] of rects) context.fillRect(l, t, w, hgt);
    }));
    return canvas;
  }
}

/** The latest book per price: [price, size] pairs, sides as received (a missing side stays empty). */
export type DepthProfile = { t: number; bids: [number, number][]; asks: [number, number][] };

const PROFILE_WIDTH = 56;
const PROFILE_COLORS = { bids: "rgba(56,189,248,0.35)", asks: "rgba(251,146,60,0.35)" };

/**
 * The live depth profile: one thin bar per price in the price-axis gutter, so it
 * never covers candles; length relative to the largest size in the book, bids
 * blue and asks orange, faint enough that the axis labels drawn over it stay
 * readable. It shows the latest displayed book only (dimmed when stale).
 */
export class DepthProfileLayer implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private profile: DepthProfile | null = null;
  private stale = false;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "bottom", renderer: () => this.renderer }];

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.series = this.requestUpdate = null;
  }

  set(profile: DepthProfile | null, stale: boolean) {
    if (profile === this.profile && stale === this.stale) return;
    this.profile = profile;
    this.stale = stale;
    this.requestUpdate?.();
  }

  updateAllViews() {}

  paneViews() { return []; }

  priceAxisPaneViews() { return this.views; }

  private draw(target: Target) {
    const { series, profile } = this;
    if (!series || !profile) return;
    const levels = [...profile.bids.map((level) => ["bids", ...level] as const), ...profile.asks.map((level) => ["asks", ...level] as const)];
    const largest = Math.max(0, ...levels.map(([, , size]) => size));
    if (!largest) return;
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      const [y0, y1] = [series.priceToCoordinate(levels[0][1]), series.priceToCoordinate(levels[0][1] + TICK)];
      if (y0 === null || y1 === null) return;
      const cell = Math.max(1, Math.round(Math.abs(y1 - y0) * v));
      context.globalAlpha = this.stale ? 0.35 : 1;
      for (const [side, price, size] of levels) {
        const y = series.priceToCoordinate(price);
        if (y === null) continue;
        const length = Math.max(1, Math.round(Math.sqrt(size / largest) * Math.min(PROFILE_WIDTH * h, bitmapSize.width)));
        context.fillStyle = PROFILE_COLORS[side];
        context.fillRect(0, Math.round(y * v - cell / 2), length, cell);
      }
      context.globalAlpha = 1;
    });
  }
}

/** A liquidity level ready to draw: a dotted segment from when it appeared, with a short size tag. */
export type WallLine = { price: number; side: "bid" | "ask"; since: number; lastSeen: number; pulled: boolean; label: string; title: string;
  /** The recorder stopped receiving: drawn faint and ending at its last update, not at "now". */
  stale: boolean };
const compact = (size: number) => size >= 1000 ? `${(size / 1000).toFixed(size >= 10_000 ? 0 : 1)}k` : String(Math.round(size));
export const WALL_COLORS = { bid: "#38bdf8", ask: "#fb923c", pulled: "#64748b" };

/** Recorder walls as chart lines: label "9.0k · 11m"; a pulled one ends where it was last seen; stale ones say so. */
export function wallLines(walls: { bids: { price: number; size: number; since: number; last_seen: number; pulled: boolean }[]; asks: { price: number; size: number; since: number; last_seen: number; pulled: boolean }[] }, lastMs: number, stale = false): WallLine[] {
  const line = (side: "bid" | "ask") => (wall: { price: number; size: number; since: number; last_seen: number; pulled: boolean }): WallLine => {
    const minutes = Math.max(0, Math.round((lastMs - wall.since) / 60_000));
    const age = `${minutes < 1 ? "<1" : minutes}m`;
    const name = side === "bid" ? "Bid" : "Ask";
    return { price: wall.price, side, since: wall.since, lastSeen: stale ? lastMs : wall.last_seen, pulled: wall.pulled, stale,
      label: wall.pulled ? `${compact(wall.size)} pulled` : `${compact(wall.size)} · ${age}${stale ? " · not live" : ""}`,
      title: wall.pulled ? `${name} wall of ${compact(wall.size)} pulled` : `${name} wall ${compact(wall.size)}, resting ${age}` };
  };
  return [...walls.bids.map(line("bid")), ...walls.asks.map(line("ask"))];
}

/**
 * Liquidity levels on the chart: each wall is a dotted segment from the time it
 * started resting to now (or to when it was last seen, if pulled), so its
 * length shows how long it held; its size tag sits at the segment's start, away
 * from the newest candles. The price axis tag comes from a line-less price line.
 */
export class WallLayer implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private walls: WallLine[] = [];
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "normal", renderer: () => this.renderer }];

  constructor(private readonly timeline: Timeline) {}

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.chart = this.series = this.requestUpdate = null;
  }

  set(walls: WallLine[]) {
    this.walls = walls;
    this.requestUpdate?.();
  }

  updateAllViews() {}

  paneViews() { return this.views; }

  private draw(target: Target) {
    const { chart, series, walls } = this;
    if (!chart || !series || !walls.length) return;
    const scale = chart.timeScale();
    const [zero, one] = [scale.logicalToCoordinate(0 as Logical), scale.logicalToCoordinate(1 as Logical)];
    if (zero === null || one === null) return;
    const x = (ms: number) => {
      const logical = this.timeline.toLogical(ms / 1000);
      return logical === null ? null : zero + logical * (one - zero);
    };
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.font = "10px ui-sans-serif, system-ui, sans-serif";
      // Current walls label first; a tag that would overlap one already drawn is left out (its line and axis tag remain).
      const tags: [number, number, number, number][] = [];
      for (const wall of [...walls].sort((a, b) => Number(a.pulled) - Number(b.pulled))) {
        const y = series.priceToCoordinate(wall.price);
        const start = x(wall.since);
        if (y === null || start === null) continue;
        const end = wall.pulled || wall.stale ? x(wall.lastSeen) ?? mediaSize.width : mediaSize.width;
        const left = Math.max(0, start);
        if (end <= left) continue;
        const color = wall.pulled ? WALL_COLORS.pulled : WALL_COLORS[wall.side];
        context.globalAlpha = wall.stale ? 0.45 : 1;
        context.strokeStyle = color;
        context.lineWidth = wall.pulled ? 1 : 1.5;
        context.setLineDash([3, 3]);
        context.beginPath();
        context.moveTo(left, Math.round(y) + 0.5);
        context.lineTo(end, Math.round(y) + 0.5);
        context.stroke();
        context.setLineDash([]);
        context.globalAlpha = 1;
        // The tag ends where the wall began, so it reads into the line and stays off the newest candles.
        const width = context.measureText(wall.label).width;
        const textX = left - width - 4 >= 0 ? left - width - 4 : Math.min(left + 3, end - width - 3);
        const box: [number, number, number, number] = [textX - 2, y - 7, textX + width + 2, y + 7];
        if (tags.some(([l, t, r, b]) => box[0] < r && box[2] > l && box[1] < b && box[3] > t)) continue;
        tags.push(box);
        context.textBaseline = "middle";
        context.globalAlpha = wall.pulled || wall.stale ? 0.6 : 1;
        context.lineWidth = 3;
        context.strokeStyle = "#10151e";
        context.strokeText(wall.label, textX, y);
        context.fillStyle = color;
        context.fillText(wall.label, textX, y);
        context.globalAlpha = 1;
      }
    });
  }
}
