"use client";

/**
 * The desk's cockpit pieces (docs/copilot-lab.md § The desk): the top bar's day P&L, the Needs-you strip, the book of
 * followed positions with "Since you looked" under it, and the centre's chart with its tiles. CopilotLab lays them out
 * and owns every action; these only show what the desk's reads say. Facts and counts only: nothing here tells the owner
 * to buy, sell or hold, sizes anything or sends an order.
 */

import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { EyeOff } from "lucide-react";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { NotFollowed } from "@/components/copilot/SessionTape";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getExposure } from "@/lib/copilot";
import { DeskChart, ReadingLine, type DeskChartActions } from "@/components/copilot/DeskChart";
import { DeskTimeline } from "@/components/copilot/Inspector";
import { ChartViewToggle, ContractChart, heldContract, useContractView } from "@/components/copilot/DeskContract";
import { EarningsTag, PositionEarnings } from "@/components/copilot/EarningsTag";
import {
  DESK_MARKET, DESK_TIMEFRAMES, daysTo, deskSymbolThread, getDeskSparks, liveOn, money, nyDay, readLook, saveLook, signedPct, sinceLines,
  type DeskBookState, type DeskChartData, type DeskEvents, type DeskLive, type DeskLook, type DeskTimeframe, type DeskNeed, type DeskSession, type DeskSparks, type DeskThread, type DeskThreadRef,
} from "@/lib/desk";
import { staleSince, tickFor, tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { Flash, PricesAsOf } from "@/components/copilot/Ticks";
import { OptionStanding, OptionStandingLine } from "@/components/copilot/OptionStanding";
import { OrderLines, OrdersGroup } from "@/components/copilot/DeskOrders";
import { DeskTape, TapeToggle, useTapeOpen } from "@/components/copilot/DeskTape";
import { cn } from "@/lib/utils";

export const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const ET = "America/New_York";
const REFRESH_MS = 60_000;
export const tone = (value: number | null | undefined) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-300" : "text-rose-300";
const clockOf = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });

/** The open positions' rows: the journal's ``trade:`` rows and, while the Robinhood feed is live, the ``robinhood:`` rows
 * of positions the journal does not have yet. */
export const positionRows = (rows: DeskThread[]) => rows.filter(r => r.key.startsWith("trade:") || r.key.startsWith("robinhood:"));

// ------------------------------------------------------------------------------------------------ top bar

/** "Realized today +$120 · Open +$355": the trades closed today (the session read) and every open position's
 * unrealized P&L now (the thread list's read, followed or not: it is the account's money). Nothing until read. */
export function DayPnl({ session, rows, read }: { session: DeskSession | null; rows: DeskThread[]; read: boolean }) {
  const ticks = useDeskTicks(positionRows(rows).map(r => r.book?.tick?.quote));
  const ticked = positionRows(rows).map(r => tickedBook(r.book, ticks));
  const open = ticked.flatMap(p => p.usd != null ? [p.usd] : []);
  const stale = ticked.some(p => p.stale); // a price in it is no longer live: greyed, as its book row is
  const total = open.reduce((a, b) => a + b, 0);
  const realized = session?.realized_today ?? null;
  if (realized === null && !(read && open.length)) return null;
  return (
    <span data-testid="desk-pnl" className="flex items-baseline gap-3 whitespace-nowrap text-xs">
      {realized !== null && <span><span className="text-muted-foreground">Realized today </span><span className={cn("tabular-nums", tone(realized))}>{money(realized)}</span></span>}
      {read && open.length > 0 && <span><span className="text-muted-foreground">Open </span><span data-testid="desk-pnl-open" className={cn("tabular-nums", tone(total), stale && "opacity-50")}>{money(total)}</span></span>}
    </span>
  );
}

const LIVE_WORDS: Record<DeskLive["state"], string> = {
  off: "", signed_out: "Robinhood signed out · from the journal", expired: "Robinhood sign-in expired · from the journal",
  loading: "reading Robinhood…", unavailable: "Robinhood unavailable · from the journal", stale: "Robinhood stale · from the journal",
  ok: "live from Robinhood",
};

