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

/** The chart's own last price and when it was read (``CentreChart`` notes it), for the Forecast tab's spot after hours. */
let chartPrice: { symbol: string; last: number; at: number } | null = null;
export function noteChartPrice(symbol: string, last: number | null, at: number | null) {
  chartPrice = last !== null && at !== null ? { symbol, last, at } : null;
}
const clock = (at: number) => new Date(at * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });

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
    // Tab stays inside the sheet: the covered desk is not reachable behind it.
    const tab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const box = document.querySelector('[data-testid="desk-research"] aside');
      const items = Array.from(box?.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []).filter(el => !el.hasAttribute("disabled") && el.offsetParent !== null);
      if (!items.length) return;
      const at = items.indexOf(document.activeElement as HTMLElement);
      const next = event.shiftKey ? (at <= 0 ? items.length - 1 : at - 1) : (at < 0 || at === items.length - 1 ? 0 : at + 1);
      event.preventDefault();
      items[next].focus();
    };
    window.addEventListener("keydown", tab, true);
    const back = opener.current;
    return () => {
      cancelAnimationFrame(frame); window.removeEventListener("keydown", key, true); window.removeEventListener("keydown", tab, true);
      // The menu item he pressed is gone with its menu: focus returns to the chart's More button, else the palette button.
      const target = back instanceof HTMLElement && back.isConnected ? back : (document.querySelector<HTMLElement>('[data-testid="desk-chart-more"]') ?? document.querySelector<HTMLElement>('[data-use="palette"]'));
      target?.focus();
    };
  }, [symbol]);
  return symbol ? <Drawer symbol={symbol} onClose={() => setSymbol(null)} /> : null;
}

function Drawer({ symbol, onClose }: { symbol: string; onClose(): void }) {
  // The Forecast tab's spot is the live tick when there is one; without it the server reads its own (the tab never waits).
  const ticks = useDeskTicks([symbol]);
  const tick = tickFor(ticks, symbol);
  const chart = chartPrice?.symbol === symbol ? chartPrice : null;
  // A fresh tick, else the chart's own last read (its time is shown beside the title); never an old tick without saying so.
  const spot = tick && !tick.stale ? { last: tick.last, at: tick.at } : chart ?? (tick ? { last: tick.last, at: tick.at } : null);
  const last = spot?.last ?? null;
  return (
    <div className="fixed inset-0 z-[70] flex justify-end" data-testid="desk-research">
      <button type="button" aria-label="Close research backdrop" tabIndex={-1} onClick={() => onClose()} className="absolute inset-0 bg-black/40 max-sm:hidden" />
      <aside role="dialog" aria-label={`${symbol} research`} className="relative flex h-full w-full flex-col bg-background shadow-xl sm:w-[28rem] sm:border-l">
        <header className="flex min-h-12 shrink-0 items-center justify-between border-b px-3">
          <h2 className="text-sm font-semibold text-foreground">Research · {symbol}{spot && <span className="ml-2 text-xs font-normal tabular-nums text-muted-foreground">{spot.last.toFixed(2)} as of {clock(spot.at)} ET</span>}</h2>
          <button type="button" aria-label="Close research" onClick={onClose} className="inline-flex size-11 items-center justify-center rounded text-muted-foreground hover:text-foreground sm:size-8"><X size={16} aria-hidden /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <SymbolInfo key={symbol} symbol={symbol} price={() => last} embedded />
        </div>
      </aside>
    </div>
  );
}
