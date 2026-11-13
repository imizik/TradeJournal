import { expect, test, type Page } from "@playwright/test";

// A held option's own chart (docs/copilot-lab.md § The desk): with a held single-leg option selected, the chart header
// offers Stock / Contract (remembered per contract); Contract draws the option's trades, its mark where the desk saw it,
// his fills at their premium (Robinhood's provisional one dashed), and at the cursor his P&L for his size and the stock's
// price then. No history, a refused read or a row without a quotable contract: no toggle. Closing tickets stay in the
// header. Every lab route is stubbed; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ids = { orcl: "11111111-1111-4111-8111-111111111111", apld: "22222222-2222-4222-8222-222222222222", mu: "33333333-3333-4333-8333-333333333333" };
const plans = { orcl: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", apld: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", mu: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" };
const ORCL_CALL = "ORCL261120C00250000";
const APLD_PUT = "APLD261127P00030000";

const position = (id: string, plan: string, symbol: string, contract: string, book: object) => ({
  key: `trade:${id}`, group: "watch", symbol, title: `${symbol} ${contract}`, instrument: contract, trade_id: id,
  value: null, status: { text: "On plan", tone: "muted" }, path: null, hidden: false,
  meter: null, investigation_id: plan, radar_event_id: null, changed_at: null, book,
});
const base = { days_held: 1, track: null, state: "on_plan", planned: true, stop_pct: null };
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [
    // Two ORCL 250 calls (Robinhood's account and Greeks), a plan with stop 240 and target 258.
    position(ids.orcl, plans.orcl, "ORCL", "11/20/26 250C", { ...base, usd: -420, pct: -33.9, expiry: "2026-11-20",
      account: { label: "Roth IRA", masked: "••8267" }, plan_levels: { stop: 240, target: 258 },
      tick: { quote: ORCL_CALL, scale: 100, cost: 620, quantity: 2, sign: 1 },
      option: { side: "call", strike: 250, expiry: "2026-11-20", direction: "long", quantity: 2, multiplier: 100, cost: 620,
        greeks: { delta: 0.38, theta: -0.31, iv: 0.44, as_of: epoch("2026-11-13T15:59:30Z"), source: "robinhood" } } }),
    // Three APLD 30 puts on Robinhood's Individual account; a plan with a stop and no target.
    position(ids.apld, plans.apld, "APLD", "11/27/26 30P", { ...base, usd: 159, pct: 55.8, expiry: "2026-11-27",
      account: { label: "Individual", masked: "••1234" }, plan_levels: { stop: 29.5, target: null },
      tick: { quote: APLD_PUT, scale: 100, cost: 95, quantity: 3, sign: 1 },
      option: { side: "put", strike: 30, expiry: "2026-11-27", direction: "long", quantity: 3, multiplier: 100, cost: 95,
        greeks: { delta: -0.42, theta: -0.04, iv: 0.9, as_of: "2026-11-13 15:00:00", source: "tradier" } } }),
    // An MU call in the journal only (no Robinhood account to name) with a plan: no closing ticket, so no button.
    position(ids.mu, plans.mu, "MU", "11/20/26 120C", { ...base, usd: 50, pct: 10, expiry: "2026-11-20",
      plan_levels: { stop: 110, target: 130 }, tick: null, mark: 600, quantity: 1,
      option: { side: "call", strike: 120, expiry: "2026-11-20", direction: "long", quantity: 1, multiplier: 100, cost: 500,
        greeks: { delta: 0.5, theta: -0.2, iv: 0.5, as_of: epoch("2026-11-13T15:59:30Z"), source: "robinhood" } } }),
  ],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const SPARKS = { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
  ORCL: { points: [250, 248, 247], change_pct: -1.2, last: 247 }, APLD: { points: [29.4, 28.9, 28.6], change_pct: -2.1, last: 28.6 },
  MU: { points: [118, 119], change_pct: 0.8, last: 119 } } };

/** ORCL's chart read: 60 two-minute candles around 247 with the plan's entry, invalidation and target lines. */
function orclChart() {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 247 + Math.sin(i / 5);
    return { time: last - (59 - i) * 120, open, high: open + 0.4, low: open - 0.4, close: open + 0.1, volume: 1000, extended: false };
  });
  return { symbol: "ORCL", timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 247, at: last, daily: false, prev_close: 249.5, vwap: null, vwap_at: null, rvol: null },
    levels: [{ role: "entry", price: 245, label: "Entry 245.00", id: "e1" }, { role: "invalidation", price: 240, label: "Invalidation 240.00", id: "i1" },
      { role: "target", price: 258, label: "Target 258.00", id: "target:c1" }],
    alerts: [], marks: [], time_stop: null, events: { earnings: null, macro: [], note: null } };
}


const NY = (hh: number, mm: number) => epoch(`2026-11-13T${String(hh + 5).padStart(2, "0")}:${String(mm).padStart(2, "0")}:00Z`);
/** ORCL 250C today: 2-minute trades from 09:30 to 10:58, its mark at 11:00, the stock beside, his buy at 6.20. */
function orclContract() {
  const bars = Array.from({ length: 45 }, (_, i) => {
    const close = 4.6 - i * 0.012;
    return { time: NY(9, 30) + i * 120, open: close + 0.02, high: close + 0.05, low: close - 0.04, close, volume: 12 };
  });
  return { state: "ok", symbol: "ORCL", occ: ORCL_CALL, label: "ORCL 11/20/26 250C", step: 120, as_of: epoch("2026-11-13T16:00:00Z"), live: true,
    day: "2026-11-13", source: "Tradier time and sales (trades)", style: "candles", reason: null, stale: null, bars,
    marks: [{ time: NY(10, 58), price: 4.08 }],
    stock: bars.map((b, i) => ({ time: b.time, price: 248 - i * 0.02 })),
    fills: [{ at: NY(9, 31), side: "buy", opening: true, contracts: 2, price: 6.2, provisional: false, text: "Bought 2 at 6.20" }] };
}

