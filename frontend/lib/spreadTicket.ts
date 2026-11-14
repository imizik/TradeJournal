/**
 * Two-leg vertical spreads on the desk (docs/copilot-lab.md § Ticket, "Spreads"): the arithmetic the ticket and the
 * Chain tab recompute as he edits, the same as the server's ``desk_ticket.spread_figures``. One long leg (bought) and
 * one short leg (sold), same expiry, same type. Prices are per share; dollars are × the multiplier × the count. The net
 * limit is a positive number, a debit (paid) or a credit (taken in) by the strikes. Copy only: nothing here reads or
 * sends anything.
 */

export type Side = "call" | "put";
export type LevelRole = "entry" | "target" | "stop";

/** Buying ``long`` and selling ``short`` costs money when the long leg is nearer the money. */
export const isDebit = (kind: Side, long: number, short: number) => kind === "call" ? long < short : long > short;
/** A call debit and a put credit gain as the stock rises. */
export const isBullish = (kind: Side, long: number, short: number) => isDebit(kind, long, short) === (kind === "call");

/** To the cent, a half cent up, as the server's ``desk_ticket.cents`` rounds the net price. */
const cents = (n: number) => Math.floor(n * 100 + 0.5 + 1e-9) / 100;
const strikeText = (n: number) => Number.isInteger(n) ? String(n) : String(+n.toFixed(2));
const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const shortDate = (iso: string) => { const [y, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}/${y.slice(2)}`; };

/** One spread's worth per share at expiry with the stock at ``price``, signed: long leg's intrinsic less the short's. */
export function spreadValue(kind: Side, long: number, short: number, price: number): number {
  const payoff = (k: number) => kind === "call" ? Math.max(price - k, 0) : Math.max(k - price, 0);
  return payoff(long) - payoff(short);
}

export type SpreadFigures = {
  type: "debit" | "credit"; width: number; cost: number | null; credit: number | null; maxLoss: number | null; maxGain: number | null;
  breakeven: number | null; movePct: number | null; vsExpected: number | null; warning: string | null;
  atLevels: { role: LevelRole; price: number; worth: number; pnl: number | null }[];
};

/** Debit: pays the limit, loses at most that, makes at most the width less it. Credit: takes in the limit, makes at
 *  most that, loses at most the width less it. Break-even at expiry: a call spread's lower strike plus the limit, a put
 *  spread's higher strike less it. A limit at or over the width gives no figures and says why. */
export function spreadFigures(kind: Side, long: number, short: number, limit: number | null, contracts: number | null,
  multiplier: number | null, spot: number | null, expectedPct: number | null = null,
  levels: Partial<Record<LevelRole, number | null>> = {}): SpreadFigures {
  const width = Math.abs(short - long);
  const debit = isDebit(kind, long, short);
  const out: SpreadFigures = { type: debit ? "debit" : "credit", width, cost: null, credit: null, maxLoss: null, maxGain: null,
    breakeven: null, movePct: null, vsExpected: null, warning: null, atLevels: [] };
  if (limit === null || !(limit > 0) || !(width > 0)) return out;
  if (limit >= width - 1e-9) {
    out.warning = debit ? `A ${limit} debit is the ${strikeText(width)} width or more: the spread can never be worth more than you pay.`
      : `A ${limit} credit is the ${strikeText(width)} width or more: no real market pays that. Check the price.`;
    return out;
  }
  const per = contracts && contracts > 0 && multiplier ? multiplier * contracts : null;
  if (per) {
    const paidOrTaken = cents(limit * per), other = cents((width - limit) * per);
    if (debit) { out.cost = paidOrTaken; out.maxLoss = paidOrTaken; out.maxGain = other; }
    else { out.credit = paidOrTaken; out.maxGain = paidOrTaken; out.maxLoss = other; }
  }
  const low = Math.min(long, short), high = Math.max(long, short);
  out.breakeven = Math.round((kind === "call" ? low + limit : high - limit) * 1e4) / 1e4;
  if (spot && spot > 0) {
    out.movePct = (out.breakeven - spot) / spot * 100;
    if (expectedPct && expectedPct > 0) out.vsExpected = Math.abs(out.movePct) / expectedPct;
  }
  const net = debit ? limit : -limit;
  for (const role of ["entry", "target", "stop"] as LevelRole[]) {
    const price = levels[role];
    if (price == null || !(price > 0)) continue;
    const value = spreadValue(kind, long, short, price);
    out.atLevels.push({ role, price, worth: Math.abs(value), pnl: per ? cents((value - net) * per) : null });
  }
  return out;
}

type Market = { bid: number | null; ask: number | null };
/** The net price from each leg's bid and ask, as a positive debit or credit: at the mid, and at the natural price (buy
 *  the long leg at its ask, sell the short leg at its bid: the worst fill). Null without both legs' bid and ask. */
export function spreadNet(kind: Side, long: number, short: number, longQ: Market, shortQ: Market): { mid: number; natural: number } | null {
  if (longQ.bid == null || longQ.ask == null || shortQ.bid == null || shortQ.ask == null) return null;
  const paidMid = (longQ.bid + longQ.ask) / 2 - (shortQ.bid + shortQ.ask) / 2;
  const paidNatural = longQ.ask - shortQ.bid;
  const sign = isDebit(kind, long, short) ? 1 : -1;
  return { mid: cents(sign * paidMid), natural: cents(sign * paidNatural) };
}

/** As Robinhood names a vertical: "NBIS $100/$110 Call Debit Spread 12/19/26". */
export function spreadLabel(symbol: string, kind: Side, long: number, short: number, expiry: string): string {
  const low = Math.min(long, short), high = Math.max(long, short);
  return `${symbol} $${strikeText(low)}/$${strikeText(high)} ${kind === "call" ? "Call" : "Put"} ${isDebit(kind, long, short) ? "Debit" : "Credit"} Spread ${shortDate(expiry)}`;
}

/** The plan's contract words for a vertical, short enough for a plan card (≤ 40) and read back by the ticket
 *  (``desk_ticket.read_spread``): "NBIS 12/19/26 100/110C debit spread". */
export function spreadWords(symbol: string, kind: Side, long: number, short: number, expiry: string): string {
  const low = Math.min(long, short), high = Math.max(long, short);
  return `${symbol} ${shortDate(expiry)} ${strikeText(low)}/${strikeText(high)}${kind === "call" ? "C" : "P"} ${isDebit(kind, long, short) ? "debit" : "credit"} spread`;
}

/** What Copy all puts on the clipboard: Robinhood's spread screen, top to bottom: each leg, then the net limit price as a
 *  debit or credit, then the quantity. */
export function spreadCopyText(t: { symbol: string; kind: Side; expiry: string; long: number; short: number; limit: string; contracts: string }): string {
  const kindWord = t.kind === "call" ? "Call" : "Put";
  const type = isDebit(t.kind, t.long, t.short) ? "debit" : "credit";
  return [`${t.symbol} · ${kindWord} ${type} spread`,
    `Leg 1: Buy · ${kindWord} · Expiration ${shortDate(t.expiry)} · Strike $${strikeText(t.long)}`,
    `Leg 2: Sell · ${kindWord} · Expiration ${shortDate(t.expiry)} · Strike $${strikeText(t.short)}`,
    `Limit price ${t.limit ? `${t.limit} ${type}` : "(set it)"}`, `Quantity ${t.contracts || "(set it)"}`].join("\n");
}

/** The plain-language line: "Pay $3.20 for the 100/110 call spread, risk $320 to make $680, breakeven 103.20." */
export function spreadSentence(kind: Side, long: number, short: number, limit: number | null, contracts: number | null, f: SpreadFigures): string | null {
  if (limit === null || f.breakeven === null) return null;
  const low = Math.min(long, short), high = Math.max(long, short);
  const n = contracts && contracts > 0 ? contracts : null;
  const what = `the ${strikeText(low)}/${strikeText(high)} ${kind} ${f.type === "credit" ? "credit " : ""}spread${n && n > 1 ? ` (${n} of them)` : ""}`;
  const money = f.maxLoss !== null && f.maxGain !== null ? `, risk ${usd(f.maxLoss)} to make ${usd(f.maxGain)}` : "";
  return `${f.type === "debit" ? "Pay" : "Take in"} ${usd(limit)} a share for ${what}${money}, breakeven ${f.breakeven.toFixed(2)}.`;
}
