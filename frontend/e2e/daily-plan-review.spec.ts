import { expect, test } from "@playwright/test";

// The review itself comes from Claude on the plan; this stubs the button's POST
// with a prompt-v2 answer so the panel's new sections can be seen. Nothing here
// reaches Claude. The calendar's status line reads the real (unconfigured) runner.
const review = {
  summary: "Three trades, -$85. The one that mattered: the 10:42 SPY call chased a move that had already used most of the day's range.",
  day_grade: "C: two entries on plan, one chase sized above your normal",
  key_takeaways: ["SPY 10:42 call: entry_day_range_used_pct 86%, after the rule said no late calls."],
  best_trade: { trade_id: null, ticker: "QQQ", reason: "Waited for the VWAP reclaim and took the first target." },
  worst_trade: { trade_id: null, ticker: "SPY", reason: "Late chase, then held through the giveback." },
  patterns: ["Both losers were entered after 80% of the range was used."],
  next_session_rules: ["No call entries when entry_day_range_used_pct > 80%", "Max 2 contracts until two green trades"],
  rules_check: [
    { rule: "No entries after 3 PM", set_on: "2026-09-30", result: "kept", evidence: "Last entry 14:12." },
    { rule: "Max 2 contracts", set_on: "2026-09-30", result: "broken", evidence: "SPY 10:42 call: 4 contracts." },
  ],
  vs_baseline: ["Premium $640 per trade vs your usual $220.", "Loss $-160 vs your average loss $-95."],
  data_gaps: ["No path metrics for 1 of 3 trades, so its exit quality is unknown."],
  market_read: "A chop day: SPY closed in the bottom 10% of its range with VIX up 2 points, the day before an FOMC decision. Your calls fought that tape.",
  plan_vs_execution: [
    { ticker: "QQQ", planned: "Calls on a VWAP reclaim, 2 contracts", did: "Bought 2 calls at the reclaim, 10:12", result: "followed" },
    { ticker: "SPY", planned: "Calls only above 581", did: "Bought 4 calls at 579.80, 10:42", result: "deviated" },
  ],
  generated_by: "claude-sonnet-5-5 through claude -p on the Claude plan",
};

test("the calendar says whether nightly plan reviews are set up, and a plan review shows rules kept and broken", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/daily");
  const status = page.getByRole("status", { name: "Nightly AI reviews" });
  await expect(status).toContainText("Nightly AI reviews");
  await page.getByTestId("daily-calendar").locator('a[href^="/daily/2"]').first().click();
  await page.route("**/api/backend/daily-review", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = route.request().postDataJSON() as { day: string };
    await route.fulfill({ json: { day: body.day, review, generated_at: "2026-10-01T00:05:00Z", trade_count: 3 } });
  });
  const run = page.getByRole("button", { name: /Run Daily Analysis|Regenerate Analysis/ });
  await expect(page.getByText("on your Claude plan")).toBeVisible();
  await run.click();
  await expect(page.getByText("The Market That Day")).toBeVisible();
  const plans = page.getByLabel("Plan versus execution");
  await expect(plans).toContainText("Followed");
  await expect(plans).toContainText("Deviated");
  await expect(plans).toContainText("Planned: Calls only above 581");
  const rules = page.getByLabel("Rules from the last review");
  await expect(rules).toContainText("Kept");
  await expect(rules).toContainText("Broken");
  await expect(rules).toContainText("SPY 10:42 call: 4 contracts.");
  await expect(page.getByText("Compared With Your Normal")).toBeVisible();
  await expect(page.getByText("What the review could not see")).toBeVisible();
  await expect(page.getByText("Written by claude-sonnet-5-5 through claude -p on the Claude plan.")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("daily-plan-review-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("daily-plan-review-phone.png"), fullPage: true });
});

const monthly = {
  summary: "Mornings paid, afternoons leaked: +$1,840 before 11:00, -$2,310 after 14:00.",
  month_grade: "C: steady size, but the afternoon habit erased the morning edge",
  edge: [{ finding: "Opening-hour SPY calls", evidence: "22 trades, +$1,840, 64% win rate" }],
  leaks: [{ finding: "Entries after 14:00", evidence: "17 trades, -$2,310, 29% win rate" }, { finding: "Chase entries", evidence: "11 trades, -$960" }],
  recurring_patterns: [{ finding: "Held losers past 30 minutes", evidence: "losers held 41 min median vs winners 12 min" }],
  rules_scorecard: [{ rule: "Max 2 contracts", kept: 14, broken: 3, verdict: "keep" }, { rule: "No entries after 3 PM", kept: 6, broken: 9, verdict: "tighten" }],
  last_commitment_check: { commitment: "Max 2 contracts", result: "kept", evidence: "17 of 20 days at 2 or fewer" },
  one_commitment: "No new entries after 14:00 in October — that window lost $2,310 on 17 trades.",
  vs_last_month: ["Win rate 48% vs 41%", "Average loss -$135 vs -$190"],
  data_gaps: ["Path metrics for 30 of 46 trades"],
  generated_by: "claude-sonnet-5 through claude -p on the Claude plan",
};

test("each calendar month links to its monthly review, which shows the edge, leaks, rules and one commitment", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/daily");
  const link = page.getByRole("link", { name: /Run month review|Month review/ }).first();
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/daily\/month\/\d{4}-\d{2}$/);
  await page.route("**/api/backend/monthly-review", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = route.request().postDataJSON() as { month: string };
    await route.fulfill({ json: { month: body.month, review: monthly, generated_at: "2026-10-01T00:12:00Z", trade_count: 46 } });
  });
  await page.getByRole("button", { name: /Run Monthly Review|Regenerate Monthly Review/ }).click();
  await expect(page.getByLabel("Next month's commitment")).toContainText("No new entries after 14:00");
  await expect(page.getByText("Where Your Money Came From")).toBeVisible();
  await expect(page.getByText("Where It Leaked")).toBeVisible();
  await expect(page.getByLabel("Rules scorecard")).toContainText("Tighten");
  await expect(page.getByText("Last month: Max 2 contracts")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("monthly-review-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("monthly-review-phone.png"), fullPage: true });
});
