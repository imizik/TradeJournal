import { expect, test, type Page } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const create = async (request: import("@playwright/test").APIRequestContext) => {
  const response = await request.post(`${API}/practice/replay/attempts`, { data: { operation_id: crypto.randomUUID() } });
  expect(response.ok()).toBeTruthy();
  return response.json();
};
const choose = async (page: Page, action: string, reason?: string) => {
  await page.getByRole("button", { name: action, exact: true }).click();
  if (reason) await page.getByPlaceholder("Add a reason, or leave this blank.").fill(reason);
  await page.getByRole("button", { name: "Save my choice", exact: true }).click();
  await expect(page.getByTestId("saved-replay-choice")).toBeVisible();
};
const noOverflow = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

test("replay saves two decisions before explicit bounded reveals and survives reload", async ({ page }) => {
  const calls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/backend/")) calls.push(new URL(request.url()).pathname); });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/practice");
  await page.screenshot({ path: test.info().outputPath("replay-entry-desktop.png"), fullPage: true });
  await page.getByRole("link", { name: "Open a replay" }).click();
  await page.getByRole("button", { name: "Start replay", exact: true }).click();
  await expect(page).toHaveURL(/attempt=/);
  await expect(page.getByText("Checkpoint 1 of 2", { exact: true })).toBeVisible();
  await expect(page.getByTestId("frozen-candles")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save my choice", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reveal what happened next", exact: true })).toHaveCount(0);
  await expect(page.getByTestId("replay-reveal-first-look")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("replay-frozen-desktop.png"), fullPage: true });
  await choose(page, "Exit", "The position no longer fits the original time horizon.");
  const savedUrl = page.url();
  await page.reload();
  await expect(page.getByTestId("saved-replay-choice")).toContainText("The position no longer fits");
  await expect(page.getByTestId("replay-reveal-first-look")).toHaveCount(0);
  await page.getByRole("button", { name: "Reveal what happened next", exact: true }).click();
  await expect(page.getByText("Checkpoint 2 of 2", { exact: true })).toBeVisible();
  await expect(page.getByTestId("replay-reveal-first-look")).toContainText("Your choice: exit");
  await expect(page.getByTestId("replay-reveal-later-look")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("replay-next-moment-desktop.png"), fullPage: true });
  await choose(page, "Reduce");
  await page.getByRole("button", { name: "Reveal what happened next", exact: true }).click();
  await expect(page.getByText("Replay complete", { exact: true })).toBeVisible();
  await expect(page.getByTestId("replay-reveal-later-look")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Replay complete", { exact: true })).toBeVisible();
  await expect(page.getByTestId("replay-reveal-first-look")).toContainText("Your choice: exit");
  await noOverflow(page);
  await page.screenshot({ path: test.info().outputPath("replay-comparison-desktop.png"), fullPage: true });
  const prior = page.getByTestId("replay-reveal-first-look");
  await prior.getByText("What was knowable at checkpoint 1", { exact: true }).click();
  await expect(prior.getByTestId("frozen-candles")).toBeVisible();
  await page.goto("/practice/replay");
  await expect(page.getByRole("link", { name: "Resume last replay" })).toHaveAttribute("href", new URL(savedUrl).pathname + new URL(savedUrl).search);
  await page.getByRole("link", { name: "Resume last replay" }).click();
  await expect(page.getByText("Replay complete", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Try this scenario again with new choices" }).click();
  await expect(page).not.toHaveURL(savedUrl);
  await expect(page.getByText(/Repeated attempt/)).toBeVisible();
  const contextReads = calls.filter(path => /\/(copilot|quotes|charts\/workspace|market-context)\//.test(path));
  // The shared navigation reads feature/job status; none contains market evidence.
  expect(contextReads.filter(path => !["/api/backend/copilot/status", "/api/backend/market-context/enrich/status", "/api/backend/market-context/trade-path/status"].includes(path))).toEqual([]);
  expect(errors).toEqual([]);
});

test("phone replay has reachable choices and explicit reveals without horizontal overflow", async ({ page, request }) => {
  const attempt = await create(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/practice/replay?attempt=${attempt.attempt_id}`);
  await expect(page.getByTestId("frozen-candles")).toBeVisible();
  await noOverflow(page);
  await page.screenshot({ path: test.info().outputPath("replay-frozen-phone.png"), fullPage: true });
  await choose(page, "Hold");
  const reveal = page.getByRole("button", { name: "Reveal what happened next", exact: true });
  await reveal.scrollIntoViewIfNeeded();
  await expect(reveal).toBeInViewport();
  expect((await reveal.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await reveal.click();
  await expect(page.getByText("Checkpoint 2 of 2", { exact: true })).toBeVisible();
  await choose(page, "Exit");
  await reveal.click();
  await expect(page.getByText("Replay complete", { exact: true })).toBeVisible();
  await noOverflow(page);
  await page.screenshot({ path: test.info().outputPath("replay-comparison-phone.png"), fullPage: true });
});

test("browser receives no sealed continuation before choice or before explicit reveal", async ({ page, request }) => {
  const attempt = await create(request);
  const packets: Record<string, unknown>[] = [];
  page.on("response", async response => {
    if (response.url().includes(`/practice/replay/attempts/${attempt.attempt_id}`) && response.ok()) {
      packets.push(await response.json());
    }
  });
  await page.goto(`/practice/replay?attempt=${attempt.attempt_id}`);
  await expect(page.getByTestId("frozen-candles")).toBeVisible();
  await choose(page, "Reduce", "Contemporaneous reason only");
  expect(packets.length).toBeGreaterThanOrEqual(2);
  for (const packet of packets) {
    expect(packet.revealed).toEqual([]);
    const serialized = JSON.stringify(packet);
    expect(serialized).not.toMatch(/actual_action|final_outcome|later-look|retrospective/);
    expect(packet).not.toHaveProperty("snapshot");
  }
  const state = await (await request.get(`${API}/practice/replay/attempts/${attempt.attempt_id}`)).json();
  const cutoff = Date.parse(state.checkpoint.input_cutoff);
  for (const bar of state.checkpoint.bars) {
    expect(Date.parse(bar.interval_end)).toBeLessThanOrEqual(cutoff);
    expect(Date.parse(bar.observed_at)).toBeLessThanOrEqual(cutoff);
    expect(Date.parse(bar.published_at)).toBeLessThanOrEqual(cutoff);
  }
});

test("uncertain choice response recovers the durable choice without revealing", async ({ page, request }) => {
  const attempt = await create(request);
  await page.goto(`/practice/replay?attempt=${attempt.attempt_id}`);
  await page.route(`**/practice/replay/attempts/${attempt.attempt_id}/choice`, async route => {
    await route.fetch();
    await route.fulfill({ status: 503, json: { detail: "Response lost after commit" } });
  }, { times: 1 });
  await page.getByRole("button", { name: "Exit", exact: true }).click();
  await page.getByRole("button", { name: "Save my choice", exact: true }).click();
  await expect(page.getByTestId("personal-replay").getByRole("alert")).toContainText("Response lost");
  await page.getByRole("button", { name: "Reload and recover" }).click();
  await expect(page.getByTestId("saved-replay-choice")).toContainText("exit");
  await expect(page.getByTestId("replay-reveal-first-look")).toHaveCount(0);
});

test("uncertain reveal response recovers only its committed segment", async ({ page, request }) => {
  const attempt = await create(request);
  await page.goto(`/practice/replay?attempt=${attempt.attempt_id}`);
  await choose(page, "Hold");
  await page.route(`**/practice/replay/attempts/${attempt.attempt_id}/reveal`, async route => {
    await route.fetch();
    await route.fulfill({ status: 503, json: { detail: "Reveal response lost after commit" } });
  }, { times: 1 });
  await page.getByRole("button", { name: "Reveal what happened next", exact: true }).click();
  await expect(page.getByTestId("personal-replay").getByRole("alert")).toContainText("Reveal response lost");
  await page.getByRole("button", { name: "Reload and recover" }).click();
  await expect(page.getByText("Checkpoint 2 of 2", { exact: true })).toBeVisible();
  await expect(page.getByTestId("replay-reveal-later-look")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save my choice", exact: true })).toBeDisabled();
});

test("an unknown saved replay reports failure instead of silently starting over", async ({ page }) => {
  await page.goto(`/practice/replay?attempt=${crypto.randomUUID()}`);
  await expect(page.getByTestId("personal-replay").getByRole("alert")).toContainText("Replay attempt not found");
  await expect(page.getByRole("button", { name: "Start replay", exact: true })).toHaveCount(0);
});


test("a lost start response retries the same attempt after reload", async ({ page }) => {
  const operations: string[] = [];
  const created: string[] = [];
  await page.route("**/practice/replay/attempts", async route => {
    operations.push(route.request().postDataJSON().operation_id);
    const response = await route.fetch();
    created.push((await response.json()).attempt_id);
    if (operations.length === 1) await route.fulfill({ status: 503, json: { detail: "Start response lost" } });
    else await route.fulfill({ response });
  });
  await page.goto("/practice/replay");
  await page.getByRole("button", { name: "Start replay", exact: true }).click();
  await expect(page.getByTestId("personal-replay").getByRole("alert")).toContainText("Start response lost");
  await page.reload();
  await page.getByRole("button", { name: "Start replay", exact: true }).click();
  await expect(page.getByText("Checkpoint 1 of 2", { exact: true })).toBeVisible();
  expect(operations).toHaveLength(2);
  expect(operations[0]).toBe(operations[1]);
  expect(created[0]).toBe(created[1]);
});
