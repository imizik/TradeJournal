"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, X } from "lucide-react";
import { etTime, price } from "@/lib/charts";
import PlanSummary from "./PlanSummary";
import { fetchOptionMark, MARK_STALE_SECONDS, type MetricState, type ObservedUnderlying, type OptionMark, type TradeCardData } from "@/lib/chartJournal";

const STATE: Record<MetricState, { text: string; style: string }> = {
  current: { text: "Current", style: "bg-emerald-400/10 text-emerald-300" },
  stale: { text: "Stale", style: "bg-amber-400/10 text-amber-300" },
  missing: { text: "Missing", style: "bg-slate-800 text-slate-400" },
};
const SOURCES: Record<string, string> = { alpaca_sip: "Alpaca SIP", alpaca_iex: "Alpaca IEX (one exchange)", fill_enrichment: "fill enrichment", polygon: "Polygon" };
const SIDES: Record<string, string> = { buy_to_open: "Buy to open", sell_to_close: "Sell to close", sell_to_open: "Sell to open", buy_to_close: "Buy to close", buy: "Buy", sell: "Sell" };

const money = (value: number | null | undefined) => value == null ? "—" : `${value < 0 ? "−" : value > 0 ? "+" : ""}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (value: number | null | undefined, digits = 2) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
const tone = (value: number | null | undefined) => value == null || value === 0 ? "text-slate-300" : value > 0 ? "text-emerald-400" : "text-rose-400";
const when = (stamp: number) => `${etTime(stamp, true)} ${etTime(stamp)} ET`;
const qty = (value: number) => value % 1 ? value.toFixed(4).replace(/0+$/, "") : String(value);
const source = (name?: string | null) => name ? SOURCES[name] ?? name : "unknown source";
const flag = (value: boolean | null | undefined) => value == null ? "—" : value ? "Yes" : "No";

function Row({ label, value, className = "text-slate-300", title }: { label: string; value: React.ReactNode; className?: string; title?: string }) {
  return <div className="flex justify-between gap-3" title={title}><span className="text-slate-500">{label}</span><span className={`text-right font-mono ${className}`}>{value}</span></div>;
}
function Section({ title, state, note, children }: { title: string; state?: MetricState; note?: string; children?: React.ReactNode }) {
  return <section aria-label={title} className="mt-2 border-t border-slate-700/50 pt-2">
    <div className="mb-1 flex items-center gap-2"><h3 className="text-[11px] font-medium text-slate-200">{title}</h3>
      {state && <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATE[state].style}`}>{STATE[state].text}</span>}</div>
    {children && <div className="space-y-0.5">{children}</div>}
    {note && <p className="mt-1 text-[10px] leading-4 text-slate-500">{note}</p>}
  </section>;
}
function Underlying({ value }: { value: ObservedUnderlying | null }) {
  if (!value) return <span className="text-slate-500">underlying not recorded</span>;
  return <span title={value.single_venue ? "Read from one exchange's prints" : undefined}>underlying {price(value.price)} <span className="text-slate-500">({source(value.source)})</span></span>;
}

/**
 * A fill arrow's card (C3.1): the trade it belongs to, its entries and exits,
 * realized or open P&L, MFE/MAE and exit efficiency from the trade path run,
 * and the entry's market context from enrichment. Missing and stale numbers say
 * so, and an option's premium is never presented as an underlying price.
 */
