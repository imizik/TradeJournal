import { expect, test, type Page } from "@playwright/test";

// Confirm-a-plan. Every lab, quote, alert and queue route is stubbed in the browser: the turn is a fixed SSE stream,
// so no model runs, and nothing reaches the e2e backend's alerts.
const INV = "33333333-3333-4333-8333-333333333333";
const status = (alerts: boolean) => ({
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: alerts },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
});
const record = {
  id: INV, source: "copilot", title: "Make a plan for NBIS", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-24T14:00:00Z", updated_at: "2026-10-24T14:00:00Z",
  transcript: [{ role: "user", content: "Make a plan for NBIS" }, { role: "assistant", content: "Plan drafted." }], evidence: [], findings: null,
};
const WATCH = { id: "p1", kind: "watch", symbol: "NBIS", condition: "crosses", price: 92.46, interval: null,
  label: "NBIS 2% below the last price", why: "A break here would mean the bounce failed.", last: 94.35, as_of: "2026-10-24T14:00:00Z" };
const REVISIT = { id: "p2", kind: "revisit", question: "Is NBIS still lagging its group?", horizon_days: 1 };
const MEMORY = { id: "p3", kind: "memory", memory_kind: "thesis", symbol: "NBIS", text: "NBIS is a two-year infra thesis for me.",
  interpretation: "Ask whether a weekly call fits that horizon." };
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
// Live provenance, as in production: the quote is "fetched" and the proposal is "proposal" (fixture evidence would
// relabel both "simulated").
const TURN = sse([
  { type: "tool", id: "q1", name: "get_quotes", status: "running" },
  { type: "tool", id: "q1", name: "get_quotes", status: "ok", summary: "NBIS 94.35", ms: 1, provenance: { source: "Tradier", kind: "fetched", as_of: "2026-10-24T14:00:00Z" } },
  { type: "tool", id: "p1", name: "propose_plan", status: "running" },
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed watch", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...WATCH },
  { type: "proposal", ...REVISIT },
  { type: "proposal", ...MEMORY },
  { type: "text", delta: "Plan drafted. Nothing is saved or active until you confirm a card below." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

type Server = { alerts: object[]; jobs: object[]; posts: { path: string; body: unknown }[]; quote: { fresh: boolean; last: number | null }; queueOff?: boolean };

async function lab(page: Page, server: Server, { alertsSupported = true, url = "/copilot-lab" } = {}) {
  const post = (path: string, route: import("@playwright/test").Route) => server.posts.push({ path, body: route.request().postDataJSON() });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status(alertsSupported) }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => { post("investigations", route); return route.fulfill({ status: 201, json: record }); });
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: route.request().method() === "PUT" ? { ...record, revision: 2 } : record }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", trade_time: 1, fetched_at: 1, age_s: 2, issue: null, ...server.quote } }));
  await page.route("**/charts/alerts", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: { alerts: server.alerts, phone: true } });
    post("alerts", route);
    const body = route.request().postDataJSON();
    server.alerts = [{ id: "a1", created_on: "2026-10-24", direction: "down", state: "active", armed_at: 1, event: null, ...body }];
    return route.fulfill({ json: { alerts: server.alerts, phone: true } });
  });
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: server.jobs, queue_enabled: true, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/jo/memories", (route) => {
    post("memories", route);
    return route.fulfill({ status: 201, json: { id: "r1", memory_id: "m1", revision: 1, operation_id: "x", status: "active" } });
  });
  await page.route("**/copilot/research-jobs/reassess", (route) => {
    post("reassess", route);
    const body = route.request().postDataJSON();
    server.jobs = [{ id: "j1", kind: "reassess", status: "queued", input: { investigation_id: body.investigation_id, question: body.question, requested_by: "owner", from_investigation: body.investigation_id },
      attempts: 0, error: null, cost_usd: null, investigation_id: null, created_at: "2026-10-24T14:01:00", next_attempt_at: "2026-10-25T14:01:00", finished_at: null }];
    return route.fulfill({ status: 201, json: { job: server.jobs[0], created: true, queue_enabled: !server.queueOff } });
  });
  // The desk's Context pane reads the thread's timeline from the server; this one answers from the alerts and revisits
  // above, as GET /copilot/desk/{id}/timeline would (its composition is tests/test_copilot_desk_context.py).
  await page.route(`**/copilot/desk/${INV}/timeline`, (route) => route.fulfill({ json: { state: "ok", symbol: "NBIS", unavailable: [],
    recent_days: 7, count: 0, rows: [
      ...(server.alerts as { price: number; label: string; state: string; source_kind: string; source_id: string;
        event: { price: number; event_at: number } | null }[]).filter((a) => a.source_kind === "copilot" && a.source_id === INV).map((a) =>
        a.state === "active" ? { kind: "alert", at: 1792857000, text: "Alert armed", detail: `crosses ${a.price} · ${a.label}` }
          : { kind: "alert", at: a.event!.event_at, text: "Alert hit", detail: `at ${a.event!.price}` }),
      ...(server.jobs as { input: { question: string } }[]).map((j) => ({ kind: "revisit", at: 1792857100, text: "Revisit queued", detail: j.input.question })),
    ] } }));
  await page.goto(url);
}

