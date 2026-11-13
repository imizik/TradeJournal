"use client";

/**
 * The desk's Tape (docs/copilot-lab.md § The desk): the selected stock or ETF's Level 2 and time & sales from the same
 * manual moomoo session Charts uses (``useDepthSession``; docs/level2-manual-connection.md). Closed by default and
 * remembered on this device; the stream starts only while the panel is open and the page shows, and stops when it
 * closes, the symbol changes or the tab hides. One symbol streams at a time across the app: when another session holds
 * the bridge (Charts, perhaps in another tab) the panel says so and leaves it alone. Owner only; nothing is saved.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { LEVEL2_TICKER, useDepthSession, type BookEvent, type Level, type Trade, type TradesEvent } from "@/components/level2/useDepthSession";
import { heatBookKind } from "@/lib/depthHeatmap";
import { cn } from "@/lib/utils";

const OPEN_KEY = "desk.tape.v1";
/** Prints kept in memory for the tape; the desktop shows this many, a phone the last ``PHONE_PRINTS``. */
const KEPT = 200;
const SHOWN = 30;
const PHONE_PRINTS = 8;
const LEVELS = 5;
/** A print is compared with the ARCA book only when that book arrived within this long of it. */
const BOOK_MATCH_MS = 1_000;
const TOPS_KEPT = 8;
/** A print this many times the session's median print size, with enough prints to judge, is a big print. */
const BIG_TIMES = 10;
const BIG_MIN_PRINTS = 20;
/** After the desk's own stop the bridge holds the old session until its unsubscribe ends (a few seconds). */
const CLOSING_MS = 12_000;
const RETRY_MS = 2_000;
/** Index symbols the provider has no equity depth for. */
const INDEXES = new Set(["SPX", "SPXW", "NDX", "RUT", "VIX", "DJX", "XSP", "XND", "OEX", "US10Y"]);

/** When the desk itself last ended a tape session (unmount included), so a quick reopen waits for the bridge. */
let lastStop = 0;

/** Whether the tape is open, remembered on this device (closed until the owner opens it). */
export function useTapeOpen(): [boolean, (next: boolean) => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => { try { setOpen(window.localStorage.getItem(OPEN_KEY) === "open"); } catch { /* closed */ } }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const pick = useCallback((next: boolean) => {
    setOpen(next);
    try { window.localStorage.setItem(OPEN_KEY, next ? "open" : "closed"); } catch { /* this view only */ }
  }, []);
  return [open, pick];
}

/** The chart header's Tape button; nothing for an assistant (the depth route is the owner's). */
export function TapeToggle({ open, onToggle }: { open: boolean; onToggle(next: boolean): void }) {
  const { owner } = useAppAccess();
  if (!owner) return null;
  return (
    <button type="button" aria-pressed={open} onClick={() => onToggle(!open)} data-testid="tape-toggle" title="Level 2 and time & sales"
      className={cn("min-h-11 rounded border px-2 text-xs sm:min-h-0 sm:py-0.5",
        open ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
      Tape
    </button>
  );
}

const px = (value: number) => value >= 1 ? value.toFixed(2) : value.toFixed(4);
const size = (value: number) => Math.round(value).toLocaleString("en-US");
const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour12: false });

/** "Spread 2¢ (0.01%)", or what is wrong with the book's top. */
export function spreadWords(bid: number | undefined, ask: number | undefined): string {
  if (bid === undefined || ask === undefined) return "No bid and ask in this update";
  const gap = ask - bid;
  if (gap < 0) return "Bid above ask in this book (crossed)";
  if (gap === 0) return "Bid equals ask in this book (locked)";
  const cents = Math.round(gap * 100);
  const words = gap >= 1 ? `$${gap.toFixed(2)}` : cents >= 1 ? `${cents}¢` : `${(gap * 100).toFixed(2)}¢`;
  return `Spread ${words} (${(gap / ((bid + ask) / 2) * 100).toFixed(2)}%)`;
}

type Side = "ask" | "bid" | null;
type Print = Trade & { side: Side; key: string };
type Top = { bids: Level[]; asks: Level[]; at: number };

/** The newest of ``tops`` (oldest first) that the bridge received at or before the print, within a second of it. */
export function bookAt(trade: Trade, tops: Top[]): Top | null {
  for (let i = tops.length - 1; i >= 0; i--) {
    if (tops[i].at <= trade.received_ms) return trade.received_ms - tops[i].at <= BOOK_MATCH_MS ? tops[i] : null;
  }
  return null;
}

/** At the ask or bid only when the ARCA book standing when the print arrived says so (never a later book); else nothing. */
export function sideOf(trade: Trade, top: Top | null): Side {
  if (!top) return null;
  const bid = top.bids[0]?.price, ask = top.asks[0]?.price;
  if (bid === undefined || ask === undefined || bid >= ask) return null;
  if (trade.price >= ask) return "ask";
  if (trade.price <= bid) return "bid";
  return null;
}

