import { expect, test, type Page } from "@playwright/test";

// Actual owner routes, persistence, review context and review saving. Only the
// external market/model boundary is a clearly labeled, disposable-server fixture.
for (const viewport of [{ name: "desktop", width: 1440, height: 900, day: "2026-08-17" },
  { name: "phone", width: 390, height: 844, day: "2026-08-18" }]) {
  test(`morning thoughts reach a no-trade review, survive retry/reopen, and preserve revisions (${viewport.name})`, async ({ page, request, browser }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(viewport);
    const mode = await request.post("/api/backend/__test/day-journal-review?mode=ready");
    expect(mode.ok()).toBeTruthy();
    const label = `DayFlow-${viewport.name}-${Date.now()}`;
    const original = `${label}: I expect SPY to hold 580 and test 585. Below 578 invalidates my view.`;
    const revision = `${label}: SPY lost 578. I changed my view and am standing aside.`;
    const idea = `${label}: Consider QQQ after a reclaim; I did not take this idea.`;
    const reflection = `${label}: I followed the invalidation and stayed out.`;
    try {
      await page.goto(`/morning?day=${viewport.day}`);
      const journal = page.getByTestId("day-journal");
      await expect(journal.getByText(/Loading saved thoughts/)).toHaveCount(0);
      await journal.getByTestId("day-journal-add-outlook").click();
      await journal.getByLabel("Your words").fill(original);
      await journal.getByLabel("Symbol (optional)").fill("SPY");

      // Lose the response after a real server commit: reload and retry must
      // recover the immutable request without creating a second entry.
      const path = `**/api/backend/day-journal/${viewport.day}/entries`;
      let committed = false;
      await page.route(path, async (route) => {
        const response = await route.fetch();
        expect(response.ok()).toBeTruthy();
        committed = true;
        await route.abort("failed");
      });
      await journal.getByTestId("day-journal-save").click();
      await expect(journal.getByRole("alert")).toContainText(/draft|save/i);
      expect(committed).toBeTruthy();
      await page.unroute(path);
      await page.reload();
      await expect(journal.getByLabel("Your words")).toHaveValue(original);
      await expect(journal.getByLabel("Your words")).toBeDisabled();
      await journal.getByTestId("day-journal-save").click();
      await expect(journal.getByRole("status")).toContainText("Saved");
      await expect(journal.getByTestId("day-journal-entry").filter({ hasText: original })).toHaveCount(1);
      const payload = await (await request.get(`/api/backend/day-journal/${viewport.day}`)).json();
      expect(payload.entries.filter((entry: { text: string }) => entry.text === original)).toHaveLength(1);
      const entryId = payload.entries.find((entry: { text: string }) => entry.text === original).id;

      await addThought(page, "update", revision);
      await addThought(page, "idea", idea, true);
      await expect(journal.getByTestId("day-journal-entry").filter({ hasText: idea })).toContainText("Not traded");
      await expect(journal.getByText(/recorded on/).first()).toBeVisible(); // Historical day, actual save time.
      await page.screenshot({ path: test.info().outputPath(`day-thoughts-${viewport.name}.png`), fullPage: true });

      // The no-trade day must now be findable through the real calendar.
      await page.goto("/daily");
      await page.locator(`a[href="/daily/${viewport.day}"]`).click();
      await expect(page.getByTestId("day-journal").getByText(original, { exact: true })).toBeVisible();
      await expect(page.getByTestId("day-journal").getByText(revision, { exact: true })).toBeVisible();
      const run = page.getByRole("button", { name: /Run Daily Analysis|Regenerate Analysis/ });
      await expect(run).toBeEnabled();
      await run.click();
      const comparison = page.getByRole("region", { name: "Morning expectations against the day" });
      await expect(comparison).toContainText(original);
      await expect(comparison).toContainText("Synthetic SPY fixture closed at 577");
      await expect(comparison.getByRole("link", { name: "Open original thought" }).first()).toHaveAttribute("href", `#thought-${entryId}`);
      await expect(page.getByText(/Synthetic browser fixture \(no model call\)/)).toBeVisible();
      await page.screenshot({ path: test.info().outputPath(`day-comparison-${viewport.name}.png`), fullPage: true });

      // A new thought must invalidate the review that was just generated,
      // without losing the new original/reflection or requiring a trade.
      await addThought(page, "reflection", reflection);
      await expect(page.getByText(/Saved analysis predates|Saved analysis used|thoughts.*changed/i).first()).toBeVisible();
      const stored = await (await request.get(`/api/backend/daily-review/${viewport.day}`)).json();
      expect(stored.review.source_data_stale).toBe(true);

      const reopened = await browser.newContext({ viewport });
      try {
        const fresh = await reopened.newPage();
        await fresh.goto(`/daily/${viewport.day}`);
        const timeline = fresh.getByTestId("day-journal");
        for (const text of [original, revision, idea, reflection]) await expect(timeline.getByText(text, { exact: true })).toBeVisible();
        await expect(fresh.getByRole("region", { name: "Morning expectations against the day" })).toContainText(original);
        expect(await fresh.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
        await fresh.screenshot({ path: test.info().outputPath(`day-reopened-${viewport.name}.png`), fullPage: true });
      } finally { await reopened.close(); }

      // Missing observations must remain an unresolved comparison.
      await request.post("/api/backend/__test/day-journal-review?mode=missing");
      await run.click();
      await expect(comparison).toContainText("Market observations unavailable");
      await expect(comparison).toContainText(/Unresolved|Not enough evidence/i);
    } finally {
      await request.post("/api/backend/__test/day-journal-review?mode=off");
    }
  });
}

async function addThought(page: Page, kind: "update" | "idea" | "reflection", text: string, notTraded = false) {
  const journal = page.getByTestId("day-journal");
  await journal.getByTestId(`day-journal-add-${kind}`).click();
  await journal.getByLabel("Your words").fill(text);
  if (notTraded) await journal.getByLabel("Mark as not traded").check();
  await journal.getByTestId("day-journal-save").click();
  await expect(journal.getByText(text, { exact: true })).toBeVisible();
}
