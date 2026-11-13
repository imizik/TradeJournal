import { expect, test, type Page } from "@playwright/test";

// The Feed's Scanner filter (docs/copilot-lab.md § Scanner on the desk): today's setup-scanner candidates with their
// setup, trigger, stop, target and paper result; a name he does not follow yet is marked new to him; a candidate that is
// also a Radar setup card is one row with the card's Plan it; a stale scanner greys the rows with its last bar's time.
// Tapping a row opens the ticker on the desk chart in place with the scanner's levels as thin lines. Every lab route is
// stubbed in the browser (invented numbers), so no model runs and nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const now = Math.floor(Date.now() / 1000);
const STEP = 120;
const LAST = now - (now % STEP);
const iso = (epoch: number) => new Date(epoch * 1000).toISOString().replace(/\.\d+Z$/, "Z");

function chartRead(symbol: string, around: number) {
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = around + Math.sin(i / 5);
    return { time: LAST - (59 - i) * STEP, open, high: open + 0.4, low: open - 0.4, close: open + 0.1, volume: 1000, extended: false };
  });
  return {
    symbol, timeframe: "2m", step: STEP, as_of: now, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: bars[59].close, at: bars[59].time + 60, daily: false, prev_close: around - 1, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts: [], marks: [], time_stop: null,
  };
}

const RADAR = { id: "setup-1", event_id: "rd0-nbis-up", words: "dip turning up", levels_line: "In near 94.00 · out below 92.50 (−1.6%)",
  plan_state: "none", investigation_id: null, href: "/copilot-lab?symbol=NBIS&radar=rd0-nbis-up" };
const ROWS = [
  { id: "c-crwv", symbol: "CRWV", setup: "fade", direction: "short", words: "VWAP fade (short)", bar_end: iso(now - 600), trigger: 118.4, stop: 120.15,
    target: 115.9, vwap: 116.8, range_high: 119.2, range_low: 116.3, flags: [], contract_line: "11-21 115P · Δ0.41", status: "exit", pnl: 42,
    exit_reason: "target", new: true, radar: null },
  { id: "c-nbis", symbol: "NBIS", setup: "orb", direction: "long", words: "Opening-range break (long)", bar_end: iso(now - 1800), trigger: 94.12, stop: 93.18,
    target: 96, vwap: 93.6, range_high: 94.05, range_low: 92.9, flags: [], contract_line: "11-21 95C · Δ0.46", status: "open", pnl: null,
    exit_reason: null, new: false, radar: RADAR },
];
const monitoring = (state: string) => ({ state, checked_at: iso(now), last_judged_bar_end: iso(now - 1500), symbols_judged: 12, symbols_selected: 12 });
const reply = (state = "fresh") => ({ state: "ok", day: "2026-11-13", monitoring: monitoring(state), rows: ROWS, message: null, simulated: false });

async function desk(page: Page, body: object) {
  const reads: string[] = [];
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/scanner", route => { reads.push(route.request().method()); return route.fulfill({ json: body }); });
  await page.route(/\/copilot\/desk\/symbol(:|%3A)(NBIS|CRWV)\//, route => {
    const url = new URL(route.request().url());
    const symbol = url.pathname.includes("CRWV") ? "CRWV" : "NBIS";
    return url.pathname.endsWith("/chart") ? route.fulfill({ json: chartRead(symbol, symbol === "CRWV" ? 118 : 94) })
      : route.fulfill({ json: { state: "ok", symbol, count: 0, unavailable: [], recent_days: 7, rows: [] } });
  });
  await page.route("**/copilot/desk/read", route => route.fulfill({ json: { state: "hidden" } }));
  await page.goto("/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and feed" });
  await pane.getByRole("tab", { name: "Feed" }).click();
  return { pane, reads };
}

