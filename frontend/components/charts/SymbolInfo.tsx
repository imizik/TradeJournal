"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { fetchSymbolEvents, fetchSymbolFinancials, fetchSymbolForecast,fetchSymbolJournal, fetchSymbolNews, fetchSymbolOverview } from "@/lib/symbolInfo";
import type { SymbolEvents, SymbolFinancials, SymbolForecast,SymbolJournal, SymbolNews, SymbolOverview } from "@/lib/symbolInfo";
import type { ChartQuote } from "@/lib/charts";
import SymbolInfoOverview from "./SymbolInfoOverview";
import SymbolInfoEvents from "./SymbolInfoEvents";
import SymbolInfoFinancials from "./SymbolInfoFinancials";
import SymbolInfoForecast from "./SymbolInfoForecast";
import SymbolInfoNews from "./SymbolInfoNews";
import SymbolInfoYou from "./SymbolInfoYou";

const TABS = ["Overview", "News", "Events", "Forecast", "Financials", "You"] as const;
type Tab = typeof TABS[number];
const TAB_KEY = "tradejournal.charts.symbol-info.tab.v1";
/** The tabs built so far: one request each, for the open tab only. The Forecast tab needs the price. Forecast and News read again each minute while open and visible. */
const BUILT = {
  Overview: { load: fetchSymbolOverview, name: "overview", title: "Overview" },
  You: { load: fetchSymbolJournal, name: "journal", title: "Journal" },
  News: { load: fetchSymbolNews, name: "news", title: "News" },
  Events: { load: fetchSymbolEvents, name: "events", title: "Events" },
  Forecast: { load: fetchSymbolForecast, name: "forecast", title: "Forecast" },
  Financials: { load: fetchSymbolFinancials, name: "financials", title: "Financials" },
} satisfies Partial<Record<Tab, { load(symbol: string, signal: AbortSignal, spot: number | null): Promise<unknown>; name: string; title: string }>>;
const built = (tab: Tab): tab is keyof typeof BUILT => tab in BUILT;
const REFRESH_MS = 60_000;

/** `price` reads the chart's latest price for the symbol when a tab needs it (the Forecast tab's straddle). */
export default function SymbolInfo({ symbol, price, quote, quoteFetchedAt }: { symbol: string; price?(): number | null; quote?: ChartQuote | null; quoteFetchedAt?: number | null }) {
  const id = useId();
  const priceOf = useRef(price);
  useEffect(() => { priceOf.current = price; });
  const [view, setView] = useState<{ ready: boolean; expanded: boolean; tab: Tab }>({ ready: false, expanded: false, tab: "You" });
  const [result, setResult] = useState<{ key: string; data?: unknown; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let tab: Tab = "You";
    try { const saved = localStorage.getItem(TAB_KEY); if (TABS.includes(saved as Tab)) tab = saved as Tab; } catch { /* device storage is optional */ }
    const expanded = window.matchMedia("(min-width: 1024px)").matches;
    queueMicrotask(() => setView({ ready: true, expanded, tab }));
  }, []);

  useEffect(() => {
    const tab = view.tab;
    if (!view.ready || !view.expanded || !built(tab)) return;
    const controller = new AbortController();
    let active = true;
    let waiting: ReturnType<typeof setTimeout> | undefined;
    const key = `${tab}|${symbol}`;
    // A refresh keeps what the tab shows if it fails; the first read says so.
    const run = (quiet: boolean) => {
      const spot = priceOf.current?.() ?? null;
      if (tab === "Forecast" && spot === null) { waiting = setTimeout(() => run(quiet), 1000); return; } // the chart's price is still loading
      BUILT[tab].load(symbol, controller.signal, spot).then((data) => {
        if (active) setResult({ key, data });
      }).catch(() => {
        if (active && !quiet) setResult({ key, error: `${BUILT[tab].title} unavailable. Try again.` });
      });
    };
    const timer = setTimeout(() => { setResult(null); run(false); }, 300);
    const again = tab === "Forecast" || tab === "News" ? setInterval(() => { if (!document.hidden) run(true); }, REFRESH_MS) : undefined;
    return () => { active = false; clearTimeout(timer); clearTimeout(waiting); clearInterval(again); controller.abort(); };
  }, [symbol, view.ready, view.expanded, view.tab, retry]);

  function select(tab: Tab) {
    setView((current) => ({ ...current, tab }));
    try { localStorage.setItem(TAB_KEY, tab); } catch { /* keep working without storage */ }
  }

  const shown = result?.key === `${view.tab}|${symbol}` ? result : null;
  return <section aria-label="Symbol info" className="min-w-0 overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]">
    <button aria-expanded={view.expanded} aria-controls={`${id}-content`} onClick={() => setView((current) => ({ ...current, expanded: !current.expanded }))} className="flex min-h-11 w-full items-center justify-between px-3 py-3 text-xs font-medium text-slate-200 lg:min-h-0">
      <span>{symbol} symbol info</span>{view.expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
    {view.expanded && <div id={`${id}-content`}>
      <div role="tablist" aria-label="Symbol info tabs" className="flex border-y border-slate-700/40">
        {TABS.map((tab, index) => <button key={tab} role="tab" aria-selected={view.tab === tab} aria-controls={`${id}-panel`} id={`${id}-${tab}`} tabIndex={view.tab === tab ? 0 : -1}
          onClick={() => select(tab)} onKeyDown={(event) => {
            const next = event.key === "ArrowRight" ? (index + 1) % TABS.length : event.key === "ArrowLeft" ? (index + TABS.length - 1) % TABS.length : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : null;
            if (next != null) { event.preventDefault(); event.stopPropagation(); select(TABS[next]); document.getElementById(`${id}-${TABS[next]}`)?.focus(); }
          }} className={`min-h-11 min-w-0 flex-1 px-1 py-3 text-[10px] lg:min-h-0 ${view.tab === tab ? "bg-sky-400/5 text-sky-300" : "text-slate-500 hover:text-slate-200"}`}>{tab}</button>)}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${view.tab}`} className="p-3">
        {!built(view.tab) ? <p className="text-xs text-slate-500">{view.tab} is coming soon.</p>
          : shown?.data ? (view.tab === "Overview" ? <SymbolInfoOverview data={shown.data as SymbolOverview} quote={quote} quoteFetchedAt={quoteFetchedAt ?? null} />
            : view.tab === "You" ? <SymbolInfoYou data={shown.data as SymbolJournal} /> : view.tab === "Events" ? <SymbolInfoEvents data={shown.data as SymbolEvents} />
            : view.tab === "News" ? <SymbolInfoNews key={symbol} data={shown.data as SymbolNews} />
            : view.tab === "Financials" ? <SymbolInfoFinancials data={shown.data as SymbolFinancials} />
            : <SymbolInfoForecast data={shown.data as SymbolForecast} />)
          : shown?.error ? <div role="alert" className="text-xs text-amber-300"><p>{shown.error}</p><button onClick={() => setRetry((value) => value + 1)} className="mt-2 min-h-11 rounded border border-slate-700 px-3 py-2 lg:min-h-0">Retry {BUILT[view.tab].name}</button></div>
          : <p role="status" className="text-xs text-slate-500">Loading {BUILT[view.tab].name}…</p>}
      </div>
    </div>}
  </section>;
}
