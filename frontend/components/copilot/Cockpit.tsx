"use client";

/**
 * The desk's cockpit pieces (docs/copilot-lab.md § The desk): the top bar's day P&L, the Needs-you strip, the book of
 * followed positions with "Since you looked" under it, and the centre's chart with its tiles. CopilotLab lays them out
 * and owns every action; these only show what the desk's reads say. Facts and counts only: nothing here tells the owner
 * to buy, sell or hold, sizes anything or sends an order.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { EyeOff, Ticket } from "lucide-react";
import { openTicket, type TicketPlan } from "@/components/copilot/DeskTicket";
import { NotFollowed } from "@/components/copilot/SessionTape";
import { usePracticeLine } from "@/components/copilot/ReviewMyWeek";
import { getExposure } from "@/lib/copilot";
import { DeskTimeline, ThreadChart } from "@/components/copilot/Inspector";
import {
  bookFacts, daysTo, deskSymbolThread, getDeskSparks, money, readLook, saveLook, signedPct, sinceLines,
  type DeskBookState, type DeskLook, type DeskNeed, type DeskSession, type DeskSparks, type DeskThread, type DeskThreadRef,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const ET = "America/New_York";
const REFRESH_MS = 60_000;
const tone = (value: number | null | undefined) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-300" : "text-rose-300";
const clockOf = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });

/** The open positions' rows (the thread list's ``trade:`` rows), followed first. */
export const positionRows = (rows: DeskThread[]) => rows.filter(r => r.key.startsWith("trade:"));

// ------------------------------------------------------------------------------------------------ top bar

/** "Realized today +$120 · Open +$355": the trades closed today (the session read) and every open position's
 * unrealized P&L now (the thread list's read, followed or not: it is the account's money). Nothing until read. */
export function DayPnl({ session, rows, read }: { session: DeskSession | null; rows: DeskThread[]; read: boolean }) {
  const open = positionRows(rows).flatMap(r => r.book?.usd != null ? [r.book.usd] : []);
  const total = open.reduce((a, b) => a + b, 0);
  const realized = session?.realized_today ?? null;
  if (realized === null && !(read && open.length)) return null;
  return (
    <span data-testid="desk-pnl" className="flex items-baseline gap-3 whitespace-nowrap text-xs">
      {realized !== null && <span><span className="text-muted-foreground">Realized today </span><span className={cn("tabular-nums", tone(realized))}>{money(realized)}</span></span>}
      {read && open.length > 0 && <span><span className="text-muted-foreground">Open </span><span className={cn("tabular-nums", tone(total))}>{money(total)}</span></span>}
    </span>
  );
}

// ------------------------------------------------------------------------------------------------ the strip

type StripAction = { label: string; run(): void; primary?: boolean };

/**
 * The Needs-you strip: one card for the most urgent item (``deskNeeds``' order), with its own answers and "+N more"
 * opening the rest. ``actions`` gives each item's buttons; Seen drops the item for today in this browser. Nothing when
 * nothing waits.
 */
