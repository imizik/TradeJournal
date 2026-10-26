import { expect, test, type Page } from "@playwright/test";
import type { ChartData, Interval, PriceLevel } from "../lib/charts";
import { drawnParam, readDeepLink, readDrawn } from "../lib/copilot";
import type { Drawing } from "../lib/drawings";
import { pairLevels, planMessage, planSource, type PlanSource } from "../lib/drawPlan";
import { fakeChartSettings, type SettingsStore } from "./fixtures/chartSettings";
import { realisticPanels } from "./fixtures/realisticBars";

// Draw the plan: two drawn levels on the Charts main chart become the copilot plan card's entry trigger and
// invalidation. Every lab, quote, capture and alert route is stubbed in the browser; a turn is a fixed SSE stream.

// ---- the pairing, without a browser ----

const source = (id: string, price: number, name: string | null = null): PlanSource => ({ id, kind: "level", price, name });

test("the level nearer the last price is the trigger, and swap trades the roles", () => {
  const [up, down] = [source("u", 95.9, "Prior day low"), source("d", 92.3)];
  // Around the price: the nearer side breaks.
  expect(pairLevels(up, down, 94.35)).toEqual({ side: "long", trigger: up, invalidation: down });
  expect(pairLevels(down, up, 93)).toEqual({ side: "short", trigger: down, invalidation: up });
  // Both below: a long off support. Both above: a short into resistance.
  expect(pairLevels(up, down, 97)).toEqual({ side: "long", trigger: up, invalidation: down });
  expect(pairLevels(up, down, 91)).toEqual({ side: "short", trigger: down, invalidation: up });
  expect(pairLevels(up, down, 94.35, true)).toEqual({ side: "short", trigger: down, invalidation: up });
  // No price, or a tie: a long breakout. One price twice: no plan.
  expect(pairLevels(up, down, null)?.side).toBe("long");
  expect(pairLevels(source("u", 96), source("d", 92), 94)?.side).toBe("long");
  expect(pairLevels(up, source("x", 95.9), 94)).toBeNull();
  // One level is the invalidation, on the side of the price it sits.
  expect(pairLevels(down, null, 94.35)).toEqual({ side: "long", trigger: null, invalidation: down });
  expect(pairLevels(up, null, 94.35)).toEqual({ side: "short", trigger: null, invalidation: up });
});

test("a zone plans from its edge nearest the price; a trend line or a note is not a plan level", () => {
  const zone: Drawing = { id: "z", kind: "zone", points: [{ time: 1, price: 92.1 }, { time: 2, price: 93.4 }], color: "#659ef0", width: 1, drawn_on: "2026-10-26" };
  expect(planSource(zone, 95)).toEqual({ id: "z", kind: "zone", price: 93.4, name: null, edge: "upper" });
  expect(planSource(zone, 90)).toMatchObject({ price: 92.1, edge: "lower" });
  expect(planSource({ ...zone, kind: "trend" }, 95)).toBeNull();
  const level: PriceLevel = { id: "l", price: 92.304, label: "Level 4" };
  expect(planSource(level, 95)).toEqual({ id: "l", kind: "level", price: 92.3, name: null });
});

test("the message and the deep link's plan parameter carry the drawn prices", () => {
  const pair = pairLevels(source("u", 95.9, "Prior day low"), source("d", 92.3), 94.35)!;
  expect(planMessage("NBIS", "5m", 94.35, pair)).toBe("Plan a trade: NBIS from the 5m chart, last 94.35. Entry trigger 95.90 (my drawn level \"Prior day low\"). "
    + "Invalidation 92.30 (my drawn level). Draft the plan around these levels; argue if they are wrong.");
  expect(drawnParam({ side: "long", trigger: 95.9, invalidation: 92.3 })).toBe("trigger:95.90,invalidation:92.30,side:long");
  expect(readDrawn("trigger:95.90,invalidation:92.30,side:long")).toEqual({ side: "long", trigger: 95.9, invalidation: 92.3 });
  expect(readDrawn("invalidation:92.30,side:short")).toEqual({ side: "short", trigger: null, invalidation: 92.3 });
  // A long's trigger is above its invalidation; anything else is dropped.
  expect(readDrawn("trigger:92.30,invalidation:95.90,side:long")).toBeNull();
  expect(readDrawn("trigger:abc,invalidation:92.30,side:long")).toBeNull();
  expect(readDeepLink({ symbol: "nbis", context: "Plan a trade: NBIS", plan: "trigger:95.90,invalidation:92.30,side:long" })?.plan)
    .toEqual({ side: "long", trigger: 95.9, invalidation: 92.3 });
});

