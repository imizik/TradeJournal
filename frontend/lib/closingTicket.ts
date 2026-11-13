/**
 * The closing ticket for a held long call or put with a plan (docs/copilot-lab.md § Ticket): "Close at target" and
 * "Close at stop" fill the desk's Ticket as a sell to close of the contracts held, with a limit price estimated for the
 * stock at that plan level. Pure arithmetic; ``DeskTicket``'s closing view only lays it out and copies it. Nothing here
 * places, sends or reads anything: the owner copies the fields into Robinhood himself.
 *
 * The estimate moves today's option mark by its delta: mark + delta x (level - stock), never below the contract's value
 * at expiry with the stock at the level, rounded to the cent and at least $0.01. A call's delta is positive and a put's
 * negative, so a call's estimate rises with the stock and a put's falls. It is a first-order guess (no gamma, no time,
 * no IV change), shown as one. Any missing input (no mark, no delta, a delta on the wrong side for the contract, no
 * stock price, no level, no size, no account) gives no ticket, so the button is absent: never a zero or made-up price.
 */

import { intrinsic, type OptionTerms } from "@/lib/optionStanding";

export type ClosingAt = "target" | "stop";
export const CLOSING_LABEL: Record<ClosingAt, string> = { target: "Close at target", stop: "Close at stop" };

export type ClosingTicket = {
  at: ClosingAt;
  symbol: string;
  side: "call" | "put";
  strike: number;
  expiry: string;  // YYYY-MM-DD
  /** Contracts held: what the ticket sells. */
  contracts: number;
  account: string;
  /** The plan's level on the underlying (its target or its invalidation). */
  level: number;
  /** The stock now and when (epoch seconds), as the estimate used it. */
  stock: number;
  stockAt: number | null;
  /** The option's mark now, a share's premium, and whether it came from a live tick. */
  mark: number;
  markLive: boolean;
  delta: number;
  /** The estimated limit, a share's premium, in cents. */
  estimate: number;
};

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** A share's premium with the stock at ``level``, from the mark and delta now; null when an input is missing or a delta
 * does not fit the contract (a call's is above 0 and at most 1, a put's below 0 and at least -1). */
export function closeEstimate(side: "call" | "put", strike: number, mark: number | null | undefined, delta: number | null | undefined,
  stock: number | null | undefined, level: number | null | undefined): number | null {
  if (!finite(mark) || mark <= 0 || !finite(delta) || !finite(stock) || stock <= 0 || !finite(level) || level <= 0 || !finite(strike) || strike <= 0) return null;
  if (side === "call" ? !(delta > 0 && delta <= 1) : !(delta < 0 && delta >= -1)) return null;
  const moved = Math.max(mark + delta * (level - stock), intrinsic(side, strike, level));
  return Math.max(0.01, Math.round(moved * 100) / 100);
}

/**
 * One closing ticket, or null when it cannot be honest. ``terms`` is the book row's option (a single long leg only),
 * ``levels`` the plan's stop and target on the underlying, ``worth`` the whole position's value now (``worthNow``),
 * ``markLive`` whether that came from a live option tick.
 */
export function closingTicket({ symbol, at, terms, levels, account, stock, worth, markLive = false }: {
  symbol: string | null; at: ClosingAt; terms: OptionTerms | null | undefined;
  levels: { stop: number | null; target: number | null } | null | undefined; account: string | null | undefined;
  stock: { last: number; at: number | null } | null; worth: number | null; markLive?: boolean;
}): ClosingTicket | null {
  if (!symbol || !terms || terms.direction !== "long" || !account) return null;
  const { side, strike, expiry, quantity, multiplier } = terms;
  if ((side !== "call" && side !== "put") || !finite(strike) || !expiry || !finite(quantity) || quantity <= 0
      || !Number.isInteger(quantity) || !finite(multiplier) || multiplier <= 0) return null;
  const level = at === "target" ? levels?.target : levels?.stop;
  if (!finite(level) || level <= 0 || !stock || !finite(worth) || worth <= 0) return null;
  const mark = Math.round(worth / (quantity * multiplier) * 10000) / 10000;
  const delta = terms.greeks?.delta;
  const estimate = closeEstimate(side, strike, mark, delta, stock.last, level);
  if (estimate === null || !finite(delta)) return null;
  return { at, symbol, side, strike, expiry, contracts: quantity, account, level, stock: stock.last, stockAt: stock.at, mark, markLive, delta, estimate };
}
