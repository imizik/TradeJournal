import { expect, test, type Page, type Request } from "@playwright/test";

// Redo a real trade in replay (docs/copilot-lab.md § Redo a real trade): a real closed trade's "Redo in replay" link
// opens desk Replay on its day and ticker with nothing of how it went in sight; it can start 15 minutes before the
// entry; the real contract is preselected on the ticket; ending the redo sells what is open and one card compares the
// two. Replay's day picker lists "Redo my worst"; outside option replay's window the redo is shares, with the reason.
// Every lab route is stubbed. Invented numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-14T17:00:00Z"); // Saturday noon New York
const OPEN_AT = Date.parse("2026-11-13T14:30:00Z") / 1000; // Fri 09:30 New York
const CLOSE_AT = OPEN_AT + 390 * 60;
const START_AT = OPEN_AT + 35 * 60; // 10:05: 15 minutes before the 10:20 entry
const TRADE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OLD_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CALL = "NBIS $100 Call 11/20/26";
const DESK = {
  as_of: NOW.toISOString(), quotes_at: null, quote_issue: null, day: { phase: "closed", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], threads: [{ key: "briefing", group: "pinned", title: "Briefing", symbol: null, instrument: null, value: null,
    meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null, status: { text: "Nothing new.", tone: "muted" } }],
};
const bar = (minute: number, close: number) => ({ time: OPEN_AT + minute * 60, open: close - 0.1, high: close + 0.2, low: close - 0.3, close, volume: 5000 });
const BARS = [bar(0, 100), bar(1, 101), ...Array.from({ length: 40 }, (_, i) => bar(i + 2, 101 + i * 0.1)), bar(389, 150)];
const stats = (pnl: number, trades: number) => ({ trades, pnl, win_rate: trades ? 100 : null, avg_win: pnl > 0 ? pnl : null, avg_loss: null, largest_loss: null, curve: [] });
const RUN = { id: "77777777-7777-4777-8777-777777777777", day: "2026-11-13", starting_cash: 10000, started_at: NOW.getTime() / 1000,
  open_at: OPEN_AT, close_at: CLOSE_AT, symbols: [], realized: 0, trades: 0, left_open: 0, options_off: null, redo_of: TRADE_ID };
const ACCOUNT = { cash: 10000, collateral: 0, reserved: 0, buying_power: 10000, equity: 10000, pnl: 0 };
const PLAN = { trade_id: TRADE_ID, day: "2026-11-13", symbol: "NBIS", label: CALL, instrument: "option",
  contract: { option_type: "call", expiry: "2026-11-20", strike: 100, label: CALL }, shares_reason: null,
  open_at: OPEN_AT, close_at: CLOSE_AT, before_at: START_AT, before_reason: null };
const OFF = "Option replay needs each contract's own minute trades, and Tradier keeps only about the last 20 days of them: Oct 2 is older. Shares only on this day.";
const OLD_PLAN = { ...PLAN, trade_id: OLD_ID, day: "2026-11-12", label: "AMD $250 Put 10/17/26", symbol: "NBIS", contract: null, shares_reason: OFF };
const OPTION = { id: "99999999-9999-4999-8999-999999999999", symbol: "NBIS", instrument: "option", option_type: "call", expiry: "2026-11-20",
  label: CALL, bias: "long", credit: false, width: null, multiplier: 100, quantity: 1, remaining: 1, per_share: -2.41, cash: -241, basis: -241, stock: 101,
  note: null, stop: null, target: null, opened_at: START_AT - 1, status: "open", closed_at: null, realized: 0,
  legs: [{ quote: "NBIS261120C00100000", action: "buy", strike: 100 }], awaiting_close: false,
  mark: { per_share: 2.6, value: 260, pnl: 19, pct: 7.9, at: START_AT + 60 }, auto: false, touched: {}, exiting: false, held: 0 };
const CLOSED = { ...OPTION, remaining: 0, status: "closed", closed_at: START_AT + 539, realized: 52, day: "2026-11-13", run_id: RUN.id, mark: undefined,
  source: "redo", redo_of: TRADE_ID, exits: [{ kind: "close", at: START_AT + 539, quantity: 1, per_share: 2.93, cash: 293, pnl: 52, stock: 102 }],
  verdict: { kind: "left", text: "Sold when you left the replay" } };
