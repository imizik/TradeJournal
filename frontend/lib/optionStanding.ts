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

// --------------------------------------------------------------------------- what if

/**
 * What if (docs/copilot-lab.md § The desk): the held option's estimated value at a stock price and a date up to expiry,
 * priced with Black-Scholes from the IV the standing already has. An estimate, said so on screen: European exercise, no
 * dividends, a flat ``RATE``. Before anything is shown the model is priced at today's stock price and checked against
 * today's mark; when it misses by more than ``MARK_TOLERANCE`` the IV the mark implies is used instead, and the screen
 * says so. No IV (or no stock price) means no what-if; a short or multi-leg position gets nothing (``optionStanding``).
 */

/** The yearly risk-free rate the estimate assumes (stated on screen). */
export const RATE = 0.04;
/** "If earnings is flat": IV after the report, as a share of today's (a plain assumption, stated on screen). */
export const EARNINGS_IV_KEPT = 0.7;
/** How far the model may sit from today's mark (a share of the mark, never under ``MARK_FLOOR`` a share). */
export const MARK_TOLERANCE = 0.05;
export const MARK_FLOOR = 0.02;
const MINUTES_A_YEAR = 365 * 24 * 60;
const CLOSE_MINUTE = 16 * 60; // 16:00 New York: an equity option's last trading minute

/** The standard normal CDF (Abramowitz & Stegun 7.1.26 for erf, error under 1.5e-7). */
export function normCdf(x: number): number {
  const z = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * z);
  const erf = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
  return x >= 0 ? 0.5 * (1 + erf) : 0.5 * (1 - erf);
}

/** A share's Black-Scholes value; ``years`` ≤ 0 is expiry, where it is exactly the intrinsic value. */
export function bsValue(side: "call" | "put", spot: number, strike: number, years: number, iv: number, rate = RATE): number {
  if (years <= 0 || iv <= 0 || spot <= 0) return intrinsic(side, strike, spot);
  const sd = iv * Math.sqrt(years);
  const d1 = (Math.log(spot / strike) + (rate + iv * iv / 2) * years) / sd;
  const d2 = d1 - sd;
  const discounted = strike * Math.exp(-rate * years);
  return side === "call" ? spot * normCdf(d1) - discounted * normCdf(d2) : discounted * normCdf(-d2) - spot * normCdf(-d1);
}

