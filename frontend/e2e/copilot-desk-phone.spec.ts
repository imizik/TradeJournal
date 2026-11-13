import { expect, test, type Page } from "@playwright/test";

// The desk on a phone (docs/copilot-lab.md § The desk, "On a phone"): nothing scrolls sideways, the strip and the book are
// the first screen, the copilot sheet opens from the round Ask button and closes with one tap, the message box stays in
// view at the height the software keyboard leaves, and tapping a position keeps its chart in view while the copilot opens
// its conversation behind the closed sheet. Every lab route is stubbed in the browser; nothing reaches a model or Robinhood.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Thursday November 12, 2026, 11:05 in New York: in the session.
const NOW = new Date("2026-11-12T16:05:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const MAIN = "77777777-7777-4777-8777-777777777777";
const ACCOUNTS = [{ label: "Roth IRA", masked: "••8267" }, { label: "MCP", masked: "••7884" }, { label: "Individual", masked: "••1113" }];
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
/** Twelve followed options across three accounts, one of them five figures up. */
const ROWS = ["NBIS", "CRWV", "SOFI", "ORCL", "IREN", "APLD", "SMCI", "TSLA", "AMD", "PLTR", "HOOD", "AAPL"].map((symbol, i) => {
  const usd = symbol === "AMD" ? 12345 : (i % 2 ? -1 : 1) * (120 + i * 37);
  return row({ key: `robinhood:${ACCOUNTS[i % 3].masked}:${symbol} 11/21/26 ${100 + i}C`, group: "watch", symbol, title: `${symbol} 11/21/26 ${100 + i}C`,
    instrument: `11/21/26 ${100 + i}C`, value: { text: `$${usd}`, tone: usd > 0 ? "gain" : "loss" }, status: { text: "New · not in the journal yet", tone: "info" },
    path: `/copilot-lab?symbol=${symbol}`, book: { usd, pct: usd / 10, expiry: "2026-11-21", days_held: null, track: null, state: "no_plan", planned: false,
      stop_pct: null, quantity: 2, mark: 300, account: ACCOUNTS[i % 3], live: "new" } });
});
const LIVE = { state: "ok", joined: true, as_of: epoch("2026-11-12T16:04:00Z"), issue: null,
  accounts: ACCOUNTS.map((a, i) => ({ ...a, total_value: [18898, 2410, 7428][i], cash: 0, buying_power: 0 })) };
const DESK = { as_of: "2026-11-12T16:05:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok" }, plans: [], robinhood: LIVE,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...ROWS] };
const SESSION = {
  as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", phase: "regular",
  open: epoch("2026-11-12T14:30:00Z"), close: epoch("2026-11-12T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 680.1, change_pct: 0.42 }, { symbol: "QQQ", last: 612.3, change_pct: 0.71 }, { symbol: "VIX", last: 16.2, change_pct: -3.4 }],
  quote_issue: null, realized_today: -1286, sections: {},
  to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: "t1", symbol: "APLD", contract: "APLD 11/21 105C", kind: "giveback",
    at: epoch("2026-11-12T15:12:00Z"), today: true, feedback: null }] }, radar: null },
};
const TRANSCRIPT = Array.from({ length: 6 }, (_, i) => [
  { role: "user", content: `Question ${i + 1}: what matters right now?` },
  { role: "assistant", content: `Verdict: Wait — answer ${i + 1}.\n\n${"- A line of the answer that runs long enough to wrap on a phone.\n".repeat(6)}` },
]).flat();
const MAIN_CHAT = { id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null, revision: 1, message_count: TRANSCRIPT.length,
  has_findings: false, created_at: "2026-11-12T14:00:00Z", updated_at: "2026-11-12T16:00:00Z", evidence: [], findings: null, transcript: TRANSCRIPT,
  main_day: "2026-11-12" };
const TICKET = {
  state: "ok", investigation_id: "inv-nbis", symbol: "NBIS", direction: "long", thesis: "Reclaims VWAP with the group", option_type: "call", entry: 95.9,
  invalidation: 92.3, time_stop: null, plan_contract_words: null, size: { contracts: 2, risk_usd: null, text: "2 contracts" }, simulated: false, account: "roth",
  accounts: [{ id: "roth", label: "Roth IRA", last4: "8267", kind: "roth" }, { id: "mcp", label: "MCP", last4: "7884", kind: "mcp" }],
  contract: { strike: 100, expiry: "2026-11-21", type: "call", label: "NBIS $100 Call 11/21/26", source: "plan", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: epoch("2026-11-12T16:04:00Z"), bid: 3.1, ask: 3.3, mid: 3.2, spread: 0.2, spread_pct: 6.3, multiplier: 100 },
  underlying: { state: "ok", last: 95, as_of: epoch("2026-11-12T16:04:00Z") }, expected_move_pct: 6, limit: 3.2, contracts: 2,
};

