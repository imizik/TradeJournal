import { expect, test, type Page } from "@playwright/test";

// Where a ping opens (docs/copilot-lab.md § Where a ping opens): each phone ping's tap is a desk link, and the desk
// brings the thing it is about forward at desktop and phone width: a price alert's ticker on the chart with its alert
// line; a Radar single's or a scanner push's card marked in the Feed on Ideas, with its chart; a Radar digest's Ideas ›
// Radar. Every route is stubbed with invented numbers, so nothing reaches the e2e backend.
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
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 1, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [{
    key: `trade:${ORCL}`, group: "watch", symbol: "ORCL", title: "ORCL 11/20/26 250C", instrument: "11/20/26 250C", trade_id: ORCL,
    value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" }, path: `/trades/${ORCL}`, hidden: false,
    meter: null, investigation_id: null, radar_event_id: null, changed_at: null,
    book: { usd: -120, pct: -54.5, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null },
  }],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", phase: "regular",
  open: epoch("2026-11-13T14:30:00Z"), close: epoch("2026-11-13T21:00:00Z"), events: [], time_stops: [], pings: null, prep: null,
  indices: [], quote_issue: null, realized_today: 0, sections: {},
  // One thing needs him: ORCL's give-back alert, not answered yet.
  to_answer: { alerts: { count: 1, rows: [{ id: "a1", trade_id: ORCL, symbol: "ORCL", contract: "ORCL 11/20/26 250C", kind: "giveback",
    at: epoch("2026-11-13T15:51:00Z"), today: true, feedback: null }] }, radar: null },
};
const item = (over: Record<string, unknown>) => ({
  has_time: true, symbol: null, detail: null, publisher: null, url: null, href: null, investigation_id: null, radar_event_id: null,
  setup: null, plan: null, mine: false, upcoming: false, ...over,
});
const FEED = {
  as_of: "2026-11-13T16:00:00Z", now: epoch("2026-11-13T16:00:00Z"), day: "2026-11-13", total: 4, sources: {}, unavailable: [],
  items: [
    item({ id: "tv:nvda", source: "TradingView", at: epoch("2026-11-13T15:46:00Z"), symbol: "NVDA", text: "ORB break long · 5m at 199.12", mine: true }),
    item({ id: "radar:mu", source: "Radar", at: epoch("2026-11-13T15:10:00Z"), symbol: "MU", text: "MU up 4.1% while SMH is up 0.6%", href: "/radar?event=rd-mu",
      radar_event_id: "rd-mu" }),
    item({ id: "radar:amd", source: "Radar", at: epoch("2026-11-13T15:05:00Z"), symbol: "AMD", text: "AMD down 3.2% while SMH is up 0.6%", href: "/radar?event=rd-amd",
      radar_event_id: "rd-amd" }),
    item({ id: "news:fed", source: "News", at: epoch("2026-11-13T15:00:00Z"), text: "Yields climb before the Fed minutes", publisher: "Reuters" }),
  ],
};
const iso = (at: number) => new Date(at * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const scan = (id: string, symbol: string, trigger: number, stop: number, target: number) => ({
  id, symbol, setup: "orb", direction: "long", words: "Opening-range break (long)", bar_end: iso(epoch("2026-11-13T15:00:00Z")), trigger, stop, target,
  vwap: null, range_high: null, range_low: null, flags: [], contract_line: "11-21 95C · Δ0.46", status: "open", pnl: null, exit_reason: null, new: true, radar: null,
});
const SCANNER = { state: "ok", day: "2026-11-13", simulated: true, message: null,
  monitoring: { state: "fresh", checked_at: "2026-11-13T16:00:00Z", last_judged_bar_end: "2026-11-13T15:58:00Z", symbols_judged: 12, symbols_selected: 12 },
  rows: [scan("c-crwv", "CRWV", 118.4, 116.9, 121.6), scan("c-nbis", "NBIS", 94.12, 93.18, 96)] };
const READS: Record<string, unknown> = {
  "/copilot/desk/threads": THREADS,
  "/copilot/desk/session": SESSION,
  "/copilot/desk/watching": { state: "ok", symbols: ["NVDA"], count: 1, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} },
  "/copilot/desk/sparks": { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0.4, rows: { ORCL: { points: [250, 248, 246], change_pct: -1.2 }, NVDA: { points: [198, 199], change_pct: 0.7, last: 199 } } },
  "/copilot/desk/moving": { state: "ok", mode: "live", session: "2026-11-13", as_of: "2026-11-13T16:00:00Z", reason: null, groups: [], movers: [] },
  "/copilot/desk/feed": FEED,
  "/copilot/investigations": { investigations: [] },
  "/copilot/tickets": { plans: [] },
  "/copilot/unusual": { state: "ok", rows: [], tickers: [], unread: [], no_history: [], stale: [], rule: "" },
  "/copilot/scanner": SCANNER,
  "/copilot/exposure": { line: null },
};

