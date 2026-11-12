import { expect, test, type Page } from "@playwright/test";

// Fixes from the owner's first evening on the desk with the Robinhood feed on (docs/copilot-lab.md § The desk): the
// Needs-you strip on every view that shows the book, an answer cut off mid-turn (live and after a reload), the book's
// tag and its layout, the chart's ticker for a Main chat answer, the day report's type and the chart's edge labels.
// Every lab route is stubbed in the browser (the e2e backend runs with the lab off); nothing reaches Robinhood or a model.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Wednesday November 11, 2026, 23:50 in New York (EST): after the close, as the owner's screenshot was.
const NOW = new Date("2026-11-12T04:50:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const MAIN = "77777777-7777-4777-8777-777777777777";
const OTHER = "88888888-8888-4888-8888-888888888888";
const ORCL = "99999999-9999-4999-8999-999999999999";
const ROTH = { label: "Roth IRA", masked: "••8267" };
const INDIVIDUAL = { label: "Individual", masked: "••1113" };
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const book = (fields: Record<string, unknown>) => ({ usd: null, pct: null, expiry: null, days_held: 1, track: null, state: "no_plan",
  planned: false, stop_pct: null, ...fields });
/** ORCL 11/13 160C ×3, no plan, expiring in two days: a journal trade Robinhood also shows (matched), or one only Robinhood has. */
const orcl = (live: "matched" | "new") => live === "matched"
  ? row({ key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/13/26 160C", instrument: "11/13/26 160C", trade_id: ORCL,
    value: { text: "−$668.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`,
    book: book({ usd: -668, pct: -100, expiry: "2026-11-13", days_held: 2, quantity: 3, mark: 0, account: ROTH, live: "matched" }) })
  : row({ key: "robinhood:••8267:ORCL 11/13/26 160C", group: "watch", symbol: "ORCL", title: "ORCL 11/13/26 160C", instrument: "11/13/26 160C",
    value: { text: "−$668.00", tone: "loss" }, status: { text: "New · not in the journal yet", tone: "info" }, path: "/copilot-lab?symbol=ORCL",
    book: book({ usd: -668, pct: -100, expiry: "2026-11-13", days_held: null, quantity: 3, mark: 0, account: ROTH, live: "new" }) });
const AAPL = row({ key: "robinhood:••1113:AAPL 11/20/26 320P", group: "watch", symbol: "AAPL", title: "AAPL 11/20/26 320P", instrument: "11/20/26 320P",
  value: { text: "−$164.00", tone: "loss" }, status: { text: "New · not in the journal yet", tone: "info" }, path: "/copilot-lab?symbol=AAPL",
  book: book({ usd: -164, pct: -89, expiry: "2026-11-20", days_held: null, quantity: 1, mark: 20, account: INDIVIDUAL, live: "new" }) });
const LIVE = { state: "ok", joined: true, as_of: epoch("2026-11-12T04:50:00Z"), issue: null, accounts: [
  { ...INDIVIDUAL, total_value: 28, cash: 0, buying_power: 0 }, { ...ROTH, total_value: 18898, cash: 0, buying_power: 0 }] };
const desk = (threads: unknown[]) => ({
  as_of: "2026-11-12T04:50:00Z", quotes_at: null, quote_issue: null, day: { phase: "closed", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: LIVE,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...threads],
});
const SESSION = {
  as_of: "2026-11-12T04:50:00Z", now: epoch("2026-11-12T04:50:00Z"), day: "2026-11-11", phase: "closed",
  open: epoch("2026-11-11T14:30:00Z"), close: epoch("2026-11-11T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }], quote_issue: null, realized_today: -20, sections: {},
};
const DAY_REPORT = { day: "2026-11-11", as_of: "2026-11-12T04:50:00Z", sections: {},
  entries: { entries: 3, planned: 0, late: 0, pending: 0, rows: [] }, checks: null };
const NO_PINGS = { day: "2026-11-11", since: "2026-11-11", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } };
const SPARKS = { as_of: "2026-11-12T04:50:00Z", spy_change_pct: 0.4, rows: {
  ORCL: { points: [250, 248, 246, 247], change_pct: -1.2 }, AAPL: { points: [270, 272, 271, 273], change_pct: 0.6 } } };
const investigation = (id: string, fields: Record<string, unknown>) => ({
  id, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null, revision: 1, message_count: 0,
  has_findings: false, created_at: "2026-11-11T14:00:00Z", updated_at: "2026-11-12T04:40:00Z", evidence: [], findings: null,
  transcript: [], main_day: "2026-11-11", ...fields,
});
const QUESTION = "if we had to take something rn.. what would you take for week-month long swing to capture this recovery";
const IREN = [
  "Verdict: Pass — IREN Dec-18 calls are extended after today's run; wait for a pullback.",
  "- SMH ripped 4.8% and MU, SNDK and SOXL led; SMH is a trade on the group, not a swing entry.",
  "- IREN needs a pullback toward 30 before the Dec-18 calls make sense.",
  "Changes if: IREN holds 32 into Friday.",
].join("\n");
/** Four reads the answer made, as a saved conversation keeps them. */
const EVIDENCE = [0, 1, 2, 3].map(n => ({ tool: ["get_quote", "get_news", "get_group", "get_positions"][n], as_of: "2026-11-12T04:40:00Z", kind: "live", message: 1 }));
const sse = (events: unknown[]) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join("");

type Opened = { chats: { messages: { role: string; content: string }[] }[]; saved: { transcript: { role: string; content: string; metrics?: { error?: string } }[] }[]; charts: string[] };

async function open(page: Page, { path = `/copilot-lab?thread=${MAIN}`, threads = [orcl("matched"), AAPL] as unknown[], main = investigation(MAIN, {}) as Record<string, unknown>,
  chat = null as string | null, chart = null as unknown, time = NOW }: { path?: string; threads?: unknown[]; main?: Record<string, unknown>; chat?: string | null; chart?: unknown; time?: Date } = {}) {
  const opened: Opened = { chats: [], saved: [], charts: [] };
  let current = main;
  await page.clock.install({ time });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: desk(threads) }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/day-report", route => route.fulfill({ json: DAY_REPORT }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: NO_PINGS }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: SPARKS }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-12T04:50:00Z", now: epoch("2026-11-12T04:50:00Z"), day: "2026-11-11", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: current }));
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: current }));
  await page.route(`**/copilot/investigations/${OTHER}`, route => route.fulfill({ json: investigation(OTHER, { title: "ORCL plan", symbol: "ORCL", main_day: null,
    message_count: 2, transcript: [{ role: "user", content: "Plan ORCL" }, { role: "assistant", content: "Verdict: Wait — ORCL needs a base." }] }) }));
  await page.route(`**/copilot/main-chat/${MAIN}/exchange`, async route => {
    const body = route.request().postDataJSON();
    opened.saved.push(body);
    const transcript = [...(current.transcript as unknown[]), ...body.transcript];
    current = { ...current, transcript, message_count: transcript.length, revision: (current.revision as number) + 1,
      evidence: [...(current.evidence as unknown[]), ...body.evidence.map((e: { message: number }) => ({ ...e, message: e.message + (current.transcript as unknown[]).length }))] };
    await route.fulfill({ json: current });
  });
  await page.route("**/copilot/chat", route => {
    opened.chats.push(route.request().postDataJSON());
    return chat === null ? route.abort() : route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: chat });
  });
  await page.route("**/copilot/desk/*/{picture,chart}*", route => {
    opened.charts.push(decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2)[0]));
    return chart ? route.fulfill({ json: chart }) : route.fulfill({ status: 503, json: { detail: "No chart in this test." } });
  });
  await page.goto(path);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return opened;
}

