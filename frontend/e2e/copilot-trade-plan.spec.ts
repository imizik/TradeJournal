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
// The turn's get_level_history result for the drafted invalidation: the owner's own past trades at that distance, shown under the field.
const HISTORY = { symbol: "NBIS", level: 92.3, side: "below", entry: 95.9, distance_pct: -3.75, trades: 31, crossed: 12, recovered: 5, median_from_cross_pct: -18, small: false, simulated: false };
const TURN = sse([
  { type: "tool", id: "h1", name: "get_level_history", status: "ok", summary: "12 of 31 past NBIS trades crossed -3.8% while held", ms: 1,
    input: { symbol: "NBIS", level: 92.3, side: "below", entry: 95.9, lookback_days: 180 }, provenance: { source: "Journal closed trades", kind: "saved", as_of: null }, history: HISTORY },
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...PLAN },
  { type: "text", delta: "NBIS plan (draft). Nothing is saved or armed until you confirm it." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

type Server = { alerts: object[]; posts: { path: string; body: Record<string, unknown> }[]; failAlert?: (body: Record<string, unknown>) => boolean;
  failCapture?: boolean; last?: number; stops?: object[]; reads?: Record<string, object>; lastExit?: object | null; loopReads?: string[]; setup?: object };
// The server's reading of a time stop; anything not listed stays a note.
const DUE = Date.UTC(2026, 9, 24, 19, 30) / 1000;
const READ = (server: Server, text: string) => server.reads?.[text] ?? { due_at: null, reason: "No time or length in it, so it stays a note.", enabled: true };

async function lab(page: Page, server: Server, { alertsSupported = true, defaultAccount = ROTH as string | null } = {}) {
  const post = (path: string, route: Route) => server.posts.push({ path, body: route.request().postDataJSON() });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: status(alertsSupported) }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: record }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: route.request().method() === "PUT" ? { ...record, revision: 2 } : record }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: true, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: server.last ?? 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: {
    accounts: [{ id: ROTH, label: "Roth IRA ··8267", broker: "robinhood" }, { id: "00000000-0000-0000-0000-000000000002", label: "Individual", broker: "robinhood" }],
    default_account_id: defaultAccount, templates: [], max_templates: 3, transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", (route) => {
    post("captures", route);
    if (server.failCapture) return route.fulfill({ status: 503, json: { detail: "The database is busy." } });
    return route.fulfill({ status: 201, json: { id: "c1", ...route.request().postDataJSON() } });
  });
  // A Confirm saves the plan's horizon as a day-journal entry (how often the desk checks in after the close).
  await page.route("**/day-journal/*/entries", (route) => {
    post("journal", route);
    return route.fulfill({ json: { id: "j1", day: "2026-10-24", not_traded: false, actor: "owner", created_at: "2026-10-24T14:01:00Z", ...route.request().postDataJSON() } });
  });
  // The draft's last exit lesson for its symbol (GET /copilot/symbol/{symbol}'s last_exit; tests/test_copilot_symbol.py).
  await page.route("**/copilot/symbol/*", (route) => {
    server.loopReads?.push(new URL(route.request().url()).pathname);
    return route.fulfill({ json: { symbol: "NBIS", as_of: "2026-10-24T14:00:00Z", positions: { state: "ok", rows: [] }, plans: { state: "ok", rows: [] },
      last_exit: { state: "ok", lesson: server.lastExit ?? null }, ...(server.setup ? { setup: { state: "ok", ...server.setup } } : {}), new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } }, quotes_at: null, quote_issue: null } });
  });
  await page.route("**/copilot/time-stops/preview?*", (route) =>
    route.fulfill({ json: READ(server, new URL(route.request().url()).searchParams.get("text") ?? "") }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: server.stops ?? [], enabled: false } }));
  await page.route("**/copilot/time-stops", (route) => {
    post("time-stops", route);
    const body = route.request().postDataJSON();
    server.stops = [{ id: "t1", symbol: body.symbol, text: body.text, due_at: DUE, delivery: "scheduled", trade_id: null, error: null, delivered_at: null }];
    return route.fulfill({ status: 201, json: { time_stops: server.stops, enabled: false } });
  });
  await page.route("**/charts/alerts", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: { alerts: server.alerts, phone: true } });
    post("alerts", route);
    const body = route.request().postDataJSON();
    if (server.failAlert?.(body)) return route.fulfill({ status: 422, json: { detail: "Up to 20 active alerts. Remove one first." } });
    server.alerts = [...server.alerts, { id: `a${server.alerts.length + 1}`, created_on: "2026-10-24", direction: "up", state: "active", armed_at: 1, event: null, ...body }];
    return route.fulfill({ json: { alerts: server.alerts, phone: true } });
  });
  // The desk's Context pane reads the thread's timeline from the server; this one answers from the alerts and time
  // stops above, as GET /copilot/desk/{id}/timeline would (its composition is tests/test_copilot_desk_context.py).
  await page.route(`**/copilot/desk/${INV}/timeline`, (route) => {
    type Alert = { price: number; condition: string; label: string; plan_role: "entry" | "invalidation" | null; state: string; event: { price: number; event_at: number } | null };
    type Stop = { text: string; delivery: string; error: string | null };
    const name = (a: Alert) => a.plan_role === "entry" ? "Entry" : a.plan_role === "invalidation" ? "Invalidation" : "Alert";
    const rows = [
      ...(server.alerts as Alert[]).map((a) => a.state === "active"
        ? { kind: "alert", at: DUE - 5 * 3600, text: `${name(a)} armed`, detail: `${a.condition.replace("_", " ")} ${a.price} · ${a.label}` }
        : { kind: "alert", at: a.event!.event_at, text: `${name(a)} hit`, detail: `at ${a.event!.price} · pinged` }),
      ...((server.stops ?? []) as Stop[]).map((t) => t.delivery === "scheduled"
        ? { kind: "time_stop", at: DUE - 5 * 3600, text: "Time stop set for 15:30", detail: `${t.text} · time-stop pings are off on this server` }
        : { kind: "time_stop", at: DUE, text: `Time stop ${t.delivery === "sent" ? "pinged" : t.delivery}`, detail: t.error ?? t.text }),
    ];
    return route.fulfill({ json: { state: "ok", symbol: "NBIS", unavailable: [], recent_days: 7, count: rows.length, rows } });
  });
  await page.goto("/copilot-lab");
}