/** ``mainChatHeld``: the Main chat answers only once the test lets it (the returned ``release``), so a tap can come first. */
async function open(page: Page, { width = 393, height = 852, path = "/copilot-lab", mainChatHeld = false } = {}) {
  let release = () => {};
  const held = mainChatHeld ? new Promise<void>(resolve => { release = resolve; }) : Promise.resolve();
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-12", since: "2026-11-11", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", async route => {
    await held;
    await route.fulfill({ json: MAIN_CHAT }).catch(() => { /* the page moved on */ });
  });
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: MAIN_CHAT }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [{ investigation_id: "inv-nbis", symbol: "NBIS", direction: "long",
    instrument: "calls", thesis: "Reclaims VWAP with the group", confirmed_at: epoch("2026-11-12T15:55:00Z"), entry: 95.9, invalidation: 92.3 }] } }));
  await page.route(/\/copilot\/tickets\/[^/]+$/, route => route.fulfill({ json: TICKET }));
  await page.goto(path);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return release;
}

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const top = (page: Page, testId: string) => page.getByTestId(testId).evaluate(el => el.getBoundingClientRect().top);
const centreTop = (page: Page) => page.locator("#desk-centre").evaluate(el => el.getBoundingClientRect().top);

for (const width of [375, 393, 440]) {
  test(`at ${width} px: nothing scrolls sideways, the strip and the book come first, the sheet opens and closes`, async ({ page }) => {
    await open(page, { width });
    await expect(page.getByTestId("needs-you")).toBeVisible();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    // The first screen: the strip, then the book's heading and its first rows above the tab bar.
    const tabBar = await page.getByRole("navigation", { name: "Main tabs" }).evaluate(el => el.getBoundingClientRect().top);
    expect(await top(page, "needs-you")).toBeLessThan(260);
    const third = await page.getByTestId("desk-book").locator("li").nth(2).evaluate(el => el.getBoundingClientRect().bottom);
    expect(third).toBeLessThanOrEqual(tabBar);
    // The accounts are one row that swipes sideways inside itself (the page does not); the numbers stay masked.
    const line = page.getByTestId("desk-accounts");
    await expect(line.getByTestId("desk-account").first()).toContainText("Roth IRA••8267$18,898");
    const boxes = await line.getByTestId("desk-account").evaluateAll(els => els.map(el => el.getBoundingClientRect().top));
    expect(new Set(boxes.map(Math.round)).size).toBe(1); // one row
    expect(await line.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
    await line.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    await expect(line.getByTestId("desk-account").last()).toBeInViewport();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    // A five-figure P&L stays in its own column, clear of the hide button.
    const amd = page.getByTestId("desk-book").getByRole("listitem").filter({ hasText: "AMD" });
    const figure = await amd.getByText("+$12,345").evaluate(el => el.getBoundingClientRect().right);
    const eye = await amd.getByRole("button", { name: /^Hide AMD/ }).evaluate(el => el.getBoundingClientRect().left);
    expect(figure).toBeLessThanOrEqual(eye);
    for (const tab of ["Feed", "Check a call", "Ticket"]) {
      await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
      expect(await sideways(page), `${tab} at ${width} px`).toBeLessThanOrEqual(0);
    }
    // The round Ask button opens the copilot over the page; one tap on Desk closes it.
    const ask = page.getByRole("button", { name: /^Ask the copilot/ });
    const box = await ask.boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44);
    await ask.click();
    const sheet = page.getByRole("region", { name: "Conversation" });
    await expect(sheet.getByRole("textbox", { name: "Message" })).toBeInViewport();
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await sheet.getByRole("button", { name: "Back to the desk" }).click();
    await expect(sheet.getByRole("textbox", { name: "Message" })).toBeHidden();
    await expect(page.getByTestId("desk-book")).toBeVisible();
  });
}

test("with the software keyboard up the message box stays in view", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /^Ask the copilot/ }).click();
  const message = page.getByRole("region", { name: "Conversation" }).getByRole("textbox", { name: "Message" });
  await message.click();
  // The keyboard leaves about 516 of the iPhone 17's 852 points.
  await page.setViewportSize({ width: 393, height: 516 });
  await expect(message).toBeInViewport();
  await expect(page.getByRole("region", { name: "Conversation" }).getByRole("button", { name: "Send" })).toBeInViewport();
});

test("tapping a position keeps its chart in view while the copilot opens behind the closed sheet", async ({ page }) => {
  const release = await open(page, { mainChatHeld: true });
  await page.getByTestId("desk-book").getByRole("button", { name: /^SOFI/ }).click();
  // In view near the top (the page's end can stop it a little short of the very top).
  await expect.poll(() => centreTop(page)).toBeLessThan(250);
  // Now the Main chat opens in the closed sheet and tries to land for the next two seconds: the page stays on the chart.
  release();
  await expect(page.locator("section[aria-label=Conversation] h2", { hasText: "Main chat" })).toBeAttached(); // in the closed sheet
  await page.waitForTimeout(3000);
  expect(await centreTop(page)).toBeLessThan(250);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(400);
});

test("a ticket link from a phone ping lands on the Ticket", async ({ page }) => {
  await open(page, { path: "/copilot-lab?ticket=inv-nbis" });
  await expect(page.getByRole("tab", { name: "Ticket" })).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => centreTop(page)).toBeLessThan(250);
  await page.waitForTimeout(2500);
  expect(await centreTop(page)).toBeLessThan(250);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(400);
});
