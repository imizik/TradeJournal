import { expect, test } from "@playwright/test";
import {
  isBullish, isDebit, spreadCopyText, spreadFigures, spreadLabel, spreadNet, spreadSentence, spreadValue, spreadWords,
} from "../lib/spreadTicket";

/* Two-leg vertical spreads on the desk (lib/spreadTicket.ts): the same hand-checked cases as the server's
   backend/tests/test_desk_spread.py, so the ticket recomputes exactly what the server first showed. Pure; no page. */

test("a call debit spread: pay the limit, make the width less it", () => {
  const f = spreadFigures("call", 100, 110, 3.2, 2, 100, 95, 8);
  expect([f.type, f.width, f.cost, f.credit, f.maxLoss, f.maxGain, f.breakeven]).toEqual(["debit", 10, 640, null, 640, 1360, 103.2]);
  expect(f.movePct).toBeCloseTo(8.6316, 3);
  expect(f.vsExpected).toBeCloseTo(1.079, 3);
});

test("a call credit spread: take in the limit, risk the width less it", () => {
  const f = spreadFigures("call", 110, 100, 3.2, 1, 100, 95);
  expect([f.type, f.cost, f.credit, f.maxLoss, f.maxGain, f.breakeven]).toEqual(["credit", null, 320, 680, 320, 103.2]);
});

test("a put debit and a put credit spread", () => {
  const d = spreadFigures("put", 100, 90, 4, 3, 100, 98);
  expect([d.type, d.cost, d.maxLoss, d.maxGain, d.breakeven]).toEqual(["debit", 1200, 1200, 1800, 96]);
  const c = spreadFigures("put", 90, 100, 2.5, 1, 100, 101);
  expect([c.type, c.credit, c.maxGain, c.maxLoss, c.breakeven]).toEqual(["credit", 250, 250, 750, 97.5]);
});

test("the count and the multiplier scale the dollars; half strikes stay exact", () => {
  expect(spreadFigures("call", 102.5, 107.5, 1.85, 1, 100, null)).toMatchObject({ cost: 185, maxGain: 315, breakeven: 104.35, width: 5 });
  expect(spreadFigures("call", 102.5, 107.5, 1.85, 10, 100, null)).toMatchObject({ cost: 1850, maxGain: 3150 });
  expect(spreadFigures("call", 102.5, 107.5, 1.85, 1, 10, null)).toMatchObject({ cost: 18.5, maxGain: 31.5 });
  expect(spreadFigures("put", 90, 100, 2.5, null, 100, null)).toMatchObject({ cost: null, credit: null, maxLoss: null, maxGain: null, breakeven: 97.5 });
});

test("a limit at or over the width, or none, gives no figures", () => {
  for (const [kind, long, short, limit] of [["call", 100, 110, 10], ["call", 110, 100, 12], ["put", 100, 90, 10.5], ["put", 90, 100, 10]] as const) {
    const f = spreadFigures(kind, long, short, limit, 1, 100, 95);
    expect(f.warning).toContain("width");
    expect([f.cost, f.credit, f.maxLoss, f.maxGain, f.breakeven]).toEqual([null, null, null, null, null]);
  }
  expect(spreadFigures("call", 100, 110, null, 1, 100, 95)).toMatchObject({ breakeven: null, warning: null, type: "debit" });
});

test("worth and profit at the plan's levels at expiry", () => {
  const debit = spreadFigures("call", 100, 110, 3.2, 2, 100, 95, null, { entry: 105, target: 112, stop: 90 });
  expect(debit.atLevels).toEqual([{ role: "entry", price: 105, worth: 5, pnl: 360 }, { role: "target", price: 112, worth: 10, pnl: 1360 },
    { role: "stop", price: 90, worth: 0, pnl: -640 }]);
  const credit = spreadFigures("call", 110, 100, 3.2, 1, 100, 95, null, { target: 90, stop: 112 });
  expect(credit.atLevels.map(a => [a.role, a.worth, a.pnl])).toEqual([["target", 0, 320], ["stop", 10, -680]]);
  const put = spreadFigures("put", 90, 100, 2.5, 1, 100, 101, null, { entry: 98, target: 101, stop: 85 });
  expect(put.atLevels.map(a => [a.role, a.worth, a.pnl])).toEqual([["entry", 2, 50], ["target", 0, 250], ["stop", 10, -750]]);
});

