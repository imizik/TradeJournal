import { barAt, gapSeconds } from "./charts";
import type { ChartBar, Interval } from "./charts";
import type { NewsArticle } from "./symbolInfo";

/** One news marker (T3.5): the candle it sits on (`time` is that candle's start) and the Focused articles attached to it, newest first. */
export type NewsMark = { id: string; time: number; articles: NewsArticle[] };

/** How many headlines a marker's hover lists before "+N more". */
export const NEWS_TIP_LINES = 5;

/**
 * The candle an article published at `at` (epoch seconds) belongs to, or undefined.
 *
 * - The candle whose bucket holds the time (`barAt`). Daily and weekly candles are
 *   regular sessions (09:30 to 16:00 New York), so a 1D bucket is a session, not a UTC day.
 * - In a gap (overnight, weekend, holiday, outside the displayed session) it is the
 *   next candle after it: the first moment the market could react.
 * - After the last candle it is the last candle.
 * - Before the first loaded candle it has none.
 *
 * Candles carry their own epoch times, so New York's daylight saving shift needs no
 * calendar maths here. A "gap" wider than the chart's ordinary step (`gapSeconds`:
 * 5 days intraday, 10 for 1D, 21 for 1W) is a hole in the loaded history, not a
 * closed market, so an article inside one has no candle either; the same bound keeps
 * a stale last candle from collecting days of news.
 */
export function newsBar(bars: ChartBar[], at: number, interval: Interval): ChartBar | undefined {
  const held = barAt(bars, at);
  if (held) return held;
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time <= at) low = mid + 1; else high = mid; }
  if (low === 0) return undefined; // before the first loaded candle
  const within = gapSeconds(interval);
  if (low === bars.length) { const last = bars[low - 1]; return at - last.end_time <= within ? last : undefined; }
  return bars[low].time - at <= within ? bars[low] : undefined;
}

/**
 * The Focused articles of a symbol as markers on `bars`, oldest candle first. Several
 * articles on one candle make one marker. A roundup (an article tagging more than
 * three symbols) is never marked, whatever the News tab's own Focused toggle says.
 */
export function newsMarks(bars: ChartBar[], articles: NewsArticle[], interval: Interval): NewsMark[] {
  if (!bars.length) return [];
  const byBar = new Map<number, NewsArticle[]>();
  for (const article of articles) {
    if (article.roundup) continue;
    const at = Date.parse(article.published_at) / 1000;
    if (!Number.isFinite(at)) continue;
    const bar = newsBar(bars, at, interval);
    if (!bar) continue;
    const held = byBar.get(bar.time);
    if (held) held.push(article); else byBar.set(bar.time, [article]);
  }
  return [...byBar].map(([time, held]) => ({ id: `news:${time}`, time,
    articles: held.sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at) || a.id.localeCompare(b.id)) }))
    .sort((a, b) => a.time - b.time);
}

/** The label drawn beside a marker: "N" for one article, "N3" for three. */
export const newsLabel = (mark: NewsMark) => mark.articles.length > 1 ? `N${mark.articles.length}` : "N";
/** The headlines a marker's hover lists, newest first, and how many more there are. */
export const newsTip = (mark: NewsMark) => ({ lines: mark.articles.slice(0, NEWS_TIP_LINES).map((article) => article.headline), more: Math.max(0, mark.articles.length - NEWS_TIP_LINES) });

/**
 * Several candles' markers drawn as one. `x` is where it sits (the members' mean), `time` the first member's candle and `last` the final one's;
 * `articles` are every member's, newest first.
 */
export type NewsCluster = { id: string; time: number; last: number; x: number; marks: number; articles: NewsArticle[] };

/**
 * Markers close together on screen become one with a count, so a run of stories on neighbouring candles reads as one event.
 * `placed` is oldest first with each marker's x in pixels; a cluster starts at its first marker and takes every later one within
 * `gap` pixels of it, so no cluster is wider than `gap` and the next one starts at least `gap` away. Same bar or nearby bars, whatever the zoom.
 */
export function clusterNews(placed: { mark: NewsMark; x: number }[], gap: number): NewsCluster[] {
  const out: NewsCluster[] = [];
  let run: { mark: NewsMark; x: number }[] = [];
  const close = () => {
    if (!run.length) return;
    const articles = run.flatMap((item) => item.mark.articles).sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at) || a.id.localeCompare(b.id));
    const [first, last] = [run[0].mark, run[run.length - 1].mark];
    out.push({ id: `news:${first.time}:${last.time}:${articles.length}`, time: first.time, last: last.time, marks: run.length,
      x: run.reduce((sum, item) => sum + item.x, 0) / run.length, articles });
    run = [];
  };
  for (const item of placed) {
    if (run.length && item.x - run[0].x > gap) close();
    run.push(item);
  }
  close();
  return out;
}
