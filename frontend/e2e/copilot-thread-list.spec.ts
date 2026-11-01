import { expect, test, type Page } from "@playwright/test";

// The desk's thread list: Main, then one row per ticker, regrouped from GET /copilot/desk/threads. Every lab route is stubbed in the browser (the
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

const summary = (id: string, symbol: string, status: string, updated: string) => ({ id, source: "copilot", title: `${symbol} reclaim`, symbol, status,
  conclusion: status === "closed" ? "Out at the invalidation; followed the plan." : null, revision: 2, message_count: 4, has_findings: false,
  created_at: updated, updated_at: updated });
const list = (page: Page) => page.getByRole("navigation", { name: "Thread list" });
const tickers = (page: Page) => list(page).getByRole("region", { name: "Tickers" });
const crumb = (page: Page) => page.getByTestId("desk-breadcrumb");

test("Main, then one row per ticker, needs-you first; meters only on Act now and Near a trigger; the list refreshes each minute", async ({ page }) => {
  const { chats, reads } = await lab(page);
  const threads = list(page);
  await expect(threads.getByTestId("desk-day")).toHaveText("1 needs you · plan streak 4");
  const main = threads.getByRole("region", { name: "Main" });
  await expect(main).toContainText("Prep: NBIS 100C expires Friday.");
  await expect(main).toContainText("1 Radar"); // Radar lives inside Main, not as a row
  await expect(tickers(page).getByRole("button")).toHaveText([/^NBIS/, /^CRWV/, /^APLD/]); // MU (Radar only) is no ticker
  const nbis = tickers(page).getByRole("button", { name: "NBIS, Held, needs you" });
  await expect(nbis).toContainText("+$180.00");
  await expect(nbis).toContainText("1.0% from invalidation 92.30");
  await expect(nbis.getByRole("img")).toHaveAttribute("aria-label", "Underlying 20% of the way from the invalidation; entry at 80%");
  await expect(tickers(page).getByRole("button", { name: "CRWV, Plan armed" }).getByRole("img")).toHaveCount(1); // near a trigger
  const apld = tickers(page).getByRole("button", { name: "APLD, Plan armed" });
  await expect(apld).toContainText("Entry 31.00 · 3.3% away");
  await expect(apld.getByRole("img")).toHaveCount(0); // a watched plan carries no meter
  // A number sets in the mono face; a word never does.
  await expect(nbis.getByText("+$180.00")).toHaveClass(/tabular-nums/);
  await expect(crumb(page)).toHaveText("Main");
  expect(reads()).toBe(1);
  await page.screenshot({ path: test.info().outputPath("thread-list-desktop.png") });

  await page.clock.fastForward(61_000);
  await expect.poll(reads).toBe(2);
  expect(chats).toEqual([]);
});

test("a ticker opens its conversation in place under a breadcrumb, and Main goes back to the Briefing without sending", async ({ page }) => {
  const { chats } = await lab(page);
  const nbis = tickers(page).getByRole("button", { name: "NBIS, Held, needs you" });
  await nbis.click();
  await expect(page.getByText("Plan: enter above 95.90, out under 92.30.")).toBeVisible();
  await expect(list(page)).toBeVisible(); // the desk keeps the list beside the open conversation
  await expect(nbis).toHaveClass(/ring-1/); // the open ticker is marked
  await expect(crumb(page)).toHaveText("NBIS›NBIS plan");
  await list(page).getByRole("region", { name: "Main" }).getByRole("button").click();
  await expect(crumb(page)).toHaveText("Main");
  await expect(page.getByText("Plan: enter above 95.90, out under 92.30.")).toHaveCount(0);
  expect(chats).toEqual([]);
});

