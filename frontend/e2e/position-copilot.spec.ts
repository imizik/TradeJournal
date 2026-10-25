import { expect, test, type Page } from "@playwright/test";

// "Ask copilot about this position" on an open trade: primary inside the alert a give-back ping opens, secondary in the
// header otherwise, absent while the lab is off. The e2e backend runs with the lab off, so the switched-on cases stand in
// only for its status read (and an empty investigation list). Nothing here sends a turn.
type SeedTrade = { id: string; ticker: string; status: string; instrument_type: string; expiration: string; strike: number };
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const at = Date.parse("2026-10-21T15:02:00Z") / 1000;
const alert = { id: "10000000-0000-0000-0000-000000000001", kind: "giveback", detected_at: at, quoted_at: at - 5, contracts: 2, mark: 412,
  bid: 410, gain: 24, gain_pct: 0.03, peak_gain: 204, peak_gain_pct: 0.255, delivery: "sent", error: null, delivered_at: at + 2 };
const nowMark = { mark: 4.3, mark_per_contract: 430, basis: "mid", bid: 4.28, ask: 4.32, last: 4.3, provider: "tradier",
  quoted_at: Math.floor(Date.now() / 1000) - 30, open: 2, open_pnl: 60 };

async function labOn(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
}

async function openOption(page: Page): Promise<SeedTrade> {
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  const trade = trades.find(t => t.status === "open" && t.instrument_type === "option")!;
  await page.route(`**/trades/${trade.id}/phone-alerts`, route => route.fulfill({ json: { enabled: true, watch: null,
    alerts: [{ ...alert, contract: `${trade.ticker} ${trade.expiration} ${trade.strike}C` }] } }));
  await page.route(`**/charts/journal/trades/${trade.id}/mark`, route => route.fulfill({ json: nowMark }));
  return trade;
}

const ask = (page: Page) => page.getByRole("link", { name: "Ask copilot about this position", exact: true });
const href = (trade: SeedTrade) => `/copilot-lab?${new URLSearchParams({ symbol: trade.ticker, context: `Review this position: ${trade.id}` })}`;

async function settled(page: Page, answered: Promise<unknown>) {
  await expect(page.getByRole("heading", { name: "Trade Summary" })).toBeVisible();
  await answered;
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 390, height: 844 }); });

for (const view of ["the alert view", "the trade page"]) {
  test(`no Ask copilot on ${view} while the lab is off`, async ({ page }) => {
    const trade = await openOption(page);
    const answered = page.waitForResponse((response) => response.url().includes("/copilot/status"));
    await page.goto(view === "the alert view" ? `/trades/${trade.id}?alert=${alert.id}` : `/trades/${trade.id}`);
    await settled(page, answered);
    await expect(page.getByTestId(view === "the alert view" ? "position-now" : "trade-phone-alerts")).toBeVisible();
    await expect(ask(page)).toHaveCount(0);
  });
}

test("from a give-back ping, Ask copilot is the alert's primary action and opens the lab prefilled, unsent", async ({ page }) => {
  let chats = 0;
  await labOn(page);
  await page.route("**/copilot/chat", (route) => { chats += 1; return route.abort(); });
  const trade = await openOption(page);
  await page.goto(`/trades/${trade.id}?alert=${alert.id}`);
  const selected = page.getByTestId("selected-position-alert");
  const link = selected.getByRole("link", { name: "Ask copilot about this position", exact: true });
  await expect(link).toHaveAttribute("href", href(trade));
  await expect(link).toHaveClass(/bg-primary/);
  await expect(ask(page)).toHaveCount(1); // not repeated in the header
  const context = `Review this position: ${trade.id}`;
  expect(context.length).toBeLessThanOrEqual(300);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await selected.screenshot({ path: test.info().outputPath("ask-copilot-alert-390.png") });
  await link.click();
  await expect(page).toHaveURL(/\/copilot-lab\?/);
  await expect(page.getByLabel("Message")).toHaveValue(`Context: ${context}\n\n`);
  await page.waitForTimeout(300);
  expect(chats).toBe(0); // opening never sends a turn
});

test("on the open trade page without an alert, Ask copilot is a secondary header link", async ({ page }) => {
  await labOn(page);
  const trade = await openOption(page);
  await page.goto(`/trades/${trade.id}`);
  const link = ask(page);
  await expect(link).toHaveAttribute("href", href(trade));
  await expect(link).not.toHaveClass(/bg-primary/);
  await expect(page.getByRole("link", { name: "Review with copilot", exact: true })).toHaveCount(0); // that one is for closed trades
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("a closed trade offers no Ask copilot, only its review", async ({ page }) => {
  await labOn(page);
  const trades = await (await page.request.get("/api/backend/trades")).json() as SeedTrade[];
  const closed = trades.find(t => t.status === "closed" && t.instrument_type === "option")!;
  await page.goto(`/trades/${closed.id}`);
  await expect(page.getByRole("link", { name: "Review with copilot", exact: true })).toBeVisible();
  await expect(ask(page)).toHaveCount(0);
});
