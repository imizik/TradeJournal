import { expect, test, type APIRequestContext, type BrowserContext, type Locator, type Page } from "@playwright/test";
import type { AutoLevel, AutoZone, ChartData, ChartBar, Interval, LevelInteraction, MarketDay, OptionsInfo, OptionsLadder, OptionStrike, PriceAdjustment, RangesInfo, RvolBaseline } from "../lib/charts";
import { fakeChartSettings, type SettingsStore } from "./fixtures/chartSettings";
import type { Earnings } from "../lib/symbolInfo";
import type { AlertsPayload, LevelAlert } from "../lib/alerts";
import type { Capture, CaptureSetup } from "../lib/captures";

// Each test starts from empty server settings of its own; tests tagged
// @real-settings use the e2e backend's endpoint instead.
/** No saved plans (C3.4) in a context, so no plan strip shifts the layout under test. */
const noPlans = (context: BrowserContext) => context.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
test.beforeEach(async ({ context }, testInfo) => {
  if (!testInfo.tags.includes("@real-settings")) await fakeChartSettings(context);
  // Saved plans (C3.4) live in the e2e database; tests that are not about them start with none, so no strip shifts their layout.
  if (!testInfo.tags.includes("@captures")) await noPlans(context);
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

// Prices are on the chart's split-adjusted basis; this symbol has no recorded splits.
const ADJUSTED: PriceAdjustment = { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: 1789000000, splits: [],
  daily: {}, dividends: "unsupported", dividends_note: "Dividends are not adjusted; prices are split-adjusted only.", warnings: [] };

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
      change: 2, change_percentage: 1.5, volume: 1200000, previous_close: 260.66, regular_close: 270, trade_time: now - 2 })),
    issues: [], adjustment: ADJUSTED, intraday_as_of: now - 60, history_note: "Synthetic chart data for browser verification.", fills: [], fills_truncated: false, extras };
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
  await expect(page.getByRole("heading", { name: "Charts", exact: true })).toHaveCount(1);
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
  await (await indicator(page, "RSI 14")).click();
  await (await indicator(page, "RSI 14")).click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Focus 1h chart" }).click();
  await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue("1h");
  await page.screenshot({ path: test.info().outputPath("charts-desktop.png"), fullPage: true });
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

test("watchlist rows use shared stream trades and the regular close for postmarket change", async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      constructor() { MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
      addEventListener(type: string, listener: EventListener | EventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() { /* no-op */ }
    }
    const testWindow = window as typeof window & {
      __chartTick?: (value: unknown) => void;
      __chartStreamReady?: () => boolean;
    };
    testWindow.__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    testWindow.__chartStreamReady = () => !!MockEventSource.current?.listeners.has("tick");
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  await stub(page);
  await page.goto("/charts");
  const row = page.locator("[data-watch-row]").filter({ hasText: "NVDA" });
  await expect(row).toBeVisible();
  // The row can render before the effect opens the shared stream. Wait until
  // its tick listener is attached so this synthetic event cannot be dropped.
  await page.waitForFunction(() =>
    (window as typeof window & { __chartStreamReady?: () => boolean }).__chartStreamReady?.() === true);
  const at = Math.floor(Date.now() / 1000) - 1;
  await page.evaluate((tick) => (window as typeof window & { __chartTick: (value: unknown) => void }).__chartTick(tick),
    { type: "tick", symbol: "NVDA", at, minute: Math.floor(at / 60) * 60, session: "post", price: 275, open: 275, high: 275, low: 275, buckets: {} });
  await expect(row).toContainText("275.00");
  await expect(row).toContainText("+1.85");
  await expect(row.locator("span[title]").first()).toHaveAttribute("title", /Live trade/);
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await expect(row).toContainText("275.00");
  await expect(row.locator("span[title]").first()).toHaveAttribute("title", /Paused trade/);
  // A trade older than 45 seconds stays shown until a newer one arrives; it keeps its change, dimmed, not a dash.
  await page.clock.fastForward(50_000);
  await expect(row.locator("span[title]").nth(1)).toHaveAttribute("title", /Paused trade · \d+s old · change as of this trade/);
  await expect(row).toContainText("+1.85");
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

test("after hours the headline names its session beside the regular close, and the watchlist dims the closing change", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const at = Date.parse("2026-09-29T21:30:00Z") / 1000; // 5:30 PM New York
  await openAt(page, at, (url) => {
    const data = currentFixture(url, at);
    data.market = { date: "2026-09-29", status: "open", source: "tradier", description: null, note: null, sessions: [
      { part: "pre", start: Date.parse("2026-09-29T08:00:00Z") / 1000, end: Date.parse("2026-09-29T13:30:00Z") / 1000 },
      { part: "regular", start: Date.parse("2026-09-29T13:30:00Z") / 1000, end: Date.parse("2026-09-29T20:00:00Z") / 1000 },
      { part: "post", start: Date.parse("2026-09-29T20:00:00Z") / 1000, end: Date.parse("2026-09-30T00:00:00Z") / 1000 }] };
    for (const quote of data.quotes) Object.assign(quote, { last: 250, previous_close: 260, regular_close: 250, trade_time: Date.parse("2026-09-29T19:59:00Z") / 1000 });
    for (const panel of Object.values(data.panels)) {
      const bar = panel?.bars.at(-1);
      if (bar && bar.end_time - bar.time < 86400) Object.assign(bar, { close: 252.5, high: Math.max(bar.high, 252.5), extended: true });
    }
    return data;
  });
  const quote = page.getByLabel("Selected symbol quote");
  // The after-hours candle, measured from the regular close; the close itself, measured from the day before.
  await expect(quote).toContainText("252.50");
  await expect(quote).toContainText("+1.00%");
  await expect(quote).toContainText("After hours");
  await expect(quote).toContainText("Close 250.00 -3.85%");
  // No trade in the last 45 seconds: the watchlist keeps the day's closing change, dimmed, instead of a dash.
  const row = page.locator("[data-watch-row]").filter({ hasText: "MRVL" });
  await expect(row).toContainText("250.00");
  await expect(row).toContainText("-3.85");
  await expect(row.locator("span[title]").nth(1)).toHaveAttribute("title", /change as of this quote/);
  await expect(page.locator("footer[aria-label='Chart status']")).toContainText("may be forming");
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
  const response = await request.get(`http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}/charts/workspace`);
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
  await page.screenshot({ path: test.info().outputPath("charts-mobile.png"), fullPage: true });
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
  await (await indicator(page, "RTH VWAP")).click();
  await page.keyboard.press("Escape"); // the menu closes before the screenshots
  await expect(page.getByRole("group", { name: "Chart indicators" })).toHaveCount(0);
  await page.mouse.move(1, 1); // off the chart, so no crosshair is drawn
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
/** Keep tests about live updates and layout independent of the local historical-data cache. */
async function stubExhaustedHistory(page: Page) {
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: { symbol: query.get("symbol"), interval: query.get("interval"), session: query.get("session"),
      before: Number(query.get("before")), limit: 1200, bars: [], markers: [], older_cursor: null, exhausted: true, continuation: null,
      warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null } });
  });
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
  // Closed reads the same everywhere: the main chart says it once, the smaller charts not at all.
  await expect(page.getByRole("timer", { name: "Panel 5 next bar" })).toHaveCount(0);
  await expect(page.getByLabel("Market hours")).toHaveText("Market is closed for Thanksgiving Day");
  // With no session open, no candle is forming, and the status strip does not say one may be.
  const status = page.locator("footer[aria-label='Chart status']");
  await expect(status).toContainText("Last minute candle");
  await expect(status).not.toContainText("may be forming");
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
  await page.getByRole("button", { name: "Extended hours", pressed: true }).click();
  await expect(page.getByRole("button", { name: "Extended hours", pressed: false })).toBeVisible();
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
      warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null,
      calendar_note: "Market calendar unavailable: holidays and early closes use regular clock hours." } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "120");
  await expect(page.getByLabel("main candle values")).toContainText("SIP");
  await expect(page.getByTestId("canvas-Panel 5")).toHaveAttribute("data-bars", "120");
  // One opening request per intraday panel, starting from now; scrolling may add older pages.
  const first = new Map<string | null, number>();
  for (const request of requests) if (!first.has(request.interval)) first.set(request.interval, request.before);
  expect([...first.keys()].sort()).toEqual(["15m", "1h", "1m", "5m"]);
  expect([...first.values()].every((before) => before === checkedAt)).toBe(true);
  await expect(page.getByRole("region", { name: "MRVL 5m chart" }).getByRole("status")).toContainText("Market calendar unavailable");
});

test("streamed ticks update the latest candle in place and keep zoom; history changes reset", async ({ page }) => {
  await stubExhaustedHistory(page);
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
  await page.getByRole("button", { name: "Extended hours", pressed: true }).click();
  await expect(pending("Loading regular hours…")).toHaveCount(5);
  open();
  await expect(pending("Loading regular hours…")).toHaveCount(0);

  // RSI adds and removes its pane on the same chart.
  const panes = () => page.evaluate(() => (window as unknown as KeepAliveWindow).__tjCharts.get("main")!.panes().length);
  expect(await panes()).toBe(2);
  await (await indicator(page, "RSI 14")).click();
  await expect.poll(panes).toBe(1);
  await (await indicator(page, "RSI 14")).click();
  await expect.poll(panes).toBe(2);
  await page.keyboard.press("Escape");

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
      warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null } });
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
      continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null,
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
      price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
  expect(requests).toHaveLength(0);
  await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
  await expect.poll(() => requests.some((request) => request.interval === "5m" && request.before === afterMidnight)).toBe(true);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "120");
  await expect(page.getByLabel("main candle values")).toContainText("SIP");
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
  await expect(page.getByLabel("main candle values")).toContainText("SIP");
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
      warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null } }); } catch { /* navigation aborted the old request */ }
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

test("full-screen mode covers the navigation in the same shell, closes the dock, and resizes and maximizes charts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page);
  await page.goto("/charts");
  const main = page.getByTestId("canvas-main");
  await expect(main).toBeVisible();
  const normal = (await main.boundingBox())!;
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true");
  // The app navigation sits at the left edge; the workspace now covers it.
  expect(await page.evaluate(() => !!document.elementFromPoint(8, 450)?.closest("[data-testid=chart-workspace]"))).toBe(true);
  await expect(page.getByRole("button", { name: "Exit full-screen charts" })).toBeInViewport();
  // Full screen keeps its own choice of dock (closed until asked for), so the main chart gains the navigation's and the dock's width.
  await expect(page.getByRole("region", { name: "Watchlist" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Saved price levels" })).toHaveCount(0);
  await expect.poll(async () => (await main.boundingBox())!.width).toBeGreaterThan(normal.width + 250);
  expect((await main.boundingBox())!.height).toBeGreaterThanOrEqual(normal.height - 1);
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(page.getByRole("region", { name: "Watchlist" })).toBeVisible();
  // The divider above the smaller charts at its lowest: the main chart takes the height they give up (C7.4).
  await rowDivider(page).focus();
  await page.keyboard.press("End");
  await expect.poll(async () => (await main.boundingBox())!.height).toBeGreaterThan(normal.height + 60);
  const smaller = (await page.getByTestId("canvas-Panel 3").boundingBox())!.height;
  await page.getByRole("button", { name: "Maximize 15m chart" }).click();
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 2").boundingBox())!.height).toBeGreaterThan(600);
  await expect.poll(async () => (await page.getByTestId("canvas-Panel 2").boundingBox())!.width).toBeGreaterThan(900);
  await page.screenshot({ path: test.info().outputPath("charts-immersive-desktop.png") });
  await page.getByRole("button", { name: "Restore charts" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");
  await expect(page.getByRole("region", { name: "Saved price levels" })).toBeVisible();
  // The divider's place is saved; a maximized chart is not.
  await page.getByRole("button", { name: "Maximize 15m chart" }).click();
  await page.reload();
  await expect.poll(async () => Math.abs((await page.getByTestId("canvas-Panel 3").boundingBox())!.height - smaller)).toBeLessThanOrEqual(2);
  await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
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
  // Scrolled down to the smaller charts (the chart grid scrolls under the toolbar), the exit stays on screen.
  await page.getByTestId("chart-grid").evaluate((el) => el.scrollTo(0, 900));
  await expect(page.getByTestId("canvas-Panel 2")).toBeInViewport();
  await expect(exit).toBeInViewport();
  await exit.click();
  await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible(); // the app's phone bar is back
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
/** Save a level from the watchlist's level form, opening the dock first when it is closed (on a phone, a sheet it then closes). */
async function addLevel(page: Page, label: string, value: string) {
  const opened = !(await page.getByLabel("Level label").isVisible());
  if (opened) await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.getByLabel("Level label").fill(label);
  await page.getByLabel("Level price", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Save price level" }).click();
  await expect(levelsPanel(page)).toContainText(label);
  if (opened && await page.getByRole("dialog", { name: "Watchlist" }).isVisible()) {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Watchlist" })).toHaveCount(0);
  }
}
type SavedLevels = { data: { levels?: Record<string, { label: string }[]> } | null; revision: number };
// The server keeps a field a save leaves out, so starting over saves every shared
// field at the page's default; otherwise one run's intervals or held symbols
// carry into the next run against the same e2e database.
const EMPTY_SETTINGS = {
  levels: {}, drawings: {}, layouts: [], toolStyles: {}, magnet: false, linkRange: false, smallSize: "normal", immersiveWatchlist: false, proportions: null, layoutProportions: {},
  intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, null, null, null], session: "extended", layout: "multi",
  watchlist: ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"], hiddenGroups: { levels: false, drawings: false }, studiesHidden: false, autoLevelsHidden: false,
  optionsLayer: { hidden: true, mode: "oi", scope: "week", nearest: 3, signed: false },
  indicators: { ema9: true, ema20: true, ema50: true, ema200: false, vwap: true, volume: true, rsi: true, fills: true },
};
const savedLabels = (saved: SavedLevels) => (saved.data?.levels?.MRVL ?? []).map((level) => level.label);

test("a level saved in one browser appears in another, and a stale save is refused", { tag: "@real-settings" }, async ({ page, browser, request }) => {
  const run = Date.now().toString(36);
  const [desk, phone, later] = [`Desk ${run}`, `Phone ${run}`, `Late ${run}`];
  // The e2e database outlives a run: start from empty settings.
  const start: SavedLevels = await (await request.get("/api/backend/charts/settings")).json();
  if (start.revision) expect((await request.put("/api/backend/charts/settings", { data: { base_revision: start.revision, data: EMPTY_SETTINGS } })).ok()).toBe(true);
  await stub(page);
  await page.goto("/charts");
  await addLevel(page, desk, "263.50");
  const serverLabels = async () => savedLabels(await (await request.get("/api/backend/charts/settings")).json());
  await expect.poll(serverLabels).toContain(desk);
  await expect(syncStatus(page)).toHaveText("Saved");

  // A second browser (its own storage, like a phone) opens the same workspace.
  const other = await browser.newContext();
  await noPlans(other);
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
    await (await indicator(page, "EMA 200")).click();
    await addLevel(page, "While loading", "264.00");
    await expect(syncStatus(page)).toHaveText("Loading saved settings"); // both changes made before the server answered
    release();
    await expect(syncStatus(page)).toHaveText(outcome === "arrive" ? "Saved" : "Saved in this browser · server unavailable");
    await expect(await indicator(page, "EMA 200")).toHaveAttribute("aria-pressed", "true");
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
  await expect(await indicator(page, "EMA 200")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => server.revision).toBe(3);
  expect(server.saves.map((save) => [save.base, save.status])).toEqual([[0, 200], [1, 409], [2, 200]]);
  const levels = (server.data as { levels: Record<string, { label: string }[]> }).levels.MRVL.map((level) => level.label);
  expect(levels).toEqual(["First", "Other device", "Second"]);
  await (await indicator(page, "Volume")).click();
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
const expectStreamSymbols = async (page: Page, symbols: string[]) =>
  expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.at(-1)?.split(",").sort())).toEqual([...symbols].sort());
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
  await expectStreamSymbols(page, ["AAPL", "AMD", "META", "MRVL", "MSFT", "NVDA", "QQQ", "SPY"]);

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
  await expectStreamSymbols(page, ["AAPL", "AMD", "META", "MRVL", "MSFT", "NVDA", "QQQ", "SPY"]);

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

  // Pause freezes every symbol; resume reconnects the chart symbols plus watchlist.
  await page.getByRole("button", { name: "Pause chart updates" }).click();
  await trade(page, "SPY", 705);
  await expect(values(page, "Panel 3")).toContainText("C 702.50");
  await page.getByRole("button", { name: "Resume chart updates" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as StreamWindow).__streams.length)).toBeGreaterThanOrEqual(3);
  await expectStreamSymbols(page, ["AAPL", "AMD", "META", "MRVL", "MSFT", "NVDA", "QQQ", "SPY"]);
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

  // Following again drops the held chart symbol from extras; QQQ remains streamed as a watchlist name.
  await page.getByRole("button", { name: "Panel 5 symbol" }).click();
  await page.getByRole("dialog", { name: "Symbol for Panel 5" }).getByRole("option", { name: /Follow the main chart \(NVDA\)/ }).click();
  await expect(page.getByRole("region", { name: "NVDA 1m chart" })).toBeVisible();
  await expect.poll(() => requests.at(-1)!.get("extras")).toBe("SPY:1h");
  await expectStreamSymbols(page, ["AAPL", "AMD", "META", "MRVL", "MSFT", "NVDA", "QQQ", "SPY"]);
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
      older_cursor: bars[0]?.time ?? null, exhausted: true, continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted", adjustment: ADJUSTED, fills_truncated: false, issue: null } });
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
  await rowDivider(page).focus();
  await page.keyboard.press("Home"); // smaller charts as tall as the main chart's minimum allows
  await expect(layoutsButton(page)).toHaveText("Layouts"); // edited: no saved layout matches
  await saveLayout(page, "Scalp");
  await expect.poll(() => layoutNames(server)).toEqual(["Names", "Scalp"]);
  expect(layoutsOn(server)[1]).toMatchObject({ layout: "multi", intervals: ["1m", "3m", "5m", "15m", "30m"], panelSymbols: [null, null, null, null, null], smallSize: "normal", linkRange: true });
  // A layout's proportions sit beside the list, by its id, so an older tab keeps both (C7.4).
  expect(Object.keys(layoutsOn(server)[1]).sort()).toEqual(LAYOUT_KEYS);
  expect(proportionsOn(server, layoutsOn(server)[1].id)!.lower).toBeGreaterThan(0.4); // the default is 0.378
  expect(proportionsOn(server, layoutsOn(server)[0].id)).toEqual({ lower: 0.378, columns: [0.25, 0.25, 0.25, 0.25] });

  // Switching back restores intervals, symbol groups, chart height and range linking.
  await useLayout(page, "Names");
  expect(await intervalsShown(page)).toEqual(["5m", "15m", "1h", "1D", "1m"]);
  await expect(page.getByRole("region", { name: "SPY 1h chart" })).toBeVisible();
  await expect(page.getByRole("region", { name: "QQQ 1m chart" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Link time ranges" })).toHaveAttribute("aria-pressed", "false");
  await expect(rowDivider(page)).toHaveAttribute("aria-valuenow", "62");
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
  if (start.revision) expect((await request.put("/api/backend/charts/settings", { data: { base_revision: start.revision, data: EMPTY_SETTINGS } })).ok()).toBe(true);
  await stub(page);
  await page.goto("/charts");
  await holdSymbol(page, "Panel 3", "SPY");
  await page.getByLabel("Panel 2 interval", { exact: true }).selectOption("30m");
  await saveLayout(page, desk);
  await expect.poll(async () => (await serverLayouts()).map((layout) => layout.name)).toEqual([desk]);
  await expect(syncStatus(page)).toHaveText("Saved");

  // A second browser (its own storage, like a phone) sees the saved layout and can switch to it.
  const other = await browser.newContext();
  await noPlans(other);
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

// ---- C0.6: one split-adjusted price basis ----
const NVDA_SPLIT: PriceAdjustment = { ...ADJUSTED, splits: [{ ex_date: "2024-06-10", ratio: 10, label: "10-for-1" }] };
async function stubAdjustment(page: Page, adjustment: PriceAdjustment) {
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: { ...fixture(route.request().url()), adjustment } }));
}

test("a recorded split labels the basis and moves levels drawn before it", async ({ page, context }) => {
  const server = await fakeChartSettings(context, { revision: 2, data: { levels: { MRVL: [
    { id: "old", price: 1210, label: "Old high", drawn_on: "2024-06-07" },
    { id: "after", price: 120, label: "After split", drawn_on: "2025-01-02" },
    { id: "legacy", price: 300, label: "Undated" },
  ] } } });
  await stubAdjustment(page, NVDA_SPLIT);
  await page.goto("/charts");
  const chip = page.getByRole("status", { name: "Price basis", exact: true });
  await expect(chip).toHaveText("Split-adjusted · 1 split");
  await expect(chip).toHaveAttribute("title", /10-for-1 split, ex-date 2024-06-10.*Dividends are not adjusted/);
  const levels = page.getByRole("region", { name: "Saved price levels" });
  await expect(levels).toContainText("Old high");
  await expect(levels.locator("div", { hasText: "Old high" }).last()).toContainText("121.00");
  await expect(levels.locator("div", { hasText: "Old high" }).last()).toContainText("was 1,210.00");
  await expect(levels.locator("div", { hasText: "After split" }).last()).not.toContainText("was");
  await expect(levels.locator("div", { hasText: "Undated" }).last()).toContainText("300.00");
  await expect(page.getByRole("status", { name: "Price basis warning" })).toHaveCount(0);
  // The stored level is untouched: only its display moved. A new level records the day it was drawn.
  await page.getByLabel("Level label").fill("Fresh");
  await page.getByLabel("Level price", { exact: true }).fill("125");
  await page.getByRole("button", { name: "Save price level" }).click();
  await expect.poll(() => (server.data?.levels as Record<string, { id: string; price: number; drawn_on?: string }[]>)?.MRVL?.length).toBe(4);
  const saved = (server.data!.levels as Record<string, { price: number; label: string; drawn_on?: string }[]>).MRVL;
  expect(saved.find((l) => l.label === "Old high")).toMatchObject({ price: 1210, drawn_on: "2024-06-07" });
  expect(saved.find((l) => l.label === "Fresh")?.drawn_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

test("missing split data says so on the chart instead of guessing", async ({ page }) => {
  await stubAdjustment(page, { ...ADJUSTED, status: "unknown", as_of: null,
    warnings: ["Split data is unavailable for this symbol, so prices are shown as the provider supplied them. A stock split would appear as a sudden price cliff."] });
  await page.goto("/charts");
  await expect(page.getByRole("status", { name: "Price basis", exact: true })).toHaveText("Splits unknown · prices as supplied");
  const warning = page.getByRole("status", { name: "Price basis warning" });
  await expect(warning).toContainText("MRVL: Split data is unavailable");
  await expect(warning).toContainText("sudden price cliff");
});

test("a history page on a different split basis than the candles on screen is refused, not mixed in", async ({ page }) => {
  await registerCharts(page);
  const base = Math.floor(Date.now() / 1000);
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: { ...currentFixture(route.request().url(), base), adjustment: NVDA_SPLIT } }));
  let asked = 0;
  await page.route("**/api/backend/charts/history?**", (route) => {
    asked++;
    const query = new URL(route.request().url()).searchParams;
    const before = Number(query.get("before"));
    const template = fixture(route.request().url()).panels["5m"]!.bars[0];
    // This page was adjusted without the split the workspace already knows about.
    const bars = Array.from({ length: 1200 }, (_, i) => ({ ...template, source: "alpaca_sip", time: before - (1200 - i) * 300, end_time: before - (1199 - i) * 300 }));
    return route.fulfill({ json: { symbol: query.get("symbol"), interval: "5m", session: "extended", before, limit: 1200, bars, markers: [],
      older_cursor: bars[0].time, exhausted: false, continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted",
      adjustment: ADJUSTED, fills_truncated: false, issue: null } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.waitForTimeout(120);
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10, to: 60 }));
  await expect(page.getByRole("button", { name: "Retry history" }).first()).toBeVisible();
  expect(asked).toBeGreaterThan(0);
  await expect(page.getByText("A split was recorded while these charts were open").first()).toBeVisible();
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100"); // nothing from the other basis was drawn
});

test("a possible unrecorded split in older candles is noted on its panel without shifting the page banner", async ({ page }) => {
  await registerCharts(page);
  const base = Math.floor(Date.now() / 1000);
  const jump = "Price jumps 10x between 2024-06-07 and 2024-06-10, like a forward split that is not in the split data. Prices there are not adjusted.";
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: currentFixture(route.request().url(), base) }));
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const before = Number(query.get("before"));
    const template = fixture(route.request().url()).panels["5m"]!.bars[0];
    const bars = Array.from({ length: 1200 }, (_, i) => ({ ...template, source: "alpaca_sip", time: before - (1200 - i) * 300, end_time: before - (1199 - i) * 300 }));
    return route.fulfill({ json: { symbol: query.get("symbol"), interval: "5m", session: "extended", before, limit: 1200, bars, markers: [],
      older_cursor: bars[0].time, exhausted: false, continuation: null, warmup: "ready", source: "alpaca_sip", price_basis: "split_adjusted",
      adjustment: { ...ADJUSTED, warnings: [jump] }, fills_truncated: false, issue: null } });
  });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.waitForTimeout(120);
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10, to: 60 }));
  await expect(page.getByRole("region", { name: "MRVL 5m chart" }).getByRole("status")).toContainText("Price jumps 10x between 2024-06-07 and 2024-06-10");
  await expect(page.getByRole("status", { name: "Price basis warning" })).toHaveCount(0);
});

// ---- C0.7: daily and weekly history depth ----
/** Tradier-style daily history of `years`, paged by the stub the way the backend pages it (limit 1,200). */
async function dailyHistoryStub(page: Page, years: number) {
  const template = fixture("http://test/charts/workspace?intervals=1D").panels["1D"]!.bars[0];
  const now = new Date();
  const daily: ChartBar[] = [];
  for (let day = Date.UTC(now.getUTCFullYear() - years, now.getUTCMonth(), now.getUTCDate()); day < Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()); day += 86400_000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday === 0 || weekday === 6) continue;
    const time = Math.floor(day / 1000) + 13 * 3600 + 30 * 60;
    const close = 150 + daily.length * 0.01 + Math.sin(daily.length / 30) * 6;
    daily.push({ ...template, time, end_time: time + 23400, open: close - 0.4, high: close + 1, low: close - 1, close, source: "tradier",
      ema9: close - 0.5, ema20: close - 1, ema50: close - 2, ema200: daily.length < 199 ? null : close - 3, vwap: null, rsi: 50 });
  }
  const weekly = [...Map.groupBy(daily, (bar) => bar.time - ((new Date(bar.time * 1000).getUTCDay() + 6) % 7) * 86400)].map(([time, days]) =>
    ({ ...days[0], time, end_time: time + 4 * 86400 + 23400, open: days[0].open, close: days.at(-1)!.close, high: Math.max(...days.map((d) => d.high)), low: Math.min(...days.map((d) => d.low)) }));
  const series: Record<string, ChartBar[]> = { "1D": daily, "1W": weekly };
  const start = new Date(daily[0].time * 1000).toISOString().slice(0, 10);
  const requests: { interval: string; before: number }[] = [];
  const base = Math.floor(Date.now() / 1000);
  let refreshes = 0;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    refreshes++;
    const data = currentFixture(route.request().url(), base);
    for (const interval of ["1D", "1W"]) if (data.panels[interval as Interval]) data.panels[interval as Interval] = { bars: series[interval].slice(-100), markers: [] };
    return route.fulfill({ json: data });
  });
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const interval = query.get("interval")!;
    const before = Number(query.get("before"));
    requests.push({ interval, before });
    if (!series[interval]) return route.fulfill({ status: 503, json: { detail: { code: "provider_unavailable", message: "unexpected intraday request", retry_at: 0 } } });
    const eligible = series[interval].filter((bar) => bar.time < before);
    const bars = eligible.slice(-1200);
    const exhausted = eligible.length <= 1200;
    return route.fulfill({ json: { symbol: "MRVL", interval, session: query.get("session"), before, limit: 1200, bars, markers: [],
      older_cursor: exhausted ? null : bars[0].time, exhausted, continuation: null, warmup: "ready", source: "tradier", price_basis: "split_adjusted",
      adjustment: ADJUSTED, fills_truncated: false, issue: null, history_start: start } });
  });
  return { series, start, base, daily: () => requests.filter((r) => r.interval in series), intraday: () => requests.filter((r) => !(r.interval in series)), refreshes: () => refreshes };
}

async function mainIs(context: BrowserContext, interval: Interval) {
  await fakeChartSettings(context, { revision: 1, data: { intervals: [interval, ...(["15m", "1h", "5m", "1m"] as Interval[])] } });
}