/** A symbol's chart read: 60 two-minute candles. */
function chart(symbol: string) {
  const last = epoch("2026-11-13T16:00:00Z");
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = (symbol === "CRWV" ? 118 : 200) + Math.sin(i / 5);
    return { time: last - (59 - i) * 120, open, high: open + 0.4, low: open - 0.4, close: open + 0.1, volume: 1000, extended: false };
  });
  return { symbol, timeframe: "2m", step: 120, as_of: last, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: symbol === "CRWV" ? 118 : 200, at: last, daily: false, prev_close: symbol === "CRWV" ? 117 : 199, vwap: null, vwap_at: null, rvol: null }, levels: [], marks: [], time_stop: null,
    alerts: symbol === "NVDA" ? [{ id: "al-1", price: 201.5, text: "Crosses 201.50", label: null, removable: true, condition: "crosses", interval: null, session: "regular" }] : [],
    events: { earnings: null, macro: [], note: null } };
}

async function open(page: Page, link: string, { width, height }: { width: number; height: number }) {
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/api/backend/**", route => route.fulfill({ status: 404, json: { detail: "Not in this test." } }));
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/chat", route => route.abort());
  for (const [path, body] of Object.entries(READS)) await page.route(url => url.pathname.endsWith(path), route => route.fulfill({ json: body }));
  await page.route("**/copilot/desk/*/chart*", route => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2) ?? "");
    return route.fulfill({ json: chart(id.includes(":") ? id.split(":").pop()! : "QQQ") });
  });
  await page.route("**/copilot/desk/minute?*", route => {
    const reads = new URL(route.request().url()).searchParams.getAll("read").map(target => {
      const body = READS[target.split("?")[0]];
      return body ? { status: 200, body } : { status: 404, body: { detail: "Not in this test." } };
    });
    return route.fulfill({ json: { reads } });
  });
  await page.goto(link);
}

const centre = (page: Page) => page.getByRole("region", { name: "Chart and tools" });
const feed = (page: Page) => page.getByTestId("desk-feed");
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

/** The Feed is forward: the side's Feed tab on a desktop, the Feed view on a phone. */
async function feedForward(page: Page, phone: boolean) {
  if (phone) await expect(page.getByTestId("desk-view-feed")).toHaveAttribute("aria-pressed", "true");
  else await expect(page.getByRole("tab", { name: "Feed" })).toHaveAttribute("aria-selected", "true");
  await expect(feed(page)).toBeVisible();
  await expect(feed(page).getByRole("button", { name: "Ideas", exact: true })).toHaveAttribute("aria-pressed", "true");
}

