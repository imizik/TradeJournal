import { expect, test, type Page } from "@playwright/test";
import type { PlanStreak } from "../components/PlanStreak";

// The plan streak chip in the nav: the owner's planned-before-entry run, one tap from Review my week.
// The streak read is stood in for, so each state is exact; nothing here saves or links a plan.
const REVIEW = "/copilot-lab?context=Review+my+week";
const now = Math.floor(Date.now() / 1000);
const STREAK: PlanStreak = {
  show: true, since: now - 86400 * 10, tracking: true, current: 4, best: 6, pending: 0,
  this_week: { planned: 5, total: 7, pending: 0, start: now - 86400 * 2 },
  last_break: { contract: "NBIS 11/20/26 100C", short: "NBIS 100C", entry_time: now - 3600, reason: "no_plan" },
};

async function answer(page: Page, body: PlanStreak) {
  await page.route("**/api/backend/charts/captures/streak", (route) => route.fulfill({ json: body }));
}

const streakRead = (page: Page) => page.waitForResponse((response) => response.url().includes("/charts/captures/streak"));

test("desktop sidebar shows the streak and links to Review my week", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await answer(page, STREAK);
  await page.goto("/");
  const chip = page.getByTestId("plan-streak-full");
  await expect(chip).toBeVisible();
  await expect(chip).toHaveText("4 planned");
  await expect(chip).toHaveAttribute("href", REVIEW);
  await expect(chip).toHaveAccessibleName(/Plan streak: 4 entries in a row planned before entry\. This week 5 of 7 planned, best 6\./);
  await page.screenshot({ path: test.info().outputPath("plan-streak-desktop.png"), animations: "disabled" });
  await chip.click();
  await expect(page).toHaveURL(/\/copilot-lab\?context=Review\+my\+week$/);
});

test("a broken streak names the last unplanned entry", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await answer(page, { ...STREAK, current: 0 });
  await page.goto("/");
  await expect(page.getByTestId("plan-streak-full")).toHaveText(/^0 planned · last: NBIS 100C \d{1,2}:\d{2}$/);
  // The charts rail carries the count alone.
  await page.goto("/charts?symbol=NBIS");
  await expect(page.getByTestId("plan-streak-rail")).toHaveText("0");
});

test("phone title bar: a compact chip, a 44px tap target, no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await answer(page, STREAK);
  await page.goto("/");
  const chip = page.getByTestId("plan-streak-compact");
  await expect(chip).toBeVisible();
  await expect(chip).toHaveText("4");
  await expect(chip).toHaveAccessibleName(/^Plan streak: 4 entries in a row/);
  await expect(chip).toHaveAttribute("href", REVIEW);
  const box = (await chip.boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.width).toBeGreaterThanOrEqual(44);
  // Title, sync line, chip and Sync all fit in the bar; the title is not cut short.
  // The seeded "Gmail disconnected" is the longest sync line; the title must still fit beside it.
  await expect(page.getByRole("banner").getByText("Gmail disconnected")).toBeVisible();
  const title = page.getByRole("banner").getByRole("heading", { name: "Trade Journal" });
  expect(await title.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  // The tap areas touch but never overlap: the sync line, the chip and Sync each keep their own.
  const sync = (await page.getByRole("banner").getByRole("button", { name: /Sync/ }).boundingBox())!;
  const line = (await page.getByRole("banner").getByText("Gmail disconnected").boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(sync.x + 0.5);
  expect(line.x + line.width).toBeLessThanOrEqual(box.x + 0.5);
  const overflow = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth + 1);
  await page.screenshot({ path: test.info().outputPath("plan-streak-phone.png"), animations: "disabled" });
  // The menu carries it too, for the charts page whose title bar gives its height to the chart.
  await page.getByRole("button", { name: /Open menu/ }).click();
  const menuChip = page.getByRole("dialog", { name: "Menu" }).getByTestId("plan-streak-menu");
  await expect(menuChip).toHaveText("4 planned");
  expect((await menuChip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
});

test("hidden until tracking is on or a plan exists", async ({ page }) => {
  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await answer(page, { ...STREAK, show: false, current: 0 });
    const read = streakRead(page);
    await page.goto("/");
    await read;
    await expect(page.getByRole("link", { name: /^Plan streak/ })).toHaveCount(0);
  }
});
