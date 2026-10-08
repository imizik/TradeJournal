import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { DEFAULT_SETTINGS, STORAGE_KEY } from "../lib/charts";
import type { FinancialQuarter, SymbolFinancials } from "../lib/symbolInfo";
import type { Earnings, NewsArticle, NewsSource, SymbolEvents, ReactionSummary, SymbolForecast, SymbolNews, SymbolOverview } from "../lib/symbolInfo";

// Only market candles/quotes/settings are stubbed. Journal values below come
// through the real private endpoint from scripts/seed_dev_data.py.
test.beforeEach(async ({ context, page }) => {
  await context.addInitScript(({ key, settings }) => {
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(settings));
  }, { key: STORAGE_KEY, settings: { ...DEFAULT_SETTINGS, symbol: "NVDA", watchlist: ["NVDA", "AAPL", "TSLA", "SPY", "AMD"] } });
  await fakeChartSettings(context, { revision: 1, data: { symbol: "NVDA", watchlist: ["NVDA", "AAPL", "TSLA", "SPY", "AMD"] } });
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const symbol = query.get("symbol");
    const now = Math.floor(Date.now() / 1000);
    const bars = Array.from({ length: 10 }, (_, i) => ({ time: 1789392600 + i * 300, end_time: 1789392900 + i * 300, open: 100, high: 102, low: 99, close: 101, volume: 1000, extended: false }));
    await route.fulfill({ json: { symbol, session: "extended", provider: "Fixture", delayed: false, refresh_seconds: 15,
      checked_at: now, fetched_at: { intraday: now, quotes: now }, intraday_as_of: now, issues: [], quotes: [{ symbol, name: `${symbol} company`, instrument_type: symbol === "SPY" ? "etf" : "stock", last: 189.12, change: 2.2,
        change_percentage: 1.18, volume: 112700000, previous_close: 186.92, trade_time: now, day_low: 185, day_high: 191, week_52_low: 86, week_52_high: 195 }], fills: [], fills_truncated: false,
      panels: Object.fromEntries((query.get("intervals") ?? "5m").split(",").map((interval) => [interval, { bars, markers: [] }])), extras: {} } });
  });
  await page.route("**/api/backend/charts/stream?**", (route) => route.fulfill({ status: 503, body: "Fixture has no stream" }));
});

const OVERVIEW_READ = Date.parse("2026-10-05T13:40:00Z") / 1000;
function overview(symbol: string): SymbolOverview {
  const block = { state: (symbol === "SPY" ? "none" : "ready") as "none" | "ready", source: "Tradier company fundamentals", fetched_at: OVERVIEW_READ, message: null };
  return { symbol, state: symbol === "SPY" ? "none" : "ready", datasets: {
    company: { ...block, name: symbol === "SPY" ? null : "NVIDIA Corporation", sector: symbol === "SPY" ? null : "Technology", employees: symbol === "SPY" ? null : 36000,
      ipo_date: symbol === "SPY" ? null : "1999-01-22", description: symbol === "SPY" ? null : "GPU designer" },
    ratios: { ...block, pe: symbol === "SPY" ? null : 52.5, price_to_sales: symbol === "SPY" ? null : 25, price_to_book: symbol === "SPY" ? null : 40,
      ev_to_ebitda: symbol === "SPY" ? null : 48, dividend_yield: symbol === "SPY" ? null : 0.0003, beta_60_month: symbol === "SPY" ? null : 1.8 },
    statistics: { ...block, market_cap: symbol === "SPY" ? null : 4500000000000, enterprise_value: symbol === "SPY" ? null : 4490000000000,
      shares_outstanding: symbol === "SPY" ? null : 24500000000, institutional_ownership: symbol === "SPY" ? null : 0.68,
      average_volume_30_day: symbol === "SPY" ? null : 112700000 },
  } };
}

