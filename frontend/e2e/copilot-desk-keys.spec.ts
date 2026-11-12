import { expect, test, type Page } from "@playwright/test";
import { openDeskThreads } from "./desk-fixtures";

// The desk's keyboard (the ⌘K palette, J / K through the threads, N for a plan, [ for the thread list) and the cockpit's
// frame: the top bar, the Needs-you strip, the book, the centre and the copilot, by the time of day and on a phone. Every lab route is stubbed in the browser (the e2e backend runs with the lab off), so no
// model runs and nothing here sends a turn.
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
const NOW = new Date("2026-10-23T15:00:00Z"); // 11:00 New York, a Friday
const epoch = (iso: string) => Date.parse(iso) / 1000;
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const DESK = {
  as_of: "2026-10-23T15:00:00Z", quotes_at: null, quote_issue: null,
  day: { phase: "regular", need_you: 1, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", decisions: "ok", radar: "ok", thesis: "ok", prep: "ok", week: "ok", phase: "ok" },
  threads: [
    row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "What matters right now? One turn across everything", tone: "muted" } }),
    row({ key: "week", group: "pinned", title: "Review my week", status: { text: "Planned vs unplanned, follow-through, exits", tone: "muted" } }),
    row({ key: `trade:${TRADE}`, group: "act", symbol: "NBIS", title: "NBIS 10/23/26 100C", instrument: "10/23/26 100C",
      value: { text: "+$180.00", tone: "gain" }, status: { text: "1.0% from invalidation 92.30", tone: "attention" }, investigation_id: NBIS, trade_id: TRADE,
      book: { usd: 180, pct: 29, expiry: "2026-10-23", days_held: 0, track: { last: 20, entry: 80, tone: "attention" }, state: "near_stop", stop_pct: -1.0 } }),
    row({ key: `plan:${CRWV}`, group: "near", symbol: "CRWV", title: "Fails at the gap", instrument: "short",
      value: { text: "Armed", tone: "muted" }, status: { text: "0.6% to entry 99.00", tone: "attention" }, investigation_id: CRWV }),
    row({ key: `radar:${EVENT}`, group: "new", symbol: "MU", title: "MU up 4.1% while SMH is up 0.6%", status: { text: "Radar · vs sector", tone: "info" },
      radar_event_id: EVENT, path: `/radar?event=${EVENT}`, changed_at: epoch("2026-10-23T14:12:00Z") }),
    row({ key: `plan:${APLD}`, group: "watch", symbol: "APLD", title: "APLD base breakout", instrument: "long",
      value: { text: "Armed", tone: "muted" }, status: { text: "Entry 31.00 · 3.3% away", tone: "muted" }, investigation_id: APLD }),
  ],
};
const SESSION = {
  as_of: "2026-10-23T15:00:00Z", now: epoch("2026-10-23T15:00:00Z"), day: "2026-10-23", phase: "regular",
  open: epoch("2026-10-23T13:30:00Z"), close: epoch("2026-10-23T20:00:00Z"),
  events: [
    { kind: "fill", at: epoch("2026-10-23T13:35:00Z"), symbol: "NBIS", text: "Bought NBIS" },
    { kind: "radar", at: epoch("2026-10-23T14:12:00Z"), symbol: "MU", text: "Radar · MU vs sector" },
    { kind: "ping", at: epoch("2026-10-23T14:31:00Z"), symbol: "NBIS", text: "Give-back ping · NBIS" },
    { kind: "decision", at: epoch("2026-10-23T14:44:00Z"), symbol: "NBIS", text: "NBIS · Holding" },
  ],
  time_stops: [{ symbol: "CRWV", at: epoch("2026-10-23T18:30:00Z"), clock: "14:30" }],
  pings: { sent: 14, held: 1, cap: null }, prep: { at: epoch("2026-10-23T12:30:00Z"), line: "NBIS 100C expires Friday." },
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }, { symbol: "QQQ", last: 500.2, change_pct: -0.31 }], quote_issue: null, realized_today: -120,
  sections: { hours: "ok", phase: "ok", fills: "ok", pings: "ok", radar: "ok", decisions: "ok", time_stops: "ok", prep: "ok", indices: "ok" },
};
const item = (fields: Record<string, unknown>) => ({
  has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null,
  setup: null, plan: null, mine: false, upcoming: false, ...fields,
});
const FEED = {
  as_of: "2026-10-23T15:00:00Z", now: epoch("2026-10-23T15:00:00Z"), day: "2026-10-23", total: 6,
  sources: { pings: "ok", plans: "ok", radar: "ok", "radar setups": "ok", brief: "ok", calendar: "ok", news: "ok", "market news": "unavailable" },
  unavailable: ["market news"],
  items: [
    item({ id: "alert:1", source: "Alert", at: epoch("2026-10-23T14:31:00Z"), symbol: "NBIS", text: "NBIS 100C give-back",
      detail: "Was +$610, now +$355.", href: "/copilot-lab?symbol=NBIS", plan: "own", mine: true }),
    item({ id: "news:1", source: "News", at: epoch("2026-10-23T14:20:00Z"), symbol: "NBIS", text: "Nebius signs a compute deal",
      publisher: "Benzinga", url: "https://news.example/nbis", href: "/copilot-lab?symbol=NBIS", mine: true }),
    item({ id: "copilot-note:brief", source: "Copilot note", at: epoch("2026-10-23T12:30:00Z"), text: "CPI is out at 8:30; SPY flat pre-market.",
      detail: "Morning brief", href: `/copilot-lab?investigation=${APLD}`, mine: true }),
    item({ id: "radar-setup:1", source: "Radar setup", at: epoch("2026-10-23T14:12:00Z"), symbol: "MU", text: "MU dip turning up",
      href: `/copilot-lab?symbol=MU&radar=${EVENT}`, radar_event_id: EVENT, plan: "setup",
      setup: { id: "s1", event_id: EVENT, words: "dip turning up", levels_line: "In near 100.00 · out below 98.50 (−1.5%)",
        contract_line: "Candidate: MU 10/30 100C · $2.10 × $2.20", record: "Your record on this setup: 7 trades, 4 up.", paper_record: null,
        plan_state: "none", investigation_id: null } }),
    item({ id: "news:2", source: "News", at: epoch("2026-10-23T13:50:00Z"), text: "Treasury yields climb before the jobs report",
      publisher: "Reuters", url: "https://news.example/yields" }),
    item({ id: "plan:stop", source: "Plan", at: epoch("2026-10-23T18:30:00Z"), symbol: "CRWV", text: "Time stop due 14:30",
      detail: "Your words: out by 14:30", investigation_id: CRWV, plan: "own", mine: true, upcoming: true }),
  ],
};
const SPARKS = { as_of: "2026-10-23T15:00:00Z", rows: { NBIS: { points: [93, 94, 93.6, 93.2], change_pct: 1.6 } }, spy_change_pct: 0.42 };
const PRACTICE = { goal: { label: "wait for the 15m close", week_start: "2026-10-19" }, this_week: { text: "3 of 5" } };
const saved = (id: string, symbol: string, answer: string) => ({
  id, source: "copilot", title: `${symbol} plan`, symbol, status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: `Plan a trade: ${symbol}` }, { role: "assistant", content: answer }],
});
const ANSWER: Record<string, [string, string]> = {
  [NBIS]: ["NBIS", "NBIS answer: hold above 92.30."], [CRWV]: ["CRWV", "CRWV answer: short under 99.00."], [APLD]: ["APLD", "APLD answer: enter at 31.00."],
};

