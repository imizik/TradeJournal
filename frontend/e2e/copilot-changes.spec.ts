import { expect, test, type Page } from "@playwright/test";

// "What changed?" on a reopened investigation. Every lab route is stubbed in the browser and the turn is a fixed SSE
// stream, so no model runs.
const INV = "44444444-4444-4444-8444-444444444444";
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const record = {
  id: INV, source: "copilot", title: "NBIS bounce", symbol: "NBIS", status: "open", conclusion: "Lagging its group", revision: 3,
  message_count: 2, has_findings: false, created_at: "2026-10-23T15:00:00Z", updated_at: "2026-10-23T15:20:00Z",
  transcript: [{ role: "user", content: "Is NBIS confirming?" }, { role: "assistant", content: "Not yet: it lags CRWV." }],
  evidence: [{ tool: "get_group_comparison", as_of: "2026-10-23T15:12:00Z", kind: "recorded", message: 1 }], findings: null,
};
const ANSWER = "Since Oct 23 the 92.46 alert fired at 92.40, and a research result finished. The saved conclusion still holds.";
const TURN = [
  { type: "tool", id: "c1", name: "get_investigation_changes", status: "running" },
  { type: "tool", id: "c1", name: "get_investigation_changes", status: "ok", summary: "1 alerts (1 fired), 1 research jobs", ms: 3,
    provenance: { source: "Saved investigation, its alerts and research jobs (TradeJournal)", kind: "saved", as_of: "2026-10-24T14:00:00Z" } },
  { type: "text", delta: ANSWER },
  { type: "done", metrics: { backend: "fake", evidence: "live", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");

async function lab(page: Page, url = "/copilot-lab") {
  const chats: { messages: { role: string; content: string }[] }[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [record] } }));
  await page.route(`**/copilot/investigations/${INV}`, (route) => route.fulfill({ json: route.request().method() === "PUT" ? { ...record, revision: 4 } : record }));
  await page.route("**/copilot/chat", (route) => {
    chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto(url);
  return chats;
}

test("a reopened investigation's What changed? runs one turn with its id and shows the answer", async ({ page }) => {
  const chats = await lab(page);
  await expect(page.getByRole("button", { name: "What changed?" })).toHaveCount(0); // a new conversation has nothing to compare
  await page.getByRole("navigation", { name: "Recent investigations" }).getByRole("button", { name: /NBIS bounce/ }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  const button = page.getByRole("button", { name: "What changed?" });
  await expect(button).toBeVisible();
  expect(chats).toEqual([]); // opening costs nothing
  await button.click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  expect(chats).toHaveLength(1);
  const sent = chats[0].messages;
  expect(sent.slice(0, 2)).toEqual(record.transcript); // the saved conversation goes with it
  expect(sent.at(-1)).toEqual({ role: "user", content: expect.stringMatching(new RegExp(`^What changed\\? Use get_investigation_changes for investigation ${INV}`)) });
  await expect(page.getByText("What changed · saved")).toBeVisible();
});

test("opened from an alert's link, What changed? waits in the message box, unsent", async ({ page }) => {
  const chats = await lab(page, `/copilot-lab?investigation=${INV}`);
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(page.getByLabel("Message")).toHaveValue(new RegExp(`^What changed\\? Use get_investigation_changes for investigation ${INV}`));
  await page.waitForTimeout(300);
  expect(chats).toEqual([]);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  expect(chats).toHaveLength(1);
});
