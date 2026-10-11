import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { DEFAULT_SETTINGS, STORAGE_KEY } from "../lib/charts";
import type { ChartBar, Interval } from "../lib/charts";
import { NEWS_TIP_LINES, newsBar, newsLabel, newsMarks, newsTip } from "../lib/newsMarkers";
import type { NewsArticle, NewsSource, SymbolNews } from "../lib/symbolInfo";

// T3.5. The alignment tests need no browser; the browser tests stub the news feed and the candles
// (live Alpaca and Polygon are not exercised). October 2026 is Eastern Daylight Time (UTC-4) and
// New York falls back on Sunday 1 November 2026, so those dates are written with their own offset.

const at = (stamp: string, offset = "-04:00") => Date.parse(`${stamp}${offset}`) / 1000;
const EDT = (day: string) => at(`2026-${day}`);
const EST = (day: string) => at(`2026-${day}`, "-05:00");

function candle(time: number, end: number): ChartBar {
  return { time, end_time: end, source: "tradier", open: 100, high: 102, low: 99, close: 101, volume: 1000, extended: false,
    ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null };
}
const minutes = (from: number, count: number) => Array.from({ length: count }, (_, i) => candle(from + i * 60, from + i * 60 + 60));
/** A daily candle is the regular session: 09:30 to 16:00 New York. */
const session = (day: string, offset = "-04:00") => candle(at(`2026-${day}T09:30:00`, offset), at(`2026-${day}T16:00:00`, offset));

let serial = 0;
function story(published: number, patch: Partial<NewsArticle> = {}): NewsArticle {
  const id = patch.id ?? `n${++serial}`;
  return { id, provider: "alpaca_benzinga", publisher: "Benzinga", headline: `Headline ${id}`, url: `https://example.com/${id}`,
    published_at: new Date(published * 1000).toISOString(), summary: null, tickers: ["NVDA"], roundup: false, sentiment: [], also_in: [], ...patch };
}
const barOf = (bars: ChartBar[], article: NewsArticle, interval: Interval) => newsBar(bars, Date.parse(article.published_at) / 1000, interval);

test("an article sits on the 1m candle whose minute holds its time", () => {
  const bars = minutes(EDT("10-06T09:30:00"), 60);
  expect(barOf(bars, story(EDT("10-06T09:32:00")), "1m")?.time).toBe(EDT("10-06T09:32:00")); // the first second of its minute
  expect(barOf(bars, story(EDT("10-06T09:32:59")), "1m")?.time).toBe(EDT("10-06T09:32:00")); // the last
  expect(barOf(bars, story(EDT("10-06T09:33:00")), "1m")?.time).toBe(EDT("10-06T09:33:00"));
});

test("an article in a gap sits on the next candle: overnight and weekend, 1m", () => {
  const bars = [...minutes(EDT("10-02T15:58:00"), 2), ...minutes(EDT("10-05T09:30:00"), 5), ...minutes(EDT("10-06T09:30:00"), 5)];
  expect(barOf(bars, story(EDT("10-02T15:59:30")), "1m")?.time).toBe(EDT("10-02T15:59:00")); // still inside its candle
  expect(barOf(bars, story(EDT("10-02T16:00:00")), "1m")?.time).toBe(EDT("10-05T09:30:00")); // the close: next is Monday's open
  expect(barOf(bars, story(EDT("10-03T12:00:00")), "1m")?.time).toBe(EDT("10-05T09:30:00")); // Saturday noon
  expect(barOf(bars, story(EDT("10-05T08:15:00")), "1m")?.time).toBe(EDT("10-05T09:30:00")); // pre-market with the regular session shown
  expect(barOf(bars, story(EDT("10-05T20:30:00")), "1m")?.time).toBe(EDT("10-06T09:30:00")); // after hours Monday
});

