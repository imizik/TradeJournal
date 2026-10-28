import { expect, test, type Page, type Route } from "@playwright/test";

// Proposal cards are kept with their investigation: a reload or a switch to another thread brings each card back as it
// was left, and a confirmed card never offers Confirm again. Every lab route is stubbed in the browser and the
// investigations live in this test's own store, so what the page saves is exactly what it reads back; the turn is a fixed
// SSE stream, so no model runs, and nothing reaches the e2e backend's plans or alerts.
const INV = "55555555-5555-4555-8555-555555555555";
const OTHER = "66666666-6666-4666-8666-666666666666";
const ROTH = "00000000-0000-0000-0000-000000000001";
const STATUS = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const PLAN = { id: "toolu_plan", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "stock", contract: null,
  thesis: "NBIS reclaims the level overhead with its group.", entry_trigger: { condition: "crosses", price: 95.9, interval: null },
  invalidation: { condition: "crosses", price: 92.3, interval: null }, time_stop: null, size_note: null, last: 94.35, as_of: "2026-10-27T14:00:00Z" };
const WATCH = { id: "toolu_watch", kind: "watch", symbol: "NBIS", condition: "crosses", price: 97.5, interval: null, label: "NBIS clears the gap",
  why: "Where the last bounce stalled.", last: 94.35, as_of: "2026-10-27T14:00:00Z" };
const ANSWER = "Two drafts: a plan and a watch. Nothing is saved or armed until you confirm.";
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const TURN = sse([
  { type: "proposal", ...PLAN },
  { type: "proposal", ...WATCH },
  { type: "text", delta: ANSWER },
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1,
    tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);
const THREADS = { as_of: "2026-10-27T14:00:00Z", positions: { state: "ok", count: 0, positions: [] },
  investigations: { state: "ok", investigations: [] }, watches: { state: "ok", watches: [] } };

type Card = { id: string; client_id?: string; outcome?: { state: string; [key: string]: unknown }; [key: string]: unknown };
type Record_ = { id: string; title: string; symbol: string | null; revision: number; updated_at: string;
  transcript: { role: string; content: string; proposals?: Card[] }[]; [key: string]: unknown };
type Server = { records: Map<string, Record_>; posts: { path: string; body: Record<string, unknown> }[]; outcomes: string[] };

const meta = (id: string, title: string) => ({ id, source: "copilot", title, symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  has_findings: false, created_at: "2026-10-27T13:00:00Z", updated_at: "2026-10-27T13:00:00Z", evidence: [], findings: null });
const summary = (record: Record_) => ({ ...record, message_count: record.transcript.length });
const cards = (server: Server) => server.records.get(INV)!.transcript.flatMap((m) => m.proposals ?? []);

async function lab(page: Page, server: Server) {
  const post = (path: string, route: Route) => server.posts.push({ path, body: route.request().postDataJSON() });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: STATUS }));
  await page.route("**/copilot/threads", (route) => route.fulfill({ json: THREADS }));
  // The desk's thread list: one row per investigation in this test's store, which a row opens in place.
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: {
    as_of: "2026-10-27T14:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
    sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" },
    threads: [...server.records.values()].map((record) => ({ key: `investigation:${record.id}`, group: "watch", symbol: record.symbol,
      title: record.title, instrument: null, value: null, status: { text: "Open", tone: "muted" }, meter: null, investigation_id: record.id,
      trade_id: null, radar_event_id: null, path: null, changed_at: null })) } }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [...server.records.values()].map(summary) } }));
  await page.route("**/copilot/investigations", (route) => {
    const record = { ...meta(INV, "x"), ...route.request().postDataJSON() } as Record_;
    server.records.set(INV, record);
    return route.fulfill({ status: 201, json: record });
  });
  await page.route("**/copilot/investigations/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    const record = server.records.get(id);
    if (!record) return route.fulfill({ status: 404, json: { detail: "No such investigation." } });
    if (route.request().method() === "PUT") {
      const { revision, ...fields } = route.request().postDataJSON();
      if (revision !== record.revision) return route.fulfill({ status: 409, json: { detail: "This investigation changed in another window." } });
      server.records.set(id, { ...record, ...fields, revision: record.revision + 1, updated_at: new Date().toISOString() });
    }
    return route.fulfill({ json: server.records.get(id) });
  });
  await page.route("**/copilot/investigations/*/proposals/*/outcome", (route) => {
    const [, , id, , proposal] = new URL(route.request().url()).pathname.split("/").slice(-6);
    const card = server.records.get(id)!.transcript.flatMap((m) => m.proposals ?? []).find((p) => p.id === proposal);
    if (!card) return route.fulfill({ status: 404, json: { detail: "That card is not saved with this investigation." } });
    card.outcome = route.request().postDataJSON();
    server.outcomes.push(`${proposal}:${card.outcome!.state}`);
    return route.fulfill({ json: server.records.get(id) });
  });
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: true, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: {
    accounts: [{ id: ROTH, label: "Roth IRA ··8267", broker: "robinhood" }], default_account_id: ROTH, templates: [], max_templates: 3,
    transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/charts/captures", (route) => { post("captures", route); return route.fulfill({ status: 201, json: { id: "c1", ...route.request().postDataJSON() } }); });
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: false } }));
  await page.route("**/charts/alerts", (route) => {
    if (route.request().method() !== "POST") return route.fulfill({ json: { alerts: [], phone: true } });
    post("alerts", route);
    return route.fulfill({ json: { alerts: [], phone: true } });
  });
  await page.goto("/copilot-lab");
}

