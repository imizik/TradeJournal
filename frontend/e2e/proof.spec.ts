import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/exit-habits-seed`)).ok()).toBe(true);
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBe(true);
});

for (const [size, width, height] of [["desktop", 1440, 1000], ["phone", 390, 844]] as const) {
  test(`proof page states both verdicts with their rule and sample on ${size}`, async ({ page }) => {
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
    const card = page.getByRole("region", { name: "Do position alerts help you reconsider?" });
    await expect(card).toContainText("What you did after 3 alerts");
    await expect(card.getByTestId("exit-habits-alert")).toHaveCount(3);
    // Radar: one sample event, unrated.
    const radar = page.getByTestId("proof-radar-verdict");
    await expect(radar).toContainText("Not enough data");
    await expect(radar).toContainText("0 of 20 rated events needed.");
    await expect(radar).toContainText("Rule: Helping: at least 20 rated events with 40%+ rated useful");
    const radarCard = page.getByRole("region", { name: "Does Radar find what you'd miss, early enough?" });
    await expect(radarCard).toContainText("1 event over 1 session of radar-rules-sample: 1 stock, 0 group");
    await expect(radarCard.getByText("Not rated").locator("..")).toContainText("1");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`proof-${size}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
