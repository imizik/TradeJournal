import { expect, test, type Page, type Request } from "@playwright/test";

// The roll ticket (docs/copilot-lab.md § Ticket, "Roll"): a held single long call or put shows Roll beside its closing
// buttons; it opens the Ticket in roll mode with the held contract as leg 1 and the Chain under it to pick leg 2; once
// picked, the ticket reads GET /copilot/roll once and shows both legs' quotes, the net at the mid and the natural price,
// the dollars, break-evens, days added and money in the trade, and copies Robinhood's roll screen (two orders when the
// counts differ). Copy only: no Send button, no write. Every lab route is stubbed; every number is invented.
const rolls: string[] = [];
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

async function open(page: Page, { width = 1440, height = 900, roll = rollReply }: { width?: number; height?: number; roll?: (q: URLSearchParams) => { json?: object; status?: number } } = {}) {
  rolls.length = 0;
  const writes: Request[] = [];
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
  await page.route("**/copilot/desk/ticks?*", async route => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [ORCL_CALL]: { last: 4.1, change_pct: null, prev_close: null, at }, ORCL: { last: 247, change_pct: -1.0, prev_close: 249.5, at },
      [APLD_PUT]: { last: 1.48, change_pct: null, prev_close: null, at }, APLD: { last: 28.6, change_pct: -2.0, prev_close: 29.2, at },
      MU: { last: 119, change_pct: 0.8, prev_close: 118, at },
    } } });
  });
  await page.route(/\/copilot\/chain\?/, route => route.fulfill({ json: orclChain(new URL(route.request().url()).searchParams.get("expiration") ?? "2026-11-20") }));
  await page.route(/\/copilot\/roll\?/, route => {
    const url = new URL(route.request().url());
    rolls.push(url.search);
    return route.fulfill(roll(url.searchParams));
  });
  page.on("request", request => { if (request.method() !== "GET") writes.push(request); });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return writes;
}


/** ORCL's chain: the held Nov 20 and a Dec 18 expiry, calls and puts 240–260. */
function orclChain(expiration: string) {
  const now = epoch("2026-11-13T16:00:00Z");
  const later = expiration === "2026-12-18";
  const cell = (strike: number, side: "call" | "put") => {
    const mark = Math.max((side === "call" ? 247 - strike : strike - 247), 0) + (later ? 7 : 3);
    return { symbol: `ORCL${expiration.replaceAll("-", "").slice(2)}${side[0].toUpperCase()}${String(strike * 1000).padStart(8, "0")}`,
      bid: +(mark - 0.1).toFixed(2), ask: +(mark + 0.1).toFixed(2), mark: +mark.toFixed(2), last: null, spread: 0.2, spread_pct: 3, wide: false, spread_note: null,
      volume: 100, open_interest: 900, delta: side === "call" ? 0.4 : -0.4, iv: 44, quoted_at: now - 20, state: "ok", multiplier: 100,
      held: !later && side === "call" && strike === 250 ? 2 : null, planned: false };
  };
  return {
    symbol: "ORCL", state: "ok", session: "open", poll_seconds: 15, expiries: [{ date: "2026-11-20", days: 7, kind: "monthly", held: true }, { date: "2026-12-18", days: 35, kind: "monthly", held: false }],
    expiration, spot: 247, spot_at: now - 5, spot_issue: null, atm_strike: 247.5, fetched_at: now - 3, age_s: 3, stale: false, message: null, simulated: false,
    rows: [240, 245, 250, 255, 260].map(strike => ({ strike, atm: strike === 245, levels: [], call: cell(strike, "call"), put: cell(strike, "put") })), levels: [],
  };
}

/** The roll route's reply: 250C Nov 20 at 3.95 x 4.15 (mid 4.05), 255C Dec 18 at 5.35 x 5.55 (mid 5.45): 1.40 debit at the
 *  mid, 5.55 − 3.95 = 1.60 at the natural price. */
