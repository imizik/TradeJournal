import { expect, test, type Page, type Request } from "@playwright/test";

// The cockpit chart's studies and level menu (docs/copilot-lab.md § The desk): the legend's toggles and their memory per
// timeframe, the reading line, the symbol's alerts as lines with a remove chip, and the level menu's three actions. The
// lab's routes and the alert routes are stubbed in the browser: nothing reaches the e2e backend's alerts, and no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const STEP = { "2m": 120, "15m": 900, "1D": 86400 } as const;
type Timeframe = keyof typeof STEP;
const ALERT = { id: "alert-1", price: 97.5, text: "Crosses above 97.50", label: "From Charts", removable: true, condition: "crosses", interval: null, session: "regular" };

/** The desk's chart read for a symbol with no plan and no fills: 60 candles ending now around 94, the studies the read
 * carries for the timeframe (VWAP only on the regular-session candles), the reference lines and the reading line. */
function chartRead(timeframe: Timeframe, alerts: object[] = [ALERT]) {
  const step = STEP[timeframe];
  const last = now - (now % step);
  const daily = timeframe === "1D";
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 94 + Math.sin(i / 5);
    return { time: last - (59 - i) * step, open, high: open + 0.4, low: open - 0.4, close: open + (i % 3 === 0 ? -0.2 : 0.2), volume: 1000 + 10 * i,
      extended: timeframe === "2m" && i < 5 };
  });
  const line = (shift: number, from = 0) => bars.map((b, i) => i < from ? null : Math.round((b.close + shift) * 100) / 100);
  const studies = daily
    ? { ema21: line(-0.5, 20), sma50: line(-1, 49), sma200: bars.map(() => null), vwap: bars.map(() => null), rvol: bars.map(() => 1.2) }
    : { vwap: bars.map((b, i) => b.extended ? null : Math.round((94 + i / 100) * 100) / 100), ema9: line(-0.1), ema21: line(-0.3), rvol: bars.map((b) => b.extended ? null : 1.4) };
  const close = bars[59].close;
  return {
    symbol: "NBIS", timeframe, step, as_of: now, live: false, state: "ok", reason: null, bars, studies,
    reference: daily ? [] : [{ key: "prev_close", price: 93.1, label: "Prev close 93.10" }, { key: "pm_high", price: 95.2, label: "PM high 95.20" },
      { key: "pm_low", price: 93.4, label: "PM low 93.40" }],
    reading: { last: close, at: bars[59].time + 60, daily: false, prev_close: 93.1, vwap: 94.59, vwap_at: bars[59].time, rvol: 1.4 },
    levels: [], alerts, marks: [], time_stop: null,
  };
}

/** One alert as the alerts routes list it. */
const listed = (id: string, price: number, label = "From the desk") => ({
  id, symbol: "NBIS", price, created_on: "2026-11-12", condition: "crosses", interval: null, session: "regular", direction: price > 94 ? "up" : "down",
  source_kind: "level", source_id: "desk", label, plan_role: null, state: "active", armed_at: now, event: null,
});

async function desk(page: Page, { alerts = [ALERT] as object[] } = {}) {
  const posted: Request[] = [];
  const timeframes: string[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.route(/\/copilot\/desk\/symbol(:|%3A)NBIS\//, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/chart")) {
      const timeframe = (url.searchParams.get("timeframe") ?? "2m") as Timeframe;
      timeframes.push(timeframe);
      return route.fulfill({ json: chartRead(timeframe, alerts) });
    }
    return route.fulfill({ json: { state: "ok", symbol: "NBIS", count: 0, unavailable: [], recent_days: 7, rows: [] } });
  });
  // The desk read of NBIS (a read sent as a POST; its own spec covers it) answers with no read here.
  await page.route("**/copilot/desk/read", (route) => route.fulfill({ json: { state: "hidden" } }));
  // Every write this page makes is recorded; the alert routes answer as the backend's listing would.
  page.on("request", (request) => {
    if (request.method() !== "GET" && !new URL(request.url()).pathname.endsWith("/copilot/desk/read")) posted.push(request);
  });
  await page.route("**/charts/alerts**", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      const body = request.postDataJSON();
      return route.fulfill({ json: { alerts: [listed("made-1", body.price, body.label)], phone: true } });
    }
    if (request.method() === "DELETE") return route.fulfill({ json: { alerts: [], phone: true } });
    return route.fulfill({ json: { alerts: [], phone: true } });
  });
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  return { pane, posted, timeframes, writes: () => posted.map((r) => `${r.method()} ${new URL(r.url()).pathname}`) };
}

