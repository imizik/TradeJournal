import { expect, test, type Page, type Request } from "@playwright/test";

// Closing tickets from a held option's plan (docs/copilot-lab.md § Ticket): a planned long call or put shows "Close at
// target" and "Close at stop" in the position header and under its book row; each opens the Ticket as a sell to close
// of the contracts held, with a limit estimated from the mark and delta for the stock at that level and the mark beside
// it. Copy only: no Send button, and opening one makes no request. The plan's target is a line on the chart. A missing
// input (no plan, no target, no delta) leaves its button out. Every lab route is stubbed; every number is invented.
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

async function open(page: Page, { width = 1440, height = 900 } = {}) {
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
  page.on("request", request => { if (request.method() !== "GET") writes.push(request); });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return writes;
}

const book = (page: Page) => page.getByTestId("desk-book");
const header = (page: Page) => page.getByTestId("desk-chart").getByTestId("option-standing");
const ticket = (page: Page) => page.getByTestId("desk-ticket");

test("a planned call: the target line on the chart, then Close at target fills a sell-to-close ticket to copy", async ({ page }) => {
  const writes = await open(page);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  await expect(page.getByTestId("desk-chart-lines")).toContainText("Target 258.00");
  // The What if…'s "At my target" lights up from the saved target and moves the stock there.
  await header(page).locator("..").getByTestId("what-if-toggle").click();
  const whatIf = page.getByTestId("what-if");
  await expect(whatIf.getByTestId("what-if-target")).toBeEnabled();
  await expect(whatIf.getByTestId("what-if-target")).toHaveText("At my target 258.00");
  await whatIf.getByTestId("what-if-target").click();
  await expect(whatIf).toContainText("258.00 (+4.5% from now)");
  const buttons = header(page).getByTestId("close-from-plan");
  await expect(buttons.getByRole("button")).toHaveText(["Close at target", "Close at stop", "Roll"]);
  // The same two (and Roll) under the book row's detail line.
  await expect(book(page).getByTestId("close-from-plan").getByRole("button")).toHaveText(["Close at target", "Close at stop", "Roll"]);
  await page.clock.runFor(6_000); // the live option tick has arrived: the ticket's mark is live, not the last read
  const before = writes.length;
  await buttons.getByRole("button", { name: "Close at target" }).click();
  const t = ticket(page);
  await expect(t).toHaveAttribute("data-closing", "target");
  await expect(t).toContainText("ORCL · Close at target, 258.00");
  await expect(t).toContainText("A closing sell of the 2 contracts you hold");
  await expect(t).toContainText("Roth IRA ••8267");
  await expect(t).toContainText("Sell to close");
  await expect(t.getByTestId("closing-when")).toContainText("It can wait in Robinhood as a limit: it fills only if the option trades up to it.");
  await expect(t).toContainText("ORCL $250 Call 11/20/26");
  await expect(t.getByLabel("Quantity in contracts")).toHaveValue("2");
  // 4.10 + 0.38 x (258 − 247) = 8.28, marked as an estimate with today's mark beside it.
  await expect(t.getByLabel("Limit price per share")).toHaveValue("8.28");
  await expect(t.getByTestId("closing-mark")).toHaveText("Mark now 4.10");
  await expect(t.getByTestId("closing-estimate")).toContainText("Estimate, not a quote: if ORCL reaches 258.00 (now 247.00");
  await expect(t.getByTestId("closing-estimate")).toContainText("the mark 4.10 +4.18 by its delta +0.38 ≈ 8.28");
  await expect(t).toContainText("about $1,656.00 at this limit");
  // Copy only: no Send button of any kind, and opening the ticket wrote nothing.
  await expect(t.getByRole("button", { name: /send/i })).toHaveCount(0);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await t.getByRole("button", { name: "Copy all for Robinhood" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "ORCL\nSell · Call\nExpiration 11/20/26\nStrike $250\nLimit price 8.28\nContracts 2");
  expect(writes.slice(before).map(r => `${r.method()} ${new URL(r.url()).pathname}`)).toEqual([]);

  // Close at stop, from the book row while the Ticket has the centre: 4.10 + 0.38 x (240 − 247) = 1.44.
  await book(page).getByRole("button", { name: "Close at stop" }).click();
  await expect(ticket(page)).toHaveAttribute("data-closing", "stop");
  await expect(ticket(page).getByLabel("Limit price per share")).toHaveValue("1.44");
  // A sell under today's bid fills at once: the ticket says to place it only once ORCL is at the stop.
  await expect(ticket(page).getByTestId("closing-when")).toContainText("Place it only once ORCL is at 240.00");
  await ticket(page).getByRole("button", { name: "Not now" }).click();
  await expect(page.getByTestId("desk-ticket")).toContainText("A ticket opens only from a saved plan.");
});

test("a put with a stop and no target offers only Close at stop; a journal-only position offers neither", async ({ page }) => {
  await open(page);
  await book(page).getByRole("button", { name: "APLD 11/27/26 30P" }).click();
  await expect(header(page).getByTestId("close-from-plan").getByRole("button")).toHaveText(["Close at stop", "Roll"]);
  await header(page).getByRole("button", { name: "Close at stop" }).click();
  // 1.48 − 0.42 x (29.5 − 28.6) = 1.102 → 1.10, on Robinhood's Individual account.
  await expect(ticket(page).getByLabel("Limit price per share")).toHaveValue("1.10");
  await expect(ticket(page)).toContainText("Individual ••1234");
  await expect(ticket(page).getByLabel("Quantity in contracts")).toHaveValue("3");

  await book(page).getByRole("button", { name: "MU 11/20/26 120C" }).click();
  await expect(header(page)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Close at/ })).toHaveCount(0); // no closing ticket without Robinhood's account
  await expect(header(page).getByTestId("roll-open")).toBeVisible(); // a roll needs no account: it names none
});

test("on a phone the closing buttons are full-size taps and the ticket fits", async ({ page }) => {
  await open(page, { width: 375, height: 812 });
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const button = book(page).getByRole("button", { name: "Close at target" });
  await expect(button).toBeVisible();
  expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await button.click();
  await expect(ticket(page).getByLabel("Limit price per share")).toHaveValue("8.28");
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(375);
});