async function lab(page: Page, { time = NOW, session = SESSION, threads = () => DESK as unknown, path = "/copilot-lab?view=briefing", showThreads = true, feed = FEED as unknown }: { time?: Date; session?: unknown; threads?(): unknown; path?: string; showThreads?: boolean; feed?: unknown } = {}) {
  const chats: unknown[] = [];
  await page.clock.install({ time });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: threads() }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: session }));
  await page.route("**/copilot/practice*", (route) => route.fulfill({ json: PRACTICE }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  for (const [id, [symbol, answer]] of Object.entries(ANSWER))
    await page.route(`**/copilot/investigations/${id}`, (route) => route.fulfill({ json: saved(id, symbol, answer) }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.route("**/copilot/desk/sparks?*", (route) => route.fulfill({ json: SPARKS }));
  await page.route("**/copilot/desk/feed", (route) => route.fulfill({ json: feed }));
  await page.route("**/copilot/desk/*/{picture,chart}*", (route) => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.goto(path);
  if (showThreads) await openDeskThreads(page);
  if (showThreads) await expect(page.getByRole("navigation", { name: "Thread list" }).getByTestId("desk-day")).toBeVisible();
  return { chats };
}

const palette = (page: Page) => page.getByRole("dialog", { name: "Jump to" });
const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });
/** A command from Jump to (⌘K): the time of day's actions (Arm today's plans, Close the day) live there, not on the desk. */
async function command(page: Page, name: string) {
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  await palette(page).getByRole("option", { name: new RegExp(`^${name}`) }).click();
}

test("⌘K opens the palette: type to filter, Enter opens the thread, Escape and a click outside close it", async ({ page }) => {
  const { chats } = await lab(page);
  await page.keyboard.press("ControlOrMeta+k");
  const box = palette(page);
  await expect(box).toBeVisible();
  const options = box.getByRole("option");
  // The thread list's rows in list order, tickers first and Main's Radar hits after (pinned rows are the commands), then the commands.
  await expect(options).toHaveText([/^NBIS/, /^CRWV/, /^APLD/, /^MU/, /^Plan a trade/, /^Review my week/, /^What matters right now\?/]);
  await expect(options.first()).toContainText("1.0% from invalidation 92.30");
  await expect(options.first()).toContainText("+$180.00");
  await page.keyboard.type("crw");
  await expect(options).toHaveText([/^CRWV/]);
  await page.keyboard.press("Enter");
  await expect(box).toBeHidden();
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible();

  // The desk bar's button opens it without a keyboard; arrows move, Escape closes, a click outside closes.
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  await expect(box).toBeVisible();
  await expect(box.getByRole("combobox")).toHaveValue("");
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Escape");
  await expect(box).toBeHidden();
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  await page.mouse.click(10, 10);
  await expect(box).toBeHidden();
  expect(chats).toEqual([]);
});

test("Plan a trade from the palette opens a new plan, unsent; after 16:00 Close the day fills the box", async ({ page }) => {
  const { chats } = await lab(page, { time: new Date("2026-10-23T21:00:00Z"), // 17:00 New York
    session: { ...SESSION, now: epoch("2026-10-23T21:00:00Z"), phase: "post", time_stops: [] } });
  await expect(page.getByTestId("desk-status")).toContainText("Closed 16:00");
  // Nothing left to review: Close the day is one quiet link under the day report (no count) and never the strip; the
  // palette's puts the question in the box.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("close-the-day")).toHaveText("Close the day →");
  await expect(page.getByTestId("needs-you")).toHaveCount(0);
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("close");
  await expect(palette(page).getByRole("option")).toHaveText([/^Close the day/]);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/^Close the day: /);
  await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
  await page.keyboard.press("ControlOrMeta+k"); // typing in the box: ignored
  await expect(palette(page)).toBeHidden();
  await page.getByRole("textbox", { name: "Message" }).blur();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(palette(page).getByRole("combobox")).toHaveValue(""); // the earlier search does not come back
  await page.keyboard.type("plan a");
  await page.keyboard.press("Enter");
  await page.waitForURL(/context=Plan\+a\+trade/);
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/Plan a trade:/);
  expect(chats).toEqual([]);
});

test("Threads stay out of the first view, open on request, and preserve a saved thread and unsent words", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { chats } = await lab(page, { showThreads: false });
  const rail = page.getByRole("navigation", { name: "Thread list" });
  const toggle = page.getByRole("button", { name: "Threads", exact: true }); // no count: the strip counts what needs him
  await expect(rail).toBeHidden();
  await toggle.click();
  await expect(rail).toBeVisible();
  await page.keyboard.press("j");
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  const message = page.getByRole("textbox", { name: "Message" });
  await message.fill("Keep this thought unsent");
  await toggle.click();
  await expect(rail).toBeHidden();
  await expect(message).toHaveValue("Keep this thought unsent");
  await page.screenshot({ path: test.info().outputPath("desk-conversation-rail-closed-1440.png") });
  await toggle.click();
  await expect(rail).toBeVisible();
  await expect(message).toHaveValue("Keep this thought unsent");
  expect(chats).toEqual([]);
});

test("an unsent draft stays with its saved thread when switching tickers", async ({ page }) => {
  const { chats } = await lab(page);
  const thread = conversation(page);
  const message = page.getByRole("textbox", { name: "Message" });
  await page.keyboard.press("j");
  await expect(thread.getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await message.fill("Recheck NBIS above the 92.30 invalidation.");

  await page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: /^CRWV/ }).click();
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(message).toHaveValue("");

  await page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: /^NBIS/ }).click();
  await expect(thread.getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await expect(message).toHaveValue("Recheck NBIS above the 92.30 invalidation.");
  expect(chats).toEqual([]);
});

test("sending a saved-thread draft clears it and switching back does not restore sent words", async ({ page }) => {
  await lab(page);
  const sent: unknown[] = [];
  const answer = [
    { type: "text", delta: "A fixed fixture reply." },
    { type: "done", metrics: { backend: "fake", evidence: "fixture", model: "fake-scripted", first_text_ms: 1, total_ms: 2,
      rounds: 1, tool_calls: [], usage: { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }, cost_usd: 0 } },
  ].map(event => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
  await page.route("**/copilot/chat", route => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: answer });
  });

  const thread = conversation(page);
  const message = page.getByRole("textbox", { name: "Message" });
  await page.keyboard.press("j");
  await expect(thread.getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await message.fill("Send this NBIS follow-up once.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(thread.getByText("A fixed fixture reply.")).toBeVisible();
  await expect(message).toHaveValue("");
  await page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: /^CRWV/ }).click();
  await page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: /^NBIS/ }).click();
  await expect(message).toHaveValue("");
  expect(sent).toHaveLength(1);
});

test("J and K open the next and previous thread in list order; keys typed in the message box are ignored", async ({ page }) => {
  const { chats } = await lab(page);
  const thread = conversation(page);
  // J and K step from the thread the desk has open, which it records just after the answer shows: each step waits for
  // the list to mark it open, or a fast next key would step from the one before.
  const open = (symbol: string) => expect(page.getByRole("navigation", { name: "Thread list" })
    .getByRole("button", { name: new RegExp(`^${symbol}, `) })).toHaveClass(/ring-1/);
  await page.keyboard.press("j");
  await expect(thread.getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await open("NBIS");
  await page.keyboard.press("j");
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible(); // an armed plan; the MU Radar row leaves the page, so J skips it
  await open("CRWV");
  await page.keyboard.press("j");
  await expect(thread.getByText("APLD answer: enter at 31.00.")).toBeVisible();
  await open("APLD");
  await page.keyboard.press("k");
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(page.getByRole("button", { name: "CRWV, Plan armed" })).toHaveClass(/ring-1/);

  const message = page.getByRole("textbox", { name: "Message" });
  await message.click();
  await page.keyboard.type("jk[n");
  await expect(message).toHaveValue(/jk\[n$/);
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible(); // still on CRWV
  await expect(page.getByRole("navigation", { name: "Thread list" })).toBeVisible(); // [ typed in the box: the list stays
  expect(page.url()).not.toContain("context=");
  expect(chats).toEqual([]);
});

test("the thread list is a drawer: [ and the top bar open it, Escape closes it, and the cockpit stays under it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await lab(page, { showThreads: false });
  const rail = page.getByRole("navigation", { name: "Thread list" });
  await expect(rail).toBeHidden();
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await page.keyboard.press("[");
  await expect(rail).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("desk-threads-drawer-1440.png") });
  await page.keyboard.press("Escape");
  await expect(rail).toBeHidden();
  await page.getByRole("button", { name: /^Threads(?:,|$)/ }).click();
  await expect(rail).toBeVisible();
  await page.getByRole("button", { name: "Close the thread list" }).click();
  await expect(rail).toBeHidden();
});

test("the phone has no desk tabs: Jump to opens a thread in the copilot sheet, and Back to the desk closes it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, { showThreads: false });
  await expect(page.getByRole("tablist", { name: "Desk" })).toHaveCount(0);
  await expect(page.getByTestId("desk-keys")).toBeHidden(); // no keyboard hint on a phone
  await expect(conversation(page)).toBeHidden(); // the copilot waits behind its button
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  await palette(page).getByRole("option", { name: /^APLD/ }).click();
  await expect(conversation(page).getByText("APLD answer: enter at 31.00.")).toBeVisible();
  await page.getByRole("button", { name: "Back to the desk" }).click();
  await expect(conversation(page)).toBeHidden();
  await page.getByRole("button", { name: /^Ask the copilot/ }).click();
  await expect(conversation(page).getByText("APLD answer: enter at 31.00.")).toBeVisible();
});

