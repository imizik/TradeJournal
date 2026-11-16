"use client";

/**
 * The phone desk's own pieces (docs/copilot-lab.md § The desk, Phone): the value block at the top of Positions, the
 * Orders view and the Chain view's ticker chips. Each shows what the desk has already read (the thread list's rows, the
 * Robinhood feed's accounts and orders, the shared live prices): nothing here reads anything of its own, places,
 * changes or cancels an order, or tells the owner to buy, sell or hold.
 */

import { useState, useSyncExternalStore, type ReactNode } from "react";
import { LABEL, LIVE_WORDS, bookTag, positionRows, tone } from "@/components/copilot/Cockpit";
import { tickedAccount } from "@/components/copilot/DeskAccounts";
import { Line } from "@/components/copilot/DeskOrders";
import { DeskValueLine } from "@/components/copilot/DeskValueLine";
import ModeMark from "@/components/copilot/ModeMark";
import { liveOn, money, signedPct, type DeskLive, type DeskOrder, type DeskThread } from "@/lib/desk";
import { tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const whole = (value: number) => `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const short = (value: number) => `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`;
const or = (value: number | null | undefined, show: (v: number) => string) => value == null ? "—" : show(value);

const PHONE = "(max-width: 767px)";
const subscribePhone = (listener: () => void) => {
  const query = window.matchMedia(PHONE);
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
};
/** Below 768 px (CopilotLab.module.css's phone): the phone's own pieces render only then. False on the server. */
export const usePhone = () => useSyncExternalStore(subscribePhone, () => window.matchMedia(PHONE).matches, () => false);

/** Every Robinhood order the book shows: the ones on followed rows and the Orders group's (none while not live). */
export function bookOrders(rows: DeskThread[], live: DeskLive | null): DeskOrder[] {
  if (!liveOn(live)) return [];
  return [...positionRows(rows).filter(r => !r.hidden).flatMap(r => r.book?.orders ?? []), ...(live?.orders ?? [])];
}

/** "3 open · +$1,420 · 1 near stop · 1 order working": the book's own rows and tags, counted. The P&L is the followed
 * rows' known figures at the live price; a row with none is left out of the sum, never counted as zero. */
export function bookRead(rows: DeskThread[], live: DeskLive | null, ticks: ReturnType<typeof useDeskTicks>, day: string) {
  const open = positionRows(rows).filter(r => !r.hidden);
  const pnl = open.map(r => tickedBook(r.book, ticks)).flatMap(p => p.usd != null ? [p.usd] : []);
  const tags = open.map(r => bookTag(r, day)?.label);
  const count = (label: string) => tags.filter(t => t === label).length;
  const working = bookOrders(rows, live).filter(o => o.working).length;
  return {
    open: open.length,
    pnl: pnl.length ? Math.round(pnl.reduce((a, b) => a + b, 0) * 100) / 100 : null,
    flags: [
      [count("Past stop"), "past stop", "past stop", true],
      [count("Near stop"), "near stop", "near stop", true],
      [count("Giving back"), "giving back", "giving back", false],
      [count("Expires today"), "expires today", "expire today", false],
      [working, "order working", "orders working", false],
    ].filter(([n]) => (n as number) > 0) as [number, string, string, boolean][],
  };
}

/**
 * The value block at the top of a phone's Positions: REAL and the account (or "2 accounts") with the feed's time, the
 * total value large with today's change under it, and one line of how the book is doing. A tap on the value opens each
 * account as a row (options, cash, buying power, open P&L); a tap on an account narrows the book to it, as the top
 * bar's account line does wider. Not live, it says so in grey with its time and shows no money, never a zero. ``aside``
 * (the desk's mode switch) sits at the right of the total, where it takes no height of its own.
 */
export function PhoneValue({ live, rows, booked, active, onPick, day, realized, aside = null }: {
  /** The feed (null until this mount's read) and every row: the accounts' figures move with all their positions. */
  live: DeskLive | null; rows: DeskThread[];
  /** The book as shown (narrowed to the picked account): the one-line read counts these. */
  booked: { rows: DeskThread[]; live: DeskLive | null };
  active: string | null; onPick(masked: string | null): void; day: string;
  /** Realized today (the session read's), shown beside today's change when a trade closed today. */
  realized?: number | null;
  aside?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ticks = useDeskTicks(positionRows(rows).map(r => r.book?.tick?.quote));
  const read = bookRead(booked.rows, booked.live, ticks, day);
  const isLive = liveOn(live) && !!live?.accounts?.length;
  const accounts = isLive ? live!.accounts!.filter(a => !active || a.masked === active) : [];
  const figures = accounts.map(a => tickedAccount(a, rows, ticks));
  const sum = (values: (number | null)[]) => values.length && values.every(v => v != null) ? values.reduce<number>((a, b) => a + b!, 0) : null;
  const total = sum(figures.map(f => f.total));
  const change = sum(figures.map(f => f.change));
  const start = total != null && change != null ? total - change : null;
  const pct = change != null && start != null && start > 0 ? 100 * change / start : null;
  const stale = figures.some(f => f.stale);
  const one = accounts.length === 1 ? accounts[0] : null;
  const who = one ? `${one.label} ${one.masked}` : isLive ? `${accounts.length} accounts` : null;
  // Not live: one grey line with its time when it has one (as the top bar's account line says it), never money.
  const quiet = !live || live.state === "off" ? null : isLive ? null
    : live.state === "stale" && live.as_of ? `${LIVE_WORDS.stale} · as of ${clock(live.as_of)}`
      : live.state === "ok" ? LIVE_WORDS.unavailable : LIVE_WORDS[live.state] ?? LIVE_WORDS.unavailable;
  return (
    <section aria-label="Account value" data-testid="desk-value" className="rounded-lg border bg-card px-3 pb-2 pt-2.5">
      <p className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
        <ModeMark mode="real" />
        {who && <span data-testid="value-who" className="min-w-0 truncate tabular-nums">{who}</span>}
        {isLive && live?.as_of && <span className="ml-auto shrink-0 tabular-nums">live · {clock(live.as_of)}</span>}
      </p>
      {isLive ? (
        // Wraps: the mode switch (aside) moves under the total when both cannot fit on one line, never over it.
        <div className="mt-1 flex flex-wrap items-center justify-end gap-2">
        <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)} data-testid="value-open"
          title={open ? "Hide each account's figures" : "Each account: options, cash, buying power"}
          className="flex min-h-11 min-w-0 flex-auto flex-col items-start rounded-md text-left hover:bg-secondary/60">
          <span data-testid="value-total" className={cn("text-[28px] font-semibold leading-8 tabular-nums tracking-tight text-foreground", stale && "opacity-50")}>
            {or(total, whole)}<span aria-hidden className="ml-1.5 align-middle text-xs font-normal text-muted-foreground">{open ? "▴" : "▾"}</span>
          </span>
          <span className="flex flex-wrap items-baseline gap-x-2 text-xs">
            {/* Today's change only when every position in it had yesterday's close: never a guessed zero. */}
            <span data-testid="value-today" className={cn("tabular-nums", tone(change), stale && "opacity-50")}>
              {change == null ? "—" : money(change)}{pct != null && ` ${signedPct(pct, 1)}`}
            </span>
            <span className="text-muted-foreground">today</span>
          </span>
        </button>
        {aside}
        </div>
      ) : <>
        {quiet && <p data-testid="value-off" className="mt-1 text-xs text-muted-foreground">{quiet}</p>}
        {aside && <div className="mt-1.5 flex">{aside}</div>}
      </>}
      {/* The day's account value line (kept while the feed is stale or signed out), as the top bar has it wider. */}
      {live && live.state !== "off" && <div className="-ml-1 mt-0.5"><DeskValueLine line={live.day_line} active={active} /></div>}
      {/* Realized today (the journal's closed trades), live or not. */}
      {realized ? <p data-testid="value-realized" className="text-xs text-muted-foreground">Realized today <span className={cn("tabular-nums", tone(realized))}>{money(realized)}</span></p> : null}
      {/* How they are doing, in one line: the book's own rows and tags. */}
      <p data-testid="value-read" className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5 text-xs text-muted-foreground">
        <span className="tabular-nums text-foreground">{read.open} open</span>
        {read.pnl != null && <><span aria-hidden>·</span><span className={cn("tabular-nums", tone(read.pnl))}>{money(read.pnl)}</span></>}
        {read.flags.map(([n, oneWord, many, risk]) => (
          <span key={oneWord} className="contents"><span aria-hidden>·</span><span className={cn("tabular-nums", risk ? "text-rose-300" : "text-foreground")}>{n} {n === 1 ? oneWord : many}</span></span>
        ))}
      </p>
      {open && isLive && (
        <ul aria-label="Accounts" data-testid="value-accounts" className="mt-2 border-t">
          {live!.accounts!.map(a => {
            const t = tickedAccount(a, rows, ticks);
            const on = active === a.masked;
            return (
              <li key={a.masked} className="border-b last:border-b-0">
                <button type="button" aria-pressed={on} onClick={() => onPick(on ? null : a.masked)} data-testid="value-account"
                  title={on ? "Show every account's positions" : `Show only ${a.label}'s positions in the book`}
                  className={cn("flex min-h-11 w-full flex-col gap-0.5 px-1 py-1.5 text-left text-xs hover:bg-secondary", on && "bg-secondary")}>
                  <span className="flex w-full items-baseline gap-1.5">
                    <span className="font-medium text-foreground">{a.label}</span>
                    <span className="tabular-nums text-muted-foreground">{a.masked}</span>
                    <span className={cn("ml-auto tabular-nums text-foreground", t.stale && "opacity-50")}>{or(t.total, whole)}</span>
                    <span className={cn("tabular-nums", tone(t.change), t.stale && "opacity-50")}>{t.change == null ? "—" : money(t.change)}{t.pct != null && ` ${signedPct(t.pct, 1)}`}</span>
                  </span>
                  <span className="flex flex-wrap gap-x-2 tabular-nums text-[11px] text-muted-foreground">
                    <span>options {or(a.options_value, short)}</span><span>cash {or(a.cash, short)}</span><span>buying power {or(a.buying_power, short)}</span>
                    <span>open <span className={cn(tone(t.open), t.stale && "opacity-50")}>{t.open == null ? "—" : money(t.open)}</span></span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The phone's Orders: Robinhood's working orders first (newest first), then today's fills (newest first), each with its
 * contract. The book's own lines, read only: nothing here places, changes or cancels an order. */
export function PhoneOrders({ rows, live }: { rows: DeskThread[]; live: DeskLive | null }) {
  const all = bookOrders(rows, live);
  const working = all.filter(o => o.working).sort((a, b) => (b.placed_at ?? 0) - (a.placed_at ?? 0));
  const filled = all.filter(o => !o.working).sort((a, b) => (b.filled_at ?? 0) - (a.filled_at ?? 0));
  const notLive = !liveOn(live);
  const words = !live || live.state === "off" ? "Orders come from the Robinhood feed, which is off." : live.state === "stale" && live.as_of
    ? `${LIVE_WORDS.stale} · as of ${clock(live.as_of)}: no orders shown.` : `${live.state === "ok" ? LIVE_WORDS.unavailable : LIVE_WORDS[live.state] ?? LIVE_WORDS.unavailable}: no orders shown.`;
  const group = (title: string, orders: DeskOrder[], testid: string) => (
    <div data-testid={testid} className="border-t px-3 py-2">
      <h3 className={LABEL}>{title}{orders.length > 0 && <> · <span className="tabular-nums">{orders.length}</span></>}</h3>
      {orders.length ? (
        <ul className="mt-1 flex flex-col">
          {orders.map((o, i) => <li key={`${o.contract}:${o.action}:${o.placed_at}:${i}`} className="border-t py-1.5 first:border-t-0"><Line order={o} short={false} withContract /></li>)}
        </ul>
      ) : <p className="mt-1 text-xs text-muted-foreground">{title === "Working" ? "No working orders." : "No fills today."}</p>}
    </div>
  );
  return (
    <section aria-label="Orders" data-testid="phone-orders" className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 px-3 pb-1.5 pt-2.5">
        <h2 className={LABEL}>Orders</h2>
        <ModeMark mode="real" />
        <span className="ml-auto text-[11px] text-muted-foreground">read only · place them in Robinhood</span>
      </div>
      {notLive ? <p data-testid="phone-orders-quiet" className="border-t px-3 py-2.5 text-xs text-muted-foreground">{words}</p> : <>
        {group("Working", working, "phone-orders-working")}
        {group("Filled today", filled, "phone-orders-filled")}
      </>}
    </section>
  );
}

/** The Chain view's ticker chips: the book's tickers, then the watched names (none he set to Not following). A tap opens
 * that ticker's chain in place. */
export function ChainPicker({ held, watched, selected, onPick }: { held: string[]; watched: string[]; selected: string | null; onPick(symbol: string): void }) {
  const names = [...held, ...watched.filter(s => !held.includes(s))];
  if (!names.length) return null;
  return (
    <div role="group" aria-label="Chain for" data-testid="chain-picker"
      className="flex gap-1.5 overflow-x-auto px-3 pb-1 pt-2.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {names.map(symbol => (
        <button key={symbol} type="button" aria-pressed={symbol === selected} onClick={() => onPick(symbol)} data-testid="chain-chip"
          data-held={held.includes(symbol) || undefined}
          className={cn("inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full border px-3 text-sm tabular-nums",
            symbol === selected ? "border-foreground/60 bg-secondary font-semibold text-foreground" : held.includes(symbol) ? "text-foreground" : "text-muted-foreground")}>
          {symbol}
        </button>
      ))}
    </div>
  );
}