test("the Scanner filter lists today's candidates; a row opens its ticker on the chart with the scanner's levels", async ({ page }) => {
  const { pane, reads } = await desk(page, reply());
  await pane.getByRole("button", { name: "Scanner", exact: true }).click();
  const list = pane.getByTestId("feed-scanner");
  await expect(list.getByTestId("scanner-freshness")).toContainText("Current — last judged");
  const rows = list.getByTestId("scanner-row");
  await expect(rows).toHaveCount(2);
  const crwv = rows.nth(0);
  await expect(crwv).toContainText("CRWV");
  await expect(crwv).toContainText("VWAP fade (short)");
  await expect(crwv.getByTestId("scanner-new")).toHaveText("new to you");
  await expect(crwv).toContainText("Trigger 118.40 · Stop 120.15 · Target 115.90");
  await expect(crwv).toContainText("11-21 115P · Δ0.41 · Paper: closed · Target +$42.00");
  // NBIS is also a Radar setup card: one row, the card's levels and its own Plan it; not new (he holds or watches it).
  const nbis = rows.nth(1);
  await expect(nbis.getByTestId("scanner-new")).toHaveCount(0);
  await expect(nbis.getByTestId("scanner-radar")).toHaveText("Radar setup too");
  await expect(nbis).toContainText("Radar: In near 94.00 · out below 92.50");
  await expect(nbis.getByRole("button", { name: "Plan it" })).toBeVisible();
  await expect(list).toHaveCount(1);
  // Never mixed into the other filters.
  await pane.getByRole("button", { name: "Mine + Market" }).click();
  await expect(pane.getByTestId("scanner-row")).toHaveCount(0);
  await pane.getByRole("button", { name: "Scanner", exact: true }).click();

  await crwv.getByRole("button").first().click();
  await expect(pane.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(pane.getByTestId("desk-chart").getByText("CRWV", { exact: true }).first()).toBeVisible();
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await expect(pane.getByTestId("desk-chart-guides")).toHaveText("Scan trigger 118.40 · Scan stop 120.15 · Scan target 115.90");
  await expect(pane.getByTestId("desk-chart-marks")).toContainText("Scan stop 120.15");
  // The level menu works as usual on that chart: Plan from here offers entry and invalidation.
  const canvas = pane.getByTestId("desk-chart-canvas");
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.3, { button: "right" });
  const menu = pane.getByTestId("desk-level-menu");
  await menu.getByRole("menuitem", { name: "Plan from here…" }).click();
  await expect(menu.getByRole("menuitem", { name: "Entry trigger" })).toBeVisible();
  await page.keyboard.press("Escape");
  // Another ticker drops the lines.
  await pane.getByRole("tab", { name: "Feed" }).click();
  await pane.getByRole("button", { name: "Scanner", exact: true }).click();
  await pane.getByTestId("scanner-row").nth(1).getByRole("button").first().click();
  await expect(pane.getByTestId("desk-chart-guides")).toHaveText("Scan trigger 94.12 · Scan stop 93.18 · Scan target 96.00");
  expect(reads.every(m => m === "GET")).toBe(true);
});

test("a stale scanner greys its rows with the time of its last judged bar", async ({ page }) => {
  const { pane } = await desk(page, reply("stale"));
  await pane.getByRole("button", { name: "Scanner", exact: true }).click();
  const list = pane.getByTestId("feed-scanner");
  await expect(list.getByTestId("scanner-when")).toHaveText(/^As of \d{1,2}:\d{2} [AP]M ET$/);
  await expect(list.getByTestId("scanner-freshness")).toContainText("Stale");
  await expect(list.locator("ol[data-stale]")).toHaveCount(1);
});

test("the Scanner filter is absent while the scanner is switched off, and a refused read leaves it out", async ({ page }) => {
  const { pane } = await desk(page, { state: "off", day: null, monitoring: null, rows: [], message: null, simulated: false });
  await expect(pane.getByRole("button", { name: "Mine + Market" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "Scanner", exact: true })).toHaveCount(0);
  await page.unroute("**/copilot/scanner");
  await page.route("**/copilot/scanner", route => route.fulfill({ status: 503, json: { detail: "Copilot Lab is off." } }));
  await page.reload();
  await page.getByRole("region", { name: "Chart and feed" }).getByRole("tab", { name: "Feed" }).click();
  await expect(page.getByRole("button", { name: "Mine + Market" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Scanner", exact: true })).toHaveCount(0);
});
