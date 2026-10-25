import { expect, test, type Page, type Route } from "@playwright/test";

// The copilot's plan card (propose_plan kind=trade_plan). Every lab, quote, capture and alert route is stubbed in the
// browser: the turn is a fixed SSE stream, so no model runs, and nothing reaches the e2e backend's plans or alerts.
const INV = "44444444-4444-4444-8444-444444444444";
const ROTH = "00000000-0000-0000-0000-000000000001";
const status = (alerts: boolean) => ({
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: alerts },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
});
const record = {
  id: INV, source: "copilot", title: "Plan a trade: yolo NBIS calls", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:00:00Z",
  transcript: [{ role: "user", content: "Plan a trade: yolo NBIS calls" }, { role: "assistant", content: "NBIS plan (draft)." }], evidence: [], findings: null,
};
const PLAN = { id: "p1", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "calls", contract: "Nov 21 100C",
  thesis: "NBIS reclaims the level overhead with its group, so the bounce has room.",
  entry_trigger: { condition: "closes_beyond", price: 95.9, interval: "5m" }, invalidation: { condition: "crosses", price: 92.3, interval: null },
  time_stop: "out by 15:30 if the entry has not worked", size_note: "one starter, no adds", last: 94.35, as_of: "2026-10-24T14:00:00Z" };
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const TURN = sse([
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...PLAN },
  { type: "text", delta: "NBIS plan (draft). Nothing is saved or armed until you confirm it." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

type Server = { alerts: object[]; posts: { path: string; body: Record<string, unknown> }[]; failAlert?: (body: Record<string, unknown>) => boolean };

async function lab(page: Page, server: Server, { alertsSupported = true, defaultAccount = ROTH as string | null } = {}) {
  const post = (path: string, route: Route) => server.posts.push({ path, body: route.request().postDataJSON() });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status(alertsSupported) }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: record }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: route.request().method() === "PUT" ? { ...record, revision: 2 } : record }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: true, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: {
    accounts: [{ id: ROTH, label: "Roth IRA ··8267", broker: "robinhood" }, { id: "00000000-0000-0000-0000-000000000002", label: "Individual", broker: "robinhood" }],
    default_account_id: defaultAccount, templates: [], max_templates: 3, transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", (route) => {
    post("captures", route);
    return route.fulfill({ status: 201, json: { id: "c1", ...route.request().postDataJSON() } });
  });
  await page.route("**/charts/alerts", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: { alerts: server.alerts, phone: true } });
    post("alerts", route);
    const body = route.request().postDataJSON();
    if (server.failAlert?.(body)) return route.fulfill({ status: 422, json: { detail: "Up to 20 active alerts. Remove one first." } });
    server.alerts = [...server.alerts, { id: `a${server.alerts.length + 1}`, created_on: "2026-10-24", direction: "up", state: "active", armed_at: 1, event: null, ...body }];
    return route.fulfill({ json: { alerts: server.alerts, phone: true } });
  });
  await page.goto("/copilot-lab");
}

async function askForPlan(page: Page) {
  await page.getByLabel("Message").fill("Plan a trade: yolo NBIS calls");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("NBIS plan (draft).")).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible(); // the investigation exists, so the alerts can link to it
  return page.getByRole("region", { name: "Proposed trade plan" });
}

const posts = (server: Server, path: string) => server.posts.filter((p) => p.path === path).map((p) => p.body);

