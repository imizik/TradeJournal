import { expect, test } from "@playwright/test";
import type { DeskBook } from "../lib/desk";
import type { DeskTicks } from "../lib/deskTicks";
import { expiryNote, mixedStructure, optionStanding, worthNow, type OptionTerms } from "../lib/optionStanding";

/* The desk's option standing (lib/optionStanding.ts): pure arithmetic, no page. */

const DAY = "2026-11-11"; // a Wednesday
const call: OptionTerms = {
  side: "call", strike: 100, expiry: "2026-11-20", direction: "long", quantity: 2, multiplier: 100, cost: 310,
  greeks: { delta: 0.6, theta: -0.15, iv: 0.62, as_of: 1_794_000_000, source: "robinhood" },
};
const put: OptionTerms = {
  side: "put", strike: 30, expiry: "2026-11-27", direction: "long", quantity: 1, multiplier: 100, cost: 120,
  greeks: { delta: -0.35, theta: -0.04, iv: 0.9, as_of: "2026-11-11 14:00:00", source: "tradier" },
};
const close = (value: number | null | undefined, expected: number) => expect(value).toBeCloseTo(expected, 6);

test("a long call: break-even, distance, value at expiry against now, decay and delta for his size", () => {
  const s = optionStanding(call, { price: 105, worth: 1040, day: DAY })!;
  close(s.breakEven, 103.1); // 100 + 310 / 100
  expect(s.toBreakEven!.past).toBe(true); // a call is past break-even above it
  close(s.toBreakEven!.usd, -1.9);
  close(s.toBreakEven!.pct, -1.9 / 105 * 100);
  close(s.atExpiry, 1000); // (105 − 100) x 100 x 2
  close(s.worth, 1040);
  close(s.timeValue, 40);
  close(s.decayPerDay, -30); // −0.15 x 100 x 2
  close(s.perDollar, 120); // 0.6 x 100 x 2
  close(s.ivPct, 62);
  expect([s.daysLeft, s.expiryNote, s.contracts]).toEqual([9, null, 2]);
  // Below break-even the stock needs to rise: a positive move.
  const under = optionStanding(call, { price: 101, worth: 300, day: DAY })!;
  expect(under.toBreakEven!.past).toBe(false);
  close(under.toBreakEven!.usd, 2.1);
  close(under.atExpiry, 200);
  close(under.timeValue, 100);
});

test("a long put: break-even under the strike, past it only below, negative delta", () => {
  const s = optionStanding(put, { price: 31.5, worth: 50, day: DAY })!;
  close(s.breakEven, 28.8); // 30 − 120 / 100
  expect(s.toBreakEven!.past).toBe(false);
  close(s.toBreakEven!.usd, -2.7); // the stock must fall 2.70
  close(s.toBreakEven!.pct, -2.7 / 31.5 * 100);
  close(s.atExpiry, 0); // out of the money: nothing at expiry if it stays here
  close(s.timeValue, 50); // all of it is time value
  close(s.decayPerDay, -4);
  close(s.perDollar, -35); // loses about $35 per $1 up
  const deep = optionStanding(put, { price: 27, worth: 330, day: DAY })!;
  expect(deep.toBreakEven!.past).toBe(true);
  close(deep.atExpiry, 300);
  close(deep.timeValue, 30);
});

test("0–2 days left read in words; further out does not", () => {
  expect(expiryNote("2026-11-11", DAY)).toBe("Expires today");
  expect(expiryNote("2026-11-12", DAY)).toBe("Expires tomorrow");
  expect(expiryNote("2026-11-13", DAY)).toBe("Expires Friday");
  expect(expiryNote("2026-11-14", DAY)).toBeNull();
  expect(expiryNote("2026-11-10", DAY)).toBe("Expired");
  const zero = optionStanding({ ...call, expiry: DAY }, { price: 104, worth: 820, day: DAY })!;
  expect([zero.daysLeft, zero.expiryNote]).toEqual([0, "Expires today"]);
  close(zero.atExpiry, 800);
  close(zero.timeValue, 20);
});