async function panToStart(page: Page, state: Awaited<ReturnType<typeof dailyHistoryStub>>, interval: "1D" | "1W") {
  const total = state.series[interval].length;
  const loaded = async () => Number(await page.getByTestId("canvas-main").getAttribute("data-bars"));
  await page.waitForTimeout(120); // past the reset's programmatic-range window
  for (let index = 0; index < 8 && await loaded() < total; index++) {
    const count = state.daily().length;
    await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 10.25, to: 60.25 }));
    await page.waitForTimeout(180);
    await expect.poll(() => state.daily().length).toBeGreaterThan(count);
    await expect.poll(loaded).toBeGreaterThan(100 + index * 600);
    const logical = (await logicalRange(page, "main"))!;
    expect(logical.to - logical.from).toBeCloseTo(50, 2); // prepending a page does not change the zoom
    const range = (await visibleRange(page, "main"))!;
    await page.getByRole("button", { name: "Refresh charts", exact: true }).click();
    await expect(page.getByRole("button", { name: "Refresh charts", exact: true })).toBeEnabled();
    expect(await visibleRange(page, "main")).toEqual(range); // nor does a REST refresh
  }
  expect(await loaded()).toBe(total);
  // At the very first bar the view can sit on it: the oldest candle is reachable.
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: -2, to: 48 }));
  await expect.poll(async () => (await visibleRange(page, "main"))!.from).toBeLessThanOrEqual(state.series[interval][0].time);
}

test("a 1D chart pans back page by page through twelve years to its first bar", async ({ page, context }) => {
  await registerCharts(page);
  await mainIs(context, "1D");
  const state = await dailyHistoryStub(page, 12);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue("1D");
  await page.waitForTimeout(300);
  await panToStart(page, state, "1D");
  const earliest = (await visibleRange(page, "main"))!.from;
  expect(earliest).toBeLessThanOrEqual(state.series["1D"][0].time + 86400 * 8);
  expect(new Date(earliest * 1000).getUTCFullYear()).toBeLessThanOrEqual(new Date(state.series["1D"][0].time * 1000).getUTCFullYear() + 1);
  expect(Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBe(state.series["1D"].length);
  expect(state.daily().length).toBeGreaterThanOrEqual(3);
  expect(state.daily().length).toBeLessThanOrEqual(5); // 3,100 bars take three 1,200-bar pages, plus at most a retry
  expect(state.daily().every((request) => request.interval === "1D")).toBe(true); // the daily chart asks for daily pages only, never minutes
  await expect(page.getByRole("region", { name: "MRVL 1D chart" }).getByRole("status")).toContainText(`Tradier daily history starts ${state.start}`);
  await page.screenshot({ path: test.info().outputPath("daily-history-desktop.png"), fullPage: true });
});

test("a 1W chart pans back to its first week, and 1D, 1W and 5m switch freely afterwards", async ({ page, context }) => {
  await registerCharts(page);
  await mainIs(context, "1W");
  const state = await dailyHistoryStub(page, 30); // 1,560 weeks: two pages
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.waitForTimeout(300);
  await panToStart(page, state, "1W");
  expect(Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBe(state.series["1W"].length);
  expect(state.daily().length).toBe(2);
  expect(state.daily().every((r) => r.interval === "1W")).toBe(true); // weekly pages only
  await expect(page.getByRole("region", { name: "MRVL 1W chart" }).getByRole("status")).toContainText(`Tradier daily history starts ${state.start}`);
  for (const interval of ["1D", "1W", "5m"] as const) {
    await page.getByRole("button", { name: interval, exact: true }).first().click();
    await expect(page.getByLabel("Main interval", { exact: true })).toHaveValue(interval);
    await expect(page.getByRole("region", { name: `MRVL ${interval} chart` }).first()).toBeVisible();
    await expect(page.getByTestId("canvas-main")).not.toHaveAttribute("data-bars", "0");
  }
});

test.describe("phone daily history", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("touch panning loads an older daily page without horizontal overflow", async ({ page, context }) => {
    await registerCharts(page);
    await mainIs(context, "1D");
    const state = await dailyHistoryStub(page, 12);
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
    await expect.poll(() => state.daily().length).toBeGreaterThan(0);
    await expect.poll(async () => Number(await page.getByTestId("canvas-main").getAttribute("data-bars"))).toBeGreaterThan(100);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // The smaller intraday panels ask for their own history at this width; the daily chart asks only for daily pages.
    expect(state.daily().every((request) => request.interval === "1D")).toBe(true);
    await page.screenshot({ path: test.info().outputPath("daily-history-phone.png"), fullPage: true });
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
  await clickAway(page);
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
  // The backdrop is the top layer everywhere beside the drawer. Nothing in a chart may paint over it:
  // the library's pane-resize handle once did, in a 9px strip whose height followed the chart's layout,
  // so the click below only missed the backdrop on some runs. Check the whole area beside the drawer,
  // not the clicked point: a grid over it, plus the centre of every element on the page so a small or
  // thin overlap between grid lines cannot hide.
  const covered = await page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"][aria-label="Background jobs"]')!;
    const backdrop = dialog.previousElementSibling;
    const beside = dialog.getBoundingClientRect().right;
    const points: [number, number][] = [];
    for (let x = Math.ceil(beside) + 1; x < innerWidth; x += 8) for (let y = 0; y < innerHeight; y += 3) points.push([x, y]);
    for (const el of document.querySelectorAll("body *")) {
      if (el === backdrop || dialog.contains(el)) continue;
      const r = el.getBoundingClientRect();
      points.push([Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]);
    }
    const stray = new Set<string>();
    for (const [x, y] of points) {
      if (x <= beside || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue; // the drawer's own side, or off screen
      const top = document.elementFromPoint(x, y);
      if (top !== backdrop) stray.add(`${top?.tagName}.${String(top?.className).slice(0, 40)} at (${x},${y})`);
    }
    return { backdrop: backdrop?.className ?? null, points: points.length, stray: [...stray].slice(0, 5) };
  });
  expect(covered.backdrop).toContain("inset-0");
  expect(covered.points).toBeGreaterThan(1000);
  expect(covered.stray).toEqual([]);
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
  await expect(page.getByRole("button", { name: "Plan trade" })).toBeFocused();
  await page.keyboard.press("Tab");
  const pause = page.getByRole("button", { name: "Pause chart updates" });
  await expect(pause).toBeFocused();
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "Resume chart updates" })).toBeFocused();
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
    "Delete or Backspace", "⌘ + Z or Ctrl + Z", "⌘ + Shift + Z or Ctrl + Shift + Z", "Esc", "Hold ⌘ or Ctrl",
    "Alt + P", "Alt + R", "End", "Esc", "↑ ↓ ← →", "?"];
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
    // The watchlist is a sheet on a phone (C7.3).
    await page.getByRole("button", { name: "Watchlist", exact: true }).tap();
    for (const name of ["Next watchlist symbol", "Previous watchlist symbol"]) {
      const box = (await page.getByRole("button", { name }).boundingBox())!;
      expect(Math.min(box.width, box.height), name).toBeGreaterThanOrEqual(44);
    }
    await page.getByRole("button", { name: "Next watchlist symbol" }).tap();
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "NVDA");
    await page.getByRole("button", { name: "Previous watchlist symbol" }).tap();
    await page.getByRole("button", { name: "Previous watchlist symbol" }).tap();
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "QQQ");
    await expect(mainInterval(page)).toHaveValue("1h");
    await page.getByRole("button", { name: "Close watchlist" }).tap();
    await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "240");
    await moveAway(page, "main", { from: 120, to: 180 });
    await page.getByRole("button", { name: "Latest candles main" }).tap();
    await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 130, to: 244 });
    expect(await autoScaled(page, "main")).toEqual([true, true]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Drawing layer (C1.1): levels are drawings you select, drag, delete, undo and redo ----

type SeriesProbe = { seriesType(): string; priceToCoordinate(value: number): number | null; coordinateToPrice(y: number): number | null };
type PaneRegistry = Map<string, { panes(): { getSeries(): SeriesProbe[] }[] }>;
/** Where a price sits on a chart's candle pane, in pixels from the top of the chart. */
const levelY = (page: Page, id: string, value: number) => page.evaluate(([key, at]) => (window as unknown as { __tjCharts: PaneRegistry }).__tjCharts.get(key as string)!
  .panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!.priceToCoordinate(at as number)!, [id, value] as const);
const priceAtY = (page: Page, id: string, y: number) => page.evaluate(([key, at]) => (window as unknown as { __tjCharts: PaneRegistry }).__tjCharts.get(key as string)!
  .panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!.coordinateToPrice(at as number)!, [id, y] as const);
const drawn = (page: Page, id: string) => page.getByTestId(`canvas-${id}`);

async function mouseDrag(page: Page, id: string, fromY: number, toY: number, options: { escape?: boolean } = {}) {
  const box = (await drawn(page, id).boundingBox())!;
  const x = box.x + 220;
  await page.mouse.move(x, box.y + fromY);
  await page.mouse.down();
  for (let step = 1; step <= 6; step++) await page.mouse.move(x, box.y + fromY + (toY - fromY) * step / 6);
  if (options.escape) await page.keyboard.press("Escape");
  await page.mouse.up();
}

test("a level drags with the mouse on the 5m chart, moves on the 1h chart, deletes, undoes, redoes and survives reload", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Breakout", "256.00");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "256.00");
  const before = await logicalRange(page, "main");
  const from = await levelY(page, "main", 256);

  // Escape during a drag puts the level back.
  await mouseDrag(page, "main", from, from + 50, { escape: true });
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", /.+/);
  await page.keyboard.press("Escape");
  await expect(drawn(page, "main")).not.toHaveAttribute("data-selected", /.+/);

  // Press on the line, drag down 50px: the level follows and the chart does not pan.
  const expected = await priceAtY(page, "main", from + 50);
  await mouseDrag(page, "main", from + 3, from + 53);
  await expect.poll(async () => Number(await drawn(page, "main").getAttribute("data-levels"))).toBeLessThan(256);
  const moved = (await drawn(page, "main").getAttribute("data-levels"))!;
  expect(Math.abs(Number(moved) - expected)).toBeLessThan(0.05);
  expect(await logicalRange(page, "main")).toEqual(before);
  // The same level, at the same price, on the 1h chart and in the list.
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", moved);
  await expect(levelsPanel(page)).toContainText(moved);
  const selected = page.getByRole("toolbar", { name: "Selected level on main" });
  await expect(selected).toContainText("Breakout");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-selected", (await drawn(page, "main").getAttribute("data-selected"))!);
  await page.screenshot({ path: test.info().outputPath("level-selected-desktop.png") });

  await page.keyboard.press("Delete");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "");
  await expect(selected).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "256.00");
  await page.keyboard.press("ControlOrMeta+Shift+z");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);
  // The delete is still there to redo; the buttons name what they would do.
  await expect(page.getByRole("button", { name: "Redo" })).toHaveAttribute("title", /^Redo deleting Breakout/);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo moving Breakout/);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);

  // A click on empty chart space selects nothing; Backspace then deletes nothing.
  const box = (await drawn(page, "main").boundingBox())!;
  const y = await levelY(page, "main", Number(moved));
  await page.mouse.click(box.x + 220, box.y + y);
  await expect(selected).toBeVisible();
  await page.mouse.click(box.x + 220, box.y + (y > 120 ? y - 80 : y + 80));
  await expect(selected).toHaveCount(0);
  await page.keyboard.press("Backspace");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);

  // Saved as dropped, dated today, and drawn there after a reload.
  await expect.poll(() => ((server.data?.levels as Record<string, { price: number; drawn_on?: string }[]> | undefined)?.MRVL ?? [])[0]?.price).toBe(Number(moved));
  expect((server.data!.levels as Record<string, { drawn_on?: string }[]>).MRVL[0].drawn_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", moved);
});

test("a level dragged to where the price scale reads zero or below is not saved", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Floor", "256.00");
  await expect.poll(() => server.revision).toBe(1);
  // The lower half of the candle pane now reads below zero; the drag jumps straight there.
  await page.evaluate(() => (window as unknown as { __tjCharts: Map<string, { priceScale(id: string, pane: number): { setVisibleRange(range: { from: number; to: number }): void } }> })
    .__tjCharts.get("main")!.priceScale("right", 0).setVisibleRange({ from: -300, to: 300 }));
  const from = await levelY(page, "main", 256);
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + 220, box.y + from);
  await page.mouse.down();
  await page.mouse.move(box.x + 220, box.y + box.height);
  await page.mouse.up();
  await page.waitForTimeout(600); // past the save debounce
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  expect(server.revision).toBe(1);
  expect(((server.data?.levels as Record<string, { price: number }[]>).MRVL)[0].price).toBe(256);
});

test("undo replays onto levels another device changed meanwhile", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Mine", "256.00");
  await expect.poll(() => server.revision).toBe(1);
  // Another device adds a level; this page picks it up when it regains focus.
  const data = server.data as { levels: Record<string, unknown[]> };
  server.data = { ...data, levels: { MRVL: [...data.levels.MRVL, { id: "phone", price: 254, label: "From phone" }] } };
  server.revision += 1;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(levelsPanel(page)).toContainText("From phone");
  // Undoing this tab's add removes only its own level.
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(levelsPanel(page)).not.toContainText("Mine");
  await expect(levelsPanel(page)).toContainText("From phone");
  await expect.poll(() => ((server.data?.levels as Record<string, { label: string }[]> | undefined)?.MRVL ?? []).map((level) => level.label)).toEqual(["From phone"]);
});

test.describe("phone drawing layer", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("a tap selects a level, a finger drags only a selected level without scrolling the page, and Delete and Undo work by touch", async ({ page }) => {
    await registerCharts(page);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await addLevel(page, "Support", "256.00");
    await drawn(page, "main").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await drawn(page, "main").boundingBox())!;
    const x = Math.round(box.x + 150);
    const client = await page.context().newCDPSession(page);
    const swipe = async (fromY: number, toY: number) => {
      await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y: Math.round(box.y + fromY) }] });
      for (let step = 1; step <= 8; step++) {
        await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: Math.round(box.y + fromY + (toY - fromY) * step / 8) }] });
        await page.waitForTimeout(16);
      }
      await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    };
    const from = await levelY(page, "main", 256);

    // A finger on a level that is not selected pans the chart; the level stays.
    await swipe(from, from + 40);
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
    await expect(drawn(page, "main")).not.toHaveAttribute("data-selected", /.+/);

    // A tap within the finger's reach selects it.
    await page.touchscreen.tap(x, Math.round(box.y + (await levelY(page, "main", 256)) + 8));
    const selected = page.getByRole("toolbar", { name: "Selected level on main" });
    await expect(selected).toContainText("Support");
    const y = await levelY(page, "main", 256);
    const scrolled = await page.evaluate(() => window.scrollY);
    const expected = await priceAtY(page, "main", y + 45);
    await swipe(y + 5, y + 50);
    await expect.poll(async () => Number(await drawn(page, "main").getAttribute("data-levels"))).toBeLessThan(256);
    const moved = (await drawn(page, "main").getAttribute("data-levels"))!;
    expect(Math.abs(Number(moved) - expected)).toBeLessThan(0.1);
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);
    await page.screenshot({ path: test.info().outputPath("level-selected-phone.png") });

    for (const name of ["Delete selected level", "Deselect level", "Undo", "Redo"]) {
      const target = (await page.getByRole("button", { name, exact: true }).boundingBox())!;
      expect(Math.min(target.width, target.height), name).toBeGreaterThanOrEqual(24);
    }
    await selected.getByRole("button", { name: "Delete selected level" }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");
    await page.getByRole("button", { name: "Undo", exact: true }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", moved);
    await page.getByRole("button", { name: "Undo", exact: true }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Drawing tools (C1.2): ray, trend line, zone, note; magnet ----

type Point = { x: number; y: number };
type LayerProbe = Map<string, { anchors(id: string): (Point | null)[] | null }>;
type CoordinateProbe = Map<string, { timeScale(): { logicalToCoordinate(at: number): number | null }; panes(): { getSeries(): SeriesProbe[] }[] }>;
type SavedDrawing = { id: string; kind: string; points: { time: number; price: number }[]; color: string; width: number; drawn_on: string; text?: string; extendLeft?: boolean; extendRight?: boolean; hidden?: boolean; locked?: boolean };
const registerLayers = (page: Page) => page.addInitScript(() => { (window as typeof window & { __tjDrawings?: Map<string, unknown> }).__tjDrawings = new Map(); });
const drawingsOf = (server: SettingsStore, symbol = "MRVL") => (server.data?.drawings as Record<string, SavedDrawing[]> | undefined)?.[symbol] ?? [];
const anchorsOf = (page: Page, panel: string, id: string) => page.evaluate(([key, item]) => (window as unknown as { __tjDrawings: LayerProbe }).__tjDrawings.get(key)!.anchors(item), [panel, id] as const);
test("levels priced out of view keep one tag at each edge, with an arrow, instead of piling up there", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await fakeChartSettings(context, { revision: 1, data: { levels: { MRVL: [
    { id: "far", price: 420, label: "Far above" }, { id: "near", price: 400, label: "Above" }, { id: "low", price: 100, label: "Below" }, { id: "in", price: 262, label: "In view" }] } } });
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "420.00,400.00,100.00,262.00");
  const edgeTags = () => page.evaluate(() => (window as unknown as { __tjDrawings: Map<string, { edgeTags(): string[] }> }).__tjDrawings.get("main")!.edgeTags());
  // The nearest level each side of the view; 420 waits behind 400, and 262 is in view with its plain price.
  await expect.poll(edgeTags).toEqual(["↑400.00", "↓100.00"]);
  await drawn(page, "main").screenshot({ path: test.info().outputPath("edge-tags.png") });
});

/** Where bar `index` and `price` are drawn on a chart's candle pane. */
const screenAt = (page: Page, id: string, index: number, value: number) => page.evaluate(([key, at, p]) => {
  const chart = (window as unknown as { __tjCharts: CoordinateProbe }).__tjCharts.get(key as string)!;
  return { x: chart.timeScale().logicalToCoordinate(at as number)!, y: chart.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!.priceToCoordinate(p as number)! };
}, [id, index, value] as const);
const FIXTURE_START = 1789392600;
/** The 5m fixture's bar `index` (78 a day): its middle, where a click places an anchor, and its prices. */
function fixtureBar(index: number) {
  const time = FIXTURE_START + Math.floor(index / 78) * 86400 + (index % 78) * 300;
  const close = 245 + index * 0.06 + Math.sin(index / 8) * 2;
  return { middle: time + 150, open: close - 0.3, high: close + 0.8, low: close - 0.7, close };
}
async function clickChart(page: Page, id: string, at: Point) {
  const box = (await drawn(page, id).boundingBox())!;
  await page.mouse.click(box.x + at.x, box.y + at.y);
}
async function dragChart(page: Page, id: string, from: Point, to: Point) {
  const box = (await drawn(page, id).boundingBox())!;
  await page.mouse.move(box.x + from.x, box.y + from.y);
  await page.mouse.down();
  for (let step = 1; step <= 6; step++) await page.mouse.move(box.x + from.x + (to.x - from.x) * step / 6, box.y + from.y + (to.y - from.y) * step / 6);
  await page.mouse.up();
}
const tool = (page: Page, name: string) => page.getByRole("button", { name: `Draw ${name}`, exact: true });
const drawingBar = (page: Page, panel = "main") => page.getByRole("toolbar", { name: `Selected drawing on ${panel}` });

test("a trend line draws, drags by handle and by body, extends, restyles, deletes, undoes and sits on the 1h chart", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");

  await tool(page, "trend line").click();
  const hint = page.getByRole("status", { name: "Drawing tool" });
  await expect(hint).toHaveText("Click the first point of the line");
  await clickChart(page, "main", await screenAt(page, "main", 180, 254));
  await expect(hint).toHaveText("Click the second point");
  await clickChart(page, "main", await screenAt(page, "main", 220, 258));
  await expect(hint).toHaveCount(0);
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  let [line] = drawingsOf(server);
  expect(line).toMatchObject({ kind: "trend", color: "#67d5eb", width: 2, extendLeft: false, extendRight: false });
  expect(line.drawn_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  // Each anchor sits in the middle of the bar clicked, at the price clicked.
  expect(line.points.map((p) => p.time)).toEqual([fixtureBar(180).middle, fixtureBar(220).middle]);
  expect(Math.abs(line.points[0].price - 254)).toBeLessThan(0.08);
  expect(Math.abs(line.points[1].price - 258)).toBeLessThan(0.08);
  await expect(drawingBar(page)).toContainText("Trend line");

  // The 1h chart draws the same moment inside the hour that holds it, at the same price.
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-drawings", "trend");
  const hourIndex = (time: number) => Math.floor((time - FIXTURE_START) / 86400) * 7 + Math.floor(((time - FIXTURE_START) % 86400) / 3600);
  const [hourA] = (await anchorsOf(page, "Panel 3", line.id))!;
  const hourBar = await screenAt(page, "Panel 3", hourIndex(line.points[0].time), line.points[0].price);
  const hourNext = await screenAt(page, "Panel 3", hourIndex(line.points[0].time) + 1, line.points[0].price);
  const spacing = hourNext.x - hourBar.x;
  expect(Math.abs(hourA!.x - hourBar.x)).toBeLessThanOrEqual(spacing / 2);
  expect(Math.abs(hourA!.y - hourBar.y)).toBeLessThan(1);

  // Dragging the second handle moves only that anchor.
  const [, end] = (await anchorsOf(page, "main", line.id))!;
  await dragChart(page, "main", end!, await screenAt(page, "main", 230, 260));
  await expect.poll(() => drawingsOf(server)[0].points[1].time).toBe(fixtureBar(230).middle);
  [line] = drawingsOf(server);
  expect(line.points[0]).toEqual({ time: fixtureBar(180).middle, price: line.points[0].price });
  expect(Math.abs(line.points[1].price - 260)).toBeLessThan(0.08);

  // Dragging the line itself moves both anchors by whole bars and the same price.
  const before = line;
  const [a, b] = (await anchorsOf(page, "main", line.id))!;
  const middle = { x: (a!.x + b!.x) / 2, y: (a!.y + b!.y) / 2 };
  const step = (await screenAt(page, "main", 1, 250)).x - (await screenAt(page, "main", 0, 250)).x;
  const expectedShift = (await priceAtY(page, "main", middle.y + 40)) - (await priceAtY(page, "main", middle.y));
  await dragChart(page, "main", middle, { x: middle.x + 5 * step, y: middle.y + 40 });
  await expect.poll(() => drawingsOf(server)[0].points[0].time).toBe(fixtureBar(185).middle);
  [line] = drawingsOf(server);
  expect(line.points[1].time).toBe(fixtureBar(235).middle); // across the night: bars, not seconds
  line.points.forEach((point, index) => expect(Math.abs(point.price - (before.points[index].price + expectedShift))).toBeLessThan(0.03));

  // Extend, color and width from the bar; each is one undo step and the tool remembers the style.
  const bar = drawingBar(page);
  await bar.getByRole("button", { name: "Style" }).click();
  await bar.getByRole("button", { name: "Extend right" }).click();
  await expect.poll(() => drawingsOf(server)[0].extendRight).toBe(true);
  await bar.getByRole("button", { name: "Red trend line" }).click();
  await bar.getByRole("button", { name: "Line width 3" }).click();
  await expect.poll(() => drawingsOf(server)[0]).toMatchObject({ color: "#ee617a", width: 3, extendRight: true });
  await expect(bar.getByRole("button", { name: "Red trend line" })).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: test.info().outputPath("trend-selected-desktop.png") });
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo changing trend line/);
  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => drawingsOf(server)[0].width).toBe(2);
  await page.keyboard.press("ControlOrMeta+Shift+z");
  await expect.poll(() => drawingsOf(server)[0].width).toBe(3);

  // Delete, then undo it back; a new trend line starts in the remembered style.
  await page.keyboard.press("Delete");
  await expect.poll(() => drawingsOf(server).length).toBe(0);
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "");
  await expect(bar).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  await tool(page, "trend line").click();
  await clickChart(page, "main", await screenAt(page, "main", 200, 252));
  await clickChart(page, "main", await screenAt(page, "main", 210, 253));
  await expect.poll(() => drawingsOf(server).length).toBe(2);
  expect(drawingsOf(server)[1]).toMatchObject({ color: "#ee617a", width: 3 });
  expect((server.data!.toolStyles as Record<string, unknown>).trend).toEqual({ color: "#ee617a", width: 3 });

  // Esc puts a half-placed line away; nothing is saved.
  await tool(page, "trend line").click();
  await clickChart(page, "main", await screenAt(page, "main", 190, 255));
  await page.keyboard.press("Escape");
  await expect(hint).toHaveCount(0);
  await expect(tool(page, "trend line")).toHaveAttribute("aria-pressed", "false");
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "trend,trend");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-drawings", "trend,trend");
});

test("a ray, a zone and a note draw, edit and delete; the zone resizes by a corner and the note takes text", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");

  // Ray: one click; its price is on the axis like a level's.
  await tool(page, "horizontal ray").click();
  await expect(page.getByRole("status", { name: "Drawing tool" })).toHaveText("Click where the ray starts");
  await clickChart(page, "main", await screenAt(page, "main", 200, 256));
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  const [ray] = drawingsOf(server);
  expect(ray).toMatchObject({ kind: "ray", points: [{ time: fixtureBar(200).middle }], color: "#f4c66b", width: 1 });
  expect(Math.abs(ray.points[0].price - 256)).toBeLessThan(0.08);
  await expect(drawingBar(page)).toContainText("Horizontal ray");
  // Dragging the ray moves it; a click on empty chart space deselects.
  const [start] = (await anchorsOf(page, "main", ray.id))!;
  await dragChart(page, "main", { x: start!.x + 60, y: start!.y }, { x: start!.x + 60, y: start!.y - 30 });
  await expect.poll(() => drawingsOf(server)[0].points[0].price).toBeGreaterThan(ray.points[0].price);
  await clickChart(page, "main", { x: start!.x + 60, y: start!.y + 90 });
  await expect(drawingBar(page)).toHaveCount(0);

  // Zone: two opposite corners; a third corner's handle moves one time and one price.
  await tool(page, "rectangle zone").click();
  await clickChart(page, "main", await screenAt(page, "main", 190, 252));
  await expect(page.getByRole("status", { name: "Drawing tool" })).toHaveText("Click the opposite corner");
  await clickChart(page, "main", await screenAt(page, "main", 210, 255));
  await expect.poll(() => drawingsOf(server).length).toBe(2);
  let zone = drawingsOf(server)[1];
  expect(zone.kind).toBe("zone");
  expect(zone.points.map((p) => p.time)).toEqual([fixtureBar(190).middle, fixtureBar(210).middle]);
  const corners = (await anchorsOf(page, "main", zone.id))!;
  await dragChart(page, "main", { x: corners[0]!.x, y: corners[1]!.y }, await screenAt(page, "main", 186, 257));
  await expect.poll(() => drawingsOf(server)[1].points[0].time).toBe(fixtureBar(186).middle);
  zone = drawingsOf(server)[1];
  expect(Math.abs(zone.points[1].price - 257)).toBeLessThan(0.08);
  expect(zone.points[1].time).toBe(fixtureBar(210).middle);
  await page.keyboard.press("Backspace");
  await expect.poll(() => drawingsOf(server).map((d) => d.kind)).toEqual(["ray"]);

  // Note: the text field opens ready to type; Enter saves the text.
  await tool(page, "text note").click();
  await clickChart(page, "main", await screenAt(page, "main", 205, 251));
  const text = drawingBar(page).getByLabel("Note text");
  await expect(text).toBeFocused();
  await page.keyboard.type("Earnings gap fills here");
  await page.keyboard.press("Enter");
  await expect.poll(() => drawingsOf(server).find((d) => d.kind === "note")?.text).toBe("Earnings gap fills here");
  // Typing Backspace in the field never deletes the note; its Delete button does.
  await text.focus();
  await page.keyboard.press("ArrowRight"); // the caret to the end of the selected text
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Enter");
  await expect.poll(() => drawingsOf(server).find((d) => d.kind === "note")?.text).toBe("Earnings gap fills her");
  await page.screenshot({ path: test.info().outputPath("note-selected-desktop.png") });
  await drawingBar(page).getByRole("button", { name: "Delete selected drawing" }).click();
  await expect.poll(() => drawingsOf(server).map((d) => d.kind)).toEqual(["ray"]);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo deleting text note/);
});

