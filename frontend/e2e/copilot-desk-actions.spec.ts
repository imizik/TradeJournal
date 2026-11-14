import { expect, test, type Page, type Route } from "@playwright/test";

// The copilot acting on the desk (docs/copilot-lab.md § Desk actions): an answer carries desk_action cards. A view change
// (a ticker, a timeframe, the Chain) applies itself with Undo; every other card waits for the tap, which calls the desk's
// own route (the chart's alerts, the Watching list, the chart settings' levels, the Ticket tab, a plan's stop alert); a
// card a day old or whose price or plan has moved says so and asks again instead of acting.
// Every lab route is stubbed in the browser (the e2e backend runs with the lab off): no model, no order, no Robinhood.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const MADE = Date.parse("2026-11-13T15:59:00Z") / 1000;
const epoch = (iso: string) => Date.parse(iso) / 1000;
const MAIN = "77777777-7777-4777-8777-777777777777";
const PLAN = "11111111-1111-4111-8111-111111111111";
const STOP = "33333333-3333-4333-8333-333333333333";
const THREADS = { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" }, symbol: null, instrument: null,
    value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null }] };
const SESSION = { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: 0, sections: {} };
const main = (fields: Record<string, unknown> = {}) => ({ id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null,
  revision: 1, message_count: 0, has_findings: false, created_at: "2026-11-13T14:00:00Z", updated_at: "2026-11-13T15:00:00Z", evidence: [],
  findings: null, transcript: [], main_day: "2026-11-13", ...fields });

const card = (id: string, fields: Record<string, unknown>) => ({ type: "proposal", id, kind: "desk_action", made_at: MADE, ...fields });
const SHOW = card("a_show", { action: "show", symbol: "NBIS", timeframe: "15m", tab: "chart" });
const ALERT = card("a_alert", { action: "alert", symbol: "NBIS", price: 98, side: "below", label: null, last: 101.2, as_of: MADE });
const WATCH = card("a_watch", { action: "watch", symbol: "IREN" });
const DRAW = card("a_draw", { action: "draw", symbol: "NBIS", price: 102.5, label: "resistance", last: 101.2, as_of: MADE });
const TICKET = card("a_ticket", { action: "ticket", symbol: "NBIS", strike: 100, option_type: "call", expiry: "2026-12-18", investigation_id: PLAN });
const PLAN_STOP = card("a_stop", { action: "plan_stop", symbol: "NBIS", price: 96, was: 92.3, investigation_id: PLAN, alert_id: STOP,
  direction: "long", last: 101.2, as_of: MADE });
