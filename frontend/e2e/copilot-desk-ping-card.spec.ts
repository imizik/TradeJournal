import { expect, test, type Page, type Request } from "@playwright/test";
import { exitOrders } from "@/components/copilot/PingCard";

// The ping card (docs/copilot-lab.md § Where a ping opens): a position ping's tap lands on what fired, what holding past
// that kind of ping has cost, the position as it stands, and Copy Close all @ bid first; the copilot's sheet waits behind
// Ask. Every lab route is stubbed; every number is invented.

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

async function open(page: Page, { width = 375, height = 812, path = LINK, card = CARD }: { width?: number; height?: number; path?: string; card?: object } = {}) {
  const writes: Request[] = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: THREADS }));
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
  await page.route("**/copilot/desk/ping-card?*", route => route.fulfill({ json: card }));
  await page.route("**/day-journal/2026-11-13", route => route.fulfill({ json: { day: "2026-11-13", entries: [], trade_plans: {} } }));
  await page.route("**/day-journal/2026-11-13/entries", route => route.fulfill({ json: { id: crypto.randomUUID(), day: "2026-11-13", ...route.request().postDataJSON(), created_at: "2026-11-13T16:00:00Z" } }));
  await page.route("**/fill-interrupts/*/noted", route => route.fulfill({ json: {} }));
  page.on("request", request => { if (request.method() !== "GET") writes.push(request); });
  await page.goto(path);
  return writes;
}

const ALERT_ID = "22222222-2222-4222-8222-222222222222";
const LINK = `/copilot-lab?symbol=ORCL&card=alert:${ALERT_ID}`;
const CARD = {
  symbol: "ORCL", interrupt: null, broker: { label: "Robinhood", url: "https://robinhood.com/stocks/ORCL" },
  alert: { id: ALERT_ID, kind: "giveback", kind_label: "Give-back", at: epoch("2026-11-13T15:57:00Z"), contract: "ORCL 11/20/26 250C",
    contracts: 2, bid: 395, mark: 405, gain: -430, gain_pct: -0.35, avg_cost: 620, quoted_at: epoch("2026-11-13T15:57:00Z") },
  habit: { kind: "giveback", kind_label: "Give-back", window_days: 30, held: 6, closed: 5, better: 1, worse: 4, vs_alert_usd: -1240 },
  position: { trade_id: ORCL_ID, open: true },
};
const card = (page: Page) => page.getByRole("region", { name: "Ping" });
// Without a Robinhood link the card copies the order lines as before; with one, Robinhood is the main button.
const COPY = { ...CARD, broker: null };
const posted = (writes: Request[]) => writes.filter(w => w.url().endsWith("/entries")).map(w => w.postDataJSON().text);

test("a give-back ping on a phone lands on its card, not the copilot's sheet", async ({ page }) => {
  await open(page);
  const c = card(page);
  await expect(c.getByTestId("ping-card-trigger")).toContainText("Give-back · 10:57 AM");
  await expect(c.getByTestId("ping-card-habit")).toHaveText("Held past 5 give-back pings (30 days): selling at the ping would have made $1,240 more.");
  await page.clock.runFor(6_000); // the live ticks land
  const figures = c.getByTestId("ping-card-figures");
  await expect(figures).toContainText("−$420"); // 2 × (410 − 620)
  await expect(figures).toContainText("3.95 / 4.10"); // the ping's bid a share, the mid now
  await expect(figures).not.toContainText("Exit order"); // the Robinhood feed is off: no claim about exit orders, not even "unknown"
  await expect(figures).not.toContainText("At expiry"); // worth $0 if the stock stays: the line is left out, it says nothing new
  // Robinhood is where he sells: the main button opens the position there; Cut it and Holding record the choice.
  await expect(c.getByTestId("ping-card-robinhood")).toHaveText("Open ORCL in Robinhood");
  await expect(c.getByTestId("ping-card-robinhood")).toHaveAttribute("href", "https://robinhood.com/stocks/ORCL");
  await expect(c.getByTestId("ping-card-cut")).toHaveText("I cut it");
  await expect(c.getByTestId("ping-card-holding")).toHaveText("Still holding…");
  await expect(c.getByTestId("ping-card-close")).toHaveCount(0);
  await expect(page.getByLabel("Message")).not.toBeInViewport(); // the sheet waits behind Ask
  const box = (await c.getByTestId("ping-card-robinhood").boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(48);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await c.screenshot({ path: test.info().outputPath("ping-card-phone.png") });
});

test("Cut it logs one exiting decision and points at Robinhood", async ({ page }) => {
  const writes = await open(page);
  await card(page).getByTestId("ping-card-cut").click();
  await expect(card(page).getByTestId("ping-card-done")).toHaveText("Saved: cutting it. Sell it in Robinhood.");
  await expect.poll(() => posted(writes)).toEqual(["Exiting. Give-back ping at 10:57 AM; said Cut it on the card."]);
});

test("with no Robinhood link, Copy Close all copies the order lines and logs one exiting decision", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const writes = await open(page, { card: COPY });
  await card(page).getByTestId("ping-card-close").click();
  await expect(card(page).getByTestId("ping-card-done")).toContainText("Copied: sell 2 at 3.95. Paste it in Robinhood.");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("ORCL\nSell · Call\nExpiration 11/20/26\nStrike $250\nLimit price 3.95\nContracts 2");
  await expect.poll(() => posted(writes)).toEqual(["Exiting. Give-back ping at 10:57 AM; copied close all 2 at bid 3.95."]);
});