/** The Context pane's Timeline tab, opened. */
async function timeline(page: Page) {
  const pane = page.getByRole("complementary", { name: "Context" });
  await pane.getByRole("tab", { name: "Timeline" }).click();
  return pane.getByRole("list", { name: "Timeline" });
}

async function askForPlan(page: Page) {
  await page.getByLabel("Message").fill("Make a plan for NBIS");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Plan drafted.")).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible(); // the investigation exists, so Confirm can link to it
}

/** The kinds `EvidenceRef.kind` accepts (backend/app/engine/copilot_investigations.py) apart from the legacy "proposal". */
const EVIDENCE_KINDS = ["recorded", "fetched", "cached", "simulated", "replay", "saved"];

const fresh = (): Server => ({ alerts: [], jobs: [], posts: [], quote: { fresh: true, last: 94.35 } });

test("a proposed watch is confirmed against a fresh quote and shows as a linked alert", async ({ page }) => {
  const server = fresh();
  await lab(page, server);
  await askForPlan(page);
  // The saved investigation carries the quote as evidence and leaves the proposal out: a proposal is not evidence.
  const saved = server.posts.find((p) => p.path === "investigations")!.body as { evidence: { tool: string; kind: string; message: number }[] };
  expect(saved.evidence).toEqual([{ tool: "get_quotes", as_of: "2026-10-24T14:00:00Z", kind: "fetched", message: 1 }]);
  expect(saved.evidence.every((ref) => EVIDENCE_KINDS.includes(ref.kind))).toBe(true);
  const card = page.getByRole("region", { name: "Proposed watch" });
  await expect(card).toContainText("Proposed watch · NBIS crosses 92.46");
  await expect(card).toContainText("Label: NBIS 2% below the last price");
  await expect(card).toContainText("Nothing is active until you confirm.");
  expect(server.posts.filter((p) => p.path === "alerts")).toEqual([]); // nothing until Confirm
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toHaveText("Alert set: NBIS crosses 92.46 (NBIS was 94.35).");
  expect(server.posts.find((p) => p.path === "alerts")!.body).toEqual({ symbol: "NBIS", price: 92.46, reference: 94.35, condition: "crosses",
    interval: null, session: "regular", source_kind: "copilot", source_id: INV, label: "NBIS 2% below the last price" });
  const linked = await timeline(page);
  await expect(linked).toContainText("Alert armed");
  await expect(linked).toContainText("NBIS 2% below the last price");
  await expect(page.getByRole("region", { name: "Research deeper" })).toHaveCount(1); // one per investigation, also after it saves
  await page.screenshot({ path: test.info().outputPath("confirm-a-plan.png") });
});

test("a stale quote refuses the watch and sends nothing", async ({ page }) => {
  const server = { ...fresh(), quote: { fresh: false, last: 94.1 } };
  await lab(page, server);
  await askForPlan(page);
  const card = page.getByRole("region", { name: "Proposed watch" });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("alert")).toHaveText("The latest NBIS quote is stale or missing, so the alert was not set. Try again in a moment.");
  await expect(card.getByRole("button", { name: "Confirm" })).toBeEnabled(); // it can be tried again
  expect(server.posts.filter((p) => p.path === "alerts")).toEqual([]);
});

