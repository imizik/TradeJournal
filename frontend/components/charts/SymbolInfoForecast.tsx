import { eventDay } from "@/lib/symbolInfo";
import type { ImpliedMove, SymbolForecast } from "@/lib/symbolInfo";

const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const quote = (bid: number | null | undefined, ask: number | null | undefined) => `${bid?.toFixed(2) ?? "—"} × ${ask?.toFixed(2) ?? "—"}`;

/** Which rows one expiration answers: "0DTE · Friday", "After earnings (est.)". */
function names(move: ImpliedMove, data: SymbolForecast): string {
  return move.tags.map((tag) => tag === "nearest" ? (move.days === 0 ? "0DTE" : "Nearest")
    : tag === "friday" ? "This Friday"
    : `After earnings ${data.earnings ? eventDay(data.earnings.date).replace(/, \d{4}$/, "") : ""}${data.earnings?.status === "estimated" ? " (est.)" : ""}`).join(" · ");
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
  </div>;
}
