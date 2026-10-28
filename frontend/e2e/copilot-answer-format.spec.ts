import { expect, test, type Page } from "@playwright/test";

// The copilot's answer format on the desk (docs/copilot-lab.md § How the copilot reasons): a verdict and a bold headline,
// the body, a plain Changes if line and the sources folded into one line that still says what was unavailable, stale or
// simulated. And the desk's cleaned conversation: one quiet status line, a scope chip in the message box, suggestion
// chips from the thread's state, a "…" menu for the conclusion and Close, and at 375 px a full-width box with the mic as
// the main round button. Every lab route is stubbed in the browser and each turn is a fixed SSE stream, so no model runs.
const INV = "77777777-7777-4777-8777-777777777777";
const NEW = "88888888-8888-4888-8888-888888888888";
const ON = {
  enabled: true, backend: "fake", evidence: "fixture", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true, transcriber: { configured: true, provider: "test" } },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const ANSWER = "Verdict: Hold — The thesis has not broken.\n\n_(Simulated model — scripted text from the tool results, not Claude.)_\n\n"
  + "NBIS is 3.1% above the invalidation and the group is up.\n\n- CRWV +1.9% over 15 minutes\n- No new headline\n\nChanges if: NBIS closes below 85.00.";
const simulated = (source: string, state = "ok") => ({ source: `SIMULATED fixture (shaped like ${source})`, kind: "simulated", as_of: "2026-10-28T14:00:00Z", state });
const sse = (events: object[]) => events.map((event) => `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
const TURN = sse([
  { type: "tool", id: "g1", name: "get_group_comparison", status: "ok", summary: "Neoclouds: 4/6 peers up (15m)", ms: 4, provenance: simulated("Radar") },
  { type: "tool", id: "n1", name: "get_symbol_news", status: "error", summary: "news provider timed out", ms: 10 },
  { type: "tool", id: "q1", name: "get_quotes", status: "ok", summary: "NBIS 87.74", ms: 2, provenance: simulated("Tradier", "stale") },
  ...ANSWER.match(/\S+\s*/g)!.map((delta) => ({ type: "text", delta })),
  { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2, rounds: 2, tool_calls: [],
    usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
]);
const PLAN = { id: "toolu_plan", kind: "trade_plan", symbol: "NBIS", direction: "long", instrument: "stock", contract: null,
  thesis: "NBIS reclaims the level overhead with its group.", entry_trigger: { condition: "crosses", price: 95.9, interval: null },
  invalidation: { condition: "crosses", price: 92.3, interval: null }, time_stop: null, size_note: null, last: 94.35, as_of: "2026-10-28T14:00:00Z",
  client_id: "plan-card-0001" };
const record = (over: Record<string, unknown> = {}) => ({
  id: INV, source: "copilot", title: "Is the NBIS recovery real?", symbol: "NBIS", status: "open", conclusion: null, revision: 1,
  message_count: 2, has_findings: false, created_at: "2026-10-27T19:00:00Z", updated_at: "2026-10-27T19:05:00Z",
  transcript: [{ role: "user", content: "Is NBIS confirming?" }, { role: "assistant", content: "Not yet: it lags CRWV." }], evidence: [], findings: null,
  ...over,
});
const DESK = {
  as_of: "2026-10-28T14:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" }, threads: [],
};

type Lab = { chats: { messages: { role: string; content: string }[]; symbol: string | null }[]; puts: Record<string, unknown>[] };

async function lab(page: Page, url: string, saved = record()) {
  const seen: Lab = { chats: [], puts: [] };
  let current = saved;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: DESK }));
  await page.route("**/copilot/desk/*/timeline", (route) => route.fulfill({ json: { events: [], sources: {} } }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/investigations", (route) =>
    route.fulfill({ status: 201, json: { ...record({ id: NEW, transcript: [] }), ...route.request().postDataJSON(), id: NEW } }));
  await page.route("**/copilot/investigations/*", (route) => {
    if (route.request().method() === "PUT") {
      const { revision, ...fields } = route.request().postDataJSON();
      seen.puts.push(fields);
      current = { ...current, ...fields, revision: revision + 1 };
    }
    return route.fulfill({ json: current });
  });
  await page.route("**/copilot/chat", (route) => {
    seen.chats.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: TURN });
  });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/quote?*", (route) => route.fulfill({ json: { symbol: "NBIS", last: 94.35, trade_time: 1, fetched_at: 1, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/captures/setup", (route) => route.fulfill({ json: { accounts: [], default_account_id: null, templates: [], max_templates: 3,
    transcriber: { configured: false, provider: "off", note: "" } } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: false } }));
  await page.goto(url);
  return seen;
}

const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });

test("an answer leads with its verdict and headline, keeps Changes if plain, and folds its sources without hiding what is missing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const seen = await lab(page, "/copilot-lab?symbol=NBIS");
  const here = conversation(page);
  // One quiet line says what answers and on what data; no Recent row, no Symbol box.
  const status = page.getByTestId("copilot-status");
  await expect(status.getByText("Simulated model — no API calls", { exact: true })).toBeVisible();
  await expect(status.getByText("Simulated market data", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Recent investigations" })).toHaveCount(0);
  await expect(page.getByLabel("Investigation symbol")).toHaveCount(0);
  await expect(page.getByTestId("copilot-scope")).toHaveText("About NBIS");
  // A fresh thread offers its first steps; nothing is sent until one is pressed.
  const chips = page.getByRole("group", { name: "Suggestions" });
  await expect(chips.getByRole("button")).toHaveText(["Is NBIS's group confirming?", "Plan a trade"]);
  expect(seen.chats).toEqual([]);

  await page.getByLabel("Message").fill("Is NBIS still a hold?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const answer = here.getByTestId("copilot-answer");
  await expect(answer.getByTestId("copilot-verdict")).toHaveText("Hold");
  await expect(answer.locator("strong").first()).toHaveText("The thesis has not broken.");
  await expect(answer).toContainText("NBIS is 3.1% above the invalidation and the group is up.");
  await expect(answer.getByRole("listitem")).toHaveText(["CRWV +1.9% over 15 minutes", "No new headline"]);
  await expect(answer.getByText("Changes if NBIS closes below 85.00.", { exact: true })).toBeVisible();
  await expect(answer).not.toContainText("Verdict:"); // the structure, not the raw lines
  await expect(answer).toContainText("(Simulated model — scripted text from the tool results, not Claude.)");
  expect(seen.chats[0].symbol).toBe("NBIS");

  // Folded, the sources still say one was unavailable, one stale, and that the data was simulated.
  const sources = here.getByTestId("copilot-sources");
  await expect(sources.locator("summary")).toHaveText("Sources · 3 · 1 unavailable · 1 stale · simulated▸");
  await expect(sources.getByText("Group comparison · simulated")).toBeHidden();
  await sources.locator("summary").click();
  await expect(sources.getByText("Group comparison · simulated")).toBeVisible();
  await expect(sources.getByText("News · unavailable")).toBeVisible();
  await expect(sources).toContainText("fake-scripted"); // the turn's model, timings and cost, one click away
  await expect(sources).toContainText("(no API call)");

  // Saved, the thread's next steps are offered instead.
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expect(chips.getByRole("button")).toHaveText(["What changed?", "Look at my chart", "Close with a lesson"]);
  await page.screenshot({ path: test.info().outputPath("answer-format-1440.png") });

  // × on the scope chip asks across everything.
  await page.getByRole("button", { name: "Ask across everything" }).click();
  await expect(page.getByTestId("copilot-scope")).toHaveText("Across everything · add a symbol");
  await page.getByLabel("Message").fill("Anything else need me?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(here.getByTestId("copilot-verdict")).toHaveCount(2);
  expect(seen.chats[1].symbol).toBeNull();
});

test("an answer without the format, a saved one from before it, reads as plain text", async ({ page }) => {
  await lab(page, `/copilot-lab?investigation=${INV}`);
  await expect(conversation(page).getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(conversation(page).getByTestId("copilot-verdict")).toHaveCount(0);
  await expect(conversation(page).getByTestId("copilot-sources")).toHaveCount(0); // nothing was read, nothing to fold
});

test("the thread menu keeps a lesson and closes the thread; a plan card offers Size it, unsent", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const saved = record({ transcript: [{ role: "user", content: "Plan a trade on NBIS" },
    { role: "assistant", content: "Verdict: Draft — A NBIS plan is on the card below, not armed.\n\nEdit the card if my levels are off.", proposals: [PLAN] }] });
  const seen = await lab(page, `/copilot-lab?investigation=${INV}`, saved);
  await expect(conversation(page).getByTestId("copilot-verdict")).toHaveText("Draft");
  await expect(page.getByRole("region", { name: "Proposed trade plan" })).toBeVisible();
  const chips = page.getByRole("group", { name: "Suggestions" });
  await expect(chips.getByRole("button")).toHaveText(["What changed?", "Look at my chart", "Size it", "Close with a lesson"]);
  await expect(page.getByLabel("Message")).toHaveValue(/^What changed\?/); // the deep link's question, unsent

  await chips.getByRole("button", { name: "Size it" }).click();
  await expect(page.getByLabel("Message")).toHaveValue(/^Size it: with this plan's entry and invalidation, .* to \$$/);
  await expect(page.getByLabel("Message")).toBeFocused();
  expect(seen.chats).toEqual([]);

  await chips.getByRole("button", { name: "Close with a lesson" }).click();
  const menu = page.getByRole("group", { name: "Thread actions" });
  await expect(menu.getByLabel("Conclusion")).toBeFocused();
  await menu.getByLabel("Conclusion").fill("Wait for the 5m close; the group led and NBIS lagged.");
  await menu.getByRole("button", { name: "Close thread" }).click();
  await expect.poll(() => seen.puts.at(-1)).toMatchObject({ status: "closed", conclusion: "Wait for the 5m close; the group led and NBIS lagged." });
  await expect(menu).toHaveCount(0);
  await expect(page.getByText("Closed", { exact: true })).toBeVisible();
  await expect(chips.getByRole("button", { name: "Close with a lesson" })).toHaveCount(0);
  await page.getByRole("button", { name: "Thread actions" }).click();
  await expect(menu.getByRole("button", { name: "Reopen" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  expect(seen.chats).toEqual([]); // nothing here spent a turn
});

test("at 375 px the box takes the full width, + holds attach and read-aloud, and the mic is the round main button above the tab bar", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, `/copilot-lab?investigation=${INV}`);
  await expect(conversation(page).getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(page.getByTestId("copilot-attach")).toBeHidden();
  await page.getByRole("button", { name: "More: attach, read aloud" }).click();
  await expect(page.getByTestId("copilot-attach")).toBeVisible();
  const field = (await page.getByLabel("Message").boundingBox())!; // measured once the tray's settings row is in
  expect(field.width).toBeGreaterThanOrEqual(320);
  const mic = page.getByTestId("copilot-mic");
  const box = (await mic.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(await mic.evaluate((el) => getComputedStyle(el).borderRadius)).toBe("9999px");
  const send = (await page.getByRole("button", { name: "Send", exact: true }).boundingBox())!;
  expect(Math.abs(box.y + box.height / 2 - (send.y + send.height / 2))).toBeLessThan(8);
  expect(box.y).toBeGreaterThanOrEqual(field.y + field.height);
  const tabs = (await page.getByRole("navigation", { name: "Main tabs" }).boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(tabs.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("composer-375.png") });
});