/** The Context pane's Timeline tab, opened. */
async function timeline(page: Page) {
  const pane = page.getByRole("complementary", { name: "Context" });
  await pane.getByRole("tab", { name: "Timeline" }).click();
  return pane.getByRole("list", { name: "Timeline" });
}

async function askForPlan(page: Page) {
  await page.getByLabel("Message").fill("Plan a trade: yolo NBIS calls");
  await page.getByRole("button", { name: "Send" }).click();
  // This turn's answer, not the saved "NBIS plan (draft)." a reload may reopen above it.
  await expect(page.getByText("NBIS plan (draft). Nothing is saved or armed until you confirm it.").last()).toBeVisible();
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

  // The owner's own history at the drafted invalidation, from the turn's evidence: counts and a link, never a rule.
  const history = card.getByLabel("Your history at this level");
  await expect(history).toHaveText("Your history at this level: 12 of 31 past NBIS trades crossed −3.8% while held; 5 recovered; median −18% from there. why this is evidence, not a rule");
  const why = history.getByRole("link", { name: "why this is evidence, not a rule" });
  await expect(why).toHaveAttribute("href", /invalidation_study_2026-10-25\.md#defaults-the-copilot-could-suggest--approval-only$/);
  await expect(why).toHaveAttribute("target", "_blank");
  const sources = page.getByTestId("copilot-sources").last();
  await sources.locator("summary").click(); // the answer's sources, folded into one line
  await expect(sources.getByText("Your history here · saved")).toBeVisible();

  // An edited level is not refetched on every keystroke: the line asks for a fresh turn instead. The distance was
  // measured from the drafted entry, so an edited entry stales it too.
  await card.getByLabel("Entry (5m close beyond)").fill("97");
  await expect(history).toHaveText("Your history at this level: you changed the levels; re-ask the copilot to refresh it.");
  await card.getByLabel("Entry (5m close beyond)").fill("95.9");
  await expect(history).toContainText("12 of 31 past NBIS trades");
  await card.getByLabel("Invalidation (crosses)").fill("96");
  await expect(history).toHaveText("Your history at this level: you changed the levels; re-ask the copilot to refresh it.");
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
    origin: { kind: "copilot", ref: INV, text: null }, // the lab's own conversation, by its investigation
  });
  expect(typeof capture.client_id).toBe("string");
  expect(posts(server, "alerts")).toEqual([
    { symbol: "NBIS", price: 95.9, reference: 94.35, condition: "closes_beyond", interval: "5m", session: "regular",
      source_kind: "copilot", source_id: INV, label: "NBIS entry: 5m close beyond 95.9", plan_role: "entry" },
    { symbol: "NBIS", price: 92.1, reference: 94.35, condition: "crosses", interval: null, session: "regular",
      source_kind: "copilot", source_id: INV, label: "NBIS invalidation: crosses 92.1", plan_role: "invalidation" },
  ]);
  expect(posts(server, "time-stops")).toEqual([]); // a time stop the server does not read as a time stays a note
  await expect(card.getByLabel("Thesis")).toBeDisabled(); // the saved plan is what the card shows now
  await expect(await timeline(page)).toContainText("NBIS invalidation: crosses 92.1");
});

