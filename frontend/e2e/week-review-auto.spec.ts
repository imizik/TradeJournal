import { expect, test, type Page } from "@playwright/test";

// The automatic week review (docs/copilot-lab.md § Review my week): Friday's review is saved as an open copilot
// investigation, so it shows in the desk's thread list; opening it shows the answer and the practice card it proposed, kept on
// the server until confirmed. The e2e backend runs with the lab off, so these tests stand in for its lab routes.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INVESTIGATION = "44444444-4444-4444-8444-444444444444";
const TITLE = "Week review Oct 19–Oct 23";
const ANSWER = "Planned trades did better: 2 of 5 had a plan before the entry.\n\nTo practice next week: exit at the invalidation.";
const SAVED = {
  id: INVESTIGATION, source: "copilot", title: TITLE, symbol: null, status: "open",
  conclusion: "Planned trades did better: 2 of 5 had a plan before the entry.", revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T20:46:00Z", updated_at: "2026-10-23T20:46:00Z",
  transcript: [{ role: "user", content: "Context: Review my week of 2026-10-19" }, { role: "assistant", content: ANSWER }],
  evidence: [{ tool: "get_week_review", as_of: "2026-10-23T20:45:00Z", kind: "saved", message: 1 }], findings: null,
};
const PROPOSED = {
  id: "plan_2", kind: "practice", text: "Exit within 15 minutes when my plan's invalidation breaks.",
  measure: "exit_at_invalidation", label: "exit at my invalidation", target: 1,
  why: "1 of 2 invalidation hits this week was held past 15 minutes.",
};

async function labOn(page: Page) {
  const posts: Record<string, unknown>[] = [];
  let confirmed = false;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: {
    as_of: "2026-10-23T20:50:00Z", quotes_at: null, quote_issue: null, day: { phase: "post", need_you: 0, streak: null }, sections: {},
    threads: [{ key: `investigation:${INVESTIGATION}`, group: "watch", symbol: null, title: TITLE, instrument: null, value: null,
      status: { text: SAVED.conclusion, tone: "muted" }, meter: null, investigation_id: INVESTIGATION, trade_id: null,
      radar_event_id: null, path: null, changed_at: null }] } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${INVESTIGATION}`, (route) => route.fulfill({ json: SAVED }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/practice", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: { goal: null, this_week: null } });
    posts.push(route.request().postDataJSON());
    confirmed = true;
    return route.fulfill({ status: 201, json: { goal: { text: PROPOSED.text, measure: PROPOSED.measure, label: PROPOSED.label,
      target: 1, week_start: "2026-10-26", since: "2026-10-24T15:00:00Z" }, this_week: null } });
  });
  await page.route(`**/copilot/practice?investigation=${INVESTIGATION}`, (route) =>
    route.fulfill({ json: { goal: null, this_week: null, proposed: confirmed ? null : PROPOSED } }));
  return posts;
}

test("Friday's saved review shows in the thread list and opens with its practice card", async ({ page }) => {
  const posts = await labOn(page);
  await page.goto("/copilot-lab");
  const home = page.getByRole("navigation", { name: "Thread list" });
  const thread = home.getByRole("link", { name: TITLE });
  await expect(thread).toHaveAttribute("href", `/copilot-lab?investigation=${INVESTIGATION}`);
  await page.screenshot({ path: test.info().outputPath("week-review-auto-threads.png") });

  await thread.click();
  await expect(page.getByText("To practice next week: exit at the invalidation.")).toBeVisible();
  const card = page.getByRole("region", { name: "Proposed practice" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("1 of 2 invalidation hits this week was held past 15 minutes.");
  await page.screenshot({ path: test.info().outputPath("week-review-auto-card.png") });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toMatchObject({ measure: "exit_at_invalidation", target: 1, investigation_id: INVESTIGATION });
});

test("the alert's link opens the review straight away", async ({ page }) => {
  await labOn(page);
  await page.goto(`/copilot-lab?investigation=${INVESTIGATION}`);
  await expect(page.getByText("To practice next week: exit at the invalidation.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Proposed practice" })).toBeVisible();
});