for (const [width, height] of [[1440, 900], [375, 812]] as const) {
  test(`the cockpit opens on the day: top bar, one item in the strip, the book, the chart and the copilot, at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const { chats } = await lab(page, { showThreads: false });
    // The top bar: live with the New York clock, the indices, realized today and the open positions' P&L.
    await expect(page.getByTestId("desk-status")).toContainText("Live · 11:00 ET");
    await expect(page.getByTestId("desk-indices")).toHaveText("SPY +0.42%QQQ −0.31%");
    await expect(page.getByTestId("desk-pnl")).toHaveText("Realized today −$120Open +$180");
    // The strip: only what needs a decision now. The option expiring today is one; a stop 1% away and a plan near its
    // entry are not (the book row and the thread list carry those). Nothing to dismiss, no rating asks.
    const strip = page.getByTestId("needs-you");
    await expect(strip.getByTestId("needs-you-title")).toHaveText("NBIS 10/23/26 100C expires today");
    await expect(strip).not.toContainText("+$180"); // the P&L and the stop distance are the book row's, not repeated here
    await expect(strip.getByRole("button")).toHaveText(["Open it"]);
    await expect(page.getByText(/to rate|Rate yesterday|alerts? to answer/)).toHaveCount(0);
    // The book: the followed position with its tag, expiry and plan track; the centre on it with its tiles.
    const book = page.getByTestId("desk-book");
    const nbis = book.getByRole("button", { name: "NBIS 10/23/26 100C" });
    await expect(nbis).toContainText("+$180+29%");
    await expect(nbis).toContainText("1.0% to stop");
    await expect(nbis).toContainText("expires today");
    await expect(nbis.getByTestId("book-state")).toHaveText("Near stop");
    await expect(nbis.getByRole("img", { name: "NBIS today" })).toBeVisible();
    // The tiles carry only what the row does not: the stock against SPY and time held.
    const tiles = page.getByTestId("desk-tiles");
    await expect(tiles).toHaveText("vs SPY today+1.2 ptsHeldtoday");
    await expect(page.getByTestId("desk-chart")).toContainText("Open in Charts →");
    // Mid-session the lower block is Since you looked (a first visit says so); no phase button.
    await expect(page.getByTestId("since-you-looked")).toContainText("First look from this browser");
    await expect(page.getByRole("button", { name: /Close the day|Arm today's plans/ })).toHaveCount(0);
    // The day's pings, Radar, news and calendar sit behind the centre's Feed tab: a grey count of what is new, mine first.
    await expect(page.getByTestId("feed-new")).toHaveText("5 new");
    await page.getByRole("tab", { name: "Feed" }).click();
    await expect(page.getByTestId("feed-item").first()).toContainText(/Alert\s*10:31\s*NBIS\s*NBIS 100C give-back/);
    await expect(page.getByTestId("feed-new")).toHaveCount(0); // looked at
    await page.getByRole("tab", { name: "Chart" }).click();
    await page.screenshot({ path: test.info().outputPath(`cockpit-session-${width}.png`), fullPage: width < 768 });

    // Selecting the position: beside the copilot it opens the thread at once; on a phone Ask the copilot does. Opening
    // it clears its strip item: nothing to click away.
    await nbis.click();
    await expect(nbis).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("needs-you")).toHaveCount(0);
    if (width < 768) {
      await expect(conversation(page)).toBeHidden();
      await page.getByRole("button", { name: /^Ask the copilot/ }).click();
    }
    await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible();
    await expect(conversation(page).getByRole("group", { name: "Suggestions" }).getByRole("button").first()).toHaveText("Why is it moving?");
    expect(chats).toEqual([]);
  });
}

/** Today's give-back alert on NBIS, as the session read lists it, and a card waiting on APLD. */
const ALERTED = { ...SESSION, to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: TRADE, symbol: "NBIS", contract: "NBIS 10/23/26 100C",
  kind: "giveback", at: epoch("2026-10-23T14:31:00Z"), today: true, feedback: null }] }, radar: null } };
const CARD = row({ key: `draft:${APLD}`, group: "draft", symbol: "APLD", title: "APLD base breakout", status: { text: "Alert at 31.00 to confirm", tone: "info" },
  investigation_id: APLD });

test("the strip shows the top decision and +N more lists every other at once, each with its answers; nothing is dismissed", async ({ page }) => {
  await lab(page, { showThreads: false, session: ALERTED, threads: () => ({ ...DESK, threads: [...DESK.threads, CARD] }) });
  const strip = page.getByTestId("needs-you");
  await expect(strip.getByTestId("needs-you-title")).toHaveText("NBIS 10/23/26 100C: give-back alert at 10:31 AM");
  await expect(strip.getByRole("button")).toHaveText(["Open it", "Ask why", "+2 more ▾"]);
  await strip.getByRole("button", { name: "+2 more ▾" }).click();
  const more = strip.getByTestId("needs-you-more");
  await expect(more).toHaveText([/^APLD: a card to confirm or dismissOpen the card$/, /^NBIS 10\/23\/26 100C expires todayOpen it$/]);
  // No Seen anywhere: nothing has to be clicked away to see the next.
  await expect(page.getByRole("button", { name: "Seen" })).toHaveCount(0);
  await expect(page.getByLabel("Seen")).toHaveCount(0);
  // Opening the card's thread clears its item; the rest stay.
  await more.filter({ hasText: "APLD" }).getByRole("button", { name: "Open the card" }).click();
  await expect(strip.getByRole("button", { name: /^\+1 more/ })).toBeVisible(); // the list stays open: "+1 more ▴"
  // A book of positions with no plan, no alert and nothing expiring today: no strip at all.
  await page.unroute("**/copilot/desk/threads");
  await page.unroute("**/copilot/desk/session");
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: { ...DESK, threads: [DESK.threads[0], unplanned("AMD", 40), unplanned("TSLA", -60)] } }));
  await page.reload();
  await expect(page.getByTestId("desk-book").getByRole("button", { name: /^AMD / })).toBeVisible();
  await expect(page.getByTestId("needs-you")).toHaveCount(0);
  await expect(page.getByTestId("desk-book").getByTestId("book-state")).toHaveCount(0); // and no "No plan" tags either
});

test("Ask why sends one turn about the strip's item, opening the copilot", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page, { showThreads: false, session: ALERTED });
  await page.getByTestId("needs-you").getByRole("button", { name: "Ask why" }).click();
  await expect.poll(() => chats.length).toBe(1);
  expect(JSON.stringify(chats[0])).toContain("Why is NBIS moving today?");
  await expect(conversation(page)).toBeVisible();
});

test("a held ticker with no conversation opens its desk view in one tap from the book; two positions on it sum in the list", async ({ page }) => {
  const aapl = (n: number, pnl: string, tone: string) => row({ key: `trade:aapl-${n}`, group: "watch", symbol: "AAPL", title: "AAPL 2/8/27 230C",
    instrument: "2/8/27 230C", value: { text: pnl, tone }, status: { text: "No plan yet", tone: "muted" }, trade_id: `aapl-${n}`,
    path: "/copilot-lab?symbol=AAPL&context=Plan%20this%20position%3A%20I%20just%20opened%20AAPL%202%2F8%2F27%20230C%20without%20a%20plan." });
  await lab(page, { threads: () => ({ ...DESK, threads: [...DESK.threads, aapl(1, "+$100.00", "gain"), aapl(2, "−$40.00", "loss")] }) });
  // The thread list's ticker shows both positions' P&L summed; the book lists each position.
  await expect(page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: /^AAPL, Held/ })).toContainText("+$60.00");
  await page.getByRole("button", { name: "Close the thread list" }).click(); // it sits over the book
  const rows = page.getByTestId("desk-book").getByRole("button", { name: /^AAPL/ });
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("No plan yet");
  // The row's link is followed in place: no server render, the address changes and the copilot starts its conversation.
  await rows.first().click();
  await expect(page).toHaveURL(/\/copilot-lab\?symbol=AAPL&context=Plan/);
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("AAPL›Decision");
  await expect(page.getByLabel("Message")).toHaveValue(/^Context: Plan this position/);
});

/** Held positions with no conversation: a book row each, whose link is the symbol's desk view with its plan question. */
const unplanned = (symbol: string, usd: number) => row({ key: `trade:${symbol}`, group: "watch", symbol, title: `${symbol} 11/20/26 50C`,
  instrument: "11/20/26 50C", value: { text: `+$${usd}.00`, tone: "gain" }, status: { text: "No plan yet", tone: "muted" }, trade_id: symbol,
  path: `/copilot-lab?symbol=${symbol}&context=${encodeURIComponent(`Plan this position: ${symbol} without a plan.`)}`,
  book: { usd, pct: 10, expiry: "2026-11-20", days_held: 2, track: null, state: "no_plan", stop_pct: null } });

/** Watch the desk for the rest of the page's life: was the book ever empty or reading, and did the desk remount? */
async function watchDesk(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { deskWatch: { emptied: number; root: Element | null; remounted: boolean } };
    w.deskWatch = { emptied: 0, root: document.querySelector("[data-sheet]"), remounted: false };
    const look = () => {
      const book = document.querySelector("[data-testid=desk-book]");
      if (!book || !book.querySelector("ul li") || /Reading positions/.test(book.textContent ?? "")) w.deskWatch.emptied++;
      if (document.querySelector("[data-sheet]") !== w.deskWatch.root) w.deskWatch.remounted = true;
    };
    new MutationObserver(look).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  return () => page.evaluate(() => (window as unknown as { deskWatch: { emptied: number; remounted: boolean } }).deskWatch);
}

test("selecting positions in the book switches the copilot in place: the book never reads again, Back and reload land on the right one", async ({ page }) => {
  let reads = 0;
  await lab(page, { showThreads: false, threads: () => { reads++; return { ...DESK, threads: [...DESK.threads, unplanned("AMD", 40), unplanned("TSLA", 60), unplanned("PLTR", 80)] }; } });
  const book = page.getByTestId("desk-book");
  await expect(book.getByRole("button", { name: /^PLTR / })).toBeVisible();
  const watched = await watchDesk(page);
  const before = reads;
  for (const symbol of ["AMD", "TSLA", "PLTR"]) {
    await book.getByRole("button", { name: new RegExp(`^${symbol} `) }).click();
    await expect(page).toHaveURL(new RegExp(`/copilot-lab\\?symbol=${symbol}&context=Plan`));
    await expect(page.getByTestId("desk-breadcrumb")).toHaveText(`${symbol}›Decision`);
    await expect(page.getByLabel("Message")).toHaveValue(`Context: Plan this position: ${symbol} without a plan.\n\n`);
  }
  // A saved conversation in between, then back to a position: the copilot follows (it used to stay on the conversation).
  await book.getByRole("button", { name: /^NBIS / }).click();
  await expect(page).toHaveURL(`/copilot-lab?thread=${NBIS}`);
  await expect(conversation(page)).toContainText("NBIS answer: hold above 92.30.");
  await book.getByRole("button", { name: /^PLTR / }).click();
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("PLTR›Decision");
  await expect(conversation(page)).not.toContainText("NBIS answer");
  expect(reads, "a click never reads the book again").toBe(before);
  expect(await watched()).toEqual({ emptied: 0, remounted: false, root: expect.anything() });

  // Back walks the same steps in place: the conversation, then each position.
  await page.goBack();
  await expect(page).toHaveURL(`/copilot-lab?thread=${NBIS}`);
  await expect(conversation(page)).toContainText("NBIS answer: hold above 92.30.");
  await page.goBack();
  await expect(page).toHaveURL(/symbol=PLTR&/);
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("PLTR›Decision");
  await page.goBack();
  await expect(page).toHaveURL(/symbol=TSLA&/);
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("TSLA›Decision");
  await expect(page.getByLabel("Message")).toHaveValue("Context: Plan this position: TSLA without a plan.\n\n");
  expect(reads).toBe(before);
  expect(await watched()).toMatchObject({ emptied: 0, remounted: false });
  // A reload lands on the same position, as a fresh load of its link.
  await page.reload();
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("TSLA›Decision");
  await expect(page.getByLabel("Message")).toHaveValue("Context: Plan this position: TSLA without a plan.\n\n");
  await expect(book.getByRole("button", { name: /^TSLA / })).toHaveAttribute("aria-pressed", "true");
});

test("Now in the top bar opens today's Main chat in place from a position", async ({ page }) => {
  const MAIN = "66666666-6666-4666-8666-666666666666";
  const main = { ...saved(MAIN, "", "Main answer: the day so far."), symbol: null, title: "Main chat", main_day: "2026-10-23" };
  await page.route("**/copilot/main-chat", (route) => route.fulfill({ json: main }));
  await page.route(`**/copilot/investigations/${MAIN}`, (route) => route.fulfill({ json: main }));
  await lab(page, { showThreads: false, path: "/copilot-lab?symbol=AMD", threads: () => ({ ...DESK, threads: [...DESK.threads, unplanned("AMD", 40)] }) });
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("AMD›Decision");
  // The book's first read has landed before the watch starts (its "Reading positions…" is not a reload).
  await expect(page.getByTestId("desk-book").getByRole("button", { name: /^AMD / })).toBeVisible();
  const watched = await watchDesk(page);
  await page.getByRole("link", { name: "Now" }).click();
  await expect(page).toHaveURL(`/copilot-lab?thread=${MAIN}`);
  await expect(conversation(page)).toContainText("Main answer: the day so far.");
  await expect(page.getByTestId("desk-breadcrumb")).toHaveCount(0);
  expect(await watched()).toMatchObject({ emptied: 0, remounted: false });
  // Already on Main chat, Now adds no step.
  const steps = await page.evaluate(() => history.length);
  await page.getByRole("link", { name: "Now" }).click();
  expect(await page.evaluate(() => history.length)).toBe(steps);
  await expect(page).toHaveURL(`/copilot-lab?thread=${MAIN}`);
  // A position picked in place, then the app menu's Desk (a plain link to the bare address): back on Main chat.
  await page.getByTestId("desk-book").getByRole("button", { name: /^AMD / }).click();
  await expect(page.getByTestId("desk-breadcrumb")).toHaveText("AMD›Decision");
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("link", { name: "Desk" }).first().click();
  await expect(page).toHaveURL(`/copilot-lab?thread=${MAIN}`);
  await expect(conversation(page)).toContainText("Main answer: the day so far.");
  await expect(page.getByTestId("desk-breadcrumb")).toHaveCount(0);
});

test("before the open the book's lower block is the morning brief alone, cut short; a closed day says so", async ({ page }) => {
  const lines = ["Verdict: Focus — Semis lead pre-market.", "- SPY +0.4% and SMH +1.1% before the open.", "- NBIS 100C expires Friday.",
    "- CRWV sits 0.6% under its entry.", "- APLD reports after the close.", "Changes if: SMH loses its gap."];
  const before = { ...SESSION, now: epoch("2026-10-23T12:45:00Z"), phase: "pre", events: [],
    prep: { at: epoch("2026-10-23T12:30:00Z"), line: lines[0], lines, fallback: false, path: null } };
  await lab(page, { time: new Date("2026-10-23T12:45:00Z"), session: before, showThreads: false }); // 8:45 New York
  await expect(page.getByTestId("desk-status")).toContainText("Pre-market · 8:45 ET");
  const brief = page.getByTestId("morning-brief");
  await expect(brief.getByRole("listitem")).toHaveCount(3);
  await expect(brief).not.toContainText("Changes if");
  await brief.getByRole("button", { name: "Read the whole brief ▾" }).click();
  await expect(brief.getByRole("listitem")).toHaveCount(4);
  await expect(brief).toContainText("Changes if: SMH loses its gap.");
  await expect(page.getByRole("button", { name: "Arm today's plans" })).toHaveCount(0); // in Jump to (⌘K), not a second button
  await expect(page.getByTestId("since-you-looked")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("cockpit-before-open-1280.png") });
  await page.unroute("**/copilot/desk/session");
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: { ...SESSION, phase: "closed", open: null, close: null, events: [], time_stops: [] } }));
  await page.reload();
  await expect(page.getByTestId("desk-status")).toContainText("Market closed");
});

test("the palette's phase commands follow the clock while the owner stays on the desk", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await lab(page, { time: new Date("2026-10-23T13:29:00Z"), showThreads: false });
  const open = async () => { await page.getByRole("button", { name: "Jump to a thread or command" }).click(); return palette(page).getByRole("option"); };
  await expect(await open()).toContainText([/^Arm today's plans/]);
  await page.keyboard.press("Escape");
  await page.clock.fastForward(61_000);
  await expect(await open()).not.toContainText([/^Arm today's plans/]);
  await page.keyboard.press("Escape");
  await page.clock.fastForward((6 * 60 + 30) * 60_000);
  await expect(await open()).toContainText([/^Close the day/]);
});

test("the copilot sits beside the cockpit from 1180 px and is a sheet below it; the message box stays reachable", async ({ page }) => {
  await lab(page, { showThreads: false, path: "/copilot-lab?view=new" });
  for (const width of [900, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const composer = page.getByRole("textbox", { name: "Message" });
    if (width < 1180) {
      await page.getByRole("button", { name: "Back to the desk" }).click(); // a new conversation opens on the sheet
      await expect(composer).toBeHidden();
      await page.getByRole("button", { name: /^Ask the copilot/ }).click();
    }
    await composer.scrollIntoViewIfNeeded();
    await expect(composer).toBeInViewport();
    if (width >= 1180) {
      const book = (await page.getByTestId("desk-book").boundingBox())!;
      const box = (await composer.boundingBox())!;
      expect(box.x).toBeGreaterThan(book.x + book.width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});

test("Arm today's plans is one tap from Jump to on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, { time: new Date("2026-10-23T12:00:00Z"), showThreads: false }); // 08:00 New York
  await command(page, "Arm today's plans");
  await expect(page.getByRole("region", { name: "Arm today's plans" })).toBeVisible();
});

test("Close the day is one tap from Jump to on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, { time: new Date("2026-10-23T21:00:00Z"), session: { ...SESSION, now: epoch("2026-10-23T21:00:00Z"), phase: "post", time_stops: [] }, showThreads: false });
  await command(page, "Close the day");
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/^Close the day: /);
});

test("before the open Arm today's plans is a checklist: still good logs, drop asks first, change fills the plan's box", async ({ page }) => {
  const DAY = "2026-10-23";
  const level = (price: number, extra: Record<string, unknown> = {}) => ({ price, condition: "crosses", interval: null, state: "armed", ...extra });
  const plan = (fields: Record<string, unknown>) => ({ instrument: null, thesis: null, horizon: "swing", last: null, entry: null, invalidation: null,
    time_stop: null, r: null, at: null, note: null, ...fields });
  const threads = () => ({ ...DESK, day: { ...DESK.day, phase: "pre" },
    threads: [...DESK.threads, row({ key: `thesis:${APLD}`, group: "new", symbol: "APLD", title: "APLD base breakout",
      status: { text: "Earnings · APLD reports after the close", tone: "info" }, investigation_id: APLD, changed_at: epoch("2026-10-23T12:00:00Z") })],
    plans: [
      plan({ stage: "armed", symbol: "APLD", investigation_id: APLD, instrument: "11/20/26 35C", entry: level(31, { distance_pct: 3.3 }),
        invalidation: level(29), time_stop: { text: "out by 15:30", due_at: epoch("2026-10-23T19:30:00Z"), state: "pending" },
        last_exit: { exited: "2026-10-21", followed: "partly", lesson: "Partly. Took half at the target, gave the rest back." } }),
      plan({ stage: "armed", symbol: "CRWV", investigation_id: CRWV, instrument: "short", entry: level(99), invalidation: level(103) }),
      plan({ stage: "in_position", symbol: "NBIS", investigation_id: NBIS, r: 0.4 }),
    ] });
  const { chats } = await lab(page, { time: new Date("2026-10-23T12:45:00Z"), threads, showThreads: false, // 8:45 New York
    session: { ...SESSION, now: epoch("2026-10-23T12:45:00Z"), phase: "pre", events: [], time_stops: [] } });
  const entries: Record<string, unknown>[] = [];
  const removed: string[] = [];
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries, trade_plans: {} } }));
  await page.route(`**/day-journal/${DAY}/entries`, (route) => {
    const body = route.request().postDataJSON();
    const saved = { id: `e${entries.length}`, day: DAY, not_traded: false, created_at: "2026-10-23T12:46:00Z", actor: "owner", symbol: null, ...body };
    entries.push(saved);
    return route.fulfill({ json: saved });
  });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { phone: true, alerts: [
    { id: "a1", symbol: "CRWV", price: 99, source_id: CRWV, plan_role: "entry", state: "active", condition: "crosses" }] } }));
  await page.route("**/charts/alerts/a1", (route) => { removed.push(route.request().method()); return route.fulfill({ json: { alerts: [], phone: true } }); });

  const arm = () => command(page, "Arm today's plans");
  await arm();
  const list = page.getByTestId("arm-checklist");
  await expect(list.getByTestId("arm-progress")).toHaveText("0 of 2 checked"); // the armed plans only
  const apld = list.getByRole("listitem", { name: "APLD" });
  await expect(apld).toContainText("Entry 31.00 · invalidation 29.00 · time stop 15:30");
  await expect(apld).toContainText("⚑ Earnings · APLD reports after the close");
  // The symbol's last answered exit review, in the owner's words; a plan with none shows no line.
  await expect(apld.getByLabel("Last APLD exit lesson")).toHaveText("Last APLD exit (Oct 21): partly followed · “Partly. Took half at the target, gave the rest back.”");
  await expect(list.getByRole("listitem", { name: "CRWV" }).getByLabel("Last CRWV exit lesson")).toHaveCount(0);
  await apld.getByRole("button", { name: "Still good" }).click();
  await expect(apld).toContainText("✓ Still good");
  await expect(list.getByTestId("arm-progress")).toHaveText("1 of 2 checked");
  expect(entries).toEqual([expect.objectContaining({ kind: "decision", symbol: "APLD", text: "Armed for today. Entry 31.00 · invalidation 29.00 · time stop 15:30." })]);

  const crwv = list.getByRole("listitem", { name: "CRWV" });
  await crwv.getByRole("button", { name: "Drop" }).click();
  await expect(crwv).toContainText("Its entry 99.00 alert is still armed. Remove it and mark the plan done?"); // the existing confirm
  expect(removed).toEqual([]);
  await crwv.getByRole("button", { name: "Remove alerts and mark done" }).click();
  await expect(crwv).toContainText("✓ Dropped");
  await expect(list.getByTestId("arm-progress")).toHaveText("2 of 2 checked");
  expect(removed).toEqual(["DELETE"]);
  expect(entries[1]).toEqual(expect.objectContaining({ kind: "plan_done", symbol: "CRWV", text: "Marked done" }));
  await page.screenshot({ path: test.info().outputPath("arm-checklist-1440.png") });

  // A reload reads Still good back from today's journal; Change opens the plan's thread with the question unsent.
  await page.reload();
  await arm();
  await expect(list.getByTestId("arm-progress")).toHaveText("1 of 2 checked");
  await list.getByRole("listitem", { name: "CRWV" }).getByRole("button", { name: "Change" }).click();
  await expect(list).toBeHidden();
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(
    "Change my CRWV plan before the open: Entry 99.00 · invalidation 103.00. What should change, and why?");

  // The old question is one link away.
  await arm();
  await list.getByRole("button", { name: "Ask the copilot instead" }).click();
  await expect(list).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/^Arm today's plans: /);
  expect(chats).toEqual([]);
});

test("the evening review ping's link (?close=1) opens the desk on Close the day", async ({ page }) => {
  const asking = () => ({ ...DESK, as_of: "2026-10-23T20:30:00Z", day: { phase: "post", need_you: 1, streak: null },
    threads: DESK.threads.map(r => r.symbol === "NBIS" ? { ...r, horizon: "swing", close: { kind: "position", question: "Review: did you follow the plan?", reviewed: null },
      status: { text: "Review: did you follow the plan?", tone: "attention" } } : r) });
  await page.route("**/today", (route) => route.fulfill({ json: { as_of: "2026-10-23T20:30:00Z", day: "2026-10-23", quotes_at: null, quote_issue: null,
    act_now: { state: "ok", rows: [], open_positions: 0 }, plans: { state: "ok", rows: [], armed: 0 }, new: {}, held: { state: "ok", rows: [], count: 0 }, week: { state: "unavailable" } } }));
  await page.route("**/copilot/symbol/*", (route) => route.fulfill({ json: { symbol: "NBIS", as_of: "2026-10-23T20:30:00Z", positions: { state: "ok", rows: [{ symbol: "NBIS" }] },
    plans: { state: "ok", rows: [] }, new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } }, quotes_at: null, quote_issue: null } }));
  await page.route("**/day-journal/2026-10-23", (route) => route.fulfill({ json: { day: "2026-10-23", entries: [], trade_plans: {} } }));
  const { chats } = await lab(page, { time: new Date("2026-10-23T20:30:00Z"), threads: asking, showThreads: false, path: "/copilot-lab?close=1", // 16:30 New York
    session: { ...SESSION, now: epoch("2026-10-23T20:30:00Z"), phase: "post", time_stops: [] } });
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible(); // the first unreviewed thread
  await expect(page.getByRole("region", { name: "Close of day" })).toContainText("Review: did you follow the plan?");
  expect(chats).toEqual([]);
});

test("the close link with nothing left to review, or before the close, opens the desk as usual", async ({ page }) => {
  await lab(page, { time: new Date("2026-10-23T20:30:00Z"), path: "/copilot-lab?close=1", // 16:30 New York, no close question
    session: { ...SESSION, now: epoch("2026-10-23T20:30:00Z"), phase: "post", time_stops: [] } });
  await expect(page.getByTestId("day-report")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  await expect(page).toHaveURL(/\/copilot-lab\?close=1$/);
  await page.clock.setSystemTime(NOW); // 11:00 New York
  await page.goto("/copilot-lab?close=1");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  await expect(page).toHaveURL(/\/copilot-lab\?close=1$/);
});

test("the close link with only an unanswered alert left asks nothing about it: ratings are optional", async ({ page }) => {
  const at = epoch("2026-10-23T20:30:00Z"); // 16:30 New York
  const to_answer = { alerts: { count: 1, rows: [{ id: "a1111111-1111-4111-8111-111111111111", trade_id: TRADE, symbol: "NBIS",
    contract: "NBIS 10/23/26 100C", kind: "giveback", at: at - 3600, today: true, feedback: null }] }, radar: null };
  const { chats } = await lab(page, { time: new Date(at * 1000), path: "/copilot-lab?close=1",
    session: { ...SESSION, now: at, phase: "post", time_stops: [], to_answer } });
  await expect(page.getByTestId("day-report")).toBeVisible();
  await expect(page.getByRole("region", { name: "Close the day" })).toHaveCount(0);
  await expect(page.getByText(/alerts? to answer|Radar hits? to rate/)).toHaveCount(0);
  expect(chats).toEqual([]);
});

test("after 16:00 Close the day walks each unreviewed thread: an answer or Skip opens the next, nothing is sent", async ({ page }) => {
  const DAY = "2026-10-23";
  const TSLA = "66666666-6666-4666-8666-666666666666";
  const entries: { kind: string; symbol: string; text: string }[] = [{ kind: "reflection", symbol: "APLD", text: "Entered at 31.00 as planned, sized half" }];
  const position = { kind: "position", question: "Review: did you follow the plan?" };
  const plan = { kind: "plan", question: "Added or not, and why?" };
  const planAsk = { kind: "plan_ask", question: "Want a plan for this?" }; // TSLA has no plan: asked once
  const asks: Record<string, typeof position> = { NBIS: position, TSLA: planAsk, CRWV: plan, APLD: plan };
  // The thread list after the close, as the server writes it: each row's question, or "Reviewed · …" once a reflection is saved.
  const threads = () => {
    const tsla = row({ key: `trade:${TSLA}`, group: "act", symbol: "TSLA", title: "TSLA", instrument: "stock", trade_id: TSLA,
      path: `/trades/${TSLA}`, status: { text: "", tone: "muted" } });
    return { ...DESK, as_of: "2026-10-23T21:00:00Z", day: { phase: "post", need_you: 2, streak: null },
      threads: [...DESK.threads.slice(0, 3), tsla, ...DESK.threads.slice(3)].map(r => {
        const ask = r.symbol ? asks[r.symbol as string] : undefined;
        if (!ask) return r;
        const text = entries.find(e => ["reflection", "plan_ask"].includes(e.kind) && e.symbol === r.symbol)?.text;
        const reviewed = text ? text.split(" ").slice(0, 6).join(" ") + "…" : null;
        return { ...r, close: { ...ask, reviewed }, status: reviewed ? { text: `Reviewed · ${reviewed}`, tone: "muted" } : { text: ask.question, tone: "attention" } };
      }) };
  };
  await page.route("**/today", (route) => route.fulfill({ json: { as_of: "2026-10-23T21:00:00Z", day: DAY, quotes_at: null, quote_issue: null,
    act_now: { state: "ok", rows: [], open_positions: 0 }, plans: { state: "ok", rows: [], armed: 0 }, new: {}, held: { state: "ok", rows: [], count: 0 }, week: { state: "unavailable" } } }));
  await page.route("**/copilot/symbol/*", (route) => {
    const symbol = route.request().url().split("/").pop()!;
    const held = asks[symbol]?.kind === "position";
    return route.fulfill({ json: { symbol, as_of: "2026-10-23T21:00:00Z", positions: { state: "ok", rows: held ? [{ symbol }] : [] },
      plans: { state: "ok", rows: held ? [] : [{ symbol, position: "waiting" }] }, new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } },
      quotes_at: null, quote_issue: null } });
  });
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: entries.map((e, i) => ({ id: `e${i}`, day: DAY,
    operation_id: `op${i}`, not_traded: false, actor: "owner", created_at: "2026-10-23T20:30:00Z", ...e })), trade_plans: {} } }));
  const posts: { kind: string; symbol: string; text: string }[] = [];
  await page.route(`**/day-journal/${DAY}/entries`, (route) => {
    const body = route.request().postDataJSON();
    posts.push(body);
    entries.push(body);
    return route.fulfill({ json: { id: `new-${posts.length}`, day: DAY, not_traded: false, actor: "owner", created_at: "2026-10-23T21:01:00Z", ...body } });
  });
  const { chats } = await lab(page, { time: new Date("2026-10-23T21:00:00Z"), threads, // 17:00 New York, a Friday
    session: { ...SESSION, now: epoch("2026-10-23T21:00:00Z"), phase: "post", time_stops: [] } });
  const rail = page.getByRole("navigation", { name: "Thread list" });
  await expect(rail.getByRole("button", { name: /^NBIS, / })).toContainText("Review: did you follow the plan?");
  await expect(rail.getByRole("button", { name: /^CRWV, / })).toContainText("Added or not, and why?");
  await expect(rail.getByRole("button", { name: /^APLD, / })).toContainText("Reviewed · Entered at 31.00 as planned, sized…");
  await page.screenshot({ path: test.info().outputPath("close-the-day-1440.png") });

  const review = page.getByRole("region", { name: "Close of day" });
  await page.getByRole("button", { name: "Close the thread list" }).click();
  await command(page, "Close the day");
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible(); // the first unreviewed thread
  await expect(review).toContainText("Review: did you follow the plan?");
  await review.getByRole("button", { name: "Answer" }).click();
  await review.getByRole("textbox").fill("Held above 92.30 all day, as planned.");
  await review.getByRole("button", { name: "Save" }).click();
  // TSLA has no conversation and no plan: it opens by its symbol, on "Want a plan for this?".
  await page.waitForURL(/\/copilot-lab\?symbol=TSLA$/);
  await expect(review).toContainText("Want a plan for this?");
  await openDeskThreads(page); // a page load: the drawer starts closed
  await expect(rail.getByRole("button", { name: /^NBIS, / })).toContainText("Reviewed · Held above 92.30 all day, as…");
  await review.getByRole("button", { name: "Not now" }).click();
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(review).toContainText("Added or not, and why?");
  await expect(rail.getByRole("button", { name: /^TSLA, / })).toContainText("Reviewed · No plan for now");
  await review.getByRole("button", { name: "Skip" }).click();
  await expect(review).toHaveCount(0);
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible(); // the last one: the pass ends here
  await expect(page.getByTestId("needs-you").getByText(/Close the day/)).toHaveCount(0); // the strip may be absent

  await page.keyboard.press("j"); // J / K still walk the threads
  await expect(conversation(page).getByText("APLD answer: enter at 31.00.")).toBeVisible();
  expect(posts).toEqual([expect.objectContaining({ kind: "reflection", symbol: "NBIS", text: "Held above 92.30 all day, as planned." }),
    expect.objectContaining({ kind: "plan_ask", symbol: "TSLA", text: "No plan for now" })]);
  expect(chats).toEqual([]);
});

test("after the close questions, Close the day asks only the fills to link, never today's alerts or Radar hits", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const DAY = "2026-10-23";
  const at = epoch("2026-10-23T21:00:00Z"); // 17:00 New York, a Friday
  const AMD = "77777777-7777-4777-8777-777777777777";
  const PLAN = "aaaaaaaa-0000-4000-8000-000000000003";
  const GIVEBACK = { id: "a1111111-1111-4111-8111-111111111111", trade_id: TRADE, symbol: "NBIS", contract: "NBIS 10/23/26 100C",
    kind: "giveback", at: at - 3600, today: true, feedback: null };
  const ANSWERED = { ...GIVEBACK, id: "a2222222-2222-4222-8222-222222222222", kind: "hold_hour", at: at - 7200,
    feedback: { rating: "already_aware", reason: null, version: 1, created_at: at - 7000, updated_at: at - 7000 } };
  const OLDER = { ...GIVEBACK, id: "a3333333-3333-4333-8333-333333333333", at: at - 86400 * 3, today: false }; // not today: not asked
  const HIT = `rv1-${DAY}-sec-mu-up-1`;
  const to_answer = { alerts: { count: 2, rows: [GIVEBACK, ANSWERED, OLDER] },
    radar: { count: 1, rows: [{ event_id: HIT, symbol: "MU", kind: "vs sector", at: at - 1800, today: true, rating: null }] } };
  const threads = () => ({ ...DESK, as_of: "2026-10-23T21:00:00Z", day: { phase: "post", need_you: 1, streak: null },
    threads: [...DESK.threads.map(r => r.symbol === "NBIS" ? { ...r, close: { kind: "position", question: "Review: did you follow the plan?", reviewed: null },
      status: { text: "Review: did you follow the plan?", tone: "attention" } } : r),
    row({ key: `trade:${AMD}`, group: "watch", symbol: "AMD", title: "AMD 10/23/26 150C", instrument: "10/23/26 150C", trade_id: AMD,
      path: "/copilot-lab?symbol=AMD", fill_to_link: AMD, status: { text: "Fill to link", tone: "attention" } })] });
  await page.route("**/today", (route) => route.fulfill({ json: { as_of: "2026-10-23T21:00:00Z", day: DAY, quotes_at: null, quote_issue: null,
    act_now: { state: "ok", rows: [], open_positions: 0 }, plans: { state: "ok", rows: [], armed: 0 }, new: {}, held: { state: "ok", rows: [], count: 0 }, week: { state: "unavailable" } } }));
  await page.route("**/copilot/symbol/*", (route) => route.fulfill({ json: { symbol: "NBIS", as_of: "2026-10-23T21:00:00Z",
    positions: { state: "ok", rows: [{ symbol: "NBIS" }] }, plans: { state: "ok", rows: [] }, new: { radar: { state: "off" }, thesis: { state: "ok", count: 0, rows: [] } },
    quotes_at: null, quote_issue: null } }));
  await page.route(`**/day-journal/${DAY}`, (route) => route.fulfill({ json: { day: DAY, entries: [], trade_plans: {} } }));
  const writes: string[] = [];
  await page.route("**/trades/*/phone-alerts/*/feedback", (route) => {
    const body = route.request().postDataJSON();
    writes.push(`alert ${route.request().url().split("/phone-alerts/")[1].split("/")[0]} ${body.rating}`);
    return route.fulfill({ json: { rating: body.rating, reason: body.reason, version: body.base_version + 1, created_at: at, updated_at: at } });
  });
  await page.route("**/radar/events/*/feedback", (route) => { writes.push("radar"); return route.fulfill({ json: { event_id: HIT, rating: "useful" } }); });
  await page.route(`**/trades/${AMD}/plan-link`, (route) => route.fulfill({ json: {
    trade: { id: AMD, ticker: "AMD", contract: "AMD 10/23/26 150C", status: "open", opened: "opened", fill: "1 at $3.10",
      opened_at: epoch("2026-10-23T14:31:00Z"), opened_at_reliable: true },
    candidates: [{ capture_id: PLAN, setup: "AMD breakout", mode: "discretionary", wording: "Entry: crosses 150.", note: null,
      received_at: epoch("2026-10-23T14:20:00Z"), timing: "pre_entry", investigation_id: null }], linked: [], plan_path: "/copilot-lab?symbol=AMD" } }));
  await page.route("**/charts/captures/*/link", (route) => { writes.push("link"); return route.fulfill({ json: {} }); });
  const { chats } = await lab(page, { time: new Date(at * 1000), threads, session: { ...SESSION, now: at, phase: "post", time_stops: [], to_answer } });
  // One close question and one fill to link; today's unanswered alert and Radar hit are not asked or counted.
  await page.getByRole("button", { name: "Close the thread list" }).click();
  const strip = page.getByTestId("needs-you");
  await expect(page.getByTestId("close-the-day")).toHaveText("Close the day · 2 to review →"); // the day report's link, not the strip
  await expect(strip.getByText(/Close the day/)).toHaveCount(0);
  await command(page, "Close the day");
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await page.getByRole("region", { name: "Close of day" }).getByRole("button", { name: "Skip" }).click();

  const pass = page.getByRole("region", { name: "Close the day" });
  await expect(pass.getByTestId("alert-answer")).toHaveCount(0);
  await expect(pass.getByTestId("close-pass-done")).toHaveText("0 of 2 done");
  await page.screenshot({ path: test.info().outputPath("close-the-day-fill-1440.png") });

  const fill = pass.getByRole("group", { name: "Fill to link" });
  await expect(fill).toContainText("Bought AMD 10/23/26 150C");
  await fill.getByRole("button", { name: "No plan" }).click();
  await expect(pass).toHaveCount(0); // the last one ends the pass
  expect(writes).toEqual([]);
  expect(chats).toEqual([]);
});

test("the palette finds a saved conversation that is not on the list, by what it was about", async ({ page }) => {
  await lab(page);
  const old = "00000000-0000-4000-8000-000000000009";
  await page.route("**/copilot/investigations?*", (route) => {
    const q = new URL(route.request().url()).searchParams.get("q");
    route.fulfill({ json: { investigations: q === "roll" ? [{ id: old, source: "copilot", title: "OKLO roll to March", symbol: "OKLO", status: "closed", conclusion: null,
      revision: 1, message_count: 2, has_findings: false, created_at: "2026-02-03T15:00:00Z", updated_at: "2026-02-03T15:00:00Z" }] : [] } });
  });
  await page.route(`**/copilot/investigations/${old}`, (route) => route.fulfill({ json: saved(old, "OKLO", "OKLO answer: rolled.") }));
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("roll");
  const hit = palette(page).getByRole("option", { name: /OKLO roll to March/ });
  await expect(hit).toContainText("Closed");
  await hit.click();
  await expect(conversation(page).getByText("OKLO answer: rolled.")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("zzzz");
  await expect(palette(page).getByText("Nothing matches.")).toBeVisible();
});

for (const width of [1440, 375] as const) {
  test(`the Feed: Mine, Market and both; a symbol's story; Ask puts the item in its thread's box; Plan it only on his own items and a setup card, at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
    const { chats } = await lab(page, { showThreads: false });
    const centre = page.getByRole("region", { name: "Chart and feed" });
    await centre.getByRole("tab", { name: "Feed" }).click();
    const feed = centre.getByTestId("desk-feed");
    const rows = feed.getByTestId("feed-item");
    // Mine (the default): his alert, a headline on his name, his brief, then what is ahead under Coming up.
    await expect(rows.getByTestId("feed-source")).toHaveText(["Alert", "News", "Copilot note", "Plan"]);
    await expect(rows.nth(3)).toContainText(/Coming up\s*Plan\s*14:30\s*CRWV/);
    await expect(rows.nth(0).getByRole("button", { name: "Plan it" })).toBeVisible();
    await expect(rows.nth(1).getByRole("button", { name: "Plan it" })).toHaveCount(0); // never on news
    await expect(rows.nth(1).getByRole("link", { name: /Read at Benzinga/ })).toHaveAttribute("href", "https://news.example/nbis");
    await expect(rows.nth(1).getByRole("link", { name: /Read at Benzinga/ })).toHaveAttribute("target", "_blank");
    await expect(rows.nth(0).getByRole("link", { name: "Open in Charts" })).toHaveAttribute("href", "/charts?symbol=NBIS");
    await expect(feed).not.toContainText("Could not read"); // a source that failed is left out quietly
    await expect(feed.getByText(/\b(buy|sell|hold)\b/i)).toHaveCount(0); // facts, never orders
    await expect(feed.getByRole("button", { name: "Chatter" })).toHaveCount(0); // no chatter source: no filter
    // Market: the Radar setup card with its level, contract and his record, and the market headline.
    await feed.getByRole("button", { name: "Market", exact: true }).click();
    await expect(rows.getByTestId("feed-source")).toHaveText(["Radar setup", "News"]);
    const setup = rows.nth(0).getByTestId("feed-setup");
    await expect(setup).toContainText("In near 100.00 · out below 98.50");
    await expect(setup).toContainText("Candidate: MU 10/30 100C");
    await expect(setup).toContainText("Your record on this setup: 7 trades, 4 up.");
    await expect(rows.nth(1).getByRole("button", { name: "Plan it" })).toHaveCount(0);
    await feed.getByRole("button", { name: "Mine + Market" }).click();
    await expect(rows).toHaveCount(6);
    if (width >= 768) await page.screenshot({ path: test.info().outputPath(`desk-feed-${width}.png`) });
    else await page.screenshot({ path: test.info().outputPath(`desk-feed-${width}.png`), fullPage: true });
    // A symbol: only its story, and a way back.
    await rows.nth(0).getByRole("button", { name: "NBIS", exact: true }).click();
    await expect(rows.getByTestId("feed-source")).toHaveText(["Alert", "News"]);
    await feed.getByRole("button", { name: "All items" }).click();
    await expect(rows).toHaveCount(6);
    // Ask the copilot about the headline: NBIS's own thread, the item quoted in the box, nothing sent.
    await rows.nth(1).getByRole("button", { name: "Ask the copilot" }).click();
    await expect(conversation(page).getByLabel("Message")).toHaveValue(/^About the Benzinga headline on NBIS \(10:20\), quoted: "Nebius signs a compute deal"\./);
    expect(chats).toEqual([]);
    if (width < 768) await page.getByRole("button", { name: "Back to the desk" }).click();
    // Plan it on the setup card opens the desk's Radar card, which has the setup's own Plan it.
    await feed.getByRole("button", { name: "Plan it" }).nth(1).click();
    await expect(page).toHaveURL(`/copilot-lab?symbol=MU&radar=${EVENT}`);
    expect(chats).toEqual([]);
  });
}

