import { expect, test, type Page, type Route } from "@playwright/test";

// The trade origin chain (docs/copilot-lab.md § Origin): Radar's Plan a trade carries the event id into the lab, the
// confirmed plan card sends it with the capture, and the trade page names where the plan came from. The lab's routes
// are stubbed in the browser (a fixed SSE turn, no model); the Radar event and the trade come from the e2e backend.
const API = `http://127.0.0.1:${Number(process.env.E2E_BACKEND_PORT || 8099)}`;
const INV = "55555555-5555-4555-8555-555555555555";
const ROTH = "00000000-0000-0000-0000-000000000001";
const STATUS = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: false },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const record = {
  id: INV, source: "copilot", title: "Plan a trade: MU", symbol: "MU", status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-26T14:41:00Z", updated_at: "2026-10-26T14:41:00Z",
  transcript: [{ role: "user", content: "Plan a trade: MU" }, { role: "assistant", content: "MU plan (draft)." }], evidence: [], findings: null,
};
const PLAN = { id: "p1", kind: "trade_plan", symbol: "MU", direction: "long", instrument: "stock", contract: null,
  thesis: "MU leads its group on the day; the move holds above the morning high.",
  entry_trigger: { condition: "closes_beyond", price: 101, interval: "5m" }, invalidation: { condition: "crosses", price: 98, interval: null },
  time_stop: null, size_note: "one starter", last: 100, as_of: "2026-10-26T14:41:00Z" };
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const TURN = sse([
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...PLAN },
  { type: "text", delta: "MU plan (draft). Nothing is saved or armed until you confirm it." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

async function lab(page: Page, captures: Record<string, unknown>[]) {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: STATUS }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: record }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: route.request().method() === "PUT" ? { ...record, revision: 2 } : record }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "MU", last: 100, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: {
    accounts: [{ id: ROTH, label: "Roth IRA", broker: "robinhood" }], default_account_id: ROTH, templates: [], max_templates: 3,
    transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", (route: Route) => {
    const body = route.request().postDataJSON();
    captures.push(body);
    return route.fulfill({ status: 201, json: { id: "c1", ...body } });
  });
}

test("a Radar event's plan carries the event to the plan and the trade page names it, at 375 px", async ({ page, request }) => {
  expect((await request.post(`${API}/__test/radar-seed`)).ok()).toBeTruthy();
  const captures: Record<string, unknown>[] = [];
  await lab(page, captures);
  await page.setViewportSize({ width: 375, height: 812 });

  // Radar: the event detail's Plan a trade names the event as the origin.
  await page.goto("/radar");
  await page.getByRole("region", { name: "New since your last visit" }).getByTestId("radar-event").getByRole("button").first().click();
  const link = page.getByTestId("radar-event").getByRole("link", { name: "Plan a trade" });
  const href = (await link.getAttribute("href"))!;
  const query = new URLSearchParams(href.split("?")[1]);
  const [kind, eventId] = query.get("origin")!.split(/:(.*)/);
  expect(kind).toBe("radar_event");
  expect(eventId.length).toBeGreaterThan(0);
  const context = query.get("context")!;
  expect(context).toMatch(/^Plan a trade: Radar .+: MU /);
  await expect(page.getByLabel("Plan marks")).toHaveCount(0); // no plan names it yet

  // The lab keeps it, and the confirmed plan card sends it with the capture.
  await link.click();
  await expect(page).toHaveURL(/\/copilot-lab\?.*origin=radar_event/);
  await page.getByRole("button", { name: "Send" }).click();
  const card = page.getByRole("region", { name: "Proposed trade plan" });
  await expect(card).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("list", { name: "Plan results" })).toContainText("Pre-trade plan: done");
  expect(captures).toHaveLength(1);
  expect(captures[0].origin).toEqual({ kind: "radar_event", ref: eventId, text: context });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);

  // The trade page: the linked plan says where it came from, and links back to the event.
  const trades = await (await page.request.get("/api/backend/trades")).json() as { id: string; ticker: string }[];
  const trade = trades[0];
  const saved = { ...captures[0], id: "c1", received_at: 1790000000, client_captured_at: null, account_label: "Roth IRA", instrument: "stock",
    template_id: null, template_revision: null, strike: null, expiration: null, quantity: null, context_state: "unavailable",
    image: { state: "unavailable", note: null, bytes: null }, audio: null, transcript: null, not_taken_at: null, notes: [], link: null,
    origin: { kind: "radar_event", ref: eventId, text: context } };
  await page.route(`**/charts/captures/for-trade/${trade.id}`, (route) => route.fulfill({ json: { captures: [saved] } }));
  await page.goto(`/trades/${trade.id}`);
  const from = page.getByRole("region", { name: "Pre-trade plan" }).getByLabel("Plan origin");
  await expect(from).toContainText(/^From: Radar event, MU .+[^.], \d.+$/);
  await expect(from.getByRole("link")).toHaveAttribute("href", `/radar?event=${encodeURIComponent(eventId)}`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.getByRole("region", { name: "Pre-trade plan" }).screenshot({ path: test.info().outputPath("trade-origin-375.png") });

  // Back on Radar, the event shows the marks the backend reads from plans that name it (here, the stored plan's link stands in).
  await page.route(`**/radar/events/${encodeURIComponent(eventId)}`, async (route) => {
    const detail = await (await route.fetch()).json();
    expect(detail.plans).toEqual({ planned: false, traded: false }); // the e2e backend holds no plan naming it
    return route.fulfill({ json: { ...detail, plans: { planned: true, traded: true } } });
  });
  await page.goto(`/radar?event=${encodeURIComponent(eventId)}`);
  const marks = page.getByLabel("Plan marks");
  await expect(marks).toHaveText("PlannedTraded");
  await marks.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.getByTestId("radar-event").filter({ has: marks }).screenshot({ path: test.info().outputPath("radar-marks-375.png") });
});