/** The ticker's chart: in the centre on a desktop; on a phone behind the ticker's view, named by its symbol. */
async function chartOn(page: Page, symbol: string, phone: boolean) {
  if (phone) {
    const ticker = page.getByTestId("desk-view-ticker");
    await expect(ticker).toHaveText(symbol);
    await ticker.click();
  }
  await expect(centre(page).getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true");
  await expect(centre(page).getByTestId("desk-chart").getByText(symbol, { exact: true }).first()).toBeVisible();
}

for (const [name, size] of [["desktop", DESKTOP], ["phone", PHONE]] as const) {
  const phone = name === "phone";

  test(`${name}: a price alert's tap opens its ticker's chart with the alert line`, async ({ page }) => {
    await open(page, "/copilot-lab?symbol=NVDA", size);
    if (phone) await expect(page.getByTestId("desk-view-ticker")).toHaveAttribute("aria-pressed", "true");
    else await expect(centre(page)).toBeVisible();
    if (phone) await page.getByRole("button", { name: "Back to the desk" }).click(); // the copilot's sheet opens over the ticker's view
    await chartOn(page, "NVDA", phone);
    await expect(centre(page).getByTestId("desk-chart-marks")).toContainText("Alert · Crosses 201.50");
  });

  test(`${name}: a Radar single's tap marks its card on Ideas › Radar with its chart`, async ({ page }) => {
    await open(page, "/copilot-lab?symbol=MU&radar=rd-mu&feed=radar%3Ard-mu", size);
    await feedForward(page, phone);
    await expect(feed(page).getByRole("button", { name: "Radar", exact: true })).toHaveAttribute("aria-pressed", "true");
    const items = feed(page).getByTestId("feed-item");
    await expect(items).toHaveCount(2);
    await expect(items.filter({ hasText: "MU up 4.1%" })).toHaveAttribute("data-focused", "true");
    await expect(items.filter({ hasText: "AMD down 3.2%" })).not.toHaveAttribute("data-focused", /.*/);
    await chartOn(page, "MU", phone);
  });

  test(`${name}: a scanner push's tap marks its row on Ideas › Scanner with its chart and levels`, async ({ page }) => {
    await open(page, "/copilot-lab?symbol=CRWV&feed=scanner%3Ac-crwv", size);
    await feedForward(page, phone);
    await expect(feed(page).getByRole("button", { name: "Scanner", exact: true })).toHaveAttribute("aria-pressed", "true");
    const rows = feed(page).getByTestId("scanner-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.filter({ hasText: "CRWV" })).toHaveAttribute("data-focused", "true");
    await expect(rows.filter({ hasText: "NBIS" })).not.toHaveAttribute("data-focused", /.*/);
    await chartOn(page, "CRWV", phone);
    await expect(centre(page).getByTestId("desk-chart-guides")).toHaveText("Scan trigger 118.40 · Scan stop 116.90 · Scan target 121.60");
  });

  test(`${name}: a Radar digest's tap opens the Feed on Ideas › Radar`, async ({ page }) => {
    await open(page, "/copilot-lab?feed=radar", size);
    await feedForward(page, phone);
    await expect(feed(page).getByRole("button", { name: "Radar", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(feed(page).getByTestId("feed-item")).toHaveCount(2);
    await expect(feed(page).locator("[data-focused]")).toHaveCount(0);
  });
}

test("between 768 and 1180 px a Radar single opens the Feed's drawer on its card; closing it leaves the Feed closed", async ({ page }) => {
  await open(page, "/copilot-lab?symbol=MU&radar=rd-mu&feed=radar%3Ard-mu", { width: 1000, height: 800 });
  const drawer = page.getByTestId("desk-feed-pane");
  await expect(drawer).toBeVisible();
  await expect(feed(page).getByTestId("feed-item").filter({ hasText: "MU up 4.1%" })).toHaveAttribute("data-focused", "true");
  await page.getByRole("button", { name: "Close the Feed" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator("[data-feed][data-view]")).toHaveAttribute("data-view", "ticker"); // not left on the phone's Feed view
  await expect(centre(page).getByTestId("desk-chart").getByText("MU", { exact: true }).first()).toBeVisible();
});

test("a Radar group move (no ticker) marks its card alone", async ({ page }) => {
  await open(page, "/copilot-lab?feed=radar%3Ard-amd", DESKTOP);
  await feedForward(page, false);
  await expect(feed(page).getByTestId("feed-item").filter({ hasText: "AMD down 3.2%" })).toHaveAttribute("data-focused", "true");
  await expect(page.locator("[data-feed][data-view]")).toHaveAttribute("data-view", "book");
});
