import { expect, test, type Page } from "@playwright/test";
import type { ChartData, ChartBar, Interval, MarketDay } from "../lib/charts";
import { fakeChartSettings, type SettingsStore } from "./fixtures/chartSettings";

// Each test starts from empty server settings of its own; tests tagged
// @real-settings use the e2e backend's endpoint instead.
test.beforeEach(async ({ context }, testInfo) => {
  if (!testInfo.tags.includes("@real-settings")) await fakeChartSettings(context);
});

// Provider responses are deliberately stubbed: browser checks prove interaction,
// not brokerage entitlement. Backend tests exercise normalization and real routes.
// Symbols that panels hold (C7.1) get candles offset by a fixed amount, so a
// legend shows at a glance which symbol a chart is drawing.
const HELD_OFFSET: Record<string, number> = { SPY: 400, QQQ: 300 };
function fixturePanels(intervals: Interval[], offset = 0): ChartData["panels"] {
  const panels: ChartData["panels"] = {};
  for (const interval of intervals) {
    const step = ({ "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 })[interval];
    const daily = step >= 86400;
    const slots = daily ? 1 : Math.ceil(23400 / step);
    const bars: ChartBar[] = Array.from({ length: 240 }, (_, i) => {
      const time = 1789392600 + (daily ? i * step : Math.floor(i / slots) * 86400 + (i % slots) * step);
      const close = 245 + i * 0.06 + Math.sin(i / 8) * 2;
      return { time, end_time: time + step, source: "tradier", open: close - 0.3 + offset, high: close + 0.8 + offset, low: close - 0.7 + offset, close: close + offset, volume: 10000 + i * 240,
        ema9: close - 0.3 + offset, ema20: close - 0.6 + offset, ema50: close - 1 + offset, ema200: close - 3 + offset, vwap: daily ? null : close - 0.8 + offset, rsi: 50 + Math.sin(i / 9) * 24, extended: false };
    });
    panels[interval] = { bars, markers: offset ? [] : [{ id: "fill-test", time: bars[220].time, label: "buy to open 1 call", buy: true }] };
  }
  return panels;
}

function fixture(url: string): ChartData {
  const query = new URL(url).searchParams;
  const symbol = query.get("symbol") ?? "MRVL";
  const panels = fixturePanels((query.get("intervals") ?? "5m").split(",") as Interval[]);
  const extras = Object.fromEntries((query.get("extras") ?? "").split(",").filter(Boolean).map((part) => {
    const [name, frames] = part.split(":");
    return [name, { panels: fixturePanels(frames.split(".") as Interval[], HELD_OFFSET[name] ?? 100),
      fetched_at: { intraday: Math.floor(Date.now() / 1000) }, intraday_as_of: Math.floor(Date.now() / 1000) - 60, issues: [],
      fills_truncated: name === "QQQ" }];
  }));
  const now = Math.floor(Date.now() / 1000);
  const symbols = [...new Set([symbol, ...(query.get("watchlist") ?? "").split(",")].filter(Boolean))];
  return { symbol, session: query.get("session") === "regular" ? "regular" : "extended", provider: "Tradier", delayed: false,
    refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels,
    quotes: symbols.map((s) => ({ symbol: s, name: `${s} test company`, last: s === "NVDA" ? 189.12 : 262.66,
      change: 2, change_percentage: 1.5, volume: 1200000, previous_close: 260.66, trade_time: now - 2 })),
    issues: [], intraday_as_of: now - 60, history_note: "Synthetic chart data for browser verification.", fills: [], fills_truncated: false, extras };
}

async function stub(page: Page, onRequest?: (url: string) => void) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    onRequest?.(route.request().url());
    await route.fulfill({ json: fixture(route.request().url()) });
  });
}

test("five charts render, symbols link, and levels survive reload", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByRole("heading", { name: "Charts", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5);
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await expect(page.getByLabel("Selected symbol quote")).toContainText("262.66");
  await page.getByLabel("Level label").fill("Breakout");
  await page.getByLabel("Level price", { exact: true }).fill("263.50");
  await page.getByRole("button", { name: "Save price level" }).click();
  await expect(page.getByRole("region", { name: "Saved price levels" })).toContainText("Breakout");
  await page.reload();
  await expect(page.getByRole("region", { name: "Saved price levels" })).toContainText("263.50");
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(page.getByRole("region", { name: /NVDA .* chart/ })).toHaveCount(5);
  await expect(page.getByLabel("Selected symbol quote")).toContainText("189.12");
  await expect(page.getByRole("region", { name: "Saved price levels" })).not.toContainText("Breakout");
  await page.getByRole("button", { name: "Chart MRVL", exact: true }).click();
  await expect(page.getByRole("region", { name: "Saved price levels" })).toContainText("Breakout");
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await page.getByRole("button", { name: "Focus 1h chart" }).click();
  await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue("1h");
  await page.screenshot({ path: "/tmp/tradejournal-charts-desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("streamed trades move the selected price and candle, then pause freezes them", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      closed = false;
      constructor() {
        MockEventSource.current = this;
        queueMicrotask(() => this.emit("status", { state: "connected" }));
      }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
        this.listeners.set(type, listener as Listener);
      }
      emit(type: string, value: unknown) {
        if (!this.closed) this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent);
      }
      close() { this.closed = true; }
    }
    (window as typeof window & { __chartTick?: (value: unknown) => void }).__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("262.66");
  const at = Math.floor(Date.now() / 1000) + 2;
  const buckets = Object.fromEntries((["1m", "3m", "5m", "15m", "30m", "1h", "4h"] as const).map((interval) => {
    const width = ({ "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400 })[interval];
    const time = Math.floor(at / width) * width;
    return [interval, { time, end_time: time + width, extended: true }];
  }));
  await page.evaluate((tick) => (window as typeof window & { __chartTick: (value: unknown) => void }).__chartTick(tick),
    { type: "tick", symbol: "MRVL", at, minute: Math.floor(at / 60) * 60, session: "post", price: 280.25, open: 280.1, high: 280.25, low: 280.1, buckets });
  await expect(page.getByLabel("Selected symbol quote")).toContainText("280.25");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("Live trade");
  await expect(page.getByLabel("main candle values")).toContainText("280.25");
  await expect(page.getByLabel("Panel 2 candle values")).toContainText("Vol pending");
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await expect(page.getByLabel("Selected symbol quote")).toContainText("280.25");
  await page.evaluate((tick) => (window as typeof window & { __chartTick: (value: unknown) => void }).__chartTick(tick),
    { type: "tick", symbol: "MRVL", at: at + 1, minute: Math.floor(at / 60) * 60, session: "post", price: 290, open: 290, high: 290, low: 290, buckets });
  await expect(page.getByLabel("Selected symbol quote")).not.toContainText("290.00");
});

test("newer extended-hours candle is labeled instead of showing an older quote", async ({ page }) => {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    const now = Math.floor(Date.now() / 1000);
    data.quotes.find((quote) => quote.symbol === data.symbol)!.trade_time = now - 3600;
    for (const panel of Object.values(data.panels)) {
      if (!panel) continue;
      const bar = panel.bars.at(-1)!;
      bar.time = now - 60;
      bar.end_time = now;
      bar.close = 280.25;
      bar.high = 280.25;
      bar.extended = true;
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/charts");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("280.25");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("Extended-hours candle");
});

test("refreshes once per cycle, stops while hidden or paused, and retains data on errors", async ({ page }) => {
  await page.clock.install();
  let requests = 0;
  let fail = false;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    requests++;
    return fail ? route.fulfill({ status: 503, json: { detail: { message: "Tradier connection unavailable" } } }) : route.fulfill({ json: fixture(route.request().url()) });
  });
  await page.goto("/charts");
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5);
  const initial = requests;
  await page.clock.runFor(15_100);
  await expect.poll(() => requests).toBe(initial + 1);
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.clock.runFor(45_000);
  expect(requests).toBe(initial + 1);
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: false }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect.poll(() => requests).toBe(initial + 2);
  await expect(page.getByRole("button", { name: "Refresh charts", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await page.clock.runFor(30_000);
  expect(requests).toBe(initial + 2);
  fail = true;
  await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
  await expect(page.getByRole("alert", { name: "Chart data error" })).toContainText("Showing the last successful data");
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5);
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(page.getByRole("alert", { name: "Chart data error" })).toContainText("Tradier connection unavailable");
  await expect(page.getByLabel("Selected symbol quote")).not.toContainText("262.66");
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(0);
});

test("missing credentials show setup state and never fake candles", async ({ page, request }) => {
  const response = await request.get("http://127.0.0.1:8099/charts/workspace");
  expect(response.status()).toBe(503);
  expect((await response.json()).detail.code).toBe("not_configured");
  await page.goto("/charts");
  await expect(page.getByRole("alert", { name: "Chart data error" })).toContainText("Connect your Tradier account");
  await expect(page.getByTestId("canvas-main")).toHaveCount(0);
});

test("slow provider responses never overlap polling requests", async ({ page }) => {
  await page.clock.install();
  let requests = 0;
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    requests++;
    if (requests === 2) await pending;
    await route.fulfill({ json: fixture(route.request().url()) });
  });
  await page.goto("/charts");
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5);
  await page.clock.runFor(15_100);
  await expect.poll(() => requests).toBe(2);
  await page.clock.runFor(45_000);
  expect(requests).toBe(2);
  release();
  await expect(page.getByRole("button", { name: "Refresh charts", exact: true })).toBeEnabled();
  await page.clock.runFor(15_000);
  await expect.poll(() => requests).toBe(3);
});

test("mobile layout stays within the viewport and chart controls work", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.getByRole("button", { name: "Show single chart" }).click();
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "/tmp/tradejournal-charts-mobile.png", fullPage: true });
});

test("VWAP draws inside the session without painting through an extended-hours gap", async ({ page }) => {
  // Keep the whole main canvas in view so locator screenshots cannot scroll
  // the page between comparisons of the chart-relative gap strip.
  await page.setViewportSize({ width: 1600, height: 1080 });
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    for (const panel of Object.values(data.panels)) {
      panel?.bars.forEach((bar, index) => {
        if (index >= 145 && index <= 210) { bar.vwap = null; bar.extended = true; }
      });
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/charts");
  const canvas = page.getByTestId("canvas-main");
  await expect(canvas).toBeVisible();
  const bounds = (await canvas.boundingBox())!;
  // The default visible window is candles 130–244. This strip crosses the
  // middle of the missing VWAP interval, excluding legends, axes and RSI.
  const clip = { x: Math.floor(bounds.x + (bounds.width - 66) * 0.45), y: Math.floor(bounds.y + 10), width: 40, height: 260 };
  const gapWithVwap = await page.screenshot({ clip, path: test.info().outputPath("gap-vwap-on.png") });
  const chartWithVwap = await canvas.screenshot({ path: test.info().outputPath("chart-vwap-on.png") });
  await page.getByRole("button", { name: "RTH VWAP", exact: true }).click();
  const gapWithoutVwap = await page.screenshot({ clip, path: test.info().outputPath("gap-vwap-off.png") });
  const chartWithoutVwap = await canvas.screenshot({ path: test.info().outputPath("chart-vwap-off.png") });
  expect(gapWithVwap.equals(gapWithoutVwap)).toBe(true);
  expect(chartWithVwap.equals(chartWithoutVwap)).toBe(false);
});

// ---- Workspace UX: countdown, incremental candles, linked ranges, immersive, navigation ----

type Registry = Map<string, { timeScale(): { getVisibleRange(): { from: number; to: number } | null; getVisibleLogicalRange(): { from: number; to: number } | null; setVisibleLogicalRange(r: { from: number; to: number }): void } }>;
const registerCharts = (page: Page) => page.addInitScript(() => { (window as typeof window & { __tjCharts?: Map<string, unknown> }).__tjCharts = new Map(); });
const visibleRange = (page: Page, id: string) => page.evaluate((key) => (window as unknown as { __tjCharts: Registry }).__tjCharts.get(key)!.timeScale().getVisibleRange(), id);
const logicalRange = (page: Page, id: string) => page.evaluate((key) => (window as unknown as { __tjCharts: Registry }).__tjCharts.get(key)!.timeScale().getVisibleLogicalRange(), id);
const resets = async (page: Page, id = "main") => Number(await page.getByTestId(`canvas-${id}`).getAttribute("data-resets"));

const intradayOnly = (interval: Interval) => interval !== "1D" && interval !== "1W";
const STEP: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };
/** Bars that end in the bucket containing `now`, so the countdown has a current session to count. */
function currentFixture(url: string, now: number, lastEnd = now + 30): ChartData {
  const data = fixture(url);
  for (const [interval, panel] of Object.entries(data.panels) as [Interval, NonNullable<ChartData["panels"][Interval]>][]) {
    const step = STEP[interval];
    panel.bars = panel.bars.slice(-100).map((bar, i) => ({ ...bar, time: lastEnd - step - (99 - i) * step, end_time: lastEnd - (99 - i) * step }));
    panel.markers = [];
  }
  data.fetched_at = { intraday: now };
  data.checked_at = now;
  return data;
}
// 10:32:15 New York time on a Tuesday (EDT).
const TUESDAY_1032 = Date.parse("2026-09-29T14:32:15Z") / 1000;

