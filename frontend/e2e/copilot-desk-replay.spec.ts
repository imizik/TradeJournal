import { expect, test, type Page, type Request } from "@playwright/test";

// Replay on the desk (docs/copilot-lab.md § Paper replay): the chart's Replay opens a past day; a day whose bars cannot be
// read is greyed out with the reason; the clock starts at 9:30 with only finished bars drawn, steps a bar and plays at a
// speed; the ticket's confirm shows the bar's close and the assumed half-spread; options are off with the reason; while
// it runs the live desk is hidden behind a "REPLAY · <date> <time>" badge; Back to live sells what is open (end) and puts
// the live desk back, with replay practice scored apart from live paper. Every lab route is stubbed. Invented numbers.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
const NOW = new Date("2026-11-14T17:00:00Z"); // Saturday noon New York: no live session
const OPEN_AT = Date.parse("2026-11-13T14:30:00Z") / 1000; // Fri 09:30 New York
const CLOSE_AT = OPEN_AT + 390 * 60;
const DESK = {
  as_of: NOW.toISOString(), quotes_at: null, quote_issue: null, day: { phase: "closed", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], threads: [{ key: "briefing", group: "pinned", title: "Briefing", symbol: null, instrument: null, value: null,
    meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null, changed_at: null, status: { text: "Nothing new.", tone: "muted" } }],
};
const bar = (minute: number, close: number) => ({ time: OPEN_AT + minute * 60, open: close - 0.1, high: close + 0.2, low: close - 0.3, close, volume: 5000 });
// The 09:29 premarket bar, then 09:30 closes 100.00, 09:31 101.00, … and a far future bar at 15:59 closing 150.00.
const BARS = [bar(-1, 99.5), bar(0, 100), bar(1, 101), bar(2, 102), bar(3, 103), bar(4, 104), bar(5, 105), bar(389, 150)];
const stats = (pnl: number, trades: number) => ({ trades, pnl, win_rate: trades ? 100 : null, avg_win: pnl > 0 ? pnl : null, avg_loss: null, largest_loss: null, curve: [] });
const RUN = { id: "77777777-7777-4777-8777-777777777777", day: "2026-11-13", starting_cash: 10000, started_at: NOW.getTime() / 1000,
  open_at: OPEN_AT, close_at: CLOSE_AT, symbols: [], realized: 0, trades: 0, left_open: 0 };
const ACCOUNT = { cash: 10000, collateral: 0, reserved: 0, buying_power: 10000, equity: 10000, pnl: 0 };
const POSITION = {
  id: "88888888-8888-4888-8888-888888888888", symbol: "NBIS", instrument: "stock", option_type: null, expiry: null, label: "NBIS shares", bias: "long",
  credit: false, width: null, multiplier: 1, quantity: 10, remaining: 10, per_share: -100.03, cash: -1000.3, basis: -1000.3, stock: 100, note: "first push",
  stop: 99, target: 106, opened_at: OPEN_AT + 59, status: "open", closed_at: null, realized: 0, legs: [{ quote: "NBIS", action: "buy", strike: null }],
  awaiting_close: false, mark: { per_share: 101, value: 1010, pnl: 9.7, pct: 1, at: OPEN_AT + 120 }, auto: true, touched: {}, exiting: false, held: 0,
};
const TRADE = { ...POSITION, remaining: 0, status: "closed", closed_at: OPEN_AT + 299, realized: 39.4, day: "2026-11-13", run_id: RUN.id, mark: undefined,
  exits: [{ kind: "close", at: OPEN_AT + 299, quantity: 10, per_share: 103.97, cash: 1039.7, pnl: 39.4, stock: 103.97 }],
  verdict: { kind: "left", text: "Sold when you left the replay" } };
const OPTIONS = "Options are not replayed yet: the app keeps no past option chain to pick a contract from and no past option quotes for that minute, so there is no honest option price. Shares only.";

