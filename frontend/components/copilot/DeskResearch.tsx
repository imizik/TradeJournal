"use client";

/**
 * The desk's Research drawer (docs/copilot-lab.md § The desk): the chart ticker's symbol research (Overview, News, Events,
 * Forecast, Financials, Short, You) from Charts, the same ``SymbolInfo`` panel and the same reads. Closed by default and
 * mounted only while open, so the desk makes no research read until he opens it from the chart's More or ⌘K. Escape
 * closes it; on a phone it is a full-height sheet. It shows only the ticker he opened it for, so a ticker he does not
 * follow is never researched on its own.
 */

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import SymbolInfo from "@/components/charts/SymbolInfo";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";

const OPEN_EVENT = "desk-research-open";
/** Opens the Research drawer for a ticker (the chart's More, ⌘K's "Research NVDA"). */
export const openResearch = (symbol: string) => window.dispatchEvent(new CustomEvent<string>(OPEN_EVENT, { detail: symbol }));

export function DeskResearch() {
  const [symbol, setSymbol] = useState<string | null>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const show = (event: Event) => {
      const next = (event as CustomEvent<string>).detail;
      if (typeof next !== "string" || !next) return;
      opener.current = document.activeElement;
      setSymbol(next);
    };
    window.addEventListener(OPEN_EVENT, show);
    return () => window.removeEventListener(OPEN_EVENT, show);
  }, []);
  useEffect(() => {
    if (!symbol) return;
    const frame = requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="Close research"]')?.focus());
    // Escape closes this before any desk key sees it; a native dialog above it (⌘K's palette) keeps its own.
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) { event.stopImmediatePropagation(); event.preventDefault(); setSymbol(null); }
    };
    window.addEventListener("keydown", key, true);
    const back = opener.current;
    return () => { cancelAnimationFrame(frame); window.removeEventListener("keydown", key, true); if (back instanceof HTMLElement && back.isConnected) back.focus(); };
  }, [symbol]);
  return symbol ? <Drawer symbol={symbol} onClose={() => setSymbol(null)} /> : null;
}

function Drawer({ symbol, onClose }: { symbol: string; onClose(): void }) {
  // The Forecast tab's spot is the live tick when there is one; without it the server reads its own (the tab never waits).
  const ticks = useDeskTicks([symbol]);
  const last = tickFor(ticks, symbol)?.last ?? null;
  return (
    <div className="fixed inset-0 z-[70] flex justify-end" data-testid="desk-research">
      <button type="button" aria-label="Close research backdrop" tabIndex={-1} onClick={() => onClose()} className="absolute inset-0 bg-black/40 max-sm:hidden" />
      <aside role="dialog" aria-label={`${symbol} research`} className="relative flex h-full w-full flex-col bg-background shadow-xl sm:w-[28rem] sm:border-l">
        <header className="flex min-h-12 shrink-0 items-center justify-between border-b px-3">
          <h2 className="text-sm font-semibold text-foreground">Research · {symbol}</h2>
          <button type="button" aria-label="Close research" onClick={onClose} className="inline-flex size-11 items-center justify-center rounded text-muted-foreground hover:text-foreground sm:size-8"><X size={16} aria-hidden /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <SymbolInfo key={symbol} symbol={symbol} price={() => last} embedded />
        </div>
      </aside>
    </div>
  );
}
