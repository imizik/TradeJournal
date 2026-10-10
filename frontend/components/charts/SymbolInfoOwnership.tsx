import { useEffect, useState } from "react";
import { fetchSymbolInsiders, readAt } from "@/lib/symbolInfo";
import type { OverviewCompany, SymbolInsiders } from "@/lib/symbolInfo";

const count = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: 0 });
const compact = (value: number) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
const shares = (value: number | null | undefined) => value == null ? "—" : compact(value);
const signed = (value: number, text: string) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${text}`;
const money = (value: number) => `$${compact(Math.abs(value))}`;
const percent = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function Value({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div title={title} className="min-w-0"><dt className="truncate text-slate-500">{label}</dt><dd className="mt-0.5 truncate font-mono text-slate-200">{value}</dd></div>;
}

/** 13F summary from the Overview payload (no request of its own) and 90-day insider activity from one Yahoo-backed request. */
export default function SymbolInfoOwnership({ symbol, company, fund, unavailable }: { symbol: string; company: OverviewCompany; fund: boolean; unavailable: string }) {
  const [insiders, setInsiders] = useState<{ symbol: string; data?: SymbolInsiders; error?: string } | null>(null);
  useEffect(() => {
    if (fund) return;
    const controller = new AbortController();
    fetchSymbolInsiders(symbol, controller.signal).then((data) => setInsiders({ symbol, data }), (error) => { if (!controller.signal.aborted) setInsiders({ symbol, error: error.message }); });
    return () => controller.abort();
  }, [symbol, fund]);

  const owners = company.ownership;
  const label = `${company.source} · ${readAt(company.fetched_at)}`;
  const shown = insiders?.symbol === symbol ? insiders : null;
  const data = shown?.data;

  return <section aria-label="Ownership" className="space-y-3">
    <h3 className="text-slate-400">Ownership</h3>
    <div aria-label="13F institutional holders" role="group" className="space-y-2">
      <h4 className="text-slate-300">Institutions (13F){owners?.as_of ? <span className="font-normal text-slate-500"> · as of {owners.as_of}</span> : null}</h4>
      {company.state !== "ready" ? <p className={company.state === "none" ? "text-slate-500" : "text-amber-300"}>{company.state === "none" ? unavailable : company.message ?? "Not loaded yet."}</p>
        : !owners ? <p className="text-slate-500">Tradier lists no 13F filers for this symbol.</p>
        : <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
          <Value label="Holders" value={count(owners.holders)} title={label} />
          <Value label="Held by institutions" value={percent(owners.percent_held)} title={label} />
          <Value label="Existing holders buying" value={count(owners.buyers)} title={label} />
          <Value label="Existing holders selling" value={count(owners.sellers)} title={label} />
          <Value label="New holders" value={count(owners.new_holders)} title={label} />
          <Value label="Sold out" value={count(owners.sold_out_holders)} title={label} />
          <Value label="Shares bought" value={shares(owners.shares_bought)} title={label} />
          <Value label="Shares sold" value={shares(owners.shares_sold)} title={label} />
        </dl>}
      <p className="text-[10px] text-slate-500">{label}</p>
    </div>

    <div aria-label="Insider activity" role="group" className="space-y-2">
      <h4 className="text-slate-300">Insiders, last 90 days</h4>
      {fund ? <p className="text-slate-500">Not available for ETFs or funds.</p>
        : shown?.error ? <p className="text-amber-300">{shown.error}</p>
        : !data ? <p role="status" className="text-slate-500">Loading insider activity…</p>
        : data.state === "ready" ? <>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
            <Value label="Open-market buys" value={`${count(data.buys?.count)} · ${shares(data.buys?.shares)} sh`} />
            <Value label="Open-market sells" value={`${count(data.sells?.count)} · ${shares(data.sells?.shares)} sh`} />
            <Value label="Net shares" value={data.net_shares == null ? "—" : signed(data.net_shares, `${shares(Math.abs(data.net_shares))} sh`)} />
            <Value label="Net value" value={data.net_value == null ? "—" : signed(data.net_value, money(data.net_value))} title={data.net_value == null ? "Yahoo gave no value for at least one counted transaction." : undefined} />
          </dl>
          {data.buys?.count === 0 && data.sells?.count === 0 && <p className="text-slate-500">No open-market insider buys or sells in this window.</p>}
          {data.latest && data.latest.length > 0 && <ul aria-label="Latest insider transactions" className="space-y-1">
            {data.latest.map((row, index) => <li key={`${row.date}-${row.insider}-${index}`} className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-slate-300" title={row.position ?? undefined}>{row.date} · {row.insider ?? "Unknown"}</span>
              <span className={`shrink-0 font-mono ${row.kind === "buy" ? "text-emerald-300" : "text-rose-300"}`}>{row.kind === "buy" ? "Buy" : "Sell"} {shares(row.shares)}{row.value != null ? ` · ${money(row.value)}` : ""}</span>
            </li>)}
          </ul>}
          <p className="text-[10px] text-slate-500">{data.note}{data.excluded ? ` ${data.excluded} other filings left out.` : ""}</p>
          {data.message && <p className="text-[10px] text-amber-300">{data.message} Showing the cached copy from {readAt(data.fetched_at)}.</p>}
        </>
        : <p className={data.state === "none" ? "text-slate-500" : "text-amber-300"}>{data.message ?? "Insider activity is unavailable."}</p>}
      {!fund && data && <p className="text-[10px] text-slate-500">{data.source} · {readAt(data.fetched_at)}</p>}
    </div>
  </section>;
}
