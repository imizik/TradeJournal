import { expect, test, type Page } from "@playwright/test";

// The lab home's Plans board. Every lab route is stubbed in the browser (the e2e backend runs with the lab off), so no
// model runs and nothing is sent. The page's clock is fixed at 11:00 ET on Oct 23 2026 so "hit at 10:41" reads the same.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NBIS = "11111111-1111-4111-8111-111111111111";
const CRWV = "22222222-2222-4222-8222-222222222222";
const NOW = new Date("2026-10-23T15:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const PLANS = {
  quotes_at: epoch("2026-10-23T14:59:50Z"), quote_issue: null,
  plans: [
    { investigation_id: CRWV, symbol: "CRWV", direction: "short", thesis: "Fails at the gap; group rolling over", last: 100,
      entry: { price: 99, condition: "crosses", interval: null, state: "armed", distance_usd: -1, distance_pct: -1 },
      invalidation: { price: 103, condition: "crosses", interval: null, state: "armed", distance_usd: 3, distance_pct: 3 },
      time_stop: null, position: "waiting" },
    { investigation_id: NBIS, symbol: "NBIS", direction: "long", thesis: "Reclaims VWAP with the neocloud group confirming", last: 94,
      entry: { price: 95.9, condition: "crosses", interval: null, state: "hit", hit_at: epoch("2026-10-23T14:41:00Z") },
      invalidation: { price: 92.3, condition: "crosses", interval: null, state: "armed", distance_usd: -1.7, distance_pct: -1.81 },
      time_stop: { text: "out by 15:30", due_at: epoch("2026-10-23T19:30:00Z"), state: "pending" }, position: "in_position" },
  ],
};
const THREADS = { as_of: "2026-10-23T15:00:00Z", positions: { state: "ok", count: 0, positions: [] },
  investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] } };
const saved = {
  id: NBIS, source: "copilot", title: "NBIS plan", symbol: "NBIS", status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: "Plan a trade: NBIS" }, { role: "assistant", content: "Plan: enter above 95.90, out under 92.30." }],
};

async function lab(page: Page, plans: unknown = PLANS) {
  const chats: unknown[] = [];
  let reads = 0;
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/plans", (route) => { reads += 1; return route.fulfill({ json: plans }); });
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${NBIS}`, (route) => route.fulfill({ json: saved }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto("/copilot-lab");
  return { chats, reads: () => reads };
}

test("the Plans board sits above Open threads, nearest trigger first, and refreshes each minute", async ({ page }) => {
  const { chats, reads } = await lab(page);
  const board = page.getByRole("region", { name: "Plans" });
  await expect(board).toContainText("2 armed · nearest trigger first");
  const rows = board.getByRole("listitem");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("CRWV");
  await expect(rows.nth(0)).toContainText("short");
  await expect(rows.nth(0)).toContainText("Fails at the gap; group rolling over");
  await expect(rows.nth(0)).toContainText("Entry 99.00 −1.0% (−$1.00)");
  await expect(rows.nth(0)).toContainText("Invalidation 103.00 +3.0% (+$3.00)");
  await expect(rows.nth(0)).toContainText("Waiting for entry");
  await expect(rows.nth(1)).toContainText("NBIS");
  await expect(rows.nth(1)).toContainText("last 94.00");
  await expect(rows.nth(1)).toContainText("Entry 95.90 · hit at 10:41");
  await expect(rows.nth(1)).toContainText("Invalidation 92.30 −1.8% (−$1.70)");
  await expect(rows.nth(1)).toContainText("Time stop 15:30");
  await expect(rows.nth(1)).toContainText("In position");
  const above = await board.boundingBox();
  const threads = await page.getByRole("region", { name: "Open threads" }).boundingBox();
  expect(above!.y).toBeLessThan(threads!.y);
  expect(reads()).toBe(1);
  await board.screenshot({ path: test.info().outputPath("plans-board-desktop.png") });

  await page.clock.fastForward(61_000);
  await expect.poll(reads).toBe(2);
  expect(chats).toEqual([]);
});

test("a tap opens that plan's investigation in place, sending nothing", async ({ page }) => {
  const { chats } = await lab(page);
  const board = page.getByRole("region", { name: "Plans" });
  const row = board.getByRole("link", { name: "NBIS plan" });
  await expect(row).toHaveAttribute("href", `/copilot-lab?investigation=${NBIS}`);
  await row.click();
  await expect(page.getByText("Plan: enter above 95.90, out under 92.30.")).toBeVisible();
  await expect(board).toHaveCount(0);
  expect(chats).toEqual([]);
});

test("with nothing armed, one line and the Plan a trade button", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, { plans: [], quotes_at: null, quote_issue: null });
  const board = page.getByRole("region", { name: "Plans" });
  await expect(board).toContainText("No armed plans. Plan the next one before you enter.");
  const plan = board.getByRole("link", { name: "Plan a trade" });
  await expect(plan).toHaveAttribute("href", /\/copilot-lab\?.*context=Plan\+a\+trade/);
  expect((await plan.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("the board fits a 375 px phone with thumb-sized rows", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page);
  const board = page.getByRole("region", { name: "Plans" });
  await expect(board.getByRole("listitem")).toHaveCount(2);
  for (const name of ["CRWV plan", "NBIS plan"]) {
    const box = (await board.getByRole("link", { name }).boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
  }
  await expect(board.getByRole("link", { name: "CRWV plan" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("plans-board-375.png"), fullPage: true });
});

test("no Plans board while the lab is off", async ({ page }) => {
  let reads = 0;
  await page.route("**/copilot/plans", (route) => { reads += 1; return route.fulfill({ json: PLANS }); });
  await page.goto("/copilot-lab");
  await expect(page.getByText(/Copilot Lab is off/)).toBeVisible(); // the e2e backend's own answer
  await expect(page.getByRole("region", { name: "Plans" })).toHaveCount(0);
  expect(reads).toBe(0);
});
