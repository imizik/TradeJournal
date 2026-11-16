import { expect, test, type Locator, type Page } from "@playwright/test";

// The desk's centre (docs/copilot-lab.md § The desk, Centre): the chart never leaves. It stays on top while the dock
// under it goes Position → Chain → a contract → Ticket; the Grid opens over the whole centre and Back to chart returns;
// a phone runs the chart, then the dock. Every lab route is stubbed in the browser, so no model runs, no provider is
// read and nothing reaches the e2e backend but the chart's own read.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "66666666-6666-4666-8666-666666666666";
const record = {
  id: INV, source: "copilot", title: "Which NBIS call?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-11-12T14:00:00Z", updated_at: "2026-11-12T14:00:00Z",
  transcript: [{ role: "user", content: "Which NBIS call?" }, { role: "assistant", content: "The group is bid; size small." }],
  evidence: [], findings: null,
};
const now = Math.floor(Date.now() / 1000);
const cell = (strike: number, side: "call" | "put") => {
  const mark = Math.round(((side === "call" ? Math.max(95 - strike, 0) : Math.max(strike - 95, 0)) + 2.5) * 100) / 100;
  return { symbol: `NBIS261113${side === "call" ? "C" : "P"}${String(strike * 1000).padStart(8, "0")}`, bid: mark - 0.1, ask: mark + 0.1, mark,
    last: null, spread: 0.2, spread_pct: 10, wide: false, spread_note: null, volume: 120, open_interest: 900, delta: side === "call" ? 0.5 : -0.5,
    iv: 64, quoted_at: now - 20, state: "ok", multiplier: 100, held: null, planned: false };
};
const CHAIN = {
  symbol: "NBIS", state: "ok", session: "open", poll_seconds: 15, simulated: false, root: "NBIS", centred_on: "price",
  expiries: [{ date: "2026-11-13", days: 1, kind: "weekly", held: false }], earnings: null, expiration: "2026-11-13", spot: 95.4, spot_at: now - 5,
  spot_issue: null, atm_strike: 95, fetched_at: now - 3, age_s: 3, stale: false, message: null, levels: [],
  rows: [92.5, 95, 97.5, 100, 102.5].map(strike => ({ strike, atm: strike === 95, levels: [], call: cell(strike, "call"), put: cell(strike, "put") })),
};
const PLAN = { investigation_id: INV, symbol: "NBIS", direction: "long", instrument: "calls", option_type: "call", thesis: "Reclaims VWAP with the group",
  confirmed_at: now - 600, entry: 95.9, invalidation: 92.3 };
const TICKET = {
  state: "ok", investigation_id: INV, symbol: "NBIS", direction: "long", thesis: "Reclaims VWAP with the group", option_type: "call",
  entry: 95.9, invalidation: 92.3, time_stop: "out by 15:30", plan_contract_words: "NBIS 11/13 100C",
  size: { contracts: 2, risk_usd: null, text: "2 contracts" }, simulated: false, account: "roth",
  accounts: [{ id: "roth", label: "Roth IRA", last4: "8267", kind: "roth" }],
  contract: { strike: 100, expiry: "2026-11-13", type: "call", label: "NBIS $100 Call 11/13/26", source: "picked", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: now - 30, bid: 2.4, ask: 2.6, mid: 2.5, spread: 0.2, spread_pct: 8, multiplier: 100 },
  underlying: { state: "ok", last: 95, as_of: now - 10 }, expected_move_pct: 6, limit: 2.5, contracts: 2,
};

async function desk(page: Page) {
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INV}`, route => route.fulfill({ json: record }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route(/\/copilot\/chain\?/, route => route.fulfill({ json: CHAIN }));
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [PLAN] } }));
  await page.route(/\/copilot\/tickets\/[^/?]+(\?.*)?$/, route => route.fulfill({ json: TICKET }));
  await page.route("**/copilot/desk/grid?*", route => route.fulfill({ json: { state: "ok", as_of: now, day: "2026-11-12", timeframe: "5m", step: 300, live: true, rows: {} } }));
  await page.goto(`/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("The group is bid; size small.")).toBeVisible();
  const back = page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Back to the desk" });
  if (await back.isVisible()) await back.click(); // a phone opens the link on the copilot sheet
  const ticker = page.getByTestId("desk-view-ticker");
  if (await ticker.isVisible()) await ticker.click(); // and the desk on its Book: the ticker's tools are its second view
  return page.getByRole("region", { name: "Chart and tools" });
}