test("a ticker with several conversations lists them as subthreads with their dates; one with a single conversation shows none", async ({ page }) => {
  await lab(page);
  const older = { ...saved, id: "33333333-3333-4333-8333-333333333333", title: "Trim into the gap?", updated_at: "2026-10-22T16:00:00Z",
    transcript: [{ role: "user", content: "Trim into the gap?" }, { role: "assistant", content: "Hold; the gap filled on volume." }] };
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [
    { ...saved, transcript: undefined }, { ...older, transcript: undefined },
    summary(CRWV, "CRWV", "open", "2026-10-22T18:00:00Z"),
  ] } }));
  await page.route(`**/copilot/investigations/${older.id}`, (route) => route.fulfill({ json: older }));
  await page.reload();
  await tickers(page).getByRole("button", { name: "NBIS, Held, needs you" }).click();
  const children = list(page).getByRole("list", { name: "NBIS threads" });
  await expect(children.getByRole("link")).toHaveText([/NBIS plan\s*Oct 23/, /Trim into the gap\?\s*Oct 22/]);
  await children.getByRole("link", { name: /Trim into the gap/ }).click();
  await expect(page.getByText("Hold; the gap filled on volume.")).toBeVisible();
  await expect(crumb(page)).toHaveText("NBIS›Trim into the gap?· Oct 22");

  await tickers(page).getByRole("button", { name: "CRWV, Plan armed" }).click();
  await expect(list(page).getByRole("list", { name: "CRWV threads" })).toHaveCount(0);
  await expect(children).toBeVisible(); // the ticker left stays as it was
});

test("a ticker's arrow shows or hides its subthreads without changing the conversation; older and closed ones fold away", async ({ page }) => {
  await lab(page);
  const talk = (n: number, status: string, day: string) => ({ ...summary(`33333333-3333-4333-8333-33333333333${n}`, "NBIS", status, `2026-10-${day}T16:00:00Z`), title: `NBIS talk ${n}` });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [
    { ...saved, transcript: undefined }, talk(1, "open", "22"), talk(2, "open", "21"), talk(3, "open", "20"), talk(4, "closed", "19"), talk(5, "closed", "18"),
    summary(CRWV, "CRWV", "open", "2026-10-22T18:00:00Z"), { ...summary(APLD, "CRWV", "open", "2026-10-21T18:00:00Z"), title: "CRWV again" },
  ] } }));
  await page.reload();
  const arrow = list(page).getByRole("button", { name: "Show NBIS threads" });
  await expect(arrow).toHaveText("6");
  await arrow.click();
  await expect(crumb(page)).toHaveText("Main"); // looked at, not opened
  const children = list(page).getByRole("list", { name: "NBIS threads" });
  await expect(children.getByRole("link")).toHaveText([/NBIS plan/, /NBIS talk 1/, /NBIS talk 2/]); // the newest open ones
  await children.getByRole("button", { name: /^Earlier/ }).click();
  await expect(children.getByRole("link", { name: /NBIS talk 3/ })).toBeVisible();
  await children.getByRole("button", { name: /^Closed/ }).click();
  await expect(children.getByRole("list", { name: "Closed" }).getByRole("link")).toHaveText([/NBIS talk 4/, /NBIS talk 5/]);
  await list(page).getByRole("button", { name: "Show CRWV threads" }).click();
  await expect(children).toBeVisible(); // any number stay open
  await expect(list(page).getByRole("list", { name: "CRWV threads" })).toBeVisible();
  await list(page).getByRole("button", { name: "Hide NBIS threads" }).click();
  await expect(children).toHaveCount(0);
  await expect(crumb(page)).toHaveText("Main");
});

test("Main stays pinned as the list scrolls, with only today's conversations under it and how many answers wait", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await lab(page);
  const loose = (n: number, day: string) => ({ ...summary(`66666666-6666-4666-8666-66666666666${n}`, "X", "open", `2026-10-${day}T16:00:00Z`), symbol: null, title: `About the market ${n}` });
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [loose(1, "23"), loose(2, "22"), loose(3, "21"), loose(4, "20")] } }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: { as_of: "2026-10-23T15:00:00Z", now: epoch("2026-10-23T15:00:00Z"), day: "2026-10-23", phase: "regular",
    open: null, close: null, events: [], time_stops: [], pings: null, prep: null, indices: [], quote_issue: null, sections: {}, to_answer: { alerts: { count: 2, rows: [] }, radar: { count: 1, rows: [] } } } }));
  await page.reload();
  const main = list(page).getByRole("region", { name: "Main" });
  await expect(main).toContainText("3 to answer");
  const under = list(page).getByRole("list", { name: "Main threads" });
  await expect(under.getByRole("link")).toHaveText([/About the market 1/]);
  await under.getByRole("button", { name: /^Earlier/ }).click();
  await expect(under.getByRole("link")).toHaveCount(4);
  await page.getByRole("complementary", { name: "Threads" }).evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await expect(main).toBeInViewport();
});