test("the magnet snaps anchors to the bar's open, high, low or close when placed, dragged by a handle or dragged whole, by toggle or while Cmd/Ctrl is held", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  const near = async (index: number, value: number, by: number) => { const at = await screenAt(page, "main", index, value); return { x: at.x, y: at.y + by }; };

  // Off: the price under the pointer, to the cent.
  await tool(page, "horizontal ray").click();
  await clickChart(page, "main", await near(200, fixtureBar(200).high, -3));
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  expect(drawingsOf(server)[0].points[0].price).not.toBe(fixtureBar(200).high);

  // On: a ray near bar 200's high takes that high exactly; a trend line takes a low and a close.
  await page.getByRole("button", { name: "Magnet" }).click();
  await expect(page.getByRole("button", { name: "Magnet" })).toHaveAttribute("aria-pressed", "true");
  await tool(page, "horizontal ray").click();
  await clickChart(page, "main", await near(200, fixtureBar(200).high, -3));
  await tool(page, "trend line").click();
  await clickChart(page, "main", await near(180, fixtureBar(180).low, 3));
  await clickChart(page, "main", await near(220, fixtureBar(220).close, -2));
  await expect.poll(() => drawingsOf(server).length).toBe(3);
  expect(drawingsOf(server)[1].points).toEqual([{ time: fixtureBar(200).middle, price: fixtureBar(200).high }]);
  const line = drawingsOf(server)[2];
  expect(line.points).toEqual([{ time: fixtureBar(180).middle, price: fixtureBar(180).low }, { time: fixtureBar(220).middle, price: fixtureBar(220).close }]);
  expect(server.data!.magnet).toBe(true);

  // A dragged handle snaps too.
  const [first] = (await anchorsOf(page, "main", line.id))!;
  await dragChart(page, "main", first!, await near(190, fixtureBar(190).high, 2));
  await expect.poll(() => drawingsOf(server)[2].points[0]).toEqual({ time: fixtureBar(190).middle, price: fixtureBar(190).high });

  // Dragged whole, the anchor nearest the press lands on its new bar's high; the other end moves by the same bars and price.
  const [a, b] = (await anchorsOf(page, "main", line.id))!;
  const grabbed = { x: a!.x + (b!.x - a!.x) * 0.15, y: a!.y + (b!.y - a!.y) * 0.15 };
  const target = await near(193, fixtureBar(193).high, 3);
  await dragChart(page, "main", grabbed, { x: grabbed.x + target.x - a!.x, y: grabbed.y + target.y - a!.y });
  await expect.poll(() => drawingsOf(server)[2].points[0]).toEqual({ time: fixtureBar(193).middle, price: fixtureBar(193).high });
  const other = drawingsOf(server)[2].points[1];
  expect(other.time).toBe(fixtureBar(223).middle);
  expect(Math.abs(other.price - (fixtureBar(220).close + fixtureBar(193).high - fixtureBar(190).high))).toBeLessThan(0.006);

  // Off again, Cmd/Ctrl held for one click: that click snaps (to the open), the next does not.
  await page.getByRole("button", { name: "Magnet" }).click();
  await tool(page, "horizontal ray").click();
  await page.keyboard.down("ControlOrMeta");
  await clickChart(page, "main", await near(205, fixtureBar(205).open, 2));
  await page.keyboard.up("ControlOrMeta");
  await expect.poll(() => drawingsOf(server).length).toBe(4);
  expect(drawingsOf(server)[3].points[0]).toEqual({ time: fixtureBar(205).middle, price: fixtureBar(205).open });
  await tool(page, "horizontal ray").click();
  await clickChart(page, "main", await near(205, fixtureBar(205).open, 4));
  await expect.poll(() => drawingsOf(server).length).toBe(5);
  expect(drawingsOf(server)[4].points[0].price).not.toBe(fixtureBar(205).open);
});

test("a drawing made before a recorded split moves with the candles, and a drag saves it on today's basis", async ({ page, context }) => {
  const zone = { id: "old-zone", kind: "zone", points: [{ time: fixtureBar(190).middle, price: 2500 }, { time: fixtureBar(210).middle, price: 2560 }],
    color: "#659ef0", width: 1, drawn_on: "2024-06-07" };
  const server = await fakeChartSettings(context, { revision: 1, data: { drawings: { MRVL: [zone] } } });
  await registerCharts(page);
  await registerLayers(page);
  await stubAdjustment(page, NVDA_SPLIT);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "zone");
  // Drawn at a tenth of its saved prices, as the candles are; the saved record is untouched.
  const corners = (await anchorsOf(page, "main", "old-zone"))!;
  expect(Math.abs(corners[0]!.y - await levelY(page, "main", 250))).toBeLessThan(1);
  expect(Math.abs(corners[1]!.y - await levelY(page, "main", 256))).toBeLessThan(1);
  expect(drawingsOf(server)[0]).toEqual(zone);
  const inside = { x: (corners[0]!.x + corners[1]!.x) / 2, y: (corners[0]!.y + corners[1]!.y) / 2 };
  await dragChart(page, "main", inside, { x: inside.x, y: inside.y - 20 });
  await expect.poll(() => drawingsOf(server)[0].drawn_on).not.toBe("2024-06-07");
  const moved = drawingsOf(server)[0];
  expect(moved.points[0].price).toBeGreaterThan(250);
  expect(moved.points[0].price).toBeLessThan(260);
  expect(Math.abs((moved.points[1].price - moved.points[0].price) - 6)).toBeLessThan(0.02);
});

test.describe("phone drawing tools", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("a trend line is placed by two taps, selected by a tap, dragged by a handle, deleted and undone by touch", async ({ page, context }) => {
    const server = await fakeChartSettings(context);
    await registerCharts(page);
    await registerLayers(page);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await drawn(page, "main").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await drawn(page, "main").boundingBox())!;
    const tap = async (at: Point) => page.touchscreen.tap(Math.round(box.x + at.x), Math.round(box.y + at.y));
    const visible = (await logicalRange(page, "main"))!;
    const [left, right] = [Math.ceil(visible.from) + 15, Math.floor(visible.to) - 15];

    await tool(page, "trend line").tap();
    await tap(await screenAt(page, "main", left, 254));
    await tap(await screenAt(page, "main", right, 258));
    await expect.poll(() => drawingsOf(server).length).toBe(1);
    const [line] = drawingsOf(server);
    expect(line.points.map((p) => p.time)).toEqual([fixtureBar(left).middle, fixtureBar(right).middle]);
    await expect(drawingBar(page)).toBeVisible();
    // Folded, the bar is one row, so it covers no more of the chart than a level's.
    expect((await drawingBar(page).boundingBox())!.height).toBeLessThan(40);
    await drawingBar(page).getByRole("button", { name: "Style" }).tap();
    for (const target of await drawingBar(page).getByRole("button").all()) {
      const size = (await target.boundingBox())!;
      expect(Math.min(size.width, size.height), (await target.getAttribute("aria-label"))!).toBeGreaterThanOrEqual(24);
    }
    await page.screenshot({ path: test.info().outputPath("trend-selected-phone.png") });
    await drawingBar(page).getByRole("button", { name: "Deselect drawing" }).tap();
    await expect(drawingBar(page)).toHaveCount(0);

    // A finger dragging across the unselected line pans the chart and leaves the line alone.
    const client = await page.context().newCDPSession(page);
    const swipe = async (from: Point, to: Point) => {
      await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: Math.round(box.x + from.x), y: Math.round(box.y + from.y) }] });
      for (let step = 1; step <= 8; step++) {
        await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: Math.round(box.x + from.x + (to.x - from.x) * step / 8), y: Math.round(box.y + from.y + (to.y - from.y) * step / 8) }] });
        await page.waitForTimeout(16);
      }
      await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    };
    let [a, b] = (await anchorsOf(page, "main", line.id))!;
    await swipe({ x: (a!.x + b!.x) / 2, y: (a!.y + b!.y) / 2 }, { x: (a!.x + b!.x) / 2 - 40, y: (a!.y + b!.y) / 2 });
    await page.waitForTimeout(500);
    expect(drawingsOf(server)[0].points).toEqual(line.points);

    // A tap near the line selects it; a finger then drags its second handle without scrolling the page.
    [a, b] = (await anchorsOf(page, "main", line.id))!;
    await tap({ x: (a!.x + b!.x) / 2, y: (a!.y + b!.y) / 2 + 8 });
    await expect(drawingBar(page)).toBeVisible();
    [, b] = (await anchorsOf(page, "main", line.id))!;
    const scrolled = await page.evaluate(() => window.scrollY);
    await swipe(b!, { x: b!.x, y: b!.y + 45 });
    await expect.poll(() => drawingsOf(server)[0].points[1].price).toBeLessThan(line.points[1].price - 0.5);
    expect(drawingsOf(server)[0].points[0]).toEqual(line.points[0]);
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);

    await drawingBar(page).getByRole("button", { name: "Delete selected drawing" }).tap();
    await expect.poll(() => drawingsOf(server).length).toBe(0);
    await page.getByRole("button", { name: "Undo", exact: true }).tap();
    await expect.poll(() => drawingsOf(server).length).toBe(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Context menu (C1.3): right-click, or a long press on a phone, on the chart, a level or a drawing ----

const chartMenu = (page: Page) => page.getByRole("dialog", { name: "Chart menu" });
const itemMenu = (page: Page, name: string) => page.getByRole("dialog", { name: `${name} menu` });
type SavedLevel = { id: string; price: number; label: string; color?: string; hidden?: boolean; locked?: boolean };
const savedLevels = (server: SettingsStore, symbol = "MRVL") => (server.data?.levels as Record<string, SavedLevel[]> | undefined)?.[symbol] ?? [];
/** Empty chart space on the main chart: near the top of the candle pane, above every candle and the levels these tests draw (the chart's height follows the window since C7.3). */
const EMPTY = { x: 300, y: 30 };
async function rightClick(page: Page, id: string, at: Point) {
  const box = (await drawn(page, id).boundingBox())!;
  await page.mouse.click(box.x + at.x, box.y + at.y, { button: "right" });
}
/** Open the chart menu on empty chart space and switch it to Layers. */
async function openLayers(page: Page) {
  await rightClick(page, "main", EMPTY);
  await chartMenu(page).getByRole("menuitem", { name: /^Layers/ }).click();
}
const plotWidth = (page: Page) => page.evaluate(() => (window as unknown as { __tjCharts: Map<string, { timeScale(): { width(): number } }> }).__tjCharts.get("main")!.timeScale().width());

test("right-click on the chart adds a level at the price, copies it, resets that chart's scale and toggles layers", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(drawn(page, "Panel 2")).toHaveAttribute("data-bars", "240");

  // At the pointer, naming the symbol and the price there to the cent; arrow keys move between rows.
  const at = await screenAt(page, "main", 200, 256);
  await rightClick(page, "main", at);
  const menu = chartMenu(page);
  await expect(menu).toContainText(/^MRVL\d+\.\d\d/);
  const expected = /^MRVL(\d+\.\d\d)/.exec((await menu.textContent())!)![1];
  expect(Math.abs(Number(expected) - await priceAtY(page, "main", at.y))).toBeLessThan(0.08);
  const box = (await drawn(page, "main").boundingBox())!;
  const spot = (await menu.boundingBox())!;
  expect(Math.abs(spot.x - (box.x + at.x))).toBeLessThan(2);
  expect(Math.abs(spot.y - (box.y + at.y))).toBeLessThan(2);
  await expect(menu).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: `Add level at ${expected}` })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: `Copy price ${expected}` })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await expect(menu.getByRole("menuitem", { name: /^Layers/ })).toBeFocused();
  await page.screenshot({ path: test.info().outputPath("chart-menu-desktop.png") });

  await menu.getByRole("menuitem", { name: `Copy price ${expected}` }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByRole("status", { name: "Chart notice" })).toHaveText(`Copied ${expected}`);
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(expected);

  await rightClick(page, "main", at);
  await chartMenu(page).getByRole("menuitem", { name: `Add level at ${expected}` }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", expected);
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", expected);
  await expect.poll(() => savedLevels(server).map((level) => level.price)).toEqual([Number(expected)]);

  // Reset puts this chart on its latest candles with automatic price scales; the others stay where they are.
  await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 130, to: 244 });
  await moveAway(page, "main", { from: 120, to: 180 });
  await moveAway(page, "Panel 2", { from: 150, to: 170 });
  await rightClick(page, "main", EMPTY);
  await chartMenu(page).getByRole("menuitem", { name: "Reset chart scale" }).click();
  await expect.poll(() => roundedRange(page, "main")).toEqual({ from: 130, to: 244 });
  expect(await autoScaled(page, "main")).toEqual([true, true]);
  expect(await roundedRange(page, "Panel 2")).toEqual({ from: 150, to: 170 });
  expect(await autoScaled(page, "Panel 2")).toEqual([false, false]);

  // On the price scale there is no price to add or copy; the rest of the menu is there.
  await rightClick(page, "main", { x: (await plotWidth(page)) + 20, y: EMPTY.y });
  await expect(chartMenu(page).getByRole("menuitem", { name: "Reset chart scale" })).toBeVisible();
  await expect(chartMenu(page).getByRole("menuitem", { name: /^(Add level|Copy price)/ })).toHaveCount(0);
  // A click elsewhere closes it, and the browser's own menu never shows over a chart.
  await clickAway(page);
  await expect(chartMenu(page)).toHaveCount(0);

  // Layers: hiding My levels takes the level off all five charts, is saved, and survives reload.
  await openLayers(page);
  const levelsShown = chartMenu(page).getByRole("menuitemcheckbox", { name: "My levels" });
  await expect(levelsShown).toHaveAttribute("aria-checked", "true");
  await levelsShown.click();
  await expect(levelsShown).toHaveAttribute("aria-checked", "false");
  for (const panel of ["main", "Panel 2", "Panel 3", "Panel 4", "Panel 5"]) await expect(drawn(page, panel)).toHaveAttribute("data-levels", "");
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "Volume" }).click();
  await expect(chartMenu(page).getByRole("menuitemcheckbox", { name: "Volume" })).toHaveAttribute("aria-checked", "false");
  await page.keyboard.press("Escape");
  await expect(chartMenu(page)).toHaveCount(0);
  await expect.poll(() => server.data?.hiddenGroups).toEqual({ levels: true, drawings: false });
  expect((server.data!.indicators as Record<string, boolean>).volume).toBe(false);
  await expect(levelsPanel(page).getByRole("button", { name: "Hidden · Show" })).toBeVisible();
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");
  await openLayers(page);
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "My levels" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", expected);
  await page.keyboard.press("Escape");

  // With a tool armed, right-click only puts the tool away.
  await tool(page, "trend line").click();
  await rightClick(page, "main", EMPTY);
  await expect(tool(page, "trend line")).toHaveAttribute("aria-pressed", "false");
  await expect(chartMenu(page)).toHaveCount(0);
});

test("right-click on a level edits its label and color inline, locks, duplicates, hides and deletes it, each one undo step", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Breakout", "256.00");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  const onLevel = async () => ({ x: 220, y: await levelY(page, "main", 256) });

  // The menu selects the level, so its bar shows too; keys go to the menu, so Delete deletes nothing.
  await rightClick(page, "main", await onLevel());
  const menu = itemMenu(page, "Level");
  await expect(menu).toContainText("Breakout");
  await expect(page.getByRole("toolbar", { name: "Selected level on main" })).toContainText("Breakout");
  await page.keyboard.press("Delete");
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await page.screenshot({ path: test.info().outputPath("level-menu-desktop.png") });
  await menu.getByLabel("Level label").fill("Pivot");
  await menu.getByLabel("Level label").press("Enter");
  await expect(menu).toHaveCount(0);
  await expect.poll(() => savedLevels(server)[0]?.label).toBe("Pivot");
  await expect(levelsPanel(page)).toContainText("Pivot");
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo changing Pivot/);

  // A color applies at once and the menu stays open on it; Esc then drops a label typed but not saved.
  await rightClick(page, "main", await onLevel());
  await itemMenu(page, "Level").getByRole("button", { name: "Red" }).click();
  await expect.poll(() => savedLevels(server)[0]?.color).toBe("#ee617a");
  await expect(itemMenu(page, "Level").getByRole("button", { name: "Red" })).toHaveAttribute("aria-pressed", "true");
  await itemMenu(page, "Level").getByLabel("Level label").fill("Never saved");
  await page.keyboard.press("Escape");
  await expect(itemMenu(page, "Level")).toHaveCount(0);
  await page.waitForTimeout(600); // past the save debounce
  expect(savedLevels(server)[0].label).toBe("Pivot");

  // Locked, it still selects, but a press on it pans the chart instead of dragging it.
  await rightClick(page, "main", await onLevel());
  await itemMenu(page, "Level").getByRole("menuitem", { name: "Lock" }).click();
  await expect.poll(() => savedLevels(server)[0]?.locked).toBe(true);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo locking Pivot/);
  const before = await logicalRange(page, "main");
  const from = await onLevel();
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + from.x, box.y + from.y);
  await page.mouse.down();
  for (let step = 1; step <= 6; step++) await page.mouse.move(box.x + from.x + step * 20, box.y + from.y + step * 8);
  await page.mouse.up();
  await expect.poll(async () => (await logicalRange(page, "main"))!.from).toBeLessThan(before!.from - 1);
  await page.waitForTimeout(600);
  expect(savedLevels(server)[0].price).toBe(256);
  const bar = page.getByRole("toolbar", { name: "Selected level on main" });
  await bar.getByRole("button", { name: "Unlock" }).click();
  await expect.poll(() => savedLevels(server)[0]?.locked).toBeUndefined();
  await expect(bar.getByRole("button", { name: "Unlock" })).toHaveCount(0);

  // A duplicate sits at the same price, unlocked, and is selected; undo removes it.
  await rightClick(page, "main", await onLevel());
  await itemMenu(page, "Level").getByRole("menuitem", { name: "Duplicate" }).click();
  await expect.poll(() => savedLevels(server).length).toBe(2);
  const [original, copy] = savedLevels(server);
  expect(copy).toMatchObject({ price: 256, label: "Pivot", color: "#ee617a" });
  expect(copy.id).not.toBe(original.id);
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", copy.id);
  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => savedLevels(server).length).toBe(1);

  // Hidden, it leaves every chart and its selection; the list and the chart menu's Layers can show it again.
  await rightClick(page, "main", await onLevel());
  await itemMenu(page, "Level").getByRole("menuitem", { name: "Hide" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "");
  await expect(bar).toHaveCount(0);
  await expect.poll(() => savedLevels(server)[0]?.hidden).toBe(true);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo hiding Pivot/);
  await expect(levelsPanel(page).getByRole("button", { name: "Show Pivot" })).toBeVisible();
  await openLayers(page);
  await expect(chartMenu(page).getByText("Hidden MRVL items")).toBeVisible();
  await chartMenu(page).getByRole("menuitem", { name: "Show Pivot 256.00" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00");
  await expect.poll(() => savedLevels(server)[0]?.hidden).toBeUndefined();
  await page.keyboard.press("Escape");

  await rightClick(page, "main", await onLevel());
  await itemMenu(page, "Level").getByRole("menuitem", { name: "Delete" }).click();
  await expect.poll(() => savedLevels(server).length).toBe(0);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => savedLevels(server)[0]).toMatchObject({ label: "Pivot", color: "#ee617a", price: 256 });
});

test("right-click on a drawing restyles, locks, hides and deletes it, and a note's text edits inline", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await tool(page, "trend line").click();
  await clickChart(page, "main", await screenAt(page, "main", 180, 254));
  await clickChart(page, "main", await screenAt(page, "main", 220, 258));
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  const [line] = drawingsOf(server);
  const onLine = async () => { const [a, b] = (await anchorsOf(page, "main", line.id))!; return { x: (a!.x + b!.x) / 2, y: (a!.y + b!.y) / 2 }; };

  await rightClick(page, "main", await onLine());
  const menu = itemMenu(page, "Trend line");
  await expect(menu).toContainText("Trend line");
  await menu.getByRole("button", { name: "Green" }).click();
  await expect.poll(() => drawingsOf(server)[0].color).toBe("#2bc9a4");
  // The tool draws its next line in the color last chosen, as from the selection bar.
  expect((server.data!.toolStyles as Record<string, unknown>).trend).toEqual({ color: "#2bc9a4", width: 2 });
  await menu.getByRole("menuitem", { name: "Lock" }).click();
  await expect.poll(() => drawingsOf(server)[0].locked).toBe(true);
  // Locked: no handles, and neither a handle nor the body drags it.
  const [, end] = (await anchorsOf(page, "main", line.id))!;
  await dragChart(page, "main", end!, { x: end!.x, y: end!.y + 40 });
  await dragChart(page, "main", await onLine(), { x: (await onLine()).x, y: (await onLine()).y - 40 });
  await page.waitForTimeout(600);
  expect(drawingsOf(server)[0].points).toEqual(line.points);
  await expect(drawingBar(page).getByRole("button", { name: "Unlock" })).toBeVisible();

  // Hidden on its own, then shown from Layers; then the whole Drawings group off and on.
  await rightClick(page, "main", await onLine());
  await itemMenu(page, "Trend line").getByRole("menuitem", { name: "Hide" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-drawings", "");
  await openLayers(page);
  await expect(chartMenu(page).getByRole("menuitem", { name: /^Layers 1 hidden/ })).toHaveCount(0); // in the Layers view now
  await chartMenu(page).getByRole("menuitem", { name: /^Show Trend line/ }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "trend");
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "Drawings" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "");
  await page.keyboard.press("Escape");
  // Placing a drawing shows the group again, so nothing is drawn out of sight.
  await tool(page, "text note").click();
  await clickChart(page, "main", await screenAt(page, "main", 205, 251));
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "trend,note");
  await expect.poll(() => drawingsOf(server).length).toBe(2);
  expect(server.data?.hiddenGroups).toEqual({ levels: false, drawings: false });

  // A note's text edits inline in its menu.
  const note = drawingsOf(server)[1];
  await page.keyboard.press("Escape");
  const [anchor] = (await anchorsOf(page, "main", note.id))!;
  await rightClick(page, "main", { x: anchor!.x + 12, y: anchor!.y });
  await itemMenu(page, "Text note").getByLabel("Note text").fill("Gap fill");
  await itemMenu(page, "Text note").getByLabel("Note text").press("Enter");
  await expect.poll(() => drawingsOf(server)[1].text).toBe("Gap fill");
  await rightClick(page, "main", { x: anchor!.x + 12, y: anchor!.y });
  await itemMenu(page, "Text note").getByRole("menuitem", { name: "Delete" }).click();
  await expect.poll(() => drawingsOf(server).map((d) => d.kind)).toEqual(["trend"]);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo deleting text note/);
});

