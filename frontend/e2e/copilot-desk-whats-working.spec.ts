import { expect, test, type Page } from "@playwright/test";

// What's working (docs/copilot-lab.md § What's working): ⌘K opens the view in place under How I'm doing, with the top 3
// buckets making and losing money, REAL beside PAPER, each with its sample; the real option ticket's "Your record" row
// shows the paper record for its option type entered at this New York time, informational only (Copy all still copies).
// Every route is stubbed with invented numbers, so nothing reaches the e2e backend.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-13T16:00:00Z"); // Friday 11:00 New York
const epoch = (iso: string) => Date.parse(iso) / 1000;
const RULES = [
  { id: "r_size000001", text: "Never more than 5% on one trade", check: { kind: "max_size_pct", n: 5 } },
  { id: "r_stop000001", text: "Stop before I enter", check: { kind: "stop_set" } },
  { id: "r_wait000001", text: "Wait out the first 15 minutes", check: { kind: "no_open_minutes", n: 15 } },
  { id: "r_aplus00001", text: "Only A+ setups", check: null },
];
const stats = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win, avg_win: null, avg_loss: null, largest_loss: null, curve: [] });
const g = (pnl: number, trades: number, win: number | null) => ({ trades, pnl, win_rate: win });
const SPLIT = {
  followed: g(184.5, 3, 66.7), broken: g(-260, 2, 0), unclear: g(0, 0, null), unrecorded: 1,
  by_rule: [
    { id: "r_size000001", text: "Never more than 5% on one trade", current: true, followed: g(64.5, 4, 50), broken: g(-140, 1, 0), unchecked: 0 },
    { id: "r_stop000001", text: "Stop before I enter", current: true, followed: g(184.5, 3, 66.7), broken: g(-260, 2, 0), unchecked: 0 },
  ],
};
const BOOK = {
  run: { id: "r1", number: 1, starting_cash: 10000, started_at: epoch("2026-11-10T15:00:00Z") },
  account: { cash: 9924.5, collateral: 0, reserved: 0, buying_power: 9924.5, equity: 9924.5, pnl: -75.5, unpriced: 0, prices_at: null },
  positions: [], closed: [], orders: [],
  score: { paper: { ...stats(-75.5, 6, 33.3), open_pnl: null, by_source: [], rules: SPLIT }, real: stats(-312, 3, 33.3),
    real_rules: { ...SPLIT, followed: g(150, 1, 100), broken: g(0, 0, null), by_rule: [], checklists: 3, matched: 1, open: 1, unmatched: 1 } },
  my_rules: RULES, earlier: [], market_open: true,
};
const TICKET = {
  state: "ok", investigation_id: "inv-nbis", symbol: "NBIS", direction: "long", thesis: "Reclaim of 98", option_type: "call", entry: 98,
  invalidation: 95, time_stop: null, target: 108, plan_contract_words: null, size: { contracts: 2, risk_usd: null, text: "2 contracts" },
  accounts: [{ id: "a1", label: "Roth", last4: "8267", kind: "roth" }], account: "a1", simulated: false,
  contract: { strike: 100, expiry: "2026-11-20", type: "call", label: "NBIS $100 Call 11/20/26", source: "plan", multiplier: 100 },
  candidates: null, quote: { state: "ok", as_of: NOW.getTime() / 1000 - 30, bid: 3.3, ask: 3.4, mid: 3.35, spread: 0.1, spread_pct: 3, multiplier: 100 },
  underlying: { state: "ok", last: 98.05, as_of: NOW.getTime() / 1000 - 30 }, expected_move_pct: null, limit: 3.35, contracts: 2, spread: null, check: null,
};
const b = (label: string, pnl: number, trades: number, wins: number, dimension = "kind") =>
  ({ label, pnl, trades, wins, losses: trades - wins, avg_pnl: pnl / trades, win_rate: Math.round(wins / trades * 1000) / 10, judged: trades >= 5, dimension });
const side = (trades: number, making: ReturnType<typeof b>[], losing: ReturnType<typeof b>[]) =>
  ({ ...b("All", 0, Math.max(trades, 1), 0), trades, missing: { pnl: 0, hold: 0, dte: 0 }, dimensions: {}, making, losing });
const REPORT = {
  as_of: NOW.getTime() / 1000, min_trades: 5, window_days: 30,
  windows: {
    recent: { real: side(48, [b("Calls 10:30–12:00", 1199, 17, 13, "kind_time")], [b("Puts before 10:00", -1986, 17, 2, "kind_time"), b("Overnight", -1191, 14, 3, "hold")]),
              paper: side(3, [], []) },
    all: { real: side(120, [b("Calls", 4210, 70, 41)], [b("Puts", -3020, 50, 12)]), paper: side(36, [b("Calls", 1373, 24, 15)], [b("Puts before 10:00", -588, 12, 5, "kind_time")]) },
  },
};
const RECORD = { record: { label: "calls 10:30–12:00", wins: 3, losses: 1, pnl: 212.5, trades: 4 } };
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": { as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
    sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [] },
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/tickets/inv-nbis": TICKET,
  "/copilot/exposure": { line: null },
  "/copilot/paper": { ...BOOK, score: { ...BOOK.score, week: { monday: "2026-11-09", paper: stats(120, 3, 66.7), real: stats(-312, 3, 33.3) } } },
  "/copilot/desk/whats-working": REPORT,
  "/copilot/desk/whats-working/record": RECORD,
};

async function open(page: Page, width: number, path = "/copilot-lab") {
  const asked: string[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  for (const [p, body] of Object.entries(READS)) {
    await page.route(url => url.pathname.endsWith(p), route => { asked.push(new URL(route.request().url()).pathname + new URL(route.request().url()).search); return route.fulfill({ json: body }); });
  }
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      asked.push(target);
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.goto(path);
  return asked;
}

for (const width of [1440, 390]) {
  test(`⌘K opens What's working under How I'm doing, REAL beside PAPER with each sample, at ${width}px`, async ({ page }) => {
    await open(page, width);
    await expect(page.getByTestId("desk-scorecard")).toBeAttached();
    await page.keyboard.press("ControlOrMeta+k");
    const dialog = page.getByRole("dialog", { name: "Jump to" });
    await dialog.getByRole("combobox", { name: "Jump to" }).fill("What's working");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("whats-working-toggle")).toHaveAttribute("aria-expanded", "true");
    const view = page.getByTestId("whats-working");
    await expect(view.getByTestId("whats-working-real")).toContainText("Puts before 10:00");
    await expect(view.getByTestId("whats-working-real")).toContainText("-$1,986 · 17 trades · 2W 15L");
    await expect(view.getByTestId("whats-working-paper")).toContainText("Too few trades to judge");
    await view.getByRole("button", { name: "All time" }).click();
    await expect(view.getByTestId("whats-working-paper")).toContainText("+$1,373 · 24 trades · 15W 9L");
  });
}

test("the real ticket shows paper's record for its option type at this time, and still copies", async ({ page }) => {
  const asked = await open(page, 1440, "/copilot-lab?ticket=inv-nbis");
  const line = page.getByTestId("paper-record-line");
  await expect(line).toContainText("calls 10:30–12:00: 3W 1L, +$212.50");
  await expect(line).toContainText("too few to judge");
  expect(asked.some(p => p.includes("/copilot/desk/whats-working/record?option_type=call"))).toBe(true);
  await expect(page.getByRole("button", { name: /Copy all for Robinhood/ })).toBeEnabled();
});
