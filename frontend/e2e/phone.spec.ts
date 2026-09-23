import { devices, expect, test } from "@playwright/test";

/**
 * Phone-layout smoke tests.
 *
 * The failure these exist to catch: the desktop sidebar eating the screen, or
 * a wide table pushing the page sideways, so the journal is unusable on the
 * phone it is meant to be read on. Desktop rendering is covered by
 * smoke.spec.ts; these only assert what changes at phone width.
 */

// Spread the device's screen, not its defaultBrowserType: CI installs only
// chromium, and webkit would fail to launch.
const iPhone = devices["iPhone 13"];
test.use({
  viewport: iPhone.viewport,
  userAgent: iPhone.userAgent,
  deviceScaleFactor: iPhone.deviceScaleFactor,
  isMobile: iPhone.isMobile,
  hasTouch: iPhone.hasTouch,
});

const PAGES = ["/", "/trades", "/fills", "/daily", "/analytics"];

for (const path of PAGES) {
  test(`${path} fits the screen with no sideways scrolling`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible();

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    // A card may scroll its own table sideways; the page itself must not.
    expect(overflow.scrollWidth, `${path} overflows horizontally`).toBeLessThanOrEqual(overflow.innerWidth + 1);
  });
}

test("the sidebar is replaced by a menu that navigates", async ({ page }) => {
  await page.goto("/");

  // The desktop sidebar must not be taking the width at this size.
  const sidebarWidth = await page.evaluate(() => {
    const sidebars = [...document.querySelectorAll("nav")].filter((nav) => nav.clientWidth > 0);
    return Math.max(0, ...sidebars.map((nav) => nav.clientWidth));
  });
  expect(sidebarWidth).toBe(0);

  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("link", { name: "Trades" }).click();

  await expect(page).toHaveURL(/\/trades$/);
  await expect(page.getByRole("button", { name: "Close menu" })).toHaveCount(0); // menu closed on navigate
  await expect(page.getByRole("heading", { name: "Trades" })).toBeVisible();
});

test("main content gets the width, and key numbers are readable", async ({ page }) => {
  await page.goto("/");

  const mainWidth = await page.evaluate(() => document.querySelector("main")?.clientWidth ?? 0);
  const viewport = page.viewportSize()?.width ?? 0;
  expect(mainWidth).toBeGreaterThan(viewport * 0.9);

  // The seeded all-time P&L must render in full, not clipped to "+$1,0...".
  // exact: the chart's own tooltip label also contains this number.
  await expect(page.getByText("+$1,019.00", { exact: true })).toBeVisible();
});

test("the home-screen manifest and icons are served", async ({ page, request }) => {
  await page.goto("/");
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ name: "Trade Journal", display: "standalone" });

  for (const icon of manifest.icons) {
    const response = await request.get(icon.src);
    expect(response.status(), `${icon.src} is missing`).toBe(200);
  }
  expect((await request.get("/apple-touch-icon.png")).status()).toBe(200);
});