test("a draft shows the symbol's last exit lesson in the owner's words, and a confirmed card does not", async ({ page }) => {
  const lesson = "No, sold the give-back too early; hold to the time stop next time.";
  const server: Server = { alerts: [], posts: [], lastExit: { exited: "2026-10-21", followed: "no", lesson }, loopReads: [] };
  await lab(page, server);
  const card = await askForPlan(page);
  const line = card.getByLabel("Last NBIS exit lesson");
  await expect(line).toHaveText(`Last NBIS exit (Oct 21): didn't follow · “${lesson}”`);
  expect(server.loopReads).toEqual([expect.stringMatching(/\/copilot\/symbol\/NBIS$/)]);
  await page.screenshot({ path: test.info().outputPath("plan-card-last-exit-1440.png") });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Set: NBIS crosses 92.3.")).toBeVisible();
  await expect(line).toBeHidden();
});

test("a draft for a symbol with no answered exit review shows no lesson line", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  const card = await askForPlan(page);
  await expect(card.getByLabel("Invalidation (crosses)")).toHaveValue("92.3");
  await expect(card.getByLabel("Last NBIS exit lesson")).toHaveCount(0);
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

test("a failed plan save arms nothing until its retry succeeds", async ({ page }) => {
  const server: Server = { alerts: [], posts: [], failCapture: true };
  await lab(page, server);
  const card = await askForPlan(page);
  await card.getByRole("button", { name: "Confirm" }).click();
  const results = card.getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Pre-trade plan: failed");
  await expect(results).toContainText("The database is busy.");
  await expect(results).toContainText("Entry alert: waits for the plan");
  expect(posts(server, "alerts")).toEqual([]);
  server.failCapture = false;
  await card.getByRole("button", { name: "Retry pre-trade plan" }).click();
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  expect(posts(server, "alerts")).toHaveLength(2);
});

test("an invalidation already crossed by Confirm is not armed on the wrong side", async ({ page }) => {
  const server: Server = { alerts: [], posts: [], last: 92.0 };
  await lab(page, server);
  const card = await askForPlan(page);
  await card.getByRole("button", { name: "Confirm" }).click();
  const results = card.getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Invalidation alert: failed");
  await expect(results).toContainText("NBIS is at 92, already past the invalidation at 92.3, so it was not set.");
  expect(posts(server, "alerts").map((b) => b.label)).toEqual(["NBIS entry: 5m close beyond 95.9"]);
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
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click(); // a phone shows the conversation on its own tab
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

test("a time stop read as a time is previewed before Confirm and set as a timed ping; other words stay a note", async ({ page }) => {
  const server: Server = { alerts: [], posts: [], reads: {
    "out by 15:30 if the entry has not worked": { due_at: DUE, when: "today 15:30 ET", enabled: false },
    "2 days": { due_at: DUE + 2 * 86400, when: "Mon Oct 26, 15:30 ET", enabled: false } } };
  await page.clock.install({ time: new Date("2026-10-24T14:00:00Z") }); // the plan's day, so "today 15:30" is today
  await lab(page, server);
  const card = await askForPlan(page);
  const reading = card.getByLabel("When it pings");
  const horizon = card.getByRole("combobox", { name: "Horizon" });
  await expect(reading).toHaveText("Pings today 15:30 ET if you hold NBIS then, from an entry after this plan. Time-stop pings are off on this server for now.");
  await expect(horizon).toHaveValue("day"); // a time stop due today makes it a day trade
  await card.getByLabel("Time stop").fill("when it feels wrong");
  await expect(reading).toHaveText("Kept as a note: No time or length in it, so it stays a note.");
  await card.getByLabel("Time stop").fill("2 days");
  await expect(reading).toContainText("Pings Mon Oct 26, 15:30 ET if you hold NBIS then");
  await expect(horizon).toHaveValue("swing"); // a number of days: a swing
  await card.screenshot({ path: test.info().outputPath("time-stop-preview.png") });
  expect(server.posts).toEqual([]); // reading the words saves nothing
  await horizon.selectOption("long");
  await expect(card).toContainText("No daily question; Review my week looks at it.");

  await card.getByRole("button", { name: "Confirm" }).click();
  const results = card.getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Time stop: done");
  await expect(results).toContainText("Set for Mon Oct 26, 15:30 ET.");
  await expect(card.getByRole("status")).toHaveText("Plan confirmed.");
  const [stop] = posts(server, "time-stops");
  expect(stop).toMatchObject({ investigation_id: INV, symbol: "NBIS", text: "2 days" });
  expect(stop.client_id).toBe(posts(server, "captures")[0].client_id); // one card, one plan, one time stop
  expect(posts(server, "captures")[0].wording).toContain("Time stop: 2 days.");
  expect(posts(server, "journal")).toEqual([expect.objectContaining({ kind: "horizon", symbol: "NBIS", text: "Long hold" })]);

  const linked = await timeline(page);
  await expect(linked).toContainText("Entry armed");
  await expect(linked).toContainText("Invalidation armed");
  await expect(linked).toContainText("Time stop set for 15:30");
  await expect(linked).toContainText("time-stop pings are off on this server");
});

test("a plan alert's link opens its investigation with the question ready, and the linked activity shows what fired", async ({ page }) => {
  const fired = { level: 95.9, price: 95.93, source: "stream", event_at: DUE - 4 * 3600, detected_at: DUE - 4 * 3600, delivery: "sent", attempts: 1, delivered_at: DUE - 4 * 3600, error: null };
  const plan = { symbol: "NBIS", created_on: "2026-10-24", session: "regular", source_kind: "copilot", source_id: INV, armed_at: 1, interval: null };
  const server: Server = { alerts: [
    { ...plan, id: "a1", price: 95.9, condition: "crosses", direction: "up", label: "NBIS entry: crosses 95.9", plan_role: "entry", state: "fired", event: fired },
    { ...plan, id: "a2", price: 92.3, condition: "crosses", direction: "down", label: "NBIS invalidation: crosses 92.3", plan_role: "invalidation", state: "active", event: null },
    { ...plan, id: "a3", price: 97, condition: "touches", direction: "up", label: "Copilot watch", plan_role: null, state: "active", event: null },
  ], posts: [], stops: [
    { id: "t1", symbol: "NBIS", text: "out by 15:30", due_at: DUE, delivery: "sent", trade_id: "t", error: null, delivered_at: DUE },
    { id: "t2", symbol: "NBIS", text: "2 days", due_at: DUE, delivery: "skipped", trade_id: null, error: "No open NBIS position opened after the plan, so nothing was sent.", delivered_at: null },
  ] };
  const chats: string[] = [];
  page.on("request", (request) => { if (request.url().endsWith("/copilot/chat")) chats.push(request.url()); });
  await lab(page, server);
  const ask = "My entry trigger hit at 95.90 (10:41). Is the plan still valid? Check the chart and group now.";
  await page.goto(`/copilot-lab?investigation=${INV}&context=${encodeURIComponent(ask)}`);
  await expect(page.getByText("NBIS plan (draft).")).toBeVisible();
  await expect(page.getByLabel("Message")).toHaveValue(ask);
  const linked = await timeline(page);
  await expect(linked).toContainText("Entry hit");
  await expect(linked).toContainText("at 95.93");
  await expect(linked).toContainText("Invalidation armed");
  await expect(linked).toContainText("Alert armed"); // a plain copilot watch keeps its own wording
  await expect(linked).toContainText("Time stop pinged");
  await expect(linked).toContainText("Time stop skipped");
  await expect(linked).toContainText("No open NBIS position opened after the plan, so nothing was sent.");
  await linked.screenshot({ path: test.info().outputPath("plan-linked-activity.png") });
  await page.waitForTimeout(300);
  expect(chats).toEqual([]); // the question waits: a turn costs money
});

test("option candidates are an evidence row and a pick list for the plan's contract beside the drafted wording", async ({ page }) => {
  const candidates = { symbol: "NBIS", direction: "long", simulated: false, picks: [
    { label: "Nov 6 '26 95C", days: 14, ask_contract: 565 }, { label: "Nov 13 '26 95C", days: 21, ask_contract: 692 },
    { label: "Nov 20 '26 95C", days: 28, ask_contract: 799 }] };
  const turn = sse([
    { type: "tool", id: "o1", name: "get_option_candidates", status: "ok", summary: "8 calls across 3 expiries for a 21-day horizon", ms: 1,
      input: { symbol: "NBIS", horizon_days: 21, direction: "long" },
      provenance: { source: "Tradier option chains (Charts options feed cache)", kind: "fetched", as_of: "2026-10-24T14:00:00Z" }, candidates },
    { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
    { type: "proposal", ...PLAN },
    { type: "text", delta: "NBIS plan (draft). Nothing is saved or armed until you confirm it." },
    { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
      tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
  ]);
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turn }));
  const card = await askForPlan(page);
  const sources = page.getByTestId("copilot-sources").last();
  await sources.locator("summary").click(); // the answer's sources, folded into one line
  await expect(sources.getByText("Option candidates · fetched")).toBeVisible();

  const contract = card.getByLabel("Contract");
  await expect(contract).toHaveValue("Nov 21 100C"); // the copilot's wording stays the default
  await expect(contract.locator("option")).toHaveText(["Nov 21 100C (as drafted)", "Nov 6 '26 95C · 14d · $565 ask",
    "Nov 13 '26 95C · 21d · $692 ask", "Nov 20 '26 95C · 28d · $799 ask"]);
  await expect(card).toContainText("From the option chain: trade-offs to weigh, not a recommendation.");
  await contract.selectOption("Nov 13 '26 95C");
  await expect(card).toContainText("Proposed trade plan · NBIS · Buy calls · Nov 13 '26 95C");
  await card.screenshot({ path: test.info().outputPath("plan-contract-picks.png") });
  expect(server.posts).toEqual([]); // picking saves nothing
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("list", { name: "Plan results" })).toContainText("Pre-trade plan: done");
  const [capture] = posts(server, "captures");
  expect(capture.note).toBe("Thesis: NBIS reclaims the level overhead with its group, so the bounce has room. Contract: Nov 13 '26 95C. From a Copilot Lab plan card.");
});

test("without option candidates the plan card shows no contract pick list", async ({ page }) => {
  await lab(page, { alerts: [], posts: [] });
  const card = await askForPlan(page);
  await expect(card.getByLabel("Contract")).toHaveCount(0);
});

// Size it for me: the turn's option candidates carry each contract's ask and, when the chain gives one, its delta.
const SIZED = { symbol: "NBIS", direction: "long", simulated: false, as_of: "2026-10-24T14:00:00Z", picks: [
  { label: "Nov 6 '26 95C", days: 14, ask_contract: 565, ask: 5.65, delta: null },
  { label: "Nov 13 '26 95C", days: 21, ask_contract: 692, ask: 6.92, delta: 0.45 }] };
const turnWith = (plan: object, candidates: object | null) => sse([
  ...(candidates ? [{ type: "tool", id: "o1", name: "get_option_candidates", status: "ok", summary: "2 calls", ms: 1,
    input: { symbol: "NBIS", horizon_days: 21, direction: "long" },
    provenance: { source: "Tradier option chains (Charts options feed cache)", kind: "fetched", as_of: "2026-10-24T14:00:00Z" }, candidates }] : []),
  { type: "tool", id: "p1", name: "propose_plan", status: "ok", summary: "proposed plan", ms: 1, provenance: { source: "proposal", kind: "proposal", as_of: null } },
  { type: "proposal", ...plan },
  { type: "text", delta: "NBIS plan (draft). Nothing is saved or armed until you confirm it." },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);

test("size it for me: a risk becomes a contract count at the chosen contract's ask, written in front of the size note", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turnWith(PLAN, SIZED) }));
  const card = await askForPlan(page);
  const sizing = card.getByLabel("Size it for me");
  await expect(sizing).toHaveCount(0); // blank until the owner types a risk
  await expect(card.getByLabel("Risk $")).toHaveAttribute("inputmode", "decimal");
  await card.getByLabel("Risk $").fill("700");
  // The drafted contract has no premium from the chain: the card says how to pick one, never a guess.
  await expect(sizing).toHaveText("Nov 21 100C has no premium from the option chain here: choose a contract from the Contract list to size it.");

  await card.getByLabel("Contract").selectOption("Nov 6 '26 95C");
  await expect(sizing).toContainText("Max loss: 1 contract, $565 of premium, all of it at risk.");
  await expect(sizing).toContainText("At invalidation: the chain gives no delta, so there is no estimate.");
  await card.getByLabel("Contract").selectOption("Nov 13 '26 95C");
  await expect(sizing).toContainText("Max loss: 1 contract, $692 of premium, all of it at risk.");
  // 0.45 × (95.90 − 92.30) × 100 = $162 a contract at the invalidation; 700 ÷ 162 rounds down to 4.
  await expect(sizing).toContainText("At invalidation: about 4 contracts, each losing about $162 if NBIS reaches 92.30 (delta 0.45); the premium is still all at risk past it.");
  await expect(sizing).toContainText("Priced at the 6.92 ask ($692 a contract) from the option chain read at 10:00 AM ET.");
  await expect(sizing).toContainText("Confirm puts this size in front of the size note.");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click(); // a phone shows the conversation on its own tab
  await card.screenshot({ path: test.info().outputPath("plan-size-it.png") });
  await card.getByLabel("Risk $").fill("500");
  await expect(sizing).toContainText("Max loss: $500 does not buy one contract at the $692 ask.");
  await card.getByLabel("Risk $").fill("1400");
  await expect(sizing).toContainText("Max loss: 2 contracts, $1,384 of premium, all of it at risk.");
  expect(server.posts).toEqual([]); // sizing saves nothing

  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("list", { name: "Plan results" })).toContainText("Pre-trade plan: done");
  const [capture] = posts(server, "captures");
  expect(capture.wording).toBe("Entry: 5m close beyond 95.9. Invalidation: crosses 92.3. Time stop: out by 15:30 if the entry has not worked. "
    + "Size: 2 contracts of Nov 13 '26 95C at 6.92, $1,384 max loss, risk $1,400; one starter, no adds.");

  // The risk is remembered in this browser for the next card.
  await page.reload();
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turnWith(PLAN, null) }));
  await page.getByRole("tablist", { name: "Desk" }).getByRole("tab").nth(1).click(); // still a phone after the reload
  const next = await askForPlan(page);
  await expect(next.getByLabel("Risk $")).toHaveValue("1400");
  await expect(next.getByLabel("Size it for me")).toHaveText(
    "No option premiums in this conversation yet: ask the copilot which strike and expiry, then choose a contract from its list to size it.");
});

