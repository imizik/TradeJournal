import { expect, test, type Page } from "@playwright/test";
import type { ChartData, Interval } from "../lib/charts";
import { realisticPanels } from "./fixtures/realisticBars";

// The Charts dock's Copilot tab above the conversation: the chart symbol's position, armed plans and what is new
// (GET /copilot/symbol/{symbol}), each opening in the panel itself, and "Plan a trade" with the chart's own context.
// Every lab route is stubbed in the browser (the e2e backend keeps the lab off) and a turn is a fixed SSE stream.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const TRADE = "77777777-7777-4777-8777-777777777777";
const PLAN_A = "88888888-8888-4888-8888-888888888888";
const PLAN_B = "99999999-9999-4999-8999-999999999999";
const level = (price: number, distance_pct: number) => ({ price, condition: "crosses", interval: null, state: "armed", distance_usd: 1, distance_pct });
const LOOP = {
  symbol: "MRVL", as_of: "2026-10-26T15:00:00Z", quotes_at: 1792000000, quote_issue: null,
  positions: { state: "ok", rows: [{
    trade_id: TRADE, symbol: "MRVL", contract: "MRVL 11/21/26 100C", instrument: "option", direction: "long", quantity: 2,
    unrealized_usd: 140, unrealized_pct: 18, giveback: "armed", latest_alert: null, link_path: null, plan_path: null,
    plan: { setup: "Copilot plan", thesis: "Leads the group", timing: "pre_entry", invalidation: level(92.3, -1.8),
      time_stop: { text: "out by 15:30", due_at: 1792000000, clock: "15:30", state: "pending", minutes_left: 30 } },
  }] },
  plans: { state: "ok", rows: [
    { investigation_id: PLAN_A, symbol: "MRVL", direction: "long", thesis: "Reclaims VWAP with the group", last: 94,
      entry: level(95.9, 2.0), invalidation: level(91.5, -2.7), time_stop: { text: "out by 15:30", due_at: 1792000000, state: "pending" }, position: "waiting" },
    { investigation_id: PLAN_B, symbol: "MRVL", direction: "short", thesis: "Fails at the prior high", last: 94,
      entry: level(92.8, -1.3), invalidation: level(97.2, 3.4), time_stop: null, position: "waiting" },
  ] },
  new: { radar: { state: "ok", count: 1, rows: [{ event_id: "ev-1", summary: "MRVL up 3.1% vs SMH", first_seen_at: "2026-10-26T14:41:00Z" }] },
    thesis: { state: "ok", count: 0, rows: [] } },
};
const record = (id: string, transcript: { role: string; content: string }[]) => ({
  id, source: "copilot", title: transcript[0].content, symbol: "MRVL", status: "open", conclusion: null, revision: 1,
  message_count: transcript.length, has_findings: false, created_at: "2026-10-26T14:00:00Z", updated_at: "2026-10-26T14:05:00Z",
  transcript, evidence: [], findings: null,
});
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const DONE = { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
  usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } };

/** Candles for MRVL with an automatic level each side of the last close; returns that close. */
async function stubLab(page: Page, reads: string[], chat = sse([{ type: "text", delta: "Noted." }, DONE])) {
  let last = 0;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const intervals = (query.get("intervals") ?? "5m").split(",") as Interval[];
    const now = Math.floor(Date.now() / 1000);
    const panels = realisticPanels(intervals);
    last = panels[intervals[0]]!.bars.at(-1)!.close;
    const zone = (id: string, at: number, label: string) => ({ id, low: at, high: at, label, score: 1, members: [{ kind: "prior_day", label, price: at,
      evidence: "observed", timeframe: "1D", source: "tradier", bar_time: null, formed_at: null, developing: false }] });
    const data = { symbol: "MRVL", session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now },
      panels, quotes: [], issues: [], adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {},
        dividends: "unsupported", dividends_note: "Dividends are not adjusted.", warnings: [] },
      intraday_as_of: now - 60, history_note: "Synthetic chart data.", fills: [], fills_truncated: false, extras: {},
      auto_levels: { day: "2026-10-26", as_of: now, atr: 3, band: 0.3, missing: {},
        zones: [zone("a", Math.round(last * 1.02 * 100) / 100, "Prior day high"), zone("b", Math.round(last * 0.98 * 100) / 100, "Prior day low"),
          zone("c", Math.round(last * 1.06 * 100) / 100, "Week high")] } } as unknown as ChartData;
    return route.fulfill({ json: data });
  });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/symbol/*", (route) => { reads.push(new URL(route.request().url()).pathname); return route.fulfill({ json: LOOP }); });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1)!;
    return route.fulfill({ json: record(id, [{ role: "user", content: "Plan MRVL long over 95.90" }, { role: "assistant", content: "Armed: entry 95.90, invalidation 91.50." }]) });
  });
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: record(PLAN_A, route.request().postDataJSON().transcript) }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: chat }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  return () => last;
}

async function openPanel(page: Page) {
  await page.goto("/charts?symbol=MRVL");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  await page.getByRole("button", { name: "Copilot", exact: true }).click();
  const panel = page.getByTestId("copilot-panel");
  await expect(panel.getByTestId("copilot-loop")).toBeVisible();
  return panel;
}

/** A dock section's one-line header (its fold button). */
const header = (panel: ReturnType<Page["getByTestId"]>, name: string) => panel.getByRole("region", { name }).locator("h2 button[aria-expanded]");

