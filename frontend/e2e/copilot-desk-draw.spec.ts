import { expect, test, type BrowserContext, type Page, type Request } from "@playwright/test";
import type { ChartBar, ChartData, Interval } from "../lib/charts";
import { fakeChartSettings, type SettingsStore } from "./fixtures/chartSettings";

// The desk chart's drawings and alerts (docs/copilot-lab.md § The desk): his Charts levels and drawings show on the desk
// chart; the pencil opens a horizontal line, trend line and zone (the line and Delete on a phone); what he draws, moves
// or deletes saves to the same chart settings Charts reads; a drawn line's menu sets an alert on it, plans from it or
// deletes it; the bell lists the symbol's armed alerts to move or remove. Chart settings are an in-memory copy of the
// real endpoint (shared by every page in the context); the lab's routes and the alert routes are stubbed in the browser.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const STEP = 120;
const LAST = now - (now % STEP);
const barTime = (i: number) => LAST - (59 - i) * STEP;
const ALERT = { id: "alert-1", price: 97.5, text: "Crosses above 97.50", label: "From Charts", removable: true, condition: "crosses", interval: null, session: "regular" };

/** The desk's 2m chart read for NBIS: 60 candles ending now around 94, no plan, one armed alert. */
function chartRead(alerts: object[]) {
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 94 + Math.sin(i / 5);
    return { time: barTime(i), open, high: open + 0.4, low: open - 0.4, close: open + (i % 3 === 0 ? -0.2 : 0.2), volume: 1000 + 10 * i, extended: false };
  });
  const close = bars[59].close;
  return {
    symbol: "NBIS", timeframe: "2m", step: STEP, as_of: now, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: close, at: bars[59].time + 60, daily: false, prev_close: 93.1, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts, marks: [], time_stop: null,
  };
}

/** His Charts drawings for NBIS before the test: a level he named and a rising trend line across the desk's candles. */
const SEEDED = {
  levels: { NBIS: [{ id: "charts-level", price: 94.8, label: "Breakout", drawn_on: "2026-11-12" }] },
  drawings: { NBIS: [{ id: "charts-trend", kind: "trend", points: [{ time: barTime(10) + 60, price: 93.2 }, { time: barTime(50) + 60, price: 95.2 }],
    color: "#67d5eb", width: 2, drawn_on: "2026-11-12" }] },
};

const listed = (id: string, price: number, extra: object = {}) => ({
  id, symbol: "NBIS", price, created_on: "2026-11-13", condition: "crosses", interval: null, session: "regular", direction: price > 94 ? "up" : "down",
  source_kind: "level", source_id: "desk", label: "From the desk", plan_role: null, state: "active", armed_at: now, event: null, ...extra,
});

async function desk(page: Page, context: BrowserContext) {
  const store = await fakeChartSettings(context, { revision: 2, data: SEEDED });
  const posted: Request[] = [];
  await page.addInitScript(() => { (window as typeof window & { __tjDrawings?: Map<string, unknown> }).__tjDrawings = new Map(); });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(/\/copilot\/desk\/symbol(:|%3A)NBIS\//, (route) => new URL(route.request().url()).pathname.endsWith("/chart")
    ? route.fulfill({ json: chartRead([ALERT]) })
    : route.fulfill({ json: { state: "ok", symbol: "NBIS", count: 0, unavailable: [], recent_days: 7, rows: [] } }));
  await page.route("**/copilot/desk/read", (route) => route.fulfill({ json: { state: "hidden" } }));
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET" && path.includes("/charts/alerts")) posted.push(request);
  });
  await context.route("**/charts/alerts**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "POST" && path.endsWith("/rearm")) return route.fulfill({ json: { alerts: [listed("alert-1", request.postDataJSON().price, { label: "From Charts" })], phone: true } });
    if (request.method() === "POST") {
      const body = request.postDataJSON();
      return route.fulfill({ json: { alerts: [listed("alert-1", 97.5, { label: "From Charts" }), listed("made-1", body.price, { source_kind: body.source_kind, source_id: body.source_id, label: body.label })], phone: true } });
    }
    return route.fulfill({ json: { alerts: [], phone: true } });
  });
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  return { pane, store, posted };
}

