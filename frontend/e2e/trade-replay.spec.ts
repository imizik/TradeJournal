import { expect, test, type Page } from "@playwright/test";

// The trade page's Replay card. The seeded backend has no market data, so the replay read is faked with one
// morning of minute bars; building the body (bars, VWAP, P&L, cut) is covered in backend tests/test_trade_replay.py.
type SeedTrade = { id: string; ticker: string; status: string; instrument_type: string };

const OPEN = Date.parse("2026-11-17T14:30:00Z") / 1000; // 9:30 New York
const at = (minute: number) => OPEN + minute * 60;

function body(trade: SeedTrade) {
  // 120 minute bars drifting down; bought 2 at $2.00 at 9:40, added 1 at $1.50 at 10:10, sold 3 at $1.20 at 11:00.
  const bars = Array.from({ length: 120 }, (_, i) => {
    const close = 50 - i * 0.02;
    const held = i < 10 ? 0 : i < 40 ? 2 : i < 90 ? 3 : 0;
    const mark = 200 - i * 1.2;
    const pnl = i < 10 ? null : i < 40 ? 2 * (mark - 200) : i < 90 ? 3 * mark - 550 : -190;
    return { time: at(i), open: close, high: close + 0.05, low: close - 0.05, close, volume: 1000, vwap: 49.5,
      held, avg_cost: held ? (i < 40 ? 200 : 183.3333) : null, realized: i < 90 ? 0 : -190, pnl };
  });
  return {
    trade_id: trade.id, ticker: trade.ticker, instrument_type: "option", state: "ok", reason: null, interval_minutes: 1,
    contract: `${trade.ticker}261118C00100000`, multiplier: 100, direction: "long", realized_pnl: -190, bars,
    option_bars: bars.map((b, i) => ({ time: b.time, open: 2 - i * 0.012, high: 2 - i * 0.012, low: 2 - i * 0.012, close: 2 - i * 0.012 })),
    option_note: null,
    fills: [
      { id: "f1", time: at(10), entry: true, side: "buy_to_open", contracts: 2, price: 200, label: "Bought 2 @ $2.00" },
      { id: "f2", time: at(40), entry: true, side: "buy_to_open", contracts: 1, price: 150, label: "Bought 1 @ $1.50" },
      { id: "f3", time: at(90), entry: false, side: "sell_to_close", contracts: 3, price: 120, label: "Sold 3 @ $1.20" },
    ],
    pings: [{ time: at(70) + 12, kind: "hold_hour", title: null, sent: true }, { time: at(15), kind: "no_exit", title: null, sent: false }],
    cut: { rule: "deep_red", time: at(71), price: 115 },
    cut_line: { price: 140, crossed: { time: at(50), state: "ignored", held: 3, cost: 12 } },
    tag: { setup: "vwap_reclaim", mistakes: ["added_below_cost", "held_past_cut"], primary_mistake: "added_below_cost",
      broke_cut_rule: true, rule_broken_computed: true, grade: "D", confidence: "high", rationale: "Averaged down into a short-dated loser.", model: "opus" },
  };
}

async function closedOption(page: Page): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  return trades.find(t => t.status !== "open" && t.instrument_type === "option")!;
}

for (const width of [390, 1280]) {
  test(`a closed trade replays bar by bar with fills, pings, the cut and P&L at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    const trade = await closedOption(page);
    await page.route(`**/trades/${trade.id}/replay`, route => route.fulfill({ json: body(trade) }));
    await page.goto(`/trades/${trade.id}`);
    const card = page.getByTestId("trade-replay");
    await expect(card.getByTestId("trade-replay-chart").locator("canvas").first()).toBeVisible();
    await expect(card.getByTestId("trade-replay-tag")).toContainText("Setup: vwap reclaim");
    await expect(card.getByTestId("trade-replay-tag")).toContainText("Mistake: added below cost");
    await expect(card.getByTestId("trade-replay-tag")).toContainText("Broke the cut rule");

    // It opens on the first buy.
    const readout = card.getByTestId("trade-replay-readout");
    await expect(readout).toContainText("9:40 AM ET");
    await expect(readout).toContainText("2 contracts @ $2.00");
    await expect(card.getByRole("list", { name: "At this bar" })).toContainText("Bought 2 @ $2.00");

    // Next event: the no-exit ping that was held, then the add.
    await card.getByRole("button", { name: "Next event" }).click();
    await expect(card.getByRole("list", { name: "At this bar" })).toContainText("No exit order ping (not sent)");
    await card.getByRole("button", { name: "Next event" }).click();
    await expect(readout).toContainText("3 contracts @ $1.83");

    // A row in the list jumps the playhead; the cut lands where the rules said sell.
    await card.getByRole("button", { name: /Cut rule: deep red past the hour, sell here at \$1\.15/ }).click();
    await expect(readout).toContainText("10:41 AM ET");
    await expect(readout).toContainText("P&L (best -$24)");
    await expect(card.getByRole("button", { name: /Cut line \$1\.40 hit with 3 open; holding on cost -\$12/ })).toBeVisible();

    // Scrubbing to the end shows the realized result; play from the end restarts and moves.
    await card.getByTestId("trade-replay-scrub").fill("119");
    await expect(readout).toContainText("Flat");
    await expect(readout).toContainText("-$190");
    await card.getByRole("button", { name: "Back to the first bar" }).click();
    await expect(readout).toContainText("9:30 AM ET");
    await expect(readout).toContainText("Not in yet");
    await card.getByRole("button", { name: "Play", exact: true }).click();
    await expect(readout).not.toContainText("9:30 AM ET");
    await card.getByRole("button", { name: "Pause", exact: true }).click();

    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await card.getByTestId("trade-replay-scrub").fill("75");
    await page.getByRole("region", { name: "Replay" }).screenshot({ path: test.info().outputPath(`trade-replay-${width}.png`) });
    expect(errors).toEqual([]);
  });
}

test("an open trade shows no replay, and a trade the feed has no bars for says so", async ({ page }) => {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  const open = trades.find(t => t.status === "open")!;
  await page.goto(`/trades/${open.id}`);
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Replay" })).toHaveCount(0);

  const closed = trades.find(t => t.status !== "open")!;
  await page.route(`**/trades/${closed.id}/replay`, route => route.fulfill({ json: {
    trade_id: closed.id, ticker: closed.ticker, instrument_type: closed.instrument_type, state: "no_bars", reason: "No minute bars for this trade's days yet." } }));
  await page.goto(`/trades/${closed.id}`);
  await expect(page.getByRole("region", { name: "Replay" })).toContainText("No minute bars for this trade's days yet.");
});
