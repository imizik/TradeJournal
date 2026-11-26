import { expect, test, type Page } from "@playwright/test";

// The phone desk as a quick look at Robinhood (docs/copilot-lab.md § The desk, Phone): the value block and its one-line
// read at the top of Positions, each position's price now and move today, the desk's own tab bar (Positions, the ticker's
// Chart, Chain, Orders, Ask, then More), the Chain's ticker chips, the Orders view (working first, then today's fills),
// and every other page keeping the app's bar. Every lab route is stubbed in the browser; nothing reaches a model or
// Robinhood, and no order can be placed from any of it.
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
const order = (fields: Record<string, unknown>) => ({
  contract: "NBIS 11/21/26 100C", symbol: "NBIS", instrument: "option", action: "Sell to close", working: true, quantity: 2, filled: 0,
  price_kind: "limit", limit: 4.5, avg: null, placed_at: epoch("2026-11-12T15:50:00Z"), filled_at: null, account: ACCOUNTS[0], pairing: null, ...fields,
});
const SYMBOLS = ["NBIS", "CRWV", "SOFI", "ORCL", "IREN", "APLD", "SMCI", "TSLA", "AMD", "PLTR", "HOOD", "AAPL"];
/** Twelve followed options across three accounts (their P&L sums to +$11,707). NBIS has Robinhood's mark and move today
 * and a working order; SOFI is near its stop; CRWV has neither a mark nor a move: dashes, never zero. */
const ROWS = SYMBOLS.map((symbol, i) => {
  const usd = symbol === "AMD" ? 12345 : (i % 2 ? -1 : 1) * (120 + i * 37);
  return row({ key: `robinhood:${ACCOUNTS[i % 3].masked}:${symbol} 11/21/26 ${100 + i}C`, group: "watch", symbol, title: `${symbol} 11/21/26 ${100 + i}C`,
    instrument: `11/21/26 ${100 + i}C`, value: { text: `$${usd}`, tone: usd > 0 ? "gain" : "loss" }, status: { text: "New · not in the journal yet", tone: "info" },
    path: `/copilot-lab?symbol=${symbol}`, book: { usd, pct: usd / 10, expiry: "2026-11-21", days_held: null, track: null,
      state: symbol === "SOFI" ? "near_stop" : "no_plan", planned: symbol === "SOFI", stop_pct: symbol === "SOFI" ? -1.2 : null, quantity: 2,
      mark: symbol === "CRWV" ? null : 300, day_change: symbol === "NBIS" ? 40 : null, account: ACCOUNTS[i % 3], live: "new",
      ...(symbol === "NBIS" ? { orders: [order({})] } : {}) } });
});
const LIVE = { state: "ok", joined: true, as_of: epoch("2026-11-12T16:04:00Z"), issue: null,
  accounts: ACCOUNTS.map((a, i) => ({ ...a, total_value: [18898, 2410, 7428][i], day_change: [120, -36, 0][i], options_value: [14100, 900, 0][i],
    cash: [2300, 1510, 7428][i], buying_power: [1200, 1510, 7428][i], open_pnl: [500, -20, 0][i] })),
  // An order with no position yet, working, and a fill that closed one today.
  orders: [order({ contract: "MU 11/20/26 120C", symbol: "MU", action: "Buy to open", quantity: 1, limit: 3.1, placed_at: epoch("2026-11-12T16:00:00Z"), account: ACCOUNTS[1] }),
    order({ contract: "RKLB 11/20/26 60C", symbol: "RKLB", working: false, filled: 2, avg: 1.93, placed_at: epoch("2026-11-12T15:00:00Z"),
      filled_at: epoch("2026-11-12T15:02:00Z"), pairing: "provisional" })] };
const desk = (robinhood: object) => ({ as_of: "2026-11-12T16:05:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok", plans: "ok" }, plans: [], robinhood,
  threads: [row({ key: "briefing", group: "pinned", title: "Briefing", status: { text: "Nothing new.", tone: "muted" } }), ...ROWS] });
