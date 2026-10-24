import Link from "next/link";
import type { DecisionRecord, PositionQuote } from "@/lib/api";
import { api } from "@/lib/serverApi";
import type { OpenPositionRow } from "@/lib/dashboard";
import type { Earnings } from "@/lib/symbolInfo";
import { buildAttention, type AttentionItem, type AttentionPriority } from "@/lib/dashboardAttention";
import { DashboardCard } from "./DashboardCard";

const SHOWN = 6;
// Read once per request, after the sources arrive, so ages are measured against them.
const requestTime = () => Date.now();
const DOT: Record<AttentionPriority, string> = {
  integrity: "bg-red-400", data: "bg-red-400", soon: "bg-amber-400", alert: "bg-sky-400", follow_up: "bg-muted-foreground",
};
const CUE: Record<AttentionPriority, string> = {
  integrity: "text-red-300", data: "text-red-300", soon: "text-amber-300", alert: "text-sky-300", follow_up: "text-muted-foreground",
};

/** Streams in after the rest of the Dashboard: its extra sources (alerts,
 * sync jobs, import health, earnings dates) must never delay the journal. */
export default async function AttentionPanel({ rows, quotes, quoteError, today, decisions, scope }: {
  /** Set when Dashboard filters narrow the positions; import, sync, alerts and WAITs are never filtered. */
  scope: string | null;
  rows: OpenPositionRow[]; quotes: Record<string, PositionQuote>; quoteError: boolean; today: string; decisions: DecisionRecord[];
}) {
  const optionTickers = [...new Set(rows.filter(({ trade }) => trade.instrument_type === "option"
    && trade.expiration && trade.expiration.slice(0, 10) >= today).map(({ trade }) => trade.ticker))].sort();
  const optionIds = rows.filter(({ trade }) => trade.instrument_type === "option").map(({ trade }) => trade.id);
  const [alerts, jobs, gmail, events, phone] = await Promise.all([
    api.levelAlerts().then((payload) => payload.alerts, () => null),
    api.syncJobs().catch(() => null),
    api.gmailHealth().catch(() => null),
    Promise.all(optionTickers.map((ticker) => api.symbolEvents(ticker).then((value) => value.earnings as Earnings, () => null))),
    Promise.all(optionIds.map((id) => api.tradePhoneAlerts(id).then((value) => value.alerts, () => null))),
  ]);
  const { items, unavailable } = buildAttention({
    rows, quotes, quoteError, today, now: requestTime(), decisions, alerts, jobs, gmail,
    earnings: Object.fromEntries(optionTickers.map((ticker, index) => [ticker, events[index]])),
    phoneAlerts: Object.fromEntries(optionIds.map((id, index) => [id, phone[index]])),
  });
  return <AttentionCard items={items} unavailable={unavailable} scope={scope} />;
}

function AttentionRow({ item, index }: { item: AttentionItem; index: number }) {
  return <li>
    <Link href={item.href} className="flex min-h-11 items-start gap-3 rounded-md px-2 py-2 hover:bg-secondary" data-attention-id={item.id}>
      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] tabular-nums text-muted-foreground">{index + 1}</span>
      <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[item.priority]}`} />
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-foreground">{item.title}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{item.detail}</span>
      </span>
      <span className={`shrink-0 text-[11px] tabular-nums ${CUE[item.priority]}`}>{item.when}</span>
      <span aria-hidden className="shrink-0 text-xs text-muted-foreground">›</span>
    </Link>
  </li>;
}

export function AttentionCard({ items, unavailable, scope = null }: { items: AttentionItem[]; unavailable: string[]; scope?: string | null }) {
  const count = <span className={`inline-grid min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums ${items.length ? "bg-red-500/80 text-white" : "bg-secondary text-muted-foreground"}`}
    aria-label={`${items.length} item${items.length === 1 ? "" : "s"}`}>{items.length}</span>;
  return <DashboardCard title="Attention" action={count}>
    {items.length === 0
      ? <p className="text-sm text-muted-foreground">Nothing needs a look right now.</p>
      : <ol className="-mx-2 space-y-0.5">{items.slice(0, SHOWN).map((item, index) => <AttentionRow key={item.id} item={item} index={index} />)}</ol>}
    {items.length > SHOWN && <details className="group -mx-2 mt-1">
      <summary className="flex min-h-11 cursor-pointer items-center px-2 text-xs text-primary sm:min-h-8">
        <span className="group-open:hidden">Show {items.length - SHOWN} more</span><span className="hidden group-open:inline">Show fewer</span>
      </summary>
      <ol className="space-y-0.5" start={SHOWN + 1}>{items.slice(SHOWN).map((item, index) => <AttentionRow key={item.id} item={item} index={index + SHOWN} />)}</ol>
    </details>}
    {scope && <p className="mt-3 text-xs text-muted-foreground">Position checks cover {scope} only; clear the filters to check every position.</p>}
    {unavailable.length > 0 && <p className="mt-3 text-xs text-amber-300">Could not check: {unavailable.join("; ")}.</p>}
  </DashboardCard>;
}

export function AttentionLoading() {
  return <DashboardCard title="Attention" action={<span className="text-xs text-muted-foreground">Checking…</span>}>
    <div className="space-y-2" aria-label="Loading attention items">
      {[0, 1, 2].map((key) => <div key={key} className="h-9 animate-pulse rounded-md bg-secondary/60" />)}
    </div>
  </DashboardCard>;
}
