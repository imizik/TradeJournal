import { expect, test, type Page } from "@playwright/test";

// "Review my week": a button on the Dashboard, on a Friday's Daily Review and on the Copilot Lab home. The e2e backend
// runs with the lab off, so these tests stand in for its status read and its lab routes. The Dashboard and Daily Review
// links open the lab prefilled and unsent; the lab's own button sends one turn.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const DESK = { as_of: "2026-10-24T15:12:00Z", quotes_at: null, quote_issue: null,
  day: { phase: "closed", need_you: 0, streak: null }, sections: {}, threads: [] };
const TURN = [
  { type: "tool", id: "fake_1_0", name: "get_week_review", input: {}, status: "ok", summary: "week of 2026-10-19: 8 trades -27.00 $ · planned 2/1/5",
    provenance: { source: "SIMULATED fixture", kind: "simulated", as_of: "2026-10-23T15:12:00Z", state: "ok" } },
  { type: "text", delta: "**Week of 2026-10-19**: 8 trades. Planned vs unplanned first." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const week = (monday?: string) => `/copilot-lab?${new URLSearchParams({ context: monday ? `Review my week of ${monday}` : "Review my week" })}`;

const statusAnswer = (page: Page) => page.waitForResponse((response) => response.url().includes("/copilot/status"));

async function labOn(page: Page) {
  const chats: { messages: { role: string; content: string }[] }[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: {
    id: "33333333-3333-4333-8333-333333333333", source: "copilot", title: "Review my week", symbol: null, status: "open", conclusion: null,
    revision: 1, message_count: 2, has_findings: false, created_at: "2026-10-24T15:12:00Z", updated_at: "2026-10-24T15:12:00Z",
    transcript: [], evidence: [], findings: null } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/chat", (route) => {
    chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  return chats;
}

test("no Review my week while the lab is off", async ({ page }) => {
  for (const route of ["/", "/daily/2026-10-23"]) {
    const answered = statusAnswer(page);
    await page.goto(route);
    await answered;
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    await expect(page.getByRole("link", { name: "Review my week" })).toHaveCount(0);
  }
});

test("the Dashboard opens the lab with Review my week in the box, unsent", async ({ page }) => {
  const chats = await labOn(page);
  await page.goto("/");
  const link = page.getByTestId("owner-dashboard").getByRole("link", { name: "Review my week" });
  await expect(link).toHaveAttribute("href", week());
  await page.screenshot({ path: test.info().outputPath("review-my-week-dashboard.png") });
  await link.click();
  await expect(page).toHaveURL(/\/copilot-lab\?context=Review/);
  await expect(page.getByLabel("Message")).toHaveValue(/Review my week/);
  await page.waitForTimeout(300);
  expect(chats).toHaveLength(0);
});

test("Daily Review offers it on a Friday, naming that week, and not on other days", async ({ page }) => {
  await labOn(page);
  await page.goto("/daily/2026-10-23");
  await expect(page.getByRole("link", { name: "Review my week" })).toHaveAttribute("href", week("2026-10-19"));
  await page.goto("/daily/2026-10-22");
  await expect(page.getByRole("heading", { name: "Daily Review" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Dashboard" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review my week" })).toHaveCount(0);
});

test("the Briefing's Review my week sends one turn and shows the week review tool", async ({ page }) => {
  const chats = await labOn(page);
  await page.goto("/copilot-lab");
  const home = page.getByRole("navigation", { name: "Thread list" });
  await expect(home.getByTestId("desk-day")).toBeVisible();
  expect(chats).toHaveLength(0);
  await page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Review my week" }).click();
  await expect(page.getByText("Planned vs unplanned first.")).toBeVisible();
  expect(chats).toHaveLength(1);
  expect(chats[0].messages.at(-1)?.content).toContain("Review my week");
  const sources = page.getByTestId("copilot-sources").last();
  await expect(sources.locator("summary")).toContainText("simulated"); // simulated evidence still shows while folded
  await sources.locator("summary").click();
  await expect(sources.getByText("Week review · simulated")).toBeVisible();
});

test("the week review shows your exit lessons, each opening its plan's thread", async ({ page }) => {
  await labOn(page);
  const lessons = { exited: 3, answered: 2, simulated: false, rows: [
    { symbol: "NBIS", followed: "no", lesson: "No. The invalidation broke at 13:59 and I waited for a bounce. Out when it breaks, not after.",
      thread: "44444444-4444-4444-8444-444444444444" },
    { symbol: "CRWV", followed: "yes", lesson: "Yes, took it at the time stop.", thread: null },
  ] };
  const turn = TURN.replace('"name":"get_week_review",', `"name":"get_week_review","lessons":${JSON.stringify(lessons)},`);
  await page.unroute("**/copilot/chat");
  await page.route("**/copilot/chat", (route) =>
    route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turn }));
  await page.goto("/copilot-lab");
  await page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Review my week" }).click();
  const block = page.getByRole("region", { name: "Your exit lessons this week" });
  await expect(block).toContainText("2 of 3 exits reviewed");
  const rows = block.getByRole("link");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("NBIS");
  await expect(rows.nth(0)).toContainText("Didn't follow");
  await expect(rows.nth(0)).toHaveAttribute("href", "/copilot-lab?investigation=44444444-4444-4444-8444-444444444444");
  await expect(rows.nth(1)).toHaveAttribute("href", "/copilot-lab?symbol=CRWV"); // no thread: its symbol
  await page.screenshot({ path: test.info().outputPath("review-my-week-lessons.png") });
});

test("the week review lists your long holds, each asking whether it is still the thesis", async ({ page }) => {
  await labOn(page);
  const holds = { simulated: false, rows: [
    { symbol: "MSFT", contract: "MSFT stock", days_held: 71, thesis: "Azure capacity keeps growing faster than capex.",
      thread: "55555555-5555-4555-8555-555555555555" },
    { symbol: "TSM", contract: "TSM 1/15/27 200C", days_held: 24, thesis: null, thread: null },
  ] };
  const turn = TURN.replace('"name":"get_week_review",', `"name":"get_week_review","long_holds":${JSON.stringify(holds)},`);
  await page.unroute("**/copilot/chat");
  await page.route("**/copilot/chat", (route) =>
    route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turn }));
  await page.goto("/copilot-lab");
  await page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Review my week" }).click();
  const block = page.getByRole("region", { name: "Your long holds" });
  await expect(block).toContainText("2 held, not asked about day to day");
  const rows = block.getByRole("link");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("71d");
  await expect(rows.nth(0)).toContainText("“Azure capacity keeps growing faster than capex.”");
  await expect(rows.nth(0)).toContainText("Still the thesis?");
  await expect(rows.nth(0)).toHaveAttribute("href", "/copilot-lab?investigation=55555555-5555-4555-8555-555555555555");
  await expect(rows.nth(1)).toContainText("TSM 1/15/27 200C · no plan");
  await expect(rows.nth(1)).toHaveAttribute("href", "/copilot-lab?symbol=TSM"); // no plan: its symbol
  await page.screenshot({ path: test.info().outputPath("review-my-week-long-holds.png") });
});
