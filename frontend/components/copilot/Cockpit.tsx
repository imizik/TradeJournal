"use client";

/**
 * The desk's cockpit pieces (docs/copilot-lab.md § The desk): the top bar's day P&L, the Needs-you strip, the book of
 * followed positions with "Since you looked" under it, and the centre's chart with its tiles. CopilotLab lays them out
 * and owns every action; these only show what the desk's reads say. Facts and counts only: nothing here tells the owner
 * to buy, sell or hold, sizes anything or sends an order.
 */

import { Fragment, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { EyeOff, RefreshCw } from "lucide-react";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { NotFollowed } from "@/components/copilot/SessionTape";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getExposure, type Exposure } from "@/lib/copilot";
import { behindWords, useRobinhoodBehind } from "@/components/copilot/DeskHealth";
import { DESK_CHANGED_EVENT, DESK_TIMEFRAME_KEY } from "@/lib/deskAction";
import { DeskChart, ReadingLine, type DeskChartActions, type DeskGuide } from "@/components/copilot/DeskChart";
import { ChartHead, type ChartTools } from "@/components/copilot/DeskChartHead";
import { noteChartPrice } from "@/components/copilot/DeskResearch";
import { DeskTimeline } from "@/components/copilot/Inspector";
import { ChartViewToggle, ContractChart, heldContract, useContractView } from "@/components/copilot/DeskContract";
import { EarningsTag, PositionEarnings } from "@/components/copilot/EarningsTag";
import {
  DESK_MARKET, DESK_TIMEFRAMES, daysTo, deskSymbolThread, getDeskSparks, liveOn, money, nyDay, readLook, saveLook, signedPct, sinceLines,
  type DeskBookState, type DeskChartData, type DeskEvents, type DeskLive, type DeskLook, type DeskTimeframe, type DeskNeed, type DeskSession, type DeskSparks, type DeskThread, type DeskThreadRef,
} from "@/lib/desk";
import { staleSince, tickFor, tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { Flash, PricesAsOf } from "@/components/copilot/Ticks";
import { OptionStandingLine } from "@/components/copilot/OptionStanding";
import { DeskPaperPosition, DeskPosition } from "@/components/copilot/DeskPosition";
import type { PanelPlan } from "@/lib/deskPosition";
import type { PaperPosition, PaperWorkingOrder } from "@/lib/paperBook";
import { OrderLines, OrdersGroup } from "@/components/copilot/DeskOrders";
import { NoteButton, NoteLines, useDeskNotes } from "@/components/copilot/DeskNotes";
import { useFolds } from "@/components/copilot/DeskUse";
import { fillKey, rowTrade } from "@/lib/deskNotes";
import ModeMark from "@/components/copilot/ModeMark";
import { useTapeOpen } from "@/components/copilot/TapeToggle";
import { cn } from "@/lib/utils";
import { deskBeats, everyDeskMinute, onDeskBeat } from "@/lib/deskMinute";

// The Tape's code (Level 2, the depth session) loads the first time it is opened.
const DeskTape = dynamic(() => import("@/components/copilot/DeskTape").then(m => m.DeskTape), { ssr: false });

export const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const ET = "America/New_York";
export const tone = (value: number | null | undefined) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-300" : "text-rose-300";
const clockOf = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });

/** The open positions' rows: the journal's ``trade:`` rows and, while the Robinhood feed is live, the ``robinhood:`` rows
 * of positions the journal does not have yet. */
export const positionRows = (rows: DeskThread[]) => rows.filter(r => r.key.startsWith("trade:") || r.key.startsWith("robinhood:"));

// ------------------------------------------------------------------------------------------------ the book's heading

/** "Open −$726 · Realized today +$539": every open position's unrealized P&L now (live prices folded in) and the trades
 * closed today. The calm pass took it off the top bar: it is the book heading's hover (and ⌘K's "Today"). Null until read. */
export function dayMoneyWords(rows: DeskThread[], ticks: ReturnType<typeof useDeskTicks>, realizedToday: number | null | undefined, read: boolean): string | null {
  const ticked = positionRows(rows).map(r => tickedBook(r.book, ticks));
  const open = ticked.flatMap(p => p.usd != null ? [p.usd] : []);
  const behind = ticked.some(p => p.stale) ? " (prices behind)" : ""; // a price in it is no longer live, as its row is greyed
  // Nothing closed today (exactly $0) says nothing.
  const realized = realizedToday ? realizedToday : null;
  const parts = [read && open.length ? `Open ${money(open.reduce((a, b) => a + b, 0))}${behind}` : null, realized !== null ? `Realized today ${money(realized)}` : null];
  return parts.filter(Boolean).join(" · ") || null;
}

export const LIVE_WORDS: Record<DeskLive["state"], string> = {
  off: "", signed_out: "Robinhood signed out · from the journal", expired: "Robinhood sign-in expired · from the journal",
  loading: "reading Robinhood…", unavailable: "Robinhood unavailable · from the journal", stale: "Robinhood stale · from the journal",
  ok: "live from Robinhood",
};

/** Where the book's numbers come from, said only when it matters (nothing while the feed is off: the book is the
 * journal's, as it always was). Behind: one quiet line, "Robinhood stale · as of 4:30 PM", the same state the status
 * line shows (``useRobinhoodBehind``: either read saying behind is behind). Live: only a small ↻ that reads Robinhood
 * again, its as-of on hover. */
