import { expect, test, type Page, type Request } from "@playwright/test";
import { levelsProblem, markNow, panelCloseTicket, paperBreakEven, planSide } from "../lib/deskPosition";
import type { DeskThread } from "../lib/desk";

// The Position panel (docs/copilot-lab.md § Where a held option stands): one panel under the chart for the selected
// position with a button for every way he manages it. Real: Stop / target moves the plan's stop through its own alert's
// rearm (at a fresh quote) and its target through the plan; Trim and Close open the Ticket's close-now view (copy only);
// Roll the roll ticket; Note the note line. Paper: the same on paper (no Roll), the stop and target saved after entry.
// The book row keeps only its standing line. Every lab route is stubbed; every number is invented.

// ------------------------------------------------------------------------------------------------ the arithmetic

const NOW_S = 1_794_000_000;
const ticksOf = (rows: Record<string, number>, at = Math.floor(Date.now() / 1000)) => ({ open: true, checked: at,
  rows: Object.fromEntries(Object.entries(rows).map(([s, last]) => [s, { last, change_pct: null, prev_close: null, at }])) });
const optionRow = (book: object): DeskThread => ({
  key: "trade:1", group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 250C", instrument: "11/20/26 250C", value: null,
  status: { text: "", tone: "muted" }, meter: null, investigationId: "inv", tradeId: "1", radarEventId: null, path: null, changedAt: null,
  horizon: null, close: null, fillToLink: null, hidden: false, book: book as DeskThread["book"],
});
const ORCL_BOOK = { usd: -420, pct: -33.9, expiry: "2026-11-20", days_held: 1, track: null, state: "on_plan", stop_pct: null, quantity: 3,
  account: { label: "Roth IRA", masked: "••8267" }, tick: { quote: "ORCL261120C00250000", scale: 100, cost: 620, quantity: 3, sign: 1 },
  option: { side: "call", strike: 250, expiry: "2026-11-20", direction: "long", quantity: 3, multiplier: 100, cost: 620, greeks: null } };

test("a share's price now: a live tick as quoted, else the book's contract mark over 100 (a share's mark over 1)", () => {
  expect(markNow(ORCL_BOOK as never, ticksOf({ ORCL261120C00250000: 4.1 }, NOW_S), NOW_S)).toEqual({ share: 4.1, live: true });
  // No tick: the contract's mark $410 is 4.10 a share.
  expect(markNow({ ...ORCL_BOOK, mark: 410 } as never, ticksOf({}), NOW_S)).toEqual({ share: 4.1, live: false });
  // Shares: the mark is a share's already.
  expect(markNow({ mark: 98.4, tick: { quote: "NBIS", scale: 1, cost: 90, quantity: 10, sign: 1 } } as never, ticksOf({}), NOW_S)).toEqual({ share: 98.4, live: false });
  expect(markNow({ mark: null } as never, ticksOf({}), NOW_S)).toBeNull();
});

test("which way the plan gains, and where a stop and target may go", () => {
  expect(planSide({ entry: 245, stop: 240 }, {})).toBe("long");
  expect(planSide({ entry: 28, stop: 29.5 }, {})).toBe("short");
  // Without an entry: a long call gains as the stock rises, a long put as it falls, a short call as it falls.
  expect(planSide({ stop: 240 }, { option: { side: "call", direction: "long" } })).toBe("long");
  expect(planSide({ stop: 29.5 }, { option: { side: "put", direction: "long" } })).toBe("short");
  expect(planSide({}, { option: { side: "call", direction: "short" } })).toBe("short");
  expect(planSide({}, { option: null, sign: -1 })).toBe("short");
  expect(planSide({}, {})).toBeNull();
  // A long's stop sits under the price and its target over the stop; a short's the other way round.
  expect(levelsProblem("long", 247, 242, 260)).toBeNull();
  expect(levelsProblem("long", 247, 248, 260)).toBe("The stock is at 247.00: a long plan's stop goes below it.");
  expect(levelsProblem("long", 247, 242, 241)).toBe("A long plan's target goes above its stop.");
  expect(levelsProblem("short", 28.6, 29.5, 27)).toBeNull();
  expect(levelsProblem("short", 28.6, 28, 27)).toBe("The stock is at 28.60: a short plan's stop goes above it.");
  expect(levelsProblem("short", 28.6, 29.5, 30)).toBe("A short plan's target goes below its stop.");
  expect(levelsProblem("long", null, 242, null)).toBeNull(); // no price yet: only the stop against the target
  expect(levelsProblem("long", 247, -1, null)).toBe("The stop must be a positive stock price.");
});

