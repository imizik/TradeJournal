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

test("audit shows missing and stale evidence without a passing badge", async ({ page }) => {
  await page.route("**/market-context/audit/*", async (route) => {
    const id = route.request().url().split("/").pop();
    await route.fulfill({ json: {
      trade_id: id, ticker: "NVDA", instrument_type: "option", option_type: "call", strike: 100,
      expiration: "2026-09-30", direction: "bullish", opened_at_et: "2026-09-24 10:00:00",
      closed_at_et: "2026-09-24 10:20:00", status: "closed", path: null, indicators: { error: "No daily cache" },
      fills: [{ fill_id: "fill-1", is_entry: true, side: "buy_to_open", executed_at_et: "2026-09-24 10:00:00",
        contracts: 1, price: 100, cache_file: null, cache_exists: false, total_bars_in_file: 0,
        rth_bars_to_fill: 0, pm_bars: 0, or5_bars: 0, raw_bar: null, bars_back: null,
        formulas: {}, structure: null, stored: {}, recomputed: {}, discrepancies: [] }],
      validation: { broker_verification: "not_performed", checks: [
        { field: "entry_vwap", stored: 100, reference: null, status: "unavailable", reason: "No completed minute bars" },
        { field: "option_peak_total_pnl", stored: 190, reference: 190, status: "stale", reason: "Stored calculation version is obsolete" },
      ], option: { values: {}, reason: "No unambiguous holding-minute bars" } },
    } });
  });
  await page.goto("/trades");
  await page.getByRole("cell", { name: "NVDA", exact: true }).first().click();
  await page.getByRole("button", { name: "Show Audit" }).click();
  await expect(page.getByText("Matched 0 · Mismatch 0 · Stale 1 · Unavailable 1 · Error 0")).toBeVisible();
  await expect(page.getByText("Broker reconciliation has not been performed.", { exact: false })).toBeVisible();
  await expect(page.getByText("No completed bar evidence available")).toBeVisible();
  await expect(page.getByText("no discrepancies", { exact: false })).toHaveCount(0);
  await expect(page.getByText("Stored calculation version is obsolete")).toBeVisible();
});

test("audit distinguishes a changed accounting value from a cached match", async ({ page }) => {
  await page.route("**/market-context/audit/*", async (route) => {
    await route.fulfill({ json: {
      trade_id: "audit-1", ticker: "NVDA", instrument_type: "option", option_type: "call", strike: 100,
      expiration: null, direction: null, opened_at_et: "2026-09-24 10:00:00", closed_at_et: null,
      status: "open", path: null, indicators: null, fills: [],
      validation: { broker_verification: "not_performed", checks: [
        { field: "realized_pnl", stored: 999, reference: 10, status: "mismatch", kind: "internal_accounting" },
        { field: "avg_entry_premium", stored: 100, reference: 100, status: "matched", kind: "internal_accounting" },
      ] },
    } });
  });
  await page.goto("/trades");
  await page.getByRole("cell", { name: "NVDA", exact: true }).first().click();
  await page.getByRole("button", { name: "Show Audit" }).click();
  await expect(page.getByText("Matched 1 · Mismatch 1 · Stale 0 · Unavailable 0 · Error 0")).toBeVisible();
  await expect(page.getByText("999 → 10")).toBeVisible();
});