function LiveLine({ live, onRefresh }: { live: DeskLive | null; onRefresh?(): void }) {
  const behind = useRobinhoodBehind();
  if (!live || live.state === "off") return null;
  const on = liveOn(live);
  const at = (seconds: number | null | undefined) => seconds ? ` · as of ${clockOf(seconds)}` : "";
  const again = (testId: string) => on && onRefresh ? (
    <button type="button" data-testid={testId} onClick={onRefresh} aria-label="Read Robinhood again"
      title={`Live from Robinhood${at(live.as_of)} · read again`}
      className="ml-auto inline-flex min-h-11 min-w-11 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-6 sm:min-w-6">
      <RefreshCw size={12} aria-hidden />
    </button>
  ) : null;
  if (on && !behind) return again("book-live");
  // The book's read was live but the health read says Robinhood is behind (a newer read, or only its orders pass): its
  // own words, as the status line says them, with the ↻ kept.
  if (on && behind) return (
    <>
      {again("book-live-again")}
      <span data-testid="book-live" data-state={behind.state} title={`${behind.line} · ${behind.affects}`}
        className="basis-full text-[11px] text-rose-300/90 max-md:hidden">{behindWords(behind)}</span>
    </>
  );
  if (live.state === "loading") return <span data-testid="book-live" className="ml-auto text-[11px] text-muted-foreground">{LIVE_WORDS.loading}</span>;
  // Not live: the book's own word ("ok" here is a read whose join with the journal failed: unavailable).
  const word = ({ stale: "stale", unavailable: "unavailable", signed_out: "signed out", expired: "sign-in expired" } as Record<string, string>)[live.state] ?? "unavailable";
  return (
    <span data-testid="book-live" data-state={live.state === "ok" ? "unavailable" : live.state} title="From the journal until Robinhood reads again"
      // A phone's value block, right above the book, already says it.
      className="basis-full text-[11px] text-rose-300/90 max-md:hidden">Robinhood {word}{word === "stale" || word === "unavailable" ? at(live.as_of) : ""}</span>
  );
}

// ------------------------------------------------------------------------------------------------ the strip

type StripAction = { label: string; run(): void; primary?: boolean };

/**
 * The Needs-you strip: one card for the most urgent decision (``deskNeeds``' order) with its own answers, and "+N more"
 * opening every other item at once, each with its own answers. Nothing here is dismissed: an item clears itself when its
 * condition ends or the owner opens its ticker. Nothing when nothing needs a decision.
 */
