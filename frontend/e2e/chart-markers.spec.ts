import { expect, test, type Page } from "@playwright/test";
import { fakeChartSettings } from "./fixtures/chartSettings";
import { routeDense, type Dense } from "./fixtures/denseMarkers";
import { cleanFillLabels, DEFAULT_SETTINGS, sanitizeSettings } from "../lib/charts";
import type { FillMarker } from "../lib/charts";
import { groupFills, groupLabel, labelled } from "../lib/chartMarks";
import { clusterNews, type NewsMark } from "../lib/newsMarkers";
import { shared } from "../lib/chartSync";
import type { NewsArticle } from "../lib/symbolInfo";

// The fill, news and report marks on the chart, merged and quiet. The pure parts need no browser; the browser tests use a deliberately
// crowded MRVL day (e2e/fixtures/denseMarkers.ts): four fills on one 5m candle, neighbours with fills, daily candles with six to eight
// fills each, five stories on neighbouring candles, one earnings date.

const fill = (id: string, time: number, label: string, buy: boolean): FillMarker => ({ id, time, label, buy });
const article = (id: string, at: number): NewsArticle => ({ id, provider: "alpaca_benzinga", publisher: "Benzinga", headline: `H ${id}`, url: `https://example.com/${id}`,
  published_at: new Date(at * 1000).toISOString(), summary: null, tickers: ["MRVL"], roundup: false, sentiment: [], also_in: [] });

test("fills merge by candle and side, keep every fill, and count only when merged", () => {
  const groups = groupFills([fill("a", 100, "buy to open 1 call", true), fill("b", 100, "buy to open 3 call", true), fill("c", 100, "sell to close 1 call", false),
    fill("d", 400, "sell to close 2 call", false), fill("e", 100, "buy to open 2 call", true)]);
  expect(groups.map((g) => [g.time, g.buy, g.fills.map((f) => f.id)])).toEqual([[100, true, ["a", "b", "e"]], [100, false, ["c"]], [400, false, ["d"]]]);
  expect(groups.reduce((sum, g) => sum + g.fills.length, 0)).toBe(5); // merged is not hidden
  expect(groupLabel(groups[0])).toBe("buy to open"); // the words the merged fills share
  expect(groupLabel(groups[1])).toBe("sell to close 1 call");
  expect(groupLabel(groupFills([fill("x", 1, "buy to open 1 call", true), fill("y", 1, "buy to close 1 call", true)])[0])).toBe("buy");
});

test("fill labels: off labels nothing, latest only the newest candle's fills, all every group", () => {
  const groups = groupFills([fill("a", 100, "buy to open 1 call", true), fill("b", 400, "buy to open 1 call", true), fill("c", 400, "sell to close 1 call", false)]);
  expect([...labelled(groups, "off")]).toEqual([]);
  expect([...labelled(groups, "latest")].sort()).toEqual(["400:buy", "400:sell"]);
  expect([...labelled(groups, "all")].sort()).toEqual(["100:buy", "400:buy", "400:sell"]);
  expect([...labelled([], "latest")]).toEqual([]);
});

test("news markers close together join into one with every headline; far apart ones stay apart", () => {
  const mark = (time: number, ids: string[]): NewsMark => ({ id: `news:${time}`, time, articles: ids.map((id) => article(id, time + Number(id.slice(1)))) });
  const placed = [{ mark: mark(100, ["n1"]), x: 10 }, { mark: mark(160, ["n2", "n3"]), x: 22 }, { mark: mark(220, ["n4"]), x: 38 }, { mark: mark(900, ["n5"]), x: 200 }];
  const clusters = clusterNews(placed, 30);
  expect(clusters.map((c) => [c.time, c.last, c.articles.length, c.marks])).toEqual([[100, 220, 4, 3], [900, 900, 1, 1]]);
  expect(clusters[0].articles.map((a) => a.id)).toEqual(["n4", "n3", "n2", "n1"]); // newest first
  expect(clusters[0].x).toBeCloseTo((10 + 22 + 38) / 3);
  expect(clusterNews([], 30)).toEqual([]);
  // Zoomed in, the same stories are far apart on screen and stay separate.
  expect(clusterNews(placed.map((p) => ({ ...p, x: p.x * 10 })), 30)).toHaveLength(4);
});

