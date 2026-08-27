import { expect, test } from "@playwright/test";

/**
 * Page-render smoke tests.
 *
 * The bar these clear: a page fetched real data from the backend and put real
 * values in the DOM. They are deliberately not exhaustive UI tests — the
 * failure they exist to catch is "the page is blank / throwing / showing
 * nothing", which typecheck, lint and build all miss.
 *
 * Every asserted number traces back to EXPECTED in
 * backend/scripts/seed_dev_data.py, which pytest independently verifies the
 * reconstructor still produces (backend/tests/test_seed_dev_data.py).
 */

const API = "http://127.0.0.1:8099";

test.describe("fixture", () => {
  test("seeded backend holds exactly the expected dataset", async ({ request }) => {
    // Runs first so contamination surfaces as one clear failure here rather
    // than as several confusing assertion failures across the page tests.
    // The usual cause is manual fills being restored from
    // backend/data/manual_fills.json into the e2e database on startup.
    const stats = await (await request.get(`${API}/stats`)).json();

    expect(
      stats,
      "e2e database does not match the seed fixture — something added data to it",
    ).toMatchObject({
      total_trades: 6,
      open_trades: 2,
      closed_trades: 4,
      total_pnl: 1154, // NVDA 1300 + RNXT 135 + RCAT 19 - TSLA 300
    });
  });
});

test.describe("dashboard", () => {
  test("renders seeded totals and open positions", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Aggregates computed by the backend from the seeded trades.
    await expect(page.getByText("+$1154").first()).toBeVisible();
    await expect(page.getByText("75.0%").first()).toBeVisible();

    // Both open positions reach the table, and the two AAPL positions stay
    // separated by account rather than merging.
    const openPositions = page.getByRole("table").first();
    await expect(openPositions.getByText("Roth IRA").first()).toBeVisible();
    await expect(openPositions.getByText("Individual").first()).toBeVisible();
  });
});

test.describe("trades", () => {
  test("lists every seeded trade with its P&L", async ({ page }) => {
    await page.goto("/trades");

    await expect(page.getByRole("heading", { name: "Trades" })).toBeVisible();

    for (const ticker of ["NVDA", "AAPL", "TSLA", "RNXT", "RCAT"]) {
      await expect(
        page.getByRole("cell", { name: ticker, exact: true }).first(),
        `${ticker} is missing from the trades table`,
      ).toBeVisible();
    }

    // Values, not just presence: a table of empty rows would pass otherwise.
    await expect(page.getByText("+$1300").first()).toBeVisible();
    await expect(page.getByText("+$19").first()).toBeVisible();
  });

  test("a trade opens its detail page with a fill timeline", async ({ page }) => {
    await page.goto("/trades");

    // Navigate the way a user does, so the row link is covered too.
    await page.getByRole("cell", { name: "NVDA", exact: true }).first().click();
    await page.waitForURL(/\/trades\/[0-9a-f-]+$/);

    await expect(page.getByText("NVDA").first()).toBeVisible();
    // The scale-in: two entry fills and one exit reconstructed into one trade.
    await expect(page.getByText("+$1300").first()).toBeVisible();
  });
});

test.describe("fills", () => {
  test("renders the seeded fill history", async ({ page }) => {
    await page.goto("/fills");

    await expect(page.getByRole("heading", { name: "Fills" })).toBeVisible();

    // The table is client-rendered, so this also proves the browser-side
    // fetch reached the backend.
    await expect(page.getByText("RNXT").first()).toBeVisible();
    await expect(page.getByText("RCAT").first()).toBeVisible();
  });
});

test.describe("analytics", () => {
  test("breaks seeded trades down by ticker", async ({ page }) => {
    await page.goto("/analytics");

    await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();

    const byTicker = page.getByRole("table").first();
    await expect(byTicker.getByText("NVDA")).toBeVisible();
    await expect(byTicker.getByText("+$1300")).toBeVisible();
    // The expired TSLA position: a full loss, and negative values render.
    await expect(byTicker.getByText("TSLA")).toBeVisible();
    await expect(byTicker.getByText("$-300")).toBeVisible();
  });
});

test.describe("strategy lab", () => {
  test("loads without data", async ({ page }) => {
    // Strategy Lab is a separate domain with nothing seeded; this checks the
    // empty state renders rather than throwing.
    await page.goto("/strategy-lab");
    await expect(page.getByRole("heading").first()).toBeVisible();
  });
});

test("no page throws an uncaught error or fails a request", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`uncaught: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 500) {
      problems.push(`${response.status()} ${response.url()}`);
    }
  });

  for (const route of ["/", "/trades", "/fills", "/analytics", "/daily", "/strategy-lab"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
  }

  expect(problems, `pages reported errors:\n${problems.join("\n")}`).toEqual([]);
});
