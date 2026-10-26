import { expect, test, type Page } from "@playwright/test";
import type { ChartBar, ChartData, Interval } from "../lib/charts";
import { fakeChartSettings } from "./fixtures/chartSettings";

// "Plan a trade": the copilot's front door on Charts, Radar, the Dashboard, the phone tab bar and the
// plan capture sheet. The e2e backend runs with the lab off, so these tests stand in only for its status
// read (and an empty investigation list). Nothing here sends a turn.
const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const STEP: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };
const plan = (context: string, symbol = "", origin = "") => `/copilot-lab?${new URLSearchParams({ symbol, context, ...(origin ? { origin } : {}) })}`;

/** Candles for whatever the chart asks for, and a quote at 94.35. */
function workspace(url: string): ChartData {
  const query = new URL(url).searchParams;
  const symbol = query.get("symbol") ?? "MRVL";
  const now = Math.floor(Date.now() / 1000);
  const panels: ChartData["panels"] = {};
  for (const interval of (query.get("intervals") ?? "5m").split(",") as Interval[]) {
    const step = STEP[interval];
    const end = Math.floor(now / step) * step + step;
    panels[interval] = { markers: [], bars: Array.from({ length: 120 }, (_, i): ChartBar => {
      const close = 94 + Math.sin(i / 7);
      return { time: end - (120 - i) * step, end_time: end - (119 - i) * step, source: "alpaca_sip", open: close - 0.3, high: close + 0.8, low: close - 0.7, close,
        volume: 10000, ema9: close, ema20: close, ema50: close, ema200: close, vwap: close, rsi: 50, extended: false };
    }) };
  }
  const symbols = [...new Set([symbol, ...(query.get("watchlist") ?? "").split(",")].filter(Boolean))];
  return { symbol, session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels,
    quotes: symbols.map((s) => ({ symbol: s, name: s, last: 94.35, change: 1, change_percentage: 1, volume: 1, previous_close: 93.35, trade_time: now - 2 })),
    issues: [], intraday_as_of: now - 60, history_note: "Synthetic", fills: [], fills_truncated: false, extras: {},
    adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] } };
}

async function labOn(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
}

test.beforeEach(async ({ context, page, request }) => {
  await fakeChartSettings(context);
  await context.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: workspace(route.request().url()) }));
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
});

const statusAnswer = (page: Page) => page.waitForResponse((response) => response.url().includes("/copilot/status"));
const painted = (page: Page) => page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));

async function openMuEvent(page: Page) {
  await page.goto("/radar");
  await page.getByRole("region", { name: "New since your last visit" }).getByTestId("radar-event").getByRole("button").first().click();
  await expect(page.getByRole("region", { name: "Original evidence" })).toContainText("As first saved");
}

