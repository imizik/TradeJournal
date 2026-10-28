import { expect, test, type Page } from "@playwright/test";

// The desk's thread list: one grouped list from GET /copilot/desk/threads. Every lab route is stubbed in the browser (the
// e2e backend runs with the lab off), so no model runs and opening the list sends nothing.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NBIS = "11111111-1111-4111-8111-111111111111";
const CRWV = "22222222-2222-4222-8222-222222222222";
const APLD = "44444444-4444-4444-8444-444444444444";
const TRADE = "55555555-5555-4555-8555-555555555555";
const EVENT = "radar-mu-1";
const NOW = new Date("2026-10-23T15:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const DESK = {
  as_of: "2026-10-23T15:00:00Z", quotes_at: epoch("2026-10-23T14:59:50Z"), quote_issue: null,
  day: { phase: "regular", need_you: 1, streak: { current: 4, best: 6 } },
  sections: { positions: "ok", plans: "ok", investigations: "ok", decisions: "ok", radar: "ok", thesis: "ok", prep: "ok", week: "ok", phase: "ok" },
  threads: [
    row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Prep: NBIS 100C expires Friday.", tone: "info" } }),
    row({ key: "week", group: "pinned", title: "Review my week", status: { text: "3 of 5 entries planned this week", tone: "muted" } }),
    row({ key: `trade:${TRADE}`, group: "act", symbol: "NBIS", title: "NBIS 10/23/26 100C", instrument: "10/23/26 100C",
      value: { text: "+$180.00", tone: "gain" }, status: { text: "1.0% from invalidation 92.30", tone: "attention" },
      meter: { last: 20, entry: 80, tone: "attention" }, investigation_id: NBIS, trade_id: TRADE }),
    row({ key: `plan:${CRWV}`, group: "near", symbol: "CRWV", title: "Fails at the gap; group rolling over", instrument: "short",
      value: { text: "Armed", tone: "muted" }, status: { text: "0.6% to entry 99.00", tone: "attention" },
      meter: { last: 71.4, entry: 80, tone: "attention" }, investigation_id: CRWV }),
    row({ key: `radar:${EVENT}`, group: "new", symbol: "MU", title: "MU up 4.1% while SMH is up 0.6%", status: { text: "Radar · vs sector", tone: "info" },
      radar_event_id: EVENT, path: `/radar?event=${EVENT}`, changed_at: epoch("2026-10-23T14:12:00Z") }),
    row({ key: `plan:${APLD}`, group: "watch", symbol: "APLD", title: "APLD base breakout", instrument: "long",
      value: { text: "Armed", tone: "muted" }, status: { text: "Entry 31.00 · 3.3% away", tone: "muted" },
      meter: { last: 40, entry: 80, tone: "muted" }, investigation_id: APLD }),
  ],
};
const QUIET = { ...DESK, day: { phase: "closed", need_you: 0, streak: null }, threads: DESK.threads.slice(0, 2) };
const saved = {
  id: NBIS, source: "copilot", title: "NBIS plan", symbol: "NBIS", status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: "Plan a trade: NBIS" }, { role: "assistant", content: "Plan: enter above 95.90, out under 92.30." }],
};

