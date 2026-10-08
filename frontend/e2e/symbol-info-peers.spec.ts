import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { DEFAULT_SETTINGS, STORAGE_KEY } from "../lib/charts";
import type { SymbolPeers } from "../lib/symbolInfo";

// T3.4. Only market candles/quotes/settings and the peers endpoint are stubbed.
test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(({ key, settings }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(settings));
  }, { key: STORAGE_KEY, settings: { ...DEFAULT_SETTINGS, symbol: "NVDA", watchlist: ["NVDA", "AAPL", "SPY"] } });
  await fakeChartSettings(context, { revision: 1, data: { symbol: "NVDA", watchlist: ["NVDA", "AAPL", "SPY"] } });
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const symbol = query.get("symbol");
    const now = Math.floor(Date.now() / 1000);
    const bars = Array.from({ length: 10 }, (_, i) => ({ time: 1789392600 + i * 300, end_time: 1789392900 + i * 300, open: 100, high: 102, low: 99, close: 101, volume: 1000, extended: false }));
    await route.fulfill({ json: { symbol, session: "extended", provider: "Fixture", delayed: false, refresh_seconds: 15,
      checked_at: now, fetched_at: { intraday: now, quotes: now }, intraday_as_of: now, issues: [], quotes: [{ symbol, name: `${symbol} company`, instrument_type: symbol === "SPY" ? "etf" : "stock", last: 189.12, change: 2.2,
        change_percentage: 1.18, volume: 112700000, previous_close: 186.92, trade_time: now, day_low: 185, day_high: 191, week_52_low: 86, week_52_high: 195 }], fills: [], fills_truncated: false,
      panels: Object.fromEntries((query.get("intervals") ?? "5m").split(",").map((interval) => [interval, { bars, markers: [] }])), extras: {} } });
  });
  await page.route("**/api/backend/charts/stream?**", (route) => route.fulfill({ status: 503, body: "Fixture has no stream" }));
});

const source = { provider: "polygon", label: "Polygon related companies", state: "ok" as const, fetched_at: 1_790_000_000, age_seconds: 7200, message: null };
const quotes = { provider: "tradier", label: "Tradier quotes", state: "ok" as const, fetched_at: 1_790_000_000, age_seconds: null, message: null };
function peers(symbol: string): SymbolPeers {
  if (symbol === "SPY") return { symbol, as_of: "2026-10-08T15:00:00Z", state: "none", source, quotes, peers: [] };
  return { symbol, as_of: "2026-10-08T15:00:00Z", state: "ready", source, quotes, peers: [
    { symbol: "AMD", name: "Advanced Micro Devices Inc", last: 617.62, change_percentage: -4.38 },
    { symbol: "GOOGL", name: "Alphabet Inc", last: 347.95, change_percentage: 0.5 },
    { symbol: "INTC", name: null, last: null, change_percentage: null },
  ] };
}
const panel = (page: Page) => page.getByRole("region", { name: "Symbol info", exact: true });

test("Peers chips show today's move and a click switches the chart like a watchlist click", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/api/backend/charts/symbol/*/peers", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    reads.push(symbol);
    await route.fulfill({ json: peers(symbol) });
  });
  await page.goto("/charts");
  const strip = panel(page).getByRole("group", { name: "Peers" });
  await expect(strip.getByRole("button", { name: "Peer AMD" })).toContainText("-4.38%");
  await expect(strip.getByRole("button", { name: "Peer GOOGL" })).toContainText("+0.50%");
  await expect(strip.getByRole("button", { name: "Peer INTC" })).toContainText("—");
  expect(reads).toEqual(["NVDA"]);

  await strip.getByRole("button", { name: "Peer AMD" }).click();
  await expect(page.getByRole("textbox", { name: "Chart symbol" })).toHaveAttribute("placeholder", "AMD");
  await expect(panel(page)).toContainText("AMD symbol info");
  await expect(page.getByRole("button", { name: "Chart NVDA", exact: true })).not.toHaveAttribute("aria-current", "true");
  await expect.poll(() => reads).toEqual(["NVDA", "AMD"]);
});

test("Peers says so when a symbol has none, like an ETF", async ({ page }) => {
  await page.route("**/api/backend/charts/symbol/*/peers", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    await route.fulfill({ json: peers(symbol) });
  });
  await page.goto("/charts");
  await page.getByRole("button", { name: "Chart SPY", exact: true }).click();
  await expect(panel(page).getByRole("group", { name: "Peers" })).toContainText("No related companies listed for SPY");
});
