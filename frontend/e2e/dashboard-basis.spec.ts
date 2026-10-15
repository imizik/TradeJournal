import { expect, test } from "@playwright/test";
import type { Fill, PositionQuote, Trade } from "../lib/api";
import { buildOpenPositionMeta, computeUnrealizedPnl, getPositionMarketValue } from "../lib/dashboard";

const trade = { contracts: 900, instrument_type: "stock", avg_entry_premium: .85, opened_at: "2026-10-01T10:00:00", realized_pnl: 45 } as Trade;
const fill = (id: string, side: string, contracts: number, price: number, executed_at = "2026-10-01T10:00:00") => ({ id, side, contracts, price, executed_at } as Fill);
const quote = { underlying_price: 1.20, option_mid: 1.5 } as PositionQuote;

test("partial FIFO stock close uses the remaining lot rather than the all-entry average", () => {
  // The committed seed: 450 @ .90, 450 @ .80, close the first 450 @ 1.00.
  const fills = [fill("c", "sell", 450, 1, "2026-10-02T10:00:00"), fill("b", "buy", 450, .80), fill("a", "buy", 450, .90)];
  const meta = buildOpenPositionMeta(trade, fills);
  expect(meta).toMatchObject({ qtyLeft: 450, openedQty: 900, exitedQty: 450, capitalLeft: 360, avgCostLeft: .80, realizedSoFar: 45 });
  expect(computeUnrealizedPnl(trade, meta, quote)).toBeCloseTo(180, 8);
  expect(getPositionMarketValue(trade, meta, quote)).toBe(540);
  expect(meta.lastActivityAt).toBe("2026-10-02T10:00:00");
  expect(fills[0].id).toBe("c"); // Sorting never mutates API data.
});

test("same-minute opens precede closes, then fill ID resolves entry lot order", () => {
  const meta = buildOpenPositionMeta(trade, [fill("0", "sell", 450, 1), fill("b", "buy", 450, .8), fill("a", "buy", 450, .9)]);
  expect(meta.capitalLeft).toBe(360);
  expect(meta.avgCostLeft).toBe(.8);
});

test("option marks convert once and short positions keep credit minus marked liability", () => {
  const option = { ...trade, instrument_type: "option", contracts: 3, avg_entry_premium: 200 };
  const short = buildOpenPositionMeta(option, [fill("a", "sell_to_open", 1, 100), fill("b", "sell_to_open", 2, 250), fill("c", "buy_to_close", 1, 80, "2026-10-02T10:00:00")]);
  expect(short).toMatchObject({ direction: "short", qtyLeft: 2, capitalLeft: 500, avgCostLeft: 250 });
  expect(computeUnrealizedPnl(option, short, quote)).toBe(200); // (250 - 1.5*100)*2
  const long = buildOpenPositionMeta(option, [fill("a", "buy_to_open", 1, 100), fill("b", "buy_to_open", 2, 250), fill("c", "sell_to_close", 1, 80, "2026-10-02T10:00:00")]);
  expect(computeUnrealizedPnl(option, long, quote)).toBe(-200);
});

test("fractional shares, scale-ins after trims and full closes preserve remaining basis", () => {
  const meta = buildOpenPositionMeta(trade, [fill("a", "buy", 1.5, 10), fill("b", "sell", 1, 12, "2026-10-02T10:00:00"), fill("c", "buy", .25, 20, "2026-10-03T10:00:00")]);
  expect(meta.qtyLeft).toBe(.75);
  expect(meta.capitalLeft).toBe(10);
  expect(meta.avgCostLeft).toBeCloseTo(10 / .75, 8);
  const closed = buildOpenPositionMeta(trade, [fill("a", "buy", 1, 10), fill("b", "sell", 1, 12, "2026-10-02T10:00:00")]);
  expect(closed.capitalLeft).toBe(0);
  expect(closed.avgCostLeft).toBeNull();
});

test("missing or invalid lot evidence leaves basis and P&L unavailable", () => {
  for (const fills of [[], [fill("a", "buy", 1, NaN)], [fill("a", "buy", 1, 10), fill("b", "sell", 2, 12, "2026-10-02T10:00:00")]]) {
    const meta = buildOpenPositionMeta(trade, fills);
    expect(meta.capitalLeft).toBeNull();
    expect(computeUnrealizedPnl(trade, meta, quote)).toBeNull();
  }
  const meta = buildOpenPositionMeta(trade, [fill("a", "buy", 1, 10)]);
  expect(computeUnrealizedPnl(trade, meta, undefined)).toBeNull();
});
