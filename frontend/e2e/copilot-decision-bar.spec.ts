import { expect, test, type Page } from "@playwright/test";

// The Copilot desk's decision bar and close-of-day review (docs/copilot-lab.md#the-desk). Every lab route, /today and the
// day journal are stubbed in the browser; no model runs and nothing is sent to a broker.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "11111111-1111-4111-8111-111111111111";
const DAY = "2026-10-27";
const at = (h: number, m: number) => Date.UTC(2026, 9, 27, h + 4, m) / 1000; // New York (EDT) to epoch seconds
const saved = {
  id: INV, source: "copilot", title: "Is the NBIS recovery real?", symbol: "NBIS", status: "open", conclusion: null,
  revision: 1, message_count: 2, has_findings: false, created_at: "2026-10-27T13:00:00Z", updated_at: "2026-10-27T13:05:00Z",
  transcript: [{ role: "user", content: "Is NBIS confirming?" }, { role: "assistant", content: "Not yet: it lags CRWV." }], evidence: [], findings: null,
};
// A give-back fired at 10:31 on an NBIS call whose plan holds above 85.00 (last 87.66: 85.00 is 3.0% below it).
const GIVEBACK = {
  trade_id: "44444444-4444-4444-8444-444444444444", symbol: "NBIS", contract: "NBIS 11/21/26 100C", direction: "long", quantity: 2,
  unrealized_usd: -120, unrealized_pct: -25, reasons: [{ kind: "giveback", text: "Give-back fired" }],
  invalidation: { price: 85, condition: "closes_beyond", state: "armed", distance_usd: -2.66, distance_pct: -3.1 },
  time_stop: null, latest_alert: { kind: "giveback", at: at(10, 31) },
};
const today = (asOf: string, rows: unknown[] = [GIVEBACK]) => ({
  as_of: asOf, day: DAY, quotes_at: null, quote_issue: null, act_now: { state: "ok", rows, open_positions: rows.length },
  plans: { state: "ok", rows: [], armed: 0 }, new: {}, held: { state: "ok", rows: [], count: 0 }, week: { state: "unavailable" },
});
const OPEN = "2026-10-27T14:44:00Z"; // 10:44 New York
const CLOSED = "2026-10-27T20:05:00Z"; // 16:05 New York

async function desk(page: Page, { asOf = OPEN, rows = [GIVEBACK] as unknown[], loop = { positions: [GIVEBACK] as unknown[], plans: [] as unknown[] },
  logged = [] as unknown[], symbol = "NBIS" } = {}) {
  const posts: { kind: string; text: string; symbol: string; operation_id: string }[] = [];
  const chats: unknown[] = [];
  const entries: unknown[] = [...logged];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: { as_of: asOf, positions: { state: "ok", count: 0, positions: [] },
    investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] } } }));
  await page.route("**/copilot/plans", (route) => route.fulfill({ json: { plans: [], quotes_at: null, quote_issue: null } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: { ...saved, symbol } }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route(`**/copilot/symbol/${symbol}`, (route) => route.fulfill({ json: { symbol: "NBIS", as_of: asOf,
    positions: { state: "ok", rows: loop.positions }, plans: { state: "ok", rows: loop.plans },
    new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } }, quotes_at: null, quote_issue: null } }));
  await page.route("**/today", (route) => route.fulfill({ json: today(asOf, rows) }));
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries, trade_plans: {} } }));
  await page.route(`**/day-journal/${DAY}/entries`, (route) => {
    const body = route.request().postDataJSON();
    posts.push(body);
    const row = { id: `new-${posts.length}`, day: DAY, not_traded: false, created_at: asOf === OPEN ? "2026-10-27T14:44:30Z" : "2026-10-27T20:06:00Z", actor: "owner", ...body };
    entries.push(row);
    return route.fulfill({ json: row });
  });
  await page.goto(`/copilot-lab?investigation=${INV}`);
  return { posts, chats };
}

test("Holding logs one decision after the Undo window, then the bar is one quiet line", async ({ page }) => {
  const { posts, chats } = await desk(page);
  const bar = page.getByRole("region", { name: "Decision" });
  await expect(bar).toContainText("Give-back fired at 10:31.");
  await expect(bar).toContainText("Your plan says hold while NBIS is above 85.00. It is 3.1% above.");
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("decision-bar-desktop.png") });

  await bar.getByRole("button", { name: "Holding" }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); }); // a double tap logs once
  await expect(page.getByTestId("desk-decision-pending")).toContainText("Logged holding");
  await page.waitForTimeout(3_500);
  expect(posts).toEqual([]); // still inside the Undo window
  await expect(page.getByTestId("desk-decision-logged")).toHaveText("You logged holding at 10:44. Next check: a close below 85.00.", { timeout: 4_000 });
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ kind: "decision", symbol: "NBIS",
    text: "Holding. Give-back fired at 10:31; plan says hold above 85.00 (3.1% above)." });
  expect(posts[0].operation_id).toMatch(/^decision-/);
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("decision-logged-desktop.png") });
  await page.waitForTimeout(500);
  expect(posts).toHaveLength(1);
  expect(chats).toEqual([]);
});

