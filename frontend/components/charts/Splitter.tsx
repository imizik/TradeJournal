"use client";

import { useEffect, useRef, useState } from "react";

/** One drag in progress: `move` shows each position, `end` keeps the last one or puts the divider back. */
export type SplitDrag = { move(delta: number): void; end(keep: boolean): void };

/**
 * A divider in the chart workspace (C7.4): between the main chart and the
 * smaller row, between two smaller charts, or at the dock's edge. Drag it with
 * a mouse, pen or finger, or focus it and use the arrow keys (Shift for bigger
 * steps), Home and End for its limits, and Enter or a double-click to reset it.
 * Escape during a drag puts it back, before the workspace's own Escape sees the
 * key. A drag previews by writing sizes straight to the page (`onDrag`'s
 * session), so nothing re-renders until it ends and is saved once.
 */
export default function Splitter({ label, orientation, now, min, max, text, className = "", onDrag, onStep, onEdge, onReset }: {
  label: string;
  /** "horizontal": a bar between a part above and a part below, moved up and down. */
  orientation: "horizontal" | "vertical";
  /** What a screen reader announces: the value and its range, and optionally words for it. */
  now: number; min: number; max: number; text?: string;
  className?: string;
  /** Measure and start a drag; null when there is no room to resize. */
  onDrag(): SplitDrag | null;
  /** An arrow key: +1 is down or right, -1 up or left, five times that with Shift. */
  onStep(by: number): void;
  onEdge(to: "min" | "max"): void;
  onReset(): void;
}) {
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ session: SplitDrag; pointer: number; from: number; at: number; frame: number } | null>(null);
  const finish = useRef((keep: boolean) => {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    cancelAnimationFrame(current.frame);
    current.session.end(keep);
    setDragging(false);
  });
  useEffect(() => {
    if (!dragging) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      finish.current(false);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [dragging]);
  useEffect(() => () => finish.current(false), []);
  const vertical = orientation === "vertical";
  const along = (event: React.PointerEvent) => vertical ? event.clientX : event.clientY;

  return <div role="separator" tabIndex={0} aria-label={label} aria-orientation={orientation} aria-valuenow={now} aria-valuemin={min} aria-valuemax={max} aria-valuetext={text}
    title={`${label}: drag, or use the arrow keys. Double-click or Enter resets it.`} data-dragging={dragging || undefined}
    onPointerDown={(event) => {
      if (event.button !== 0 || drag.current) return;
      const session = onDrag();
      if (!session) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { session, pointer: event.pointerId, from: along(event), at: along(event), frame: 0 };
      setDragging(true);
    }}
    onPointerMove={(event) => {
      const current = drag.current;
      if (!current || event.pointerId !== current.pointer) return;
      current.at = along(event);
      // One layout per frame however fast the pointer reports.
      if (!current.frame) current.frame = requestAnimationFrame(() => { current.frame = 0; current.session.move(current.at - current.from); });
    }}
    onPointerUp={(event) => {
      const current = drag.current;
      if (!current || event.pointerId !== current.pointer) return;
      current.at = along(event);
      current.session.move(current.at - current.from);
      finish.current(current.at !== current.from); // a click, or each half of a double-click, changes nothing
    }}
    // The browser took the pointer (a gesture, a lost window): the drag ends where it was.
    onPointerCancel={() => { if (drag.current) finish.current(drag.current.at !== drag.current.from); }}
    onLostPointerCapture={() => { if (drag.current) finish.current(drag.current.at !== drag.current.from); }}
    onDoubleClick={onReset}
    onKeyDown={(event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return; // Alt+arrows step the watchlist from anywhere
      const back = vertical ? "ArrowLeft" : "ArrowUp";
      const ahead = vertical ? "ArrowRight" : "ArrowDown";
      if (event.key === back || event.key === ahead) onStep((event.key === ahead ? 1 : -1) * (event.shiftKey ? 5 : 1));
      else if (event.key === "Home") onEdge("min");
      else if (event.key === "End") onEdge("max");
      else if (event.key === "Enter") onReset();
      else return;
      // Handled here: the workspace's hotkeys (End, Enter for a typed interval) leave it alone.
      event.preventDefault();
    }}
    className={`relative z-10 shrink-0 touch-none select-none outline-none transition-colors before:absolute before:content-[''] ${vertical
      ? "cursor-col-resize before:-inset-x-[3px] before:inset-y-0"
      : "cursor-row-resize before:-inset-y-[3px] before:inset-x-0"} ${dragging ? "bg-sky-400/70" : "hover:bg-sky-400/40 focus-visible:bg-sky-400/70"} ${className}`} />;
}
