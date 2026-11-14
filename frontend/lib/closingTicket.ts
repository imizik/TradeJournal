/**
 * The closing ticket for a held long call or put with a plan (docs/copilot-lab.md § Ticket): "Close at target" and
 * "Close at stop" fill the desk's Ticket as a sell to close of the contracts held, with a limit price estimated for the
 * stock at that plan level. Pure arithmetic; ``DeskTicket``'s closing view only lays it out and copies it. Nothing here
 * places, sends or reads anything: the owner copies the fields into Robinhood himself.
 *
 * The estimate moves today's option mark by its delta: mark + delta x (level - stock), never below the contract's value
 * at expiry with the stock at the level, rounded to the cent and at least $0.01. When the stock is already at or past
 * the level (through the stop, or beyond the target), the limit is today's mark instead: a sell priced for a level the
 * stock has left would sit above the market at the stop, so the ticket starts where the option trades now and says so. A call's delta is positive and a put's
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
  /** The stock is already at or past the level: the limit is today's mark, not a move to the level. */
  past: boolean;
  /** The delta move alone came out lower: the limit is the contract's value at expiry there (or the $0.01 floor). */
  floored: boolean;
  /** Shares a contract (100 for a standard contract), for the proceeds. */
  multiplier: number;
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
  const moved = closeEstimate(side, strike, mark, delta, stock.last, level);
  if (moved === null || !finite(delta)) return null;
  // Past the level: a call's stop or a put's target is below the stock's path, so "past" is at or under it.
  const below = (side === "call") === (at === "stop");
  const past = below ? stock.last <= level : stock.last >= level;
  const estimate = past ? Math.max(0.01, Math.round(mark * 100) / 100) : moved;
  const floored = !past && estimate > Math.max(0.01, Math.round((mark + delta * (level - stock.last)) * 100) / 100);
  return { at, symbol, side, strike, expiry, contracts: quantity, account, level, stock: stock.last, stockAt: stock.at, mark, markLive, delta,
    estimate, past, floored, multiplier };
}

// --------------------------------------------------------------------------- close now: the copilot's close and trim cards

/**
 * A closing ticket at the mark now, for the copilot's close and trim cards (``lib/deskAction.ts``): a sell to close of a
 * held long call or put, or the closing spread of a held vertical (sell the bought leg, buy back the sold leg), for all
 * of it or part. ``mark`` and ``shortMark`` are a share's premium now, from the book row's own value (``worthNow``);
 * ``net`` is the bought leg's less the sold leg's (positive: closing brings money in; negative: a held credit spread costs
 * money to close). ``limit`` is ``net`` as a limit price, to the cent and at least $0.01; ``proceeds`` the signed dollars
 * at that limit. Pure arithmetic: nothing here places, sends or reads anything.
 */
export type CloseNowTicket = {
  at: "now";
  symbol: string;
  side: "call" | "put";
  expiry: string;
  /** The leg held long (a vertical's bought leg). */
  strike: number;
  /** A held vertical's sold leg, bought back with it; null for a single option. */
  shortStrike: number | null;
  /** Contracts (or spreads) held, sold by this ticket, and left after it. */
  held: number;
  contracts: number;
  remains: number;
  /** Robinhood's label and masked number when the book row has them; null for a position only the journal shows. */
  account: string | null;
  mark: number;
  shortMark: number | null;
  net: number;
  limit: number;
  /** Closing brings money in (a sell for a credit), or costs it (a debit). */
  credit: boolean;
  proceeds: number;
  markLive: boolean;
  multiplier: number;
};

/** Any ticket the Ticket tab's closing views open. */
export type AnyClosingTicket = ClosingTicket | CloseNowTicket;

/** Contracts a trim sells out of ``held`` (the server's ``copilot_actions.trim_count``): half rounds down and is at least
 * 1; a count must be a whole number from 1 to ``held``. Null when it cannot be. */
export function trimCount(held: number, ask: { quantity?: number | null; half?: boolean }): number | null {
  if (!Number.isInteger(held) || held < 1) return null;
  if (ask.half) return Math.max(1, Math.floor(held / 2));
  const q = ask.quantity;
  return typeof q === "number" && Number.isInteger(q) && q >= 1 && q <= held ? q : null;
}

/** One held leg as the book row has it: its terms and what the whole leg is worth now (``worthNow``). */
export type HeldLeg = { terms: OptionTerms | null | undefined; worth: number | null; markLive: boolean };

/** A share's premium now: the leg's worth over its size. */
function markOf(leg: HeldLeg): number | null {
  const t = leg.terms;
  if (!t || !finite(leg.worth) || leg.worth < 0 || !finite(t.quantity) || t.quantity <= 0 || !finite(t.multiplier) || t.multiplier <= 0) return null;
  return Math.round(leg.worth / (t.quantity * t.multiplier) * 10000) / 10000;
}

/**
 * The close-now ticket for ``contracts`` of a held position, or null when it cannot be honest. ``legs`` is the long leg,
 * and for a vertical the short leg after it: same type, expiry, multiplier and size, other strikes. Any missing mark,
 * size or term gives no ticket: never a zero or made-up price.
 */
export function closeNowTicket({ symbol, legs, account, contracts }: {
  symbol: string; legs: HeldLeg[]; account: string | null; contracts: number;
}): CloseNowTicket | null {
  const [long, short] = legs;
  const t = long?.terms;
  if (!symbol || !t || t.direction !== "long" || legs.length > 2) return null;
  if ((t.side !== "call" && t.side !== "put") || !finite(t.strike) || !t.expiry || !finite(t.quantity) || !Number.isInteger(t.quantity)
      || t.quantity < 1 || !finite(t.multiplier) || t.multiplier <= 0) return null;
  const s = short?.terms;
  if (short && (!s || s.direction !== "short" || s.side !== t.side || s.expiry !== t.expiry || s.quantity !== t.quantity
      || s.multiplier !== t.multiplier || !finite(s.strike) || s.strike === t.strike)) return null;
  if (!Number.isInteger(contracts) || contracts < 1 || contracts > t.quantity) return null;
  const mark = markOf(long);
  const shortMark = short ? markOf(short) : null;
  if (mark === null || (short && shortMark === null)) return null;
  const net = Math.round((mark - (shortMark ?? 0)) * 10000) / 10000;
  const limit = Math.max(0.01, Math.round(Math.abs(net) * 100) / 100);
  const credit = net >= 0;
  return { at: "now", symbol, side: t.side, expiry: t.expiry, strike: t.strike, shortStrike: short ? s!.strike : null,
    held: t.quantity, contracts, remains: t.quantity - contracts, account, mark, shortMark, net, limit, credit,
    proceeds: Math.round((credit ? 1 : -1) * limit * t.multiplier * contracts * 100) / 100,
    markLive: long.markLive && (!short || short.markLive), multiplier: t.multiplier };
}