test("Overview combines the chart's existing quote with cached company fundamentals", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/api/backend/charts/symbol/*/overview", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    reads.push(symbol);
    await route.fulfill({ json: overview(symbol) });
  });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(info.getByRole("region", { name: "Price and range" })).toContainText("$189.12");
  await expect(info.getByRole("region", { name: "Price and range" })).toContainText("$185.00 – $191.00");
  await expect(info.getByRole("region", { name: "Company", exact: true })).toContainText("Technology");
  await expect(info.getByRole("region", { name: "Key statistics" })).toContainText("$4.5T");
  await expect(info.getByRole("region", { name: "Valuation" })).toContainText("EV/EBITDA");
  await expect(info.getByText("52.5", { exact: true }).locator("..")).toHaveAttribute("title", /Tradier company fundamentals · read/);
  expect(reads).toEqual(["NVDA"]);
  await choose(page, "SPY");
  await expect(info.getByRole("region", { name: "Company", exact: true })).toContainText("Not available for ETFs or funds.");
  expect(reads).toEqual(["NVDA", "SPY"]);
});

const panel = (page: Page) => page.getByRole("region", { name: "Symbol info", exact: true });
const choose = (page: Page, symbol: string) => page.getByRole("button", { name: `Chart ${symbol}`, exact: true }).click();

test("You renders seeded completed results, account-separated open trades and an empty symbol", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.goto("/charts");
  const info = panel(page);
  await expect(info.getByRole("tab", { name: "You", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(info.locator("dl")).toContainText("$1,300.00");
  await expect(info.locator("dl")).toContainText("100.0%");
  await expect(info.locator("dl")).toContainText("7.2 d");
  await expect(info).toContainText("Journal · all accounts");
  const tradeLink = info.getByRole("link").first();
  await expect(tradeLink).toHaveAttribute("href", /\/trades\/[0-9a-f-]+$/);
  await expect(info).toContainText("No open positions");
  expect(reads).toHaveLength(1);
  // Dense journal content scrolls inside the dock, preserving C7.3's shell.
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("symbol-info-desktop.png"), fullPage: true });
  await choose(page, "AAPL");
  await expect(info).toContainText("Open positions · 2 trades");
  await expect(info).toContainText("8267");
  await expect(info).toContainText("1113");
  await expect(info.locator("dl")).not.toContainText("$400.00"); // partial exit excluded from completed P&L
  expect(reads).toHaveLength(2);
  await choose(page, "TSLA");
  await expect(info.locator("dl")).toContainText("-$300.00");
  await expect(info.locator("dl")).toContainText("0.0%");
  await choose(page, "SPY");
  await expect(info).toContainText("No trades on this symbol");
  expect(reads).toHaveLength(4);
});

test("Overview persists per device and rapid symbol steps fetch only the settled symbol", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.route("**/api/backend/charts/symbol/*/overview", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    await route.fulfill({ json: overview(symbol) });
  });
  await page.goto("/charts");
  const info = panel(page);
  await expect(info.locator("dl")).toContainText("$1,300.00");
  await info.getByRole("tab", { name: "Overview", exact: true }).click();
  await expect(info.getByRole("region", { name: "Company", exact: true })).toContainText("Technology");
  await page.reload();
  await expect(info.getByRole("tab", { name: "Overview", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(info.getByRole("region", { name: "Company", exact: true })).toContainText("Technology");
  expect(reads).toHaveLength(3);
  // Anchor both operations to one fixed time. Pausing at wall-clock "now"
  // races the browser advancing while the command travels to it on CI.
  const clockStart = new Date("2026-10-02T16:00:00Z");
  await page.clock.install({ time: clockStart });
  await page.clock.pauseAt(new Date(clockStart.getTime() + 60_000));
  await info.getByRole("tab", { name: "You", exact: true }).click();
  await choose(page, "SPY");
  await page.clock.runFor(100);
  await choose(page, "AMD");
  await page.clock.runFor(301);
  await expect(info).toContainText("No trades on this symbol");
  expect(reads).toHaveLength(4);
  expect(reads[3]).toContain("/AMD/you");
});

test("a failed journal request retries without replacing charts", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/backend/charts/symbol/NVDA/you", async (route) => {
    attempts += 1;
    if (attempts === 1) await route.fulfill({ status: 503, body: "Unavailable" });
    else await route.continue();
  });
  await page.goto("/charts");
  await expect(panel(page).getByRole("alert")).toContainText("Journal unavailable");
  await panel(page).getByRole("button", { name: "Retry journal" }).click();
  await expect(panel(page).locator("dl")).toContainText("$1,300.00");
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  expect(attempts).toBe(2);
});

test("a late result from the previous symbol cannot overwrite the current journal", async ({ page }) => {
  let started = false;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/backend/charts/symbol/NVDA/you", async (route) => {
    started = true;
    await pending;
    await route.fulfill({ json: { symbol: "NVDA", total_trades: 0, source: "OLD RESULT", as_of: new Date().toISOString() } }).catch(() => {});
  });
  await page.goto("/charts");
  await expect.poll(() => started).toBe(true);
  await choose(page, "AAPL");
  await expect(panel(page)).toContainText("Open positions · 2 trades");
  release();
  await expect(panel(page)).not.toContainText("OLD RESULT");
  await expect(panel(page)).toContainText("Open positions · 2 trades");
});

test("390px opens collapsed inside the watchlist sheet and follows its visibility in immersive mode", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\//.test(request.url())) reads.push(request.url()); });
  await page.goto("/charts");
  const info = panel(page);
  await expect(info).toHaveCount(0);
  expect(reads).toHaveLength(0);
  await expect(page.getByTestId("canvas-main").locator("canvas").first()).toBeVisible();
  const canvasHeight = (await page.getByTestId("canvas-main").boundingBox())!.height;
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Watchlist", exact: true });
  await expect(sheet).toBeVisible();
  const disclosure = info.getByRole("button", { name: "NVDA symbol info" });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  expect(reads).toHaveLength(0);
  await disclosure.click();
  await expect(info.locator("dl")).toContainText("$1,300.00");
  expect((await page.getByTestId("canvas-main").boundingBox())!.height).toBe(canvasHeight);
  await expect(info.getByRole("tab", { name: "Overview", exact: true })).toBeVisible();
  for (const target of await info.getByRole("button").all()) {
    expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("symbol-info-phone.png"), fullPage: true });
  await sheet.getByRole("button", { name: "Close watchlist" }).click();
  await expect(info).toHaveCount(0);
  await page.getByRole("button", { name: "Enter full-screen charts" }).click();
  await expect(info).toHaveCount(0);
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(info).toBeVisible();
  await expect(info.getByRole("button", { name: "NVDA symbol info" })).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("dialog", { name: "Watchlist", exact: true }).getByRole("button", { name: "Close watchlist" }).click();
  await page.getByRole("button", { name: "Exit full-screen charts" }).click();
});

// ---- Events (T1.4): Tradier's dates, stubbed; the backend tests normalize the recorded responses ----

const READ = Date.parse("2026-10-05T13:40:00Z") / 1000;
const block = { source: "Tradier corporate calendar", fetched_at: READ, message: null };
const NVDA_LABELS = ["Q2 FY2027", "Q1 FY2027", "Q4 FY2026", "Q3 FY2026", "Q2 FY2026", "Q1 FY2026", "Q4 FY2025", "Q3 FY2025"];
const NVDA_REPORTS = ["2026-08-26", "2026-05-20", "2026-02-25", "2025-11-19", "2025-08-27", "2025-05-28", "2025-02-26", "2024-11-20"];
function events(symbol: string): SymbolEvents {
  const none = { state: "none" as const, source: "Tradier dividends", fetched_at: READ, message: null };
  const earnings: Earnings = symbol === "NVDA"
    ? { ...block, state: "ready", next: { date: "2026-11-19", status: "estimated", label: "Q3 FY2027" },
      reports: NVDA_REPORTS.map((date, i) => ({ date, label: NVDA_LABELS[i] })) }
    : symbol === "AAPL" ? { ...block, state: "ready", next: { date: "2026-10-30", status: "confirmed", label: "Q4 FY2026" }, reports: [{ date: "2026-07-30", label: "Q3 FY2026" }] }
    : symbol === "AMD" ? { ...block, state: "unavailable", fetched_at: null, message: "Tradier could not read the corporate calendar (503).", next: null, reports: [] }
    : symbol === "TSLA" ? { ...block, state: "ready", next: null, reports: [{ date: "2026-07-22", label: "Q2 FY2026" }] }
    : { ...block, state: "none", next: null, reports: [] };
  const dividend = (ex_date: string, amount: number, pay_date: string) => ({ ex_date, amount, currency: "USD", pay_date, record_date: ex_date, declared: null, frequency: 4, type: "CD" });
  return { symbol, today: "2026-10-05", time_zone: "America/New_York",
    earnings: { ...earnings, time_note: "Time of day not published. Tradier's calendar has dates only, so before the open or after the close is unknown." },
    dividends: symbol === "SPY" ? { ...none, state: "ready", next: null, last: dividend("2026-09-18", 1.888834, "2026-10-30") }
      : symbol === "NVDA" ? { ...none, state: "ready", next: dividend("2026-12-03", 0.25, "2026-12-26"), last: dividend("2026-09-10", 0.25, "2026-10-01") }
      : { ...none, next: null, last: null },
    splits: { ...none, source: "Tradier corporate actions", state: symbol === "SPY" ? "none" : "ready",
      rows: symbol === "AAPL" ? [{ ex_date: "2026-05-08", from: 1, to: 5, label: "5-for-1" }] : [] } };
}

test("Events shows the next report with its status, the last eight reports, dividends and splits, and an ETF's missing calendar", async ({ page }) => {
  const reads: string[] = [];
  page.on("request", (request) => { if (/\/charts\/symbol\/[^/]+\/events/.test(request.url())) reads.push(request.url()); });
  await page.route("**/api/backend/charts/symbol/*/events", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    await route.fulfill({ json: events(symbol) });
  });
  // New York's 2026-10-05, so "in N days" is fixed.
  await page.clock.install({ time: new Date("2026-10-05T14:00:00Z") });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "Events", exact: true }).click();
  const next = info.getByRole("region", { name: "Next earnings" });
  await expect(next).toContainText("Thu, Nov 19, 2026");
  await expect(next.getByText("Estimated", { exact: true })).toHaveAttribute("title", /Tradier's estimate; the company has not announced this date/);
  await expect(next).toContainText("in 45 days · Q3 FY2027");
  await expect(next.getByText("Time of day not published")).toHaveAttribute("title", /dates only/);
  await expect(next.getByRole("listitem")).toHaveCount(8);
  await expect(next.getByRole("listitem").first()).toContainText("Wed, Aug 26, 2026");
  await expect(next).toContainText("Tradier corporate calendar · read Oct 5, 9:40 AM ET");
  const dividends = info.getByRole("region", { name: "Dividends" });
  await expect(dividends).toContainText("Next ex-dividend");
  await expect(dividends).toContainText("Thu, Dec 3, 2026 · $0.25 · pays Sat, Dec 26, 2026");
  await expect(info.getByRole("region", { name: "Splits · last two years" })).toContainText("No splits in the last two years");
  expect(reads).toHaveLength(1);
  // Dense content scrolls inside the dock; the page itself does not grow.
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("symbol-info-events.png"), fullPage: true });

  await choose(page, "AAPL");
  await expect(next).toContainText("Fri, Oct 30, 2026");
  await expect(next.getByText("Confirmed", { exact: true })).toBeVisible();
  await expect(next).toContainText("in 25 days · Q4 FY2026");
  await expect(info.getByRole("region", { name: "Splits · last two years" })).toContainText("5-for-1");
  await expect(dividends).toContainText(`No cash dividends on record for AAPL.`);
  // A past report but no upcoming date: nothing is guessed.
  await choose(page, "TSLA");
  await expect(next).toContainText("Not announced. Nothing is shown until Tradier lists a date.");
  await expect(next).toContainText("Wed, Jul 22, 2026");
  await choose(page, "SPY");
  await expect(next).toContainText("Tradier lists no earnings for SPY. ETFs, funds and indices do not report them.");
  await expect(dividends).toContainText("Last ex-dividend");
  await expect(dividends).toContainText("$1.888834");
  await expect(dividends).toContainText("None announced");
  // A failed calendar degrades only its own block.
  await choose(page, "AMD");
  await expect(next).toContainText("Tradier could not read the corporate calendar (503).");
  await expect(next).toContainText("not read yet");
  await expect(info.getByRole("region", { name: "Splits · last two years" })).toContainText("No splits in the last two years");
  expect(reads.map((url) => url.split("/").at(-2))).toEqual(["NVDA", "AAPL", "TSLA", "SPY", "AMD"]);
});

test("a failed events request retries", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/backend/charts/symbol/NVDA/events", async (route) => {
    attempts += 1;
    await route.fulfill(attempts === 1 ? { status: 503, body: "Unavailable" } : { json: events("NVDA") });
  });
  await page.goto("/charts");
  await panel(page).getByRole("tab", { name: "Events", exact: true }).click();
  await expect(panel(page).getByRole("alert")).toContainText("Events unavailable. Try again.");
  await panel(page).getByRole("button", { name: "Retry events" }).click();
  await expect(panel(page).getByRole("region", { name: "Next earnings" })).toContainText("Q3 FY2027");
  expect(attempts).toBe(2);
});

// ---- Forecast (T2.1): the implied move from stubbed chains; the backend tests choose the straddle and refuse wide markets ----

const QUOTED = Date.parse("2026-10-05T14:28:00Z") / 1000;
const REACTIONS: ReactionSummary = { state: "ready", message: null, source: "Tradier daily history", fetched_at: QUOTED, earnings_fetched_at: QUOTED,
      earnings_stale: false, earnings_message: null, stale: false, price_basis: "split_adjusted", adjustment: {},
      usable_count: 4, average_abs_pct: 6.4, report_range: { from: "2025-10-01", to: "2026-07-30" },
      rows: [{ report_date: "2026-07-30", label: "Q2 FY2026", state: "ready", reason: null, reaction_date: "2026-07-30", gap_pct: 2.3, reaction_pct: -4.1,
        sessions: [{ date: "2026-07-30", previous_date: "2026-07-29", state: "ready", reason: null, gap_pct: 2.3, day_pct: -4.1 },
          { date: "2026-07-31", previous_date: "2026-07-30", state: "ready", reason: null, gap_pct: 1.2, day_pct: 2.5 }] }] };

function forecast(symbol: string, spot: number): SymbolForecast {
  return { symbol, today: "2026-10-05", source: "Tradier option chains", spot, state: "ready", message: null,
    earnings: { date: "2026-11-19", status: "estimated", label: "Q3 FY2027" }, earnings_note: null,
    moves: [
      { tags: ["nearest", "friday"], expiration: "2026-10-09", days: 4, state: "ready", strike: 100, move: 4.4, percent: 4.4 / spot, iv: 0.512,
        quoted_at: QUOTED, fetched_at: QUOTED + 60, call: { symbol: "NVDA261009C00100000", bid: 2.2, ask: 2.3, iv: 0.5 }, put: { symbol: "NVDA261009P00100000", bid: 2.1, ask: 2.2, iv: 0.524 } },
      { tags: ["earnings"], expiration: "2026-11-20", days: 46, state: "too_wide", strike: 100, reason: "The 100 put has no bid.", quoted_at: null,
        call: { symbol: "NVDA261120C00100000", bid: 6.1, ask: 6.4, iv: 0.55 }, put: { symbol: "NVDA261120P00100000", bid: 0, ask: 7.5, iv: null } },
    ] };
}

test("Forecast shows the implied move at the chart's price for the nearest expiration, Friday and after earnings, and refuses a one-sided market", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/api/backend/charts/symbol/*/reactions", (route) => route.fulfill({ json: REACTIONS }));
  await page.route("**/api/backend/charts/symbol/*/forecast**", async (route) => {
    const url = new URL(route.request().url());
    reads.push(url.pathname + url.search);
    await route.fulfill({ json: forecast(decodeURIComponent(url.pathname.split("/").at(-2)!), Number(url.searchParams.get("spot"))) });
  });
  await page.route("**/api/backend/charts/symbol/*/analysts", async (route) => {
    const ready = (source: string, value: unknown) => ({ state: "ready", source, fetched_at: 1, value });
    await route.fulfill({ json: { symbol: "NVDA", state: "ready", providers: {}, blocks: {
      targets: ready("Webull", { mean: 121, median: 120, high: 150, low: 90 }),
      ratings: ready("Yahoo, unofficial", { strong_buy: 10, buy: 48, hold: 2, sell: 1, strong_sell: 0 }),
      estimates: ready("Yahoo, unofficial", [{ period: "current quarter", eps: { avg: 2.47, low: 2.3, high: 2.7, analysts: 44, growth: 0.9 } }]),
      history: ready("Yahoo, unofficial", [{ quarter: "2026-04-30", actual: 1.87, estimate: 1.77, surprise: 0.055, result: "beat" }]),
      actions: { state: "unavailable", source: "Yahoo, unofficial", message: "Yahoo could not be read." },
    } } });
  });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "Forecast", exact: true }).click();
  const analysts = info.getByRole("region", { name: "Analyst consensus" });
  await expect(analysts).toContainText("Median $120.00 · mean $121.00 · +18.8% vs 101.00");
  await expect(analysts).toContainText("Low $90.00 · High $150.00");
  await expect(analysts).toContainText("Strong Buy 10 · Buy 48 · Hold 2 · Sell 1 · Strong Sell 0");
  await expect(analysts).toContainText("EPS $2.47 (2.30–2.70, 44 analysts)");
  await expect(analysts).toContainText("Last 1 reports: beat 5.5%");
  await expect(analysts).toContainText("Yahoo could not be read.");
  const moves = info.getByRole("region", { name: "Implied move" });
  // The chart's latest price (the fixture's candles close at 101) goes with the request.
  await expect(moves).toContainText("Nearest · This Friday");
  expect(reads[0]).toMatch(/\/NVDA\/forecast\?spot=101$/);
  const nearest = moves.getByRole("listitem").first();
  await expect(nearest).toContainText("±$4.40 ±4.4%");
  await expect(nearest).toContainText("100 straddle: call 2.20 × 2.30, put 2.10 × 2.20 · IV 51.2% · quoted 10:28 AM ET");
  const earnings = moves.getByRole("listitem").nth(1);
  await expect(earnings).toContainText("After earnings Thu, Nov 19 (est.)");
  await expect(earnings).toContainText("Market too wide");
  await expect(earnings).toContainText("The 100 put has no bid.");
  await expect(moves.getByText("calculated", { exact: true })).toBeVisible();
  await expect(moves).toContainText("What the options market prices for a move either way by expiry, at 101.00: not a direction or a forecast of one.");
  const reactions = info.getByRole("region", { name: "Past earnings reactions" });
  await expect(reactions).toContainText("inferred");
  await expect(reactions).toContainText("-4.1%");
  await expect(reactions).toContainText("Past inferred average ±6.4% (4 reports).");
  await expect(reactions).toContainText("Reports Wed, Oct 1–Thu, Jul 30.");
  await reactions.getByText("Show both candidate sessions").click();
  await expect(reactions).toContainText("full-day -4.1%");
  await page.screenshot({ path: test.info().outputPath("symbol-info-forecast.png"), fullPage: true });
  await choose(page, "AAPL");
  await expect.poll(() => reads.at(-1)).toMatch(/\/AAPL\/forecast\?spot=101$/);
});