test("a long conversation opens on its latest question; the ladder is one line and the idle box opens when used", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 780 });
  await lab(page);
  const long = "A long answer, line after line of it.\n\n".repeat(30);
  await page.route(`**/copilot/investigations/${NBIS}`, (route) => route.fulfill({ json: { ...saved, transcript: [
    { role: "user", content: "The first question" }, { role: "assistant", content: long }, { role: "user", content: "The latest question" }, { role: "assistant", content: "The latest answer." }] } }));
  await tickers(page).getByRole("button", { name: "NBIS, Held, needs you" }).click();
  await expect(page.getByText("The latest question")).toBeInViewport();
  await expect(page.getByText("The latest answer.")).toBeInViewport();
  await expect(crumb(page)).toBeInViewport(); // where you are stays on screen
  await expect(page.getByText("The first question")).not.toBeInViewport();

  const message = page.getByLabel("Message");
  const idle = (await message.boundingBox())!.height;
  await expect(page.getByText("Research on read-only evidence.")).toHaveCount(0);
  await message.click();
  await expect(page.getByText(/^Research on read-only evidence\./)).toBeVisible();
  expect((await message.boundingBox())!.height).toBeGreaterThan(idle);
  await page.getByRole("region", { name: "Conversation" }).screenshot({ path: test.info().outputPath("desk-latest-turn-desktop.png") });
});

test("Radar hits sit inside Main: one line, each hit opening its event", async ({ page }) => {
  await lab(page);
  const radar = page.getByTestId("briefing-radar-new");
  await expect(radar.locator("summary")).toHaveText("1 new on Radar ▾");
  await radar.locator("summary").click();
  await expect(radar.getByRole("link", { name: /MU/ })).toHaveAttribute("href", `/radar?event=${EVENT}`);
  await expect(tickers(page).getByRole("button", { name: /^MU/ })).toHaveCount(0);
});

test("a quiet day: nothing open says so, and Plan a trade is one tap away", async ({ page }) => {
  await lab(page, QUIET);
  const threads = list(page);
  await expect(threads.getByTestId("desk-day")).toHaveText("Nothing needs you");
  await expect(tickers(page)).toContainText("Nothing open. Plan a trade to start a ticker.");
  await expect(threads.getByRole("link", { name: "Plan a trade" })).toHaveAttribute("href", /\/copilot-lab\?.*context=Plan\+a\+trade/);
});

test("an unavailable source says so, and the list never claims nothing is open without positions", async ({ page }) => {
  await lab(page, { ...QUIET, sections: { ...QUIET.sections, positions: "unavailable", radar: "unavailable" } });
  const threads = list(page);
  await expect(tickers(page)).toContainText("Positions unavailable right now.");
  await expect(threads).toContainText("Unavailable right now: positions, Radar.");
});

test("the list fits a 375 px phone with thumb-sized rows, and the middle tab names where you are", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const threads = list(page);
  await expect(page.getByRole("tab", { name: "Main" })).toBeVisible();
  for (const item of [...await threads.getByRole("link").all(), ...await threads.getByRole("button").all()]) {
    const box = (await item.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
  }
  await expect(threads.getByRole("region", { name: "Main" }).getByRole("button")).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("thread-list-375.png"), fullPage: true });
  await threads.getByRole("button", { name: "NBIS, Held, needs you" }).click();
  await expect(page.getByRole("tab", { name: "NBIS" })).toHaveAttribute("aria-selected", "true");
  await expect(crumb(page)).toBeInViewport();
  // Measured while its tab was hidden, the one-line box still fits its line.
  expect((await page.getByLabel("Message").boundingBox())!.height).toBeGreaterThanOrEqual(40);
  await page.screenshot({ path: test.info().outputPath("thread-open-375.png") });
  expect(chats).toEqual([]);
});