const sse = (cards: unknown[], text = "Tap the card to do it; nothing happens until you do.") => [
  ...cards.map((c) => ({ type: "tool", id: (c as { id: string }).id, name: "desk_action", status: "ok", summary: "desk action",
    provenance: { source: "A desk action for the owner to tap; nothing done", kind: "proposal", as_of: null } })),
  ...cards, { type: "text", delta: text },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");

type Seen = { alerts: unknown[]; rearmed: unknown[]; watched: string[]; settings: { data: { levels: Record<string, { price: number; label: string }[]> } }[];
  outcomes: { id: string; body: { state: string; note?: string } }[]; tickets: string[] };

async function desk(page: Page, cards: unknown[], { width = 1440, quote = 101.2, stop = 92.3 } = {}) {
  const seen: Seen = { alerts: [], rearmed: [], watched: [], settings: [], outcomes: [], tickets: [] };
  let current = main();
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (r) => r.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (r) => r.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", (r) => r.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", (r) => r.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", (r) => r.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/desk/watching", (r: Route) => {
    if (r.request().method() === "POST") seen.watched.push(r.request().postDataJSON().symbol);
    return r.fulfill({ json: { state: "ok", symbols: seen.watched, count: seen.watched.length, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } });
  });
  await page.route("**/copilot/investigations?*", (r) => r.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", (r) => r.fulfill({ json: current }));
  await page.route("**/copilot/main-chat/history*", (r) => r.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, (r) => r.fulfill({ json: current }));
  await page.route(`**/copilot/main-chat/${MAIN}/exchange`, async (r) => {
    const transcript = [...current.transcript, ...r.request().postDataJSON().transcript];
    current = { ...current, transcript, message_count: transcript.length, revision: current.revision + 1 };
    await r.fulfill({ json: current });
  });
  await page.route(`**/copilot/investigations/${MAIN}/proposals/*/outcome`, async (r) => {
    seen.outcomes.push({ id: decodeURIComponent(new URL(r.request().url()).pathname.split("/").at(-2)!), body: r.request().postDataJSON() });
    await r.fulfill({ json: current });
  });
  await page.route("**/copilot/chat", (r) => r.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: sse(cards) }));
  await page.route("**/copilot/quote?*", (r) => r.fulfill({ json: { symbol: "NBIS", last: quote, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/alerts", (r) => {
    if (r.request().method() === "POST") seen.alerts.push(r.request().postDataJSON());
    return r.fulfill({ json: { alerts: [{ id: STOP, symbol: "NBIS", price: stop, created_on: "2026-11-12", condition: "crosses", interval: null, session: "regular",
      direction: "down", source_kind: "copilot", source_id: PLAN, label: "NBIS invalidation", state: "active", armed_at: 1, event: null, plan_role: "invalidation" }], phone: true } });
  });
  await page.route(`**/charts/alerts/${STOP}/rearm`, (r) => { seen.rearmed.push(r.request().postDataJSON()); return r.fulfill({ json: { alerts: [], phone: true } }); });
  await page.route("**/charts/settings", (r) => {
    if (r.request().method() === "PUT") { const body = r.request().postDataJSON(); seen.settings.push(body); return r.fulfill({ json: { revision: 2, data: body.data } }); }
    return r.fulfill({ json: { revision: 1, data: null } });
  });
  await page.route("**/copilot/tickets", (r) => r.fulfill({ json: { plans: [] } }));
  await page.route("**/copilot/tickets/*", (r) => { seen.tickets.push(r.request().url()); return r.fulfill({ status: 503, json: { detail: "No ticket in this test." } }); });
  await page.route("**/copilot/desk/*/{picture,chart}*", (r) => r.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.goto(`/copilot-lab?thread=${MAIN}`);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await page.getByLabel("Message").fill("Do it on the desk");
  await page.getByLabel("Message").press("Enter");
  return seen;
}

const actionCard = (page: Page, action: string) => page.getByTestId("desk-action").and(page.locator(`[data-action="${action}"]`));

test("a view change shows at once on the desk chart, with Undo", async ({ page }) => {
  await desk(page, [SHOW]);
  const shown = actionCard(page, "show");
  await expect(shown).toContainText("Show NBIS · 15m");
  await expect(shown).toContainText("Shown on the desk.");
  await expect(page.getByTestId("desk-chart")).toContainText("NBIS");
  await expect(page.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "15m" })).toHaveAttribute("aria-pressed", "true");
  await shown.getByRole("button", { name: "Undo" }).click();
  await expect(shown).toContainText("Undone: the desk is back as it was.");
  await expect(page.getByRole("group", { name: "Timeframe" }).getByRole("button", { name: "2m" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("desk-chart")).toContainText("QQQ");
});

test("an alert card sets nothing until the tap, then the chart's own alert route with the price now", async ({ page }) => {
  const seen = await desk(page, [ALERT, WATCH]);
  const alert = actionCard(page, "alert");
  await expect(alert).toContainText("Set alert: NBIS below 98.00");
  expect(seen.alerts).toEqual([]);
  await alert.getByRole("button", { name: "Set it" }).click();
  await expect(alert).toContainText("Alert set: NBIS crosses below 98.00, regular hours.");
  expect(seen.alerts).toEqual([{ symbol: "NBIS", price: 98, reference: 101.2, condition: "crosses", interval: null, session: "regular",
    source_kind: "level", source_id: "desk", label: "Set from the copilot" }]);
  await expect.poll(() => seen.outcomes.find((o) => o.id === "a_alert")?.body.state).toBe("confirmed");
  // Show it puts the ticker on the desk chart; Dismiss hides a card and keeps that.
  await alert.getByRole("button", { name: "Show it" }).click();
  await expect(page.getByTestId("desk-chart")).toContainText("NBIS");
  await actionCard(page, "watch").getByRole("button", { name: "Dismiss" }).click();
  await expect(actionCard(page, "watch")).toHaveCount(0);
  await expect.poll(() => seen.outcomes.find((o) => o.id === "a_watch")?.body).toEqual({ state: "dismissed" });
  expect(seen.watched).toEqual([]);
});

test("a card whose price moved far, or that is a day old, says so and does not act", async ({ page }) => {
  const seen = await desk(page, [ALERT, { ...WATCH, made_at: MADE - 2 * 86400 }], { quote: 90 });
  await actionCard(page, "alert").getByRole("button", { name: "Set it" }).click();
  await expect(actionCard(page, "alert")).toContainText("NBIS has moved from 101.20 to 90.00 since this card, so it does not act. Ask again.");
  await actionCard(page, "watch").getByRole("button", { name: "Add" }).click();
  await expect(actionCard(page, "watch")).toContainText("This card is more than a day old");
  expect(seen.alerts).toEqual([]);
  expect(seen.watched).toEqual([]);
});

test("watch adds to the app's own Watching list; draw saves a level in the chart settings", async ({ page }) => {
  const seen = await desk(page, [WATCH, DRAW]);
  await actionCard(page, "watch").getByRole("button", { name: "Add" }).click();
  await expect(actionCard(page, "watch")).toContainText("Added IREN to Watching.");
  expect(seen.watched).toEqual(["IREN"]);
  await expect(page.getByTestId("desk-watching")).toContainText("IREN");
  await actionCard(page, "draw").getByRole("button", { name: "Draw" }).click();
  await expect(actionCard(page, "draw")).toContainText("Drawn: 102.50 on NBIS (resistance)");
  const levels = seen.settings.at(-1)!.data.levels.NBIS;
  expect(levels).toEqual([expect.objectContaining({ price: 102.5, label: "resistance" })]);
});

test("moving a plan's stop arms its own stop alert at the new price", async ({ page }) => {
  const seen = await desk(page, [PLAN_STOP]);
  await expect(actionCard(page, "plan_stop")).toContainText("Update plan: NBIS stop 92.30 → 96.00");
  await actionCard(page, "plan_stop").getByRole("button", { name: "Update plan" }).click();
  await expect(actionCard(page, "plan_stop")).toContainText("Plan updated: NBIS stop 96.00 (was 92.30).");
  expect(seen.rearmed).toEqual([{ price: 96, reference: 101.2 }]);
});

test("a plan whose stop already changed is not moved", async ({ page }) => {
  const seen = await desk(page, [PLAN_STOP], { stop: 93 });
  await actionCard(page, "plan_stop").getByRole("button", { name: "Update plan" }).click();
  await expect(actionCard(page, "plan_stop")).toContainText("The plan's stop is 93.00 now, not 92.30. Ask again.");
  expect(seen.rearmed).toEqual([]);
});

test("a ticket card opens the copy-only Ticket tab on the saved plan with that contract", async ({ page }) => {
  const seen = await desk(page, [TICKET]);
  await actionCard(page, "ticket").getByRole("button", { name: "Open ticket" }).click();
  await expect(actionCard(page, "ticket")).toContainText("Nothing is sent from here.");
  await expect(page.getByRole("tab", { name: "Ticket" })).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => seen.tickets.at(-1) ?? "").toContain(`/copilot/tickets/${PLAN}`);
  expect(seen.tickets.at(-1)).toContain("strike=100");
});

test("on a phone the card fits and Show it closes the sheet onto the chart", async ({ page }) => {
  await desk(page, [ALERT], { width: 393 });
  const alert = actionCard(page, "alert");
  await alert.getByRole("button", { name: "Set it" }).click();
  await expect(alert).toContainText("Alert set");
  const box = await alert.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(393);
  await alert.getByRole("button", { name: "Show it" }).click();
  await expect(page.getByTestId("desk-chart")).toBeInViewport();
});
