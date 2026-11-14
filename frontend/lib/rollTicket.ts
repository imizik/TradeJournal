/**
 * The roll ticket's arithmetic (docs/copilot-lab.md § Ticket, "Roll"): the same as the server's ``desk_roll``, so the
 * ticket recomputes exactly what the server first showed as he edits the counts and the limit. Close a held long call or
 * put, open another of the same type. Prices are a share's premium; dollars are × the multiplier × the contracts. A net
 * is signed as money paid: positive is a debit (he pays), negative a credit (he takes in). Copy only: nothing here reads
 * or sends anything.
 */

export type Side = "call" | "put";
export type NetType = "debit" | "credit" | "even";

/** What a held long option needs to be rolled: from the desk's book row. ``cost`` is dollars a contract (the premium ×
 * the multiplier, as the book keeps it), null when the book has none. ``account`` is Robinhood's label and masked
 * number when the book has them. */
export type RollFrom = { symbol: string; side: Side; strike: number; expiry: string; held: number; cost: number | null; account: string | null };

/** To the cent, a half cent up, as the server's ``desk_ticket.cents``. */
export const cents = (n: number) => Math.floor(n * 100 + 0.5 + 1e-9) / 100;
/** To the cent, symmetric about zero (``desk_roll.signed_cents``). */
export const signedCents = (n: number) => n >= 0 ? cents(n) : -cents(-n);
const EVEN = 0.005;
export const netType = (net: number | null): NetType | null => net === null ? null : net >= EVEN ? "debit" : net <= -EVEN ? "credit" : "even";

const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86_400_000);
const round = (n: number, places: number) => Math.round(n * 10 ** places) / 10 ** places;
const isCount = (n: number | null): n is number => typeof n === "number" && Number.isInteger(n) && n > 0;

export type RollFigures = {
  daysAdded: number; sameCount: boolean | null; net: number | null; netType: NetType | null;
  proceeds: number | null; cost: number | null; netUsd: number | null; basisBefore: number | null; inTradeAfter: number | null;
  atRiskBefore: number | null; atRiskAfter: number | null; breakeven: number | null; movePct: number | null;
  tradeBreakeven: number | null; ahead: boolean;
};

/** ``desk_roll.roll_figures``: proceeds, cost, the net in dollars (``net`` × multiplier × count when both legs have one
 *  count, else cost − proceeds), the cost basis against the money in the trade after it, what is at risk before and
 *  after, the new contract's break-even at ``openPrice`` and the whole trade's, and the days added. */
