import { expect, test } from "@playwright/test";

// Rendering tests use controlled market responses; financial calculations are
// independently covered by backend/tests/test_trustworthy_metrics.py.
test("trade detail distinguishes total peak, open peak, and context timing", async ({ page }) => {
  await page.route("**/market-context/fills/bulk?*", async (route) => {
    const id = new URL(route.request().url()).searchParams.get("ids")!.split(",")[0];
    await route.fulfill({ json: { [id]: {
      fill_id: id, data_source: "alpaca_iex", calculation_version: "entry-context-v2",
      entry_context_as_of: "2026-09-24T10:00:00", entry_underlying_price: 100,
    } } });
  });
  await page.route("**/market-context/trade/*", async (route) => {
    await route.fulfill({ json: {
      calculation_version: "position-path-v2", data_source: "alpaca_iex", option_path_quality: "observed_1min",
      option_peak_total_pnl: 190, option_peak_unrealized_pnl: 100,
      option_giveback_from_peak: 0, option_exit_efficiency: 100,
    } });
  });
  await page.goto("/trades");
  await page.getByRole("cell", { name: "NVDA", exact: true }).first().click();
  await expect(page.getByText("Completed bars through 10:00 ET")).toBeVisible();
  await expect(page.getByText("Peak Total P&L").locator("..")).toContainText("+$190");
  await expect(page.getByText("Peak Open P&L").locator("..")).toContainText("+$100");
  await expect(page.getByText("missing bars can hide larger moves", { exact: false })).toBeVisible();
});

test("legacy calculations carry a recompute notice", async ({ page }) => {
  await page.route("**/market-context/trade/*", async (route) => {
    await route.fulfill({ json: { calculation_version: null, data_source: "alpaca_iex", underlying_mfe_pct: 2 } });
  });
  await page.goto("/trades");
  await page.getByRole("cell", { name: "NVDA", exact: true }).first().click();
  await expect(page.getByText("Historical calculation. Recompute before comparing setups.")).toBeVisible();
});