test("Keep holding is not one tap: it asks for a check-in time or a price stop first", async ({ page }) => {
  const writes = await open(page);
  await card(page).getByTestId("ping-card-holding").click();
  expect(posted(writes)).toEqual([]);
  const pick = card(page).getByTestId("ping-card-hold-pick");
  await expect(pick.getByRole("button")).toHaveText(["+15m", "+30m", "Price stop", "Cancel"]);
  await pick.getByRole("button", { name: "+15m" }).click();
  await expect(card(page).getByTestId("ping-card-done")).toHaveText("Holding. Check again at 11:15 AM.");
  await expect.poll(() => posted(writes)).toEqual(["Holding. Give-back ping at 10:57 AM; check again at 11:15 AM."]);
  // The hold carries its check-in, so the server can ping again then (when its switch is on).
  expect(writes.find(w => w.url().endsWith("/entries"))!.postDataJSON().check_in).toEqual({ minutes: 15, alert: ALERT_ID });
});

test("with check-in pings on, Keep holding says it will ping at that time", async ({ page }) => {
  const writes = await open(page, { card: { ...CARD, check_in_pings: true } });
  await card(page).getByTestId("ping-card-holding").click();
  await card(page).getByTestId("ping-card-hold-pick").getByRole("button", { name: "+30m" }).click();
  await expect(card(page).getByTestId("ping-card-done")).toHaveText("Holding. I'll ping you at 11:30 AM if it's still open.");
  await expect.poll(() => writes.filter(w => w.url().endsWith("/entries")).map(w => w.postDataJSON().check_in))
    .toEqual([{ minutes: 30, alert: ALERT_ID }]);
});

test("a stale bid prices at the mid and says so; the card puts away to the chart", async ({ page }) => {
  await open(page, { card: { ...COPY, alert: { ...CARD.alert, at: epoch("2026-11-13T15:30:00Z"), quoted_at: epoch("2026-11-13T15:30:00Z") } } });
  await page.clock.runFor(6_000);
  await expect(card(page).getByTestId("ping-card-close")).toHaveText("Copy Close all 2 @ mid 4.10");
  await card(page).getByRole("button", { name: "Put the card away" }).click();
  await expect(card(page)).toHaveCount(0);
});

test("a ping on a position that has since closed offers no copy buttons", async ({ page }) => {
  await open(page, { card: { ...CARD, position: { trade_id: ORCL_ID, open: false } } });
  await expect(card(page).getByTestId("ping-card-closed")).toHaveText("This ORCL position is closed.");
  await expect(card(page).getByTestId("ping-card-close")).toHaveCount(0);
});

test("a ping names its own position: another ORCL row on the desk is not it", async ({ page }) => {
  await open(page, { card: { ...CARD, position: { trade_id: "99999999-9999-4999-8999-999999999999", open: true } } });
  await expect(card(page).getByTestId("ping-card-closed")).toContainText("not on the desk now");
  await expect(card(page).getByTestId("ping-card-close")).toHaveCount(0);
});

test("only a working closing order counts as the exit: a working buy to open is a scale-in", () => {
  const order = (action: string, working = true) => ({ contract: "ORCL 11/20/26 250C", symbol: "ORCL", instrument: "option" as const, action, working,
    quantity: 1, filled: 0, price_kind: "limit" as const, limit: 5, avg: null, placed_at: null, filled_at: null, account: { label: "RH", masked: "1234" }, pairing: null });
  expect(exitOrders([order("Buy to open")])).toEqual([]);
  expect(exitOrders([order("Sell to close", false)])).toEqual([]);
  expect(exitOrders([order("Buy to open"), order("Sell to close")]).map(o => o.action)).toEqual(["Sell to close"]);
  expect(exitOrders(undefined)).toEqual([]);
});

test("a risk ping's Trim button lands on the card pointing at Trim, without copying anything by itself", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const writes = await open(page, { path: `${LINK}&do=trim`, card: COPY });
  const trim = card(page).getByTestId("ping-card-trim");
  await expect(trim).toHaveAttribute("data-asked", "true");
  await expect(trim).toBeFocused();
  await expect(card(page).getByTestId("ping-card-close")).not.toHaveAttribute("data-asked");
  expect(posted(writes)).toEqual([]);
});
