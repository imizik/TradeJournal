import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

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


// --- A2: Practice paper plans on the Today page -----------------------------------------------

const BACKEND_DIR = path.resolve(__dirname, "..", "..", "backend");
const E2E_DB = path.join(BACKEND_DIR, "data", "e2e_seed.db");

/** The API cannot save a TAKE without provider minute facts, so the row goes straight into the e2e database. */
function insertTake(contextId: string): string {
  const id = crypto.randomUUID();
  const python = existsSync(path.join(BACKEND_DIR, ".venv", "bin", "python")) ? path.join(BACKEND_DIR, ".venv", "bin", "python") : "python3";
  const script = `
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
plan = {"trigger_level": 600.0, "stop": 598.0, "target": 604.0, "target_source": {"source": "fixture"}, "entry_guard": {"min": 599.0, "max": 601.0}, "expiry": "2026-10-08T15:00:00-04:00", "max_holding_sessions": 2, "initial_risk_per_share": 2.0, "cost_model": {"version": "p0-cost-v1", "slippage_bps": 1, "slippage_per_share": 0.01}}
db.execute("insert into decision_record (id, operation_id, opportunity_id, actor, decision, symbol, context_id, received_at, input_cutoff, policy_version, policy_hash, evidence_json, evidence_sha256, decision_json, record_sha256) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
  (sys.argv[2], "e2e-take-" + sys.argv[2], "e2e-paper-" + sys.argv[2], "human", "take", "SPY", sys.argv[3], "2026-10-07 12:55:00.000000", "2026-10-07 12:54:00.000000", "v", "h", "{}", "e", json.dumps({"plan": plan, "rationale": "", "wait_condition": None, "wait_expiry": None}), "r"))
db.commit()
`;
  execFileSync(python, ["-c", script, E2E_DB, id.replace(/-/g, ""), contextId.replace(/-/g, "")]);
  return id;
}

// The smoke test loads Today against the real backend, so these rows must not outlive the tests that need them.
test.afterEach(() => {
  const python = existsSync(path.join(BACKEND_DIR, ".venv", "bin", "python")) ? path.join(BACKEND_DIR, ".venv", "bin", "python") : "python3";
  execFileSync(python, ["-c", "import sqlite3,sys\ndb=sqlite3.connect(sys.argv[1])\ndb.execute(\"delete from decision_record where operation_id like 'e2e-take-%'\")\ndb.commit()", E2E_DB]);
});

async function takeRecord(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const ctx = await request.post(`${API}/decisions/context/SPY`, { data: { operation_id: `e2e-context-${crypto.randomUUID()}` } });
  expect(ctx.ok()).toBeTruthy();
  return insertTake((await ctx.json()).context_id);
}

const ev = (type: string, seq: number, at: number, extra: Record<string, unknown> = {}) => ({
  type, key: type, at, seq, recorded_at: at, source: "fixture", reconstructed: false, delivery: null, delivery_error: null, ...extra,
});
const outcome = (version: string, net: number, r: number) => ({
  cost_version: version, entry_fill: 600.11, exit_fill: 603.89, net_per_share: net, planned_r: r,
  entry_to_stop_exposure: 2.11, exit_kind: "target", ambiguous: false, gap: false,
});

async function mockPaper(page: Page, id: string, initial: Record<string, unknown>, armed?: Record<string, unknown>) {
  let current = initial;
  const armOps: string[] = [];
  await page.route(`**/api/backend/decisions/${id}/paper`, (route) => route.fulfill({ json: current }));
  await page.route(`**/api/backend/decisions/${id}/arm`, (route) => {
    armOps.push(route.request().postDataJSON().operation_id);
    if (!armed) return route.fulfill({ status: 422, json: { detail: "Plan expires before the next session." } });
    current = armed;
    return route.fulfill({ status: 201, json: armed });
  });
  return armOps;
}

test("arms a TAKE and shows the paper timeline", async ({ page, request }) => {
  const id = await takeRecord(request);
  const base = { record_id: id, policy_version: "shadow-isaac-p0-v1", outcome: null, outcome_x3: null };
  const armOps = await mockPaper(page, id, { ...base, status: "unarmed", events: [] },
    { ...base, status: "armed", events: [ev("armed", 1, 1791378000, { delivery: "pending" })] });
  await page.goto("/");
  const card = page.locator(`#decision-${id}`);
  await card.locator("summary").click();
  await card.getByRole("button", { name: "Arm paper plan" }).click();
  await expect(card.getByText("PRACTICE · PAPER · ARMED").first()).toBeVisible();
  await expect(card.getByRole("button", { name: "Arm paper plan" })).toHaveCount(0);
  await expect(card.getByText("phone alert pending")).toBeVisible();
  expect(armOps).toHaveLength(1);
  expect(armOps[0]).toMatch(/^arm-[A-Za-z0-9._:-]+$/);
});

test("shows a policy refusal verbatim and reuses no stale operation", async ({ page, request }) => {
  const id = await takeRecord(request);
  await mockPaper(page, id, { record_id: id, status: "unarmed", policy_version: null, events: [], outcome: null, outcome_x3: null });
  await page.goto("/");
  const card = page.locator(`#decision-${id}`);
  await card.locator("summary").click();
  await card.getByRole("button", { name: "Arm paper plan" }).click();
  await expect(card.getByRole("alert")).toHaveText("Plan expires before the next session.");
});

test("a closed paper plan shows base and 3x outcomes, and ?decision= opens the card without overflow", async ({ page, request }) => {
  const id = await takeRecord(request);
  await mockPaper(page, id, {
    record_id: id, status: "closed", policy_version: "shadow-isaac-p0-v1",
    events: [
      ev("armed", 1, 1791378000, { delivery: "sent" }),
      ev("trigger", 2, 1791381600, { close: 600.5, level: 600, detected_at: 1791381610, delay_seconds: 10, reconstructed: true, delivery: "sent" }),
      ev("entry", 3, 1791381660, { fill: 600.11, reference: 600.1 }),
      ev("exit", 4, 1791385200, { kind: "target", fill: 603.89, ambiguous: true, gap: false }),
    ],
    outcome: outcome("p0-cost-v1", 3.78, 1.791), outcome_x3: outcome("p0-cost-v1-x3", 3.7, 1.753),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/?decision=${id}`);
  const card = page.locator(`#decision-${id}`);
  await expect(card).toHaveJSProperty("open", true);
  await expect(card.getByText("PRACTICE · PAPER · CLOSED").first()).toBeVisible();
  await expect(card.getByText(/Paper outcome \(p0-cost-v1\)/)).toBeVisible();
  await expect(card.getByText(/Paper outcome at 3× costs/)).toBeVisible();
  await expect(card.getByText(/planned R 1\.791/)).toBeVisible();
  await expect(card.getByText(/planned R 1\.753/)).toBeVisible();
  await expect(card.getByText("reconstructed")).toBeVisible();
  await expect(card.getByText("ambiguous").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
