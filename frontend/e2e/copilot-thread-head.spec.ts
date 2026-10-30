import { expect, test, type Page } from "@playwright/test";

// The desk's thread header and plan ladder above the conversation. Every lab route is stubbed in the browser (the e2e
// backend runs with the lab off), so no model runs and nothing is sent. The clock is fixed at 11:00 ET on Oct 23 2026.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NBIS = "11111111-1111-4111-8111-111111111111";
const CRWV = "22222222-2222-4222-8222-222222222222";
const APLD = "33333333-3333-4333-8333-333333333333";
const IREN = "44444444-4444-4444-8444-444444444444";
const NOW = new Date("2026-10-23T15:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const NBIS_THESIS = "The recovery is real only if NBIS keeps pace with its group, not just the tape, through the financing headlines and the Nov earnings.";
const PLANS = {
  quotes_at: epoch("2026-10-23T14:59:50Z"), quote_issue: null,
  plans: [
    { investigation_id: NBIS, symbol: "NBIS", direction: "long", thesis: NBIS_THESIS, last: 87.74,
      entry: { price: 88.1, condition: "crosses", interval: null, state: "hit", hit_at: epoch("2026-10-23T13:41:00Z") },
      invalidation: { price: 85, condition: "closes_beyond", interval: "15m", state: "armed", distance_usd: -2.74, distance_pct: -3.12 },
      time_stop: null, position: "in_position" },
    { investigation_id: CRWV, symbol: "CRWV", direction: "long", thesis: "Capacity deals keep the group bid", last: 134.19,
      entry: { price: 126.95, condition: "crosses", interval: null, state: "hit", hit_at: epoch("2026-10-12T14:00:00Z") },
      invalidation: { price: 122, condition: "crosses", interval: null, state: "armed", distance_usd: -12.19, distance_pct: -9.08 },
      time_stop: { text: "out by 14:30", due_at: epoch("2026-10-23T18:30:00Z"), state: "pending" }, position: "in_position" },
    { investigation_id: APLD, symbol: "APLD", direction: "long", thesis: "A reclaim of the morning high", last: 30.62,
      entry: { price: 31.2, condition: "crosses", interval: null, state: "armed", distance_usd: 0.58, distance_pct: 1.89 },
      invalidation: { price: 29.8, condition: "crosses", interval: null, state: "armed", distance_usd: -0.82, distance_pct: -2.68 },
      time_stop: null, position: "waiting" },
  ],
};
const plan = (invalidation: number, thesis: string) => ({ setup: "Copilot plan", thesis, timing: "pre_entry",
  invalidation: { price: invalidation, condition: "crosses", state: "armed" }, time_stop: null });
const POSITIONS = {
  count: 3, quotes_at: null, quote_issue: null,
  positions: [
    // An older NBIS position under another plan comes first, so the match has to use the invalidation.
    { trade_id: "t-old", symbol: "NBIS", contract: "NBIS 11/21/26 95C", instrument: "option", direction: "long", quantity: 1,
      option: { side: "call", strike: 95, expiry: "2026-11-21" }, mark: 610, avg_entry: 500, days_held: 9,
      unrealized_usd: 110, unrealized_pct: 22, giveback: null, latest_alert: null, plan: plan(80, "older"), link_path: null, plan_path: null },
    { trade_id: "t-nbis", symbol: "NBIS", contract: "NBIS 11/21/26 100C", instrument: "option", direction: "long", quantity: 2,
      option: { side: "call", strike: 100, expiry: "2026-11-21" }, mark: 314, avg_entry: 421, days_held: 0,
      unrealized_usd: -214, unrealized_pct: -25.4, giveback: "fired", latest_alert: null, plan: plan(85, NBIS_THESIS), link_path: null, plan_path: null },
    { trade_id: "t-crwv", symbol: "CRWV", contract: "CRWV stock", instrument: "stock", direction: "long", quantity: 40,
      option: null, mark: 134.19, avg_entry: 126.95, days_held: 11,
      unrealized_usd: 289.6, unrealized_pct: 5.7, giveback: null, latest_alert: null, plan: plan(122, "Capacity deals keep the group bid"), link_path: null, plan_path: null },
  ],
};
const THREADS = { as_of: "2026-10-23T15:00:00Z", positions: { state: "ok", count: 0, positions: [] },
  investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] } };
const saved = (id: string, symbol: string) => ({
  id, source: "copilot", title: `${symbol} plan`, symbol, status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: `Plan a trade: ${symbol}` }, { role: "assistant", content: `A plan for ${symbol}.` }],
});

async function lab(page: Page, id: string) {
  const chats: unknown[] = [];
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/plans", (route) => route.fulfill({ json: PLANS }));
  await page.route("**/copilot/plans/positions", (route) => route.fulfill({ json: POSITIONS }));
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  for (const [inv, symbol] of [[NBIS, "NBIS"], [CRWV, "CRWV"], [APLD, "APLD"], [IREN, "IREN"]])
    await page.route(`**/copilot/investigations/${inv}`, (route) => route.fulfill({ json: saved(inv, symbol) }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto(`/copilot-lab?investigation=${id}`);
  return { chats };
}

const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });

