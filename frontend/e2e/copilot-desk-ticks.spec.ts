import { expect, test, type Page } from "@playwright/test";

// The desk's live prices (docs/copilot-lab.md § Live prices): in the session one shared read every few seconds moves the
// book's P&L, the Watching rows and the chart's reading line in place (no remount, no other desk read again); a price no
// longer live is greyed with its time; outside the session nothing polls. Every lab route is stubbed in the browser.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const CALL = "ORCL261120C00050000";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{
    key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 50C", instrument: "11/20/26 50C", trade_id: ORCL,
    value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`, hidden: false,
    meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
    // One contract bought at 2.20 (220 a contract): -$120 at a 1.00 mark.
    book: { usd: -120, pct: -54.5, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null,
      tick: { quote: CALL, scale: 100, cost: 220, quantity: 1, sign: 1 } },
  }],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const WATCHING = { state: "ok", symbols: ["NVDA"], count: 1, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} };
const SPARKS = { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {
  ORCL: { points: [250, 248, 246], change_pct: -1.2 }, NVDA: { points: [99, 100, 100.5], change_pct: 0.5, last: 100.5 } } };

type Feed = { state: "ok" | "closed" | "fail"; mark: number; nvda: number; asked: string[]; reads: Record<string, number> };

async function open(page: Page, feed: Feed, { width = 1440, height = 900 } = {}) {
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  const count = (name: string) => { feed.reads[name] = (feed.reads[name] ?? 0) + 1; };
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => { count("threads"); return route.fulfill({ json: THREADS }); });
  await page.route("**/copilot/desk/session", route => { count("session"); return route.fulfill({ json: SESSION }); });
  await page.route("**/copilot/desk/pings*", route => route.fulfill({ json: { day: "2026-11-13", since: "2026-11-12", alerts: { state: "ok", rows: [] }, radar: { state: "off", reason: null, rows: [] } } }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => { count("sparks"); return route.fulfill({ json: SPARKS }); });
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: WATCHING }));
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/desk/*/{picture,chart}*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/ticks?*", async route => {
    feed.asked.push(new URL(route.request().url()).searchParams.get("symbols") ?? "");
    // The browser's clock, so a tick's time is the page's "now".
    const at = Math.floor(await page.evaluate(() => Date.now() / 1000));
    if (feed.state === "fail") return route.fulfill({ status: 200, json: { state: "unavailable", as_of: "", rows: {}, poll_seconds: 5 } });
    if (feed.state === "closed") return route.fulfill({ json: { state: "closed", as_of: "", rows: {}, opens_at: null, poll_seconds: null } });
    return route.fulfill({ json: { state: "ok", as_of: "", poll_seconds: 5, closes_at: epoch("2026-11-13T21:00:00Z"), rows: {
      [CALL]: { last: feed.mark, change_pct: null, prev_close: null, at },
      ORCL: { last: 247, change_pct: -1.0, prev_close: 249.5, at },
      NVDA: { last: feed.nvda, change_pct: 1.25, prev_close: 99.5, at },
    } } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

const pnl = (page: Page) => page.getByTestId("desk-book").getByTestId("book-pnl");
const watchPrice = (page: Page) => page.getByTestId("desk-watching").getByTestId("watch-price");
const feedOf = (state: Feed["state"]): Feed => ({ state, mark: 1.0, nvda: 101, asked: [], reads: {} });

test("in the session the book and Watching rows move in place every few seconds", async ({ page }) => {
  const feed = feedOf("ok");
  await open(page, feed);
  await expect(pnl(page)).toHaveText("−$120−55%");
  await expect(watchPrice(page)).toContainText("101.00");
  const reads = { ...feed.reads };
  // Mark the row's element: a remount would replace it.
  await pnl(page).evaluate(node => { (node as HTMLElement & { kept?: boolean }).kept = true; });
  feed.mark = 1.5;
  feed.nvda = 102.25;
  await page.clock.runFor(5_000);
  await expect(pnl(page)).toHaveText("−$70−32%");
  // One read for every piece: the held contract, its underlying, the watched name (the chart's symbol is ORCL too).
  expect(feed.asked.at(-1)!.split(",")).toEqual(expect.arrayContaining([CALL, "ORCL", "NVDA"]));
  await expect(watchPrice(page)).toContainText("102.25");
  await expect(watchPrice(page)).toContainText("+1.25%");
  expect(await pnl(page).evaluate(node => (node as HTMLElement & { kept?: boolean }).kept)).toBe(true); // the same element
  expect(feed.reads).toEqual(reads); // no other desk read again
  await expect(page.getByTestId("prices-as-of")).toHaveCount(0);
  expect(await pnl(page).evaluate(node => node.className)).not.toMatch(/opacity-50/);
});

test("a price no longer live is greyed with its time, then hands back to the minute reads; the reads back off", async ({ page }) => {
  const feed = feedOf("ok");
  await open(page, feed);
  await expect.poll(() => feed.asked.some(symbols => symbols.includes(CALL))).toBe(true); // the contract's price is in
  feed.mark = 1.1;
  await page.clock.runFor(5_000);
  await expect(pnl(page)).toHaveText("−$110−50%");
  await expect(page.getByTestId("desk-pnl-open")).toHaveText("−$110");
  feed.state = "fail";
  const before = feed.asked.length;
  await page.clock.runFor(25_000);
  // The last good price stays, greyed, with the time it was read: never a zero, never a number that looks live.
  await expect(pnl(page)).toHaveText("−$110−50%");
  await expect.poll(() => pnl(page).evaluate(node => node.className)).toMatch(/opacity-50/);
  await expect.poll(() => page.getByTestId("desk-pnl-open").evaluate(node => node.className)).toMatch(/opacity-50/);
  await expect(page.getByTestId("desk-book").getByTestId("prices-as-of")).toHaveText(/^prices 11:00:\d\d AM$/);
  await expect(page.getByTestId("desk-watching").getByTestId("prices-as-of")).toHaveText(/^prices 11:00:\d\d AM$/);
  // 25 s of failures: 5, 10 then 20 s apart, not one every 5 s.
  expect(feed.asked.length - before).toBeLessThanOrEqual(3);
  // Past a minute the old tick is dropped: the desk's own minute read (the server's -$120) shows, as before live prices.
  await page.clock.runFor(40_000);
  await expect(pnl(page)).toHaveText("−$120−55%");
  expect(await pnl(page).evaluate(node => node.className)).not.toMatch(/opacity-50/);
  await expect(page.getByTestId("prices-as-of")).toHaveCount(0);
  feed.state = "ok";
  feed.mark = 1.2;
  await page.clock.runFor(60_000);
  await expect(pnl(page)).toHaveText("−$100−46%");
  await expect(page.getByTestId("desk-pnl-open")).toHaveText("−$100");
});

test("outside the session nothing polls", async ({ page }) => {
  const feed = feedOf("closed");
  await open(page, feed);
  await expect(pnl(page)).toHaveText("−$120−55%");
  await page.clock.runFor(5 * 60_000);
  expect(feed.asked.length).toBe(1); // the one read that said closed; the next is after the half hour
  await expect(page.getByTestId("prices-as-of")).toHaveCount(0);
});

test("on a phone the rows tick without changing the layout", async ({ page }) => {
  const feed = feedOf("ok");
  await open(page, feed, { width: 390, height: 844 });
  await expect(pnl(page)).toHaveText("−$120−55%");
  const before = await pnl(page).boundingBox();
  feed.mark = 1.5;
  await page.clock.runFor(5_000);
  await expect(pnl(page)).toHaveText("−$70−32%");
  const after = await pnl(page).boundingBox();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
  expect(Math.abs(after!.height - before!.height)).toBeLessThan(1);
});