async function openAt(page: Page, at: number, data: (url: string) => ChartData) {
  await page.clock.install({ time: at * 1000 });
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: data(route.request().url()) }));
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.clock.pauseAt((at + 5) * 1000);
}

test("next-bar countdown ticks each second from end times without extra requests", async ({ page }) => {
  let requests = 0;
  await page.clock.install({ time: TUESDAY_1032 * 1000 });
  await page.route("**/api/backend/charts/workspace?**", (route) => { requests++; return route.fulfill({ json: currentFixture(route.request().url(), TUESDAY_1032) }); });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.clock.pauseAt((TUESDAY_1032 + 5) * 1000);
  const before = requests;
  // 5m bucket 10:30–10:35 at 10:32:20; 15m 10:30–10:45; 1h anchors at 9:30.
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:40");
  await expect(page.getByRole("timer", { name: "Panel 2 next bar" })).toHaveText("12:40");
  await expect(page.getByRole("timer", { name: "Panel 3 next bar" })).toHaveText("57:40");
  await expect(page.getByRole("timer", { name: "Panel 5 next bar" })).toHaveText("0:40");
  await expect(page.getByRole("timer", { name: "Panel 4 next bar" })).toHaveCount(0);
  await page.clock.runFor(1000);
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:39");
  await page.clock.runFor(3000);
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:36");
  expect(requests).toBe(before);
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("Paused");
});

const clockCases: { name: string; at: number; expected: string; tweak?: (data: ChartData) => void; session?: "regular" }[] = [
  { name: "weekend", at: Date.parse("2026-10-03T15:00:00Z") / 1000, expected: "Market closed" },
  { name: "after the close in regular-hours mode", at: Date.parse("2026-09-29T21:10:00Z") / 1000, expected: "Market closed", session: "regular" },
  { name: "stale refresh", at: TUESDAY_1032, expected: "Stale data", tweak: (data) => { data.fetched_at.intraday -= 300; } },
  { name: "delayed sandbox data", at: TUESDAY_1032, expected: "Delayed data", tweak: (data) => { data.delayed = true; } },
  { name: "no bars in today's session (holiday or halt)", at: TUESDAY_1032, expected: "Waiting for bars", tweak: (data) => {
    for (const panel of Object.values(data.panels)) panel?.bars.forEach((bar) => { bar.time -= 86400; bar.end_time -= 86400; });
  } },
];
for (const scenario of clockCases) {
  test(`countdown shows a named state instead of a number: ${scenario.name}`, async ({ page }) => {
    if (scenario.session) await page.addInitScript(() => localStorage.setItem("tradejournal.charts.v1", JSON.stringify({ session: "regular" })));
    await openAt(page, scenario.at, (url) => {
      const data = currentFixture(url, scenario.at);
      scenario.tweak?.(data);
      return data;
    });
    await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText(scenario.expected);
    await expect(page.getByRole("timer", { name: "Main next bar" })).not.toHaveText(/\d:\d\d/);
  });
}

// Tradier's calendar for November 2026 (EST): Thanksgiving closed, the next day closes at 13:00.
const et = (clock: string) => Date.parse(`${clock}-05:00`) / 1000;
const THANKSGIVING: MarketDay = { date: "2026-11-26", status: "closed", source: "tradier", description: "Market is closed for Thanksgiving Day", sessions: [], note: null };
const HALF_DAY: MarketDay = { date: "2026-11-27", status: "open", source: "tradier", description: "Market closes early at 13:00", note: null, sessions: [
  { part: "pre", start: et("2026-11-27T04:00:00"), end: et("2026-11-27T09:30:00") },
  { part: "regular", start: et("2026-11-27T09:30:00"), end: et("2026-11-27T13:00:00") },
  { part: "post", start: et("2026-11-27T13:00:00"), end: et("2026-11-27T17:00:00") }] };

test("a holiday from the market calendar reads Market closed and names the closure", async ({ page }) => {
  const at = et("2026-11-26T10:32:15");
  await openAt(page, at, (url) => ({ ...currentFixture(url, at), market: THANKSGIVING }));
  // The clock rule alone would count down here: it is a Thursday morning with fresh bars.
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("Market closed");
  await expect(page.getByRole("timer", { name: "Panel 5 next bar" })).toHaveText("Market closed");
  await expect(page.getByLabel("Market hours")).toHaveText("Market is closed for Thanksgiving Day");
});

test("an early close ends the regular session at 13:00 and the last bar's countdown respects it", async ({ page }) => {
  let now = et("2026-11-27T12:58:00");
  await openAt(page, now, (url) => ({ ...currentFixture(url, now), market: HALF_DAY }));
  await expect(page.getByLabel("Market hours")).toHaveText("Early close 1:00 PM ET");
  // 12:58:05. Every bucket, including the 12:30 hourly one, ends at 13:00.
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("1:55");
  await expect(page.getByRole("timer", { name: "Panel 2 next bar" })).toHaveText("1:55");
  await expect(page.getByRole("timer", { name: "Panel 3 next bar" })).toHaveText("1:55");
  await expect(page.getByRole("timer", { name: "Panel 5 next bar" })).toHaveText("0:55");
  now = et("2026-11-27T13:00:05");
  await page.clock.pauseAt(now * 1000);
  // Postmarket starts at the early close and anchors its own buckets.
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("4:55");
  await page.getByRole("button", { name: "Extended hours on" }).click();
  await expect(page.getByRole("button", { name: "Regular hours only" })).toBeVisible();
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("Market closed");
});

test("without a market calendar the countdown keeps clock hours and says so", async ({ page }) => {
  const note = "Market calendar unavailable: holidays and early closes use regular clock hours.";
  await openAt(page, TUESDAY_1032, (url) => ({ ...currentFixture(url, TUESDAY_1032),
    market: { date: "2026-09-29", status: "unknown", source: "clock", description: null, note, sessions: [
      { part: "pre", start: Date.parse("2026-09-29T08:00:00Z") / 1000, end: Date.parse("2026-09-29T13:30:00Z") / 1000 },
      { part: "regular", start: Date.parse("2026-09-29T13:30:00Z") / 1000, end: Date.parse("2026-09-29T20:00:00Z") / 1000 },
      { part: "post", start: Date.parse("2026-09-29T20:00:00Z") / 1000, end: Date.parse("2026-09-30T00:00:00Z") / 1000 }] } }));
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:40");
  await expect(page.getByLabel("Market hours")).toHaveText(note);
});

test("with no intraday bars today (weekend, holiday, overnight) charts open on the latest completed sessions", async ({ page }) => {
  const requests: { interval: string | null; before: number }[] = [];
  const template = fixture("http://test/charts/workspace?intervals=5m").panels["5m"]!.bars[0];
  const completed = Array.from({ length: 120 }, (_, index) => ({ ...template,
    time: Date.parse("2026-11-25T14:30:00Z") / 1000 + index * 300,
    end_time: Date.parse("2026-11-25T14:35:00Z") / 1000 + index * 300, source: "alpaca_sip" as const }));
  let checkedAt = 0;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const data = fixture(route.request().url());
    checkedAt ||= data.checked_at;
    data.checked_at = checkedAt;
    for (const [interval, panel] of Object.entries(data.panels))
      if (interval !== "1D" && interval !== "1W" && panel) panel.bars = [];
    return route.fulfill({ json: { ...data, market: THANKSGIVING } });
  });
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    requests.push({ interval: query.get("interval"), before: Number(query.get("before")) });
    return route.fulfill({ json: { symbol: "MRVL", interval: query.get("interval"), session: "extended", before: Number(query.get("before")),
      limit: 1200, bars: completed, markers: [], older_cursor: completed[0].time, exhausted: false, continuation: null,
      warmup: "ready", source: "alpaca_sip", price_basis: "raw", fills_truncated: false, issue: null,
      calendar_note: "Market calendar unavailable: holidays and early closes use regular clock hours." } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "120");
  await expect(page.getByLabel("main candle values")).toContainText("SIP raw");
  await expect(page.getByTestId("canvas-Panel 5")).toHaveAttribute("data-bars", "120");
  // One opening request per intraday panel, starting from now; scrolling may add older pages.
  const first = new Map<string | null, number>();
  for (const request of requests) if (!first.has(request.interval)) first.set(request.interval, request.before);
  expect([...first.keys()].sort()).toEqual(["15m", "1h", "1m", "5m"]);
  expect([...first.values()].every((before) => before === checkedAt)).toBe(true);
  await expect(page.getByRole("region", { name: "MRVL 5m chart" }).getByRole("status")).toContainText("Market calendar unavailable");
});

test("streamed ticks update the latest candle in place and keep zoom; history changes reset", async ({ page }) => {
  await registerCharts(page);
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      constructor() { MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() {}
    }
    (window as typeof window & { __chartTick?: (value: unknown) => void }).__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  let corrected = false;
  const base = Math.floor(Date.now() / 1000);
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const data = currentFixture(route.request().url(), base);
    if (corrected) data.panels["5m"]!.bars[40].close += 5;
    return route.fulfill({ json: data });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await expect.poll(() => resets(page)).toBe(1);
  // Scroll away from the live edge; an in-place update must not move it back.
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 20, to: 70 }));
  await page.waitForTimeout(200); // let the new range paint before hovering
  const box = (await page.getByTestId("canvas-main").boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.4);
  await page.mouse.move(box.x + box.width * 0.4 + 1, box.y + box.height * 0.4);
  await expect(page.getByLabel("main candle values")).not.toContainText("C 301");
  await page.waitForTimeout(300);
  const hovered = await page.getByLabel("main candle values").textContent();
  const last = (await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().getVisibleRange()))!;
  const at = base;
  const buckets = Object.fromEntries((["1m", "3m", "5m", "15m", "30m", "1h", "4h"] as const).map((interval) => {
    const end = base + 30;
    return [interval, { time: end - STEP[interval], end_time: end, extended: false }];
  }));
  for (const [offset, value] of [[1, 300.5], [2, 301.25]] as const) {
    await page.evaluate((tick) => (window as typeof window & { __chartTick: (value: unknown) => void }).__chartTick(tick),
      { type: "tick", symbol: "MRVL", at: at + offset, minute: Math.floor(at / 60) * 60, session: "regular", price: value, open: value, high: value, low: value, buckets });
  }
  await expect(page.getByLabel("Selected symbol quote")).toContainText("301.25");
  expect(await resets(page)).toBe(1);
  expect(await logicalRange(page, "main")).toEqual({ from: 20, to: 70 });
  expect(await visibleRange(page, "main")).toEqual(last);
  // The crosshair survives the update: the legend still describes the hovered
  // candle rather than falling back to the live one.
  expect(hovered).not.toContain("301");
  await expect(page.getByLabel("main candle values")).not.toContainText("301.25");
  await expect(page.getByLabel("main candle values")).toContainText("O ");
  // Same REST history on refresh: still no reset. A corrected older bar: reset.
  await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
  await expect(page.getByRole("button", { name: "Refresh charts", exact: true })).toBeEnabled();
  expect(await resets(page)).toBe(1);
  corrected = true;
  await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
  await expect.poll(() => resets(page)).toBe(2);
  const kept = (await logicalRange(page, "main"))!;
  expect(kept.from).toBeCloseTo(20, 0);
  expect(kept.to).toBeCloseTo(70, 0);
  // A new symbol keeps the chart, resets its data, and opens on the latest candles.
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(page.getByRole("region", { name: /NVDA 5m chart/ })).toBeVisible();
  await expect.poll(() => resets(page)).toBe(3);
  await expect.poll(async () => Math.round((await logicalRange(page, "main"))!.to)).toBe(104); // applied on the next frame
});