test("size it for me on a stock plan: shares from the invalidation distance, cost at the fresh quote; a hand-edited note is kept", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await lab(page, server);
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" },
    body: turnWith({ ...PLAN, instrument: "stock", contract: null }, null) }));
  const card = await askForPlan(page);
  // A long note written before sizing is cut to keep 120 characters, and the card says so before Confirm.
  await card.getByLabel("Size", { exact: true }).fill("x".repeat(100));
  await card.getByLabel("Risk $").fill("150");
  await expect(card.getByLabel("Size it for me")).toContainText("Confirm puts this size in front of the size note, which is cut to fit 120 characters.");
  // 150 ÷ (95.90 − 92.30) = 41.7, rounded down to 41 shares: $147.60 (shown $148) at risk, $3,868 at the 94.35 quote.
  const sizing = card.getByLabel("Size it for me");
  await expect(sizing).toContainText("41 shares: $148 lost if it reaches the 92.30 invalidation (3.60 a share).");
  await expect(sizing).toContainText("$3,868 at the 94.35 quote (2s old).");
  await card.getByLabel("Risk $").fill("3");
  await expect(sizing).toContainText("$3 does not cover one share: it is 3.60 a share to the 92.30 invalidation.");
  await card.getByLabel("Invalidation (crosses)").fill("97");
  await expect(sizing).toHaveText("Size needs an invalidation on the losing side of the entry.");
  await card.getByLabel("Invalidation (crosses)").fill("92.3");
  await card.getByLabel("Risk $").fill("150");
  await card.getByLabel("Size", { exact: true }).fill("half size, earnings week");
  await expect(sizing).toContainText("Your size note is kept as you wrote it.");
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByRole("list", { name: "Plan results" })).toContainText("Pre-trade plan: done");
  const [capture] = posts(server, "captures");
  expect(capture.wording).toContain("Size: half size, earnings week.");
});