const SESSION = {
  as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", phase: "regular",
  open: epoch("2026-11-12T14:30:00Z"), close: epoch("2026-11-12T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [{ symbol: "SPY", last: 680.1, change_pct: 0.42 }, { symbol: "QQQ", last: 612.3, change_pct: 0.71 }, { symbol: "VIX", last: 16.2, change_pct: -3.4 }],
  quote_issue: null, realized_today: -1286, sections: {}, to_answer: { alerts: { count: 0, rows: [] }, radar: null },
};
const MAIN_CHAT = { id: MAIN, source: "copilot", title: "Main chat", symbol: null, status: "open", conclusion: null, revision: 1, message_count: 0,
  has_findings: false, created_at: "2026-11-12T14:00:00Z", updated_at: "2026-11-12T16:00:00Z", evidence: [], findings: null, transcript: [],
  main_day: "2026-11-12" };

function chain(symbol: string) {
  const now = epoch("2026-11-12T16:05:00Z");
  const cell = (strike: number, side: "call" | "put") => ({
    symbol: `${symbol}261120${side === "call" ? "C" : "P"}${String(strike * 1000).padStart(8, "0")}`, bid: 2.4, ask: 2.6, mark: 2.5, last: null,
    spread: 0.2, spread_pct: 8, wide: false, spread_note: null, volume: 120, open_interest: 900, delta: side === "call" ? 0.5 : -0.5, iv: 64,
    quoted_at: now - 20, state: "ok", multiplier: 100, held: null, planned: false,
  });
  return {
    symbol, state: "ok", session: "open", poll_seconds: 15, simulated: false, root: symbol, centred_on: "price",
    expiries: [{ date: "2026-11-20", days: 8, kind: "monthly", held: false }], earnings: null, expiration: "2026-11-20", spot: 100, spot_at: now - 5,
    spot_issue: null, atm_strike: 100, fetched_at: now - 3, age_s: 3, stale: false, message: null,
    rows: [95, 100, 105].map(strike => ({ strike, atm: strike === 100, levels: [], call: cell(strike, "call"), put: cell(strike, "put") })), levels: [],
  };
}

async function open(page: Page, { width = 375, height = 812, robinhood = LIVE as object } = {}) {
  const reads = { chain: [] as string[] };
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: desk(robinhood) }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-12", since: "2026-11-11", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", spy_change_pct: 0.4, rows: {} } }));
  await page.route("**/copilot/desk/ticks?*", route => route.fulfill({ json: { state: "ok", as_of: "2026-11-12T16:05:00Z", rows: {}, poll_seconds: 5 } }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: { state: "ok", symbols: ["MU"], count: 1, max: 30, levels: {}, setups: {}, imported_at: null, robinhood: "off" } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-12T16:05:00Z", now: epoch("2026-11-12T16:05:00Z"), day: "2026-11-12", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route(/\/copilot\/chain\?/, route => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol") ?? "";
    reads.chain.push(symbol);
    return route.fulfill({ json: chain(symbol) });
  });
  await page.route("**/copilot/unusual", route => route.fulfill({ json: { state: "ok", session: "open", label: "live", day: "2026-11-12", rule: "", rows: [], tickers: [], unread: [], no_history: [], stale: [], held: [], message: null, simulated: false } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/main-chat", route => route.fulfill({ json: MAIN_CHAT }));
  await page.route("**/copilot/main-chat/history*", route => route.fulfill({ json: { conversations: [] } }));
  await page.route(`**/copilot/investigations/${MAIN}`, route => route.fulfill({ json: MAIN_CHAT }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [] } }));
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return reads;
}

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
const tabs = (page: Page) => page.getByRole("navigation", { name: "Main tabs" });