const COMPARE = {
  run_id: RUN.id, trade_id: TRADE_ID, day: "2026-11-13", start: "before", left_open: 0, difference: 452, note: "Exited 1 h 6 min earlier, smaller size (1 vs 2 contracts).",
  real: { label: CALL, instrument: "option", quantity: 2, pnl: -400, held_minutes: 75, entry: { price: 2.5, at: OPEN_AT + 50 * 60 }, exit: { price: 0.5, at: OPEN_AT + 125 * 60 },
    expired: false, overnight: false, closed_day: "2026-11-13" },
  redo: { label: CALL, instrument: "option", quantity: 1, pnl: 52, held_minutes: 9, trades: 1, entry: { price: 2.41, at: START_AT - 1 }, exit: { price: 2.93, at: START_AT + 539 } },
};
const WORST = [
  { trade_id: TRADE_ID, day: "2026-11-13", symbol: "NBIS", label: CALL, instrument: "option", pnl: -400, opened_at: OPEN_AT + 50 * 60 },
  { trade_id: OLD_ID, day: "2026-11-12", symbol: "NBIS", label: "NBIS shares", instrument: "stock", pnl: -120, opened_at: OPEN_AT - 86400 + 600 },
];

async function stub(page: Page, width: number) {
  const steps: Request[] = [];
  const started: Request[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper"), route => route.fulfill({ json: { run: null, default_cash: 10000, earlier: [], market_open: false } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper/replay"), route => route.fulfill({ json: {
    score: stats(0, 0), runs: [], trades: [], spread_bps: 5, options: "Options: only contracts that traded that day.", worst: WORST,
    days: [{ date: "2026-11-13", open_at: OPEN_AT, close_at: CLOSE_AT, early_close: false }, { date: "2026-11-12", open_at: OPEN_AT - 86400, close_at: CLOSE_AT - 86400, early_close: false }],
  } }));
  await page.route("**/copilot/paper/replay/day?*", route => route.fulfill({ json: { day: "2026-11-13", symbols: [{ symbol: "NBIS", why: "traded" }] } }));
  await page.route("**/copilot/paper/replay/bars?*", route => {
    const ask = new URL(route.request().url()).searchParams;
    const shift = ask.get("day") === "2026-11-12" ? 86400 : 0;
    return route.fulfill({ json: { symbol: ask.get("symbol"), day: ask.get("day"), open_at: OPEN_AT - shift, close_at: CLOSE_AT - shift,
      bars: BARS.map(b => ({ ...b, time: b.time - shift })) } });
  });
  await page.route("**/copilot/paper/replay/options?*", route => route.fulfill({ json: { symbol: "NBIS", day: "2026-11-13", at: START_AT, off: null,
    rule: "Options: only contracts that traded that day.", price: 101, step: 1, expiries: ["2026-11-13", "2026-11-20"], option_type: null, expiry: null,
    contracts: null, missing: [], waiting: [], waiting_reason: null } }));
  await page.route("**/copilot/paper/replay/redo?*", route => {
    const id = new URL(route.request().url()).searchParams.get("trade_id");
    return route.fulfill({ json: id === OLD_ID ? OLD_PLAN : PLAN });
  });
  const view = (at: number, extra = {}) => ({ run: RUN, at, ended: false, score: stats(0, 0), account: ACCOUNT, positions: [], orders: [], closed: [], happened: [], ...extra });
  await page.route(url => url.pathname.endsWith("/copilot/paper/replay/redo"), route => {
    if (route.request().method() !== "POST") return route.fallback();
    started.push(route.request());
    const start = route.request().postDataJSON().start;
    const at = start === "before" ? START_AT : OPEN_AT;
    return route.fulfill({ json: { ...view(at), redo: { ...PLAN, start, start_at: at } } });
  });
  await page.route("**/copilot/paper/replay/orders", route => {
    const body = route.request().postDataJSON();
    const quote = { label: CALL, instrument: "option", multiplier: 100, quantity: body.quantity, close: 2.35, half_spread: 0.06, half_from: "range",
      low: 2.28, high: 2.4, bid: 2.29, ask: 2.41, bar: START_AT - 60, spread_bps: 5, stock: 101, buying_power: 10000, buying_power_after: 9759,
      fills_now: true, per_share: -2.41, cash: -241 };
    if (body.preview) return route.fulfill({ json: { preview: quote } });
    return route.fulfill({ json: { ...view(body.at, { positions: [OPTION], account: { ...ACCOUNT, cash: 9759, buying_power: 9759 } }),
      filled: { ...quote, at: START_AT - 1 }, working: null } });
  });
  await page.route("**/copilot/paper/replay/step", route => {
    steps.push(route.request());
    const body = route.request().postDataJSON();
    return route.fulfill({ json: body.end ? view(body.at, { closed: [CLOSED], score: stats(52, 1) }) : view(body.at, { positions: [OPTION] }) });
  });
  await page.route("**/copilot/paper/replay/redo/compare?*", route => route.fulfill({ json: COMPARE }));
  return { steps, started };
}

