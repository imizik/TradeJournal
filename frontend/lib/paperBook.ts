/**
 * His own paper book (backend ``app/engine/paper_book.py``, docs/copilot-lab.md § Paper): the read, the orders and the
 * live P&L of a paper position from the desk's ticks. Paper only: nothing here places an order anywhere.
 */

import { apiUrl } from "@/lib/api";
import { tickFor, type DeskTicks } from "@/lib/deskTicks";

export const PAPER_EVENT = "tradejournal:paper-changed";

export type PaperLeg = { quote: string; action: "buy" | "sell"; strike: number | null };
export type PaperMark = { per_share: number; value: number; pnl: number; pct: number | null; at: number } | null;
/** ``auto``: the switch closed it at the stop or target, not his own hand. */
export type PaperVerdict = { kind: "target" | "stop" | "early" | "expiry" | "none" | "unknown"; text: string; auto?: boolean };
export type PaperPosition = {
  id: string; symbol: string; instrument: "stock" | "option" | "spread"; option_type: "call" | "put" | null; expiry: string | null;
  label: string; bias: "long" | "short"; credit: boolean; width: number | null; multiplier: number; quantity: number; remaining: number;
  per_share: number; cash: number; basis: number; stock: number | null; note: string | null; stop: number | null; target: number | null;
  opened_at: number; status: "open" | "closed" | "expired"; closed_at: number | null; realized: number; legs: PaperLeg[];
  awaiting_close: boolean; mark?: PaperMark; verdict?: PaperVerdict;
  /** Open positions: the "Close automatically at stop/target" switch, when each level was touched, an automatic exit
   *  waiting for a fresh bid, and how many a working sell limit holds. */
  auto?: boolean; touched?: { stop?: number; target?: number }; exiting?: boolean; held?: number;
  exits?: { kind: "close" | "expire"; at: number; quantity: number; per_share: number; cash: number; pnl: number; stock: number | null }[];
};
export type PaperStats = {
  trades: number; pnl: number; win_rate: number | null; avg_win: number | null; avg_loss: number | null; largest_loss: number | null;
  curve: { day: string; pnl: number }[]; open_pnl?: number | null;
};
/** A working day limit order: ``check`` is the minute's last look (its quote's time, the natural price then, or why
 *  it could not fill on it). */
export type PaperWorkingOrder = {
  id: string; side: "open" | "close"; symbol: string; instrument: "stock" | "option" | "spread"; label: string; multiplier: number;
  quantity: number; limit: number; pays: boolean; reserve: number; placed_at: number; expires_at: number; position: string | null;
  check: { at: number; quoted_at: number | null; natural: number | null; issue: string | null } | null;
};
export type PaperBook = {
  run: null | { id: string; number: number; starting_cash: number; started_at: number };
  default_cash?: number;
  account?: { cash: number; collateral: number; reserved?: number; buying_power: number; equity: number | null; pnl: number | null; unpriced: number; prices_at: number | null };
  positions?: PaperPosition[]; closed?: PaperPosition[]; orders?: PaperWorkingOrder[];
  score?: { paper: PaperStats; real: PaperStats };
  earlier: { number: number; started_at: number; ended_at: number; starting_cash: number; realized: number; trades: number; left_open: number }[];
  market_open: boolean;
  /** The newest Friday paper review (backend engine/paper_review.py), shown until the next one. */
  review?: PaperReview | null;
};
/** The copilot's weekly paper review: ``day`` the Friday it was written, ``monday`` its week. */
export type PaperReview = { day: string; monday: string; at: number; text: string };

/** What the Paper button opens: shares, one call or put, or a vertical (the leg bought and the leg sold). */
export type PaperOrder =
  | { instrument: "stock"; symbol: string }
  | { instrument: "option"; symbol: string; option_type: "call" | "put"; expiry: string; strike: number }
  | { instrument: "spread"; symbol: string; option_type: "call" | "put"; expiry: string; long_strike: number; short_strike: number };
export type PaperFill = {
  label: string; quantity: number; per_share: number; cash: number; quoted_at: number; stock: number | null;
  legs: Record<string, { action: "buy" | "sell"; bid: number; ask: number; price: number }>;
  buying_power_after?: number; buying_power?: number; need_each?: number; pnl?: number; all?: boolean; position_id?: string;
};

export class PaperRefused extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