test("phone Forecast keeps inferred reaction details inside the watchlist sheet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/backend/charts/symbol/*/reactions", (route) => route.fulfill({ json: REACTIONS }));
  await page.route("**/api/backend/charts/symbol/*/forecast**", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({ json: forecast(decodeURIComponent(url.pathname.split("/").at(-2)!), Number(url.searchParams.get("spot"))) });
  });
  await page.goto("/charts");
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  const sheet = page.getByRole("dialog", { name: "Watchlist", exact: true });
  const info = panel(page);
  await info.getByRole("button", { name: "NVDA symbol info" }).click();
  await info.getByRole("tab", { name: "Forecast", exact: true }).click();
  const reactions = info.getByRole("region", { name: "Past earnings reactions" });
  await expect(reactions).toContainText("Past inferred average ±6.4% (4 reports).");
  await expect(info.getByText("Show both candidate sessions")).toBeVisible();
  expect(await sheet.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

// ---- News (T1.2): stubbed feed; the backend tests prove the merge, dedupe and caches ----

const NEWS_NOW = Date.parse("2026-10-06T15:00:00Z");
const article = (id: string, headline: string, minutesAgo: number, tickers: string[], extra: Partial<NewsArticle> = {}): NewsArticle => ({
  id, provider: "alpaca_benzinga", publisher: "Benzinga", headline, url: `https://example.com/${id}`,
  published_at: new Date(NEWS_NOW - minutesAgo * 60_000).toISOString(), summary: `Summary of ${headline}`, tickers,
  roundup: tickers.length > 3, sentiment: [], also_in: [], ...extra,
});
const sources = (polygon: NewsSource["state"] = "ok"): NewsSource[] => [
  { provider: "alpaca_benzinga", label: "Alpaca (Benzinga)", state: "ok", fetched_at: NEWS_NOW / 1000, age_seconds: 0, message: null },
  { provider: "polygon", label: "Polygon", state: polygon, fetched_at: NEWS_NOW / 1000 - 900, age_seconds: 900, message: polygon === "ok" ? null : "Polygon refused the read (429)." }];
const newsBody = (articles: NewsArticle[], polygon: NewsSource["state"] = "ok"): SymbolNews => ({
  symbol: "NVDA", as_of: new Date(NEWS_NOW).toISOString(), time_zone: "America/New_York", days: 7, sentiment_note: "Sentiment is supplied by Polygon, not calculated here.",
  sources: sources(polygon), articles });

test("News lists headlines with Focused on, expands summaries, shows provider sentiment and a degraded source", async ({ page }) => {
  const mixed = [
    article("a1", "Nvidia ships a chip", 5, ["NVDA"], { sentiment: [{ ticker: "NVDA", sentiment: "positive", reasoning: "Strong demand." }], provider: "polygon", publisher: "Reuters" }),
    article("a2", "Five stocks moving today", 30, ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]),
    article("a3", "Three tickers stay", 90, ["NVDA", "AMD", "AVGO"]),
  ];
  await page.route("**/api/backend/charts/symbol/NVDA/news", (route) => route.fulfill({ json: newsBody(mixed, "stale") }));
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "News", exact: true }).click();
  await expect(info.getByRole("link", { name: "Nvidia ships a chip" })).toHaveAttribute("href", "https://example.com/a1");
  await expect(info.getByRole("link", { name: "Nvidia ships a chip" })).toHaveAttribute("target", "_blank");
  await expect(info.getByRole("link", { name: "Five stocks moving today" })).toHaveCount(0); // Focused hides the roundup
  await expect(info.getByText("Three tickers stay")).toBeVisible();
  await expect(info.getByText("+2 tickers")).toBeVisible();
  await expect(info.getByText("5 min ago")).toHaveAttribute("title", "Oct 6, 10:55 AM ET");
  await expect(info.getByText("Polygon: positive")).toHaveAttribute("title", /not ours: Strong demand\./);
  await expect(info).toContainText("Polygon refused the read (429).");
  await expect(info).not.toContainText("Summary of Nvidia ships a chip");
  await info.getByRole("button", { name: /Show summary: Nvidia ships a chip/ }).click();
  await expect(info).toContainText("Summary of Nvidia ships a chip");
  await info.getByLabel("Focused").uncheck();
  await expect(info.getByRole("link", { name: "Five stocks moving today" })).toBeVisible();
  await expect(info.getByText("+4 tickers")).toBeVisible();
});