// Jo's red team (GET/POST /copilot/plans/{id}/red-team, tests/test_jo_research.py): a pending request, then Jo's answer.
async function redTeam(page: Page, answered: boolean) {
  const asked: object[] = [];
  const pending = { request_id: "r1", proposal_id: "p1", symbol: "NBIS", status: "pending", requested_at: "2026-10-24T14:02:00Z", answered_at: null, answer: null };
  await page.route(`**/copilot/plans/${INV}/red-team`, (route) => {
    if (route.request().method() === "POST") {
      asked.push(route.request().postDataJSON());
      return route.fulfill({ status: 201, json: pending });
    }
    return route.fulfill({ json: { requests: answered ? [{ ...pending, status: "answered", answered_at: "2026-10-24T23:10:00Z",
      answer: { investigation_id: "j1", title: "Dilution risk is underpriced", body: "A secondary is likely after the run.\n\nDetails.",
        citations: [{ url: "https://www.reuters.com/x", publisher: "Reuters", published_at: "2026-10-24" }] } }] : [] } });
  });
  return asked;
}

test("a confirmed plan asks Jo to argue against it and then waits for Jo's run", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  const asked = await redTeam(page, false);
  await lab(page, server);
  const card = await askForPlan(page);
  await expect(card.getByRole("button", { name: "Ask Jo to argue against this" })).toBeHidden(); // a draft has no button
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Plan confirmed.")).toBeVisible();
  await card.getByRole("button", { name: "Ask Jo to argue against this" }).click();
  await expect(card.getByText("Waiting for Jo: it answers in its next research run, outside market hours.")).toBeVisible();
  expect(asked).toEqual([{ proposal_id: "p1" }]);
});

