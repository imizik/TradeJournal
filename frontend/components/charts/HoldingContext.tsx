"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { chartLink, fetchTradeCard, type ChartPosition, type TradeCardData } from "@/lib/chartJournal";
import { captureTime } from "@/lib/captures";
import HoldingEntryContext from "./HoldingEntryContext";
import PlanSummary from "./PlanSummary";

const money = (n: number | null | undefined) => n == null || !Number.isFinite(n) ? "Unavailable" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

/** Journal facts only. The workspace already reads positions; details are read
 * only for the owner's explicit selection. Never request option marks or alerts. */
export default function HoldingContext({ symbol, positions, onPeers }: { symbol: string; positions?: ChartPosition[]; onPeers(): void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState("");
  const options = positions?.filter((p) => p.instrument === "option");
  const chosen = options?.find((p) => p.trade_id === selected);
  return <section aria-label="Holding context" className="mb-3 rounded-md border border-slate-700/60 bg-slate-950/40 text-[11px]">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="min-h-11 w-full px-2 text-left font-medium text-slate-200">
      {open ? "▾" : "▸"} Holding context{options ? ` · ${options.length} recorded option trades` : ""}
    </button>
    {open && <div className="space-y-3 px-2.5 pb-3">
      <p className="text-amber-200">Journal records, not live broker holdings. Import completeness/time unknown; confirm quantity in Robinhood.</p>
      {options == null ? <p>Position list unavailable. Reload Charts to retry.</p> : !options.length ? <p>No recorded open option trades for {symbol}.</p> : <>
        <label className="block space-y-1"><span>Select contract and account</span>
          <select aria-label="Holding contract and account" value={chosen?.trade_id ?? ""} onChange={(e) => setSelected(e.target.value)} className="min-h-11 w-full min-w-0 rounded border border-slate-600 bg-slate-900 px-1 text-slate-200">
            <option value="">Choose a recorded trade…</option>
            {options.map((p) => <option key={p.trade_id} value={p.trade_id}>{p.contract} · {p.direction} · {p.account} {p.last4} · opened {captureTime(p.opened_at)}</option>)}
          </select>
        </label>
        {chosen && <HoldingDetails key={`${symbol}:${chosen.trade_id}`} symbol={symbol} id={chosen.trade_id} />}
      </>}
      <button type="button" onClick={onPeers} className="min-h-11 text-left text-sky-300 underline">Compare stock, group & market</button>
      <p className="text-slate-400">Peers has separate 15 min, Session and From low views; its window is independent of this holding.</p>
    </div>}
  </section>;
}

function HoldingDetails({ symbol, id }: { symbol: string; id: string }) {
  const [result, setResult] = useState<{ data?: TradeCardData; readAt?: number; error?: string } | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    fetchTradeCard(id, controller.signal).then((data) => {
      if (active) setResult({ data, readAt: Date.now() / 1000 });
    }).catch(() => { if (active) setResult({ error: "Holding details unavailable. Refresh to retry." }); });
    return () => { active = false; controller.abort(); };
  }, [id, revision]);
  const data = result?.data;
  const trade = data?.trade;
  const matches = trade?.id === id && trade.ticker === symbol && trade.instrument === "option";
  const position = matches && trade.status === "open" ? data?.position : null;
  const lastFill = data?.fills?.reduce((last, fill) => Math.max(last, fill.time), 0);
  return <div className="space-y-3 break-words" data-testid="holding-details">
    <button type="button" onClick={() => { setResult(null); setRevision((n) => n + 1); }} className="min-h-11 rounded border border-slate-600 px-2 text-sky-300">Refresh recorded details</button>
    {!result ? <p role="status">Loading recorded details…</p> : result.error ? <p role="alert" className="text-amber-300">{result.error}</p> : !matches ? <p className="text-amber-300">This trade no longer matches this symbol. Reload Charts for the current recorded list.</p> : <>
      <p className="font-medium text-slate-100">{trade.contract} · {trade.direction}<br />{trade.account?.name ?? "Account unavailable"} · {trade.account?.last4 ?? "—"}</p>
      {!position ? <p className="text-amber-300">No remaining open position is recorded. Reload Charts to update the list.</p> : <dl className="space-y-2">
        <div><dt className="text-slate-400">Recorded remaining contracts</dt><dd>{position.open}</dd></div>
        <div><dt className="text-slate-400">{trade.direction === "long" ? "Remaining premium paid" : "Remaining entry premium received"}</dt><dd>{money(position.avg_cost == null ? null : position.avg_cost * position.open)}</dd></div>
        <div><dt className="text-slate-400">Realized on recorded exits</dt><dd>{money(position.realized)}</dd></div>
      </dl>}
      <p className="text-slate-400">Recorded cost/credit, not current value or remaining loss. Option value unavailable here.</p>
      <p>Expiration: {trade.expiration ?? "Unavailable"}<br />Holding horizon: unspecified (not inferred from chart timeframe).</p>
      <p className="text-slate-500">Details read {captureTime(result.readAt!)}.<br />Latest recorded fill: {lastFill ? captureTime(lastFill) : "Unavailable"}. This is execution time, not import time.</p>
      <div className="flex flex-wrap gap-3 text-sky-300">
        <Link href={`/trades/${id}`} className="py-2 underline">Trade details</Link>
        <Link href={chartLink({ symbol, from: trade.opened_at, trade: id })} className="py-2 underline">Entry on chart</Link>
      </div>
      {position && <HoldingEntryContext symbol={symbol} tradeId={id} />}
      <details className="rounded border border-slate-700 p-2">
        <summary className="cursor-pointer py-1 text-slate-200">Saved plan & reference</summary>
        <div className="mt-2 space-y-3">
          {data?.plans == null ? <p>Linked plans unavailable.</p> : !data.plans.length ? <p>No linked plan. Original rationale, horizon and invalidation are not established.</p> : data.plans.map((plan) => <div key={plan.id} className="space-y-2">
            <PlanSummary capture={plan} />
            {plan.context.state === "captured" ? <p className="text-slate-400">Saved chart reference: {plan.context.symbol} · {plan.context.interval} · {plan.context.session} · {captureTime(plan.context.captured_at)}. Price {money(plan.context.price.value)} ({plan.context.price.source}; {plan.context.price.at ? captureTime(plan.context.price.at) : "time unavailable"}{plan.context.price.stale ? "; stale when saved" : ""}). Saved levels are chart annotations, not confirmed invalidation rules.</p> : <p className="text-slate-400">Chart reference unavailable: {plan.context.reason}</p>}
          </div>)}
        </div>
      </details>
    </>}
  </div>;
}