const strip = (page: Page) => page.getByTestId("needs-you");
const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });

// ------------------------------------------------------------------------------------------------ 1. the strip

for (const live of ["matched", "new"] as const) {
  test(`an option the feed supplies (${live}), expiring in 2 days with no plan, is in the strip after the close with Main chat open`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, { threads: [orcl(live), AAPL] });
    await expect(conversation(page).getByRole("heading", { name: /Main chat/ })).toBeVisible();
    await expect(strip(page).getByTestId("needs-you-title")).toHaveText("ORCL 11/13/26 160C expires in 2 days and has no plan.");
    await expect(strip(page).getByRole("button", { name: "Plan it" })).toBeVisible();
  });
}

for (const [view, path] of [["Now", "/copilot-lab"], ["a saved conversation", `/copilot-lab?thread=${OTHER}`], ["a position's desk view", "/copilot-lab?symbol=ORCL"]] as const) {
  for (const width of [1440, 375]) {
    test(`the strip shows wherever the book shows: ${view} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page, { path });
      await expect(strip(page).getByTestId("needs-you-title")).toHaveText("ORCL 11/13/26 160C expires in 2 days and has no plan.");
    });
  }
}

test("the strip's Seen and the thread list's new-since-you-looked keep separate notes in the browser", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // The thread list's own note (rows read) is in the browser already; the strip's Seen must neither read nor replace it.
  await page.addInitScript(() => window.localStorage.setItem("desk.seen.v1", JSON.stringify({ "radar:x": 1 })));
  await open(page);
  await strip(page).getByRole("button", { name: "Seen" }).click();
  await expect(strip(page)).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(window.localStorage.getItem("desk.seen.v1") ?? "{}"))).toMatchObject({ "radar:x": 1 });
});

// ------------------------------------------------------------------------------------------------ 2. an answer cut off

test("an answer cut off mid-turn ends in a quiet interrupted line with Ask again, and is saved that way", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // The server read four sources, then the connection closed (a restart) before any words or the turn's end.
  const cut = sse([0, 1, 2, 3].map(n => ({ type: "tool", id: `t${n}`, name: "get_quote", input: {}, status: "ok", summary: "read",
    provenance: { source: "fixture", kind: "live", as_of: "2026-11-12T04:49:00Z", state: "ok" } })));
  const opened = await open(page, { chat: cut });
  await page.getByLabel("Message").fill(QUESTION);
  await page.getByLabel("Message").press("Enter");
  const line = conversation(page).getByTestId("copilot-interrupted");
  await expect(line).toContainText("This answer was interrupted.");
  await expect(conversation(page).getByLabel("Progress")).toHaveCount(0);
  await expect.poll(() => opened.saved.length).toBe(1);
  const [question, reply] = opened.saved[0].transcript;
  expect(question.content).toBe(QUESTION);
  expect(reply).toMatchObject({ role: "assistant", content: "", metrics: { error: "interrupted" } });
  // Ask again sends the same question as a new turn.
  await line.getByRole("button", { name: "Ask again" }).click();
  await expect.poll(() => opened.chats.length).toBe(2);
  expect(opened.chats[1].messages.at(-1)).toEqual({ role: "user", content: QUESTION });
});

for (const saved of ["marked interrupted", "an older empty reply"] as const) {
  test(`a reload of a conversation holding a cut-off answer (${saved}) shows it interrupted, never a progress line`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const reply = saved === "marked interrupted" ? { role: "assistant", content: "", metrics: { error: "interrupted" } } : { role: "assistant", content: "" };
    await open(page, { main: investigation(MAIN, { message_count: 4, evidence: EVIDENCE, transcript: [
      { role: "user", content: QUESTION }, reply, { role: "user", content: "and now?" }, { role: "assistant", content: IREN }] }) });
    await expect(conversation(page).getByText("IREN needs a pullback")).toBeVisible();
    await expect(conversation(page).getByTestId("copilot-interrupted")).toHaveText("This answer was interrupted.");
    await expect(conversation(page).getByLabel("Progress")).toHaveCount(0);
    await expect(conversation(page).getByText(/Weighing the evidence|Thinking…|Reading evidence/)).toHaveCount(0);
  });
}

// ------------------------------------------------------------------------------------------------ 3. the book's tag

for (const width of [1440, 375]) {
  test(`at ${width}px a book row's tag never runs under its sparkline or its P&L`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, { path: "/copilot-lab" });
    const rows = page.getByTestId("desk-book").locator("li");
    await expect(rows).toHaveCount(2);
    for (const symbol of ["ORCL", "AAPL"]) {
      const item = rows.filter({ has: page.getByRole("img", { name: `${symbol} today` }) });
      const tag = await item.getByTestId("book-state").boundingBox();
      const spark = await item.getByRole("img", { name: `${symbol} today` }).boundingBox();
      expect(tag && spark, symbol).toBeTruthy();
      expect(tag!.x + tag!.width, `${symbol}'s tag ends before its sparkline`).toBeLessThanOrEqual(spark!.x);
    }
  });
}