test("an article after the last candle sits on it, and one before the first loaded candle has none", () => {
  const bars = minutes(EDT("10-02T15:55:00"), 5); // the last candle ends at the Friday close
  expect(barOf(bars, story(EDT("10-02T16:45:00")), "1m")?.time).toBe(EDT("10-02T15:59:00"));
  expect(barOf(bars, story(EDT("10-04T10:00:00")), "1m")?.time).toBe(EDT("10-02T15:59:00")); // Sunday
  expect(barOf(bars, story(EDT("10-02T15:54:59")), "1m")).toBeUndefined();
  expect(barOf(bars, story(EDT("09-30T10:00:00")), "1m")).toBeUndefined();
  expect(newsMarks(bars, [story(EDT("09-30T10:00:00"))], "1m")).toEqual([]);
  expect(newsMarks([], [story(EDT("10-02T10:00:00"))], "1m")).toEqual([]);
});

test("a hole in the loaded history is not a closed market", () => {
  // Two pages of candles with nothing between them: an article in the hole has no candle to react on, and a stale last candle collects no old news.
  const bars = [...minutes(EDT("09-01T10:00:00"), 5), ...minutes(EDT("10-06T10:00:00"), 5)];
  expect(barOf(bars, story(EDT("09-15T10:00:00")), "1m")).toBeUndefined();
  expect(barOf(bars, story(EDT("10-05T20:00:00")), "1m")?.time).toBe(EDT("10-06T10:00:00")); // an ordinary overnight
  expect(barOf(bars.slice(0, 5), story(EDT("10-06T10:00:00")), "1m")).toBeUndefined();
});

test("a daily candle is a session: after the close and over the weekend an article sits on the next session, across the November time change", () => {
  const bars = [session("10-29"), session("10-30"), session("11-02", "-05:00"), session("11-03", "-05:00")];
  const on = (time: number) => barOf(bars, story(time), "1D")?.time;
  expect(on(EDT("10-30T09:30:00"))).toBe(EDT("10-30T09:30:00"));
  expect(on(EDT("10-30T15:59:59"))).toBe(EDT("10-30T09:30:00"));
  expect(on(EDT("10-30T16:00:00"))).toBe(EST("11-02T09:30:00")); // the close: Monday's session, an hour later on the UTC clock
  // 20:30 New York on Friday is already Saturday in UTC: it is still Friday's news and Monday's reaction.
  expect(on(EDT("10-30T20:30:00"))).toBe(EST("11-02T09:30:00"));
  expect(on(EDT("10-29T22:00:00"))).toBe(EDT("10-30T09:30:00"));
  expect(on(at("2026-11-01T12:00:00", "-05:00"))).toBe(EST("11-02T09:30:00")); // Sunday, after New York fell back
  expect(on(EST("11-02T08:00:00"))).toBe(EST("11-02T09:30:00")); // pre-market the same day
  expect(on(EST("11-02T10:00:00"))).toBe(EST("11-02T09:30:00"));
  expect(on(EST("11-03T17:00:00"))).toBe(EST("11-03T09:30:00")); // after the last session: the last candle
  expect(on(EDT("10-29T08:00:00"))).toBeUndefined(); // before the first loaded session, even if it is only its pre-market
});

test("1m candles on either side of the November time change", () => {
  const bars = [...minutes(EDT("10-30T15:58:00"), 2), ...minutes(EST("11-02T09:30:00"), 3)];
  expect(EST("11-02T09:30:00") - EDT("10-30T15:59:00")).toBe(2 * 86400 + 18 * 3600 + 31 * 60); // the weekend is an hour longer on the clock, and the candles know it
  expect(barOf(bars, story(at("2026-11-01T03:00:00", "-05:00")), "1m")?.time).toBe(EST("11-02T09:30:00"));
  expect(barOf(bars, story(at("2026-11-01T01:30:00", "-04:00")), "1m")?.time).toBe(EST("11-02T09:30:00")); // the first 01:30
  expect(barOf(bars, story(at("2026-11-01T01:30:00", "-05:00")), "1m")?.time).toBe(EST("11-02T09:30:00")); // the second 01:30
  expect(barOf(bars, story(EST("11-02T09:31:30")), "1m")?.time).toBe(EST("11-02T09:31:00"));
});

