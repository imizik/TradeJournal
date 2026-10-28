import { expect, test, type Page } from "@playwright/test";

// The owner's Today screen. GET /today and the lab status are stubbed in the browser (the e2e backend runs with the lab
// off), so the sections are fixed and nothing is sent.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const TRADE = "aaaaaaaa-0000-4000-8000-000000000001";
const PLAN_INV = "bbbbbbbb-0000-4000-8000-000000000002";
const PREP_INV = "cccccccc-0000-4000-8000-000000000003";
const THESIS_PATH = `/copilot-lab?investigation=dddddddd-0000-4000-8000-000000000004&context=${encodeURIComponent('New since my thesis: "NBIS wins a contract". What changed?')}`;
const EVENT = "rad_sample_mu_20261020_1";
const BODY = {
  as_of: "2026-10-23T18:49:00Z", day: "2026-10-23", quotes_at: 1792000000, quote_issue: null,
  act_now: { state: "ok", open_positions: 3, rows: [
    { trade_id: TRADE, symbol: "NBIS", contract: "NBIS 10/23/26 100C", quantity: 2, unrealized_usd: 180, unrealized_pct: 29,
      reasons: [{ kind: "invalidation_near", text: "0.8% from invalidation 92.30" }, { kind: "expires_today", text: "Expires today" }] },
  ] },
  plans: { state: "ok", armed: 2, rows: [
    { symbol: "CRWV", direction: "long", thesis: "Breakout over the week's high with the group", last: 100, trigger: "entry", price: 100.6,
      distance_pct: 0.6, position: "waiting", path: `/copilot-lab?investigation=${PLAN_INV}` },
  ] },
  new: {
    radar: { state: "ok", count: 1, last_visit_at: null, rows: [
      { event_id: EVENT, symbol: "MU", kind: "relative_to_sector", direction: "up", first_seen_at: "2026-10-23T15:12:04Z",
        summary: "MU up 4.1% while SMH is up 0.6%: 3.5 points ahead of its sector on 2.3x usual volume.", path: `/radar?event=${EVENT}` },
    ] },
    thesis: { state: "ok", count: 1, rows: [
      { symbol: "NBIS", kind: "news", text: "NBIS wins a contract", fired_at: "2026-10-23T14:30:00Z", delivery: "sent", path: THESIS_PATH },
    ] },
    prep: { state: "ok", prep: { lines: ["NBIS 100C expires today.", "CRWV entry 100.60 is 0.6% away."], fallback: false, delivery: "sent",
      at: "2026-10-23T12:30:00Z", path: `/copilot-lab?investigation=${PREP_INV}` } },
  },
  held: { state: "ok", count: 1, rows: [
    { kind: "plan nudge", decision: "suppressed", symbol: "APLD", title: "Plan APLD 35C", body: "You opened APLD 35C without a plan.",
      reason: "Quiet window", at: "2026-10-23T16:00:00Z" },
  ] },
  week: { state: "ok", show: true, current: 2, best: 4, pending: 0, planned: 3, total: 5, week_pending: 0 },
};
const EMPTY = {
  ...BODY, act_now: { state: "ok", open_positions: 0, rows: [] }, plans: { state: "ok", armed: 0, rows: [] },
  new: { radar: { state: "off", reason: "Radar recording is not switched on.", count: 0, rows: [] }, thesis: { state: "ok", count: 0, rows: [] },
    prep: { state: "ok", prep: null } },
  held: { state: "ok", count: 0, rows: [] }, week: { ...BODY.week, current: 0, planned: 0, total: 0 },
};
const ORDER = ["Act now", "Plans near a trigger", "New since you looked", "Held back", "Your week so far"];

async function today(page: Page, body: unknown = BODY, on = true) {
  let reads = 0;
  await page.clock.install({ time: new Date("2026-10-23T18:49:00Z") });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: { ...ON, enabled: on } }));
  await page.route("**/api/backend/today", (route) => { reads += 1; return route.fulfill({ json: body }); });
  await page.goto("/today");
  await expect(page.getByTestId("today-as-of")).toHaveText("As of 2:49 PM ET");
  return { reads: () => reads };
}

const section = (page: Page, name: string) => page.getByRole("region", { name, exact: true });
const fits = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

test("the sections in priority order, each row linking to where you act, refreshed every minute", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { reads } = await today(page, BODY, false); // Today shows while the lab is off; with it on, the desk is home
  const names = await page.getByTestId("today-section").evaluateAll((all) => all.map((el) => el.getAttribute("aria-label")));
  expect(names).toEqual(ORDER);
  const act = section(page, "Act now");
  await expect(act.getByTestId("today-count")).toHaveText("1");
  await expect(act).toContainText("3 open");
  await expect(act.getByTestId("today-act-row")).toContainText("2× NBIS 10/23/26 100C");
  await expect(act.getByTestId("today-act-row")).toContainText("+$180 · +29%");
  await expect(act.getByTestId("today-act-row")).toContainText("0.8% from invalidation 92.30");
  await expect(act.getByTestId("today-act-row")).toContainText("Expires today");
  await expect(act.getByRole("link", { name: "Review NBIS 10/23/26 100C" })).toHaveAttribute("href", `/trades/${TRADE}`);
  const plans = section(page, "Plans near a trigger");
  await expect(plans).toContainText("Entry 100.60 · 0.6% away");
  const fresh = section(page, "New since you looked");
  await expect(fresh.getByTestId("today-count")).toHaveText("3");
  await expect(fresh.getByRole("link", { name: "Open the MU Radar event" })).toHaveAttribute("href", `/radar?event=${EVENT}`);
  await expect(fresh.getByTestId("today-prep-row")).toContainText("CRWV entry 100.60 is 0.6% away.");
  const held = section(page, "Held back");
  await expect(held.getByTestId("today-held-row")).toContainText("Quiet window · plan nudge");
  await expect(held.getByTestId("today-held-row")).toContainText("You opened APLD 35C without a plan.");
  await expect(page.getByTestId("today-week")).toContainText("3 of 5 entries planned");
  await expect(page.getByTestId("today-week")).toContainText("Streak 2 · best 4");
  // Desktop: Today sits ahead of Dashboard in the sidebar; one readable column, not stretched across 1440.
  const sidebar = page.getByRole("navigation").filter({ has: page.getByRole("heading", { name: "Labs" }) });
  expect((await sidebar.getByRole("link").allTextContents()).slice(0, 2)).toEqual(["Today", "Dashboard"]);
  await expect(sidebar.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
  expect((await page.getByTestId("today").boundingBox())!.width).toBeLessThanOrEqual(672);
  await fits(page);
  await page.screenshot({ path: test.info().outputPath("today-1440.png"), fullPage: true });
  expect(reads()).toBe(1);
  await page.clock.fastForward(61_000);
  await expect.poll(reads).toBe(2);
});

