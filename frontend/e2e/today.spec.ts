import { expect, test } from "@playwright/test";

// Today is retired (the desk shows all of it): its address opens the desk while the lab is on, else the Dashboard, and
// the menu leads with Desk. The lab status is stubbed in the browser; the e2e backend runs with the lab off, so the
// server's redirect takes the Dashboard branch here. GET /today itself stays: the desk's decision bar reads it.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};

test("with the lab off an old Today bookmark opens the Dashboard, and the menu has no Today", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/today");
  await expect(page).toHaveURL((url) => url.pathname === "/");
  await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  await expect(page.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
});

test("while the lab is on the desk is home: Desk leads the tabs and the menu, and Today is gone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.goto("/copilot-lab");
  const tabs = page.getByRole("navigation", { name: "Main tabs" });
  // On the desk itself the bar is the desk's own (docs/copilot-lab.md § Phone), with More last.
  await expect(tabs.getByTestId("desk-view-book")).toHaveText("Positions");
  await expect(tabs.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
  await tabs.getByRole("button", { name: "Open menu" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu.getByRole("link", { name: "Desk", exact: true })).toHaveAttribute("href", "/copilot-lab");
  await expect(menu.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Copilot", exact: true })).toHaveCount(0); // one entry for one page
  // The Dashboard leaves the menu: More → Journal lists the desk's Journal summary instead.
  await menu.getByRole("button", { name: "Journal", exact: true }).click();
  await expect(menu.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Journal summary", exact: true })).toHaveAttribute("href", "/copilot-lab?desk=journal");
  await page.goto("/dashboard?account=all"); // a parameter keeps the page (bare /dashboard opens the desk once the server gate is on)
  await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  // Every other page: the app's bar, Desk first, the Dashboard not on it.
  await expect(tabs.getByRole("link")).toHaveText(["Desk", "Charts", /Plan/, "Trades"]);
  await expect(tabs.getByRole("link", { name: "Desk" })).toHaveAttribute("href", "/copilot-lab");
});

test("while the lab is on the sidebar leads with Desk, then Charts; Journal summary heads Journal and the Dashboard is gone from the menu", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.goto("/dashboard?account=all");
  const sidebar = page.getByRole("navigation").filter({ has: page.getByRole("button", { name: "Journal", exact: true }) });
  await expect(sidebar.getByRole("link", { name: "Desk", exact: true })).toBeVisible();
  const primary = sidebar.getByRole("list").first().getByRole("link");
  await expect(primary).toHaveText(["Desk", "Charts"]);
  await expect(sidebar.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
  await sidebar.getByRole("button", { name: "Journal", exact: true }).click();
  await expect(sidebar.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Journal summary", exact: true })).toHaveAttribute("href", "/copilot-lab?desk=journal");
  await expect(page.getByTestId("owner-dashboard")).toBeVisible();
  // Its filters stay on /dashboard rather than going home to the desk.
  await page.getByRole("group", { name: "Type" }).getByRole("link", { name: "Options" }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/dashboard" && url.searchParams.get("type") === "option");
});

// The frontend proxy forwards only known first path segments; "today" was missing when the screen first shipped, so
// production showed "Request failed (404)" while the backend answered. This one goes through the real proxy, unstubbed.
test("the frontend proxy forwards GET /today to the backend", async ({ page }) => {
  const response = await page.request.get("/api/backend/today");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(Object.keys(await response.json()).length).toBeGreaterThan(0);
});
