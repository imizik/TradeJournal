import { expect, test, type Page } from "@playwright/test";
import { openDeskThreads } from "./desk-fixtures";

// The practice goal: Review my week proposes one thing to practice as a card; the owner edits the text, Confirm posts it
// to /copilot/practice (and a lesson memory only when "Remember this too" is ticked), and the goal's line appears in the
// desk's facts line under the book and on the Dashboard's Review my week button. The e2e backend runs with the lab off, so these tests
// stand in for its status read and its lab routes.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DESK = { as_of: "2026-10-24T15:12:00Z", quotes_at: null, quote_issue: null,
  day: { phase: "closed", need_you: 0, streak: null }, sections: {}, threads: [] };
// A closed day: the session strip waits and only its facts line (with the practice goal) shows.
const SESSION = { as_of: "2026-10-24T15:12:00Z", now: 1792854720, day: "2026-10-24", phase: "closed", open: null, close: null,
  events: [], time_stops: [], pings: null, prep: null, indices: [], quote_issue: null, sections: { hours: "ok" } };
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
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: SESSION }));
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
  await page.goto("/copilot-lab?view=briefing");
  await openDeskThreads(page);
  const home = page.getByRole("navigation", { name: "Thread list" });
  await expect(home.getByTestId("desk-day")).toBeVisible();
  await expect(home).not.toContainText("Practicing:");
  const saved = page.waitForRequest((request) => request.url().endsWith("/copilot/investigations") && request.method() === "POST");
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await centre.getByRole("tab", { name: "Feed" }).click();
  await centre.getByRole("button", { name: "Review my week" }).click();
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

  await page.goto("/copilot-lab?view=briefing");
  await expect(page.getByTestId("session-facts")).toContainText("Practicing: exit at my invalidation · 2 of 3 this week");
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

// At risk now (docs/copilot-lab.md § Exposure): the desk's facts line under the book carries the open long options' premium beside
// the practice goal, and draws nothing when the read fails.
const EXPOSURE = { state: "ok", at_risk_usd: 6400, positions: 3, usual_day_usd: 2100, sample_days: 60, as_of: "2026-10-24T11:12:00-04:00",
  line: "At risk now: $6,400 in 3 options · usual day $2,100" };

test("the session line shows what is at risk now, and fits a phone", async ({ page }) => {
  await labOn(page);
  await page.route("**/copilot/exposure", (route) => route.fulfill({ json: EXPOSURE }));
  await page.goto("/copilot-lab?view=briefing");
  await expect(page.getByTestId("exposure-line")).toHaveText("At risk now: $6,400 in 3 options · usual day $2,100");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/copilot-lab?view=briefing");
  await expect(page.getByTestId("exposure-line")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("exposure-phone.png") });
});

test("a failed exposure read draws no line", async ({ page }) => {
  await labOn(page);
  await page.route("**/copilot/exposure", (route) => route.fulfill({ status: 500, json: { detail: "down" } }));
  const read = page.waitForResponse("**/copilot/exposure");
  await page.goto("/copilot-lab?view=briefing");
  await read;
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByTestId("exposure-line")).toHaveCount(0);
});