test("an option: its own mark and P&L, the underlying labelled, and the plan ladder on the underlying", async ({ page }) => {
  const { chats } = await lab(page, NBIS);
  const head = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(head).toContainText("In position");
  await expect(head).toContainText("100C · Nov 21 · 29 days left");
  await expect(head.getByRole("heading", { name: "NBIS" })).toBeVisible();
  const thesis = head.getByText(NBIS_THESIS);
  await expect(thesis).toHaveAttribute("title", NBIS_THESIS);
  expect(await thesis.evaluate(el => getComputedStyle(el).textOverflow)).toBe("ellipsis");

  // The option's mark (a share: 314 a contract) and its P&L, never beside the underlying's price without the label.
  const priceBlock = head.getByTestId("thread-price");
  await expect(priceBlock).toContainText("option mark3.14−25.4%");
  await expect(priceBlock).toContainText("NBIS 87.74 · underlying");
  await expect(priceBlock).not.toContainText("610"); // the older NBIS position is not this plan's
  await expect(priceBlock.getByText("NBIS 87.74 · underlying")).toBeVisible();

  const ladder = conversation(page).getByRole("region", { name: "Plan ladder" });
  await expect(ladder).toContainText("Plan · NBIS levels (underlying)");
  await expect(ladder).toContainText("3.1% above invalidation");
  await expect(ladder).toContainText("−0.12R on NBIS");
  for (const tick of ["85.00Invalidation", "88.10Entry · hit", "91.201R", "94.302R", "87.74"]) await expect(ladder).toContainText(tick);
  await expect(ladder).toContainText("No time stop · expires Nov 21 · 29 days");
  await expect(ladder).not.toContainText("Target");
  // Secondary numbers wait behind Details.
  const details = ladder.getByText("Entry premium");
  await expect(details).toBeHidden();
  await ladder.getByText("Details").click();
  await expect(ladder).toContainText("Entry premium4.21");
  await expect(ladder).toContainText("Size2 contracts");
  await expect(ladder).toContainText("Invalidation alertcloses beyond 85.00 (15m) · armed");
  await page.screenshot({ path: test.info().outputPath("thread-head-option-desktop.png") });
  expect(chats).toEqual([]);
});

test("a stock: last price and P&L with the average cost, a time stop under the ladder", async ({ page }) => {
  await lab(page, CRWV);
  const head = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(head).toContainText("In position");
  await expect(head).toContainText("Stock · held 11 days");
  const priceBlock = head.getByTestId("thread-price");
  await expect(priceBlock).toContainText("134.19+5.7%");
  await expect(priceBlock).toContainText("Avg cost 126.95");
  await expect(priceBlock).not.toContainText("underlying");
  await expect(priceBlock).not.toContainText("option mark");
  const ladder = conversation(page).getByRole("region", { name: "Plan ladder" });
  await expect(ladder).toContainText("Plan9.1% above invalidation");
  await expect(ladder).toContainText("+1.46R");
  await expect(ladder).toContainText("Time stop 14:30");
});

test("an armed plan not yet entered shows no position; a thread with no plan shows only the header", async ({ page }) => {
  await lab(page, APLD);
  const head = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(head).toContainText("Armed");
  await expect(head).toContainText("Long plan · waiting for entry");
  await expect(head.getByTestId("thread-price")).toContainText("last30.62");
  await expect(conversation(page).getByRole("region", { name: "Plan ladder" })).toContainText("2.7% above invalidation");

  await page.goto(`/copilot-lab?investigation=${IREN}`);
  const bare = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(bare).toContainText("Not planned");
  await expect(bare).toContainText("No plan yet");
  await expect(bare.getByRole("heading", { name: "IREN" })).toBeVisible();
  await expect(conversation(page).getByRole("region", { name: "Plan ladder" })).toHaveCount(0);
});

test("a position the copilot adopted: its row and header say Adopted while the plan is a draft", async ({ page }) => {
  const SOUN = "55555555-5555-4555-8555-555555555555";
  await lab(page, SOUN);
  await page.route(`**/copilot/investigations/${SOUN}`, (route) => route.fulfill({ json: { ...saved(SOUN, "SOUN"), title: "Adopted: SOUN 12C" } }));
  await page.route("**/copilot/plans/positions", (route) => route.fulfill({ json: { ...POSITIONS, count: 4, positions: [...POSITIONS.positions,
    { trade_id: "t-soun", symbol: "SOUN", contract: "SOUN 10/24/26 12C", instrument: "option", direction: "long", quantity: 3,
      option: { side: "call", strike: 12, expiry: "2026-10-24" }, mark: 95, avg_entry: 80, days_held: 0, unrealized_usd: 45,
      unrealized_pct: 18.8, giveback: null, latest_alert: null, plan: null, link_path: null, plan_path: null }] } }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: {
    as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null, sections: {}, day: { phase: "regular", need_you: 0, streak: null },
    plans: [], threads: [{ key: "trade:t-soun", group: "watch", symbol: "SOUN", title: "SOUN 10/24/26 12C", instrument: "10/24/26 12C",
      value: null, status: { text: "Adopted · draft plan to confirm", tone: "info" }, meter: null, investigation_id: SOUN, trade_id: "t-soun",
      radar_event_id: null, path: null, changed_at: null, horizon: "day", close: null, fill_to_link: null, adopted: true }] } }));
  await page.reload();
  await expect(page.getByText("Adopted · draft plan to confirm").first()).toBeVisible();
  const head = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(head).toContainText("Adopted");
  await expect(head).not.toContainText("In position");
  await expect(head).toContainText("12C · Oct 24 · 1 day left");
  await expect(head.getByTestId("thread-price")).toContainText("option mark0.95+18.8%");
  await page.screenshot({ path: test.info().outputPath("thread-head-adopted.png") });
});

test("the header and ladder fit a 375 px phone, the underlying still labelled", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, NBIS);
  const head = conversation(page).getByRole("group", { name: "Thread header" });
  await expect(head).toBeInViewport();
  await expect(head.getByTestId("thread-price")).toContainText("NBIS 87.74 · underlying");
  const ladder = conversation(page).getByRole("region", { name: "Plan ladder" });
  await expect(ladder).toContainText("3.1% above invalidation");
  const box = (await ladder.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(375);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("thread-head-option-375.png"), fullPage: true });
});