async function post<T>(path: string, body: object): Promise<T> {
  const response = await fetch(apiUrl(path), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const reply = await response.json().catch(() => null);
  if (!response.ok) throw new PaperRefused(typeof reply?.detail === "string" ? reply.detail : `Request failed (${response.status}).`, response.status);
  return reply as T;
}

const changed = () => window.dispatchEvent(new Event(PAPER_EVENT));
/** One key per confirm: a retry of the same Fill on paper reuses it, so the server records one fill. */
export const orderKey = () => (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, "");

export async function startPaper(startingCash: number, reset = false): Promise<PaperBook> {
  const book = await post<PaperBook>("/copilot/paper/runs", { starting_cash: startingCash, reset });
  changed();
  return book;
}

type Levels = { note?: string | null; stop?: number | null; target?: number | null };
export function previewOpen(order: PaperOrder, quantity: number) {
  return post<{ preview: PaperFill }>("/copilot/paper/orders", { action: "open", preview: true, ...order, quantity }).then(r => r.preview);
}
export async function fillOpen(order: PaperOrder, quantity: number, levels: Levels, key: string) {
  const reply = await post<{ filled: PaperFill | null }>("/copilot/paper/orders", { action: "open", ...order, quantity, ...levels, order_key: key });
  changed();
  return reply.filled;
}
export function previewClose(positionId: string, quantity: number) {
  return post<{ preview: PaperFill }>("/copilot/paper/orders", { action: "close", preview: true, position_id: positionId, quantity }).then(r => r.preview);
}
export async function fillClose(positionId: string, quantity: number, key: string) {
  const reply = await post<{ filled: PaperFill | null }>("/copilot/paper/orders", { action: "close", position_id: positionId, quantity, order_key: key });
  changed();
  return reply.filled;
}

/** A day limit order: it works until a fresh quote crosses it, the close or a cancel; ``filled`` when it crossed at once. */
export type PaperPlaced = { working: (PaperWorkingOrder & { buying_power_after: number }) | null; filled: PaperFill | null; duplicate?: boolean };
export async function placeLimitOpen(order: PaperOrder, quantity: number, limit: number, levels: Levels, key: string) {
  const reply = await post<PaperPlaced>("/copilot/paper/orders", { action: "open", order_type: "limit", limit_price: limit, ...order, quantity, ...levels, order_key: key });
  changed();
  return reply;
}
export async function placeLimitClose(positionId: string, quantity: number, limit: number, key: string) {
  const reply = await post<PaperPlaced>("/copilot/paper/orders", { action: "close", order_type: "limit", limit_price: limit, position_id: positionId, quantity, order_key: key });
  changed();
  return reply;
}
export async function cancelPaperOrder(orderId: string) {
  await post<{ canceled: string }>("/copilot/paper/orders/cancel", { order_id: orderId });
  changed();
}
export async function setPaperAuto(positionId: string, on: boolean) {
  await post<{ auto: boolean }>("/copilot/paper/auto", { position_id: positionId, on, order_key: orderKey() });
  changed();
}

/** Whether a spread takes in a credit to open: a call spread buying the higher strike, a put spread buying the lower. */
export const isCredit = (order: PaperOrder) => order.instrument === "spread"
  && (order.option_type === "call" ? order.long_strike > order.short_strike : order.long_strike < order.short_strike);

/** A paper position's P&L at the desk's live prices (each leg's tick; a spread is the bought leg less the sold), by the
 *  server's own formula: worth × multiplier × held, plus the opening cash left (negative for a debit). The server's
 *  kept mark (greyed with its time) when a leg has no live tick; null when there is no price at all, never a zero. */
export function paperPnl(p: PaperPosition, ticks: DeskTicks, now = Date.now() / 1000):
  { pnl: number; pct: number | null; at: number; live: boolean; stale: boolean } | null {
  const live = p.legs.map(leg => tickFor(ticks, leg.quote, now));
  if (live.every(t => t)) {
    const per = p.legs.reduce((sum, leg, i) => sum + (leg.action === "buy" ? 1 : -1) * live[i]!.last, 0);
    const pnl = Math.round((per * p.multiplier * p.remaining + p.basis) * 100) / 100;
    return { pnl, pct: p.basis ? Math.round(pnl / Math.abs(p.basis) * 1000) / 10 : null, at: Math.min(...live.map(t => t!.at)), live: true,
      stale: live.some(t => t!.stale) };
  }
  if (!p.mark) return null;
  return { pnl: p.mark.pnl, pct: p.mark.pct, at: p.mark.at, live: false, stale: true };
}

/** The symbols the desk's ticker should price for these positions: each leg's quote and the underlying. */
export const paperSymbols = (positions: PaperPosition[] | undefined) => (positions ?? []).flatMap(p => [...p.legs.map(l => l.quote), p.symbol]);

/** The account's value at the desk's live prices: cash plus what each open position is worth (its P&L less the opening
 *  cash left), with the oldest price's time; the server's value (and its prices' time) when a position has no live
 *  price. Null when a position has no price at all. */
export function paperValue(book: PaperBook, ticks: DeskTicks, now = Date.now() / 1000): { value: number; at: number | null; stale: boolean } | null {
  const acct = book.account!;
  const each = (book.positions ?? []).map(p => ({ p, pnl: paperPnl(p, ticks, now) }));
  if (each.every(e => e.pnl?.live)) {
    const value = Math.round((acct.cash + each.reduce((sum, e) => sum + e.pnl!.pnl - e.p.basis, 0)) * 100) / 100;
    return { value, at: each.length ? Math.min(...each.map(e => e.pnl!.at)) : null, stale: each.some(e => e.pnl!.stale) };
  }
  return acct.equity == null ? null : { value: acct.equity, at: acct.prices_at, stale: true };
}
