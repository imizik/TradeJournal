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
  await expect(page.getByRole("region", { name: "Conversation" }).getByTestId("desk-book")).toHaveCount(0); // the decision, not the book
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

const SETUP_ID = "6f0c2f8e-1d1a-4c3e-9a51-2d5c6f7a8b90";
const THREAD = "77777777-7777-4777-8777-777777777777";
const dip = (day = DAY) => ({ ...event(day), event_id: ID, kind: "dip_turn", symbols: ["MU"], summary: "MU turned up from its session low 98.20 and has recovered 1.4%." });
const setupCard = (over: Record<string, unknown> = {}) => ({
  id: SETUP_ID, event_id: ID, session_date: DAY, kind: "dip_turn", direction: "up", symbol: "MU", words: "dip turning up", entry: 99.6,
  invalidation: 98.2, side: "below", levels_line: "In near 99.60 · out below 98.20 (−1.4%)",
  contract_line: "Candidate: MU Nov 14 100C · 2.10 × 2.20 (4.7% wide) · Δ0.48", record: "Your first-hour calls: 9 of 17 green, +$1.2k",
  paper_record: null, plan_state: "none", plan_note: null, investigation_id: null, last: { price: 99.9, at: `${DAY}T14:50:00.000Z` }, distance_pct: 1.7,
  paper: { state: "closed", pnl: 45, exit_reason: "time_stop" }, ...over,
});

async function setupHit(page: Page, reply: Record<string, unknown>, setup = setupCard(), day = DAY) {
  const plans: string[] = [];
  const { posts } = await (async () => {
    const posts: { text: string }[] = [];
    await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
    await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
    await page.route(`**/radar/events/${ID}`, (route) => route.fulfill({ json: { event: dip(day), revisions: [], rating: null, news: null,
      news_checks: [], plans: { planned: false, traded: false } } }));
    await page.route(`**/copilot/desk/radar-setup?event=${ID}`, (route) => route.fulfill({ json: { setup } }));
    await page.route(`**/copilot/desk/radar-setup/${SETUP_ID}/plan`, (route) => { plans.push(route.request().method()); return route.fulfill({ json: reply }); });
    await page.route(`**/day-journal/${day}`, (route) => route.fulfill({ json: { day, entries: [], trade_plans: {} } }));
    await page.route(`**/day-journal/${DAY}/entries`, (route) => {
      const body = route.request().postDataJSON();
      posts.push(body);
      return route.fulfill({ json: { id: `new-${posts.length}`, day: DAY, not_traded: false, created_at: `${DAY}T14:55:00Z`, actor: "owner", ...body } });
    });
    await page.goto(`/copilot-lab?symbol=MU&radar=${ID}`);
    return { posts };
  })();
  return { posts, plans };
}

test("a hit with a setup card shows the card as the ping words it, and Plan it plans it in place with a link to its thread", async ({ page }) => {
  const planned = setupCard({ plan_state: "planned", investigation_id: THREAD });
  const { posts, plans } = await setupHit(page, { reply: "Planned MU: out below 98.20. Alert armed. 60-minute check armed.", planned: true, refused: false, setup: planned });
  const card = page.getByRole("region", { name: "Radar hit" });
  const setup = card.getByTestId("radar-setup");
  await expect(setup).toContainText("Setup: MU dip turning up");
  await expect(card.getByTestId("radar-setup-levels")).toHaveText("In near 99.60 · out below 98.20 (−1.4%)");
  await expect(card.getByTestId("radar-setup-distance")).toContainText(": 1.7% above the level.");
  await expect(card.getByTestId("radar-setup-contract")).toHaveText("Candidate: MU Nov 14 100C · 2.10 × 2.20 (4.7% wide) · Δ0.48");
  await expect(setup).toContainText("Your first-hour calls: 9 of 17 green, +$1.2k");
  await expect(card.getByTestId("radar-setup-paper")).toHaveText("Paper result: +$45 per contract, out at the 60-minute stop.");
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("radar-setup-desktop.png") });

  await card.getByRole("button", { name: "Plan it" }).click();
  await expect(card.getByTestId("radar-setup-planned")).toContainText("Planned: out below 98.20. Alert armed. 60-minute check armed.");
  await expect(card.getByRole("link", { name: "Open its thread →" })).toHaveAttribute("href", `/copilot-lab?investigation=${THREAD}`);
  await expect(card.getByRole("button", { name: "Plan it" })).toHaveCount(0);
  expect(plans).toEqual(["POST"]);
  await expect.poll(() => posts.map(p => p.text)).toEqual(["Planning. Radar Dip turning up: MU turned up from its session low 98.20 and has recovered 1.4%."]);
  expect(page.url()).toContain(`radar=${ID}`); // stays on the card
});

test("an already planned setup links its thread instead of Plan it; a refusal says why; at 375 px the card fits", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await setupHit(page, {}, setupCard({ plan_state: "planned", investigation_id: THREAD, contract_line: null, paper: { state: "open" } }));
  const card = page.getByRole("region", { name: "Radar hit" });
  await expect(card.getByTestId("radar-setup-contract")).toHaveText("No liquid contract found.");
  await expect(card.getByTestId("radar-setup-planned")).toContainText("Planned.");
  await expect(card.getByRole("link", { name: "Open its thread →" })).toBeVisible();
  await expect(card.getByRole("button", { name: "Plan it" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("radar-setup-375.png"), fullPage: true });

  await page.unrouteAll({ behavior: "ignoreErrors" });
  const note = "MU is already below 98.20, the level this setup was built on. No plan saved.";
  await setupHit(page, { reply: note, planned: false, refused: true, setup: setupCard({ plan_state: "refused", plan_note: note }) });
  await card.getByRole("button", { name: "Plan it" }).click();
  await expect(card.getByTestId("radar-setup-refused")).toHaveText(`Not planned: ${note}`);
  await expect(card.getByRole("button", { name: "Plan it" })).toHaveCount(0);
});

test("an earlier day's setup card is shown, and Plan it opens a plan conversation instead of a plan the server would refuse", async ({ page }) => {
  const { plans } = await setupHit(page, {}, setupCard({ session_date: "2026-10-20", last: null, distance_pct: null }), "2026-10-20");
  const card = page.getByRole("region", { name: "Radar hit" });
  await expect(card.getByTestId("radar-setup-levels")).toHaveText("In near 99.60 · out below 98.20 (−1.4%)");
  await expect(card.getByTestId("radar-setup-distance")).toHaveCount(0);
  await card.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/origin=radar_event%3Arv1-/);
  expect(plans).toEqual([]);
});
