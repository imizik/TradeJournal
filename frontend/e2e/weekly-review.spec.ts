import { test, expect } from "@playwright/test";
import { mondayOf } from "../lib/format";

for (const width of [1440, 390]) test(`standalone weekly recovery ${width}`, async ({ page, request }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await page.goto("/daily/week");
  await expect(page).toHaveURL(/\/daily\/week\/\d{4}-\d{2}-\d{2}$/);

  // Locate the invented trade from the fixture server, independently of the runner's clock.
  const trades = await (await request.get("/api/backend/trades")).json() as { ticker: string; expiration: string | null; status: string }[];
  const expired = trades.find(trade => trade.ticker === "TSLA" && trade.status === "expired");
  expect(expired?.expiration).toBeTruthy();
  await page.goto(`/daily/week/${mondayOf(expired!.expiration!)}`);
  const leaks = page.getByRole("region", { name: "Exit leaks this week" });
  await expect(leaks.locator("details").first()).toBeVisible();
  await leaks.locator("summary").first().click();
  await expect(leaks.getByRole("link").first()).toHaveAttribute("href", /^\/trades\//);

  // Separate weeks keep the two viewport journeys independent in the seeded database.
  const week = width === 1440 ? "2026-08-03" : "2026-08-24";
  // Reset only these invented weeks: the local browser database can survive reruns.
  for (const target of [week, mondayOf(week, -7)]) {
    const reset = await request.put(`/api/backend/weekly-review/${target}`, { data: { rule_key: null, note: null } });
    expect(reset.ok()).toBe(true);
  }
  await page.goto(`/daily/week/${week}`);
  await expect(page.getByRole("heading", { name: /^Week of/ })).toContainText(width === 1440 ? "Aug 3" : "Aug 24");
  await expect(page.getByText(/trades have a price path/)).toBeVisible();
  const pick = page.getByRole("region", { name: "Pick one rule for next week" });
  await pick.getByRole("radio").first().check();
  const note = pick.getByLabel("Note (optional)");
  await note.fill(`Invented weekly note ${width}`);

  let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  const endpoint = `**/api/backend/weekly-review/${week}`;
  await page.route(endpoint, async route => {
    await gate;
    await route.fulfill({ status: 503, json: { detail: "Synthetic save unavailable" } });
  });
  await pick.getByRole("button", { name: /^Save(?: change)?$/ }).click();
  await expect(pick.getByRole("button", { name: "Saving…" })).toBeDisabled();
  release();
  await expect(page.getByRole("alert").filter({ hasText: "Synthetic save unavailable" })).toBeVisible();
  await expect(note).toHaveValue(`Invented weekly note ${width}`);
  await expect(pick.getByRole("radio").first()).toBeChecked();
  await page.screenshot({ path: test.info().outputPath(`weekly-failed-${width}.png`), fullPage: true });

  // Retry reaches the real disposable backend, so reload proves persistence.
  await page.unroute(endpoint);
  await pick.getByRole("button", { name: /^Save(?: change)?$/ }).click();
  await expect(pick.getByText(/^Saved /)).toBeVisible();
  await page.reload();
  await expect(note).toHaveValue(`Invented weekly note ${width}`);
  await page.getByRole("link", { name: "← Previous week" }).click();
  await expect(page).not.toHaveURL(new RegExp(`${week}$`));
  await expect(note).toHaveValue("");
  await page.getByRole("link", { name: "Next week →" }).click();
  await expect(page).toHaveURL(new RegExp(`${week}$`));
  await expect(note).toHaveValue(`Invented weekly note ${width}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`weekly-return-${width}.png`), fullPage: true });
});