// A conversation with an alert and a plan card the owner has not confirmed or dismissed yet.
const DRAFT = row({ key: `draft:${APLD}`, group: "draft", symbol: "APLD", title: "APLD base", investigation_id: APLD,
  value: { text: "2 to confirm", tone: "attention" }, status: { text: "Alert · APLD crosses 31.20", tone: "muted" }, changed_at: epoch("2026-10-23T14:30:00Z") });
const waiting = {
  ...saved, id: APLD, title: "APLD base", symbol: "APLD", transcript: [{ role: "user", content: "Watch APLD's base" }, {
    role: "assistant", content: "Two cards for the base.", proposals: [
      { id: "w1", kind: "watch", symbol: "APLD", condition: "crosses", price: 31.2, interval: null, label: "APLD base", why: "the base's top", last: 30.4 },
      { id: "w0", kind: "watch", symbol: "APLD", condition: "touches", price: 29.5, interval: null, label: "APLD floor", why: "the floor",
        outcome: { state: "dismissed" } },
    ] }],
};

test("a conversation with cards to confirm puts the needs-you dot on its ticker and opens on them; nothing arms from the list", async ({ page }) => {
  const posts: string[] = [];
  page.on("request", (request) => { if (request.method() !== "GET") posts.push(request.url()); });
  const { chats } = await lab(page, { ...DESK, threads: [...DESK.threads.slice(0, 4), DRAFT, ...DESK.threads.slice(4)] });
  await page.route(`**/copilot/investigations/${APLD}`, (route) => route.fulfill({ json: waiting }));
  // Needs you first: NBIS (Act now) and APLD (a card waiting), then CRWV's armed plan.
  await expect(tickers(page).getByRole("button")).toHaveText([/^NBIS/, /^APLD/, /^CRWV/]);
  const apld = tickers(page).getByRole("button", { name: "APLD, Plan armed, needs you" });
  await expect(apld).toContainText("Alert · APLD crosses 31.20");
  await page.screenshot({ path: test.info().outputPath("thread-list-drafts.png") });

  await apld.click();
  const card = page.getByRole("region", { name: "Proposed watch" });
  await expect(card).toHaveCount(1); // the dismissed card stays hidden
  await expect(card).toContainText("APLD crosses 31.2");
  await expect(card.getByRole("button", { name: /Confirm/ })).toBeVisible(); // the card's own Confirm, not the row's
  await expect(apld).toHaveClass(/ring-1/);
  expect(posts.filter((url) => !url.includes("/copilot/chat"))).toEqual([]);
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

// A busy day: two Radar hits and two thesis items on two symbols, seven new symbols in all, five watched threads.
const fresh = (symbol: string, minute: number, radar = false) => row(radar
  ? { key: `radar:${symbol}-${minute}`, group: "new", symbol, title: `${symbol} up while its group is flat`, status: { text: "Radar · vs sector", tone: "info" },
    radar_event_id: `${symbol}-${minute}`, path: `/radar?event=${symbol}-${minute}`, changed_at: epoch("2026-10-23T13:30:00Z") + minute * 60 }
  : { key: `thesis:${symbol}-${minute}`, group: "new", symbol, title: `${symbol} thesis`, status: { text: `News · ${symbol} headline ${minute}`, tone: "info" },
    path: "/copilot-lab", changed_at: epoch("2026-10-23T13:30:00Z") + minute * 60 });
const BUSY = { ...DESK, threads: [
  ...DESK.threads.slice(0, 4), // the pinned, Act now and Near a trigger rows
  fresh("MU", 10, true), fresh("MU", 50), fresh("NBIS", 40), fresh("NBIS", 45), fresh("IREN", 30, true),
  fresh("CRWV", 20), fresh("AMD", 15), fresh("SMCI", 12), fresh("ORCL", 5),
  ...["APLD", "RNXT", "AAPL", "TSLA", "META"].map((symbol) => row({ key: `investigation:${symbol}`, group: "watch", symbol, title: `${symbol} idea`,
    status: { text: "Open investigation", tone: "muted" }, investigation_id: `${symbol}-id`, changed_at: epoch("2026-10-22T14:00:00Z") })),
] };
test("a busy day stays calm: one row per ticker, six quiet ones shown, a ticker closed this week kept", async ({ page }) => {
  await lab(page, BUSY);
  // Registered after lab()'s empty list, so it answers first; the reload reads it.
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [
    summary("closed-1", "HOOD", "closed", "2026-10-21T18:00:00Z"), summary("closed-0", "PLTR", "closed", "2026-10-16T18:00:00Z"),
    summary("open-1", "APLD", "open", "2026-10-22T18:00:00Z"),
  ] } }));
  await page.reload();
  const threads = list(page);
  await expect(threads.getByRole("region", { name: "Main" })).toContainText("2 Radar");
  // NBIS and CRWV, then six of MU, AMD, SMCI, ORCL (news), APLD, RNXT, AAPL, TSLA, META (open) and HOOD (closed Wednesday).
  await expect(tickers(page).getByRole("button", { name: /^[A-Z]+, / })).toHaveCount(8);
  await expect(tickers(page).getByRole("button", { name: /^NBIS, / })).toHaveCount(1); // its news folds into its row
  await tickers(page).getByRole("button", { name: "+4 more" }).click();
  await expect(tickers(page).getByRole("button", { name: /^[A-Z]+, / })).toHaveCount(12);
  await expect(tickers(page).getByRole("button", { name: "HOOD, Closed" })).toContainText("Out at the invalidation");
  await expect(tickers(page).getByRole("button", { name: /^(IREN|PLTR), / })).toHaveCount(0); // Radar only, or closed last week
  await tickers(page).getByRole("button", { name: "Show fewer" }).click();
  await expect(tickers(page).getByRole("button", { name: /^[A-Z]+, / })).toHaveCount(8);
  await expect(threads.getByTestId("desk-keys")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("thread-list-busy.png") });
});

