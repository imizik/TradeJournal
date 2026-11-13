"use client";

/**
 * The desk's account line (docs/copilot-lab.md § The desk, top bar): in the top bar, one tappable figure group per
 * Robinhood account — its label and number masked to the last four, total value, today's change in dollars and percent,
 * options value, cash and buying power, and the open P&L of its positions. Tapping an account narrows the book to its
 * rows; tapping it again shows every row. A phone gets the same line as one row that swipes sideways.
 *
 * The figures are the feed's last read. Between reads, the positions' live prices (#768) move the total, today's change
 * and the open P&L by exactly what they move those positions' P&L. Not live (off, signed out, unavailable, stale): one
 * grey line and no money; a figure Robinhood did not give is a dash, never zero.
 */

import { liveOn, money, signedPct, type DeskLive, type DeskLiveAccount, type DeskThread } from "@/lib/desk";
import { tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { positionRows, tone } from "@/components/copilot/Cockpit";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const whole = (value: number) => `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const short = (value: number) => `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`;
const or = (value: number | null | undefined, show: (v: number) => string) => value == null ? "—" : show(value);

/** The account the book is narrowed to, while that account is still on a live line (else none). */
export function activeAccount(live: DeskLive | null | undefined, picked: string | null): string | null {
  return picked && liveOn(live) && live?.accounts?.some(a => a.masked === picked) ? picked : null;
}

/** The book's rows and Robinhood orders for one account: its positions, and a journal row carrying one of its orders
 * (an order with no row of its own account sits on one); a journal row Robinhood does not show is in no account. Every
 * other row is left as it is (``masked`` null: all). */
export function forAccount(rows: DeskThread[], live: DeskLive | null, masked: string | null): { rows: DeskThread[]; live: DeskLive | null } {
  if (!masked) return { rows, live };
  const held = new Set(positionRows(rows));
  return {
    rows: rows.filter(r => !held.has(r) || r.book?.account?.masked === masked || !!r.book?.orders?.some(o => o.account.masked === masked)),
    live: live && { ...live, orders: live.orders?.filter(o => o.account.masked === masked) },
  };
}

/** One account's figures with its positions' live prices folded in: what the ticks add to their P&L since the read. */
export function tickedAccount(account: DeskLiveAccount, rows: DeskThread[], ticks: Parameters<typeof tickedBook>[1]) {
  let delta = 0;
  let stale = false;
  for (const row of positionRows(rows)) {
    if (row.book?.account?.masked !== account.masked || row.book.usd == null) continue;
    const now = tickedBook(row.book, ticks);
    if (now.usd != null) delta += now.usd - row.book.usd;
    stale ||= now.stale;
  }
  const add = (value: number | null | undefined) => value == null ? null : Math.round((value + delta) * 100) / 100;
  const change = add(account.day_change);
  // The day's start does not move with the ticks: total less today's change, as the read had it.
  const start = account.total_value != null && account.day_change != null ? account.total_value - account.day_change : null;
  return {
    total: add(account.total_value), change, open: add(account.open_pnl), stale,
    pct: change != null && start != null && start > 0 ? 100 * change / start : null,
  };
}

export function DeskAccounts({ live, rows, active, onPick }: {
  live: DeskLive | null; rows: DeskThread[]; active: string | null; onPick(masked: string | null): void;
}) {
  const ticks = useDeskTicks(positionRows(rows).map(r => r.book?.account ? r.book.tick?.quote : null));
  // Off: no account line at all (the book is the journal's, as it always was). Loading: the first read is on its way.
  if (!live || live.state === "off" || live.state === "loading") return null;
  if (!liveOn(live) || !live.accounts?.length) {
    const age = live.state === "stale" && live.as_of
      ? `Accounts as of ${new Date(live.as_of * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" })}`
      : "Accounts unavailable";
    return <span data-testid="desk-accounts" className="whitespace-nowrap text-xs text-muted-foreground">{age}</span>;
  }
  return (
    <div data-testid="desk-accounts" role="group" aria-label="Accounts"
      className="flex min-w-0 max-w-full snap-x items-center gap-1.5 overflow-x-auto [scrollbar-width:none] max-sm:basis-full sm:order-last [&::-webkit-scrollbar]:hidden">
      {live.accounts.map(a => {
        const t = tickedAccount(a, rows, ticks);
        const on = active === a.masked;
        return (
          <button key={a.masked} type="button" aria-pressed={on} onClick={() => onPick(on ? null : a.masked)}
            data-testid="desk-account" title={on ? "Show every account's positions" : `Show only ${a.label}'s positions in the book`}
            className={cn("inline-flex min-h-11 shrink-0 snap-start items-baseline gap-1 whitespace-nowrap rounded-md border px-2 py-1 text-xs text-foreground hover:bg-secondary sm:min-h-0 sm:py-0.5",
              on && "border-foreground/60 bg-secondary")}>
            <span className="font-medium">{a.label}</span>
            <span className="tabular-nums text-muted-foreground">{a.masked}</span>
            <span data-testid="account-total" className={cn("tabular-nums", t.stale && "opacity-50")}>{or(t.total, whole)}</span>
            {/* Today's change: shown only when every position in the account had yesterday's close (never a guessed zero). */}
            {t.change != null && (
              <span data-testid="account-today" title="Today: the move since yesterday's close of the positions open now (an option opened today, since its cost). Trades closed today are in Realized today."
                className={cn("tabular-nums", tone(t.change), t.stale && "opacity-50")}>
                {money(t.change)}{t.pct != null && ` ${signedPct(t.pct, 1)}`}
              </span>
            )}
            <span className="tabular-nums text-[11px] text-muted-foreground">
              opt {or(a.options_value, short)} cash {or(a.cash, short)} BP {or(a.buying_power, short)}
            </span>
            <span data-testid="account-open" className="tabular-nums text-[11px]">
              <span className="text-muted-foreground">open </span>
              <span className={cn(tone(t.open), t.stale && "opacity-50")}>{t.open == null ? "—" : money(t.open)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
