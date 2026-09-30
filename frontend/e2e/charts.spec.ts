import { expect, test, type Page } from "@playwright/test";
import type { ChartData, ChartBar, Interval } from "../lib/charts";

// Provider responses are deliberately stubbed: browser checks prove interaction,
// not brokerage entitlement. Backend tests exercise normalization and real routes.
function fixture(url: string): ChartData {
  const query = new URL(url).searchParams;
  const symbol = query.get("symbol") ?? "MRVL";
  const intervals = (query.get("intervals") ?? "5m").split(",") as Interval[];
  const panels: ChartData["panels"] = {};
  for (const interval of intervals) {
    const step = ({ "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 })[interval];
    const daily = step >= 86400;
    const slots = daily ? 1 : Math.ceil(23400 / step);
    const bars: ChartBar[] = Array.from({ length: 240 }, (_, i) => {
      const time = 1789392600 + (daily ? i * step : Math.floor(i / slots) * 86400 + (i % slots) * step);
      const close = 245 + i * 0.06 + Math.sin(i / 8) * 2;
      return { time, end_time: time + step, source: "tradier", open: close - 0.3, high: close + 0.8, low: close - 0.7, close, volume: 10000 + i * 240,
        ema9: close - 0.3, ema20: close - 0.6, ema50: close - 1, ema200: close - 3, vwap: daily ? null : close - 0.8, rsi: 50 + Math.sin(i / 9) * 24, extended: false };
    });
    panels[interval] = { bars, markers: [{ id: "fill-test", time: bars[220].time, label: "buy to open 1 call", buy: true }] };
  }
  const now = Math.floor(Date.now() / 1000);
  const symbols = [...new Set([symbol, ...(query.get("watchlist") ?? "").split(",")].filter(Boolean))];
  return { symbol, session: query.get("session") === "regular" ? "regular" : "extended", provider: "Tradier", delayed: false,
    refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels,
    quotes: symbols.map((s) => ({ symbol: s, name: `${s} test company`, last: s === "NVDA" ? 189.12 : 262.66,
      change: 2, change_percentage: 1.5, volume: 1200000, previous_close: 260.66, trade_time: now - 2 })),
    issues: [], intraday_as_of: now - 60, history_note: "Synthetic chart data for browser verification.", fills: [], fills_truncated: false };
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
  // A new symbol recreates the chart.
  await page.getByRole("button", { name: "Chart NVDA", exact: true }).click();
  await expect(page.getByRole("region", { name: /NVDA 5m chart/ })).toBeVisible();
  await expect.poll(() => resets(page)).toBe(1);
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
