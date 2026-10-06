import { expect, test, type Page } from "@playwright/test";
import type { ChartBar, ChartData, Interval } from "../lib/charts";
import type { ChartPosition, OptionMark, TradeCardData } from "../lib/chartJournal";
import { fakeChartSettings } from "./fixtures/chartSettings";

// The journal on the chart (C3.1 trade card, C3.2 position lines, C3.3 historical
// mode). Candles are stubbed; the journal routes are stubbed where a test needs
// exact states (stale, missing), and read from the seeded backend in the last test.

test.beforeEach(async ({ context }) => {
  await fakeChartSettings(context);
  await context.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
});

const STEP: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };
const FILL = "00000000-0000-4000-8000-000000000001";
const TRADE = "00000000-0000-4000-8000-0000000000aa";
// Tuesday 14 July 2026, 09:40 and 10:20 New York (EDT): months before the stubbed "today".
const ENTRY = Date.parse("2026-07-14T13:40:00Z") / 1000;
const EXIT = Date.parse("2026-07-14T14:20:00Z") / 1000;

function bar(time: number, step: number, close: number): ChartBar {
  return { time, end_time: time + step, source: "alpaca_sip", open: close - 0.3, high: close + 0.8, low: close - 0.7, close, volume: 10000,
    ema9: close, ema20: close, ema50: close, ema200: close, vwap: close, rsi: 50, extended: false };
}
/** `count` candles of `step` seconds ending at `end`. */
const bars = (end: number, step: number, count: number, base = 100) =>
  Array.from({ length: count }, (_, i) => bar(end - (count - i) * step, step, base + Math.sin(i / 7) * 2 + i * 0.01));

function workspace(url: string, now: number, extra: Partial<ChartData> = {}, marker = false): ChartData {
  const query = new URL(url).searchParams;
  const symbol = query.get("symbol") ?? "MRVL";
  const panels: ChartData["panels"] = {};
  for (const interval of (query.get("intervals") ?? "5m").split(",") as Interval[]) {
    const step = STEP[interval];
    const shown = bars(Math.floor(now / step) * step + step, step, 120);
    panels[interval] = { bars: shown, markers: marker ? [{ id: FILL, time: shown[100].time, label: "buy to open 1 call", buy: true }] : [] };
  }
  const symbols = [...new Set([symbol, ...(query.get("watchlist") ?? "").split(",")].filter(Boolean))];
  return { symbol, session: "extended", provider: "Tradier", delayed: false, refresh_seconds: 15, checked_at: now, fetched_at: { intraday: now }, panels,
    quotes: symbols.map((s) => ({ symbol: s, name: s, last: 105, change: 1, change_percentage: 1, volume: 1, previous_close: 104, trade_time: now - 2 })),
    issues: [], intraday_as_of: now - 60, history_note: "Synthetic", fills: [], fills_truncated: false, extras: {},
    adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] },
    ...extra };
}

const POSITIONS: ChartPosition[] = [
  { trade_id: "s1", account: "Roth", last4: "8267", instrument: "stock", contract: "MRVL stock", direction: "long", open: 20, avg_cost: 102.5, realized: 100,
    opened_at: ENTRY, exits: [EXIT], line: 102.5, underlying_at_entry: null, unit: "share", price_note: "" },
  { trade_id: "o1", account: "Roth", last4: "8267", instrument: "option", contract: "MRVL 1/15/27 110C", direction: "long", open: 1, avg_cost: 310, realized: 110,
    opened_at: ENTRY, exits: [], line: 98.75, underlying_at_entry: { price: 98.75, source: "alpaca_sip", single_venue: false }, unit: "contract", price_note: "" },
  // No observed underlying: no line, never the premium.
  { trade_id: "o2", account: "Roth", last4: "8267", instrument: "option", contract: "MRVL 1/15/27 90P", direction: "long", open: 1, avg_cost: 200, realized: 0,
    opened_at: ENTRY, exits: [], line: null, underlying_at_entry: null, unit: "contract", price_note: "" },
];

const CARD: TradeCardData = {
  fill: { id: FILL, ticker: "MRVL", side: "buy_to_open", qty: 1, price: 310, time: ENTRY, instrument: "option", contract: "MRVL 1/15/27 110C" },
  trade: { id: TRADE, ticker: "MRVL", instrument: "option", contract: "MRVL 1/15/27 110C", option_type: "call", strike: 110, expiration: "2027-01-15",
    account: { name: "Roth", last4: "8267" }, status: "open", direction: "long", expired_worthless: false, opened_at: ENTRY, closed_at: null, hold_minutes: null,
    contracts: 2, avg_entry: 310, avg_exit: 420, cost: 620, realized_pnl: null, pnl_pct: null, unit: "contract",
    price_note: "Option prices are the premium per contract (100 shares), in dollars. They are not underlying prices." },
  fills: [
    { id: FILL, role: "entry", side: "buy_to_open", qty: 2, price: 310, time: ENTRY, underlying: null },
    { id: "00000000-0000-4000-8000-000000000002", role: "exit", side: "sell_to_close", qty: 1, price: 420, time: EXIT, underlying: null },
  ],
  position: { open: 1, avg_cost: 310, realized: 110 },
  path: { state: "stale", note: "Computed from an older version of this trade or its inputs; the next path run recomputes it.", source: "alpaca_sip",
    underlying_mfe_pct: 1.2, underlying_mae_pct: 0.4, underlying_exit_efficiency: 61, option_mfe_pct: 40, option_mae_pct: 10, option_exit_efficiency: 55 },
  context: { state: "missing", note: "This entry has no market context yet. Enrich fills from Sync." },
};

