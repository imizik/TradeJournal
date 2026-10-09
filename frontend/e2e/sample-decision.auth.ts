import { test, expect, type Browser, type Page } from "@playwright/test";
const ownerOrigin = `http://127.0.0.1:${process.env.SAMPLE_OWNER_PORT ?? 3141}`;
const assistantOrigin = `http://127.0.0.1:${process.env.SAMPLE_ASSISTANT_PORT ?? 3142}`;

async function login(page: Page, browser: Browser, write: boolean) {
  const owner = await browser.newContext({ baseURL: ownerOrigin });
  const session = await (await owner.request.get("/api/access/me")).json();
  const run = (await (await owner.request.get("/api/backend/practice/runs")).json()).runs.find((item: { policy_version: string }) => item.policy_version === "practice-sample-long-15m-v1");
  expect(run).toBeTruthy();
  const identity = `sample-${Date.now()}-${write ? "writer" : "reader"}`;
  const created = await owner.request.post("/api/access/assistants", { headers: { Origin: ownerOrigin, "x-tj-csrf": session.csrf }, data: { identifier: identity, grants: { symbols: write ? ["MU", "NBIS"] : ["MU", "NBIS", "RNXT", "AAPL", "RCAT"], run_ids: [run.id], journal_read: !write, decision_write: write } } });
  expect(created.status()).toBe(201);
  const key = (await created.json()).key;
  await page.goto("/login");
  await page.getByLabel("Assistant ID").fill(identity);
  await page.getByLabel("Access key").fill(key);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: write ? "Today" : "Dashboard", exact: true })).toBeVisible();
  await owner.close();
  return run;
}

test("writer inspects frozen MU/NBIS facts, saves TAKE/WAIT, reloads and reopens exact records", async ({ page, browser }) => {
  const errors: string[] = [];
  const forbiddenReads: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (/\/api\/backend\/(fills|trades|accounts|stats|daily-review)(?:[/?]|$)/.test(request.url())) forbiddenReads.push(request.url()); });
  const run = await login(page, browser, true);
  await expect(page.getByText("Simulated decision trial", { exact: true })).toBeVisible();
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await expect(mu.getByText(/300 timestamped price facts/)).toBeVisible();
  await mu.getByLabel("MU choice").selectOption("take");
  await mu.getByLabel("MU reason").fill("Exercise TAKE uses the frozen MU trigger, stop, guard and target.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByText("SIMULATED · UNARMED", { exact: true })).toBeVisible();
  const nbis = page.getByRole("article", { name: "NBIS sample opportunity" });
  await nbis.getByLabel("NBIS choice").selectOption("wait");
  await nbis.getByLabel("NBIS reason").fill("Wait for the sample range to resolve.");
  await nbis.getByLabel("NBIS wait condition").fill("Reassess after the simulated close above the range.");
  await nbis.getByRole("button", { name: "Save NBIS decision", exact: true }).click();
  await expect(nbis.getByRole("button", { name: "Reopen saved NBIS decision" })).toBeVisible();
  const before = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(before).toHaveLength(2);
  expect(new Set(before.map((record: { actor: string }) => record.actor)).size).toBe(1);
  await page.goto(`/daily/${run.day}`);
  await expect(page.getByRole("heading", { name: "Simulated decision practice" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Reopen saved MU decision" }).click();
  await expect(page.getByRole("article", { name: "MU sample opportunity" }).getByRole("status")).toContainText("original record reopened");
  const after = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
  expect(after.map((record: { id: string; record_sha256: string }) => [record.id, record.record_sha256])).toEqual(before.map((record: { id: string; record_sha256: string }) => [record.id, record.record_sha256]));
  const auth = await (await page.request.get("/api/access/me")).json();
  expect((await page.request.get("/api/backend/fills")).status()).toBe(403);
  expect((await page.request.post(`/api/backend/decisions/${before[0].id}/arm`, { headers: { Origin: assistantOrigin, "x-tj-csrf": auth.csrf }, data: { operation_id: "forbidden" } })).status()).toBe(403);
  expect(forbiddenReads).toEqual([]);
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: test.info().outputPath("sample-saved-decisions-phone.png"), animations: "disabled" });
});

