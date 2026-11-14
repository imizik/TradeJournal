import { expect, test, type Page } from "@playwright/test";

// His TradingView alerts on the desk (docs/copilot-lab.md § The desk): each one that fired today is a row under Mine,
// counted as new, with what fired, the price then and how long ago; Show on chart puts its ticker on the desk chart,
// where the alert is a mark with its words; On Signals opens the stored alert. A day with none ends Mine with one grey
// line saying when the last one came. Every route is stubbed; every number is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ALERT_ID = "v1:1.0.0:NBIS:5:1763049600000:orb_break:long";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" }, threads: [],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
};
const item = (over: Record<string, unknown>) => ({
  has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null,
  setup: null, plan: null, mine: false, upcoming: false, ...over,
});
const ALERT = item({ id: `tradingview:${ALERT_ID}`, source: "TradingView", at: epoch("2026-11-13T15:46:00Z"), symbol: "NBIS",
  text: "ORB break long · 5m at 94.12", href: `/signals/${encodeURIComponent(ALERT_ID)}`, plan: "own", mine: true });
const feed = (items: unknown[], lastAt: number | null) => ({
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: items.length, sources: {},
  unavailable: [], items, tradingview: { last_at: lastAt },
});
const MARKET = item({ id: "news:fed", source: "News", at: epoch("2026-11-13T15:00:00Z"), text: "Yields climb before the Fed minutes", publisher: "Reuters" });

/** NBIS's chart read: 60 two-minute candles around 94 with the alert as a mark at 10:46. */
function nbisChart() {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 94 + Math.sin(i / 5) * 0.6;
    return { time: last - (59 - i) * 120, open, high: open + 0.2, low: open - 0.2, close: open + 0.05, volume: 1000, extended: false };
  });
  return { symbol: "NBIS", timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 94.1, at: last, daily: false, prev_close: 93.2, vwap: null, vwap_at: null, rvol: null }, levels: [], alerts: [],
    marks: [{ kind: "tradingview", at: epoch("2026-11-13T15:46:00Z"), price: null, side: null, text: "ORB break long · 5m at 94.12" }],
    time_stop: null, events: { earnings: null, macro: [], note: null } };
}

async function open(page: Page, body: unknown) {
  const reads: Record<string, unknown> = {
    "/copilot/desk/threads": THREADS,
    "/copilot/desk/session": SESSION,
    "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
    "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: {} },
    "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null, groups: [], movers: [] },
    "/copilot/desk/feed": body,
    "/copilot/investigations": { investigations: [] },
    "/copilot/tickets": { plans: [] },
    "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
    "/copilot/scanner": { state: "off", rows: [] },
    "/copilot/exposure": { line: null },
  };
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, json] of Object.entries(reads)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json }));
  await page.route("**/copilot/desk/*/news*", route => route.fulfill({ json: { state: "none", groups: [], complete_from: null, as_of: epoch("2026-11-13T16:00:00Z") } }));
  await page.route("**/copilot/desk/*/chart*", route => route.fulfill({ json: nbisChart() }));
  await page.route("**/copilot/desk/minute?*", route => {
    const answers = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const json = reads[target.split("?")[0]];
      return json ? { status: 200, body: json } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads: answers } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

test("an alert that fired today: a row under Mine, counted as new, and Show on chart marks it there", async ({ page }) => {
  await open(page, feed([ALERT, MARKET], epoch("2026-11-13T15:46:00Z")));
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await expect(page.getByTestId("feed-new")).toHaveText("1 new"); // his alert; the market's headline never counts
  await centre.getByRole("tab", { name: "Feed" }).click();
  const feedList = centre.getByTestId("desk-feed");
  const row = feedList.getByTestId("feed-item");
  await expect(row).toHaveCount(1); // Mine: the alert only
  await expect(row.getByTestId("feed-source")).toHaveText("TradingView");
  await expect(row).toContainText("10:46 · 14 min ago");
  await expect(row).toContainText("NBIS");
  await expect(row).toContainText("ORB break long · 5m at 94.12");
  await expect(row.getByRole("link", { name: "On Signals" })).toHaveAttribute("href", `/signals/${encodeURIComponent(ALERT_ID)}`);
  await expect(row.getByRole("button", { name: "Plan it" })).toBeVisible();
  await expect(row.getByRole("button", { name: "Ask the copilot" })).toBeVisible();
  await expect(feedList.getByTestId("feed-tradingview-quiet")).toHaveCount(0);
  await row.getByRole("button", { name: "Show on chart" }).click();
  await expect(centre.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("[data-marks]")).toHaveAttribute("data-marks", "1");
  await expect(page.getByTestId("desk-chart-marks")).toContainText("TradingView · ORB break long · 5m at 94.12 · 10:46 AM ET");
  await expect(page.getByLabel("Legend")).toContainText("TradingView");
});

test("a day with no alert yet: one grey line with the last one's time, and nothing when there has never been one", async ({ page }) => {
  await open(page, feed([MARKET], epoch("2026-11-12T20:42:00Z")));
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await centre.getByRole("tab", { name: "Feed" }).click();
  const feedList = centre.getByTestId("desk-feed");
  await expect(feedList.getByTestId("feed-tradingview-quiet")).toHaveText("No TradingView alerts today. Last one Thu 15:42.");
  await feedList.getByRole("group", { name: "Show" }).getByRole("button", { name: "Market" }).click();
  await expect(feedList.getByTestId("feed-tradingview-quiet")).toHaveCount(0); // Mine only
});

test("no alert ever: no line at all", async ({ page }) => {
  await open(page, feed([MARKET], null));
  const centre = page.getByRole("region", { name: "Chart and feed" });
  await centre.getByRole("tab", { name: "Feed" }).click();
  await expect(centre.getByTestId("desk-feed").getByText("Nothing on your book or plans yet today.", { exact: false })).toBeVisible();
  await expect(centre.getByTestId("feed-tradingview-quiet")).toHaveCount(0);
});
