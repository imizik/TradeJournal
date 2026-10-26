import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Watch your day (docs/copilot-lab.md § Watch your day). The day's listing and the clip are stubbed in the browser; the
// clip is a real 20-frame animated PNG from the backend's renderer (e2e/fixtures/replay-nbis.png, a Friday's NBIS
// session from 9:30 to 16:00), cut into frames on the page and drawn to a canvas the scrub bar moves through.
const CLIP = readFileSync(path.join(__dirname, "fixtures", "replay-nbis.png"));
const START = 1792762200; // 2026-10-23 09:30 New York
const TIMES = Array.from({ length: 20 }, (_, i) => START + (i + 1) * 1170);
const DAY = {
  date: "2026-10-23", fills: 3, pings: 2,
  clips: [{ symbol: "NBIS", frames: 20, fps: 10, width: 720, height: 360, bytes: CLIP.length, times: TIMES, path: "/replay/2026-10-23/NBIS" }],
};
const UNAVAILABLE = { state: "unavailable" };
const TODAY = {
  as_of: "2026-10-23T20:30:00Z", day: "2026-10-23", quotes_at: null, quote_issue: null, act_now: UNAVAILABLE, plans: UNAVAILABLE,
  new: { radar: UNAVAILABLE, thesis: UNAVAILABLE, prep: UNAVAILABLE }, held: UNAVAILABLE, week: UNAVAILABLE,
};

async function stub(page: Page) {
  await page.route("**/api/backend/replay", (route) => route.fulfill({ json: { days: [{ date: "2026-10-23", symbols: ["NBIS"] }] } }));
  await page.route("**/api/backend/replay/2026-10-23", (route) => route.fulfill({ json: DAY }));
  await page.route("**/api/backend/replay/2026-10-23/NBIS", (route) => route.fulfill({ body: CLIP, contentType: "image/png" }));
}

const pixels = (page: Page) => page.locator("canvas").evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
const fits = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

test("a clip opens on the day's last frame and the thumb scrubs it at 375 px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await stub(page);
  await page.goto("/replay/2026-10-23");
  await expect(page.getByRole("heading", { name: "Watch your day" })).toBeVisible();
  await expect(page.getByText("Fri, Oct 23 · 3 fills, 2 pings")).toBeVisible();
  const clip = page.getByRole("region", { name: "NBIS replay" });
  const scrub = clip.getByRole("slider", { name: "Scrub NBIS" });
  await expect(scrub).toBeEnabled();
  await expect(clip.getByTestId("replay-clock")).toHaveText("4:00 PM ET");
  await expect.poll(() => page.locator("canvas").evaluate((c: HTMLCanvasElement) =>
    c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 !== 3 && v > 200))).toBe(true);
  const end = await pixels(page);
  await page.screenshot({ path: test.info().outputPath("replay-end-375.png") });

  await scrub.fill("0");
  await expect(clip.getByTestId("replay-clock")).toHaveText("9:49 AM ET");
  await expect.poll(() => pixels(page)).not.toBe(end);
  const start = await pixels(page);
  await scrub.fill("10");
  await expect(clip.getByTestId("replay-clock")).toHaveText("1:04 PM ET");
  await expect.poll(() => pixels(page)).not.toBe(start);
  await page.screenshot({ path: test.info().outputPath("replay-mid-375.png") });

  // Play runs from here to the end of the day and stops.
  await clip.getByRole("button", { name: "Play NBIS" }).click();
  await expect(clip.getByTestId("replay-clock")).toHaveText("4:00 PM ET");
  await expect(clip.getByRole("button", { name: "Play NBIS" })).toBeVisible();
  await expect.poll(() => pixels(page)).toBe(end);
  const box = await page.locator("canvas").boundingBox();
  expect(box!.width).toBeLessThanOrEqual(375);
  await fits(page);
});

test("a day without a replay says why", async ({ page }) => {
  await page.route("**/api/backend/replay/2026-10-22", (route) => route.fulfill({ status: 404, json: { detail: "No replay for that day." } }));
  await page.goto("/replay/2026-10-22");
  await expect(page.getByRole("status")).toContainText("clips are built at the close on days you trade and kept 14 days");
});

test("Today offers Watch today once the day's replay exists", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await stub(page);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: { enabled: false } }));
  await page.route("**/api/backend/today", (route) => route.fulfill({ json: TODAY }));
  await page.goto("/today");
  const watch = page.getByRole("link", { name: "Watch today" });
  await expect(watch).toHaveAttribute("href", "/replay/2026-10-23");
  await fits(page);
  await watch.click();
  await expect(page).toHaveURL(/\/replay\/2026-10-23$/);
  await expect(page.getByRole("region", { name: "NBIS replay" })).toBeVisible();
});