test("News says so when the feed is empty", async ({ page }) => {
  await page.route("**/api/backend/charts/symbol/NVDA/news", (route) => route.fulfill({ json: newsBody([]) }));
  await page.goto("/charts");
  await panel(page).getByRole("tab", { name: "News", exact: true }).click();
  await expect(panel(page)).toContainText("No news in the last 7 days");
});

test("News polls each minute only while the tab is open and the page is visible, and new headlines wait behind a banner", async ({ page }) => {
  const reads: number[] = [];
  const feed = [article("a1", "First story", 10, ["NVDA"])];
  await page.route("**/api/backend/charts/symbol/NVDA/news", (route) => {
    reads.push(reads.length);
    return route.fulfill({ json: newsBody(feed) });
  });
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "News", exact: true }).click();
  await page.clock.runFor(400);
  await expect(info.getByRole("link", { name: "First story" })).toBeVisible();
  expect(reads).toHaveLength(1);
  feed.unshift(article("a2", "Breaking story", 0, ["NVDA"]));
  await page.clock.runFor(60_000);
  await expect(info.getByRole("button", { name: "1 new" })).toBeVisible();
  await expect(info.getByRole("link", { name: "Breaking story" })).toHaveCount(0); // the list did not shift
  expect(reads).toHaveLength(2);
  await info.getByRole("button", { name: "1 new" }).click();
  await expect(info.getByRole("link", { name: "Breaking story" })).toBeVisible();
  // A hidden page does not poll.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.runFor(180_000);
  expect(reads).toHaveLength(2);
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, get: () => false }); });
  await page.clock.runFor(60_000);
  expect(reads).toHaveLength(3);
  // Leaving the tab stops it too.
  await info.getByRole("tab", { name: "You", exact: true }).click();
  await page.clock.runFor(180_000);
  expect(reads).toHaveLength(3);
});