test.describe("phone context menu", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("a long press opens the chart menu and a level's menu as bottom sheets; a swipe or a tap does not", async ({ page, context }) => {
    const server = await fakeChartSettings(context);
    await registerCharts(page);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await drawn(page, "main").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await drawn(page, "main").boundingBox())!;
    const client = await page.context().newCDPSession(page);
    const point = (at: Point) => ({ x: Math.round(box.x + at.x), y: Math.round(box.y + at.y) });
    const hold = async (at: Point) => {
      await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point(at)] });
      await page.waitForTimeout(700);
      await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    };
    const at = { x: 150, y: 120 };

    // A swipe pans and a tap selects nothing: neither opens a menu.
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point(at)] });
    for (let step = 1; step <= 8; step++) {
      await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [point({ x: at.x - step * 6, y: at.y })] });
      await page.waitForTimeout(80);
    }
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.touchscreen.tap(point(at).x, point(at).y);
    await page.waitForTimeout(700);
    await expect(chartMenu(page)).toHaveCount(0);

    // Held still: the chart menu, as a bottom sheet with 44px rows.
    await hold(at);
    const menu = chartMenu(page);
    await expect(menu).toContainText(/MRVL\d+\.\d\d/);
    const expected = /MRVL(\d+\.\d\d)/.exec((await menu.textContent())!)![1];
    expect(Math.abs(Number(expected) - await priceAtY(page, "main", at.y))).toBeLessThan(0.1);
    const sheet = (await menu.boundingBox())!;
    expect(sheet.width).toBeGreaterThanOrEqual(389);
    expect(Math.abs(sheet.y + sheet.height - 844)).toBeLessThan(2);
    for (const row of await menu.getByRole("menuitem").all()) expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: test.info().outputPath("chart-menu-phone.png") });
    await menu.getByRole("menuitem", { name: `Add level at ${expected}` }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", expected);
    const onLevel = async () => ({ x: 150, y: (await levelY(page, "main", Number(expected))) + 6 });

    // Held on a level that is not selected: its menu, and it is selected. The backdrop closes the sheet.
    await hold(await onLevel());
    const levelMenu = itemMenu(page, "Level");
    await expect(levelMenu).toBeVisible();
    await expect(page.getByRole("toolbar", { name: "Selected level on main" })).toBeVisible();
    for (const swatch of await levelMenu.getByRole("group", { name: "Level color" }).getByRole("button").all()) {
      const size = (await swatch.boundingBox())!;
      expect(Math.min(size.width, size.height)).toBeGreaterThanOrEqual(44);
    }
    await page.screenshot({ path: test.info().outputPath("level-menu-phone.png") });
    await page.touchscreen.tap(195, 30);
    await expect(levelMenu).toHaveCount(0);
    await expect(page.getByRole("toolbar", { name: "Selected level on main" })).toBeVisible();

    // Held on the selected level: the menu again, and the level has not moved (a held finger is not a drag).
    await hold(await onLevel());
    await levelMenu.getByRole("menuitem", { name: "Lock" }).tap();
    await expect.poll(() => savedLevels(server)[0]?.locked).toBe(true);
    expect(savedLevels(server)[0].price).toBe(Number(expected));
    await hold(await onLevel());
    await expect(levelMenu.getByRole("menuitem", { name: "Unlock" })).toBeVisible();
    await levelMenu.getByRole("menuitem", { name: "Hide" }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");

    // Layers in the sheet shows it again.
    await hold(at);
    await chartMenu(page).getByRole("menuitem", { name: /^Layers/ }).tap();
    await chartMenu(page).getByRole("menuitem", { name: `Show Level 1 ${expected}` }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", expected);
    await page.touchscreen.tap(195, 30);
    await expect(chartMenu(page)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- Layers panel (C1.4): show, hide, lock and delete by group and item; a click brings an item into view ----

const layersPanel = (page: Page) => page.getByRole("region", { name: "Layers" });
const layerGroup = (page: Page, name: string) => layersPanel(page).getByRole("group", { name });
const paneCount = (page: Page, id: string) => page.evaluate((key) => (window as unknown as { __tjCharts: Map<string, { panes(): unknown[] }> }).__tjCharts.get(key)!.panes().length, id);
const ALL_PANELS = ["main", "Panel 2", "Panel 3", "Panel 4", "Panel 5"];

test("the layers panel hides, locks and deletes by group and by item, and a click brings an item into view", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerLayers(page);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Breakout", "256.00");
  await addLevel(page, "Far", "280.00"); // above every candle, so off the price scale
  await tool(page, "trend line").click();
  await clickChart(page, "main", await screenAt(page, "main", 180, 254));
  await clickChart(page, "main", await screenAt(page, "main", 220, 258));
  await expect.poll(() => drawingsOf(server).length).toBe(1);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Layers", exact: true }).click();
  await expect(layersPanel(page)).toBeVisible();
  await expect(layerGroup(page, "My levels").getByRole("button", { name: "My levels, 2" })).toHaveAttribute("aria-expanded", "true");
  await expect(layerGroup(page, "Drawings")).toContainText("Trend line");
  await page.screenshot({ path: test.info().outputPath("layers-desktop.png") });

  // A group hidden here is hidden on all five charts, saved, and still hidden (with the panel open) after a reload.
  await layerGroup(page, "My levels").getByRole("button", { name: "Hide My levels" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-levels", "");
  await layerGroup(page, "Drawings").getByRole("button", { name: "Hide Drawings" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-drawings", "");
  await expect.poll(() => server.data?.hiddenGroups).toEqual({ levels: true, drawings: true });
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(layersPanel(page)).toBeVisible();
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "");
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-drawings", "");
  await layerGroup(page, "My levels").getByRole("button", { name: "Show My levels" }).click();
  await layerGroup(page, "Drawings").getByRole("button", { name: "Show Drawings" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-levels", "256.00,280.00");
  await expect(drawn(page, "main")).toHaveAttribute("data-drawings", "trend");

  // One item hides and shows; it is an undo step.
  const levels = layerGroup(page, "My levels");
  await levels.getByRole("button", { name: "Hide Breakout 256.00" }).click();
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "280.00");
  await expect(levels.getByRole("button", { name: "Go to Breakout 256.00" })).toBeDisabled();
  await levels.getByRole("button", { name: "Show Breakout 256.00" }).click();
  await expect(drawn(page, "Panel 3")).toHaveAttribute("data-levels", "256.00,280.00");

  // Lock all is one undo step; then every level reads locked, and the button unlocks them all.
  await levels.getByRole("button", { name: "Lock all levels" }).click();
  await expect.poll(() => savedLevels(server).map((level) => level.locked)).toEqual([true, true]);
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo locking 2 levels/);
  await expect(levels.getByRole("button", { name: "Unlock all levels" })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => savedLevels(server).map((level) => level.locked)).toEqual([undefined, undefined]);
  await levels.getByRole("button", { name: "Lock Far 280.00" }).click();
  await expect.poll(() => savedLevels(server)[1].locked).toBe(true);

  // A click on a level off the price scale widens the scale to it and selects it.
  const far = savedLevels(server)[1];
  const height = await page.evaluate(() => (window as unknown as { __tjCharts: Map<string, { panes(): { getHeight(): number }[] }> }).__tjCharts.get("main")!.panes()[0].getHeight());
  expect(await levelY(page, "main", 280)).toBeLessThan(0);
  await levels.getByRole("button", { name: "Go to Far 280.00" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", far.id);
  await expect.poll(() => levelY(page, "main", 280)).toBeGreaterThan(0);
  expect(await levelY(page, "main", 280)).toBeLessThan(height);

  // A click on the trend line centres its bars at the current zoom.
  const line = drawingsOf(server)[0];
  await moveAway(page, "main", { from: 20, to: 80 });
  await layerGroup(page, "Drawings").getByRole("button", { name: /^Go to Trend line/ }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", line.id);
  await expect.poll(async () => { const range = (await visibleRange(page, "main"))!; return range.from < line.points[0].time && line.points[1].time < range.to; }).toBe(true);

  // Indicators hide together and come back with their own settings; Journal is the fill arrows.
  await expect.poll(() => paneCount(page, "main")).toBe(2);
  await layerGroup(page, "Indicators").getByRole("button", { name: /^Indicators,/ }).click(); // unfold
  await layerGroup(page, "Indicators").getByRole("button", { name: "Hide Indicators" }).click();
  await expect.poll(() => paneCount(page, "main")).toBe(1);
  await expect(page.getByRole("region", { name: "MRVL 5m chart" })).not.toContainText("EMA9");
  await expect(await indicator(page, "EMA 9")).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Indicators hidden · Show" })).toBeVisible();
  await expect.poll(() => server.data?.studiesHidden).toBe(true);
  expect(server.data?.hiddenGroups).toEqual({ levels: false, drawings: false });
  expect((server.data!.indicators as Record<string, boolean>).ema9).toBe(true); // kept for when the group shows again
  await layerGroup(page, "Indicators").getByRole("button", { name: "Show EMA 9" }).click();
  await expect.poll(() => paneCount(page, "main")).toBe(2);
  await expect(page.getByRole("button", { name: "Indicators hidden · Show" })).toHaveCount(0);
  await layerGroup(page, "Journal").getByRole("button", { name: "Hide Journal" }).click();
  await expect(await indicator(page, "My fills")).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Escape");
  await expect.poll(() => (server.data?.indicators as Record<string, boolean>).fills).toBe(false);

  // Delete all asks first; Cancel keeps them, Delete removes them as one undo step that puts them back in order.
  await levels.getByRole("button", { name: "Delete all levels" }).click();
  await expect(levels.getByRole("alert")).toContainText("Delete 2 levels?");
  await levels.getByRole("button", { name: "Cancel" }).click();
  await expect(levels.getByRole("alert")).toHaveCount(0);
  await levels.getByRole("button", { name: "Delete all levels" }).click();
  await levels.getByRole("alert").getByRole("button", { name: "Delete" }).click();
  await expect.poll(() => savedLevels(server).length).toBe(0);
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-levels", "");
  await expect(page.getByRole("button", { name: "Undo" })).toHaveAttribute("title", /^Undo deleting 2 levels/);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => savedLevels(server).map((level) => level.label)).toEqual(["Breakout", "Far"]);
  await layerGroup(page, "Drawings").getByRole("button", { name: /^Delete Trend line/ }).click();
  await expect.poll(() => drawingsOf(server).length).toBe(0);

  // Groups fold, and the panel closes from its own button and from the toolbar.
  await levels.getByRole("button", { name: "My levels, 2" }).click();
  await expect(levels.getByRole("button", { name: /^Go to/ })).toHaveCount(0);
  await layersPanel(page).getByRole("button", { name: "Close layers" }).click();
  await expect(layersPanel(page)).toHaveCount(0);
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(layersPanel(page)).toHaveCount(0);
});

test("a click on a drawing older than the loaded candles loads pages back to it", async ({ page, context }) => {
  await registerCharts(page);
  const state = await deepHistoryStub(page);
  const [a, b] = [state.bars[state.bars.length - 2400], state.bars[state.bars.length - 2390]];
  const old = { id: "old-line", kind: "trend", points: [{ time: a.time + 150, price: a.close }, { time: b.time + 150, price: b.close }],
    color: "#67d5eb", width: 2, drawn_on: "2026-07-01", extendLeft: false, extendRight: false };
  await fakeChartSettings(context, { revision: 1, data: { drawings: { MRVL: [old] } } });
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-bars", "100");
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  await layerGroup(page, "Drawings").getByRole("button", { name: /^Go to Trend line/ }).click();
  // Two pages of 1,200 candles reach it; the view then centres on it, and it is selected.
  await expect.poll(async () => { const range = await visibleRange(page, "main"); return !!range && range.from < old.points[0].time && old.points[1].time < range.to; }, { timeout: 15_000 }).toBe(true);
  expect(state.requests()).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-selected", "old-line");
});

test.describe("phone layers panel", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the layers panel is a bottom sheet with 44px targets that hides a group on every chart", async ({ page, context }) => {
    const server = await fakeChartSettings(context);
    await registerCharts(page);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await addLevel(page, "Support", "256.00");
    await page.getByRole("button", { name: "Layers", exact: true }).tap();
    const sheet = page.getByRole("dialog", { name: "Layers" });
    await expect(sheet).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(389);
    expect(Math.abs(box.y + box.height - 844)).toBeLessThan(2);
    for (const target of await sheet.getByRole("button").all()) {
      const size = (await target.boundingBox())!;
      expect(size.height, (await target.getAttribute("aria-label")) ?? (await target.textContent())!).toBeGreaterThanOrEqual(44);
    }
    await page.screenshot({ path: test.info().outputPath("layers-phone.png") });
    await sheet.getByRole("button", { name: "Hide My levels" }).tap();
    await expect(drawn(page, "main")).toHaveAttribute("data-levels", "");
    await expect.poll(() => (server.data?.hiddenGroups as Record<string, boolean> | undefined)?.levels).toBe(true);
    await sheet.getByRole("button", { name: "Show My levels" }).tap();
    // Going to an item closes the sheet so the chart shows, with the item selected.
    await sheet.getByRole("button", { name: "Go to Support 256.00" }).tap();
    await expect(sheet).toHaveCount(0);
    await expect(drawn(page, "main")).toHaveAttribute("data-selected", savedLevels(server)[0].id);
    // The backdrop closes it too.
    await page.getByRole("button", { name: "Layers", exact: true }).tap();
    await expect(sheet).toBeVisible();
    await page.touchscreen.tap(195, 30);
    await expect(sheet).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});

// ---- C7.3: a workspace that fills the screen ----

const chartGrid = (page: Page) => page.getByTestId("chart-grid");
// ---- C7.4 helpers: the dividers and the boxes they size ----
const rowDivider = (page: Page) => page.getByRole("separator", { name: "Resize main chart and smaller charts" });
const columnDivider = (page: Page, left: number) => page.getByRole("separator", { name: `Resize Panel ${left} and Panel ${left + 1}` });
const dockDivider = (page: Page) => page.getByRole("separator", { name: "Resize side panel" });
/** A chart's whole box (header, legend and canvas), as the dividers size it. */
const section = async (page: Page, id: string) => (await page.getByTestId(`canvas-${id}`).evaluate((el) => { const box = el.closest("section")!.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height }; }));
const MAIN_MIN = 320;
const LOWER_MIN = 180;
/** A saved layout's keys exactly as C7.2 saved them; an older tab drops a layout with anything else missing. */
const LAYOUT_KEYS = ["id", "intervals", "layout", "linkRange", "name", "panelSymbols", "smallSize"];
type Sizes = { lower: number; columns: number[] };
const proportionsOn = (server: SettingsStore, id?: string) => {
  const data = server.data as { proportions?: Sizes | null; layoutProportions?: Record<string, Sizes> } | null;
  return id ? data?.layoutProportions?.[id] : data?.proportions;
};
const sidePanel = (page: Page) => page.getByRole("complementary", { name: "Side panel" });
/** A click on the status strip's plain text: somewhere that is not a chart, a field or a control. */
const clickAway = (page: Page) => page.locator("footer[aria-label='Chart status']").getByText(/New York time|Last minute candle/).click();
/** The studies are in the toolbar's Indicators menu; this opens it when it is closed. */
async function indicator(page: Page, name: string) {
  const menu = page.getByRole("group", { name: "Chart indicators" });
  if (!(await menu.isVisible())) await page.getByRole("button", { name: "Indicators", exact: true }).click();
  return menu.getByRole("button", { name, exact: true });
}
/**
 * The Gmail state the app shows (the e2e backend has no Gmail, so it reports a
 * disconnected one and the app puts its Reconnect banner above the charts).
 * Layout measurements pin it, so they measure the workspace itself.
 */
const gmail = (page: Page, connected: boolean) => page.route("**/api/backend/gmail/health", (route) => route.fulfill({ json: {
  status: connected ? "live" : "down", message: connected ? "Live" : "Gmail is disconnected, so new Robinhood fills can't be imported. Reconnect Gmail.",
  action: connected ? null : "reconnect_gmail", listener_enabled: connected, last_notification_at: null, last_import_at: null, watch_expires_at: null, data_version: "e2e" } }));
/** The page's scroll size, the window, and the chart grid's box and scroll height. */
const fit = (page: Page) => page.evaluate(() => {
  const grid = document.querySelector<HTMLElement>("[data-testid=chart-grid]")!;
  const box = grid.getBoundingClientRect();
  return { pageHeight: document.documentElement.scrollHeight, pageWidth: document.documentElement.scrollWidth, width: innerWidth, height: innerHeight,
    grid: { top: box.top, bottom: box.bottom, width: Math.round(box.width), height: Math.round(box.height), scrolls: grid.scrollHeight > grid.clientHeight + 1 } };
});

for (const [width, height] of [[1440, 900], [1920, 1080]] as const) {
  test(`at ${width}×${height} the five charts fill the window without page scrolling, with the dock open or closed`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await gmail(page, true);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
    await expect(sidePanel(page)).toBeVisible(); // a desktop opens with the watchlist docked
    for (const docked of [true, false]) {
      if (!docked) {
        await page.getByRole("button", { name: "Watchlist", exact: true }).click();
        await expect(sidePanel(page)).toHaveCount(0);
      }
      await expect.poll(async () => (await fit(page)).grid.width).toBeGreaterThan(docked ? width * 0.7 : width * 0.9);
      const at = await fit(page);
      expect(at.pageHeight, "no page scrolling").toBeLessThanOrEqual(height);
      expect(at.pageWidth, "no sideways scrolling").toBeLessThanOrEqual(width);
      expect(at.grid.scrolls, "all five charts in view").toBe(false);
      for (const id of ALL_PANELS) expect((await drawn(page, id).boundingBox())!.y + (await drawn(page, id).boundingBox())!.height).toBeLessThanOrEqual(at.grid.bottom + 1);
      if (!docked) {
        // The grid, with its panel headers, scales and study panes, is most of the window.
        expect(at.grid.height).toBeGreaterThanOrEqual(height * 0.8);
        expect(at.grid.width).toBeGreaterThanOrEqual(width * 0.9);
      }
      test.info().annotations.push({ type: "layout", description: `${width}×${height} dock ${docked ? "open" : "closed"}: grid ${at.grid.width}×${at.grid.height}, main canvas ${JSON.stringify(await drawn(page, "main").boundingBox())}` });
      await page.screenshot({ path: test.info().outputPath(`workspace-${width}x${height}-dock-${docked ? "open" : "closed"}.png`) });
    }
  });
}

test("at 1280×720 the main chart keeps a usable height however the divider sits, a shorter window scrolls the grid, and Focus gives one chart all of it", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  let at = await fit(page);
  expect(at.pageHeight).toBeLessThanOrEqual(720);
  expect(at.pageWidth).toBeLessThanOrEqual(1280);
  expect(at.grid.scrolls).toBe(false); // five charts fit at the default proportions
  expect((await drawn(page, "main").boundingBox())!.height).toBeGreaterThanOrEqual(230);
  await page.screenshot({ path: test.info().outputPath("workspace-1280x720.png") });
  // The tallest smaller charts the divider allows still leave the main chart its minimum, in view.
  await rowDivider(page).focus();
  await page.keyboard.press("Home");
  await expect.poll(async () => Math.round((await section(page, "main")).height)).toBe(MAIN_MIN);
  at = await fit(page);
  expect(at.grid.scrolls).toBe(false);
  expect(at.pageHeight).toBeLessThanOrEqual(720);
  await page.screenshot({ path: test.info().outputPath("workspace-1280x720-tall.png") });
  // A window too short for both minimums scrolls the grid, never the page.
  await page.setViewportSize({ width: 1280, height: 540 });
  await expect.poll(async () => (await fit(page)).grid.scrolls).toBe(true);
  expect((await fit(page)).pageHeight).toBeLessThanOrEqual(540);
  expect(Math.round((await section(page, "main")).height)).toBeGreaterThanOrEqual(MAIN_MIN);
  expect(Math.round((await section(page, "Panel 3")).height)).toBeGreaterThanOrEqual(LOWER_MIN);
  await chartGrid(page).evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await expect(drawn(page, "Panel 3")).toBeInViewport({ ratio: 1 });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole("button", { name: "Show single chart" }).click();
  await expect.poll(async () => (await drawn(page, "main").boundingBox())!.height).toBeGreaterThan(500);
  expect((await fit(page)).grid.scrolls).toBe(false);
  await page.screenshot({ path: test.info().outputPath("workspace-1280x720-focus.png") });
});

test("a Gmail warning stays above the charts with its Reconnect button, and the page still does not scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await gmail(page, false);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  const reconnect = page.getByRole("button", { name: "Reconnect Gmail" });
  await expect(reconnect).toBeInViewport({ ratio: 1 });
  const banner = (await page.getByRole("alert").filter({ has: reconnect }).boundingBox())!;
  expect(banner.y + banner.height).toBeLessThanOrEqual((await page.locator("header[aria-label='Chart toolbar']").boundingBox())!.y);
  const at = await fit(page);
  expect(at.pageHeight).toBeLessThanOrEqual(720); // the charts give up the banner's height; the grid scrolls if it must
  expect(at.pageWidth).toBeLessThanOrEqual(1280);
  expect((await drawn(page, "main").boundingBox())!.height).toBeGreaterThanOrEqual(230);
});

test("on the charts page the journal navigation is a rail that expands and is remembered; other pages keep the sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main").locator("canvas").first()).toBeVisible();
  const rail = page.getByRole("navigation").filter({ has: page.getByRole("button", { name: "Expand navigation" }) });
  expect((await rail.boundingBox())!.width).toBeLessThanOrEqual(48);
  // Every page is still a named link, the current one marked, with sync status and the Sync drawer reachable.
  for (const name of ["Dashboard", "Daily Review", "Trades", "Analytics", "Fills", "Signals", "Strategy Lab", "Research"]) await expect(rail.getByRole("link", { name, exact: true })).toBeVisible();
  await expect(rail.getByRole("link", { name: "Charts", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(rail.getByTitle("Sync & enrichment status")).toBeVisible();
  const narrow = (await drawn(page, "main").boundingBox())!.width;
  await rail.getByRole("button", { name: "Expand navigation" }).click();
  await expect(page.getByRole("button", { name: "Collapse navigation" })).toBeVisible();
  await expect.poll(async () => (await drawn(page, "main").boundingBox())!.width).toBeLessThan(narrow - 150);
  expect((await fit(page)).pageWidth).toBeLessThanOrEqual(1440);
  await page.reload();
  await expect(page.getByRole("button", { name: "Collapse navigation" })).toBeVisible();
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(rail).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand navigation" })).toBeVisible();
  // Other pages keep the full sidebar.
  await rail.getByRole("link", { name: "Fills", exact: true }).click();
  await expect(page).toHaveURL(/\/fills$/);
  await expect(page.getByRole("button", { name: "Expand navigation" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Trade Journal", exact: true })).toBeVisible();
});

test("dock, navigation and window resizes keep every chart, the selection, the scrolled-back view and the live stream, with no new requests", async ({ page, context }) => {
  await stubExhaustedHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent) => void;
    const win = window as typeof window & { __streams: number; __chartTick?: (value: unknown) => void };
    win.__streams = 0;
    class MockEventSource {
      static current: MockEventSource | null = null;
      listeners = new Map<string, Listener>();
      closed = false;
      constructor() { win.__streams++; MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
      emit(type: string, value: unknown) { if (!this.closed) this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
      close() { this.closed = true; }
    }
    win.__chartTick = (value) => MockEventSource.current?.emit("tick", value);
    window.EventSource = MockEventSource as unknown as typeof EventSource;
  });
  const requests: number[] = [];
  await stub(page, () => { requests.push(Date.now()); });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Pivot", "250.00");
  await expect.poll(() => savedLevels(server).length).toBe(1);
  const pivot = savedLevels(server)[0].id;
  await clickChart(page, "main", { x: 220, y: await levelY(page, "main", 250) });
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", pivot);
  await moveAway(page, "main", { from: 100, to: 160 });
  await page.evaluate(() => { for (const [id, chart] of (window as unknown as { __tjCharts: Map<string, Record<string, unknown>> }).__tjCharts) chart.__was = id; });
  const streams = await page.evaluate(() => (window as unknown as { __streams: number }).__streams);
  const started = Date.now();
  const before = requests.length;
  const unchanged = async (step: string) => {
    await page.waitForTimeout(250);
    expect(await page.evaluate(() => [...(window as unknown as { __tjCharts: Map<string, Record<string, unknown>> }).__tjCharts].map(([id, chart]) => chart.__was === id)), `${step}: same chart instances`).toEqual([true, true, true, true, true]);
    await expect(drawn(page, "main"), `${step}: still selected`).toHaveAttribute("data-selected", pivot);
    expect((await roundedRange(page, "main"))!.to, `${step}: still scrolled back`).toBe(160);
    expect(await page.evaluate(() => (window as unknown as { __streams: number }).__streams), `${step}: same stream`).toBe(streams);
    // Only the regular 15-second refresh may have run meanwhile.
    expect(requests.length - before, `${step}: no new requests`).toBeLessThanOrEqual(Math.floor((Date.now() - started) / 15_000));
  };
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(sidePanel(page)).toHaveCount(0);
  await unchanged("dock closed");
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  await expect(page.getByRole("region", { name: "Layers" })).toBeVisible();
  await unchanged("layers docked");
  await page.getByRole("button", { name: "Expand navigation" }).click();
  await unchanged("navigation expanded");
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await page.setViewportSize({ width: 1180, height: 760 });
  await unchanged("window shrunk");
  await page.setViewportSize({ width: 1700, height: 1000 });
  await unchanged("window grown");
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await unchanged("full screen");
  await page.keyboard.press("Escape"); // drops the selection first
  await expect(drawn(page, "main")).not.toHaveAttribute("data-selected", pivot);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");

  // The charts still work after all that: a streamed trade moves the quote, a drag moves the level.
  const at = Math.floor(Date.now() / 1000) + 2;
  await page.evaluate((tick) => (window as unknown as { __chartTick: (value: unknown) => void }).__chartTick(tick),
    { type: "tick", symbol: "MRVL", at, minute: Math.floor(at / 60) * 60, session: "post", price: 281.5, open: 281.5, high: 281.5, low: 281.5,
      buckets: { "5m": { time: Math.floor(at / 300) * 300, end_time: Math.floor(at / 300) * 300 + 300, extended: true } } });
  await expect(page.getByLabel("Selected symbol quote")).toContainText("281.50");
  await page.keyboard.press("Alt+r");
  await expect.poll(async () => (await roundedRange(page, "main"))?.to).toBeGreaterThanOrEqual(244); // the trade opened a newer candle
  // Following the new live candle animates the price scale. A coordinate read
  // during that transition can miss the level, or turn a $2 move into <3px.
  await expect.poll(async () => {
    const before = await levelY(page, "main", 250);
    await page.waitForTimeout(100);
    return Math.abs((await levelY(page, "main", 250)) - before);
  }).toBeLessThan(0.5);
  await clickChart(page, "main", { x: 220, y: await levelY(page, "main", 250) });
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", pivot);
  const [fromY, toY] = await page.evaluate(() => {
    const candles = (window as unknown as { __tjCharts: PaneRegistry }).__tjCharts.get("main")!
      .panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!;
    return [candles.priceToCoordinate(250)!, candles.priceToCoordinate(252)!];
  });
  expect(fromY - toY).toBeGreaterThan(3); // the chart's minimum drag distance
  await mouseDrag(page, "main", fromY, toY);
  await expect.poll(() => savedLevels(server)[0].price).toBeGreaterThan(251);
});

test("the toolbar fits a 1024px window, its menus close on Escape before anything else, and Tab runs toolbar, tools, charts, dock", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "main").locator("canvas").first()).toBeVisible();
  const toolbar = page.locator("header[aria-label='Chart toolbar']");
  expect(await toolbar.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  expect((await fit(page)).pageWidth).toBeLessThanOrEqual(1024);
  for (const name of ["Chart symbol", "Indicators", "Layouts", "Show single chart", "Link time ranges", "Plan trade", "Pause chart updates", "Refresh charts", "Keyboard shortcuts", "Enter full-screen charts", "Watchlist", "Layers", "Strike ladder"]) {
    const control = name === "Chart symbol" ? page.getByLabel(name) : page.getByRole("button", { name, exact: name !== "Layouts" });
    await expect(control.first(), name).toBeInViewport();
  }
  await page.screenshot({ path: test.info().outputPath("toolbar-1024.png") });

  // The Indicators menu: toggles keep their pressed state; Escape closes it before it puts a tool away.
  await tool(page, "trend line").click();
  const rsi = await indicator(page, "RSI 14");
  await expect(rsi).toHaveAttribute("aria-pressed", "true");
  await rsi.click();
  await expect(rsi).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("group", { name: "Chart indicators" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Indicators", exact: true })).toBeFocused();
  await expect(tool(page, "trend line")).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(tool(page, "trend line")).toHaveAttribute("aria-pressed", "false");
  // A press outside closes it too.
  await indicator(page, "RSI 14");
  await clickAway(page);
  await expect(page.getByRole("group", { name: "Chart indicators" })).toHaveCount(0);

  // Focus order: the toolbar's last control (the strike ladder's dock tab, C4.5), then the tool rail, then the charts, with the dock last.
  await page.getByRole("button", { name: "Strike ladder", exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(tool(page, "price level")).toBeFocused(); // Undo and Redo are disabled, so the first tool is next
  await page.getByRole("button", { name: "Magnet" }).focus();
  await page.keyboard.press("Tab");
  await expect(mainInterval(page)).toBeFocused();
  // Past the last chart (each chart's own attribution link takes a stop), the dock's edge is next, then the dock.
  await page.getByRole("button", { name: "Focus 1m chart" }).focus();
  for (let stops = 0; stops < 4 && await page.evaluate(() => !!document.activeElement?.closest("[data-testid=chart-grid]")); stops++) await page.keyboard.press("Tab");
  await expect(dockDivider(page)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Previous watchlist symbol" })).toBeFocused();
});

// ---- C7.4: dividers, the dock's edge and maximize ----

/** Drag a divider by (dx, dy) with the mouse, in steps; `release: false` leaves the button down. */
async function dragDivider(page: Page, divider: Locator, dx: number, dy: number, release = true) {
  const box = (await divider.boundingBox())!;
  const [x, y] = [box.x + box.width / 2, box.y + box.height / 2];
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 5 });
  await page.mouse.move(x + dx, y + dy, { steps: 5 });
  if (release) await page.mouse.up();
}
const near = (value: number, target: number, within = 2) => Math.abs(value - target) <= within;
/** At 1440×900 the main chart and the smaller row share 823px (C7.3's grid less its padding and divider). */
const ROWS_1440 = 823;
/** The four smaller charts' boxes, left to right. */
const lowerRow = (page: Page) => Promise.all(["Panel 2", "Panel 3", "Panel 4", "Panel 5"].map((id) => section(page, id)));
type LiveWindow = typeof window & { __streams: number; __chartTick?: (value: unknown) => void; __tjRenders?: Map<string, number> };
/** A stand-in for the chart stream that counts connections and takes ticks from the test. */
const mockStream = (page: Page) => page.addInitScript(() => {
  type Listener = (event: MessageEvent) => void;
  const win = window as LiveWindow;
  win.__streams = 0;
  win.__tjRenders = new Map();
  class MockEventSource {
    static current: MockEventSource | null = null;
    listeners = new Map<string, Listener>();
    closed = false;
    constructor() { win.__streams++; MockEventSource.current = this; queueMicrotask(() => this.emit("status", { state: "connected" })); }
    addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.listeners.set(type, listener as Listener); }
    emit(type: string, value: unknown) { if (!this.closed) this.listeners.get(type)?.({ data: JSON.stringify(value) } as MessageEvent); }
    close() { this.closed = true; }
  }
  win.__chartTick = (value) => MockEventSource.current?.emit("tick", value);
  window.EventSource = MockEventSource as unknown as typeof EventSource;
});
const sendTrade = (page: Page, value: number) => {
  const at = Math.floor(Date.now() / 1000) + 2;
  return page.evaluate((tick) => (window as LiveWindow).__chartTick!(tick), { type: "tick", symbol: "MRVL", at, minute: Math.floor(at / 60) * 60, session: "post",
    price: value, open: value, high: value, low: value, buckets: { "5m": { time: Math.floor(at / 300) * 300, end_time: Math.floor(at / 300) * 300 + 300, extended: true } } });
};
const markCharts = (page: Page) => page.evaluate(() => { for (const [id, chart] of (window as unknown as { __tjCharts: Map<string, Record<string, unknown>> }).__tjCharts) chart.__was = id; });
const sameCharts = (page: Page) => page.evaluate(() => [...(window as unknown as { __tjCharts: Map<string, Record<string, unknown>> }).__tjCharts].every(([id, chart]) => chart.__was === id)
  && (window as unknown as { __tjCharts: Map<string, unknown> }).__tjCharts.size === 5);

test("the divider above the smaller charts drags, steps by keyboard, stops at its limits, resets, and Escape mid-drag puts it back", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const server = await fakeChartSettings(context);
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  // The defaults reproduce C7.3's geometry: smaller charts 311px tall with their headers.
  expect(near((await section(page, "Panel 2")).height, 311)).toBe(true);
  await expect(rowDivider(page)).toHaveAttribute("aria-valuenow", "62");
  await expect(rowDivider(page)).toHaveAttribute("aria-orientation", "horizontal");
  await page.screenshot({ path: test.info().outputPath("dividers-default-1440.png") });

  // A drag up 120px gives the smaller charts 120px and saves their share once.
  await dragDivider(page, rowDivider(page), 0, -120);
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 431)).toBe(true);
  expect(near((await section(page, "main")).height, ROWS_1440 - 431)).toBe(true);
  await expect.poll(() => proportionsOn(server)?.lower).toBeCloseTo(431 / ROWS_1440, 2);
  expect(proportionsOn(server)?.columns).toEqual([0.25, 0.25, 0.25, 0.25]);
  await page.screenshot({ path: test.info().outputPath("dividers-dragged-1440.png") });

  // Keyboard: Down gives the main chart 2% more, Shift+Down 10%; Home and End are the limits; Enter resets.
  await rowDivider(page).focus();
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 431 - 0.02 * ROWS_1440)).toBe(true);
  await page.keyboard.press("Shift+ArrowDown");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 431 - 0.12 * ROWS_1440)).toBe(true);
  await page.keyboard.press("Home");
  await expect(rowDivider(page)).toHaveAttribute("aria-valuenow", "40");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 0.6 * ROWS_1440)).toBe(true);
  await page.keyboard.press("End");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, LOWER_MIN)).toBe(true);
  // Dragged past its limit, the divider stops there: the main chart never goes under its minimum.
  await dragDivider(page, rowDivider(page), 0, -2000);
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 0.6 * ROWS_1440)).toBe(true);
  expect((await section(page, "main")).height).toBeGreaterThanOrEqual(MAIN_MIN);
  await rowDivider(page).focus();
  await page.keyboard.press("Enter");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 311)).toBe(true);
  await expect(rowDivider(page)).toHaveAttribute("aria-valuenow", "62");
  // End did not jump every chart to its latest candle, and Enter typed no interval: the divider kept those keys.
  await expect(page.getByRole("status", { name: "Interval entry" })).toHaveCount(0);
  await expect.poll(() => proportionsOn(server)?.lower).toBe(0.378);

  // A double-click resets it too.
  await dragDivider(page, rowDivider(page), 0, 80);
  await expect.poll(() => proportionsOn(server)?.lower).toBeLessThan(0.3);
  const bar = (await rowDivider(page).boundingBox())!;
  await page.mouse.dblclick(bar.x + bar.width / 2, bar.y + bar.height / 2);
  await expect.poll(() => proportionsOn(server)?.lower).toBe(0.378);
  expect(near((await section(page, "Panel 2")).height, 311)).toBe(true);

  // Escape during a drag puts the divider back and saves nothing; the Escape goes no further.
  await page.waitForTimeout(600);
  const saves = server.saves.length;
  await dragDivider(page, rowDivider(page), 0, -90, false);
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 401)).toBe(true);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 311)).toBe(true);
  await page.waitForTimeout(800);
  expect(server.saves.length).toBe(saves);
});