test("Jo's answer shows on the confirmed plan card, folded until opened", async ({ page }) => {
  const server: Server = { alerts: [], posts: [] };
  await redTeam(page, true);
  await lab(page, server);
  const card = await askForPlan(page);
  await card.getByRole("button", { name: "Confirm" }).click();
  const against = card.getByRole("group", { name: "Jo's case against" });
  await expect(against.locator("summary")).toHaveText("Jo's case against: Dilution risk is underpriced");
  await expect(against.getByText("A secondary is likely after the run.", { exact: false })).toBeHidden();
  await against.locator("summary").click();
  await expect(against.getByText("A secondary is likely after the run.", { exact: false })).toBeVisible();
  await expect(against.getByRole("link", { name: "Reuters" })).toHaveAttribute("href", "https://www.reuters.com/x");
  await page.screenshot({ path: test.info().outputPath("plan-card-jo-case-against.png") });
});

// The owner's record for an option plan's setup today (GET /copilot/symbol/{symbol}'s setup; tests/test_setup_record.py).
const SETUP = { gap_pct: -2.4, vs_sma_pct: -3.1,
  calls: { gap: { relation: "against", record: { trades: 12, won: 8, pnl: 1240 } }, trend: { relation: "against", record: { trades: 20, won: 11, pnl: 860 } } },
  puts: { gap: { relation: "with", record: { trades: 9, won: 3, pnl: -700 } }, trend: { relation: "with", record: null } },
  size: { usual: 500, top_quarter_from: 1000, top_quarter: { trades: 15, won: 9, pnl: -310 } } };