/** The IV at which ``bsValue`` equals ``price`` (a share's), by bisection over 1%–500%; null when no IV there does. */
export function impliedVol(side: "call" | "put", spot: number, strike: number, years: number, price: number, rate = RATE): number | null {
  if (years <= 0 || !(price > 0)) return null;
  let lo = 0.01, hi = 5;
  if (price < bsValue(side, spot, strike, years, lo, rate) || price > bsValue(side, spot, strike, years, hi, rate)) return null;
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    if (bsValue(side, spot, strike, years, mid, rate) < price) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

/** Years from now to expiry's 16:00 close: whole days to ``expiry`` from ``day`` plus what is left of today, given the
 * New York minute of the day now (0–1439). Never negative. */
export const yearsLeft = (expiry: string, day: string, nyMinute: number) =>
  Math.max(0, daysLeft(expiry, day) * 1440 + CLOSE_MINUTE - nyMinute) / MINUTES_A_YEAR;

/** ``day`` (YYYY-MM-DD) moved by ``n`` calendar days. */
export function addDays(day: string, n: number): string {
  return new Date(Date.parse(`${day}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}

/** The first weekday after the earnings date (holidays not known), for "If earnings is flat"; null when the report is
 * already past or that day falls after expiry. */
export function dayAfterEarnings(earnings: string | null | undefined, day: string, expiry: string): string | null {
  if (!earnings || !DAY.test(earnings) || earnings < day) return null;
  let next = addDays(earnings, 1);
  while ([0, 6].includes(new Date(`${next}T12:00:00Z`).getUTCDay())) next = addDays(next, 1);
  return next <= expiry ? next : null;
}

export type WhatIfModel = {
  side: "call" | "put"; strike: number; expiry: string;
  /** Shares the position controls, and its total cost (null when the book has none: value without P&L). */
  size: number; cost: number | null;
  /** Today (New York), the stock now, and years left from now to expiry's close. */
  day: string; price: number; yearsNow: number;
  /** The IV the estimate uses, and where it came from: the standing's Greeks, or implied from today's mark because the
   * Greeks' IV missed the mark by more than ``MARK_TOLERANCE``. */
  iv: number; ivSource: "greeks" | "mark"; givenIv: number;
  /** Today's model value against today's mark, both a share's (null without a mark). */
  check: { model: number; mark: number } | null;
};

/**
 * The what-if's inputs for one held option, or a plain reason it has none (no IV, no stock price, a model that cannot
 * reproduce today's mark). Null for anything ``optionStanding`` does not read as a single long call or put.
 */
export function whatIfModel(terms: OptionTerms | null | undefined, { price, worth, day, nyMinute }: {
  price: number | null | undefined; worth: number | null | undefined; day: string; nyMinute: number;
}): WhatIfModel | { reason: string } | null {
  const leg = readable(terms);
  if (!leg) return null;
  const given = terms?.greeks?.iv;
  if (!finite(given) || given <= 0) return { reason: "no IV for this contract" };
  if (!finite(price) || price <= 0) return { reason: "no stock price" };
  if (leg.expiry < day) return { reason: "expired" };
  const size = leg.quantity * leg.multiplier;
  const yearsNow = yearsLeft(leg.expiry, day, nyMinute);
  const base = { side: leg.side, strike: leg.strike, expiry: leg.expiry, size, day, price, yearsNow, givenIv: given,
    cost: leg.cost === null ? null : leg.cost * leg.quantity };
  const mark = finite(worth) && worth > 0 ? worth / size : null;
  if (mark === null) return { ...base, iv: given, ivSource: "greeks", check: null };
  const model = bsValue(leg.side, price, leg.strike, yearsNow, given);
  if (Math.abs(model - mark) <= Math.max(MARK_TOLERANCE * mark, MARK_FLOOR)) return { ...base, iv: given, ivSource: "greeks", check: { model, mark } };
  const implied = impliedVol(leg.side, price, leg.strike, yearsNow, mark);
  if (implied === null) return { reason: "the estimate cannot match today's mark" };
  return { ...base, iv: implied, ivSource: "mark", check: { model, mark } };
}

/** Years from ``day``'s close to expiry's close; today counts from now. */
export const yearsAt = (m: WhatIfModel, day: string) => day <= m.day ? m.yearsNow : Math.max(0, daysLeft(m.expiry, day)) / 365;

export type WhatIfPoint = { share: number; value: number; pnl: number | null; pnlPct: number | null };

/** The estimate at a stock price on a date (its close; today: now), with ``iv`` (default the model's). */
export function whatIfAt(m: WhatIfModel, { price, day, iv = m.iv }: { price: number; day: string; iv?: number }): WhatIfPoint {
  const share = bsValue(m.side, price, m.strike, yearsAt(m, day), iv);
  const value = share * m.size;
  const pnl = m.cost === null ? null : value - m.cost;
  return { share, value, pnl, pnlPct: pnl === null || !m.cost ? null : pnl / m.cost * 100 };
}

/** The price range the what-if offers: about 2.5 standard deviations to expiry around today's price (10%–60%), widened
 * to take in the strike and the plan's levels, its ends on a round ``step`` (about 400 steps) so a dragged price lands
 * on whole cents like 247.25. */
export function whatIfRange(m: WhatIfModel, levels: readonly number[] = []): { lo: number; hi: number; step: number } {
  const span = Math.min(0.6, Math.max(0.1, 2.5 * m.iv * Math.sqrt(Math.max(m.yearsNow, 1 / 365))));
  const marks = [m.strike, ...levels.filter(l => finite(l) && l > 0)];
  const lo = Math.min(m.price * (1 - span), ...marks.map(l => l * 0.97));
  const hi = Math.max(m.price * (1 + span), ...marks.map(l => l * 1.03));
  const step = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10].find(s => (hi - lo) / s <= 400) ?? 25;
  const cents = (value: number) => Math.round(value * 100) / 100;
  return { lo: Math.max(step, cents(Math.floor(lo / step) * step)), hi: cents(Math.ceil(hi / step) * step), step };
}

/** The estimate across the range on a date: P&L (value when the cost is unknown) at 61 stock prices. */
export function whatIfCurve(m: WhatIfModel, { day, iv = m.iv, lo, hi }: { day: string; iv?: number; lo: number; hi: number }) {
  return Array.from({ length: 61 }, (_, i) => {
    const price = lo + (hi - lo) * i / 60;
    const at = whatIfAt(m, { price, day, iv });
    return { price, y: at.pnl ?? at.value };
  });
}