test("the dividers between the smaller charts and the dock's edge resize, stop at their limits and reset; the dock's width stays on this device", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const server = await fakeChartSettings(context);
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  let row = await lowerRow(page);
  const total = row.reduce((sum, box) => sum + box.width, 0);
  for (const box of row) expect(near(box.width, total / 4)).toBe(true);

  // Panel 2 takes 60px from Panel 3; the others keep their widths.
  await dragDivider(page, columnDivider(page, 2), 60, 0);
  await expect.poll(async () => near((await lowerRow(page))[0].width, total / 4 + 60)).toBe(true);
  row = await lowerRow(page);
  expect(near(row[1].width, total / 4 - 60)).toBe(true);
  expect(near(row[2].width, total / 4) && near(row[3].width, total / 4)).toBe(true);
  await expect.poll(() => proportionsOn(server)?.columns[0]).toBeCloseTo((total / 4 + 60) / total, 2);
  // Keyboard, then the limits: no smaller chart narrower than 160px or a tenth of the row.
  const least = Math.max(160, total * 0.1);
  await columnDivider(page, 3).focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => near((await lowerRow(page))[1].width, total / 4 - 60 - 0.02 * total)).toBe(true);
  await page.keyboard.press("Home");
  await expect.poll(async () => near((await lowerRow(page))[1].width, least)).toBe(true);
  await dragDivider(page, columnDivider(page, 3), 2000, 0);
  await expect.poll(async () => near((await lowerRow(page))[2].width, least)).toBe(true);
  expect((await lowerRow(page)).every((box) => box.width >= least - 1)).toBe(true);
  // At its narrowest a chart's header buttons stay whole and usable.
  for (const name of ["Maximize 1D chart", "Focus 1D chart", "Latest candles Panel 4"]) await expect(page.getByRole("button", { name, exact: true })).toBeInViewport({ ratio: 1 });
  const header = await section(page, "Panel 4");
  const maximize = (await page.getByRole("button", { name: "Focus 1D chart", exact: true }).boundingBox())!;
  expect(maximize.x + maximize.width).toBeLessThanOrEqual(header.x + header.width);
  await page.screenshot({ path: test.info().outputPath("dividers-columns-1440.png") });
  await columnDivider(page, 4).focus();
  await page.keyboard.press("Enter"); // every smaller chart back to a quarter of the row
  await expect.poll(async () => (await lowerRow(page)).every((box) => near(box.width, total / 4))).toBe(true);
  await expect.poll(() => proportionsOn(server)?.columns).toEqual([0.25, 0.25, 0.25, 0.25]);

  // The dock's edge: 256px to start, wider to the left, within 200px and the room the charts need.
  const dock = async () => Math.round((await sidePanel(page).boundingBox())!.width);
  expect(await dock()).toBe(256);
  await dragDivider(page, dockDivider(page), -100, 0);
  await expect.poll(dock).toBe(356);
  await dockDivider(page).focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(dock).toBe(340);
  await page.keyboard.press("Home");
  await expect.poll(dock).toBe(200);
  await page.keyboard.press("End");
  await expect.poll(dock).toBe(480);
  expect((await fit(page)).grid.width).toBeGreaterThanOrEqual(640);
  await page.keyboard.press("Enter");
  await expect.poll(dock).toBe(256);
  await dragDivider(page, dockDivider(page), -44, 0);
  await expect.poll(dock).toBe(300);
  // Kept on this device across a reload, and never sent to the server.
  await page.waitForTimeout(600);
  await page.reload();
  await expect(sidePanel(page)).toBeVisible();
  await expect.poll(dock).toBe(300);
  expect(Object.keys(server.data ?? {}).filter((key) => /dock/i.test(key))).toEqual([]);

  // Reset chart sizes puts the dividers and the dock back.
  await rowDivider(page).focus();
  await page.keyboard.press("Home");
  await dragDivider(page, columnDivider(page, 2), -40, 0);
  await expect.poll(() => proportionsOn(server)?.lower).toBe(0.6);
  const menu = await openLayouts(page);
  await menu.getByRole("button", { name: "Reset chart sizes" }).click();
  await expect(menu).toHaveCount(0);
  await expect.poll(dock).toBe(256);
  await expect.poll(() => proportionsOn(server)).toEqual({ lower: 0.378, columns: [0.25, 0.25, 0.25, 0.25] });
  expect(near((await section(page, "Panel 2")).height, 311)).toBe(true);
});

test("a divider drag re-renders no chart while it moves, saves once when released, and fetches nothing", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await mockStream(page);
  let requests = 0;
  await gmail(page, true);
  await stub(page, () => { requests++; });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(page.getByText("Tradier stream · studies refresh 15s")).toBeVisible();
  await markCharts(page);
  await page.waitForTimeout(600);
  const renders = () => page.evaluate(() => Object.fromEntries((window as LiveWindow).__tjRenders!));
  const streams = await page.evaluate(() => (window as LiveWindow).__streams);
  const started = Date.now();
  const fetched = requests;
  for (const [name, divider, dx, dy] of [["rows", rowDivider(page), 0, -100], ["columns", columnDivider(page, 3), 70, 0], ["dock", dockDivider(page), -60, 0]] as const) {
    const saves = server.saves.length;
    const before = await renders();
    const sizes = [await section(page, "Panel 3"), (await sidePanel(page).boundingBox())!];
    await dragDivider(page, divider, dx, dy, false);
    // Twenty pointer moves later the boxes have moved, and nothing re-rendered or saved.
    await expect.poll(async () => JSON.stringify([await section(page, "Panel 3"), (await sidePanel(page).boundingBox())!]), `${name}: previewed`).not.toBe(JSON.stringify(sizes));
    expect(await renders(), `${name}: no chart rendered while dragging`).toEqual(before);
    expect(server.saves.length, `${name}: nothing saved while dragging`).toBe(saves);
    await page.mouse.up();
    if (name === "dock") {
      await page.waitForTimeout(800);
      expect(server.saves.length, "the dock's width is not a shared setting").toBe(saves);
    } else {
      await expect.poll(() => server.saves.length, `${name}: saved on release`).toBe(saves + 1);
      await page.waitForTimeout(800);
      expect(server.saves.length, `${name}: saved once`).toBe(saves + 1);
    }
  }
  expect(await sameCharts(page)).toBe(true);
  expect(await page.evaluate(() => (window as LiveWindow).__streams)).toBe(streams);
  expect(requests - fetched).toBeLessThanOrEqual(Math.floor((Date.now() - started) / 15_000));
});

test("maximize and restore each chart: the same instances, view, selection and stream, with no requests; Escape restores after the selection and before full screen", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await mockStream(page);
  const requests: number[] = [];
  await gmail(page, true);
  await stub(page, () => { requests.push(Date.now()); });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await addLevel(page, "Pivot", "250.00");
  await expect.poll(() => savedLevels(server).length).toBe(1);
  const pivot = savedLevels(server)[0].id;
  await clickChart(page, "main", { x: 220, y: await levelY(page, "main", 250) });
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", pivot);
  await moveAway(page, "main", { from: 100, to: 160 });
  await moveAway(page, "Panel 2", { from: 150, to: 190 });
  await markCharts(page);
  const streams = await page.evaluate(() => (window as LiveWindow).__streams);
  const started = Date.now();
  const before = requests.length;
  const boxes = async () => Promise.all(ALL_PANELS.map((id) => section(page, id)));
  const ranges = async () => Promise.all(ALL_PANELS.map((id) => roundedRange(page, id)));
  const grid = await fit(page);
  const geometry = await boxes();
  const views = await ranges();
  const intervals = ["5m", "15m", "1h", "1D", "1m"];
  for (const [index, id] of ALL_PANELS.entries()) {
    await page.getByRole("button", { name: `Maximize ${intervals[index]} chart`, exact: true }).click();
    await expect(chartGrid(page)).toHaveAttribute("data-maximized", String(index));
    // It covers the grid; the others are hidden at their size underneath.
    await expect.poll(async () => (await section(page, id)).width).toBeGreaterThan(grid.grid.width - 12);
    expect((await section(page, id)).height).toBeGreaterThan(grid.grid.height - 12);
    for (const other of ALL_PANELS.filter((name) => name !== id)) await expect(drawn(page, other)).not.toBeVisible();
    if (index === 1) await page.screenshot({ path: test.info().outputPath("maximized-15m-1440.png") });
    await page.getByRole("button", { name: "Restore charts" }).click();
    await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
    await expect.poll(async () => (await boxes()).every((box, at) => near(box.x, geometry[at].x, 1) && near(box.y, geometry[at].y, 1) && near(box.width, geometry[at].width, 1) && near(box.height, geometry[at].height, 1)), `${id}: geometry restored`).toBe(true);
    expect(await ranges(), `${id}: every chart's view as it was`).toEqual(views);
  }
  expect(await sameCharts(page)).toBe(true);
  await expect(drawn(page, "main")).toHaveAttribute("data-selected", pivot);

  // While maximized the chart takes ticks; it stays maximized through a symbol, an interval and the dock.
  await page.getByRole("button", { name: "Maximize 5m chart", exact: true }).click();
  await sendTrade(page, 281.5);
  await expect(page.getByLabel("Selected symbol quote")).toContainText("281.50");
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await page.getByLabel("Main interval", { exact: true }).selectOption("15m");
  await expect(page.getByRole("region", { name: "NVDA 15m chart" }).first()).toBeVisible();
  await expect(chartGrid(page)).toHaveAttribute("data-maximized", "0");
  await page.getByRole("button", { name: "Restore charts" }).click();
  await page.getByLabel("Main interval", { exact: true }).selectOption("5m");
  await page.getByRole("button", { name: "Chart MRVL", exact: true }).click();
  await expect(page.getByRole("region", { name: "MRVL 5m chart" })).toBeVisible();
  expect(await sameCharts(page)).toBe(true);
  expect(await page.evaluate(() => (window as LiveWindow).__streams)).toBe(streams + 2); // two symbol switches, nothing else
  // Maximizing and restoring fetched nothing: only the two symbol and two interval switches, and the regular refresh.
  await expect.poll(() => requests.length - before).toBeGreaterThanOrEqual(4);
  expect(requests.length - before - 4).toBeLessThanOrEqual(Math.floor((Date.now() - started) / 15_000));

  // Escape: the selection first, then the maximized chart, then full screen.
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true");
  // The chart resizes into full screen: the level's place is read again until the click lands on it.
  await expect(async () => {
    await clickChart(page, "main", { x: 220, y: await levelY(page, "main", 250) });
    await expect(drawn(page, "main")).toHaveAttribute("data-selected", pivot, { timeout: 1000 });
  }).toPass();
  await page.getByRole("button", { name: "Maximize 5m chart", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(drawn(page, "main")).not.toHaveAttribute("data-selected", pivot);
  await expect(chartGrid(page)).toHaveAttribute("data-maximized", "0");
  await page.keyboard.press("Escape");
  await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
  await expect(page.getByTestId("chart-workspace")).toHaveAttribute("data-immersive", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("chart-workspace")).not.toHaveAttribute("data-immersive", "true");

  // Switching layouts, Focus and "make main chart" each end it.
  await saveLayout(page, "Plain");
  await page.getByRole("button", { name: "Maximize 1h chart", exact: true }).click();
  await useLayout(page, "Plain");
  await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
  await page.getByRole("button", { name: "Maximize 1h chart", exact: true }).click();
  await page.getByRole("button", { name: "Show single chart" }).click();
  await page.getByRole("button", { name: "Show five charts" }).click();
  await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
  await page.getByRole("button", { name: "Maximize 1h chart", exact: true }).click();
  await page.getByRole("button", { name: "Focus 1h chart" }).click();
  await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
  await expect(mainInterval(page)).toHaveValue("1h"); // the panel became the main chart, as before
});

test("a shrinking window clamps the dividers on screen without saving them, and growing back restores the same sizes", async ({ page, context }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const server = await fakeChartSettings(context);
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  await rowDivider(page).focus();
  await page.keyboard.press("Home");
  await dragDivider(page, columnDivider(page, 2), 150, 0);
  await expect.poll(() => proportionsOn(server)?.columns[0]).toBeGreaterThan(0.3);
  await page.waitForTimeout(600);
  const saved = JSON.stringify(proportionsOn(server));
  const saves = server.saves.length;
  const wide = await Promise.all(ALL_PANELS.map((id) => section(page, id)));
  for (const [width, height] of [[1280, 720], [1024, 768], [1100, 600]] as const) {
    await page.setViewportSize({ width, height });
    await expect.poll(async () => (await fit(page)).width).toBe(width);
    await page.waitForTimeout(200);
    const at = await fit(page);
    expect(at.pageHeight, `${width}×${height}: no page scrolling`).toBeLessThanOrEqual(height);
    expect(at.pageWidth, `${width}×${height}: no sideways scrolling`).toBeLessThanOrEqual(width);
    expect(Math.round((await section(page, "main")).height), `${width}×${height}: main chart minimum`).toBeGreaterThanOrEqual(MAIN_MIN);
    for (const box of await lowerRow(page)) expect(Math.round(box.height), `${width}×${height}: smaller chart minimum`).toBeGreaterThanOrEqual(LOWER_MIN);
    expect(Math.min(...(await lowerRow(page)).map((box) => box.width)), `${width}×${height}: smaller chart width`).toBeGreaterThanOrEqual(159);
    await page.screenshot({ path: test.info().outputPath(`dividers-clamped-${width}x${height}.png`) });
  }
  // The navigation expanded beside a 1024px window leaves too little width for four 160px charts:
  // the smaller row scrolls sideways inside the grid; neither the page nor a chart is squeezed.
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.getByRole("button", { name: "Expand navigation" }).click();
  const row = chartGrid(page).locator("> div").nth(2);
  await expect.poll(() => row.evaluate((el) => el.scrollWidth > el.clientWidth + 1)).toBe(true);
  for (const box of await lowerRow(page)) expect(Math.round(box.width)).toBeGreaterThanOrEqual(159);
  expect((await fit(page)).pageWidth).toBeLessThanOrEqual(1024);
  await row.evaluate((el) => el.scrollTo({ left: el.scrollWidth }));
  await expect(drawn(page, "Panel 5")).toBeInViewport({ ratio: 0.9 });
  await expect(page.getByRole("button", { name: "Maximize 1m chart", exact: true })).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: test.info().outputPath("dividers-1024-navigation-expanded.png") });
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect.poll(async () => (await Promise.all(ALL_PANELS.map((id) => section(page, id)))).every((box, at) => near(box.height, wide[at].height, 1) && near(box.width, wide[at].width, 1))).toBe(true);
  await page.waitForTimeout(800);
  expect(server.saves.length, "resizing the window saved nothing").toBe(saves);
  expect(JSON.stringify(proportionsOn(server))).toBe(saved);
});

test("saved layouts keep their chart sizes, layouts saved before the dividers open at their S/M/L height, and malformed sizes load safely", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const old = (name: string, smallSize: string) => ({ id: `id-${name}`, name, layout: "multi", intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, null, null, null], smallSize, linkRange: false });
  const server = await fakeChartSettings(context, { revision: 1, data: {
    layouts: [old("Tall", "tall"), old("Compact", "compact")],
    // Not proportions at all, and one for a layout an older tab deleted.
    layoutProportions: { "id-Tall": "bad", "id-Gone": { lower: 0.3, columns: [0.25, 0.25, 0.25, 0.25] } },
  } });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  // C7.3's S/M/L heights at this window: 426, 311 and 226px with headers.
  await useLayout(page, "Tall");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 426, 8)).toBe(true);
  await expect(layoutsButton(page)).toContainText("Tall");
  await useLayout(page, "Compact");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 226, 8)).toBe(true);
  await expect.poll(() => (server.data as { layoutProportions?: object }).layoutProportions).toEqual({}); // the unusable and the orphaned are gone
  // A layout saved now keeps its proportions, and the list keeps exactly the keys an older tab reads.
  await dragDivider(page, rowDivider(page), 0, -150);
  await dragDivider(page, columnDivider(page, 4), -50, 0);
  await expect(layoutsButton(page)).toHaveText("Layouts");
  await saveLayout(page, "Mine");
  await expect.poll(() => layoutNames(server)).toEqual(["Tall", "Compact", "Mine"]);
  for (const layout of layoutsOn(server)) expect(Object.keys(layout).sort()).toEqual(LAYOUT_KEYS);
  const mine = layoutsOn(server)[2].id;
  await expect.poll(() => proportionsOn(server, mine)?.columns[2]).toBeLessThan(0.25);
  const shaped = await lowerRow(page);
  await useLayout(page, "Tall");
  await expect.poll(async () => near((await section(page, "Panel 2")).height, 426, 8)).toBe(true);
  await useLayout(page, "Mine");
  await expect.poll(async () => (await lowerRow(page)).every((box, at) => near(box.width, shaped[at].width, 1) && near(box.height, shaped[at].height, 1))).toBe(true);
  // Deleting a layout drops its proportions with it.
  const menu = await openLayouts(page);
  await menu.getByRole("button", { name: "Delete Mine" }).click();
  await menu.getByRole("button", { name: "Delete", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect.poll(() => Object.keys((server.data as { layoutProportions: object }).layoutProportions)).toEqual([]);

  // Proportions nobody could have saved are repaired into ones the dividers could make:
  // the main divider's value is the main chart's share, each column divider's the share of the row to its left.
  const cases: [unknown, string, string[]][] = [
    [{ lower: "0.3" }, "62", ["25", "50", "75"]],
    ["nonsense", "62", ["25", "50", "75"]],
    [{ lower: null, columns: [0.4, 0.2, 0.2, 0.2] }, "62", ["25", "50", "75"]],
    [{ lower: 0.95, columns: [1, 1, 1] }, "40", ["25", "50", "75"]],
    [{ lower: -1, columns: [0, 0, 0, 1] }, "85", ["10", "20", "30"]],
    [{ lower: 0.3, columns: [0.97, 0.01, 0.01, 0.01] }, "70", ["70", "80", "90"]],
    [{ lower: 0.3, columns: [2, 2, 2, 2] }, "70", ["25", "50", "75"]],
  ];
  for (const [bad, valuenow, columns] of cases) {
    server.data = { ...(server.data as object), proportions: bad, smallSize: "normal" }; // without proportions the share follows S/M/L
    server.revision += 1;
    await page.reload();
    await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
    await expect(rowDivider(page), JSON.stringify(bad)).toHaveAttribute("aria-valuenow", valuenow);
    for (const [at, value] of columns.entries()) await expect(columnDivider(page, at + 2), JSON.stringify(bad)).toHaveAttribute("aria-valuenow", value);
    // On screen no smaller chart is narrower than 160px, however small its share.
    for (const box of await lowerRow(page)) expect(Math.round(box.width), JSON.stringify(bad)).toBeGreaterThanOrEqual(159);
    expect(Math.round((await section(page, "Panel 2")).height)).toBeGreaterThanOrEqual(LOWER_MIN);
    expect(Math.round((await section(page, "main")).height)).toBeGreaterThanOrEqual(MAIN_MIN);
  }
  expect(errors).toEqual([]);
});

test("two browsers share the chart proportions but not the dock's width, merge a conflicting save, and keep proportions through an older build's save", { tag: "@real-settings" }, async ({ page, browser, request }) => {
  const settingsNow = async () => (await (await request.get("/api/backend/charts/settings")).json()) as { revision: number; data: Record<string, unknown> & { proportions?: Sizes | null; layoutProportions?: Record<string, Sizes>; layouts?: SavedLayouts; intervals?: string[] } };
  const start = await settingsNow();
  if (start.revision) expect((await request.put("/api/backend/charts/settings", { data: { base_revision: start.revision, data: EMPTY_SETTINGS } })).ok()).toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await gmail(page, true);
  await stub(page);
  await page.goto("/charts");
  await expect(drawn(page, "Panel 5").locator("canvas").first()).toBeVisible();
  await dragDivider(page, rowDivider(page), 0, -100);
  await expect.poll(async () => (await settingsNow()).data?.proportions?.lower).toBeCloseTo(411 / ROWS_1440, 2);
  await dragDivider(page, dockDivider(page), -80, 0);
  await expect.poll(async () => Math.round((await sidePanel(page).boundingBox())!.width)).toBe(336);
  await expect(syncStatus(page)).toHaveText("Saved");

  // A second browser (its own storage, like another computer) opens at the same proportions and its own dock width.
  const other = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await noPlans(other);
  const second = await other.newPage();
  await gmail(second, true);
  await stub(second);
  await second.goto("/charts");
  await expect(drawn(second, "Panel 5").locator("canvas").first()).toBeVisible();
  await expect.poll(async () => near((await section(second, "Panel 2")).height, (await section(page, "Panel 2")).height)).toBe(true);
  await expect.poll(async () => Math.round((await sidePanel(second).boundingBox())!.width)).toBe(256);

  // It changes an interval; the first browser, not yet refreshed, drags a divider: the refused save merges both.
  await second.getByLabel("Panel 4 interval", { exact: true }).selectOption("4h");
  await expect.poll(async () => (await settingsNow()).data?.intervals?.[3]).toBe("4h");
  await dragDivider(page, columnDivider(page, 2), 60, 0);
  await expect(syncStatus(page)).toHaveText("Merged with changes from another device");
  await expect.poll(async () => (await settingsNow()).data?.proportions?.columns[0] ?? 0).toBeGreaterThan(0.27);
  const merged = await settingsNow();
  expect(merged.data.intervals?.[3]).toBe("4h");
  expect(merged.data.proportions?.lower).toBeCloseTo(411 / ROWS_1440, 2);
  await expect(page.getByLabel("Panel 4 interval", { exact: true })).toHaveValue("4h");

  // A saved layout: the list keeps C7.2's keys, its proportions sit beside it.
  await saveLayout(page, "Wide main");
  await expect.poll(async () => (await settingsNow()).data?.layouts?.map((layout) => layout.name)).toEqual(["Wide main"]);
  const saved = await settingsNow();
  const id = saved.data.layouts![0].id;
  expect(Object.keys(saved.data.layouts![0]).sort()).toEqual(LAYOUT_KEYS);
  expect(saved.data.layoutProportions?.[id]).toEqual(saved.data.proportions);

  // A tab on an older build saves without the fields it does not know: the server keeps them.
  const { proportions, layoutProportions, ...older } = saved.data;
  expect((await request.put("/api/backend/charts/settings", { data: { base_revision: saved.revision, data: { ...older, session: "regular" } } })).ok()).toBe(true);
  const after = await settingsNow();
  expect(after.data.proportions).toEqual(proportions);
  expect(after.data.layoutProportions).toEqual(layoutProportions);
  expect(after.data.session).toBe("regular");
  // The older tab deletes the layout; this browser's next save lets its proportions go.
  expect((await request.put("/api/backend/charts/settings", { data: { base_revision: after.revision, data: { ...older, session: "regular", layouts: [] } } })).ok()).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("button", { name: "Extended hours", pressed: false })).toBeVisible();
  await rowDivider(page).focus();
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await settingsNow()).data?.layoutProportions).toEqual({});
  expect((await settingsNow()).data.proportions?.lower).toBeCloseTo(411 / ROWS_1440 - 0.02, 2);
  await other.close();
});

test.describe("phone workspace", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("toolbar controls are 44px, the dock is a sheet over the chart, and nothing scrolls sideways", async ({ page }) => {
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "main").locator("canvas").first()).toBeVisible();
    const toolbar = page.locator("header[aria-label='Chart toolbar']");
    for (const target of await toolbar.getByRole("button").all()) {
      if (!(await target.isVisible())) continue;
      const size = (await target.boundingBox())!;
      expect(Math.min(size.width, size.height), (await target.getAttribute("aria-label")) ?? (await target.textContent())!).toBeGreaterThanOrEqual(44);
    }
    expect((await fit(page)).pageWidth).toBeLessThanOrEqual(390);
    const canvas = (await drawn(page, "main").boundingBox())!;
    expect(canvas.height).toBeGreaterThanOrEqual(400);
    await page.screenshot({ path: test.info().outputPath("phone-toolbar.png"), fullPage: true });

    // The secondary controls, the data note and the library's attribution wait in the More menu.
    await page.getByRole("button", { name: "More chart controls" }).tap();
    const more = page.getByRole("group", { name: "More chart controls" });
    for (const name of ["Link time ranges", "Pause chart updates", "Refresh charts", "compact small charts"]) await expect(more.getByRole("button", { name })).toBeInViewport();
    await expect(more.getByRole("link", { name: "TradingView Lightweight Charts™" })).toBeInViewport();
    expect((await fit(page)).pageWidth).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("phone-more-menu.png") });
    await page.keyboard.press("Escape");
    await expect(more).toHaveCount(0);

    await page.getByRole("button", { name: "Watchlist", exact: true }).tap();
    const sheet = page.getByRole("dialog", { name: "Watchlist" });
    await expect(sheet).toBeVisible();
    const box = (await sheet.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(389);
    expect(Math.abs(box.y + box.height - 844)).toBeLessThan(2);
    for (const target of await sheet.getByRole("button").all()) {
      const size = (await target.boundingBox())!;
      expect(size.height, (await target.getAttribute("aria-label")) ?? (await target.textContent())!).toBeGreaterThanOrEqual(44);
    }
    expect((await drawn(page, "main").boundingBox())!.height).toBe(canvas.height); // over the chart, not squeezing it
    await page.screenshot({ path: test.info().outputPath("phone-watchlist-sheet.png") });
    await sheet.getByRole("button", { name: "Next watchlist symbol" }).tap();
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "NVDA");
    await expect(sheet).toBeVisible(); // stepping keeps it open
    await sheet.getByRole("button", { name: "Chart AMD", exact: true }).tap();
    await expect(sheet).toHaveCount(0); // charting a row shows the chart
    await expect(chartedSymbol(page)).toHaveAttribute("placeholder", "AMD");
    await page.getByRole("button", { name: "Watchlist", exact: true }).tap();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await page.getByRole("button", { name: "Watchlist", exact: true }).tap();
    await page.touchscreen.tap(195, 30);
    await expect(sheet).toHaveCount(0);
    expect((await fit(page)).pageWidth).toBeLessThanOrEqual(390);
  });
});

test.describe("phone dividers and maximize", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("a phone has no dividers, keeps S/M/L in its More menu, and maximizes and restores a chart", async ({ page }) => {
    await registerCharts(page);
    await stub(page);
    await page.goto("/charts");
    await expect(drawn(page, "Panel 5")).toHaveAttribute("data-bars", "240");
    await expect(page.getByRole("separator")).toHaveCount(0);
    await page.getByRole("button", { name: "More chart controls" }).tap();
    await expect(page.getByRole("group", { name: "More chart controls" }).getByRole("button", { name: "tall small charts" })).toBeInViewport();
    await page.keyboard.press("Escape");
    await markCharts(page);
    const before = await Promise.all(ALL_PANELS.map((id) => drawn(page, id).boundingBox()));
    await page.getByRole("button", { name: "Maximize 1h chart", exact: true }).tap();
    await expect(chartGrid(page)).toHaveAttribute("data-maximized", "2");
    await expect.poll(async () => (await drawn(page, "Panel 3").boundingBox())!.height).toBe(410);
    for (const other of ALL_PANELS.filter((id) => id !== "Panel 3")) await expect(drawn(page, other)).not.toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("phone-maximized.png") });
    await page.getByRole("button", { name: "Restore charts" }).tap();
    await expect(chartGrid(page)).not.toHaveAttribute("data-maximized");
    const after = await Promise.all(ALL_PANELS.map((id) => drawn(page, id).boundingBox()));
    expect(after.map((box) => Math.round(box!.height))).toEqual(before.map((box) => Math.round(box!.height)));
    // Full screen: the maximized chart covers the screen under the toolbar.
    await page.getByRole("button", { name: "Enter full-screen charts" }).tap();
    await page.getByRole("button", { name: "Maximize 15m chart", exact: true }).tap();
    await expect.poll(async () => (await drawn(page, "Panel 2").boundingBox())!.height).toBeGreaterThan(500);
    await expect(drawn(page, "main")).not.toBeVisible();
    await page.screenshot({ path: test.info().outputPath("phone-fullscreen-maximized.png") });
    await page.getByRole("button", { name: "Restore charts" }).tap();
    await expect(drawn(page, "main")).toBeVisible();
    expect(await sameCharts(page)).toBe(true);
  });
});

// ---- Automatic levels (C2.3): the nearest three each side, a card on hover or tap, hidden as a group ----

const ROUND = { evidence: "calculated", timeframe: null, source: null, bar_time: null, formed_at: null } as const;
const autoMember = (kind: string, label: string, value: number, extra: Partial<AutoLevel> = {}): AutoLevel => ({ kind, label, price: value,
  evidence: "calculated", timeframe: "1m", source: "tradier", bar_time: FIXTURE_START, formed_at: FIXTURE_START + 300, developing: false, ...extra });