test("without alert support a watch waits, while a revisit still confirms; Dismiss removes a card", async ({ page }) => {
  const server = { ...fresh(), queueOff: true };
  await lab(page, server, { alertsSupported: false });
  await askForPlan(page);
  const watch = page.getByRole("region", { name: "Proposed watch" });
  await expect(watch).toContainText("Awaiting alert support");
  await expect(watch.getByRole("button", { name: "Confirm" })).toHaveCount(0);
  const revisit = page.getByRole("region", { name: "Proposed revisit" });
  await expect(revisit).toContainText("Research again in 1 day: Is NBIS still lagging its group?");
  await revisit.getByRole("button", { name: "Confirm" }).click();
  await expect(revisit.getByRole("status")).toHaveText("Revisit queued. The research queue is off, so it waits until the queue is turned on.");
  expect(server.posts.find((p) => p.path === "reassess")!.body).toEqual({ investigation_id: INV, question: "Is NBIS still lagging its group?", after_days: 1 });
  await expect(await timeline(page)).toContainText("Revisit queued");
  await watch.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("region", { name: "Proposed watch" })).toHaveCount(0);
  expect(server.posts.filter((p) => p.path === "alerts")).toEqual([]);
});

test("a memory card saves the owner's edited words as an approved memory, and only on Confirm", async ({ page }) => {
  const server = fresh();
  await lab(page, server);
  await askForPlan(page);
  const card = page.getByRole("region", { name: "Proposed memory" });
  await expect(card).toContainText("Proposed memory · thesis · NBIS");
  await expect(card).toContainText("How it will be used: Ask whether a weekly call fits that horizon.");
  const box = card.getByLabel("Memory text");
  await expect(box).toHaveValue("NBIS is a two-year infra thesis for me.");
  expect(server.posts.filter((p) => p.path === "memories")).toEqual([]); // nothing until Confirm
  await box.fill("NBIS is a two-year infrastructure thesis for me, not a weekly trade.");
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("status")).toHaveText("Remembered (thesis, NBIS). It joins your approved memories from the next turn.");
  const [saved] = server.posts.filter((p) => p.path === "memories");
  const body = saved.body as Record<string, unknown>;
  expect(body).toMatchObject({ kind: "thesis", symbol: "NBIS", original_text: "NBIS is a two-year infrastructure thesis for me, not a weekly trade.",
    interpretation: "Ask whether a weekly call fits that horizon.", source: "owner_statement", source_reference: `copilot:${INV}`,
    status: "active", owner_confirmed: true });
  expect(typeof body.operation_id).toBe("string");
  await expect(card.getByRole("button", { name: "Confirm" })).toHaveCount(0);
  await expect(card.getByLabel("Memory text")).toHaveCount(0); // the saved words are shown as text now
});

test("?investigation= opens that investigation with its fired alert", async ({ page }) => {
  const server = fresh();
  server.alerts = [
    { id: "a1", symbol: "NBIS", price: 92.46, created_on: "2026-10-24", condition: "crosses", interval: null, session: "regular", direction: "down",
      source_kind: "copilot", source_id: INV, label: "NBIS 2% below the last price", state: "fired", armed_at: 1,
      event: { level: 92.46, price: 92.4, source: "stream", event_at: 1792857000, detected_at: 1792857001, delivery: "sent", attempts: 1, delivered_at: 1792857002, error: null } },
    { id: "a2", symbol: "SPY", price: 600, created_on: "2026-10-24", condition: "touches", interval: null, session: "regular", direction: "up",
      source_kind: "level", source_id: "lvl", label: "Charts level", state: "active", armed_at: 1, event: null },
  ];
  await lab(page, server, { url: `/copilot-lab?investigation=${INV}` });
  await expect(page.getByText("Make a plan for NBIS").first()).toBeVisible(); // the breadcrumb names it too
  const linked = await timeline(page);
  await expect(linked).toContainText("Alert hit");
  await expect(linked).toContainText("at 92.4");
});