type KeepAliveWindow = typeof window & { __tjCharts: Map<string, { panes(): unknown[] }>; __firstCharts?: Map<string, unknown>; __cardSeen?: boolean };
test("switching symbol, interval, session and RSI keeps every chart instance and never blanks to the loading card", async ({ page }) => {
  await registerCharts(page);
  let gate: Promise<void> | null = null;
  let open = () => {};
  const hold = () => { gate = new Promise<void>((resolve) => { open = () => { gate = null; resolve(); }; }); };
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const url = route.request().url();
    if (new URL(url).searchParams.get("symbol") === "ZZZZ")
      return route.fulfill({ status: 503, json: { detail: { message: "Tradier has no ZZZZ candles." } } });
    if (gate) await gate;
    try { await route.fulfill({ json: fixture(url) }); } catch { /* the page moved on */ }
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  // Record the five chart instances, and watch for the first-load card from here on.
  const sameCharts = () => page.evaluate(() => {
    const w = window as unknown as KeepAliveWindow;
    w.__firstCharts ??= new Map(w.__tjCharts);
    return w.__tjCharts.size === 5 && [...w.__tjCharts].every(([id, chart]) => w.__firstCharts!.get(id) === chart);
  });
  expect(await sameCharts()).toBe(true);
  await page.evaluate(() => new MutationObserver(() => {
    if (document.querySelector("[data-testid=chart-workspace]")?.textContent?.includes("Loading shared intraday")) (window as unknown as KeepAliveWindow).__cardSeen = true;
  }).observe(document.body, { subtree: true, childList: true, characterData: true }));
  const pending = (label: string) => page.getByRole("status").filter({ hasText: new RegExp(`^${label}$`) });

  // A new symbol: the previous candles stay drawn, dimmed and labeled, until the new ones arrive.
  hold();
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(pending("Loading NVDA…")).toHaveCount(5);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-pending", "");
  await expect(page.getByTestId("canvas-main")).toHaveCSS("opacity", "0.4");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await expect(page.getByLabel("Selected symbol quote")).toContainText("189.12"); // NVDA's own watchlist quote
  await page.screenshot({ path: test.info().outputPath("symbol-switch-pending.png") });
  open();
  await expect(pending("Loading NVDA…")).toHaveCount(0);
  await expect(page.getByTestId("canvas-main")).not.toHaveAttribute("data-pending", "");
  await expect(page.getByTestId("canvas-main")).toHaveCSS("opacity", "1");
  await expect(page.getByRole("region", { name: /NVDA .* chart/ })).toHaveCount(5);
  await page.screenshot({ path: test.info().outputPath("symbol-switch-loaded.png") });

  // Moving an interval into the main chart draws candles already loaded, without waiting for the request.
  hold();
  await page.getByRole("button", { name: "Focus 1h chart" }).click();
  await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue("1h");
  await expect(page.getByRole("region", { name: "NVDA 1h chart" })).toBeVisible();
  await expect(page.getByTestId("canvas-main")).not.toHaveAttribute("data-pending", "");
  await expect(page.getByLabel("main candle values")).toContainText("C ");
  // A new session is new candles: labeled until they arrive.
  await page.getByRole("button", { name: "Extended hours on" }).click();
  await expect(pending("Loading regular hours…")).toHaveCount(5);
  open();
  await expect(pending("Loading regular hours…")).toHaveCount(0);

  // RSI adds and removes its pane on the same chart.
  const panes = () => page.evaluate(() => (window as unknown as KeepAliveWindow).__tjCharts.get("main")!.panes().length);
  expect(await panes()).toBe(2);
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await expect.poll(panes).toBe(1);
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await expect.poll(panes).toBe(2);

  // A symbol that fails to load clears the charts rather than leaving another symbol's candles under its name.
  await page.getByLabel("Chart symbol").fill("ZZZZ");
  await page.getByRole("button", { name: "Load symbol" }).click();
  await expect(page.getByRole("alert", { name: "Chart data error" })).toContainText("Tradier has no ZZZZ candles.");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "0");
  await expect(page.getByRole("region", { name: "ZZZZ 1h chart" })).toContainText("No candles available");
  await expect(page.getByTestId("canvas-main")).not.toHaveAttribute("data-pending", "");

  expect(await sameCharts()).toBe(true);
  expect(await page.evaluate(() => (window as unknown as KeepAliveWindow).__cardSeen ?? false)).toBe(false);
});

type RenderWindow = typeof window & { __tjRenders?: Map<string, number>; __chartTick?: (value: unknown) => void };
test("a tick re-renders only the charts whose candles moved, and the clock re-renders no chart", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      constructor() { MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() {}
    }
    const target = window as RenderWindow;
    target.__tjRenders = new Map();
    target.__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  // Older history is exhausted, so nothing but the clock and the stream can render a chart.
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: { symbol: query.get("symbol"), interval: query.get("interval"), session: query.get("session"),
      before: Number(query.get("before")), limit: 1200, bars: [], markers: [], older_cursor: null, exhausted: true, continuation: null,
      warmup: "ready", source: "alpaca_sip", price_basis: "raw", fills_truncated: false, issue: null } });
  });
  await openAt(page, TUESDAY_1032, (url) => currentFixture(url, TUESDAY_1032));
  await expect(page.getByText("Tradier stream · studies refresh 15s")).toBeVisible();
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:40");
  const renders = () => page.evaluate(() => Object.fromEntries((window as RenderWindow).__tjRenders!));
  const settled = async () => { await page.waitForTimeout(300); return renders(); };
  const before = await settled();
  expect(Object.keys(before).sort()).toEqual(["Panel 2", "Panel 3", "Panel 4", "Panel 5", "main"]);
  const plus = (base: Record<string, number>, changed: string[]) =>
    Object.fromEntries(Object.entries(base).map(([id, count]) => [id, count + (changed.includes(id) ? 1 : 0)]));

  // Three seconds pass: every countdown moves, and no chart renders.
  await page.clock.runFor(3000);
  await expect(page.getByRole("timer", { name: "Main next bar" })).toHaveText("2:37");
  await expect(page.getByRole("timer", { name: "Panel 5 next bar" })).toHaveText("0:37");
  expect(await settled()).toEqual(before);

  // The fixture's newest candles end at 10:32:45 in every interval (5m main, 15m, 1h, 1D, 1m).
  const end = TUESDAY_1032 + 30;
  const send = (at: number, value: number, nextMinute = false) => page.evaluate((tick) => (window as RenderWindow).__chartTick!(tick), {
    type: "tick", symbol: "MRVL", at, minute: Math.floor(at / 60) * 60, session: "regular", price: value, open: value, high: value, low: value,
    buckets: Object.fromEntries((["1m", "3m", "5m", "15m", "30m", "1h", "4h"] as const).map((interval) => [interval,
      nextMinute && interval === "1m" ? { time: end, end_time: end + 60, extended: false } : { time: end - STEP[interval], end_time: end, extended: false }])) });
  const intraday = ["main", "Panel 2", "Panel 3", "Panel 5"];

  // A new price moves every intraday candle; the daily chart is untouched.
  await send(TUESDAY_1032 + 6, 300.5);
  await expect(page.getByLabel("Selected symbol quote")).toContainText("300.50");
  await expect.poll(renders).toEqual(plus(before, intraday));
  expect(await settled()).toEqual(plus(before, intraday));
  // The next minute's first trade at the same price opens a 1m candle and changes nothing else.
  const afterMove = await renders();
  await send(end + 1, 300.5, true);
  await expect(page.getByTestId("canvas-Panel 5")).toHaveAttribute("data-bars", "101");
  await expect(page.getByLabel("Panel 5 candle values")).toContainText("Vol pending");
  expect(await settled()).toEqual(plus(afterMove, ["Panel 5"]));
  // A repeat of that trade changes no candle, so no chart renders; the next move renders only the intraday charts again.
  const afterMinute = await renders();
  await send(end + 2, 300.5, true);
  await send(end + 3, 301.25, true);
  await expect(page.getByLabel("Selected symbol quote")).toContainText("301.25");
  await expect.poll(renders).toEqual(plus(afterMinute, intraday));
  expect(await settled()).toEqual(plus(afterMinute, intraday));
  await expect(page.getByLabel("main candle values")).toContainText("301.25");
});

function sixMonthBars(months = 6): ChartBar[] {
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - months, now.getUTCDate()));
  const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const template = fixture("http://test/charts/workspace?intervals=5m").panels["5m"]!.bars[0];
  const bars: ChartBar[] = [];
  for (let day = start.getTime(); day < end; day += 86400_000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday === 0 || weekday === 6) continue;
    for (let slot = 0; slot < 78; slot++) {
      const time = Math.floor(day / 1000) + 13 * 3600 + 30 * 60 + slot * 300;
      const close = 230 + bars.length * 0.0027;
      bars.push({ ...template, time, end_time: time + 300, open: close - 0.1, high: close + 0.2,
        low: close - 0.2, close, source: "alpaca_sip", ema9: close - 0.2, ema20: close - 0.5,
        ema50: close - 0.9, ema200: close - 1.3, vwap: close - 0.1, rsi: 50 });
    }
  }
  return bars;
}

async function deepHistoryStub(page: Page, months = 6) {
  const bars = sixMonthBars(months);
  const base = Math.floor(Date.now() / 1000);
  let requests = 0;
  let refreshes = 0;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    refreshes++;
    const data = currentFixture(route.request().url(), base);
    const main = data.panels["5m"];
    if (main) main.bars = main.bars.map((bar) => ({ ...bar, source: "tradier" }));
    return route.fulfill({ json: data });
  });
  await page.route("**/api/backend/charts/history?**", (route) => {
    requests++;
    const query = new URL(route.request().url()).searchParams;
    const before = Number(query.get("before"));
    const pageBars = bars.filter((bar) => bar.time < before).slice(-1200);
    const marker = bars[Math.floor(bars.length / 2)];
    return route.fulfill({ json: {
      symbol: query.get("symbol"), interval: query.get("interval"), session: query.get("session"), before,
      limit: 1200, bars: pageBars, markers: pageBars.some((bar) => bar.time === marker.time)
        ? [{ id: "old-fill", time: marker.time, label: "buy to open 1 stock", buy: true }] : [],
      older_cursor: pageBars[0]?.time ?? null, exhausted: pageBars[0]?.time === bars[0].time,
      continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "raw", fills_truncated: false, issue: null,
    } });
  });
  return { bars, base, requests: () => requests, refreshes: () => refreshes };
}

test("New York midnight replaces the completed Tradier day with SIP without waiting for a pan", async ({ page }) => {
  const beforeMidnight = Date.parse("2026-09-30T03:59:00Z") / 1000;
  const afterMidnight = Date.parse("2026-09-30T04:01:00Z") / 1000;
  let refreshes = 0;
  const requests: { interval: string | null; before: number }[] = [];
  const template = fixture("http://test/charts/workspace?intervals=5m").panels["5m"]!.bars[0];
  const completed = Array.from({ length: 120 }, (_, index) => ({ ...template,
    time: Date.parse("2026-09-29T13:30:00Z") / 1000 + index * 300,
    end_time: Date.parse("2026-09-29T13:35:00Z") / 1000 + index * 300,
    source: "alpaca_sip" as const }));
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    refreshes++;
    const data = fixture(route.request().url());
    data.checked_at = refreshes === 1 ? beforeMidnight : afterMidnight;
    data.fetched_at.intraday = data.checked_at;
    if (refreshes > 1) for (const [interval, panel] of Object.entries(data.panels))
      if (interval !== "1D" && interval !== "1W" && panel) panel.bars = [];
    return route.fulfill({ json: data });
  });
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const interval = query.get("interval");
    const before = Number(query.get("before"));
    requests.push({ interval, before });
    return route.fulfill({ json: { symbol: "MRVL", interval, session: "extended", before,
      limit: 1200, bars: completed, markers: [], older_cursor: completed[0].time,
      exhausted: false, continuation: null, warmup: "ready", source: "alpaca_sip",
      price_basis: "raw", fills_truncated: false, issue: null } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  expect(requests).toHaveLength(0);
  await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
  await expect.poll(() => requests.some((request) => request.interval === "5m" && request.before === afterMidnight)).toBe(true);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "120");
  await expect(page.getByLabel("main candle values")).toContainText("SIP raw");
});

test("5m scroll-back crosses six months without moving the viewport during pages, ticks, or REST", async ({ page }) => {
  await registerCharts(page);
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      constructor() { MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() {}
    }
    (window as typeof window & { __chartTick?: (value: unknown) => void }).__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  const state = await deepHistoryStub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  // A range change within 60 ms of a data reset reads as programmatic and loads nothing.
  await page.waitForTimeout(120);
  let reached = false;
  for (let index = 0; index < 15; index++) {
    const count = state.requests();
    await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10.25, to: 60.25 }));
    await page.waitForTimeout(180); // Lightweight Charts publishes its visible time range on the next frame.
    if ((await visibleRange(page, "main"))!.from <= state.bars[0].time + 86400 * 5) { reached = true; break; }
    await expect.poll(() => state.requests()).toBeGreaterThan(count);
    await expect.poll(async () => Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeGreaterThan(100 + index * 1000);
    const range = (await visibleRange(page, "main"))!;
    const logical = (await logicalRange(page, "main"))!;
    expect(logical.to - logical.from).toBeCloseTo(50, 2);
    if (index === 0) {
      await page.evaluate((base) => (window as typeof window & { __chartTick: (value: unknown) => void }).__chartTick({
        type: "tick", symbol: "MRVL", at: base + 2, minute: Math.floor(base / 60) * 60,
        session: "regular", price: 301.25, open: 301, high: 301.25, low: 301,
        buckets: { "5m": { time: base - 270, end_time: base + 30, extended: false } },
      }), state.base);
      await expect(page.getByLabel("Selected symbol quote")).toContainText("301.25");
      expect(await visibleRange(page, "main")).toEqual(range);
    }
    await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
    await expect(page.getByRole("button", { name: "Refresh charts", exact: true })).toBeEnabled();
    expect(await visibleRange(page, "main")).toEqual(range);
    if (range.from <= state.bars[0].time + 86400 * 5) { reached = true; break; }
  }
  expect(reached).toBe(true);
  expect(state.requests()).toBeGreaterThanOrEqual(6);
  expect(state.refreshes()).toBeGreaterThan(1);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-markers", "1");
  const plot = (await page.getByTestId("canvas-main").boundingBox())!;
  await page.mouse.move(plot.x + plot.width * 0.5, plot.y + plot.height * 0.35);
  await expect(page.getByLabel("main candle values")).toContainText("SIP raw");
  await page.screenshot({ path: test.info().outputPath("deep-history-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Latest candles main" }).click();
  await expect.poll(async () => (await visibleRange(page, "main"))?.to ?? 0).toBeGreaterThan(state.bars.at(-1)!.time);
});

