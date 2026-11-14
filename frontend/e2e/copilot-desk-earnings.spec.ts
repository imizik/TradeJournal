import { expect, test, type Page } from "@playwright/test";

// Known events where the owner looks (docs/copilot-lab.md § The desk): a short earnings tag on the book's and the Watching
// list's rows (grey within 7 trading days, amber when a held option expires on or after the report), and on the chart the
// next and last earnings as chips on the date axis with the implied move on hover, macro days only on index ETFs. Every
// lab route is stubbed in the browser; every date and price is invented.
const ON = {
  enabled: true, backend: "fake", evidence: "live", model: "fake-scripted", effort: "medium", fallbacks: false, key_configured: false,
  plan_configured: false, tools: [], capabilities: { copilot_alerts: true },
  limits: { max_rounds: 4, max_tool_calls: 8, tool_timeout_s: 10, turn_timeout_s: 120, turn_budget_usd: 0.25 },
};
// Friday November 13, 2026, 11:00 in New York.
const NOW = new Date("2026-11-13T16:00:00Z");
const NOW_S = NOW.getTime() / 1000;
const ORCL = "99999999-9999-4999-8999-999999999999";
const IREN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const row = (fields: Record<string, unknown>) => ({
  symbol: null, instrument: null, value: null, meter: null, investigation_id: null, trade_id: null, radar_event_id: null, path: null,
  changed_at: null, ...fields,
});
const position = (symbol: string, id: string, hidden = false) => row({ key: `trade:${id}`, group: "watch", symbol, title: `${symbol} 11/20/26 50C`,
  instrument: "11/20/26 50C", trade_id: id, value: { text: "−$120.00", tone: "loss" }, status: { text: "No plan yet", tone: "muted" },
  path: `/trades/${id}`, hidden, book: { usd: -120, pct: -12, expiry: "2026-11-20", days_held: 1, track: null, state: "no_plan", planned: false, stop_pct: null } });
const THREADS = {
  as_of: "2026-11-13T16:00:00Z", quotes_at: null, quote_issue: null, day: { phase: "regular", need_you: 0, streak: null },
  sections: { positions: "ok" }, plans: [], robinhood: { state: "off" },
  threads: [position("ORCL", ORCL), position("IREN", IREN, true)],
};
const SESSION = {
  as_of: "2026-11-13T16:00:00Z", now: NOW_S, day: "2026-11-13", phase: "regular", open: NOW_S - 5400, close: NOW_S + 18000,
  events: [], time_stops: [], pings: null, prep: null, indices: [], quote_issue: null, realized_today: 0, sections: {},
};
// ORCL reports Thursday, inside the held Nov 20 contract's life: amber. NVDA (watched) reports Wednesday: grey.
const EVENTS = { state: "ok", today: "2026-11-13", window: 7, loading: false, note: "Time of day not published.", rows: {
  ORCL: { symbol: "ORCL", date: "2026-11-19", status: "confirmed", trading_days: 4, label: "ER Thu", tone: "amber", through: ["2026-11-20"] },
  NVDA: { symbol: "NVDA", date: "2026-11-18", status: "confirmed", trading_days: 3, label: "ER Wed", tone: "grey", through: [] },
} };

/** A chart read of 60 candles ending now; ``events`` as the backend sends them. */
function chartRead(symbol: string, timeframe: string, events: object) {
  const step = timeframe === "1D" ? 86400 : timeframe === "15m" ? 900 : 120;
  const last = NOW_S - (NOW_S % step);
  const bars = Array.from({ length: 60 }, (_, i) => {
    const open = 94 + Math.sin(i / 5);
    return { time: last - (59 - i) * step, open, high: open + 0.4, low: open - 0.4, close: open + 0.2, volume: 1000, extended: false };
  });
  return { symbol, timeframe, step, as_of: NOW_S, live: false, state: "ok", reason: null, bars, studies: {}, reference: [],
    reading: { last: 94.2, at: last, daily: false, prev_close: 93, vwap: null, vwap_at: null, rvol: null },
    levels: [], alerts: [], marks: [], time_stop: null, events };
}
const NBIS_EVENTS = { note: "Time of day not published.", macro: [], earnings: {
  next: { date: "2026-11-19", status: "confirmed", label: "Q3 FY2026", implied: { expiration: "2026-11-20", move: 4.9, percent: 0.052 } },
  last: { date: "2026-10-15", label: "Q2 FY2026" } } };
const QQQ_EVENTS = { note: "Time of day not published.", earnings: null, macro: [
  { date: "2026-10-28", time: "14:00", kind: "fomc", name: "FOMC statement" },
  { date: "2026-11-18", time: "08:30", kind: "cpi", name: "CPI (Oct 2026)" }] };

