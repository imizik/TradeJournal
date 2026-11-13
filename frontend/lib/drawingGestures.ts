import type { IChartApi, ISeriesApi, SeriesType, Time } from "lightweight-charts";
import { DRAG_START, levelShape, MOUSE_SLOP, moveHandle, POINTS, roundPrice, shiftPoints, TOUCH_SLOP } from "./drawings";
import type { Anchor, DrawingKind, DrawingLayer, DrawingPatch, Shown, Timeline, Tool, ToolStyle } from "./drawings";

/**
 * Placing, selecting and dragging levels and drawings with the mouse or a finger (C1.1, C1.2), shared by the Charts
 * workspace's charts and the desk's chart, so both behave the same. The chart owns its own event wiring for anything
 * else (menus, long presses, marks); it hands its presses here first.
 *
 * Levels and drawings drag in front of the chart: a press on one never reaches the library, so the chart does not pan
 * under it. A mouse drags any item; a finger drags only the selected one, so panning across a drawing never moves it. A
 * press on a selected drawing's handle moves that anchor; anywhere else on it moves the whole drawing by whole bars, and
 * with the magnet the anchor nearest the press (`anchor`) snaps. `offset` keeps a level where it was grabbed, so it
 * moves by the drag instead of jumping to the pointer.
 *
 * An armed tool reads its own clicks and taps. The library holds back a second click that follows the first within its
 * double-click time, which would lose a quick second point of a trend line or zone. A press that moves is a pan, not a
 * placement.
 */
export type GestureActions = {
  /** The tool the next click places with. */
  tool: Tool | null;
  /** Nothing is placed or dragged while true (the chart is loading, or editing is off). */
  pending: boolean;
  selected: string | null;
  magnet: boolean;
  toolStyle?: ToolStyle;
  onSelect?(id: string | null): void;
  onMove?(id: string, price: number): void;
  onEditDrawing?(id: string, patch: DrawingPatch): void;
  onDraw?(price: number): void;
  onPlace?(kind: DrawingKind, points: Anchor[]): void;
};

type Drag = { id: string; handle: number | null; anchor: number; touch: number | null; from: { x: number; y: number }; base: Shown; offset: number; result: Shown | null; moved: boolean };

export type DrawingGestures = ReturnType<typeof drawingGestures>;

