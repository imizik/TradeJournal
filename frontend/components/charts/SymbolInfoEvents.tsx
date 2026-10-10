import type { ReactNode } from "react";
import { useClock } from "@/lib/chartStore";
import { BADGE_DAYS, daysUntil, eventDay, readAt } from "@/lib/symbolInfo";
import type { Dividend, EventsBlock, SymbolEvents } from "@/lib/symbolInfo";

const money = (value: number, currency: string) => value.toLocaleString("en-US", { style: "currency", currency, maximumFractionDigits: 6 });
const away = (days: number) => days === 0 ? "today" : days === 1 ? "tomorrow" : days < 0 ? `${-days} days ago` : `in ${days} days`;

/** One dataset's block: its rows, or why there are none, with the source and when it was read. */
function Block({ title, block, none, children }: { title: string; block: EventsBlock; none: string; children: ReactNode }) {
  return <section aria-label={title} className="space-y-2">
    <h3 className="text-slate-400">{title}</h3>
    {block.state === "ready" ? children
      : block.state === "none" ? <p className="text-slate-500">{none}</p>
      : <p className="text-amber-300">{block.message ?? "Not loaded yet."}</p>}
    {block.state === "ready" && block.message && <p className="text-[10px] text-amber-300">{block.message} Showing the copy {readAt(block.fetched_at)}.</p>}
    <p className="text-[10px] text-slate-500">{block.source} · {readAt(block.fetched_at)}</p>
  </section>;
}

function DividendRow({ label, row }: { label: string; row: Dividend | null }) {
  return <div title={row ? `Observed · Tradier type ${row.type || "—"}${row.record_date ? ` · record ${row.record_date}` : ""}${row.declared ? ` · declared ${row.declared}` : ""}` : undefined}>
    <dt className="text-slate-500">{label}</dt>
    <dd className="mt-1 text-slate-200">{row ? <>{eventDay(row.ex_date)} · <span className="font-mono">{money(row.amount, row.currency)}</span>{row.pay_date && <span className="text-slate-500"> · pays {eventDay(row.pay_date)}</span>}</> : "None announced"}</dd>
  </div>;
}

/** The Events tab (T1.4): next earnings, the last eight reports, dividends and splits. */
export default function SymbolInfoEvents({ data }: { data: SymbolEvents }) {
  const { earnings, dividends, splits } = data;
  const next = earnings.next;
  // Days away from New York's today; this re-renders when the date turns, not every second.
  const days = useClock((now) => next ? daysUntil(next.date, now * 1000) : null);
  return <div className="space-y-5 text-[11px]">
    <Block title="Next earnings" block={earnings} none={`Tradier lists no earnings for ${data.symbol}. ETFs, funds and indices do not report them.`}>
      {next && days !== null ? <div className="space-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-100">
          <span title="Observed · the date Tradier's calendar gives">{eventDay(next.date)}</span>
          <span title={next.status === "estimated" ? "Estimated · Tradier's estimate; the company has not announced this date" : "Observed · the company's announced date"}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${next.status === "estimated" ? "border-dashed border-violet-400/50 text-violet-200" : "border-violet-400/60 bg-violet-400/10 text-violet-200"}`}>
            {next.status === "estimated" ? "Estimated" : "Confirmed"}</span>
        </p>
        <p className="text-slate-400"><span title={`Calculated · New York calendar days; the chart shows a badge within ${BADGE_DAYS}`}>{away(days)}</span> · {next.label}</p>
        <p className="text-slate-500" title={earnings.time_note}>Time of day not published</p>
      </div> : <p className="text-slate-400">Not announced. Nothing is shown until Tradier lists a date.</p>}
      {earnings.reports.length > 0 && <div>
        <h4 className="mt-3 text-slate-400">Past reports · last {earnings.reports.length}</h4>
        <ul className="mt-1 divide-y divide-slate-800">
          {earnings.reports.map((report) => <li key={report.date} className="flex justify-between gap-2 py-1.5" title="Observed · confirmed report date">
            <span className="text-slate-300">{eventDay(report.date)}</span><span className="text-slate-500">{report.label}</span></li>)}
        </ul>
      </div>}
    </Block>
    <Block title="Dividends" block={dividends} none={`No cash dividends on record for ${data.symbol}.`}>
      <dl className="space-y-2">
        <DividendRow label="Next ex-dividend" row={dividends.next} />
        <DividendRow label="Last ex-dividend" row={dividends.last} />
      </dl>
    </Block>
    <Block title="Splits · last two years" block={splits} none={`No splits on record for ${data.symbol}.`}>
      {splits.rows.length ? <ul className="space-y-1">
        {splits.rows.map((split) => <li key={split.ex_date} className="flex justify-between gap-2" title={`Observed · ${split.to} new shares for every ${split.from}`}>
          <span className="text-slate-300">{eventDay(split.ex_date)}</span><span className="font-mono text-slate-200">{split.label}</span></li>)}
      </ul> : <p className="text-slate-500">No splits in the last two years</p>}
    </Block>
  </div>;
}
