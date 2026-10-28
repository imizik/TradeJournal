import { expect, test, type Page } from "@playwright/test";

// A Radar hit opened from the desk (docs/copilot-lab.md#the-desk): watching, passing or planning it, logged as a day-journal
// decision. Every lab route, the Radar event and the day journal are stubbed in the browser; no model runs.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Decisions count on the hit's own New York day, so the hit is today's.
const DAY = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const ID = `rv1-${DAY}-sec-mu-up-1`;
const event = (day = DAY) => ({
  event_id: ID, session_date: day, kind: "relative_to_sector", direction: "up", symbols: ["MU"],
  summary: "MU up 4.1% vs Semis by 3.2% over 30 min.", first_seen_at: `${day}T14:42:05.000Z`,
});

async function hit(page: Page, { day = DAY, logged = [] as unknown[] } = {}) {
  const posts: { kind: string; text: string; symbol: string; operation_id: string }[] = [];
  const entries: unknown[] = [...logged];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/radar/events/${ID}`, (route) => route.fulfill({ json: { event: event(day), revisions: [], rating: null, news: null,
    news_checks: [], plans: { planned: false, traded: false } } }));
  await page.route(`**/day-journal/${day}`, (route) => route.fulfill({ json: { day, entries, trade_plans: {} } }));
  await page.route(`**/day-journal/${day}/entries`, (route) => {
    const body = route.request().postDataJSON();
    posts.push(body);
    const row = { id: `new-${posts.length}`, day, not_traded: false, created_at: `${day}T14:45:00Z`, actor: "owner", ...body };
    entries.push(row);
    return route.fulfill({ json: row });
  });
  await page.goto(`/copilot-lab?symbol=MU&radar=${ID}`);
  return { posts };
}

test("a Radar hit opens on the desk straight onto watching, passing or planning it, and Watching logs once after the Undo window", async ({ page }) => {
  const { posts } = await hit(page);
  const card = page.getByRole("region", { name: "Radar hit" });
  await expect(card).toContainText("Radar · vs sector");
  await expect(card).toContainText("MU up 4.1% vs Semis by 3.2% over 30 min.");
  await expect(card.getByRole("link", { name: "Open in Radar" })).toHaveAttribute("href", `/radar?event=${ID}`);
  await expect(page.getByTestId("session-tape")).toHaveCount(0); // not the Briefing
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("radar-decision-desktop.png") });

  await card.getByRole("button", { name: "Watching" }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(card).toContainText("Logged watching");
  await page.waitForTimeout(3_500);
  expect(posts).toEqual([]); // still inside the Undo window
  await expect(page.getByTestId("radar-decision-logged")).toContainText("You logged watching at", { timeout: 4_000 });
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ kind: "decision", symbol: "MU", text: "Watching. Radar vs sector: MU up 4.1% vs Semis by 3.2% over 30 min." });
});

test("Undo posts nothing; Pass is logged; a decision already logged shows as one line", async ({ page }) => {
  const { posts } = await hit(page);
  const card = page.getByRole("region", { name: "Radar hit" });
  await card.getByRole("button", { name: "Pass" }).click();
  await card.getByRole("button", { name: "Undo" }).click();
  await expect(card.getByRole("button", { name: "Watching" })).toBeVisible();
  await card.getByRole("button", { name: "Pass" }).click();
  await expect(page.getByTestId("radar-decision-logged")).toContainText("You logged passing", { timeout: 7_000 });
  expect(posts.map(p => p.text)).toEqual(["Passing. Radar vs sector: MU up 4.1% vs Semis by 3.2% over 30 min."]);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await hit(page, { logged: [{ id: "x", day: DAY, kind: "decision", symbol: "MU", text: "Watching. Radar vs sector: MU up 4.1% vs Semis by 3.2% over 30 min.", not_traded: false,
    created_at: `${DAY}T14:50:00Z`, actor: "owner" }] });
  await expect(page.getByTestId("radar-decision-logged")).toContainText("You logged watching at");
  await expect(page.getByRole("region", { name: "Radar hit" }).getByRole("button", { name: "Plan it" })).toBeVisible();
});

test("Plan it logs planning and opens a plan conversation that names the hit as its origin", async ({ page }) => {
  const { posts } = await hit(page);
  await page.getByRole("region", { name: "Radar hit" }).getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/origin=radar_event%3Arv1-/);
  expect(new URL(page.url()).searchParams.get("context")).toBe("Plan a trade: Radar: MU up 4.1% vs Semis by 3.2% over 30 min");
  expect(posts.map(p => p.text)).toEqual(["Planning. Radar vs sector: MU up 4.1% vs Semis by 3.2% over 30 min."]);
});

test("a hit from an earlier day offers only Plan it, and at 375 px the card fits", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await hit(page, { day: "2026-10-20" });
  const card = page.getByRole("region", { name: "Radar hit" });
  await expect(card).toContainText("on 2026-10-20");
  await expect(card.getByRole("button", { name: "Watching" })).toHaveCount(0);
  await expect(card).toContainText("Watching or passing counts on the hit's own day.");
  await expect(card.getByRole("button", { name: "Plan it" })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("radar-decision-375.png") });
});