type Answer = { status?: number; json: unknown };
async function open(page: Page, { width = 1440, height = 900, contract = (occ: string): Answer => occ === ORCL_CALL ? { json: orclContract() } : { json: { state: "none", symbol: "APLD", reason: "No trades in this contract in the last few sessions." } } }: { width?: number; height?: number; contract?: (occ: string) => Answer } = {}) {
  const asked: string[] = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: THREADS }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: SPARKS }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/tickets", route => route.fulfill({ json: { plans: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.request().url().includes(plans.orcl) && route.request().url().includes("/chart")
    ? route.fulfill({ json: orclChart() }) : route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/contract?*", route => {
    const url = new URL(route.request().url());
    asked.push(`${url.searchParams.get("symbol")} ${url.searchParams.get("occ")}`);
    return route.fulfill(contract(url.searchParams.get("occ") ?? ""));
  });
  await page.route("**/copilot/desk/ticks?*", async route => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [ORCL_CALL]: { last: 4.1, change_pct: null, prev_close: null, at }, ORCL: { last: 247, change_pct: -1.0, prev_close: 249.5, at },
      [APLD_PUT]: { last: 1.48, change_pct: null, prev_close: null, at }, APLD: { last: 28.6, change_pct: -2.0, prev_close: 29.2, at },
      MU: { last: 119, change_pct: 0.8, prev_close: 118, at },
    } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return asked;
}

const book = (page: Page) => page.getByTestId("desk-book");
const toggle = (page: Page) => page.getByTestId("desk-chart-view");

test("a held call: Contract shows its trades, his fills and P&L at the cursor, and stays chosen for that contract", async ({ page }) => {
  const asked = await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(page.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");  // the stock chart first
  await expect(toggle(page).getByRole("button", { name: "Stock" })).toHaveAttribute("aria-pressed", "true");
  expect(asked).toEqual([`ORCL ${ORCL_CALL}`]);  // one read, to know there is something to draw
  await toggle(page).getByRole("button", { name: "Contract" }).click();
  const canvas = page.getByTestId("desk-contract-canvas");
  await expect(canvas).toHaveAttribute("data-style", "candles");
  await expect(canvas).toHaveAttribute("data-bars", "45");
  await expect(page.getByRole("group", { name: "Timeframe" })).toHaveCount(0);  // the stock's timeframes have no place here
  await expect(page.getByTestId("desk-chart-canvas")).toHaveCount(0);
  // The latest price is the live mark (4.10, 11:00): 2 contracts x (410 − 620) = −$420.
  await expect(page.getByTestId("desk-contract-readout")).toContainText("ORCL 11/20/26 250C · Mark 4.10");
  await expect(page.getByTestId("desk-contract-readout")).toContainText("−$420 on 2 contracts");
  await expect(page.getByTestId("desk-contract-legend")).toContainText("trades");
  await expect(page.getByTestId("desk-contract-legend")).toContainText("mark (bid/ask mid) while the desk was open");
  await expect(page.getByTestId("desk-contract-legend")).toContainText("your fills");
  // The closing tickets stay in the position header above the chart.
  await expect(page.getByTestId("desk-chart").getByTestId("close-from-plan").getByRole("button")).toHaveText(["Close at target", "Close at stop"]);
  // At the cursor: the price and which it is, his P&L for 2 contracts, and ORCL then.
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5);
  const tip = page.getByTestId("desk-contract-tip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText("trade");
  await expect(tip.getByTestId("desk-contract-tip-pnl")).toContainText(/^−\$\d{3} on 2 contracts$/);
  await expect(tip.getByTestId("desk-contract-tip-stock")).toContainText(/^ORCL 24\d\.\d\d$/);

  // Another position and back: the choice is this contract's, kept in this browser.
  await book(page).getByRole("button", { name: "APLD 11/27/26 30P" }).click();
  await expect(page.getByTestId("desk-chart-view")).toHaveCount(0);  // no trades to draw: no toggle, the stock chart
  await page.reload();
  await expect(page.getByTestId("desk-book")).toBeVisible();
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(page.getByTestId("desk-contract-canvas")).toHaveAttribute("data-bars", "45");
  await toggle(page).getByRole("button", { name: "Stock" }).click();
  await expect(page.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await expect(page.getByRole("group", { name: "Timeframe" })).toBeVisible();
});

test("a row with no quotable contract is never asked about, and a refused read leaves the toggle out", async ({ page }) => {
  const asked = await open(page, { contract: () => ({ status: 503, json: { detail: "Copilot Lab is off." } }) });
  await book(page).getByRole("button", { name: "MU 11/20/26 120C" }).click();
  await expect(page.getByTestId("option-standing").first()).toBeVisible();
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(page.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await expect.poll(() => asked.length).toBeGreaterThan(0);
  await expect(toggle(page)).toHaveCount(0);
  expect(new Set(asked)).toEqual(new Set([`ORCL ${ORCL_CALL}`]));  // MU's row has no contract to quote: never read
});

test("on a phone the toggle is a full-size tap and the contract chart fits", async ({ page }) => {
  await open(page, { width: 375, height: 812 });
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const button = toggle(page).getByRole("button", { name: "Contract" });
  await expect(button).toBeVisible();
  expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await button.click();
  await expect(page.getByTestId("desk-contract-canvas")).toHaveAttribute("data-bars", "45");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});