function autoZone(members: AutoLevel[], score = members.length): AutoZone {
  const prices = members.map((member) => member.price);
  return { id: members.map((member) => `${member.kind}@${member.price}`).join("|"), low: Math.min(...prices), high: Math.max(...prices),
    label: members.map((member) => member.label).join(" + "), score, members };
}
// The fixture's last close is about 257.34: 256, the 254 zone and 252 are the nearest below; 258.50, 260 and 262 above.
const AUTO_ZONES = [
  autoZone([autoMember("round", "250", 250, ROUND)]), autoZone([autoMember("round", "252", 252, ROUND)]),
  autoZone([autoMember("prior_day_high", "PDH", 254.3, { evidence: "observed", timeframe: "1D", formed_at: Date.parse("2026-09-11T16:00:00-04:00") / 1000 }), autoMember("round", "254", 254, ROUND)]),
  autoZone([autoMember("premarket_low", "PML", 256)]), autoZone([autoMember("overnight_high", "ONH", 258.5, { source: "alpaca_sip" })]),
  autoZone([autoMember("round", "260", 260, ROUND)]), autoZone([autoMember("round", "262", 262, ROUND)]),
  autoZone([autoMember("swing_high", "Swing high", 264, { evidence: "inferred", timeframe: "1D" })]),
];
const NEAREST_IDS = AUTO_ZONES.slice(1, 7).map((zone) => zone.id).join(",");
const at = (clock: string) => Date.parse(`2026-09-14T${clock}:00-04:00`) / 1000;
const AUTO_EVENTS: Record<string, LevelInteraction> = Object.fromEntries(AUTO_ZONES.map((zone) => [zone.id, { state: "untested", events: [], at_level: false }]));
AUTO_EVENTS[AUTO_ZONES[2].id] = { state: "broken", events: [
  { event: "approached", direction: "below", time: at("09:55"), bar_time: at("09:50") },
  { event: "tested", direction: "below", time: at("10:05"), bar_time: at("10:00") },
  { event: "broken", direction: "above", time: at("11:40"), bar_time: at("11:35") },
], at_level: false, since: at("09:35"), last_close: 257.34, last_close_at: at("11:55") };

async function stubAutoLevels(page: Page, configure?: (data: ChartData) => void) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    data.auto_levels = { day: "2026-09-14", as_of: at("12:00"), session: "extended", atr: 5.5, band: 0.55, zones: AUTO_ZONES, missing: { overnight: "No minute bars for 2026-09-11.", opening_range_15m: "Forms at 09:45." } };
    for (const [interval, panel] of Object.entries(data.panels)) if (panel && interval !== "1D" && interval !== "1W") panel.level_events = AUTO_EVENTS;
    configure?.(data);
    await route.fulfill({ json: data });
  });
}
type AutoProbe = Map<string, { y(id: string): number | null }>;
const registerAutoLevels = (page: Page) => page.addInitScript(() => { (window as typeof window & { __tjAutoLevels?: Map<string, unknown> }).__tjAutoLevels = new Map(); });
const autoY = (page: Page, panel: string, id: string) => page.evaluate(([key, zone]) => (window as unknown as { __tjAutoLevels: AutoProbe }).__tjAutoLevels.get(key)!.y(zone)!, [panel, id] as const);

test("level cards stay on the chart under the pointer through linked crosshair redraws and interval changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubAutoLevels(page);
  await page.goto("/charts");
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-bars", "240");
  const main = drawn(page, "main");
  const region = page.getByRole("region", { name: "MRVL 5m chart", exact: true });
  const box = (await main.boundingBox())!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(region.getByRole("tooltip")).toBeVisible();
  // Range changes recalculate a linked crosshair after the synchronous linking guard has ended.
  await page.evaluate(() => {
    type Candles = SeriesProbe & { data(): { time: number }[] };
    type Chart = { panes(): { getSeries(): Candles[] }[]; setCrosshairPosition(price: number, time: number, series: Candles): void;
      timeScale(): { getVisibleLogicalRange(): { from: number; to: number } | null; setVisibleLogicalRange(range: { from: number; to: number }): void } };
    const charts = (window as unknown as { __tjCharts: Map<string, Chart> }).__tjCharts;
    const receiver = charts.get("Panel 2")!;
    const candles = receiver.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!;
    // The link uses this API. Put a receiver's synthetic crosshair on a zone so the bug must exhibit.
    receiver.setCrosshairPosition(258.5, candles.data().at(-1)!.time, candles);
    for (const chart of [...charts.values()].reverse()) {
      const range = chart.timeScale().getVisibleLogicalRange()!;
      chart.timeScale().setVisibleLogicalRange({ from: range.from + 0.25, to: range.to + 0.25 });
    }
  });
  await expect(region.getByRole("tooltip")).toBeVisible();
  await expect(page.getByRole("tooltip")).toHaveCount(1);
  // Leaving the plot for its price axis clears the hover even while inside the chart container.
  await page.mouse.move(box.x + box.width - 20, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(region.getByRole("tooltip")).toBeVisible();
  await page.mouse.move(1, 1);
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  // An intentional click still pins a card, but a different timeframe starts without it.
  await page.mouse.click(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(region.getByRole("tooltip").getByRole("button", { name: "Close level card" })).toBeVisible();
  await page.getByLabel("Main interval", { exact: true }).selectOption("15m");
  await expect(page.getByRole("region", { name: "MRVL 15m chart", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
});

test("redraws under a stationary pointer refresh its candle readout, linked time and level card", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubAutoLevels(page);
  await page.goto("/charts");
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-bars", "240");
  const region = page.getByRole("region", { name: "MRVL 5m chart", exact: true });
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(region.getByRole("tooltip", { name: "ONH level card" })).toBeVisible();
  const before = await page.getByLabel("main candle values").textContent();
  // Move the candles under a pointer that stays put; use the chart's new coordinate/time mapping.
  const candle = await page.evaluate(async () => {
    type Chart = import("lightweight-charts").IChartApi;
    const chart = (window as unknown as { __tjCharts: Map<string, Chart> }).__tjCharts.get("main")!;
    chart.timeScale().setVisibleLogicalRange({ from: 20, to: 70 });
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const time = chart.timeScale().coordinateToTime(300);
    const row = chart.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!.data().find((bar) => bar.time === time)!;
    if (typeof time !== "number" || !("close" in row)) throw new Error("Expected a candle under the stationary pointer");
    return { time, close: row.close };
  });
  await expect(page.getByLabel("main candle values")).toContainText(`C ${candle.close.toFixed(2)}`);
  await expect(page.getByLabel("main candle values")).not.toHaveText(before!);
  const followerBars = fixturePanels(["15m"])["15m"]!.bars;
  const follower = followerBars.find((bar) => bar.time <= candle.time && candle.time < bar.end_time) ?? followerBars.at(-1)!;
  await expect(page.getByLabel("Panel 2 candle values")).toContainText(`C ${follower.close.toFixed(2)}`);
  // The former zone is now off the price scale; no old card may stay at the pointer.
  expect(await autoY(page, "main", AUTO_ZONES[4].id)).toBeLessThan(0);
  await expect(region.getByRole("tooltip", { name: "ONH level card" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "MRVL 15m chart", exact: true }).getByRole("tooltip")).toHaveCount(0);
});

test("a pinned level card covers the RSI resize handle and chart lines", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubAutoLevels(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  // A taller RSI pane puts its separator through the card, as on the reported layout.
  await page.evaluate(async () => {
    type Chart = { panes(): { setHeight(height: number): void }[] };
    (window as unknown as { __tjCharts: Map<string, Chart> }).__tjCharts.get("main")!.panes()[1].setHeight(300);
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
  const canvas = drawn(page, "main");
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + 320, box.y + await autoY(page, "main", AUTO_ZONES[2].id));
  const card = page.getByRole("region", { name: "MRVL 5m chart", exact: true }).getByRole("tooltip");
  await expect(card.getByRole("button", { name: "Close level card" })).toBeVisible();
  // Find the actual library handle; sample the overlap so a z-index regression cannot pass.
  const overlap = await canvas.evaluate((element) => {
    const handle = [...element.querySelectorAll<HTMLElement>("*")].find((node) => node.style.zIndex === "50" && getComputedStyle(node).cursor === "row-resize")!;
    const tooltip = element.parentElement!.querySelector('[role="tooltip"]')!;
    const [line, card] = [handle.getBoundingClientRect(), tooltip.getBoundingClientRect()];
    const top = Math.max(line.top, card.top), bottom = Math.min(line.bottom, card.bottom);
    const x = card.left + 20, y = (top + bottom) / 2;
    return { height: bottom - top, covered: tooltip.contains(document.elementFromPoint(x, y)), background: getComputedStyle(tooltip).backgroundColor };
  });
  expect(overlap.height).toBeGreaterThan(0);
  expect(overlap.covered).toBe(true);
  expect(overlap.background).toBe("rgb(20, 27, 38)");
  await page.screenshot({ path: test.info().outputPath("auto-level-card-over-rsi.png") });
  await card.getByRole("button", { name: "Close level card" }).click();
  await expect(card).toHaveCount(0);
});

test("automatic levels draw the nearest three each side, a hover shows each one's card, and the group hides on every chart", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const server = await fakeChartSettings(context);
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubAutoLevels(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-auto-levels", NEAREST_IDS);
  // The main chart names each zone on a tag, its most telling member first and the rest counted; tags never
  // overlap, and the smaller charts carry none.
  const tagsOf = (panel: string) => page.evaluate((key) => (window as unknown as { __tjAutoLevels: Map<string, { tags(): { text: string; top: number; bottom: number }[] }> }).__tjAutoLevels.get(key)!.tags(), panel);
  await expect.poll(async () => (await tagsOf("main")).map((tag) => tag.text)).toEqual(expect.arrayContaining(["PDH +1", "ONH"]));
  const tags = (await tagsOf("main")).sort((a, b) => a.top - b.top);
  for (let index = 1; index < tags.length; index++) expect(tags[index].top).toBeGreaterThanOrEqual(tags[index - 1].bottom);
  expect(tags.map((tag) => tag.text).filter((text) => /^\d/.test(text))).toEqual([]); // a round number reads "Round 252", never a bare price
  expect(await tagsOf("Panel 2")).toEqual([]);

  // Hovering the 254 zone on the 5m chart reads its card: members, sources, and today's tests and breaks.
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[2].id));
  const card = page.getByRole("tooltip", { name: "PDH + 254 level card" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("254.00–254.30 · 2 landmarks");
  await expect(card.getByLabel("Interactions today")).toContainText("Closed across zone");
  await expect(card).toContainText("Approached; left below · confirmed 9:55 AM ET");
  await expect(card).toContainText("Touched; left below · confirmed 10:05 AM ET");
  await expect(card).toContainText("Closed above · confirmed 11:40 AM ET");
  await expect(card).toContainText("Today, on closed 5m bars, including extended hours. Touches enter 254.00–254.30.");
  await expect(card).toContainText("Nearby only: 253.45–254.85. Approaches are not touches.");
  await expect(card).toContainText("History since 9:35 AM ET for this confirmed combination; earlier bars are excluded.");
  await expect(card).toContainText("Last closed candle: 257.34 at 11:55 AM ET.");
  await expect(card).not.toContainText("independent sources");
  await expect(card).not.toContainText("Price is at it now");
  await expect(card).toContainText("PDH Prior day high254.30");
  await expect(card).toContainText("observed · Tradier daily bar · formed Sep 11, 2026 4:00 PM");
  await expect(card).toContainText("calculated · price rule");
  await page.screenshot({ path: test.info().outputPath("auto-level-card.png") });
  await page.mouse.move(box.x + EMPTY.x, box.y + EMPTY.y);
  await expect(card).toHaveCount(0);

  // A daily chart draws the same levels; how price met them is read on intraday charts.
  const daily = (await drawn(page, "Panel 4").boundingBox())!;
  await page.mouse.move(daily.x + 100, daily.y + await autoY(page, "Panel 4", AUTO_ZONES[4].id));
  const onDaily = page.getByRole("tooltip", { name: "ONH level card" });
  await expect(onDaily).toContainText("How price met it today is read on intraday charts.");
  await expect(onDaily).toContainText("calculated · SIP minute");
  await page.mouse.move(daily.x + 100, daily.y + 5);

  // The Layers panel lists what is missing and hides the group on all five charts, through a reload.
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  const group = layerGroup(page, "Auto levels");
  await expect(group).toContainText("Not shown for MRVL: No minute bars for 2026-09-11.");
  await expect(group).not.toContainText("Forms at");
  await group.getByRole("button", { name: "Hide Auto levels" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-auto-levels", "");
  await expect.poll(() => server.data?.autoLevelsHidden).toBe(true);
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(drawn(page, "main")).toHaveAttribute("data-auto-levels", "");
  // The chart menu's Layers shows them again.
  await rightClick(page, "main", EMPTY);
  await chartMenu(page).getByRole("menuitem", { name: /^Layers/ }).click();
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "Auto levels" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-auto-levels", NEAREST_IDS);
  await expect.poll(() => server.data?.autoLevelsHidden).toBe(false);
  expect(errors).toEqual([]);
});

test("a changing combination counts landmarks without inventing a fixed contact history", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  const combined = autoZone([AUTO_ZONES[4].members[0], autoMember("premarket_high", "PMH", 258.5, { developing: true })], 1);
  await stubAutoLevels(page, (data) => {
    data.auto_levels!.zones = AUTO_ZONES.map((zone) => zone.id === AUTO_ZONES[4].id ? combined : zone);
    for (const [interval, panel] of Object.entries(data.panels)) if (panel && interval !== "1D") {
      panel.level_events = { ...AUTO_EVENTS, [combined.id]: { state: "developing", events: [], at_level: false } };
    }
  });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(drawn(page, "main")).toHaveAttribute("data-auto-levels", new RegExp(combined.id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + 150, box.y + await autoY(page, "main", combined.id));
  const card = page.getByRole("tooltip", { name: "ONH + PMH level card" });
  await expect(card).toContainText("258.50 · 2 landmarks");
  await expect(card).toContainText("Combination still changing");
  await expect(card).toContainText("this combination has no fixed contact history");
  await expect(card).not.toContainText("History since");
  await expect(card).not.toContainText("independent");
  await page.screenshot({ path: test.info().outputPath("zone-changing-combination.png") });
});

test.describe("phone automatic levels", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("a tap opens a level's card and it stays until Close", async ({ page }) => {
    await registerCharts(page);
    await registerAutoLevels(page);
    await stubAutoLevels(page, (data) => {
      data.auto_levels!.session = "regular";
      for (const [interval, panel] of Object.entries(data.panels)) if (panel && interval !== "1D") {
        panel.level_events = { ...AUTO_EVENTS, [AUTO_ZONES[4].id]: { state: "touched", events: [], at_level: true,
          near_level: true, since: at("09:35"), last_close: 258.50, last_close_at: at("11:55") } };
      }
    });
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await drawn(page, "main").scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await drawn(page, "main").boundingBox())!;
    await page.touchscreen.tap(Math.round(box.x + 150), Math.round(box.y + await autoY(page, "main", AUTO_ZONES[4].id) + 8));
    const card = page.getByRole("tooltip", { name: "ONH level card" });
    await expect(card).toBeVisible();
    await expect(card.getByLabel("Interactions today")).toContainText("Contact observed");
    await expect(card).toContainText("Last closed candle touched");
    await expect(card).toContainText("Last closed candle: 258.50 at 11:55 AM ET.");
    await expect(card).toContainText("regular hours. Touches enter 258.50.");
    await expect(card).not.toContainText("Price is at it now");
    const close = card.getByRole("button", { name: "Close level card" });
    expect((await close.boundingBox())!.height).toBeGreaterThanOrEqual(24);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("auto-level-card-phone.png") });
    await close.tap();
    await expect(card).toHaveCount(0);
  });
});

test("a card kept open by a click gives way to hovering once its level is no longer drawn", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  // NVDA's levels lack the ONH zone that MRVL's card is kept open on.
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    const zones = data.symbol === "NVDA" ? AUTO_ZONES.filter((zone) => zone !== AUTO_ZONES[4]) : AUTO_ZONES;
    data.auto_levels = { day: "2026-09-14", as_of: at("12:00"), atr: 5.5, band: 0.55, zones, missing: {} };
    await route.fulfill({ json: data });
  });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.click(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[4].id));
  await expect(page.getByRole("tooltip", { name: "ONH level card" })).toBeVisible();
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(page.getByRole("region", { name: /^NVDA 5m chart/ })).toHaveCount(1);
  await expect(drawn(page, "main")).toHaveAttribute("data-auto-levels", /swing_high/);
  await expect(page.getByRole("tooltip", { name: "ONH level card" })).toHaveCount(0);
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", AUTO_ZONES[5].id));
  await expect(page.getByRole("tooltip", { name: "260 level card" })).toBeVisible();
});

// ---- Relative volume (C2.4): today's candles shaded by RVol, the legend's value and what the baseline covers ----

// 20 sessions before 2026-09-17, across Labor Day.
const RVOL_SESSIONS = ["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31", "2026-09-01",
  "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16"];
const READY: RvolBaseline = { state: "ready", day: "2026-09-17", sessions: RVOL_SESSIONS, traded: 20, missing: [], message: null };
const BUILDING: RvolBaseline = { state: "building", day: "2026-09-17", sessions: RVOL_SESSIONS, traded: 0, missing: ["2026-09-15", "2026-09-16"],
  message: "RVol needs the 20 sessions before today; 2 not stored yet. Watchlist names are stored each morning before the open, and any symbol's sessions as its older candles load." };
// The 5m fixture's last six candles (2026-09-17, 09:30-09:55) are today's.
const TODAY_RVOL = [0.3, 1, 2.6, 2, null, 1.2];

async function stubRvol(page: Page, baseline: RvolBaseline) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    data.rvol = baseline;
    for (const [interval, panel] of Object.entries(data.panels) as [Interval, NonNullable<ChartData["panels"][Interval]>][]) {
      if (interval === "5m") panel.bars = panel.bars.map((bar, i) => i < 234 ? bar : { ...bar, rvol: baseline.state === "ready" ? TODAY_RVOL[i - 234] : null });
      // The 1m fixture is one session from 09:30: its 228th candle, 13:17, is in view.
      if (interval === "1m") panel.bars = panel.bars.map((bar, i) => ({ ...bar, rvol: baseline.state === "ready" ? (i === 227 ? 2.6 : 1.1) : null }));
    }
    await route.fulfill({ json: data });
  });
}
type VolumeProbe = Map<string, { panes(): { getSeries(): { options(): { priceScaleId?: string }; data(): readonly { color?: string }[] }[] }[] }>;
const volumeColors = (page: Page, id: string, count: number) => page.evaluate(([key, last]) => {
  const chart = (window as unknown as { __tjCharts: VolumeProbe }).__tjCharts.get(key as string)!;
  const series = chart.panes()[0].getSeries().find((item) => item.options().priceScaleId === "volume")!;
  return series.data().slice(-(last as number)).map((point) => point.color);
}, [id, count] as const);
const candleX = (page: Page, id: string, time: number) => page.evaluate(([key, at]) =>
  (window as unknown as { __tjCharts: Map<string, { timeScale(): { timeToCoordinate(t: number): number | null } }> }).__tjCharts.get(key as string)!.timeScale().timeToCoordinate(at as number)!, [id, time] as const);

test("relative volume shades today's volume bars and the legend reads each candle's RVol and the sessions it is measured against", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await stubRvol(page, READY);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");

  // The main chart names the baseline's sessions, and its latest candle's RVol.
  const studies = page.getByLabel("main study values");
  await expect(studies.getByRole("note", { name: "Relative volume baseline" })).toHaveText("RVol vs 20 sessions Aug 19 – Sep 16");
  await expect(studies).toContainText("RVol 1.2× for 9:55 AM");
  // Brighter with RVol, faint below 0.5×; a candle without RVol, and every earlier session's, keeps the plain shade.
  expect(await volumeColors(page, "main", 8)).toEqual(["#2bc9a43d", "#2bc9a43d", "#2bc9a41f", "#2bc9a43d", "#2bc9a4d9", "#2bc9a480", "#2bc9a43d", "#2bc9a43d"]);

  // Hovering a candle reads its own RVol.
  const box = (await drawn(page, "main").boundingBox())!;
  const nineForty = FIXTURE_START + 3 * 86400 + 2 * 300;
  await page.mouse.move(box.x + await candleX(page, "main", nineForty), box.y + box.height * 0.4);
  await expect(studies).toContainText("RVol 2.6× for 9:40 AM");
  await page.mouse.move(box.x + await candleX(page, "main", nineForty + 600), box.y + box.height * 0.4);
  await expect(studies.getByText("RVol —")).toHaveAttribute("title", "Fewer than five of the baseline sessions had traded by this minute.");
  await page.mouse.move(1, 1);

  // A smaller chart's row is tight beside its countdown: RVol takes the volume's place, with the volume, candle and sessions on hover.
  const minute = values(page, "Panel 5");
  await expect(minute).toContainText("RVol 1.1×");
  await expect(minute).not.toContainText("Vol 64");
  const row = (await minute.boundingBox())!;
  const shown = (await minute.getByText("RVol 1.1×").boundingBox())!;
  expect(shown.x + shown.width).toBeLessThanOrEqual(row.x + row.width);
  await expect(values(page, "Panel 2")).toContainText(/Vol [\d.]+K/); // no RVol on these 15m candles
  const small = (await drawn(page, "Panel 5").boundingBox())!;
  await page.mouse.move(small.x + await candleX(page, "Panel 5", FIXTURE_START + 227 * 60), small.y + small.height * 0.4);
  await expect(minute.getByText("RVol 2.6×")).toHaveAttribute("title", /^Vol [\d.]+K\. RVol 2\.6× for 1:17\sPM\. RVol vs 20 sessions Aug 19 – Sep 16: /);
  await expect(values(page, "Panel 4")).not.toContainText("RVol");
  await page.screenshot({ path: test.info().outputPath("rvol-desktop.png") });
});

test("without a baseline the chart says so and shades nothing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await stubRvol(page, BUILDING);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  const note = page.getByRole("note", { name: "Relative volume baseline" });
  await expect(note).toHaveText("RVol baseline not built yet");
  await expect(note).toHaveAttribute("title", BUILDING.message!);
  await expect(page.getByLabel("main study values").getByText("RVol —")).toHaveAttribute("title", BUILDING.message!);
  expect(new Set(await volumeColors(page, "main", 240))).toEqual(new Set(["#2bc9a43d"]));
});

test.describe("phone relative volume", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the main chart's RVol and its sessions wrap into view on a phone", async ({ page }) => {
    await registerCharts(page);
    await stubRvol(page, READY);
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    const studies = page.getByLabel("main study values");
    for (const text of [/^RVol 1\.2× for 9:55\sAM$/, /^RVol vs 20 sessions Aug 19 – Sep 16$/]) {
      const shown = (await studies.getByText(text).boundingBox())!;
      expect(shown.x).toBeGreaterThanOrEqual(0);
      expect(shown.x + shown.width).toBeLessThanOrEqual(390);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("rvol-phone.png") });
  });
});

// ---- Earnings (C2.5): markers on report dates and the header badge, from the workspace's cached calendar ----

const EARNINGS: Earnings = { state: "ready", source: "Tradier corporate calendar", fetched_at: FIXTURE_START, message: null,
  next: { date: "2026-10-28", status: "confirmed", label: "Q3 FY2026" },
  reports: [{ date: "2026-09-15", label: "Q2 FY2026" }, { date: "2026-06-01", label: "Q1 FY2026" }] };

async function stubEarnings(page: Page, bySymbol: Record<string, Earnings>) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    data.earnings = bySymbol[data.symbol] ?? null;
    for (const [name, other] of Object.entries(data.extras ?? {})) other.earnings = bySymbol[name] ?? null;
    await route.fulfill({ json: data });
  });
}

test("earnings dates mark the candles that hold them, intraday and daily, and an unknown date marks nothing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await stubEarnings(page, { MRVL: EARNINGS, NVDA: { ...EARNINGS, next: null, reports: [] }, SPY: { ...EARNINGS, state: "none", next: null, reports: [] } });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  // Intraday, the date's first candle (09:30 New York): the report's time of day is unknown.
  const sept15 = FIXTURE_START + 86400;
  await expect(drawn(page, "main")).toHaveAttribute("data-earnings", `2026-09-15@${sept15}`);
  await expect(drawn(page, "Panel 2")).toHaveAttribute("data-earnings", `2026-09-15@${sept15}`);
  // The synthetic daily candles run on past the next report, so it is marked as well; June 1 is before them.
  await expect(drawn(page, "Panel 4")).toHaveAttribute("data-earnings", `2026-09-15@${sept15},2026-10-28@${FIXTURE_START + 44 * 86400}`);
  // The 1m candles are one session, Sept 14: no report that day.
  await expect(drawn(page, "Panel 5")).toHaveAttribute("data-earnings", "");
  // Scrolled back to Sept 15 (the 79th 5m candle) for the screenshot.
  await page.evaluate(() => (window as unknown as { __tjCharts: Registry }).__tjCharts.get("main")!.timeScale().setVisibleLogicalRange({ from: 50, to: 110 }));
  await page.screenshot({ path: test.info().outputPath("earnings-markers.png") });
  for (const symbol of ["NVDA", "SPY"]) {
    await page.getByRole("button", { name: `Chart ${symbol}`, exact: true }).click();
    await expect(page.getByRole("region", { name: new RegExp(`^${symbol} 5m chart`) })).toHaveCount(1);
    await expect(drawn(page, "main")).toHaveAttribute("data-earnings", "");
    await expect(drawn(page, "Panel 4")).toHaveAttribute("data-earnings", "");
  }
  await expect(page.getByRole("note", { name: /^Earnings/ })).toHaveCount(0);
});

test("the earnings badge appears 14 days out, counts New York days and disappears after the report", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fakeChartSettings(context, { revision: 1, data: { symbol: "MRVL", panelSymbols: [null, "NVDA", null, null, null] } });
  await stubEarnings(page, { MRVL: EARNINGS, NVDA: { ...EARNINGS, next: { date: "2026-10-23", status: "estimated", label: "Q3 FY2027" } } });
  await page.clock.install({ time: new Date("2026-10-13T16:00:00Z") });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  const main = page.getByRole("region", { name: /^MRVL 5m chart/ });
  const held = page.getByRole("region", { name: /^NVDA 15m chart/ });
  // Fifteen days before MRVL's report: no badge. NVDA, held by a smaller chart, is ten days out.
  await expect(main.getByRole("note", { name: /^Earnings/ })).toHaveCount(0);
  const estimate = held.getByRole("note", { name: "Earnings in 10 d · est.", exact: true });
  await expect(estimate).toHaveText("E 10 d?");
  await expect(estimate).toHaveAttribute("title", "Q3 FY2027 earnings Fri, Oct 23, 2026: Tradier's estimate; the company has not confirmed it. Time of day not published. Tradier corporate calendar.");
  await page.clock.setSystemTime(new Date("2026-10-14T16:00:00Z"));
  const badge = main.getByRole("note", { name: "Earnings in 14 d", exact: true });
  await expect(badge).toBeVisible();
  await expect(badge).toHaveAttribute("title", "Q3 FY2026 earnings Wed, Oct 28, 2026: confirmed. Time of day not published. Tradier corporate calendar.");
  await page.screenshot({ path: test.info().outputPath("earnings-badge.png") });
  // 23:30 on the 27th in New York is still the day before, though UTC has turned.
  await page.clock.setSystemTime(new Date("2026-10-28T03:30:00Z"));
  await expect(main.getByRole("note", { name: "Earnings tomorrow", exact: true })).toBeVisible();
  await page.clock.setSystemTime(new Date("2026-10-28T16:00:00Z"));
  await expect(main.getByRole("note", { name: "Earnings today", exact: true })).toBeVisible();
  await page.clock.setSystemTime(new Date("2026-10-29T04:30:00Z"));
  await expect(page.getByRole("note", { name: /^Earnings/ })).toHaveCount(0);
});

test.describe("phone earnings badge", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the main chart's badge takes its short form and stays inside the header", async ({ page }) => {
    await stubEarnings(page, { MRVL: EARNINGS });
    await page.clock.install({ time: new Date("2026-10-23T16:00:00Z") });
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    const badge = page.getByRole("note", { name: "Earnings in 5 d", exact: true });
    await expect(badge).toBeVisible();
    await expect(badge.getByText("E 5 d", { exact: true })).toBeVisible();
    const shown = (await badge.boundingBox())!;
    expect(shown.x + shown.width).toBeLessThanOrEqual(390);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("earnings-badge-phone.png") });
  });
});

// ---- Level alerts (C5.1): made from the chart menu, a bell at each price, listed with what reached the phone ----

