import { expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;

const frozen = (symbol: string) => ({
  context_id: `context-${symbol}`,
  symbol,
  captured_at: "2026-10-07T14:00:00Z",
  provider: "fixture",
  context_sha256: "abc",
  price_facts: [],
  packet: {},
});

test("discards freeze responses after the symbol changes", async ({ page }) => {
  let release!: () => void;
  const waiting = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/backend/decisions/context/SPY", async (route) => {
    await waiting;
    await route.fulfill({ json: frozen("SPY") });
  });
  await page.goto("/");
  await page.getByText("Save a human decision").click();
  await page.getByLabel("Symbol").fill("SPY");
  const spyRequest = page.waitForRequest((request) => request.url().includes("/decisions/context/SPY"));
  await page.getByRole("button", { name: "Freeze market context" }).click();
  await spyRequest;
  await page.getByLabel("Symbol").fill("QQQ");
  release();
  await expect(page.getByText(/Saved server context for SPY/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save immutable decision" })).toBeDisabled();
});

test("newer freeze request wins when responses arrive out of order", async ({ page }) => {
  let releaseSpy!: () => void;
  const spyWaiting = new Promise<void>((resolve) => { releaseSpy = resolve; });
  await page.route("**/api/backend/decisions/context/**", async (route) => {
    const symbol = new URL(route.request().url()).pathname.split("/").at(-1)!;
    if (symbol === "SPY") await spyWaiting;
    await route.fulfill({ json: frozen(symbol) });
  });
  await page.goto("/");
  await page.getByText("Save a human decision").click();
  await page.getByLabel("Symbol").fill("SPY");
  const spyRequest = page.waitForRequest((request) => request.url().includes("/decisions/context/SPY"));
  await page.getByRole("button", { name: "Freeze market context" }).click();
  await spyRequest;
  await page.getByLabel("Symbol").fill("QQQ");
  await page.getByRole("button", { name: "Freeze market context" }).click();
  await expect(page.getByText(/Saved server context for QQQ/)).toBeVisible();
  releaseSpy();
  await expect(page.getByText(/Saved server context for QQQ/)).toBeVisible();
  await expect(page.getByText(/Saved server context for SPY/)).toHaveCount(0);
});

test("retries an uncertain freeze with the same operation ID", async ({ page }) => {
  const operationIds: string[] = [];
  let attempts = 0;
  await page.route("**/api/backend/decisions/context/SPY", async (route) => {
    operationIds.push(route.request().postDataJSON().operation_id);
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 503, json: { detail: "temporary failure" } });
    await route.fulfill({ json: frozen("SPY") });
  });
  await page.goto("/");
  await page.getByText("Save a human decision").click();
  await page.getByLabel("Symbol").fill("SPY");
  await page.getByRole("button", { name: "Freeze market context" }).click();
  await expect(page.locator("details").filter({ hasText: "Save a human decision" }).locator('p[role="alert"]')).toBeVisible();
  await page.getByRole("button", { name: "Freeze market context" }).click();
  await expect(page.getByText(/Saved server context for SPY/)).toBeVisible();
  expect(operationIds).toHaveLength(2);
  expect(operationIds[1]).toBe(operationIds[0]);
});

test("saved WAIT and SKIP details survive a page reload", async ({ page, request }) => {
  const contextResponse = await request.post(`${API}/decisions/context/SPY`, {
    data: { operation_id: `e2e-context-${crypto.randomUUID()}` },
  });
  expect(contextResponse.ok()).toBeTruthy();
  const context = await contextResponse.json();
  const common = { actor: "human", symbol: "SPY", context_id: context.context_id };
  const waitOpportunityId = `e2e-wait-${crypto.randomUUID()}`;
  const waitResponse = await request.post(`${API}/decisions`, {
    data: {
      ...common,
      operation_id: `e2e-wait-${crypto.randomUUID()}`,
      opportunity_id: waitOpportunityId,
      decision: "wait",
      rationale: "Need confirmation before entry",
      wait_condition: "Close above 600",
      wait_expiry: "2030-01-01T21:00:00Z",
    },
  });
  expect(waitResponse.ok()).toBeTruthy();
  const skipOpportunityId = `e2e-skip-${crypto.randomUUID()}`;
  const skipResponse = await request.post(`${API}/decisions`, {
    data: {
      ...common,
      operation_id: `e2e-skip-${crypto.randomUUID()}`,
      opportunity_id: skipOpportunityId,
      decision: "skip",
      rationale: "Setup no longer fits the plan",
    },
  });
  expect(skipResponse.ok()).toBeTruthy();

  await page.goto("/");
  await page.reload();
  const waitRecord = page.locator("details").filter({ hasText: waitOpportunityId });
  await waitRecord.locator("summary").click();
  await expect(waitRecord).toContainText("Need confirmation before entry");
  await expect(waitRecord).toContainText("Close above 600");
  await expect(waitRecord).toContainText("2030");
  const skipRecord = page.locator("details").filter({ hasText: skipOpportunityId });
  await skipRecord.locator("summary").click();
  await expect(skipRecord).toContainText("Setup no longer fits the plan");
});
