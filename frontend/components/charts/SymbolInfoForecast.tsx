import { useEffect, useState } from "react";
import { eventDay, fetchSymbolAnalysts } from "@/lib/symbolInfo";
import type { AnalystBlock, ImpliedMove, SymbolAnalysts, SymbolForecast } from "@/lib/symbolInfo";

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const quote = (bid: number | null | undefined, ask: number | null | undefined) => `${bid?.toFixed(2) ?? "—"} × ${ask?.toFixed(2) ?? "—"}`;

/** Which rows one expiration answers: "0DTE · Friday", "After earnings (est.)". */
function names(move: ImpliedMove, data: SymbolForecast): string {
  return move.tags.map((tag) => tag === "nearest" ? (move.days === 0 ? "0DTE" : "Nearest")
    : tag === "friday" ? "This Friday"
    : `After earnings ${data.earnings ? eventDay(data.earnings.date).replace(/, \d{4}$/, "") : ""}${data.earnings?.status === "estimated" ? " (est.)" : ""}`).join(" · ");
}

const compact = (n: number) => Math.abs(n) >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(0)}M` : n.toFixed(2);
const RATINGS = [["strong_buy", "Strong Buy", "bg-emerald-500"], ["buy", "Buy", "bg-emerald-700"], ["hold", "Hold", "bg-slate-500"], ["sell", "Sell", "bg-rose-700"], ["strong_sell", "Strong Sell", "bg-rose-500"]] as const;

const Source = ({ block }: { block: AnalystBlock<unknown> }) => <span className="rounded bg-slate-800 px-1 text-[9px] uppercase tracking-wider text-slate-400">{block.source}</span>;
const Missing = ({ block, what }: { block: AnalystBlock<unknown>; what: string }) => <p className={block.state === "unavailable" ? "text-amber-300" : "text-slate-500"}>{block.state === "unavailable" ? block.message ?? `${what} unavailable.` : `No ${what} published.`}</p>;

/** Analyst consensus (T2.3): Webull targets and ratings, Yahoo (unofficial) for estimates and actions; each block names its source. */
function Analysts({ symbol, spot }: { symbol: string; spot: number | null }) {
  const [data, setData] = useState<SymbolAnalysts | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchSymbolAnalysts(symbol, controller.signal).then(setData, (e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [symbol]);
  if (error) return <p className="text-amber-300">{error}</p>;
  if (!data) return <p className="text-slate-500">Loading analyst data…</p>;
  const { targets, ratings, estimates, history, actions } = data.blocks;
  const t = targets.value, r = ratings.value;
  const total = r ? RATINGS.reduce((sum, [key]) => sum + (r[key] ?? 0), 0) : 0;
  const upside = t?.median != null && spot ? (t.median / spot - 1) * 100 : null;
  return <section aria-label="Analyst consensus" className="space-y-3">
    <div className="space-y-1"><h3 className="flex items-center gap-2 text-slate-400">Price target {t && <Source block={targets} />}</h3>
      {t ? <>
        <p className="font-mono text-slate-100">Median ${t.median?.toFixed(2) ?? "—"} <span className="text-slate-400">· mean ${t.mean?.toFixed(2) ?? "—"}</span>
          {upside != null && <span className={upside >= 0 ? " text-emerald-300" : " text-rose-300"}> · {upside >= 0 ? "+" : ""}{upside.toFixed(1)}% vs {spot?.toFixed(2)}</span>}</p>
        <p className="text-[10px] text-slate-500">Low ${t.low?.toFixed(2) ?? "—"} · High ${t.high?.toFixed(2) ?? "—"}</p></>
        : <Missing block={targets} what="price targets" />}</div>
    <div className="space-y-1"><h3 className="flex items-center gap-2 text-slate-400">Ratings {r && <Source block={ratings} />}</h3>
      {r && total > 0 ? <>
        <div className="flex h-2 overflow-hidden rounded" role="img" aria-label={RATINGS.map(([key, label]) => `${label} ${r[key] ?? 0}`).join(", ")}>
          {RATINGS.map(([key, label, color]) => (r[key] ?? 0) > 0 && <div key={key} className={color} style={{ width: `${((r[key] ?? 0) / total) * 100}%` }} title={`${label} ${r[key]}`} />)}</div>
        <p className="text-[10px] text-slate-400">{RATINGS.map(([key, label]) => `${label} ${r[key] ?? 0}`).join(" · ")}</p></>
        : <Missing block={ratings} what="ratings" />}</div>
    <div className="space-y-1"><h3 className="flex items-center gap-2 text-slate-400">Estimates {estimates.value && <Source block={estimates} />}</h3>
      {estimates.value ? <ul className="divide-y divide-slate-800">{estimates.value.map((e) => <li key={e.period} className="py-1.5" aria-label={`${e.period} estimates`}>
        <span className="text-slate-300">{e.period}</span>
        {e.eps && <p className="font-mono text-slate-100">EPS ${e.eps.avg.toFixed(2)} <span className="text-slate-500">({e.eps.low?.toFixed(2) ?? "—"}–{e.eps.high?.toFixed(2) ?? "—"}{e.eps.analysts ? `, ${e.eps.analysts} analysts` : ""})</span></p>}
        {e.revenue && <p className="font-mono text-slate-100">Revenue ${compact(e.revenue.avg)} <span className="text-slate-500">({compact(e.revenue.low ?? e.revenue.avg)}–{compact(e.revenue.high ?? e.revenue.avg)})</span></p>}</li>)}</ul>
        : <Missing block={estimates} what="estimates" />}
      {history.value && <p className="text-[10px] text-slate-400">Last {history.value.length} reports: {history.value.map((h) => `${h.result === "beat" ? "beat" : h.result === "miss" ? "missed" : "met"} ${h.surprise != null ? `${(h.surprise * 100).toFixed(1)}%` : ""}`.trim()).join(" · ")}</p>}</div>
    <div className="space-y-1"><h3 className="flex items-center gap-2 text-slate-400">Recent analyst actions {actions.value && <Source block={actions} />}</h3>
      {actions.value ? <ul className="divide-y divide-slate-800">{actions.value.map((a) => <li key={`${a.date}${a.firm}`} className="flex justify-between gap-2 py-1">
        <span className="min-w-0 text-slate-300">{a.firm} <span className="text-slate-500">· {a.date.slice(5)} · {a.action ?? a.to_grade ?? ""}</span></span>
        <span className="shrink-0 font-mono text-slate-100">{a.target ? `${a.prior_target ? `$${a.prior_target.toFixed(0)} → ` : ""}$${a.target.toFixed(0)}` : a.to_grade ?? ""}</span></li>)}</ul>
        : <Missing block={actions} what="analyst actions" />}</div>
    <p className="text-[10px] leading-4 text-slate-500">What analysts publish, not a forecast of where price will go. Cached for a day.</p>
  </section>;
}

/**
 * The Forecast tab (T2.1): the implied move, from the at-the-money straddle's
 * mid for the nearest expiration, the nearest Friday and the first expiration
 * after the next report. Calculated from quotes, with their times; a one-sided
 * or very wide market shows why there is no number instead of one.
 */
export default function SymbolInfoForecast({ data }: { data: SymbolForecast }) {
  return <div className="space-y-3 text-[11px]">
    <section aria-label="Implied move" className="space-y-2">
      <h3 className="flex items-center gap-2 text-slate-400">Implied move
        <span title="Calculated: the call's and the put's mid prices at the strike nearest the price, added" className="rounded bg-slate-800 px-1 text-[9px] uppercase tracking-wider text-slate-400">calculated</span></h3>
      {data.state === "unavailable" ? <p className="text-amber-300">{data.message}</p>
        : !data.moves.length ? <p className="text-slate-500">No {data.symbol} option expirations are listed.</p>
        : <ul className="divide-y divide-slate-800">{data.moves.map((move) => <li key={move.expiration} className="py-2" aria-label={`${names(move, data)} ${move.expiration}`}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 text-slate-300">{names(move, data)} <span className="text-slate-500">· {eventDay(move.expiration).replace(/, \d{4}$/, "")} · {move.days} d</span></span>
            {move.state === "ready" && move.move !== undefined && move.percent !== undefined
              ? <span className="shrink-0 font-mono text-slate-100">±${move.move.toFixed(2)} <span className="text-slate-400">±{(move.percent * 100).toFixed(1)}%</span></span>
              : <span className="shrink-0 text-amber-300">{move.state === "too_wide" ? "Market too wide" : "No number"}</span>}
          </div>
          <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{move.state === "ready"
            ? [`${move.strike} straddle: call ${quote(move.call?.bid, move.call?.ask)}, put ${quote(move.put?.bid, move.put?.ask)}`,
              move.iv != null ? `IV ${(move.iv * 100).toFixed(1)}%` : null, move.quoted_at ? `quoted ${clock(move.quoted_at)} ET` : null].filter(Boolean).join(" · ")
            : move.reason}</p>
        </li>)}</ul>}
      {data.earnings_note && <p className="text-[10px] text-slate-500">{data.earnings_note}</p>}
      {data.message && data.state !== "unavailable" && <p className="text-[10px] text-amber-300">{data.message}</p>}
      <p className="text-[10px] leading-4 text-slate-500">What the options market prices for a move either way by expiry, at {data.spot?.toFixed(2) ?? "—"}: not a direction or a forecast of one. {data.source}.</p>
    </section>
    <Analysts key={data.symbol} symbol={data.symbol} spot={data.spot} />
  </div>;
}