type AlertsServer = { payload: AlertsPayload; posts: Record<string, unknown>[]; rearms: Record<string, unknown>[]; deletes: string[] };
/** The alert routes as the backend answers them; the backend tests judge and deliver. */
async function stubAlerts(page: Page, phone = true): Promise<AlertsServer> {
  const server: AlertsServer = { payload: { alerts: [], phone }, posts: [], rearms: [], deletes: [] };
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const data = fixture(route.request().url());
    data.auto_levels = { day: "2026-09-14", as_of: at("12:00"), atr: 5.5, band: 0.55, zones: AUTO_ZONES, missing: {} };
    data.alerts = server.payload;
    await route.fulfill({ json: data });
  });
  await page.route("**/api/backend/charts/alerts**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const replace = (id: string, change: Partial<LevelAlert>) => server.payload.alerts.map((alert) => alert.id === id ? { ...alert, ...change } : alert);
    if (request.method() === "DELETE") {
      const id = path.split("/").at(-1)!;
      server.deletes.push(id);
      server.payload = { ...server.payload, alerts: server.payload.alerts.filter((alert) => alert.id !== id) };
    } else if (path.endsWith("/rearm")) {
      const body = request.postDataJSON();
      server.rearms.push(body);
      server.payload = { ...server.payload, alerts: replace(path.split("/").at(-2)!, { state: "active", event: null, price: body.price, direction: body.reference < body.price ? "up" : "down" }) };
    } else {
      const body = request.postDataJSON();
      server.posts.push(body);
      server.payload = { ...server.payload, alerts: [{ id: `alert-${server.posts.length}`, symbol: body.symbol, price: body.price, created_on: "2026-09-17",
        condition: body.condition, interval: body.interval, session: body.session, direction: body.reference < body.price ? "up" : "down",
        source_kind: body.source_kind, source_id: body.source_id, label: body.label, state: "active", armed_at: at("12:00"), event: null }, ...server.payload.alerts] };
    }
    await route.fulfill({ json: server.payload });
  });
  return server;
}
const alertsPanel = (page: Page) => page.getByRole("region", { name: "Price alerts" });

test("a level's menu sets an alert, its bell turns gray once it fires, and the list re-arms and removes it", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fakeChartSettings(context);
  await registerCharts(page);
  const server = await stubAlerts(page);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await expect(alertsPanel(page)).toContainText("Right-click (long-press on a phone) a level");
  await addLevel(page, "Breakout", "256.00");
  const onLevel = async () => ({ x: 220, y: await levelY(page, "main", 256) });

  await rightClick(page, "main", await onLevel());
  const menu = itemMenu(page, "Level");
  await expect(menu.getByRole("menu", { name: "Level alerts" })).toContainText("Alerts at 256.00");
  await page.screenshot({ path: test.info().outputPath("alert-level-menu.png") });
  await menu.getByRole("menuitem", { name: "Alert when price crosses" }).click();
  await expect(menu).toHaveCount(0);
  // Price is above the level, so the alert waits for a cross below; the server is told which side from the chart's latest price.
  await expect.poll(() => server.posts.length).toBe(1);
  expect(server.posts[0]).toMatchObject({ symbol: "MRVL", price: 256, condition: "crosses", interval: null, session: "extended", source_kind: "level", label: "Breakout" });
  expect(server.posts[0].reference as number).toBeGreaterThan(256);
  await expect(page.getByRole("status", { name: "Chart notice" })).toHaveText("Alert set: MRVL Crosses below 256.00");
  // A bell on every chart of the symbol, and the list.
  await expect(drawn(page, "main")).toHaveAttribute("data-alerts", "256.00:active");
  await expect(drawn(page, "Panel 2")).toHaveAttribute("data-alerts", "256.00:active");
  await expect(alertsPanel(page).getByRole("listitem", { name: "MRVL Crosses below 256.00, active" })).toBeVisible();
  await expect(alertsPanel(page)).toContainText("1/20 active");
  await expect(alertsPanel(page)).toContainText("Breakout · extended hours");
  // The level's menu lists the alert on it.
  await rightClick(page, "main", await onLevel());
  await expect(itemMenu(page, "Level").getByRole("menuitem", { name: "Remove Crosses below 256.00" })).toBeVisible();
  await page.keyboard.press("Escape");

  // The server judged a trade through the level and the phone has it.
  server.payload = { ...server.payload, alerts: server.payload.alerts.map((alert) => ({ ...alert, state: "fired", event: {
    level: 256, price: 255.98, source: "stream", event_at: at("12:01"), detected_at: at("12:01"), delivery: "sent", attempts: 1, delivered_at: at("12:01"), error: null } })) };
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-alerts", "256.00:fired");
  const fired = alertsPanel(page).getByRole("listitem", { name: "MRVL Crosses below 256.00, fired" });
  await expect(fired).toContainText("Fired Sep 14, 2026 12:01 PM ET at 255.98 · Sent to phone 12:01 PM ET");
  await page.screenshot({ path: test.info().outputPath("alert-fired.png") });
  await fired.getByRole("button", { name: "Re-arm MRVL Crosses below 256.00" }).click();
  await expect.poll(() => server.rearms.length).toBe(1);
  expect(server.rearms[0]).toMatchObject({ price: 256 });
  await expect(drawn(page, "main")).toHaveAttribute("data-alerts", "256.00:active");
  await alertsPanel(page).getByRole("button", { name: "Remove MRVL Crosses below 256.00" }).click();
  await expect.poll(() => server.deletes).toEqual(["alert-1"]);
  await expect(drawn(page, "main")).toHaveAttribute("data-alerts", "");
  await expect(alertsPanel(page)).toContainText("0/20 active");
});

test("an automatic level's menu sets a close-beyond alert on that chart's interval, at the zone's edge nearest the price", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerCharts(page);
  await registerAutoLevels(page);
  const server = await stubAlerts(page, false);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  // PDH 254.30 and the round 254: price is above the zone, so its top edge.
  const zone = AUTO_ZONES[2];
  await rightClick(page, "main", { x: 300, y: await autoY(page, "main", zone.id) });
  const menu = itemMenu(page, "Auto level");
  await expect(menu).toContainText("PDH + 254");
  await expect(menu).toContainText("Alerts at 254.30");
  await expect(menu).toContainText("Phone alerts are not set up on this server");
  await menu.getByRole("menuitem", { name: "Alert on a 5m close beyond" }).click();
  await expect.poll(() => server.posts.length).toBe(1);
  expect(server.posts[0]).toMatchObject({ symbol: "MRVL", price: 254.3, condition: "closes_beyond", interval: "5m", source_kind: "auto", source_id: zone.id, label: "PDH + 254" });
  await expect(alertsPanel(page)).toContainText("Phone alerts are not set up on this server");
  await expect(drawn(page, "main")).toHaveAttribute("data-alerts", "254.30:active");
  // A 15m chart offers its own candle.
  await rightClick(page, "Panel 2", { x: 120, y: await autoY(page, "Panel 2", zone.id) });
  await expect(itemMenu(page, "Auto level").getByRole("menuitem", { name: "Alert on a 15m close beyond" })).toBeVisible();
  await expect(itemMenu(page, "Auto level").getByRole("menuitem", { name: "Remove 5m close below 254.30" })).toBeVisible();
});

test.describe("phone alerts list", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the list sits in the watchlist sheet with full-size buttons and no sideways scroll", async ({ page }) => {
    const server = await stubAlerts(page);
    server.payload = { phone: true, alerts: [{ id: "alert-9", symbol: "SPY", price: 581.2, created_on: "2026-09-17", condition: "touches", interval: null, session: "regular",
      direction: "up", source_kind: "auto", source_id: "z", label: "PDH + 581", state: "fired", armed_at: at("09:40"), event: {
        level: 581.2, price: 581.2, source: "minute_bars", event_at: at("10:03"), detected_at: at("10:12"), delivery: "pending", attempts: 2, delivered_at: null, error: "ntfy could not be reached (ConnectError)." } }] };
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    await page.getByRole("button", { name: "Watchlist", exact: true }).click();
    const item = alertsPanel(page).getByRole("listitem", { name: "SPY Touches 581.20, fired" });
    await item.scrollIntoViewIfNeeded();
    await expect(item).toContainText("at 581.20 (1-minute bar) · Retrying phone message (2 tries)");
    for (const button of await item.getByRole("button").all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("alerts-phone.png") });
  });
});

// ---- Options levels (C4.4) and the strike ladder (C4.5): stubbed chains; the backend tests compute and merge them ----

// The fixture's last close is about 257.34. The backend merges strikes into the automatic levels' zones; this fixture
// does the same within the 0.55 band, so a strike at 254.40 joins the PDH zone and one at 260 the round 260.
const OPTION_READ = Date.parse("2026-10-05T14:31:00Z") / 1000;
const optionMember = (kind: string, label: string, value: number, evidence: AutoLevel["evidence"] = "calculated", developing = false): AutoLevel => ({
  kind, label, price: value, evidence, timeframe: null, source: "tradier", bar_time: null, formed_at: null, developing });
function optionMembers(mode: string, signed: boolean): AutoLevel[] {
  if (mode === "volume") return [optionMember("call_volume_wall", "Call vol wall", 257.5, "calculated", true), optionMember("put_volume_wall", "Put vol wall", 255, "calculated", true),
    optionMember("options_volume", "Vol #3", 260, "calculated", true), optionMember("options_volume", "Vol #4", 252.5, "calculated", true)];
  const walls = [optionMember("call_wall", "Call wall", 265), optionMember("put_wall", "Put wall", 250)];
  if (mode === "gamma") return [...walls, optionMember("options_gamma", "Gamma #1", 257.5, signed ? "assumed" : "calculated", true),
    optionMember("options_gamma", "Gamma #2", 255, signed ? "assumed" : "calculated", true), ...(signed ? [optionMember("gamma_flip", "Gamma flip", 256.2, "assumed", true)] : [])];
  return [...walls, ...([[254.4, 3], [257.5, 4], [260, 5], [255, 6], [263, 7], [247.5, 8], [270, 9]] as const).map(([value, rank]) => optionMember("options_oi", `OI #${rank}`, value))];
}
function mergeZones(base: AutoZone[], members: AutoLevel[]): AutoZone[] {
  const zones = base.map((zone) => [...zone.members]);
  for (const member of members) {
    const into = zones.find((group) => group.some((other) => Math.abs(other.price - member.price) < 0.55));
    if (into) into.push(member); else zones.push([member]);
  }
  return zones.map((group) => autoZone([...group].sort((a, b) => b.price - a.price), new Set(group.map((m) => `${m.kind}@${m.price}`)).size)).sort((a, b) => a.low - b.low);
}
const optionRow = (strike: number, rank: number | null): OptionStrike => ({ strike, call_oi: 1200 + strike, put_oi: 900 + strike, call_volume: 340, put_volume: 120,
  call_gamma: 2_400_000, put_gamma: 1_100_000, gamma: 3_500_000, rank, call_oi_rank: rank, put_oi_rank: null, call_volume_rank: null, put_volume_rank: null,
  oi_change: { session: "2026-10-02", previous_session: "2026-10-01", status: "ready", calls: 125, puts: -45 } });
function optionInfo(mode: string, scope: string, signed: boolean, members: AutoLevel[]): OptionsInfo {
  return { state: "ready", message: null, symbol: "MRVL", root: "MRVL", scope: scope as OptionsInfo["scope"], source: "Tradier option chains", spot: 257.34,
    expirations: ["2026-10-09"], scope_note: scope === "nearest" ? "Next expiration Fri Oct 9 (no 0DTE today)" : "Week of Oct 5: 1 expiration",
    mode: mode as OptionsInfo["mode"], signed, fetched_at: OPTION_READ, last_trade_at: OPTION_READ - 30, greeks_updated_at: "2026-10-05 14:00:05",
    excluded: {}, missing: {}, totals: { call_oi: 52000, put_oi: 61000, call_volume: 9000, put_volume: 7000, put_call_oi: 1.17, put_call_volume: 0.78, call_volume_oi: 0.17, put_volume_oi: 0.11 },
    strikes: members.filter((m) => m.kind !== "gamma_flip").map((m) => optionRow(m.price, Number(/#(\d)/.exec(m.label)?.[1] ?? 1))),
    flip: signed ? { price: 256.2, low: 244.47, high: 270.21, note: "Model estimate: Dealers long calls and short puts: call gamma counts positive, put gamma negative.", assumption: "Dealers long calls and short puts: call gamma counts positive, put gamma negative." } : null };
}
async function stubOptions(page: Page, requests: string[]) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const url = route.request().url();
    requests.push(url);
    const query = new URL(url).searchParams;
    const data = fixture(url);
    const layer = query.get("options");
    const auto = query.get("auto") !== "0";
    const [mode, scope, signed] = (layer ?? "oi.week.0").split(".");
    const members = layer ? optionMembers(mode, signed === "1") : [];
    data.auto_levels = { day: "2026-09-14", as_of: at("12:00"), atr: 5.5, band: 0.55, missing: {}, auto,
      zones: mergeZones(auto ? AUTO_ZONES : [], members), ...(layer ? { options: optionInfo(mode, scope, signed === "1", members) } : {}) };
    await route.fulfill({ json: data });
  });
}
const OI_LEVELS = "250 + Put wall,OI #3 + PDH + 254,OI #6,OI #4,260 + OI #5,OI #7,Call wall";

test("options levels draw the walls and the nearest strikes, follow every filter, merge with automatic levels and explain themselves", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const server = await fakeChartSettings(context);
  const requests: string[] = [];
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubOptions(page, requests);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  // Off until asked for: the workspace asks for no options at all.
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", "");
  expect(requests.every((url) => !new URL(url).searchParams.has("options"))).toBe(true);

  await page.getByRole("button", { name: "Layers", exact: true }).click();
  const group = layerGroup(page, "Options levels");
  await group.getByRole("button", { name: "Show Options levels" }).click();
  await expect.poll(() => requests.at(-1)).toContain("options=oi.week.0");
  // The walls always, and the three nearest option zones on each side; the 247.50 and 270 strikes are further out.
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-option-levels", OI_LEVELS);
  await expect(group).toContainText("MRVL: Week of Oct 5: 1 expiration.");
  await expect.poll(() => (server.data?.optionsLayer as { hidden?: boolean } | undefined)?.hidden).toBe(false);

  // The nearest count is drawn from what is loaded: no request. One each side drops the 263 strike; the
  // zones a strike shares with PDH and with 260 still draw among the nearest automatic levels.
  const asked = requests.length;
  await group.getByLabel("Strikes each side").selectOption("1");
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", "250 + Put wall,OI #3 + PDH + 254,OI #6,OI #4,260 + OI #5,Call wall");
  expect(requests.length).toBe(asked);
  await group.getByLabel("Strikes each side").selectOption("3");

  // Hovering the zone a strike shares with the prior day's high: both members, the strike's numbers, and how old they are.
  const box = (await drawn(page, "main").boundingBox())!;
  const pdh = (await page.evaluate(() => (window as unknown as { __tjAutoLevels: Map<string, { shown(): string[] }> }).__tjAutoLevels.get("main")!.shown()))
    .find((id) => id.includes("options_oi@254.4"))!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", pdh));
  const card = page.getByRole("tooltip", { name: "OI #3 + PDH + 254 level card" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("OI #3 Open interest, ranked254.40");
  await expect(card).toContainText("calculated · Tradier option chains");
  const numbers = card.getByLabel("Strike 254.40");
  await expect(numbers).toContainText("OI 1.5K (#3) · Vol 340");
  await expect(numbers).toContainText("#3 by open interest · -1.14% from 257.34");
  await expect(numbers).toContainText("Δ OI calls +125 · puts −45 · Oct 1, 2026 → Oct 2, 2026");
  await expect(numbers).toContainText("$3.5M per 1% (calculated)");
  await expect(card).toContainText("open interest is OCC's overnight figure for the prior close");
  await expect(card).toContainText("PDH Prior day high254.30");
  await page.screenshot({ path: test.info().outputPath("options-level-card.png") });
  await page.mouse.move(box.x + EMPTY.x, box.y + EMPTY.y);

  // Volume mode asks for volume walls; 0DTE / nearest narrows the expirations.
  await group.getByRole("button", { name: "Volume", exact: true }).click();
  await expect.poll(() => requests.at(-1)).toContain("options=volume.week.0");
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", /Call vol wall/);
  await group.getByRole("button", { name: "0DTE / nearest" }).click();
  await expect.poll(() => requests.at(-1)).toContain("options=volume.nearest.0");
  await expect(group).toContainText("MRVL: Next expiration Fri Oct 9 (no 0DTE today).");
  // A sign is only for gamma; signed gamma adds the flip, labelled assumed.
  await expect(group.getByLabel("Signed gamma and flip (assumed)")).toBeDisabled();
  await group.getByRole("button", { name: "Gamma", exact: true }).click();
  await group.getByLabel("Signed gamma and flip (assumed)").check();
  await expect.poll(() => requests.at(-1)).toContain("options=gamma.nearest.1");
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", /Gamma flip \+ PML/);
  const flip = (await page.evaluate(() => (window as unknown as { __tjAutoLevels: Map<string, { shown(): string[] }> }).__tjAutoLevels.get("main")!.shown()))
    .find((id) => id.includes("gamma_flip"))!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", flip));
  const flipCard = page.getByRole("tooltip", { name: "Gamma flip + PML level card" });
  await expect(flipCard).toContainText("assumed · Tradier option chains · moves during the session");
  await expect(flipCard).toContainText("Model estimate: Dealers long calls and short puts");
  await page.mouse.move(box.x + EMPTY.x, box.y + EMPTY.y);

  // Hiding the automatic levels with options on asks for the strikes alone.
  await layerGroup(page, "Auto levels").getByRole("button", { name: "Hide Auto levels" }).click();
  await expect.poll(() => requests.at(-1)).toContain("auto=0");
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", "Put wall,Gamma #2,Gamma flip,Gamma #1,Call wall");
  await expect.poll(() => server.data?.optionsLayer).toEqual({ hidden: false, mode: "gamma", scope: "nearest", nearest: 3, signed: true });

  // Through a reload, then off again from the chart menu's Layers.
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-option-levels", "Put wall,Gamma #2,Gamma flip,Gamma #1,Call wall");
  await rightClick(page, "main", EMPTY);
  await chartMenu(page).getByRole("menuitem", { name: /^Layers/ }).click();
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "Options levels" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-option-levels", "");
  await expect.poll(() => (server.data?.optionsLayer as { hidden?: boolean } | undefined)?.hidden).toBe(true);
  expect(errors).toEqual([]);
});

// ---- Range bands (C2.7) and max pain (C4.7): stubbed bands; the backend tests capture and merge them ----

const CAPTURED = Date.parse("2026-10-05T09:35:00-04:00") / 1000;
const RANGES: RangesInfo = { state: "ready", message: null, symbol: "MRVL", root: "MRVL", source: "Tradier option chains", day: "2026-10-05", bands: [
  { expiration: "2026-10-05", tags: ["nearest"], today: true, anchor: 257.34, move: 2.1, percent: 2.1 / 257.34, strike: 257.5, iv: 0.31, quoted_at: CAPTURED - 5, captured_at: CAPTURED },
  { expiration: "2026-10-09", tags: ["friday"], today: false, anchor: 257.34, move: 4.6, percent: 4.6 / 257.34, strike: 257.5, iv: 0.29, quoted_at: CAPTURED - 5, captured_at: CAPTURED },
] };
const rangeMember = (kind: string, label: string, value: number): AutoLevel => ({
  kind, label, price: value, evidence: "calculated", timeframe: null, source: "tradier", bar_time: null, formed_at: CAPTURED, developing: false });
const RANGE_MEMBERS = [rangeMember("expected_move_high", "EM 0DTE high", 259.44), rangeMember("expected_move_low", "EM 0DTE low", 255.24),
  rangeMember("expected_move_high", "EM Fri high", 261.94), rangeMember("expected_move_low", "EM Fri low", 252.74)];
const MAX_PAIN = optionMember("max_pain", "Max pain", 248.5, "inferred");
async function stubRanges(page: Page, requests: string[], bands: RangesInfo = RANGES, members: AutoLevel[] = RANGE_MEMBERS) {
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const url = route.request().url();
    requests.push(url);
    const query = new URL(url).searchParams;
    const data = fixture(url);
    // Intraday candles carry VWAP's standard deviation; daily ones have no VWAP.
    for (const panel of Object.values(data.panels)) for (const bar of panel?.bars ?? []) bar.vwap_sd = bar.vwap === null ? null : 0.6;
    const layer = query.get("options");
    const ranges = query.get("ranges") === "1";
    const auto = query.get("auto") !== "0";
    const options = layer ? [...optionMembers("oi", false), MAX_PAIN] : [];
    data.auto_levels = { day: "2026-10-05", as_of: CAPTURED + 600, atr: 5.5, band: 0.55, missing: {}, auto,
      zones: mergeZones(auto ? AUTO_ZONES : [], [...options, ...(ranges ? members : [])]),
      ...(layer ? { options: { ...optionInfo("oi", "week", false, options), max_pain: { price: 248.5, expiration: "2026-10-09",
        note: "The strike where this expiration's open contracts would pay their holders least at expiry. Arithmetic on open interest; that price drifts to it is folklore, so treat it as a reference, not a target." } } } : {}),
      ...(ranges ? { ranges: bands } : {}) };
    await route.fulfill({ json: data });
  });
}
const RANGE_LEVELS = "EM Fri low,EM 0DTE low,EM 0DTE high,262 + EM Fri high";

test("range bands draw today's and Friday's expected move and VWAP ±1σ/±2σ, explain themselves, and hide from the menu", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const server = await fakeChartSettings(context);
  const requests: string[] = [];
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubRanges(page, requests);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  // Off until asked for: no bands drawn and none asked for.
  await expect(drawn(page, "main")).toHaveAttribute("data-range-levels", "");
  await expect(drawn(page, "main")).toHaveAttribute("data-vwap-bands-shown", "false");
  expect(requests.every((url) => !new URL(url).searchParams.has("ranges"))).toBe(true);

  await page.getByRole("button", { name: "Layers", exact: true }).click();
  const group = layerGroup(page, "Range bands");
  await group.getByRole("button", { name: "Show Range bands" }).click();
  await expect.poll(() => requests.at(-1)).toContain("ranges=1");
  // Every expected-move level draws on every chart, however far; Friday's high shares the round 262's zone.
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-range-levels", RANGE_LEVELS);
  await expect(group).toContainText("MRVL: 0DTE ±2.10, Fri ±4.60.");
  // VWAP bands on the intraday charts' every candle; the daily chart has no VWAP to band.
  await expect(drawn(page, "main")).toHaveAttribute("data-vwap-bands-shown", "true");
  await expect(drawn(page, "main")).toHaveAttribute("data-vwap-bands", "240");
  await expect(drawn(page, "Panel 4")).toHaveAttribute("data-vwap-bands", "0");
  await expect.poll(() => server.data?.rangeBandsHidden).toBe(false);

  const box = (await drawn(page, "main").boundingBox())!;
  const high = (await page.evaluate(() => (window as unknown as { __tjAutoLevels: Map<string, { shown(): string[] }> }).__tjAutoLevels.get("main")!.shown()))
    .find((id) => id === "expected_move_high@259.44")!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", high));
  const card = page.getByRole("tooltip", { name: "EM 0DTE high level card" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("EM 0DTE high Expected move, upper259.44");
  await expect(card).toContainText("calculated · Tradier option chains · priced 9:35 AM ET, fixed for the session");
  await expect(card).toContainText("Today's (0DTE) 257.50 straddle cost 2.10 (0.82%) at 9:35 AM ET, added to 257.34, the price then; IV 31.0%.");
  await expect(card).toContainText("a price, not a forecast of where price will stay");
  await page.mouse.move(box.x + EMPTY.x, box.y + EMPTY.y);
  // Friday's high, in the round 262's zone, reads Friday's straddle and not today's.
  const friday = (await page.evaluate(() => (window as unknown as { __tjAutoLevels: Map<string, { shown(): string[] }> }).__tjAutoLevels.get("main")!.shown()))
    .find((id) => id.includes("expected_move_high@261.94"))!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", friday));
  await expect(page.getByRole("tooltip", { name: "262 + EM Fri high level card" })).toContainText("Fri, Oct 9's 257.50 straddle cost 4.60 (1.79%)");
  await page.screenshot({ path: test.info().outputPath("range-bands.png") });
  await page.mouse.move(box.x + EMPTY.x, box.y + EMPTY.y);

  // With the automatic levels hidden, the bands still ask for themselves alone.
  await layerGroup(page, "Auto levels").getByRole("button", { name: "Hide Auto levels" }).click();
  await expect.poll(() => requests.at(-1)).toContain("auto=0");
  await expect(drawn(page, "main")).toHaveAttribute("data-range-levels", "EM Fri low,EM 0DTE low,EM 0DTE high,EM Fri high");
  await expect(drawn(page, "main")).toHaveAttribute("data-auto-levels", /^expected_move_low@252.74/);

  // Through a reload, then off again from the chart menu's Layers.
  await page.reload();
  await expect(drawn(page, "main")).toHaveAttribute("data-range-levels", "EM Fri low,EM 0DTE low,EM 0DTE high,EM Fri high");
  await rightClick(page, "main", EMPTY);
  await chartMenu(page).getByRole("menuitem", { name: /^Layers/ }).click();
  await chartMenu(page).getByRole("menuitemcheckbox", { name: "Range bands" }).click();
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-range-levels", "");
  await expect(drawn(page, "main")).toHaveAttribute("data-vwap-bands-shown", "false");
  await expect.poll(() => server.data?.rangeBandsHidden).toBe(true);
  expect(errors).toEqual([]);
});

test("two expected-move levels on the same cent each show their own expiration's straddle", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fakeChartSettings(context, { revision: 1, data: { rangeBandsHidden: false } });
  await registerCharts(page);
  await registerAutoLevels(page);
  // Friday's straddle centred 1.00 lower and 1.00 wider ends on today's high exactly.
  const friday = { ...RANGES.bands[1], anchor: 256.34, move: 3.1, percent: 3.1 / 256.34, strike: 256 };
  await stubRanges(page, [], { ...RANGES, bands: [RANGES.bands[0], friday] },
    [rangeMember("expected_move_high", "EM 0DTE high", 259.44), rangeMember("expected_move_high", "EM Fri high", 259.44)]);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-range-levels", "EM 0DTE high + EM Fri high");
  const box = (await drawn(page, "main").boundingBox())!;
  const zone = (await page.evaluate(() => (window as unknown as { __tjAutoLevels: Map<string, { shown(): string[] }> }).__tjAutoLevels.get("main")!.shown()))
    .find((id) => id.includes("expected_move_high@259.44"))!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", zone));
  const card = page.getByRole("tooltip", { name: "EM 0DTE high + EM Fri high level card" });
  await expect(card.getByLabel("Straddle Mon, Oct 5")).toContainText("Today's (0DTE) 257.50 straddle cost 2.10");
  await expect(card.getByLabel("Straddle Fri, Oct 9")).toContainText("Fri, Oct 9's 256.00 straddle cost 3.10");
});

test("max pain always draws with the options levels, labelled inferred, with its expiration and a caveat", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fakeChartSettings(context);
  const requests: string[] = [];
  await registerCharts(page);
  await registerAutoLevels(page);
  await stubRanges(page, requests);
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  await layerGroup(page, "Options levels").getByRole("button", { name: "Show Options levels" }).click();
  // Far below the nearest strikes, and still drawn: like the walls, max pain is not ranked away.
  for (const panel of ALL_PANELS) await expect(drawn(page, panel)).toHaveAttribute("data-option-levels", `Max pain,${OI_LEVELS}`);
  const box = (await drawn(page, "main").boundingBox())!;
  await page.mouse.move(box.x + 300, box.y + await autoY(page, "main", "max_pain@248.5"));
  const card = page.getByRole("tooltip", { name: "Max pain level card" });
  await expect(card).toContainText("Max pain Max pain: least paid out at expiry248.50");
  await expect(card).toContainText("inferred · Tradier option chains");
  await expect(card).toContainText("Fri, Oct 9 expiration. The strike where this expiration's open contracts would pay their holders least at expiry.");
  await expect(card).toContainText("folklore");
});

function ladder(url: string): OptionsLadder {
  const query = new URL(url).searchParams;
  const rows = Array.from({ length: 13 }, (_, i) => 245 + i * 2.5).map((strike) => ({ ...optionRow(strike, null),
    ...(strike === 260 ? { oi_change: { session: "2026-10-02", previous_session: "2026-10-01", status: "unavailable" as const, calls: null, puts: null } } : {}),
    gamma: query.get("signed") === "1" ? (strike > 256 ? 1 : -1) * (5_000_000 - Math.abs(strike - 257.5) * 300_000) : 5_000_000 - Math.abs(strike - 257.5) * 300_000 }));
  return { ...optionInfo("gamma", query.get("scope") ?? "week", query.get("signed") === "1", []), spot: Number(query.get("spot")) || null, rows,
    signed: query.get("signed") === "1", walls: { call_oi: 265, put_oi: 250, call_volume: 257.5, put_volume: 255 } };
}

