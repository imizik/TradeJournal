import { expect, test, type Page, type Request } from "@playwright/test";
import { minutesToClose, noExit, zeroDte } from "../components/copilot/Cockpit";
import type { DeskThread } from "../lib/desk";

// Risk on the Positions rows (docs/copilot-lab.md § The book's tag): a same-day option's time left (amber, red in the
// last hour), "No exit order" only when every working order was just read, and "N× usual size". A phone row keeps a
// full-size Note and no eye beside it; its top row is the Feed and one More. Every lab route is stubbed; numbers invented.

const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL_ID = "11111111-1111-4111-8111-111111111111";
const PLAN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ORCL_CALL = "ORCL261120C00250000";
const NBIS_CALL = "NBIS261120C00100000";
const ORCL = {
  key: `trade:${ORCL_ID}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 250C", instrument: "11/20/26 250C", trade_id: ORCL_ID,
  value: null, status: { text: "On plan", tone: "muted" }, path: null, hidden: false, meter: null, investigation_id: PLAN, radar_event_id: null,
  changed_at: null, book: { usd: -420, pct: -33.9, expiry: "2026-11-20", days_held: 1, track: null, state: "on_plan", planned: true, stop_pct: null,
    account: { label: "Roth IRA", masked: "••8267" }, plan_levels: { stop: 240, target: 258 },
    tick: { quote: ORCL_CALL, scale: 100, cost: 620, quantity: 2, sign: 1 },
    option: { side: "call", strike: 250, expiry: "2026-11-20", direction: "long", quantity: 2, multiplier: 100, cost: 620,
      greeks: { delta: 0.38, theta: -0.31, iv: 0.44, as_of: epoch("2026-11-13T15:59:30Z"), source: "robinhood" } } },
};
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [ORCL],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const PAPER_POSITION = {
  id: "99999999-9999-4999-8999-999999999999", symbol: "NBIS", instrument: "option", option_type: "call", expiry: "2026-11-20",
  label: "NBIS $100 Call 11/20/26", bias: "long", credit: false, width: null, multiplier: 100, quantity: 2, remaining: 2, per_share: -3.4,
  cash: -680, basis: -680, stock: 98.05, note: null, stop: 95, target: 105, opened_at: epoch("2026-11-13T15:10:00Z"),
  status: "open", closed_at: null, realized: 0, legs: [{ quote: NBIS_CALL, action: "buy", strike: 100 }], awaiting_close: false,
  mark: { per_share: 3.6, value: 720, pnl: 40, pct: 5.9, at: epoch("2026-11-13T15:50:00Z") }, auto: false, touched: {}, exiting: false, held: 0,
};
const stats = { trades: 0, pnl: 0, win_rate: null, avg_win: null, avg_loss: null, largest_loss: null, curve: [] };
const PAPER = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9320, collateral: 0, reserved: 0, buying_power: 9320, equity: 10040, pnl: 40, unpriced: 0 },
  positions: [PAPER_POSITION], closed: [], orders: [], score: { paper: stats, real: stats }, earlier: [], market_open: true,
};

function orclChart() {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 247 + Math.sin(i / 5);
    return { time: last - (59 - i) * 120, open, high: open + 0.4, low: open - 0.4, close: open + 0.1, volume: 1000, extended: false };
  });
  return { symbol: "ORCL", timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 247, at: last, daily: false, prev_close: 249.5, vwap: null, vwap_at: null, rvol: null },
    levels: [{ role: "entry", price: 245, label: "Entry 245.00", id: "e1" }, { role: "invalidation", price: 240, label: "Invalidation 240.00", id: "i1" },
      { role: "target", price: 258, label: "Target 258.00", id: `target:c1` }],
    alerts: [], marks: [], time_stop: null, events: { earnings: null, macro: [], note: null } };
}

const ALERT = { id: "i1", symbol: "ORCL", price: 240, created_on: "2026-11-12", condition: "crosses", interval: null, session: "regular", direction: "down",
  source_kind: "copilot", source_id: PLAN, label: "ORCL invalidation", state: "active", armed_at: epoch("2026-11-12T15:00:00Z"), event: null, plan_role: "invalidation" };

async function open(page: Page, { width = 375, height = 812, threads = THREADS, now = NOW }: { width?: number; height?: number; threads?: object; now?: Date } = {}) {
  const writes: Request[] = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: now });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: threads }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
    ORCL: { points: [250, 248, 247], change_pct: -1.2, last: 247 }, NBIS: { points: [97, 98], change_pct: 1.1, last: 98.2 } } } }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [] } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper"), route => route.fulfill({ json: PAPER }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.request().url().includes(PLAN) && route.request().url().includes("/chart")
    ? route.fulfill({ json: orclChart() }) : route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/ticks?*", async route => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [ORCL_CALL]: { last: 4.1, change_pct: null, prev_close: null, at }, ORCL: { last: 247, change_pct: -1.0, prev_close: 249.5, at },
      [NBIS_CALL]: { last: 3.8, change_pct: null, prev_close: null, at }, NBIS: { last: 98.2, change_pct: 1.1, prev_close: 97.1, at },
    } } });
  });
  page.on("request", request => { if (request.method() !== "GET") writes.push(request); });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return writes;
}

const book = (page: Page) => page.getByTestId("desk-book");

const ZERO = { ...ORCL, book: { ...ORCL.book, live: "matched", expiry: "2026-11-13", size_x: 2.6, option: { ...ORCL.book.option, expiry: "2026-11-13" } } };
const LIVE_THREADS = { ...THREADS, threads: [ZERO], robinhood: { state: "ok", as_of: epoch("2026-11-13T15:59:00Z"), joined: true, orders_read: true,
  accounts: [{ label: "Roth IRA", masked: "••8267", total_value: 10000, cash: 1000, buying_power: 1000 }] } };
const row = (book: object) => ({ symbol: "ORCL", instrument: "11/13/26 250C", book } as unknown as DeskThread);

test("the badges' rules: today's expiry, minutes to 16:00 New York, and no exit order only on a whole read", () => {
  expect(zeroDte(row({ expiry: "2026-11-13", option: {} }), "2026-11-13")).toBe(true);
  expect(zeroDte(row({ expiry: "2026-11-14", option: {} }), "2026-11-13")).toBe(false);
  expect(minutesToClose(epoch("2026-11-13T19:55:00Z"))).toBe(65); // 14:55 New York
  const long = { live: "matched", option: { direction: "long" }, orders: [{ working: true, action: "Buy to open" }] };
  expect(noExit(row(long), true)).toBe(true);
  expect(noExit(row(long), false)).toBe(false); // the order read is off or partial: say nothing
  expect(noExit(row({ ...long, orders: [{ working: true, action: "Sell to close" }] }), true)).toBe(false);
  expect(noExit(row({ ...long, orders: [{ working: true, action: "Buy to open" }] }), true)).toBe(true); // a scale-in is not an exit
  expect(noExit(row({ ...long, live: "new" }), true)).toBe(true);
  expect(noExit(row({ ...long, live: "not_on_robinhood" }), true)).toBe(false); // sold; its close has not reached the journal
  expect(noExit(row({ ...long, live: undefined }), true)).toBe(false);
});

test("a phone row shows 0DTE with time left, No exit order and the size, and no eye beside its Note", async ({ page }) => {
  await open(page, { threads: LIVE_THREADS });
  const r = book(page).locator("li").filter({ hasText: "ORCL" }).first();
  await expect(r.getByTestId("book-0dte")).toHaveText("0DTE · 5h 00m left");
  await expect(r.getByTestId("book-no-exit")).toHaveText("No exit order");
  await expect(r.getByTestId("book-size")).toHaveText("2.6× usual size");
  await expect(r.getByRole("button", { name: /^Hide ORCL/ })).toBeHidden();
  await expect(r.getByTestId("book-0dte")).not.toHaveAttribute("data-urgent");
});

test("in the last hour the 0DTE badge is red", async ({ page }) => {
  await open(page, { threads: LIVE_THREADS, now: new Date("2026-11-13T20:10:00Z") }); // 15:10 New York
  const r = book(page).locator("li").filter({ hasText: "ORCL" }).first();
  await expect(r.getByTestId("book-0dte")).toHaveText("0DTE · 50m left");
  await expect(r.getByTestId("book-0dte")).toHaveAttribute("data-urgent", "true");
  await book(page).screenshot({ path: test.info().outputPath("risk-badges-phone.png") });
});

test("a phone's top row keeps Threads in its More", async ({ page }) => {
  await open(page);
  await expect(page.getByRole("button", { name: "Threads", exact: true })).toHaveCount(0);
  await page.getByTestId("desk-top-more").click();
  await page.getByTestId("desk-top-menu").getByRole("menuitem", { name: "Threads and previous days" }).click();
  await expect(page.getByTestId("desk-top-menu")).toHaveCount(0);
});