type Probe = { y(id: string): number | null; anchors(id: string): ({ x: number; y: number } | null)[] | null };
const probe = (page: Page) => ({
  y: (id: string) => page.evaluate((item) => (window as unknown as { __tjDrawings: Map<string, Probe> }).__tjDrawings.get("desk")!.y(item), id),
  anchors: (id: string) => page.evaluate((item) => (window as unknown as { __tjDrawings: Map<string, Probe> }).__tjDrawings.get("desk")!.anchors(item), id),
});
const saved = (store: SettingsStore) => ({
  levels: ((store.data?.levels ?? {}) as Record<string, { id: string; price: number }[]>).NBIS ?? [],
  drawings: ((store.data?.drawings ?? {}) as Record<string, { id: string; kind: string }[]>).NBIS ?? [],
});

/** A Charts workspace read for NBIS whose candles cover the desk's (so the drawings anchored to them draw there too). */
function workspace(url: string): ChartData {
  const query = new URL(url).searchParams;
  const panels: ChartData["panels"] = {};
  for (const interval of (query.get("intervals") ?? "5m").split(",") as Interval[]) {
    const step = ({ "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 } as Record<string, number>)[interval];
    const count = Math.min(240, Math.ceil(7200 / step) + 2);
    const bars: ChartBar[] = Array.from({ length: count }, (_, i) => {
      const time = LAST - 7200 - (LAST % step) + i * step;
      const close = 94 + Math.sin(i / 5);
      return { time, end_time: time + step, source: "tradier", open: close - 0.2, high: close + 0.4, low: close - 0.4, close, volume: 1000,
        ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null, extended: false } as unknown as ChartBar;
    });
    panels[interval] = { bars, markers: [] };
  }
  return { symbol: "NBIS", session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels,
    quotes: [{ symbol: "NBIS", name: "NBIS test company", last: 94.2, change: 1, change_percentage: 1.1, volume: 1000, previous_close: 93.1, regular_close: 94, trade_time: now - 2 }],
    issues: [], adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] },
    intraday_as_of: now - 60, history_note: "Synthetic chart data for browser verification.", fills: [], fills_truncated: false, extras: {} } as unknown as ChartData;
}

test("his Charts drawings show on the desk; the pencil draws a line, trend line and zone that save where Charts reads them, select, move, delete and undo", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { pane, store } = await desk(page, context);
  const canvas = pane.getByTestId("desk-chart-canvas");
  await expect(canvas).toHaveAttribute("data-drawings", "2");  // the Charts level and trend line
  await expect(pane.getByTestId("desk-draw-bar")).toHaveCount(0);  // no tools until the pencil
  await pane.screenshot({ path: test.info().outputPath("desk-drawings.png") });

  await pane.getByRole("button", { name: "Draw on the chart" }).click();
  const bar = pane.getByTestId("desk-draw-bar");
  await expect(bar.getByRole("button")).toHaveText(["Line", "Trend line", "Zone", "Delete", "Undo"]);
  // The candle pane is the top ~70% of the canvas (volume below); the canvas moves when a message shows above it.
  const at = async (fx: number, fy: number) => { const box = (await canvas.boundingBox())!; return { x: box.x + box.width * fx, y: box.y + box.height * fy }; };

  // A horizontal line: one click. It is saved as a Charts level, and selected.
  await bar.getByRole("button", { name: "Horizontal line" }).click();
  await expect(canvas).toHaveAttribute("data-tool", "level");
  let p = await at(0.3, 0.2);
  await page.mouse.click(p.x, p.y);
  await expect.poll(() => saved(store).levels.length).toBe(2);
  const line = saved(store).levels[1];
  await expect(canvas).toHaveAttribute("data-selected", line.id);
  await expect(canvas).not.toHaveAttribute("data-tool", /./);

  // A trend line and a zone: two clicks each.
  await bar.getByRole("button", { name: "Trend line" }).click();
  p = await at(0.15, 0.6); await page.mouse.click(p.x, p.y);
  await expect(bar).toContainText("Click the second point");
  p = await at(0.5, 0.4); await page.mouse.click(p.x, p.y);
  await bar.getByRole("button", { name: "Zone" }).click();
  p = await at(0.6, 0.15); await page.mouse.click(p.x, p.y);
  p = await at(0.72, 0.3); await page.mouse.click(p.x, p.y);
  await expect.poll(() => saved(store).drawings.map((d) => d.kind)).toEqual(["trend", "trend", "zone"]);
  await expect(canvas).toHaveAttribute("data-drawings", "5");
  const zone = saved(store).drawings[2].id;
  await expect(canvas).toHaveAttribute("data-selected", zone);

  // Delete removes the selected zone; Cmd/Ctrl+Z brings it back.
  await page.keyboard.press("Delete");
  await expect.poll(() => saved(store).drawings.length).toBe(2);
  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => saved(store).drawings.map((d) => d.id)).toContain(zone);

  // Drag his Charts level down: it saves at the new price, dated today.
  const y = (await probe(page).y("charts-level"))!;
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + 200, box.y + y);
  await page.mouse.down();
  for (let step = 1; step <= 6; step++) await page.mouse.move(box.x + 200, box.y + y + step * 6);
  await page.mouse.up();
  await expect.poll(() => saved(store).levels[0].price).toBeLessThan(94.8);
  await pane.screenshot({ path: test.info().outputPath("desk-drawing-tools.png") });

  // The pencil again: the tools go away; the drawings stay.
  await pane.getByRole("button", { name: "Done drawing" }).click();
  await expect(pane.getByTestId("desk-draw-bar")).toHaveCount(0);
  await expect(canvas).not.toHaveAttribute("data-selected", /./);

  // Charts reads the same settings: the desk's line, trend line and zone are on its chart.
  const charts = await context.newPage();
  await charts.setViewportSize({ width: 1440, height: 900 });
  await charts.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: workspace(route.request().url()) }));
  await charts.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
  await charts.goto("/charts?symbol=NBIS");
  const main = charts.getByTestId("canvas-main");
  await expect(main).toHaveAttribute("data-drawings", "trend,trend,zone");
  await expect(main).toHaveAttribute("data-levels", new RegExp(`^\\d+\\.\\d{2},${line.price.toFixed(2)}$`));
  await main.screenshot({ path: test.info().outputPath("charts-shows-desk-drawings.png") });
  await charts.close();

  // And a line he adds in Charts (another device's save) shows on the desk at its next read.
  store.revision += 1;
  store.data = { ...store.data, levels: { NBIS: [...saved(store).levels, { id: "from-charts", price: 93.5, label: "Level 3", drawn_on: "2026-11-13" }] } };
  await page.reload();
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-drawings", "6");
});

