import { expect, test, type Page } from "@playwright/test";

// The practice goal: Review my week proposes one thing to practice as a card; the owner edits the text, Confirm posts it
// to /copilot/practice (and a lesson memory only when "Remember this too" is ticked), and the goal's line appears under
// Review my week on the lab home and on the Dashboard's button. The e2e backend runs with the lab off, so these tests
// stand in for its status read and its lab routes.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DESK = { as_of: "2026-10-24T15:12:00Z", quotes_at: null, quote_issue: null,
  day: { phase: "closed", need_you: 0, streak: null }, sections: {}, threads: [] };
const INVESTIGATION = "33333333-3333-4333-8333-333333333333";
const PROPOSAL = {
  type: "proposal", id: "fake_3_0", kind: "practice", text: "Exit within 15 minutes when my plan's invalidation breaks.",
  measure: "exit_at_invalidation", label: "exit at my invalidation", target: 1,
  why: "2 of 3 invalidation hits this week were held past 15 minutes.",
};
const TURN = [
  { type: "tool", id: "fake_1_0", name: "get_week_review", input: {}, status: "ok", summary: "week of 2026-10-19: 12 trades",
    provenance: { source: "SIMULATED fixture", kind: "simulated", as_of: "2026-10-23T15:12:00Z", state: "ok" } },
  { type: "tool", id: "fake_3_0", name: "propose_plan", input: {}, status: "ok", summary: "proposed practice (exit_at_invalidation)",
    provenance: { source: "A proposal", kind: "proposal", as_of: null, state: "ok" } },
  PROPOSAL,
  { type: "text", delta: "**Week of 2026-10-19**: 12 trades. To practice next week: exiting at the invalidation." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 3,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const SCORE = { week_start: "2026-10-26", hit: 2, of: 3, text: "2 of 3", of_what: "invalidation pings followed by an exit within 15 min",
  share: 0.67, met: false, source: "invalidation pings" };

async function labOn(page: Page) {
  const posts: { practice: Record<string, unknown>[]; memories: Record<string, unknown>[] } = { practice: [], memories: [] };
  let now: { goal: Record<string, unknown> | null; this_week: typeof SCORE | null } = { goal: null, this_week: null };
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: {
    id: INVESTIGATION, source: "copilot", title: "Review my week", symbol: null, status: "open", conclusion: null,
    revision: 1, message_count: 2, has_findings: false, created_at: "2026-10-24T15:12:00Z", updated_at: "2026-10-24T15:12:00Z",
    transcript: [], evidence: [], findings: null } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/practice", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      posts.practice.push(body);
      // Confirmed on the weekend: it starts Monday. The next read (a later page load) is mid-week, with a score.
      const goal = { text: body.text, measure: body.measure, label: "exit at my invalidation", target: body.target,
        week_start: "2026-10-26", since: "2026-10-25T15:00:00Z" };
      const confirmed = { goal, this_week: null };
      now = { goal, this_week: SCORE };
      return route.fulfill({ status: 201, json: confirmed });
    }
    return route.fulfill({ json: now });
  });
  await page.route("**/jo/memories", (route) => {
    posts.memories.push(route.request().postDataJSON());
    return route.fulfill({ status: 201, json: { id: "r1", memory_id: "m1", revision: 1 } });
  });
  return posts;
}

async function reviewToCard(page: Page) {
  await page.goto("/copilot-lab");
  const home = page.getByRole("navigation", { name: "Thread list" });
  await expect(home.getByTestId("desk-day")).toBeVisible();
  await expect(home).not.toContainText("Practicing:");
  const saved = page.waitForRequest((request) => request.url().endsWith("/copilot/investigations") && request.method() === "POST");
  await home.getByRole("button", { name: "Review my week" }).click();
  const card = page.getByRole("region", { name: "Proposed practice" });
  await expect(card).toBeVisible();
  await saved;
  return card;
}

test("a practice card is edited, confirmed, remembered, and its line appears on the lab home and the Dashboard", async ({ page }) => {
  const posts = await labOn(page);
  const card = await reviewToCard(page);
  await expect(card).toContainText("exit at my invalidation, target 100%");
  await expect(card).toContainText("Why: 2 of 3 invalidation hits this week were held past 15 minutes.");
  await expect(card.getByText("Confirm replaces any practice you have now.")).toBeVisible();
  const box = card.getByLabel("Practice text");
  await expect(box).toHaveValue(PROPOSAL.text);
  await box.fill("Be out within 15 minutes when my invalidation breaks, every time.");
  await card.getByLabel(/Remember this too/).check();
  await page.screenshot({ path: test.info().outputPath("practice-card.png") });
  await card.getByRole("button", { name: "Confirm" }).click();

  await expect(card.getByRole("status")).toContainText("Practicing: exit at my invalidation · starts Mon, Oct 26");
  await expect(card.getByRole("status")).toContainText("Also remembered as a lesson.");
  expect(posts.practice).toEqual([{ text: "Be out within 15 minutes when my invalidation breaks, every time.",
    measure: "exit_at_invalidation", target: 1, investigation_id: INVESTIGATION }]);
  expect(posts.memories).toHaveLength(1);
  expect(posts.memories[0]).toMatchObject({ kind: "lesson", symbol: null, source: "owner_statement", status: "active", owner_confirmed: true,
    original_text: "Be out within 15 minutes when my invalidation breaks, every time.", source_reference: `copilot:${INVESTIGATION}` });

  await page.goto("/copilot-lab");
  await expect(page.getByRole("navigation", { name: "Thread list" })).toContainText("Practicing: exit at my invalidation · 2 of 3 this week");
  await page.goto("/");
  const link = page.getByTestId("owner-dashboard").getByRole("link", { name: /Review my week/ });
  await expect(link).toContainText("Practicing: exit at my invalidation · 2 of 3 this week");
  await page.screenshot({ path: test.info().outputPath("practice-dashboard.png") });
});

test("without Remember this too, Confirm saves only the practice", async ({ page }) => {
  const posts = await labOn(page);
  const card = await reviewToCard(page);
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toContainText("Next week's review scores it.");
  expect(posts.practice).toHaveLength(1);
  expect(posts.practice[0]).toMatchObject({ text: PROPOSAL.text, measure: "exit_at_invalidation", target: 1 });
  expect(posts.memories).toHaveLength(0);
});
