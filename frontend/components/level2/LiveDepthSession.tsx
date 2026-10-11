"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Kind = "quote" | "order_book" | "ticker";
type Phase = "connecting" | "authenticated" | "subscribed" | "failed" | "closed";
type Level = { price: number; volume: number; order_count: number | null; mpid: string | null };
type LiveBook = {
  exchange: "ARCA" | "NASDAQ" | "UNKNOWN" | "";
  source_time_ms: number | null;
  estimated_age_ms: number | null;
  order_volume_precision: number | null;
  bids: Level[];
  asks: Level[];
};
type BookEvent = { event: "book"; symbol: "US.NVDA"; received_ms: number; books: LiveBook[] };
type StatusEvent = { event: "status"; phase: Phase; kind?: Kind; code?: number | null };
type ProtocolStatus = "success" | "failed" | "unconfirmed" | "not_attempted" | "sent_unconfirmed" | "not_needed" | "unconfirmed; connection will close";
type ProtocolResult = { status: ProtocolStatus; code?: number | null };
type Summary = {
  authentication?: ProtocolResult;
  status?: "completed" | "failed_or_timed_out";
  subscriptions?: Partial<Record<Kind, ProtocolResult>>;
  message_counts?: Partial<Record<"QUOTE" | "ORDER_BOOK" | "TICKER", number>>;
  unsubscribe?: ProtocolResult;
  closed?: boolean;
};

const KINDS: Kind[] = ["quote", "order_book", "ticker"];
const REPORT_KINDS = ["QUOTE", "ORDER_BOOK", "TICKER"] as const;
const REPORT_STATUSES: ProtocolStatus[] = ["success", "failed", "unconfirmed", "not_attempted", "sent_unconfirmed", "not_needed", "unconfirmed; connection will close"];
const MAX_LINE_BYTES = 256 * 1024;
const SESSION_TIMEOUT_MS = 40_000;
const numberOrNull = (value: unknown): value is number | null => value === null || (typeof value === "number" && Number.isFinite(value));
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const safeTimestamp = (value: unknown): value is number | null => value === null || (typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 8_640_000_000_000_000);

function validProtocolResult(value: unknown): value is ProtocolResult {
  return isRecord(value) && REPORT_STATUSES.includes(value.status as ProtocolStatus)
    && (value.code === undefined || (value.code === null || (typeof value.code === "number" && Number.isSafeInteger(value.code))));
}

function validLevel(value: unknown): value is Level {
  if (!isRecord(value)) return false;
  return typeof value.price === "number" && Number.isFinite(value.price) && value.price > 0
    && typeof value.volume === "number" && Number.isFinite(value.volume) && value.volume >= 0
    && (value.order_count === null || (typeof value.order_count === "number" && Number.isSafeInteger(value.order_count) && value.order_count >= 0))
    && (value.mpid === null || (typeof value.mpid === "string" && /^[A-Z0-9]{1,8}$/.test(value.mpid)));
}

function validBook(value: unknown): value is BookEvent {
  if (!isRecord(value) || value.event !== "book" || value.symbol !== "US.NVDA"
    || !safeTimestamp(value.received_ms) || value.received_ms === null || value.received_ms === 0
    || !Array.isArray(value.books) || value.books.length > 10) return false;
  return value.books.every(book => isRecord(book)
    && (book.exchange === "ARCA" || book.exchange === "NASDAQ" || book.exchange === "UNKNOWN" || book.exchange === "")
    && safeTimestamp(book.source_time_ms)
    && (book.estimated_age_ms === null || (typeof book.estimated_age_ms === "number" && Number.isFinite(book.estimated_age_ms) && Math.abs(book.estimated_age_ms) <= 8_640_000_000_000_000))
    && (book.order_volume_precision === null || (typeof book.order_volume_precision === "number" && Number.isInteger(book.order_volume_precision) && book.order_volume_precision >= 0 && book.order_volume_precision <= 9))
    && Array.isArray(book.bids) && book.bids.length <= 60 && book.bids.every(validLevel)
    && Array.isArray(book.asks) && book.asks.length <= 60 && book.asks.every(validLevel));
}