const registerCharts = (page: Page) => page.addInitScript(() => { (window as typeof window & { __tjCharts?: Map<string, unknown> }).__tjCharts = new Map(); });
type Api = { timeScale(): { getVisibleRange(): { from: number; to: number } | null; timeToCoordinate(t: number): number | null };
  panes(): { getSeries(): { seriesType(): string; priceToCoordinate(p: number): number | null }[] }[] };
const visible = (page: Page) => page.evaluate(() => (window as unknown as { __tjCharts: Map<string, Api> }).__tjCharts.get("main")!.timeScale().getVisibleRange());

/** Hover down from a candle's low until the fill arrow under it answers with its summary. */
async function hoverFill(page: Page, time: number, low: number) {
  const at = await page.evaluate(([t, p]) => {
    const chart = (window as unknown as { __tjCharts: Map<string, Api> }).__tjCharts.get("main")!;
    const candles = chart.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!;
    return { x: chart.timeScale().timeToCoordinate(t), y: candles.priceToCoordinate(p) };
  }, [time, low]);
  const box = (await page.getByTestId("canvas-main").boundingBox())!;
  for (let dy = 4; dy <= 40; dy += 3) {
    await page.mouse.move(box.x + at.x!, box.y + at.y! + dy);
    if (await page.getByRole("tooltip", { name: "Fill summary" }).isVisible()) return { x: box.x + at.x!, y: box.y + at.y! + dy };
  }
  throw new Error("No fill arrow answered under the candle.");
}

test("a fill arrow's hover and card label units, stale and missing metrics, and an old option mark; positions draw honest lines", async ({ page }) => {
  await registerCharts(page);
  const now = Math.floor(Date.now() / 1000);
  let shown: ChartBar | undefined;
  await page.route("**/api/backend/charts/workspace?**", (route) => {
    const data = workspace(route.request().url(), now, { positions: POSITIONS }, true);
    shown = data.panels["5m"]!.bars[100];
    return route.fulfill({ json: data });
  });
  await page.route(`**/api/backend/charts/journal/fills/${FILL}`, (route) => route.fulfill({ json: CARD }));
  let marks = 0;
  await page.route(`**/api/backend/charts/journal/trades/${TRADE}/mark`, (route) => {
    marks++;
    const mark: OptionMark = { mark: 4.0, mark_per_contract: 400, basis: "mid", bid: 3.9, ask: 4.1, last: 4.05, provider: "tradier", quoted_at: now - 900, open_pnl: 90 };
    return route.fulfill({ json: mark });
  });
  await page.goto("/charts");
  const main = page.getByTestId("canvas-main");
  await expect(main).toHaveAttribute("data-markers", "1");
  // C3.2: the stock at its average cost, the call at the underlying when it was bought; the put has no observed underlying and no line.
  await expect(main).toHaveAttribute("data-positions", "stock:102.50,option:98.75");

  const point = await hoverFill(page, shown!.time, shown!.low);
  await expect(page.getByRole("tooltip", { name: "Fill summary" })).toContainText("buy to open 1 call");
  await page.mouse.click(point.x, point.y);
  const card = page.getByRole("dialog", { name: "Trade card" });
  await expect(card).toContainText("MRVL 1/15/27 110C");
  await expect(card).toContainText("not underlying prices");
  await expect(card).toContainText("$310.00/contract");
  await expect(card).toContainText("underlying not recorded");
  await expect(card.getByRole("region", { name: "Path (MFE / MAE)" })).toContainText("Stale");
  await expect(card.getByRole("region", { name: "Entry context" })).toContainText("Missing");
  await expect(card.getByRole("region", { name: "Entry context" })).toContainText("Enrich fills from Sync");
  expect(marks).toBe(0); // a mark is asked for, never fetched on open
  await card.getByRole("button", { name: "Get mark and open P&L" }).click();
  await expect(card).toContainText("$400.00/contract");
  await expect(card).toContainText("+$90.00");
  await expect(card).toContainText("Stale: quoted 15m ago");
  await expect(card.getByRole("link", { name: "Trade page" })).toHaveAttribute("href", `/trades/${TRADE}`);
  await page.screenshot({ path: test.info().outputPath("trade-card-desktop.png") });
  await card.getByRole("button", { name: "Close trade card" }).click();
  await expect(card).toHaveCount(0);

  // The Journal layer hides the arrows and the position lines together.
  await page.getByRole("button", { name: "Layers", exact: true }).first().click();
  await page.getByRole("button", { name: "Hide Journal", exact: true }).click();
  await expect(main).toHaveAttribute("data-positions", "");
});

