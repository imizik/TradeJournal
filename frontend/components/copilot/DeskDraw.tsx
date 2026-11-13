"use client";

/*
 * The desk chart's drawings (docs/copilot-lab.md § The desk): the levels and drawings he made in Charts, kept in the
 * same shared chart settings (``useChartSettings``: one store, so Charts shows what is drawn here and the reverse), drawn
 * with Charts' drawing layer and moved with Charts' gestures (``lib/drawingGestures.ts``). The tools hide behind the
 * pencil: a horizontal line (a Charts level), a trend line and a zone; on a phone the line and Delete only. Undo is this
 * tab's, as in Charts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Minus, Pencil, Square, Trash2, TrendingUp, Undo2 } from "lucide-react";
import { cleanLevel, isMacroSymbol, todayNewYork, validSymbol } from "@/lib/charts";
import type { PriceLevel } from "@/lib/charts";
import { useChartSettings } from "@/lib/chartSync";
import { applyEdit, cleanDrawing, drawingShape, editName, levelShape, MAX_DRAWINGS, MAX_LEVELS, MAX_UNDO, TOOL_NAMES } from "@/lib/drawings";
import type { Anchor, Drawing, DrawingEdit, DrawingKind, DrawingPatch, Shown, Tool } from "@/lib/drawings";
import { readHotkey } from "@/lib/hotkeys";
import { cn } from "@/lib/utils";

const NO_LEVELS: PriceLevel[] = [];
const NO_DRAWINGS: Drawing[] = [];
/** A level's default name says nothing: the desk leaves it off the line, so the chart stays quiet. */
const DEFAULT_LABEL = /^Level \d+$/;

/** The desk's tools: Charts' price level (a horizontal line), trend line and zone. */
export type DeskTool = Extract<Tool, "level" | "trend" | "zone">;
const TOOLS: { tool: DeskTool; name: string; icon: typeof Minus; phone: boolean }[] = [
  { tool: "level", name: "Horizontal line", icon: Minus, phone: true },
  { tool: "trend", name: "Trend line", icon: TrendingUp, phone: false },
  { tool: "zone", name: "Zone", icon: Square, phone: false },
];

/** What the layer draws for this symbol: shown levels and drawings, the hidden ones and hidden groups left out (as in Charts).
 * ``thin``: a Grid tile's, one pixel wide and without notes. */
export function deskShapes(levels: PriceLevel[], drawings: Drawing[], hidden: { levels: boolean; drawings: boolean }, thin = false): Shown[] {
  const out: Shown[] = [];
  if (!hidden.levels) for (const level of levels) if (!level.hidden) out.push(levelShape({ ...level, label: DEFAULT_LABEL.test(level.label) ? "" : level.label }));
  if (!hidden.drawings) for (const drawing of drawings) if (!drawing.hidden && !(thin && drawing.kind === "note")) out.push(thin ? { ...drawingShape(drawing), width: 1 } : drawingShape(drawing));
  return out;
}

/** "Level 3", "Trend line": what a selected item is called. */
export function itemName(item: PriceLevel | Drawing): string {
  return "kind" in item ? TOOL_NAMES[item.kind] : item.label || "Horizontal line";
}

/**
 * The symbol's levels and drawings from the shared chart settings, and the edits the desk makes to them: each one an
 * undo step (Charts' ``applyEdit``), saved through the same sync as the workspace's.
 */