test("older history failure retries without clearing current candles; a stale response cannot cross symbols", async ({ page }) => {
  await registerCharts(page);
  const base = Math.floor(Date.now() / 1000);
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: currentFixture(route.request().url(), base) }));
  let calls = 0;
  let holdNext = false;
  let release: (() => void) | undefined;
  await page.route("**/api/backend/charts/history?**", async (route) => {
    calls++;
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: { message: "History unavailable" } } });
    if (holdNext) {
      holdNext = false;
      await new Promise<void>((resolve) => { release = resolve; });
    }
    const query = new URL(route.request().url()).searchParams;
    const before = Number(query.get("before"));
    const template = fixture(route.request().url()).panels["5m"]!.bars[0];
    const bars = Array.from({ length: 1200 }, (_, i) => ({ ...template, source: "alpaca_sip", time: before - (1200 - i) * 300, end_time: before - (1199 - i) * 300 }));
    try { await route.fulfill({ json: { symbol: query.get("symbol"), interval: "5m", session: "extended", before, limit: 1200,
      bars, markers: [], older_cursor: bars[0].time, exhausted: false, continuation: null,
      warmup: "ready", source: "alpaca_sip", price_basis: "raw", fills_truncated: false, issue: null } }); } catch { /* navigation aborted the old request */ }
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.waitForTimeout(120); // past the reset's programmatic-range window
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10, to: 60 }));
  await expect(page.getByRole("button", { name: "Retry history" })).toBeVisible();
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.getByRole("button", { name: "Retry history" }).click();
  await expect.poll(async () => Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeGreaterThan(100);
  await expect.poll(async () => (await logicalRange(page, "main"))?.from ?? 0).toBeGreaterThan(1000);
  await page.waitForTimeout(120);
  holdNext = true;
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10, to: 60 }));
  await expect.poll(() => release !== undefined).toBe(true);
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  release?.();
  await expect(page.getByRole("region", { name: /NVDA 5m chart/ })).toBeVisible();
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await expect(page.getByLabel("main candle values")).toContainText("Tradier");
});

test("history retention stays under 12,000, refills a newer gap, and returns to live", async ({ page }) => {
  await registerCharts(page);
  const state = await deepHistoryStub(page, 9);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  let previous = 0;
  let previousReset = await resets(page);
  for (let index = 0; index < 25; index++) {
    await page.waitForTimeout(120);
    await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10, to: 60 }));
    await page.waitForTimeout(180);
    if ((await visibleRange(page, "main"))!.from <= state.bars[0].time + 86400 * 5) break;
    await expect.poll(() => state.requests()).toBeGreaterThan(previous);
    previous = state.requests();
    await expect.poll(() => resets(page)).toBeGreaterThan(previousReset);
    previousReset = await resets(page);
    expect(Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeLessThanOrEqual(12000);
  }
  expect(previous).toBeGreaterThanOrEqual(10);
  const count = state.requests();
  const n = Number(await page.getByTestId("canvas-main").getAttribute("data-bars"));
  await page.evaluate((length) => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: length - 220, to: length - 80 }), n);
  await expect.poll(() => state.requests()).toBeGreaterThan(count); // reread a page near the retained live tail
  expect(Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeLessThanOrEqual(12000);
  await page.getByRole("button", { name: "Latest candles main" }).click();
  await expect.poll(async () => (await visibleRange(page, "main"))?.to ?? 0).toBeGreaterThan(state.bars.at(-1)!.time);
});

test.describe("phone deep history", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("touch panning loads an older 5m page without horizontal overflow", async ({ page }) => {
    await registerCharts(page);
    const state = await deepHistoryStub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
    await page.getByTestId("canvas-main").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await page.getByTestId("canvas-main").boundingBox())!;
    const client = await page.context().newCDPSession(page);
    const y = Math.round(box.y + box.height / 2);
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: Math.round(box.x + 90), y }] });
    for (let x = 110; x <= 330; x += 20) {
      await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: Math.round(box.x + x), y }] });
      await page.waitForTimeout(20);
    }
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect.poll(() => state.requests()).toBeGreaterThan(0);
    await expect.poll(async () => Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeGreaterThan(100);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath("deep-history-phone.png"), fullPage: true });
  });
});

test("linked time ranges follow the chart being moved, by time, without feedback", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  // Continuous history ending now, so every interval covers the same moments.
  const end = Math.floor(Date.now() / 1000);
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const data = fixture(route.request().url());
    for (const [interval, panel] of Object.entries(data.panels) as [Interval, NonNullable<ChartData["panels"][Interval]>][]) {
      const step = STEP[interval];
      const count = Math.min(1200, Math.ceil((intradayOnly(interval) ? 3 * 86400 : 200 * 86400) / step));
      const template = panel.bars[0];
      panel.bars = Array.from({ length: count }, (_, i) => {
        const time = end - (count - i) * step;
        const close = 245 + Math.sin(i / 11) * 3;
        return { ...template, time, end_time: time + step, open: close - 0.2, high: close + 0.5, low: close - 0.5, close };
      });
      panel.markers = [];
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-Panel 2").locator("canvas").first()).toBeVisible();
  const unlinked = await visibleRange(page, "Panel 2");
  const main = page.getByTestId("canvas-main");
  const box = (await main.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.3, box.y + 120);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(300);
  expect(await visibleRange(page, "Panel 2")).toEqual(unlinked);

  await page.getByRole("button", { name: "Link time ranges" }).click();
  await expect(page.getByRole("button", { name: "Link time ranges" })).toHaveAttribute("aria-pressed", "true");
  await page.mouse.move(box.x + 60, box.y + 120);
  await page.mouse.down();
  await page.mouse.move(box.x + 360, box.y + 120, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const lead = (await visibleRange(page, "main"))!;
  const middle = (lead.from + lead.to) / 2;
  for (const id of ["Panel 2", "Panel 3", "Panel 5"]) {
    const range = (await visibleRange(page, id))!;
    expect(range.from, `${id} starts at or before the main window`).toBeLessThanOrEqual(middle);
    expect(range.to, `${id} ends at or after the main window`).toBeGreaterThanOrEqual(middle);
  }
  // The 15m panel shows the same span of time as the 5m main chart, not the same bar count.
  const fifteen = (await visibleRange(page, "Panel 2"))!;
  expect(Math.abs((fifteen.to - fifteen.from) - (lead.to - lead.from))).toBeLessThanOrEqual(2 * 900 + 600);
  // Settled: nothing keeps re-broadcasting.
  const settled = await Promise.all(["main", "Panel 2", "Panel 3", "Panel 4", "Panel 5"].map((id) => visibleRange(page, id)));
  await page.waitForTimeout(600);
  expect(await Promise.all(["main", "Panel 2", "Panel 3", "Panel 4", "Panel 5"].map((id) => visibleRange(page, id)))).toEqual(settled);
  // Moving a smaller chart drives the main one too.
  const small = (await page.getByTestId("canvas-Panel 2").boundingBox())!;
  await page.mouse.move(small.x + 40, small.y + 80);
  await page.mouse.down();
  await page.mouse.move(small.x + 200, small.y + 80, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(400);
  const moved = (await visibleRange(page, "main"))!;
  expect(moved).not.toEqual(lead);
});

test("full-screen mode hides navigation, grows the main chart, and resizes smaller charts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page);
  await page.goto("/charts");
  const main = page.getByTestId("canvas-main");
  await expect(main).toBeVisible();
  const normal = (await main.boundingBox())!.height;
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true");
  // The app navigation sits at the left edge; the workspace now covers it.
  expect(await page.evaluate(() => !!document.elementFromPoint(8, 450)?.closest("[data-testid=chart-workspace]"))).toBe(true);
  expect((await main.boundingBox())!.height).toBeGreaterThan(normal);
  await expect(page.getByRole("region", { name: "Watchlist" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Saved price levels" })).toHaveCount(0);
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(page.getByRole("region", { name: "Watchlist" })).toBeVisible();
  await page.getByRole("button", { name: "compact small charts" }).click();
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 3").boundingBox())!.height).toBe(160);
  await page.getByRole("button", { name: "Expand 15m chart" }).click();
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 2").boundingBox())!.height).toBeGreaterThan(400);
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 2").boundingBox())!.width).toBeGreaterThan(900);
  await page.screenshot({ path: test.info().outputPath("charts-immersive-desktop.png") });
  await page.getByRole("button", { name: "Shrink 15m chart" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");
  await expect(page.getByRole("region", { name: "Saved price levels" })).toBeVisible();
  // Height preference is saved; expansion is not.
  await page.reload();
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 3").boundingBox())!.height).toBe(160);
});

test("full-screen mode works on a phone with a reachable exit", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  const exit = page.getByRole("button", { name: "Exit full-screen charts" });
  await expect(exit).toBeInViewport();
  expect((await page.getByTestId("canvas-main").boundingBox())!.height).toBeGreaterThanOrEqual(500);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await page.getByTestId("chart-workspace").evaluate((el) => el.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath("charts-immersive-mobile.png") });
  // Scrolled down to the smaller charts, the sticky exit stays on screen.
  await page.getByTestId("chart-workspace").evaluate((el) => el.scrollTo(0, 900));
  await expect(exit).toBeInViewport();
  await exit.click();
  await expect(page.getByRole("heading", { name: "Charts", exact: true })).toBeVisible();
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");
});

test("Cmd/Ctrl+K and the watchlist switch symbols by keyboard and keep timeframes", async ({ page }) => {
  let requests = 0;
  await stub(page, () => { requests++; });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.getByLabel("Main interval", { exact: true }).selectOption("30m");
  await expect(page.getByRole("region", { name: "MRVL 30m chart" })).toBeVisible();
  const settled = requests;
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog", { name: "Symbol search" });
  await expect(dialog).toBeVisible();
  await page.keyboard.type("nv");
  await expect(dialog.getByRole("option")).toHaveText([/NVDA/, /Chart NV$/]);
  await expect(dialog.getByRole("option", { selected: true })).toContainText("NVDA");
  expect(requests).toBe(settled);
  await page.keyboard.press("Enter");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("region", { name: "NVDA 30m chart" })).toBeVisible();

  await page.keyboard.press("ControlOrMeta+k");
  await expect(dialog.getByRole("option").first()).toContainText("MRVL");
  await expect(dialog.getByRole("option").first()).toContainText("Recent");
  await page.keyboard.type("tsla");
  await expect(dialog.getByRole("option", { selected: true })).toContainText("Chart TSLA");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("region", { name: "NVDA 30m chart" })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await expect(dialog.getByRole("option", { selected: true })).toContainText("MRVL");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "MRVL 30m chart" })).toBeVisible();

  // Arrow keys move through watchlist rows; Enter charts the focused row.
  await page.getByRole("button", { name: "Chart SPY", exact: true }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Chart QQQ", exact: true })).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByRole("button", { name: "Chart MSFT", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "MSFT 30m chart" })).toBeVisible();
  // Alt+Arrow steps the charted symbol through the watchlist from anywhere.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Alt+ArrowDown");
  await expect(page.getByRole("region", { name: "SPY 30m chart" })).toBeVisible();
  await expect(page.getByLabel("Panel 2 interval")).toHaveValue("15m");
});

// ---- Server-saved settings: shared levels and layout, revision conflicts, offline copy ----

const levelsPanel = (page: Page) => page.getByRole("region", { name: "Saved price levels" });
const syncStatus = (page: Page) => page.getByRole("status", { name: "Chart settings" });
async function addLevel(page: Page, label: string, value: string) {
  await page.getByLabel("Level label").fill(label);
  await page.getByLabel("Level price", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Save price level" }).click();
  await expect(levelsPanel(page)).toContainText(label);
}
type SavedLevels = { data: { levels?: Record<string, { label: string }[]> } | null; revision: number };
const savedLabels = (saved: SavedLevels) => (saved.data?.levels?.MRVL ?? []).map((level) => level.label);

test("a level saved in one browser appears in another, and a stale save is refused", { tag: "@real-settings" }, async ({ page, browser, request }) => {
  const run = Date.now().toString(36);
  const [desk, phone, later] = [`Desk ${run}`, `Phone ${run}`, `Late ${run}`];
  // The e2e database outlives a run: start from empty settings.
  const start: SavedLevels = await (await request.get("/api/backend/charts/settings")).json();
  if (start.revision) expect((await request.put("/api/backend/charts/settings", { data: { base_revision: start.revision, data: {} } })).ok()).toBe(true);
  await stub(page);
  await page.goto("/charts");
  await addLevel(page, desk, "263.50");
  const serverLabels = async () => savedLabels(await (await request.get("/api/backend/charts/settings")).json());
  await expect.poll(serverLabels).toContain(desk);
  await expect(syncStatus(page)).toHaveText("Saved");

  // A second browser (its own storage, like a phone) opens the same workspace.
  const other = await browser.newContext();
  const phonePage = await other.newPage();
  await stub(phonePage);
  await phonePage.goto("/charts");
  await expect(levelsPanel(phonePage)).toContainText(desk);
  await addLevel(phonePage, phone, "264.10");
  await expect.poll(serverLabels).toContain(phone);
  await expect(syncStatus(phonePage)).toHaveText("Saved");
  const current: SavedLevels = await (await request.get("/api/backend/charts/settings")).json();
  expect(savedLabels(current)).toEqual(expect.arrayContaining([desk, phone]));
  expect(current.data).not.toHaveProperty("symbol"); // the symbol on screen stays per device

  // A save based on an older revision is refused and changes nothing.
  const stale = await request.put("/api/backend/charts/settings", { data: { base_revision: current.revision - 1, data: {} } });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).detail.current.revision).toBe(current.revision);
  expect(await (await request.get("/api/backend/charts/settings")).json()).toEqual(current);

  // The first browser saves again from wherever it is; nothing either browser added is lost.
  await addLevel(page, later, "265.00");
  await expect.poll(serverLabels).toEqual(expect.arrayContaining([desk, phone, later]));
  await expect(levelsPanel(page)).toContainText(phone);
  await other.close();
});

