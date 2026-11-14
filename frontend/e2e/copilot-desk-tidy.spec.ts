import { expect, test, type Page } from "@playwright/test";

// The desk's quiet defaults (docs/copilot-lab.md § The desk): What's moving starts folded and remembers being opened;
// no account line while the Robinhood feed is off; no "Realized today" before a trade closes; the Feed in four groups
// (Mine, Ideas, Market, All) with its tab counting only his own items; and on a phone the book comes before What's
// moving. Every route is stubbed.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York: in the session.
const NOW = new Date("2026-11-13T16:00:00Z");
const epoch = (iso: string) => Date.parse(iso) / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{
    key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 50C", instrument: "11/20/26 50C", trade_id: ORCL,
    value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`, hidden: false,
    meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
    book: { usd: -120, pct: -54.5, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null },
  }],
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
const FEED = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 3, sources: {}, unavailable: [],
  items: [
    item({ id: "news:orcl", source: "News", at: epoch("2026-11-13T15:20:00Z"), symbol: "ORCL", text: "Oracle books a cloud deal", publisher: "Benzinga", mine: true }),
    item({ id: "radar:mu", source: "Radar", at: epoch("2026-11-13T15:10:00Z"), symbol: "MU", text: "MU up 4.1% while SMH is up 0.6%", href: "/radar?event=1" }),
    item({ id: "news:fed", source: "News", at: epoch("2026-11-13T15:00:00Z"), text: "Yields climb before the Fed minutes", publisher: "Reuters" }),
  ],
};
const MOVING = { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null,
  groups: [{ key: "SPY", label: "SPY", kind: "index", symbol: "SPY", change_pct: 0.4, members: [] }], movers: [] };
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: [], count: 0, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: { ORCL: { points: [250, 248, 246], change_pct: -1.2 } } },
  "/copilot/desk/moving": MOVING,
  "/copilot/desk/feed": FEED,
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
  "/copilot/scanner": { state: "off", rows: [] },
  "/copilot/exposure": { line: null },
};

async function open(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  for (const [path, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/*/chart*", route => route.fulfill({ status: 503, json: { detail: "No chart in this test." } }));
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.goto("/copilot-lab");
  await expect(page.getByTestId("desk-book")).toBeVisible();
}

test("quiet top: What's moving starts folded and remembers being opened; no account line while off; no $0 realized", async ({ page }) => {
  await open(page);
  const toggle = page.getByTestId("desk-moving-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("desk-moving-row")).toHaveCount(0);
  // The top bar: the open positions' P&L, nothing for a day with no trade closed, and no account line with the feed off.
  await expect(page.getByTestId("desk-pnl")).toHaveText("Open −$120");
  await expect(page.getByTestId("desk-accounts")).toHaveCount(0);
  await toggle.click();
  await expect(page.getByTestId("desk-moving-group")).toHaveText("SPY▲+0.4%");
  await page.reload();
  await expect(page.getByTestId("desk-moving-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("desk-moving-group")).toHaveText("SPY▲+0.4%");
});

test("the Feed: four groups, Ideas opens on Radar, and the tab counts only his own new items", async ({ page }) => {
  await open(page);
  const centre = page.getByRole("region", { name: "Chart and tools" });
  await expect(page.getByTestId("feed-new")).toHaveText("1 new"); // the ORCL headline; Radar and the Fed line never count
  await page.getByRole("tab", { name: "Feed" }).click();
  const feed = page.getByTestId("desk-feed");
  const show = feed.getByRole("group", { name: "Show" }).getByRole("button");
  await expect(show).toHaveText(["Mine", "Ideas", "Market", "All"]);
  await expect(show.nth(0)).toHaveAttribute("aria-pressed", "true");
  const sources = feed.getByTestId("feed-item").getByTestId("feed-source");
  await expect(feed.getByTestId("feed-item")).toHaveText([/Oracle books a cloud deal/]);
  await show.nth(1).click();
  // Ideas: Radar, then Unusual options; Scanner only while the scanner is on.
  await expect(feed.getByRole("group", { name: "Ideas" }).getByRole("button")).toHaveText(["Radar", "Unusual options"]);
  await expect(sources).toHaveText(["Radar"]);
  await feed.getByRole("group", { name: "Ideas" }).getByRole("button", { name: "Unusual options" }).click();
  await expect(feed.getByTestId("feed-unusual")).toBeVisible();
  await show.nth(2).click();
  await expect(feed.getByTestId("feed-item")).toHaveText([/Yields climb before the Fed minutes/]);
  await expect(feed.getByRole("group", { name: "Market" })).toHaveCount(0); // no chatter: no second row
  await show.nth(3).click();
  await expect(sources).toHaveText(["News", "Radar", "News"]);
});

test("a phone: the book comes before What's moving, and the centre waits behind the switch", async ({ page }) => {
  await open(page, 390);
  const top = async (id: string) => (await page.getByTestId(id).boundingBox())!.y;
  const book = await top("desk-book");
  const moving = await top("desk-moving");
  expect(book).toBeLessThan(moving);
  // The ticker's tools are the second view: not on the Book, and there once its button is tapped.
  const centre = page.getByRole("region", { name: "Chart and tools" });
  await expect(centre).toBeHidden();
  await page.getByTestId("desk-view-ticker").click();
  await expect(centre).toBeVisible();
  await expect(page.getByTestId("desk-moving")).toBeHidden();
});