export function useDeskDrawings(symbol: string | null) {
  const { settings, setSettings, ready } = useChartSettings();
  const usable = !!symbol && validSymbol(symbol) && !isMacroSymbol(symbol);
  const levels = (usable && settings.levels[symbol!]) || NO_LEVELS;
  const drawings = (usable && settings.drawings[symbol!]) || NO_DRAWINGS;
  const hidden = settings.hiddenGroups;
  const [history, setHistory] = useState<{ undo: DrawingEdit[]; redo: DrawingEdit[] }>({ undo: [], redo: [] });
  const [error, setError] = useState("");
  const latest = useRef(settings);
  useEffect(() => { latest.current = settings; }, [settings]);

  const edit = useCallback((change: DrawingEdit) => {
    // A new level or drawing is never placed out of sight (as in Charts).
    const added = change.layer !== "batch" && !change.before ? change.layer : null;
    setSettings(s => {
      const next = applyEdit(s, change, "after") ?? s;
      return added && next.hiddenGroups[added] ? { ...next, hiddenGroups: { ...next.hiddenGroups, [added]: false } } : next;
    });
    setHistory(h => ({ undo: [...h.undo, change].slice(-MAX_UNDO), redo: [] }));
    setError("");
  }, [setSettings]);

  const replay = useCallback((side: "before" | "after") => {
    const change = (side === "before" ? history.undo : history.redo).at(-1);
    if (!change) return null;
    if (!applyEdit(latest.current, change, side)) {
      setError(`Remove a ${change.symbol} ${change.layer === "levels" ? "line" : "drawing"} first: ${change.layer === "levels" ? MAX_LEVELS : MAX_DRAWINGS} per symbol.`);
      return null;
    }
    setSettings(s => applyEdit(s, change, side) ?? s);
    setHistory(h => side === "before" ? { undo: h.undo.slice(0, -1), redo: [...h.redo, change] } : { undo: [...h.undo, change], redo: h.redo.slice(0, -1) });
    setError("");
    return change;
  }, [history, setSettings]);

  const addLevel = useCallback((value: number): string | null => {
    if (!usable || !Number.isFinite(value) || value <= 0) return null;
    if (levels.length >= MAX_LEVELS) { setError(`Remove a ${symbol} line before adding another (${MAX_LEVELS} per symbol).`); return null; }
    const level = cleanLevel({ id: crypto.randomUUID(), price: value, label: `Level ${levels.length + 1}`, drawn_on: todayNewYork() });
    if (!level) return null;
    edit({ symbol: symbol!, layer: "levels", before: null, after: level, index: levels.length });
    return level.id;
  }, [usable, levels, symbol, edit]);

  const place = useCallback((kind: DrawingKind, points: Anchor[]): string | null => {
    if (!usable) return null;
    if (drawings.length >= MAX_DRAWINGS) { setError(`Remove a ${symbol} drawing before adding another (${MAX_DRAWINGS} per symbol).`); return null; }
    const style = settings.toolStyles[kind];
    const drawing = cleanDrawing({ id: crypto.randomUUID(), kind, points, color: style.color, width: style.width, drawn_on: todayNewYork() });
    if (!drawing) return null;
    edit({ symbol: symbol!, layer: "drawings", before: null, after: drawing, index: drawings.length });
    return drawing.id;
  }, [usable, drawings, symbol, settings.toolStyles, edit]);

  // A dragged level saves the price it was dropped at, dated today: that is the basis the chart shows.
  const moveLevel = useCallback((id: string, value: number) => {
    const index = levels.findIndex(row => row.id === id);
    if (index < 0 || !Number.isFinite(value) || value <= 0 || Math.abs(levels[index].price - value) < 0.005) return;
    edit({ symbol: symbol!, layer: "levels", before: levels[index], after: cleanLevel({ ...levels[index], price: value, drawn_on: todayNewYork() })!, index });
  }, [levels, symbol, edit]);

  const editDrawing = useCallback((id: string, patch: DrawingPatch) => {
    const index = drawings.findIndex(row => row.id === id);
    if (index < 0) return;
    const before = drawings[index];
    const after = cleanDrawing({ ...before, ...patch, ...(patch.points ? { drawn_on: todayNewYork() } : {}) });
    if (!after || JSON.stringify(after) === JSON.stringify(before)) return;
    edit({ symbol: symbol!, layer: "drawings", before, after, index });
  }, [drawings, symbol, edit]);

  const remove = useCallback((id: string): string | null => {
    const level = levels.findIndex(row => row.id === id);
    const drawing = drawings.findIndex(row => row.id === id);
    if (level >= 0) { edit({ symbol: symbol!, layer: "levels", before: levels[level], after: null, index: level }); return itemName(levels[level]); }
    if (drawing >= 0) { edit({ symbol: symbol!, layer: "drawings", before: drawings[drawing], after: null, index: drawing }); return itemName(drawings[drawing]); }
    return null;
  }, [levels, drawings, symbol, edit]);

  const find = useCallback((id: string | null): PriceLevel | Drawing | null =>
    id ? levels.find(row => row.id === id) ?? drawings.find(row => row.id === id) ?? null : null, [levels, drawings]);

  const shapes = useMemo(() => deskShapes(levels, drawings, hidden), [levels, drawings, hidden]);
  return {
    ready, usable, levels, drawings, shapes, magnet: settings.magnet, toolStyles: settings.toolStyles, error, setError,
    addLevel, place, moveLevel, editDrawing, remove, find,
    undo: () => replay("before"), redo: () => replay("after"),
    canUndo: history.undo.length > 0, undoName: history.undo.length ? editName(history.undo.at(-1)!) : null,
  };
}
export type DeskDrawings = ReturnType<typeof useDeskDrawings>;