test("settings kept in a browser before the server saved them merge with another device's", async ({ page, context }) => {
  const server = await fakeChartSettings(context, { revision: 3, data: {
    intervals: ["5m", "15m", "1h", "1D", "1m"], watchlist: ["SPY", "TSLA"], session: "extended", layout: "multi",
    levels: { MRVL: [{ id: "phone-1", price: 250, label: "Phone level" }] }, smallSize: "normal" } });
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    localStorage.setItem("tradejournal.charts.v1", JSON.stringify({ symbol: "NVDA", recent: ["MRVL"],
      watchlist: ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT", "COIN"],
      levels: { MRVL: [{ id: "desk-1", price: 263.5, label: "Desk level" }] } }));
  });
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("NVDA"); // this device's symbol
  await expect.poll(() => server.saves.length).toBe(1);
  await expect(syncStatus(page)).toHaveText("Saved");
  expect(server.saves[0]).toMatchObject({ base: 3, status: 200 });
  const saved = server.data as { levels: Record<string, { label: string }[]>; watchlist: string[] };
  expect(saved.levels.MRVL.map((level) => level.label)).toEqual(["Phone level", "Desk level"]);
  expect(saved.watchlist).toEqual(["SPY", "TSLA", "COIN"]); // the other device's list, plus what this browser added
  expect(saved).not.toHaveProperty("symbol");
  expect(saved).not.toHaveProperty("recent");
  await page.reload();
  await expect(page.getByLabel("Selected symbol quote")).toContainText("NVDA");
  await page.getByLabel("Chart symbol").fill("MRVL");
  await page.getByRole("button", { name: "Load symbol" }).click();
  await expect(levelsPanel(page)).toContainText("Phone level");
  await expect(levelsPanel(page)).toContainText("Desk level");
  expect(server.saves).toHaveLength(1);
});

for (const outcome of ["arrive", "fail"] as const) {
  test(`changes made while saved settings load are kept when they ${outcome}`, async ({ page, context }) => {
    const server = await fakeChartSettings(context, { revision: 2, data: { levels: { MRVL: [{ id: "phone", price: 250, label: "Phone level" }] } } });
    let release = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    await context.route("**/api/backend/charts/settings", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await held;
      if (outcome === "fail") server.offline = true;
      await route.fallback();
    });
    await page.addInitScript(() => localStorage.setItem("tradejournal.charts.v1",
      JSON.stringify({ levels: { MRVL: [{ id: "desk", price: 263.5, label: "Desk level" }] } })));
    await stub(page);
    await page.goto("/charts");
    await expect(syncStatus(page)).toHaveText("Loading saved settings");
    await expect(levelsPanel(page)).toContainText("Desk level"); // this browser's copy, not the defaults
    await page.getByRole("button", { name: "EMA 200", exact: true }).click();
    await addLevel(page, "While loading", "264.00");
    await expect(syncStatus(page)).toHaveText("Loading saved settings"); // both changes made before the server answered
    release();
    await expect(syncStatus(page)).toHaveText(outcome === "arrive" ? "Saved" : "Saved in this browser · server unavailable");
    await expect(page.getByRole("button", { name: "EMA 200", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(levelsPanel(page)).toContainText("While loading");
    await expect(levelsPanel(page)).toContainText("Desk level");
    if (outcome === "fail") return;
    await expect(levelsPanel(page)).toContainText("Phone level");
    await expect.poll(() => server.saves.length).toBe(1);
    expect(server.saves[0]).toMatchObject({ base: 2, status: 200 });
    const saved = server.data as { levels: Record<string, { label: string }[]>; indicators: Record<string, boolean> };
    expect(saved.levels.MRVL.map((level) => level.label)).toEqual(["Phone level", "Desk level", "While loading"]);
    expect(saved.indicators.ema200).toBe(true);
  });
}

test("a save refused as stale keeps the other device's change and this one", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await stub(page);
  await page.goto("/charts");
  await addLevel(page, "First", "263.50");
  await expect.poll(() => server.revision).toBe(1);
  await expect(syncStatus(page)).toHaveText("Saved");
  // Another device saves revision 2 without this page knowing.
  const data = server.data as { levels: Record<string, unknown[]>; indicators: Record<string, boolean> };
  server.data = { ...data, indicators: { ...data.indicators, ema200: true },
    levels: { MRVL: [...data.levels.MRVL, { id: "other", price: 270, label: "Other device" }] } };
  server.revision = 2;
  await addLevel(page, "Second", "264.00");
  await expect(syncStatus(page)).toHaveText("Merged with changes from another device");
  await expect(levelsPanel(page)).toContainText("Other device");
  await expect(page.getByRole("button", { name: "EMA 200", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => server.revision).toBe(3);
  expect(server.saves.map((save) => [save.base, save.status])).toEqual([[0, 200], [1, 409], [2, 200]]);
  const levels = (server.data as { levels: Record<string, { label: string }[]> }).levels.MRVL.map((level) => level.label);
  expect(levels).toEqual(["First", "Other device", "Second"]);
  await page.getByRole("button", { name: "Volume", exact: true }).click();
  await expect(syncStatus(page)).toHaveText("Saved");
});

test("without the server, settings stay in this browser and save when it returns; other devices' changes arrive on focus", async ({ page, context }) => {
  const server = await fakeChartSettings(context, { offline: true });
  await stub(page);
  await page.goto("/charts");
  await expect(syncStatus(page)).toHaveText("Saved in this browser · server unavailable");
  await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5); // charts do not wait for it
  await addLevel(page, "Offline level", "262.00");
  await expect.poll(() => server.saves.length).toBe(1); // tried, refused
  await page.reload();
  await expect(levelsPanel(page)).toContainText("Offline level"); // the browser copy
  await expect.poll(() => server.saves.length).toBe(2); // tried again after the reload, refused
  await expect(syncStatus(page)).toHaveText("Saved in this browser · server unavailable");
  server.offline = false;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(syncStatus(page)).toHaveText("Saved");
  expect(server.saves.map((save) => [save.base, save.status])).toEqual([[0, 503], [0, 503], [0, 200]]);
  // Another device adds a level; this page picks it up when it regains focus.
  const data = server.data as { levels: Record<string, unknown[]> };
  server.data = { ...data, levels: { MRVL: [...data.levels.MRVL, { id: "phone", price: 261, label: "From phone" }] } };
  server.revision += 1;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(levelsPanel(page)).toContainText("From phone");
  expect(server.saves).toHaveLength(3);
});

// ---- Per-panel symbols (C7.1): SPY, QQQ and the traded name side by side ----

type StreamWindow = typeof window & { __streams: string[]; __emit: (type: string, value: unknown) => void };
async function mockStreams(page: Page) {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    const target = window as unknown as StreamWindow;
    target.__streams = [];
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      closed = false;
      constructor(url: string) {
        target.__streams.push(new URL(url, location.href).searchParams.get("symbols") ?? "");
        MockEventSource.current = this;
        queueMicrotask(() => this.emit("status", { state: "connected" }));
      }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { if (!this.closed) this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() { this.closed = true; }
    }
    target.__emit = (type, value) => MockEventSource.current?.emit(type, value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
}
const lastFixtureBar = (interval: Interval) => fixturePanels([interval])[interval]!.bars.at(-1)!;
async function trade(page: Page, symbol: string, value: number) {
  const at = Math.floor(Date.now() / 1000) + 5;
  const buckets = Object.fromEntries((["1m", "3m", "5m", "15m", "30m", "1h", "4h"] as const).map((interval) => {
    const time = lastFixtureBar(interval).time + STEP[interval]; // opens the next candle
    return [interval, { time, end_time: time + STEP[interval], extended: false }];
  }));
  await page.evaluate((tick) => (window as unknown as StreamWindow).__emit("tick", tick),
    { type: "tick", symbol, at, minute: Math.floor(at / 60) * 60, session: "regular", price: value, open: value, high: value, low: value, buckets });
}
async function holdSymbol(page: Page, panel: string, symbol: string) {
  await page.getByRole("button", { name: `${panel} symbol` }).click();
  const dialog = page.getByRole("dialog", { name: `Symbol for ${panel}` });
  await dialog.getByLabel("Search symbols").fill(symbol);
  await dialog.getByLabel("Search symbols").press("Enter");
  await expect(dialog).toHaveCount(0);
}
const values = (page: Page, id: string) => page.getByLabel(`${id} candle values`);

test("panels hold SPY and QQQ beside the traded name through symbol switches, streaming and pause", async ({ page }) => {
  await registerCharts(page);
  await mockStreams(page);
  const requests: URLSearchParams[] = [];
  await stub(page, (url) => requests.push(new URL(url).searchParams));
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");

  await holdSymbol(page, "Panel 3", "SPY");
  await holdSymbol(page, "Panel 5", "QQQ");
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect(page.getByRole("region", { name: "QQQ 1m chart" })).toBeVisible();
  await expect(values(page, "Panel 3")).toContainText(/C 6\d\d\.\d\d/); // SPY's candles, not MRVL's
  await expect(values(page, "Panel 5")).toContainText(/C 5\d\d\.\d\d/);
  await expect(values(page, "Panel 2")).toContainText(/C 2\d\d\.\d\d/);
  // A held chart says when its fill markers stop at the newest 1,000.
  await expect(page.getByRole("region", { name: "QQQ 1m chart" })).toContainText("Most recent 1,000 QQQ fills shown.");
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).not.toContainText("fills shown");
  expect(requests.at(-1)!.get("intervals")).toBe("5m,15m,1D");
  expect(requests.at(-1)!.get("extras")).toBe("QQQ:1m,SPY:1h");
  await expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.at(-1))).toBe("MRVL,QQQ,SPY");

  await page.screenshot({ path: test.info().outputPath("panel-symbols.png") });
  // A fourth symbol is refused; the panel keeps following MRVL.
  await holdSymbol(page, "Panel 2", "AAPL");
  await expect(page.getByRole("alert").filter({ hasText: "Charts show up to three symbols" })).toBeVisible();
  await expect(page.getByRole("region", { name: "MRVL 15m chart" })).toBeVisible();

  // Switching the main symbol moves the panels that follow it, and only those.
  const heldResets = await resets(page, "Panel 3");
  const spyChart = await page.evaluate(() => (window as unknown as { __tjCharts: Map<string, unknown>; __spy?: unknown }).__spy = (window as unknown as { __tjCharts: Map<string, unknown> }).__tjCharts.get("Panel 3"));
  expect(spyChart).toBeTruthy();
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  for (const name of ["NVDA 5m chart", "NVDA 15m chart", "NVDA 1D chart", "SPY 1h chart", "QQQ 1m chart"])
    await expect(page.getByRole("region", { name })).toBeVisible();
  await expect(page.getByLabel("Selected symbol quote")).toContainText("189.12");
  expect(await resets(page, "Panel 3")).toBe(heldResets); // SPY was never redrawn
  expect(await page.evaluate(() => { const w = window as unknown as { __tjCharts: Map<string, unknown>; __spy: unknown }; return w.__tjCharts.get("Panel 3") === w.__spy; })).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.at(-1))).toBe("NVDA,QQQ,SPY");

  // One stream carries all three; each chart applies only its own symbol's trades.
  await trade(page, "SPY", 701.25);
  await expect(values(page, "Panel 3")).toContainText("C 701.25");
  await expect(values(page, "main")).not.toContainText("701.25");
  await trade(page, "NVDA", 191.5);
  await expect(values(page, "main")).toContainText("C 191.50");
  await expect(values(page, "Panel 3")).toContainText("C 701.25");
  await expect(values(page, "Panel 5")).not.toContainText("191.50");
  // The headline follows NVDA's newest trade even after SPY trades again.
  await trade(page, "SPY", 702.5);
  await expect(values(page, "Panel 3")).toContainText("C 702.50");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("191.50");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("Live trade");
  await expect(page.getByText(/^Live trade \d+s ago$/)).toBeVisible();

  // Pause freezes every symbol; resume reconnects the same three.
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await trade(page, "SPY", 705);
  await expect(values(page, "Panel 3")).toContainText("C 702.50");
  await page.getByRole("button", { name: "Resume chart updates" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.length)).toBeGreaterThanOrEqual(3);
  expect(await page.evaluate(() => (window as unknown as StreamWindow).__streams.at(-1))).toBe("NVDA,QQQ,SPY");
  await trade(page, "SPY", 706.5);
  await expect(values(page, "Panel 3")).toContainText("C 706.50");

  // Linked time ranges still match charts by time across symbols.
  await page.getByRole("button", { name: "Link time ranges" }).click();
  await page.waitForTimeout(120);
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 150, to: 190 }));
  await page.waitForTimeout(300);
  const main = (await visibleRange(page, "main"))!;
  const held = (await visibleRange(page, "Panel 3"))!;
  const middle = (main.from + main.to) / 2;
  expect(held.from).toBeLessThanOrEqual(middle);
  expect(held.to).toBeGreaterThanOrEqual(middle);

  // Following again drops the symbol from requests and the stream.
  await page.getByRole("button", { name: "Panel 5 symbol" }).click();
  await page.getByRole("dialog", { name: "Symbol for Panel 5" }).getByRole("option", { name: /Follow the main chart \(NVDA\)/ }).click();
  await expect(page.getByRole("region", { name: "NVDA 1m chart" })).toBeVisible();
  await expect.poll(() => requests.at(-1)!.get("extras")).toBe("SPY:1h");
  await expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.at(-1))).toBe("NVDA,SPY");
});