export function rollFigures(kind: Side, oldStrike: number, newStrike: number, oldExpiry: string, newExpiry: string, o: {
  closeQty: number | null; openQty: number | null; multiplier: number | null; closePrice: number | null; openPrice: number | null;
  net?: number | null; costPerContract?: number | null; spot?: number | null;
}): RollFigures {
  const out: RollFigures = { daysAdded: daysBetween(oldExpiry, newExpiry), sameCount: null, net: null, netType: null, proceeds: null,
    cost: null, netUsd: null, basisBefore: null, inTradeAfter: null, atRiskBefore: null, atRiskAfter: null, breakeven: null,
    movePct: null, tradeBreakeven: null, ahead: false };
  const countsOk = isCount(o.closeQty) && isCount(o.openQty);
  out.sameCount = countsOk ? o.closeQty === o.openQty : null;
  const sign = kind === "call" ? 1 : -1;
  if (o.openPrice !== null && o.openPrice > 0) {
    out.breakeven = round(newStrike + sign * o.openPrice, 4);
    if (o.spot && o.spot > 0) out.movePct = round((out.breakeven - o.spot) / o.spot * 100, 2);
  }
  let net = o.net ?? null;
  if (net === null && out.sameCount !== false && o.closePrice !== null && o.openPrice !== null) net = o.openPrice - o.closePrice;
  if (net !== null && out.sameCount !== false) { out.net = round(Math.abs(signedCents(net)), 2); out.netType = netType(net); }
  if (!countsOk || !o.multiplier || o.multiplier <= 0) return out;
  const m = o.multiplier, closeQty = o.closeQty as number, openQty = o.openQty as number;
  if (o.closePrice !== null && o.closePrice >= 0) { out.proceeds = cents(o.closePrice * m * closeQty); out.atRiskBefore = out.proceeds; }
  if (o.openPrice !== null && o.openPrice > 0) out.cost = cents(o.openPrice * m * openQty);
  if (out.sameCount && net !== null) out.netUsd = signedCents(net * m * closeQty);
  else if (!out.sameCount && out.proceeds !== null && out.cost !== null) out.netUsd = round(out.cost - out.proceeds, 2);
  if (out.netUsd !== null && out.atRiskBefore !== null) out.atRiskAfter = round(out.atRiskBefore + out.netUsd, 2);
  if (o.costPerContract != null && o.costPerContract > 0) {
    out.basisBefore = cents(o.costPerContract * closeQty);
    if (out.netUsd !== null) {
      out.inTradeAfter = round(out.basisBefore + out.netUsd, 2);
      if (out.inTradeAfter <= 0) out.ahead = true;
      else out.tradeBreakeven = round(newStrike + sign * out.inTradeAfter / (m * openQty), 4);
    }
  }
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const strikeText = (n: number) => Number.isInteger(n) ? String(n) : String(+n.toFixed(2));
const monthDay = (iso: string) => { const [, m, d] = iso.split("-"); return `${MONTHS[Number(m) - 1]} ${Number(d)}`; };
const shortDate = (iso: string) => { const [y, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}/${y.slice(2)}`; };
const dollars = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** As Robinhood names an option: "NBIS $105 Call 12/19/26". */
export const optionLabel = (symbol: string, side: Side, strike: number, expiry: string) => `${symbol} $${strikeText(strike)} ${side === "call" ? "Call" : "Put"} ${shortDate(expiry)}`;

/** "NBIS 100C Nov 21 → 105C Dec 19". */
export function rollLabel(symbol: string, side: Side, oldStrike: number, oldExpiry: string, newStrike: number, newExpiry: string) {
  const k = side === "call" ? "C" : "P";
  return `${symbol} ${strikeText(oldStrike)}${k} ${monthDay(oldExpiry)} → ${strikeText(newStrike)}${k} ${monthDay(newExpiry)}`;
}

/** The roll in one line, as the server's ``desk_roll.sentence``; null without a net. */
export function rollSentence(symbol: string, side: Side, oldStrike: number, oldExpiry: string, newStrike: number, newExpiry: string, f: RollFigures): string | null {
  if (f.net === null && f.netUsd === null) return null;
  const usd = f.netUsd;
  const inAll = usd !== null ? ` (${dollars(Math.abs(usd))})` : "";
  const money = f.net !== null
    ? f.netType === "debit" ? `pay $${f.net.toFixed(2)} a share more${inAll}` : f.netType === "credit" ? `take in $${f.net.toFixed(2)} a share${inAll}` : "even money"
    : usd! > 0 ? `pay ${dollars(usd!)} more in all` : usd! < 0 ? `take in ${dollars(-usd!)} in all` : "even money";
  const parts = [money];
  if (f.breakeven !== null) parts.push(`break-even ${f.breakeven.toFixed(2)}`);
  const d = f.daysAdded;
  parts.push(d > 0 ? `${d} more day${d !== 1 ? "s" : ""}` : d === 0 ? "same expiry" : `${-d} fewer day${d !== -1 ? "s" : ""}`);
  return `Roll ${rollLabel(symbol, side, oldStrike, oldExpiry, newStrike, newExpiry)}: ${parts.join(", ")}.`;
}

/** What Copy all puts on the clipboard (``desk_roll.copy_text``). One count: Robinhood's roll screen, the close leg, the
 *  open leg, the net limit as a debit or credit, the quantity. Two counts: two orders, the close first. */
export function rollCopyText(t: { symbol: string; side: Side; oldStrike: number; oldExpiry: string; newStrike: number; newExpiry: string;
  closeQty: number; openQty: number; net: number | null; netType: NetType | null; closeLimit?: number | null; openLimit?: number | null }) {
  const old = optionLabel(t.symbol, t.side, t.oldStrike, t.oldExpiry), next = optionLabel(t.symbol, t.side, t.newStrike, t.newExpiry);
  if (t.closeQty === t.openQty) {
    const price = t.net !== null && t.netType ? `${t.net.toFixed(2)} ${t.netType}` : "(set it)";
    return [`${t.symbol} · Roll`, `Leg 1: Sell to close · ${old}`, `Leg 2: Buy to open · ${next}`, `Limit price ${price}`, `Quantity ${t.closeQty}`].join("\n");
  }
  const money = (p: number | null | undefined) => p != null ? p.toFixed(2) : "(set it)";
  return [`Order 1 of 2 · ${t.symbol} · Sell to close · ${old}`, `Limit price ${money(t.closeLimit)}`, `Contracts ${t.closeQty}`, "",
    `Order 2 of 2 · ${t.symbol} · Buy to open · ${next}`, `Limit price ${money(t.openLimit)}`, `Contracts ${t.openQty}`].join("\n");
}
