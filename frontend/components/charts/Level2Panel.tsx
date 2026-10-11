"use client";

import { X } from "lucide-react";
import LiveDepthSession from "@/components/level2/LiveDepthSession";
import Sheet from "./Sheet";

/** The only symbol the local bridge serves in this first slice. */
export const LEVEL2_SYMBOL = "NVDA";

/**
 * The optional Level 2 dock panel: owner-only (ChartWorkspace never renders it
 * otherwise). It follows the main chart's symbol. NVDA shows the manual
 * 30-second session; any other symbol only says so and never contacts the
 * provider. The session is keyed by symbol and lives only while this panel is
 * mounted, so closing the dock, switching tabs or symbols and leaving Charts
 * abort it, and reopening never reconnects: Connect stays an explicit click.
 */
export default function Level2Panel({ symbol, sheet, onClose }: { symbol: string; sheet: boolean; onClose(): void }) {
  const supported = symbol === LEVEL2_SYMBOL;
  const body = <>
    <div className="flex items-center justify-between border-b border-slate-700/40 py-1 pl-3 pr-1">
      <h2 className="text-xs font-medium text-slate-200">{symbol} Level 2</h2>
      <button aria-label="Close Level 2" title="Close Level 2" onClick={onClose} className={`inline-flex items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${sheet ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
    </div>
    {supported
      ? <LiveDepthSession key={symbol} compact />
      : <p role="status" className="px-3 py-3 text-xs leading-5 text-slate-400">Level 2 depth supports {LEVEL2_SYMBOL} only in this first slice, so nothing is shown for {symbol}. No provider connection was started.</p>}
    <p className="px-3 py-2 text-[10px] leading-4 text-slate-500">Equity depth only; it is separate from an option contract&apos;s depth. Not saved, not drawn on the charts.</p>
  </>;
  if (sheet) return <Sheet label="Level 2" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Level 2">{body}</section>;
}