test("a held panel scrolls back its own symbol, and focusing it swaps it with the main chart", async ({ page, context }) => {
  await registerCharts(page);
  const server = await fakeChartSettings(context);
  const history: string[] = [];
  await stub(page);
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const interval = query.get("interval") as Interval;
    const before = Number(query.get("before"));
    history.push(`${query.get("symbol")}:${interval}`);
    const bars = fixturePanels([interval], HELD_OFFSET[query.get("symbol")!] ?? 0)[interval]!.bars.map((bar) => ({ ...bar,
      time: bar.time - 60 * 86400, end_time: bar.end_time - 60 * 86400, source: "alpaca_sip" as const })).filter((bar) => bar.time < before); // the 60 days before
    return route.fulfill({ json: { symbol: query.get("symbol"), interval, session: query.get("session"), before, limit: 1200, bars, markers: [],
      older_cursor: bars[0]?.time ?? null, exhausted: true, continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "raw", fills_truncated: false, issue: null } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  await holdSymbol(page, "Panel 3", "SPY");
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect.poll(() => (server.data as { panelSymbols?: unknown } | null)?.panelSymbols).toEqual([null, null, "SPY", null, null]);

  // Scrolling the SPY chart asks for SPY's history at its own interval.
  await page.waitForTimeout(150);
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("Panel 3")!.timeScale().setVisibleLogicalRange({ from: 5, to: 40 }));
  await expect.poll(() => history).toContain("SPY:1h");
  expect(history.filter((entry) => entry.startsWith("MRVL")).every((entry) => entry !== "MRVL:1h")).toBe(true);
  await expect(page.getByTestId("canvas-Panel 3")).toHaveAttribute("data-bars", "480");


  // Focus: SPY becomes the main chart at 1h, and the panel keeps MRVL at 5m.
  await page.getByRole("button", { name: "Focus 1h chart" }).click();
  await expect(page.locator("section", { has: page.getByTestId("canvas-main") })).toHaveAttribute("aria-label", "SPY 1h chart");
  await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue("1h");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("SPY");
  await expect(page.getByRole("region", { name: "MRVL 5m chart" })).toBeVisible();
  await expect(page.getByRole("region", { name: "SPY 15m chart" })).toBeVisible(); // followers follow SPY now
  await expect(page.getByRole("region", { name: "Saved price levels" })).toContainText("SPY levels");
  await expect.poll(() => (server.data as { panelSymbols?: unknown } | null)?.panelSymbols).toEqual([null, null, "MRVL", null, null]);
});


// ---- Named layouts (C7.2): save, switch, rename, replace and delete arrangements ----

type SavedLayouts = { id: string; name: string; layout: string; intervals: string[]; panelSymbols: (string | null)[]; smallSize: string; linkRange: boolean }[];
const layoutsOn = (server: SettingsStore) => (server.data as { layouts?: SavedLayouts } | null)?.layouts ?? [];
const layoutNames = (server: SettingsStore) => layoutsOn(server).map((layout) => layout.name);
const layoutsButton = (page: Page) => page.getByRole("button", { name: /^Layouts/ });
const layoutsDialog = (page: Page) => page.getByRole("dialog", { name: "Saved layouts", exact: true });
const intervalsShown = (page: Page) => Promise.all(["Main", "Panel 2", "Panel 3", "Panel 4", "Panel 5"].map((id) => page.getByLabel(`${id} interval`, { exact: true }).inputValue()));
async function openLayouts(page: Page) {
  await layoutsButton(page).click();
  const dialog = layoutsDialog(page);
  await expect(dialog).toBeVisible();
  return dialog;
}
async function saveLayout(page: Page, name: string) {
  const dialog = await openLayouts(page);
  await dialog.getByLabel("Layout name", { exact: true }).fill(name);
  await dialog.getByRole("button", { name: "Save layout" }).click();
  await expect(dialog.getByRole("button", { name: `Use layout ${name}`, exact: true })).toHaveAttribute("aria-current", "true");
  await dialog.getByRole("button", { name: "Close layouts" }).click();
  await expect(dialog).toHaveCount(0);
}
async function useLayout(page: Page, name: string) {
  const dialog = await openLayouts(page);
  await dialog.getByRole("button", { name: `Use layout ${name}`, exact: true }).click();
  await expect(dialog).toHaveCount(0);
}
async function followMain(page: Page, panel: string, main: string) {
  await page.getByRole("button", { name: `${panel} symbol` }).click();
  await page.getByRole("dialog", { name: `Symbol for ${panel}` }).getByRole("option", { name: new RegExp(`Follow the main chart \\(${main}\\)`) }).click();
}

test("named layouts save, switch, rename, update and delete without moving the symbol, levels or watchlist", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  await expect(layoutsButton(page)).toHaveText("Layouts");
  await addLevel(page, "Support", "255.00");
  const dialog = await openLayouts(page);
  await expect(dialog).toContainText("No saved layouts yet");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // "Names": SPY and QQQ beside the traded name.
  await holdSymbol(page, "Panel 3", "SPY");
  await holdSymbol(page, "Panel 5", "QQQ");
  await saveLayout(page, "Names");
  await expect(layoutsButton(page)).toContainText("Names"); // the panels are arranged as this layout
  await expect.poll(() => layoutNames(server)).toEqual(["Names"]);
  expect(layoutsOn(server)[0]).toMatchObject({ layout: "multi", intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, "SPY", null, "QQQ"], smallSize: "normal", linkRange: false });

  // "Scalp": faster intervals on the traded name alone, tall charts, linked ranges.
  await followMain(page, "Panel 3", "MRVL");
  await followMain(page, "Panel 5", "MRVL");
  for (const [id, interval] of [["Main", "1m"], ["Panel 2", "3m"], ["Panel 3", "5m"], ["Panel 4", "15m"], ["Panel 5", "30m"]]) await page.getByLabel(`${id} interval`, { exact: true }).selectOption(interval);
  await page.getByRole("button", { name: "Link time ranges" }).click();
  await page.getByRole("button", { name: "tall small charts" }).click();
  await expect(layoutsButton(page)).toHaveText("Layouts"); // edited: no saved layout matches
  await saveLayout(page, "Scalp");
  await expect.poll(() => layoutNames(server)).toEqual(["Names", "Scalp"]);
  expect(layoutsOn(server)[1]).toMatchObject({ layout: "multi", intervals: ["1m", "3m", "5m", "15m", "30m"], panelSymbols: [null, null, null, null, null], smallSize: "tall", linkRange: true });

  // Switching back restores intervals, symbol groups, chart height and range linking.
  await useLayout(page, "Names");
  expect(await intervalsShown(page)).toEqual(["5m", "15m", "1h", "1D", "1m"]);
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect(page.getByRole("region", { name: "QQQ 1m chart" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Link time ranges" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "normal small charts" })).toHaveAttribute("aria-pressed", "true");
  await expect(layoutsButton(page)).toContainText("Names");

  // The main symbol, levels and watchlist belong to the workspace, not to a layout.
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await useLayout(page, "Scalp");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("NVDA");
  await expect(page.getByRole("region", { name: "NVDA 1m chart" }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: /SPY .* chart/ })).toHaveCount(0);
  await useLayout(page, "Names");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("NVDA");
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect(page.getByRole("region", { name: "NVDA 5m chart" })).toBeVisible();
  await expect(levelsPanel(page)).toContainText("NVDA levels");
  await page.getByRole("button", { name: "Chart MRVL", exact: true }).click();
  await expect(levelsPanel(page)).toContainText("Support");
  expect((server.data as { watchlist: string[] }).watchlist).toEqual(["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"]);
  expect((server.data as { levels: Record<string, { label: string }[]> }).levels.MRVL.map((level) => level.label)).toEqual(["Support"]);
  expect(server.data).not.toHaveProperty("symbol");

  // Rename. A name already used (ignoring case) is refused.
  let menu = await openLayouts(page);
  await page.screenshot({ path: test.info().outputPath("layouts-menu.png") });
  await menu.getByRole("button", { name: "Rename Names" }).click();
  // Symbol search stays closed behind the dialog, and the rename field keeps focus.
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog", { name: "Symbol search" })).toHaveCount(0);
  await expect(menu.getByLabel("Rename Names")).toBeFocused();
  await menu.getByLabel("Rename Names").fill("scalp");
  await menu.getByLabel("Rename Names").press("Enter");
  await expect(menu.getByRole("alert")).toHaveText("A layout named scalp already exists.");
  await menu.getByLabel("Rename Names").fill("Index  names");
  await menu.getByLabel("Rename Names").press("Enter");
  await expect(menu.getByRole("button", { name: "Use layout Index names" })).toHaveAttribute("aria-current", "true");
  await menu.getByLabel("Layout name", { exact: true }).fill("SCALP");
  await menu.getByRole("button", { name: "Save layout" }).click();
  await expect(menu.getByRole("alert")).toHaveText("A layout named SCALP already exists.");
  await expect.poll(() => layoutNames(server)).toEqual(["Index names", "Scalp"]);
  await menu.getByRole("button", { name: "Close layouts" }).click();

  // Edit a panel: no layout is in use until one is replaced with the new arrangement.
  await page.getByLabel("Panel 2 interval", { exact: true }).selectOption("30m");
  await expect(layoutsButton(page)).toHaveText("Layouts");
  menu = await openLayouts(page);
  await expect(menu.getByRole("button", { name: "Update Index names with the current arrangement" })).toBeEnabled();
  await menu.getByRole("button", { name: "Update Index names with the current arrangement" }).click();
  await expect(menu.getByRole("button", { name: "Update Index names with the current arrangement" })).toBeDisabled();
  await expect(menu.getByRole("button", { name: "Use layout Index names" })).toHaveAttribute("aria-current", "true");
  await menu.getByRole("button", { name: "Close layouts" }).click();
  await expect.poll(() => layoutsOn(server)[0].intervals[1]).toBe("30m");
  expect(layoutsOn(server)[1].intervals[1]).toBe("3m"); // the other layout is untouched

  // Delete asks first.
  menu = await openLayouts(page);
  await menu.getByRole("button", { name: "Delete Scalp" }).click();
  await expect(menu).toContainText("Delete Scalp?");
  await menu.getByRole("button", { name: "Keep" }).click();
  await expect(menu.getByRole("button", { name: "Use layout Scalp" })).toBeVisible();
  await menu.getByRole("button", { name: "Delete Scalp" }).click();
  await menu.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(menu.getByRole("button", { name: "Use layout Scalp" })).toHaveCount(0);
  await expect.poll(() => layoutNames(server)).toEqual(["Index names"]);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  // The saved layout survives a reload and is still the one in use.
  await page.reload();
  await expect(layoutsButton(page)).toContainText("Index names");
  await expect(syncStatus(page)).toHaveText("Saved");
});

test("a layout saved in one browser is usable in another with its symbol groups", { tag: "@real-settings" }, async ({ page, browser, request }) => {
  const run = Date.now().toString(36);
  const [desk, phone] = [`Desk ${run}`, `Phone ${run}`];
  const serverLayouts = async (): Promise<SavedLayouts> => (await (await request.get("/api/backend/charts/settings")).json()).data?.layouts ?? [];
  const start = await (await request.get("/api/backend/charts/settings")).json();
  if (start.revision) expect((await request.put("/api/backend/charts/settings", { data: { base_revision: start.revision, data: {} } })).ok()).toBe(true);
  await stub(page);
  await page.goto("/charts");
  await holdSymbol(page, "Panel 3", "SPY");
  await page.getByLabel("Panel 2 interval", { exact: true }).selectOption("30m");
  await saveLayout(page, desk);
  await expect.poll(async () => (await serverLayouts()).map((layout) => layout.name)).toEqual([desk]);
  await expect(syncStatus(page)).toHaveText("Saved");

  // A second browser (its own storage, like a phone) sees the saved layout and can switch to it.
  const other = await browser.newContext();
  const phonePage = await other.newPage();
  await stub(phonePage);
  await phonePage.goto("/charts");
  await expect(layoutsButton(phonePage)).toContainText(desk);
  await phonePage.getByLabel("Panel 2 interval", { exact: true }).selectOption("3m");
  await phonePage.getByRole("button", { name: "Panel 3 symbol" }).click();
  await phonePage.getByRole("dialog", { name: "Symbol for Panel 3" }).getByRole("option", { name: /Follow the main chart/ }).click();
  await expect(layoutsButton(phonePage)).toHaveText("Layouts");
  await useLayout(phonePage, desk);
  await expect(phonePage.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect(phonePage.getByLabel("Panel 2 interval", { exact: true })).toHaveValue("30m");

  // It saves a layout of its own, which the first browser picks up on focus next to the one it saved.
  await phonePage.getByLabel("Panel 4 interval", { exact: true }).selectOption("4h");
  await saveLayout(phonePage, phone);
  await expect.poll(async () => (await serverLayouts()).map((layout) => layout.name)).toEqual([desk, phone]);
  const saved = await serverLayouts();
  expect(saved[0]).toMatchObject({ intervals: ["5m", "30m", "1h", "1D", "1m"], panelSymbols: [null, null, "SPY", null, null] });
  expect(saved[1]).toMatchObject({ intervals: ["5m", "30m", "1h", "4h", "1m"], panelSymbols: [null, null, "SPY", null, null] });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const menu = await openLayouts(page);
  await expect(menu.getByRole("button", { name: `Use layout ${desk}` })).toBeVisible();
  await expect(menu.getByRole("button", { name: `Use layout ${phone}` })).toHaveAttribute("aria-current", "true");
  await menu.getByRole("button", { name: `Delete ${phone}` }).click();
  await menu.getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(async () => (await serverLayouts()).map((layout) => layout.name)).toEqual([desk]);
  await other.close();
});

test("a layout save refused as stale keeps the other device's layouts, renames and additions", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await stub(page);
  await page.goto("/charts");
  await saveLayout(page, "Alpha");
  await page.getByLabel("Panel 2 interval", { exact: true }).selectOption("30m");
  await saveLayout(page, "Beta");
  await expect.poll(() => layoutNames(server)).toEqual(["Alpha", "Beta"]);
  await expect(syncStatus(page)).toHaveText("Saved");

  // This device deletes Alpha and saves Delta while it cannot reach the server...
  server.offline = true;
  let menu = await openLayouts(page);
  await menu.getByRole("button", { name: "Delete Alpha" }).click();
  await menu.getByRole("button", { name: "Delete", exact: true }).click();
  await menu.getByLabel("Layout name", { exact: true }).fill("Delta");
  await menu.getByRole("button", { name: "Save layout" }).click();
  await menu.getByRole("button", { name: "Close layouts" }).click();
  await expect(syncStatus(page)).toHaveText("Saved in this browser · server unavailable");

  // ...while another device renamed Beta and saved Gamma and its own Delta.
  const theirs = layoutsOn(server);
  server.data = { ...(server.data as object), layouts: [theirs[0], { ...theirs[1], name: "Beta desk" },
    { ...theirs[0], id: "other-gamma", name: "Gamma", intervals: ["1m", "3m", "5m", "15m", "30m"] },
    { ...theirs[0], id: "other-delta", name: "Delta", intervals: ["1D", "1h", "30m", "15m", "5m"] }] };
  server.revision += 1;
  server.offline = false;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(syncStatus(page)).toHaveText("Merged with changes from another device");
  await expect.poll(() => layoutNames(server)).toEqual(["Beta desk", "Gamma", "Delta", "Delta (2)"]);
  expect(server.saves.map((save) => save.status).slice(-2)).toEqual([409, 200]);
  const merged = layoutsOn(server);
  expect(merged.map((layout) => layout.id)).not.toContain(theirs[0].id); // Alpha stays deleted
  expect(merged[0]).toMatchObject({ id: theirs[1].id, intervals: ["5m", "30m", "1h", "1D", "1m"] }); // Beta kept its arrangement
  expect(merged[1]).toMatchObject({ id: "other-gamma", intervals: ["1m", "3m", "5m", "15m", "30m"] });
  expect(merged[2]).toMatchObject({ id: "other-delta", intervals: ["1D", "1h", "30m", "15m", "5m"] });
  expect(merged[3]).toMatchObject({ intervals: ["5m", "30m", "1h", "1D", "1m"] }); // this device's Delta, renamed to tell them apart
  menu = await openLayouts(page);
  for (const name of ["Beta desk", "Gamma", "Delta", "Delta (2)"]) await expect(menu.getByRole("button", { name: `Use layout ${name}`, exact: true })).toBeVisible();
  await expect(menu.getByRole("button", { name: "Use layout Alpha" })).toHaveCount(0);
});

test("saved layouts that are malformed are dropped whole and duplicate names are told apart", async ({ page, context }) => {
  const names = (name: string, extra: object = {}) => ({ id: `id-${name}`, name, layout: "multi", intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, null, null, null], smallSize: "normal", linkRange: false, ...extra });
  await fakeChartSettings(context, { revision: 1, data: { layouts: [
    names("Index", { panelSymbols: [null, "SPY", "QQQ", null, null] }),
    // None of these is an arrangement anyone saved, so none is repaired into one.
    names("Three held", { panelSymbols: [null, "SPY", "QQQ", "AAPL", null] }),
    names("No held list", { panelSymbols: undefined }), names("Short held list", { panelSymbols: [null, "SPY"] }),
    names("Main holds", { panelSymbols: ["SPY", null, null, null, null] }), names("Bad symbol", { panelSymbols: [null, "spy!", null, null, null] }),
    names("Bad mode", { layout: "grid" }), names("No mode", { layout: undefined }), names("Bad size", { smallSize: "huge" }), names("Bad link", { linkRange: "yes" }),
    names("Four intervals", { intervals: ["5m", "15m", "1h", "1D"] }), names("Bad interval", { intervals: ["5m", "15m", "1h", "1D", "2m"] }),
    names("   "), { ...names("No id"), id: undefined }, "nonsense", null,
    names("Index", { id: "second-index", layout: "single" }),
    names("Copy", { id: "id-Index" }), // reuses an id
  ] } });
  await stub(page);
  await page.goto("/charts");
  const menu = await openLayouts(page);
  await expect(menu.getByRole("list", { name: "Saved layouts list" }).getByRole("listitem")).toHaveCount(2);
  await expect(menu.getByRole("button", { name: "Use layout Index", exact: true })).toContainText("5m | 15m | 1h | 1D | 1m · SPY, QQQ");
  await expect(menu.getByRole("button", { name: "Use layout Index (2)", exact: true })).toContainText(/^Index \(2\)\s*5m$/);
});