for (const [width, height] of [[360, 780], [375, 812], [390, 844]] as const) {
  test(`at ${width} px: the value block, its one-line read and each position's price now and today come first`, async ({ page }) => {
    await open(page, { width, height });
    const value = page.getByTestId("desk-value");
    await expect(value.getByTestId("mode-mark")).toHaveAttribute("data-mode", "real");
    await expect(value.getByTestId("value-who")).toHaveText("3 accounts");
    await expect(value.getByTestId("value-total")).toContainText("$28,736");
    // One line (November 26, 2026): today +$120 − $36 + $0 on a $28,652 start, then the book; realized is the day card's.
    await expect(value.getByTestId("value-today")).toHaveText("+$84 +0.3% today");
    await expect(value.getByTestId("value-realized")).toHaveCount(0);
    await expect(value.getByTestId("value-read")).toHaveText("12 open+$11,707▾");
    // Under it, in red, only what makes a position need him; the orders are the Orders tab's.
    await expect(value.getByTestId("value-flags")).toHaveText("1 near stop");
    // Above the fold, with no page scrolled sideways (the old account strip was cut off at the right).
    const bar = await tabs(page).evaluate(el => el.getBoundingClientRect().top);
    expect(await value.evaluate(el => el.getBoundingClientRect().bottom)).toBeLessThan(bar);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    // A row: the contract's price now and its move today; none known is a dash, never zero.
    const book = page.getByTestId("desk-book");
    const nbis = book.getByRole("listitem").filter({ has: page.getByRole("button", { name: /^NBIS/ }) });
    await expect(nbis.getByTestId("book-now")).toHaveText("$3.00 · today +$40");
    const crwv = book.getByRole("listitem").filter({ has: page.getByRole("button", { name: /^CRWV/ }) });
    await expect(crwv.getByTestId("book-now")).toHaveCount(0); // no price and no move: no dashes stand in
    // A tap on the value: each account as its own row (masked), never a strip that swipes; a tap on one narrows the book.
    await value.getByTestId("value-open").click();
    const accounts = value.getByTestId("value-account");
    await expect(accounts).toHaveCount(3);
    await expect(accounts.first()).toContainText("Roth IRA••8267$18,898+$120");
    await expect(accounts.first()).toContainText("options $14.1K");
    await expect(accounts.first()).toContainText("cash $2.3K");
    await expect(accounts.first()).toContainText("buying power $1.2K");
    const tops = await accounts.evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(3); // one under another
    for (const a of await accounts.all()) expect((await a.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await expect(page.locator("body")).not.toContainText("333338267");
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await accounts.nth(1).click();
    await expect(accounts.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(value.getByTestId("value-who")).toHaveText("MCP ••7884"); // a picked account names itself beside its total
    await expect(value.getByTestId("value-total")).toContainText("$2,410");
    await expect(value.getByTestId("value-read")).toHaveText(/^4 open/); // CRWV, IREN, TSLA, HOOD
    await page.screenshot({ path: test.info().outputPath(`phone-value-${width}.png`) });
  });
}

test("not live: the block says so in grey with its time and shows no money", async ({ page }) => {
  await open(page, { robinhood: { state: "stale", as_of: epoch("2026-11-12T15:40:00Z") } });
  const value = page.getByTestId("desk-value");
  await expect(value.getByTestId("value-off")).toHaveText("Robinhood stale · from the journal · as of 10:40 AM");
  await expect(value.getByTestId("value-total")).toHaveCount(0);
  await expect(value).not.toContainText("$0");
  // The book's own rows are counted all the same.
  await expect(value.getByTestId("value-read")).toHaveText("12 open+$11,707");
  await expect(value.getByTestId("value-flags")).toHaveText("1 near stop");
  await page.getByTestId("desk-view-orders").click();
  await expect(page.getByTestId("phone-orders-quiet")).toContainText("Robinhood stale");
});

test("the desk's tab bar: Positions, Chart, Chain, Orders and Ask, each thumb-sized, nothing sideways", async ({ page }) => {
  await open(page);
  const bar = tabs(page);
  await expect(bar.getByRole("button")).toHaveText(["Positions", "NBIS", "Chain", "Orders", "Ask", "More"]);
  await expect(bar.getByRole("link")).toHaveCount(0); // Charts, Plan and Trades are under More (and Plan in the top row)
  for (const b of await bar.getByRole("button").all()) {
    const box = (await b.boundingBox())!;
    expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(44);
  }
  // The top row keeps the health dot, Day, ⌘K and More; the Feed is under More (November 26, 2026). No view switch.
  await expect(page.getByRole("navigation", { name: "Desk views" })).toHaveCount(0);
  for (const name of [/^Day|^Start|^Close/, /Jump to a thread or command/]) await expect(page.getByRole("button", { name }).first()).toBeVisible();
  await expect(page.getByTestId("desk-view-feed")).toBeHidden();
  await expect(page.getByTestId("desk-view-book")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("desk-value")).toBeVisible();

  // Chart: the selected ticker's chart, the dock under it.
  await page.getByTestId("desk-view-ticker").click();
  await expect(page.getByTestId("desk-view-ticker")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("desk-chart")).toBeVisible();
  await expect(page.getByTestId("desk-value")).toBeHidden();
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  // The Grid's button is no longer under a floating Ask button: there is none on a phone.
  const grid = (await page.getByTestId("grid-open").boundingBox())!;
  expect(grid.width).toBeGreaterThanOrEqual(44);
  await expect(page.locator("button", { hasText: /^Ask the copilot/ })).toBeHidden();
  await page.getByTestId("grid-open").click();
  await expect(page.getByTestId("desk-grid-view")).toBeVisible();
  await page.getByTestId("desk-view-ticker").click(); // Chart closes the Grid
  await expect(page.getByTestId("desk-dock")).toBeVisible();

  // Orders: working first (newest first), then today's fills, each with its contract. Read only.
  await page.getByTestId("desk-view-orders").click();
  const orders = page.getByTestId("phone-orders");
  await expect(orders).toBeVisible();
  await expect(orders.getByTestId("book-order")).toHaveText([/^MU 11\/20\/26 120CWorking: Buy to open 1 @ 3.10 · MCP/, /^NBIS 11\/21\/26 100CWorking: Sell to close 2 @ 4.50 · Roth IRA/,
    /^RKLB 11\/20\/26 60CFilled: Sell to close 2 @ 1.93, 10:02/]);
  expect(await orders.getByTestId("book-order").evaluateAll(els => els.map(el => el.getAttribute("data-working")))).toEqual(["true", "true", "false"]);
  await expect(orders.getByRole("button")).toHaveCount(0); // nothing to place, change or cancel
  await expect(page.getByTestId("desk-book")).toBeHidden();
  expect(await sideways(page)).toBeLessThanOrEqual(0);

  // The Feed from More, and back.
  await page.getByTestId("desk-top-more").click();
  await page.getByTestId("desk-top-feed").click();
  await expect(page.getByTestId("desk-feed")).toBeVisible();
  expect(await sideways(page)).toBeLessThanOrEqual(0);

  // Positions: the value block, the strip and the book again.
  await page.getByTestId("desk-view-book").click();
  await expect(page.getByTestId("desk-value")).toBeVisible();
  await expect(page.getByTestId("desk-book")).toBeVisible();

  // Ask: the copilot's sheet; Desk closes it.
  await page.getByTestId("desk-view-ask").click();
  const sheet = page.getByRole("region", { name: "Conversation" });
  await expect(sheet.getByRole("textbox", { name: "Message" })).toBeInViewport();
  await sheet.getByRole("button", { name: "Back to the desk" }).click();
  await expect(sheet.getByRole("textbox", { name: "Message" })).toBeHidden();
  await page.screenshot({ path: test.info().outputPath("phone-tabs-375.png") });
});

test("Chain: the held ticker's chain in one tap, and a chip switches to another ticker", async ({ page }) => {
  const reads = await open(page);
  await page.getByTestId("desk-view-chain").click();
  await expect(page.getByTestId("desk-view-chain")).toHaveAttribute("aria-pressed", "true");
  const chips = page.getByTestId("chain-chip");
  // His book's tickers first, then the watched names; none he set to Not following.
  await expect(chips).toHaveText([...SYMBOLS, "MU"]);
  await expect(chips.first()).toHaveAttribute("aria-pressed", "true");
  const panel = page.getByRole("tabpanel", { name: "Chain" });
  await expect(panel.getByTestId("desk-chain")).toBeVisible();
  await expect.poll(() => reads.chain.at(-1)).toBe("NBIS");
  // The chart and the dock's tab row wait on the Chart tab: the chain sits right under the chips.
  await expect(page.locator("#desk-centre").getByRole("tablist", { name: "Centre" })).toBeHidden();
  await chips.filter({ hasText: /^MU$/ }).click();
  await expect(chips.filter({ hasText: /^MU$/ })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => reads.chain.at(-1)).toBe("MU");
  await expect(page.getByTestId("desk-view-ticker")).toHaveText("MU"); // the Chart tab follows the ticker
  for (const chip of await chips.all()) expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await page.screenshot({ path: test.info().outputPath("phone-chain-375.png") });
  // Chart from here: the ticker's view, the dock back on its default.
  await page.getByTestId("desk-view-ticker").click();
  await expect(page.locator("#desk-centre").getByRole("tablist", { name: "Centre" })).toBeVisible();
});

test("only the desk swaps the bar: other pages keep theirs, and the laptop keeps its own layout", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("desk-tabs")).toBeAttached();
  await page.goto("/charts?symbol=NBIS");
  const bar = tabs(page);
  await expect(bar.getByRole("link", { name: "Desk" })).toBeVisible();
  await expect(bar.getByRole("link", { name: "Charts" })).toBeVisible();
  await expect(bar.getByRole("link", { name: "Plan a trade" })).toBeVisible();
  await expect(bar.getByTestId("desk-view-book")).toHaveCount(0);
  // The laptop: no value block, no tab bar; the account line sits under the book's heading.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await expect(page.getByTestId("desk-value")).toBeHidden();
  await expect(page.getByTestId("desk-accounts")).toBeVisible();
  await expect(page.getByTestId("book-now").first()).toBeHidden();
  await expect(tabs(page)).toBeHidden();
});
