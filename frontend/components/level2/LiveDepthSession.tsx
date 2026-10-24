"use client";

import { Button } from "@/components/ui/button";
import { KINDS, useDepthSession } from "./useDepthSession";
import type { DepthSession, LiveBook } from "./useDepthSession";
import { timeET } from "@/lib/format";

function displayTime(value: number | null): string {
  if (value === null || value === 0) return "Unavailable";
  return new Date(value).toISOString();
}

function BookTable({ book, side }: { book: LiveBook; side: "bids" | "asks" }) {
  const levels = book[side];
  return <table className="w-full table-fixed text-right text-xs tabular-nums" aria-label={`${side === "bids" ? "Bid" : "Ask"} levels`}>
    <thead className="text-muted-foreground"><tr><th className="py-1 text-left font-normal">Price</th><th className="font-normal">Provider volume*</th><th className="font-normal">Orders</th></tr></thead>
    <tbody>{levels.length ? levels.map((level, index) => <tr className="border-t border-border/50" key={`${side}-${index}`}>
      <td className="py-1 text-left font-medium break-all">{String(level.price)}</td>
          <td className="px-1 break-all">{String(level.volume)}</td><td className="break-words">{level.order_count ?? "Unavailable"}</td>
    </tr>) : <tr><td colSpan={3} className="py-2 text-left text-muted-foreground">No levels in this update</td></tr>}</tbody>
  </table>;
}

/**
 * `compact` adapts the same session to the Charts dock: stacked books, one
 * column, no page heading. Charts passes its own page-level `session` so the
 * heatmap keeps collecting while the dock is closed; the lab owns one here,
 * cancelled when its tab is hidden.
 */
