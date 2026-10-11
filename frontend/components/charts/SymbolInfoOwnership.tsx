import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchSymbolInsiders, readAt } from "@/lib/symbolInfo";
import type { OverviewCompany, SymbolInsiders } from "@/lib/symbolInfo";
import { Block, EXPLAIN, Row, Rows, SourceFooter } from "./SymbolInfoParts";
import type { FooterSource } from "./SymbolInfoParts";

const count = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: 0 });
const compact = (value: number) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
const shares = (value: number | null | undefined) => value == null ? "—" : compact(value);
const signed = (value: number, text: string) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${text}`;
const money = (value: number) => `$${compact(Math.abs(value))}`;
const percent = (value: number | null) => value == null || value <= 0 ? "—" : `${(value * 100).toFixed(1)}%`;

type Owners = NonNullable<OverviewCompany["ownership"]>;
/**
 * Tradier sends 0, not null, when it has no 13F summary (Micron arrived with every count at 0). A listed stock
 * with no institutional holders cannot be real, so an all-zero summary is "not reported", and a zero holder count is "—".
 */
export const ownersReported = (owners: OverviewCompany["ownership"]): owners is Owners =>
  !!owners && [owners.holders, owners.buyers, owners.sellers, owners.new_holders, owners.sold_out_holders, owners.shares_bought, owners.shares_sold].some((value) => !!value);
const WHY_ZERO = "Tradier sent 0 for the holder count; that cannot be real for a listed stock, so it is not reported here.";

/** 13F summary from the Overview payload (no request of its own) and 90-day insider activity from one Yahoo-backed request. */
export default function SymbolInfoOwnership({ symbol, company, fund, unavailable, sources, children }: { symbol: string; company: OverviewCompany; fund: boolean; unavailable: string; sources: FooterSource[]; children?: ReactNode }) {
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
  const footer: FooterSource[] = [...sources, ...(data ? [{ source: data.source, at: data.fetched_at, label: "Insiders" }] : [])];

  return <>
  <Block name="ownership" title="Ownership"><div className="space-y-3">
    <div aria-label="13F institutional holders" role="group" className="space-y-1.5">
      <h4 className="text-slate-300">Institutions (13F){owners?.as_of ? <span className="font-normal text-slate-500"> · as of {owners.as_of}</span> : null}</h4>
      {company.state !== "ready" ? <p className={company.state === "none" ? "text-slate-500" : "text-amber-300"}>{company.state === "none" ? unavailable : company.message ?? "Not loaded yet."}</p>
        : !owners ? <p className="text-slate-500">Tradier lists no 13F filers for this symbol.</p>
        : !ownersReported(owners) ? <p className="text-slate-500">13F summary not reported by Tradier for this symbol.</p>
        : <Rows>
          <Row label="Holders" value={owners.holders ? count(owners.holders) : "—"} title={owners.holders ? label : `${WHY_ZERO} ${label}`} />
          <Row label="Held by institutions" value={percent(owners.percent_held)} title={label} explain={EXPLAIN.held} />
          <Row label="Existing holders buying" value={count(owners.buyers)} title={label} />
          <Row label="Existing holders selling" value={count(owners.sellers)} title={label} />
          <Row label="New holders" value={count(owners.new_holders)} title={label} />
          <Row label="Sold out" value={count(owners.sold_out_holders)} title={label} />
          <Row label="Shares bought" value={shares(owners.shares_bought)} title={label} />
          <Row label="Shares sold" value={shares(owners.shares_sold)} title={label} />
        </Rows>}
    </div>

    <div aria-label="Insider activity" role="group" className="space-y-1.5">
      <h4 className="flex flex-wrap items-baseline gap-x-1.5 text-slate-300">Insiders, last 90 days
        {data && <span title="Yahoo's insider feed is not an official source" className="text-[10px] font-normal text-slate-500">{data.source}</span>}</h4>
      {fund ? <p className="text-slate-500">Not available for ETFs or funds.</p>
        : shown?.error ? <p className="text-amber-300">{shown.error}</p>
        : !data ? <p role="status" className="text-slate-500">Loading insider activity…</p>
        : data.state === "ready" ? <>
          <Rows>
            <Row label="Open-market buys" value={`${count(data.buys?.count)} · ${shares(data.buys?.shares)} sh`} />
            <Row label="Open-market sells" value={`${count(data.sells?.count)} · ${shares(data.sells?.shares)} sh`} />
            <Row label="Net shares" value={data.net_shares == null ? "—" : signed(data.net_shares, `${shares(Math.abs(data.net_shares))} sh`)} />
            <Row label="Net value" value={data.net_value == null ? "—" : signed(data.net_value, money(data.net_value))} title={data.net_value == null ? "Yahoo gave no value for at least one counted transaction." : undefined} />
          </Rows>
          {data.buys?.count === 0 && data.sells?.count === 0 && <p className="text-slate-500">No open-market insider buys or sells in this window.</p>}
          {data.latest && data.latest.length > 0 && <ul aria-label="Latest insider transactions" className="divide-y divide-slate-800/70">
            {data.latest.map((row, index) => <li key={`${row.date}-${row.insider}-${index}`} className="py-1" title={`${row.insider ?? "Unknown"}${row.position ? ` · ${row.position}` : ""} · ${row.date}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-slate-300">{row.insider ?? "Unknown"}</span>
                <span className={`shrink-0 whitespace-nowrap font-mono ${row.kind === "buy" ? "text-emerald-300" : "text-rose-300"}`}>{row.kind === "buy" ? "Buy" : "Sell"} {shares(row.shares)}</span>
              </div>
              <div className="flex items-baseline justify-between gap-2 text-[10px] text-slate-500">
                <span className="min-w-0 truncate">{row.date}{row.position ? ` · ${row.position}` : ""}</span>
                {row.value != null && <span className="shrink-0 whitespace-nowrap font-mono">{money(row.value)}</span>}
              </div>
            </li>)}
          </ul>}
          <p className="text-[10px] text-slate-500">{data.note}{data.excluded ? ` ${data.excluded} other filings left out.` : ""}</p>
          {data.message && <p className="text-[10px] text-amber-300">{data.message} Showing the cached copy ({readAt(data.fetched_at)}).</p>}
        </>
        : <p className={data.state === "none" ? "text-slate-500" : "text-amber-300"}>{data.message ?? "Insider activity is unavailable."}</p>}
    </div>
  </div></Block>
  {children}
  <SourceFooter items={footer} />
  </>;
}
