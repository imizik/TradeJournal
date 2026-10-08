import type { ReactNode } from "react";
import { copyAge, eventDay, readAt } from "@/lib/symbolInfo";
import type { ShortBlockMeta, ShortBorrow, ShortInterest, ShortVolume, SymbolShort } from "@/lib/symbolInfo";

const count = (value: number) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
const shortDay = (day: string) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" }).format(new Date(`${day}T00:00:00Z`));
const whole = (value: number) => value.toLocaleString("en-US");

/** A block's footer: where it came from and when it was read; an older copy says why and how old it is. */
function Source({ block }: { block: Pick<ShortBlockMeta, "source" | "fetched_at" | "age_seconds" | "stale" | "message"> }) {
  return <>
    {block.stale && <p role="status" className="text-[10px] text-amber-300">{block.message} Copy is {copyAge(block.age_seconds)}.</p>}
    <p className="text-[10px] text-slate-500">{block.source} · {readAt(block.fetched_at)}</p>
  </>;
}

function Block({ title, block, children }: { title: string; block: ShortBlockMeta; children: () => ReactNode }) {
  return <section aria-label={title} className="space-y-2">
    <h3 className="text-slate-400">{title}</h3>
    {block.state === "ready" ? <>{children()}<Source block={block} /></>
      : block.state === "none" ? <><p className="text-slate-500">{block.none_message}</p><p className="text-[10px] text-slate-500">{block.source}</p></>
      : <p role="status" className="text-amber-300">{block.message ?? "Not loaded yet."}</p>}
  </section>;
}

function Interest({ data }: { data: ShortInterest }) {
  return <Block title="Short interest" block={data}>{() => <>
    <p className="text-sm text-slate-100"><span title="Observed · FINRA short interest, shares sold short and not yet covered">{count(data.short_interest!)} shares</span>
      <span className="text-slate-500"> · settled {eventDay(data.settlement_date!)}</span></p>
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
      <div title="Observed · Polygon's days to cover: short interest over average daily volume">
        <dt className="text-slate-500">Days to cover</dt><dd className="font-mono text-slate-200">{data.days_to_cover != null ? data.days_to_cover.toFixed(2) : "—"}</dd></div>
      <div title={data.shares_outstanding ? `Calculated · short interest over ${whole(data.shares_outstanding)} shares outstanding. ${data.pct_note ?? ""}` : data.pct_message ?? undefined}>
        <dt className="text-slate-500">% of shares outstanding</dt>
        <dd className="font-mono text-slate-200">{data.pct_of_shares_outstanding != null ? `${data.pct_of_shares_outstanding.toFixed(2)}%` : "—"}</dd></div>
      {data.previous && <div title={`Calculated · against ${data.previous.settlement_date}: ${whole(data.previous.short_interest)} shares`}>
        <dt className="text-slate-500">Since prior report</dt>
        <dd className={`font-mono ${data.previous.change_pct > 0 ? "text-rose-300" : data.previous.change_pct < 0 ? "text-emerald-300" : "text-slate-200"}`}>{data.previous.change_pct > 0 ? "+" : ""}{data.previous.change_pct.toFixed(1)}%</dd></div>}
      {data.avg_daily_volume != null && <div title="Observed · the average daily volume FINRA used for days to cover">
        <dt className="text-slate-500">Avg daily volume</dt><dd className="font-mono text-slate-200">{count(data.avg_daily_volume)}</dd></div>}
    </dl>
    {data.pct_message && <p className="text-[10px] text-amber-300">{data.pct_message}</p>}
    <p className="text-[10px] text-slate-500">{data.pct_note} {data.settlement_note}</p>
  </>}</Block>;
}

function Borrow({ data }: { data: ShortBorrow }) {
  return <section aria-label="Borrow" className="space-y-2">
    <h3 className="text-slate-400">Borrow</h3>
    {data.state === "unavailable" ? <p role="status" className="text-amber-300">{data.message}</p> : <>
      <p className="flex flex-wrap items-center gap-2">
        <span title="Observed · whether the symbol is on Tradier's easy-to-borrow list"
          className={`rounded border px-1.5 py-0.5 text-[10px] ${data.hard_to_borrow ? "border-amber-400/60 bg-amber-400/10 text-amber-200" : "border-emerald-400/50 text-emerald-300"}`}>
          {data.hard_to_borrow ? "Hard to borrow" : "Easy to borrow"}</span>
        <span className="text-slate-400">{data.hard_to_borrow ? "Not on Tradier's easy-to-borrow list" : "On Tradier's easy-to-borrow list"}</span>
      </p>
      {data.hard_to_borrow && <p className="text-slate-400">{data.note}</p>}
      <Source block={data} />
    </>}
  </section>;
}

function Volume({ data }: { data: ShortVolume }) {
  const rows = data.rows ?? [];
  return <Block title={`Short volume · last ${rows.length || 10} sessions`} block={data}>{() => <>
    <p className="text-slate-400"><span title="Calculated · total short volume over total FINRA-reported volume across the listed sessions">Average {data.average_pct?.toFixed(1)}%</span> of FINRA-reported volume</p>
    <ul className="space-y-1" aria-label="Daily short volume ratio">
      {rows.map((row) => <li key={row.date} className="grid grid-cols-[4.5rem_1fr_3.5rem] items-center gap-2"
        title={`Calculated · ${whole(row.short_volume)} short of ${whole(row.total_volume)} FINRA-reported shares`}>
        <span className="text-slate-400">{shortDay(row.date)}</span>
        <span className="h-1.5 rounded bg-slate-800" aria-hidden><span className="block h-full rounded bg-sky-400/70" style={{ width: `${Math.min(100, row.ratio_pct)}%` }} /></span>
        <span className="text-right font-mono text-slate-200">{row.ratio_pct.toFixed(1)}%</span></li>)}
    </ul>
    <p className="text-[10px] text-slate-500">{data.note}</p>
  </>}</Block>;
}

/** The Short tab (T3.1). Each block degrades on its own; the borrow flag needs no Polygon read. */
export default function SymbolInfoShort({ data }: { data: SymbolShort }) {
  return <div className="space-y-5 text-[11px]">
    <Interest data={data.interest} />
    <Borrow data={data.borrow} />
    <Volume data={data.volume} />
  </div>;
}
