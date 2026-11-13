import { expect, test, type Page } from "@playwright/test";

// Where a held option stands (docs/copilot-lab.md § The desk): selecting a held call or put shows its break-even, days
// left, value at expiry against now, decay, delta and IV under the centre's header and in one line under its book row;
// the stock-price figures move with the desk's live prices; a ticker that also holds a short leg shows no numbers.
// Every lab route is stubbed in the browser; every number here is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ids = { orcl: "11111111-1111-4111-8111-111111111111", apld: "22222222-2222-4222-8222-222222222222",
  nbisLong: "33333333-3333-4333-8333-333333333333", nbisShort: "44444444-4444-4444-8444-444444444444" };
const ORCL_CALL = "ORCL261120C00250000";
const APLD_PUT = "APLD261113P00030000";

const position = (id: string, symbol: string, contract: string, book: object) => ({
  key: `trade:${id}`, group: "watch", symbol, title: `${symbol} ${contract}`, instrument: contract, trade_id: id,
  value: null, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${id}`, hidden: false,
  meter: null, investigation_id: null, radar_event_id: null, changed_at: null, book,
});
const base = { days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null };
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [
    // Two ORCL 250 calls bought at 6.20 (620 a contract), Robinhood's Greeks.
    position(ids.orcl, "ORCL", "11/20/26 250C", { ...base, usd: -420, pct: -33.9, expiry: "2026-11-20",
      tick: { quote: ORCL_CALL, scale: 100, cost: 620, quantity: 2, sign: 1 },
      option: { side: "call", strike: 250, expiry: "2026-11-20", direction: "long", quantity: 2, multiplier: 100, cost: 620,
        greeks: { delta: 0.38, theta: -0.31, iv: 0.44, as_of: epoch("2026-11-13T15:59:30Z"), source: "robinhood" } } }),
    // Three APLD 30 puts expiring today, bought at 0.95; the app's own hourly Greeks.
    position(ids.apld, "APLD", "11/13/26 30P", { ...base, usd: 159, pct: 55.8, expiry: "2026-11-13",
      tick: { quote: APLD_PUT, scale: 100, cost: 95, quantity: 3, sign: 1 },
      option: { side: "put", strike: 30, expiry: "2026-11-13", direction: "long", quantity: 3, multiplier: 100, cost: 95,
        greeks: { delta: -0.82, theta: -0.09, iv: 0.95, as_of: "2026-11-13 15:00:00", source: "tradier" } } }),
    // A call spread the book holds as two trades: no standing for either leg.
    position(ids.nbisLong, "NBIS", "11/20/26 100C", { ...base, usd: 80, pct: 20, expiry: "2026-11-20", tick: null,
      option: { side: "call", strike: 100, expiry: "2026-11-20", direction: "long", quantity: 1, multiplier: 100, cost: 400, greeks: null } }),
    position(ids.nbisShort, "NBIS", "11/20/26 110C", { ...base, usd: -30, pct: -20, expiry: "2026-11-20", tick: null,
      option: { side: "call", strike: 110, expiry: "2026-11-20", direction: "short", quantity: 1, multiplier: 100, cost: 150, greeks: null } }),
  ],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const SPARKS = { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
  ORCL: { points: [250, 248, 247], change_pct: -1.2, last: 247 }, APLD: { points: [29.4, 28.9, 28.6], change_pct: -2.1, last: 28.6 },
  NBIS: { points: [104, 105], change_pct: 0.8, last: 105 } } };

type Feed = { orcl: number; orclMark: number };

async function open(page: Page, feed: Feed, { width = 1440, height = 900 } = {}) {
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
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/ticks?*", async route => {
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [ORCL_CALL]: { last: feed.orclMark, change_pct: null, prev_close: null, at },
      ORCL: { last: feed.orcl, change_pct: -1.0, prev_close: 249.5, at },
      [APLD_PUT]: { last: 1.48, change_pct: null, prev_close: null, at },
      APLD: { last: 28.6, change_pct: -2.0, prev_close: 29.2, at },
      NBIS: { last: 105, change_pct: 0.8, prev_close: 104.2, at },
    } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

const book = (page: Page) => page.getByTestId("desk-book");
const standing = (page: Page) => page.getByTestId("desk-chart").getByTestId("option-standing");

test("a held call and a held put show where they stand; the stock-price figures move with the live price", async ({ page }) => {
  const feed: Feed = { orcl: 247, orclMark: 4.1 };
  await open(page, feed);
  await book(page).getByRole("button", { name: "ORCL 11/20/26 250C" }).click();
  const head = standing(page);
  // 250 + 6.20 = 256.20; the stock at 247 needs +9.20 (+3.7%).
  await expect(head.getByTestId("standing-break-even")).toHaveText("Break-even 256.20 · stock 247.00 needs +$9.20 (+3.7%)");
  await expect(head.getByTestId("standing-expiry")).toHaveText("Expiry 7d left");
  // Out of the money: $0 at expiry if it stays here, 2 x 410 = $820 now, all of it time value.
  await expect(head.getByTestId("standing-at-expiry")).toHaveText("If it stays here $0 at expiry · $820 now · $820 time value");
  await expect(head.getByTestId("standing-decay")).toHaveText("Decay −$62/day"); // −0.31 x 100 x 2
  await expect(head.getByTestId("standing-delta")).toHaveText("Moves about +$76 per $1 up in ORCL"); // 0.38 x 200
  await expect(head.getByTestId("standing-iv")).toHaveText("IV 44%");
  await expect(head.getByTestId("standing-greeks")).toHaveText(/^Greeks · Robinhood 10:59/);
  await expect(head.getByTestId("option-expiry-line")).toBeVisible();
  await expect(book(page).getByTestId("book-standing")).toHaveText("BE 256.20 +3.7% · $820 time value · −$62/day · +$76 per $1 · IV 44%");

  // The stock runs to 258 and the call to 9.50: past break-even, $1,600 at expiry, $1,900 now.
  feed.orcl = 258;
  feed.orclMark = 9.5;
  await page.clock.runFor(6_000);
  await expect(head.getByTestId("standing-break-even")).toHaveText("Break-even 256.20 · stock 258.00 $1.80 (0.7%) past it");
  await expect(head.getByTestId("standing-at-expiry")).toHaveText("If it stays here $1,600 at expiry · $1,900 now · $300 time value");

  // A put expiring today, past break-even: 3 x (30 − 28.60) = $420 at expiry, 3 x 148 = $444 now.
  await book(page).getByRole("button", { name: "APLD 11/13/26 30P" }).click();
  await expect(head.getByTestId("standing-break-even")).toHaveText("Break-even 29.05 · stock 28.60 $0.45 (1.6%) past it");
  await expect(head.getByTestId("standing-expiry")).toHaveText("Expiry Expires today · 0d");
  await expect(head.getByTestId("standing-at-expiry")).toHaveText("If it stays here $420 at expiry · $444 now · $24 time value");
  await expect(head.getByTestId("standing-decay")).toHaveText("Decay −$27/day");
  await expect(head.getByTestId("standing-delta")).toHaveText("Moves about −$246 per $1 up in APLD");
  await expect(head.getByTestId("standing-greeks")).toHaveText("Greeks · app quote, hourly (stamp 15:00)");
});

test("one leg of a spread shows no numbers, and a stock row has no standing", async ({ page }) => {
  await open(page, { orcl: 247, orclMark: 4.1 });
  await book(page).getByRole("button", { name: "NBIS 11/20/26 100C" }).click();
  await expect(standing(page)).toHaveText(/not shown: a short or multi-leg position/);
  await expect(standing(page).getByTestId("standing-break-even")).toHaveCount(0);
  await expect(book(page).getByTestId("book-standing")).toHaveCount(0);
});