/** The candles' box: on screen, and where it was. */
async function candles(page: Page) {
  const canvas = page.getByTestId("desk-chart-canvas");
  await expect(canvas).toBeInViewport();
  const box = (await canvas.boundingBox())!;
  return { top: Math.round(box.y), height: Math.round(box.height) };
}
const tab = (pane: Locator, name: string) => pane.getByRole("tablist", { name: "Centre" }).getByRole("tab", { name, exact: true });

test("the chart stays put while the dock goes Position → Chain → a contract → Ticket; the Grid comes and goes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const pane = await desk(page);
  // The desk settles first (the strip and the book read in above the centre); from then on the chart must not move.
  await expect(pane.getByTestId("desk-chain").getByRole("table")).toBeVisible();
  let at = await candles(page), still = 0;
  await expect.poll(async () => { const now = await candles(page); still = JSON.stringify(now) === JSON.stringify(at) ? still + 1 : 0; at = now; return still; },
    { intervals: [1000], timeout: 20_000 }).toBeGreaterThanOrEqual(3);
  expect(at.height).toBeGreaterThanOrEqual(200);
  // Nothing held in NBIS: the dock opens on its Chain, under the chart.
  await expect(tab(pane, "Chain")).toHaveAttribute("aria-selected", "true");
  await tab(pane, "Position").click();
  await expect(pane.getByTestId("desk-position-none")).toHaveText("No open position in NBIS. The Chain picks a contract.");
  expect(await candles(page)).toEqual(at);
  await tab(pane, "Chain").click();
  const chain = pane.getByTestId("desk-chain");
  await expect(chain.getByRole("table")).toBeVisible();
  expect(await candles(page)).toEqual(at);
  await chain.getByRole("button", { name: "100 call" }).click();
  await expect(chain.getByTestId("chain-actions")).toContainText("NBIS $100 Call 11/13/26");
  expect(await candles(page)).toEqual(at);
  await chain.getByTestId("chain-actions").getByRole("button", { name: "Put on ticket" }).click();
  await expect(tab(pane, "Ticket")).toHaveAttribute("aria-selected", "true");
  await expect(pane.getByTestId("desk-ticket")).toContainText("NBIS $100 Call 11/13/26");
  expect(await candles(page)).toEqual(at); // the chart never moved
  // The dock scrolls on its own; the page and the chart stay.
  const panel = pane.getByTestId("dock-panel");
  await panel.evaluate(el => { el.scrollTop = el.scrollHeight; });
  expect(await candles(page)).toEqual(at);

  // Grid: a button beside the dock's tabs, over the whole centre, and Back to chart puts the chart and the Ticket back.
  await pane.getByRole("button", { name: "Grid", exact: true }).click();
  await expect(page.getByTestId("desk-grid")).toBeVisible();
  await expect(page.getByTestId("desk-chart-canvas")).toHaveCount(0);
  await pane.getByRole("button", { name: "Back to chart" }).click();
  await expect(page.getByTestId("desk-grid")).toHaveCount(0);
  expect(await candles(page)).toEqual(at);
  await expect(tab(pane, "Ticket")).toHaveAttribute("aria-selected", "true");
  // The keys: G opens the Grid, C comes back to the chart; O and L open the Chain and Check a call under it.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("g");
  await expect(page.getByTestId("desk-grid")).toBeVisible();
  await page.keyboard.press("c");
  await expect(page.getByTestId("desk-chart-canvas")).toBeVisible();
  await page.keyboard.press("o");
  await expect(tab(pane, "Chain")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("l");
  await expect(tab(pane, "Check a call")).toHaveAttribute("aria-selected", "true");
  expect(await candles(page)).toEqual(at);
});

test("the splitter gives the chart more room and is kept for this browser", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await desk(page);
  const before = await candles(page);
  const splitter = page.getByTestId("dock-splitter");
  await splitter.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await candles(page)).height).toBeGreaterThan(before.height + 20);
  const grown = await candles(page);
  await page.reload();
  const back = page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Back to the desk" });
  if (await back.isVisible()) await back.click();
  await expect.poll(async () => (await candles(page)).height).toBe(grown.height);
});

test("a phone: the chart first, its candles inside the first screen, then the dock's tabs and content", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const pane = await desk(page);
  const at = await candles(page);
  expect(at.top).toBeLessThan(812 / 2); // the candles start in the first screen's top half
  const tabs = (await pane.getByRole("tablist", { name: "Centre" }).boundingBox())!;
  expect(tabs.y).toBeGreaterThan(at.top + at.height - 1); // the dock comes after the chart
  await tab(pane, "Chain").click();
  await expect(pane.getByTestId("desk-chain").getByRole("table")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
