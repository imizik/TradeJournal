import { expect, test, type Page } from "@playwright/test";

// "Review with copilot" on the trade page. The e2e backend runs with the lab off, so the switched-on cases stand in
// only for its status read (and an empty investigation list). Nothing here sends a turn.
type SeedTrade = { id: string; ticker: string; status: string; instrument_type: string };
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};

async function labOn(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
}

async function seeded(page: Page, status: "open" | "closed"): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  return trades.find(t => t.status === status && t.instrument_type === "option")!;
}

const reviewLink = (page: Page) => page.getByRole("link", { name: "Review with copilot", exact: true });

test("no Review with copilot link while the lab is off", async ({ page }) => {
  const trade = await seeded(page, "closed");
  const answered = page.waitForResponse((response) => response.url().includes("/copilot/status"));
  await page.goto(`/trades/${trade.id}`);
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await answered;
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await expect(reviewLink(page)).toHaveCount(0);
});

test("an open trade offers no review, even with the lab on", async ({ page }) => {
  await labOn(page);
  const trade = await seeded(page, "open");
  const answered = page.waitForResponse((response) => response.url().includes("/copilot/status"));
  await page.goto(`/trades/${trade.id}`);
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await answered;
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await expect(reviewLink(page)).toHaveCount(0);
});

test("a closed trade's Review with copilot opens the lab prefilled with the trade, unsent", async ({ page }) => {
  let chats = 0;
  await labOn(page);
  await page.route("**/copilot/chat", (route) => { chats += 1; return route.abort(); });
  await page.setViewportSize({ width: 390, height: 844 });
  const trade = await seeded(page, "closed");
  await page.goto(`/trades/${trade.id}`);
  const link = reviewLink(page);
  const context = `Review this trade: ${trade.id}`;
  expect(context.length).toBeLessThanOrEqual(300);
  await expect(link).toHaveAttribute("href", `/copilot-lab?${new URLSearchParams({ symbol: trade.ticker, context })}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath("trade-review-link-390.png") });
  await link.click();
  await expect(page).toHaveURL(/\/copilot-lab\?/);
  await expect(page.getByLabel("Message")).toHaveValue(`Context: ${context}\n\n`);
  await page.waitForTimeout(300);
  expect(chats).toBe(0); // opening never sends a turn
});
