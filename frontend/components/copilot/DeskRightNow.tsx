"use client";

/**
 * Right now (docs/copilot-lab.md § The desk, Right now): the copilot's column before a conversation has a word in it.
 * Instead of an empty column with a hint, each open position that needs a look, most urgent first, in one line of what
 * is true now (past its cut line or stop, near its stop, expiring today or tomorrow, giving back) and one question to
 * ask about it. The line opens the position on the desk; the button asks the copilot. With nothing needing him, one
 * quiet line says so; a cut line with no price yet is never called clear. It reads nothing of its own: the thread list's rows and the shared live prices, as the book does.
 * Nothing here tells him to buy, sell or hold.
 */

import { needRank, overCut, pastCut, positionRows, rowNow } from "@/components/copilot/Cockpit";
import { daysTo, type DeskThread } from "@/lib/desk";
import { closable } from "@/lib/deskPosition";
import { useDeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

const premium = (value: number) => `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type Item = { row: DeskThread; rank: number; risk: boolean; what: string; ask: string; button: string };

/** What is true now about one position, in words, and the question it raises; null when nothing about it needs a look. */
export function rightNowItem(row: DeskThread, day: string, ticks: ReturnType<typeof useDeskTicks>): Item | null {
  const book = row.book;
  if (!book) return null;
  const contract = row.title;
  const option = row.instrument !== "stock" && !!book.expiry;
  const left = option ? daysTo(book.expiry!, day) : null;
  const expiring = left === 0 ? "expires today" : left === 1 ? "expires tomorrow" : null;
  const now = rowNow(book, ticks).price;
  const parts: string[] = [];
  let risk = false;
  let ask: string;
  let button = "Ask";
  if (pastCut(book, ticks)) {
    risk = true;
    parts.push(`past cut ${premium(book.cut_line! / 100)}${now != null ? ` · now ${premium(now)}` : ""}`);
    ask = `${contract} is past my cut line ${premium(book.cut_line! / 100)}${now != null ? ` at ${premium(now)}` : ""}. Cut or hold?`;
    button = "Cut or hold?";
  } else if (book.state === "past_stop") {
    risk = true;
    parts.push("past its stop");
    ask = `${contract} is past its plan's stop. Cut or hold?`;
    button = "Cut or hold?";
  } else if (book.state === "near_stop") {
    risk = true;
    parts.push(book.stop_pct != null ? `${Math.abs(book.stop_pct).toFixed(1)}% to stop` : "near its stop");
    ask = `${contract} is near its stop. What would make me cut it?`;
  } else if (book.state === "giving_back") {
    const over = overCut(book, ticks);
    parts.push(over != null ? `giving back · ${Math.round(over)}% over cut ${premium(book.cut_line! / 100)}` : "giving back");
    ask = `${contract} is giving back its gain. Why, and what would make me cut it?`;
  } else if (expiring) {
    ask = `${contract} ${expiring}. What are my choices before the close?`;
  } else return null;
  if (expiring) parts.push(expiring);
  return { row, rank: needRank(row, day, ticks), risk, what: parts.join(" · "), ask, button };
}

export function DeskRightNow({ rows, day, onOpen, onAsk, onClose, onlyNeeds = false }: {
  rows: DeskThread[]; day: string; onOpen(row: DeskThread): void; onAsk(text: string): void;
  /** Past a cut line or stop: the closing ticket (copy only), the first button. */
  onClose?(row: DeskThread): void;
  /** Beside the Feed: nothing at all unless something needs a look. */
  onlyNeeds?: boolean;
}) {
  const open = positionRows(rows).filter(r => !r.hidden && r.book);
  const ticks = useDeskTicks(open.flatMap(r => [r.book?.tick?.quote, r.symbol]));
  if (!open.length) return null;
  const items = open.flatMap(r => rightNowItem(r, day, ticks) ?? [])
    .sort((a, b) => a.rank - b.rank || Number(b.risk) - Number(a.risk));
  // A cut line with no price to hold it against cannot be checked: never an all-clear for it.
  const listed = new Set(items.map(i => i.row.key));
  const unchecked = open.filter(r => !listed.has(r.key) && r.book!.cut_line != null && !r.book!.planned && rowNow(r.book, ticks).price == null).length;
  const uncheckedLine = unchecked > 0 && (
    <p data-testid="right-now-unchecked" className="border-t px-3 py-2 text-xs text-muted-foreground">
      No price yet for {unchecked === 1 ? "1 position" : `${unchecked} positions`} with a cut line: not checked against it.
    </p>
  );
  if (onlyNeeds && !items.length) return null;
  return (
    <section aria-label="Right now" data-testid="right-now" className={cn("rounded-lg border bg-card", onlyNeeds && "mb-2")}>
      <h2 className="px-3 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Right now</h2>
      {items.length ? (
        <ul>
          {items.map(item => (
            <li key={item.row.key} data-testid="right-now-item" className="flex items-center gap-2 border-t px-3 py-2">
              <button type="button" onClick={() => onOpen(item.row)} aria-label={`Open ${item.row.title}`}
                className="min-w-0 flex-1 text-left hover:underline">
                <span className="block truncate text-sm font-semibold text-foreground">{item.row.title}</span>
                <span data-testid="right-now-what" className={cn("block text-xs tabular-nums", item.risk ? "text-rose-300" : "text-muted-foreground")}>{item.what}</span>
              </button>
              {item.risk && item.button === "Cut or hold?" && onClose && closable(item.row, rows) && (
                <button type="button" data-testid="right-now-close" onClick={() => onClose(item.row)}
                  title="A closing ticket for all of it at the mark now, to copy into Robinhood. Nothing is sent."
                  className="inline-flex min-h-11 shrink-0 items-center rounded-md border border-rose-400 bg-rose-500 px-2.5 text-xs font-semibold text-white hover:bg-rose-500/90 sm:min-h-8">
                  Close ticket
                </button>
              )}
              <button type="button" data-testid="right-now-ask" onClick={() => onAsk(item.ask)}
                className="inline-flex min-h-11 shrink-0 items-center rounded-md border px-2.5 text-xs font-medium text-foreground hover:bg-secondary sm:min-h-8">
                {item.button}
              </button>
            </li>
          ))}
        </ul>
      ) : unchecked > 0 ? null : (
        <p data-testid="right-now-calm" className="border-t px-3 py-2 text-sm text-muted-foreground">
          Nothing needs you · {open.length} open, none past a cut line or stop.
        </p>
      )}
      {uncheckedLine}
    </section>
  );
}
