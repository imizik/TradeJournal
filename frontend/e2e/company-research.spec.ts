import { test, expect } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`company research persists a thesis and shows source gaps at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const company = { id: "11111111-1111-4111-8111-111111111111", symbol: "NVDA", name: "Sample company", revision: 0, followed: true, thesis: "", assumptions: [] as string[], latest: {} as Record<string, unknown> };
    let added = false;
    await page.route("**/api/backend/company-research/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      if (path.endsWith("/companies") && method === "POST") { added = true; return route.fulfill({ json: company }); }
      if (path.endsWith("/companies")) return route.fulfill({ json: added ? [company] : [] });
      if (method === "PATCH") { const body = route.request().postDataJSON(); Object.assign(company, body, { revision: company.revision + 1 }); return route.fulfill({ json: company }); }
      if (path.endsWith("/refresh")) {
        company.latest = { actuals: { id: "obs-1", component: "actuals", provider: "SEC EDGAR", observed_at: "2026-10-30T12:00:00Z", data: { state: "ready", quarters: [
          { end: "2026-01-31", fiscal_period: "Q4", fiscal_year: 2026, gap: true, revenue: null, eps_diluted: null, evidence: {} },
          { end: "2026-04-30", fiscal_period: "Q1", fiscal_year: 2027, gap: false, revenue: "100000000", eps_diluted: "1.25", gross_margin: "0.5", operating_margin: "0.2", net_income: "20000000", evidence: { revenue: { url: "https://www.sec.gov/Archives/edgar/data/1/", filed: "2026-05-20", accession: "0001-26-001" } } },
        ] } } };
        return route.fulfill({ json: { status: "queued" } });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto("/research/companies");
    await expect(page.getByText("Your list starts empty.", { exact: false })).toBeVisible();
    await page.getByLabel("Company ticker").fill("NVDA");
    await page.getByRole("button", { name: "Add company" }).click();
    await page.getByRole("link", { name: "NVDA", exact: true }).click();
    await page.getByRole("button", { name: "Refresh sources" }).click();
    await expect(page.getByText("Annual results are not substituted", { exact: false })).toBeVisible();
    await page.getByLabel("Fiscal period").selectOption("1");
    await expect(page.getByText("$100M", { exact: true })).toBeVisible();
    await page.getByText("Source evidence", { exact: true }).click();
    await expect(page.getByRole("link", { name: "SEC filing 0001-26-001" })).toHaveAttribute("href", "https://www.sec.gov/Archives/edgar/data/1/");
    await page.screenshot({ path: test.info().outputPath(`company-results-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Thesis & research" }).click();
    await page.getByRole("button", { name: "Edit thesis", exact: true }).click();
    await page.getByLabel("Thesis", { exact: true }).fill("Margins will improve as capacity ramps.");
    await page.getByLabel("Assumptions (up to five, one per line)").fill("Capacity arrives on schedule");
    await page.getByRole("button", { name: "Save thesis" }).click();
    await expect(page.getByText("Margins will improve as capacity ramps.", { exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: "Thesis & research" }).click();
    await expect(page.getByText("Margins will improve as capacity ramps.", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: test.info().outputPath(`company-thesis-${width}.png`), fullPage: true });
  });
}