export function NeedsStrip({ needs, actions }: { needs: DeskNeed[]; actions(need: DeskNeed): StripAction[] }) {
  const [more, setMore] = useState(false);
  const [first, ...rest] = needs;
  if (!first) return null;
  const buttons = (need: DeskNeed, small = false) => actions(need).map(b => (
    <button key={b.label} type="button" onClick={b.run}
      className={cn("inline-flex min-h-11 items-center rounded-md border px-3 text-xs sm:min-h-8", small && "sm:min-h-7 px-2",
        b.primary && !small ? "border-primary bg-primary font-semibold text-primary-foreground hover:bg-primary/90" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
      {b.label}
    </button>
  ));
  return (
    <section aria-label="Needs you" data-testid="needs-you" className="rounded-lg border border-primary/45 bg-primary/[0.07] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className={cn(LABEL, "text-primary")}>Needs you</span>
        <div className="min-w-0 flex-1 basis-60">
          <p data-testid="needs-you-title" className="text-sm font-semibold text-foreground">{first.title}</p>
          {first.detail && <p className="text-xs text-muted-foreground">{first.detail}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {buttons(first)}
          {rest.length > 0 && (
            <button type="button" aria-expanded={more} onClick={() => setMore(open => !open)}
              className="min-h-11 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">+{rest.length} more {more ? "▴" : "▾"}</button>
          )}
        </div>
      </div>
      {more && rest.length > 0 && (
        <ul aria-label="More waiting" className="mt-2 space-y-1 border-t border-primary/20 pt-2">
          {rest.map(need => (
            <li key={need.key} data-testid="needs-you-more" className="flex flex-wrap items-center gap-x-2 gap-y-1 border-primary/15 px-1 py-1 text-xs max-sm:border-t max-sm:py-2 max-sm:first:border-t-0 max-sm:first:pt-0">
              <span className="min-w-0 flex-1 basis-48 text-foreground">{need.title}</span>
              <span className="flex flex-wrap gap-1.5">{buttons(need, true)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ the book

/** Each symbol's day so far (``GET /copilot/desk/sparks``, at most ``SPARKS`` symbols in the order given), read once a
 * minute while the page shows; nothing when the read fails. ``watch``, the Watching list's names, ride the same read
 * (its price and change, a line only where one costs no read of its own). A read started for an earlier set of symbols
 * is not cut off: its rows land beside the new read's (the Watching list often arrives a moment after the book). */
const SPARKS = 12;
export function useSparks(symbols: string[], watch: string[] = []): DeskSparks | null {
  const [data, setData] = useKeptState<DeskSparks | null>("desk.sparks", null); // the last lines, until today's read
  const shown = useRef(data);
  const book = [...new Set(symbols)].slice(0, SPARKS);
  const key = book.sort().join(",");
  const watchKey = [...new Set(watch)].filter(s => !book.includes(s)).sort().join(",");
  const controllers = useRef(new Set<AbortController>());
  useEffect(() => {
    const open = controllers.current;
    return () => { for (const c of open) c.abort(); }; // leaving the desk cuts every read off
  }, []);
  useEffect(() => {
    if (!key && !watchKey) return;
    const read = () => {
      const controller = new AbortController();
      controllers.current.add(controller);
      getDeskSparks(key ? key.split(",") : [], controller.signal, watchKey ? watchKey.split(",") : []).then(next => {
        const prev = shown.current;
        if (prev && next.as_of < prev.as_of) return; // a slower, older read never replaces a newer one
        // Rows of symbols this read did not name stay only within the same New York day: never yesterday's line as today's.
        const merged = prev && nyDay(new Date(prev.as_of)) === nyDay(new Date(next.as_of)) ? { ...next, rows: { ...prev.rows, ...next.rows } } : next;
        shown.current = merged;
        setData(merged);
      }).catch(() => { /* the lines are extra */ }).finally(() => controllers.current.delete(controller));
    };
    read();
    return everyDeskMinute(read); // a new set of symbols starts another read; the one in flight still lands
  }, [key, watchKey, setData]);
  return data;
}

export function Spark({ points, label }: { points: number[] | undefined; label: string }) {
  if (!points || points.length < 2) return <span aria-hidden className="w-12" />;
  const lo = Math.min(...points), hi = Math.max(...points);
  const line = points.map((v, i) => `${(i * 56 / (points.length - 1)).toFixed(1)},${(20 - ((v - lo) / (hi - lo || 1)) * 18).toFixed(1)}`).join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg width="48" height="22" viewBox="0 0 56 22" preserveAspectRatio="none" role="img" aria-label={label} className="shrink-0">
      <polyline points={line} fill="none" strokeWidth="1.4" className={up ? "stroke-emerald-300" : "stroke-rose-300"} />
    </svg>
  );
}

const STATE: Record<Exclude<DeskBookState, "no_plan">, { label: string; className: string }> = {
  on_plan: { label: "On plan", className: "text-muted-foreground" },
  giving_back: { label: "Giving back", className: "border-foreground/30 text-foreground" },
  near_stop: { label: "Near stop", className: "border-rose-300/40 text-rose-300" },
  past_stop: { label: "Past stop", className: "border-rose-300/40 text-rose-300" },
};
const EXPIRES_TODAY = { label: "Expires today", className: "border-foreground/30 text-foreground" };

/** The book row's tag, only when it tells the owner something: Past stop, Near stop and Giving back first, then
 * Expires today (an option), then On plan. A position with no plan has none: its missing plan bar and the day report's
 * "Open without a plan" line say so, and on four rows of five the tag said nothing. */
export function bookTag(row: DeskThread, day: string): { label: string; className: string } | null {
  const book = row.book;
  if (!book) return null;
  if (book.state === "past_stop" || book.state === "near_stop" || book.state === "giving_back") return STATE[book.state];
  if (book.expiry && row.instrument !== "stock" && daysTo(book.expiry, day) === 0) return EXPIRES_TODAY;
  return book.state === "on_plan" ? STATE.on_plan : null;
}

/** Where the underlying sits between the plan's invalidation (left) and entry (the tick), from the row's track; nothing
 * without plan lines (no bar: no plan). */
function Track({ track }: { track: NonNullable<DeskThread["book"]>["track"] }) {
  if (!track) return null;
  return (
    <div role="img" aria-label={`Between invalidation and entry: ${track.last.toFixed(0)} of ${track.entry.toFixed(0)}`} className="relative mb-1 mt-2 h-[3px] rounded bg-secondary">
      <i className="absolute -top-[3px] left-0 h-[9px] w-0.5 bg-muted-foreground/60" />
      <i className="absolute -top-[3px] h-[9px] w-0.5 bg-muted-foreground/60" style={{ left: `${track.entry}%` }} />
      <u className="absolute -top-[3px] -ml-1 h-[9px] w-[9px] rounded-full bg-foreground" style={{ left: `${track.last}%` }} />
    </div>
  );
}

/** A symbol's last price from the sparks read (the minute line), for a standing when the live ticker is not running. */
const sparkPrice = (sparks: DeskSparks | null, symbol: string | null) => {
  const spark = symbol ? sparks?.rows[symbol] : undefined;
  const last = spark?.last ?? spark?.points.at(-1);
  const at = sparks ? Date.parse(sparks.as_of) / 1000 : NaN;
  return last != null && Number.isFinite(at) ? { last, at } : null;
};

const premium = (value: number) => `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A held contract's (or share's) price now and its move today, for the phone's row line: the live tick of the
 * contract, else Robinhood's mark at its read; today is Robinhood's move at the read (``book.day_change``) carried to
 * the live price, or, with the feed not live, a share held since before today: its move since yesterday's close from its tick. Null when unknown:
 * shown as a dash, never zero. */
export function rowNow(book: DeskThread["book"], ticks: ReturnType<typeof useDeskTicks>): { price: number | null; today: number | null; stale: boolean } {
  if (!book) return { price: null, today: null, stale: false };
  const terms = book.tick;
  const tick = terms ? tickFor(ticks, terms.quote) : null;
  const scale = terms?.scale ?? (book.option || book.expiry ? 100 : 1); // an option's mark is a contract's
  const price = tick ? tick.last : book.live && book.live !== "not_on_robinhood" && book.mark ? book.mark / scale : null;
  let today: number | null = null;
  if (book.day_change != null) {
    const moved = tickedBook(book, ticks);
    today = Math.round((book.day_change + (moved.usd != null && book.usd != null ? moved.usd - book.usd : 0)) * 100) / 100;
  } else if (!book.live && terms && tick && scale === 1 && tick.prev_close && book.days_held != null && book.days_held > 0) {
    today = Math.round(terms.sign * (tick.last - tick.prev_close) * terms.quantity * 100) / 100;
  }
  return { price, today, stale: !!tick?.stale };
}

const left = (expiry: string | null, day: string) => {
  if (!expiry) return null;
  const n = daysTo(expiry, day);
  return n < 0 ? "expired" : n === 0 ? "expires today" : `${n}d left`;
};

/**
 * The book: one dense row per followed open position (ticker, contract, unrealized P&L in dollars and percent, where it
 * sits between invalidation and entry, days to expiry and one state tag; no sparkline since the calm pass: the chart has it).
 * Selecting a row (``onSelect``) drives the centre and the copilot; its eye stops following the ticker (``onFollow``),
 * and those sit behind "N not followed" at the bottom. The selected row (and its standing line) carry ``data-selected``:
 * a phone's ticker view keeps just that row above the chart (CopilotLab.module.css).
 */
export function Book({ rows, sparks, selected, selectedKey = null, day, read, updating = false, live = null, earnings = null, risk = null, filter = null, accounts = null, realized = null, onRefreshLive, onSelect, onFollow, children }: {
  rows: DeskThread[]; sparks: DeskSparks | null; selected: string | null; selectedKey?: string | null; day: string; read: boolean;
  /** The book narrowed to one account (an account chip): "Showing Roth IRA only · Show all" under the heading. */
  filter?: { label: string; onShowAll(): void } | null;
  /** The safety figure in the heading (``RiskWord``: what is at risk now, its full line on hover). Never folded. */
  risk?: ReactNode;
  /** The live account line (``DeskAccounts``), under the heading: only while Robinhood is live. */
  accounts?: ReactNode;
  /** Trades closed today (the session read), for the heading's hover beside the open P&L. */
  realized?: number | null;
  /** Earnings tags (``useDeskEvents``), by symbol. */
  earnings?: DeskEvents | null;
  /** The rows are the desk's last read, kept for its remount, with the fresh read on the way: P&L dimmed, "Updating". */
  updating?: boolean;
  live?: DeskLive | null; onRefreshLive?(): void;
  onSelect(row: DeskThread): void; onFollow(symbol: string, following: boolean): Promise<void>; children?: ReactNode;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const [stocksOpen, setStocksOpen] = useState(false);
  const held = positionRows(rows);
  const shown = held.filter(r => !r.hidden);
  // Live from Robinhood: options first; a stock without a plan (a long-term holding) waits behind "N stock positions".
  const isLive = liveOn(live);
  // A stock with a Robinhood order working or filled today stays out in the open.
  const folded = isLive ? shown.filter(r => r.instrument === "stock" && !r.book?.planned && !r.book?.orders?.length) : [];
  const followed = isLive ? [...shown.filter(r => r.instrument !== "stock"), ...shown.filter(r => r.instrument === "stock" && !folded.includes(r)),
    ...(stocksOpen ? folded : [])] : shown;
  // The account tag only when the book spans accounts: one account is the top bar's chip, not a word on every row.
  const mixed = new Set(followed.flatMap(r => r.book?.account ? [r.book.account.masked] : [])).size > 1;
  // One row is marked: the one tapped, else the first on the centre's ticker (two contracts can share a ticker).
  const marked = followed.find(r => r.key === selectedKey && r.symbol === selected)?.key ?? followed.find(r => r.symbol === selected)?.key;
  const ticks = useDeskTicks(followed.flatMap(r => [r.book?.tick?.quote, r.symbol]));
  // His notes on each row's trade and on the Orders group's fills (DeskNotes.tsx).
  const notes = useDeskNotes(followed.flatMap(r => rowTrade(r) ?? []), isLive ? (live?.orders ?? []).filter(o => !o.working).map(fillKey) : []);
  const follow = (symbol: string, following: boolean) => {
    setFailed(null);
    onFollow(symbol, following).catch(() => setFailed(`${symbol}: not saved. Try again.`));
  };
  const allTicks = useDeskTicks(held.map(r => r.book?.tick?.quote));
  const moneyWords = dayMoneyWords(held, allTicks, realized, read);
  return (
    <section aria-label="Your book" data-testid="desk-book" data-desk-book className="rounded-lg border bg-card">
      {/* One line: "Your book · 8 · at risk $1,969" and its REAL mark; the open P&L and today's realized on hover; where
          the numbers come from only when Robinhood is behind. */}
      <div data-testid="book-head" className="flex min-w-0 flex-wrap items-baseline gap-x-2 px-3 pb-1.5 pt-2.5 max-sm:items-center max-sm:py-0">
        <h2 data-use="pnl" className={cn(LABEL, "shrink-0")} title={moneyWords ? `${moneyWords} · ${shown.length} followed` : undefined}>
          Your book{shown.length > 0 && <> · <span className="tabular-nums" data-testid="book-count">{shown.length}</span></>}
        </h2>
        {risk}
        <ModeMark mode="real" />
        <LiveLine live={live} onRefresh={onRefreshLive} />
        <PricesAsOf at={staleSince(ticks, followed.map(r => r.book?.tick?.quote))} />
        {updating && <span role="status" data-testid="book-updating" className="text-[11px] text-muted-foreground">Updating…</span>}
      </div>
      {accounts}
      {filter && (
        <p data-testid="book-filter" className="flex flex-wrap items-center gap-x-1.5 px-3 pb-1 text-xs text-muted-foreground">
          <span>Showing <span className="font-medium text-foreground">{filter.label}</span> only</span>
          <span aria-hidden>·</span>
          <button type="button" data-testid="book-filter-all" onClick={filter.onShowAll}
            className="inline-flex min-h-11 items-center text-foreground underline underline-offset-2 hover:text-foreground sm:min-h-0">Show all</button>
        </p>
      )}
      {isLive && <OrdersGroup orders={live?.orders} notes={notes} />}
      {followed.length ? (
        <ul>
          {followed.map(row => {
            const book = row.book;
            const state = bookTag(row, day);
            // "11/14 105C": this year's expiries drop the year, so the contract fits beside its line and figures.
            const full = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
            const contract = full.replace(/\b(\d{1,2}\/\d{1,2})\/(\d{2})\b/, (date, monthDay: string, year: string) => year === day.slice(2, 4) ? monthDay : date);
            const count = book?.quantity != null ? ` ×${book.quantity.toLocaleString("en-US", { maximumFractionDigits: 4 })}` : "";
            const on = row.key === marked;
            const pnl = tickedBook(book, ticks);
            const now = rowNow(book, ticks);
            return (<Fragment key={row.key}>
              <li data-selected={on || undefined} className={cn("group/row flex items-stretch border-t", on && "bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]")}>
                <button type="button" onClick={() => onSelect(row)} aria-pressed={on} aria-label={`${row.symbol} ${full}`}
                  className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(60px,auto)] items-center gap-2 py-2 pl-3 text-left hover:bg-secondary">
                  <span className="min-w-0 overflow-hidden">
                    <span className="flex items-baseline gap-1.5">
                      <span className="text-sm font-semibold text-foreground">{row.symbol}</span>
                      <span className="min-w-0 truncate text-xs tabular-nums text-muted-foreground">{contract}{count}</span>
                    </span>
                    {/* A phone (as Robinhood's list does): the contract's price now and its move today. */}
                    {book && <span data-testid="book-now" className={cn("block text-[11px] tabular-nums text-muted-foreground md:hidden", now.stale && "opacity-50")}>
                      <span data-testid="book-price">{now.price == null ? "—" : premium(now.price)}</span> · today{" "}
                      <span data-testid="book-today" className={tone(now.today)}>{now.today == null ? "—" : money(now.today)}</span>
                    </span>}
                    {book ? <Track track={book.track} /> : <span className="block truncate text-xs text-muted-foreground">{row.status.text}</span>}
                    {/* Wraps rather than spilling: a tag never runs under the sparkline or the P&L, at any width. */}
                    <span data-testid="book-meta" className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-muted-foreground [&>*]:max-w-full [&>*]:truncate [&>*]:whitespace-nowrap">
                      {mixed && book?.account && <span data-testid="book-account" title={`${book.account.label} ${book.account.masked}`}>{book.account.label}</span>}
                      {book?.stop_pct != null && <span className="tabular-nums">{Math.abs(book.stop_pct).toFixed(1)}% to stop</span>}
                      {book && left(book.expiry, day) && state !== EXPIRES_TODAY && <span className="tabular-nums">{left(book.expiry, day)}</span>}
                      {book?.live === "new" ? <span data-testid="book-state" className="rounded border border-sky-300/40 px-1 text-sky-300">New · not in the journal yet</span>
                        : state && <span data-testid="book-state" className={cn("rounded border px-1", state.className)}>{state.label}</span>}
                      <EarningsTag tag={row.symbol ? earnings?.rows[row.symbol] : undefined} day={day} />
                      {book?.live === "not_on_robinhood" && <span data-testid="book-not-live" className="rounded border px-1">Not on Robinhood</span>}
                    </span>
                    {isLive && <OrderLines orders={book?.orders} />}
                  </span>
                  <span data-testid="book-pnl" className={cn("whitespace-nowrap text-right text-sm tabular-nums", tone(pnl.usd), (updating || pnl.stale) && "opacity-50")}>
                    <Flash value={pnl.usd}>{pnl.usd != null ? money(pnl.usd) : row.value?.text ?? "—"}</Flash>
                    {pnl.pct != null && <span className="block text-[11px]">{signedPct(pnl.pct)}</span>}
                  </span>
                </button>
                {/* The pen and the eye: side by side on a phone, stacked in one column beside the narrow book. With a mouse
                    they show on the row's hover or focus (the space stays, so nothing moves); a touch screen always has them. */}
                <span data-testid="book-row-tools" className="flex shrink-0 sm:flex-col-reverse [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/row:opacity-100 [@media(hover:hover)]:group-focus-within/row:opacity-100">
                  {rowTrade(row) && <NoteButton notes={notes} id={row.key} label="this position" className="sm:flex-1" />}
                  {row.symbol && (
                    <button type="button" onClick={() => follow(row.symbol!, false)} aria-label={`Hide ${row.symbol}: not following`}
                      title="Not following: hide this ticker from the desk and every count (Show again undoes it)"
                      className="flex w-8 shrink-0 items-center justify-center text-muted-foreground/40 hover:bg-secondary hover:text-foreground sm:flex-1">
                      <EyeOff size={13} aria-hidden />
                    </button>
                  )}
                </span>
              </li>
              <NoteLines notes={notes} id={row.key} trade={rowTrade(row)} target={rowTrade(row) ? { trade_id: rowTrade(row)! } : null} selected={on}
                label="this position" className={cn("px-3 pb-1.5", on && "bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]")} as="li" />
              {on && book?.option && <li data-selected className="bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]"><OptionStandingLine row={row} rows={held} fallback={sparkPrice(sparks, row.symbol)} /></li>}
            </Fragment>);
          })}
        </ul>
      ) : <p className="border-t px-3 py-2.5 text-xs text-muted-foreground">{!read ? "Reading positions…" : held.length ? "Only positions you don't follow are open." : "No open positions."}</p>}
      {folded.length > 0 && (
        <button type="button" aria-expanded={stocksOpen} onClick={() => setStocksOpen(open => !open)} data-testid="book-stocks"
          className="flex min-h-11 w-full items-center gap-1 border-t px-3 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
          {stocksOpen ? "Hide" : <span className="tabular-nums">{folded.length}</span>} stock position{folded.length === 1 ? "" : "s"} {stocksOpen ? "▴" : "▾"}
        </button>
      )}
      <div className="px-1.5 pb-1"><NotFollowed rows={held.filter(r => r.hidden)} open={onSelect} onFollow={follow} /></div>
      {failed && <p role="alert" className="px-3 pb-2 text-xs text-rose-300">{failed}</p>}
      {children}
    </section>
  );
}

/**
 * "Since you looked · 10:20": what changed since the owner last left the desk in this browser (``sinceLines``), four
 * lines at most. The look is saved when the page is hidden or left, and read again when it shows.
 */
export function SinceYouLooked({ rows, session, read }: { rows: DeskThread[]; session: DeskSession | null; read: boolean }) {
  const [look, setLook] = useState<DeskLook | null | undefined>(undefined);
  useEffect(() => { setLook(readLook()); }, []); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
  const current = useMemo<DeskLook | null>(() => {
    if (!read) return null;
    // The journal's positions only: a Robinhood-only row becomes a trade row once its email arrives (not a close).
    const held = rows.filter(r => r.key.startsWith("trade:") && r.book && r.symbol && !r.hidden);
    return { at: 0, pnl: Object.fromEntries(held.map(r => [r.key, r.book!.usd ?? 0])),
      contracts: Object.fromEntries(held.map(r => [r.key, r.title])) };
  }, [rows, read]);
  useEffect(() => {
    if (!current) return;
    const away = () => { if (document.visibilityState === "hidden") saveLook({ ...current, at: Math.floor(Date.now() / 1000) }); };
    const back = () => { if (document.visibilityState === "visible") setLook(readLook()); };
    const leave = () => saveLook({ ...current, at: Math.floor(Date.now() / 1000) });
    document.addEventListener("visibilitychange", away);
    document.addEventListener("visibilitychange", back);
    window.addEventListener("pagehide", leave);
    return () => {
      document.removeEventListener("visibilitychange", away);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("pagehide", leave);
      leave(); // a thread opened by its link remounts the desk: that counts as having looked
    };
  }, [current]);
  if (look === undefined || !read) return null;
  const lines = look ? sinceLines(look, rows, session?.events ?? []) : [];
  return (
    <section aria-label="Since you looked" data-testid="since-you-looked" className="rounded-lg border bg-card px-3 py-2.5">
      <h2 className={LABEL}>Since you looked{look && <> · <span className="tabular-nums">{clockOf(look.at)}</span></>}</h2>
      {!look ? <p className="mt-1 text-xs text-muted-foreground">First look from this browser. Changes show from your next visit.</p>
        : lines.length ? <ul className="mt-1 space-y-0.5 text-xs text-foreground/90">{lines.map(line => <li key={line} className="tabular-nums">{line}</li>)}</ul>
          : <p className="mt-1 text-xs text-muted-foreground">Nothing new since then.</p>}
    </section>
  );
}

/** The exposure read ("At risk now: $6,400 in 3 options · usual day $2,100" and its figure), once the session is known,
 * then each minute; null when the read fails or no long option is open. */
function useExposure(asOf: string | undefined): Exposure | null {
  const [exposure, setExposure] = useState<Exposure | null>(null);
  const beat = useSyncExternalStore(onDeskBeat, deskBeats, () => 0); // the desk's shared minute, inside its one request
  const known = !!asOf;
  useEffect(() => {
    if (!known) return;
    const controller = new AbortController();
    getExposure(controller.signal).then(now => setExposure(now.line ? now : null)).catch(() => {
      if (!controller.signal.aborted) setExposure(null); /* the figure is extra */
    });
    return () => controller.abort();
  }, [known, beat]);
  return exposure;
}

/** The book's safety figure, in its heading: "· at risk $6,400", the full line on hover (in how many options, against a
 * usual day). Never folded (``dayfacts``). Nothing when the read fails or no long option is open. */
export function RiskWord({ session }: { session: DeskSession | null }) {
  const exposure = useExposure(session?.as_of);
  if (!exposure?.line) return null;
  const figure = exposure.at_risk_usd != null ? `$${Math.round(exposure.at_risk_usd).toLocaleString("en-US")}` : null;
  return (
    <span data-testid="exposure-line" data-use="dayfacts" title={exposure.line} aria-label={exposure.line}
      className={cn(LABEL, "shrink-0 normal-case tracking-normal")}>
      {figure ? <>· at risk <span className="tabular-nums text-foreground/90">{figure}</span></> : exposure.line}
    </span>
  );
}

/** One quiet line under the day's block: the practice goal with this week's count. Nothing until it reads. */
export function DayFacts() {
  const practice = usePracticeLine(true);
  if (!practice) return null;
  return <p data-testid="session-facts" className="px-1 text-xs text-muted-foreground">{practice}</p>;
}

// ------------------------------------------------------------------------------------------------ the centre

function Tile({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className="rounded-md bg-secondary px-2.5 py-1.5">
      <span className="block text-[11px] text-muted-foreground">{label}</span>
      <b className={cn("text-sm font-medium tabular-nums", className)}>{children}</b>
    </div>
  );
}

const NO_PAPER: readonly PaperPosition[] = [];
const SPAN: Record<DeskTimeframe, string> ={ "2m": "today: 2-minute candles", "15m": "recent sessions: 15-minute candles", "1D": "the last few months: daily candles" };
const TIMEFRAME_KEY = DESK_TIMEFRAME_KEY;

/** The chart's timeframe, kept for the tab's session so it holds its place across positions and tab switches. */
function useDeskTimeframe(): [DeskTimeframe, (next: DeskTimeframe) => void] {
  const [timeframe, setTimeframe] = useState<DeskTimeframe>("2m");
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(TIMEFRAME_KEY);
      if (saved && (DESK_TIMEFRAMES as readonly string[]).includes(saved)) setTimeframe(saved as DeskTimeframe); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
    } catch { /* 2m */ }
    // A copilot card that shows a timeframe wrote it where this reads (``lib/deskAction.ts``): follow it.
    const follow = (event: Event) => { const next = (event as CustomEvent<{ timeframe?: DeskTimeframe }>).detail?.timeframe; if (next) setTimeframe(next); };
    window.addEventListener(DESK_CHANGED_EVENT, follow);
    return () => window.removeEventListener(DESK_CHANGED_EVENT, follow);
  }, []);
  const pick = (next: DeskTimeframe) => {
    setTimeframe(next);
    try { window.sessionStorage.setItem(TIMEFRAME_KEY, next); } catch { /* private mode: the choice lasts this view */ }
  };
  return [timeframe, pick];
}

/**
 * The centre's Chart: the selected symbol's interactive chart (``DeskChart``: candles with the plan's entry and invalidation
 * lines, the owner's fills, today's pings and Radar hits and a time stop still ahead, on 2m, 15m or 1D; the timeframe
 * holds across positions) under its one header row (``DeskChartHead``), then the Position content: the held position's
 * Position panel (``DeskPosition``: its figures, an option's standing and every button that manages it) and any paper
 * position's in the ticker, then two tiles for a held position that its book row does not carry (the stock against SPY
 * today, time held: P&L, the distance to the stop and expiry are the row's) and, folded, what touched the thread. No
 * symbol: QQQ with the owner's fills and pings. ``dock`` places the Position content (the desk's dock under the chart,
 * its Position tab); without it the content follows the chart.
 */
export function CentreChart({ symbol, thread, row, sparks, actions, rows = [], earnings = null, guides, onReplay, paper = NO_PAPER, paperOrders, onPlan, ordersLive = false, dock, className, chartClassName }: {
  /** The dock under the chart, given the Position content for its Position tab. */
  dock?(position: ReactNode): ReactNode;
  /** The whole (chart and dock) and the chart's own part: the desk's layout classes. */
  className?: string; chartClassName?: string;
  symbol: string | null; thread: DeskThreadRef | null; row: DeskThread | null; sparks: DeskSparks | null; actions?: DeskChartActions;
  /** Opens Replay: paper trading on a past day (``DeskReplay``). */
  onReplay?(): void;
  /** His open paper positions in this ticker, each with its own Position panel, and the paper book's working orders. */
  paper?: readonly PaperPosition[]; paperOrders?: PaperWorkingOrder[];
  /** The plan flow for a held position with no saved plan (the panel's Plan it). */
  onPlan?(symbol: string): void;
  /** The Robinhood feed is live: the panel shows the position's working orders, as the book does. */
  ordersLive?: boolean;
  /** The desk's rows, so a held option's standing can tell a lone long option from one leg of a structure. */
  rows?: DeskThread[];
  /** Earnings tags (``useDeskEvents``): a held option's header says when a report falls inside its life. */
  earnings?: DeskEvents | null;
  /** Thin lines for this symbol (a Feed Scanner row's trigger, stop and target). */
  guides?: DeskGuide[];
}) {
  const ref = useMemo(() => thread ?? (symbol ? deskSymbolThread(symbol) : null), [thread, symbol]);
  const [timeline, setTimeline] = useState(false);
  const [shown, setShown] = useState<DeskChartData | null>(null);
  const [timeframe, pickTimeframe] = useDeskTimeframe();
  const book = row?.book;
  const change = symbol ? sparks?.rows[symbol]?.change_pct ?? null : null;
  const spy = sparks?.spy_change_pct ?? null;
  const versus = change !== null && spy !== null ? change - spy : null;
  const charts = `/charts?symbol=${encodeURIComponent(symbol ?? "QQQ")}`;
  const sparksAt = sparks ? Date.parse(sparks.as_of) / 1000 : NaN;
  const fallback = change !== null && Number.isFinite(sparksAt) ? { pct: change, at: sparksAt } : null;
  const reading = shown && shown.symbol === (symbol ?? "QQQ") ? shown : null;
  const live = tickFor(useDeskTicks([symbol ?? "QQQ"]), symbol ?? "QQQ");
  const held = useMemo(() => heldContract(row, rows), [row, rows]);
  const contract = useContractView(held);
  const onContract = contract.view === "contract" && held && contract.data;
  const [tape, setTape] = useTapeOpen();
  const folds = useFolds(); // the chart's tools he folded away wait in its More (DeskChartHead.tsx)
  const name = symbol ?? "QQQ";
  const lastRead = reading?.state === "ok" ? reading.reading : null;
  useEffect(() => { noteChartPrice(name, lastRead?.last ?? null, lastRead?.at ?? null); }, [name, lastRead?.last, lastRead?.at]); // the Research drawer's Forecast uses the chart's price
  // The held position's plan for its panel: the chart's own read of its thread's plan (entry, invalidation, target), else
  // the book row's plan levels with the position's own thread. None without a stop.
  const levelAt = (role: "entry" | "invalidation" | "target") => reading?.levels.find(l => l.role === role)?.price ?? null;
  const chartLevels = { entry: levelAt("entry"), stop: levelAt("invalidation"), target: levelAt("target") };
  // The chart's plan only when it is the selected position's own (another conversation on the ticker may be another
  // plan, or another contract's): the panel never edits a plan that is not the row's.
  const readPlan = reading && ref && ref.id !== DESK_MARKET && !ref.id.startsWith("symbol:") && chartLevels.stop !== null
    && (!row?.investigationId || ref.id === row.investigationId);
  const plan: PanelPlan | null = readPlan
    ? { investigationId: ref!.id, ...chartLevels }
    : row?.investigationId && row.book?.plan_levels?.stop != null
      ? { investigationId: row.investigationId, entry: null, stop: row.book.plan_levels.stop, target: row.book.plan_levels.target ?? null }
      : null;
  const tapePanel =tape && !folds.hidden("chart.tape") ? <DeskTape symbol={name} option={!!row?.book?.option} /> : null;
  // The one row above the chart: the ticker, its price and change, the held contract, the switch and the timeframes, then
  // the chart's own tools (none on a held option's own chart).
  const head = (tools: ChartTools | null, info: ReactNode = null) => (
    <ChartHead symbol={name} reading={<ReadingLine part="head" symbol={name} data={reading} fallback={fallback} live={live} />}
      held={row ? (row.instrument && row.instrument !== row.symbol ? row.instrument : row.title) : null}
      view={contract.available ? <ChartViewToggle view={contract.view} onPick={contract.pick} /> : null}
      timeframe={onContract ? null : timeframe} onTimeframe={pickTimeframe} tools={tools} info={info} onReplay={onReplay}
      tape={tape} onTape={setTape} charts={charts} />
  );
  // The Position content: under the chart, or the dock's Position tab.
  const position = (
    <div className="space-y-2">
      {/* A held position's figures (an option's full standing) and every button that manages it; its book row keeps only
          the short standing line. A paper position in this ticker has its own panel, marked PAPER. */}
      {row?.book && <DeskPosition key={row.key} row={row} rows={rows} plan={plan} levels={!row.investigationId || ref?.id === row.investigationId ? chartLevels : undefined} change={change} onPlan={onPlan} ordersLive={ordersLive}
        fallback={reading?.state === "ok" && reading.reading ? { last: reading.reading.last, at: reading.reading.at } : sparkPrice(sparks, symbol)}
        earnings={symbol ? earnings?.rows[symbol]?.date ?? null : null} />}
      {paper.map(p => <DeskPaperPosition key={p.id} position={p} orders={paperOrders} />)}
      <PositionEarnings row={row} earnings={earnings} />
      {book && (versus !== null || book.days_held != null) && (
        <div data-testid="desk-tiles" className="grid grid-cols-[repeat(auto-fit,minmax(104px,1fr))] gap-1.5">
          {versus !== null && <Tile label="vs SPY today" className={tone(versus)}>{`${versus > 0 ? "+" : versus < 0 ? "−" : ""}${Math.abs(versus).toFixed(1)} pts`}</Tile>}
          {book.days_held != null && <Tile label="Held">{book.days_held === 0 ? "today" : `${book.days_held}d`}</Tile>}
        </div>
      )}
      {row && !book && <p className="text-xs text-muted-foreground">{row.status.text}</p>}
      {!book && !paper.length && <p data-testid="desk-position-none" className="text-xs text-muted-foreground">No open position in {name}. The Chain picks a contract.</p>}
      {ref?.symbol && (
        <div className="border-t pt-2">
          <button type="button" aria-expanded={timeline} onClick={() => setTimeline(open => !open)} data-use="chart.timeline"
            className="min-h-11 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Timeline {timeline ? "▴" : "▾"}</button>
          {timeline && <div className="pt-2"><DeskTimeline thread={ref} /></div>}
        </div>
      )}
    </div>
  );
  return (
    <div className={className ?? "space-y-2"} data-testid="desk-chart">
      {/* The chart part: it stays on top while the dock under it changes. Its time on screen counts as the Chart's. */}
      <div className={cn("space-y-2", chartClassName)} data-use="tab.chart">
      {onContract && <>
        {/* The stock's reading, with its as-of and basis, behind the header's ⓘ beside the contract's own chart. */}
        {head(null, <p className="text-[11px] leading-4 tabular-nums text-muted-foreground"><ReadingLine part="facts" symbol={name} data={reading} fallback={fallback} live={live} /></p>)}
        {tapePanel}
      </>}
      {onContract ? <ContractChart held={held} data={contract.data!} /> : (
        <DeskChart id={ref?.id ?? DESK_MARKET} timeframe={timeframe} refreshKey={ref?.refreshKey ?? 0} onRead={setShown} actions={actions} live={live} guides={guides}
          head={head} under={tapePanel} reading={<ReadingLine part="facts" symbol={name} data={reading} fallback={fallback} live={live} />} onTimeframe={pickTimeframe}
          label={`${name} ${SPAN[timeframe]}${ref ? " with the plan's entry and invalidation lines, your fills, and today's pings and Radar hits" : " with your fills and the phone pings sent today"}`} />
      )}
      </div>
      {dock ? dock(position) : position}
    </div>
  );
}
