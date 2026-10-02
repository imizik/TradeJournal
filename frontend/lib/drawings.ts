import type { IChartApiBase, IPrimitivePaneRenderer, Logical, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, ISeriesPrimitiveAxisView, PrimitiveHoveredItem, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { ChartBar, PriceLevel } from "./charts";

/**
 * The drawing layer (C1.1, C1.2): one series primitive on each chart's candles
 * draws the user's levels and drawings and says which one the pointer is on.
 * Drawings are anchored to time and price, never to pixels or bar index, so
 * every panel showing a symbol draws them at the same moments and prices at
 * any zoom or interval.
 *
 * Edits are item-level (`DrawingEdit`), so undo and redo replay onto whatever
 * the workspace holds now, including items another device saved since.
 */

/** Pointer distance, in CSS pixels, that still counts as on a line. A finger gets a 28px band. */
export const MOUSE_SLOP = 6;
export const TOUCH_SLOP = 14;
/** Movement below this is a click or tap, not a drag. */
export const DRAG_START = 3;
export const MAX_LEVELS = 30;
export const MAX_DRAWINGS = 40;
export const NOTE_MAX = 120;
/** Undo steps kept in this tab; edits are not saved to the server's history. */
export const MAX_UNDO = 100;

const LINE = "#659ef0";
const SELECTED = "#9cc2ff";
const BACKGROUND = "#10151e";
const FONT = "ui-sans-serif, system-ui, sans-serif";

export type DrawingKind = "ray" | "trend" | "zone" | "note";
/** What the main chart places on the next click: a saved level or a drawing. */
export type Tool = "level" | DrawingKind;
/** A moment on the time axis (UTC seconds) and a price. Placed anchors sit in the middle of a bar. */
export type Anchor = { time: number; price: number };
export type LineWidth = 1 | 2 | 3;
export type ToolStyle = { color: string; width: LineWidth };
/**
 * A saved drawing. Prices are on the chart's basis on `drawn_on`, like a
 * level's, so a later split moves every anchor by the same ratio. A ray and a
 * note have one anchor; a trend line and a zone (two opposite corners) have two.
 */
export type Drawing = {
  id: string; kind: DrawingKind; points: Anchor[]; color: string; width: LineWidth; drawn_on: string;
  text?: string; extendLeft?: boolean; extendRight?: boolean;
};
export type DrawingPatch = Partial<Pick<Drawing, "points" | "color" | "width" | "text" | "extendLeft" | "extendRight">>;

export const DRAWING_KINDS: DrawingKind[] = ["ray", "trend", "zone", "note"];
export const TOOL_NAMES: Record<Tool, string> = { level: "Price level", ray: "Horizontal ray", trend: "Trend line", zone: "Rectangle zone", note: "Text note" };
export const POINTS: Record<DrawingKind, number> = { ray: 1, trend: 2, zone: 2, note: 1 };
/** The colors a drawing can take, named for their buttons. */
export const PALETTE: [string, string][] = [["#659ef0", "Blue"], ["#67d5eb", "Cyan"], ["#2bc9a4", "Green"], ["#f4c66b", "Amber"], ["#ee617a", "Red"], ["#b494f5", "Violet"], ["#e2e8f0", "White"]];
export const DEFAULT_TOOL_STYLES: Record<DrawingKind, ToolStyle> = {
  ray: { color: "#f4c66b", width: 1 }, trend: { color: "#67d5eb", width: 2 }, zone: { color: "#659ef0", width: 1 }, note: { color: "#e2e8f0", width: 1 },
};
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const COLOR = /^#[0-9a-f]{6}$/;

/** Prices are saved to the cent, as levels are. */
export const roundPrice = (value: number) => Math.round(value * 100) / 100;
const width = (value: unknown): LineWidth => value === 2 || value === 3 ? value : 1;

/** A drawing in the one shape the workspace saves and compares, or null if it is not one the page could have made. */
export function cleanDrawing(row: unknown): Drawing | null {
  const value = row as Partial<Drawing> | null;
  if (!value || typeof value.id !== "string" || !DRAWING_KINDS.includes(value.kind as DrawingKind) || !Array.isArray(value.points)) return null;
  const kind = value.kind as DrawingKind;
  const points = value.points.map((point) => ({ time: point?.time, price: point?.price }));
  if (points.length !== POINTS[kind] || !points.every((p) => Number.isFinite(p.time) && Number.isFinite(p.price) && (p.price as number) > 0)) return null;
  if (typeof value.drawn_on !== "string" || !DAY.test(value.drawn_on)) return null;
  return {
    id: value.id, kind, points: points as Anchor[], color: typeof value.color === "string" && COLOR.test(value.color) ? value.color : DEFAULT_TOOL_STYLES[kind].color,
    width: width(value.width), drawn_on: value.drawn_on,
    ...(kind === "note" ? { text: typeof value.text === "string" && value.text.trim() ? value.text.slice(0, NOTE_MAX) : "Note" } : {}),
    ...(kind === "trend" ? { extendLeft: value.extendLeft === true, extendRight: value.extendRight === true } : {}),
  };
}

export function cleanDrawings(value: unknown, symbolOk: (symbol: string) => boolean): Record<string, Drawing[]> {
  const out: Record<string, Drawing[]> = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [symbol, rows] of Object.entries(value)) {
    if (!symbolOk(symbol) || !Array.isArray(rows)) continue;
    const kept = rows.map(cleanDrawing).filter((row): row is Drawing => !!row).slice(0, MAX_DRAWINGS);
    if (kept.length) out[symbol] = kept;
  }
  return out;
}

