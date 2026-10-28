import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/exit-habits-seed`)).ok()).toBe(true);
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBe(true);
});

for (const [size, width, height] of [["desktop", 1440, 1000], ["phone", 390, 844]] as const) {
  test(`proof page states every verdict with its rule and sample on ${size}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto("/proof");
    // Alerts: every seeded trade predates the alerts, so nothing is claimed.
    const alerts = page.getByTestId("proof-alerts-verdict");
    await expect(alerts).toContainText("Not enough data");
    await expect(alerts).toContainText("0 of 30 trades closed since the alerts went live.");
    await expect(alerts).toContainText("Sample: 0 of the last 30 trades since 2026-10-21 vs 2 before");
    await expect(alerts).toContainText("2 standard errors");
    const card = page.getByRole("region", { name: "Exit habits and alert follow-up" });
    await expect(card).toContainText("What you did after 3 alerts");
    await expect(card).toContainText("does not establish that alerts caused a change");
    await expect(card).toContainText("not a guaranteed exit price");
    // The habits against baseline, counts only, and each alert's follow-up (moved here from the Dashboard card).
    await expect(card).toContainText("0 since phone alerts went live on Oct 21, against 2 before");
    await expect(card).toContainText("Too few trades yet to read a change");
    await expect(card).not.toContainText(/improv|grade|score/i);
    const expired = card.getByTestId("habit-expired_worthless");
    await expect(expired).toContainText("Since Oct 21 (0 of 30 so far)");
    await expect(expired).toContainText("no trades");
    await expect(expired).toContainText("1 of 2 · 50% · -$300");
    await expect(card.getByTestId("habit-green_to_red")).toContainText("2 trades, no data"); // no path metrics in the seed
    const rows = card.getByTestId("exit-habits-alert");
    await expect(rows).toHaveCount(3);
    const nvda = rows.filter({ hasText: "NVDA" });
    await expect(nvda).toContainText("Gave back its gain");
    await expect(nvda).toContainText("Closed within 15 min");
    await expect(nvda).toContainText("Your result was $250 above the recorded midpoint value at the alert."); // 5 sold at $700 vs a $650 mark
    const tsla = rows.filter({ hasText: "TSLA" });
    await expect(tsla).toContainText("Held an hour");
    await expect(tsla).toContainText("Let it expire");
    await expect(tsla).toContainText("Your result was $240 below the recorded midpoint value at the alert.");
    const aapl = rows.filter({ hasText: "AAPL" });
    await expect(aapl).toContainText("Trimmed within 15 min");
    await expect(aapl).toContainText("Still open, so there is no result yet.");
    await expect(nvda.getByRole("link")).toHaveAttribute("href", /^\/trades\/[0-9a-f-]{36}\?alert=[0-9a-f-]{36}$/); // the alert itself, not just its trade
    // Radar: one sample event, unrated.
    const radar = page.getByTestId("proof-radar-verdict");
    await expect(radar).toContainText("Not enough data");
    await expect(radar).toContainText("0 of 20 rated events needed.");
    await expect(radar).toContainText("Rule: Helping: at least 20 rated events with 40%+ rated useful");
    const radarCard = page.getByRole("region", { name: "Does Radar find what you'd miss, early enough?" });
    await expect(radarCard).toContainText("1 event over 1 session of radar-rules-sample: 1 stock, 0 group");
    await expect(radarCard.getByText("Not rated").locator("..")).toContainText("1");
    // Planning: a secondary read; every seeded trade predates the plan card, so nothing is claimed.
    const planningCard = page.getByRole("region", { name: "Do planned trades do better?" });
    await expect(planningCard).toContainText("A secondary read, not a third proof.");
    const planning = page.getByTestId("proof-planning-verdict");
    await expect(planning).toContainText("Not enough data");
    await expect(planning).toContainText("0 planned and 0 unplanned of 20 each needed.");
    await expect(planning).toContainText("Sample: 0 planned vs 0 unplanned closed long options since 2026-10-25; 0 with a late plan, not counted");
    await expect(planning).toContainText("by 2 standard errors (clustered by entry day)");
    await expect(page.getByTestId("proof-planning-caveat")).toContainText("Selection-biased");
    await expect(page.getByTestId("proof-planning-caveat")).toContainText("not that planning causes it");
    await expect(planningCard.getByTestId("plan-group-planned")).toContainText("0 trades");
    await expect(planningCard.getByTestId("plan-group-late")).toContainText("shown, not counted");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`proof-${size}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
