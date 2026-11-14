"use client";

/**
 * Robinhood's orders on the book (docs/robinhood-order-fills.md § On the desk): a working order's line ("Working: Sell
 * 2 @ 4.50 · 1/2 filled · Roth IRA · 9m") and a fresh fill's ("Filled: Buy 2 @ 1.93, 10:42", marked
 * provisional until its email arrives and matches). Read only: there is no button here that places, changes or cancels
 * an order, and none may be added.
 */

import { NoteButton, NoteLines, type DeskNotesState } from "@/components/copilot/DeskNotes";
import type { DeskOrder } from "@/lib/desk";
import { fillKey } from "@/lib/deskNotes";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
// "10:42": trading hours need no AM/PM, and the line stays short in the book's narrow column.
const clock = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" }).replace(/\s?[AP]M$/, "");
const count = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 4 });
const price = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** "now", "9m", "2h", "3d" since the order was placed. */
export function age(placedAt: number | null, now = Date.now() / 1000): string | null {
  if (placedAt == null) return null;
  const minutes = Math.max(0, Math.floor((now - placedAt) / 60));
  return minutes < 1 ? "now" : minutes < 60 ? `${minutes}m` : minutes < 24 * 60 ? `${Math.floor(minutes / 60)}h` : `${Math.floor(minutes / 1440)}d`;
}

/** The short side word: an option's "Sell to close" reads "Sell" on its own contract's row (the row says what it is). */
const verb = (o: DeskOrder, short: boolean) => short ? o.action.split(" ")[0] : o.action;

export function orderText(o: DeskOrder, short: boolean, now?: number): string {
  if (!o.working) return `Filled: ${verb(o, short)} ${count(o.filled)}${o.avg != null ? ` @ ${price(o.avg)}` : ""}${o.filled_at ? `, ${clock(o.filled_at)}` : ""}`;
  // A limit is the usual order: its price alone ("@ 4.50"); a stop, a market order and a roll's net price say so.
  const terms = o.price_kind === "market" ? "market" : o.limit == null ? o.price_kind
    : o.price_kind === "limit" ? `@ ${price(o.limit)}` : `${o.price_kind} ${price(o.limit)}`; // "stop 4.20", a roll's "net 0.50"
  const filled = o.filled > 0 ? `${count(o.filled)}${o.quantity != null ? `/${count(o.quantity)}` : ""} filled` : null;
  const placed = age(o.placed_at, now);
  return `Working: ${[`${verb(o, short)}${o.quantity != null ? ` ${count(o.quantity)}` : ""} ${terms}`, filled, o.account.label, placed]
    .filter(Boolean).join(" · ")}`;
}

const MARK: Record<string, { label: string; title: string; className: string }> = {
  provisional: { label: "provisional", title: "From Robinhood's order history; the journal has it once the fill email arrives and matches",
    className: "border-amber-300/40 text-amber-300" },
  differs: { label: "email differs", title: "The fill email does not agree with Robinhood's order: see Fills → Robinhood order history",
    className: "border-rose-300/40 text-rose-300" },
  roll: { label: "roll", title: "A two-leg order: the journal takes it from its email", className: "" },
  recurring: { label: "recurring · no email", title: "A recurring buy: Robinhood sends no email for it, and the journal does not take it from the order history yet",
    className: "border-amber-300/40 text-amber-300" },
};

function Line({ order, short, withContract }: { order: DeskOrder; short: boolean; withContract?: boolean }) {
  const mark = order.pairing ? MARK[order.pairing] : undefined;
  return (
    <span data-testid="book-order" data-working={order.working ? "true" : "false"}
      title={`${order.contract} · ${order.account.label} ${order.account.masked}`}
      className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-[11px] tabular-nums">
      {withContract && <span className="font-medium text-foreground">{order.contract}</span>}
      <span className={cn("min-w-0", order.working ? "text-sky-300" : "text-foreground/80")}>{orderText(order, short)}</span>
      {mark && <span data-testid="book-order-mark" title={mark.title} className={cn("rounded border px-1", mark.className)}>{mark.label}</span>}
    </span>
  );
}

/** The orders on one book row, under its tags. */
export function OrderLines({ orders }: { orders?: DeskOrder[] }) {
  if (!orders?.length) return null;
  return <span className="mt-0.5 flex flex-col gap-0.5">{orders.map((o, i) => <Line key={`${o.action}:${o.placed_at}:${i}`} order={o} short />)}</span>;
}

/** Orders with no followed row to sit on (no position yet, or the fill closed it), at the top of the book. Nothing at
 * all when there are none: no empty heading. */
export function OrdersGroup({ orders, notes }: { orders?: DeskOrder[]; notes?: DeskNotesState }) {
  if (!orders?.length) return null;
  return (
    <div data-testid="book-orders" className="border-t px-3 py-1.5">
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Orders</h3>
      <ul className="mt-0.5 flex flex-col gap-0.5">
        {orders.map((o, i) => {
          const id = `fill:${fillKey(o)}:${o.filled_at}:${i}`;
          // A fresh fill takes a note once the journal has its trade ("why I left"); a working order takes none. Two
          // fills of one trade share its notes: they show under the first.
          const trade = !o.working && notes ? notes.data.fills[fillKey(o)] ?? null : null;
          const first = trade !== null && orders.findIndex(other => !other.working && notes?.data.fills[fillKey(other)] === trade) === i;
          return (
            <li key={`${o.contract}:${o.action}:${o.placed_at}:${i}`}>
              <span className="flex min-w-0 items-center gap-1">
                <span className="min-w-0 flex-1"><Line order={o} short={false} withContract /></span>
                {trade && notes && <NoteButton notes={notes} id={id} label="this fill" className="h-6 w-6 self-start rounded" />}
              </span>
              {notes && <NoteLines notes={notes} id={id} trade={first ? trade : null} target={trade ? { trade_id: trade } : null} label="this fill"
                className="mb-1 mt-0.5" />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
