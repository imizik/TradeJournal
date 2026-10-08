import { eventDay, readAt } from "@/lib/symbolInfo";
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
  const reactions = data.reactions;
  const earningsMove = data.moves.find((move) => move.tags.includes("earnings"));
  const comparisonReady = reactions?.average_abs_pct != null && earningsMove?.state === "ready" && earningsMove.percent != null
    && earningsMove.fetched_at != null && Date.now() / 1000 - earningsMove.fetched_at <= 60;
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
    {reactions && <section aria-label="Past earnings reactions" className="space-y-2 border-t border-slate-800 pt-3">
      <h3 className="text-slate-300">Past earnings reactions <span className="ml-1 rounded bg-slate-800 px-1 text-[9px] uppercase tracking-wider text-slate-400">inferred</span></h3>
      <p className="text-[10px] leading-4 text-slate-500">Report timing is unknown. For each report, the larger absolute full-day move across the report session and next session is shown. This is descriptive, not a forecast. {reactions.source} ({readAt(reactions.fetched_at)}); split-adjusted, dividends not adjusted.{reactions.stale ? " Split data is stale." : ""}{reactions.earnings_stale ? " Earnings dates use an older cached calendar because refresh failed." : ""}</p>
      {reactions.state === "loading" || reactions.state === "unavailable" ? <p role="status" className="text-amber-300">{reactions.message ?? "Earnings reactions unavailable."}</p>
        : reactions.state === "none" ? <p className="text-slate-500">{reactions.message ?? "No past earnings history."}</p>
        : <>
          <ul className="divide-y divide-slate-800">{reactions.rows.map((row) => <li key={row.report_date} className="py-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-slate-300">{row.label ?? eventDay(row.report_date)} · report {eventDay(row.report_date).replace(/, \d{4}$/, "")}</span>
              {row.state === "ready" && row.reaction_date && row.gap_pct != null && row.reaction_pct != null
                ? <span className="shrink-0 font-mono text-slate-100">{row.reaction_pct > 0 ? "+" : ""}{row.reaction_pct.toFixed(1)}%</span>
                : <span className="shrink-0 text-amber-300">No number</span>}
            </div>
            <p className="mt-0.5 text-[10px] text-slate-500">{row.state === "ready" && row.reaction_date && row.gap_pct != null
              ? `${eventDay(row.reaction_date)} gap ${row.gap_pct > 0 ? "+" : ""}${row.gap_pct.toFixed(1)}% · inferred full-day reaction`
              : row.reason}</p>
            <details className="mt-1 text-[10px] text-slate-500"><summary className="min-h-6 cursor-pointer py-1">Show both candidate sessions</summary>
              <ul>{row.sessions.map((session) => <li key={session.date}>{eventDay(session.date)}: {session.state === "ready" && session.day_pct != null && session.gap_pct != null
                ? `gap ${session.gap_pct > 0 ? "+" : ""}${session.gap_pct.toFixed(1)}%, full-day ${session.day_pct > 0 ? "+" : ""}${session.day_pct.toFixed(1)}%`
                : session.reason}</li>)}</ul>
            </details>
          </li>)}</ul>
          {reactions.average_abs_pct != null
            ? <p className="text-slate-300">{comparisonReady && earningsMove ? `Priced ±${(earningsMove.percent! * 100).toFixed(1)}% through ${eventDay(earningsMove.expiration).replace(/, \d{4}$/, "")}; past inferred average ±${reactions.average_abs_pct.toFixed(1)}% (${reactions.usable_count} reports).` : `Past inferred average ±${reactions.average_abs_pct.toFixed(1)}% (${reactions.usable_count} reports).`}{reactions.report_range ? ` Reports ${eventDay(reactions.report_range.from).replace(/, \d{4}$/, "")}–${eventDay(reactions.report_range.to).replace(/, \d{4}$/, "")}.` : ""}</p>
            : <p className="text-slate-500">At least four usable reports are required for an average; {reactions.usable_count} available.</p>}
          {reactions.average_abs_pct != null && !comparisonReady && <p className="text-[10px] text-slate-500">Earnings implied move is unavailable or stale, so the comparison is omitted.</p>}
          {reactions.message && <p className="text-[10px] text-amber-300">{reactions.message}</p>}
        </>}
    </section>}
  </div>;
}