test("News keeps the same 20 rows behind the banner when a poll adds one and the backend drops the oldest", async ({ page }) => {
  const stories = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => article(`s${from + i}`, `Story ${from + i}`, 100 - (from + i), ["NVDA"]));
  let feed = stories(1, 20).reverse(); // newest first
  await page.route("**/api/backend/charts/symbol/NVDA/news", (route) => route.fulfill({ json: newsBody(feed) }));
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "News", exact: true }).click();
  await page.clock.runFor(400);
  const rows = info.locator("ul > li");
  await expect(rows).toHaveCount(20);
  feed = stories(2, 21).reverse(); // one new, the oldest evicted from the capped feed
  await page.clock.runFor(60_000);
  await expect(info.getByRole("button", { name: "1 new" })).toBeVisible();
  await expect(rows).toHaveCount(20);
  await expect(info.getByRole("link", { name: "Story 1", exact: true })).toBeVisible();
  await expect(info.getByRole("link", { name: "Story 21", exact: true })).toHaveCount(0);
  await info.getByRole("button", { name: "1 new" }).click();
  await expect(rows).toHaveCount(20);
  await expect(info.getByRole("link", { name: "Story 21", exact: true })).toBeVisible();
  await expect(info.getByRole("link", { name: "Story 1", exact: true })).toHaveCount(0);
});