async function lab(page: Page, desk: unknown = DESK) {
  const chats: unknown[] = [];
  let reads = 0;
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => { reads += 1; return route.fulfill({ json: desk }); });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.route(`**/copilot/investigations/${NBIS}`, (route) => route.fulfill({ json: saved }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto("/copilot-lab");
  return { chats, reads: () => reads };
}

const list = (page: Page) => page.getByRole("navigation", { name: "Thread list" });

test("the groups read in desk order, meters only on Act now and Near a trigger, and the list refreshes each minute", async ({ page }) => {
  const { chats, reads } = await lab(page);
  const threads = list(page);
  await expect(threads.getByTestId("desk-day")).toHaveText("Market open · 1 needs you · plan streak 4");
  const titles = await threads.locator("section h3").allTextContents();
  expect(titles).toEqual(["Pinned", "Act now", "Near a trigger", "New since you looked", "Watching"]); // no empty Waiting for you

  const act = threads.getByRole("region", { name: "Act now" });
  const nbis = act.getByRole("link", { name: "NBIS 10/23/26 100C" });
  await expect(nbis).toContainText("+$180.00");
  await expect(nbis).toContainText("1.0% from invalidation 92.30");
  await expect(nbis.getByRole("img")).toHaveAttribute("aria-label", "Underlying 20% of the way from the invalidation; entry at 80%");
  await expect(threads.getByRole("region", { name: "Near a trigger" }).getByRole("img")).toHaveCount(1);
  const watching = threads.getByRole("region", { name: "Watching" });
  await expect(watching).toContainText("Entry 31.00 · 3.3% away");
  await expect(watching.getByRole("img")).toHaveCount(0); // a watched plan carries no meter
  await expect(threads.getByRole("region", { name: "Pinned" })).toContainText("Prep: NBIS 100C expires Friday.");
  // A number sets in the mono face; a word never does.
  await expect(nbis.getByText("+$180.00")).toHaveClass(/tabular-nums/);
  await expect(threads.getByRole("region", { name: "Near a trigger" }).getByText("Armed")).not.toHaveClass(/tabular-nums/);
  expect(reads()).toBe(1);
  await page.screenshot({ path: test.info().outputPath("thread-list-desktop.png") });

  await page.clock.fastForward(61_000);
  await expect.poll(reads).toBe(2);
  expect(chats).toEqual([]);
});

test("a row with an investigation opens it in place; a Radar row links to its event", async ({ page }) => {
  const { chats } = await lab(page);
  const threads = list(page);
  await expect(threads.getByRole("link", { name: "MU MU up 4.1% while SMH is up 0.6%" })).toHaveAttribute("href", `/radar?event=${EVENT}`);
  const nbis = threads.getByRole("link", { name: "NBIS 10/23/26 100C" });
  await expect(nbis).toHaveAttribute("href", `/copilot-lab?investigation=${NBIS}`);
  await nbis.click();
  await expect(page.getByText("Plan: enter above 95.90, out under 92.30.")).toBeVisible();
  await expect(threads).toBeVisible(); // the desk keeps the list beside the open conversation
  await expect(nbis).toHaveClass(/ring-1/); // the open thread is marked
  expect(chats).toEqual([]);
});

test("new since you looked is remembered in this browser", async ({ page }) => {
  await lab(page);
  const fresh = list(page).getByRole("region", { name: "New since you looked" });
  await expect(fresh).toContainText("New:");
  await fresh.getByRole("button", { name: "Mark seen" }).click();
  await expect(fresh).not.toContainText("New:");
  await page.reload();
  await expect(fresh.getByRole("link")).toHaveCount(1); // still listed, no longer marked new
  await expect(fresh).not.toContainText("New:");
  await expect(fresh.getByRole("button", { name: "Mark seen" })).toHaveCount(0);
});

test("a quiet day: Act now says it is clear, and Plan a trade is one tap away", async ({ page }) => {
  await lab(page, QUIET);
  const threads = list(page);
  await expect(threads.getByTestId("desk-day")).toHaveText("Market closed · Nothing needs you");
  await expect(threads.getByRole("region", { name: "Act now" })).toHaveText(/Clear\. Nothing needs a decision right now\./);
  await expect(threads.getByRole("link", { name: "Plan a trade" })).toHaveAttribute("href", /\/copilot-lab\?.*context=Plan\+a\+trade/);
});

test("an unavailable source says so, and Act now never claims clear without positions", async ({ page }) => {
  await lab(page, { ...QUIET, sections: { ...QUIET.sections, positions: "unavailable", radar: "unavailable" } });
  const threads = list(page);
  await expect(threads.getByRole("region", { name: "Act now" })).toContainText("Positions unavailable right now.");
  await expect(threads).toContainText("Unavailable right now: positions, Radar.");
});

test("the list fits a 375 px phone with thumb-sized rows", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const threads = list(page);
  for (const link of await threads.getByRole("link").all()) {
    const box = (await link.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
  }
  const ask = threads.getByRole("button", { name: "What matters right now?" });
  await expect(ask).toBeInViewport();
  expect((await ask.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("thread-list-375.png"), fullPage: true });
  expect(chats).toEqual([]);
});

test("no thread list while the lab is off", async ({ page }) => {
  let reads = 0;
  await page.route("**/copilot/desk/threads", (route) => { reads += 1; return route.fulfill({ json: DESK }); });
  await page.goto("/copilot-lab");
  await expect(page.getByText(/Copilot Lab is off/)).toBeVisible();
  await expect(list(page)).toHaveCount(0);
  expect(reads).toBe(0);
});