function rollReply(q: URLSearchParams, stale = false) {
  const now = epoch("2026-11-13T16:00:00Z");
  const quote = (bid: number, ask: number) => ({ state: "ok", as_of: now - 30, simulated: false, multiplier: 100, bid, ask, mid: +((bid + ask) / 2).toFixed(2), spread: +(ask - bid).toFixed(2), spread_pct: 3.7 });
  const close = stale ? { state: "stale", as_of: now - 3600, reason: "The latest bid and ask are too old to price an order from.", simulated: false, multiplier: 100 } : quote(3.95, 4.15);
  return { json: {
    state: "ok", symbol: q.get("symbol"), kind: "call", simulated: false, held: Number(q.get("held")), close_qty: Number(q.get("held")), open_qty: Number(q.get("held")), kept: 0, multiplier: 100,
    legs: [
      { role: "close", action: "sell_to_close", strike: 250, expiry: "2026-11-20", label: "ORCL $250 Call 11/20/26", quote: close, wide: false },
      { role: "open", action: "buy_to_open", strike: Number(q.get("new_strike")), expiry: q.get("new_expiration"), label: "ORCL $255 Call 12/18/26", quote: quote(5.35, 5.55), wide: false },
    ],
    rough: stale ? ["the contract you hold has a stale quote"] : [], close_mid: stale ? null : 4.05, open_mid: 5.45,
    net_mid: stale ? null : 1.4, net_mid_type: stale ? null : "debit", net_natural: stale ? null : 1.6, net_natural_type: stale ? null : "debit",
    underlying: { state: "ok", last: 247, as_of: now - 10 },
  } };
}

const book = (page: Page) => page.getByTestId("desk-book");
const header = (page: Page) => page.getByTestId("desk-chart").getByTestId("option-standing");
const rollView = (page: Page) => page.getByTestId("desk-roll");

async function pickDec255(page: Page) {
  const chain = rollView(page).getByTestId("desk-chain");
  await expect(chain.getByRole("radio", { name: /Nov 20/ })).toHaveAttribute("aria-checked", "true"); // opens on the held expiry
  await chain.getByRole("radio", { name: /Dec 18/ }).click();
  await chain.getByRole("button", { name: "255 call" }).click();
  await chain.getByTestId("chain-roll-pick").getByRole("button", { name: "Roll to this" }).click();
}

