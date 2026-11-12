import { expect, test, type Page } from "@playwright/test";

// While the model has not spoken, the copilot shows each read's one fact as it lands (docs/copilot-lab.md § The desk):
// the server builds it from the result (backend/app/ai/copilot_tool_summary.py), never the model. Every lab route is
// stubbed in the browser and each turn is a fixed SSE stream, so no model runs. A fulfilled stream arrives and ends at
// once (and a stream that ends before its done event reads as interrupted), so the waiting state is held by a turn
// whose stream stays open after its reads (``held``); the facts are the ones the backend builds from the simulated
// fixture (backend/tests/test_copilot_tool_summary.py).
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NEW = "99999999-9999-4999-8999-999999999999";
const simulated = { source: "SIMULATED fixture", kind: "simulated", as_of: "2026-10-23T15:12:00Z", state: "ok" };
const GROUP = "NBIS +0.84% vs SPY +0.09%, 4 of 6 peers up (15m, 11:12)";
const NEWS = "3 headlines since 08:10, latest 10:40";
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const READS = [
  { type: "tool", id: "g1", name: "get_group_comparison", status: "running" },
  { type: "tool", id: "n1", name: "get_symbol_news", status: "running" },
  { type: "tool", id: "e1", name: "get_symbol_events", status: "running" },
  { type: "tool", id: "x1", name: "get_saved_research", status: "running" },
  { type: "tool", id: "g1", name: "get_group_comparison", status: "ok", summary: "Neoclouds: 4/6 peers up (15m)", fact: GROUP, ms: 4, provenance: simulated },
  { type: "tool", id: "n1", name: "get_symbol_news", status: "ok", summary: "3 headlines", fact: NEWS, ms: 3, provenance: simulated },
  { type: "tool", id: "e1", name: "get_symbol_events", status: "error", summary: "unavailable", ms: 2 },
  { type: "tool", id: "x1", name: "get_saved_research", status: "ok", summary: "0 saved", fact: null, ms: 1, provenance: simulated },
];
const ANSWER = "Verdict: Hold — The group is confirming.\n\nNBIS is up with four of six peers.";
const DONE = { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2,
  tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } };

async function lab(page: Page, body: string, held = false) {
  const record = { id: NEW, source: "copilot", title: "Is NBIS's group confirming?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
    message_count: 0, has_findings: false, created_at: "2026-10-23T15:00:00Z", updated_at: "2026-10-23T15:00:00Z", transcript: [], evidence: [], findings: null };
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null,
    day: { phase: "regular", need_you: 0, streak: null }, sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" }, threads: [] } }));
  await page.route("**/copilot/desk/*/timeline", (route) => route.fulfill({ json: { events: [], sources: {} } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => route.fulfill({ status: 201, json: { ...record, ...route.request().postDataJSON(), id: NEW } }));
  await page.route("**/copilot/investigations/*", (route) => route.fulfill({ json: { ...record, ...(route.request().method() === "PUT" ? route.request().postDataJSON() : {}) } }));
  await page.route("**/copilot/chat", (route) => route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: false } }));
  if (held) // the reads arrive and the stream stays open: the model has not written yet
    await page.addInitScript((text: string) => {
      const real = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => String(input instanceof Request ? input.url : input).includes("/copilot/chat")
        ? Promise.resolve(new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(text)); } }),
          { status: 200, headers: { "content-type": "text/event-stream" } }))
        : real(input, init);
    }, body);
  await page.goto("/copilot-lab?symbol=NBIS");
}

const ask = async (page: Page) => {
  await page.getByLabel("Message").fill("Is NBIS's group confirming?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
};

test("before the answer's first text, each completed read shows its fact in arrival order", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await lab(page, sse(READS), true); // the reads are back; the model has not written yet
  await ask(page);
  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByLabel("Progress")).toHaveText("Weighing the evidence…");
  // Only completed reads with a fact: not the failed one, not the one with nothing to say.
  await expect(conversation.getByTestId("copilot-progress-fact")).toHaveText([GROUP, NEWS]);

  // The phone keeps its gutters: the facts wrap, nothing scrolls sideways.
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(conversation.getByTestId("copilot-progress-fact").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("once the answer has text the facts leave the progress line", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await lab(page, sse([...READS, ...ANSWER.match(/\S+\s*/g)!.map((delta) => ({ type: "text", delta })), DONE]));
  await ask(page);
  const conversation = page.getByRole("region", { name: "Conversation" });
  await expect(conversation.getByTestId("copilot-answer")).toContainText("NBIS is up with four of six peers.");
  await expect(conversation.getByTestId("copilot-progress-fact")).toHaveCount(0);
});
