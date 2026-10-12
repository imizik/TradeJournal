"use client";

import { useAppAccess } from "@/components/AccessProvider";
import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { fetchSymbolEvents, fetchSymbolFinancials, fetchSymbolForecast, fetchSymbolJournal, fetchSymbolOverview, fetchSymbolShort } from "@/lib/symbolInfo";
import { useSymbolNews } from "@/lib/newsFeed";
import type { SymbolEvents, SymbolFinancials, SymbolForecast, SymbolJournal, SymbolNews, SymbolOverview, SymbolShort } from "@/lib/symbolInfo";
import type { ChartQuote } from "@/lib/charts";
import SymbolInfoOverview from "./SymbolInfoOverview";
import SymbolInfoEvents from "./SymbolInfoEvents";
import SymbolInfoFinancials from "./SymbolInfoFinancials";
import SymbolInfoForecast from "./SymbolInfoForecast";
import SymbolInfoNews, { LIT_MS } from "./SymbolInfoNews";
import SymbolInfoPeers, { usePeers } from "./SymbolInfoPeers";
import SymbolInfoShort from "./SymbolInfoShort";
import SymbolInfoYou from "./SymbolInfoYou";

const TABS = ["Overview", "News", "Events", "Forecast", "Financials", "Short", "You"] as const;
type Tab = typeof TABS[number];
const TAB_KEY = "tradejournal.charts.symbol-info.tab.v1";
/** The tabs built so far: one request each, for the open tab only. The Forecast tab needs the price. Forecast reads again each minute while open and visible. News is read through `useSymbolNews`, shared with the chart's news markers (T3.5). */
const BUILT = {
  Overview: { load: fetchSymbolOverview, name: "overview", title: "Overview" },
  You: { load: fetchSymbolJournal, name: "journal", title: "Journal" },
  News: { load: async () => null, name: "news", title: "News" }, // read by useSymbolNews, never by the generic loop below
  Events: { load: fetchSymbolEvents, name: "events", title: "Events" },
  Forecast: { load: fetchSymbolForecast, name: "forecast", title: "Forecast" },
  Financials: { load: fetchSymbolFinancials, name: "financials", title: "Financials" },
  Short: { load: fetchSymbolShort, name: "short", title: "Short" },
} satisfies Partial<Record<Tab, { load(symbol: string, signal: AbortSignal, spot: number | null): Promise<unknown>; name: string; title: string }>>;
const built = (tab: Tab): tab is keyof typeof BUILT => tab in BUILT;
const REFRESH_MS = 60_000;