test("the symbol's position, plans and what is new sit above the conversation and open in the panel", async ({ page }) => {
  const reads: string[] = [];
  await stubLab(page, reads);
  await page.setViewportSize({ width: 1440, height: 900 });
  const panel = await openPanel(page);
  await expect(header(panel, "MRVL open position")).toHaveText(/Position\s*1/);
  await expect(header(panel, "MRVL armed plans")).toHaveText(/Armed plans\s*2/);
  await expect(header(panel, "New on MRVL since you looked")).toHaveText(/New since you looked\s*1/);
  expect(reads).toEqual(["/api/backend/copilot/symbol/MRVL"]);

  // The position: contract, P&L, invalidation distance, time stop and give-back; one tap is its review, here.
  const position = panel.getByRole("button", { name: "Review MRVL 11/21/26 100C" });
  await expect(position).toContainText("+$140 · +18%");
  await expect(position).toContainText("Invalidation 92.30 · 1.8% away");
  await expect(position).toContainText("Time stop 15:30 · 30 min");
  await expect(position).toContainText("Give-back armed");
  await page.screenshot({ path: test.info().outputPath("charts-copilot-loop-1440.png") });
  await position.click();
  await expect(panel.getByLabel("Message")).toHaveValue(`Context: Review this position: ${TRADE}\n\n`);
  await expect(page).toHaveURL(/\/charts\?symbol=MRVL/);

  // Typing never reads the loop again; only the minute's refresh does.
  await panel.getByLabel("Message").pressSequentially(" How is it?");
  expect(reads).toHaveLength(1);

  // The plans are folded by default; a plan opens its investigation in the panel.
  await expect(panel.getByRole("button", { name: "Open the MRVL plan (long)" })).toHaveCount(0);
  await header(panel, "MRVL armed plans").click();
  const plan = panel.getByRole("button", { name: "Open the MRVL plan (long)" });
  await expect(plan).toContainText("Entry 95.90 · 2.0% away");
  await expect(plan).toContainText("Invalidation 91.50 · 2.7% away");
  await plan.click();
  await expect(panel.getByText("Armed: entry 95.90, invalidation 91.50.")).toBeVisible();
  await expect(page).toHaveURL(/\/charts\?symbol=MRVL/);

  // What is new: one line, asked about in the panel with its Radar origin.
  // Words the owner typed stay under the new context line.
  await panel.getByLabel("Message").fill("Is it extended?");
  await panel.getByRole("button", { name: /Radar .*MRVL up 3\.1% vs SMH/ }).click();
  await expect(panel.getByLabel("Message")).toHaveValue(/^Context: Radar \d+:\d\d [AP]M: MRVL up 3\.1% vs SMH\n\nIs it extended\?$/);

  // Folds are remembered on this device.
  await header(panel, "MRVL open position").click();
  await expect(position).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  if (!(await page.getByTestId("copilot-loop").isVisible())) await page.getByRole("button", { name: "Copilot", exact: true }).click();
  await expect(page.getByTestId("copilot-loop")).toBeVisible();
  await expect(header(page.getByTestId("copilot-panel"), "MRVL open position")).toHaveAttribute("aria-expanded", "false");
  await expect(header(page.getByTestId("copilot-panel"), "MRVL armed plans")).toHaveAttribute("aria-expanded", "true");
});

