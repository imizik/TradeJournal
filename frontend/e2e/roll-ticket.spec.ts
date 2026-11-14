import { expect, test } from "@playwright/test";
import { netType, rollCopyText, rollFigures, rollLabel, rollSentence, signedCents } from "../lib/rollTicket";

/* The roll ticket's arithmetic (lib/rollTicket.ts): the same hand-checked cases as the server's
   backend/tests/test_desk_roll.py, so the ticket recomputes exactly what the server first showed. Pure; no page. */

const NOV21 = "2026-11-21", DEC19 = "2026-12-19";

test("a call rolled up and out for a debit", () => {
  const f = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 3, openQty: 3, multiplier: 100, closePrice: 4, openPrice: 5.4, costPerContract: 250, spot: 98 });
  expect([f.net, f.netType, f.sameCount]).toEqual([1.4, "debit", true]);
  expect([f.proceeds, f.cost, f.netUsd]).toEqual([1200, 1620, 420]);
  expect([f.basisBefore, f.inTradeAfter, f.ahead, f.atRiskBefore, f.atRiskAfter]).toEqual([750, 1170, false, 1200, 1620]);
  expect([f.breakeven, f.movePct, f.tradeBreakeven, f.daysAdded]).toEqual([110.4, 12.65, 108.9, 28]);
});

test("a call rolled up for a credit, and puts either way", () => {
  const c = rollFigures("call", 100, 110, NOV21, DEC19, { closeQty: 2, openQty: 2, multiplier: 100, closePrice: 6, openPrice: 4.5, costPerContract: 300 });
  expect([c.net, c.netType, c.netUsd, c.atRiskAfter, c.inTradeAfter, c.tradeBreakeven, c.breakeven]).toEqual([1.5, "credit", -300, 900, 300, 111.5, 114.5]);
  const p = rollFigures("put", 90, 85, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 2.1, openPrice: 3, costPerContract: 450, spot: 92 });
  expect([p.net, p.netType, p.netUsd, p.breakeven, p.tradeBreakeven, p.inTradeAfter]).toEqual([0.9, "debit", 90, 82, 79.6, 540]);
  const pc = rollFigures("put", 95, 90, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 7, openPrice: 5.2, costPerContract: 400 });
  expect([pc.net, pc.netType, pc.netUsd, pc.inTradeAfter, pc.breakeven, pc.tradeBreakeven]).toEqual([1.8, "credit", -180, 220, 84.8, 87.8]);
});

test("a credit bigger than the cost leaves him ahead", () => {
  const f = rollFigures("call", 100, 120, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 8, openPrice: 1, costPerContract: 200 });
  expect([f.net, f.netType, f.netUsd, f.inTradeAfter, f.ahead, f.tradeBreakeven, f.breakeven]).toEqual([7, "credit", -700, -500, true, null, 121]);
});

test("taking out exactly what he put in is not ahead: the new strike is the break-even", () => {
  const f = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 3, openQty: 3, multiplier: 100, closePrice: 4, openPrice: 1.5, costPerContract: 250 });
  expect([f.netUsd, f.inTradeAfter, f.ahead, f.tradeBreakeven]).toEqual([-750, 0, false, 105]);
  const p = rollFigures("put", 100, 95, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 5, openPrice: 1, costPerContract: 400 });
  expect([p.inTradeAfter, p.ahead, p.tradeBreakeven]).toEqual([0, false, 95]);
});

