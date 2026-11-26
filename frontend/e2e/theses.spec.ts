import { expect, test } from "@playwright/test";

// /theses on a phone: one row per active thesis with price vs break level, earnings and review date; tap open for the
// full thesis and its pings, edit the break level and review date, archive. Quotes and earnings are fixture stubs.
test("thesis page: row, expand, edit break and review date, archive", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const tag = crypto.randomUUID().slice(0, 8);
  const saved = await page.request.post("/api/backend/jo/memories", { data: {
    operation_id: `thesis-${crypto.randomUUID()}`, kind: "thesis", symbol: "NBIS", original_text: `AI capex keeps compounding ${tag}.`,
    source: "owner_statement", status: "active", owner_confirmed: true, break_below: 72, review_on: "2027-02-15" } });
  expect(saved.ok()).toBeTruthy();
  const memory = await saved.json();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/theses");
  const row = page.getByTestId("thesis-row").filter({ hasText: tag });
  await expect(row).toContainText("NBIS");
  await expect(row).toContainText("$80.00");
  await expect(row).toContainText("10.0% above break 72.00");
  await expect(row).toContainText("Earnings Dec 10");
  await expect(row).toContainText("Review Feb 15");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath("theses-phone.png") });

  await row.getByRole("button", { expanded: false }).click();
  await expect(row.getByText("Recent thesis pings")).toBeVisible();
  await row.getByLabel("Break under").fill("76");
  await row.getByLabel("Review on").fill("2027-03-01");
  await row.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("NBIS thesis updated");
  const updated = page.getByTestId("thesis-row").filter({ hasText: tag });
  await expect(updated).toContainText("5.0% above break 76.00");
  await expect(updated).toContainText("Review Mar 1");
  const latest = (await (await page.request.get(`/api/backend/jo/memories/${memory.memory_id}?limit=1`)).json()).items[0];
  expect(latest).toMatchObject({ revision: 2, status: "active", body: { break_below: 76, review_on: "2027-03-01", original_text: `AI capex keeps compounding ${tag}.` } });
  await page.screenshot({ path: test.info().outputPath("theses-phone-open.png") });

  await updated.getByRole("button", { name: "Archive", exact: true }).click();
  await updated.getByRole("button", { name: "Confirm archive" }).click();
  await expect(page.getByRole("status")).toContainText("archived");
  await expect(page.getByTestId("thesis-row").filter({ hasText: tag })).toHaveCount(0);
  expect((await (await page.request.get(`/api/backend/jo/memories/${memory.memory_id}?limit=1`)).json()).items[0].status).toBe("retired");
  expect(errors).toEqual([]);
});
