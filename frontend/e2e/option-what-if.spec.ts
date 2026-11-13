import { expect, test } from "@playwright/test";
import {
  RATE, EARNINGS_IV_KEPT, bsValue, dayAfterEarnings, impliedVol, normCdf, whatIfAt, whatIfCurve, whatIfModel, whatIfRange,
  yearsLeft, type OptionTerms, type WhatIfModel,
} from "../lib/optionStanding";

/* The desk's what-if (lib/optionStanding.ts): Black-Scholes from the standing's IV, checked against today's mark. */

const DAY = "2026-11-13"; // a Friday
const NOON = 12 * 60; // 12:00 New York
const call: OptionTerms = {
  side: "call", strike: 250, expiry: "2026-12-18", direction: "long", quantity: 2, multiplier: 100, cost: 800,
  greeks: { delta: 0.45, theta: -0.12, iv: 0.44, as_of: 1_794_000_000, source: "robinhood" },
};
const put: OptionTerms = { ...call, side: "put", strike: 30, cost: 150, quantity: 3, greeks: { ...call.greeks!, iv: 0.9 } };
const model = (terms: OptionTerms, price: number, worth: number | null) =>
  whatIfModel(terms, { price, worth, day: DAY, nyMinute: NOON }) as WhatIfModel;

test("Black-Scholes matches the textbook values and put-call parity", () => {
  expect(normCdf(0)).toBeCloseTo(0.5, 7);
  expect(normCdf(1.96)).toBeCloseTo(0.975, 4);
  expect(normCdf(-1)).toBeCloseTo(1 - normCdf(1), 7);
  // Hull's standard example: S = K = 100, a year, 20% vol, 5% rate.
  expect(bsValue("call", 100, 100, 1, 0.2, 0.05)).toBeCloseTo(10.4506, 3);
  expect(bsValue("put", 100, 100, 1, 0.2, 0.05)).toBeCloseTo(5.5735, 3);
  // C − P = S − K·e^(−rT) at the app's rate.
  const parity = bsValue("call", 247, 250, 0.1, 0.44) - bsValue("put", 247, 250, 0.1, 0.44);
  expect(parity).toBeCloseTo(247 - 250 * Math.exp(-RATE * 0.1), 6);
  // The IV that prices a value back out is the one that made it.
  expect(impliedVol("call", 247, 250, 0.1, bsValue("call", 247, 250, 0.1, 0.37))).toBeCloseTo(0.37, 5);
  expect(impliedVol("put", 28, 30, 0.05, bsValue("put", 28, 30, 0.05, 1.2))).toBeCloseTo(1.2, 5);
  expect(impliedVol("call", 247, 250, 0.1, 0.0001)).toBeNull(); // under any IV's price
});

test("at expiry the estimate is exactly the intrinsic value", () => {
  const m = model(call, 247, null);
  for (const price of [200, 250, 262.5]) {
    const at = whatIfAt(m, { price, day: "2026-12-18" });
    expect(at.share).toBeCloseTo(Math.max(0, price - 250), 9);
  }
  // 262.50 at expiry: 12.50 x 200 shares = $2,500, less the $1,600 cost = +$900 (+56.25%).
  const win = whatIfAt(m, { price: 262.5, day: "2026-12-18" });
  expect(win.value).toBeCloseTo(2500, 6);
  expect(win.pnl).toBeCloseTo(900, 6);
  expect(win.pnlPct).toBeCloseTo(56.25, 6);
  const p = model(put, 28, null);
  expect(whatIfAt(p, { price: 25, day: "2026-12-18" }).value).toBeCloseTo(1500, 6); // 5 x 300
  expect(whatIfAt(p, { price: 31, day: "2026-12-18" }).value).toBe(0);
});

test("the sign of P&L for a long call and a long put", () => {
  const c = model(call, 247, null);
  const p = model(put, 28, null);
  const day = "2026-11-27";
  // A long call gains as the stock rises and loses as it falls; a long put the other way round.
  expect(whatIfAt(c, { price: 280, day }).pnl!).toBeGreaterThan(0);
  expect(whatIfAt(c, { price: 220, day }).pnl!).toBeLessThan(0);
  expect(whatIfAt(p, { price: 22, day }).pnl!).toBeGreaterThan(0);
  expect(whatIfAt(p, { price: 34, day }).pnl!).toBeLessThan(0);
  // The worst a long option can do is lose what it cost.
  expect(whatIfAt(c, { price: 150, day: "2026-12-18" }).pnl).toBeCloseTo(-1600, 6);
  expect(whatIfAt(c, { price: 150, day: "2026-12-18" }).pnlPct).toBeCloseTo(-100, 6);
  // The curve rises with the stock for a call and falls for a put; time costs a call held at the same price.
  const up = whatIfCurve(c, { day, lo: 200, hi: 300 });
  expect(up.every((pt, i) => i === 0 || pt.y >= up[i - 1].y)).toBe(true);
  const down = whatIfCurve(p, { day, lo: 20, hi: 40 });
  expect(down.every((pt, i) => i === 0 || pt.y <= down[i - 1].y)).toBe(true);
  expect(whatIfAt(c, { price: 247, day: "2026-12-11" }).value).toBeLessThan(whatIfAt(c, { price: 247, day: DAY }).value);
});

