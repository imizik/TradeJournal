"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import LiveDepthSession from "@/components/level2/LiveDepthSession";
import { LEVEL2_TICKER } from "@/components/level2/useDepthSession";
import type { DepthSession } from "@/components/level2/useDepthSession";
import { HEAT_BOOK_LABELS, HEAT_BUCKET_MS } from "@/lib/depthHeatmap";
import type { DepthHeatmap, HeatBookKind } from "@/lib/depthHeatmap";
import Sheet from "./Sheet";

type Heat = { shown: boolean; kind: HeatBookKind };

/** How much of the heatmap has filled, refreshed with the data at most once a second. */
function HeatStats({ heatmap, kind }: { heatmap: DepthHeatmap | null; kind: HeatBookKind }) {
  const [, setVersion] = useState(0);
  useEffect(() => {
    if (!heatmap) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = heatmap.subscribe(() => { timer ??= setTimeout(() => { timer = null; setVersion(heatmap.version); }, 1_000); });
    return () => { off(); if (timer) clearTimeout(timer); };
  }, [heatmap]);
  if (!heatmap) return <p className="text-[10px] leading-4 text-slate-500">Nothing collected for this symbol yet</p>;
  const columns = heatmap.columns(kind);
  const minutes = columns.length * HEAT_BUCKET_MS / 60_000;
  return <p className="text-[10px] leading-4 text-slate-500">
    {columns.length ? `${minutes < 1 ? "<1" : Math.round(minutes)} min of ${HEAT_BOOK_LABELS[kind]} collected` : "Nothing collected for this book yet"}
    {heatmap.skipped ? ` · ${heatmap.skipped} updates without a usable source time left out` : ""}
  </p>;
}

/**
 * The optional Level 2 dock panel: owner-only (ChartWorkspace never renders it
 * otherwise). It shows the Charts page's one manual session (`session`, owned
 * by ChartWorkspace so it keeps running with the dock closed) for the chart's
 * US stock or ETF ticker, and the heatmap's controls. One ticker streams at a
 * time: while another is running, the panel only offers to stop it. Anything
 * that is not a plain ticker (an option, an index) says so and makes no
 * request. Connect stays an explicit click.
 */
export default function Level2Panel({ symbol, sheet, session, onConnect, heatmap, heat, onHeat, onClose }: {
  symbol: string; sheet: boolean; session: DepthSession; onConnect(ticker: string): void; heatmap: DepthHeatmap | null; heat: Heat; onHeat(next: Heat): void; onClose(): void;
}) {
  const supported = LEVEL2_TICKER.test(symbol);
  const elsewhere = session.running && session.symbol !== symbol ? session.symbol : null;
  const controls = <div className="min-w-0 space-y-1 border-b border-sky-400/20 px-3 py-2 text-xs text-slate-300" aria-label="Level 2 heatmap">
    <label className="flex min-w-0 items-center gap-2"><input type="checkbox" checked={heat.shown} onChange={(event) => onHeat({ ...heat, shown: event.target.checked })} />Heatmap behind the {symbol} candles</label>
    <label className="flex min-w-0 items-center gap-2">Book
      <select value={heat.kind} onChange={(event) => onHeat({ ...heat, kind: event.target.value as HeatBookKind })} className="min-w-0 flex-1 truncate rounded border border-slate-700 bg-slate-900 px-1 py-0.5">
        {(Object.keys(HEAT_BOOK_LABELS) as HeatBookKind[]).map((kind) => <option key={kind} value={kind}>{HEAT_BOOK_LABELS[kind]}</option>)}
      </select></label>
    <HeatStats heatmap={heatmap} kind={heat.kind} />
    <p className="text-[10px] leading-4 text-slate-500">Displayed size from this provider&apos;s book, sampled up to four times a second per book; not consolidated or executable liquidity. Brightness is relative to the view. Blank means no usable update, not zero. Kept in this page only.</p>
  </div>;
  const body = <>
    <div className="flex items-center justify-between border-b border-slate-700/40 py-1 pl-3 pr-1">
      <h2 className="text-xs font-medium text-slate-200">{symbol} Level 2</h2>
      <button aria-label="Close Level 2" title="Close Level 2" onClick={onClose} className={`inline-flex items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${sheet ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
    </div>
    {supported && !elsewhere
      ? <>{controls}<LiveDepthSession compact symbol={symbol} session={{ ...session, connect: onConnect }} /></>
      : <div className="space-y-2 px-3 py-3 text-xs leading-5 text-slate-400">
        <p role="status">{elsewhere ? `One symbol streams at a time, and ${elsewhere} is running for its heatmap.` : `Level 2 depth covers US stock and ETF tickers, so nothing is shown for ${symbol}.`}{session.running ? "" : " No provider connection was started."}</p>
        {elsewhere && <p><button onClick={session.stop} className="text-sky-300 underline">Stop {elsewhere}</button>{supported ? ` to start ${symbol}.` : ""}</p>}
      </div>}
    <p className="px-3 py-2 text-[10px] leading-4 text-slate-500">Equity depth only; it is separate from an option contract&apos;s depth. Nothing is saved; the heatmap lives only in this page.</p>
  </>;
  if (sheet) return <Sheet label="Level 2" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Level 2">{body}</section>;
}
