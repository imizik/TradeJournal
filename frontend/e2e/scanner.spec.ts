import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const defaults = ["AAPL", "AMZN", "GOOGL", "META", "SPY", "QQQ", "NBIS", "MU", "CRDO", "MRVL", "LLY", "AMD"];

test.beforeEach(async ({ request }) => {
  const current = await (await request.get(`${API}/scanner/settings`)).json();
  expect((await request.put(`${API}/scanner/settings`, { data: { symbols: defaults, base_revision: current.revision } })).ok()).toBeTruthy();
});

for (const [size, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`scanner ticker editing persists on ${size}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto("/scanner?day=2026-10-07");
    const panel = page.getByRole("region", { name: "Scanner tickers" });
    await expect(panel.getByText("12 / 12")).toBeVisible();
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`scanner-tickers-${size}.png`) });
    await panel.getByRole("button", { name: "Edit tickers" }).click();
    await panel.getByLabel("Add tickers").fill("NVDA");
    await panel.getByRole("button", { name: "Add", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("up to 12 tickers");
    await panel.getByRole("button", { name: "Remove AAPL", exact: true }).click();
    await panel.getByRole("button", { name: "Add", exact: true }).click();
    await expect(panel.getByRole("button", { name: "Remove NVDA" })).toBeVisible();
    await panel.getByLabel("Add tickers").fill("mu");
    await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
    await expect(panel.getByRole("status")).toContainText("Saved");
    await page.reload();
    await expect(panel.getByLabel("Saved tickers")).toContainText("NVDA");
    await expect(panel.getByLabel("Saved tickers")).not.toContainText("AAPL");
    await panel.getByRole("button", { name: "Edit tickers" }).click();
    await panel.getByRole("button", { name: "Remove NVDA" }).click();
    await panel.getByLabel("Add tickers").fill("BAD!");
    await panel.getByRole("button", { name: "Add", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("Use ticker symbols");
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`scanner-tickers-edit-${size}.png`) });
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByLabel("Saved tickers")).toContainText("NVDA");
    expect(errors).toEqual([]);
  });
}

test("scanner handles conflicting saves, an empty list and request failures", async ({ page, request }) => {
  await page.goto("/scanner");
  const panel = page.getByRole("region", { name: "Scanner tickers" });
  await panel.getByRole("button", { name: "Edit tickers" }).click();
  await panel.getByRole("button", { name: "Remove AAPL" }).click();
  const current = await (await request.get(`${API}/scanner/settings`)).json();
  expect((await request.put(`${API}/scanner/settings`, { data: { symbols: ["MU"], base_revision: current.revision } })).ok()).toBeTruthy();
  await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("changed on another device");
  await expect(panel.getByRole("button", { name: "Remove AMD" })).toBeVisible();
  await panel.getByRole("button", { name: "Reload saved tickers" }).click();
  await expect(panel.getByRole("button", { name: "Remove AMD" })).toHaveCount(0);
  await panel.getByRole("button", { name: "Remove MU" }).click();
  await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
  await expect(panel.getByText("No tickers selected. New setups are paused.")).toBeVisible();
  await page.reload();
  await expect(panel.getByText("No tickers selected. New setups are paused.")).toBeVisible();
  await panel.getByRole("button", { name: "Edit tickers" }).click();
  await panel.getByLabel("Add tickers").fill("MU");
  await page.route("**/scanner/settings", async (route) => {
    if (route.request().method() === "PUT") await route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
    else await route.continue();
  });
  await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("Temporarily unavailable");
  await expect(panel.getByLabel("Add tickers")).toHaveValue("MU");
  await page.unroute("**/scanner/settings");
  await panel.getByRole("button", { name: "Save tickers", exact: true }).click();
  await expect(panel.getByLabel("Saved tickers")).toHaveText("MU");
  await page.route("**/scanner/settings", (route) => route.fulfill({ status: 503 }));
  await page.reload();
  await expect(panel.getByRole("alert")).toContainText("Could not load");
  await page.unroute("**/scanner/settings");
  await panel.getByRole("button", { name: "Reload tickers" }).click();
  await expect(panel.getByLabel("Saved tickers")).toHaveText("MU");
});

for (const [size, width, height] of [["desktop", 1440, 900], ["phone", 390, 844]] as const) {
  test(`scanner setups come first with unambiguous paper timing on ${size}`, async ({ page, request }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    expect((await request.post(`${API}/__test/scanner-amzn`)).ok()).toBeTruthy();
    await page.setViewportSize({ width, height });
    await page.goto("/scanner?day=2026-10-19");
    const setups = page.getByRole("region", { name: "Setups" });
    const amzn = setups.getByRole("listitem", { name: /^AMZN/ });
    await expect(amzn).toBeVisible();
    // The 10:10 setup bar close is not the 10:11:10 paper entry or the 10:55:54 paper exit.
    await expect(amzn.getByTestId("latest-event")).toHaveText("Paper exit 10:55:54 AM ET · Target+$288.70");
    await expect(amzn.getByText("Paper: closed")).toBeVisible();
    const timing = (label: string) => amzn.locator("dl").first().locator("div").filter({ has: page.getByText(label, { exact: true }) });
    await expect(timing("Setup bar close")).toContainText("10:10 AM ET");
    await expect(timing("Paper entry")).toContainText("10:11:10 AM ET$1.80 ask");
    await expect(timing("Paper exit")).toContainText("10:55:54 AM ET$4.70 bid · Target");
    await expect(timing("Stock stop/target")).toContainText("219.10 / 222.40");
    await expect(timing("Option premium")).toContainText("$1.80 → $4.70");
    await expect(timing("Time-stop deadline")).toContainText("11:11:10 AM ET");
    await expect(page.getByText("Rules paper P&L · one contract per priced setup")).toBeVisible();

    // Setups sit above the comparison scorecards, and nothing scrolls sideways.
    const setupsTop = (await setups.boundingBox())!.y;
    expect(setupsTop).toBeLessThan((await page.getByRole("region", { name: "Day scorecard scorecard" }).boundingBox())!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
    for (const part of [amzn.getByText("AMZN", { exact: true }), amzn.getByText("Paper: closed"), amzn.getByTestId("latest-event")]) {
      const box = (await part.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(width);
    }
    await amzn.getByText(/^Comparison detail/).click();
    await expect(amzn.getByText("Setup email")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();

    // A past day has a manual refresh only; monitoring freshness is reported separately.
    const freshness = page.getByRole("region", { name: "Scanner freshness" });
    await expect(freshness).toContainText("Page updated at");
    await expect(freshness).toContainText("past day, no auto-refresh");
    await expect(freshness).toContainText("Scanner monitoring now:");
    await freshness.getByRole("button", { name: "Refresh" }).click();
    await expect(freshness.getByRole("button", { name: "Refresh" })).toBeEnabled();
    await setups.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`scanner-setups-${size}.png`), fullPage: true });

    await page.goto("/scanner?day=2026-10-18");
    await expect(page.getByRole("region", { name: "Setups" })).toContainText("The market was closed on this date");
    await page.goto("/scanner");
    await expect(page.getByRole("region", { name: "Scanner freshness" })).toContainText("refreshes every 60 s while this tab is visible");
    expect(errors).toEqual([]);
  });
}