export function cleanToolStyles(value: unknown): Record<DrawingKind, ToolStyle> {
  const styles = (value && typeof value === "object" ? value : {}) as Partial<Record<DrawingKind, Partial<ToolStyle>>>;
  return Object.fromEntries(DRAWING_KINDS.map((kind) => {
    const style = styles[kind];
    return [kind, { color: typeof style?.color === "string" && COLOR.test(style.color) ? style.color : DEFAULT_TOOL_STYLES[kind].color, width: style ? width(style.width) : DEFAULT_TOOL_STYLES[kind].width }];
  })) as Record<DrawingKind, ToolStyle>;
}

/** One item changed: added (no `before`), deleted (no `after`), moved or restyled. `index` is where it sat. */
export type DrawingEdit =
  | { symbol: string; layer: "levels"; before: PriceLevel | null; after: PriceLevel | null; index: number }
  | { symbol: string; layer: "drawings"; before: Drawing | null; after: Drawing | null; index: number };
type Items = { levels: Record<string, PriceLevel[]>; drawings: Record<string, Drawing[]> };

function applyRows<T extends { id: string }>(map: Record<string, T[]>, edit: { symbol: string; before: T | null; after: T | null; index: number }, side: "before" | "after", max: number): Record<string, T[]> | null {
  const target = edit[side];
  const id = (edit.after ?? edit.before)!.id;
  const rows = map[edit.symbol] ?? [];
  const at = rows.findIndex((row) => row.id === id);
  let next: T[];
  if (!target) next = rows.filter((row) => row.id !== id);
  else if (at >= 0) next = rows.map((row) => row.id === id ? target : row);
  else if (rows.length >= max) return null;
  else next = [...rows.slice(0, edit.index), target, ...rows.slice(edit.index)];
  return { ...map, [edit.symbol]: next };
}

/**
 * Levels and drawings with one side of an edit applied: `after` replays it,
 * `before` undoes it. Null when that would put a symbol over its limit.
 */
export function applyEdit<T extends Items>(items: T, edit: DrawingEdit, side: "before" | "after"): T | null {
  if (edit.layer === "levels") { const levels = applyRows(items.levels, edit, side, MAX_LEVELS); return levels && { ...items, levels }; }
  const drawings = applyRows(items.drawings, edit, side, MAX_DRAWINGS);
  return drawings && { ...items, drawings };
}