// ---- Financials (T3.2): stubbed normalized quarters; the backend tests prove the SEC selection and the margin math ----
function quarter(end: string, label: [number, string], revenue: number | null, rest: Partial<FinancialQuarter> = {}): FinancialQuarter {
  const gap = revenue == null;
  return { start: gap ? null : end, end, gap, fiscal_year: label[0], fiscal_period: label[1], filed: gap ? null : end, revenue, gross_profit: null, operating_income: null,
    net_income: gap ? null : revenue * 0.5, eps_diluted: gap ? null : 1.25, gross_margin: gap ? null : 0.72, operating_margin: gap ? null : 0.6,
    revenue_yoy: null, net_income_yoy: null, eps_diluted_yoy: null, ...rest };
}
function financials(symbol: string): SymbolFinancials {
  const base = { symbol, source: "SEC EDGAR", entity: null, fetched_at: OVERVIEW_READ, stale: false, latest_end: null, quarters: [] as FinancialQuarter[] };
  if (symbol === "AMD") return { ...base, state: "none", message: "No quarterly SEC financials for this issuer." };
  if (symbol === "SPY") return { ...base, state: "none", message: "Not available for ETFs or funds." };
  return { ...base, state: "ready", message: null, entity: "NVIDIA CORP", latest_end: "2026-07-26", quarters: [
    quarter("2024-10-27", [2025, "Q3"], 35082000000, { revenue_yoy: 1.1 }), quarter("2025-01-26", [2025, "Q4"], null),
    quarter("2025-04-27", [2026, "Q1"], 44062000000, { revenue_yoy: 0.69 }), quarter("2025-07-27", [2026, "Q2"], 46743000000, { revenue_yoy: 0.56 }),
    quarter("2025-10-26", [2026, "Q3"], 57006000000, { revenue_yoy: 0.62 }), quarter("2026-01-25", [2026, "Q4"], null),
    quarter("2026-04-26", [2027, "Q1"], 81615000000, { revenue_yoy: 0.85, net_income: -1000000000 }), quarter("2026-07-26", [2027, "Q2"], 96221000000, { revenue_yoy: 1.06, eps_diluted: 2.46 }),
  ] };
}