test("no Plan a trade anywhere while the lab is off", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const route of ["/", "/charts?symbol=NBIS", "/radar"]) {
    const answered = statusAnswer(page);
    if (route === "/radar") await openMuEvent(page); else await page.goto(route);
    await answered;
    await painted(page);
    await expect(page.getByRole("link", { name: /^Plan a trade/ })).toHaveCount(0);
  }
  await page.getByRole("link", { name: "Charts", exact: true }).click();
  await page.getByRole("button", { name: "Plan trade" }).first().click();
  await expect(page.getByRole("dialog", { name: "Plan trade" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Pressure-test with copilot" })).toHaveCount(0);
});

test("Charts' header plans the chart's symbol, interval and price, unsent", async ({ page }) => {
  let chats = 0;
  await labOn(page);
  await page.route("**/copilot/chat", (route) => { chats += 1; return route.abort(); });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=NBIS");
  const toolbar = page.locator(`header[aria-label="Chart toolbar"]`);
  const link = toolbar.getByRole("link", { name: "Plan a trade" });
  await expect(link).toHaveAttribute("href", plan("Plan a trade: NBIS from the 5m chart at 94.35", "NBIS", "chart"));
  await page.screenshot({ path: test.info().outputPath("plan-a-trade-charts-1440.png") });
  await page.setViewportSize({ width: 1380, height: 700 });
  expect((await toolbar.boundingBox())!.height).toBeLessThan(48); // a laptop still gets one row of controls
  await link.click();
  await expect(page).toHaveURL(/\/copilot-lab\?/);
  await expect(page.getByLabel("Message")).toHaveValue(/Plan a trade: NBIS from the 5m chart at 94\.35/);
  await page.waitForTimeout(300);
  expect(chats).toBe(0); // opened prefilled, never sent
});

test("Radar's event detail offers Plan a trade ahead of Ask copilot", async ({ page }) => {
  await labOn(page);
  await openMuEvent(page);
  const link = page.getByTestId("radar-event").getByRole("link", { name: "Plan a trade" });
  await expect(link).toHaveAttribute("href", /^\/copilot-lab\?symbol=MU&context=Plan\+a\+trade%3A\+Radar\+.+MU\+up\+4\.1%25.*&origin=radar_event%3A.+$/);
  const [plan, ask] = await Promise.all([link.boundingBox(), page.getByRole("button", { name: "Ask copilot · MU" }).boundingBox()]);
  expect(plan!.x).toBeLessThan(ask!.x);
});

test("the Dashboard's top and the phone tab bar open the lab to name the ticker", async ({ page }) => {
  await labOn(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const top = page.getByTestId("owner-dashboard").getByRole("link", { name: "Plan a trade" });
  await expect(top).toHaveAttribute("href", plan("Plan a trade:", "", "dashboard"));
  expect(await top.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)"); // primary, not a bare link
  await page.setViewportSize({ width: 375, height: 812 });
  const tab = page.getByRole("navigation", { name: "Main tabs" }).getByRole("link", { name: "Plan a trade" });
  await expect(tab).toHaveAttribute("href", plan("Plan a trade:", "", "manual"));
  await page.screenshot({ path: test.info().outputPath("plan-a-trade-dashboard-375.png") });
  await tab.click();
  await expect(page.getByLabel("Message")).toHaveValue(/Plan a trade:/);
});

test("the plan sheet's Pressure-test carries the typed plan to the copilot", async ({ page }) => {
  await labOn(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/charts?symbol=NBIS");
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = page.getByRole("dialog", { name: "Plan trade" });
  await sheet.getByRole("button", { name: "Buy stock" }).click();
  await sheet.getByRole("button", { name: /Discretionary/ }).click();
  const long = `Long the reclaim of 94; out on a 5m close back below it. ${"Then trail under each higher low. ".repeat(12)}`;
  await sheet.getByLabel("Plan note").fill(long);
  const href = await sheet.getByRole("link", { name: "Pressure-test with copilot" }).getAttribute("href");
  const context = new URLSearchParams(href!.split("?")[1]).get("context")!;
  expect(context).toMatch(/^Plan a trade: pressure-test my plan before I enter\. NBIS · Buy stock · Note: Long the reclaim of 94; out on a 5m close back below it\./);
  expect(context.length).toBe(300); // trimmed to the deep link's limit
  await sheet.getByRole("link", { name: "Pressure-test with copilot" }).focus();
  await page.keyboard.press("Enter"); // follows the link; it does not save the plan
  await expect(page).toHaveURL(/\/copilot-lab\?/);
  await expect(page.getByLabel("Message")).toHaveValue(/pressure-test my plan before I enter\. NBIS · Buy stock/);
});

test("Plan a trade fits a 375 px phone: thumb-sized, no sideways scroll", async ({ page }) => {
  await labOn(page);
  await page.setViewportSize({ width: 375, height: 812 });
  const fits = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  const thumb = async (link: ReturnType<Page["getByRole"]>) => {
    await expect(link).toBeInViewport();
    const box = (await link.boundingBox())!;
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(44);
  };

  await page.goto("/charts?symbol=NBIS");
  await thumb(page.locator(`header[aria-label="Chart toolbar"]`).getByRole("link", { name: "Plan a trade" }));
  await thumb(page.getByRole("navigation", { name: "Main tabs" }).getByRole("link", { name: "Plan a trade" }));
  await fits();
  await page.screenshot({ path: test.info().outputPath("plan-a-trade-charts-375.png") });
  await page.getByRole("button", { name: "Plan trade" }).first().click();
  const sheet = page.getByRole("dialog", { name: "Plan trade" });
  await thumb(sheet.getByRole("link", { name: "Pressure-test with copilot" }));
  await fits();
  await page.screenshot({ path: test.info().outputPath("plan-a-trade-sheet-375.png") });

  await page.goto("/");
  await thumb(page.getByTestId("owner-dashboard").getByRole("link", { name: "Plan a trade" }));
  await fits();

  await openMuEvent(page);
  const radar = page.getByTestId("radar-event").getByRole("link", { name: "Plan a trade" });
  await radar.scrollIntoViewIfNeeded();
  await thumb(radar);
  await fits();
  await page.screenshot({ path: test.info().outputPath("plan-a-trade-radar-375.png") });
});