export function drawingGestures({ element, chart, candles, layer, timeline, actions, onSecond }: {
  element: HTMLElement; chart: IChartApi; candles: ISeriesApi<SeriesType, Time>; layer: DrawingLayer; timeline: Timeline;
  actions(): GestureActions;
  /** A two-point tool's first point is down (true) or the placement ended (false): the chart's hint changes. */
  onSecond(second: boolean): void;
}) {
  // A two-point tool's first click, kept until the second.
  let placing: { kind: DrawingKind; first: Anchor } | null = null;
  let drag: Drag | null = null;
  let press: { x: number; y: number; touch: number | null; held: boolean } | null = null;
  // The magnet is on, or Cmd/Ctrl is held for this click or move.
  const magnetOn = (held: boolean) => actions().magnet || held;
  const modifier = (event?: { metaKey: boolean; ctrlKey: boolean }) => !!(event?.metaKey || event?.ctrlKey);
  const ghost = (kind: Tool, points: Anchor[]) => {
    const style = actions().toolStyle;
    layer.setPreview(kind === "level" ? levelShape({ id: "placing", price: points[0].price, label: "" })
      : { id: "placing", kind, points, label: kind === "note" ? "Note" : "", color: style?.color ?? "#9cc2ff", width: style?.width ?? 1 });
  };
  const local = (clientX: number, clientY: number) => { const box = element.getBoundingClientRect(); return { x: clientX - box.left, y: clientY - box.top }; };
  const onPlot = (x: number, y: number) => x >= 0 && x <= chart.timeScale().width() && y >= 0 && y <= chart.panes()[0].getHeight();
  const inPane = (y: number) => Math.max(0, Math.min(chart.panes()[0].getHeight(), y));
  const priceAt = (y: number) => {
    const value = candles.coordinateToPrice(inPane(y));
    return value === null || roundPrice(value) <= 0 ? null : roundPrice(value);
  };
  const grab = (x: number, y: number, touch: number | null) => {
    const now = actions();
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
    if (done.base.kind === "level") actions().onMove?.(done.id, done.result.points[0].price);
    else actions().onEditDrawing?.(done.id, { points: done.result.points });
    window.setTimeout(() => { if (!drag) layer.setPreview(null); }, 1000);
  };
  const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape" && drag) { event.preventDefault(); event.stopPropagation(); finish(false); } };
  const place = (x: number, y: number, held: boolean) => {
    const now = actions();
    const kind = now.tool;
    if (!kind) return;
    // Placed at the middle of the nearest bar, or with the magnet at its nearest open, high, low or close.
    const point = layer.anchorAt(x, y, magnetOn(held));
    if (kind === "level") { const value = point?.price ?? priceAt(y); if (value !== null) now.onDraw?.(value); return; }
    if (!point) return;
    if (POINTS[kind] === 1) { now.onPlace?.(kind, [point]); return; }
    const first = placing?.kind === kind ? placing.first : null;
    if (!first) { placing = { kind, first: point }; onSecond(true); ghost(kind, [point, point]); return; }
    if (first.time === point.time && first.price === point.price) return; // a second click on the first point
    placing = null;
    onSecond(false);
    layer.setPreview(null);
    now.onPlace?.(kind, [first, point]);
  };
  const pressTool = (x: number, y: number, touch: number | null, held: boolean) => {
    if (!actions().tool || actions().pending || !onPlot(x, y)) return false;
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
  const onMouseMove = (event: MouseEvent) => { const at = local(event.clientX, event.clientY); follow(at.x, at.y, modifier(event)); };
  const onMouseUp = () => finish(true);
  const ours = (event: TouchEvent) => drag?.touch != null ? [...event.changedTouches].find((touch) => touch.identifier === drag!.touch) : undefined;

  return {
    local, onPlot, priceAt, magnetOn, modifier,
    dragging: () => drag !== null,
    /** Drop a drag without saving it (a long press opened a menu, a second finger came down, the chart went away). */
    cancel: () => finish(false),
    /** A mousedown on the chart, in the capture phase: arms a placement or starts a drag (then the chart does not see it). */
    mouseDown(event: MouseEvent) {
      if (event.button !== 0 || drag) return;
      const at = local(event.clientX, event.clientY);
      if (pressTool(at.x, at.y, null, modifier(event))) { window.addEventListener("mouseup", onPlaceUp); return; }
      if (!grab(at.x, at.y, null)) return;
      event.stopPropagation();
      event.preventDefault();
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    /** A single finger down: arms a placement, or grabs the selected item. True when the chart must not see it. */
    touchStart(touch: Touch): boolean {
      const at = local(touch.clientX, touch.clientY);
      if (pressTool(at.x, at.y, touch.identifier, false)) return false;
      return grab(at.x, at.y, touch.identifier);
    },
    /** A finger moving: drags the grabbed item (the page must not scroll under it). True when it was the dragging finger. */
    touchMove(event: TouchEvent): boolean {
      const touch = ours(event);
      if (!touch) return false;
      event.preventDefault();
      event.stopPropagation();
      const at = local(touch.clientX, touch.clientY);
      follow(at.x, at.y, false);
      return true;
    },
    /** A finger lifted or cancelled: a still tap places; a drag saves (or, cancelled, does not). */
    touchEnd(event: TouchEvent) {
      const tapped = press?.touch != null ? [...event.changedTouches].find((touch) => touch.identifier === press!.touch) : undefined;
      if (tapped) { const at = local(tapped.clientX, tapped.clientY); if (event.type === "touchend") release(at.x, at.y, 10); else press = null; }
      if (ours(event)) { event.stopPropagation(); finish(event.type === "touchend"); }
    },
    /** The pointer over the chart with a tool armed: preview what a click would place, where the magnet would put it. */
    hover(point: { x: number; y: number } | null, held: boolean) {
      const kind = actions().tool;
      if (!kind) return;
      const anchor = point ? layer.anchorAt(point.x, point.y, magnetOn(held)) : null;
      if (placing) { if (anchor) ghost(placing.kind, [placing.first, anchor]); }
      else if (anchor && kind !== "trend" && kind !== "zone") ghost(kind, [anchor]);
      else layer.setPreview(null);
    },
    /** Arming, switching or dropping a tool forgets a half-placed drawing. */
    forget(tool: Tool | null) {
      if (!placing && !tool) return;
      placing = null;
      onSecond(false);
      layer.setPreview(null);
    },
    /** The chart is going away. */
    detach() {
      finish(false);
      window.removeEventListener("mouseup", onPlaceUp);
    },
  };
}