test("a drawn line's menu sets an alert on it, plans from it and deletes it; the bell lists the alerts to move or remove", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { pane, store, posted } = await desk(page, context);
  const canvas = pane.getByTestId("desk-chart-canvas");
  await expect(canvas).toHaveAttribute("data-drawings", "2");
  let box = (await canvas.boundingBox())!;
  const menu = pane.getByTestId("desk-level-menu");

  // A right-click on his trend line (no pencil needed): the menu is the line's, at its price at the last candle.
  const [a, b] = (await probe(page).anchors("charts-trend"))!;
  await page.mouse.click(box.x + (a!.x + b!.x) / 2, box.y + (a!.y + b!.y) / 2, { button: "right" });
  await expect(menu.getByTestId("desk-level-menu-line")).toHaveText(/^Trend line \(at the last candle\) · $/);
  await expect(menu.getByRole("menuitem")).toHaveText(["Alert when price crosses here", "Plan from here…", "Ask the copilot about this level", "Delete this trend line"]);
  const price = Number((await menu.getAttribute("aria-label"))!.replace(/^At /, ""));
  expect(price).toBeGreaterThan(95.2); // past its second point, still rising: 93.20 + (59 − 10) / 40 × 2.00 = 95.65
  expect(price).toBeLessThan(95.8);
  await pane.screenshot({ path: test.info().outputPath("desk-line-menu.png") });
  await menu.getByRole("menuitem", { name: "Alert when price crosses here" }).click();
  await expect(pane.getByTestId("desk-chart-status")).toContainText(`Alert set: NBIS crosses above ${price.toFixed(2)}`);
  expect(posted.at(-1)!.postDataJSON()).toMatchObject({ symbol: "NBIS", price, condition: "crosses", source_kind: "drawing", source_id: "charts-trend", label: "Trend line (at the last candle)" });

  // His level: "Plan from here… → Invalidation" is Charts' "Plan this" message on his drawn level.
  const y = (await probe(page).y("charts-level"))!;
  box = (await canvas.boundingBox())!;  // the message above moved the chart down
  await page.mouse.click(box.x + box.width * 0.4, box.y + y, { button: "right" });
  await expect(menu.getByTestId("desk-level-menu-line")).toHaveText("Breakout · ");
  await expect(menu).toHaveAttribute("aria-label", "At 94.80");
  await menu.getByRole("menuitem", { name: "Plan from here…" }).click();
  await menu.getByRole("menuitem", { name: "Invalidation" }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/Invalidation 94\.80 \(my drawn level "Breakout"\), a short\./);
  await expect(page).toHaveURL(/plan=invalidation%3A94\.80%2Cside%3Ashort/);

  // Delete from the menu: gone from the shared settings, and the message offers Undo.
  const [c, d] = (await probe(page).anchors("charts-trend"))!;
  box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + (c!.x + d!.x) / 2, box.y + (c!.y + d!.y) / 2, { button: "right" });
  await menu.getByRole("menuitem", { name: "Delete this trend line" }).click();
  await expect.poll(() => saved(store).drawings.length).toBe(0);
  const status = pane.getByTestId("desk-chart-status");
  await expect(status).toContainText("Deleted trend line.");
  await status.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => saved(store).drawings.map((x) => x.id)).toEqual(["charts-trend"]);

  // The bell: the symbol's armed alerts, to move or remove.
  await pane.getByRole("button", { name: /^Alerts on this symbol: \d$/ }).click();
  const list = pane.getByTestId("desk-chart-alerts");
  await expect(list).toContainText("Crosses above 97.50");
  await list.getByRole("button", { name: "Move alert: Crosses above 97.50", exact: true }).click();
  await list.getByRole("textbox", { name: "New price for Crosses above 97.50" }).fill("98.25");
  await list.getByRole("button", { name: "Move", exact: true }).click();
  await expect(status).toContainText("Alert moved: Crosses above 98.25.");
  const moved = posted.at(-1)!;
  expect(new URL(moved.url()).pathname).toMatch(/\/charts\/alerts\/alert-1\/rearm$/);
  expect(moved.postDataJSON()).toMatchObject({ price: 98.25 });
  await pane.screenshot({ path: test.info().outputPath("desk-alerts-list.png") });
  await list.getByRole("button", { name: "Remove alert: Crosses above 98.25", exact: true }).click();
  await expect(status).toContainText("Alert removed: Crosses above 98.25.");
  expect(posted.at(-1)!.method()).toBe("DELETE");
});