test("a draft option plan shows the owner's record for its setup, and its premium against the usual once sized", async ({ page }) => {
  const server: Server = { alerts: [], posts: [], setup: SETUP };
  await lab(page, server);
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: turnWith(PLAN, SIZED) }));
  const card = await askForPlan(page);
  const record = card.getByLabel("Your record for this NBIS setup");
  await expect(record.locator("p")).toHaveText([
    "Gap −2.4%. Your opening calls bought against a gap down of 1%+: 12 trades, 67% won, +$1,240.",
    "NBIS is 3.1% below its 20-day average. Your opening calls bought below it: 20 trades, 55% won, +$860.",
  ]);
  await card.getByLabel("Contract").selectOption("Nov 13 '26 95C");
  await card.getByLabel("Risk $").fill("1400");
  // The size line sits with the sizing lines, where the risk is typed.
  await expect(card.getByLabel("Size it for me")).toContainText(
    "This plan: $1,384 of premium, 2.8× your usual $500. Your opening option trades of $1,000+: 15 trades, 60% won, −$310.");
  await card.getByLabel("Contract").selectOption("Nov 6 '26 95C");
  await card.getByLabel("Risk $").fill("600");
  await expect(card.getByLabel("Size it for me")).toContainText("This plan: $565 of premium, 1.1× your usual $500.");
  await expect(card.getByLabel("Size it for me")).not.toContainText("Your opening option trades of");
  await record.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("plan-card-setup-record-1440.png") });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Set: NBIS crosses 92.3.")).toBeVisible();
  await expect(record).toBeHidden(); // a confirmed card no longer shows it
});

test("a thin or unknown setup shows no record lines", async ({ page }) => {
  const thin = { ...SETUP, calls: { gap: { relation: "small", record: null }, trend: null }, size: null };
  const server: Server = { alerts: [], posts: [], setup: thin };
  await lab(page, server);
  const card = await askForPlan(page);
  await expect(card.getByLabel("Invalidation (crosses)")).toHaveValue("92.3");
  await expect(card.getByLabel("Your record for this NBIS setup")).toHaveCount(0);
});