async function open(page: Page, width: number) {
  const steps: Request[] = [];
  const orders: Request[] = [];
  let practiced = false;
  await page.setViewportSize({ width, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: DESK }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper"), route => route.fulfill({ json: { run: null, default_cash: 10000, earlier: [], market_open: false } }));
  await page.route(url => url.pathname.endsWith("/copilot/paper/replay"), route => route.fulfill({ json: {
    score: practiced ? stats(39.4, 1) : stats(0, 0), runs: practiced ? [{ ...RUN, realized: 39.4, trades: 1 }] : [], trades: practiced ? [TRADE] : [],
    spread_bps: 5, options: OPTIONS,
    days: [{ date: "2026-11-13", open_at: OPEN_AT, close_at: CLOSE_AT, early_close: false }, { date: "2026-11-12", open_at: OPEN_AT - 86400, close_at: CLOSE_AT - 86400, early_close: false }],
  } }));
  await page.route("**/copilot/paper/replay/day?*", route => route.fulfill({ json: { day: "2026-11-13", symbols: [{ symbol: "NBIS", why: "traded" }, { symbol: "SPY", why: "watched" }] } }));
  await page.route("**/copilot/paper/replay/bars?*", route => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol");
    return symbol === "NBIS" ? route.fulfill({ json: { symbol, day: "2026-11-13", open_at: OPEN_AT, close_at: CLOSE_AT, bars: BARS } })
      : route.fulfill({ status: 409, json: { detail: `No minute bars for ${symbol} on Nov 13: history_unavailable` } });
  });
  const view = (at: number, extra = {}) => ({ run: RUN, at, ended: false, score: stats(0, 0), account: ACCOUNT, positions: [], orders: [], closed: [], happened: [], ...extra });
  await page.route("**/copilot/paper/replay/runs", route => route.fulfill({ json: view(OPEN_AT) }));
  await page.route("**/copilot/paper/replay/step", route => {
    steps.push(route.request());
    const body = route.request().postDataJSON();
    if (body.end) practiced = true;
    return route.fulfill({ json: body.end
      ? view(body.at, { positions: [], closed: [TRADE], score: stats(39.4, 1), happened: [{ kind: "left", symbol: "NBIS", label: "NBIS shares", at: OPEN_AT + 299, price: 103.97, quantity: 10, pnl: 39.4 }] })
      : view(body.at, { positions: [POSITION], account: { ...ACCOUNT, cash: 8999.7, buying_power: 8999.7 } }) });
  });
  await page.route("**/copilot/paper/replay/orders", route => {
    const body = route.request().postDataJSON();
    const quote = { label: "NBIS shares", quantity: body.quantity, close: 100, half_spread: 0.03, bid: 99.97, ask: 100.03, bar: OPEN_AT, spread_bps: 5,
      buying_power: 10000, buying_power_after: 8999.7, fills_now: true, per_share: -100.03, cash: -1000.3 };
    if (body.preview) return route.fulfill({ json: { preview: quote } });
    orders.push(route.request());
    return route.fulfill({ json: { ...view(body.at, { positions: [POSITION], account: { ...ACCOUNT, cash: 8999.7, buying_power: 8999.7 } }),
      filled: { ...quote, at: OPEN_AT + 59 }, working: null } });
  });
  await page.goto("/copilot-lab?symbol=NBIS");
  const back = page.getByRole("button", { name: "Back to the desk" });
  if (width < 768 && await back.isVisible()) await back.click();
  await page.getByTestId("replay-open").click();
  return { steps, orders };
}

