import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`trade filters survive status changes and a detail round trip at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/trades?ticker=AAPL");
    await page.getByRole("link", { name: /^open$/i }).click();
    await expect(page).toHaveURL(/ticker=AAPL/);
    await expect(page.getByRole("table").getByRole("link", { name: "RNXT", exact: true })).toHaveCount(0);
    await page.getByRole("link", { name: "Individual", exact: true }).click();
    await page.getByRole("link", { name: /^option$/i }).click();
    const filtered = new URL(page.url());
    expect(Object.fromEntries(filtered.searchParams)).toEqual({ status: "open", account: "individual", type: "option", ticker: "AAPL" });
    const returnTo = filtered.pathname + filtered.search;
    const row = page.getByRole("table").getByRole("link", { name: "AAPL", exact: true });
    await expect(row).toHaveCount(1);
    await row.click();
    const back = page.getByRole("link", { name: "Back", exact: true });
    await expect(back).toHaveAttribute("href", returnTo);
    await back.click();
    await expect(page).toHaveURL(filtered.href);
    await expect(page.getByRole("table").getByRole("link")).toHaveCount(1);
    await page.screenshot({ path: test.info().outputPath(`trades-filter-return-${width === 390 ? "phone" : "desktop"}.png`) });

    // Unfiltered entry keeps the familiar Back to Trades destination.
    await page.goto("/trades");
    await page.getByRole("table").getByRole("link", { name: "AAPL", exact: true }).first().click();
    await expect(page.getByRole("link", { name: "Back to Trades", exact: true })).toHaveAttribute("href", "/trades");
  });
}