test("simulated charts support indicators and symbol URLs without requesting a live stream", async ({ page, browser }) => {
  const errors: string[] = [];
  const streams: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/charts/stream")) streams.push(request.url()); });
  await login(page, browser, true);
  await page.goto("/charts?symbol=NBIS");
  await expect(page.getByRole("button", { name: "Chart NBIS", exact: true })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("region", { name: "NBIS 5m chart", exact: true })).toBeVisible();
  await expect(page.getByText("Simulated chart snapshot", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Chart MU", exact: true }).click();
  await expect(page).toHaveURL(/symbol=MU/);
  await expect(page.getByRole("region", { name: "MU 5m chart", exact: true })).toBeVisible();
  // Studies need explicit numeric/null fields from the real fixture backend.
  await page.getByRole("button", { name: "Indicators", exact: true }).click();
  await page.getByRole("button", { name: "RSI 14", exact: true }).click();
  await page.getByRole("button", { name: "EMA 9", exact: true }).click();
  await page.getByRole("button", { name: "Indicators", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("region", { name: "MU 5m chart", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(streams).toEqual([]);
});

test("read-only calendar includes the practice-only date and opens its saved evidence", async ({ page, browser }) => {
  const run = await login(page, browser, false);
  await page.goto("/daily");
  const linked = page.getByRole("link", { name: `Review practice ${run.day}`, exact: true });
  await expect(linked).toBeVisible();
  await linked.click();
  await expect(page).toHaveURL(new RegExp(`/daily/${run.day}\\?practice_run=${run.id}`));
  await expect(page.getByText("Daily practice routine", { exact: true })).toBeVisible();
  await page.getByText("Frozen neutral context", { exact: true }).first().click();
  await expect(page.getByText(/sample_fixture/).first()).toBeVisible();
});

test("a slow pre-save reload cannot hide the immutable SKIP receipt", async ({ page, browser }) => {
  await login(page, browser, true);
  const mu = page.getByRole("article", { name: "MU sample opportunity" });
  await expect(mu.getByLabel("MU reason")).toBeVisible();
  let release: (() => void) | undefined;
  let captured: (() => void) | undefined;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const seen = new Promise<void>(resolve => { captured = resolve; });
  await page.route("**/api/backend/practice/runs/*", async route => {
    const original = await route.fetch();
    captured?.();
    await pending;
    await route.fulfill({ response: original });
  });
  await page.getByRole("button", { name: "Reload saved practice" }).click();
  await seen;
  await mu.getByLabel("MU reason").fill("No setup in this simulated exercise.");
  await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
  await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
  release?.();
  await expect(page.getByRole("button", { name: "Reload saved practice" })).toBeEnabled();
  await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
  await expect(mu.getByLabel("MU reason")).toHaveCount(0);
});

for (const timezoneId of ["America/Los_Angeles", "America/New_York", "UTC"]) {
  test(`WAIT expiry previews and saves the same instant in ${timezoneId}`, async ({ browser }) => {
    const context = await browser.newContext({ baseURL: assistantOrigin, timezoneId });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    try {
      const run = await login(page, browser, true);
      const mu = page.getByRole("article", { name: "MU sample opportunity" });
      await mu.getByLabel("MU choice").selectOption("wait");
      const input = mu.getByLabel(`MU waiting ends (${timezoneId})`, { exact: true });
      const preview = mu.locator("time[datetime]");
      const deadlineMinute = new Date(Math.floor(new Date(run.deadline).getTime() / 60_000) * 60_000).toISOString();
      await expect(preview).toHaveAttribute("datetime", deadlineMinute);
      // Choose one future UTC instant, then enter its wall time in each browser.
      const instant = new Date(Math.floor((Date.now() + 10 * 60_000) / 60_000) * 60_000);
      const localInput = new Intl.DateTimeFormat("sv-SE", { timeZone: timezoneId,
        year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(instant).replace(" ", "T");
      await input.fill(localInput);
      await expect(preview).toHaveAttribute("datetime", instant.toISOString());
      const eastern = `${instant.toLocaleString("en-US", { timeZone: "America/New_York" })} ET`;
      await expect(preview).toHaveText(eastern);
      await expect(input).toHaveAccessibleDescription(`Will save as ${eastern}. Daily Review shows Eastern time.`);
      if (timezoneId === "America/Los_Angeles") {
        await page.setViewportSize({ width: 390, height: 844 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
        await mu.screenshot({ path: test.info().outputPath("wait-expiry-preview-phone.png") });
      }
      await input.fill("");
      await expect(mu.getByText("Choose an expiry to preview its Eastern time.", { exact: true })).toBeVisible();
      await expect(preview).toHaveCount(0);
      await input.fill(localInput);
      await mu.getByLabel("MU reason").fill("Verify local-time input and Eastern-time preview preserve the same instant.");
      await mu.getByLabel("MU wait condition").fill("Reassess the invented trigger before this expiry.");
      await mu.getByRole("button", { name: "Save MU decision", exact: true }).click();
      await expect(mu.getByRole("button", { name: "Reopen saved MU decision" })).toBeVisible();
      await mu.getByText("MU · WAIT", { exact: true }).click();
      await expect(mu.getByText(eastern, { exact: true })).toBeVisible();
      const records = (await (await page.request.get("/api/backend/decisions")).json()).decisions;
      expect(records).toHaveLength(1);
      expect(new Date(records[0].wait_expiry).toISOString()).toBe(instant.toISOString());
      await page.goto(`/daily/${run.day}?practice_run=${run.id}`);
      await page.reload();
      await page.getByRole("button", { name: "Reopen saved MU decision" }).click();
      await page.getByRole("article", { name: "MU sample opportunity" }).getByText("MU · WAIT", { exact: true }).click();
      await expect(page.getByRole("article", { name: "MU sample opportunity" }).getByText(eastern, { exact: true })).toBeVisible();
      const reopened = (await (await page.request.get(`/api/backend/decisions/${records[0].id}`)).json());
      expect(reopened.wait_expiry).toBe(records[0].wait_expiry);
      expect(reopened.record_sha256).toBe(records[0].record_sha256);
      expect(errors).toEqual([]);
    } finally { await context.close(); }
  });
}