/** The print size at or above which a print is big, or null until there are enough prints to judge. */
export function bigFrom(prints: { volume: number }[]): number | null {
  if (prints.length < BIG_MIN_PRINTS) return null;
  const sizes = prints.map(p => p.volume).sort((a, b) => a - b);
  return sizes[Math.floor(sizes.length / 2)] * BIG_TIMES;
}

/** Which symbols the tape covers, and what to say for the rest. */
export function tapeCovers(symbol: string): string | null {
  if (!LEVEL2_TICKER.test(symbol)) return `The tape covers US stocks and ETFs; option contracts and ${symbol} are not supported.`;
  if (INDEXES.has(symbol)) return `${symbol} is an index: the tape covers US stocks and ETFs only.`;
  return null;
}

export function DeskTape({ symbol, option = false }: { symbol: string; option?: boolean }) {
  const { owner } = useAppAccess();
  const unsupported = tapeCovers(symbol);
  if (!owner) return null; // the depth route is the owner's: an assistant's remembered "open" starts nothing
  return (
    <section aria-label="Tape" data-testid="desk-tape" className="rounded-md border bg-card/60 px-3 py-2 text-xs">
      {unsupported ? <p role="status" className="text-muted-foreground">{unsupported} Nothing was started.</p>
        : <TapeStream key={symbol} symbol={symbol} />}
      {option && !unsupported && <p className="mt-1 text-[11px] text-muted-foreground">This is {symbol}&apos;s stock tape: option contracts have none here.</p>}
    </section>
  );
}

function TapeStream({ symbol }: { symbol: string }) {
  // The last few ARCA books (oldest first): a flush sends its books before its prints, so a print is matched with the
  // book standing when it arrived, not a newer one.
  const tops = useRef<Top[]>([]);
  const [book, setBook] = useState<Top | null>(null);
  const [prints, setPrints] = useState<Print[]>([]);
  const [dropped, setDropped] = useState(0);
  const onBook = useCallback((event: BookEvent) => {
    // The ARCA-labelled book only (one row per price); the other market-maker book is never merged into it.
    const arca = event.books.find(b => heatBookKind(b) === "arca");
    if (!arca || (!arca.bids.length && !arca.asks.length)) return;
    const next = { bids: arca.bids, asks: arca.asks, at: event.received_ms };
    tops.current = [...tops.current, next].slice(-TOPS_KEPT);
    setBook(next);
  }, []);
  const onTrades = useCallback((event: TradesEvent) => {
    const fresh = event.trades.map((t, i) => ({ ...t, side: sideOf(t, bookAt(t, tops.current)), key: `${t.received_ms}-${t.sequence ?? ""}-${i}` }));
    setPrints(current => [...fresh.reverse(), ...current].slice(0, KEPT));
    if (event.dropped) setDropped(n => n + event.dropped);
  }, []);
  const session = useDepthSession({ stopWhenHidden: true, onBook, onTrades });
  const { availability, enabled, running, refused, connect } = session;
  // Only a session this panel had running counts as its own stop (hiding or closing it while refused stops nothing).
  const ownRunning = useRef(false);
  useEffect(() => { ownRunning.current = running; }, [running]);
  const lastRefused = useRef<number | null>(null);
  useEffect(() => { lastRefused.current = refused; }, [refused]);

  // The page's visibility: hiding stops the stream (the hook), showing again starts it.
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const seen = () => { if (document.hidden && ownRunning.current) lastStop = Date.now(); setVisible(!document.hidden); };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => document.removeEventListener("visibilitychange", seen);
  }, []);
  useEffect(() => () => { if (ownRunning.current) lastStop = Date.now(); }, []); // closing the panel or changing symbol ends this session

  // Start once per showing; a refusal right after the desk's own stop is the old session still closing: try again
  // a few times. Any other refusal waits for Try again.
  const [attempt, setAttempt] = useState(0);
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!visible || availability !== "ready" || !enabled || running) return;
    const key = `${attempt}`;
    if (startedFor.current === key) return;
    startedFor.current = key;
    connect(symbol);
  }, [visible, availability, enabled, running, attempt, connect, symbol]);
  // The next showing starts again, unless another session held the bridge: that waits for Try again.
  useEffect(() => { if (!visible && lastRefused.current !== 409) startedFor.current = null; }, [visible]);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    const wait = refused === 409 && !running && Date.now() - lastStop < CLOSING_MS;
    setClosing(wait); // eslint-disable-line react-hooks/set-state-in-effect -- decided when the refusal arrives
    if (!wait) return;
    const timer = window.setTimeout(() => setAttempt(n => n + 1), RETRY_MS);
    return () => window.clearTimeout(timer);
  }, [running, refused, attempt]);

  const big = useMemo(() => bigFrom(prints), [prints]);
  const bid = book?.bids[0], ask = book?.asks[0];
  const status = availability === "checking" ? "Checking the depth service…"
    : availability === "unavailable" || !enabled ? "The depth service is off, so there is no tape. Nothing was started."
      : running ? (prints.length || book ? `Live · ${symbol}` : `Connecting ${symbol}…`)
        : closing ? "Waiting for the last session to close…"
          : refused === 409 ? "Another Level 2 stream is running (Charts, perhaps in another tab). One symbol streams at a time: stop it there, then try again."
            : refused ? "The depth service could not start this tape."
              : !visible ? "Paused while the page is hidden." : "The tape ended.";
  const retry = !running && !closing && availability === "ready" && enabled && (refused !== null || session.started);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span role="status" data-testid="tape-status" className="text-muted-foreground">{status}</span>
        {retry && <button type="button" onClick={() => setAttempt(n => n + 1)} className="min-h-11 text-foreground underline sm:min-h-0">Try again</button>}
      </div>
      {book && (
        <p data-testid="tape-spread" className="tabular-nums text-foreground">
          {bid && <>Bid <b className="font-medium text-rose-300">{px(bid.price)}</b> × {size(bid.volume)}</>}
          {bid && ask && " · "}
          {ask && <>Ask <b className="font-medium text-emerald-300">{px(ask.price)}</b> × {size(ask.volume)}</>}
          <span className="text-muted-foreground"> · {spreadWords(bid?.price, ask?.price)}</span>
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {book && <Levels book={book} />}
        <Prints prints={prints} big={big} />
      </div>
      {dropped > 0 && <p className="text-[11px] text-muted-foreground">{dropped.toLocaleString("en-US")} prints in fast bursts were too many to show.</p>}
      <p className="text-[10px] leading-4 text-muted-foreground max-sm:hidden">
        Level 2 is the ARCA-labelled book from moomoo (sizes as the provider reports them), not the whole market. Green
        or red: the print was at or through the ask or bid of the last book received before it (within a second; the
        bridge sends the newest book every quarter second); plain when it fell between them or there was no such book. Bold: at least {BIG_TIMES}× the median print so far. Nothing is saved.
      </p>
    </div>
  );
}