test("each tag the book can show reads in the desk's words", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const tagged = (symbol: string, state: string, usd: number) => row({ key: `trade:${symbol}`, group: "watch", symbol, title: `${symbol} 12/18/26 50C`,
    instrument: "12/18/26 50C", trade_id: symbol, value: null, status: { text: "", tone: "muted" }, path: null,
    book: book({ usd, pct: usd / 10, expiry: "2026-12-18", state, planned: state !== "no_plan" }) });
  await open(page, { path: "/copilot-lab", threads: [tagged("GRN", "giving_back", 120), tagged("RED", "no_plan", -80), tagged("PLN", "on_plan", -80),
    tagged("NER", "near_stop", -40), tagged("PST", "past_stop", -200)] });
  const tag = (symbol: string) => page.getByTestId("desk-book").getByRole("button", { name: new RegExp(`^${symbol} `) }).getByTestId("book-state");
  await expect(tag("GRN")).toHaveText("Giving back");
  await expect(tag("RED")).toHaveText("No plan");
  await expect(tag("PLN")).toHaveText("On plan");
  await expect(tag("NER")).toHaveText("Near stop");
  await expect(tag("PST")).toHaveText("Past stop");
});

// ------------------------------------------------------------------------------------------------ 4. the chart's ticker

test("with no row selected the chart follows the ticker the latest answer is about, and a selected row wins", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const opened = await open(page, { main: investigation(MAIN, { message_count: 2, transcript: [{ role: "user", content: QUESTION }, { role: "assistant", content: IREN }] }) });
  const chart = page.getByTestId("desk-chart");
  // SMH comes first and twice in the answer, but the verdict is about IREN.
  await expect(chart.locator("span").first()).toHaveText("IREN");
  await expect.poll(() => opened.charts.at(-1)).toBe("symbol:IREN");
  await page.getByTestId("desk-book").getByRole("button", { name: /^ORCL / }).click();
  await expect(chart.locator("span").first()).toHaveText("ORCL");
});