// The Feed's chatter block (app/engine/chatter.py): buzz and rising posts from r/wallstreetbets and NYT headlines.
const CHATTER = {
  sources: { "r/wallstreetbets": "on", NYT: "unavailable" },
  buzz: [{ symbol: "NBIS", count: 9, usual: 1.5, multiple: 6.2, history: true, held: true },
    { symbol: "RKLB", count: 4, usual: 0, multiple: null, history: true, held: false }],
  record: "Your entries during a mention spike: 12 closed trades, 5 up, net −$1,240.",
  items: [
    item({ id: "r/wallstreetbets:buzz:NBIS", source: "r/wallstreetbets", at: epoch("2026-10-23T15:00:00Z"), symbol: "NBIS",
      text: "NBIS mentioned 6.2× its usual rate in the last hour",
      detail: "9 posts in the last hour; usually 1.5 at this hour. Your entries during a mention spike: 12 closed trades, 5 up, net −$1,240.",
      publisher: "r/wallstreetbets", url: "https://www.reddit.com/r/wallstreetbets/search/?q=NBIS&restrict_sr=1&sort=new", chatter: true }),
    item({ id: "r/wallstreetbets:post:rise1", source: "r/wallstreetbets", at: epoch("2026-10-23T14:40:00Z"), symbol: "NBIS",
      text: "NBIS 105c 11/14, all in before the compute deal", detail: "1,240 points · 341 comments", publisher: "r/wallstreetbets",
      url: "https://www.reddit.com/r/wallstreetbets/comments/rise1/x/", chatter: true }),
    item({ id: "nyt:1", source: "NYT", at: epoch("2026-10-23T13:10:00Z"), text: "Chipmakers brace for new export rules",
      detail: "A draft rule would widen limits on advanced chip sales.", publisher: "NYT",
      url: "https://www.nytimes.com/2026/10/23/business/chips.html", chatter: true }),
  ],
};

