import { expect, test } from "@playwright/test";
import { closeEstimate, closingTicket } from "../lib/closingTicket";
import type { OptionTerms } from "../lib/optionStanding";

/* The closing ticket's numbers (lib/closingTicket.ts): pure arithmetic, no page. Every number is invented. */

const call: OptionTerms = {
  side: "call", strike: 250, expiry: "2026-11-20", direction: "long", quantity: 2, multiplier: 100, cost: 620,
  greeks: { delta: 0.38, theta: -0.31, iv: 0.44, as_of: 1_794_000_000, source: "robinhood" },
};
const put: OptionTerms = {
  side: "put", strike: 30, expiry: "2026-11-27", direction: "long", quantity: 3, multiplier: 100, cost: 95,
  greeks: { delta: -0.42, theta: -0.04, iv: 0.9, as_of: "2026-11-13 15:00:00", source: "tradier" },
};
const levels = { stop: 240, target: 258 };
const stock = { last: 247, at: 1_794_000_000 };
// Two calls at a 4.10 mark: $820 for the position.
const orcl = { symbol: "ORCL", terms: call, levels, account: "Roth IRA ••8267", stock, worth: 820, markLive: true };

test("a call: the mark moves by its delta toward the level, up at the target and down at the stop", () => {
  const atTarget = closingTicket({ ...orcl, at: "target" })!;
  // 4.10 + 0.38 x (258 − 247) = 8.28, above the 8.00 it is worth at expiry there.
  expect(atTarget).toEqual({ at: "target", symbol: "ORCL", side: "call", strike: 250, expiry: "2026-11-20", contracts: 2,
    account: "Roth IRA ••8267", level: 258, stock: 247, stockAt: 1_794_000_000, mark: 4.1, markLive: true, delta: 0.38, estimate: 8.28 });
  // 4.10 + 0.38 x (240 − 247) = 1.44.
  expect(closingTicket({ ...orcl, at: "stop" })!.estimate).toBe(1.44);
});

test("a put: a negative delta raises the estimate as the stock falls to the target and lowers it at the stop", () => {
  const apld = { symbol: "APLD", terms: put, levels: { stop: 29.5, target: 27.8 }, account: "Individual ••1234",
    stock: { last: 28.6, at: null }, worth: 3 * 148, markLive: false };
  // 1.48 − 0.42 x (27.8 − 28.6) = 1.816, below the 2.20 it is worth at expiry there: 2.20.
  expect(closingTicket({ ...apld, at: "target" })!.estimate).toBe(2.2);
  // Closer in, the delta's move shows: 1.48 − 0.42 x (28.5 − 28.6) = 1.522 → 1.52, above the 1.50 at expiry.
  expect(closeEstimate("put", 30, 1.48, -0.42, 28.6, 28.5)).toBe(1.52);
  // 1.48 − 0.42 x (29.5 − 28.6) = 1.102 → 1.10; intrinsic at 29.5 is 0.50.
  const atStop = closingTicket({ ...apld, at: "stop" })!;
  expect(atStop.estimate).toBe(1.1);
  expect(atStop.mark).toBe(1.48);
  expect(atStop.markLive).toBe(false);
});

test("never a zero price: a far stop floors at a cent, and the value at expiry floors the estimate", () => {
  expect(closeEstimate("call", 250, 0.3, 0.2, 247, 200)).toBe(0.01); // 0.30 − 9.40 is below zero
  expect(closeEstimate("call", 250, 4.1, 0.38, 247, 280)).toBe(30); // 4.10 + 12.54 = 16.64 < 30 at expiry
  expect(closeEstimate("put", 30, 1.48, -0.42, 28.6, 20)).toBe(10);
});

test("any missing input or a delta that does not fit the contract gives no ticket, so no button", () => {
  for (const at of ["target", "stop"] as const) {
    expect(closingTicket({ ...orcl, at, levels: { stop: null, target: null } })).toBeNull();
    expect(closingTicket({ ...orcl, at, levels: undefined })).toBeNull();
    expect(closingTicket({ ...orcl, at, account: null })).toBeNull();
    expect(closingTicket({ ...orcl, at, stock: null })).toBeNull();
    expect(closingTicket({ ...orcl, at, worth: null })).toBeNull();
    expect(closingTicket({ ...orcl, at, worth: 0 })).toBeNull();
    expect(closingTicket({ ...orcl, at, terms: { ...call, greeks: null } })).toBeNull();
    expect(closingTicket({ ...orcl, at, terms: { ...call, greeks: { ...call.greeks!, delta: null } } })).toBeNull();
    expect(closingTicket({ ...orcl, at, terms: { ...call, greeks: { ...call.greeks!, delta: -0.38 } } })).toBeNull(); // a call's is positive
    expect(closingTicket({ ...orcl, at, terms: { ...call, direction: "short" } })).toBeNull(); // only a held long
    expect(closingTicket({ ...orcl, at, terms: { ...call, quantity: 1.5 } })).toBeNull();
    expect(closingTicket({ ...orcl, at, terms: null })).toBeNull();
    expect(closingTicket({ ...orcl, at, symbol: null })).toBeNull();
  }
  expect(closingTicket({ ...orcl, at: "target", levels: { stop: 240, target: null } })).toBeNull();
  expect(closingTicket({ ...orcl, at: "stop", levels: { stop: 240, target: null } })).not.toBeNull(); // a plan without a target still closes at its stop
  expect(closeEstimate("put", 30, 1.48, 0.42, 28.6, 27)).toBeNull(); // a put's delta is negative
  expect(closeEstimate("call", 250, 4.1, 1.4, 247, 258)).toBeNull();
  expect(closeEstimate("call", 250, 0, 0.38, 247, 258)).toBeNull();
});