/** The ARCA book's first levels, bids beside asks; hidden on a phone, where only the tape shows. */
function Levels({ book }: { book: Top }) {
  const rows = Array.from({ length: LEVELS }, (_, i) => [book.bids[i], book.asks[i]] as const);
  return (
    <table data-testid="tape-levels" aria-label="Level 2" className="w-full table-fixed self-start text-right tabular-nums max-sm:hidden">
      <thead className="text-[11px] text-muted-foreground"><tr>
        <th className="font-normal">Size</th><th className="font-normal">Bid</th><th className="font-normal">Ask</th><th className="font-normal">Size</th>
      </tr></thead>
      <tbody>{rows.map(([b, a], i) => (
        <tr key={i} className="border-t border-border/40">
          <td className="py-0.5 text-muted-foreground">{b ? size(b.volume) : ""}</td>
          <td className="text-rose-300">{b ? px(b.price) : ""}</td>
          <td className="text-emerald-300">{a ? px(a.price) : ""}</td>
          <td className="text-muted-foreground">{a ? size(a.volume) : ""}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}

const SIDE_CLASS: Record<Exclude<Side, null>, string> = { ask: "text-emerald-300", bid: "text-rose-300" };

function Prints({ prints, big }: { prints: Print[]; big: number | null }) {
  if (!prints.length) return <p data-testid="tape-prints" className="text-muted-foreground">No prints yet.</p>;
  return (
    <ol data-testid="tape-prints" aria-label="Time and sales" className="max-h-56 overflow-y-auto tabular-nums">
      {prints.slice(0, SHOWN).map((p, i) => {
        const heavy = big !== null && p.volume >= big;
        return (
          <li key={p.key} data-side={p.side ?? undefined} data-big={heavy || undefined}
            className={cn("grid grid-cols-[4.25rem_minmax(0,1fr)_3.5rem_2.75rem] gap-x-2 border-t border-border/30 py-0.5 first:border-t-0",
              i >= PHONE_PRINTS && "max-sm:hidden", heavy && "bg-primary/10 font-semibold")}>
            <span className="text-muted-foreground">{clock(p.time_ms ?? p.received_ms)}</span>
            <span className={cn("text-right", p.side ? SIDE_CLASS[p.side] : "text-foreground")}>{px(p.price)}</span>
            <span className="text-right">{size(p.volume)}</span>
            <span className="text-right text-[10px] text-muted-foreground">{p.side === "ask" ? "at ask" : p.side === "bid" ? "at bid" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}