test("each study has a toggle that shows its value at the crosshair, and the choices are kept per timeframe", async ({ page }) => {
  const { pane, writes } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  const legend = pane.getByTestId("desk-chart-studies");
  // Intraday defaults: VWAP, EMA 9 and 21, volume and the reference lines, each with its value on the last candle.
  await expect(legend.getByRole("button")).toHaveText([/^VWAP \d+\.\d{2}$/, /^EMA 9 \d+\.\d{2}$/, /^EMA 21 \d+\.\d{2}$/, /^Vol 1\.6K · 1\.4×$/, "Prev close · PM high/low", "News"]);
  for (const button of await legend.getByRole("button").all()) await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(canvas).toHaveAttribute("data-studies", "vwap,ema9,ema21");
  await expect(canvas).toHaveAttribute("data-volume", "on");
  await expect(canvas).toHaveAttribute("data-reference", "3");
  // The reading line: price, change against the previous close, VWAP, volume against usual, and when.
  const reading = pane.getByTestId("desk-reading");
  await expect(reading).toContainText(/^\d+\.\d{2} · [+−]\d+\.\d{2}% vs prev close · [+−]\d+\.\d{2}% vs VWAP 94\.59 · vol 1\.4× usual · as of \d{1,2}:\d{2} [AP]M ET$/);
  await pane.screenshot({ path: test.info().outputPath("desk-chart-studies-2m.png") });

  // The crosshair moves the values to the candle under the pointer.
  const box = (await canvas.boundingBox())!;
  const before = await legend.getByTestId("desk-study-ema9").textContent();
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.4);
  await expect(legend.getByTestId("desk-study-ema9")).not.toHaveText(before!);

  await legend.getByTestId("desk-study-ema9").click();
  await legend.getByTestId("desk-study-volume").click();
  await expect(legend.getByTestId("desk-study-ema9")).toHaveAttribute("aria-pressed", "false");
  await expect(legend.getByTestId("desk-study-ema9")).toHaveText("EMA 9"); // off: no value
  await expect(canvas).toHaveAttribute("data-studies", "vwap,ema21");
  await expect(canvas).toHaveAttribute("data-volume", "off");

  // The daily chart offers its own studies, all on, untouched by the 2m choices.
  await pane.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "1D" }).click();
  await expect(canvas).toHaveAttribute("data-timeframe", "1D");
  await expect(legend.getByRole("button")).toHaveText([/^EMA 21 /, /^SMA 50 /, "SMA 200 —", /^Vol .* · 1\.2× 30d$/]);
  await expect(canvas).toHaveAttribute("data-studies", "ema21,sma50"); // SMA 200 has no value yet: nothing drawn, no flat line
  await expect(canvas).toHaveAttribute("data-volume", "on");
  await expect(canvas).toHaveAttribute("data-reference", "0");

  // Remembered in this browser: after a reload, 2m still has EMA 9 and volume off.
  await pane.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "2m" }).click();
  await page.reload();
  await expect(canvas).toHaveAttribute("data-timeframe", "2m");
  await expect(legend.getByTestId("desk-study-ema9")).toHaveAttribute("aria-pressed", "false");
  await expect(legend.getByTestId("desk-study-volume")).toHaveAttribute("aria-pressed", "false");
  await expect(canvas).toHaveAttribute("data-studies", "vwap,ema21");
  expect(writes()).toEqual([]); // toggling saves nothing anywhere but this browser
});