function validStatus(value: unknown): value is StatusEvent {
  return isRecord(value) && value.event === "status"
    && ["connecting", "authenticated", "subscribed", "failed", "closed"].includes(String(value.phase))
    && (value.kind === undefined || KINDS.includes(value.kind as Kind))
    && (value.code === undefined || numberOrNull(value.code));
}

function validSummary(value: unknown): value is { event: "summary"; report: Summary } {
  if (!isRecord(value) || value.event !== "summary" || !isRecord(value.report)) return false;
  const report = value.report;
  if (report.authentication !== undefined && !validProtocolResult(report.authentication)) return false;
  if (report.status !== undefined && report.status !== "completed" && report.status !== "failed_or_timed_out") return false;
  if (report.subscriptions !== undefined) {
    if (!isRecord(report.subscriptions)) return false;
    for (const kind of KINDS) {
      const subscription = report.subscriptions[kind];
      if (subscription !== undefined && !validProtocolResult(subscription)) return false;
    }
  }
  if (report.message_counts !== undefined) {
    if (!isRecord(report.message_counts)) return false;
    for (const kind of REPORT_KINDS) {
      const count = report.message_counts[kind];
      if (count !== undefined && (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0)) return false;
    }
  }
  return (report.unsubscribe === undefined || validProtocolResult(report.unsubscribe))
    && (report.closed === undefined || typeof report.closed === "boolean");
}

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

