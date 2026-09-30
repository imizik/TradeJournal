"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Clock3, Search, Star } from "lucide-react";
import { price, validSymbol } from "@/lib/charts";
import type { ChartQuote } from "@/lib/charts";

type Option = { symbol: string; kind: "typed" | "recent" | "watchlist" };

/**
 * Cmd/Ctrl+K symbol switcher. It only searches symbols the browser already
 * knows (recent and watchlist) plus the typed ticker; it never asks a provider.
 */
export default function SymbolPalette({ current, recent, watchlist, quotes, onChoose, onClose }: {
  current: string; recent: string[]; watchlist: string[]; quotes: ChartQuote[];
  onChoose(symbol: string): void; onClose(): void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); }, []);

  const options = useMemo(() => {
    const q = query.trim().toUpperCase();
    const seen = new Set<string>();
    const list: Option[] = [];
    const add = (symbol: string, kind: Option["kind"]) => {
      if (seen.has(symbol) || (q && !symbol.includes(q))) return;
      seen.add(symbol); list.push({ symbol, kind });
    };
    // Exact and prefix matches first, then anything containing the query.
    const rank = (symbols: string[]) => q ? [...symbols].sort((a, b) => Number(!a.startsWith(q)) - Number(!b.startsWith(q))) : symbols;
    rank(recent.filter((s) => s !== current)).forEach((s) => add(s, "recent"));
    rank(watchlist).forEach((s) => add(s, "watchlist"));
    // Known symbols first, so "NV" selects NVDA; an exact new ticker leads.
    if (q && validSymbol(q) && !seen.has(q)) {
      if (list.some((o) => o.symbol.startsWith(q))) list.push({ symbol: q, kind: "typed" }); else list.unshift({ symbol: q, kind: "typed" });
    }
    return list;
  }, [query, recent, watchlist, current]);
  const selected = Math.min(active, Math.max(0, options.length - 1));

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); }
    else if (event.key === "ArrowDown" && options.length) { event.preventDefault(); setActive((selected + 1) % options.length); }
    else if (event.key === "ArrowUp" && options.length) { event.preventDefault(); setActive((selected - 1 + options.length) % options.length); }
    else if (event.key === "Enter") {
      event.preventDefault();
      const option = options[selected];
      if (option) onChoose(option.symbol);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center bg-black/60 px-4 pt-[12vh]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Symbol search" onKeyDown={onKey} className="w-full max-w-md overflow-hidden rounded-xl border border-slate-700 bg-[#121924] shadow-2xl">
        <div className="flex items-center gap-2 border-b border-slate-700/60 px-3">
          <Search size={15} className="text-slate-500" />
          <input ref={input} role="combobox" aria-expanded="true" aria-controls="symbol-search-options" aria-activedescendant={options[selected] ? `symbol-option-${options[selected].symbol}` : undefined}
            aria-label="Search symbols" value={query} maxLength={15} placeholder="Ticker, recent, or watchlist"
            onChange={(e) => { setQuery(e.target.value.toUpperCase()); setActive(0); }}
            className="h-12 min-w-0 flex-1 bg-transparent text-sm font-medium uppercase text-slate-100 outline-none placeholder:normal-case placeholder:text-slate-500" />
          <kbd className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-500">Esc</kbd>
        </div>
        <ul id="symbol-search-options" role="listbox" aria-label="Symbols" className="max-h-[50vh] overflow-y-auto py-1">
          {options.map((option, index) => {
            const quote = quotes.find((q) => q.symbol === option.symbol);
            return <li key={option.symbol} id={`symbol-option-${option.symbol}`} role="option" aria-selected={index === selected}
              onMouseEnter={() => setActive(index)} onClick={() => onChoose(option.symbol)}
              className={`flex cursor-pointer items-center gap-2 px-3 py-2.5 text-xs ${index === selected ? "bg-sky-400/10 text-slate-100" : "text-slate-300"}`}>
              {option.kind === "typed" ? <ArrowUpRight size={13} className="text-sky-300" /> : option.kind === "recent" ? <Clock3 size={13} className="text-slate-500" /> : <Star size={13} className="text-slate-500" />}
              <span className="font-semibold">{option.kind === "typed" ? `Chart ${option.symbol}` : option.symbol}</span>
              <span className="text-[10px] text-slate-500">{option.kind === "recent" ? "Recent" : option.kind === "watchlist" ? "Watchlist" : ""}</span>
              <span className="ml-auto font-mono text-slate-400">{quote ? price(quote.last) : ""}</span>
            </li>;
          })}
          {!options.length && <li className="px-3 py-4 text-xs text-slate-500">{query ? "Enter a US stock or ETF ticker, such as MRVL." : "No recent symbols yet."}</li>}
        </ul>
        <p className="border-t border-slate-800 px-3 py-2 text-[10px] text-slate-500">↑↓ to move · Enter to chart · your intervals stay the same</p>
      </div>
    </div>
  );
}