test("the shape: debit or credit, bullish or bearish, and the worth at expiry", () => {
  expect([isDebit("call", 100, 110), isDebit("call", 110, 100), isDebit("put", 100, 90), isDebit("put", 90, 100)]).toEqual([true, false, true, false]);
  expect([isBullish("call", 100, 110), isBullish("put", 90, 100), isBullish("put", 100, 90), isBullish("call", 110, 100)]).toEqual([true, true, false, false]);
  expect([spreadValue("call", 100, 110, 104), spreadValue("call", 110, 100, 104), spreadValue("put", 90, 100, 50)]).toEqual([4, -4, -10]);
});

test("the net price at the mid and at the natural price", () => {
  // Debit: 3.20 − 1.00 = 2.20 at the mid; buy at the 3.30 ask, sell at the 0.97 bid = 2.33.
  expect(spreadNet("call", 100, 110, { bid: 3.1, ask: 3.3 }, { bid: 0.97, ask: 1.03 })).toEqual({ mid: 2.2, natural: 2.33 });
  // Credit: the same two contracts the other way: 2.20 taken in at the mid, 2.07 at the natural price.
  expect(spreadNet("call", 110, 100, { bid: 0.97, ask: 1.03 }, { bid: 3.1, ask: 3.3 })).toEqual({ mid: 2.2, natural: 2.07 });
  expect(spreadNet("put", 95, 90, { bid: 4, ask: 4.2 }, { bid: 2, ask: 2.1 })).toEqual({ mid: 2.05, natural: 2.2 });
  expect(spreadNet("call", 100, 110, { bid: null, ask: 3.3 }, { bid: 0.97, ask: 1.03 })).toBeNull();
  // A half-cent net (0.865) rounds up to 0.87, as the server's ticket does.
  expect(spreadNet("call", 100, 110, { bid: 1, ask: 1 }, { bid: 0.1, ask: 0.17 })).toEqual({ mid: 0.87, natural: 0.9 });
});

test("names, plan words, the copy block and the plain line", () => {
  expect(spreadLabel("NBIS", "call", 110, 100, "2026-12-19")).toBe("NBIS $100/$110 Call Credit Spread 12/19/26");
  expect(spreadWords("NBIS", "call", 100, 110, "2026-12-19")).toBe("NBIS 12/19/26 100/110C debit spread");
  expect(spreadWords("NBIS", "put", 90, 95, "2026-12-19")).toBe("NBIS 12/19/26 90/95P credit spread");
  expect(spreadWords("NBIS", "put", 97.5, 102.5, "2026-12-19").length).toBeLessThanOrEqual(40);
  expect(spreadCopyText({ symbol: "NBIS", kind: "call", expiry: "2026-12-19", long: 100, short: 110, limit: "3.20", contracts: "1" })).toBe(
    "NBIS · Call debit spread\nLeg 1: Buy · Call · Expiration 12/19/26 · Strike $100\nLeg 2: Sell · Call · Expiration 12/19/26 · Strike $110\nLimit price 3.20 debit\nQuantity 1");
  expect(spreadCopyText({ symbol: "NBIS", kind: "put", expiry: "2026-12-19", long: 90, short: 95, limit: "", contracts: "" })).toContain(
    "Limit price (set it)\nQuantity (set it)");
  const f = spreadFigures("call", 100, 110, 3.2, 1, 100, null);
  expect(spreadSentence("call", 100, 110, 3.2, 1, f)).toBe("Pay $3.20 a share for the 100/110 call spread, risk $320.00 to make $680.00, breakeven 103.20.");
  const c = spreadFigures("put", 90, 95, 1.5, 2, 100, null);
  expect(spreadSentence("put", 90, 95, 1.5, 2, c)).toBe("Take in $1.50 a share for the 90/95 put credit spread (2 of them), risk $700.00 to make $300.00, breakeven 93.50.");
  expect(spreadSentence("call", 100, 110, null, 1, spreadFigures("call", 100, 110, null, 1, 100, null))).toBeNull();
});
