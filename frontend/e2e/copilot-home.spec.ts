import { expect, test, type Page } from "@playwright/test";
import { openDeskThreads } from "./desk-fixtures";

// The lab's home: the desk's thread list (a drawer) beside the conversation. Every lab route is stubbed in the browser and the one
// turn is a fixed SSE stream, so no model runs. Opening the lab reads /copilot/desk/threads and sends nothing; only a
// Briefing button sends, and only when pressed. The list itself: copilot-thread-list.spec.ts.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const INV = "11111111-1111-4111-8111-111111111111";
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const DESK = {
  as_of: "2026-10-23T15:12:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok", investigations: "ok", radar: "off" },
  threads: [
    row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "What matters right now? One turn across everything", tone: "muted" } }),
    row({ key: "week", group: "pinned", title: "Review my week", status: { text: "Planned vs unplanned, follow-through, exits", tone: "muted" } }),
    row({ key: `investigation:${INV}`, group: "watch", symbol: "NBIS", title: "Is the NBIS recovery real?",
      status: { text: "Group is confirming; the symbol lags.", tone: "muted" }, investigation_id: INV, changed_at: 1792000000 }),
  ],
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
  let reads = 0;
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", (route) => { reads += 1; return route.fulfill({ json: DESK }); });
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
  await page.goto("/copilot-lab?view=briefing");
  await openDeskThreads(page);
  return { chats, saves, reads: () => reads };
}

const list = (page: Page) => page.getByRole("navigation", { name: "Thread list" });
/** Jump to (⌘K): What matters right now? and Review my week are its commands (the copilot keeps its own asks). */
async function jump(page: Page) {
  await page.getByRole("button", { name: "Jump to a thread or command" }).click();
  return page.getByRole("dialog", { name: "Jump to" });
}

test("the list sends nothing on open, and What matters right now? asks across everything beside it", async ({ page }) => {
  const { chats, saves, reads } = await lab(page);
  const threads = list(page);
  await expect(threads.getByRole("button", { name: "NBIS, Watching" })).toContainText("Group is confirming; the symbol lags.");
  await page.waitForTimeout(300);
  expect(chats).toEqual([]); // opening costs nothing
  expect(reads()).toBe(1);

  await (await jump(page)).getByRole("option", { name: /^What matters right now\?/ }).click();
  await expect(page.getByText(ANSWER)).toBeVisible();
  expect(chats).toEqual([{ messages: [{ role: "user", content: PROMPT }], symbol: null, source: "desk" }]);
  await expect(threads).toBeVisible(); // the desk keeps the thread list beside the open conversation
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].symbol).toBeNull(); // saved about no symbol
  await expect(page.getByTestId("copilot-scope")).toHaveText("Across everything · add a symbol");
});