// ---- on the Charts page ----

const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "88888888-8888-4888-8888-888888888888";
const ROTH = "00000000-0000-0000-0000-000000000001";
const LAST = realisticPanels(["5m"])["5m"]!.bars.at(-1)!.close;
const cents = (value: number) => Math.round(value * 100) / 100;
// Two levels around the price, the upper one nearer: a long from the upper, out under the lower.
const UPPER = cents(LAST * 1.004);
const LOWER = cents(LAST * 0.992);
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const DONE = { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
  usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } };
// The copilot argues the entry up 40 cents and keeps the invalidation the owner drew.
const MOVED = cents(UPPER + 0.4);
const TURN = sse([
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", id: "p1", kind: "trade_plan", symbol: "MRVL", direction: "long", instrument: "stock", contract: null,
    thesis: "MRVL clears the drawn level with room to the next one.", entry_trigger: { condition: "closes_beyond", price: MOVED, interval: "5m" },
    invalidation: { condition: "crosses", price: LOWER, interval: null }, time_stop: null, size_note: null, last: LAST, as_of: "2026-10-26T14:00:00Z" },
  { type: "text", delta: "MRVL plan (draft): the entry is a close above, a little past your line." }, DONE,
]);
type Lab = { alerts: Record<string, unknown>[]; captures: Record<string, unknown>[] };

async function stubLab(page: Page): Promise<Lab> {
  const lab: Lab = { alerts: [], captures: [] };
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
  await page.route("**/copilot/investigations", (route) => {
    const transcript = route.request().postDataJSON().transcript;
    return route.fulfill({ status: 201, json: { id: INV, source: "copilot", title: transcript[0].content, symbol: "MRVL", status: "open", conclusion: null, revision: 1,
      message_count: transcript.length, has_findings: false, created_at: "2026-10-26T14:00:00Z", updated_at: "2026-10-26T14:05:00Z", transcript, evidence: [], findings: null } });
  });
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: { id: INV, revision: 2 } }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "MRVL", last: LAST, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: { accounts: [{ id: ROTH, label: "Roth IRA ··8267", broker: "robinhood" }],
    default_account_id: ROTH, templates: [], max_templates: 3, transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", (route) => { lab.captures.push(route.request().postDataJSON()); return route.fulfill({ status: 201, json: { id: "c1", ...route.request().postDataJSON() } }); });
  await page.route("**/charts/alerts", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      lab.alerts = [...lab.alerts, { id: `a${lab.alerts.length + 1}`, created_on: "2026-10-26", direction: body.reference < body.price ? "up" : "down", state: "active", armed_at: 1, event: null, ...body }];
    }
    return route.fulfill({ json: { alerts: lab.alerts, phone: true } });
  });
  return lab;
}

type PaneRegistry = Map<string, { panes(): { getSeries(): { seriesType(): string; priceToCoordinate(value: number): number | null; coordinateToPrice(y: number): number | null }[] }[] }>;
const series = "__tjCharts";
const levelY = (page: Page, value: number) => page.evaluate(([key, at]) => (window as unknown as Record<string, PaneRegistry>)[key as string].get("main")!
  .panes()[0].getSeries().find((s) => s.seriesType() === "Candlestick")!.priceToCoordinate(at as number)!, [series, value] as const);
const chart = (page: Page) => page.getByTestId("canvas-main");
const levelsPanel = (page: Page) => page.getByRole("region", { name: "Saved price levels" });
const savedLevels = (server: SettingsStore) => ((server.data?.levels as Record<string, PriceLevel[]> | undefined)?.MRVL ?? []);

