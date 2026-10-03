"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Pencil, RefreshCw, RotateCcw, Trash2, X } from "lucide-react";
import { LAYOUT_NAME_MAX, MAX_LAYOUTS, layoutName, layoutSummary, nameTaken, sameArrangement } from "@/lib/charts";
import type { Arrangement, SavedLayout } from "@/lib/charts";

const small = "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-100 disabled:opacity-30 disabled:hover:bg-transparent sm:h-8 sm:w-8";
const field = "h-9 min-w-0 flex-1 rounded border border-slate-700 bg-[#10151e] px-2 text-xs text-slate-100 outline-none focus:border-sky-600";

/**
 * Named layouts: pick one to arrange the panels that way, save the current
 * arrangement, rename, replace or delete. A bottom sheet on a phone. It reads
 * and writes only the arrangement (intervals, held symbols, chart sizes,
 * linked ranges); symbols, levels and the watchlist are untouched by every
 * action. On a wide screen it also puts the dividers back (C7.4).
 */
export default function LayoutMenu({ layouts, current, onApply, onSave, onRename, onUpdate, onDelete, onResetSizes, onClose }: {
  /** Each with its proportions, so the one in use is found by its chart sizes too. */
  layouts: (SavedLayout & Arrangement)[]; current: Arrangement;
  onApply(id: string): void; onSave(name: string): void; onRename(id: string, name: string): void;
  onUpdate(id: string): void; onDelete(id: string): void; onResetSizes?(): void; onClose(): void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  // One row at a time is being renamed or asked to confirm its deletion.
  const [editing, setEditing] = useState<{ id: string; kind: "rename" | "delete"; value: string } | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { dialog.current?.focus(); }, []);
  // Escape closes from wherever focus is: deleting or renaming removes the focused button.
  // The rename field handles its own Escape and stops it there.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); onClose(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const problem = (value: string, exceptId?: string) => {
    if (!value) return "Enter a name for this layout.";
    if (nameTaken(layouts, value, exceptId)) return `A layout named ${value} already exists.`;
    return "";
  };
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    const value = layoutName(name);
    const refused = layouts.length >= MAX_LAYOUTS ? `Delete a layout before saving another (${MAX_LAYOUTS} at most).` : problem(value);
    if (refused) { setError(refused); return; }
    onSave(value); setName(""); setError("");
  };
  const rename = (event: React.FormEvent) => {
    event.preventDefault();
    if (editing?.kind !== "rename") return;
    const value = layoutName(editing.value);
    const refused = problem(value, editing.id);
    if (refused) { setError(refused); return; }
    onRename(editing.id, value); setEditing(null); setError("");
  };
  const edit = (next: typeof editing) => { setEditing(next); setError(""); };

  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:items-start sm:px-4 sm:pb-0 sm:pt-[12vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Saved layouts"
        className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-xl border border-slate-700 bg-[#121924] shadow-2xl outline-none">
        <div className="flex items-center justify-between border-b border-slate-700/60 px-3 py-2.5">
          <h2 className="text-xs font-medium text-slate-200">Layouts <span className="ml-1 text-slate-500">{layouts.length}/{MAX_LAYOUTS}</span></h2>
          <button className={small} aria-label="Close layouts" onClick={onClose}><X size={14} /></button>
        </div>

        {layouts.length > MAX_LAYOUTS && <p className="border-b border-slate-700/60 px-4 py-2 text-[11px] leading-4 text-amber-300">Two devices each saved a layout at the limit, so both are kept. Delete one before saving another.</p>}
        <ul aria-label="Saved layouts list" className="py-1">
          {layouts.map((layout) => {
            const active = sameArrangement(layout, current);
            const row = editing?.id === layout.id ? editing : null;
            if (row?.kind === "rename") return <li key={layout.id} className="px-3 py-1.5">
              <form onSubmit={rename} className="flex items-center gap-1">
                <input aria-label={`Rename ${layout.name}`} autoFocus value={row.value} maxLength={LAYOUT_NAME_MAX} className={field}
                  onChange={(e) => edit({ ...row, value: e.target.value })} onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); edit(null); } }} />
                <button type="submit" className={small} aria-label={`Save name for ${layout.name}`}><Check size={14} /></button>
                <button type="button" className={small} aria-label="Cancel rename" onClick={() => edit(null)}><X size={14} /></button>
              </form>
            </li>;
            if (row?.kind === "delete") return <li key={layout.id} className="flex items-center gap-1 px-3 py-1.5">
              <span className="min-w-0 flex-1 truncate text-xs text-slate-300">Delete {layout.name}?</span>
              <button className="h-9 rounded-md bg-rose-500/15 px-3 text-xs text-rose-200 hover:bg-rose-500/25 sm:h-8" onClick={() => { onDelete(layout.id); edit(null); }}>Delete</button>
              <button className="h-9 rounded-md px-3 text-xs text-slate-300 hover:bg-slate-800 sm:h-8" onClick={() => edit(null)}>Keep</button>
            </li>;
            return <li key={layout.id} className="flex items-center gap-0.5 px-2">
              <button onClick={() => onApply(layout.id)} aria-current={active || undefined} aria-label={`Use layout ${layout.name}`}
                className={`flex min-h-11 min-w-0 flex-1 flex-col justify-center rounded-md px-2 py-1.5 text-left hover:bg-slate-800/60 ${active ? "bg-sky-400/10" : ""}`}>
                <span className="flex items-center gap-1.5 text-xs font-medium text-slate-100"><span className="truncate">{layout.name}</span>{active && <span className="inline-flex shrink-0 items-center gap-0.5 text-[10px] font-normal text-sky-300"><Check size={11} />In use</span>}</span>
                <span className="truncate font-mono text-[10px] text-slate-500">{layoutSummary(layout)}</span>
              </button>
              <button className={small} aria-label={`Update ${layout.name} with the current arrangement`} title="Replace with the current arrangement" disabled={active} onClick={() => onUpdate(layout.id)}><RefreshCw size={13} /></button>
              <button className={small} aria-label={`Rename ${layout.name}`} title="Rename" onClick={() => edit({ id: layout.id, kind: "rename", value: layout.name })}><Pencil size={13} /></button>
              <button className={`${small} hover:text-rose-300`} aria-label={`Delete ${layout.name}`} title="Delete" onClick={() => edit({ id: layout.id, kind: "delete", value: "" })}><Trash2 size={13} /></button>
            </li>;
          })}
          {!layouts.length && <li className="px-4 py-3 text-xs leading-5 text-slate-500">No saved layouts yet. Arrange the charts, then save them below, for example &ldquo;0DTE SPY&rdquo; or &ldquo;Names&rdquo;.</li>}
        </ul>

        <form onSubmit={save} className="space-y-2 border-t border-slate-700/60 p-3">
          <label htmlFor="layout-name" className="block text-[11px] text-slate-400">Save the current arrangement as</label>
          <div className="flex gap-2">
            <input id="layout-name" aria-label="Layout name" value={name} maxLength={LAYOUT_NAME_MAX} placeholder="Layout name" className={field} onChange={(e) => { setName(e.target.value); setError(""); }} />
            <button type="submit" className="h-9 shrink-0 rounded-md border border-slate-700/60 px-3 text-xs hover:bg-slate-800 sm:h-8">Save layout</button>
          </div>
          {error && <p role="alert" className="text-[11px] text-amber-300">{error}</p>}
          <p className="text-[10px] leading-4 text-slate-500">A layout keeps the intervals, the symbols charts hold, the chart sizes and linked time ranges. The main symbol, levels and watchlist stay as they are.</p>
        </form>
        {onResetSizes && <div className="flex items-center justify-between gap-2 border-t border-slate-700/60 px-3 py-2">
          <span className="text-[10px] leading-4 text-slate-500">Dividers moved too far? Put every chart and the side panel back to their default sizes.</span>
          <button className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-slate-700/60 px-2.5 text-xs hover:bg-slate-800" onClick={onResetSizes}><RotateCcw size={12} />Reset chart sizes</button>
        </div>}
      </div>
    </div>
  );
}
