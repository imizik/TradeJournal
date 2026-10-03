import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { DEFAULT_SETTINGS, STORAGE_KEY } from "../lib/charts";

// Only market candles/quotes/settings are stubbed. Journal values below come
// through the real private endpoint from scripts/seed_dev_data.py.
test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(({ key, settings }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(settings));
  }, { key: STORAGE_KEY, settings: { ...DEFAULT_SETTINGS, symbol: "NVDA", watchlist: ["NVDA", "AAPL", "TSLA", "SPY", "AMD"] } });
  await fakeChartSettings(context, { revision: 1, data: { symbol: "NVDA", watchlist: ["NVDA", "AAPL", "TSLA", "SPY", "AMD"] } });
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const symbol = query.get("symbol");
    const now = Math.floor(Date.now() / 1000);
    const bars = Array.from({ length: 10 }, (_, i) => ({ time: 1789392600 + i * 300, end_time: 1789392900 + i * 300, open: 100, high: 102, low: 99, close: 101, volume: 1000, extended: false }));
    await route.fulfill({ json: { symbol, session: "extended", provider: "Fixture", delayed: false, refresh_seconds: 15,
      checked_at: now, fetched_at: { intraday: now }, intraday_as_of: now, issues: [], quotes: [], fills: [], fills_truncated: false,
      panels: Object.fromEntries((query.get("intervals") ?? "5m").split(",").map((interval) => [interval, { bars, markers: [] }])), extras: {} } });
  });
  await page.route("**/api/backend/charts/stream?**", (route) => route.fulfill({ status: 503, body: "Fixture has no stream" }));
});

const panel = (page: Page) => page.getByRole("region", { name: "Symbol info", exact: true });
const choose = (page: Page, symbol: string) => page.getByRole("button", { name: `Chart ${symbol}`, exact: true }).click();

test("You renders seeded completed results, account-separated open trades and an empty symbol", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.goto("/charts");
  const info = panel(page);
  await expect(info.getByRole("tab", { name: "You", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(info.locator("dl")).toContainText("$1,300.00");
  await expect(info.locator("dl")).toContainText("100.0%");
  await expect(info.locator("dl")).toContainText("7.2 d");
  await expect(info).toContainText("Journal · all accounts");
  const tradeLink = info.getByRole("link").first();
  await expect(tradeLink).toHaveAttribute("href", /\/trades\/[0-9a-f-]+$/);
  await expect(info).toContainText("No open positions");
  expect(reads).toHaveLength(1);
  await page.screenshot({ path: "/tmp/tradejournal-symbol-info-desktop.png", fullPage: true });
  await choose(page, "AAPL");
  await expect(info).toContainText("Open positions · 2 trades");
  await expect(info).toContainText("8267");
  await expect(info).toContainText("1113");
  await expect(info.locator("dl")).not.toContainText("$400.00"); // partial exit excluded from completed P&L
  expect(reads).toHaveLength(2);
  await choose(page, "TSLA");
  await expect(info.locator("dl")).toContainText("-$300.00");
  await expect(info.locator("dl")).toContainText("0.0%");
  await choose(page, "SPY");
  await expect(info).toContainText("No trades on this symbol");
  expect(reads).toHaveLength(4);
});

test("placeholder tabs persist per device and rapid symbol steps fetch only the settled symbol", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.goto("/charts");
  const info = panel(page);
  await expect(info.locator("dl")).toContainText("$1,300.00");
  for (const tab of ["Overview", "News", "Events", "Forecast"]) {
    await info.getByRole("tab", { name: tab, exact: true }).click();
    await expect(info).toContainText(`${tab} is coming soon.`);
  }
  await page.reload();
  await expect(info.getByRole("tab", { name: "Forecast", exact: true })).toHaveAttribute("aria-selected", "true");
  expect(reads).toHaveLength(1);
  // Install the clock after hydration, then advance less than the debounce.
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await info.getByRole("tab", { name: "You", exact: true }).click();
  await choose(page, "SPY");
  await page.clock.runFor(100);
  await choose(page, "AMD");
  await page.clock.runFor(301);
  await expect(info).toContainText("No trades on this symbol");
  expect(reads).toHaveLength(2);
  expect(reads[1]).toContain("/AMD/you");
});

test("a failed journal request retries without replacing charts", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/backend/charts/symbol/NVDA/you", async (route) => {
    attempts += 1;
    if (attempts === 1) await route.fulfill({ status: 503, body: "Unavailable" });
    else await route.continue();
  });
  await page.goto("/charts");
  await expect(panel(page).getByRole("alert")).toContainText("Journal unavailable");
  await panel(page).getByRole("button", { name: "Retry journal" }).click();
  await expect(panel(page).locator("dl")).toContainText("$1,300.00");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  expect(attempts).toBe(2);
});

test("a late result from the previous symbol cannot overwrite the current journal", async ({ page }) => {
  let started = false;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/backend/charts/symbol/NVDA/you", async (route) => {
    started = true;
    await pending;
    await route.fulfill({ json: { symbol: "NVDA", total_trades: 0, source: "OLD RESULT", as_of: new Date().toISOString() } }).catch(() => {});
  });
  await page.goto("/charts");
  await expect.poll(() => started).toBe(true);
  await choose(page, "AAPL");
  await expect(panel(page)).toContainText("Open positions · 2 trades");
  release();
  await expect(panel(page)).not.toContainText("OLD RESULT");
  await expect(panel(page)).toContainText("Open positions · 2 trades");
});

test("390px starts collapsed, expands cleanly, and follows watchlist visibility in immersive mode", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.goto("/charts");
  const info = panel(page);
  const disclosure = info.getByRole("button", { name: "NVDA symbol info" });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  expect(reads).toHaveLength(0);
  await disclosure.click();
  await expect(info.locator("dl")).toContainText("$1,300.00");
  await expect(info.getByRole("tab", { name: "Overview", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/tradejournal-symbol-info-phone.png", fullPage: true });
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await expect(info).toHaveCount(0);
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(info).toBeVisible();
  await expect(info.getByRole("button", { name: "NVDA symbol info" })).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Exit full-screen charts" }).click();
});
