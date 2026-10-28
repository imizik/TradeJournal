import { expect, test, type Page } from "@playwright/test";

// The lab's home, Open threads. Every lab route is stubbed in the browser and the one turn is a fixed SSE stream, so no
// model runs. Opening the lab reads /copilot/threads and sends nothing; only the button sends.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "11111111-1111-4111-8111-111111111111";
const THREADS = {
  as_of: "2026-10-23T15:12:00Z",
  positions: { state: "ok", count: 3, positions: [
    { symbol: "NBIS", instrument: "option", option: { side: "call", strike: 100, expiry: "2026-11-21" }, direction: "long", quantity: 2,
      unrealized_pct: -25.4, giveback: "fired", peak_gain_pct: 15.7, days_to_expiry: 29, expires_today: false, days_held: 6 },
    { symbol: "CRWV", instrument: "stock", direction: "long", quantity: 15, unrealized_pct: 5.7, days_held: 11 },
  ] },
  investigations: { state: "ok", investigations: [
    { id: INV, source: "copilot", symbol: "NBIS", title: "Is the NBIS recovery real?", status: "open",
      conclusion: "Group is confirming; the symbol lags.", updated_at: "2026-10-22T19:05:00Z",
      // Thesis watch: the last triggers for this investigation, newest first (docs/copilot-lab.md § Thesis watch).
      watch: [
        { kind: "news", text: "Nebius wins $3B Meta deal (Benzinga, 09:52)", fired_at: "2026-10-23T13:55:00Z", delivery: "sent", reason: null, path: `/copilot-lab?investigation=${INV}` },
        { kind: "move", text: "NBIS +4.1% since your investigation's evidence (Oct 22 15:05 NY): 101 → 105.1", fired_at: "2026-10-23T14:15:00Z",
          delivery: "skipped", reason: "already told today", path: `/copilot-lab?investigation=${INV}` },
      ] },
    { id: "22222222-2222-4222-8222-222222222222", source: "research_job", symbol: "CRWV", title: "CRWV capacity deal terms",
      status: "open", updated_at: "2026-10-22T16:30:00Z" },
  ] },
  watches: { state: "ok", watches: [
    { watch: "level alert", symbol: "NBIS", price: 92.5, condition: "crosses", label: "NBIS loses the bounce low", source: "copilot" },
    { watch: "level alert", symbol: "CRWV", price: 135, condition: "closes_beyond", interval: "15m", label: "CRWV clears the gap", source: "level" },
    { watch: "research job (reassess)", status: "queued", symbols: ["NBIS"], question: "Has the financing overhang cleared?" },
  ] },
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
  let threadReads = 0;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/threads", (route) => { threadReads += 1; return route.fulfill({ json: THREADS }); });
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
  return { chats, saves, reads: () => threadReads };
}

test("Open threads shows what is live, sends nothing on open, and one button asks across everything", async ({ page }) => {
  const { chats, saves, reads } = await lab(page);
  const home = page.getByRole("region", { name: "Open threads" });
  await expect(home).toContainText("NBIS 100C Nov 21");
  await expect(home).toContainText("-25.4%");
  await expect(home).toContainText("give-back fired");
  await expect(home).toContainText("29 days to expiry");
  await expect(home).toContainText("CRWV stock · +5.7% · held 11 days");
  await expect(home).toContainText("+1 more");
  await expect(home).toContainText("NBIS crosses 92.5 · NBIS loses the bounce low");
  await expect(home).toContainText("CRWV closes beyond 135 (15m) · CRWV clears the gap");
  await expect(home.getByRole("link", { name: "NBIS · Is the NBIS recovery real?" })).toHaveAttribute("href", `/copilot-lab?investigation=${INV}`);
  await expect(home).toContainText("Group is confirming; the symbol lags.");
  const since = home.getByRole("list", { name: "New since Is the NBIS recovery real?" });
  await expect(since).toContainText("News · Nebius wins $3B Meta deal (Benzinga, 09:52)");
  await expect(since).toContainText("Move · NBIS +4.1% since your investigation's evidence (Oct 22 15:05 NY): 101 → 105.1");
  await expect(since).toContainText("skipped (already told today)");
  await expect(since).not.toContainText("sent"); // a delivered ping needs no state
  await expect(home.getByRole("link", { name: "CRWV · research · CRWV capacity deal terms" })).toBeVisible();
  await expect(home).toContainText("reassess · queued · NBIS · Has the financing overhang cleared?");
  await page.waitForTimeout(300);
  expect(chats).toEqual([]); // opening costs nothing
  expect(reads()).toBe(1);
  await home.screenshot({ path: test.info().outputPath("copilot-home-desktop.png") });

  await home.getByRole("button", { name: "What matters right now?" }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  expect(chats).toEqual([{ messages: [{ role: "user", content: PROMPT }], symbol: null }]);
  await expect(home).toBeVisible(); // the desk keeps the thread list beside the open conversation
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].symbol).toBeNull(); // saved about no symbol
  await expect(page.getByLabel("Investigation symbol")).toHaveValue("");
});

test("an open investigation from Open threads opens in place without sending", async ({ page }) => {
  const { chats } = await lab(page);
  const home = page.getByRole("region", { name: "Open threads" });
  await home.getByRole("link", { name: "NBIS · Is the NBIS recovery real?" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(home).toBeVisible(); // still beside the conversation on a wide screen
  await expect(page.getByLabel("Message")).toHaveValue(""); // not even a prefilled question
  expect(chats).toEqual([]);
});

test("Open threads fits a 375 px phone and its button is thumb-sized", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const home = page.getByRole("region", { name: "Open threads" });
  await expect(home).toContainText("NBIS loses the bounce low");
  const ask = home.getByRole("button", { name: "What matters right now?" });
  await expect(ask).toBeInViewport();
  expect((await ask.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("copilot-home-375.png"), fullPage: true });
  expect(chats).toEqual([]);
});

test("on a phone the desk shows one pane at a time, and opening a thread moves to it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const home = page.getByRole("region", { name: "Open threads" });
  const tabs = page.getByRole("tablist", { name: "Desk" });
  await expect(tabs.getByRole("tab", { name: "Now" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Message")).toBeHidden();
  await home.getByRole("link", { name: "NBIS · Is the NBIS recovery real?" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(home).toBeHidden();
  await expect(tabs.getByRole("tab", { name: "NBIS" })).toHaveAttribute("aria-selected", "true");
  await tabs.getByRole("tab", { name: "Now" }).click();
  await expect(home).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  expect(chats).toEqual([]);
});

test("Open threads says so when the read fails, and the button still works", async ({ page }) => {
  await page.route("**/copilot/threads", (route) => route.fulfill({ status: 503, json: { detail: "Copilot Lab is off." } }));
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.goto("/copilot-lab");
  const home = page.getByRole("region", { name: "Open threads" });
  await expect(home).toContainText("Open threads unavailable: Copilot Lab is off.");
  await expect(home.getByRole("button", { name: "What matters right now?" })).toBeEnabled();
});

test("no Open threads while the lab is off", async ({ page }) => {
  let reads = 0;
  await page.route("**/copilot/threads", (route) => { reads += 1; return route.fulfill({ json: THREADS }); });
  await page.goto("/copilot-lab");
  await expect(page.getByText(/Copilot Lab is off/)).toBeVisible(); // the e2e backend's own answer
  await expect(page.getByRole("region", { name: "Open threads" })).toHaveCount(0);
  expect(reads).toBe(0);
});
