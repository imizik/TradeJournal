import { expect, test, type Page } from "@playwright/test";
import { barAt, explainCandle, price, todayNewYork, type ChartBar, type ChartData, type Interval } from "../lib/charts";
import { realisticPanels } from "./fixtures/realisticBars";

// Explain this candle: right-click (desktop) or long-press (phone) a candle on the Charts main chart, choose "Explain
// this candle", and the dock's Copilot tab opens with the candle's line ready and nothing sent; its Send also shows the
// copilot the chart. Every lab route is stubbed in the browser (the e2e backend keeps the lab off).

// ---- the line, without a browser ----

/** Today's 10:41 New York as epoch seconds (EDT or EST). */
function todayAt(hour: number, minute: number): number {
  const [y, m, d] = todayNewYork().split("-").map(Number);
  const clock = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hourCycle: "h23", hour: "2-digit", minute: "2-digit" });
  for (const offset of [4, 5]) {
    const stamp = Date.UTC(y, m - 1, d, hour + offset, minute) / 1000;
    if (clock.format(stamp * 1000) === `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`) return stamp;
  }
  throw new Error("no New York offset fits");
}
const candle = (time: number, extra: Partial<ChartBar> = {}): ChartBar => ({ time, end_time: time + 300, open: 94.1, high: 94.6, low: 93.95, close: 94.35,
  volume: 41_000, source: "tradier", extended: false, ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null, rvol: 1.3, ...extra });

test("the line names the candle by its New York time, OHLC, volume and RVol, and dates an older one", () => {
  expect(explainCandle("NBIS", "5m", candle(todayAt(10, 41))))
    .toBe("Explain this candle: NBIS 5m at 10:41 ET (O 94.10 H 94.60 L 93.95 C 94.35, vol 41k, RVol 1.3). What moved it, and what did I do here?");
  // An earlier session's candle carries its date; no RVol when the candle has none; a daily candle by its date.
  const older = Date.UTC(2026, 9, 23, 14, 41) / 1000;
  expect(explainCandle("NBIS", "15m", candle(older, { rvol: null, volume: 1_250_000 })))
    .toBe("Explain this candle: NBIS 15m at 10:41 ET on 2026-10-23 (O 94.10 H 94.60 L 93.95 C 94.35, vol 1.3m). What moved it, and what did I do here?");
  expect(explainCandle("NBIS", "1D", candle(Date.UTC(2026, 9, 23, 13, 30) / 1000))).toMatch(/^Explain this candle: NBIS 1D on 2026-10-23 \(O 94\.10 /);
});

// ---- on the Charts page ----

const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const DONE = { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
  usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } };
const IMAGE = "c".repeat(32);
type Seen = { chats: { messages: { content: string }[]; image_ids?: string[] }[]; uploads: number };

async function stubLab(page: Page): Promise<Seen> {
  const seen: Seen = { chats: [], uploads: 0 };
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const intervals = (new URL(route.request().url()).searchParams.get("intervals") ?? "5m").split(",") as Interval[];
    const now = Math.floor(Date.now() / 1000);
    const data = { symbol: "MRVL", session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now },
      panels: realisticPanels(intervals), quotes: [], issues: [], adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {},
        dividends: "unsupported", dividends_note: "Dividends are not adjusted.", warnings: [] },
      intraday_as_of: now - 60, history_note: "Synthetic chart data.", fills: [], fills_truncated: false, extras: {} } as unknown as ChartData;
    return route.fulfill({ json: data });
  });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/symbol/*", (route) => route.fulfill({ json: { symbol: "MRVL", as_of: "2026-10-26T15:00:00Z", quotes_at: null, quote_issue: null,
    positions: { state: "ok", rows: [] }, plans: { state: "ok", rows: [] }, new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } } } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: { id: "88888888-8888-4888-8888-888888888888", source: "copilot",
    title: "x", symbol: "MRVL", status: "open", conclusion: null, revision: 1, message_count: 2, has_findings: false, created_at: "2026-10-26T14:00:00Z",
    updated_at: "2026-10-26T14:05:00Z", transcript: [], evidence: [], findings: null } }));
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: { id: "88888888-8888-4888-8888-888888888888", revision: 2 } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/images", (route) => { seen.uploads += 1; return route.fulfill({ status: 201, json: { id: IMAGE, width: 1200, height: 600, bytes: 90000 } }); });
  await page.route("**/copilot/chat", (route) => {
    seen.chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse([{ type: "text", delta: "The group led it." }, DONE]) });
  });
  return seen;
}

type Registry = Map<string, { timeScale(): { coordinateToTime(x: number): number | null; width(): number } }>;
const chart = (page: Page) => page.getByTestId("canvas-main");
const chartMenu = (page: Page) => page.getByRole("dialog", { name: "Chart menu" });
const message = (page: Page) => page.getByTestId("copilot-panel").getByLabel("Message");

