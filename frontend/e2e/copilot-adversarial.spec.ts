import { expect, test } from "@playwright/test";

// Copilot Lab adversarial cases that need the browser (backend cases: backend/tests/test_copilot_adversarial.py).
// Every lab route is stubbed, so no model runs and nothing reaches the e2e backend.
const RESULT = "22222222-2222-4222-8222-222222222222";
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false,
  key_configured: false, plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// A background research result: its saved transcript is the question alone, one message.
const result = {
  id: RESULT, source: "research_job", title: "Why are neoclouds weak?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 1, has_findings: true, created_at: "2026-10-24T14:20:00Z", updated_at: "2026-10-24T14:20:00Z",
  transcript: [{ role: "user", content: "Why are neoclouds weak?" }], evidence: [],
  findings: { summary: "Financing stress, not demand.", key_findings: [], counterpoints: [], what_would_change: [], citations: [] },
};
const answer = (text: string) => [
  `event: text\ndata: ${JSON.stringify({ type: "text", delta: text })}\n\n`,
  `event: done\ndata: ${JSON.stringify({ type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted",
    first_text_ms: 1, total_ms: 1, rounds: 1, tool_calls: [], cost_usd: 0,
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } })}\n\n`,
].join("");

// DEFECT, reported not fixed (CopilotLab.tsx is being refactored in another PR): the history builder pairs messages
// from index 0 in steps of two. After an odd-length transcript, every later pair is (answer, question) and dropped, so
// the second follow-up is sent without the first one and its answer.
test("follow-ups on an opened research result keep the earlier follow-up in the history", async ({ page }) => {
  test.fail(true, "Known defect: odd-length transcripts misalign the history pairs (see the PR report).");
  const sent: { role: string; content: string }[][] = [];
  await page.addInitScript((id) => window.localStorage.setItem("tradejournal.copilot-lab.current.v2", id), RESULT);
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [result] } }));
  await page.route(`**/copilot/investigations/${RESULT}`, (route) => route.fulfill({ json: { ...result, revision: 2 } }));
  await page.route(/\/copilot\/research-jobs(\?.*)?$/, (route) =>
    route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/chat", (route) => {
    sent.push(route.request().postDataJSON().messages);
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: answer(`Answer ${sent.length}.`) });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByText("Financing stress, not demand.")).toBeVisible();
  for (const [i, text] of ["First follow-up?", "Second follow-up?"].entries()) {
    await page.getByLabel("Message").fill(text);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(`Answer ${i + 1}.`)).toBeVisible();
  }
  expect(sent[1]).toEqual([
    { role: "user", content: "First follow-up?" }, { role: "assistant", content: "Answer 1." },
    { role: "user", content: "Second follow-up?" },
  ]);
});
