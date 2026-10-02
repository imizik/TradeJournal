import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, ISeriesPrimitiveAxisView, PrimitiveHoveredItem, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { PriceLevel } from "./charts";

/**
 * The drawing layer (C1.1): one series primitive on each chart's candles draws
 * the user's drawings and says which one the pointer is on. Drawings are
 * anchored to price (and, for C1.2's tools, time), never to pixels or bar
 * index, so every panel showing a symbol draws them at the same prices at any
 * zoom or interval. Today the one kind is the saved horizontal level.
 *
 * Edits are item-level (`LevelEdit`), so undo and redo replay onto whatever the
 * workspace holds now, including levels another device saved since.
 */

/** Pointer distance, in CSS pixels, that still counts as on a line. A finger gets a 28px band. */
export const MOUSE_SLOP = 6;
export const TOUCH_SLOP = 14;
/** Movement below this is a click or tap, not a drag. */
export const DRAG_START = 3;
export const MAX_LEVELS = 30;
/** Undo steps kept in this tab; edits are not saved to the server's history. */
export const MAX_UNDO = 100;

const LINE = "#659ef0";
const SELECTED = "#9cc2ff";
const BACKGROUND = "#10151e";

export type LevelDrawing = { id: string; price: number; label: string };
/** One level changed: added (no `before`), deleted (no `after`), or moved. `index` is where it sat. */
export type LevelEdit = { symbol: string; before: PriceLevel | null; after: PriceLevel | null; index: number };

/**
 * `levels` with one side of an edit applied: `after` replays it, `before` undoes it.
 * Null when that would put a symbol over the 30-level limit.
 */
export function applyLevelEdit(levels: Record<string, PriceLevel[]>, edit: LevelEdit, side: "before" | "after"): Record<string, PriceLevel[]> | null {
  const target = edit[side];
  const id = (edit.after ?? edit.before)!.id;
  const rows = levels[edit.symbol] ?? [];
  const at = rows.findIndex((row) => row.id === id);
  let next: PriceLevel[];
  if (!target) next = rows.filter((row) => row.id !== id);
  else if (at >= 0) next = rows.map((row) => row.id === id ? target : row);
  else if (rows.length >= MAX_LEVELS) return null;
  else next = [...rows.slice(0, edit.index), target, ...rows.slice(edit.index)];
  return { ...levels, [edit.symbol]: next };
}

type Placed = { level: LevelDrawing; y: number | null };
type Renderer = IPrimitivePaneRenderer;
type Target = Parameters<Renderer["draw"]>[0];

export class DrawingLayer implements ISeriesPrimitive<Time> {
  private levels: LevelDrawing[] = [];
  private selected: string | null = null;
  private labels = false;
  private interactive = true;
  /** A level being dragged is drawn here until the saved price comes back. */
  private preview: { id: string; price: number } | null = null;
  private placed: Placed[] = [];
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private axis: ISeriesPrimitiveAxisView[] = [];
  private readonly renderer: Renderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "top", renderer: () => this.renderer }];

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.series = null;
    this.requestUpdate = null;
  }

  /** What to draw. `labels` writes each level's name on the line (the main chart). */
  set(levels: LevelDrawing[], selected: string | null, labels: boolean) {
    const ids = levels.map((level) => level.id).join(",");
    if (ids !== this.levels.map((level) => level.id).join(",")) this.axis = levels.map((level) => this.axisView(level.id));
    this.levels = levels;
    this.selected = selected;
    this.labels = labels;
    this.preview = null;
    this.update();
  }

  /** Off while the chart places a new level by click, so the pointer is not taken for a drag. */
  setInteractive(on: boolean) { this.interactive = on; }

  setPreview(preview: { id: string; price: number } | null) {
    this.preview = preview;
    this.update();
  }

  /** The nearest level within `slop` pixels of `y`, or null. `only` restricts the search to one level. */
  hit(y: number, slop: number, only?: string | null): string | null {
    let best: { id: string; distance: number } | null = null;
    for (const { level, y: at } of this.placed) {
      if (at === null || (only !== undefined && level.id !== only)) continue;
      const distance = Math.abs(at - y);
      // On a tie the selected level wins, so a level under another can still be moved.
      if (distance <= slop && (!best || distance < best.distance || (distance === best.distance && level.id === this.selected))) best = { id: level.id, distance };
    }
    return best?.id ?? null;
  }

  /** Where a level is drawn now, in pixels from the top of the pane. */
  y(id: string): number | null { return this.placed.find((entry) => entry.level.id === id)?.y ?? null; }

  updateAllViews() {
    const series = this.series;
    this.placed = this.levels.map((level) => {
      const price = this.preview?.id === level.id ? this.preview.price : level.price;
      return { level: { ...level, price }, y: series?.priceToCoordinate(price) ?? null };
    });
  }

  paneViews() { return this.views; }

  priceAxisViews() { return this.axis; }

  hitTest(_x: number, y: number): PrimitiveHoveredItem | null {
    if (!this.interactive) return null;
    const id = this.hit(y, MOUSE_SLOP);
    return id ? { externalId: id, zOrder: "top", cursorStyle: "ns-resize", hitTestPriority: 1 } : null;
  }

  private update() {
    this.updateAllViews();
    this.requestUpdate?.();
  }

  private axisView(id: string): ISeriesPrimitiveAxisView {
    const placed = () => this.placed.find((entry) => entry.level.id === id);
    return {
      coordinate: () => placed()?.y ?? -100,
      text: () => { const entry = placed(); return entry && this.series ? this.series.priceFormatter().format(entry.level.price) : ""; },
      textColor: () => id === this.selected ? BACKGROUND : "#ffffff",
      backColor: () => id === this.selected ? SELECTED : LINE,
      visible: () => placed()?.y != null,
    };
  }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      for (const { level, y } of this.placed) {
        if (y === null || y < -2 || y * v > bitmapSize.height + 2 * v) continue;
        const selected = level.id === this.selected;
        const width = Math.max(1, Math.floor((selected ? 2 : 1) * v));
        const row = Math.round(y * v) + (width % 2 ? 0.5 : 0);
        context.strokeStyle = selected ? SELECTED : LINE;
        context.lineWidth = width;
        context.setLineDash(selected ? [] : [Math.round(4 * h), Math.round(3 * h)]);
        context.beginPath();
        context.moveTo(0, row);
        context.lineTo(bitmapSize.width, row);
        context.stroke();
        context.setLineDash([]);
        if (this.labels && level.label) {
          context.font = `${Math.round(10 * v)}px ui-sans-serif, system-ui, sans-serif`;
          context.fillStyle = selected ? SELECTED : LINE;
          context.textAlign = "right";
          context.textBaseline = "bottom";
          context.fillText(level.label, bitmapSize.width - Math.round(6 * h), row - Math.round(3 * v));
        }
        if (selected) {
          // The handle: where the level reads as grabbable. The whole line drags.
          context.beginPath();
          context.arc(Math.round(bitmapSize.width / 2), row, Math.round(5 * h), 0, Math.PI * 2);
          context.fillStyle = BACKGROUND;
          context.fill();
          context.lineWidth = Math.max(1, Math.floor(2 * h));
          context.strokeStyle = SELECTED;
          context.stroke();
        }
      }
    });
  }
}