test("the level menu sets an alert that can be undone, and an existing alert's chip removes it with an undo", async ({ page }) => {
  const { pane, writes, posted } = await desk(page);
  const canvas = pane.getByTestId("desk-chart-canvas");
  await expect(canvas).toHaveAttribute("data-alerts", "1");
  await expect(pane.getByTestId("desk-chart-alerts")).toHaveText(/Crosses above 97\.50/);

  // A right-click on the candles opens the menu at that price.
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.2, { button: "right" });
  const menu = pane.getByTestId("desk-level-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Alert when price crosses here", "Plan from here…", "Ask the copilot about this level"]);
  const level = Number((await menu.getAttribute("aria-label"))!.replace(/^At /, "").replace(/,/g, ""));
  expect(level).toBeGreaterThan(90);
  await pane.screenshot({ path: test.info().outputPath("desk-level-menu.png") });
  await menu.getByRole("menuitem", { name: "Alert when price crosses here" }).click();
  const status = pane.getByTestId("desk-chart-status");
  await expect(status).toContainText(new RegExp(`^Alert set: NBIS crosses (above|below) ${level.toFixed(2)}, regular hours\\.`));
  const body = posted.find((r) => r.method() === "POST")!.postDataJSON();
  expect(body).toMatchObject({ symbol: "NBIS", price: level, condition: "crosses", session: "regular", source_kind: "level", source_id: "desk", label: "From the desk" });
  expect(Math.abs(body.reference - 94)).toBeLessThan(2); // which side it waits on is judged from the last price
  await expect(canvas).toHaveAttribute("data-alerts", "1"); // the listing's answer: the new alert
  await expect(pane.getByTestId("desk-chart-alerts")).toContainText(level.toFixed(2));

  await status.getByRole("button", { name: "Undo" }).click();
  await expect(status).toHaveText("Alert removed.");
  await expect(canvas).toHaveAttribute("data-alerts", "0");
  expect(writes()).toEqual(["POST /api/backend/charts/alerts", "DELETE /api/backend/charts/alerts/made-1"]);

  // An existing alert: its chip removes it, and Undo sets it again.
  await page.reload();
  await expect(canvas).toHaveAttribute("data-alerts", "1");
  await pane.getByRole("button", { name: "Remove alert: Crosses above 97.50" }).click();
  await expect(status).toContainText("Alert removed: Crosses above 97.50.");
  await expect(canvas).toHaveAttribute("data-alerts", "0");
  await status.getByRole("button", { name: "Undo" }).click();
  await expect(status).toContainText("Alert set again: Crosses above 97.50.");
  const again = posted.filter((r) => r.method() === "POST").at(-1)!.postDataJSON();
  expect(again).toMatchObject({ symbol: "NBIS", price: 97.5, condition: "crosses", label: "From Charts" });
});