const level = (price: number, extra: Record<string, unknown> = {}) => ({ price, condition: "crosses", interval: null, state: "armed", ...extra });
const plan = (fields: Record<string, unknown>) => ({
  investigation_id: null, instrument: null, thesis: null, horizon: "swing", last: null, entry: null, invalidation: null, time_stop: null,
  r: null, at: null, note: null, ...fields,
});
const PLANS = {
  ...DESK,
  plans: [
    plan({ stage: "armed", symbol: "APLD", investigation_id: APLD, instrument: "long", horizon: "day", last: 30, thesis: "APLD base breakout",
      entry: level(31, { distance_pct: 3.33 }), invalidation: level(29, { distance_pct: -3.33 }),
      time_stop: { text: "out by 15:30", due_at: epoch("2026-10-23T19:30:00Z"), state: "pending" } }),
    plan({ stage: "in_position", symbol: "NBIS", investigation_id: NBIS, instrument: "10/23/26 100C", last: 94, r: -0.53,
      entry: level(95.9, { state: "hit", hit_at: epoch("2026-10-23T14:10:00Z") }), invalidation: level(92.3, { distance_pct: -1.81 }) }),
    plan({ stage: "exited", symbol: "CRWV", investigation_id: CRWV, instrument: "short", horizon: "long", at: epoch("2026-10-22T17:00:00Z") }),
    plan({ stage: "done", symbol: "SOFI", note: "Marked done", at: epoch("2026-10-21T14:30:00Z") }),
  ],
};