test("missing inputs stay unavailable, never zero", () => {
  const bare = optionStanding({ ...call, greeks: null }, { price: 105, worth: 1040, day: DAY })!;
  expect([bare.decayPerDay, bare.perDollar, bare.ivPct, bare.greeks]).toEqual([null, null, null, null]);
  close(bare.breakEven, 103.1); // what can be computed still is
  close(bare.atExpiry, 1000);
  const partial = optionStanding({ ...call, greeks: { ...call.greeks!, theta: null, iv: 0 } }, { price: 105, worth: null, day: DAY })!;
  expect([partial.decayPerDay, partial.ivPct, partial.worth, partial.timeValue]).toEqual([null, null, null, null]);
  close(partial.perDollar, 120);
  const noPrice = optionStanding(call, { price: null, worth: 1040, day: DAY })!;
  expect([noPrice.atExpiry, noPrice.toBreakEven, noPrice.timeValue, noPrice.curve]).toEqual([null, null, null, null]);
  const noCost = optionStanding({ ...call, cost: null }, { price: 105, worth: 1040, day: DAY })!;
  expect([noCost.breakEven, noCost.toBreakEven, noCost.curve]).toEqual([null, null, null]);
  close(noCost.atExpiry, 1000);
});

test("a short, a malformed contract or a ticker with a short leg gets nothing", () => {
  expect(optionStanding({ ...call, direction: "short" }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding({ ...call, direction: null }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding({ ...call, side: null }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding({ ...call, quantity: 0 }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding({ ...call, strike: null }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding({ ...call, multiplier: null }, { price: 105, worth: 1040, day: DAY })).toBeNull();
  expect(optionStanding(null, { price: 105, worth: 1040, day: DAY })).toBeNull();
  const shortLeg = { ...call, strike: 110, direction: "short" };
  expect(mixedStructure("NBIS", call, [{ symbol: "NBIS", option: call }, { symbol: "NBIS", option: shortLeg }])).toBe(true);
  expect(mixedStructure("NBIS", call, [{ symbol: "NBIS", option: call }, { symbol: "APLD", option: shortLeg }])).toBe(false);
  expect(mixedStructure("NBIS", call, [{ symbol: "NBIS", option: call }, { symbol: "NBIS", option: null }])).toBe(false);
});

test("the expiry line: max loss is what was paid, zero at break-even", () => {
  const { curve } = optionStanding(call, { price: 105, worth: 1040, day: DAY })!;
  expect(curve!.lo).toBeLessThan(100);
  expect(curve!.hi).toBeGreaterThan(105);
  close(curve!.points[0].pnl, -620); // below the strike: the 2 x $310 paid
  const at = (price: number) => curve!.points.reduce((best, p) => Math.abs(p.price - price) < Math.abs(best.price - price) ? p : best);
  expect(Math.sign(at(110).pnl)).toBe(1);
  const { curve: putCurve } = optionStanding(put, { price: 31.5, worth: 50, day: DAY })!;
  close(putCurve!.points.at(-1)!.pnl, -120); // above the strike a put expires worthless
});

test("worth now: the live option mark, else the book's mark, else cost plus P&L", () => {
  const book: DeskBook = { usd: 180, pct: 29, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", stop_pct: null,
    tick: { quote: "NBIS261120C00100000", scale: 100, cost: 310, quantity: 2, sign: 1 }, option: call };
  const now = Date.now() / 1000;
  const closed: DeskTicks = { rows: {}, open: false, checked: now };
  close(worthNow(book, closed), 800); // 310 x 2 + 180
  close(worthNow({ ...book, mark: 420, quantity: 2 }, closed), 840);
  const live: DeskTicks = { rows: { NBIS261120C00100000: { last: 5.2, change_pct: null, prev_close: null, at: now } }, open: true, checked: now };
  close(worthNow(book, live), 1040);
  expect(worthNow({ ...book, usd: null, tick: null }, closed)).toBeNull();
});
