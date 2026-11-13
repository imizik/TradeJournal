/**
 * Where a held option stands (docs/copilot-lab.md § The desk): break-even and the stock's distance to it, days left,
 * what it is worth at expiry if the stock stays put against what it is worth now (the rest is time value), the day's
 * decay and the dollar move per $1 in the stock for the whole position, and IV. Pure arithmetic over the book row's
 * ``option`` terms (``_option_terms`` / ``_live_terms`` in copilot_desk.py) and the newest stock price; the desk's
 * ``OptionStanding`` component draws it.
 *
 * Units: ``cost`` is dollars a contract (the premium x the multiplier, as the journal and Robinhood keep it), Greeks are
 * a share's (theta a day), IV a fraction. Only a single long call or put is read: a short contract, or a ticker that
 * also holds a short option (a spread, a calendar), is a structure the book cannot tell, so it gets nothing rather than
 * a wrong number. A missing input leaves its figure null (shown as unavailable), never zero.
 */

import type { DeskBook } from "@/lib/desk";
import { tickFor, tickedBook, type DeskTicks } from "@/lib/deskTicks";

export type OptionGreeks = {
  delta: number | null; theta: number | null; iv: number | null;
  /** Robinhood: the snapshot's epoch seconds. Tradier: the provider's own hourly stamp, as given (its time zone unknown). */
  as_of: number | string | null;
  source: "robinhood" | "tradier";
};

export type OptionTerms = {
  side: string | null; strike: number | null; expiry: string | null; direction: string | null;
  quantity: number | null; multiplier: number | null; cost: number | null; greeks: OptionGreeks | null;
};

export type ExpiryCurve = { lo: number; hi: number; points: { price: number; pnl: number }[] };

export type Standing = {
  side: "call" | "put";
  contracts: number;
  daysLeft: number;
  /** 0–2 days left, in words ("Expires today", "Expires tomorrow", "Expires Friday"); null further out. */
  expiryNote: string | null;
  breakEven: number | null;
  /** The stock move to break-even (break-even − price, in $ and % of the price), and whether the stock is already past it
   * on the profitable side (above for a call, below for a put). */
  toBreakEven: { usd: number; pct: number; past: boolean } | null;
  /** The whole position's intrinsic value if the stock stays at today's price until expiry. */
  atExpiry: number | null;
  /** What the whole position is worth now. */
  worth: number | null;
  /** ``worth − atExpiry``: what time alone is holding up. */
  timeValue: number | null;
  /** Theta for the whole position: dollars a day (negative is a loss). */
  decayPerDay: number | null;
  /** Delta for the whole position: dollars per $1 up in the stock (a put's is negative). */
  perDollar: number | null;
  /** IV in percent. */
  ivPct: number | null;
  greeks: OptionGreeks | null;
  /** P&L at expiry across a price range (null without the cost or the price). */
  curve: ExpiryCurve | null;
};

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Calendar days from ``day`` to ``expiry`` (both YYYY-MM-DD). */
export const daysLeft = (expiry: string, day: string) =>
  Math.round((Date.parse(`${expiry}T12:00:00Z`) - Date.parse(`${day}T12:00:00Z`)) / 86_400_000);

export function expiryNote(expiry: string, day: string): string | null {
  const n = daysLeft(expiry, day);
  if (n < 0) return "Expired";
  if (n === 0) return "Expires today";
  if (n === 1) return "Expires tomorrow";
  if (n === 2) return `Expires ${WEEKDAYS[new Date(`${expiry}T12:00:00Z`).getUTCDay()]}`;
  return null;
}

/** A share's value at expiry with the stock at ``price``. */
export const intrinsic = (side: "call" | "put", strike: number, price: number) =>
  side === "call" ? Math.max(0, price - strike) : Math.max(0, strike - price);

/** A single long call or put the book can read, or null (a short, a missing contract fact, a ticker with a short leg). */
function readable(terms: OptionTerms | null | undefined) {
  if (!terms || terms.direction !== "long") return null;
  const { side, strike, expiry, quantity, multiplier } = terms;
  if ((side !== "call" && side !== "put") || !finite(strike) || strike <= 0 || !expiry || !DAY.test(expiry)
      || !finite(quantity) || quantity <= 0 || !finite(multiplier) || multiplier <= 0) return null;
  return { side, strike, expiry, quantity, multiplier, cost: finite(terms.cost) && terms.cost > 0 ? terms.cost : null } as const;
}