test("Trim and Close tickets: contracts × 100 a share's mark, from the row's own worth", () => {
  const row = optionRow(ORCL_BOOK);
  // A live tick of 4.10 a share: the 3 contracts are worth 4.10 × 100 × 3 = $1,230; a trim of 1 brings in $410.
  const trim = panelCloseTicket(row, ticksOf({ ORCL261120C00250000: 4.1 }), 1)!;
  expect(trim).toMatchObject({ at: "now", symbol: "ORCL", side: "call", strike: 250, held: 3, contracts: 1, remains: 2, mark: 4.1, limit: 4.1,
    credit: true, proceeds: 410, markLive: true, account: "Roth IRA ••8267", multiplier: 100 });
  expect(panelCloseTicket(row, ticksOf({ ORCL261120C00250000: 4.1 }), 3)!.proceeds).toBe(1230);
  // No tick: cost and P&L give the worth: 620 × 3 − 420 = $1,440, so 4.80 a share.
  expect(panelCloseTicket(row, ticksOf({}), 2)).toMatchObject({ mark: 4.8, contracts: 2, remains: 1, proceeds: 960, markLive: false });
  // More than held, none, or a short leg: no ticket.
  expect(panelCloseTicket(row, ticksOf({}), 4)).toBeNull();
  expect(panelCloseTicket(row, ticksOf({}), 0)).toBeNull();
  expect(panelCloseTicket(optionRow({ ...ORCL_BOOK, option: { ...ORCL_BOOK.option, direction: "short" } }), ticksOf({}), 1)).toBeNull();
});

test("a paper option's break-even: the strike plus the premium paid for a call, less it for a put", () => {
  const call = { instrument: "option", option_type: "call", per_share: -3.4, legs: [{ action: "buy", strike: 100 }] };
  expect(paperBreakEven(call)).toBe(103.4);
  expect(paperBreakEven({ ...call, option_type: "put", per_share: -1.25, legs: [{ action: "buy", strike: 30 }] })).toBe(28.75);
  expect(paperBreakEven({ ...call, instrument: "stock" })).toBeNull();
  expect(paperBreakEven({ ...call, legs: [{ action: "buy", strike: 100 }, { action: "sell", strike: 105 }] })).toBeNull();
});

// ------------------------------------------------------------------------------------------------ the desk

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