async function open(page: Page, path = "/copilot-lab", { width = 1440, height = 900, threads = THREADS } = {}) {
  const asked: URL[] = [];
  await page.setViewportSize({ width, height });
  await page.clock.install({ time: NOW });
  await page.route("**/copilot/status", route => route.fulfill({ json: ON }));
  await page.route("**/copilot/desk/threads", route => route.fulfill({ json: threads }));
  await page.route("**/copilot/desk/session", route => route.fulfill({ json: SESSION }));
  await page.route("**/copilot/desk/feed", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", now: NOW_S, day: "2026-11-13", total: 0, sources: {}, unavailable: [], items: [] } }));
  await page.route("**/copilot/desk/sparks?*", route => route.fulfill({ json: { as_of: "2026-11-13T16:00:00Z", spy_change_pct: 0, rows: {} } }));
  await page.route("**/copilot/desk/watching", route => route.fulfill({ json: {
    state: "ok", symbols: ["NVDA", "AMD", "IREN"], count: 3, max: 30, imported_at: null, robinhood: "off", levels: {}, setups: {} } }));
  await page.route("**/copilot/desk/events?*", route => { asked.push(new URL(route.request().url())); return route.fulfill({ json: EVENTS }); });
  await page.route("**/copilot/investigations?*", route => route.fulfill({ json: { investigations: [] } }));
  await page.route("**/copilot/chat", route => route.abort());
  await page.route(/\/copilot\/desk\/(symbol(:|%3A)[A-Z]+|market)\/(chart|timeline)/, route => {
    const url = new URL(route.request().url());
    if (!url.pathname.endsWith("/chart")) return route.fulfill({ json: { state: "ok", symbol: null, count: 0, unavailable: [], recent_days: 7, rows: [] } });
    const market = url.pathname.includes("/market/");
    const timeframe = url.searchParams.get("timeframe") ?? "2m";
    return route.fulfill({ json: market ? chartRead("QQQ", timeframe, QQQ_EVENTS) : chartRead("NBIS", timeframe, NBIS_EVENTS) });
  });
  await page.goto(path);
  await expect(page.getByTestId("desk-book")).toBeVisible();
  return asked;
}

test("book and Watching rows: amber when the report is inside a held contract, grey within a week, none otherwise", async ({ page }) => {
  const asked = await open(page);
  const book = page.getByTestId("desk-book");
  const orcl = book.getByRole("button", { name: /^ORCL / }).getByTestId("earnings-tag");
  await expect(orcl).toHaveText("ER Thu");
  await expect(orcl).toHaveAttribute("data-tone", "amber");
  await expect(orcl).toHaveAttribute("title", /Earnings Thu Nov 19 \(confirmed\), 4 trading days away\. Your Nov 20 contract expires after it\. Time of day not published\./);
  const watching = page.getByTestId("desk-watching");
  const nvda = watching.getByTestId("watch-row").filter({ hasText: "NVDA" }).getByTestId("earnings-tag");
  await expect(nvda).toHaveText("ER Wed");
  await expect(nvda).toHaveAttribute("data-tone", "grey");
  await expect(watching.getByTestId("watch-row").filter({ hasText: "AMD" }).getByTestId("earnings-tag")).toHaveCount(0);
  // One read for the book and the list together, naming the held expiry; the hidden ticker is never asked about.
  const last = asked.at(-1)!;
  expect(last.searchParams.get("symbols")!.split(",").sort()).toEqual(["AMD", "NVDA", "ORCL"]);
  expect(last.searchParams.get("held")).toBe("ORCL:2026-11-20");
  // The held contract's header says the report is inside its life, once.
  await book.getByRole("button", { name: /^ORCL / }).click();
  await expect(page.getByTestId("position-earnings")).toHaveText("Earnings Thu, before your Nov 20 expiry · time of day not published");
  await page.screenshot({ path: test.info().outputPath("book-tags.png") });
});

test("chart: the next earnings sits on the date axis with the implied move on hover; macro days only on QQQ", async ({ page }) => {
  await open(page, "/copilot-lab?symbol=NBIS");
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await expect(pane.getByTestId("desk-chart-earnings")).toHaveText("Earnings Thu · ±5.2% implied");
  // 2m: today's candles only, so next Thursday is past the right edge, pinned with an arrow; the last report is off the left.
  const next = pane.locator('[data-testid="desk-chart-event"][data-kind="earnings"]');
  await expect(next).toHaveText("ER Thu →");
  await expect(next).toHaveAttribute("data-pinned", "true");
  await expect(pane.locator('[data-testid="desk-chart-event"][data-kind="last"]')).toHaveCount(0);
  await next.hover();
  const tip = pane.getByTestId("desk-chart-event-tip");
  await expect(tip).toContainText("Earnings Thu, Nov 19 · Q3 FY2026");
  await expect(tip).toContainText("Time of day not published.");
  await expect(tip).toContainText("Options price a ±5.2% ($4.90) move by the Nov 20 expiry.");
  await page.screenshot({ path: test.info().outputPath("chart-2m.png") });
  // 1D: 60 days back, so the last report sits on its candle and the next one just past the last candle.
  await pane.getByRole("button", { name: "1D", exact: true }).click();
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-timeframe", "1D");
  const last = pane.locator('[data-testid="desk-chart-event"][data-kind="last"]');
  await expect(last).toHaveText("ER");
  await expect(last).toHaveAttribute("data-pinned", "false");
  await expect(pane.locator('[data-testid="desk-chart-event"][data-kind="earnings"]')).toHaveAttribute("data-pinned", "false");
  await expect(pane.locator('[data-testid="desk-chart-event"][data-kind="macro"]')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("chart-1d.png") });
});

test("the market chart (QQQ) shows the macro days, faint, and no earnings", async ({ page }) => {
  // No book row: the centre is the market chart.
  await open(page, "/copilot-lab", { threads: { ...THREADS, threads: [] } });
  const pane = page.getByRole("region", { name: "Chart and tools" });
  await expect(pane.getByTestId("desk-chart-canvas")).toHaveAttribute("data-bars", "60");
  await pane.getByRole("button", { name: "1D", exact: true }).click();
  await expect(pane.locator('[data-testid="desk-chart-event"][data-kind="macro"]')).toHaveText(["FOMC", "CPI"]);
  await expect(pane.getByTestId("desk-chart-earnings")).toHaveCount(0);
});
