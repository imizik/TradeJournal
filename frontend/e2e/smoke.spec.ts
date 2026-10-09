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

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;

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
      open_trades: 3,
      closed_trades: 3,
      total_pnl: 1019, // NVDA 1300 + RCAT 19 - TSLA 300; open RNXT is excluded
    });
  });
});

test.describe("dashboard", () => {
  test("renders realized performance, range metrics, and open positions", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Today comes first: today's P&L and the open positions sit above the all-time performance.
    const main = page.locator("main").first();
    const order = await main.evaluate((root) => {
      const text = root.textContent ?? "";
      return { today: text.indexOf("Today's Closed P&L"), positions: text.indexOf("Shows what is still open"), performance: text.indexOf("Trading Performance") };
    });
    expect(order.today).toBeGreaterThanOrEqual(0);
    expect(order.positions).toBeGreaterThanOrEqual(0);
    expect(order.today).toBeLessThan(order.performance);
    expect(order.positions).toBeLessThan(order.performance);
    // Money always puts the sign before the dollar sign.
    await expect(main).not.toContainText("$-");
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.screenshot({ path: test.info().outputPath("dashboard-desktop.png") });

    // Aggregates computed from the seeded, reconstructed closed trades.
    await expect(page.getByText("+$1,019.00").first()).toBeVisible();
    await expect(page.getByText("4.40", { exact: true })).toBeVisible();
    await expect(page.getByText("+$339.67", { exact: true })).toBeVisible();

    // A period selection recomputes the total and trader metrics from the
    // closes inside that window. The seed's TSLA expiry and RCAT close are in 1M.
    await page.getByRole("button", { name: "1M" }).click();
    await expect(page.getByText("1M Closed P&L")).toBeVisible();
    await expect(page.getByText("-$281.00", { exact: true })).toBeVisible();
    await expect(page.getByText("Closed Trades", { exact: true }).locator("xpath=..")).toContainText("2");
    await page.getByRole("button", { name: "ALL" }).click();
    await expect(page.getByText("+$1,019.00", { exact: true })).toBeVisible();

    // All three open positions reach the table, and the two AAPL positions
    // stay separated by account rather than merging.
    const openPositions = page.getByRole("table").first();
    await expect(openPositions.getByText("RNXT").first()).toBeVisible();
    await expect(openPositions.getByText("Roth IRA").first()).toBeVisible();
    await expect(openPositions.getByText("Individual").first()).toBeVisible();
  });

  test("refreshes server-rendered tables when a sync job finishes", async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (request) => {
      if (["fetch", "xhr"].includes(request.resourceType())) requests.push(request.url());
    });
    await page.goto("/");
    const frontendOrigin = new URL(page.url()).origin;

    await page.getByRole("button", { name: "Sync / Update Data" }).click();
    const fillCheck = page.locator("section").filter({ hasText: "Import/manual fills check" });
    await expect(fillCheck).toBeVisible();

    const pageRefresh = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return url.origin === frontendOrigin && url.pathname === "/" && request.headers().rsc === "1";
    });

    const queued = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/backend/sync/jobs/fill_import_check/run" && response.ok(),
    );
    await fillCheck.getByRole("button", { name: "Run" }).click();
    await queued;
    await pageRefresh;
    expect(requests.some((url) => new URL(url).port === new URL(API).port || new URL(url).port === "8080")).toBe(false);
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
    await expect(page.getByText("+$1,300").first()).toBeVisible();
    await expect(page.getByText("+$19").first()).toBeVisible();
    // Short calendar expiries, cents on prices, hold in hours and days.
    const table = page.getByRole("table");
    await expect(table).toContainText("Jan 7, 2027");
    await expect(table).not.toContainText("2027-01-07");
    await expect(table).not.toContainText("$-");
  });

  test("the daily review calendar tints each trade day by what closed and links to its review", async ({ page }) => {
    await page.goto("/daily");
    await expect(page.getByRole("heading", { name: "Daily Review Calendar" })).toBeVisible();
    const days = page.locator('a[href^="/daily/2"]');
    await expect(days.first()).toBeVisible();
    // Every trade day names its trades, what closed and whether it is reviewed.
    for (const label of await days.evaluateAll((links) => links.map((link) => link.getAttribute("aria-label") ?? ""))) {
      expect(label).toMatch(/^\w{3}, \w{3} \d{1,2}, \d{4}: \d+ trades?, (nothing closed|[+-]?\$[\d,]+), (reviewed|not reviewed|review needs refresh)$/);
    }
    expect((await days.evaluateAll((links) => links.map((link) => link.getAttribute("aria-label")))).some((label) => /[+-]\$/.test(label ?? ""))).toBe(true);
    await expect(page.getByText("trade(s)")).toHaveCount(0);
    // Every trade day the index lists has a cell, weekends included.
    const listed = (await (await page.request.get("/api/backend/daily-review")).json()) as { day: string }[];
    await expect(days).toHaveCount(listed.length);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: test.info().outputPath("daily-calendar.png") });
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

    // The table is server-rendered; Sync Center above covers browser fetches.
    await expect(page.getByText("RNXT").first()).toBeVisible();
    await expect(page.getByText("RCAT").first()).toBeVisible();
  });
});

test.describe("analytics", () => {
  test("breaks seeded trades down by ticker", async ({ page }) => {
    await page.goto("/analytics");

    await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();

    const byTicker = page.getByRole("table", { name: "Analytics breakdown" });
    await expect(byTicker.getByText("NVDA")).toBeVisible();
    await expect(byTicker.getByRole("row").filter({ has: page.getByRole("button", { name: "NVDA", exact: true }) }).locator("td").nth(2)).toHaveText("+$1,300.00");
    // The expired TSLA position: a full loss, and negative values render.
    await expect(byTicker.getByText("TSLA")).toBeVisible();
    await expect(byTicker.getByRole("row").filter({ has: page.getByRole("button", { name: "TSLA", exact: true }) }).locator("td").nth(2)).toHaveText("−$300.00");
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