test.describe("at 393 px with a finger", () => {
  test.use({ viewport: { width: 393, height: 852 }, hasTouch: true, isMobile: true });

  test("the pencil offers the line and Delete only; a tap draws a line, a tap selects it, Delete removes it with an undo", async ({ page, context }) => {
    const { pane, store } = await desk(page, context);
    await page.getByRole("button", { name: "Back to the desk" }).click({ timeout: 2000 }).catch(() => { /* already on the desk */ });
    const canvas = pane.getByTestId("desk-chart-canvas");
    await canvas.scrollIntoViewIfNeeded();
    await pane.getByRole("button", { name: "Draw on the chart" }).tap();
    const bar = pane.getByTestId("desk-draw-bar");
    await expect(bar.getByRole("button")).toHaveText(["Line", ""]);  // the line and Delete (an icon)
    await expect(bar.getByRole("button", { name: "Trend line" })).toHaveCount(0);
    for (const button of await bar.getByRole("button").all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await bar.getByRole("button", { name: "Horizontal line" }).tap();
    let box = (await canvas.boundingBox())!;
    await page.touchscreen.tap(box.x + box.width * 0.4, box.y + box.height * 0.25);
    await expect.poll(() => saved(store).levels.length).toBe(2);
    const id = saved(store).levels[1].id;
    await expect(canvas).toHaveAttribute("data-selected", id);
    // Tap off it, then on it again.
    box = (await canvas.boundingBox())!;
    await page.touchscreen.tap(box.x + box.width * 0.4, box.y + box.height * 0.55);
    await expect(canvas).not.toHaveAttribute("data-selected", /./);
    const y = (await probe(page).y(id))!;
    box = (await canvas.boundingBox())!;
    await page.waitForTimeout(700);  // two taps within half a second are the chart's double tap, as in Charts
    await page.touchscreen.tap(box.x + box.width * 0.4, box.y + y + 6);
    await expect(canvas).toHaveAttribute("data-selected", id);
    await page.screenshot({ path: test.info().outputPath("desk-draw-393.png") });
    await bar.getByRole("button", { name: "Delete the selected line" }).tap();
    await expect.poll(() => saved(store).levels.length).toBe(1);
    const status = pane.getByTestId("desk-chart-status");
    await expect(status).toContainText("Deleted the line.");
    await status.getByRole("button", { name: "Undo" }).tap();
    await expect.poll(() => saved(store).levels.map((level) => level.id)).toEqual(["charts-level", id]);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(393);
  });
});