test("several articles on one candle make one marker, newest first, and roundups are never marked", () => {
  const bars = minutes(EDT("10-06T09:30:00"), 60);
  const [a, b, c] = [story(EDT("10-06T10:00:05"), { id: "a" }), story(EDT("10-06T10:00:40"), { id: "b" }), story(EDT("10-06T10:00:40"), { id: "c" })];
  const roundup = story(EDT("10-06T10:00:10"), { id: "r", roundup: true, tickers: ["A", "B", "C", "D"] });
  const marks = newsMarks(bars, [a, roundup, b, c, story(EDT("10-06T10:10:00"), { id: "d" })], "1m");
  expect(marks.map((mark) => [mark.time, mark.articles.map((article) => article.id)])).toEqual([[EDT("10-06T10:00:00"), ["b", "c", "a"]], [EDT("10-06T10:10:00"), ["d"]]]);
  expect(marks.map(newsLabel)).toEqual(["N3", "N"]);
  const seven = Array.from({ length: 7 }, (_, i) => story(EDT("10-06T10:20:00") + i, { id: `s${i}`, headline: `Story ${i}` }));
  const [mark] = newsMarks(bars, seven, "1m");
  expect(newsTip(mark)).toEqual({ lines: ["Story 6", "Story 5", "Story 4", "Story 3", "Story 2"], more: 2 });
  expect(NEWS_TIP_LINES).toBe(5);
});

// ---- Browser ----

const NEWS_NOW = EDT("10-06T11:00:00") * 1000;
const FEED = {
  a1: story(EDT("10-06T10:05:30"), { id: "a1", headline: "Nvidia ships a chip" }),
  a2: story(EDT("10-06T10:05:50"), { id: "a2", headline: "Analyst lifts target" }),
  a3: story(EDT("10-05T20:30:00"), { id: "a3", headline: "After-hours supply report" }),
  a4: story(EDT("10-03T12:00:00"), { id: "a4", headline: "Weekend profile piece" }),
  roundup: story(EDT("10-06T10:20:00"), { id: "r1", headline: "Five stocks moving today", tickers: ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"], roundup: true }),
  old: story(EDT("09-30T12:00:00"), { id: "o1", headline: "Last week's story" }),
};
const sources: NewsSource[] = [{ provider: "alpaca_benzinga", label: "Alpaca (Benzinga)", state: "ok", fetched_at: NEWS_NOW / 1000, age_seconds: 0, message: null },
  { provider: "polygon", label: "Polygon", state: "ok", fetched_at: NEWS_NOW / 1000, age_seconds: 0, message: null }];
const newsBody = (articles: NewsArticle[]): SymbolNews => ({ symbol: "NVDA", as_of: new Date(NEWS_NOW).toISOString(), time_zone: "America/New_York", days: 7,
  sentiment_note: "Sentiment is supplied by Polygon, not calculated here.", sources, articles });

/** Candles the stubbed workspace serves: Monday's last five minutes and Tuesday's session so far, or four daily sessions. */
function barsFor(interval: string): ChartBar[] {
  if (interval === "1D") return [session("10-01"), session("10-02"), session("10-05"), session("10-06")];
  const step = interval === "1m" ? 60 : 300;
  const run = (from: number, to: number) => Array.from({ length: Math.round((to - from) / step) }, (_, i) => candle(from + i * step, from + i * step + step));
  return [...run(EDT("10-05T15:55:00"), EDT("10-05T16:00:00")), ...run(EDT("10-06T09:30:00"), EDT("10-06T11:00:00"))];
}

const settingsData = { symbol: "NVDA", watchlist: ["NVDA", "AAPL", "SPY"], intervals: ["1m", "5m", "15m", "1h", "1D"] };
async function seed(context: BrowserContext, extra: Record<string, unknown> = {}, tab?: string) {
  // News interactions use their own fixture; saved plans from earlier tests
  // must not move the plot while its screen coordinates are being measured.
  await context.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
  await context.addInitScript(({ key, settings, tab }) => {
    (window as typeof window & { __tjCharts?: Map<string, unknown> }).__tjCharts = new Map();
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(settings));
    if (tab) localStorage.setItem("tradejournal.charts.symbol-info.tab.v1", tab);
  }, { key: STORAGE_KEY, settings: { ...DEFAULT_SETTINGS, ...settingsData, ...extra }, tab });
  return fakeChartSettings(context, { revision: 1, data: { ...settingsData, ...extra } });
}

async function stub(page: Page, markers: object[] = [], articles: NewsArticle[] = Object.values(FEED).sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at))) {
  const reads: string[] = [];
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const now = Math.floor(Date.now() / 1000);
    await route.fulfill({ json: { symbol: query.get("symbol"), session: "extended", provider: "Fixture", delayed: false, refresh_seconds: 15,
      checked_at: now, fetched_at: { intraday: now, quotes: now }, intraday_as_of: now, issues: [], fills: [], fills_truncated: false, extras: {},
      quotes: [{ symbol: query.get("symbol"), name: "Nvidia", instrument_type: "stock", last: 101, change: 1, change_percentage: 1, volume: 1000, previous_close: 100, trade_time: now }],
      panels: Object.fromEntries((query.get("intervals") ?? "5m").split(",").map((interval) => [interval, { bars: barsFor(interval), markers }])) } });
  });
  await page.route("**/api/backend/charts/stream?**", (route) => route.fulfill({ status: 503, body: "Fixture has no stream" }));
  await page.route("**/api/backend/charts/symbol/*/news", (route) => { reads.push(new URL(route.request().url()).pathname); return route.fulfill({ json: newsBody(articles) }); });
  return reads;
}