test("fill labels and news-on-small are shared settings: off by default, old settings load unchanged, bad values fall back", () => {
  expect(DEFAULT_SETTINGS.fillLabels).toBe("off");
  expect(DEFAULT_SETTINGS.newsOnSmall).toBe(false);
  const old = sanitizeSettings({ symbol: "NVDA", indicators: { fills: true } });
  expect([old.fillLabels, old.newsOnSmall, old.symbol]).toEqual(["off", false, "NVDA"]);
  expect(cleanFillLabels("all")).toBe("all");
  expect(cleanFillLabels("everything")).toBe("off");
  const saved = sanitizeSettings({ fillLabels: "latest", newsOnSmall: true });
  expect(shared(saved)).toMatchObject({ fillLabels: "latest", newsOnSmall: true });
  expect(shared(sanitizeSettings({ fillLabels: 3, newsOnSmall: "yes" }))).toMatchObject({ fillLabels: "off", newsOnSmall: false });
});

// ---- Browser ----

type Marks = { drawnLabels(): string[]; clusters(): { time: number; last: number; count: number; x: number; y: number }[];
  fillBoxes(): { id: string; buy: boolean; count: number; x: number; y: number; half: number }[] };
type Chart = { timeScale(): { setVisibleRange(range: { from: number; to: number }): void } };

async function open(page: Page, context: Parameters<typeof fakeChartSettings>[0]) {
  const server = await fakeChartSettings(context);
  await page.addInitScript(() => {
    const w = window as typeof window & { __tjCharts?: Map<string, unknown>; __tjMarks?: Map<string, unknown> };
    w.__tjCharts = new Map(); w.__tjMarks = new Map();
  });
  const dense = await routeDense(page);
  await page.goto("/charts");
  await expect(page.getByTestId("canvas-main")).toHaveAttribute("data-fill-marks", /buy|sell/);
  return { server, dense };
}
const main = (page: Page) => page.getByTestId("canvas-main");
const marks = (page: Page, panel: string) => page.evaluate(([id]) => {
  const layer = (window as unknown as { __tjMarks: Map<string, Marks> }).__tjMarks.get(id)!;
  return { labels: layer.drawnLabels(), clusters: layer.clusters(), fills: layer.fillBoxes() };
}, [panel]);
/** Bring the busy stretch of 5m candles into view, so the pictures show the marks. */
const focusDense = (page: Page, dense: Dense) => {
  const bars = dense.panels["5m"]!.bars;
  return page.evaluate(([from, to]) => (window as unknown as { __tjCharts: Map<string, Chart> }).__tjCharts.get("main")!.timeScale().setVisibleRange({ from, to }), [bars.at(-75)!.time, bars.at(-6)!.time]);
};
const layerGroup = (page: Page, name: string) => page.getByRole("region", { name: "Layers" }).getByRole("group", { name }).first();
const tip = (page: Page) => page.getByRole("tooltip", { name: "Fill summary" });