async function open(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.addInitScript(() => { (window as typeof window & { __tjCharts?: Map<string, unknown> }).__tjCharts = new Map(); });
  await page.goto("/charts?symbol=MRVL");
  await expect(chart(page).locator("canvas").first()).toBeVisible();
  await expect(chart(page)).toHaveAttribute("data-bars", /\d+/);
}

/** Save a level from the watchlist's level form (on a phone, its sheet, closed again after). */
async function addLevel(page: Page, label: string, value: number) {
  const opened = !(await levelsPanel(page).isVisible());
  if (opened) await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  if (!(await page.getByLabel("Level label").isVisible())) await page.getByRole("button", { name: "Add level" }).click();
  await page.getByLabel("Level label").fill(label);
  await page.getByLabel("Level price", { exact: true }).fill(value.toFixed(2));
  await page.getByRole("button", { name: "Save price level" }).click();
  await expect(levelsPanel(page)).toContainText(value.toFixed(2));
  if (opened && await page.getByRole("dialog", { name: "Watchlist" }).isVisible()) {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Watchlist" })).toHaveCount(0);
  }
}

const message = (page: Page) => page.getByTestId("copilot-panel").getByLabel("Message");
const longText = `Context: Plan a trade: MRVL from the 5m chart, last ${LAST.toFixed(2)}. Entry trigger ${UPPER.toFixed(2)} (my drawn level "Breakout"). `
  + `Invalidation ${LOWER.toFixed(2)} (my drawn level). Draft the plan around these levels; argue if they are wrong.\n\n`;

test("two drawn levels: Plan this opens the dock's copilot with them, swaps, and the confirmed plan labels them", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  const lab = await stubLab(page);
  await open(page, 1440, 900);
  const toolbarPlan = page.getByRole("button", { name: "Plan this", exact: true });
  await expect(toolbarPlan).toBeDisabled();

  await addLevel(page, "Breakout", UPPER);
  await addLevel(page, "", LOWER);
  await expect(toolbarPlan).toBeEnabled();
  await expect(toolbarPlan).toHaveAttribute("title", `Plan this: Long · entry ${UPPER.toFixed(2)} · invalidation ${LOWER.toFixed(2)}. Opens the copilot with it; nothing is sent until you press Send.`);

  // Selecting either drawn level shows the chip beside it, naming the side and both prices.
  await chart(page).click({ position: { x: 220, y: await levelY(page, LOWER) } });
  const chip = page.getByRole("group", { name: "Plan from your drawing" });
  await expect(chip.getByRole("button", { name: `Plan this: Long · ${UPPER.toFixed(2)} → ${LOWER.toFixed(2)}` })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("draw-the-plan-chip-1440.png") });

  // Plan this: the dock's Copilot tab, in place, with the message ready and nothing sent.
  await chip.getByRole("button", { name: /^Plan this:/ }).click();
  await expect(message(page)).toHaveValue(longText);
  await expect(page).toHaveURL(/\/charts\?symbol=MRVL/);

  // One tap swaps the roles: now a short from the lower level, out over the upper. The level's menu offers it too.
  await chip.getByRole("button", { name: "Swap entry and invalidation" }).click();
  await expect(chip.getByRole("button", { name: `Plan this: Short · ${LOWER.toFixed(2)} → ${UPPER.toFixed(2)}` })).toBeVisible();
  await chart(page).click({ position: { x: 220, y: await levelY(page, UPPER) }, button: "right" });
  const menu = page.getByRole("dialog", { name: "Level menu" });
  await menu.getByRole("menuitem", { name: `Plan this: Short · entry ${LOWER.toFixed(2)} · invalidation ${UPPER.toFixed(2)}` }).click();
  await expect(message(page)).toHaveValue(`Context: Plan a trade: MRVL from the 5m chart, last ${LAST.toFixed(2)}. Entry trigger ${LOWER.toFixed(2)} (my drawn level). `
    + `Invalidation ${UPPER.toFixed(2)} (my drawn level "Breakout"). Draft the plan around these levels; argue if they are wrong.\n\n`);

  // Back to the long, sent: the card shows which prices are the owner's and flags the one the copilot moved.
  await chip.getByRole("button", { name: "Swap entry and invalidation" }).click();
  await toolbarPlan.click();
  await expect(message(page)).toHaveValue(longText);
  await page.getByTestId("copilot-panel").getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("region", { name: "Proposed trade plan" });
  await expect(card.getByLabel("Entry from your drawing")).toHaveText(`Changed from your drawing: ${UPPER.toFixed(2)}`);
  await expect(card.getByLabel("Invalidation from your drawing")).toHaveText("From your drawing");
  await card.screenshot({ path: test.info().outputPath("draw-the-plan-card.png") });

  // Confirm (stubbed): the plan saves, both alerts arm, and the chart shows the plan on the drawn levels with their bells.
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  expect(lab.alerts.map((alert) => [alert.plan_role, alert.price])).toEqual([["entry", MOVED], ["invalidation", LOWER]]);
  await expect.poll(() => savedLevels(server).map((level) => [level.label, level.price])).toEqual([["Entry trigger", MOVED], ["Invalidation", LOWER]]);
  await expect(chart(page)).toHaveAttribute("data-levels", [MOVED, LOWER].map((value) => value.toFixed(2)).join(","));
  await expect(chart(page)).toHaveAttribute("data-alerts", `${MOVED.toFixed(2)}:active,${LOWER.toFixed(2)}:active`);
  await page.screenshot({ path: test.info().outputPath("draw-the-plan-confirmed-1440.png") });
});

