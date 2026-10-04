import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8099";

test("analytics drills into groups and winning outliers", async ({ page }, testInfo) => {
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Breakdown explorer" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("analytics-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("analytics-phone.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 720 });
  const breakdown = page.getByRole("table", { name: "Analytics breakdown" });
  await breakdown.getByRole("button", { name: "NVDA", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ticker: NVDA", exact: true })).toBeVisible();
  const trades = page.getByRole("table", { name: "Analytics trades" });
  await expect(trades.locator("tbody tr")).toHaveCount(1);
  await expect(trades.getByRole("link", { name: "NVDA", exact: true })).toBeVisible();
  await expect(trades.getByRole("link", { name: "TSLA", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Show all selected trades" }).click();
  await expect(trades.getByRole("link", { name: "TSLA", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Inspect winners" }).first().click();
  await expect(page.getByRole("heading", { name: "Best 1 winning trades" })).toBeVisible();
  await expect(trades.locator("tbody tr")).toHaveCount(1);
  await trades.getByRole("link", { name: "NVDA", exact: true }).click();
  await expect(page).toHaveURL(/\/trades\/[0-9a-f-]+$/);
});

test("date, exact account, and instrument filters affect the same population", async ({ page, request }) => {
  const response = await request.get(`${API}/stats/analytics`);
  expect(response.ok()).toBeTruthy();
  const all = await response.json();
  const nvda = all.trades.find((trade: { ticker: string }) => trade.ticker === "NVDA");
  const day = nvda.closed_at.slice(0, 10);
  await page.goto("/analytics");
  await page.getByLabel("Closed from", { exact: true }).fill(day);
  await page.getByLabel("Closed through", { exact: true }).fill(day);
  await page.getByLabel("Account", { exact: true }).selectOption(nvda.account_id);
  await page.getByLabel("Instrument", { exact: true }).selectOption("option");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(new RegExp(`start=${day}.*end=${day}.*account_id=${nvda.account_id}.*instrument_type=option`));
  const expected = await (await request.get(`${API}/stats/analytics?start=${day}&end=${day}&account_id=${nvda.account_id}&instrument_type=option`)).json();
  await expect(page.getByLabel("Data coverage")).toContainText(`${expected.summary.pnl_count} of ${expected.summary.count}`);
  const links = page.getByRole("table", { name: "Analytics trades" }).locator("tbody a");
  await expect(links).toHaveCount(expected.trades.length);
  for (const trade of expected.trades) {
    await expect(page.locator(`table[aria-label="Analytics trades"] a[href="/trades/${trade.id}"]`)).toBeVisible();
  }
  await page.getByRole("link", { name: "Reset", exact: true }).click();
  await expect(page).toHaveURL(/\/analytics$/);
  await expect(page.getByLabel("Data coverage")).toContainText(`${all.summary.pnl_count} of ${all.summary.count}`);
});

test("group selection, sample filters, and empty results stay honest", async ({ page }) => {
  await page.goto("/analytics");
  await page.getByLabel("Group by", { exact: true }).selectOption("repeat_entry");
  const breakdown = page.getByRole("table", { name: "Analytics breakdown" });
  await expect(breakdown.getByRole("button", { name: "First entry time", exact: true })).toBeVisible();
  await page.getByLabel("Minimum trades", { exact: true }).selectOption("20");
  await expect(breakdown).toContainText("No groups match this selection and minimum sample.");
  await expect(page.getByLabel("Data coverage")).toContainText("3 of 3");
  await page.getByLabel("Minimum trades", { exact: true }).selectOption("1");
  await page.getByLabel("Group by", { exact: true }).selectOption("tag");
  await expect(breakdown.getByRole("button", { name: "Untagged", exact: true })).toBeVisible();
  await page.goto("/analytics?start=2099-01-01");
  await expect(page.getByLabel("Data coverage")).toContainText("0 of 0");
  await expect(page.getByRole("table", { name: "Analytics trades" })).toContainText("No closed trades in this selection.");
  await expect(page.getByText("No priced closed trades in this selection.", { exact: true })).toBeVisible();
});

test("invalid filter combinations have a recoverable error", async ({ page }) => {
  await page.goto("/analytics?start=2026-09-02&end=2026-09-01");
  await expect(page.getByRole("alert").filter({ hasText: "Check your filters" })).toBeVisible();
  await page.getByRole("link", { name: "Reset", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Breakdown explorer" })).toBeVisible();
});