export default function LiveDepthSession({ compact = false, session, symbol = "NVDA" }: { compact?: boolean; session?: DepthSession; symbol?: string }) {
  const own = useDepthSession({ active: !session, stopWhenHidden: true });
  const current = session ?? own;
  const { availability, enabled, running, statuses, sessionPhase, summary, bookEvent, protocolError, refreshedAt, connect, stop } = current;
  // A finished session for another ticker is not this symbol's result.
  const mine = current.symbol === null || current.symbol === symbol;
  const message = mine ? current.message : "No live session started.";

  // Compact (dock) mode puts the latest book first so the depth is visible without scrolling past diagnostics.
  const diagBlocks = <>
    <div className={compact ? "grid gap-2" : "grid gap-3 sm:grid-cols-3"} aria-label="Per-kind provider acknowledgements">
      {KINDS.map(kind => {
        const status = statuses[kind];
        const countKind = kind.toUpperCase() as "QUOTE" | "ORDER_BOOK" | "TICKER";
        const sub = summary?.subscriptions?.[kind];
        const count = summary?.message_counts?.[countKind];
        return <div key={kind} className="rounded border p-3 text-xs">
          <p className="font-medium">{kind.replace("_", " ")}</p>
          <p className="mt-1 text-muted-foreground">Phase: {status?.phase ?? "No acknowledgement"}{status?.code !== undefined ? ` · code ${status.code ?? "unavailable"}` : ""}</p>
          <p className="text-muted-foreground">Subscription: {sub?.status ?? "No report"}{sub?.code !== undefined ? ` · code ${sub.code ?? "unavailable"}` : ""}</p>
          <p className="text-muted-foreground">Messages: {count ?? "No messages reported"}</p>
        </div>;
      })}
    </div>
    {summary && <div className="rounded border p-3 text-xs text-muted-foreground" aria-label="Sanitized session summary">
      <p>Authentication: {summary.authentication?.status ?? "Unavailable"} · Session status: {summary.status ?? "Unavailable"}</p>
      <p>Unsubscribe: {summary.unsubscribe?.status ?? "Unavailable"} · Closed: {summary.closed === undefined ? "Unavailable" : summary.closed ? "Yes" : "No"}</p>
      {summary.refreshes && <p>Sign-in refreshes: {summary.refreshes.confirmed} of {summary.refreshes.sent} confirmed{summary.refresh_failed ? " · the session ended on an unconfirmed refresh" : ""}</p>}
      <p>No-message success does not confirm live delivery.</p>
    </div>}
  </>;
  const bookBlock = bookEvent && <div className="space-y-3 rounded border p-3" aria-label="Latest provider book">
      <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
        <span>Received: {displayTime(bookEvent.received_ms)} (local receive timestamp)</span>
        <span>Symbol: {bookEvent.symbol}</span>
      </div>
      {bookEvent.books.map((book, index) => {
        const missingTime = book.source_time_ms === null || book.source_time_ms === 0 || book.estimated_age_ms === null;
        const ageLabel = book.estimated_age_ms !== null && (book.estimated_age_ms < 0 || book.estimated_age_ms > 2000)
          ? `Stale or invalid at receipt: ${book.estimated_age_ms}ms` : `Estimated age at receipt: ${book.estimated_age_ms}ms`;
        const mpids = [...new Set([...book.bids, ...book.asks].map(level => level.mpid).filter((mpid): mpid is string => mpid !== null))].slice(0, 20);
        return <div key={`${book.exchange}-${index}`} className="space-y-2 border-t pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="font-medium">Exchange: {book.exchange === "UNKNOWN" || book.exchange === "" ? "Unavailable" : book.exchange}</span>
            <span role="status" className="text-amber-200">{missingTime ? "Freshness unavailable" : ageLabel}</span>
          </div>
          <p className="text-xs text-muted-foreground">{book.bids.length} bid entries · {book.asks.length} ask entries</p>
          <p className="text-xs text-muted-foreground">Source time: {displayTime(book.source_time_ms)} · received separately above · provider volume precision: {book.order_volume_precision ?? "unavailable"}</p>
          <div className={compact ? "grid min-w-0 gap-3" : "grid min-w-0 gap-4 md:grid-cols-2"}><BookTable book={book} side="bids" /><BookTable book={book} side="asks" /></div>
          <p className="text-xs text-muted-foreground">* Provider volume units are unverified. Exchange is shown only when supplied by the provider; MPIDs are separate provider labels.</p>
          {mpids.length > 0 && <p className="text-xs text-muted-foreground">Reported MPIDs (not exchange evidence): {mpids.join(", ")}</p>}
          <p className="text-xs text-amber-200">Latest update is for inspection only; no current freshness is claimed.</p>
        </div>;
      })}
    </div>;

  return <section aria-labelledby="live-depth-title" className={compact ? "min-w-0 space-y-2 border-b border-sky-400/20 p-3 text-slate-200" : "space-y-3 rounded-lg border border-sky-400/30 bg-card p-4"} data-testid="live-depth-session" data-compact={compact || undefined}>
    <div className="flex flex-wrap items-center gap-3">
      <h2 id="live-depth-title" className={compact ? "text-xs font-medium" : "text-lg font-semibold"}>Manual provider session</h2>
      <span className="rounded border border-sky-400/40 bg-sky-400/10 px-2 py-1 text-xs font-semibold text-sky-200">MANUAL · UNTIL STOPPED</span>
    </div>
    {compact
      ? <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">About this session (US.{symbol}, manual, until stopped)</summary>
        <div className="space-y-1 pt-1">
    <p className="text-sm text-muted-foreground">US.{symbol} · isolated local service session. It runs until Stop (eight hours at most), refreshing its sign-in every four minutes. Nothing is recorded or saved, and it never reconnects by itself.</p>
    <p className="text-xs text-muted-foreground">Provider volume units are unverified. Exchange and source timestamps are shown as reported. A received update does not establish consolidated depth or entitlement coverage.</p>
        </div></details>
      : <>
    <p className="text-sm text-muted-foreground">US.{symbol} · isolated local service session. It runs until Stop (eight hours at most), refreshing its sign-in every four minutes. Nothing is recorded or saved, and it never reconnects by itself.</p>
    <p className="text-xs text-muted-foreground">Provider volume units are unverified. Exchange and source timestamps are shown as reported. A received update does not establish consolidated depth or entitlement coverage.</p>
      </>}
    {availability === "unavailable" && <p role="status" className="rounded border border-amber-400/40 p-2 text-sm text-amber-200">Local service is not enabled or unavailable. No provider connection was started.</p>}
    {availability === "ready" && !enabled && <p role="status" className="rounded border border-muted p-2 text-sm text-muted-foreground">Local live service is disabled. No provider connection was started.</p>}
    <div className="flex flex-wrap items-center gap-2">
      <Button size={compact ? "sm" : undefined} onClick={() => connect(symbol)} disabled={availability !== "ready" || !enabled || running}>{running ? "Session running…" : "Connect"}</Button>
      <Button size={compact ? "sm" : undefined} variant="outline" onClick={stop} disabled={!running}>Stop</Button>
      <span role="status" aria-live="polite" className="text-sm text-muted-foreground">{message}</span>
    </div>
    {mine && <>
    {sessionPhase && <p className="text-xs text-muted-foreground">Provider phase: {sessionPhase}{refreshedAt ? ` · sign-in refreshed ${timeET(refreshedAt)}` : ""}</p>}
    {protocolError && <p role="status" className="text-xs text-amber-200">An invalid or oversized protocol line was ignored.</p>}
    {compact && bookBlock}
    {diagBlocks}
    {!compact && bookBlock}
    </>}
  </section>;
}
