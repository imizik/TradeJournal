import { expect, test, type Page } from "@playwright/test";

const fixtureApi = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;

// Actual owner routes, persistence, review context and review saving. Only the
// external market/model boundary is a clearly labeled, disposable-server fixture.
for (const viewport of [{ name: "desktop", width: 1440, height: 900, day: "2026-08-17", hasTrades: false },
  { name: "phone", width: 390, height: 844, day: "2026-08-18", hasTrades: false },
  { name: "traded-desktop", width: 1440, height: 900, day: "", hasTrades: true }]) {
  test(`morning thoughts reach ${viewport.hasTrades ? "a traded-day" : "a no-trade"} review, survive retry/reopen, and preserve revisions (${viewport.name})`, async ({ page, request, browser }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(viewport);
    // The seed dates trades relative to the host's today, so the traded day is the seeded
    // TSLA call's expiry (when it closes as expired), never a fixed calendar date.
    const day = viewport.day || (await (await request.get("/api/backend/trades?ticker=TSLA")).json())[0].expiration;
    const mode = await request.post(`${fixtureApi}/__test/day-journal-review?mode=ready`);
    expect(mode.ok(), await mode.text()).toBeTruthy();
    const label = `DayFlow-${viewport.name}-${Date.now()}`;
    const original = `${label}: I expect SPY to hold 580 and test 585. Below 578 invalidates my view.`;
    const revision = `${label}: SPY lost 578. I changed my view and am standing aside.`;
    const idea = `${label}: Consider QQQ after a reclaim; I did not take this idea.`;
    const reflection = `${label}: I followed the invalidation and stayed out.`;
    try {
      await page.goto(`/morning?day=${day}`);
      const journal = page.getByTestId("day-journal");
      await expect(journal.getByText(/Loading saved thoughts/)).toHaveCount(0);
      await journal.getByTestId("day-journal-add-outlook").click();
      await journal.getByLabel("Your words").fill(original);
      await journal.getByLabel("Symbol (optional)").fill("SPY??");
      await journal.getByTestId("day-journal-save").click();
      await expect(journal.getByRole("alert")).toContainText("still editable");
      await expect(journal.getByLabel("Your words")).toBeEnabled();
      await journal.getByLabel("Symbol (optional)").fill("SPY");

      // Lose the response after a real server commit: reload and retry must
      // recover the immutable request without creating a second entry.
      const path = `**/api/backend/day-journal/${day}/entries`;
      let committed = false;
      await page.route(path, async (route) => {
        const response = await route.fetch();
        expect(response.ok(), `${response.status()}: ${await response.text()}`).toBeTruthy();
        committed = true;
        await route.abort("failed");
      });
      await journal.getByTestId("day-journal-save").click();
      await expect(journal.getByRole("alert")).toContainText(/draft|save/i);
      expect(committed).toBeTruthy();
      await page.unroute(path);
      await page.reload();
      // The reloaded timeline already holds the committed save, so its pending draft is retired.
      await expect(journal.getByRole("status")).toContainText("Your earlier save went through");
      await expect(journal.getByLabel("Your words")).toHaveCount(0);
      await expect(journal.getByTestId("day-journal-entry").filter({ hasText: original })).toHaveCount(1);
      const payload = await (await request.get(`/api/backend/day-journal/${day}`)).json();
      expect(payload.entries.filter((entry: { text: string }) => entry.text === original)).toHaveLength(1);
      const entryId = payload.entries.find((entry: { text: string }) => entry.text === original).id;

      await addThought(page, "update", revision);
      await addThought(page, "idea", idea, true);
      await expect(journal.getByTestId("day-journal-entry").filter({ hasText: idea })).toContainText("Not traded");
      await expect(journal.getByText(/recorded on/).first()).toBeVisible(); // Historical day, actual save time.
      await page.screenshot({ path: test.info().outputPath(`day-thoughts-${viewport.name}.png`), fullPage: true });

      // The no-trade day must now be findable through the real calendar.
      await page.goto("/daily");
      await page.locator(`a[href="/daily/${day}"]`).click();
      await expect(page.getByTestId("day-journal").getByText(original, { exact: true })).toBeVisible();
      await expect(page.getByTestId("day-journal").getByText(revision, { exact: true })).toBeVisible();
      const run = page.getByRole("button", { name: /Run Daily Analysis|Regenerate Analysis/ });
      await expect(run).toBeEnabled();
      await run.click();
      const comparison = page.getByRole("region", { name: "Morning expectations against the day" });
      await expect(comparison).toContainText(original);
      await expect(comparison).toContainText("Synthetic SPY fixture closed at 577");
      await expect(comparison.locator("li").filter({ hasText: original }).getByRole("link", { name: "Open original thought" })).toHaveAttribute("href", `#thought-${entryId}`);
      await expect(page.getByText(/Synthetic browser fixture \(no model call\)/)).toBeVisible();
      await expect(page.locator("#ai-review").getByText(/^Saved .+ E[DS]T$/)).toBeVisible(); // Zoned save time, shown in ET.
      if (viewport.hasTrades) {
        const actions = page.getByLabel("Plan versus execution");
        await expect(actions).toContainText("Recorded TSLA");
        await expect(actions).toContainText("no contemporaneous linked trade plan");
      }
      await page.screenshot({ path: test.info().outputPath(`day-comparison-${viewport.name}.png`), fullPage: true });

      // A new thought must invalidate the review that was just generated,
      // without losing the new original/reflection or requiring a trade.
      await addThought(page, "reflection", reflection);
      await expect(page.getByText("Saved analysis may not include the latest thoughts, plans, fills, or market context. Regenerate it to review the current saved inputs.", { exact: true })).toBeVisible();
      const stored = await (await request.get(`/api/backend/daily-review/${day}`)).json();
      expect(stored.review.source_data_stale).toBe(true);
      if (viewport.hasTrades) expect(stored.trade_count).toBeGreaterThan(0);
      else expect(stored.trade_count).toBe(0);

      const reopened = await browser.newContext({ viewport });
      try {
        const fresh = await reopened.newPage();
        await fresh.goto(`/daily/${day}`);
        const timeline = fresh.getByTestId("day-journal");
        for (const text of [original, revision, idea, reflection]) await expect(timeline.getByText(text, { exact: true })).toBeVisible();
        await expect(fresh.getByRole("region", { name: "Morning expectations against the day" })).toContainText(original);
        expect(await fresh.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
        await fresh.screenshot({ path: test.info().outputPath(`day-reopened-${viewport.name}.png`), fullPage: true });
      } finally { await reopened.close(); }

      // Missing observations must remain an unresolved comparison.
      await request.post(`${fixtureApi}/__test/day-journal-review?mode=missing`);
      await run.click();
      await expect(comparison).toContainText("Market observations unavailable");
      await expect(comparison).toContainText(/Unresolved|Not enough evidence/i);
    } finally {
      await request.post(`${fixtureApi}/__test/day-journal-review?mode=off`);
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

test("Daily Review refresh receives another tab's thoughts and invalidates its saved review", async ({ page, request }) => {
  let day = "";
  for (let candidate = 1; candidate <= 31; candidate++) {
    const value = `2001-01-${String(candidate).padStart(2, "0")}`;
    const existing = await (await request.get(`/api/backend/day-journal/${value}`)).json();
    if (existing.entries.length === 0) { day = value; break; }
  }
  expect(day).not.toBe("");
  expect((await request.post(`${fixtureApi}/__test/day-journal-review?mode=ready`)).ok()).toBeTruthy();
  const second = await page.context().newPage();
  try {
    await page.goto(`/daily/${day}`);
    const run = page.getByRole("button", { name: /Run Daily Analysis|Regenerate Analysis/ });
    await expect(run).toBeDisabled();
    await second.goto(`/morning?day=${day}`);
    const words = `Remote morning plan ${Date.now()}: wait for SPY above 580.`;
    await second.getByTestId("day-journal-add-outlook").click();
    await second.getByLabel("Your words").fill(words);
    await second.getByTestId("day-journal-save").click();
    await expect(second.getByTestId("day-journal-entry").filter({ hasText: words })).toBeVisible();
    await page.getByRole("button", { name: "Refresh saved day journal" }).click();
    await expect(page.getByTestId("day-journal-entry").filter({ hasText: words })).toBeVisible();
    await expect(run).toBeEnabled();
    await run.click();
    await expect(page.getByRole("region", { name: "Morning expectations against the day" })).toContainText(words);
    const update = `Remote revision ${Date.now()}: the reclaim failed.`;
    await addThought(second, "update", update);
    await page.getByRole("button", { name: "Refresh saved day journal" }).click();
    await expect(page.getByTestId("day-journal-entry").filter({ hasText: update })).toBeVisible();
    await expect(page.getByText("Saved analysis may not include the latest thoughts, plans, fills, or market context. Regenerate it to review the current saved inputs.", { exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("day-refresh-cross-tab.png"), fullPage: true });
  } finally {
    await second.close();
    await request.post(`${fixtureApi}/__test/day-journal-review?mode=off`);
  }
});

test("Daily Review explains a review that is not set up instead of asking for a retry", async ({ page }) => {
  await page.route("**/api/backend/daily-review", (route) => route.request().method() === "POST"
    ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Daily review is not set up on the Claude plan: no plan token" }) })
    : route.continue());
  await page.goto("/daily/2026-10-01");
  await page.getByRole("button", { name: /Run Daily Analysis|Regenerate Analysis/ }).click();
  await expect(page.locator("#ai-review")).toContainText("Daily review is not set up on the Claude plan: no plan token");
  await expect(page.locator("#ai-review")).not.toContainText("Please retry");
});