/** `price` reads the chart's latest price for the symbol when a tab needs it (the Forecast tab's straddle). */
/** `focus` (a click on a news marker) opens the News tab and lights the listed articles once: the panel keeps its own copy and calls `onFocusHandled`, so a later remount replays nothing. */
export type NewsFocus = { symbol: string; ids: string[]; n: number };
export default function SymbolInfo({ symbol, price, quote, quoteFetchedAt, onSelectSymbol, focus, onFocusHandled }: { symbol: string; price?(): number | null; quote?: ChartQuote | null; quoteFetchedAt?: number | null; onSelectSymbol?(symbol: string): void; focus?: NewsFocus | null; onFocusHandled?(): void }) {
  const { owner, grants } = useAppAccess();
  const journal = owner || !!grants.journal_read;
  const id = useId();
  const priceOf = useRef(price);
  useEffect(() => { priceOf.current = price; });
  const [view, setView] = useState<{ ready: boolean; expanded: boolean; tab: Tab }>({ ready: false, expanded: false, tab: "You" });
  const [result, setResult] = useState<{ key: string; data?: unknown; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  // A news marker was clicked (T3.5): show the News tab, expanded, whatever was open before. A panel that mounts with the click keeps it.
  const focused = useRef(false);
  const tabRow = useRef<HTMLDivElement>(null);
  const [lit, setLit] = useState<NewsFocus | null>(null);

  useEffect(() => {
    let tab: Tab = "You";
    try { const saved = localStorage.getItem(TAB_KEY); if (TABS.includes(saved as Tab)) tab = saved as Tab; } catch { /* device storage is optional */ }
    const expanded = window.matchMedia("(min-width: 1024px)").matches;
    queueMicrotask(() => setView((current) => focused.current ? { ...current, ready: true } : { ready: true, expanded, tab }));
  }, []);
  const focusN = focus?.symbol === symbol ? focus.n : 0;
  useEffect(() => {
    if (!focusN) return;
    focused.current = true;
    queueMicrotask(() => { setView((current) => ({ ...current, expanded: true, tab: "News" })); setLit(focus ?? null); });
    onFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one click (a new `n`) is handled once
  }, [focusN]);
  // The highlight is for this click only: a later return to News (tab, symbol or collapse) shows it unlit.
  useEffect(() => {
    if (!lit) return;
    const timer = setTimeout(() => setLit((now) => now?.n === lit.n ? null : now), LIT_MS);
    return () => clearTimeout(timer);
  }, [lit]);

  useEffect(() => {
    const tab = view.tab;
    if (!view.ready || !view.expanded || !built(tab) || tab === "News" || (tab === "You" && !journal)) return;
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
    const again = tab === "Forecast" ? setInterval(() => { if (!document.hidden) run(true); }, REFRESH_MS) : undefined;
    return () => { active = false; clearTimeout(timer); clearTimeout(waiting); clearInterval(again); controller.abort(); };
  }, [symbol, view.ready, view.expanded, view.tab, retry, journal]);

  function select(tab: Tab) {
    setLit(null);
    setView((current) => ({ ...current, tab }));
    try { localStorage.setItem(TAB_KEY, tab); } catch { /* keep working without storage */ }
  }

  // The tab row scrolls sideways at a narrow width: bring the chosen tab into it (sideways only, so the dock itself does not jump).
  useEffect(() => {
    if (!view.expanded) return;
    const tab = document.getElementById(`${id}-${view.tab}`);
    const list = tab?.parentElement;
    if (!tab || !list) return;
    if (tab.offsetLeft < list.scrollLeft) list.scrollLeft = tab.offsetLeft;
    else if (tab.offsetLeft + tab.offsetWidth > list.scrollLeft + list.clientWidth) list.scrollLeft = tab.offsetLeft + tab.offsetWidth - list.clientWidth;
  }, [id, view.tab, view.expanded]);

  // A mouse wheel only scrolls up and down, and the row has no scrollbar: turn the wheel sideways while the row has room to move.
  useEffect(() => {
    const list = tabRow.current;
    if (!view.expanded || !list) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return; // trackpads already scroll sideways
      const room = list.scrollWidth - list.clientWidth;
      if (room <= 0 || (event.deltaY < 0 && list.scrollLeft <= 0) || (event.deltaY > 0 && list.scrollLeft >= room - 1)) return; // let the dock scroll
      event.preventDefault();
      list.scrollLeft += event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
    };
    list.addEventListener("wheel", onWheel, { passive: false });
    return () => list.removeEventListener("wheel", onWheel);
  }, [view.expanded]);

  const news = useSymbolNews(symbol, view.ready && view.expanded && view.tab === "News");
  const shown = view.tab === "News" ? (news.data ? { key: `News|${symbol}`, data: news.data } : news.error ? { key: `News|${symbol}`, error: news.error } : null)
    : result?.key === `${view.tab}|${symbol}` ? result : null;
  const peersResult = usePeers(symbol, !!onSelectSymbol && view.expanded && view.tab === "Overview");
  const peers = onSelectSymbol ? <SymbolInfoPeers symbol={symbol} result={peersResult} onSelect={onSelectSymbol} /> : null;
  return <section aria-label="Symbol info" className="min-w-0 overflow-hidden rounded-lg border border-slate-700/50 bg-[#141b25]">
    <button aria-expanded={view.expanded} aria-controls={`${id}-content`} onClick={() => setView((current) => ({ ...current, expanded: !current.expanded }))} className="flex min-h-11 w-full items-center justify-between px-3 py-3 text-xs font-medium text-slate-200 lg:min-h-0">
      <span>{symbol} symbol info</span>{view.expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
    </button>
    {view.expanded && <div id={`${id}-content`}>
      {/* One row. Names never squeeze into each other: a narrow dock scrolls the row sideways, and the chosen tab is kept in view. */}
      <div ref={tabRow} role="tablist" aria-label="Symbol info tabs" className="relative flex overflow-x-auto border-y border-slate-700/40 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {TABS.map((tab, index) => <button key={tab} role="tab" aria-selected={view.tab === tab} aria-controls={`${id}-panel`} id={`${id}-${tab}`} tabIndex={view.tab === tab ? 0 : -1}
          onClick={() => select(tab)} onKeyDown={(event) => {
            const next = event.key === "ArrowRight" ? (index + 1) % TABS.length : event.key === "ArrowLeft" ? (index + TABS.length - 1) % TABS.length : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : null;
            if (next != null) { event.preventDefault(); event.stopPropagation(); select(TABS[next]); document.getElementById(`${id}-${TABS[next]}`)?.focus(); }
          }} className={`min-h-11 flex-auto whitespace-nowrap border-b-2 px-2.5 py-2.5 text-[11px] lg:min-h-0 ${view.tab === tab ? "border-sky-400 bg-sky-400/5 text-sky-300" : "border-transparent text-slate-500 hover:text-slate-200"}`}>{tab}</button>)}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${view.tab}`} className="p-2">
        {view.tab === "You" && !journal ? <p className="text-xs text-slate-500">Your journal is not shared with this assistant.</p> : !built(view.tab) ? <p className="text-xs text-slate-500">{view.tab} is coming soon.</p>
          : shown?.data ? (view.tab === "Overview" ? <SymbolInfoOverview data={shown.data as SymbolOverview} quote={quote} quoteFetchedAt={quoteFetchedAt ?? null}
              peers={peersResult?.symbol === symbol ? peersResult.data?.valuation : null}
              peerGroup={peersResult?.symbol === symbol && peersResult.data?.source.provider === "curated" ? peersResult.data.source.label.replace(/^Peer group: /, "") : undefined}>{peers}</SymbolInfoOverview>
            : view.tab === "You" ? <SymbolInfoYou data={shown.data as SymbolJournal} /> : view.tab === "Events" ? <SymbolInfoEvents data={shown.data as SymbolEvents} />
            : view.tab === "Short" ? <SymbolInfoShort data={shown.data as SymbolShort} />
            : view.tab === "News" ? <SymbolInfoNews key={symbol} data={shown.data as SymbolNews} focus={lit?.symbol === symbol ? lit : null} />
            : view.tab === "Financials" ? <SymbolInfoFinancials data={shown.data as SymbolFinancials} />
            : <SymbolInfoForecast data={shown.data as SymbolForecast} />)
          : shown?.error ? <div role="alert" className="text-xs text-amber-300"><p>{shown.error}</p><button onClick={() => view.tab === "News" ? news.retry() : setRetry((value) => value + 1)} className="mt-2 min-h-11 rounded border border-slate-700 px-3 py-2 lg:min-h-0">Retry {BUILT[view.tab].name}</button></div>
          : <p role="status" className="text-xs text-slate-500">Loading {BUILT[view.tab].name}…</p>}
        {/* Peers are Overview's last block; while Overview loads or fails they still show below. */}
        {view.tab === "Overview" && !shown?.data && peers && <div className="mt-3">{peers}</div>}
      </div>
    </div>}
  </section>;
}