test("Financials draws eight quarters as bars with year-over-year growth, leaves Q4 as a gap, and explains issuers without quarterly filings", async ({ page }) => {
  const reads: string[] = [];
  await page.route("**/api/backend/charts/symbol/*/financials", async (route) => {
    const symbol = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-2)!);
    reads.push(symbol);
    await route.fulfill({ json: financials(symbol) });
  });
  await page.goto("/charts");
  const info = panel(page);
  await info.getByRole("tab", { name: "Financials", exact: true }).click();
  const revenue = info.getByRole("region", { name: "Revenue", exact: true });
  await expect(revenue).toContainText("$96.2B");
  await expect(revenue).toContainText("+106%");
  await expect(revenue.getByTestId("bar")).toHaveCount(6); // eight columns, the two Q4 gaps draw no bar
  await expect(revenue.locator("li").nth(1)).toContainText("—");
  await expect(info.getByRole("list", { name: "Quarters" })).toContainText("Q4 FY26");
  await expect(info.getByRole("region", { name: "Gross margin" })).toContainText("72.0%");
  await expect(info.getByRole("region", { name: "Net income" })).toContainText("-$1.0B");
  await expect(info.getByRole("region", { name: "Diluted EPS" })).toContainText("$2.46");
  await expect(info).toContainText("SEC EDGAR");
  await choose(page, "AMD");
  await expect(info).toContainText("No quarterly SEC financials for this issuer.");
  await choose(page, "SPY");
  await expect(info).toContainText("Not available for ETFs or funds.");
  expect(reads).toEqual(["NVDA", "AMD", "SPY"]);
});