async function open(page: Page, { width = 1440, height = 900, threads = THREADS as object } = {}) {
  const writes: Request[] = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
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
const panel = (page: Page) => page.getByTestId("desk-chart").getByTestId("desk-position");
const ticket = (page: Page) => page.getByTestId("desk-ticket");
const sent = (writes: Request[], from: number) => writes.slice(from).map(w => `${w.method()} ${new URL(w.url()).pathname.replace(/^\/api\/backend/, "")}`);

test("a real option: the panel shows the position and its plan, and the book row keeps no buttons", async ({ page }) => {
  await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const p = panel(page);
  await expect(p.getByTestId("mode-mark")).toHaveText("Real · Roth IRA ••8267");
  await expect(p.getByTestId("position-head")).toContainText("ORCL 11/20/26 250C ×2");
  await page.clock.runFor(6_000); // the live ticks land
  await expect(p.getByTestId("position-pnl")).toContainText("−$420 (−33.9%)"); // 2 × (410 − 620)
  await expect(p.getByTestId("position-mark")).toHaveText("Now 4.10 a share");
  await expect(p.getByTestId("position-stock")).toContainText("ORCL 247.00 −1.0% today");
  await expect(p.getByTestId("position-plan")).toContainText("Entry 245.00");
  await expect(p.getByTestId("position-stop")).toHaveText("Stop 240.00");
  await expect(p.getByTestId("position-target")).toHaveText("Target 258.00");
  await expect(p.getByTestId("standing-break-even")).toContainText("256.20"); // 250 + 6.20
  await expect(p.getByTestId("standing-expiry")).toContainText("7d left");
  await expect(p.getByTestId("position-actions").getByRole("button"))
    .toHaveText(["Stop / target", "Trim", "Close", "Roll", "Note", "Close at target", "Close at stop"]);
  // The book row: its standing line, and none of the buttons (they are the panel's).
  await expect(book(page).getByTestId("book-standing")).toBeVisible();
  for (const name of ["Close at target", "Close at stop", "Roll", "Trim", "Close"])
    await expect(book(page).getByRole("button", { name, exact: true })).toHaveCount(0);
});

test("a position with no plan: his cut line, how far the price is from it and his record in the ticker, not a prompt to plan", async ({ page }) => {
  // Bought at 6.20 with three days or less left: the cut line is 30% under it (4.34 a share); the quote now is 4.10.
  const bare = { ...ORCL, investigation_id: null, status: { text: "", tone: "muted" },
    book: { ...ORCL.book, state: null, planned: false, plan_levels: null, cut_line: 434 } };
  await page.route("**/charts/symbol/ORCL/you", route => route.fulfill({ json: { symbol: "ORCL", total_trades: 13, closed_trades: 12, missing_pnl: 0,
    realized_pnl: -1240, win_rate: 5 / 12, average_hold_mins: 90, hold_samples: 12, best_trade: null, worst_trade: null, last_traded_at: null,
    open_positions: [], recent_trades: [], source: "Journal · all accounts", as_of: "2026-11-13T16:00:00Z", time_zone: "America/New_York" } }));
  await open(page, { threads: { ...THREADS, threads: [bare] } });
  const p = panel(page);
  await expect(p.getByTestId("position-cut")).toHaveText(/^(Now \$[\d.]+ · )?Cut \$4\.34 · past it$/);
  // Past the cut line, Close is the button that stands out.
  await expect(p.getByTestId("position-close")).toHaveClass(/rose/);
  await expect(p.getByTestId("position-record")).toHaveText("Your ORCL record 12 closed · 5 won · −$1,240");
  await expect(p.getByTestId("position-plan")).not.toContainText("No saved plan");
  // Plan it is still there, last and quiet.
  await expect(p.getByTestId("position-actions").getByRole("button").last()).toHaveText("Plan it");
});

test("Stop / target re-arms the plan's stop alert at the new price from a fresh quote and saves the target", async ({ page }) => {
  const rearms: unknown[] = [], targets: unknown[] = [];
  await page.route("**/charts/alerts", route => route.fulfill({ json: { alerts: [ALERT], phone: false } }));
  await page.route("**/copilot/quote?*", route => route.fulfill({ json: { symbol: "ORCL", last: 247.2, trade_time: null, fetched_at: null, age_s: 2, issue: null, fresh: true } }));
  await page.route("**/charts/alerts/i1/rearm", route => { rearms.push(route.request().postDataJSON()); return route.fulfill({ json: { alerts: [], phone: false } }); });
  await page.route(`**/copilot/plans/${PLAN}/target`, route => { targets.push({ method: route.request().method(), ...route.request().postDataJSON() });
    return route.fulfill({ json: { investigation_id: PLAN, symbol: "ORCL", target: 260 } }); });
  const writes = await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await page.clock.runFor(6_000);
  await panel(page).getByTestId("position-levels").click();
  const editor = panel(page).getByTestId("position-levels-editor");
  await expect(editor.getByLabel("Stop (stock price)")).toHaveValue("240");
  await expect(editor.getByLabel("Target (stock price)")).toHaveValue("258");
  // A long plan's stop above the price is refused before anything is sent.
  await editor.getByLabel("Stop (stock price)").fill("248");
  await expect(editor.getByTestId("position-levels-problem")).toHaveText("The stock is at 247.00: a long plan's stop goes below it.");
  await expect(editor.getByTestId("position-levels-save")).toBeDisabled();
  await editor.getByLabel("Stop (stock price)").fill("242.5");
  await editor.getByLabel("Target (stock price)").fill("260");
  const before = writes.length;
  await editor.getByTestId("position-levels-save").click();
  await expect(panel(page).getByTestId("position-said")).toHaveText("Plan updated: ORCL stop 242.50 (was 240.00), target 260.00 (was 258.00).");
  // The plan_stop card's own route: the invalidation alert armed again at 242.50 from the fresh 247.20; then the target.
  expect(rearms).toEqual([{ price: 242.5, reference: 247.2 }]);
  expect(targets).toEqual([{ method: "PUT", target: 260 }]);
  expect(sent(writes, before)).toEqual(["POST /charts/alerts/i1/rearm", `PUT /copilot/plans/${PLAN}/target`]);
  await expect(panel(page).getByTestId("position-stop")).toHaveText("Stop 242.50");
  await expect(panel(page).getByTestId("position-target")).toHaveText("Target 260.00");
});

test("Trim opens the close-now ticket with the count, Close with all of them; nothing is sent", async ({ page }) => {
  const writes = await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await page.clock.runFor(6_000);
  const before = writes.length;
  await panel(page).getByTestId("position-trim").click();
  const pick = panel(page).getByTestId("position-trim-pick");
  await expect(pick.getByLabel("Contracts to trim")).toHaveValue("1"); // half of 2
  await pick.getByTestId("position-trim-open").click();
  await expect(ticket(page)).toHaveAttribute("data-closing", "now");
  await expect(ticket(page)).toContainText("Trim at the mark now");
  await expect(ticket(page)).toContainText("Roth IRA ••8267");
  await expect(ticket(page).getByLabel("Quantity in contracts")).toHaveValue("1");
  await expect(ticket(page).getByLabel("Limit price per share")).toHaveValue("4.10");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $410.00 at this limit"); // 4.10 × 100 × 1
  await page.getByRole("tab", { name: "Position" }).click(); // the dock back on the panel; the chart above never left
  await panel(page).getByTestId("position-close").click();
  await expect(ticket(page)).toContainText("Close at the mark now");
  await expect(ticket(page).getByLabel("Quantity in contracts")).toHaveValue("2");
  await expect(ticket(page).getByTestId("close-now-proceeds")).toHaveText("about $820.00 at this limit");
  await expect(ticket(page).getByRole("button", { name: /send/i })).toHaveCount(0);
  expect(sent(writes, before)).toEqual([]);
});

test("a paper position: its own panel marked PAPER, the stop and target saved after entry, Close on paper, no Roll", async ({ page }) => {
  const patches: unknown[] = [];
  await page.route(`**/copilot/paper/positions/${PAPER_POSITION.id}`, route => {
    patches.push({ method: route.request().method(), ...route.request().postDataJSON() });
    const body = route.request().postDataJSON();
    return route.fulfill({ json: { stop: body.stop ?? 95, target: "target" in body ? body.target : 105, note: body.note ?? null } });
  });
  await page.route("**/copilot/paper/orders", route => route.fulfill({ json: { preview: { label: PAPER_POSITION.label, quantity: 2, per_share: 3.7, cash: 740,
    quoted_at: epoch("2026-11-13T15:59:58Z"), legs: { [NBIS_CALL]: { action: "sell", bid: 3.7, ask: 3.8, price: 3.7 } }, stock: 98.2, pnl: 60, all: true, held: 0 } } }));
  await open(page);
  // The paper line opens with a position open; its card's sheet shows NBIS on the desk with the paper panel under the chart.
  await page.getByTestId("paper-position-card").click();
  await page.getByTestId("paper-position-show").click();
  const p = page.getByTestId("desk-chart").getByTestId("desk-paper-position");
  await expect(p.getByTestId("mode-mark")).toHaveText("Paper · not real money");
  await expect(p).toContainText("NBIS $100 Call 11/20/26 ×2");
  await expect(p.getByTestId("paper-position-stop")).toHaveText("Stop 95.00");
  await expect(p).toContainText("Break-even 103.40");
  await expect(p.getByTestId("paper-position-actions").getByRole("button")).toHaveText(["Stop / target", "Trim", "Close", "Note"]);
  await expect(p.getByTestId("roll-open")).toHaveCount(0);
  // The stop moves to 96 on paper; only the stop is sent.
  await p.getByTestId("paper-position-levels").click();
  await p.getByLabel("Stop (stock price)").fill("96");
  await p.getByTestId("position-levels-save").click();
  await expect(p.getByTestId("paper-position-said")).toContainText("Paper: stop 96.00, target 105.00. Nothing was closed");
  expect(patches).toMatchObject([{ method: "PATCH", stop: 96 }]);
  expect(patches[0]).not.toHaveProperty("target");
  // A note rides on the same route.
  await p.getByTestId("paper-position-note-button").click();
  await p.getByLabel("Paper note").fill("Base held at 97");
  await p.getByTestId("paper-position-note-save").click();
  await expect(p.getByTestId("paper-position-said")).toHaveText("Paper note saved.");
  expect(patches[1]).toMatchObject({ method: "PATCH", note: "Base held at 97" });
  // Close opens the paper book's own close row: a preview of the bid, nothing filled until he taps Fill on paper.
  await p.getByTestId("paper-position-close").click();
  await expect(p.getByTestId("paper-close")).toContainText("Sell 2 × NBIS $100 Call 11/20/26 at 3.70");
  await expect(p.getByTestId("paper-close-fill")).toBeVisible();
});

test("on a phone the panel sits under the chart on the ticker view, with full-size taps", async ({ page }) => {
  await open(page, { width: 375, height: 812 });
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const levels = panel(page).getByTestId("position-levels");
  await expect(levels).toBeVisible();
  expect((await levels.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  const chart = await page.getByTestId("desk-chart-canvas").boundingBox();
  const box = await panel(page).boundingBox();
  if (chart) expect(box!.y).toBeGreaterThan(chart.y);
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(375);
});
