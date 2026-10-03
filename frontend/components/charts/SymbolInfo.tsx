"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { fetchSymbolJournal } from "@/lib/symbolInfo";
import type { SymbolJournal } from "@/lib/symbolInfo";
import SymbolInfoYou from "./SymbolInfoYou";

const TABS = ["Overview", "News", "Events", "Forecast", "You"] as const;
type Tab = typeof TABS[number];
const TAB_KEY = "tradejournal.charts.symbol-info.tab.v1";

export default function SymbolInfo({ symbol }: { symbol: string }) {
  const id = useId();
  const [view, setView] = useState<{ ready: boolean; expanded: boolean; tab: Tab }>({ ready: false, expanded: false, tab: "You" });
  const [result, setResult] = useState<{ symbol: string; data?: SymbolJournal; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let tab: Tab = "You";
    try { const saved = localStorage.getItem(TAB_KEY); if (TABS.includes(saved as Tab)) tab = saved as Tab; } catch { /* device storage is optional */ }
    const expanded = window.matchMedia("(min-width: 1024px)").matches;
    queueMicrotask(() => setView({ ready: true, expanded, tab }));
  }, []);

  useEffect(() => {
    if (!view.ready || !view.expanded || view.tab !== "You") return;
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => {
      setResult(null);
      fetchSymbolJournal(symbol, controller.signal).then((data) => {
        if (active) setResult({ symbol, data });
      }).catch(() => {
        if (active) setResult({ symbol, error: "Journal unavailable. Try again." });
      });
    }, 300);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [symbol, view.ready, view.expanded, view.tab, retry]);

  function select(tab: Tab) {
    setView((current) => ({ ...current, tab }));
    try { localStorage.setItem(TAB_KEY, tab); } catch { /* keep working without storage */ }
  }

  const shown = result?.symbol === symbol ? result : null;
  return <section aria-label="Symbol info" className="min-w-0 overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]">
    <button aria-expanded={view.expanded} aria-controls={`${id}-content`} onClick={() => setView((current) => ({ ...current, expanded: !current.expanded }))} className="flex w-full items-center justify-between px-3 py-3 text-xs font-medium text-slate-200">
      <span>{symbol} symbol info</span>{view.expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
    {view.expanded && <div id={`${id}-content`}>
      <div role="tablist" aria-label="Symbol info tabs" className="flex border-y border-slate-700/40">
        {TABS.map((tab, index) => <button key={tab} role="tab" aria-selected={view.tab === tab} aria-controls={`${id}-panel`} id={`${id}-${tab}`} tabIndex={view.tab === tab ? 0 : -1}
          onClick={() => select(tab)} onKeyDown={(event) => {
            const next = event.key === "ArrowRight" ? (index + 1) % TABS.length : event.key === "ArrowLeft" ? (index + TABS.length - 1) % TABS.length : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : null;
            if (next != null) { event.preventDefault(); event.stopPropagation(); select(TABS[next]); document.getElementById(`${id}-${TABS[next]}`)?.focus(); }
          }} className={`min-w-0 flex-1 px-1 py-3 text-[10px] ${view.tab === tab ? "bg-sky-400/5 text-sky-300" : "text-slate-500 hover:text-slate-200"}`}>{tab}</button>)}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${view.tab}`} className="p-3">
        {view.tab !== "You" ? <p className="text-xs text-slate-500">{view.tab} is coming soon.</p>
          : shown?.data ? <SymbolInfoYou data={shown.data} />
          : shown?.error ? <div role="alert" className="text-xs text-amber-300"><p>{shown.error}</p><button onClick={() => setRetry((value) => value + 1)} className="mt-2 rounded border border-slate-700 px-3 py-2">Retry journal</button></div>
          : <p role="status" className="text-xs text-slate-500">Loading journal…</p>}
      </div>
    </div>}
  </section>;
}
