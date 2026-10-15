import type { Page } from "@playwright/test";
import type { ChartBar, ChartData, FillMarker, Interval } from "../../lib/charts";
import type { Earnings, NewsArticle } from "../../lib/symbolInfo";
import { realisticPanels } from "./realisticBars";

/**
 * A deliberately crowded MRVL day for pictures of the fill, news and earnings markers: several fills on one 5m candle,
 * neighbouring candles with fills, daily candles with six to eight fills each, and news stories on nearby candles.
 * Candles are the seeded realistic session, so the same code always draws the same picture.
 */
export const DENSE_INTERVALS: Interval[] = ["5m", "15m", "1h", "1D", "1m"];

type Fill = { id: string; time: number; label: string; buy: boolean };

const CALL = (side: string, qty: number, kind = "call") => `${side} ${qty} ${kind}`;

/** The fills as the server sends them: each panel gets those inside its candles, stamped with the candle's start. */
function fillsFor(panels: ChartData["panels"]): Fill[] {
  const five = panels["5m"]!.bars;
  const daily = panels["1D"]!.bars;
  const at = (back: number) => five.at(-back)!.time + 20;
  const fills: Fill[] = [];
  const add = (time: number, label: string, buy: boolean) => fills.push({ id: `fill-${fills.length + 1}`, time, label, buy });
  // One 5m candle with four fills, both sides.
  add(at(40), CALL("buy to open", 1), true); add(at(40) + 30, CALL("buy to open", 3), true); add(at(40) + 60, CALL("buy to open", 2), true); add(at(40) + 90, CALL("sell to close", 1), false);
  // Neighbouring candles.
  add(at(37), CALL("sell to close", 2), false); add(at(37) + 40, CALL("sell to close", 1), false);
  add(at(34), CALL("buy to open", 1), true);
  add(at(31), "buy to open 100 stock", true);
  add(at(22), "sell to close 100 stock", false);
  // Daily candles with many fills each: they also stack on the hourly candles.
  daily.slice(-9, -1).forEach((bar, day) => {
    const count = 6 + (day % 3);
    for (let k = 0; k < count; k++) add(bar.time + 600 + k * 2400, CALL(k % 2 ? "sell to close" : "buy to open", 1 + (k % 3)), k % 2 === 0);
  });
  return fills;
}

export function markersOf(bars: ChartBar[], fills: Fill[]): FillMarker[] {
  const times = bars.map((bar) => bar.time);
  return fills.flatMap((fill) => {
    let low = 0, high = times.length;
    while (low < high) { const mid = (low + high) >>> 1; if (times[mid] <= fill.time) low = mid + 1; else high = mid; }
    const index = low - 1;
    return index >= 0 && fill.time < bars[index].end_time ? [{ ...fill, time: times[index] }] : [];
  });
}

export function denseNews(panels: ChartData["panels"]): NewsArticle[] {
  const five = panels["5m"]!.bars;
  const daily = panels["1D"]!.bars;
  const when = (time: number) => new Date((time + 25) * 1000).toISOString();
  const times = [five.at(-41)!.time, five.at(-40)!.time, five.at(-39)!.time, five.at(-38)!.time, five.at(-37)!.time, five.at(-12)!.time,
    ...daily.slice(-12, -1).map((bar) => bar.time + 3600)];
  return times.map((time, i) => ({ id: `n${i}`, provider: "alpaca_benzinga", publisher: "Benzinga", headline: `MRVL headline ${i + 1}: analysts react to the quarter`,
    url: `https://example.com/n${i}`, published_at: when(time), summary: null, tickers: ["MRVL"], roundup: false, sentiment: [], also_in: [] }));
}

export const DENSE_EARNINGS = (panels: ChartData["panels"]): Earnings => {
  const day = new Date(panels["5m"]!.bars.at(-130)!.time * 1000);
  const date = day.toISOString().slice(0, 10);
  return { state: "ready", source: "Tradier corporate calendar", fetched_at: Date.now() / 1000, message: null,
    next: null, reports: [{ date, label: "Q3 FY2026" }] };
};

export type Dense = { fills: Fill[]; panels: ChartData["panels"]; articles: NewsArticle[] };

/** Routes the workspace feed and the news read to the dense scenario; returns what it serves, for assertions. */
export async function routeDense(page: Page): Promise<Dense> {
  const base = realisticPanels(DENSE_INTERVALS);
  const fills = fillsFor(base);
  const panels: ChartData["panels"] = Object.fromEntries(DENSE_INTERVALS.map((interval) => [interval, { bars: base[interval]!.bars, markers: markersOf(base[interval]!.bars, fills) }]));
  const articles = denseNews(base);
  await page.route("**/api/backend/charts/workspace?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const now = Math.floor(Date.now() / 1000);
    const last = base["1D"]!.bars.at(-1)!.close;
    await route.fulfill({ json: { symbol: query.get("symbol"), session: "extended", provider: "Fixture", delayed: false, refresh_seconds: 15, checked_at: now,
      fetched_at: { intraday: now, quotes: now }, intraday_as_of: now, issues: [], fills: [], fills_truncated: false, extras: {}, earnings: DENSE_EARNINGS(base),
      history_note: "Synthetic", adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: now, splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] },
      quotes: [{ symbol: query.get("symbol"), name: "Marvell", instrument_type: "stock", last, change: 1, change_percentage: 1, volume: 1000, previous_close: last - 1, regular_close: last, trade_time: now }],
      panels } });
  });
  await page.route("**/api/backend/charts/stream?**", (route) => route.fulfill({ status: 503, body: "Fixture has no stream" }));
  await page.route("**/api/backend/charts/symbol/*/news", (route) => route.fulfill({ json: { symbol: "MRVL", as_of: new Date().toISOString(), time_zone: "America/New_York",
    days: 7, sentiment_note: "", sources: [], articles } }));
  await page.route("**/api/backend/charts/captures?**", (route) => route.fulfill({ json: { captures: [] } }));
  return { fills, panels, articles };
}