test("two devices that each save a layout at the limit both keep it, and the menu shows the overflow", async ({ page, context }) => {
  const layout = (n: number, extra: object = {}) => ({ id: `id-${n}`, name: `Layout ${n}`, layout: "multi", intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, null, null, null], smallSize: "normal", linkRange: false, ...extra });
  const eleven = Array.from({ length: 11 }, (_, n) => layout(n + 1));
  const server = await fakeChartSettings(context, { revision: 1, data: { layouts: eleven } });
  await stub(page);
  await page.goto("/charts");
  let menu = await openLayouts(page);
  await expect(menu).toContainText("11/12");
  await menu.getByRole("button", { name: "Close layouts" }).click();

  // This device saves the twelfth while it cannot reach the server, and another device saves its own twelfth.
  server.offline = true;
  await page.getByLabel("Panel 2 interval", { exact: true }).selectOption("30m");
  await saveLayout(page, "Mine");
  await expect(syncStatus(page)).toHaveText("Saved in this browser · server unavailable");
  server.data = { layouts: [...eleven, layout(12, { name: "Theirs", id: "other-12" })] };
  server.revision += 1;
  server.offline = false;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(syncStatus(page)).toHaveText("Merged with changes from another device");
  await expect.poll(() => layoutNames(server).length).toBe(13);
  expect(layoutNames(server).slice(-2)).toEqual(["Theirs", "Mine"]); // neither is dropped

  // Over the limit the menu says so, refuses another, and lets one go.
  menu = await openLayouts(page);
  await expect(menu).toContainText("13/12");
  await expect(menu.getByRole("button", { name: "Use layout Mine", exact: true })).toBeVisible();
  await expect(menu.getByRole("button", { name: "Use layout Theirs", exact: true })).toBeVisible();
  await menu.getByLabel("Layout name", { exact: true }).fill("One more");
  await menu.getByRole("button", { name: "Save layout" }).click();
  await expect(menu.getByRole("alert")).toContainText("Delete a layout before saving another");
  await menu.getByRole("button", { name: "Delete Layout 1", exact: true }).click();
  await menu.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(menu).toContainText("12/12");
  await expect.poll(() => layoutNames(server).length).toBe(12);
});

test.describe("phone layouts", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the layouts sheet fits the screen, saves and switches by touch, and works full screen", async ({ page, context }) => {
    const server = await fakeChartSettings(context);
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main")).toBeVisible();
    await page.getByRole("button", { name: "Show single chart" }).click();
    await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(1);
    await layoutsButton(page).tap();
    let dialog = layoutsDialog(page);
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Layout name", { exact: true }).fill("Focus");
    await dialog.getByRole("button", { name: "Save layout" }).tap();
    await expect(dialog.getByRole("button", { name: "Use layout Focus" })).toHaveAttribute("aria-current", "true");
    // A bottom sheet inside the viewport with touch-sized controls.
    const sheet = (await dialog.boundingBox())!;
    expect(sheet.x).toBeGreaterThanOrEqual(0);
    expect(sheet.x + sheet.width).toBeLessThanOrEqual(390);
    expect(sheet.y + sheet.height).toBeLessThanOrEqual(844);
    expect(sheet.y + sheet.height).toBeGreaterThan(780);
    for (const name of ["Update Focus with the current arrangement", "Rename Focus", "Delete Focus", "Use layout Focus"]) {
      const box = (await dialog.getByRole("button", { name }).boundingBox())!;
      expect(Math.min(box.width, box.height), name).toBeGreaterThanOrEqual(32);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("layouts-sheet-mobile.png") });
    await dialog.getByRole("button", { name: "Close layouts" }).tap();

    // Back to five charts, then the single-chart layout in one tap.
    await page.getByRole("button", { name: "Show five charts" }).tap();
    await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(5);
    await layoutsButton(page).tap();
    await dialog.getByRole("button", { name: "Use layout Focus" }).tap();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("region", { name: /MRVL .* chart/ })).toHaveCount(1);
    await expect.poll(() => layoutNames(server)).toEqual(["Focus"]);

    // Full screen: the button is in the sticky header and the sheet sits above the charts.
    await page.getByRole("button", { name: "Enter full-screen charts" }).tap();
    await layoutsButton(page).tap();
    dialog = layoutsDialog(page);
    await expect(dialog).toBeInViewport();
    await expect(dialog.getByRole("button", { name: "Use layout Focus" })).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true"); // Escape closed the sheet only
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Hotkeys (C0.5): typed and immediate intervals, watchlist steps, view resets, cheat sheet ----