type Api = { timeScale(): { timeToCoordinate(t: number): number | null }; panes(): { getSeries(): { seriesType(): string; priceToCoordinate(p: number): number | null }[] }[] };
const canvas = (page: Page) => page.getByTestId("canvas-main");
const panel = (page: Page) => page.getByRole("region", { name: "Symbol info", exact: true });
const tooltip = (page: Page) => page.getByRole("tooltip", { name: "News headlines" });

/** Where the candle at `time` is on the page: its x and the y of its high. */
async function onPage(page: Page, time: number, high: number) {
  const at = await page.evaluate(([t, p]) => {
    const chart = (window as unknown as { __tjCharts: Map<string, Api> }).__tjCharts.get("main")!;
    const candles = chart.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")!;
    return { x: chart.timeScale().timeToCoordinate(t), y: candles.priceToCoordinate(p) };
  }, [time, high]);
  const box = (await canvas(page).boundingBox())!;
  return { x: box.x + at.x!, y: box.y + at.y! };
}
/** Move up from the candle's high until the marker above it answers with its headlines. */
async function hoverMarker(page: Page, time: number) {
  await page.mouse.move(2, 2); // leave the chart first, so a tooltip still open is not taken for this marker's
  await expect(tooltip(page)).toHaveCount(0);
  const top = await onPage(page, time, 102);
  for (let dy = -3; dy >= -140; dy -= 3) {
    await page.mouse.move(top.x, top.y + dy);
    await page.waitForTimeout(30);
    if (await tooltip(page).isVisible()) return { x: top.x, y: top.y + dy };
  }
  throw new Error("No news marker answered above the candle.");
}

