import { expect, test, type Page } from "@playwright/test";

// The e2e backend runs with the lab off, so these tests stand in only for its status read (and an empty
// investigation list). Nothing here sends a turn.
const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, tools: [], limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};

async function labOn(page: Page) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
}

async function openMuEvent(page: Page) {
  await page.goto("/radar");
  await page.getByRole("region", { name: "New since your last visit" }).getByTestId("radar-event").getByRole("button").first().click();
  await expect(page.getByRole("region", { name: "Original evidence" })).toContainText("As first saved");
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
});

test("no Ask copilot entry point while the lab is off", async ({ page }) => {
  await openMuEvent(page);
  await expect(page.getByRole("link", { name: /Open chart · MU/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ask copilot/ })).toHaveCount(0);
});

test("Radar's Ask copilot opens a new, prefilled, unsent investigation", async ({ page }) => {
  await labOn(page);
  await openMuEvent(page);
  const ask = page.getByRole("link", { name: "Ask copilot · MU" });
  const href = new URL((await ask.getAttribute("href"))!, "http://fixture");
  expect(href.pathname).toBe("/copilot-lab");
  expect(href.searchParams.get("symbol")).toBe("MU");
  expect(href.searchParams.get("context")).toMatch(/^Radar .+: MU up 4\.1% while SMH is up 0\.6%/);
  await ask.click();
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=MU/);
  await expect(page.getByLabel("Investigation symbol")).toHaveValue("MU");
  await expect(page.getByLabel("Message")).toHaveValue(/^Context: Radar .+MU up 4\.1%/);
  await expect(page.getByText(/Ask about an opportunity/)).toBeVisible(); // nothing was sent
});

test("Charts' Overview offers Ask copilot for the current symbol", async ({ page }) => {
  await labOn(page);
  await page.goto("/charts?symbol=MU");
  const info = page.getByRole("region", { name: "Symbol info", exact: true });
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(info.getByRole("link", { name: "Ask copilot · MU" })).toHaveAttribute("href", "/copilot-lab?symbol=MU");
});

test("the lab fits a 375 px phone without sideways scrolling", async ({ page }) => {
  await labOn(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/copilot-lab?symbol=NBIS&context=Radar%2010%3A41%20AM%3A%20NBIS%20up%203%25%20while%20its%20group%20is%20flat");
  await expect(page.getByLabel("Message")).toHaveValue(/^Context: Radar 10:41 AM/);
  const send = page.getByRole("button", { name: "Send" });
  await expect(send).toBeInViewport();
  expect((await send.boundingBox())!.height).toBeGreaterThanOrEqual(44); // a thumb-sized target
  expect(await page.getByLabel("Message").evaluate((box) => getComputedStyle(box).fontSize)).toBe("16px"); // iOS does not zoom
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("copilot-lab-375.png") });
});