test("the Plans view lists every plan by stage, opens its thread, and is remembered in this browser", async ({ page }) => {
  const { chats } = await lab(page, PLANS);
  const threads = list(page);
  const tab = threads.getByRole("tab", { name: /^Plans/ });
  await expect(tab).toHaveText("Plans2"); // armed and in position
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  const plans = threads.getByTestId("desk-plans");
  await expect(plans.locator("section h3")).toHaveText(["Armed", "In position", "Exited this week", "Done this week"]);
  const apld = plans.getByRole("link", { name: "APLD long Day trade" });
  await expect(apld).toContainText("3.3% to entry");
  await expect(apld).toContainText("Entry 31.00 · invalidation 29.00 · time stop 15:30");
  const nbis = plans.getByRole("link", { name: "NBIS 10/23/26 100C Swing" });
  await expect(nbis).toContainText("−0.5R");
  await expect(nbis).toContainText("1.8% to invalidation 92.30");
  await expect(plans.getByRole("link", { name: "CRWV short Long hold" })).toContainText("Exited Oct 22Exit review waiting");
  const sofi = plans.getByRole("link", { name: "SOFI Swing" });
  await expect(sofi).toContainText("Marked done");
  await expect(sofi).toHaveAttribute("href", "/copilot-lab?symbol=SOFI"); // no saved thread: it opens by its symbol
  await expect(threads.getByRole("region", { name: "Tickers" })).toHaveCount(0);

  await nbis.click();
  await expect(page.getByText("Plan: enter above 95.90, out under 92.30.")).toBeVisible();
  await expect(nbis).toHaveClass(/ring-1/);
  expect(chats).toEqual([]);

  await page.reload();
  await expect(list(page).getByTestId("desk-plans")).toBeVisible();
  await list(page).getByRole("tab", { name: "All" }).click();
  await expect(list(page).getByRole("region", { name: "Tickers" })).toBeVisible();
});

test("the Plans view fits a 375 px phone inside the Now tab", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page, PLANS);
  const threads = list(page);
  await threads.getByRole("tab", { name: /^Plans/ }).click();
  for (const link of await threads.getByTestId("desk-plans").getByRole("link").all()) {
    const box = (await link.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("the open thread is in the address: Back returns to the one before, a reload stays, and J / K walk the subthreads", async ({ page }) => {
  const ID = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;
  const saved = [1, 2].map(n => summary(ID(n), "NBIS", "open", `2026-10-2${n}T15:00:00Z`));
  await lab(page);
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: saved } }));
  for (const n of [1, 2]) await page.route(`**/copilot/investigations/${ID(n)}`, (route) => route.fulfill({ json: { ...saved[n - 1], title: `Talk ${n}`,
    findings: null, evidence: [], transcript: [{ role: "user", content: `Question ${n}` }, { role: "assistant", content: `Answer ${n}` }] } }));
  await page.clock.runFor(60_000);
  await expect(tickers(page).getByRole("button", { name: "Show NBIS threads" })).toBeVisible();
  const here = page.getByRole("region", { name: "Conversation" });
  await page.keyboard.press("j"); // NBIS's newest
  await expect(here.getByText("Answer 2")).toBeVisible();
  await expect(page).toHaveURL(`/copilot-lab?thread=${ID(2)}`);
  await page.keyboard.press("j"); // its subthreads are now shown, so the older one is next
  await expect(here.getByText("Answer 1")).toBeVisible();
  await expect(page).toHaveURL(`/copilot-lab?thread=${ID(1)}`);
  await page.goBack();
  await expect(here.getByText("Answer 2")).toBeVisible();
  await expect(page).toHaveURL(`/copilot-lab?thread=${ID(2)}`);
  await page.goBack();
  await expect(page).toHaveURL("/copilot-lab");
  await expect(here.getByText("Answer 2")).toBeHidden();
  await page.goForward();
  await expect(here.getByText("Answer 2")).toBeVisible();
  await page.reload();
  await expect(here.getByText("Answer 2")).toBeVisible();
  await expect(page.getByLabel("Message")).toHaveValue(""); // no prefilled question, unlike an alert's link
  // The next day the bare address starts on Main.
  await page.evaluate(() => window.localStorage.setItem("tradejournal.copilot-lab.current-day.v1", "2020-01-01"));
  await page.goto("/copilot-lab");
  await expect(list(page).getByRole("button", { name: /^NBIS/ }).first()).toBeVisible();
  await expect(here.getByText("Answer 2")).toBeHidden();
  await expect(page.getByTestId("copilot-scope")).toHaveText("Across everything · add a symbol");
});
