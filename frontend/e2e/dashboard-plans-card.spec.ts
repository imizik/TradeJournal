import { expect, test, type Page } from "@playwright/test";

// The Dashboard's Plans card: each open position beside its plan. The lab routes are stubbed in the browser (the e2e
// backend runs with the lab off), so no model runs and nothing is sent.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const PLANNED = "aaaaaaaa-0000-4000-8000-000000000001";
const SUGGESTED = "aaaaaaaa-0000-4000-8000-000000000002";
const BARE = "aaaaaaaa-0000-4000-8000-000000000003";
const epoch = (iso: string) => Date.parse(iso) / 1000;
const PLAN_PATH = `/copilot-lab?symbol=APLD&context=${encodeURIComponent("Plan this position: I just opened APLD 10/31/26 35C (1 at $1.20) without a plan. Help me set an invalidation and a time stop.")}`;
const BOOK = {
  count: 3, quotes_at: epoch("2026-10-23T18:49:00Z"), quote_issue: null,
  positions: [
    { trade_id: PLANNED, symbol: "NBIS", contract: "NBIS 10/24/26 100C", instrument: "option", direction: "long", quantity: 2,
      unrealized_usd: 180, unrealized_pct: 29, giveback: "armed", latest_alert: { kind: "hold_hour", at: epoch("2026-10-23T15:05:00Z") },
      plan: { setup: "Copilot plan", thesis: "Reclaims VWAP", timing: "pre_entry",
        invalidation: { price: 92.3, condition: "crosses", state: "armed", distance_usd: -1.94, distance_pct: -2.06 },
        time_stop: { text: "out by 15:30", due_at: epoch("2026-10-23T19:30:00Z"), clock: "15:30", state: "pending", minutes_left: 41 } },
      link_path: null, plan_path: null },
    { trade_id: SUGGESTED, symbol: "CRWV", contract: "CRWV 10/31/26 95P", instrument: "option", direction: "long", quantity: 1,
      unrealized_usd: -45, unrealized_pct: -12, giveback: "fired", latest_alert: { kind: "giveback", at: epoch("2026-10-23T16:00:00Z") },
      plan: null, link_path: `/plans/link?trade=${SUGGESTED}`, plan_path: null },
    { trade_id: BARE, symbol: "APLD", contract: "APLD 10/31/26 35C", instrument: "option", direction: "long", quantity: 1,
      unrealized_usd: null, unrealized_pct: null, giveback: "watching", latest_alert: null,
      plan: null, link_path: null, plan_path: PLAN_PATH },
  ],
};
const EMPTY = { count: 0, quotes_at: null, quote_issue: null, positions: [] };

async function dashboard(page: Page, book: unknown = BOOK, on = true) {
  let reads = 0;
  await page.clock.install({ time: new Date("2026-10-23T18:49:00Z") });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: { ...ON, enabled: on } }));
  await page.route("**/copilot/plans/positions", (route) => { reads += 1; return route.fulfill({ json: book }); });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/plans", (route) => route.fulfill({ json: { plans: [], quotes_at: null, quote_issue: null } }));
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: { as_of: "2026-10-23T18:49:00Z", positions: { state: "ok", count: 0, positions: [] },
    investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] } } }));
  await page.goto("/");
  return { reads: () => reads };
}

const card = (page: Page) => page.getByRole("region", { name: "Plans" });
const fits = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

test("one row per position: P&L, invalidation distance, time stop countdown, give-back and the unplanned actions", async ({ page }) => {
  const { reads } = await dashboard(page);
  const rows = card(page).getByTestId("plans-card-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("2× NBIS 10/24/26 100C");
  await expect(rows.nth(0)).toContainText("+$180 · +29%");
  await expect(rows.nth(0)).toContainText("Invalidation 92.30 · 2.1% away");
  await expect(rows.nth(0)).toContainText("Time stop 15:30 · 41 min");
  await expect(rows.nth(0)).toContainText("Give-back armed");
  await expect(rows.nth(0)).toContainText("Held an hour 11:05");
  await expect(rows.nth(1)).toContainText("-$45 · -12%");
  await expect(rows.nth(1)).toContainText("No plan");
  await expect(rows.nth(1)).toContainText("Give-back fired");
  await expect(rows.nth(1).getByRole("link", { name: "Link plan" })).toHaveAttribute("href", `/plans/link?trade=${SUGGESTED}`);
  await expect(rows.nth(2).getByRole("link", { name: "Plan it" })).toHaveAttribute("href", PLAN_PATH);
  await expect(rows.nth(2)).not.toContainText("Give-back");
  // Above Exit habits.
  const [plans, habits] = await Promise.all([card(page).boundingBox(), page.getByRole("region", { name: "Exit habits" }).boundingBox()]);
  expect(plans!.y).toBeLessThan(habits!.y);
  expect(reads()).toBe(1);
  await page.clock.fastForward(61_000);
  await expect.poll(reads).toBe(2);
});

test("a row opens the position review; Plan it and Link plan open their pages", async ({ page }) => {
  await dashboard(page);
  const rows = card(page).getByTestId("plans-card-row");
  await rows.nth(0).getByRole("link", { name: "Review NBIS 10/24/26 100C" }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/copilot-lab" && url.searchParams.get("symbol") === "NBIS"
    && url.searchParams.get("context") === `Review this position: ${PLANNED}`);
  await page.goBack();
  await rows.nth(2).getByRole("link", { name: "Plan it" }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/copilot-lab" && (url.searchParams.get("context") ?? "").startsWith("Plan this position:"));
  await page.goBack();
  await page.route(`**/trades/${SUGGESTED}/plan-link`, (route) => route.fulfill({ status: 404, json: { detail: "Not found" } }));
  await rows.nth(1).getByRole("link", { name: "Link plan" }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/plans/link" && url.searchParams.get("trade") === SUGGESTED);
});

test("nothing open shows the Plan a trade button", async ({ page }) => {
  await dashboard(page, EMPTY);
  await expect(card(page)).toContainText("Nothing open.");
  await expect(card(page).getByRole("link", { name: "Plan a trade" })).toHaveAttribute("href", /^\/copilot-lab\?symbol=&context=Plan\+a\+trade%3A/);
});

test("the card is hidden while the lab is off", async ({ page }) => {
  const { reads } = await dashboard(page, BOOK, false);
  await expect(page.getByRole("region", { name: "Exit habits" })).toBeVisible();
  await expect(card(page)).toHaveCount(0);
  expect(reads()).toBe(0);
});

test("at 375 px every row is thumb-sized and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await dashboard(page);
  const rows = card(page).getByTestId("plans-card-row");
  await expect(rows).toHaveCount(3);
  for (const link of await card(page).getByRole("link").all()) {
    const box = await link.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);
  }
  await fits(page);
  await card(page).screenshot({ path: test.info().outputPath("dashboard-plans-card-375.png") });
});
