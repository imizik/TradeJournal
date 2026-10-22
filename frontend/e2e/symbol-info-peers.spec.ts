import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { DEFAULT_SETTINGS, STORAGE_KEY } from "../lib/charts";
import type { SymbolPeers } from "../lib/symbolInfo";

// T3.4. Only market candles/quotes/settings and the peers endpoint are stubbed.
// The news markers (T3.5) are off here so these tests count the tabs' own reads; e2e/news-markers.spec.ts covers the markers.
test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(({ key, settings }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(settings));
  }, { key: STORAGE_KEY, settings: { ...DEFAULT_SETTINGS, symbol: "NVDA", watchlist: ["NVDA", "AAPL", "SPY"], newsHidden: true } });
  await fakeChartSettings(context, { revision: 1, data: { symbol: "NVDA", watchlist: ["NVDA", "AAPL", "SPY"], newsHidden: true } });
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
  // Peers sit in the Overview tab, not above every tab.
  await expect(panel(page).getByRole("group", { name: "Peers" })).toHaveCount(0);
  await panel(page).getByRole("tab", { name: "Overview" }).click();
  const strip = panel(page).getByRole("group", { name: "Peers" });
  await expect(strip.getByRole("button", { name: "Peer AMD" })).toContainText("-4.38%");
  await expect(strip.getByRole("button", { name: "Peer GOOGL" })).toContainText("+0.50%");
  await expect(strip.getByRole("button", { name: "Peer INTC" })).toContainText("—");
  expect(reads).toEqual(["NVDA"]);
  await strip.screenshot({ path: test.info().outputPath("peers-day-moves-desktop.png") });

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
  await panel(page).getByRole("tab", { name: "Overview" }).click();
  await expect(panel(page).getByRole("group", { name: "Peers" })).toContainText("No related companies listed for SPY");
});

const groups = [{ name: "Chips", members: ["NVDA", "AMD", "MU"] }, { name: "AI compute", members: ["NVDA", "AMD"] }];
function comparison(symbol = "NVDA", group = "Chips", state = "partial") {
  const selected = groups.find((g) => g.name === group)!;
  const start = "2026-10-20T14:00:00.000Z", end = "2026-10-20T14:15:00.000Z";
  const point = (at: string) => ({ price: 100, retrieved_at: at, trade_at: at });
  return { symbol, state, reason: state === "stale" ? "Recording is stale; these are older observations." : "Some observations are missing or ineligible.",
    groups, group: selected, universe_version: "fixture-v1", source: "Radar curated groups · Tradier sampled trades", methodology: "sampled_last_trade_observation",
    window_minutes: 15, session: "2026-10-20", live: true, generated_at: end, window: { start, end, start_pass_id: 1, end_pass_id: 16 },
    rows: [...selected.members, "QQQ", "SPY"].map((ticker) => ({ symbol: ticker, role: ticker === symbol ? "selected" : ["SPY", "QQQ"].includes(ticker) ? "benchmark" : "peer",
      change_pct: ticker === "MU" ? null : ticker === "QQQ" ? -0.3 : 1.2, reason: ticker === "MU" ? "Stale or future trade time" : null,
      start: point(start), end: ticker === "MU" ? null : point(end) })),
    coverage: { recorded_minutes: 16, expected_minutes: 16, peers_total: selected.members.length - 1, peers_available: 1, peers_up: 1, peers_down: 0, missing: group === "Chips" ? ["MU"] : [] } };
}

