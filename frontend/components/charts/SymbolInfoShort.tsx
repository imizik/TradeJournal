import type { ReactNode } from "react";
import { copyAge, eventDay } from "@/lib/symbolInfo";
import type { ShortBlockMeta, ShortBorrow, ShortInterest, ShortVolume, SymbolShort } from "@/lib/symbolInfo";
import { HEADING, Row, Rows, SourceFooter } from "./SymbolInfoParts";
import type { FooterSource } from "./SymbolInfoParts";

const count = (value: number) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
const shortDay = (day: string) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" }).format(new Date(`${day}T00:00:00Z`));
const whole = (value: number) => value.toLocaleString("en-US");

/** A block that is an older copy says so, with how old it is. The source line is the tab's single footer. */
function Stale({ block }: { block: Pick<ShortBlockMeta, "age_seconds" | "stale" | "message"> }) {
  return block.stale ? <p role="status" className="text-[10px] text-amber-300">{block.message} Copy is {copyAge(block.age_seconds)}.</p> : null;
}

function Block({ title, block, children }: { title: string; block: ShortBlockMeta; children: () => ReactNode }) {
  return <section aria-label={title} className="space-y-1.5">
    <h3 className={HEADING}>{title}</h3>
    {block.state === "ready" ? <>{children()}<Stale block={block} /></>
      : block.state === "none" ? <p className="text-slate-500">{block.none_message}</p>
      : <p role="status" className="text-amber-300">{block.message ?? "Not loaded yet."}</p>}
  </section>;
}

function Interest({ data }: { data: ShortInterest }) {
  return <Block title="Short interest" block={data}>{() => <>
    <p className="text-sm text-slate-100"><span title="Observed · FINRA short interest, shares sold short and not yet covered">{count(data.short_interest!)} shares</span>
      <span className="text-slate-500"> · settled {eventDay(data.settlement_date!)}</span></p>
    <Rows>
      <Row label="Days to cover" value={data.days_to_cover != null ? data.days_to_cover.toFixed(2) : "—"} title="Observed · Polygon's days to cover: short interest over average daily volume" />
      <Row label="% of shares outstanding" value={data.pct_of_shares_outstanding != null ? `${data.pct_of_shares_outstanding.toFixed(2)}%` : "—"}
        title={data.shares_outstanding ? `Calculated · short interest over ${whole(data.shares_outstanding)} shares outstanding. ${data.pct_note ?? ""}` : data.pct_message ?? undefined} />
      {data.previous && <Row label="Since prior report" value={`${data.previous.change_pct > 0 ? "+" : ""}${data.previous.change_pct.toFixed(1)}%`}
        tone={data.previous.change_pct > 0 ? "text-rose-300" : data.previous.change_pct < 0 ? "text-emerald-300" : undefined}
        title={`Calculated · against ${data.previous.settlement_date}: ${whole(data.previous.short_interest)} shares`} />}
      {data.avg_daily_volume != null && <Row label="Avg daily volume" value={count(data.avg_daily_volume)} title="Observed · the average daily volume FINRA used for days to cover" />}
    </Rows>
    {data.pct_message && <p className="text-[10px] text-amber-300">{data.pct_message}</p>}
    <p className="text-[10px] text-slate-500">{data.pct_note} {data.settlement_note}</p>
  </>}</Block>;
}

function Borrow({ data }: { data: ShortBorrow }) {
  return <section aria-label="Borrow" className="space-y-1.5">
    <h3 className={HEADING}>Borrow</h3>
    {data.state === "unavailable" ? <p role="status" className="text-amber-300">{data.message}</p> : <>
      <p className="flex flex-wrap items-center gap-2">
        <span title="Observed · whether the symbol is on Tradier's easy-to-borrow list"
          className={`rounded border px-1.5 py-0.5 text-[10px] ${data.hard_to_borrow ? "border-amber-400/60 bg-amber-400/10 text-amber-200" : "border-emerald-400/50 text-emerald-300"}`}>
          {data.hard_to_borrow ? "Hard to borrow" : "Easy to borrow"}</span>
        <span className="text-slate-400">{data.hard_to_borrow ? "Not on Tradier's easy-to-borrow list" : "On Tradier's easy-to-borrow list"}</span>
      </p>
      {data.hard_to_borrow && <p className="text-slate-400">{data.note}</p>}
      <Stale block={data} />
    </>}
  </section>;
}

function Volume({ data }: { data: ShortVolume }) {
  const rows = data.rows ?? [];
  return <Block title={`Short volume · last ${rows.length || 10} sessions`} block={data}>{() => <>
    <p className="text-slate-400"><span title="Calculated · total short volume over total FINRA-reported volume across the listed sessions">Average {data.average_pct?.toFixed(1)}%</span> of FINRA-reported volume</p>
    <ul className="space-y-0.5" aria-label="Daily short volume ratio">
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
  const { interest, borrow, volume } = data;
  const sources: FooterSource[] = [
    { source: interest.source, at: interest.state === "ready" ? interest.fetched_at : undefined, label: "Short interest" },
    ...(borrow.state === "unavailable" ? [] : [{ source: borrow.source, at: borrow.fetched_at, label: "Borrow" }]),
    { source: volume.source, at: volume.state === "ready" ? volume.fetched_at : undefined, label: "Short volume" },
  ];
  return <div className="space-y-4 text-[11px]">
    <Interest data={interest} />
    <Borrow data={borrow} />
    <Volume data={volume} />
    <SourceFooter items={sources} />
  </div>;
}
