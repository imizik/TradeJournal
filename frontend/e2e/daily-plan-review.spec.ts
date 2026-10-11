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
