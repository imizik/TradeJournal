"use client";

import { useState } from "react";
import { ArrowLeftToLine, ArrowRightToLine, Palette, Trash2, X } from "lucide-react";
import { price } from "@/lib/charts";
import { NOTE_MAX, PALETTE, TOOL_NAMES } from "@/lib/drawings";
import type { Drawing, DrawingPatch, LineWidth } from "@/lib/drawings";

const square = "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded";
/** Style buttons: 24px, the smallest touch target the chart allows. */
const small = "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded";

/** What a drawing spans, in prices: shown beside its name. */
function summary(drawing: Drawing) {
  const [a, b] = drawing.points;
  if (drawing.kind === "ray") return price(a.price);
  if (drawing.kind === "trend") return `${price(a.price)} → ${price(b.price)}`;
  if (drawing.kind === "zone") return `${price(Math.min(a.price, b.price))}–${price(Math.max(a.price, b.price))}`;
  return null;
}

/**
 * The bar on the panel an item was selected on. A level shows its name, price
 * and Delete; a drawing adds a note's text and, behind Style, its color, line
 * width and trend-line extensions. Style stays folded so the bar is one row
 * and covers as little of the chart as a level's does. Every change is one
 * undo step, and a color or width becomes what that tool draws with next.
 */
export default function SelectionBar({ panel, level, drawing, focusText = false, onDelete, onDeselect, onEdit }: {
  panel: string; level?: { id: string; label: string; price: number }; drawing?: Drawing; focusText?: boolean;
  onDelete(): void; onDeselect(): void; onEdit?(patch: DrawingPatch): void;
}) {
  const [draft, setDraft] = useState(drawing?.text ?? "");
  const [styling, setStyling] = useState(false);
  if (level) return <div role="toolbar" aria-label={`Selected level on ${panel}`} className="absolute left-2 top-2 z-10 flex max-w-[calc(100%-5rem)] items-center gap-1 rounded-md border border-slate-600 bg-[#121924]/95 py-0.5 pl-2 pr-0.5 text-[11px] shadow-lg">
    <span className="h-0.5 w-3 shrink-0 bg-[#9cc2ff]" /><span className="min-w-0 truncate text-slate-300">{level.label}</span><span className="font-mono text-[#9cc2ff]">{price(level.price)}</span>
    <button aria-label="Delete selected level" title="Delete (Delete or Backspace)" onClick={onDelete} className={`${square} text-slate-400 hover:bg-slate-800 hover:text-rose-300`}><Trash2 size={13} /></button>
    <button aria-label="Deselect level" title="Deselect (Esc)" onClick={onDeselect} className={`${square} text-slate-400 hover:bg-slate-800 hover:text-slate-200`}><X size={13} /></button>
  </div>;
  if (!drawing) return null;
  const name = TOOL_NAMES[drawing.kind];
  const span = summary(drawing);
  const commit = () => { const text = draft.trim().slice(0, NOTE_MAX); if (text && text !== drawing.text) onEdit?.({ text }); else setDraft(drawing.text ?? ""); };
  return <div role="toolbar" aria-label={`Selected drawing on ${panel}`} className="absolute left-2 top-2 z-10 flex max-w-[calc(100%-5rem)] flex-col gap-0.5 rounded-md border border-slate-600 bg-[#121924]/95 py-0.5 pl-2 pr-0.5 text-[11px] shadow-lg">
    <div className="flex min-w-0 items-center gap-1">
      <span className="h-2 w-3 shrink-0 rounded-sm" style={{ background: drawing.color }} />
      <span className="shrink-0 text-slate-300">{name}</span>
      {span && <span className="min-w-0 truncate font-mono text-slate-400">{span}</span>}
      {drawing.kind === "note" && <input aria-label="Note text" value={draft} maxLength={NOTE_MAX} autoFocus={focusText} onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); else if (e.key === "Escape") { setDraft(drawing.text ?? ""); e.preventDefault(); e.stopPropagation(); } }}
        className="h-7 w-32 min-w-0 rounded border border-slate-700 bg-[#10151e] px-1.5 text-[11px] text-slate-200 outline-none focus:border-sky-600" />}
      <button aria-label="Style" aria-expanded={styling} title="Color, width and extensions" onClick={() => setStyling((v) => !v)} className={`${square} ml-auto ${styling ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}><Palette size={13} /></button>
      <button aria-label="Delete selected drawing" title="Delete (Delete or Backspace)" onClick={onDelete} className={`${square} text-slate-400 hover:bg-slate-800 hover:text-rose-300`}><Trash2 size={13} /></button>
      <button aria-label="Deselect drawing" title="Deselect (Esc)" onClick={onDeselect} className={`${square} text-slate-400 hover:bg-slate-800 hover:text-slate-200`}><X size={13} /></button>
    </div>
    {styling && <div role="group" className="flex flex-wrap items-center gap-1 pb-0.5" aria-label={`${name} style`}>
      {PALETTE.map(([color, label]) => <button key={color} aria-label={`${label} ${name.toLowerCase()}`} aria-pressed={drawing.color === color} title={label} onClick={() => onEdit?.({ color })}
        className={`${small} ${drawing.color === color ? "ring-1 ring-slate-200" : ""}`}><span className="h-3.5 w-3.5 rounded-full" style={{ background: color }} /></button>)}
      {(drawing.kind === "ray" || drawing.kind === "trend") && <span className="ml-1 flex items-center gap-0.5">
        {([1, 2, 3] as LineWidth[]).map((width) => <button key={width} aria-label={`Line width ${width}`} aria-pressed={drawing.width === width} title={`${width}px line`} onClick={() => onEdit?.({ width })}
          className={`${small} ${drawing.width === width ? "bg-slate-700" : "hover:bg-slate-800"}`}><span className="w-3.5 rounded-full bg-slate-300" style={{ height: width + 0.5 }} /></button>)}
      </span>}
      {drawing.kind === "trend" && <span className="ml-1 flex items-center gap-0.5">
        <button aria-label="Extend left" aria-pressed={!!drawing.extendLeft} title="Extend the line to the left" onClick={() => onEdit?.({ extendLeft: !drawing.extendLeft })}
          className={`${small} ${drawing.extendLeft ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800"}`}><ArrowLeftToLine size={13} /></button>
        <button aria-label="Extend right" aria-pressed={!!drawing.extendRight} title="Extend the line to the right" onClick={() => onEdit?.({ extendRight: !drawing.extendRight })}
          className={`${small} ${drawing.extendRight ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800"}`}><ArrowRightToLine size={13} /></button>
      </span>}
    </div>}
  </div>;
}