test("a long put's plan holds below a level above the price, and a later alert brings the bar back", async ({ page }) => {
  // A bought put: the lot is long, but the invalidation (600) sits above SPY (590), so the plan holds below it.
  const put = { ...GIVEBACK, symbol: "SPY", contract: "SPY 11/21/26 580P",
    invalidation: { price: 600, condition: "closes_beyond", state: "armed", distance_usd: 10, distance_pct: 1.7 } };
  const holding = { id: "1", operation_id: "decision-old", day: DAY, kind: "decision", symbol: "SPY", not_traded: false, actor: "owner",
    text: "Holding. Give-back fired at 10:31; plan says hold below 600.00 (1.7% below).", created_at: "2026-10-27T14:20:00Z" }; // 10:20
  await desk(page, { rows: [put], logged: [holding], symbol: "SPY" });
  const bar = page.getByRole("region", { name: "Decision" }); // the 10:31 give-back came after the 10:20 decision
  await expect(bar).toContainText("Your plan says hold while SPY is below 600.00. It is 1.7% below.");
  await bar.getByRole("button", { name: "Ask why" }).click();
  await expect(page.getByLabel("Message")).toHaveValue("Give-back fired at 10:31 on SPY; plan says hold below 600.00 (1.7% below). Should I hold or exit here, and why?");
});

test("Undo inside the window posts nothing and brings the bar back", async ({ page }) => {
  const { posts } = await desk(page);
  const bar = page.getByRole("region", { name: "Decision" });
  await bar.getByRole("button", { name: "Exiting" }).click();
  await expect(page.getByTestId("desk-decision-pending")).toContainText("Logged exiting");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(bar.getByRole("button", { name: "Holding" })).toBeVisible();
  await page.waitForTimeout(5_500);
  expect(posts).toEqual([]);
});

test("Exiting says to close it in Robinhood, and Ask why fills the message box without sending", async ({ page }) => {
  const { posts, chats } = await desk(page);
  const bar = page.getByRole("region", { name: "Decision" });
  await bar.getByRole("button", { name: "Ask why" }).click();
  await expect(page.getByLabel("Message")).toHaveValue("Give-back fired at 10:31 on NBIS; plan says hold above 85.00 (3.1% above). Should I hold or exit here, and why?");
  await bar.getByRole("button", { name: "Exiting" }).click();
  await expect(page.getByTestId("desk-decision-logged"))
    .toHaveText("You logged exiting at 10:44. Close it in Robinhood; the fill links to the plan on its own.", { timeout: 7_000 });
  expect(posts.map(p => p.text)).toEqual(["Exiting. Give-back fired at 10:31; plan says hold above 85.00 (3.1% above)."]);
  expect(chats).toEqual([]);
});

test("on a 375 px phone the two choices are full-width and thumb-sized", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { posts } = await desk(page);
  const bar = page.getByRole("region", { name: "Decision" });
  await expect(bar).toContainText("Give-back fired at 10:31.");
  const width = (await bar.boundingBox())!.width;
  for (const name of ["Holding", "Exiting"]) {
    const box = (await bar.getByRole("button", { name }).boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.width).toBeGreaterThan(width - 40);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("decision-bar-375.png") });
  await bar.getByRole("button", { name: "Holding" }).click();
  await expect(page.getByTestId("desk-decision-logged")).toBeVisible({ timeout: 7_000 });
  await page.screenshot({ path: test.info().outputPath("decision-logged-375.png") });
  expect(posts).toHaveLength(1);
});

test("after the close a position's thread asks one review question and saves the answer as a reflection", async ({ page }) => {
  const { posts } = await desk(page, { asOf: CLOSED });
  const review = page.getByRole("region", { name: "Close of day" });
  await expect(review).toContainText("Review: did you follow the plan?");
  await expect(page.getByRole("region", { name: "Decision" })).toHaveCount(0); // the review replaces the bar
  await review.getByRole("button", { name: "Answer" }).click();
  await review.getByRole("textbox").fill("Held through the give-back; it closed above 85.");
  await review.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("desk-review-done")).toHaveText("You reviewed NBIS at 16:06.");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ kind: "reflection", symbol: "NBIS", text: "Held through the give-back; it closed above 85." });
});

test("after the close a plan's thread asks whether it was added, and Skip hides the prompt", async ({ page }) => {
  const { posts } = await desk(page, { asOf: CLOSED, rows: [], loop: { positions: [], plans: [{ symbol: "NBIS", position: "waiting" }] } });
  const review = page.getByRole("region", { name: "Close of day" });
  await expect(review).toContainText("Added or not, and why?");
  await review.getByRole("button", { name: "Skip" }).click();
  await expect(review).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Close of day" })).toHaveCount(0); // skipped for the day
  expect(posts).toEqual([]);
});