test("today at today's price reproduces the mark; a mark the IV misses uses the mark's own IV", () => {
  const years = yearsLeft("2026-12-18", DAY, NOON);
  expect(years).toBeCloseTo((35 * 1440 + 240) / (365 * 1440), 9); // 35 days and four hours to the 16:00 close
  const fair = bsValue("call", 247, 250, years, 0.44);
  const m = model(call, 247, fair * 200 * 1.02); // a mark 2% above: close enough
  expect(m.ivSource).toBe("greeks");
  expect(m.iv).toBe(0.44);
  expect(whatIfAt(m, { price: 247, day: DAY }).share).toBeCloseTo(m.check!.model, 9);
  const off = model(call, 247, fair * 200 * 1.2); // 20% above: Robinhood's IV is not what this mark is priced at
  expect(off.ivSource).toBe("mark");
  expect(off.givenIv).toBe(0.44);
  expect(off.iv).toBeGreaterThan(0.44);
  expect(whatIfAt(off, { price: 247, day: DAY }).share).toBeCloseTo(fair * 1.2, 4); // now it reproduces the mark
  // A mark no IV can reach (40 a share on a call $47 in the money) shows no what-if rather than a wrong one.
  expect(whatIfModel({ ...call, strike: 200 }, { price: 247, worth: 40 * 200, day: DAY, nyMinute: NOON })).toEqual(
    expect.objectContaining({ reason: expect.stringContaining("cannot match") }));
});

test("If earnings is flat: the next weekday after the report, the stock unchanged, IV down to the stated share", () => {
  expect(dayAfterEarnings("2026-12-10", DAY, "2026-12-18")).toBe("2026-12-11"); // Thursday → Friday
  expect(dayAfterEarnings("2026-12-11", DAY, "2026-12-18")).toBe("2026-12-14"); // Friday → Monday
  expect(dayAfterEarnings("2026-12-18", DAY, "2026-12-18")).toBeNull(); // after expiry
  expect(dayAfterEarnings("2026-11-10", DAY, "2026-12-18")).toBeNull(); // already past
  expect(dayAfterEarnings(null, DAY, "2026-12-18")).toBeNull();
  const m = model(call, 247, null);
  const day = "2026-12-11";
  const crushed = whatIfAt(m, { price: 247, day, iv: m.iv * EARNINGS_IV_KEPT });
  const kept = whatIfAt(m, { price: 247, day });
  expect(crushed.value).toBeCloseTo(bsValue("call", 247, 250, 7 / 365, 0.44 * EARNINGS_IV_KEPT) * 200, 9);
  expect(crushed.value).toBeLessThan(kept.value); // the crush costs a long option
  expect(crushed.pnl!).toBeLessThan(0);
});

test("no IV, no price, a short or a missing cost", () => {
  expect(whatIfModel({ ...call, greeks: { ...call.greeks!, iv: null } }, { price: 247, worth: 800, day: DAY, nyMinute: NOON }))
    .toEqual({ reason: "no IV for this contract" });
  expect(whatIfModel({ ...call, greeks: null }, { price: 247, worth: 800, day: DAY, nyMinute: NOON })).toEqual({ reason: "no IV for this contract" });
  expect(whatIfModel(call, { price: null, worth: 800, day: DAY, nyMinute: NOON })).toEqual({ reason: "no stock price" });
  expect(whatIfModel({ ...call, direction: "short" }, { price: 247, worth: 800, day: DAY, nyMinute: NOON })).toBeNull();
  const noCost = model({ ...call, cost: null }, 247, null);
  const at = whatIfAt(noCost, { price: 260, day: "2026-12-18" });
  expect(at.value).toBeCloseTo(2000, 6);
  expect([at.pnl, at.pnlPct]).toEqual([null, null]);
});

test("the range takes in today's price, the strike and the plan's levels", () => {
  const m = model(call, 247, null);
  const { lo, hi } = whatIfRange(m, [180, 300]);
  expect(lo).toBeLessThan(180);
  expect(hi).toBeGreaterThan(300);
  const plain = whatIfRange(m);
  expect(plain.lo).toBeLessThan(247);
  expect(plain.hi).toBeGreaterThan(250);
  // Round ends on a round step, about 400 steps across.
  expect(plain.step).toBeGreaterThan(0);
  expect((plain.hi - plain.lo) / plain.step).toBeLessThanOrEqual(401);
  for (const end of [plain.lo, plain.hi]) expect(Math.abs(end / plain.step - Math.round(end / plain.step))).toBeLessThan(1e-6);
});