test("the typed net sets the dollars; different counts are two orders", () => {
  const typed = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 3, openQty: 3, multiplier: 100, closePrice: 4, openPrice: 5.4, net: 1.25, costPerContract: 250 });
  expect([typed.net, typed.netUsd, typed.atRiskAfter, typed.inTradeAfter, typed.tradeBreakeven]).toEqual([1.25, 375, 1575, 1125, 108.75]);
  const credit = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 3, openQty: 3, multiplier: 100, closePrice: 4, openPrice: 5.4, net: -0.3, costPerContract: 250 });
  expect([credit.net, credit.netType, credit.netUsd, credit.atRiskAfter]).toEqual([0.3, "credit", -90, 1110]);
  const two = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 3, openQty: 2, multiplier: 100, closePrice: 4, openPrice: 5.4, net: 1, costPerContract: 250 });
  expect([two.sameCount, two.net, two.netType, two.proceeds, two.cost, two.netUsd, two.inTradeAfter, two.tradeBreakeven]).toEqual([false, null, null, 1200, 1080, -120, 630, 108.15]);
});

test("the multiplier scales; no count or no cost gives fewer figures; even money; days either way", () => {
  const ten = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 10, closePrice: 4, openPrice: 5.4, costPerContract: 25 });
  expect([ten.proceeds, ten.cost, ten.netUsd, ten.tradeBreakeven]).toEqual([40, 54, 14, 108.9]);
  const bare = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: null, openQty: null, multiplier: 100, closePrice: 4, openPrice: 5.4 });
  expect([bare.net, bare.netType, bare.breakeven, bare.proceeds, bare.netUsd, bare.basisBefore]).toEqual([1.4, "debit", 110.4, null, null, null]);
  const even = rollFigures("call", 100, 105, NOV21, NOV21, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 3, openPrice: 3 });
  expect([even.net, even.netType, even.netUsd, even.daysAdded]).toEqual([0, "even", 0, 0]);
  expect(rollFigures("call", 100, 100, DEC19, NOV21, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 5, openPrice: 3 }).daysAdded).toBe(-28);
  expect([signedCents(1.405), signedCents(-1.405), netType(0.004), netType(-0.004), netType(0.01), netType(-0.01)]).toEqual([1.41, -1.41, "even", "even", "debit", "credit"]);
});

test("the plain line and the copy block match the server's", () => {
  const f = rollFigures("call", 100, 105, NOV21, DEC19, { closeQty: 1, openQty: 1, multiplier: 100, closePrice: 4, openPrice: 5.4 });
  expect(rollLabel("NBIS", "call", 100, NOV21, 105, DEC19)).toBe("NBIS 100C Nov 21 → 105C Dec 19");
  expect(rollSentence("NBIS", "call", 100, NOV21, 105, DEC19, f)).toBe("Roll NBIS 100C Nov 21 → 105C Dec 19: pay $1.40 a share more ($140.00), break-even 110.40, 28 more days.");
  const c = rollFigures("put", 95, 90, NOV21, DEC19, { closeQty: 2, openQty: 2, multiplier: 100, closePrice: 7, openPrice: 5.2 });
  expect(rollSentence("NBIS", "put", 95, NOV21, 90, DEC19, c)).toBe("Roll NBIS 95P Nov 21 → 90P Dec 19: take in $1.80 a share ($360.00), break-even 84.80, 28 more days.");
  expect(rollCopyText({ symbol: "NBIS", side: "call", oldStrike: 100, oldExpiry: NOV21, newStrike: 105, newExpiry: DEC19, closeQty: 2, openQty: 2, net: 1.4, netType: "debit" }).split("\n"))
    .toEqual(["NBIS · Roll", "Leg 1: Sell to close · NBIS $100 Call 11/21/26", "Leg 2: Buy to open · NBIS $105 Call 12/19/26", "Limit price 1.40 debit", "Quantity 2"]);
  const two = rollCopyText({ symbol: "NBIS", side: "call", oldStrike: 100, oldExpiry: NOV21, newStrike: 105, newExpiry: DEC19, closeQty: 3, openQty: 2, net: null, netType: null, closeLimit: 4, openLimit: 5.4 });
  expect(two.split("\n")[0]).toBe("Order 1 of 2 · NBIS · Sell to close · NBIS $100 Call 11/21/26");
  expect(two).toContain("Order 2 of 2 · NBIS · Buy to open · NBIS $105 Call 12/19/26");
});
