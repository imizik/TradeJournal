import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { realisticPanels } from "./fixtures/realisticBars";
import { fakeChartSettings } from "./fixtures/chartSettings";
import type { ChartData, Interval } from "../lib/charts";

// Opt-in production-build benchmark. Fixed service latency isolates navigation
// and reuse from provider/weather variability; it is not a live-data benchmark.
test.skip(!process.env.TJ_NAV_BENCHMARK, "Set TJ_NAV_BENCHMARK to an output directory");
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const paint = (page: Page) => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

for (const layout of ["single", "multi"] as const) test(`navigation load benchmark ${layout}`, async ({ page, context, request }, info) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fakeChartSettings(context, { data: { layout, symbol: "MRVL", newsHidden: true } });
  await context.route("**/api/backend/charts/settings", async route => { await delay(400); await route.fallback(); });
  const panels = realisticPanels(["1m", "5m", "15m", "1h", "1D"]);
  let workspaceReads = 0, documentReads = 0;
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", r => { if (r.resourceType() === "document") documentReads++; });
  await context.route("**/api/backend/charts/captures?**", r => r.fulfill({ json: { captures: [] } }));
  await context.route("**/api/backend/charts/stream?**", r => r.abort());
  await context.route("**/api/backend/charts/workspace?**", async route => {
    workspaceReads++;
    const q = new URL(route.request().url()).searchParams;
    await delay(q.get("symbol") === "AMD" && q.get("phase") !== "prices" ? 2000 : 600);
    const now = Math.floor(Date.now() / 1000), symbol = q.get("symbol") ?? "MRVL";
    const data: ChartData = { symbol, session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15,
      checked_at: now, fetched_at: { intraday: now }, intraday_as_of: now - 60,
      panels: Object.fromEntries((q.get("intervals") ?? "5m").split(",").map(i => [i, panels[i as Interval]])),
      quotes: ["MRVL", "NVDA"].map(s => ({ symbol: s, name: s, last: 96, change: 1, change_percentage: 1, volume: 1000, previous_close: 95, trade_time: now })),
      issues: [], fills: [], fills_truncated: false, extras: {}, history_note: "Invented benchmark candles",
      adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] } };
    await route.fulfill({ json: data });
  });
  const usable = async (symbol = "MRVL") => {
    await expect(page.getByRole("region", { name: new RegExp(`^${symbol} .* chart$`) }).first()).toBeVisible();
    await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", /[1-9]\d*/);
    await expect(page.getByTestId("canvas-main")).not.toHaveAttribute("data-pending");
    await paint(page);
  };
  const samples: Record<string, number[]> = {};
  async function measure(name: string, action: () => Promise<unknown>, ready: () => Promise<unknown>) {
    const start = Date.now(); await action(); await ready();
    (samples[name] ??= []).push(Date.now() - start);
  }
  // Fixture controls are private to the isolated test backend (not proxy routes).
  const backend = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || 8099}`;
  await request.post(`${backend}/__test/dashboard-state?value=ready`);
  await measure("first_chart", () => page.goto("/charts"), usable);
  for (let i = 0; i < 4; i++) await measure("first_chart", () => page.reload(), usable);
  await delay(750); // Initial context finishes before testing a return visit.
  for (let i = 0; i < 5; i++) {
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await expect(page.getByTestId("owner-dashboard")).toBeVisible();
    await measure("return_chart", () => page.getByRole("link", { name: "Charts", exact: true }).click(), usable);
    await delay(750);
    await measure("symbol_new_or_recent", () => page.getByRole("button", { name: "Chart NVDA", exact: true }).click(), () => usable("NVDA"));
    await delay(750);
    await measure("symbol_return", () => page.getByRole("button", { name: "Chart MRVL", exact: true }).click(), usable);
    // Let refresh finish before the next visit, without including it in restore latency.
    await delay(750);
  }
  await measure("new_symbol_slow_context", () => page.getByRole("button", { name: "Chart AMD", exact: true }).click(), () => usable("AMD"));
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  for (let i = 0; i < 4; i++) await measure("dashboard_filter", () => page.getByRole("link", { name: i % 2 ? "All types" : "Options", exact: true }).click(), async () => {
    await expect(page.getByRole("link", { name: i % 2 ? "All types" : "Options", exact: true })).toHaveAttribute("aria-current", "true"); await paint(page);
  });
  await request.post(`${backend}/__test/dashboard-state?value=slow`);
  try {
    await measure("dashboard_market_slow_journal", () => page.goto("/", { waitUntil: "commit" }), async () => { await expect(page.locator('[aria-label="Market and discovery"]')).toBeVisible(); await paint(page); });
  } finally { await request.post(`${backend}/__test/dashboard-state?value=ready`); }
  await page.screenshot({ path: info.outputPath("dashboard-desktop.png"), fullPage: true });
  expect(errors).toEqual([]);
  const output = process.env.TJ_NAV_BENCHMARK!;
  mkdirSync(output, { recursive: true });
  writeFileSync(`${output}/${layout}.json`, JSON.stringify({ layout, settingsDelayMs: 400, workspaceDelayMs: 600, samples, workspaceReads, documentReads, errors }, null, 2));
});