/**
 * Delete, Backspace and Cmd/Ctrl+Z (Shift for redo) while drawing, as in Charts (``readHotkey``); Escape drops the armed
 * tool, else the selection, else leaves drawing. Ignored while typing in a field. Taken before the desk's own keys.
 */
export function useDrawKeys(on: boolean, handlers: { remove(): void; undo(): void; redo(): void; escape(): void }) {
  const latest = useRef(handlers);
  useEffect(() => { latest.current = handlers; });
  useEffect(() => {
    if (!on) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.closest("input, textarea, select, [contenteditable='true']") || target.closest("[role='dialog']"))) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); latest.current.escape(); return; }
      const key = readHotkey(event, "");
      if (!key || (key.kind !== "delete" && key.kind !== "undo" && key.kind !== "redo")) return;
      event.preventDefault();
      event.stopPropagation();
      if (key.kind === "delete") latest.current.remove();
      else if (key.kind === "undo") latest.current.undo();
      else latest.current.redo();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [on]);
}

/** The pencil in the chart's header: opens and closes the drawing tools. */
export function PencilButton({ on, disabled, count, onToggle }: { on: boolean; disabled: boolean; count: number; onToggle(): void }) {
  return (
    <button type="button" aria-pressed={on} onClick={onToggle} disabled={disabled} data-testid="desk-draw-toggle"
      aria-label={on ? "Done drawing" : "Draw on the chart"}
      title={disabled ? "Drawing needs a stock or ETF chart" : on ? "Done drawing" : `Draw a line, trend line or zone (saved with your Charts drawings${count ? `; ${count} on this symbol` : ""})`}
      className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded border px-1.5 text-xs disabled:opacity-40 sm:min-h-0 sm:min-w-0 sm:py-0.5",
        on ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
      <Pencil size={13} aria-hidden />
    </button>
  );
}

/** The drawing tools, shown while the pencil is on (the pencil again closes them): the three tools (the line only on a
 * phone), Delete for the selected item, and Undo (not on a phone: a deleted line's message offers Undo there). */
export function DrawBar({ narrow, tool, selected, canUndo, undoName, second, onTool, onDelete, onUndo }: {
  narrow: boolean; tool: DeskTool | null; selected: string | null; canUndo: boolean; undoName: string | null; second: boolean;
  onTool(tool: DeskTool): void; onDelete(): void; onUndo(): void;
}) {
  const button = "inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded border px-2 text-xs sm:min-h-0 sm:min-w-0 sm:py-0.5";
  const hint = tool ? (second ? (tool === "trend" ? "Click the second point" : "Click the opposite corner")
    : tool === "level" ? (narrow ? "Tap a price" : "Click a price") : tool === "trend" ? "Click the first point" : "Click one corner")
    : selected ? (narrow ? "Drag to move" : "Drag to move · Delete removes") : (narrow ? "Tap a line to select it" : "Click a line to select it, drag to move");
  return (
    <div role="toolbar" aria-label="Drawing tools" data-testid="desk-draw-bar" className="flex flex-wrap items-center gap-1 text-xs">
      {TOOLS.filter(t => !narrow || t.phone).map(({ tool: one, name, icon: Icon }) => (
        <button key={one} type="button" aria-pressed={tool === one} onClick={() => onTool(one)} aria-label={name} title={name}
          className={cn(button, tool === one ? "border-foreground/60 bg-secondary text-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
          <Icon size={13} aria-hidden />{!narrow || one === "level" ? <span>{one === "level" ? "Line" : name}</span> : null}
        </button>
      ))}
      <button type="button" onClick={onDelete} disabled={!selected} aria-label="Delete the selected line"
        className={cn(button, "border-border text-muted-foreground hover:text-rose-300 disabled:opacity-40")}><Trash2 size={13} aria-hidden />{narrow ? null : <span>Delete</span>}</button>
      {!narrow && (
        <button type="button" onClick={onUndo} disabled={!canUndo} aria-label={undoName ? `Undo ${undoName}` : "Undo"} title={undoName ? `Undo ${undoName} (Cmd/Ctrl+Z)` : "Nothing to undo"}
          className={cn(button, "border-border text-muted-foreground hover:text-foreground disabled:opacity-40")}><Undo2 size={13} aria-hidden /><span>Undo</span></button>
      )}
      <span role="status" className="min-w-0 truncate px-1 text-muted-foreground">{hint}</span>
    </div>
  );
}