test("an answer with no clear subject leaves the chart on the market", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const opened = await open(page, { main: investigation(MAIN, { message_count: 2, transcript: [{ role: "user", content: "how did I do today?" },
    { role: "assistant", content: "Verdict: Unclear — Three entries, none with a plan saved before the fill.\n- The day was green for the market." }] }) });
  await expect(page.getByTestId("desk-chart").locator("span").first()).toHaveText("QQQ");
  await expect.poll(() => opened.charts.at(-1)).toBe("market");
});

// ------------------------------------------------------------------------------------------------ 5. type and the axis

test("the day report's Today line sets only its figures in the mono face", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, { path: "/copilot-lab" });
  const line = page.getByTestId("report-today-line");
  await expect(line).toHaveText("3 entries, 0 with a plan saved before the fill");
  const faces = await line.evaluate(el => ({ words: getComputedStyle(el).fontFamily, figures: [...el.querySelectorAll(".tabular-nums")].map(n => [n.textContent, getComputedStyle(n).fontFamily]) }));
  expect(faces.words).not.toMatch(/mono/i);
  expect(faces.figures.map(([text]) => text)).toEqual(["3", "0"]);
  for (const [, face] of faces.figures) expect(face).toMatch(/mono/i);
});

for (const width of [1440, 375]) {
  test(`at ${width}px the chart keeps room at both ends so its first and last time labels draw whole`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const step = 120, last = epoch("2026-11-11T21:00:00Z");
    const bars = Array.from({ length: 480 }, (_, i) => ({ time: last - (479 - i) * step, open: 100, high: 101, low: 99, close: 100.5, volume: 10, extended: false }));
    await open(page, { path: "/copilot-lab", chart: { symbol: "ORCL", timeframe: "2m", step, as_of: last, live: false, state: "ok",
      reason: null, bars, levels: [], marks: [], time_stop: null } });
    const canvas = page.getByTestId("desk-chart-canvas");
    await expect(canvas).toHaveAttribute("data-bars", "480");
    await expect(canvas).toHaveAttribute("data-edges", /^\d+,\d+$/);
    const [left, right] = (await canvas.getAttribute("data-edges"))!.split(",").map(Number);
    expect(left, "room before the first candle").toBeGreaterThanOrEqual(26);
    expect(right, "room after the last candle").toBeGreaterThanOrEqual(26);
  });
}
