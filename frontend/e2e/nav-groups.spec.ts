import { expect, test } from "@playwright/test";

// The sidebar: three primary links, four folded groups, remembered per device. The assistant's view is in browser-access.auth.ts.
const GROUPS = ["Journal", "Market", "Practice", "Research"];

test("the sidebar shows three links and four collapsed groups; the current page's group opens by itself; choices are remembered", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const sidebar = page.getByRole("navigation").filter({ has: page.getByRole("button", { name: "Journal", exact: true }) });
  for (const name of ["Today", "Dashboard", "Charts"]) await expect(sidebar.getByRole("link", { name, exact: true })).toBeVisible();
  for (const name of GROUPS) await expect(sidebar.getByRole("button", { name, exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect(sidebar.getByRole("link", { name: "Trades", exact: true })).toHaveCount(0);
  // Assistant access and Deploys sit beside Sync, not in the list.
  await expect(sidebar.getByRole("link", { name: "Deploys", exact: true })).toBeVisible();
  await expect(sidebar.getByTitle("Sync & enrichment status")).toBeVisible();

  // A click opens a group and the device remembers it.
  await sidebar.getByRole("button", { name: "Market", exact: true }).click();
  await expect(sidebar.getByRole("button", { name: "Market", exact: true })).toHaveAttribute("aria-expanded", "true");
  await expect(sidebar.getByRole("link", { name: "Radar", exact: true })).toBeVisible();
  await page.reload();
  await expect(sidebar.getByRole("link", { name: "Radar", exact: true })).toBeVisible();
  await sidebar.getByRole("button", { name: "Market", exact: true }).click();
  await expect(sidebar.getByRole("link", { name: "Radar", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(sidebar.getByRole("button", { name: "Journal", exact: true })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Radar", exact: true })).toHaveCount(0);

  // The current page's group opens by itself, closes on a click, and is not remembered once you leave.
  await page.goto("/fills");
  await expect(sidebar.getByRole("button", { name: "Journal", exact: true })).toHaveAttribute("aria-expanded", "true");
  await expect(sidebar.getByRole("link", { name: "Fills", exact: true })).toHaveAttribute("aria-current", "page");
  await sidebar.getByRole("button", { name: "Journal", exact: true }).click();
  await expect(sidebar.getByRole("link", { name: "Fills", exact: true })).toHaveCount(0);
  await sidebar.getByRole("button", { name: "Journal", exact: true }).click();
  await sidebar.getByRole("button", { name: "Journal", exact: true }).click(); // leave it closed
  await sidebar.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(sidebar.getByRole("button", { name: "Journal", exact: true })).toHaveAttribute("aria-expanded", "false");
  await page.goBack(); // back on the page, its group opens by itself again
  await expect(page).toHaveURL(/\/fills$/);
  await expect(sidebar.getByRole("button", { name: "Journal", exact: true })).toHaveAttribute("aria-expanded", "true");
  await sidebar.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await sidebar.getByRole("button", { name: "Research", exact: true }).click();
  await sidebar.getByRole("link", { name: "Research Studio", exact: true }).click();
  await expect(page).toHaveURL(/\/research-studio/);
  await expect(page.getByRole("button", { name: "Journal", exact: true })).toHaveAttribute("aria-expanded", "false");
  await page.screenshot({ path: test.info().outputPath("nav-groups-desktop.png") });
});

test("the phone's More menu has the same three links and groups; the tab bar is unchanged", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.getByRole("button", { name: /^Open menu/ }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  for (const name of ["Today", "Dashboard", "Charts"]) await expect(menu.getByRole("link", { name, exact: true })).toBeVisible();
  for (const name of GROUPS) await expect(menu.getByRole("button", { name, exact: true })).toHaveAttribute("aria-expanded", "false");
  await menu.getByRole("button", { name: "Practice", exact: true }).click();
  await menu.getByRole("link", { name: "Daily Practice", exact: true }).click();
  await expect(page).toHaveURL(/\/practice$/);
  await expect(menu).toHaveCount(0);
  await page.getByRole("button", { name: /^Open menu/ }).click();
  await expect(menu.getByRole("button", { name: "Practice", exact: true })).toHaveAttribute("aria-expanded", "true");
  await expect(menu.getByRole("link", { name: "Deploys", exact: true })).toBeVisible();
});
