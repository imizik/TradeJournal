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

async function lab(page: Page, { time = NOW, session = SESSION }: { time?: Date; session?: unknown } = {}) {
  const chats: unknown[] = [];
  await page.clock.install({ time });
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ json: DESK }));
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: session }));
  await page.route("**/copilot/practice*", (route) => route.fulfill({ json: PRACTICE }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  for (const [id, [symbol, answer]] of Object.entries(ANSWER))
    await page.route(`**/copilot/investigations/${id}`, (route) => route.fulfill({ json: saved(id, symbol, answer) }));
  await page.route("**/copilot/chat", (route) => { chats.push(route.request().postDataJSON()); return route.abort(); });
  await page.route("**/charts/alerts", (route) => route.fulfill({ json: { alerts: [], phone: true } }));
  await page.route("**/copilot/time-stops?*", (route) => route.fulfill({ json: { time_stops: [], enabled: true } }));
  await page.route("**/copilot/research-jobs?*", (route) => route.fulfill({ json: { jobs: [], queue_enabled: false, daily_budget_usd: 2, spent_today_usd: 0 } }));
  await page.goto("/copilot-lab");
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
  const { chats } = await lab(page, { time: new Date("2026-10-23T21:00:00Z") }); // 17:00 New York
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
    await expect(tape.getByTestId("session-facts")).toHaveText(
      "Next: CRWV time stop 14:30 · Practicing: wait for the 15m close · 3 of 5 this week · Pings 4 of 12 · 1 held");
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
  await page.unroute("**/copilot/desk/session");
  await page.route("**/copilot/desk/session", (route) => route.fulfill({ json: { ...SESSION, phase: "closed", open: null, close: null, events: [], time_stops: [] } }));
  await page.reload();
  await expect(tape).toContainText("No regular session today.");
});