test("Roll: the held call is leg 1, the chain picks leg 2, and the ticket prices the roll to copy", async ({ page }) => {
  const writes = await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(header(page).getByTestId("close-from-plan").getByRole("button")).toHaveText(["Close at target", "Close at stop", "Roll"]);
  await header(page).getByTestId("roll-open").click();
  const r = rollView(page);
  await expect(r).toContainText("ORCL · Roll your 2 ORCL $250 Call 11/20/26");
  await expect(r).toContainText("Roth IRA ••8267");
  await expect(r.getByLabel("Contracts to close")).toHaveValue("2");
  // The chain's held contract itself, and a put, cannot be rolled to; each says why.
  const chain = r.getByTestId("desk-chain");
  await chain.getByRole("button", { name: "250 call" }).click();
  await expect(chain.getByTestId("chain-roll-pick")).toContainText("This is the contract you hold");
  await expect(chain.getByTestId("chain-roll-pick").getByRole("button", { name: "Roll to this" })).toBeDisabled();
  const puts = chain.getByRole("radio", { name: "Puts" }); // one side at a time when the tab is narrow
  if (await puts.count()) await puts.click();
  await chain.getByRole("button", { name: "245 put" }).click();
  await expect(chain.getByTestId("chain-roll-pick")).toContainText("A roll keeps the call");
  const calls = chain.getByRole("radio", { name: "Calls" });
  if (await calls.count()) await calls.click();
  await pickDec255(page);
  // One read, with the book row's terms: 2 held at $620 a contract.
  await expect.poll(() => rolls.length).toBe(1);
  const q = new URLSearchParams(rolls[0]);
  expect(Object.fromEntries(q)).toEqual({ symbol: "ORCL", option_type: "call", strike: "250", expiration: "2026-11-20", held: "2",
    new_strike: "255", new_expiration: "2026-12-18", cost: "620" });
  await expect(r.getByTestId("roll-net")).toContainText("1.40 debit at the mid · 1.60 debit at the natural price");
  await expect(r.getByLabel("Net limit price per share, debit")).toHaveValue("1.40");
  // 4.05 x 200 = $810 in; 5.45 x 200 = $1,090 out; the roll pays 1.40 x 200 = $280.
  await expect(r.getByTestId("roll-proceeds")).toContainText("$810.00 at the mid · $790.00 at the bid");
  await expect(r.getByTestId("roll-cost")).toContainText("$1,090.00 at the mid · $1,110.00 at the ask");
  await expect(r.getByTestId("roll-net-usd")).toContainText("You pay $280.00 at this limit");
  await expect(r.getByTestId("roll-breakeven")).toContainText("ORCL 260.45 at expiry"); // 255 + 5.45
  // $1,240 paid for the 2, plus $280: $1,520 in the trade; over 200 shares from 255: 262.60.
  await expect(r.getByTestId("roll-trade-breakeven")).toContainText("ORCL 262.60 at expiry");
  await expect(r.getByTestId("roll-basis")).toContainText("$1,240.00 paid for these 2 → $1,520.00 after the roll (+$280.00)");
  await expect(r.getByTestId("roll-risk")).toContainText("$810.00 (what yours are worth now) → $1,090.00 (what the new ones cost)");
  await expect(r.getByTestId("roll-days")).toHaveText("28 more days");
  await expect(r.getByTestId("roll-sentence")).toHaveText("Roll ORCL 250C Nov 20 → 255C Dec 18: pay $1.40 a share more ($280.00), break-even 260.45, 28 more days.");
  await expect(r.getByTestId("roll-plan")).toContainText("plan the new contract");
  // A typed credit flips the signs: 0.30 credit takes in $60.
  await r.getByLabel("Net limit price per share, debit").fill("0.30");
  await r.getByRole("radio", { name: "Credit (you take in)" }).click();
  await expect(r.getByTestId("roll-net-usd")).toContainText("You take in $60.00");
  await expect(r.getByTestId("roll-basis")).toContainText("→ $1,180.00 after the roll (−$60.00)");
  await r.getByRole("radio", { name: "Debit (you pay)" }).click();
  await r.getByLabel("Net limit price per share, debit").fill("1.40");
  // Copy only: no Send button; Copy all is Robinhood's roll screen.
  await expect(r.getByRole("button", { name: /send/i })).toHaveCount(0);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await r.getByRole("button", { name: "Copy all for Robinhood" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "ORCL · Roll\nLeg 1: Sell to close · ORCL $250 Call 11/20/26\nLeg 2: Buy to open · ORCL $255 Call 12/18/26\nLimit price 1.40 debit\nQuantity 2");
  // A different count on each leg: Robinhood's roll cannot take it, so two orders, the close first.
  await r.getByLabel("Contracts to open").fill("1");
  await expect(r.getByTestId("roll-two-orders")).toContainText("place two orders, in this order");
  await expect(r.getByTestId("roll-net-usd")).toContainText("You take in $265.00 across the two orders"); // 545 − 810
  await r.getByRole("button", { name: "Copy both orders for Robinhood" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "Order 1 of 2 · ORCL · Sell to close · ORCL $250 Call 11/20/26\nLimit price 4.05\nContracts 2\n\nOrder 2 of 2 · ORCL · Buy to open · ORCL $255 Call 12/18/26\nLimit price 5.45\nContracts 1");
  // Closing more than held is said, and the copy waits.
  await r.getByLabel("Contracts to close").fill("3");
  await expect(r).toContainText("You hold 2: a roll closes at most that many.");
  expect(writes.map(w => `${w.method()} ${new URL(w.url()).pathname}`)).toEqual([]);
});

test("a stale held quote: grey with its time, no net price, the net marked rough", async ({ page }) => {
  await open(page, { roll: q => rollReply(q, true) });
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await header(page).getByTestId("roll-open").click();
  await pickDec255(page);
  const r = rollView(page);
  await expect(r.getByTestId("roll-leg-quote").first()).toContainText("Quote stale (last 10:00 AM ET)");
  await expect(r.getByTestId("roll-net")).toContainText("No net price: the contract you hold has a stale quote.");
  await expect(r.getByTestId("roll-net")).toContainText("rough");
  await expect(r.getByLabel("Net limit price per share, debit")).toHaveValue("");
  await expect(r.getByTestId("roll-sentence")).toHaveCount(0);
  await expect(r.getByRole("button", { name: "Read the quotes again" })).toBeVisible();
});

test("a closing ticket offers Roll it instead", async ({ page }) => {
  await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await header(page).getByRole("button", { name: "Close at target" }).click();
  await page.getByTestId("closing-roll").click();
  await expect(rollView(page)).toContainText("Roll your 2 ORCL $250 Call 11/20/26");
});

test("on a phone Roll is a full-size tap and the roll ticket fits", async ({ page }) => {
  await open(page, { width: 375, height: 812 });
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const button = book(page).getByTestId("roll-open");
  await expect(button).toBeVisible();
  expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await button.click();
  await pickDec255(page);
  await expect(rollView(page).getByTestId("roll-sentence")).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(375);
});
