import { expect, test, type Page } from "@playwright/test";

// The desk's keyboard: the ⌘K palette, J / K through the threads, N for a plan, ] for the Context pane, and the
// Briefing's session timeline. Every lab route is stubbed in the browser (the e2e backend runs with the lab off), so no
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
      value: { text: "+$180.00", tone: "gain" }, status: { text: "1.0% from invalidation 92.30", tone: "attention" }, investigation_id: NBIS, trade_id: TRADE }),
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
  pings: { sent: 4, held: 1, cap: 12 }, prep: { at: epoch("2026-10-23T12:30:00Z"), line: "NBIS 100C expires Friday." },
  indices: [{ symbol: "SPY", last: 580.1, change_pct: 0.42 }, { symbol: "QQQ", last: 500.2, change_pct: -0.31 }], quote_issue: null,
  sections: { hours: "ok", phase: "ok", fills: "ok", pings: "ok", radar: "ok", decisions: "ok", time_stops: "ok", prep: "ok", indices: "ok" },
};
const PRACTICE = { goal: { label: "wait for the 15m close", week_start: "2026-10-19" }, this_week: { text: "3 of 5" } };
const saved = (id: string, symbol: string, answer: string) => ({
  id, source: "copilot", title: `${symbol} plan`, symbol, status: "open", conclusion: null, revision: 1, message_count: 2,
  has_findings: false, created_at: "2026-10-23T14:00:00Z", updated_at: "2026-10-23T14:05:00Z", evidence: [], findings: null,
  transcript: [{ role: "user", content: `Plan a trade: ${symbol}` }, { role: "assistant", content: answer }],
});
const ANSWER: Record<string, [string, string]> = {
  [NBIS]: ["NBIS", "NBIS answer: hold above 92.30."], [CRWV]: ["CRWV", "CRWV answer: short under 99.00."], [APLD]: ["APLD", "APLD answer: enter at 31.00."],
};

async function lab(page: Page, { time = NOW, session = SESSION, threads = () => DESK as unknown, path = "/copilot-lab" }: { time?: Date; session?: unknown; threads?(): unknown; path?: string } = {}) {
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
  await page.goto(path);
  await expect(page.getByRole("navigation", { name: "Thread list" }).getByTestId("desk-day")).toBeVisible();
  return { chats };
}

const palette = (page: Page) => page.getByRole("dialog", { name: "Jump to" });
const conversation = (page: Page) => page.getByRole("region", { name: "Conversation" });

test("⌘K opens the palette: type to filter, Enter opens the thread, Escape and a click outside close it", async ({ page }) => {
  const { chats } = await lab(page);
  await page.keyboard.press("ControlOrMeta+k");
  const box = palette(page);
  await expect(box).toBeVisible();
  const options = box.getByRole("option");
  // The thread list's rows in list order (pinned rows are the commands), then the commands.
  await expect(options).toHaveText([/^NBIS/, /^CRWV/, /^MU/, /^APLD/, /^Plan a trade/, /^Review my week/, /^What matters right now\?/]);
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
  // The thread list's phase button puts the same question in the box, unsent.
  await page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: "Close the day" }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/^Close the day: /);
  await page.getByRole("textbox", { name: "Message" }).fill("");
  await page.getByRole("textbox", { name: "Message" }).blur();
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

test("J and K open the next and previous thread in list order; keys typed in the message box are ignored", async ({ page }) => {
  const { chats } = await lab(page);
  const thread = conversation(page);
  await page.keyboard.press("j");
  await expect(thread.getByText("NBIS answer: hold above 92.30.")).toBeVisible();
  await page.keyboard.press("j");
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible(); // Near a trigger; the MU Radar row leaves the page, so J skips it
  await page.keyboard.press("j");
  await expect(thread.getByText("APLD answer: enter at 31.00.")).toBeVisible();
  await page.keyboard.press("k");
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(page.getByRole("link", { name: "CRWV short" })).toHaveClass(/ring-1/);

  const message = page.getByRole("textbox", { name: "Message" });
  await message.click();
  await page.keyboard.type("jk]n");
  await expect(message).toHaveValue(/jk\]n$/);
  await expect(thread.getByText("CRWV answer: short under 99.00.")).toBeVisible(); // still on CRWV
  await expect(page.getByRole("complementary", { name: "Context" })).toBeVisible();
  expect(page.url()).not.toContain("context=");
  expect(chats).toEqual([]);
});