const planCard = (page: Page) => page.getByRole("region", { name: "Proposed trade plan" });
const watchCard = (page: Page) => page.getByRole("region", { name: "Proposed watch" });

test("drafted cards come back after a reload and a thread switch, a confirmed one as done", async ({ page }) => {
  const server: Server = { records: new Map(), posts: [], outcomes: [] };
  server.records.set(OTHER, { ...meta(OTHER, "CRWV capacity"), symbol: "CRWV",
    transcript: [{ role: "user", content: "CRWV capacity?" }, { role: "assistant", content: "CRWV is still adding capacity." }] } as Record_);
  await lab(page, server);
  await page.getByLabel("Message").fill("Plan NBIS and watch the gap");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  // Saved with the answer: each card with its one client id, and nothing done with it yet.
  const saved = cards(server);
  expect(saved.map((c) => c.id)).toEqual([PLAN.id, WATCH.id]);
  expect(saved.every((c) => /^[A-Za-z0-9_-]{8,64}$/.test(c.client_id ?? "") && !("outcome" in c) && !("type" in c))).toBe(true);
  expect(saved[0]).toMatchObject({ ...PLAN });

  // A reload brings both back with Confirm; nothing was saved or armed by bringing them back.
  await page.reload();
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(planCard(page).getByRole("button", { name: "Confirm" })).toBeEnabled();
  await expect(planCard(page).getByLabel("Thesis")).toHaveValue(PLAN.thesis);
  await expect(watchCard(page)).toContainText("Proposed watch · NBIS crosses 97.5");
  await expect(watchCard(page).getByRole("button", { name: "Confirm" })).toBeEnabled();
  expect(server.posts).toEqual([]);

  // Confirm the watch: its result is recorded with the investigation at once.
  await watchCard(page).getByRole("button", { name: "Confirm" }).click();
  await expect(watchCard(page).getByRole("status")).toHaveText("Alert set: NBIS crosses 97.5 (NBIS was 94.35).");
  await expect.poll(() => server.outcomes).toEqual([`${WATCH.id}:confirmed`]);
  expect(server.posts.map((p) => p.path)).toEqual(["alerts"]);

  // After a reload the watch shows done with no Confirm; the plan still offers Confirm.
  await page.reload();
  await expect(watchCard(page).getByRole("status")).toHaveText("Alert set: NBIS crosses 97.5 (NBIS was 94.35).");
  await expect(watchCard(page).getByRole("button", { name: "Confirm" })).toHaveCount(0);
  await expect(planCard(page).getByRole("button", { name: "Confirm" })).toBeEnabled();

  // Switch to another investigation and back: the same two states.
  const recent = page.getByRole("navigation", { name: "Thread list" });
  await recent.getByRole("link", { name: /CRWV capacity/ }).click();
  await expect(page.getByText("CRWV is still adding capacity.")).toBeVisible();
  await expect(planCard(page)).toHaveCount(0);
  await recent.getByRole("link", { name: /Plan NBIS and watch the gap/ }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(watchCard(page).getByRole("status")).toHaveText("Alert set: NBIS crosses 97.5 (NBIS was 94.35).");
  await expect(planCard(page).getByRole("button", { name: "Confirm" })).toBeEnabled();
  expect(server.posts.map((p) => p.path)).toEqual(["alerts"]); // nothing made again

  // Confirm the plan: its results come back after a reload, locked, with no Confirm.
  await planCard(page).getByLabel("Thesis").fill("NBIS reclaims 95.90 with CRWV.");
  await planCard(page).getByRole("button", { name: "Confirm" }).click();
  await expect(planCard(page).getByRole("status")).toHaveText("Plan confirmed.");
  await expect.poll(() => cards(server).find((c) => c.id === PLAN.id)?.outcome?.state).toBe("confirmed");
  const made = server.posts.length;
  const [capture] = server.posts.filter((p) => p.path === "captures").map((p) => p.body);
  expect(capture.client_id).toBe(saved[0].client_id); // the card's kept id, so a retry anywhere replays it
  await page.reload();
  const results = planCard(page).getByRole("list", { name: "Plan results" });
  await expect(results).toContainText("Pre-trade plan: done");
  await expect(results).toContainText("Entry alert: done");
  await expect(results).toContainText("Invalidation alert: done");
  await expect(planCard(page).getByLabel("Thesis")).toHaveValue("NBIS reclaims 95.90 with CRWV.");
  await expect(planCard(page).getByLabel("Thesis")).toBeDisabled();
  await expect(planCard(page).getByRole("button", { name: "Confirm" })).toHaveCount(0);
  expect(server.posts.length).toBe(made);
});

test("a dismissed card stays dismissed, and a card confirmed in another window is not made again", async ({ page }) => {
  const server: Server = { records: new Map(), posts: [], outcomes: [] };
  await lab(page, server);
  await page.getByLabel("Message").fill("Plan NBIS and watch the gap");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await watchCard(page).getByRole("button", { name: "Dismiss" }).click();
  await expect(watchCard(page)).toHaveCount(0);
  await expect.poll(() => server.outcomes).toEqual([`${WATCH.id}:dismissed`]);

  // Another window confirmed the plan after this one drew it: Confirm here shows that result instead of saving again.
  const plan = cards(server).find((c) => c.id === PLAN.id)!;
  plan.outcome = { state: "confirmed", parts: { plan: { state: "done", text: "Saved as your pre-trade plan." },
    entry: { state: "done", text: "Set: NBIS crosses 95.9." }, invalidation: { state: "done", text: "Set: NBIS crosses 92.3." } },
    fields: { thesis: "Confirmed elsewhere.", contract: "", entry: "95.9", invalidation: "92.3", time_stop: "", size_note: "" } };
  await planCard(page).getByRole("button", { name: "Confirm" }).click();
  await expect(planCard(page).getByRole("status")).toHaveText("Plan confirmed.");
  await expect(planCard(page).getByLabel("Thesis")).toHaveValue("Confirmed elsewhere.");
  expect(server.posts).toEqual([]);

  await page.reload();
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(watchCard(page)).toHaveCount(0);
  await expect(planCard(page).getByRole("list", { name: "Plan results" })).toContainText("Pre-trade plan: done");
});

test("a week review's practice card kept in an earlier answer is not added again", async ({ page }) => {
  const server: Server = { records: new Map(), posts: [], outcomes: [] };
  const PRACTICE = { id: "week-practice", kind: "practice", text: "Exit at my invalidation", measure: "exit_at_invalidation",
    label: "exit at my invalidation", target: 1, why: "Two of three held past it." };
  // The review proposed it, the owner dismissed it, then asked a follow-up; the practice route still offers the card.
  server.records.set(INV, { ...meta(INV, "Week review Oct 19"), transcript: [
    { role: "user", content: "Review my week" }, { role: "assistant", content: "Your week.", proposals: [{ ...PRACTICE, outcome: { state: "dismissed" } }] },
    { role: "user", content: "And NBIS?" }, { role: "assistant", content: "NBIS lagged its group." }] } as Record_);
  await page.route("**/copilot/practice?*", (route) => route.fulfill({ json: { goal: null, this_week: null, proposed: PRACTICE } }));
  await page.addInitScript((id) => window.localStorage.setItem("tradejournal.copilot-lab.current.v2", id), INV);
  await lab(page, server);
  await expect(page.getByText("NBIS lagged its group.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Proposed practice" })).toHaveCount(0);
  await page.getByLabel("Message").fill("Anything else?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  expect(cards(server).filter((c) => c.id === PRACTICE.id)).toEqual([expect.objectContaining({ outcome: { state: "dismissed" } })]);
});
