import { expect, test, type Page } from "@playwright/test";

// The lab's home: the desk's thread list beside the conversation. Every lab route is stubbed in the browser and the one
// turn is a fixed SSE stream, so no model runs. Opening the lab reads /copilot/desk/threads and sends nothing; only a
// pinned row sends, and only when pressed. The grouped list itself: copilot-thread-list.spec.ts.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "11111111-1111-4111-8111-111111111111";
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const DESK = {
  as_of: "2026-10-23T15:12:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" },
  threads: [
    row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "What matters right now? One turn across everything", tone: "muted" } }),
    row({ key: "week", group: "pinned", title: "Review my week", status: { text: "Planned vs unplanned, follow-through, exits", tone: "muted" } }),
    row({ key: `investigation:${INV}`, group: "watch", symbol: "NBIS", title: "Is the NBIS recovery real?",
      status: { text: "Group is confirming; the symbol lags.", tone: "muted" }, investigation_id: INV, changed_at: 1792000000 }),
  ],
};
const PROMPT = "What matters right now across my open positions, armed watches and open investigations? Lead with anything that needs a decision today; say plainly if nothing does.";
const ANSWER = "Only the NBIS call needs a decision today: its give-back fired.";
const TURN = [
  { type: "text", delta: ANSWER },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 1, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const saved = {
  id: INV, source: "copilot", title: "Is the NBIS recovery real?", symbol: "NBIS", status: "open", conclusion: "Group is confirming; the symbol lags.",
  revision: 1, message_count: 2, has_findings: false, created_at: "2026-10-22T19:00:00Z", updated_at: "2026-10-22T19:05:00Z",
  transcript: [{ role: "user", content: "Is NBIS confirming?" }, { role: "assistant", content: "Not yet: it lags CRWV." }], evidence: [], findings: null,
};

async function lab(page: Page) {
  const chats: { messages: { role: string; content: string }[]; symbol: string | null }[] = [];
  const saves: { symbol: string | null; title: string }[] = [];
  let reads = 0;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => { reads += 1; return route.fulfill({ json: DESK }); });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) => {
    const body = route.request().postDataJSON();
    saves.push(body);
    return route.fulfill({ status: 201, json: { ...saved, ...body, id: "33333333-3333-4333-8333-333333333333", revision: 1 } });
  });
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: saved }));
  await page.route("**/copilot/chat", (route) => {
    chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto("/copilot-lab");
  return { chats, saves, reads: () => reads };
}

const list = (page: Page) => page.getByRole("navigation", { name: "Thread list" });

test("the list sends nothing on open, and What matters right now? asks across everything beside it", async ({ page }) => {
  const { chats, saves, reads } = await lab(page);
  const threads = list(page);
  await expect(threads.getByRole("link", { name: "NBIS Is the NBIS recovery real?" })).toHaveAttribute("href", `/copilot-lab?investigation=${INV}`);
  await expect(threads).toContainText("Group is confirming; the symbol lags.");
  await page.waitForTimeout(300);
  expect(chats).toEqual([]); // opening costs nothing
  expect(reads()).toBe(1);

  await threads.getByRole("button", { name: "What matters right now?" }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  expect(chats).toEqual([{ messages: [{ role: "user", content: PROMPT }], symbol: null }]);
  await expect(threads).toBeVisible(); // the desk keeps the thread list beside the open conversation
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].symbol).toBeNull(); // saved about no symbol
  await expect(page.getByLabel("Investigation symbol")).toHaveValue("");
});

test("an open investigation opens in place without sending", async ({ page }) => {
  const { chats } = await lab(page);
  const threads = list(page);
  await threads.getByRole("link", { name: "NBIS Is the NBIS recovery real?" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(threads).toBeVisible(); // still beside the conversation on a wide screen
  await expect(page.getByLabel("Message")).toHaveValue(""); // not even a prefilled question
  expect(chats).toEqual([]);
});

test("on a phone the desk shows one pane at a time, and opening a thread moves to it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const threads = list(page);
  const tabs = page.getByRole("tablist", { name: "Desk" });
  await expect(tabs.getByRole("tab", { name: "Now" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Message")).toBeHidden();
  await threads.getByRole("link", { name: "NBIS Is the NBIS recovery real?" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(threads).toBeHidden();
  await expect(tabs.getByRole("tab", { name: "NBIS" })).toHaveAttribute("aria-selected", "true");
  await tabs.getByRole("tab", { name: "Now" }).click();
  await expect(threads).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  expect(chats).toEqual([]);
});

test("the list says so when its read fails, and the pinned rows still work", async ({ page }) => {
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ status: 503, json: { detail: "Copilot Lab is off." } }));
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.goto("/copilot-lab");
  const threads = list(page);
  await expect(threads).toContainText("Threads unavailable: Copilot Lab is off.");
  await expect(threads.getByRole("button", { name: "What matters right now?" })).toBeEnabled();
  await expect(threads.getByRole("button", { name: "Review my week" })).toBeEnabled();
});