export function NeedsStrip({ needs, seen, actions, onSeen }: {
  needs: DeskNeed[]; seen: readonly string[]; actions(need: DeskNeed): StripAction[]; onSeen(need: DeskNeed): void;
}) {
  const [more, setMore] = useState(false);
  const first = needs.find(n => !seen.includes(n.key));
  if (!first) return null;
  const rest = needs.filter(n => n !== first);
  const buttons = actions(first);
  return (
    <section aria-label="Needs you" data-testid="needs-you" className="rounded-lg border border-primary/45 bg-primary/[0.07] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className={cn(LABEL, "text-primary")}>Needs you</span>
        <div className="min-w-0 flex-1 basis-60">
          <p data-testid="needs-you-title" className="text-sm font-semibold text-foreground">{first.title}</p>
          {first.detail && <p className="text-xs text-muted-foreground">{first.detail}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {buttons.map(b => (
            <button key={b.label} type="button" onClick={b.run}
              className={cn("inline-flex min-h-11 items-center rounded-md border px-3 text-xs sm:min-h-8",
                b.primary ? "border-primary bg-primary font-semibold text-primary-foreground hover:bg-primary/90" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
              {b.label}
            </button>
          ))}
          <button type="button" onClick={() => onSeen(first)} title="Out of this strip for today, in this browser"
            className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Seen</button>
          {rest.length > 0 && (
            <button type="button" aria-expanded={more} onClick={() => setMore(open => !open)}
              className="min-h-11 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">+{rest.length} more {more ? "▴" : "▾"}</button>
          )}
        </div>
      </div>
      {more && rest.length > 0 && (
        <ul aria-label="More waiting" className="mt-2 space-y-1 border-t border-primary/20 pt-2">
          {rest.map(need => {
            const [open] = actions(need);
            return (
              <li key={need.key}>
                <button type="button" onClick={open?.run} className="flex min-h-11 w-full items-baseline gap-2 rounded px-1 text-left text-xs hover:bg-secondary sm:min-h-8">
                  <span className="min-w-0 flex-1 truncate text-foreground">{need.title}</span>
                  {seen.includes(need.key) && <span className="shrink-0 text-muted-foreground">seen</span>}
                  {open && <span className="shrink-0 text-muted-foreground">{open.label} →</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ the book

/** Each symbol's day so far (``GET /copilot/desk/sparks``, at most ``SPARKS`` symbols in the order given), read once a
 * minute while the page shows; nothing when the read fails. */
const SPARKS = 12;
export function useSparks(symbols: string[]): DeskSparks | null {
  const [data, setData] = useState<DeskSparks | null>(null);
  const key = [...new Set(symbols)].slice(0, SPARKS).sort().join(",");
  useEffect(() => {
    if (!key) return;
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      getDeskSparks(key.split(","), controller.signal).then(setData).catch(() => { /* the lines are extra */ });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [key]);
  return data;
}

function Spark({ points, label }: { points: number[] | undefined; label: string }) {
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

const STATE: Record<DeskBookState, { label: string; className: string }> = {
  on_plan: { label: "On plan", className: "text-muted-foreground" },
  giving_back: { label: "Giving back", className: "border-primary/40 text-primary" },
  near_stop: { label: "Near stop", className: "border-rose-300/40 text-rose-300" },
  no_plan: { label: "No plan", className: "border-rose-300/40 text-rose-300" },
};

/** Where the underlying sits between the plan's invalidation (left) and entry (the tick), from the row's track. */
function Track({ track }: { track: NonNullable<DeskThread["book"]>["track"] }) {
  if (!track) return <p className="mt-1 text-[11px] text-muted-foreground">no plan lines</p>;
  return (
    <div role="img" aria-label={`Between invalidation and entry: ${track.last.toFixed(0)} of ${track.entry.toFixed(0)}`} className="relative mb-1 mt-2 h-[3px] rounded bg-secondary">
      <i className="absolute -top-[3px] left-0 h-[9px] w-0.5 bg-muted-foreground/60" />
      <i className="absolute -top-[3px] h-[9px] w-0.5 bg-muted-foreground/60" style={{ left: `${track.entry}%` }} />
      <u className="absolute -top-[3px] -ml-1 h-[9px] w-[9px] rounded-full bg-foreground" style={{ left: `${track.last}%` }} />
    </div>
  );
}

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
export function Book({ rows, sparks, selected, selectedKey = null, day, read, onSelect, onFollow, tickets = null, children }: {
  rows: DeskThread[]; sparks: DeskSparks | null; selected: string | null; selectedKey?: string | null; day: string; read: boolean;
  onSelect(row: DeskThread): void; onFollow(symbol: string, following: boolean): Promise<void>;
  /** Saved plans armed and not yet entered: a row whose ticker has one opens its ticket (the newest). */
  tickets?: TicketPlan[] | null; children?: ReactNode;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const held = positionRows(rows);
  const followed = held.filter(r => !r.hidden);
  // One row is marked: the one tapped, else the first on the centre's ticker (two contracts can share a ticker).
  const marked = followed.find(r => r.key === selectedKey && r.symbol === selected)?.key ?? followed.find(r => r.symbol === selected)?.key;
  const follow = (symbol: string, following: boolean) => {
    setFailed(null);
    onFollow(symbol, following).catch(() => setFailed(`${symbol}: not saved. Try again.`));
  };
  return (
    <section aria-label="Your book" data-testid="desk-book" className="rounded-lg border bg-card">
      <h2 className={cn(LABEL, "px-3 pb-1.5 pt-2.5")}>
        Your book{followed.length > 0 && <> · <span className="tabular-nums">{followed.length}</span> followed</>}
      </h2>
      {followed.length ? (
        <ul>
          {followed.map(row => {
            const book = row.book;
            const spark = row.symbol ? sparks?.rows[row.symbol] : undefined;
            const state = book ? STATE[book.state] : null;
            const contract = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
            const on = row.key === marked;
            return (
              <li key={row.key} className={cn("flex items-stretch border-t", on && "bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]")}>
                <button type="button" onClick={() => onSelect(row)} aria-pressed={on} aria-label={`${row.symbol} ${contract}`}
                  className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_48px_60px] items-center gap-2 py-2 pl-3 text-left hover:bg-secondary">
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-1.5">
                      <span className="text-sm font-semibold text-foreground">{row.symbol}</span>
                      <span className="min-w-0 truncate text-xs tabular-nums text-muted-foreground">{contract}</span>
                    </span>
                    {book ? <Track track={book.track} /> : <span className="block truncate text-xs text-muted-foreground">{row.status.text}</span>}
                    <span className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-muted-foreground">
                      {book?.stop_pct != null && <span className="tabular-nums">{Math.abs(book.stop_pct).toFixed(1)}% to stop</span>}
                      {book && left(book.expiry, day) && <span className="tabular-nums">{left(book.expiry, day)}</span>}
                      {state && <span data-testid="book-state" className={cn("rounded border px-1", state.className)}>{state.label}</span>}
                    </span>
                  </span>
                  <Spark points={spark?.points} label={`${row.symbol} today`} />
                  <span className={cn("text-right text-sm tabular-nums", tone(book?.usd))}>
                    {book?.usd != null ? money(book.usd) : row.value?.text ?? "—"}
                    {book?.pct != null && <span className="block text-[11px]">{signedPct(book.pct)}</span>}
                  </span>
                </button>
                {(() => {
                  const plan = tickets?.find(t => t.symbol === row.symbol);
                  return plan && (
                    <button type="button" onClick={() => openTicket(plan.investigation_id)} aria-label={`Open the ticket for your saved ${row.symbol} plan`}
                      title="Open the ticket for your saved plan (copies; never sends)"
                      className="flex shrink-0 items-center px-1.5 text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground">
                      <Ticket size={13} aria-hidden />
                    </button>
                  );
                })()}
                {row.symbol && (
                  <button type="button" onClick={() => follow(row.symbol!, false)} aria-label={`Hide ${row.symbol}: not following`}
                    title="Not following: hide this ticker from the desk and every count (Show again undoes it)"
                    className="flex w-8 shrink-0 items-center justify-center text-muted-foreground/40 hover:bg-secondary hover:text-foreground">
                    <EyeOff size={13} aria-hidden />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : <p className="border-t px-3 py-2.5 text-xs text-muted-foreground">{!read ? "Reading positions…" : held.length ? "Only positions you don't follow are open." : "No open positions."}</p>}
      <div className="px-1.5 pb-1"><NotFollowed rows={held.filter(r => r.hidden)} open={onSelect} onFollow={follow} /></div>
      {failed && <p role="alert" className="px-3 pb-2 text-xs text-primary">{failed}</p>}
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
    const held = positionRows(rows).filter(r => r.book && r.symbol && !r.hidden);
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

const expiryWords = (iso: string, day: string) => {
  const n = daysTo(iso, day);
  const date = new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  return `${date} · ${n <= 0 ? (n === 0 ? "today" : "past") : `${n}d`}`;
};

/**
 * The centre's Chart: the selected symbol's picture (the desk's server-drawn chart with the plan's entry and invalidation
 * lines, the owner's fills and today's pings and Radar hits, on 2m, 15m or 1D) with Open in Charts, then a row of
 * tiles for a held position (open P&L, distance to the invalidation, the stock against SPY today, time held, expiry)
 * and, folded, what touched the thread. No symbol: QQQ's day with the owner's fills and pings.
 */
export function CentreChart({ symbol, thread, row, sparks, day }: {
  symbol: string | null; thread: DeskThreadRef | null; row: DeskThread | null; sparks: DeskSparks | null; day: string;
}) {
  const ref = useMemo(() => thread ?? (symbol ? deskSymbolThread(symbol) : null), [thread, symbol]);
  const [timeline, setTimeline] = useState(false);
  const book = row?.book;
  const change = symbol ? sparks?.rows[symbol]?.change_pct ?? null : null;
  const spy = sparks?.spy_change_pct ?? null;
  const versus = change !== null && spy !== null ? change - spy : null;
  const charts = `/charts?symbol=${encodeURIComponent(symbol ?? "QQQ")}`;
  return (
    <div className="space-y-3" data-testid="desk-chart">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-base font-semibold text-foreground">{symbol ?? "QQQ"}</span>
        {change !== null && <span className={cn("text-sm tabular-nums", tone(change))}>{signedPct(change, 2)}</span>}
        <span className="min-w-0 truncate text-xs text-muted-foreground">{row ? row.title : symbol ? "today" : "market today"}</span>
      </div>
      {ref ? <ThreadChart key={ref.id} thread={ref} extra={<Link href={charts} className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>} />
        : <ThreadChart key="market" market extra={<Link href={charts} className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>} />}
      {book && (
        <div data-testid="desk-tiles" className="grid grid-cols-[repeat(auto-fit,minmax(104px,1fr))] gap-1.5">
          <Tile label="Open P&L" className={tone(book.usd)}>{book.usd != null ? money(book.usd) : "—"}{book.pct != null && <span className="ml-1 text-xs">{signedPct(book.pct)}</span>}</Tile>
          <Tile label="To your stop">{book.stop_pct != null ? `${Math.abs(book.stop_pct).toFixed(1)}%` : "none saved"}</Tile>
          {versus !== null && <Tile label="vs SPY today" className={tone(versus)}>{`${versus > 0 ? "+" : versus < 0 ? "−" : ""}${Math.abs(versus).toFixed(1)} pts`}</Tile>}
          {book.days_held != null && <Tile label="Held">{book.days_held === 0 ? "today" : `${book.days_held}d`}</Tile>}
          {book.expiry && <Tile label="Expires">{expiryWords(book.expiry, day)}</Tile>}
        </div>
      )}
      {row && !book && bookFacts(row) === null && <p className="text-xs text-muted-foreground">{row.status.text}</p>}
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