test("a crowded day: one chevron per candle per side with the right count, hover lists every fill, labels off, news clustered", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  const { dense } = await open(page, context);
  await focusDense(page, dense);
  const five = dense.panels["5m"]!;
  const crowded = five.bars.at(-40)!.time;
  const rawFills = five.markers.length;
  // The raw fills are all there (the chart's own count), and they are drawn as one marker per candle per side.
  await expect(main(page)).toHaveAttribute("data-markers", String(rawFills));
  const groupsOf = (await main(page).getAttribute("data-fill-marks"))!.split(",").map((part) => part.split(":"));
  expect(groupsOf.reduce((sum, [, , n]) => sum + Number(n), 0)).toBe(rawFills);
  expect(new Set(groupsOf.map(([t, side]) => `${t}:${side}`)).size).toBe(groupsOf.length);
  expect(groupsOf).toContainEqual([String(crowded), "buy", "3"]);
  expect(groupsOf).toContainEqual([String(crowded), "sell", "1"]);
  expect(groupsOf.length).toBeLessThan(rawFills);
  // No text by default.
  await expect(main(page)).toHaveAttribute("data-fill-labels", "off");
  await expect.poll(async () => (await marks(page, "main")).fills.length).toBeGreaterThan(3);
  expect((await marks(page, "main")).labels).toEqual([]);

  // Hover the merged buy: every fill in it is listed.
  const box = (await main(page).boundingBox())!;
  const buy = (await marks(page, "main")).fills.find((f) => f.buy && f.count === 3)!;
  await page.mouse.move(box.x + buy.x, box.y + buy.y + 5);
  await expect(tip(page)).toBeVisible();
  await expect(tip(page)).toContainText("3 buys");
  expect(await tip(page).getByRole("listitem").allTextContents()).toEqual(["buy to open 1 call", "buy to open 3 call", "buy to open 2 call"]);
  // A single fill still reads on one line.
  const single = (await marks(page, "main")).fills.find((f) => !f.buy && f.count === 1 && f.id.startsWith(`${crowded}`))!;
  await page.mouse.move(box.x + single.x, box.y + single.y - 5);
  await expect(tip(page)).toContainText("sell to close 1 call");

  // News: stories on neighbouring candles are one marker with a count; hovering it lists every headline.
  // (Only the stories in view are drawn: the older ones are off to the left.)
  const shown = five.bars.at(-75)!.time;
  await expect(main(page)).toHaveAttribute("data-news", /\d+:\d+/); // the news read lands after the candles
  const stories = (await main(page).getAttribute("data-news"))!.split(",").map((part) => part.split(":").map(Number)).filter(([time]) => time >= shown).map(([, n]) => n);
  const total = stories.reduce((a, b) => a + b, 0);
  await expect.poll(async () => (await marks(page, "main")).clusters.reduce((sum, c) => sum + c.count, 0)).toBe(total);
  const { clusters } = await marks(page, "main");
  expect(clusters.length).toBeLessThan(stories.length);
  const big = [...clusters].sort((a, b) => b.count - a.count)[0];
  expect(big.count).toBeGreaterThanOrEqual(2);
  await page.mouse.move(2, 2);
  await page.mouse.move(box.x + big.x, box.y + big.y);
  const news = page.getByRole("tooltip", { name: "News headlines" });
  await expect(news).toBeVisible();
  await expect(news).toContainText(`${big.count} headlines`);
  expect(await news.getByRole("listitem").count()).toBe(Math.min(big.count, 5));
  // The report date is on its candle.
  await expect(main(page)).toHaveAttribute("data-earnings", /2026-10-0\d@\d+/);

  await page.mouse.move(2, 2);
  await page.screenshot({ path: test.info().outputPath("markers-dense-desktop.png"), animations: "disabled" });
  expect(errors).toEqual([]);
});

test("Fill labels: Latest trade labels only the newest fills, All labels the rest; smaller charts never show text or news until asked", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { server, dense } = await open(page, context);
  await focusDense(page, dense);
  // Smaller charts: no news by default, no text ever.
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-news", "");
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-fill-marks", /buy|sell/);
  expect((await marks(page, "Panel 2")).clusters).toEqual([]);
  await page.getByRole("button", { name: "Layers", exact: true }).click();
  const journal = layerGroup(page, "Journal");
  await expect(journal.getByRole("button", { name: "Off", exact: true })).toHaveAttribute("aria-pressed", "true");
  await journal.getByRole("button", { name: "Latest trade" }).click();
  await expect(main(page)).toHaveAttribute("data-fill-labels", "latest");
  await expect.poll(async () => (await marks(page, "main")).labels).toEqual(["sell to close 100 stock"]); // the newest candle with fills
  await journal.getByRole("button", { name: "All", exact: true }).click();
  await expect(main(page)).toHaveAttribute("data-fill-labels", "all");
  await expect.poll(async () => (await marks(page, "main")).labels.length).toBeGreaterThan(2);
  const all = (await marks(page, "main")).labels;
  expect(all).toContain("sell to close 100 stock");
  expect(all).toContain("buy to open 100 stock");
  // No two labels are drawn on top of each other: the layer drops a crowded one (the hover still lists it).
  expect(new Set(all).size).toBeLessThanOrEqual(all.length);
  await page.screenshot({ path: test.info().outputPath("markers-dense-labels-desktop.png"), animations: "disabled" });
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-fill-labels", "off");
  expect((await marks(page, "Panel 2")).labels).toEqual([]);
  await expect.poll(() => server.data?.fillLabels).toBe("all");

  // News on small charts: a toggle in the News markers group, off until checked, and saved.
  const newsGroup = layerGroup(page, "News markers");
  const toggle = newsGroup.getByRole("checkbox", { name: "News on small charts" });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-news", /\d+:\d+/);
  await expect.poll(async () => (await marks(page, "Panel 2")).clusters.length).toBeGreaterThan(0);
  await expect.poll(() => server.data?.newsOnSmall).toBe(true);
  await toggle.uncheck();
  await expect(page.getByTestId("canvas-Panel 2")).toHaveAttribute("data-news", "");
  await journal.getByRole("button", { name: "Off", exact: true }).click();
  await expect(main(page)).toHaveAttribute("data-fill-labels", "off");
});