async function open(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.addInitScript(() => { (window as typeof window & { __tjCharts?: Map<string, unknown> }).__tjCharts = new Map(); });
  await page.goto("/charts?symbol=MRVL");
  await expect(chart(page).locator("canvas").first()).toBeVisible();
  await expect(chart(page)).toHaveAttribute("data-bars", /\d+/);
}

/** The line the candle under ``x`` (chart pixels) should give, written out from the fixture's own bar. */
async function lineAt(page: Page, x: number): Promise<{ text: string; clock: string }> {
  const time = await page.evaluate(([key, at]) => (window as unknown as Record<string, Registry>)[key as string].get("main")!.timeScale().coordinateToTime(at as number),
    ["__tjCharts", x] as const);
  const bar = barAt(realisticPanels(["5m"])["5m"]!.bars, time!)!;
  const ny = (format: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", ...format }).format(bar.time * 1000);
  const hhmm = ny({ hourCycle: "h23", hour: "2-digit", minute: "2-digit" });
  const volume = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(bar.volume).toLowerCase();
  const rvol = typeof bar.rvol === "number" && !bar.extended ? `, RVol ${bar.rvol.toFixed(1)}` : "";
  const day = ny({});
  return { clock: new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }).format(bar.time * 1000),
    text: `Explain this candle: MRVL 5m at ${hhmm} ET${day === todayNewYork() ? "" : ` on ${day}`} (O ${price(bar.open)} H ${price(bar.high)} L ${price(bar.low)} `
      + `C ${price(bar.close)}, vol ${volume}${rvol}). What moved it, and what did I do here?` };
}

test("right-click a candle: Explain this candle opens the dock with the line, sends nothing, and Send shows the chart", async ({ page }) => {
  const seen = await stubLab(page);
  await open(page, 1440, 900);
  const at = { x: 300, y: 120 };
  const { text, clock } = await lineAt(page, at.x);
  await chart(page).click({ position: at, button: "right" });
  const explain = chartMenu(page).getByRole("menuitem", { name: /^Explain this candle/ });
  await expect(explain).toHaveText(`Explain this candle${clock}`);
  await page.screenshot({ path: test.info().outputPath("explain-candle-menu-1440.png") });
  await explain.click();
  await expect(chartMenu(page)).toHaveCount(0);
  await expect(message(page)).toHaveValue(`Context: ${text}\n\n`);
  await expect(page).toHaveURL(/\/charts\?symbol=MRVL/);
  await page.waitForTimeout(500);
  expect(seen.chats).toHaveLength(0);
  expect(seen.uploads).toBe(0); // the chart is read at Send, not before

  await page.getByTestId("copilot-panel").getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("copilot-panel").getByText("The group led it.")).toBeVisible();
  expect(seen.uploads).toBe(1);
  expect(seen.chats).toHaveLength(1);
  expect(seen.chats[0].image_ids).toEqual([IMAGE]);
  expect(seen.chats[0].messages.at(-1)!.content).toBe(`[shared a screenshot] Context: ${text}`);
  await page.screenshot({ path: test.info().outputPath("explain-candle-sent-1440.png") });

  // The price scale has no candle to explain.
  const plot = await page.evaluate((key) => (window as unknown as Record<string, Registry>)[key].get("main")!.timeScale().width(), "__tjCharts");
  await chart(page).click({ position: { x: plot + 20, y: 120 }, button: "right" });
  await expect(chartMenu(page).getByRole("menuitem", { name: "Reset chart scale" })).toBeVisible();
  await expect(chartMenu(page).getByRole("menuitem", { name: /^Explain this candle/ })).toHaveCount(0);
});

test.describe("phone", () => {
  test.use({ hasTouch: true });
  test("on a 375 px phone a long press offers it as a 44 px row and the dock opens with the line, unsent", async ({ page }) => {
    const seen = await stubLab(page);
    await open(page, 375, 812);
    await chart(page).scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const box = (await chart(page).boundingBox())!;
    const at = { x: 150, y: 120 };
    const { text } = await lineAt(page, at.x);
    const client = await page.context().newCDPSession(page);
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: Math.round(box.x + at.x), y: Math.round(box.y + at.y) }] });
    await page.waitForTimeout(700);
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    const row = chartMenu(page).getByRole("menuitem", { name: /^Explain this candle/ });
    await expect(row).toBeVisible();
    const b = (await row.boundingBox())!;
    expect(b.height).toBeGreaterThanOrEqual(44);
    expect(b.x + b.width).toBeLessThanOrEqual(375);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await page.screenshot({ path: test.info().outputPath("explain-candle-sheet-375.png") });
    await row.tap();
    await expect(page.getByRole("dialog", { name: "Copilot" })).toBeVisible();
    await expect(message(page)).toHaveValue(`Context: ${text}\n\n`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await page.screenshot({ path: test.info().outputPath("explain-candle-dock-375.png") });
    await page.waitForTimeout(500);
    expect(seen.chats).toHaveLength(0);
  });
});
