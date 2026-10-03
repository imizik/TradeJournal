"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Eye, EyeOff, Lock, LockOpen, Trash2, X } from "lucide-react";
import Sheet from "./Sheet";

/** One level or drawing in the panel. `name` and `detail` ("Breakout", "256.00") name its buttons. */
export type LayerItem = { id: string; symbol: string; name: string; detail: string; color: string; line: boolean; hidden: boolean; locked: boolean };
export type ItemGroup = "levels" | "drawings";
export type LayerGroup =
  | { key: ItemGroup; name: string; noun: string; hidden: boolean; items: LayerItem[] }
  | { key: "journal"; name: string; hidden: boolean; note: string }
  | { key: "indicators"; name: string; hidden: boolean; studies: { key: string; label: string; on: boolean }[] };

const COLLAPSED_KEY = "tradejournal.charts.layers.collapsed.v1";
function readCollapsed(): string[] {
  try { const value = JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? "null"); return Array.isArray(value) ? value.filter((key) => typeof key === "string") : ["indicators"]; }
  catch { return ["indicators"]; }
}

/**
 * The layers panel (C1.4): what the charts draw, grouped as My levels,
 * Drawings, Journal and Indicators. Every group hides on all five charts;
 * levels and drawings also lock and delete as a group (one undo step) and
 * item by item, and a click on an item brings the chart to it. Groups fold
 * (remembered on this device). A tab of the side dock on a desktop (C7.3); a
 * bottom sheet with 44px targets on a phone. Auto levels and options join
 * when their layers exist (C2.3, C4.4).
 */