test("markers sit on the right candle on 1m and 1D; hover lists the headlines, click opens them in the News tab, and one read serves both", async ({ page, context }) => {
  await seed(context);
  const reads = await stub(page);
  await page.goto("/charts");
  const main = canvas(page);
  // 1m: Monday's after-hours story lands on Tuesday's open. The weekend piece is before the first loaded candle, and the roundup and last week's story have none.
  await expect(main).toHaveAttribute("data-news", `${EDT("10-06T09:30:00")}:1,${EDT("10-06T10:05:00")}:2`);
  await expect.poll(() => reads.length).toBe(1);
  await page.screenshot({ path: test.info().outputPath("news-markers-desktop.png"), animations: "disabled" });

  const point = await hoverMarker(page, EDT("10-06T10:05:00"));
  await expect(tooltip(page)).toContainText("Oct 6, 2026 10:05 AM ET candle");
  await expect(tooltip(page)).toContainText("2 headlines");
  const lines = await tooltip(page).getByRole("listitem").allTextContents();
  expect(lines).toEqual(["Analyst lifts target", "Nvidia ships a chip"]); // newest first
  await expect(tooltip(page)).not.toContainText("Five stocks moving today");
  await page.mouse.move(point.x, point.y - 80);
  await expect(tooltip(page)).toHaveCount(0);

  // Click: the symbol info panel shows the News tab with that candle's articles lit, without another read.
  await expect(panel(page).getByRole("tab", { name: "You", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.mouse.click(point.x, point.y);
  await expect(panel(page).getByRole("tab", { name: "News", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).getByRole("link", { name: "Nvidia ships a chip" })).toBeVisible();
  const lit = panel(page).locator("li[data-news-lit]");
  await expect(lit).toHaveCount(2);
  await expect(lit.first()).toContainText("Analyst lifts target");
  await expect(panel(page).locator("li", { hasText: "Weekend profile piece" })).not.toHaveAttribute("data-news-lit", "true");
  await page.waitForTimeout(700);
  expect(reads).toHaveLength(1);

  // 1D: a candle is a session. Tuesday holds its own two stories and Monday's after-hours one; the weekend piece is Monday's.
  await page.getByLabel("Main interval").selectOption("1D");
  await expect(main).toHaveAttribute("data-news", `${EDT("10-05T09:30:00")}:1,${EDT("10-06T09:30:00")}:3`);
  await hoverMarker(page, EDT("10-06T09:30:00"));
  await expect(tooltip(page)).toContainText("Oct 6, 2026 session");
  await expect(tooltip(page)).toContainText("3 headlines");
  expect(await tooltip(page).getByRole("listitem").allTextContents()).toEqual(["Analyst lifts target", "Nvidia ships a chip", "After-hours supply report"]);
  await hoverMarker(page, EDT("10-05T09:30:00"));
  await expect(tooltip(page)).toContainText("Weekend profile piece");
  expect(reads).toHaveLength(1);
});

test("the News layer toggle hides the markers and stops the reads; the setting is saved with the other layers", async ({ page, context }) => {
  const server = await seed(context);
  const reads = await stub(page);
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  await page.clock.runFor(400);
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  expect(reads).toHaveLength(1);
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  const group = page.getByRole("region", { name: "Layers" }).getByRole("group", { name: "News markers" });
  await group.getByRole("button", { name: "Hide News markers" }).click();
  await expect(canvas(page)).toHaveAttribute("data-news", "");
  await page.clock.runFor(1000);
  await expect.poll(() => server.data?.newsHidden).toBe(true);
  await expect(page.getByRole("tooltip", { name: "News headlines" })).toHaveCount(0);
  await page.clock.runFor(180_000); // three poll periods with the layer off
  expect(reads).toHaveLength(1);
  await group.getByRole("button", { name: "Show News markers" }).click();
  await page.clock.runFor(400);
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  await page.clock.runFor(1000);
  await expect.poll(() => server.data?.newsHidden).toBe(false);
  expect(reads).toHaveLength(2);
});

test("a layer that starts hidden reads no news, and the chart's menu lists it", async ({ page, context }) => {
  await seed(context, { newsHidden: true });
  const reads = await stub(page);
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  await expect(canvas(page)).toHaveAttribute("data-bars", /\d+/);
  await expect(canvas(page)).toHaveAttribute("data-news", "");
  await page.clock.runFor(120_000);
  expect(reads).toHaveLength(0);
  // The chart menu's Layers list carries the toggle, unchecked.
  const box = (await canvas(page).boundingBox())!;
  await page.mouse.click(box.x + 140, box.y + 40, { button: "right" });
  await page.getByRole("dialog", { name: "Chart menu" }).getByRole("menuitem", { name: /^Layers/ }).click();
  const toggle = page.getByRole("dialog", { name: "Chart menu" }).getByRole("menuitemcheckbox", { name: "News markers" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await page.clock.runFor(400);
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  expect(reads).toHaveLength(1);
});

test("a marker click is one-shot: coming back to the Watchlist tab shows the tab chosen before, with nothing lit", async ({ page, context }) => {
  await seed(context);
  await stub(page);
  await page.goto("/charts");
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  await expect(panel(page).getByRole("tab", { name: "You", exact: true })).toHaveAttribute("aria-selected", "true");
  const point = await hoverMarker(page, EDT("10-06T10:05:00"));
  await page.mouse.click(point.x, point.y);
  await expect(panel(page).locator("li[data-news-lit]")).toHaveCount(2);
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  await expect(panel(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Watchlist", exact: true }).click();
  await expect(panel(page).getByRole("tab", { name: "You", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(panel(page).locator("li[data-news-lit]")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("tradejournal.charts.symbol-info.tab.v1"))).not.toBe("News");
});

test("leaving the News tab ends the highlight: coming back to News shows nothing lit", async ({ page, context }) => {
  await seed(context);
  await stub(page);
  await page.goto("/charts");
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  const point = await hoverMarker(page, EDT("10-06T10:05:00"));
  await page.mouse.click(point.x, point.y);
  await expect(panel(page).locator("li[data-news-lit]")).toHaveCount(2);
  await panel(page).getByRole("tab", { name: "Events", exact: true }).click();
  await panel(page).getByRole("tab", { name: "News", exact: true }).click();
  await expect(panel(page).locator("li", { hasText: "Analyst lifts target" })).toBeVisible();
  // Well inside the 6 s highlight window, so this proves the switch ended it, not the timer.
  await expect(panel(page).locator("li[data-news-lit]")).toHaveCount(0, { timeout: 1000 });
});

test("with the News tab open the tab and the markers share one read, then one each minute", async ({ page, context }) => {
  await seed(context, {}, "News");
  const reads = await stub(page);
  await page.clock.install({ time: new Date(NEWS_NOW) });
  await page.goto("/charts");
  await page.clock.runFor(400);
  await expect(panel(page).getByRole("link", { name: "Nvidia ships a chip" })).toBeVisible();
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  expect(reads).toHaveLength(1);
  await page.clock.runFor(60_000);
  expect(reads).toHaveLength(2);
  // Leaving the tab keeps the markers' read going: the layer, not the tab, asks for it.
  await panel(page).getByRole("tab", { name: "You", exact: true }).click();
  await page.clock.runFor(60_000);
  expect(reads).toHaveLength(3);
  // A hidden page reads nothing.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.runFor(180_000);
  expect(reads).toHaveLength(3);
});

test("a news marker does not hide a fill arrow on the same candle: both still answer", async ({ page, context }) => {
  await seed(context);
  // A sale on the 10:05 candle the two stories mark.
  const reads = await stub(page, [{ id: "00000000-0000-4000-8000-000000000001", time: EDT("10-06T10:05:00"), label: "sell to close 1 share", buy: false }]);
  await page.goto("/charts");
  await expect(canvas(page)).toHaveAttribute("data-markers", "1");
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  const top = await onPage(page, EDT("10-06T10:05:00"), 102);
  const seen = new Set<string>();
  for (let dy = -3; dy >= -60; dy -= 3) {
    await page.mouse.move(top.x, top.y + dy);
    await page.waitForTimeout(30);
    if (await page.getByRole("tooltip", { name: "Fill summary" }).isVisible()) seen.add("fill");
    if (await tooltip(page).isVisible()) seen.add("news");
  }
  expect([...seen].sort()).toEqual(["fill", "news"]);
  expect(reads).toHaveLength(1);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("a tap shows the headlines and Read in News opens the sheet on the News tab", async ({ page, context }) => {
    await seed(context);
    const reads = await stub(page);
    let polls = 0;
    page.on("request", (request) => { if (request.url().includes("/charts/workspace?")) polls++; });
    await page.clock.install({ time: new Date(NEWS_NOW) });
    await page.goto("/charts");
    await page.clock.runFor(400);
    await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
    const top = await onPage(page, EDT("10-06T10:05:00"), 102);
    let popover = page.getByRole("dialog", { name: "News headlines" });
    for (let dy = -3; dy >= -140 && !(await popover.isVisible()); dy -= 3) {
      await page.touchscreen.tap(top.x, top.y + dy);
      await page.waitForTimeout(150);
    }
    await expect(popover).toContainText("Analyst lifts target");
    await expect(popover).toContainText("Nvidia ships a chip");
    // A workspace poll rebuilds the fill list; the pinned popover stays open through it.
    const seen = polls;
    await page.clock.runFor(16_000);
    await expect.poll(() => polls).toBeGreaterThan(seen);
    await expect(popover).toBeVisible();
    popover = page.getByRole("dialog", { name: "News headlines" });
    await popover.getByRole("button", { name: "Read in News" }).tap();
    const sheet = page.getByRole("dialog", { name: "Watchlist", exact: true });
    await expect(sheet.getByRole("tab", { name: "News", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(sheet.locator("li[data-news-lit]")).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(reads).toHaveLength(1); // the sheet's tab joined the chart's read
  });
});

test("news markers never move the price scale: the visible prices are the same with and without them", async ({ page, context }) => {
  await seed(context);
  await stub(page);
  const range = () => page.evaluate(() => {
    const chart = (window as unknown as { __tjCharts: Map<string, unknown> }).__tjCharts.get("main")! as unknown as Api & { panes(): { getHeight(): number }[] };
    const candles = chart.panes()[0].getSeries().find((series) => series.seriesType() === "Candlestick")! as unknown as { coordinateToPrice(y: number): number | null };
    // The prices at the pane's top and bottom edges: the same fit puts the same prices there, whatever the pane's height.
    return [candles.coordinateToPrice(0), candles.coordinateToPrice((chart.panes()[0] as unknown as { getHeight(): number }).getHeight())];
  });
  // The scale settles over the first frames; read it once two reads in a row agree.
  const settled = async () => { let last = await range(); for (let i = 0; i < 40; i++) { await page.waitForTimeout(100); const next = await range(); if (JSON.stringify(next) === JSON.stringify(last) && i > 4) return next; last = next; } return last; };
  await page.goto("/charts");
  await expect(canvas(page)).toHaveAttribute("data-news", /:2/);
  const withNews = await settled();
  await page.screenshot({ path: test.info().outputPath("news-markers-lifted-desktop.png"), animations: "disabled" });
  await page.unroute("**/api/backend/charts/symbol/*/news");
  await page.route("**/api/backend/charts/symbol/*/news", (route) => route.fulfill({ json: newsBody([]) }));
  await page.reload();
  await expect(canvas(page).locator("canvas").first()).toBeVisible();
  await expect(canvas(page)).toHaveAttribute("data-news", "");
  const without = await settled();
  // A pixel of pane height moves these by a hundredth; a marker widening the fit would move them by whole candles.
  without.forEach((price, i) => expect(price).toBeCloseTo(withNews[i]!, 1));
});