for (const width of [1440, 375]) {
  test(`replay plays a past day from the open, prices from finished bars and goes back to live at ${width}px`, async ({ page }) => {
    const { steps, orders } = await open(page, width);
    const badge = page.getByTestId("replay-badge");
    await expect(badge).toHaveText("REPLAY · Fri, Nov 13 · not started");
    await expect(page.locator("#desk-cockpit")).toBeHidden();  // nothing live beside a replayed price
    // A ticker with no bars greys the day out with the reason; the one he traded that day is ready.
    await page.getByLabel("Replay ticker").fill("SPY");
    await expect(page.getByTestId("replay-missing")).toContainText("greyed out for SPY: No minute bars for SPY on Nov 13");
    await expect(page.getByTestId("replay-start")).toBeDisabled();
    await page.getByLabel("Replay ticker").fill("NBIS");
    await expect(page.getByTestId("replay-ready")).toContainText("NBIS on Fri, Nov 13: 7 minute bars");
    await page.getByTestId("replay-start").click();
    await expect(badge).toHaveText("REPLAY · Fri, Nov 13 · 9:30 AM ET");
    await expect(page.getByTestId("replay-chart")).toBeVisible();
    await expect(page.getByTestId("replay-options-off")).toBeDisabled();
    await expect(page.getByTestId("replay-options-reason")).toContainText("no honest option price");
    // One bar: the 09:30 bar is finished, so the price is its close; the future bars are never shown.
    await page.getByTestId("replay-step").click();
    await expect(badge).toHaveText("REPLAY · Fri, Nov 13 · 9:31 AM ET");
    await expect(page.getByTestId("desk-replay")).toContainText("100.00 at 9:31 AM ET");
    await expect(page.getByTestId("desk-replay")).not.toContainText("150.00");
    await page.getByLabel("Replay stop").fill("99");
    await page.getByLabel("Replay target").fill("106");
    await page.getByLabel("Replay note").fill("first push");
    await page.getByTestId("replay-review").click();
    const confirm = page.getByTestId("replay-confirm");
    await expect(confirm).toContainText("Buy 10 NBIS at 100.03: costs $1,000.30.");
    await expect(confirm).toContainText("The 9:30 AM bar closed at 100.00; buying pays that plus a 0.03 half-spread = 100.03.");
    await expect(confirm).toContainText("0.05% of the price");
    expect(orders).toHaveLength(0);  // the review alone fills nothing
    await page.getByTestId("replay-fill").click();
    await expect(page.getByTestId("replay-done")).toContainText("bought 10 NBIS at 100.03");
    expect(orders[0].postDataJSON()).toMatchObject({ at: OPEN_AT + 60, action: "open", symbol: "NBIS", instrument: "stock", quantity: 10, stop: 99, target: 106 });
    await expect(page.getByTestId("replay-position")).toContainText("10 NBIS");
    // 60×: a replayed minute a second; with a position open each new minute brings the run to the clock.
    await page.getByRole("radio", { name: "60×" }).click();
    await page.getByTestId("replay-play").click();
    await page.clock.runFor(3_100);
    await page.getByTestId("replay-play").click();
    await expect(badge).toHaveText("REPLAY · Fri, Nov 13 · 9:34 AM ET");
    await expect.poll(() => steps.length).toBeGreaterThan(0);
    expect(steps.map(s => s.postDataJSON().at).every(at => at > OPEN_AT + 60 && at <= OPEN_AT + 240)).toBe(true);
    // Back to live sells what is open at the clock and puts the live desk back; practice is scored apart.
    await page.getByTestId("replay-leave").click();
    await expect.poll(() => steps.some(s => s.postDataJSON().end === true)).toBe(true);
    await expect(page.getByTestId("desk-replay")).toHaveCount(0);
    await expect(page.locator("#desk-cockpit")).toBeVisible();
    if (width < 768) await page.getByTestId("desk-view-book").click();
    const practice = page.getByTestId("replay-practice");
    await expect(practice).toContainText("Replay practice");
    await expect(practice.getByTestId("replay-score")).toContainText("+$39.40");
    await practice.getByRole("button").first().click();
    await expect(practice.getByTestId("replay-trade")).toContainText("“first push”");
  });
}