/** One quiet line beside the book's heading: where its numbers come from, and as of when (nothing while the feed is off:
 * the book is the journal's, as it always was). Live, it is a button that reads Robinhood again. */
function LiveLine({ live, onRefresh }: { live: DeskLive | null; onRefresh?(): void }) {
  if (!live || live.state === "off") return null;
  const on = liveOn(live);
  const words = live.state === "ok" && !on ? LIVE_WORDS.unavailable : LIVE_WORDS[live.state] ?? LIVE_WORDS.unavailable;
  const at = live.as_of ? ` · as of ${clockOf(live.as_of)}` : "";
  const text = `${words}${on || live.state === "stale" ? at : ""}`;
  return on && onRefresh ? (
    <button type="button" data-testid="book-live" onClick={onRefresh} title="Read Robinhood again"
      className="ml-auto min-h-11 text-[11px] text-muted-foreground hover:text-foreground sm:min-h-0">
      {/* A phone keeps the heading on one line: "live · as of 10:04 AM" (the words stay for a screen reader). */}
      {words === LIVE_WORDS.ok ? <>live<span className="max-sm:sr-only"> from Robinhood</span>{at}</> : text}
    </button>
  ) : <span data-testid="book-live" className="ml-auto text-[11px] text-muted-foreground">{text}</span>;
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
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    return () => clearInterval(timer); // a new set of symbols starts another read; the one in flight still lands
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

const left = (expiry: string | null, day: string) => {
  if (!expiry) return null;
  const n = daysTo(expiry, day);
  return n < 0 ? "expired" : n === 0 ? "expires today" : `${n}d left`;
};

/**
 * The book: one dense row per followed open position (ticker, contract, unrealized P&L in dollars and percent, today's
 * sparkline of the underlying, where it sits between invalidation and entry, days to expiry and one state tag).
 * Selecting a row (``onSelect``) drives the centre and the copilot; its eye stops following the ticker (``onFollow``),
 * and those sit behind "N not followed" at the bottom.
 */
export function Book({ rows, sparks, selected, selectedKey = null, day, read, updating = false, live = null, earnings = null, onRefreshLive, onSelect, onFollow, children }: {
  rows: DeskThread[]; sparks: DeskSparks | null; selected: string | null; selectedKey?: string | null; day: string; read: boolean;
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
  const follow = (symbol: string, following: boolean) => {
    setFailed(null);
    onFollow(symbol, following).catch(() => setFailed(`${symbol}: not saved. Try again.`));
  };
  return (
    <section aria-label="Your book" data-testid="desk-book" className="rounded-lg border bg-card">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 px-3 pb-1.5 pt-2.5 max-sm:items-center max-sm:py-0">
        <h2 className={cn(LABEL, "shrink-0")}>
          Your book{shown.length > 0 && <> · <span className="tabular-nums">{shown.length}</span> followed</>}
        </h2>
        <LiveLine live={live} onRefresh={onRefreshLive} />
        <PricesAsOf at={staleSince(ticks, followed.map(r => r.book?.tick?.quote))} />
        {updating && <span role="status" data-testid="book-updating" className="text-[11px] text-muted-foreground">Updating…</span>}
      </div>
      {isLive && <OrdersGroup orders={live?.orders} />}
      {followed.length ? (
        <ul>
          {followed.map(row => {
            const book = row.book;
            const spark = row.symbol ? sparks?.rows[row.symbol] : undefined;
            const state = bookTag(row, day);
            // "11/14 105C": this year's expiries drop the year, so the contract fits beside its line and figures.
            const full = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
            const contract = full.replace(/\b(\d{1,2}\/\d{1,2})\/(\d{2})\b/, (date, monthDay: string, year: string) => year === day.slice(2, 4) ? monthDay : date);
            const count = book?.quantity != null ? ` ×${book.quantity.toLocaleString("en-US", { maximumFractionDigits: 4 })}` : "";
            const on = row.key === marked;
            const pnl = tickedBook(book, ticks);
            const under = tickFor(ticks, row.symbol);
            // The line's newest point follows the live price, so the row moves between the minute reads.
            const points = spark?.points.length && under && !under.stale ? [...spark.points.slice(0, -1), under.last] : spark?.points;
            return (<Fragment key={row.key}>
              <li className={cn("flex items-stretch border-t", on && "bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]")}>
                <button type="button" onClick={() => onSelect(row)} aria-pressed={on} aria-label={`${row.symbol} ${full}`}
                  className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_48px_minmax(60px,auto)] items-center gap-2 py-2 pl-3 text-left hover:bg-secondary">
                  <span className="min-w-0 overflow-hidden">
                    <span className="flex items-baseline gap-1.5">
                      <span className="text-sm font-semibold text-foreground">{row.symbol}</span>
                      <span className="min-w-0 truncate text-xs tabular-nums text-muted-foreground">{contract}{count}</span>
                    </span>
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
                  <Spark points={points} label={`${row.symbol} today`} />
                  <span data-testid="book-pnl" className={cn("whitespace-nowrap text-right text-sm tabular-nums", tone(pnl.usd), (updating || pnl.stale) && "opacity-50")}>
                    <Flash value={pnl.usd}>{pnl.usd != null ? money(pnl.usd) : row.value?.text ?? "—"}</Flash>
                    {pnl.pct != null && <span className="block text-[11px]">{signedPct(pnl.pct)}</span>}
                  </span>
                </button>
                {row.symbol && (
                  <button type="button" onClick={() => follow(row.symbol!, false)} aria-label={`Hide ${row.symbol}: not following`}
                    title="Not following: hide this ticker from the desk and every count (Show again undoes it)"
                    className="flex w-8 shrink-0 items-center justify-center text-muted-foreground/40 hover:bg-secondary hover:text-foreground">
                    <EyeOff size={13} aria-hidden />
                  </button>
                )}
              </li>
              {on && book?.option && <li className="bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]"><OptionStandingLine row={row} rows={held} fallback={sparkPrice(sparks, row.symbol)} /></li>}
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

/** "At risk now: $6,400 in 3 options · usual day $2,100", re-read with each session read (its ``as_of``); null when the
 * read fails or no long option is open. */
function useExposureLine(asOf: string | undefined): string | null {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    if (!asOf) return;
    const controller = new AbortController();
    getExposure(controller.signal).then(now => setLine(now.line)).catch(() => {
      if (!controller.signal.aborted) setLine(null); /* the line is extra */
    });
    return () => controller.abort();
  }, [asOf]);
  return line;
}

/** One quiet line under the book's lower block: the open long options' premium at risk now against a usual day, and the
 * practice goal with this week's count. Nothing when neither reads. */
export function DayFacts({ session }: { session: DeskSession | null }) {
  const practice = usePracticeLine(true);
  const exposure = useExposureLine(session?.as_of);
  if (!practice && !exposure) return null;
  return (
    <p data-testid="session-facts" className="px-1 text-xs text-muted-foreground">
      {exposure && <span data-testid="exposure-line">{exposure}</span>}
      {exposure && practice && " · "}
      {practice}
    </p>
  );
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

const SPAN: Record<DeskTimeframe, string> = { "2m": "today: 2-minute candles", "15m": "recent sessions: 15-minute candles", "1D": "the last few months: daily candles" };
const TIMEFRAME_KEY = "desk.chart.timeframe.v1";
const Key = ({ color, glyph, children }: { color: string; glyph: string; children: ReactNode }) => (
  <span><span aria-hidden style={{ color }}>{glyph}</span> {children}</span>
);

/** The chart's timeframe, kept for the tab's session so it holds its place across positions and tab switches. */
function useDeskTimeframe(): [DeskTimeframe, (next: DeskTimeframe) => void] {
  const [timeframe, setTimeframe] = useState<DeskTimeframe>("2m");
  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(TIMEFRAME_KEY);
      if (saved && (DESK_TIMEFRAMES as readonly string[]).includes(saved)) setTimeframe(saved as DeskTimeframe); // eslint-disable-line react-hooks/set-state-in-effect -- the store is read after hydration
    } catch { /* 2m */ }
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
 * holds across positions) with Open in Charts, then two tiles for a held position that its book row does not carry (the
 * stock against SPY today, time held: P&L, the distance to the stop and expiry are the row's) and, folded, what touched
 * the thread. No symbol: QQQ with the owner's fills and pings.
 */
export function CentreChart({ symbol, thread, row, sparks, actions, rows = [], earnings = null }: {
  symbol: string | null; thread: DeskThreadRef | null; row: DeskThread | null; sparks: DeskSparks | null; actions?: DeskChartActions;
  /** The desk's rows, so a held option's standing can tell a lone long option from one leg of a structure. */
  rows?: DeskThread[];
  /** Earnings tags (``useDeskEvents``): a held option's header says when a report falls inside its life. */
  earnings?: DeskEvents | null;
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
  return (
    <div className="space-y-3" data-testid="desk-chart">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-base font-semibold text-foreground">{symbol ?? "QQQ"}</span>
        <span className="min-w-0 truncate text-xs text-muted-foreground">{row ? (row.instrument && row.instrument !== row.symbol ? row.instrument : row.title) : symbol ? "today" : "market today"}</span>
      </div>
      <ReadingLine symbol={symbol ?? "QQQ"} data={reading} fallback={fallback} live={live} />
      {row?.book?.option && <OptionStanding row={row} rows={rows}
        fallback={reading?.state === "ok" && reading.reading ? { last: reading.reading.last, at: reading.reading.at } : sparkPrice(sparks, symbol)}
        levels={{ entry: reading?.levels.find(l => l.role === "entry")?.price, stop: reading?.levels.find(l => l.role === "invalidation")?.price,
          target: reading?.levels.find(l => l.role === "target")?.price }}
        earnings={symbol ? earnings?.rows[symbol]?.date ?? null : null} />}
      <PositionEarnings row={row} earnings={earnings} />
      <div className="flex items-center gap-1">
        {contract.available && <ChartViewToggle view={contract.view} onPick={contract.pick} />}
        {!onContract && <div role="group" aria-label="Timeframe" className="flex gap-1">
          {DESK_TIMEFRAMES.map(item => (
            <button key={item} type="button" aria-pressed={timeframe === item} onClick={() => pickTimeframe(item)}
              className={cn("min-h-11 min-w-11 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:min-w-0 sm:py-0.5",
                timeframe === item ? "border-foreground/60 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {item}
            </button>
          ))}
        </div>}
        <span className="ml-auto" />
        <TapeToggle open={tape} onToggle={setTape} />
        <Link href={charts} className="inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Open in Charts →</Link>
      </div>
      {tape && <DeskTape symbol={symbol ?? "QQQ"} option={!!row?.book?.option} />}
      {onContract ? <ContractChart held={held} data={contract.data!} /> : <>
      <DeskChart id={ref?.id ?? DESK_MARKET} timeframe={timeframe} refreshKey={ref?.refreshKey ?? 0} onRead={setShown} actions={actions} live={live}
        label={`${symbol ?? "QQQ"} ${SPAN[timeframe]}${ref ? " with the plan's entry and invalidation lines, your fills, and today's pings and Radar hits" : " with your fills and the phone pings sent today"}`} />
      <p aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Key color="#e9a23b" glyph="▲▼">your fills</Key>
        <Key color="#a78bfa" glyph="●">pings</Key>
        {ref && <Key color="#60a5fa" glyph="■">Radar</Key>}
      </p>
      </>}
      {book && (versus !== null || book.days_held != null) && (
        <div data-testid="desk-tiles" className="grid grid-cols-[repeat(auto-fit,minmax(104px,1fr))] gap-1.5">
          {versus !== null && <Tile label="vs SPY today" className={tone(versus)}>{`${versus > 0 ? "+" : versus < 0 ? "−" : ""}${Math.abs(versus).toFixed(1)} pts`}</Tile>}
          {book.days_held != null && <Tile label="Held">{book.days_held === 0 ? "today" : `${book.days_held}d`}</Tile>}
        </div>
      )}
      {row && !book && <p className="text-xs text-muted-foreground">{row.status.text}</p>}
      {ref?.symbol && (
        <div className="border-t pt-2">
          <button type="button" aria-expanded={timeline} onClick={() => setTimeline(open => !open)}
            className="min-h-11 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Timeline {timeline ? "▴" : "▾"}</button>
          {timeline && <div className="pt-2"><DeskTimeline thread={ref} /></div>}
        </div>
      )}
    </div>
  );
}