/** `compact` adapts the same session to the Charts dock: stacked books, one column, no page heading. Parsing and cancellation are unchanged. */
export default function LiveDepthSession({ compact = false }: { compact?: boolean }) {
  const again = compact ? "Close and reopen this panel to start again." : "Reload to start again.";
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [availability, setAvailability] = useState<"checking" | "ready" | "unavailable">("checking");
  const [running, setRunning] = useState(false);
  const [started, setStarted] = useState(false);
  const [message, setMessage] = useState("No live session started.");
  const [statuses, setStatuses] = useState<Partial<Record<Kind, StatusEvent>>>({});
  const [sessionPhase, setSessionPhase] = useState<Phase | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [bookEvent, setBookEvent] = useState<BookEvent | null>(null);
  const [protocolError, setProtocolError] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/level2-lab/session", { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error("unavailable");
        return response.json();
      })
      .then((payload: unknown) => {
        if (!isRecord(payload) || typeof payload.enabled !== "boolean") throw new Error("unavailable");
        setEnabled(payload.enabled);
        setAvailability("ready");
      })
      .catch(() => { if (!controller.signal.aborted) setAvailability("unavailable"); });
    return () => controller.abort();
  }, []);

  const stop = useCallback(() => {
    const active = abortRef.current;
    if (!active) return;
    active.abort();
    abortRef.current = null;
    setStarted(true);
    setRunning(false);
    setSessionPhase("closed");
    setMessage(`Session stopped. Any retained book is for inspection only. ${again}`);
  }, [again]);

  useEffect(() => {
    const onVisibility = () => { if (document.hidden && abortRef.current) stop(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [stop]);

  const connect = async () => {
    if (availability !== "ready" || !enabled || running || started) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), SESSION_TIMEOUT_MS);
    setStarted(true); setRunning(true); setMessage("Connecting to the provider…"); setStatuses({}); setSessionPhase(null); setSummary(null); setBookEvent(null); setProtocolError(false);
    let sawClosed = false;
    try {
      const response = await fetch("/api/level2-lab/session", {
        method: "POST",
        headers: { "Content-Type": "application/x-level2-start" },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) { setMessage("The local service could not start this session."); return; }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const consumeLine = (line: string) => {
        if (!line.trim()) return;
        if (new TextEncoder().encode(line).byteLength > MAX_LINE_BYTES) { setProtocolError(true); return; }
        let parsed: unknown;
        try { parsed = JSON.parse(line); } catch { setProtocolError(true); return; }
        if (validStatus(parsed)) {
          setSessionPhase(parsed.phase);
          if (parsed.phase === "closed") sawClosed = true;
          if (parsed.kind) setStatuses(current => ({ ...current, [parsed.kind!]: parsed }));
          if (parsed.phase === "failed") setMessage("Provider session failed. See the sanitized diagnostic status below.");
          if (parsed.phase === "closed") setMessage("Session closed. Any retained book is for inspection only.");
        } else if (validBook(parsed)) {
          setBookEvent(parsed);
          setMessage("Receiving provider book updates. This display is for inspection only.");
        } else if (validSummary(parsed)) {
          setSummary(parsed.report);
          if (parsed.report.closed) sawClosed = true;
        }
        // Unknown and malformed protocol records are ignored without exposing provider text.
      };
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        if (new TextEncoder().encode(buffer).byteLength > MAX_LINE_BYTES && !buffer.includes("\n")) {
          setProtocolError(true); buffer = ""; continue;
        }
        let newline = buffer.indexOf("\n");
        while (newline >= 0) { consumeLine(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1); newline = buffer.indexOf("\n"); }
      }
      buffer += decoder.decode();
      if (buffer) consumeLine(buffer);
      if (!controller.signal.aborted) setMessage(sawClosed ? `Session closed. Any retained book is for inspection only. ${again}` : `Session ended. Any retained book is for inspection only. ${again}`);
    } catch {
      if (abortRef.current === controller) setMessage(controller.signal.aborted ? `Session timed out. Any retained book is for inspection only. ${again}` : `The local service connection ended. ${again}`);
    } finally {
      window.clearTimeout(timeout);
      if (abortRef.current === controller) { abortRef.current = null; setRunning(false); }
    }
  };

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
      <span className="rounded border border-sky-400/40 bg-sky-400/10 px-2 py-1 text-xs font-semibold text-sky-200">MANUAL · 30 SECONDS</span>
    </div>
    {compact
      ? <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">About this session (US.NVDA, 30 seconds, manual)</summary>
        <div className="space-y-1 pt-1">
    <p className="text-sm text-muted-foreground">US.NVDA · isolated local service session. Latest order-book update only; no recording, history, saved metrics, or automatic reconnect.</p>
    <p className="text-xs text-muted-foreground">Provider volume units are unverified. Exchange and source timestamps are shown as reported. A received update does not establish consolidated depth or entitlement coverage.</p>
        </div></details>
      : <>
    <p className="text-sm text-muted-foreground">US.NVDA · isolated local service session. Latest order-book update only; no recording, history, saved metrics, or automatic reconnect.</p>
    <p className="text-xs text-muted-foreground">Provider volume units are unverified. Exchange and source timestamps are shown as reported. A received update does not establish consolidated depth or entitlement coverage.</p>
      </>}
    {availability === "unavailable" && <p role="status" className="rounded border border-amber-400/40 p-2 text-sm text-amber-200">Local service is not enabled or unavailable. No provider connection was started.</p>}
    {availability === "ready" && !enabled && <p role="status" className="rounded border border-muted p-2 text-sm text-muted-foreground">Local live service is disabled. No provider connection was started.</p>}
    <div className="flex flex-wrap items-center gap-2">
      <Button size={compact ? "sm" : undefined} onClick={connect} disabled={availability !== "ready" || !enabled || running || started}>{running ? "Session running…" : started ? (compact ? "Reopen to start again" : "Reload to start again") : "Connect for 30 seconds"}</Button>
      <Button size={compact ? "sm" : undefined} variant="outline" onClick={stop} disabled={!running}>Stop</Button>
      <span role="status" aria-live="polite" className="text-sm text-muted-foreground">{message}</span>
    </div>
    {sessionPhase && <p className="text-xs text-muted-foreground">Provider phase: {sessionPhase}</p>}
    {protocolError && <p role="status" className="text-xs text-amber-200">An invalid or oversized protocol line was ignored.</p>}
    {compact && bookBlock}
    {diagBlocks}
    {!compact && bookBlock}
  </section>;
}
