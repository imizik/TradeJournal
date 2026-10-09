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
    // The bottom tab bar is the phone's own navigation, not the sidebar.
    const sidebars = [...document.querySelectorAll("nav")].filter((nav) => nav.clientWidth > 0 && nav.getAttribute("aria-label") !== "Main tabs");
    return Math.max(0, ...sidebars.map((nav) => nav.clientWidth));
  });
  expect(sidebarWidth).toBe(0);

  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "Trades" }).click();

  await expect(page).toHaveURL(/\/trades$/);
  await expect(page.getByRole("button", { name: "Close menu" })).toHaveCount(0); // menu closed on navigate
  await expect(page.getByRole("heading", { name: "Trades" })).toBeVisible();
});

test("a tab bar at the bottom reaches the main pages in one tap and never covers the page's end", async ({ page }) => {
  await page.goto("/");
  const tabs = page.getByRole("navigation", { name: "Main tabs" });
  await expect(tabs).toBeInViewport();
  for (const name of ["Dashboard", "Charts", "Daily", "Trades", "More"]) {
    const target = name === "More" ? tabs.getByRole("button", { name: "Open menu" }) : tabs.getByRole("link", { name });
    expect(Math.min(...Object.values((await target.boundingBox())!).slice(2)), name).toBeGreaterThanOrEqual(44);
  }
  await expect(tabs.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
  await tabs.getByRole("link", { name: "Trades" }).click();
  await expect(page).toHaveURL(/\/trades$/);
  await expect(tabs.getByRole("link", { name: "Trades" })).toHaveAttribute("aria-current", "page");
  // Scrolled to the end, the last of the page sits above the bar, not under it.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const bar = (await tabs.boundingBox())!;
  const lastBottom = await page.evaluate(() => Math.max(...[...document.querySelectorAll("main *")].map((el) => el.getBoundingClientRect().bottom)));
  expect(lastBottom).toBeLessThanOrEqual(bar.y + 1);
  await page.screenshot({ path: test.info().outputPath("phone-tabs.png") });
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

test("a trade opens to a readable detail page", async ({ page }) => {
  await page.goto("/trades");
  await page.locator('tbody a[href^="/trades/"]').first().click();
  await expect(page).toHaveURL(/\/trades\/[0-9a-f-]+$/);

  // Wait for a heading before measuring them. toHaveURL resolves on the URL
  // change, and the client-side navigation can leave `main` empty for a frame,
  // where Math.max over no headings is -Infinity and the failure names a
  // width instead of the empty page that caused it.
  await expect(page.getByText("Trade Summary")).toBeVisible();

  // The audit panel is a fixed 320px column: beside it the trade itself was
  // squeezed to a few pixels.
  const widths = await page.evaluate(() => ({
    content: Math.max(
      ...[...document.querySelectorAll("main h2")].map((el) => el.getBoundingClientRect().width),
    ),
    viewport: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(widths.content).toBeGreaterThan(widths.viewport * 0.7);
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.viewport + 1);

  await expect(page.getByRole("button", { name: /Show Audit/ })).toBeVisible();
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