test("the strike ladder centres on the price, marks a strike on the charts and shares the layer's scope", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await fakeChartSettings(context);
  const reads: string[] = [];
  await stub(page);
  await page.route("**/api/backend/charts/options/*/ladder?**", async (route) => {
    reads.push(route.request().url());
    await route.fulfill({ json: ladder(route.request().url()) });
  });
  await page.goto("/charts");
  await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
  expect(reads).toHaveLength(0); // off until opened
  await page.getByRole("button", { name: "Strike ladder", exact: true }).click();
  const panel = page.getByRole("region", { name: "Strike ladder" });
  await expect(panel.getByRole("button", { name: /^Strike / })).toHaveCount(13);
  // The chart's latest price goes with the request and sits between the strikes around it.
  expect(new URL(reads[0]).searchParams.get("spot")).toMatch(/^257\.3/);
  await expect(panel.getByRole("separator", { name: /^Price 257\.3/ })).toBeVisible();
  const order = await panel.locator("button[aria-label^='Strike '], [role='separator']").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("aria-label")));
  const at = order.findIndex((label) => label?.startsWith("Price"));
  expect([order[at - 1], order[at + 1]]).toEqual(["Strike 255.00", "Strike 257.50"]);
  await expect(panel.getByRole("button", { name: "Strike 265.00, call wall" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Strike 250.00, put wall" })).toBeVisible();
  await expect(panel).toContainText("OI change: Oct 1, 2026 → Oct 2, 2026");
  await expect(panel.getByRole("button", { name: "Strike 255.00" })).toContainText("Δ +125");
  await expect(panel.getByRole("button", { name: "Strike 260.00" })).toContainText("Δ —");
  await expect(panel).toContainText("P/C OI 1.17 · P/C vol 0.78");
  await page.screenshot({ path: test.info().outputPath("strike-ladder.png") });

  // A click marks the strike on every chart of the symbol; a second click clears it.
  await panel.getByRole("button", { name: "Strike 260.00" }).click();
  for (const id of ALL_PANELS) await expect(drawn(page, id)).toHaveAttribute("data-highlight", "260");
  await expect(panel.getByRole("button", { name: "Strike 260.00" })).toHaveAttribute("aria-pressed", "true");
  await panel.getByRole("button", { name: "Strike 260.00" }).click();
  await expect(drawn(page, "main")).toHaveAttribute("data-highlight", "");

  // Its expirations and sign are the options layer's, saved with the workspace.
  await panel.getByRole("button", { name: "Within 45 days" }).click();
  await expect.poll(() => reads.at(-1)).toContain("scope=all");
  await panel.getByLabel("Signed gamma (assumed dealer side)").check();
  await expect.poll(() => reads.at(-1)).toContain("signed=1");
  await expect.poll(() => server.data?.optionsLayer).toEqual({ hidden: true, mode: "oi", scope: "all", nearest: 3, signed: true });
  // Another symbol's ladder; the mark belonged to MRVL.
  await panel.getByRole("button", { name: "Strike 255.00" }).click();
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await page.getByRole("button", { name: "Strike ladder", exact: true }).click();
  await expect.poll(() => reads.at(-1)).toContain("/options/NVDA/ladder");
  await expect(drawn(page, "main")).toHaveAttribute("data-highlight", "");
});

test.describe("phone strike ladder", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the ladder is a bottom sheet, and a tap marks the strike and shows the chart", async ({ page }) => {
    await stub(page);
    await page.route("**/api/backend/charts/options/*/ladder?**", (route) => route.fulfill({ json: ladder(route.request().url()) }));
    await page.goto("/charts");
    await expect(drawn(page, "main")).toHaveAttribute("data-bars", "240");
    // The top row keeps room for the chart: the ladder opens from the More menu.
    await page.getByRole("button", { name: "More chart controls" }).tap();
    await page.getByRole("button", { name: "Strike ladder", exact: true }).tap();
    const sheet = page.getByRole("dialog", { name: "Strike ladder" });
    await expect(sheet.getByRole("button", { name: /^Strike / })).toHaveCount(13);
    for (const target of await sheet.getByRole("button").all()) expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("strike-ladder-phone.png") });
    await sheet.getByRole("button", { name: "Strike 262.50" }).tap();
    await expect(sheet).toHaveCount(0);
    await expect(drawn(page, "main")).toHaveAttribute("data-highlight", "262.5");
  });
});

// ---- Pre-trade capture (C3.4, C3.5): Plan trade, templates, Discretionary, voice, saved strip ----
// Plans go to the real e2e backend, so they persist across browser contexts and reloads.
const CAPTURES = "/api/backend/charts/captures";

/** One template ("Reclaim") and a default account, set through the real routes; returns the setup. */
async function captureSetup(request: APIRequestContext, templates: { setup_label: string; wording: string }[] = [{ setup_label: "Reclaim", wording: "Out on a 5m close back below the level." }]): Promise<CaptureSetup> {
  let setup: CaptureSetup = await (await request.get(`${CAPTURES}/setup`)).json();
  for (const row of setup.templates) setup = await (await request.delete(`${CAPTURES}/templates/${row.id}`)).json();
  for (const row of templates) setup = await (await request.post(`${CAPTURES}/templates`, { data: row })).json();
  return (await request.put(`${CAPTURES}/setup`, { data: { default_account_id: setup.accounts[0].id } })).json();
}
const savedCaptures = async (request: APIRequestContext): Promise<Capture[]> => (await (await request.get(`${CAPTURES}?limit=100`)).json()).captures;
const planSheet = (page: Page) => page.getByRole("dialog", { name: "Plan trade" });

test("Plan trade saves in four actions: open, side, template, save; the strip shows it in every browser", { tag: "@captures" }, async ({ page, browser, request }) => {
  const setup = await captureSetup(request);
  const before = (await savedCaptures(request)).length;
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Plan trade" }).click();                       // 1. open
  const sheet = planSheet(page);
  await expect(sheet.getByTestId("plan-symbol")).toHaveText("MRVL");
  await expect(sheet.getByLabel("Plan account")).toHaveValue(setup.accounts[0].id);
  await sheet.getByRole("button", { name: "Buy calls" }).click();                         // 2. side
  await sheet.getByRole("button", { name: /Reclaim/ }).click();                           // 3. template, wording visible before saving
  await expect(sheet.getByRole("button", { name: /Reclaim/ })).toContainText("Out on a 5m close back below the level.");
  await sheet.getByRole("button", { name: "Save plan" }).click();                         // 4. save
  await expect(sheet).toHaveCount(0);
  await expect(page.getByLabel("Chart notice")).toContainText("Plan saved: MRVL · Buy calls · Reclaim");
  const strip = page.getByRole("region", { name: "Saved plan" });
  await expect(strip).toContainText("MRVL · Buy calls · Reclaim");
  await expect(strip.getByRole("status")).toHaveText("Saved");
  const rows = await savedCaptures(request);
  expect(rows.length).toBe(before + 1);
  const row = rows[0];
  expect([row.underlying, row.side, row.mode, row.setup_label, row.wording, row.template_revision]).toEqual(["MRVL", "buy_calls", "template", "Reclaim", "Out on a 5m close back below the level.", 1]);
  // The chart as it stood: interval, session, basis and price from what the page held; the frozen image uploaded after the save.
  expect(row.context.state).toBe("captured");
  if (row.context.state === "captured") {
    expect([row.context.symbol, row.context.interval, row.context.panel, row.context.basis?.status]).toEqual(["MRVL", "5m", "main", "ok"]);
    expect(row.context.price.value).toBeGreaterThan(0);
    expect(row.context.last_candle?.close).toBeGreaterThan(0);
  }
  await expect.poll(async () => (await savedCaptures(request))[0].image.state).toBe("saved");
  const image = await request.get(`${CAPTURES}/${row.id}/image`);
  expect(image.headers()["content-type"]).toBe("image/jpeg");
  // Editing the template later never changes the saved plan.
  await request.put(`${CAPTURES}/templates/${setup.templates[0].id}`, { data: { setup_label: "Reclaim", wording: "Changed later." } });
  expect((await savedCaptures(request))[0].wording).toBe("Out on a 5m close back below the level.");
  // Another browser sees the same saved plan.
  const other = await browser.newContext();
  await fakeChartSettings(other);
  const second = await other.newPage();
  await stub(second);
  await second.goto("/charts");
  await expect(second.getByRole("region", { name: "Saved plan" })).toContainText("MRVL · Buy calls · Reclaim");
  await second.getByRole("button", { name: "Show plan details" }).click();
  await expect(second.getByRole("img", { name: "MRVL chart when the plan was saved" })).toBeVisible();
  await expect(second.getByRole("region", { name: "Saved plan" })).toContainText("Reclaim (template rev 1): Out on a 5m close back below the level.");
  await other.close();
  // Did not take trade keeps the plan as a record; dismissing only hides the strip here.
  await page.getByRole("button", { name: "Did not take trade" }).click();
  await expect(strip.getByRole("status")).toHaveText("Not taken");
  await page.getByRole("button", { name: "Dismiss saved plan" }).click();
  await expect(strip).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Saved plan" })).toHaveCount(0);
  expect((await savedCaptures(request))[0].not_taken_at).not.toBeNull();
});

test("Alt+P opens Plan trade only when nothing else has the keys; Enter saves and Esc closes", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  // Typing in a field: Alt+P is the field's.
  await page.getByLabel("Chart symbol").focus();
  await page.keyboard.press("Alt+KeyP");
  await expect(planSheet(page)).toHaveCount(0);
  // Another dialog open: it keeps the keys.
  await page.getByLabel("Chart symbol").blur();
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toContainText("Plan trade");
  await page.keyboard.press("Alt+KeyP");
  await expect(planSheet(page)).toHaveCount(0);
  await page.keyboard.press("Escape");
  // The physical key, so Option+P (π on a Mac) works; a held key opens it once.
  await page.keyboard.down("Alt");
  await page.keyboard.down("KeyP");
  await page.keyboard.down("KeyP");
  await page.keyboard.up("KeyP");
  await page.keyboard.up("Alt");
  await expect(planSheet(page)).toHaveCount(1);
  // Chart hotkeys stay off while it is open.
  await page.keyboard.press("d");
  await expect(page.getByRole("button", { name: "1D", exact: true })).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Escape");
  await expect(planSheet(page)).toHaveCount(0);
  await page.keyboard.press("Alt+KeyP");
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy puts" }).click();
  await page.keyboard.press("Enter"); // not enabled yet: no plan chosen
  await expect(sheet).toHaveCount(1);
  await sheet.getByRole("button", { name: /Discretionary/ }).click();
  await page.keyboard.press("Enter");
  await expect(sheet).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Saved plan" })).toContainText("MRVL · Buy puts · Discretionary");
  // Existing chart hotkeys still work afterwards.
  await page.keyboard.press("d");
  await expect(page.getByRole("button", { name: "1D", exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("on a 390px phone the plan sheet is a bottom sheet; Discretionary with a note saves without templates", { tag: "@captures" }, async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await captureSetup(request, []);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toBeVisible();
  // Reachable at 390px with the side panel closed.
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  const box = await sheet.boundingBox();
  expect(box && Math.round(box.width)).toBe(390);
  expect(box && Math.round(box.y + box.height)).toBeGreaterThan(800);
  await expect(sheet).toContainText("No favorite templates yet");
  for (const name of ["Buy calls", "Buy puts", "Buy stock"]) expect((await sheet.getByRole("button", { name }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await sheet.getByRole("button", { name: "More" }).click();
  await sheet.getByRole("button", { name: "Short stock" }).click();
  await sheet.getByRole("button", { name: /Discretionary/ }).click();
  await sheet.getByLabel("Plan note").fill("Fading the gap into resistance");
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
  const row = (await savedCaptures(request))[0];
  expect([row.side, row.instrument, row.mode, row.note, row.setup_label]).toEqual(["short_stock", "stock", "discretionary", "Fading the gap into resistance", null]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "Show plan details" }).click();
  await expect(page.getByRole("region", { name: "Saved plan" })).toContainText("Discretionary: no explicit plan.");
  await page.getByRole("button", { name: "Add a later note" }).click();
  await page.getByLabel("Later note").fill("Did not fill; price ran.");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("region", { name: "Saved plan" })).toContainText(/Added later, .*Did not fill; price ran\./);
  expect((await savedCaptures(request))[0].note).toBe("Fading the gap into resistance");
});

test("a symbol switch while the sheet is open never retargets the plan; a failed chart image still saves the plan", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  // The chart moves on (the sheet leaves the toolbar free on a desktop).
  await page.getByLabel("Chart symbol").fill("NVDA");
  await page.getByLabel("Chart symbol").press("Enter");
  await expect(page.getByLabel("Selected symbol quote")).toContainText("189.12");
  await expect(sheet.getByTestId("plan-symbol")).toHaveText("MRVL");
  await expect(sheet).toContainText("The chart now shows NVDA. This plan stays on MRVL");
  await sheet.getByRole("button", { name: "Buy stock" }).click();
  await sheet.getByRole("button", { name: /Reclaim/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
  let row = (await savedCaptures(request))[0];
  expect([row.underlying, row.context_state, row.image.state]).toEqual(["MRVL", "unavailable", "unavailable"]);
  expect(row.context.state === "unavailable" && row.context.reason).toContain("showed NVDA, not MRVL");
  // An explicit change is allowed before saving.
  await page.getByRole("button", { name: "Plan trade" }).click();
  await sheet.getByRole("button", { name: "Change" }).click();
  await sheet.getByLabel("Plan symbol").fill("NVDA");
  await sheet.getByLabel("Plan symbol").press("Enter");
  await expect(sheet.getByTestId("plan-symbol")).toHaveText("NVDA");
  // The chart's picture cannot be made: the plan saves anyway, saying so, with the rest of the snapshot.
  await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = function (callback: BlobCallback) { callback(null); }; });
  await sheet.getByRole("button", { name: "Buy calls" }).click();
  await sheet.getByRole("button", { name: /Discretionary/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
  row = (await savedCaptures(request))[0];
  expect([row.underlying, row.context_state, row.image.state, row.image.note]).toEqual(["NVDA", "captured", "unavailable", "The chart image could not be made."]);
});

test("a rejected save keeps the sheet open; an unreachable server keeps the plan for Retry across a reload, saved once", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const before = (await savedCaptures(request)).length;
  await page.route(`**${CAPTURES}`, (route) => route.request().method() === "POST" ? route.fulfill({ status: 422, json: { detail: "Choose the journal account this plan is for." } }) : route.fallback());
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy calls" }).click();
  await sheet.getByRole("button", { name: /Reclaim/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet.getByRole("alert")).toHaveText("Not saved: Choose the journal account this plan is for.");
  await expect(sheet).toHaveCount(1);
  expect((await savedCaptures(request)).length).toBe(before);
  // Now the server cannot be reached at all.
  await page.unroute(`**${CAPTURES}`);
  let posts = 0;
  await page.route(`**${CAPTURES}`, (route) => { if (route.request().method() !== "POST") return route.fallback(); posts++; return route.abort("connectionrefused"); });
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet.getByRole("alert")).toContainText("Not saved yet");
  await expect(sheet.getByRole("alert")).toContainText("kept in this browser");
  expect(posts).toBe(1);
  await expect(sheet.getByRole("button", { name: "Buy puts" })).toBeDisabled(); // locked to the request it holds
  await page.reload();
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const strip = page.getByRole("region", { name: "Saved plan" });
  await expect(strip.getByRole("alert")).toContainText("Not saved: MRVL Buy calls");
  // The first send reached the server after all, but its answer was lost: Retry returns that plan, never a second one.
  const pending = await page.evaluate(() => new Promise<{ body: unknown }>((resolve) => {
    const open = indexedDB.open("tradejournal-captures", 1);
    open.onsuccess = () => { const all = open.result.transaction("outbox").objectStore("outbox").getAll(); all.onsuccess = () => resolve(all.result[0]); };
  }));
  expect((await request.post(CAPTURES, { data: pending.body })).status()).toBe(201);
  await page.unroute(`**${CAPTURES}`);
  await strip.getByRole("button", { name: "Retry" }).click();
  await expect(strip.getByRole("alert")).toHaveCount(0);
  await expect(strip).toContainText("MRVL · Buy calls · Reclaim");
  expect((await savedCaptures(request)).length).toBe(before + 1);
});

test("a double tap on Save plan sends one request and saves one plan", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const before = (await savedCaptures(request)).length;
  let posts = 0;
  await page.route(`**${CAPTURES}`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    posts++;
    await new Promise((resolve) => setTimeout(resolve, 400));
    return route.continue();
  });
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy calls" }).click();
  await sheet.getByRole("button", { name: /Reclaim/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).dblclick();
  await expect(sheet).toHaveCount(0);
  expect(posts).toBe(1);
  expect((await savedCaptures(request)).length).toBe(before + 1);
});

test("a template edited on another device is refused, then its new wording is shown and saves", { tag: "@captures" }, async ({ page, request }) => {
  const setup = await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy calls" }).click();
  await sheet.getByRole("button", { name: /Reclaim/ }).click();
  await request.put(`${CAPTURES}/templates/${setup.templates[0].id}`, { data: { setup_label: "Reclaim", wording: "Out under the 9 EMA." } });
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet.getByRole("alert")).toContainText("edited on another device");
  await expect(sheet.getByRole("button", { name: /Reclaim/ })).toContainText("Out under the 9 EMA.");
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
  const row = (await savedCaptures(request))[0];
  expect([row.wording, row.template_revision]).toEqual(["Out under the 9 EMA.", 2]);
});

test("a chart image that failed to upload keeps its Retry after its plan is dismissed", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.route(`**${CAPTURES}/*/image`, (route) => route.abort("connectionrefused"));
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy puts" }).click();
  await sheet.getByRole("button", { name: /Discretionary/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
  const id = (await savedCaptures(request))[0].id;
  await page.getByRole("button", { name: "Dismiss saved plan" }).click();
  const strip = page.getByRole("region", { name: "Saved plan" });
  await expect(strip.getByRole("alert")).toContainText("Chart image not uploaded: MRVL Buy puts plan");
  await page.unroute(`**${CAPTURES}/*/image`);
  await strip.getByRole("button", { name: "Retry image" }).click();
  await expect(strip).toHaveCount(0);
  expect((await savedCaptures(request)).find((row) => row.id === id)?.image.state).toBe("saved");
});

// The voice tests use Chromium's fake microphone (a tone, see playwright.config.ts): real MediaRecorder, real upload, real storage.
test.describe("voice plans", () => {
  test.use({ permissions: ["microphone"] });

  test("hold to record and release saves the recording; with no speech engine it says so and plays back", { tag: "@captures" }, async ({ page, request }) => {
    await captureSetup(request);
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: "Plan trade" }).click();
    const sheet = planSheet(page);
    await expect(sheet).toContainText("What am I taking, why here, and what would change my mind?");
    // Ticker, account and side stay explicit for voice; no microphone until then.
    await sheet.getByRole("button", { name: "Record voice plan" }).click();
    await expect(sheet.getByRole("alert")).toHaveText("Choose what you are taking first.");
    await sheet.getByRole("button", { name: "Buy calls" }).click();
    const mic = sheet.getByRole("button", { name: "Record voice plan" });
    const at = (await mic.boundingBox())!;
    await page.mouse.move(at.x + at.width / 2, at.y + at.height / 2);
    await page.mouse.down();
    await expect(sheet.getByRole("timer", { name: "Recording time" })).toBeVisible();
    await page.waitForTimeout(1500);
    await page.mouse.up();
    await expect(sheet).toHaveCount(0);
    await expect(page.getByLabel("Chart notice")).toHaveText("Recording saved");
    const row = (await savedCaptures(request))[0];
    expect([row.mode, row.side, row.setup_label, row.transcript?.status]).toEqual(["voice", "buy_calls", null, "not_configured"]);
    expect(row.audio?.type).toBe("audio/webm");
    expect(row.audio!.ms!).toBeGreaterThan(1000);
    const strip = page.getByRole("region", { name: "Saved plan" });
    await expect(strip).toContainText("MRVL · Buy calls · Voice plan");
    await strip.getByRole("button", { name: "Show plan details" }).click();
    await expect(strip.getByLabel("Plan recording")).toBeVisible();
    await expect(strip).toContainText("Transcription is turned off on this server. Recordings are saved and can be played back.");
    const audio = await request.get(`${CAPTURES}/${row.id}/audio`);
    expect(audio.headers()["content-type"]).toBe("audio/webm");
    expect((await audio.body()).subarray(0, 4)).toEqual(Buffer.from([0x1a, 0x45, 0xdf, 0xa3]));
  });

  test("tap to start, Stop & save; a cancelled press or a hidden tab stops and offers Save or Discard", { tag: "@captures" }, async ({ page, request }) => {
    await captureSetup(request);
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: "Plan trade" }).click();
    const sheet = planSheet(page);
    await sheet.getByRole("button", { name: "Buy puts" }).click();
    // Keyboard: the accessible tap path.
    await sheet.getByRole("button", { name: "Record voice plan" }).focus();
    await page.keyboard.press("Enter");
    await expect(sheet.getByRole("button", { name: "Stop & save" })).toBeEnabled();
    await page.waitForTimeout(600);
    // The tab is hidden: recording stops, nothing is uploaded, the clip waits for a choice.
    await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => true }); document.dispatchEvent(new Event("visibilitychange")); });
    await expect(sheet.getByRole("status").filter({ hasText: "page was hidden" })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Save recording" })).toBeVisible();
    await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => false }); });
    await sheet.getByRole("button", { name: "Discard" }).click();
    await expect(sheet.getByRole("button", { name: "Record voice plan" })).toBeVisible();
    // A press the browser cancels (a scroll took it): stopped, not saved.
    const mic = sheet.getByRole("button", { name: "Record voice plan" });
    await mic.dispatchEvent("pointerdown", { button: 0, pointerId: 7, isPrimary: true });
    await expect(sheet.getByRole("timer", { name: "Recording time" })).toBeVisible();
    await page.waitForTimeout(600);
    await sheet.getByRole("button", { name: "Recording: release to save" }).dispatchEvent("pointercancel", { pointerId: 7 });
    await expect(sheet.getByRole("status").filter({ hasText: "press was interrupted" })).toBeVisible();
    const before = (await savedCaptures(request)).length;
    await sheet.getByRole("button", { name: "Save recording" }).click();
    await expect(sheet).toHaveCount(0);
    expect((await savedCaptures(request)).length).toBe(before + 1);
    expect((await savedCaptures(request))[0].side).toBe("buy_puts");
  });

  test("the 30-second limit stops the clip and offers Save or Discard", { tag: "@captures" }, async ({ page, request }) => {
    await captureSetup(request);
    await page.clock.install();
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: "Plan trade" }).click();
    const sheet = planSheet(page);
    await sheet.getByRole("button", { name: "Buy stock" }).click();
    await sheet.getByRole("button", { name: "Record voice plan" }).focus();
    await page.keyboard.press("Enter");
    await expect(sheet.getByRole("button", { name: "Stop & save" })).toBeEnabled();
    await page.clock.runFor(31_000);
    await expect(sheet.getByRole("status").filter({ hasText: "30-second limit" })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Save recording" })).toBeVisible();
    await sheet.getByRole("button", { name: "Discard" }).click();
    await expect(sheet.getByRole("button", { name: "Save recording" })).toHaveCount(0);
  });

  test("a voice plan that cannot reach the server waits with its audio and saves on Retry", { tag: "@captures" }, async ({ page, request }) => {
    await captureSetup(request);
    await stub(page);
    await page.goto("/charts");
    await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
    await page.route(`**${CAPTURES}/voice`, (route) => route.abort("connectionrefused"));
    await page.getByRole("button", { name: "Plan trade" }).click();
    const sheet = planSheet(page);
    await sheet.getByRole("button", { name: "Buy calls" }).click();
    await sheet.getByRole("button", { name: "Record voice plan" }).focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1200);
    await sheet.getByRole("button", { name: "Stop & save" }).click();
    await expect(sheet.getByRole("alert")).toContainText("Not saved yet");
    await page.keyboard.press("Escape");
    await page.reload();
    await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
    const strip = page.getByRole("region", { name: "Saved plan" });
    await expect(strip.getByRole("alert")).toContainText("Not saved: MRVL Buy calls (voice)");
    await page.unroute(`**${CAPTURES}/voice`);
    await strip.getByRole("button", { name: "Retry" }).click();
    await expect(strip).toContainText("MRVL · Buy calls · Voice plan");
    const row = (await savedCaptures(request))[0];
    expect(row.audio?.bytes).toBeGreaterThan(1000);
    // The server's receipt is what counts; the device's time is kept, unverified.
    expect(row.client_captured_at).toBeLessThan(row.received_at);
  });
});

test("microphone denied or unavailable leaves the click path working", { tag: "@captures" }, async ({ page, request }) => {
  await captureSetup(request);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Permission denied", "NotAllowedError"));
  });
  await stub(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Plan trade" }).click();
  const sheet = planSheet(page);
  await sheet.getByRole("button", { name: "Buy calls" }).click();
  await sheet.getByRole("button", { name: "Record voice plan" }).focus();
  await page.keyboard.press("Enter");
  await expect(sheet.getByRole("status").filter({ hasText: "Microphone access is blocked" })).toBeVisible();
  await sheet.getByRole("button", { name: /Reclaim/ }).click();
  await sheet.getByRole("button", { name: "Save plan" }).click();
  await expect(sheet).toHaveCount(0);
});

test("transcript states: transcribing, then ready; a failure keeps the recording and offers Retry; a correction sits beside it", { tag: "@captures" }, async ({ page }) => {
  const base: Capture = { id: "cap-1", client_id: "client-1", received_at: Math.floor(Date.now() / 1000) - 30, client_captured_at: Math.floor(Date.now() / 1000) - 31,
    account_id: "acct", account_label: "Roth IRA ··8267", underlying: "MRVL", side: "buy_calls", instrument: "option", mode: "voice", template_id: null, template_revision: null,
    setup_label: null, wording: null, note: null, strike: null, expiration: null, quantity: null, context_state: "unavailable", context: { state: "unavailable", reason: "fixture" },
    image: { state: "unavailable", note: null, bytes: null }, audio: { type: "audio/webm", ms: 4000, bytes: 30000 },
    transcript: { status: "pending", text: null, provider: null, error: null, transcribed_at: null }, not_taken_at: null, notes: [] };
  let current = base;
  let lists = 0;
  const posts: string[] = [];
  await page.route(`**${CAPTURES}?**`, (route) => { lists++; return route.fulfill({ json: { captures: [current] } }); });
  await page.route(`**${CAPTURES}/cap-1/**`, (route) => {
    posts.push(new URL(route.request().url()).pathname.split("/").at(-1)!);
    if (route.request().url().endsWith("/transcribe")) current = { ...current, transcript: { ...current.transcript!, status: "pending", error: null } };
    if (route.request().url().endsWith("/notes")) current = { ...current, notes: [{ id: "n1", kind: "transcript_correction", text: "Out below 182.", created_at: Date.now() / 1000 }] };
    return route.fulfill({ json: current });
  });
  await stub(page);
  await page.goto("/charts");
  const strip = page.getByRole("region", { name: "Saved plan" });
  await expect(strip.getByRole("status")).toHaveText("Recording saved — transcribing");
  // While a transcript is on its way the list is checked every few seconds.
  current = { ...base, transcript: { status: "ready", text: "Taking MRVL calls on the reclaim. Out below one eighty.", provider: "Whisper base.en (on this server)", error: null, transcribed_at: Date.now() / 1000 } };
  await expect(strip.getByRole("status")).toHaveText("Saved", { timeout: 8000 });
  const settled = lists;
  await strip.getByRole("button", { name: "Show plan details" }).click();
  await expect(strip.getByLabel("Transcript", { exact: true })).toContainText("Taking MRVL calls on the reclaim. Out below one eighty.");
  await expect(strip.getByLabel("Transcript", { exact: true })).toContainText("Whisper base.en (on this server)");
  await strip.getByRole("button", { name: "Correct transcript" }).click();
  await strip.getByLabel("Transcript correction").fill("Out below 182.");
  await strip.getByRole("button", { name: "Add", exact: true }).click();
  await expect(strip.getByLabel("Transcript", { exact: true })).toContainText(/Corrected later, .*Out below 182\./);
  await expect(strip.getByLabel("Transcript", { exact: true })).toContainText("Taking MRVL calls on the reclaim. Out below one eighty.");
  await page.waitForTimeout(3500);
  expect(lists).toBe(settled); // no polling once nothing is pending
  // A provider failure: the recording stays, Retry asks once.
  current = { ...base, transcript: { status: "failed", text: null, provider: null, error: "Transcription took longer than 180 seconds and was stopped.", transcribed_at: null } };
  await page.reload();
  await strip.getByRole("button", { name: "Show plan details" }).click();
  await expect(strip).toContainText("Transcription took longer than 180 seconds and was stopped. The recording is saved.");
  await expect(strip.getByLabel("Plan recording")).toBeVisible();
  await strip.getByRole("button", { name: "Retry transcript" }).click();
  await expect(strip.getByRole("status")).toHaveText("Recording saved — transcribing");
  expect(posts.filter((post) => post === "transcribe")).toHaveLength(1);
});
