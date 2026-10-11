"use client";

import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, ChevronRight, Info } from "lucide-react";

/**
 * One section of the watchlist dock (levels, alerts, journal): a one-line header with its count,
 * a fold, an optional (i) that reveals the first-use help, and an optional action beside them.
 * `status` stays visible when the section is folded (a warning is status, not help). The fold is
 * remembered on this device only; until the person folds it, `defaultOpen` decides.
 */
export default function DockSection({ name, ariaLabel, title, count, defaultOpen, info, status, action, narrow, children }: {
  name: string; ariaLabel: string; title: string; count: ReactNode; defaultOpen: boolean; info?: ReactNode; status?: ReactNode;
  /** Receives `reveal`, which opens the section without saving that as the person's choice. */
  action?(reveal: () => void): ReactNode; narrow: boolean; children: ReactNode;
}) {
  const id = useId();
  const key = `tradejournal.charts.dock.${name}.open.v1`;
  const [chosen, setChosen] = useState<boolean | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [explained, setExplained] = useState(false);
  useEffect(() => {
    try { const saved = localStorage.getItem(key); if (saved === "1" || saved === "0") queueMicrotask(() => setChosen(saved === "1")); } catch { /* device storage is optional */ }
  }, [key]);
  const open = revealed || (chosen ?? defaultOpen);
  const toggle = () => {
    const next = !open;
    setChosen(next); setRevealed(false);
    try { localStorage.setItem(key, next ? "1" : "0"); } catch { /* keep working without storage */ }
  };
  const tap = narrow ? "h-11 w-11" : "h-6 w-6";
  return <section className="border-t border-slate-700/40" aria-label={ariaLabel}>
    <div className={`flex items-center gap-0.5 pl-2 pr-1.5 ${narrow ? "" : "min-h-8"}`}>
      <h2 className="min-w-0 flex-1 text-xs font-medium text-slate-200">
        <button aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle} className={`flex w-full min-w-0 items-center gap-1 text-left ${narrow ? "min-h-11" : "min-h-8"}`}>
          {open ? <ChevronDown size={12} className="shrink-0 text-slate-500" aria-hidden /> : <ChevronRight size={12} className="shrink-0 text-slate-500" aria-hidden />}
          <span className="truncate">{title}</span><span className="shrink-0 font-mono text-[10px] font-normal text-slate-500">{count}</span>
        </button>
      </h2>
      {info && <button aria-label={`About ${title}`} title={`About ${title}`} aria-expanded={explained} aria-controls={`${id}-info`} onClick={() => setExplained(!explained)}
        className={`inline-flex shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${explained ? "bg-slate-800 text-sky-300" : ""} ${tap}`}><Info size={12} /></button>}
      {action?.(() => setRevealed(true))}
    </div>
    {status && <div className="px-3 pb-2">{status}</div>}
    {info && explained && <p id={`${id}-info`} className="px-3 pb-2 text-[11px] leading-5 text-slate-400">{info}</p>}
    {open && <div id={`${id}-body`} className="px-3 pb-3">{children}</div>}
  </section>;
}