/** True when another option position on the same ticker is not a plain long: the book cannot tell the structure. */
export function mixedStructure(symbol: string | null | undefined, self: OptionTerms | null | undefined,
  others: readonly { symbol: string | null; option?: OptionTerms | null }[]): boolean {
  return !!symbol && others.some(o => o.symbol === symbol && o.option && o.option !== self && o.option.direction !== "long");
}

export function expiryCurve(side: "call" | "put", strike: number, costPerShare: number, size: number, price: number): ExpiryCurve {
  const breakEven = side === "call" ? strike + costPerShare : strike - costPerShare;
  const lo = Math.max(0, Math.min(price, strike, breakEven) * 0.9);
  const hi = Math.max(price, strike, breakEven) * 1.1;
  const points = Array.from({ length: 41 }, (_, i) => {
    const at = lo + (hi - lo) * i / 40;
    return { price: at, pnl: (intrinsic(side, strike, at) - costPerShare) * size };
  });
  return { lo, hi, points };
}

/**
 * The standing of one held option. ``price`` is the stock's newest price (the desk's ticker, else the chart's last
 * read); ``worth`` the whole position's value now (the live option mark x size, else cost x size + its P&L); ``day``
 * today's New York date. Null when the position is not a single long call or put.
 */
export function optionStanding(terms: OptionTerms | null | undefined, { price, worth, day }: {
  price: number | null | undefined; worth: number | null | undefined; day: string;
}): Standing | null {
  const leg = readable(terms);
  if (!leg) return null;
  const size = leg.quantity * leg.multiplier;  // shares the position controls
  const costPerShare = leg.cost === null ? null : leg.cost / leg.multiplier;
  const breakEven = costPerShare === null ? null : leg.side === "call" ? leg.strike + costPerShare : leg.strike - costPerShare;
  const stock = finite(price) && price > 0 ? price : null;
  const now = finite(worth) && worth >= 0 ? worth : null;
  const atExpiry = stock === null ? null : intrinsic(leg.side, leg.strike, stock) * size;
  const toBreakEven = breakEven === null || stock === null ? null : {
    usd: breakEven - stock, pct: (breakEven - stock) / stock * 100,
    past: leg.side === "call" ? stock >= breakEven : stock <= breakEven,
  };
  const greeks = terms?.greeks ?? null;
  const delta = finite(greeks?.delta) ? greeks.delta : null;
  const theta = finite(greeks?.theta) ? greeks.theta : null;
  const iv = finite(greeks?.iv) && greeks.iv > 0 ? greeks.iv : null;
  return {
    side: leg.side, contracts: leg.quantity,
    daysLeft: daysLeft(leg.expiry, day), expiryNote: expiryNote(leg.expiry, day),
    breakEven, toBreakEven, atExpiry, worth: now,
    timeValue: now === null || atExpiry === null ? null : now - atExpiry,
    decayPerDay: theta === null ? null : theta * size,
    perDollar: delta === null ? null : delta * size,
    ivPct: iv === null ? null : iv * 100,
    greeks,
    curve: costPerShare === null || stock === null ? null : expiryCurve(leg.side, leg.strike, costPerShare, size, stock),
  };
}

/** The whole position's value now: the live option mark x size, else the book's mark, else cost x size + its P&L. */
export function worthNow(book: DeskBook | undefined, ticks: DeskTicks): number | null {
  const terms = book?.tick;
  const live = terms ? tickFor(ticks, terms.quote) : null;
  if (terms && live && !live.stale) return live.last * terms.scale * terms.quantity;
  const quantity = book?.quantity ?? terms?.quantity ?? book?.option?.quantity ?? null;
  if (book?.mark != null && quantity) return book.mark * quantity;
  const pnl = tickedBook(book, ticks).usd;
  const cost = terms?.cost ?? book?.option?.cost ?? null;
  return pnl != null && cost != null && quantity ? cost * quantity + pnl : null;
}