for (const width of [1440, 375]) {
  test(`a redo hides the real trade, starts before the entry on its contract and compares at the end at ${width}px`, async ({ page }) => {
    const { steps, started } = await stub(page, width);
    await page.goto(`/copilot-lab?redo=${TRADE_ID}`);
    const replay = page.getByTestId("desk-replay");
    await expect(page.getByTestId("redo-setup")).toContainText(`${CALL} on Fri, Nov 13`);
    await expect(page.getByTestId("redo-badge")).toBeVisible();
    await expect(page.locator("#desk-cockpit")).toBeHidden();
    await expect(page).toHaveURL(/\/copilot-lab$/);  // read once: a reload never starts a second redo
    await expect(replay).not.toContainText("400");  // no peeking: the real P&L is nowhere until the end
    await expect(page.getByTestId("redo-worst")).toHaveCount(0);
    await page.getByTestId("redo-before").click();
    await page.getByTestId("replay-start").click();
    expect(started[0].postDataJSON()).toEqual({ trade_id: TRADE_ID, start: "before" });
    await expect(page.getByTestId("replay-badge")).toHaveText("REPLAY · Fri, Nov 13 · 10:05 AM ET");
    await expect(page.getByTestId("redo-preset")).toContainText(CALL);
    await page.getByTestId("replay-review").click();
    await expect(page.getByTestId("replay-confirm")).toContainText(`Buy 1 ${CALL} at 2.41`);
    await page.getByTestId("replay-fill").click();
    await expect(page.getByTestId("replay-position")).toContainText(CALL);
    await expect(replay).not.toContainText("−$400");
    await page.getByTestId("redo-end").click();
    const card = page.getByTestId("redo-compare");
    await expect(card).toBeVisible();
    expect(steps.some(s => s.postDataJSON().end === true)).toBe(true);  // ending sells what is open at the clock
    await expect(page.getByTestId("redo-real-pnl")).toHaveText("−$400.00");
    await expect(page.getByTestId("redo-redo-pnl")).toHaveText("+$52.00");
    await expect(page.getByTestId("redo-difference")).toHaveText("The redo did $452.00 better than the real trade.");
    await expect(page.getByTestId("redo-note")).toHaveText(COMPARE.note);
    await expect(card).toContainText("2.50 · 10:20 AM");
    await expect(page.getByTestId("replay-review")).toHaveCount(0);  // the redo is over
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `test-results/redo-compare-${width}.png`, fullPage: false });
  });
}

test("Replay's day picker lists Redo my worst; an old day redoes on shares with the reason", async ({ page }) => {
  await stub(page, 1440);
  await page.goto("/copilot-lab?symbol=NBIS");
  await page.getByTestId("replay-open").click();
  const worst = page.getByTestId("redo-worst-trade");
  await expect(worst).toHaveCount(2);
  await expect(worst.first()).toContainText(`Fri, Nov 13${CALL}−$400.00`);
  await worst.nth(1).click();
  await expect(page.getByTestId("redo-setup")).toContainText("AMD $250 Put 10/17/26 on Thu, Nov 12");
  await expect(page.getByTestId("redo-shares-reason")).toHaveText(OFF);
  await page.getByRole("button", { name: "Pick a day instead" }).click();
  await expect(page.getByTestId("redo-worst")).toBeVisible();
});
