"use client";

/**
 * Replay never hides real money (docs/copilot-lab.md § Paper replay): one compact line in Replay's header while a replay
 * runs, marked REAL, "3 open · +$1,420 · 1 near stop · 1 order working", the Needs-you item when one is active, and a
 * money source behind when the Data health dot would be red. A tap opens a read-only list of the real positions and
 * working orders. Everything here is what the live desk underneath already read and keeps reading (the thread list's
 * rows, the Robinhood feed's orders, the shared live prices, the one health read): it asks for nothing of its own, has
 * no action and sends nothing. A ticker he does not follow stays out of it, as it stays out of the book. When the
 * positions could not be read it says so in words with the last good read's time, never a count or "No open positions";
 * a P&L with a price no longer live is greyed, as the book greys it.
 */

import { useState } from "react";
import { bookTag, positionRows, tone } from "@/components/copilot/Cockpit";
import { useDeskHealth } from "@/components/copilot/DeskHealth";
import { Line } from "@/components/copilot/DeskOrders";
import { bookOrders, bookRead } from "@/components/copilot/DeskPhone";
import ModeMark from "@/components/copilot/ModeMark";
import { liveOn, money, type DeskLive, type DeskNeed, type DeskThread } from "@/lib/desk";
import { tickedBook, useHeldTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

export default function ReplayLiveLine({ rows, live, read, day, need, failed = false, asOf = null }: {
  /** The thread list's rows and the Robinhood feed, as the live desk holds them (every account: none is narrowed away). */
  rows: DeskThread[]; live: DeskLive | null;
  /** The book has read at least once. */
  read: boolean;
  day: string;
  /** The Needs-you strip's first item, when one is active. */
  need: DeskNeed | null;
  /** The newest read failed, or it could not read the positions: the rows held are not current. */
  failed?: boolean;
  /** When the positions last read (ISO), for "as of". */
  asOf?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const ticks = useHeldTicks(); // the prices the hidden book already asks for; no symbol of its own
  const { said } = useDeskHealth();
  const book = bookRead(rows, live, ticks, day);
  const held = positionRows(rows).filter(r => !r.hidden);
  const stale = held.some(r => tickedBook(r.book, ticks).stale); // a price in the sum is no longer live: greyed
  const working = bookOrders(rows, live).filter(o => o.working).sort((a, b) => (b.placed_at ?? 0) - (a.placed_at ?? 0));
  const unread = `Positions could not be read${asOf ? ` · as of ${clock(asOf)}` : ""}`;
  return (
    <section aria-label="Your real money, live" data-testid="replay-live" className="basis-full text-xs">
      <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)} data-testid="replay-live-line" data-failed={failed || undefined}
        title={open ? "Hide your real positions and orders" : "Your real positions and working orders, read only"}
        className="flex min-h-11 w-full min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-md border border-foreground/20 bg-background/60 px-2 py-1 text-left text-muted-foreground hover:bg-secondary sm:min-h-8">
        <ModeMark mode="real" detail={failed ? null : "live"} />
        {failed ? <span data-testid="replay-live-unread" className="text-amber-300">{unread}</span>
          : !read ? <span>Reading your book…</span> : <>
          <span className="tabular-nums text-foreground">{book.open} open</span>
          {book.pnl != null && <><span aria-hidden>·</span><span data-testid="replay-live-pnl" className={cn("tabular-nums", tone(book.pnl), stale && "opacity-50")}>{money(book.pnl)}</span></>}
          {book.flags.map(([n, one, many, risk]) => (
            <span key={one} className="contents"><span aria-hidden>·</span><span className={cn("tabular-nums", risk ? "text-rose-300" : "text-foreground")}>{n} {n === 1 ? one : many}</span></span>
          ))}
        </>}
        {need && <><span aria-hidden>·</span><span data-testid="replay-live-need" className="min-w-0 truncate font-medium text-primary">Needs you: {need.title}</span></>}
        {said.tone === "red" && <><span aria-hidden>·</span><span data-testid="replay-live-health" className="font-medium text-rose-300">{said.text}</span></>}
        <span aria-hidden className="ml-auto pl-1">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div data-testid="replay-live-list" className="mt-1 max-h-[40vh] overflow-y-auto rounded-md border border-foreground/20 bg-background px-2 py-1.5">
          <p className="pb-1 text-[11px] text-muted-foreground">Read only · nothing here is sent. Back to live to act on it.</p>
          {/* Positions and orders ride the same read: when it failed, neither is shown as current. */}
          {failed ? <p className="text-amber-300">{unread}; it reads again each minute. Positions and orders are not shown until then.</p> : <>
          {held.length ? (
            <ul aria-label="Real positions" className="flex flex-col">
              {held.map(row => {
                const pnl = tickedBook(row.book, ticks);
                const tag = bookTag(row, day);
                const name = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
                const count = row.book?.quantity != null ? ` ×${row.book.quantity.toLocaleString("en-US", { maximumFractionDigits: 4 })}` : "";
                return (
                  <li key={row.key} data-testid="replay-live-position" className="flex flex-wrap items-baseline gap-x-2 border-t py-1 first:border-t-0">
                    <span className="font-semibold text-foreground">{row.symbol}</span>
                    <span className="min-w-0 flex-1 truncate tabular-nums">{name}{count}</span>
                    {tag && tag.label !== "On plan" && <span className={cn("rounded border px-1 text-[10px]", tag.className)}>{tag.label}</span>}
                    <span className={cn("tabular-nums", tone(pnl.usd), pnl.stale && "opacity-50")}>{pnl.usd == null ? "—" : money(pnl.usd)}</span>
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-muted-foreground">{read ? "No open positions." : "Reading your book…"}</p>}
          <h3 className="mt-1.5 border-t pt-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Working orders</h3>
          {!liveOn(live) ? <p data-testid="replay-live-orders-off" className="text-muted-foreground">Orders come from the Robinhood feed, which is not live now.</p>
            : working.length ? (
              <ul aria-label="Working orders" className="flex flex-col">
                {working.map((o, i) => <li key={`${o.contract}:${o.action}:${o.placed_at}:${i}`} data-testid="replay-live-order" className="border-t py-1 first:border-t-0"><Line order={o} short={false} withContract /></li>)}
              </ul>
            ) : <p className="text-muted-foreground">No working orders.</p>}
          </>}
        </div>
      )}
    </section>
  );
}