export default function LayersPanel({ groups, sheet, onClose, onGroupHidden, onGroupLock, onGroupDelete, onJump, onItem, onDelete, onStudy }: {
  groups: LayerGroup[]; sheet: boolean; onClose(): void;
  onGroupHidden(key: LayerGroup["key"]): void; onGroupLock(key: ItemGroup): void; onGroupDelete(key: ItemGroup): void;
  onJump(group: ItemGroup, item: LayerItem): void; onItem(item: LayerItem, patch: { hidden?: boolean; locked?: boolean }): void;
  onDelete(item: LayerItem): void; onStudy(key: string): void;
}) {
  const [collapsed, setCollapsed] = useState<string[]>(readCollapsed);
  const [confirming, setConfirming] = useState<ItemGroup | null>(null);
  const fold = (key: string) => setCollapsed((keys) => {
    const next = keys.includes(key) ? keys.filter((other) => other !== key) : [...keys, key];
    try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next)); } catch { /* folding still works for this visit */ }
    return next;
  });
  const size = sheet ? "h-11 w-11" : "h-6 w-6";
  const icon = sheet ? 16 : 12;
  const button = `inline-flex ${size} shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30 disabled:hover:bg-transparent`;
  // On a desktop, an item's quiet buttons wait for the pointer or focus; on and off states always show.
  const quiet = sheet ? "" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100";
  const row = `group flex items-center gap-1.5 ${sheet ? "min-h-11 px-3" : "min-h-7 px-2"}`;
  // A name is a button as tall as its row, so a finger has the whole row to aim at.
  const tall = sheet ? "min-h-11" : "py-1";

  const body = <>
    <div className={`flex items-center justify-between border-b border-slate-700/40 ${sheet ? "px-3 py-2" : "px-3 py-2.5"}`}>
      <h2 className="text-xs font-medium text-slate-200">Layers</h2>
      <button aria-label="Close layers" title="Close layers" onClick={onClose} className={button}><X size={icon + 1} /></button>
    </div>
    {groups.map((group) => {
      const open = !collapsed.includes(group.key);
      const count = "items" in group ? group.items.length : "studies" in group ? group.studies.filter((study) => study.on).length : null;
      const items = "items" in group ? group.items : [];
      const allLocked = items.length > 0 && items.every((item) => item.locked);
      const symbols = [...new Set(items.map((item) => item.symbol))];
      return <div key={group.key} role="group" aria-label={group.name} className="border-b border-slate-800 last:border-b-0">
        <div className={`${row} ${group.hidden ? "text-slate-500" : "text-slate-200"}`}>
          <button aria-expanded={open} aria-label={`${group.name}${count === null ? "" : `, ${count}`}`} onClick={() => fold(group.key)}
            className={`flex min-w-0 flex-1 items-center gap-1 text-left text-[11px] font-medium ${tall}`}>
            {open ? <ChevronDown size={icon} className="shrink-0 text-slate-500" /> : <ChevronRight size={icon} className="shrink-0 text-slate-500" />}
            <span className="truncate">{group.name}</span>{count !== null && <span className="text-[10px] font-normal text-slate-500">{count}</span>}
          </button>
          {"items" in group && !!items.length && <button aria-label={`${allLocked ? "Unlock" : "Lock"} all ${group.noun}`} aria-pressed={allLocked}
            title={allLocked ? `Let every ${group.noun.replace(/s$/, "")} drag again` : `Keep every ${group.noun.replace(/s$/, "")} from being dragged`}
            onClick={() => onGroupLock(group.key)} className={`${button} ${allLocked ? "text-amber-300" : ""}`}>{allLocked ? <Lock size={icon} /> : <LockOpen size={icon} />}</button>}
          <button aria-label={`${group.hidden ? "Show" : "Hide"} ${group.name}`} aria-pressed={group.hidden} title={group.hidden ? `Show ${group.name} on every chart` : `Hide ${group.name} on every chart`}
            onClick={() => onGroupHidden(group.key)} className={`${button} ${group.hidden ? "text-amber-300" : ""}`}>{group.hidden ? <EyeOff size={icon} /> : <Eye size={icon} />}</button>
          {"items" in group && !!items.length && <button aria-label={`Delete all ${group.noun}`} title={`Delete every ${group.noun.replace(/s$/, "")} listed here`}
            onClick={() => setConfirming(group.key)} className={`${button} hover:text-rose-300`}><Trash2 size={icon} /></button>}
        </div>
        {confirming === group.key && "items" in group && <div role="alert" className={`flex items-center gap-2 bg-rose-500/10 text-[11px] text-rose-200 ${sheet ? "px-3 py-2" : "px-3 py-1.5"}`}>
          <span className="min-w-0 flex-1">Delete {items.length} {items.length === 1 ? group.noun.replace(/s$/, "") : group.noun}{symbols.length > 1 ? ` (${symbols.join(", ")})` : ""}? Undo brings them back.</span>
          <button onClick={() => { onGroupDelete(group.key); setConfirming(null); }} className={`rounded bg-rose-500/80 px-2 font-medium text-white hover:bg-rose-500 ${sheet ? "h-11" : "h-6"}`}>Delete</button>
          <button onClick={() => setConfirming(null)} className={`rounded px-2 text-slate-300 hover:bg-slate-800 ${sheet ? "h-11" : "h-6"}`}>Cancel</button>
        </div>}
        {open && "items" in group && <div className="pb-1">
          {!items.length && <p className="px-3 pb-2 text-[10px] text-slate-600">None on these charts.</p>}
          {items.map((item, index) => {
            const label = `${item.name}${item.detail ? ` ${item.detail}` : ""}`;
            const away = item.hidden || group.hidden;
            return <div key={item.id}>
              {symbols.length > 1 && item.symbol !== items[index - 1]?.symbol && <div className="px-3 pb-0.5 pt-1.5 text-[9px] uppercase tracking-wider text-slate-600">{item.symbol}</div>}
              <div className={`${row} pl-5 ${away ? "opacity-60" : ""}`}>
                <span className={`shrink-0 rounded-sm ${item.line ? "h-0.5 w-3" : "h-2 w-3"}`} style={{ background: item.color }} />
                <button aria-label={`Go to ${label}`} title={away ? "Hidden: show it to go to it" : "Show it on the chart"} disabled={away} onClick={() => onJump(group.key, item)}
                  className={`flex min-w-0 flex-1 text-left text-[11px] text-slate-300 hover:text-sky-200 disabled:hover:text-slate-300 ${tall} ${item.line ? "items-center gap-1.5" : "flex-col justify-center"}`}>
                  {/* A level's price fits beside its name; a drawing's span of prices goes underneath. */}
                  <span className="max-w-full truncate">{item.name}</span>{item.detail && <span className={`shrink-0 truncate font-mono text-[10px] text-slate-500 ${item.line ? "ml-auto" : "max-w-full leading-3"}`}>{item.detail}</span>}
                </button>
                <button aria-label={`${item.locked ? "Unlock" : "Lock"} ${label}`} aria-pressed={item.locked} onClick={() => onItem(item, { locked: !item.locked })}
                  className={`${button} ${item.locked ? "text-amber-300" : quiet}`}>{item.locked ? <Lock size={icon} /> : <LockOpen size={icon} />}</button>
                <button aria-label={`${item.hidden ? "Show" : "Hide"} ${label}`} aria-pressed={item.hidden} onClick={() => onItem(item, { hidden: !item.hidden })}
                  className={`${button} ${item.hidden ? "text-amber-300" : quiet}`}>{item.hidden ? <EyeOff size={icon} /> : <Eye size={icon} />}</button>
                <button aria-label={`Delete ${label}`} onClick={() => onDelete(item)} className={`${button} hover:text-rose-300 ${quiet}`}><Trash2 size={icon} /></button>
              </div>
            </div>;
          })}
        </div>}
        {open && "note" in group && <p className="px-3 pb-2 pl-5 text-[10px] leading-4 text-slate-500">{group.note}</p>}
        {open && "studies" in group && <div className="pb-1">
          {group.studies.map((study) => <div key={study.key} className={`${row} pl-5 ${group.hidden ? "opacity-60" : ""}`}>
            <span className={`min-w-0 flex-1 truncate text-[11px] ${study.on ? "text-slate-300" : "text-slate-600"}`}>{study.label}</span>
            <button aria-label={`${study.on ? "Hide" : "Show"} ${study.label}`} aria-pressed={!study.on} onClick={() => onStudy(study.key)}
              className={`${button} ${study.on ? "" : "text-slate-600"}`}>{study.on ? <Eye size={icon} /> : <EyeOff size={icon} />}</button>
          </div>)}
        </div>}
      </div>;
    })}
  </>;

  if (sheet) return <Sheet label="Layers" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Layers">{body}</section>;
}