/** "trend line", or a level's label: what Undo and Redo name. */
export const editName = (edit: DrawingEdit) => edit.layer === "levels" ? (edit.after ?? edit.before)!.label : TOOL_NAMES[(edit.after ?? edit.before)!.kind].toLowerCase();
export function editVerb(edit: DrawingEdit) {
  if (!edit.before) return "adding";
  if (!edit.after) return "deleting";
  if (edit.layer === "levels") return "moving";
  return JSON.stringify(edit.before.points) === JSON.stringify(edit.after.points) ? "changing" : "moving";
}

/**
 * Where a moment sits on one chart's logical axis, and back. Bar `i` is drawn
 * centered on `i` and spans `i - 0.5` to `i + 0.5`, its own start to end time,
 * so a 5m anchor lands inside the right 1h bar, and a 1h anchor between the
 * right 5m bars. A moment between bars (overnight) sits on their boundary.
 * Beyond the loaded bars the axis continues at one interval per bar, as the
 * chart's empty space to the right does.
 */
export class Timeline {
  constructor(private readonly bars: () => ChartBar[], private readonly step: () => number) {}

  get count() { return this.bars().length; }
  bar(index: number): ChartBar | undefined { return this.bars()[index]; }

  toLogical(time: number): number | null {
    const bars = this.bars();
    const n = bars.length;
    if (!n) return null;
    if (time < bars[0].time) return -0.5 + (time - bars[0].time) / this.step();
    const last = bars[n - 1];
    if (time >= last.end_time) return n - 0.5 + (time - last.end_time) / this.step();
    let lo = 0;
    let hi = n - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (bars[mid].time <= time) lo = mid; else hi = mid - 1; }
    const bar = bars[lo];
    if (time >= bar.end_time || bar.end_time <= bar.time) return lo + 0.5;
    return lo - 0.5 + (time - bar.time) / (bar.end_time - bar.time);
  }

  toTime(logical: number): number | null {
    const bars = this.bars();
    const n = bars.length;
    if (!n) return null;
    if (logical < -0.5) return Math.round(bars[0].time + (logical + 0.5) * this.step());
    if (logical >= n - 0.5) return Math.round(bars[n - 1].end_time + (logical - (n - 0.5)) * this.step());
    const index = Math.floor(logical + 0.5);
    const bar = bars[index];
    return Math.round(bar.time + (logical - (index - 0.5)) * (bar.end_time - bar.time));
  }
}

/** Which anchor's time and which anchor's price each handle moves. A zone has a handle at every corner. */
const HANDLES: Record<Tool, [number, number][]> = { level: [], ray: [[0, 0]], note: [[0, 0]], trend: [[0, 0], [1, 1]], zone: [[0, 0], [1, 1], [0, 1], [1, 0]] };

export function moveHandle(points: Anchor[], kind: DrawingKind, handle: number, to: Anchor): Anchor[] {
  const [time, price] = HANDLES[kind][handle];
  const next = points.map((point) => ({ ...point }));
  next[time].time = to.time;
  next[price].price = to.price;
  return next;
}

/** What the layer draws: a level (one price, no time) or a drawing, on the chart's current basis. */
export type Shown = { id: string; kind: Tool; points: Anchor[]; label: string; color: string; width: number; extendLeft?: boolean; extendRight?: boolean };
export const levelShape = (level: { id: string; price: number; label: string }): Shown => ({ id: level.id, kind: "level", points: [{ time: 0, price: level.price }], label: level.label, color: LINE, width: 1 });
export const drawingShape = (drawing: Drawing): Shown => ({ id: drawing.id, kind: drawing.kind, points: drawing.points, label: drawing.text ?? "", color: drawing.color, width: drawing.width, extendLeft: drawing.extendLeft, extendRight: drawing.extendRight });
/** Zones under everything, notes on top; ties in a hit go to what is drawn on top. */
const LAYER: Record<Tool, number> = { zone: 0, level: 1, ray: 2, trend: 3, note: 4 };