test("on a phone: Today is the first tab, rows are thumb-sized, nothing scrolls sideways, and a tap opens the row", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await today(page, BODY, false); // with the lab on, the desk is home instead (below)
  const tabs = page.getByRole("navigation", { name: "Main tabs" });
  await expect(tabs.getByRole("link").first()).toHaveText("Today");
  await expect(tabs.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
  for (const row of await page.locator("[data-testid^='today-'][data-testid$='-row']").all()) {
    expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  for (const link of await page.getByTestId("today").getByRole("link").all()) {
    expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  await fits(page);
  await page.screenshot({ path: test.info().outputPath("today-375.png"), fullPage: true });
  // Dashboard stays one menu away.
  await tabs.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
  await page.getByRole("button", { name: "Close menu" }).click();
  await section(page, "New since you looked").getByRole("link", { name: "Open the MU Radar event" }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/radar" && url.searchParams.get("event") === EVENT);
  await page.goBack();
  await expect(section(page, "Act now").getByRole("link", { name: "Review NBIS 10/23/26 100C" })).toHaveAttribute("href", `/trades/${TRADE}`);
});

test("while the lab is on the desk is home: Today forwards to it, and Desk leads the tabs and the menu", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/api/backend/today", (route) => route.fulfill({ json: BODY }));
  await page.goto("/today");
  await expect(page).toHaveURL((url) => url.pathname === "/copilot-lab");
  const tabs = page.getByRole("navigation", { name: "Main tabs" });
  await expect(tabs.getByRole("link").first()).toHaveText("Desk");
  await expect(tabs.getByRole("link", { name: "Desk" })).toHaveAttribute("aria-current", "page");
  await expect(tabs.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
  await tabs.getByRole("button", { name: "Open menu" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu.getByRole("link", { name: "Desk", exact: true })).toHaveAttribute("href", "/copilot-lab");
  await expect(menu.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Copilot", exact: true })).toHaveCount(0); // one entry for one page
});

test("an empty day collapses every section to its count; a failed section says so and the rest stand", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await today(page, { ...EMPTY, held: { state: "unavailable" }, new: { ...EMPTY.new, thesis: { state: "unavailable" } } }, false);
  for (const name of ["Act now", "Plans near a trigger", "New since you looked"]) {
    await expect(section(page, name)).toHaveAttribute("data-empty", "true");
    await expect(section(page, name).getByTestId("today-count")).toHaveText("0");
  }
  await expect(section(page, "New since you looked")).toContainText("Radar off");
  await expect(section(page, "New since you looked")).toContainText("Could not read thesis watch right now.");
  await expect(page.locator("[data-testid$='-row']")).toHaveCount(0);
  await expect(section(page, "Held back")).toContainText("Could not read this right now.");
  await expect(page.getByTestId("today-week")).toContainText("0 of 0 entries planned");
  await fits(page);
  await page.screenshot({ path: test.info().outputPath("today-empty-375.png"), fullPage: true });
});

test("with the lab off the page still reads, and copilot links are left out", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await today(page, BODY, false);
  await expect(section(page, "Act now").getByRole("link", { name: "Review NBIS 10/23/26 100C" })).toHaveAttribute("href", `/trades/${TRADE}`);
  await expect(section(page, "Plans near a trigger").getByTestId("today-plan-row")).toContainText("Entry 100.60");
  await expect(section(page, "New since you looked").getByRole("link", { name: "Open the MU Radar event" })).toBeVisible();
  await expect(section(page, "New since you looked").getByTestId("today-thesis-row")).toContainText("NBIS wins a contract");
  await expect(page.getByTestId("today").locator("a[href*='copilot-lab']")).toHaveCount(0);
  await expect(page.getByTestId("today").getByRole("link", { name: "Plan a trade" })).toHaveCount(0);
  await expect(page.getByTestId("today").getByRole("link", { name: "Review my week" })).toHaveCount(0);
});

// The frontend proxy forwards only known first path segments; "today" was missing when the screen first shipped, so
// production showed "Request failed (404)" while the backend answered. This one goes through the real proxy, unstubbed.
test("the frontend proxy forwards GET /today to the backend", async ({ page }) => {
  const response = await page.request.get("/api/backend/today");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(Object.keys(await response.json()).length).toBeGreaterThan(0);
});