test("] hides the Context pane on a wide desk and the choice is remembered; the toggle does the same", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await lab(page);
  const context = page.getByRole("complementary", { name: "Context" });
  const toggle = page.getByRole("button", { name: "Context pane" });
  await expect(context).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("]");
  await expect(context).toBeHidden();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await page.screenshot({ path: test.info().outputPath("desk-context-hidden-1440.png") });
  await page.reload();
  await expect(page.getByTestId("session-tape")).toBeVisible();
  await expect(context).toBeHidden();
  await toggle.click();
  await expect(context).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("session-tape")).toBeVisible();
  await expect(context).toBeVisible();
});

test("the phone keeps its tabs: no pane toggle, and the Jump to button still opens the palette", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await lab(page);
  await expect(page.getByRole("button", { name: "Context pane" })).toBeHidden();
  await expect(page.getByTestId("desk-keys")).toBeHidden(); // no keyboard hint on a phone
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  await palette(page).getByRole("option", { name: /^APLD/ }).click();
  await expect(conversation(page).getByText("APLD answer: enter at 31.00.")).toBeVisible();
  await expect(page.getByRole("tab", { name: "APLD" })).toHaveAttribute("aria-selected", "true");
});

for (const [width, height] of [[1440, 900], [375, 812]] as const) {
  test(`the Briefing opens on today's session at ${width} px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await lab(page);
    if (width < 760) await page.getByRole("tab", { name: "Thread" }).click();
    const tape = page.getByTestId("session-tape");
    await expect(tape).toBeVisible();
    await expect(tape).toContainText("Market open");
    await expect(tape.getByTestId("session-indices")).toHaveText("SPY +0.42%QQQ −0.31%");
    const strip = tape.getByTestId("session-strip");
    await expect(strip).toHaveAttribute("aria-label", "So far: 1 fill, 1 ping, 1 Radar event, 1 decision. Ahead: CRWV time stop 14:30.");
    for (const kind of ["fill", "ping", "radar", "decision", "time_stop"]) await expect(strip.locator(`[data-kind="${kind}"]`)).toHaveCount(1);
    // 11:00 is 90 of the session's 390 minutes.
    await expect(tape.getByTestId("session-now")).toHaveAttribute("style", /left: 23\.07/);
    await expect(tape.getByTestId("session-labels")).toHaveText("9:3011:0012:3014:0016:00");
    await expect(tape.getByTestId("briefing-numbers")).toHaveText(
      "Positions1Needs you1Nearest triggerCRWV · 0.6% to entry 99.00Pings today4 of 12 · 1 held");
    await expect(tape.getByTestId("session-facts")).toHaveText("Next: CRWV time stop 14:30 · Practicing: wait for the 15m close · 3 of 5 this week");
    // The desk bar: live, with the indices on a wide screen only.
    await expect(page.getByTestId("desk-status")).toContainText("Live");
    if (width >= 760) await expect(page.getByTestId("desk-indices")).toHaveText("SPY +0.42%QQQ −0.31%");
    else await expect(page.getByTestId("desk-indices")).toBeHidden();
    await expect(page.getByRole("button", { name: "Close the day" })).toHaveCount(0); // no phase button mid-session
    await page.screenshot({ path: test.info().outputPath(`briefing-session-${width}.png`), fullPage: width < 760 });

    await page.keyboard.press("j"); // a symbol's thread opens on its own header instead
    if (width < 760) await expect(page.getByRole("tab", { name: "NBIS" })).toBeVisible();
    await expect(tape).toBeHidden();
  });
}

test("before the open the strip waits and the prep line leads; a closed day says so", async ({ page }) => {
  const before = { ...SESSION, now: epoch("2026-10-23T12:45:00Z"), phase: "pre", events: [] };
  await lab(page, { session: before });
  const tape = page.getByTestId("session-tape");
  await expect(tape).toContainText("Pre-market");
  await expect(tape.getByTestId("session-now")).toHaveCount(0);
  await expect(tape.getByTestId("session-facts")).toHaveText(/^Prep written 8:30 · Next: CRWV time stop 14:30/);
  await expect(page.getByTestId("desk-status")).toContainText("Pre-market");
  await page.unroute("**/copilot/desk/session");
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: { ...SESSION, phase: "closed", open: null, close: null, events: [], time_stops: [] } }));
  await page.reload();
  await expect(tape).toContainText("No regular session today.");
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
        invalidation: level(29), time_stop: { text: "out by 15:30", due_at: epoch("2026-10-23T19:30:00Z"), state: "pending" } }),
      plan({ stage: "armed", symbol: "CRWV", investigation_id: CRWV, instrument: "short", entry: level(99), invalidation: level(103) }),
      plan({ stage: "in_position", symbol: "NBIS", investigation_id: NBIS, r: 0.4 }),
    ] });
  const { chats } = await lab(page, { time: new Date("2026-10-23T12:45:00Z"), threads, // 8:45 New York
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

  const arm = page.getByRole("navigation", { name: "Thread list" }).getByRole("button", { name: "Arm today's plans" });
  await expect(page.getByTestId("session-facts")).toContainText("Next: the open 9:30");
  await arm.click();
  const list = page.getByTestId("arm-checklist");
  await expect(list.getByTestId("arm-progress")).toHaveText("0 of 2 checked"); // the armed plans only
  await expect(page.getByTestId("session-tape")).toBeHidden();
  const apld = list.getByRole("listitem", { name: "APLD" });
  await expect(apld).toContainText("Entry 31.00 · invalidation 29.00 · time stop 15:30");
  await expect(apld).toContainText("⚑ Earnings · APLD reports after the close");
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
  await arm.click();
  await expect(list.getByTestId("arm-progress")).toHaveText("1 of 2 checked");
  await list.getByRole("listitem", { name: "CRWV" }).getByRole("button", { name: "Change" }).click();
  await expect(list).toBeHidden();
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(
    "Change my CRWV plan before the open: Entry 99.00 · invalidation 103.00. What should change, and why?");

  // The old question is one link away.
  await arm.click();
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
  const { chats } = await lab(page, { time: new Date("2026-10-23T20:30:00Z"), threads: asking, path: "/copilot-lab?close=1", // 16:30 New York
    session: { ...SESSION, now: epoch("2026-10-23T20:30:00Z"), phase: "post", time_stops: [] } });
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible(); // the first unreviewed thread
  await expect(page.getByRole("region", { name: "Close of day" })).toContainText("Review: did you follow the plan?");
  expect(chats).toEqual([]);
});

test("the close link with nothing left to review puts the day's question in the box; before the close it opens the desk as usual", async ({ page }) => {
  await lab(page, { time: new Date("2026-10-23T20:30:00Z"), path: "/copilot-lab?close=1", // 16:30 New York, no close question
    session: { ...SESSION, now: epoch("2026-10-23T20:30:00Z"), phase: "post", time_stops: [] } });
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/^Close the day: /);
  await page.clock.setSystemTime(NOW); // 11:00 New York
  await page.goto("/copilot-lab?close=1");
  await expect(page.getByRole("navigation", { name: "Thread list" }).getByTestId("desk-day")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  await expect(page).toHaveURL(/\/copilot-lab\?close=1$/);
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
  await expect(rail.getByRole("link", { name: /^NBIS/ })).toContainText("Review: did you follow the plan?");
  await expect(rail.getByRole("link", { name: /^CRWV/ })).toContainText("Added or not, and why?");
  await expect(rail.getByRole("link", { name: /^APLD/ })).toContainText("Reviewed · Entered at 31.00 as planned, sized…");
  await expect(page.getByTestId("briefing-reviewed")).toHaveText("1 of 4 reviewed");
  await page.screenshot({ path: test.info().outputPath("close-the-day-1440.png") });

  const review = page.getByRole("region", { name: "Close of day" });
  await rail.getByRole("button", { name: "Close the day · 3 to review" }).click();
  await expect(conversation(page).getByText("NBIS answer: hold above 92.30.")).toBeVisible(); // the first unreviewed thread
  await expect(review).toContainText("Review: did you follow the plan?");
  await review.getByRole("button", { name: "Answer" }).click();
  await review.getByRole("textbox").fill("Held above 92.30 all day, as planned.");
  await review.getByRole("button", { name: "Save" }).click();
  // TSLA has no conversation and no plan: it opens by its symbol, on "Want a plan for this?".
  await page.waitForURL(/\/copilot-lab\?symbol=TSLA$/);
  await expect(review).toContainText("Want a plan for this?");
  await expect(rail.getByRole("link", { name: /^NBIS/ })).toContainText("Reviewed · Held above 92.30 all day, as…");
  await review.getByRole("button", { name: "Not now" }).click();
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible();
  await expect(review).toContainText("Added or not, and why?");
  await expect(rail.getByRole("link", { name: /^TSLA/ })).toContainText("Reviewed · No plan for now");
  await review.getByRole("button", { name: "Skip" }).click();
  await expect(review).toHaveCount(0);
  await expect(conversation(page).getByText("CRWV answer: short under 99.00.")).toBeVisible(); // the last one: the pass ends here
  await expect(rail.getByRole("button", { name: "Close the day", exact: true })).toBeVisible();

  await page.keyboard.press("j"); // J / K still walk the threads
  await expect(conversation(page).getByText("APLD answer: enter at 31.00.")).toBeVisible();
  expect(posts).toEqual([expect.objectContaining({ kind: "reflection", symbol: "NBIS", text: "Held above 92.30 all day, as planned." }),
    expect.objectContaining({ kind: "plan_ask", symbol: "TSLA", text: "No plan for now" })]);
  expect(chats).toEqual([]);
});