test("an open investigation opens in place without sending", async ({ page }) => {
  const { chats } = await lab(page);
  const threads = list(page);
  await threads.getByRole("button", { name: "NBIS, Watching" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(threads).toBeVisible(); // still beside the conversation on a wide screen
  await expect(page.getByLabel("Message")).toHaveValue(""); // not even a prefilled question
  expect(chats).toEqual([]);
});

test("on a phone the thread list covers the desk, and opening a thread moves to the copilot sheet", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { chats } = await lab(page);
  const threads = list(page);
  await expect(threads).toBeVisible();
  await expect(page.getByLabel("Message")).toBeHidden();
  await threads.getByRole("button", { name: "NBIS, Watching" }).click();
  await expect(page.getByText("Not yet: it lags CRWV.")).toBeVisible();
  await expect(threads).toBeHidden();
  await page.getByRole("button", { name: "Back to the desk" }).click();
  await expect(page.getByLabel("Message")).toBeHidden();
  await openDeskThreads(page);
  await expect(threads).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  expect(chats).toEqual([]);
});

test("the list says so when its read fails, and the Briefing and Review my week still work", async ({ page }) => {
  await page.route("**/copilot/desk/threads", (route) => route.fulfill({ status: 503, json: { detail: "Copilot Lab is off." } }));
  await page.route("**/copilot/status", (route) => route.fulfill({ json: ON }));
  await page.route("**/copilot/investigations?*", (route) => route.fulfill({ json: { investigations: [] } }));
  await page.goto("/copilot-lab?view=briefing");
  await openDeskThreads(page);
  const threads = list(page);
  await expect(threads).toContainText("Threads unavailable: Copilot Lab is off.");
  await expect(threads.getByRole("button", { name: "Review my week" })).toHaveCount(0); // in ⌘K and the Briefing now
  const palette = await jump(page);
  await expect(palette.getByRole("option", { name: /^What matters right now\?/ })).toBeVisible();
  await expect(palette.getByRole("option", { name: /^Review my week/ })).toBeVisible();
});

test("on a wide screen the app's navigation folds into the desk bar's Menu, and keeping the sidebar open is remembered", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await lab(page);
  const desk = page.getByRole("heading", { name: "Desk", level: 1 });
  await expect(desk).toBeVisible();
  // No icon rail and no sidebar: the desk starts at the left edge.
  await expect(page.getByRole("link", { name: "Charts", exact: true })).toBeHidden();
  expect((await page.getByRole("navigation", { name: "Thread list" }).boundingBox())!.x).toBeLessThan(40);
  const menu = page.getByRole("button", { name: "Open menu" }).first();
  await menu.click();
  const dialog = page.getByRole("dialog", { name: "Menu" });
  // The desk is home: Desk and Charts on top; the Dashboard waits under Journal.
  for (const name of ["Desk", "Charts"]) await expect(dialog.getByRole("link", { name, exact: true })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Dashboard", exact: true })).toHaveCount(0);
  for (const name of ["Journal", "Market", "Practice", "Research"]) await expect(dialog.getByRole("button", { name, exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("desk-menu-1440.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  await menu.click();
  await dialog.getByRole("button", { name: "Keep the sidebar open" }).click();
  await expect(page.getByRole("button", { name: "Collapse navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Charts", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open menu" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Collapse navigation" })).toBeVisible();
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await expect(page.getByRole("button", { name: "Open menu" }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
});

const SESSION = { as_of: "2026-10-23T15:00:00Z", now: 1792767600, day: "2026-10-23", phase: "regular", open: null, close: null, events: [],
  time_stops: [], pings: null, prep: null, indices: [], quote_issue: null, sections: {} };

test("daily Main reopens across devices in the copilot, keeps drafts in their tab and opens earlier dates without sending", async ({ page, browser }) => {
  const prior = { ...saved, main_day: "2026-10-22", title: "Main chat · 2026-10-22", symbol: null };
  const today = { ...prior, id: "33333333-3333-4333-8333-333333333333", main_day: "2026-10-23", title: "Main chat · 2026-10-23" };
  let sends = 0;
  async function fixture(p: Page) {
    await p.route("**/copilot/status", route => route.fulfill({ json: ON }));
    await p.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
    await p.route("**/copilot/main-chat", route => route.fulfill({ json: today }));
    await p.route("**/copilot/main-chat/history", route => route.fulfill({ json: { chats: [today, prior] } }));
    for (const chat of [prior, today]) await p.route(`**/copilot/investigations/${chat.id}`, route => route.fulfill({ json: chat }));
    await p.route("**/copilot/chat", route => { sends++; return route.abort(); });
    await p.goto("/copilot-lab");
    await expect(p).toHaveURL(`/copilot-lab?thread=${today.id}`);
    // A phone's copilot waits behind Ask the copilot: there the heading is checked once it is open.
    if (p.viewportSize()!.width >= 1180) await expect(p.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  }
  await fixture(page);
  await page.getByLabel("Message").fill("Follow up after lunch");
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, baseURL: test.info().project.use.baseURL });
  try {
    const mobile = await phone.newPage();
    await fixture(mobile);
    // A phone opens on the cockpit; today's conversation waits behind Ask the copilot, its box at the bottom.
    await expect(mobile.getByTestId("desk-book")).toBeVisible();
    await expect(mobile.getByRole("link", { name: "Now", exact: true })).toBeHidden(); // already there: the bar drops it
    await mobile.getByRole("button", { name: /^Ask the copilot/ }).click();
    await expect(mobile.getByLabel("Message")).toHaveValue("");
    await expect(mobile.getByText("Not yet: it lags CRWV.")).toBeVisible();
    await mobile.screenshot({ path: test.info().outputPath("daily-main-phone.png") });
  } finally { await phone.close(); }
  // The cockpit and today's conversation are one screen: the book and the centre, the copilot on Main chat beside them.
  await expect(page.getByRole("link", { name: "Now", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByLabel("Message")).toHaveValue("Follow up after lunch");
  await page.getByText("Previous days", { exact: true }).click();
  await page.getByRole("button", { name: "Main chat · Thu, Oct 22" }).click();
  await expect(page.getByRole("heading", { name: "Main chat · Thu, Oct 22" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Message")).toHaveValue("Follow up after lunch");
  await page.getByText("Previous days", { exact: true }).click();
  await page.getByRole("button", { name: "Main chat · Thu, Oct 22" }).click();
  await expect(page.getByRole("heading", { name: "Main chat · Thu, Oct 22" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Now", exact: true })).not.toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Now", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Now", exact: true })).toHaveAttribute("aria-current", "page");
  expect(sends).toBe(0);
  await page.screenshot({ path: test.info().outputPath("daily-main-desktop.png") });
});

test("two devices keep their own exchange and feedback targets when both opened the same revision", async ({ page, browser }) => {
  const shared = { ...saved, title: "Main chat · 2026-10-23", symbol: null, main_day: "2026-10-23",
    message_count: 0, transcript: [] as { role: string; content: string; exchange_id?: string }[] };
  const indexes: number[] = [];
  async function device(p: Page, answer: string) {
    await p.route("**/copilot/status", r => r.fulfill({ json: ON }));
    await p.route("**/copilot/main-chat", r => r.fulfill({ json: shared }));
    await p.route(`**/copilot/investigations/${shared.id}`, r => r.fulfill({ json: shared }));
    await p.route("**/copilot/chat", r => r.fulfill({ contentType: "text/event-stream", body: TURN.replace(ANSWER, answer) }));
    await p.route("**/main-chat/*/exchange", r => {
      const { transcript } = r.request().postDataJSON();
      expect(transcript).toHaveLength(2);
      expect(transcript[1].exchange_id).toBeTruthy();
      shared.transcript.push(...transcript);
      shared.revision++;
      shared.message_count = shared.transcript.length;
      return r.fulfill({ json: shared });
    });
    await p.route("**/messages/*/rating", r => {
      indexes.push(Number(r.request().url().split("/").at(-2)));
      return r.fulfill({ json: shared });
    });
    await p.goto("/copilot-lab");
    await expect(p.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  }
  const other = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  try {
    const b = await other.newPage();
    await Promise.all([device(page, "First answer."), device(b, "Second answer.")]);
    for (const [p, question] of [[page, "Question A"], [b, "Question B"]] as const) {
      await p.getByLabel("Message").fill(question);
      await p.getByLabel("Message").press("Enter");
      await expect(p.getByText("Saved", { exact: true })).toBeVisible();
    }
    const rating = b.getByRole("button", { name: "Helped", exact: true }).last();
    await rating.focus(); // leave the expanded composer before rating the saved answer
    await rating.click();
    await expect(rating).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => indexes).toEqual([3]);
    for (const p of [b, page]) {
      await p.reload();
      for (const answer of ["First answer.", "Second answer."]) await expect(p.getByText(answer, { exact: true })).toBeVisible();
    }
  } finally { await other.close(); }
});

test("before the open the book's lower block is the morning brief, cut short with its thread a tap away, and asks about it in Main chat", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-10-23T12:45:00Z") }); // 8:45 New York, a Friday
  const BRIEF = "44444444-4444-4444-8444-444444444444";
  const prior = { ...saved, main_day: "2026-10-22", title: "Main chat · 2026-10-22", symbol: null };
  const today = { ...prior, id: "33333333-3333-4333-8333-333333333333", main_day: "2026-10-23", title: "Main chat · 2026-10-23" };
  let sends = 0;
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: today }));
  await page.route("**/copilot/main-chat/history", route => route.fulfill({ json: { chats: [today, prior] } }));
  for (const chat of [prior, today]) await page.route(`**/copilot/investigations/${chat.id}`, route => route.fulfill({ json: chat }));
  await page.route("**/copilot/chat", route => { sends++; return route.abort(); });
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: {
    as_of: "2026-10-23T15:00:00Z", now: 1792767600, day: "2026-10-23", phase: "regular", open: null, close: null, events: [], time_stops: [],
    pings: null, indices: [], quote_issue: null, sections: {},
    prep: { at: 1792760400, line: "Verdict: Focus — Semis lead pre-market.", fallback: false, path: `/copilot-lab?investigation=${BRIEF}`,
      lines: ["Verdict: Focus — Semis lead pre-market.", "- **SPY** +0.4% and SMH +1.1% before the open.", "- NBIS 100C expires Friday.", "Changes if: SMH loses its gap."] },
  } }));
  await page.goto("/copilot-lab");
  await expect(page.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  const card = page.getByRole("region", { name: "Morning brief" });
  await expect(card).toContainText("09:00 ET");
  await expect(card).toContainText("FocusSemis lead pre-market.");
  // The saved lines read as words: no list marker or bold; the closing line waits with the rest in the brief's thread.
  await expect(card.getByRole("listitem")).toHaveText(["SPY +0.4% and SMH +1.1% before the open.", "NBIS 100C expires Friday."]);
  await expect(card).not.toContainText("Changes if");
  await expect(card.getByRole("link", { name: "Read the whole brief →" })).toHaveAttribute("href", `/copilot-lab?investigation=${BRIEF}`);
  await page.screenshot({ path: test.info().outputPath("main-chat-brief-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card).toBeInViewport();
  // On Now the top row drops its Now button and keeps the view switch, search and New plan on one line.
  await expect(page.getByRole("link", { name: "Now", exact: true })).toBeHidden();
  const middle = async (box: Promise<{ y: number; height: number } | null>) => { const b = await box; return b ? b.y + b.height / 2 : NaN; };
  const desk = await middle(page.getByTestId("desk-views").boundingBox());
  for (const button of [page.getByRole("button", { name: "Jump to a thread or command" }), page.getByRole("button", { name: "Plan a trade" })])
    expect(Math.abs(await middle(button.boundingBox()) - desk)).toBeLessThan(12);
  await page.screenshot({ path: test.info().outputPath("main-chat-brief-phone.png") });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByText("Previous days", { exact: true }).click();
  await page.getByRole("button", { name: "Main chat · Thu, Oct 22" }).click();
  await expect(page.getByRole("heading", { name: "Main chat · Thu, Oct 22" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Main chat · Fri, Oct 23" })).toBeVisible();
  // Ask about it stays in today's Main chat: the brief goes in the message box as context, unsent, for the question after it.
  await card.getByRole("button", { name: "Ask about it →" }).click();
  await expect(page).toHaveURL(`/copilot-lab?thread=${today.id}`);
  await expect(page.getByLabel("Message")).toHaveValue("Context: this morning's brief (09:00 ET): Focus — Semis lead pre-market. "
    + "SPY +0.4% and SMH +1.1% before the open. NBIS 100C expires Friday. Changes if: SMH loses its gap.\n\n");
  await expect(page.getByLabel("Message")).toBeFocused();
  expect(sends).toBe(0);
});