test("on a daily chart a candle's many fills are one chevron per side; the list opens on a click and picks a trade", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { dense } = await open(page, context);
  const daily = dense.panels["1D"]!;
  await page.getByLabel("Main interval").selectOption("1D");
  await expect(main(page)).toHaveAttribute("data-markers", String(daily.markers.length));
  await expect.poll(async () => (await main(page).getAttribute("data-fill-marks"))?.split(",").length).toBeLessThan(daily.markers.length / 2);
  const counts = (await main(page).getAttribute("data-fill-marks"))!.split(",").map((part) => Number(part.split(":")[2]));
  expect(counts.reduce((a, b) => a + b, 0)).toBe(daily.markers.length);
  expect(Math.max(...counts)).toBeGreaterThanOrEqual(3);
  await page.mouse.move(2, 2);
  await page.screenshot({ path: test.info().outputPath("markers-dense-1d-desktop.png"), animations: "disabled" });
  const pick = (await marks(page, "main")).fills.filter((f) => f.count >= 3).at(-1)!;
  const box = (await main(page).boundingBox())!;
  let opened = "";
  await page.route("**/api/backend/charts/journal/fills/*", (route) => { opened = route.request().url(); return route.abort(); });
  await page.mouse.click(box.x + pick.x, box.y + pick.y + (pick.buy ? 5 : -5));
  const list = page.getByRole("dialog", { name: "Fill summary" });
  await expect(list).toBeVisible();
  expect(await list.getByRole("button").count()).toBe(pick.count + 1); // every fill, and Close
  await list.getByRole("button").first().click();
  await expect.poll(() => opened).toContain("/journal/fills/fill-");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("fills are chevrons on the main chart and plain dots on the small ones, no text and no news there; a tap lists a merged candle's fills", async ({ page, context }) => {
    const { dense } = await open(page, context);
    await focusDense(page, dense);
    await expect.poll(async () => (await marks(page, "main")).fills.length).toBeGreaterThan(3);
    expect((await marks(page, "main")).labels).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: test.info().outputPath("markers-dense-phone.png"), animations: "disabled", fullPage: true });
    // Small charts: dots and no text, no news.
    for (const name of ["Panel 2", "Panel 3", "Panel 4", "Panel 5"]) {
      await expect(page.getByTestId(`canvas-${name}`)).toHaveAttribute("data-news", "");
      expect((await marks(page, name)).labels).toEqual([]);
    }
    // A tap on the merged buy lists its fills.
    const buy = (await marks(page, "main")).fills.find((f) => f.buy && f.count === 3)!;
    const box = (await main(page).boundingBox())!;
    await page.touchscreen.tap(box.x + buy.x, box.y + buy.y + 5);
    const list = page.getByRole("dialog", { name: "Fill summary" });
    await expect(list).toBeVisible();
    await expect(list).toContainText("3 buys");
    expect(await list.getByRole("button").count()).toBe(4);
    await list.getByRole("button", { name: "Close" }).tap();
    await expect(list).toHaveCount(0);
  });
});
