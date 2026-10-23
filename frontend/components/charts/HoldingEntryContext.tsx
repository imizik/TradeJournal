"use client";

import { useEffect, useState } from "react";
import { getHoldingComparison, nyTime, pctText, type GroupComparison } from "@/lib/radar";
import { ComparisonRows } from "./SymbolInfoPeers";

/** Visible, selected holding only; server resolves entry and rechecks open status on every read. */
export default function HoldingEntryContext({ symbol, tradeId }: { symbol: string; tradeId: string }) {
  const [open, setOpen] = useState(false);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ data?: GroupComparison; error?: boolean } | null>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let active = true, sequence = 0;
    const read = () => {
      const request = ++sequence;
      getHoldingComparison(symbol, tradeId, controller.signal).then((data) => {
        if (data.symbol !== symbol || (data.entry && data.entry.trade_id !== tradeId) || (data.rows.length && !data.entry)) throw new Error("Holding mismatch");
        if (active && request === sequence) setResult({ data });
      }).catch(() => { if (active && request === sequence) setResult({ error: true }); });
    };
    read();
    const timer = setInterval(() => { if (!document.hidden) read(); }, 60_000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, [open, symbol, tradeId, retry]);
  const data = result?.data;
  const entry = data?.entry;
  return <section aria-label="Since first recorded entry" className="rounded border border-slate-700 p-2">
    <button type="button" aria-expanded={open} onClick={() => { setResult(null); setOpen(!open); }} className="min-h-11 w-full text-left font-medium text-slate-200">
      {open ? "▾" : "▸"} Since first recorded entry
    </button>
    {open && <div className="space-y-2">
      {!result ? <p role="status">Loading recorded movement…</p> : result.error ? <p role="alert" className="text-amber-300">Since-entry context unavailable. Previous values hidden until a fresh read succeeds.</p> : data && <>
        {entry && <p>First recorded entry: {entry.recorded_at.slice(0, 10)} · {nyTime(entry.recorded_at)} ET.</p>}
        {data.reason && <p className="text-amber-300">{data.reason}</p>}
        {entry?.baseline_at && <p className="text-slate-300">Post-entry baseline: {nyTime(entry.baseline_at, true)} ET · {Math.round(entry.baseline_delay_seconds ?? 0)}s after recorded entry. The initial move is excluded.</p>}
        {data.window && <p className="text-slate-400">{data.live ? "Recorded window" : "Regular-session snapshot"}: {nyTime(data.window.start, true)}–{nyTime(data.window.end, true)} ET.</p>}
        {data.rows.length > 0 && <dl aria-label="Stock and market since entry" className="space-y-1">
          {data.rows.filter((row) => row.role !== "peer").map((row) => <div key={row.symbol} className="flex justify-between gap-2"><dt>{row.symbol}</dt><dd className="font-mono text-slate-100">{pctText(row.change_pct, 2)}</dd></div>)}
        </dl>}
        {data.coverage && <p className="text-slate-200">{data.coverage.peers_up} up · {data.coverage.peers_down} down · {data.coverage.peers_available}/{data.coverage.peers_total} peers available<br /><span className="text-slate-400">{data.group?.name}</span></p>}
        {data.coverage && <p className="text-[10px] text-slate-400">{data.coverage.recorded_minutes}/{data.coverage.expected_minutes} minutes recorded. All returns share the same endpoint passes.</p>}
        {data.rows.length > 0 && <details>
          <summary className="cursor-pointer py-2 text-sky-300">Peer changes & observation times</summary>
          <ComparisonRows data={data} />
          <p className="mt-2 break-words text-[10px] text-slate-500">{data.source}. Recorded: {data.recorded_versions?.join(", ") ?? data.universe_version}; current group: {data.universe_version}. Known equivalent memberships only.</p>
        </details>}
      </>}
      <p className="text-slate-400">Underlying moves, not option P&amp;L or a sell signal. Adds and partial exits do not reset the original entry. Recorded execution time can be minute-level; import time is unknown.</p>
      <button type="button" onClick={() => { setResult(null); setRetry((n) => n + 1); }} className="min-h-11 text-sky-300 underline">Refresh since-entry context</button>
    </div>}
  </section>;
}