test("the plan card is edited, then Confirm saves the pre-trade plan and arms both alerts", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  const card = await askForPlan(page);
  await expect(card).toContainText("Proposed trade plan · NBIS · Buy calls · Nov 21 100C");
  await expect(card.getByLabel("Thesis")).toHaveValue(PLAN.thesis);
  await expect(card.getByLabel("Entry (5m close beyond)")).toHaveValue("95.9");
  await expect(card.getByLabel("Invalidation (crosses)")).toHaveValue("92.3");
  expect(server.posts).toEqual([]); // nothing until Confirm

  await card.getByLabel("Invalidation (crosses)").fill("96");
  await expect(card.getByRole("alert")).toHaveText("A long plan's invalidation must be below its entry.");
  await expect(card.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await card.getByLabel("Invalidation (crosses)").fill("92.1");
  await card.getByLabel("Thesis").fill("Neoclouds turn and NBIS reclaims the prior-day low.");
  await card.getByLabel("Time stop").fill("out by 15:30");
  await card.getByRole("button", { name: "Confirm" }).click();

  const results = card.getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Pre-trade plan: done");
  await expect(results).toContainText("Entry alert: done");
  await expect(results).toContainText("Invalidation alert: done");
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");

  const [capture] = posts(server, "captures");
  expect(capture).toMatchObject({
    underlying: "NBIS", account_id: ROTH, side: "buy_calls", mode: "discretionary", setup_label: "Copilot plan", image: false,
    wording: "Entry: 5m close beyond 95.9. Invalidation: crosses 92.1. Time stop: out by 15:30. Size: one starter, no adds.",
    note: "Thesis: Neoclouds turn and NBIS reclaims the prior-day low. Contract: Nov 21 100C. From a Copilot Lab plan card.",
    context: { state: "unavailable", reason: "Saved from a Copilot Lab plan card." },
  });
  expect(typeof capture.client_id).toBe("string");
  expect(posts(server, "alerts")).toEqual([
    { symbol: "NBIS", price: 95.9, reference: 94.35, condition: "closes_beyond", interval: "5m", session: "regular",
      source_kind: "copilot", source_id: INV, label: "NBIS entry: 5m close beyond 95.9" },
    { symbol: "NBIS", price: 92.1, reference: 94.35, condition: "crosses", interval: null, session: "regular",
      source_kind: "copilot", source_id: INV, label: "NBIS invalidation: crosses 92.1" },
  ]);
  await expect(card.getByLabel("Thesis")).toBeDisabled(); // the saved plan is what the card shows now
  await expect(page.getByRole("region", { name: "Linked to this investigation" })).toContainText("NBIS invalidation: crosses 92.1");
});

test("a partial failure names the failed part and retries only that part", async ({ page }) => {
  let failing = true;
  const server: Server = { alerts: [], posts: [], failAlert: (body) => failing && String(body.label).includes("invalidation") };
  await lab(page, server);
  const card = await askForPlan(page);
  await card.getByRole("button", { name: "Confirm" }).click();
  const results = card.getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Invalidation alert: failed");
  await expect(results).toContainText("Up to 20 active alerts. Remove one first.");
  await expect(results).toContainText("Pre-trade plan: done");
  await expect(results).toContainText("Entry alert: done");
  await expect(card.getByRole("button", { name: /^Retry/ })).toHaveCount(1);
  await expect(card.getByRole("status")).toHaveCount(0);

  failing = false;
  await card.getByRole("button", { name: "Retry invalidation alert" }).click();
  await expect(results).toContainText("Invalidation alert: done");
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  expect(posts(server, "captures")).toHaveLength(1); // the plan was not saved twice
  expect(posts(server, "alerts").map((b) => b.label)).toEqual(["NBIS entry: 5m close beyond 95.9", "NBIS invalidation: crosses 92.3", "NBIS invalidation: crosses 92.3"]);
});

test("without alert support Confirm saves only the plan; with no default account it asks which", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server, { alertsSupported: false, defaultAccount: null });
  const card = await askForPlan(page);
  await expect(card).toContainText("Awaiting alert support");
  await expect(card.getByRole("alert")).toHaveText("Choose the journal account this plan is for.");
  await expect(card.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await card.getByLabel("Journal account").selectOption({ label: "Individual" });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  expect(posts(server, "captures").map((b) => b.account_id)).toEqual(["00000000-0000-0000-0000-000000000002"]);
  expect(posts(server, "alerts")).toEqual([]);
});

test("the plan card fits a 375 px phone with large tap targets, and Dismiss removes it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  const card = await askForPlan(page);
  const box = (await card.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(375);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  for (const control of [card.getByRole("button", { name: "Confirm" }), card.getByRole("button", { name: "Dismiss" }),
    card.getByLabel("Entry (5m close beyond)"), card.getByLabel("Invalidation (crosses)"), card.getByLabel("Time stop")]) {
    const size = (await control.boundingBox())!;
    expect(size.height).toBeGreaterThanOrEqual(44);
    expect(size.x + size.width).toBeLessThanOrEqual(375);
  }
  await page.screenshot({ path: test.info().outputPath("trade-plan-375.png"), fullPage: false });
  await card.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("region", { name: "Proposed trade plan" })).toHaveCount(0);
  expect(server.posts).toEqual([]);
});
