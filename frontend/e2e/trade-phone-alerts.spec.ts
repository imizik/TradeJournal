import { expect, test, type Page } from "@playwright/test";

// Open-trade phone alerts on the trade page. The seeded backend has them switched off; the
// switched-on case fakes the one read, since firing needs live option quotes (covered in pytest).
type SeedTrade = { id: string; ticker: string; status: string; instrument_type: string };

async function openAapl(page: Page): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  return trades.find(t => t.ticker === "AAPL" && t.status === "open" && t.instrument_type === "option")!;
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

test("switched off with nothing sent: the trade page shows no phone alerts section", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const trade = await openAapl(page);
  const read = page.waitForResponse(r => r.url().includes(`/trades/${trade.id}/phone-alerts`));
  await page.goto(`/trades/${trade.id}`);
  expect(await (await read).json()).toEqual({ enabled: false, alerts: [], watch: null });
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await expect(page.getByTestId("trade-phone-alerts")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("switched on: the watch state and each alert's delivery read plainly at phone width", async ({ page }) => {
  const trade = await openAapl(page);
  const at = Date.parse("2026-10-21T15:02:00Z") / 1000;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: {
    enabled: true,
    watch: { peak_gain: 1109, peak_gain_pct: 0.38, armed: true, peak_at: at - 1800 },
    alerts: [
      { kind: "giveback", detected_at: at, contracts: 6, mark: 412, bid: 410, gain: 40, gain_pct: 0.01, peak_gain: 1109,
        peak_gain_pct: 0.38, delivery: "sent", error: null, delivered_at: at + 2 },
      { kind: "expiry_final", detected_at: at + 3600, contracts: 6, mark: null, bid: null, gain: null, gain_pct: null,
        peak_gain: null, peak_gain_pct: null, delivery: "unknown", error: "timed out", delivered_at: null },
    ],
  } }));
  await page.goto(`/trades/${trade.id}`);
  const section = page.getByTestId("trade-phone-alerts");
  await expect(section).toContainText("Watching for a give-back: best so far +$1,109 (+38%)");
  await expect(section).toContainText("Gave back its gain · Oct 21, 11:02 AM · sent to your phone");
  await expect(section).toContainText("Was up +$1,109 (+38%), at +$40 (+1%) with 6 open");
  await expect(section).toContainText("30 minutes to the close · Oct 21, 12:02 PM · may have reached your phone, so it was not resent");
  await expect(section).toContainText("no live quote, 6 open");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await section.screenshot({ path: test.info().outputPath("trade-phone-alerts-phone.png") });
});
