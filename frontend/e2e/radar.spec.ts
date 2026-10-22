import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const EVENT = "rad_sample_mu_20261020_1";

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
});

for (const [size, width, height] of [["desktop", 1440, 900], ["phone", 375, 812]] as const) {
  test(`radar feed, detail, rating and chart link on ${size}`, async ({ page, request }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto("/radar");
    await expect(page.getByTestId("radar-coverage")).toContainText("Recorded · 169 symbols");
    await expect(page.getByTestId("radar-coverage")).toContainText("1 missing");
    // Never visited before, so the sample event is new.
    const newSection = page.getByRole("region", { name: "New since your last visit" });
    const card = newSection.getByTestId("radar-event");
    await expect(card).toContainText("MU up 4.1% while SMH is up 0.6%");
    await expect(card).toContainText("Now: Extended");
    await card.getByRole("button").first().click();
    const original = page.getByRole("region", { name: "Original evidence" });
    await expect(original).toContainText("As first saved");
    await expect(original.getByRole("row")).toHaveCount(3);
    await expect(page.getByRole("region", { name: "Revisions" })).toContainText("Lead widened from 3.5 to 4.8 points");
    await page.getByRole("button", { name: "Too late", exact: true }).click();
    await expect(page.getByRole("button", { name: "Too late", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("link", { name: /Open chart · MU/ })).toHaveAttribute("href", "/charts?symbol=MU");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: test.info().outputPath(`radar-${size}.png`), fullPage: true });

    // The visit was recorded when the page opened, so a reload moves the event to Earlier and keeps the rating.
    await page.reload();
    await expect(page.getByRole("region", { name: "New since your last visit" })).toHaveCount(0);
    const earlier = page.getByRole("region", { name: "Earlier in this session" }).getByTestId("radar-event");
    await expect(earlier).toContainText("Rated: Too late");
    const saved = await (await request.get(`${API}/radar/events/${EVENT}`)).json();
    expect(saved.rating).toBe("too_late");
    expect(errors).toEqual([]);
  });
}