type ScaleRegistry = Map<string, { priceScale(id: string, pane?: number): { applyOptions(o: { autoScale: boolean }): void; options(): { autoScale: boolean } };
  timeScale(): { setVisibleLogicalRange(r: { from: number; to: number }): void } }>;
const mainInterval = (page: Page) => page.getByLabel("Main interval", { exact: true });
const intervalEntry = (page: Page) => page.getByRole("status", { name: "Interval entry" });
const chartedSymbol = (page: Page) => page.getByLabel("Chart symbol");
/** Zoom and scroll a chart away from its latest candles and stop its price scales autoscaling, as a user dragging the axis does. */
async function moveAway(page: Page, id: string, range: { from: number; to: number }) {
  // Lightweight Charts applies a range on its next frame; wait until it has.
  await expect.poll(async () => {
    await page.evaluate(({ id, range }) => {
      const chart = (window as unknown as { __tjCharts: ScaleRegistry }).__tjCharts.get(id)!;
      chart.timeScale().setVisibleLogicalRange(range);
      for (const pane of [0, 1]) chart.priceScale("right", pane).applyOptions({ autoScale: false });
    }, { id, range });
    await page.waitForTimeout(50);
    return roundedRange(page, id);
  }).toEqual(range);
}
const autoScaled = (page: Page, id: string) => page.evaluate((id) => {
  const chart = (window as unknown as { __tjCharts: ScaleRegistry }).__tjCharts.get(id)!;
  return [0, 1].map((pane) => chart.priceScale("right", pane).options().autoScale);
}, id);
const roundedRange = async (page: Page, id: string) => { const range = await logicalRange(page, id); return range && { from: Math.round(range.from), to: Math.round(range.to) }; };

test("typed minutes change the main interval only on Enter; Backspace erases, Escape and a click cancel", async ({ page }) => {
  // The main chart's interval leads each request, so a 1m detour on the way to 15m would show here.
  const mains: string[] = [];
  await stub(page, (url) => { mains.push((new URL(url).searchParams.get("intervals") ?? "").split(",")[0]); });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  const entry = intervalEntry(page);
  const typed = entry.locator("div").first();
  await expect(mainInterval(page)).toHaveValue("5m");
  await page.keyboard.press("1");
  await expect(typed).toHaveText("1m");
  await expect(entry).toContainText("Enter to apply · Esc to cancel");
  await page.keyboard.press("5");
  await expect(typed).toHaveText("15m");
  await expect(mainInterval(page)).toHaveValue("5m");
  await page.screenshot({ path: test.info().outputPath("interval-entry.png") });
  await page.keyboard.press("Enter");
  await expect(entry).toHaveCount(0);
  await expect(mainInterval(page)).toHaveValue("15m");
  await expect(page.getByRole("region", { name: "MRVL 15m chart" }).first()).toBeVisible();
  expect(mains).toContain("15m");
  expect(mains).not.toContain("1m");

  // An interval that does not exist is refused in place; Backspace erases digits.
  await page.keyboard.press("7");
  await page.keyboard.press("Enter");
  await expect(entry).toContainText("No 7m interval. Type 1, 3, 5, 15 or 30.");
  await expect(mainInterval(page)).toHaveValue("15m");
  await page.keyboard.press("Backspace");
  await expect(entry).toHaveCount(0);
  await page.keyboard.press("3");
  await page.keyboard.press("5");
  await page.keyboard.press("Backspace");
  await expect(typed).toHaveText("3m");
  await page.keyboard.press("0");
  await page.keyboard.press("Enter");
  await expect(mainInterval(page)).toHaveValue("30m");
  // Typed digits are the main chart's only: 1 then Enter is 1m, and the smaller charts stay.
  await page.keyboard.press("1");
  await page.keyboard.press("Enter");
  await expect(mainInterval(page)).toHaveValue("1m");
  await expect(page.getByLabel("Panel 2 interval")).toHaveValue("15m");

  // Escape cancels the digits without leaving full screen; the next Escape leaves.
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await page.keyboard.press("3");
  await expect(typed).toHaveText("3m");
  await page.keyboard.press("Escape");
  await expect(entry).toHaveCount(0);
  await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true");
  // A click elsewhere drops them too, so a later Enter means nothing.
  await page.keyboard.press("5");
  await expect(typed).toHaveText("5m");
  await page.getByRole("heading", { name: "Charts", exact: true }).click();
  await expect(entry).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(mainInterval(page)).toHaveValue("1m");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");
});

test("H, 4, D and W switch the main chart at once; hotkeys stay off in fields and under dialogs", async ({ page }) => {
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  for (const [key, interval] of [["h", "1h"], ["4", "4h"], ["Shift+D", "1D"], ["w", "1W"]] as const) {
    await page.keyboard.press(key);
    await expect(mainInterval(page)).toHaveValue(interval);
    await expect(intervalEntry(page)).toHaveCount(0);
    await expect(page.getByRole("region", { name: `MRVL ${interval} chart` }).first()).toBeVisible();
  }
  await expect(page.getByLabel("Panel 2 interval")).toHaveValue("15m");

  // Typing in a field types; it never changes the chart.
  await chartedSymbol(page).click();
  await page.keyboard.type("hd 15");
  await expect(chartedSymbol(page)).toHaveValue("HD 15");
  await page.getByLabel("Level label").click();
  await page.keyboard.type("4 W");
  await expect(page.getByLabel("Level label")).toHaveValue("4 W");
  await expect(intervalEntry(page)).toHaveCount(0);
  await page.getByLabel("Panel 2 interval").focus();
  await page.keyboard.press("h");
  await expect(page.getByLabel("Panel 2 interval")).toHaveValue("15m");
  await expect(mainInterval(page)).toHaveValue("1W");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "MRVL");

  // With a dialog open the keys belong to it.
  await page.getByRole("button", { name: /^Layouts/ }).click();
  await expect(page.getByRole("dialog", { name: "Saved layouts" })).toBeVisible();
  await page.keyboard.press("d");
  await page.keyboard.press("Space");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Saved layouts" })).toHaveCount(0);
  await expect(mainInterval(page)).toHaveValue("1W");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "MRVL");

  // So do the app's own overlays: the Sync drawer covers the charts and takes every key.
  await page.getByTitle("Sync & enrichment status").filter({ visible: true }).click();
  await expect(page.getByRole("dialog", { name: "Background jobs" })).toBeVisible();
  // Off the Sync button, which Space would press like any focused button.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (const key of ["d", "Space", "?", "End", "1", "Enter", "ControlOrMeta+k"]) await page.keyboard.press(key);
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "Symbol search" })).toHaveCount(0);
  await expect(intervalEntry(page)).toHaveCount(0);
  await expect(mainInterval(page)).toHaveValue("1W");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "MRVL");
  await page.mouse.click(1000, 400); // the backdrop beside the drawer closes it
  await expect(page.getByRole("dialog", { name: "Background jobs" })).toHaveCount(0);
  await page.keyboard.press("d");
  await expect(mainInterval(page)).toHaveValue("1D");
});

test("Space and Shift+Space step through the watchlist; a button reached by keyboard keeps Space", async ({ page }) => {
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  const scrolled = await page.evaluate(() => window.scrollY);
  // MRVL is third on the default watchlist: SPY, QQQ, MRVL, NVDA, AMD, AAPL, META, MSFT.
  await page.keyboard.press("Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "NVDA");
  await expect(page.getByRole("region", { name: "NVDA 5m chart" })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "AMD");
  await page.keyboard.press("Shift+Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "NVDA");
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled); // Space does not scroll the page
  await expect(mainInterval(page)).toHaveValue("5m");

  // After a click on a watchlist row, Space still steps, and both ends wrap.
  await page.getByRole("button", { name: "Chart SPY", exact: true }).click();
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "SPY");
  await page.keyboard.press("Shift+Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "MSFT");
  await page.keyboard.press("Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "SPY");

  // A toggle clicked with the mouse is not pressed again by Space; one reached with Tab is.
  const linkRanges = page.getByRole("button", { name: "Link time ranges" });
  await linkRanges.click();
  await expect(linkRanges).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Space");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "QQQ");
  await expect(linkRanges).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Tab");
  const compact = page.getByRole("button", { name: "compact small charts" });
  await expect(compact).toBeFocused();
  await page.keyboard.press("Space");
  await expect(compact).toHaveAttribute("aria-pressed", "true");
  await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "QQQ");
});

test("Alt+R resets every chart's scales and End returns every chart to its latest candle at the same zoom", async ({ page }) => {
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-bars", "240");
  // Reset returns each chart to the view it opened on.
  await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 130, to: 244 });
  await expect.poll(async () => (await roundedRange(page, "Panel 2"))?.to).toBe(244);
  const opened = { main: await roundedRange(page, "main"), panel: await roundedRange(page, "Panel 2") };
  // Well clear of the left edge, so no older page is asked for.
  await moveAway(page, "main", { from: 120, to: 180 });
  await moveAway(page, "Panel 2", { from: 150, to: 170 });
  await page.keyboard.press("End");
  await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 184, to: 244 });
  await expect.poll(() => roundedRange(page, "Panel 2")).toEqual({ from: 224, to: 244 });
  expect(await autoScaled(page, "main")).toEqual([false, false]); // End keeps the price scale as it is

  await moveAway(page, "main", { from: 120, to: 180 });
  await moveAway(page, "Panel 2", { from: 150, to: 170 });
  await page.keyboard.press("Alt+r");
  await expect.poll(() => roundedRange(page, "main")).toEqual(opened.main);
  await expect.poll(() => roundedRange(page, "Panel 2")).toEqual(opened.panel);
  expect(await autoScaled(page, "main")).toEqual([true, true]);
  expect(await autoScaled(page, "Panel 2")).toEqual([true, true]);

  // With linked time ranges, each chart still goes to its own latest candle.
  await page.getByRole("button", { name: "Link time ranges" }).click();
  await moveAway(page, "main", { from: 120, to: 180 });
  await moveAway(page, "Panel 2", { from: 150, to: 170 });
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("End");
  await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 184, to: 244 });
  await page.waitForTimeout(300);
  expect(await roundedRange(page, "Panel 2")).toEqual({ from: 224, to: 244 });
});

test("? opens a cheat sheet listing exactly the bindings that exist; ? and Escape close it", async ({ page }) => {
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  await page.keyboard.press("?");
  const sheet = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(sheet).toBeVisible();
  // Each of these has a test in this file; the sheet lists them and nothing else.
  const bindings = ["1 3 5 15 30 then Enter", "Backspace", "Esc", "H", "4", "D", "W",
    "Space", "Shift + Space", "Alt + ↓ or Alt + ↑", "⌘ + K or Ctrl + K",
    "Alt + R", "End", "Esc", "?"];
  expect(await sheet.locator("td[aria-label]").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("aria-label")))).toEqual(bindings);
  await expect(sheet.getByRole("row")).toHaveCount(bindings.length);
  await page.screenshot({ path: test.info().outputPath("hotkey-sheet-desktop.png") });
  // The sheet is modal: other hotkeys and symbol search wait.
  await page.keyboard.press("d");
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Symbol search" })).toHaveCount(0);
  await expect(mainInterval(page)).toHaveValue("5m");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
  await expect(sheet).toBeVisible();
  await page.keyboard.press("?");
  await expect(sheet).toHaveCount(0);
  await page.keyboard.press("Shift+Slash");
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: "Close keyboard shortcuts" }).click();
  await expect(sheet).toHaveCount(0);
});

test.describe("phone hotkey equivalents", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("interval buttons, watchlist arrows and the latest-candles button do by touch what the hotkeys do", async ({ page }) => {
    await registerCharts(page);
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
    await expect(page.getByRole("button", { name: "Keyboard shortcuts" })).toBeHidden();
    await page.getByRole("button", { name: "1h", exact: true }).tap();
    await expect(mainInterval(page)).toHaveValue("1h");
    for (const name of ["Next watchlist symbol", "Previous watchlist symbol"]) {
      const box = (await page.getByRole("button", { name }).boundingBox())!;
      expect(Math.min(box.width, box.height), name).toBeGreaterThanOrEqual(24);
    }
    await page.getByRole("button", { name: "Next watchlist symbol" }).tap();
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "NVDA");
    await page.getByRole("button", { name: "Previous watchlist symbol" }).tap();
    await page.getByRole("button", { name: "Previous watchlist symbol" }).tap();
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "QQQ");
    await expect(mainInterval(page)).toHaveValue("1h");
    await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
    await moveAway(page, "main", { from: 120, to: 180 });
    await page.getByRole("button", { name: "Latest candles main" }).tap();
    await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 130, to: 244 });
    expect(await autoScaled(page, "main")).toEqual([true, true]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});