for (const width of [1440, 375] as const) {
  test(`Chatter: its own filter only, buzz chips outlined when held, his spike record, only Ask and the link, at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
    const { chats } = await lab(page, { showThreads: false, feed: { ...FEED, chatter: CHATTER } });
    // The tab's new count is the feed's own items only: chatter never counts.
    await expect(page.getByTestId("feed-new")).toHaveText("5 new");
    const centre = page.getByRole("region", { name: "Chart and feed" });
    await centre.getByRole("tab", { name: "Feed" }).click();
    const feed = centre.getByTestId("desk-feed");
    const rows = feed.getByTestId("feed-item");
    // Mine, Market and both never show chatter.
    await expect(rows.getByTestId("feed-source")).toHaveText(["Alert", "News", "Copilot note", "Plan"]);
    await feed.getByRole("button", { name: "Mine + Market" }).click();
    await expect(rows).toHaveCount(6);
    await expect(rows.getByTestId("feed-source")).not.toContainText(["r/wallstreetbets"]);
    await feed.getByRole("button", { name: "Chatter" }).click();
    await expect(rows.getByTestId("feed-source")).toHaveText(["r/wallstreetbets", "r/wallstreetbets", "NYT"]);
    const chips = feed.getByTestId("buzz-chip");
    await expect(chips).toHaveText(["NBIS 6.2×", "RKLB 4, usually none"]);
    await expect(chips.nth(0)).toHaveAttribute("data-held", "true");
    await expect(chips.nth(1)).not.toHaveAttribute("data-held", "true");
    await expect(rows.nth(0)).toContainText("Your entries during a mention spike: 12 closed trades, 5 up, net −$1,240.");
    await expect(rows.locator('[aria-label="new"]')).toHaveCount(0); // chatter is never "new"
    await expect(feed.getByTestId("feed-chatter-note")).toHaveText("NYT could not be read.");
    // Only Ask the copilot and the outbound link: no Plan it, no Open in Charts, no symbol story.
    await expect(rows.getByRole("button", { name: "Plan it" })).toHaveCount(0);
    await expect(rows.getByRole("link", { name: "Open in Charts" })).toHaveCount(0);
    await expect(rows.getByRole("button", { name: "NBIS", exact: true })).toHaveCount(0);
    await expect(rows.nth(1).getByRole("link", { name: /Open on Reddit/ })).toHaveAttribute("href", "https://www.reddit.com/r/wallstreetbets/comments/rise1/x/");
    await expect(rows.nth(1).getByRole("link", { name: /Open on Reddit/ })).toHaveAttribute("target", "_blank");
    await expect(rows.nth(2).getByRole("link", { name: /Read at NYT/ })).toHaveAttribute("href", "https://www.nytimes.com/2026/10/23/business/chips.html");
    if (width >= 768) await page.screenshot({ path: test.info().outputPath(`desk-chatter-${width}.png`) });
    else await page.screenshot({ path: test.info().outputPath(`desk-chatter-${width}.png`), fullPage: true });
    // Ask quotes the post as posted, unsent.
    await rows.nth(1).getByRole("button", { name: "Ask the copilot" }).click();
    await expect(conversation(page).getByLabel("Message")).toHaveValue(/^About this r\/wallstreetbets item \(10:40, NBIS\), quoted as posted: "NBIS 105c 11\/14, all in before the compute deal"\./);
    expect(chats).toEqual([]);
  });
}

test("Chatter that is on but has nothing yet: no filter, and nothing about it outside its filter", async ({ page }) => {
  await lab(page, { showThreads: false, feed: { ...FEED, chatter: { ...CHATTER, sources: { "r/wallstreetbets": "on", NYT: "not set up" }, buzz: [], record: null, items: [] } } });
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await centre.getByRole("tab", { name: "Feed" }).click();
  const feed = centre.getByTestId("desk-feed");
  await expect(feed.getByRole("button", { name: "Chatter" })).toHaveCount(0);
  await expect(feed.getByTestId("feed-chatter-note")).toHaveCount(0);
  await expect(feed).not.toContainText(/chatter|wallstreetbets/i);
});