test("Plan a trade fills the box with the chart's interval, last price and nearest automatic levels, unsent", async ({ page }) => {
  const reads: string[] = [];
  const last = await stubLab(page, reads);
  await page.setViewportSize({ width: 1440, height: 900 });
  const panel = await openPanel(page);
  await panel.getByRole("button", { name: "Plan a trade" }).click();
  const close = last().toFixed(2);
  const value = await panel.getByLabel("Message").inputValue();
  expect(value).toContain(`Context: Plan a trade: MRVL from the 5m chart at ${close}`);
  expect(value).toMatch(/nearest automatic levels: above [\d.,]+ \(Prior day high\), below [\d.,]+ \(Prior day low\)\n\n$/);
  expect(value).not.toContain("Week high");
  await expect(page).toHaveURL(/\/charts\?symbol=MRVL/);
});

test("the plan card's contract pick list fits the narrow dock", async ({ page }) => {
  const candidates = { symbol: "MRVL", direction: "long", simulated: false, picks: [
    { label: "Nov 6 '26 95C", days: 14, ask_contract: 565 }, { label: "Nov 13 '26 95C", days: 21, ask_contract: 692 },
    { label: "Nov 20 '26 95C", days: 28, ask_contract: 799 }] };
  const plan = { id: "p1", kind: "trade_plan", symbol: "MRVL", direction: "long", instrument: "calls", contract: "Nov 21 100C",
    thesis: "MRVL reclaims the level overhead with its group.", entry_trigger: { condition: "closes_beyond", price: 95.9, interval: "5m" },
    invalidation: { condition: "crosses", price: 92.3, interval: null }, time_stop: "out by 15:30", size_note: "one starter", last: 94.35, as_of: "2026-10-26T14:00:00Z" };
  const turn = sse([
    { type: "tool", id: "o1", name: "get_option_candidates", status: "ok", summary: "3 calls", ms: 1, input: { symbol: "MRVL", horizon_days: 21, direction: "long" },
      provenance: { source: "Tradier option chains", kind: "fetched", as_of: "2026-10-26T14:00:00Z" }, candidates },
    { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
    { type: "proposal", ...plan }, { type: "text", delta: "MRVL plan (draft)." }, DONE,
  ]);
  await stubLab(page, [], turn);
  await page.setViewportSize({ width: 1440, height: 900 });
  const panel = await openPanel(page);
  await panel.getByRole("button", { name: "Plan a trade" }).click();
  await panel.getByRole("button", { name: "Send" }).click();
  const card = panel.getByRole("region", { name: "Proposed trade plan" });
  const select = card.locator("label", { hasText: "Contract" }).locator("select");
  await select.scrollIntoViewIfNeeded();
  await expect(select).toBeVisible();
  const [box, side] = [(await select.boundingBox())!, (await panel.boundingBox())!];
  expect(box.x).toBeGreaterThanOrEqual(side.x);
  expect(box.x + box.width).toBeLessThanOrEqual(side.x + side.width + 1);
  await select.selectOption("Nov 13 '26 95C");
  await expect(card).toContainText("Nov 13 '26 95C");
  expect(await panel.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await card.screenshot({ path: test.info().outputPath("charts-copilot-plan-card-dock.png") });
});

test("on a 375 px phone the three headers fit the sheet with thumb-sized targets", async ({ page }) => {
  await stubLab(page, []);
  await page.setViewportSize({ width: 375, height: 812 });
  const panel = await openPanel(page);
  await expect(page.getByRole("dialog", { name: "Copilot" })).toBeVisible();
  for (const name of ["MRVL open position", "MRVL armed plans", "New on MRVL since you looked"]) {
    const box = (await header(panel, name).boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
  }
  expect((await panel.getByRole("button", { name: "Plan a trade" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect((await panel.getByRole("button", { name: "Review MRVL 11/21/26 100C" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("charts-copilot-loop-375.png") });
});