test("a trade opened from its page shows its months-old candles and arrows, its card, and goes back to live", async ({ page }) => {
  await registerCharts(page);
  const now = Math.floor(Date.now() / 1000);
  const history: { interval: string; before: number }[] = [];
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: workspace(route.request().url(), now) }));
  await page.route("**/api/backend/charts/history?**", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const interval = query.get("interval") as Interval;
    const before = Number(query.get("before"));
    history.push({ interval, before });
    const step = STEP[interval];
    const page_ = bars(Math.floor(before / step) * step, step, 1200, 90);
    const entry = page_.find((b) => b.time <= ENTRY && ENTRY < b.end_time);
    return route.fulfill({ json: { symbol: query.get("symbol"), interval, session: "extended", before, limit: 1200, bars: page_,
      markers: entry ? [{ id: FILL, time: entry.time, label: "buy to open 1 call", buy: true }] : [],
      older_cursor: page_[0].time, exhausted: false, continuation: null, warmup: "ready", source: interval === "1D" ? "tradier" : "alpaca_sip",
      price_basis: "split_adjusted", adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] },
      fills_truncated: false, issue: null } });
  });
  await page.route(`**/api/backend/charts/journal/trades/${TRADE}`, (route) => route.fulfill({ json: { ...CARD, fill: null } }));
  await page.goto(`/charts?symbol=NVDA&from=${ENTRY}&to=${EXIT}&trade=${TRADE}`);
  const banner = page.getByRole("status", { name: "Past trade view" });
  await expect(banner).toContainText("Showing NVDA Jul 14, 2026, 9:40 AM–10:20 AM ET");
  await expect(page.getByRole("region", { name: /NVDA 5m chart/ })).toHaveCount(1);
  // The 5m page ends at the close of that day's extended session (20:00 New York), not today.
  await expect.poll(() => history.find((h) => h.interval === "5m")?.before).toBe(Date.parse("2026-07-15T01:00:00Z") / 1000);
  // The main chart is centred on the trade, with its arrow on the entry candle.
  await expect.poll(async () => { const range = await visible(page); return !!range && range.from <= ENTRY && range.to >= EXIT; }).toBe(true);
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-markers", "1");
  await expect(page.getByRole("dialog", { name: "Trade card" })).toContainText("MRVL 1/15/27 110C");
  await page.screenshot({ path: test.info().outputPath("past-trade-desktop.png") });

  await page.getByRole("dialog", { name: "Trade card" }).getByRole("button", { name: "Close trade card" }).click();
  await banner.getByRole("button", { name: "Back to live" }).click();
  await expect(banner).toHaveCount(0);
  expect(new URL(page.url()).search).toBe("");
  await expect.poll(async () => (await visible(page))?.to ?? 0).toBeGreaterThan(now - 600);
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("the trade card is a bottom sheet at 390px", async ({ page }) => {
    const now = Math.floor(Date.now() / 1000);
    await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: workspace(route.request().url(), now) }));
    await page.route("**/api/backend/charts/history?**", (route) => route.fulfill({ status: 503, json: { detail: { message: "History unavailable" } } }));
    await page.route(`**/api/backend/charts/journal/trades/${TRADE}`, (route) => route.fulfill({ json: { ...CARD, fill: null } }));
    await page.goto(`/charts?symbol=MRVL&from=${ENTRY}&to=${EXIT}&trade=${TRADE}`);
    const sheet = page.getByRole("dialog", { name: "Trade card" });
    await expect(sheet).toContainText("Still open");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    // History that cannot load says so; the banner still offers the way back.
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(page.getByRole("status", { name: "Past trade view" }).getByRole("button", { name: "Back to live" })).toBeVisible();
  });
});

test("a seeded trade's page links to the chart, and the real journal route fills its card", async ({ page }) => {
  await page.goto("/trades");
  await page.locator('tbody a[href^="/trades/"]').first().click();
  const link = page.getByRole("link", { name: "Open on chart" });
  await expect(link).toBeVisible();
  const href = new URL((await link.getAttribute("href"))!, "http://x");
  const id = href.searchParams.get("trade")!;
  expect(page.url()).toContain(id);
  expect(Number(href.searchParams.get("from"))).toBeGreaterThan(1_600_000_000);
  const card = await (await page.request.get(`/api/backend/charts/journal/trades/${id}`)).json() as TradeCardData;
  expect(card.trade?.id).toBe(id);
  expect(card.trade?.ticker).toBe(href.searchParams.get("symbol"));
  expect(["current", "stale", "missing"]).toContain(card.path?.state);

  const now = Math.floor(Date.now() / 1000);
  await page.route("**/api/backend/charts/workspace?**", (route) => route.fulfill({ json: workspace(route.request().url(), now) }));
  await page.route("**/api/backend/charts/history?**", (route) => route.fulfill({ status: 503, json: { detail: { message: "History unavailable" } } }));
  await link.click();
  await expect(page.getByRole("dialog", { name: "Trade card" })).toContainText(card.trade!.contract);
});