type Point = { x: number; y: number };
type Placed = { item: Shown; at: (Point | null)[]; box: { left: number; top: number; right: number; bottom: number } | null };
/** The pointer is on `id`: on one of its handles (selected items only), or on the item itself. */
export type Hit = { id: string; handle: number | null };
type Renderer = IPrimitivePaneRenderer;
type Target = Parameters<Renderer["draw"]>[0];

let measurer: CanvasRenderingContext2D | null = null;
function textWidth(text: string): number {
  measurer ??= document.createElement("canvas").getContext("2d");
  if (!measurer) return text.length * 6;
  measurer.font = `11px ${FONT}`;
  return measurer.measureText(text).width;
}

function segmentDistance(p: Point, a: Point, b: Point, from: number, to: number) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(from, Math.min(to, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length)) : 0;
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

export class DrawingLayer implements ISeriesPrimitive<Time> {
  private items: Shown[] = [];
  private selected: string | null = null;
  private labels = false;
  private interactive = true;
  /** An item being dragged or placed is drawn here until the saved one comes back. */
  private preview: Shown | null = null;
  private placed: Placed[] = [];
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private chart: IChartApiBase<Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private axis: ISeriesPrimitiveAxisView[] = [];
  private axisKey = "";
  private readonly renderer: Renderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "top", renderer: () => this.renderer }];

  constructor(readonly timeline: Timeline) {}

  attached({ series, chart, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series;
    this.chart = chart;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.series = null;
    this.chart = null;
    this.requestUpdate = null;
  }

  /** What to draw. `labels` writes each level's name on the line (the main chart). */
  set(items: Shown[], selected: string | null, labels: boolean) {
    this.items = [...items].sort((a, b) => LAYER[a.kind] - LAYER[b.kind]);
    this.selected = selected;
    this.labels = labels;
    this.preview = null;
    this.update();
  }

  /** Off while the chart places a new item by click, so the pointer is not taken for a drag. */
  setInteractive(on: boolean) { this.interactive = on; }

  /** Draw `item` in place of the item with its id, or in addition (one being placed). */
  setPreview(item: Shown | null) {
    this.preview = item;
    this.update();
  }

  item(id: string): Shown | undefined { return this.items.find((item) => item.id === id); }

  /** Pixel x of a logical index, fractions included (the library converts whole indexes only). */
  x(logical: number): number | null {
    const scale = this.chart?.timeScale();
    const zero = scale?.logicalToCoordinate(0 as Logical);
    const one = scale?.logicalToCoordinate(1 as Logical);
    return zero == null || one == null ? null : zero + logical * (one - zero);
  }

  logicalAt(x: number): number | null {
    const scale = this.chart?.timeScale();
    const zero = scale?.logicalToCoordinate(0 as Logical);
    const one = scale?.logicalToCoordinate(1 as Logical);
    return zero == null || one == null || one === zero ? null : (x - zero) / (one - zero);
  }

  /** With the magnet: the open, high, low or close of the bar at `logical` drawn nearest `price`, or null past the bars. */
  snapPrice(logical: number, price: number): number | null {
    const bar = this.timeline.bar(Math.floor(logical + 0.5));
    const series = this.series;
    const y = series?.priceToCoordinate(price);
    if (!bar || !series || y == null) return null;
    const near = (value: number) => Math.abs((series.priceToCoordinate(value) ?? Infinity) - y);
    return [bar.open, bar.high, bar.low, bar.close].reduce((best, value) => near(value) < near(best) ? value : best);
  }

  /**
   * The anchor a click at (x, y) places: the middle of the nearest bar (or of
   * an empty slot past the last one) at the price under the pointer, to the
   * cent. With the magnet, the price is that bar's open, high, low or close,
   * whichever is drawn nearest the pointer.
   */
  anchorAt(x: number, y: number, magnet: boolean): Anchor | null {
    const logical = this.logicalAt(x);
    if (logical === null || !this.series) return null;
    const index = Math.floor(logical + 0.5);
    const time = this.timeline.toTime(index);
    if (time === null) return null;
    const bar = this.timeline.bar(index);
    if (magnet && bar) {
      const series = this.series;
      const near = (price: number) => Math.abs((series.priceToCoordinate(price) ?? Infinity) - y);
      return { time, price: [bar.open, bar.high, bar.low, bar.close].reduce((best, price) => near(price) < near(best) ? price : best) };
    }
    const price = this.series.coordinateToPrice(y);
    return price === null || roundPrice(price) <= 0 ? null : { time, price: roundPrice(price) };
  }

  /** Where an item's anchors are drawn now, in pixels from the pane's top left. */
  anchors(id: string): (Point | null)[] | null { return this.placed.find((entry) => entry.item.id === id)?.at ?? null; }

  /** Where a level is drawn now, in pixels from the top of the pane. */
  y(id: string): number | null { return this.anchors(id)?.[0]?.y ?? null; }

  /**
   * The item under the pointer within `slop` pixels, or null. A selected item's
   * handles come first; then the nearest item, the selected one or the one on
   * top winning a tie. `only` restricts the search to one item.
   */
  hit(x: number, y: number, slop: number, only?: string | null): Hit | null {
    const p = { x, y };
    const selected = this.placed.find((entry) => entry.item.id === this.selected && (only === undefined || entry.item.id === only));
    if (selected) {
      const handles = this.handlePoints(selected);
      const index = handles.findIndex((handle) => handle && Math.hypot(handle.x - x, handle.y - y) <= slop + 3);
      if (index >= 0) return { id: selected.item.id, handle: index };
    }
    let best: { id: string; distance: number; selected: boolean } | null = null;
    for (const entry of this.placed) {
      if (only !== undefined && entry.item.id !== only) continue;
      const distance = this.distance(entry, p, slop);
      if (distance === null || distance > slop) continue;
      const mine = entry.item.id === this.selected;
      if (!best || distance < best.distance || (distance === best.distance && (mine || !best.selected))) best = { id: entry.item.id, distance, selected: mine };
    }
    return best && { id: best.id, handle: null };
  }

  updateAllViews() {
    const series = this.series;
    const items = this.preview && !this.items.some((item) => item.id === this.preview!.id) ? [...this.items, this.preview] : this.items;
    this.placed = items.map((stored) => {
      const item = this.preview?.id === stored.id ? this.preview : stored;
      const at = item.points.map((point) => {
        const y = series?.priceToCoordinate(point.price) ?? null;
        if (y === null) return null;
        if (item.kind === "level") return { x: 0, y };
        const logical = this.timeline.toLogical(point.time);
        const x = logical === null ? null : this.x(logical);
        return x === null ? null : { x, y };
      });
      const anchor = at[0];
      const box = item.kind === "note" && anchor ? { left: anchor.x, top: anchor.y - 10, right: anchor.x + textWidth(item.label) + 12, bottom: anchor.y + 10 } : null;
      return { item, at, box };
    });
    const key = `${this.selected}|${this.placed.map((entry) => entry.item.id).join(",")}`;
    if (key !== this.axisKey) {
      this.axisKey = key;
      // Levels and rays always label their price; the selected drawing labels each anchor's.
      this.axis = this.placed.flatMap(({ item }) => item.kind === "level" || item.kind === "ray" ? [this.axisView(item.id, 0)]
        : item.id === this.selected ? item.points.map((_, index) => this.axisView(item.id, index)) : []);
    }
  }

  paneViews() { return this.views; }

  priceAxisViews() { return this.axis; }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (!this.interactive) return null;
    const hit = this.hit(x, y, MOUSE_SLOP);
    if (!hit) return null;
    const kind = this.item(hit.id)?.kind;
    return { externalId: hit.id, zOrder: "top", cursorStyle: hit.handle !== null ? "pointer" : kind === "level" ? "ns-resize" : "move", hitTestPriority: 1 };
  }

  private update() {
    this.updateAllViews();
    this.requestUpdate?.();
  }

  private handlePoints({ item, at }: Placed): (Point | null)[] {
    if (item.kind === "level" || item.kind === "note") return item.kind === "note" ? [at[0]] : [];
    return HANDLES[item.kind].map(([time, price]) => at[time] && at[price] ? { x: at[time]!.x, y: at[price]!.y } : null);
  }

  /** The two ends of a trend line as drawn, extensions included, as a fraction range along it. */
  private span(item: Shown, a: Point, b: Point): [number, number] {
    const far = 4 * ((this.chart?.timeScale().width() ?? 2000) + 2000) / Math.max(1, Math.hypot(b.x - a.x, b.y - a.y));
    return [item.extendLeft ? -far : 0, item.extendRight ? 1 + far : 1];
  }

  private distance({ item, at, box }: Placed, p: Point, slop: number): number | null {
    const [a, b] = at;
    if (!a) return null;
    switch (item.kind) {
      case "level": return Math.abs(p.y - a.y);
      case "ray": return p.x >= a.x - slop ? Math.abs(p.y - a.y) : null;
      case "note": return box && p.x >= box.left - slop && p.x <= box.right + slop && p.y >= box.top - slop && p.y <= box.bottom + slop ? 0 : null;
      case "trend": { if (!b) return null; const [from, to] = this.span(item, a, b); return segmentDistance(p, a, b, from, to); }
      case "zone": {
        if (!b) return null;
        const [left, right, top, bottom] = [Math.min(a.x, b.x), Math.max(a.x, b.x), Math.min(a.y, b.y), Math.max(a.y, b.y)];
        const outside = Math.hypot(Math.max(left - p.x, 0, p.x - right), Math.max(top - p.y, 0, p.y - bottom));
        if (outside) return outside;
        // Inside: as far as the slop, so a line drawn over a zone wins.
        return Math.min(slop, p.x - left, right - p.x, p.y - top, bottom - p.y);
      }
    }
  }

  private axisView(id: string, index: number): ISeriesPrimitiveAxisView {
    const placed = () => this.placed.find((entry) => entry.item.id === id);
    const color = () => { const item = placed()?.item; return !item ? LINE : item.kind === "level" ? (id === this.selected ? SELECTED : LINE) : item.color; };
    return {
      coordinate: () => placed()?.at[index]?.y ?? -100,
      text: () => { const entry = placed(); return entry && this.series ? this.series.priceFormatter().format(entry.item.points[index].price) : ""; },
      textColor: () => placed()?.item.kind === "level" && id !== this.selected ? "#ffffff" : BACKGROUND,
      backColor: color,
      visible: () => placed()?.at[index] != null,
    };
  }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      const handle = (point: Point, color: string) => {
        context.beginPath();
        context.arc(Math.round(point.x * h), Math.round(point.y * v), Math.round(5 * h), 0, Math.PI * 2);
        context.fillStyle = BACKGROUND;
        context.fill();
        context.lineWidth = Math.max(1, Math.floor(2 * h));
        context.strokeStyle = color;
        context.stroke();
      };
      for (const entry of this.placed) {
        const { item, at, box } = entry;
        const [a, b] = at;
        if (!a) continue;
        const selected = item.id === this.selected;
        context.setLineDash([]);
        if (item.kind === "level") {
          if (a.y < -2 || a.y * v > bitmapSize.height + 2 * v) continue;
          const lineWidth = Math.max(1, Math.floor((selected ? 2 : 1) * v));
          const row = Math.round(a.y * v) + (lineWidth % 2 ? 0.5 : 0);
          context.strokeStyle = selected ? SELECTED : LINE;
          context.lineWidth = lineWidth;
          context.setLineDash(selected ? [] : [Math.round(4 * h), Math.round(3 * h)]);
          context.beginPath();
          context.moveTo(0, row);
          context.lineTo(bitmapSize.width, row);
          context.stroke();
          context.setLineDash([]);
          if (this.labels && item.label) {
            context.font = `${Math.round(10 * v)}px ${FONT}`;
            context.fillStyle = selected ? SELECTED : LINE;
            context.textAlign = "right";
            context.textBaseline = "bottom";
            context.fillText(item.label, bitmapSize.width - Math.round(6 * h), row - Math.round(3 * v));
          }
          // The handle: where the level reads as grabbable. The whole line drags.
          if (selected) handle({ x: bitmapSize.width / h / 2, y: a.y }, SELECTED);
          continue;
        }
        context.strokeStyle = item.color;
        context.lineWidth = Math.max(1, Math.floor(item.width * h));
        if (item.kind === "ray") {
          context.beginPath();
          context.moveTo(Math.round(a.x * h), Math.round(a.y * v));
          context.lineTo(bitmapSize.width, Math.round(a.y * v));
          context.stroke();
        } else if (item.kind === "trend" && b) {
          const [from, to] = this.span(item, a, b);
          const along = (t: number) => [Math.round((a.x + t * (b.x - a.x)) * h), Math.round((a.y + t * (b.y - a.y)) * v)] as const;
          context.beginPath();
          context.moveTo(...along(from));
          context.lineTo(...along(to));
          context.stroke();
        } else if (item.kind === "zone" && b) {
          const [left, top] = [Math.round(Math.min(a.x, b.x) * h), Math.round(Math.min(a.y, b.y) * v)];
          const [right, bottom] = [Math.round(Math.max(a.x, b.x) * h), Math.round(Math.max(a.y, b.y) * v)];
          context.fillStyle = `${item.color}26`;
          context.fillRect(left, top, right - left, bottom - top);
          context.lineWidth = Math.max(1, Math.floor(h));
          context.strokeRect(left + 0.5, top + 0.5, right - left, bottom - top);
        } else if (item.kind === "note" && box) {
          context.fillStyle = `${BACKGROUND}e6`;
          context.fillRect(Math.round(box.left * h), Math.round(box.top * v), Math.round((box.right - box.left) * h), Math.round((box.bottom - box.top) * v));
          context.lineWidth = Math.max(1, Math.floor((selected ? 2 : 1) * h));
          context.strokeRect(Math.round(box.left * h) + 0.5, Math.round(box.top * v) + 0.5, Math.round((box.right - box.left) * h), Math.round((box.bottom - box.top) * v));
          context.font = `${Math.round(11 * v)}px ${FONT}`;
          context.fillStyle = item.color;
          context.textAlign = "left";
          context.textBaseline = "middle";
          context.fillText(item.label, Math.round((box.left + 6) * h), Math.round(a.y * v));
        }
        if (selected) for (const point of this.handlePoints(entry)) if (point) handle(point, item.color);
      }
    });
  }
}

/** A drawing's prices on the chart's basis: every recorded split after `drawn_on` divides them, as it does the candles. */
export function drawingOnBasis(drawing: Drawing, splits: { ex_date: string; ratio: number }[]): Drawing {
  const factor = splits.reduce((product, split) => split.ex_date > drawing.drawn_on ? product * split.ratio : product, 1);
  return factor === 1 ? drawing : { ...drawing, points: drawing.points.map((point) => ({ ...point, price: point.price / factor })) };
}

/** Moving a whole drawing: whole bars along the time axis and any distance in price. Null if a price would not be positive. */
export function shiftPoints(points: Anchor[], timeline: Timeline, bars: number, price: number): Anchor[] | null {
  const next = points.map((point) => {
    const logical = timeline.toLogical(point.time);
    const time = logical === null ? null : timeline.toTime(logical + bars);
    return { time: time ?? point.time, price: roundPrice(point.price + price) };
  });
  return next.every((point) => point.price > 0) ? next : null;
}