test("Plan from here opens the plan form prefilled with his choice of role and saves nothing; Ask scopes the copilot to the level", async ({ page }) => {
  const { pane, writes } = await desk(page, { alerts: [] });
  const canvas = pane.getByTestId("desk-chart-canvas");
  const box = (await canvas.boundingBox())!;
  const message = page.getByRole("textbox", { name: "Message" });
  // A tap on the price scale opens the menu at that price.
  await page.mouse.click(box.x + box.width - 20, box.y + box.height * 0.25);
  const menu = pane.getByTestId("desk-level-menu");
  await expect(menu).toBeVisible();
  const level = (await menu.getAttribute("aria-label"))!.replace(/^At /, "");
  await menu.getByRole("menuitem", { name: "Plan from here…" }).click();
  await expect(menu).toContainText("nothing is saved");
  await menu.getByRole("menuitem", { name: "Entry trigger" }).click();
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=NBIS&context=Plan\+a\+trade.*&origin=chart$/);
  await expect(message).toHaveValue(new RegExp(`Plan a trade: NBIS from the desk's 2m chart, last \\d+\\.\\d{2}\\. Entry trigger ${level.replace(".", "\\.")} \\(a level I picked on the chart\\)`));

  // As the invalidation: the drawn plan rides in the link (a long below the price), the message says so.
  await canvas.scrollIntoViewIfNeeded();
  const lower = (await canvas.boundingBox())!;
  await page.mouse.click(lower.x + lower.width * 0.5, lower.y + lower.height * 0.6, { button: "right" });
  const low = (await menu.getAttribute("aria-label"))!.replace(/^At /, "");
  await menu.getByRole("menuitem", { name: "Plan from here…" }).click();
  await menu.getByRole("menuitem", { name: "Invalidation" }).click();
  await expect(page).toHaveURL(new RegExp(`plan=invalidation%3A${low.replace(".", "\\.")}%2Cside%3Along`));
  await expect(message).toHaveValue(new RegExp(`Invalidation ${low.replace(".", "\\.")} \\(a level I picked on the chart\\), a long\\.`));

  // Ask: the copilot is about NBIS, with the level, where price is against it and when in the question's context line.
  await page.mouse.click(lower.x + lower.width * 0.5, lower.y + lower.height * 0.3, { button: "right" });
  const asked = (await menu.getAttribute("aria-label"))!.replace(/^At /, "");
  await menu.getByRole("menuitem", { name: "Ask the copilot about this level" }).click();
  await expect(message).toHaveValue(new RegExp(`^Context: NBIS ${asked.replace(".", "\\.")}, a level I picked on the desk's 2m chart\\. Last \\d+\\.\\d{2} at .* ET, \\d+\\.\\d% (above|below) it\\.`));
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=NBIS&context=NBIS\+/); // the copilot is on NBIS (no saved conversation here)
  expect(writes()).toEqual([]); // nothing saved, sent or armed
});

test.describe("at 393 px with a finger", () => {
  test.use({ viewport: { width: 393, height: 852 }, hasTouch: true, isMobile: true });

  test("a long-press opens the level menu with thumb-sized items, the legend scrolls sideways, and the page does not", async ({ page }) => {
    const { pane, writes } = await desk(page);
    await page.getByRole("button", { name: "Back to the desk" }).click({ timeout: 2000 }).catch(() => { /* already on the desk */ });
    const canvas = pane.getByTestId("desk-chart-canvas");
    await canvas.scrollIntoViewIfNeeded();
    const box = (await canvas.boundingBox())!;
    const at = { x: Math.round(box.x + box.width * 0.4), y: Math.round(box.y + box.height * 0.3) };
    const client = await page.context().newCDPSession(page);
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [at] });
    await page.waitForTimeout(700);
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    const menu = pane.getByTestId("desk-level-menu");
    await expect(menu).toBeVisible();
    for (const item of await menu.getByRole("menuitem").all()) expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    const placed = (await menu.boundingBox())!;
    expect(placed.x).toBeGreaterThanOrEqual(0);
    expect(placed.x + placed.width).toBeLessThanOrEqual(393);
    for (const button of await pane.getByTestId("desk-chart-studies").getByRole("button").all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: test.info().outputPath("desk-level-menu-393.png") });
    await menu.getByRole("menuitem", { name: "Alert when price crosses here" }).tap();
    await expect(pane.getByTestId("desk-chart-status")).toContainText("Alert set: NBIS crosses");
    // A short tap on the candles opens nothing.
    await page.touchscreen.tap(at.x, at.y);
    await page.waitForTimeout(700);
    await expect(menu).toHaveCount(0);
    // A vertical swipe that starts on the chart scrolls the page and opens nothing.
    const before = await page.evaluate(() => window.scrollY);
    await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [at] });
    for (let step = 1; step <= 8; step++) {
      await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: at.x, y: at.y - step * 25 }] });
      await page.waitForTimeout(30);
    }
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(700);
    await expect(menu).toHaveCount(0);
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(before);
    // A tap on the price scale opens the menu at that price.
    const scale = (await canvas.boundingBox())!;
    await page.touchscreen.tap(Math.round(scale.x + scale.width - 20), Math.round(scale.y + scale.height * 0.3));
    await expect(menu).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    expect(writes()).toEqual(["POST /api/backend/charts/alerts"]);
  });
});
