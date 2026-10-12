"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type Kind = "quote" | "order_book" | "ticker";
export type Phase = "connecting" | "authenticated" | "subscribed" | "refreshed" | "failed" | "closed";
export type Level = { price: number; volume: number; order_count: number | null; mpid: string | null };
export type LiveBook = {
  exchange: "ARCA" | "NASDAQ" | "UNKNOWN" | "";
  source_time_ms: number | null;
  estimated_age_ms: number | null;
  order_volume_precision: number | null;
  bids: Level[];
  asks: Level[];
};
export type BookEvent = { event: "book"; symbol: "US.NVDA"; received_ms: number; books: LiveBook[] };
export type StatusEvent = { event: "status"; phase: Phase; kind?: Kind; code?: number | null };
type ProtocolStatus = "success" | "failed" | "unconfirmed" | "not_attempted" | "sent_unconfirmed" | "not_needed" | "unconfirmed; connection will close";
export type ProtocolResult = { status: ProtocolStatus; code?: number | null };
export type Summary = {
  authentication?: ProtocolResult;
  status?: "completed" | "failed_or_timed_out";
  subscriptions?: Partial<Record<Kind, ProtocolResult>>;
  message_counts?: Partial<Record<"QUOTE" | "ORDER_BOOK" | "TICKER", number>>;
  refreshes?: { sent: number; confirmed: number };
  refresh_failed?: boolean;
  unsubscribe?: ProtocolResult;
  closed?: boolean;
};

export const KINDS: Kind[] = ["quote", "order_book", "ticker"];
const REPORT_KINDS = ["QUOTE", "ORDER_BOOK", "TICKER"] as const;
const REPORT_STATUSES: ProtocolStatus[] = ["success", "failed", "unconfirmed", "not_attempted", "sent_unconfirmed", "not_needed", "unconfirmed; connection will close"];
const MAX_LINE_BYTES = 256 * 1024;
/** The bridge ends a session by itself after eight hours; this is only a backstop above that. */
const SESSION_TIMEOUT_MS = 8 * 3600_000 + 60_000;
const numberOrNull = (value: unknown): value is number | null => value === null || (typeof value === "number" && Number.isFinite(value));
export const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const safeTimestamp = (value: unknown): value is number | null => value === null || (typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 8_640_000_000_000_000);
const safeCount = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

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
    && ["connecting", "authenticated", "subscribed", "refreshed", "failed", "closed"].includes(String(value.phase))
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
      if (count !== undefined && !safeCount(count)) return false;
    }
  }
  if (report.refreshes !== undefined && !(isRecord(report.refreshes) && safeCount(report.refreshes.sent) && safeCount(report.refreshes.confirmed))) return false;
  if (report.refresh_failed !== undefined && typeof report.refresh_failed !== "boolean") return false;
  return (report.unsubscribe === undefined || validProtocolResult(report.unsubscribe))
    && (report.closed === undefined || typeof report.closed === "boolean");
}

export type DepthSession = {
  availability: "checking" | "ready" | "unavailable";
  enabled: boolean | null;
  running: boolean;
  started: boolean;
  message: string;
  statuses: Partial<Record<Kind, StatusEvent>>;
  sessionPhase: Phase | null;
  summary: Summary | null;
  bookEvent: BookEvent | null;
  protocolError: boolean;
  /** Local time of the last confirmed in-session auth refresh. */
  refreshedAt: number | null;
  connect(): void;
  stop(): void;
};

/**
 * One manual NVDA depth session: nothing is requested until `active` (the
 * status check) and nothing reaches the provider until `connect()`. It runs
 * until `stop()`, unmount, the bridge's own ceiling or a failure; there is no
 * automatic reconnect. `stopWhenHidden` keeps the lab's hide-to-cancel rule;
 * the Charts heatmap keeps collecting while the page is in the background.
 * `onBook` sees each validated book, for memory-only views such as the heatmap.
 */
export function useDepthSession({ active = true, stopWhenHidden = false, onBook }: { active?: boolean; stopWhenHidden?: boolean; onBook?: (event: BookEvent) => void } = {}): DepthSession {
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
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const onBookRef = useRef(onBook);
  useEffect(() => { onBookRef.current = onBook; }, [onBook]);

  useEffect(() => {
    if (!active) return;
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
  }, [active]);

  const stop = useCallback(() => {
    const current = abortRef.current;
    if (!current) return;
    current.abort();
    abortRef.current = null;
    setRunning(false);
    setSessionPhase("closed");
    setMessage("Session stopped. Connect starts a new one.");
  }, []);

  useEffect(() => {
    const onVisibility = () => { if (stopWhenHidden && document.hidden && abortRef.current) stop(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [stop, stopWhenHidden]);
  useEffect(() => () => { abortRef.current?.abort(); abortRef.current = null; }, []);

  const connect = useCallback(async () => {
    if (availability !== "ready" || !enabled || abortRef.current) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), SESSION_TIMEOUT_MS);
    setStarted(true); setRunning(true); setMessage("Connecting to the provider…"); setStatuses({}); setSessionPhase(null); setSummary(null); setBookEvent(null); setProtocolError(false); setRefreshedAt(null);
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
          if (parsed.phase === "refreshed") { setRefreshedAt(Date.now()); return; }
          setSessionPhase(parsed.phase);
          if (parsed.phase === "closed") sawClosed = true;
          if (parsed.kind) setStatuses(current => ({ ...current, [parsed.kind!]: parsed }));
          if (parsed.phase === "failed") setMessage("Provider session failed. See the sanitized diagnostic status below.");
          if (parsed.phase === "closed") setMessage("Session closed.");
        } else if (validBook(parsed)) {
          setBookEvent(parsed);
          onBookRef.current?.(parsed);
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
      if (!controller.signal.aborted) setMessage(sawClosed ? "Session closed. Connect starts a new one." : "Session ended. Connect starts a new one.");
    } catch {
      if (abortRef.current === controller) setMessage(controller.signal.aborted ? "Session timed out. Connect starts a new one." : "The local service connection ended. Connect starts a new one.");
    } finally {
      window.clearTimeout(timeout);
      if (abortRef.current === controller) { abortRef.current = null; setRunning(false); }
    }
  }, [availability, enabled]);

  return { availability, enabled, running, started, message, statuses, sessionPhase, summary, bookEvent, protocolError, refreshedAt, connect, stop };
}
