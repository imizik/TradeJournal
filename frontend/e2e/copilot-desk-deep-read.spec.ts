import { expect, test } from "@playwright/test";

// Deep read on the desk: one tap asks this thread's copilot for the full read of its ticker now, in the chat. Every lab
// route is stubbed in the browser, so no model runs; the test reads the request the tap sends.
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};

test("Deep read sends the ticker's full read as the thread's next question", async ({ page }) => {
  const sent: { messages: { role: string; content: string }[]; symbol: string }[] = [];
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/research-jobs*", (route) => route.fulfill({ json: { queue_enabled: false, jobs: [] } }));
  await page.route("**/copilot/chat", (route) => { sent.push(route.request().postDataJSON()); return route.abort(); });
  await page.goto("/copilot-lab?symbol=NBIS");
  const talk = page.getByRole("region", { name: "Conversation" });
  const deep = talk.getByRole("button", { name: "Deep read" });
  await expect(deep).toBeVisible(); // no answer yet: it sits above the box, and needs no research queue
  await expect(talk.getByRole("button", { name: "Research deeper" })).toHaveCount(0); // the queue is off
  await deep.click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].symbol).toBe("NBIS");
  expect(sent[0].messages.at(-1)).toEqual({ role: "user", content: "Deep read NBIS" });
});

test("with no ticker there is no Deep read", async ({ page }) => {
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", (route) => route.abort());
  await page.goto("/copilot-lab");
  await expect(page.getByRole("region", { name: "Conversation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Deep read" })).toHaveCount(0);
});