export default function TradeCard({ card, loading, error, last, onClose, onShow }: {
  card: TradeCardData | null; loading: boolean; error: string;
  /** The chart's latest price, for a stock position's open P&L. */
  last: number | null;
  onClose(): void;
  /** Bring the whole trade into view on the main chart. */
  onShow?(from: number, to: number): void;
}) {
  const [mark, setMark] = useState<{ state: "idle" | "loading" | "error"; data?: OptionMark; error?: string }>({ state: "idle" });
  const trade = card?.trade;
  const option = trade?.instrument === "option";
  const position = card?.position ?? null;
  const unit = option ? "/contract" : "/sh";
  const stockOpen = !option && position?.avg_cost != null && last != null ? (last - position.avg_cost) * position.open * (trade?.direction === "short" ? -1 : 1) : null;
  const markAge = mark.data?.quoted_at ? Math.max(0, Math.floor(Date.now() / 1000 - mark.data.quoted_at)) : null;
  const askMark = async () => {
    if (!trade) return;
    setMark({ state: "loading" });
    try { setMark({ state: "idle", data: await fetchOptionMark(trade.id) }); }
    catch (err) { setMark({ state: "error", error: err instanceof Error ? err.message : "The mark could not be read." }); }
  };
  const path = card?.path;
  const context = card?.context;
  return <div className="p-3 text-[11px] text-slate-300" aria-label="Trade card" role="region">
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-sm font-semibold text-slate-100">{trade?.contract ?? card?.fill?.contract ?? "Trade"}</h2>
        {trade && <p className="text-[10px] text-slate-400">{trade.account ? `${trade.account.name} ··${trade.account.last4}` : "Unknown account"} · {trade.direction === "short" ? "Short" : "Long"} · <span className={trade.status === "open" ? "text-sky-300" : ""}>{trade.status === "expired" ? "Expired" : trade.status === "open" ? "Open" : "Closed"}</span></p>}
      </div>
      <button aria-label="Close trade card" onClick={onClose} className="-m-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"><X size={14} /></button>
    </div>
    {loading && <p role="status" className="mt-2 flex items-center gap-1.5 text-slate-400"><Loader2 size={12} className="animate-spin" />Reading the journal…</p>}
    {error && <p role="alert" className="mt-2 text-rose-300">{error}</p>}
    {card && !trade && <p className="mt-2 text-slate-400">{card.note}</p>}
    {trade && <>
      <p className="mt-1.5 text-[10px] leading-4 text-slate-500">{trade.price_note}</p>
      <div className="mt-1.5 space-y-0.5">
        <Row label="Opened" value={when(trade.opened_at)} />
        <Row label={trade.status === "expired" ? "Expired" : "Closed"} value={trade.closed_at ? when(trade.closed_at) : "—"} />
        <Row label={option ? "Contracts" : "Shares"} value={qty(trade.contracts)} />
        <Row label="Avg entry" value={`$${price(trade.avg_entry)}${unit}`} />
        <Row label="Avg exit" value={trade.avg_exit == null ? "—" : `$${price(trade.avg_exit)}${unit}`} />
        {trade.status !== "open" && <Row label="Realized P&L" value={<>{money(trade.realized_pnl)} <span className="text-slate-500">{pct(trade.pnl_pct)}</span></>} className={tone(trade.realized_pnl)} />}
      </div>
      {position && <Section title="Still open">
        <Row label={option ? "Contracts open" : "Shares open"} value={qty(position.open)} />
        <Row label="Avg cost of open" value={position.avg_cost == null ? "—" : `$${price(position.avg_cost)}${unit}`} title="First in, first out: what the lots still open cost" />
        <Row label="Realized so far" value={money(position.realized)} className={tone(position.realized)} />
        {!option ? <Row label="Open P&L" value={stockOpen == null ? "—" : money(stockOpen)} className={tone(stockOpen)} title="At the chart's latest price" />
          : <div className="pt-1">
            {mark.data ? <>
              <Row label={`Mark (${mark.data.basis ?? "none"})`} value={mark.data.mark_per_contract == null ? "unavailable" : `$${price(mark.data.mark_per_contract)}/contract`} />
              <Row label="Open P&L" value={money(mark.data.open_pnl)} className={tone(mark.data.open_pnl)} />
              <p className={`text-[10px] ${markAge != null && markAge > MARK_STALE_SECONDS ? "text-amber-300" : "text-slate-500"}`}>
                {mark.data.quoted_at == null ? "No quote came back for this contract." : `${markAge != null && markAge > MARK_STALE_SECONDS ? "Stale: " : ""}quoted ${markAge! < 60 ? `${markAge}s` : `${Math.floor(markAge! / 60)}m`} ago by ${mark.data.provider ?? "the quotes provider"}.`}</p>
            </> : null}
            <button onClick={() => void askMark()} disabled={mark.state === "loading"} className="mt-1 inline-flex min-h-8 items-center gap-1 rounded border border-slate-700 px-2 text-[11px] text-slate-200 hover:bg-slate-800 disabled:opacity-50">
              {mark.state === "loading" && <Loader2 size={11} className="animate-spin" />}{mark.data ? "Refresh mark" : "Get mark and open P&L"}</button>
            {mark.state === "error" && <p role="alert" className="text-[10px] text-rose-300">{mark.error}</p>}
          </div>}
      </Section>}
      {card.plans !== undefined && <Section title="Plan">
        {card.plans.length ? card.plans.map((capture) => <PlanSummary key={capture.id} capture={capture} />)
          : <p className="text-slate-500">No plan linked. Plans saved with Plan trade are linked from Needs linking.</p>}
      </Section>}
      <Section title="Entries and exits">
        <ol className="space-y-1">{(card.fills ?? []).map((fill) => <li key={fill.id} className={card.fill?.id === fill.id ? "rounded bg-sky-400/10 px-1 -mx-1" : ""}>
          <div className="flex justify-between gap-2"><span><span className={fill.role === "entry" ? "text-sky-300" : "text-amber-300"}>{SIDES[fill.side] ?? fill.side}</span> {qty(fill.qty)} @ <span className="font-mono">${price(fill.price)}</span></span>
            <Link href={`/fills/${fill.id}`} className="shrink-0 text-[10px] text-slate-500 hover:text-sky-300">{etTime(fill.time, true)} {etTime(fill.time)}</Link></div>
          {option && fill.role === "entry" && <div className="text-[10px] text-slate-500"><Underlying value={fill.underlying} /></div>}
        </li>)}</ol>
      </Section>
      {path && <Section title="Path (MFE / MAE)" state={path.state} note={[path.note, path.source ? `Source: ${source(path.source)}.` : ""].filter(Boolean).join(" ")}>
        {path.state !== "missing" && <>
          <Row label="Underlying MFE / MAE" value={`${pct(path.underlying_mfe_pct)} / ${pct(path.underlying_mae_pct == null ? null : -path.underlying_mae_pct)}`} />
          <Row label="Exit efficiency (underlying)" value={path.underlying_exit_efficiency == null ? "—" : `${path.underlying_exit_efficiency.toFixed(0)}%`} />
          {option && <Row label="Option MFE / MAE" value={`${pct(path.option_mfe_pct, 1)} / ${pct(path.option_mae_pct == null ? null : -path.option_mae_pct, 1)}`} />}
          {option && <Row label="Exit efficiency (option)" value={path.option_exit_efficiency == null ? "—" : `${path.option_exit_efficiency.toFixed(0)}%`} />}
        </>}
      </Section>}
      {context && <Section title="Entry context" state={context.state} note={[context.note, context.source ? `Source: ${source(context.source)}${context.as_of ? `, as of ${etTime(context.as_of)} ET` : ""}.` : ""].filter(Boolean).join(" ")}>
        {context.state !== "missing" && <>
          {option && <Row label="Underlying at entry" value={price(context.entry_underlying_price)} />}
          <Row label="vs VWAP" value={pct(context.entry_vs_vwap_pct)} />
          <Row label="Relative volume" value={context.rvol_time_adjusted == null ? "—" : `${context.rvol_time_adjusted.toFixed(2)}×`} title="Time-of-day adjusted, from enrichment" />
          <Row label="Chase" value={`${flag(context.flags?.is_chase_entry)}${context.chase_score == null ? "" : ` (${context.chase_score.toFixed(0)})`}`} />
          <Row label="VWAP reclaim" value={flag(context.flags?.is_vwap_reclaim)} />
          <Row label="Opening-range breakout" value={flag(context.flags?.is_opening_range_breakout)} />
          <Row label="From day high / low" value={`${pct(context.entry_distance_from_day_high_pct)} / ${pct(context.entry_distance_from_day_low_pct)}`} />
          <Row label="From prior-day high / low" value={`${pct(context.entry_distance_from_prev_high_pct)} / ${pct(context.entry_distance_from_prev_low_pct)}`} />
          <Row label="From premarket high / low" value={`${pct(context.entry_distance_from_premarket_high_pct)} / ${pct(context.entry_distance_from_premarket_low_pct)}`} />
        </>}
      </Section>}
      <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-700/50 pt-2">
        <Link href={`/trades/${trade.id}`} className="inline-flex min-h-8 items-center rounded border border-slate-700 px-2 text-slate-200 hover:bg-slate-800">Trade page</Link>
        {card.fill && <Link href={`/fills/${card.fill.id}`} className="inline-flex min-h-8 items-center rounded border border-slate-700 px-2 text-slate-200 hover:bg-slate-800">Fill page</Link>}
        {onShow && <button onClick={() => onShow(trade.opened_at, trade.closed_at ?? trade.opened_at)} className="inline-flex min-h-8 items-center rounded border border-slate-700 px-2 text-slate-200 hover:bg-slate-800">Show whole trade</button>}
      </div>
    </>}
  </div>;
}