for (const phone of [false, true]) test(`Group movement preserves group on peer navigation ${phone ? "phone" : "desktop"}`, async ({ page }) => {
  await page.setViewportSize(phone ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
  const reads: string[] = [];
  await page.route("**/api/backend/charts/symbol/*/peers", (route) => route.fulfill({ json: peers("NVDA") }));
  await page.route("**/api/backend/radar/groups/compare?**", (route) => {
    const q = new URL(route.request().url()).searchParams;
    reads.push(`${q.get("symbol")}|${q.get("group") ?? ""}`);
    return route.fulfill({ json: comparison(q.get("symbol")!, q.get("group") ?? "Chips") });
  });
  await page.goto("/charts");
  const info = panel(page);
  if (phone) {
    await page.getByRole("button", { name: "Watchlist", exact: true }).click();
    await info.getByRole("button", { name: "NVDA symbol info" }).click();
  }
  expect(reads).toEqual([]);
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  const movement = info.getByRole("group", { name: "Group movement", exact: true });
  await expect(movement).toContainText("1 up · 0 down · 1 of 2 peers available");
  await expect(movement).toContainText("10:00 AM–10:15 AM ET");
  await expect(movement.getByRole("button", { name: "Compare chart QQQ", exact: true })).toContainText("-0.30%");
  await expect(movement.getByRole("button", { name: "Compare chart MU", exact: true })).toContainText("—");
  await expect(movement).toContainText("Stale or future trade time");
  await movement.scrollIntoViewIfNeeded();
  expect(await movement.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await movement.screenshot({ path: test.info().outputPath(`group-movement-partial-${phone ? "phone" : "desktop"}.png`) });
  await movement.getByRole("combobox", { name: "Comparison group" }).selectOption("AI compute");
  await expect(movement.getByRole("combobox")).toHaveValue("AI compute");
  await movement.getByRole("button", { name: "Compare chart AMD", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Chart symbol" })).toHaveAttribute("placeholder", "AMD");
  if (phone) {
    await page.getByRole("button", { name: "Watchlist", exact: true }).click();
    await info.getByRole("button", { name: "AMD symbol info" }).click();
  }
  await expect(movement.getByRole("combobox")).toHaveValue("AI compute");
  await expect.poll(() => reads.at(-1)).toBe("AMD|AI compute");
  await info.getByRole("tab", { name: "News", exact: true }).click();
  await expect(movement).toHaveCount(0);
});

test("Group movement hides old values after a failed refresh", async ({ page }) => {
  let fail = false;
  await page.route("**/api/backend/charts/symbol/*/peers", (route) => route.fulfill({ json: peers("NVDA") }));
  await page.route("**/api/backend/radar/groups/compare?**", (route) => fail
    ? route.fulfill({ status: 503, body: "unavailable" }) : route.fulfill({ json: comparison() }));
  await page.clock.install();
  await page.goto("/charts");
  await panel(page).getByRole("tab", { name: "Overview", exact: true }).click();
  const movement = panel(page).getByRole("group", { name: "Group movement", exact: true });
  await expect(movement.getByRole("button", { name: "Compare chart NVDA" })).toBeVisible();
  fail = true;
  await page.clock.fastForward(60_000);
  await expect(movement).toContainText("Group movement unavailable");
  await expect(movement.getByRole("button", { name: "Compare chart NVDA" })).toHaveCount(0);
});

test("Group movement discloses stale and off states", async ({ page }) => {
  let off = false;
  await page.route("**/api/backend/charts/symbol/*/peers", (route) => route.fulfill({ json: peers("NVDA") }));
  await page.route("**/api/backend/radar/groups/compare?**", (route) => route.fulfill({ json: off
    ? { ...comparison(), state: "off", reason: "Radar recording is not switched on.", rows: [], coverage: null, window: null }
    : comparison("NVDA", "Chips", "stale") }));
  await page.goto("/charts");
  await panel(page).getByRole("tab", { name: "Overview", exact: true }).click();
  const movement = panel(page).getByRole("group", { name: "Group movement", exact: true });
  await expect(movement).toContainText("Recording is stale");
  off = true;
  await page.reload();
  await expect(movement).toContainText("Radar recording is not switched on.");
  await expect(movement.getByRole("button", { name: "Compare chart NVDA" })).toHaveCount(0);
});