test("one drawn zone plans as the invalidation from its edge nearest the price", async ({ page, context }) => {
  const server = await fakeChartSettings(context);
  await stubLab(page);
  await open(page, 1440, 900);
  // A zone drawn under the price, two clicks apart.
  await page.getByRole("button", { name: "Draw rectangle zone", exact: true }).click();
  const box = (await chart(page).boundingBox())!;
  const [top, bottom] = [await levelY(page, cents(LAST * 0.996)), await levelY(page, cents(LAST * 0.99))];
  await page.mouse.click(box.x + 200, box.y + top);
  await page.mouse.click(box.x + 320, box.y + bottom);
  await expect.poll(() => ((server.data?.drawings as Record<string, Drawing[]> | undefined)?.MRVL ?? []).length).toBe(1);
  const zone = (server.data!.drawings as Record<string, Drawing[]>).MRVL[0];
  const edge = cents(Math.max(...zone.points.map((point) => point.price)));

  const chip = page.getByRole("group", { name: "Plan from your drawing" });
  await expect(chip.getByRole("button", { name: `Plan this as invalidation: Long · ${edge.toFixed(2)}` })).toBeVisible();
  await expect(chip.getByRole("button", { name: "Swap entry and invalidation" })).toHaveCount(0);
  await chip.getByRole("button", { name: /^Plan this as invalidation/ }).click();
  await expect(message(page)).toHaveValue(`Context: Plan a trade: MRVL from the 5m chart, last ${LAST.toFixed(2)}. Invalidation ${edge.toFixed(2)} (the upper edge of my drawn zone), `
    + "a long. Draft the entry trigger and the plan around it; argue if it is wrong.\n\n");
});

test("on a 375 px phone the chip and swap are thumb-sized and the page never scrolls sideways", async ({ page, context }) => {
  await fakeChartSettings(context);
  await stubLab(page);
  await open(page, 375, 812);
  await addLevel(page, "Breakout", UPPER);
  await addLevel(page, "", LOWER);
  await chart(page).click({ position: { x: 150, y: await levelY(page, UPPER) } });
  const chip = page.getByRole("group", { name: "Plan from your drawing" });
  const plan = chip.getByRole("button", { name: /^Plan this:/ });
  const swap = chip.getByRole("button", { name: "Swap entry and invalidation" });
  await expect(plan).toBeVisible();
  for (const target of [plan, swap]) {
    const b = (await target.boundingBox())!;
    expect(b.height).toBeGreaterThanOrEqual(44);
    expect(b.x + b.width).toBeLessThanOrEqual(375);
  }
  expect((await swap.boundingBox())!.width).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("draw-the-plan-chip-375.png") });
  await plan.click();
  await expect(page.getByRole("dialog", { name: "Copilot" })).toBeVisible();
  await expect(message(page)).toHaveValue(longText);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});
