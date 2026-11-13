"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi, UTCTimestamp } from "lightweight-charts";
import { CONTEXT_MAX } from "@/lib/copilot";
import { DESK_MARKET, getDeskChartNews, type DeskChartData, type DeskChartNews, type DeskNewsGroup, type DeskNewsItem, type DeskTimeframe } from "@/lib/desk";
import { cn } from "@/lib/utils";

/**
 * The selected symbol's headlines on the desk chart (``desk_news.build``): a small marker along the top of the candles at
 * the candle where each was published, one per group (the server groups headlines a few minutes apart; markers closer
 * than ``MERGE_PX`` at the current zoom merge too). Amber when a headline came within a few minutes of a move well
 * beyond the day's typical candle; a move with no headline gets nothing. Hover, focus or tap opens the headlines with
 * their publisher, time and a link out, and Ask hands one with its move to the copilot. Intraday charts only.
 */

const ET = "America/New_York";
const MERGE_PX = 18;
const CLOSE_MS = 250;
const clock = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" });

/** "10:05 ET" on ``today``'s New York date, "Oct 20 10:05 ET" another day. */
export function newsWhen(seconds: number, today: number): string {
  const sameDay = dayFmt.format(seconds * 1000) === dayFmt.format(today * 1000);
  return `${sameDay ? "" : `${dayFmt.format(seconds * 1000)} `}${clock.format(seconds * 1000)} ET`;
}

const signed = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;

/** The move line under an emphasised marker: "Moved +2.4% 10:26–10:32 ET (range 2.6%)". */
export function moveLine(move: NonNullable<DeskNewsGroup["move"]>, today: number): string {
  return `Moved ${signed(move.pct)} ${newsWhen(move.start, today).replace(/ ET$/, "")}–${clock.format(move.end * 1000)} ET (range ${move.range_pct.toFixed(1)}%)`;
}

/** The context line Ask hands the copilot: the headline as quoted data, when and where it sits, and the move beside it
 * when there was one. The headline is shortened (never the question) to fit ``CONTEXT_MAX``. */
export function newsQuestion(symbol: string, timeframe: DeskTimeframe, item: DeskNewsItem, group: DeskNewsGroup, today: number): string {
  const when = `${newsWhen(item.at, today)}${item.session !== "regular" ? `, ${item.session}` : ""}`;
  const where = group.move
    ? ` ${symbol} moved ${signed(group.move.pct)} ${newsWhen(group.move.start, today).replace(/ ET$/, "")}–${clock.format(group.move.end * 1000)} ET on the ${timeframe} chart, well beyond its typical candle.`
    : ` On the ${timeframe} chart at the ${newsWhen(group.time, today)} candle.`;
  const head = `${symbol} headline (${item.source}, ${when}): "`;
  const tail = `".${where} Did this headline move it, and does it touch my positions or plans?`;
  const room = CONTEXT_MAX - head.length - tail.length;
  const quoted = item.headline.length <= room ? item.headline : `${item.headline.slice(0, Math.max(0, room - 1)).trimEnd()}…`;
  return `${head}${quoted}${tail}`.slice(0, CONTEXT_MAX);
}

/** The headlines for the chart ``id`` on ``timeframe``, read again with each chart read shown (the server keeps one read
 * per symbol a few minutes). None while ``on`` is off, on the market chart, on 1D and while the chart has no candles. */
export function useChartNews(id: string, timeframe: DeskTimeframe, data: DeskChartData | null, on: boolean): DeskChartNews | null {
  const key = `${id}|${timeframe}`;
  const [news, setNews] = useState<{ key: string; body: DeskChartNews } | null>(null);
  const wanted = on && id !== DESK_MARKET && timeframe !== "1D" && !!data && data.timeframe === timeframe && data.state === "ok" && data.bars.length > 0;
  const asOf = data?.as_of ?? 0;
  useEffect(() => {
    if (!wanted) return;
    const controller = new AbortController();
    getDeskChartNews(id, timeframe, controller.signal)
      .then(body => setNews({ key, body: Array.isArray(body?.groups) ? body : { ...body, state: "unavailable", groups: [] } }))
      .catch(() => { /* the markers are extra: the last ones stand until a read succeeds */ });
    return () => controller.abort();
  }, [wanted, id, timeframe, key, asOf]);
  return wanted && news?.key === key ? news.body : null;
}

type Placed = DeskNewsGroup & { key: string; x: number };

/** Groups that sit closer than ``MERGE_PX`` at the current zoom as one marker at the first. */
export function mergeClose(groups: (DeskNewsGroup & { x: number })[]): Placed[] {
  const out: Placed[] = [];
  for (const g of [...groups].sort((a, b) => a.x - b.x)) {
    const last = out[out.length - 1];
    if (last && g.x - last.x < MERGE_PX) {
      const items = [...last.items, ...g.items].sort((a, b) => b.at - a.at);
      const move = [last.move, g.move].filter((m): m is NonNullable<typeof m> => !!m).sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))[0] ?? null;
      out[out.length - 1] = { ...last, items, count: last.count + g.count, emphasis: last.emphasis || g.emphasis, move };
    } else {
      out.push({ ...g, key: String(g.time) });
    }
  }
  return out;
}

export function ChartNewsMarks({ chart, news, symbol, timeframe, onAsk }: {
  chart: IChartApi | null; news: DeskChartNews | null; symbol: string; timeframe: DeskTimeframe;
  onAsk?(text: string): void;
}) {
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<{ key: string; pinned: boolean } | null>(null);
  const closing = useRef<number | null>(null);
  const groups = useMemo(() => news?.state === "ok" ? news.groups : [], [news]);
  useEffect(() => {
    if (!chart || !groups.length) return;
    const bump = () => setVersion(v => v + 1);
    const scale = chart.timeScale();
    scale.subscribeVisibleLogicalRangeChange(bump);
    scale.subscribeSizeChange(bump);
    bump();
    return () => { scale.unsubscribeVisibleLogicalRangeChange(bump); scale.unsubscribeSizeChange(bump); };
  }, [chart, groups]);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(null); };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open]);
  useEffect(() => () => { if (closing.current) window.clearTimeout(closing.current); }, []);
  const placed = useMemo<Placed[]>(() => {
    void version;
    if (!chart) return [];
    const scale = chart.timeScale();
    const width = scale.width();
    const onScreen = groups.flatMap(g => {
      const x = scale.timeToCoordinate(g.time as UTCTimestamp);
      return x === null || x < 0 || x > width ? [] : [{ ...g, x }];
    });
    return mergeClose(onScreen);
  }, [chart, groups, version]);
  if (!chart || !news || !placed.length) return null;
  const today = news.as_of;
  const width = chart.timeScale().width();
  const box = Math.min(320, Math.round(width * 0.92));  // beside the marker where it fits, never past the chart's edge
  const tip = open ? placed.find(p => p.key === open.key) : undefined;
  const keep = () => { if (closing.current) { window.clearTimeout(closing.current); closing.current = null; } };
  const leave = () => {
    keep();
    closing.current = window.setTimeout(() => setOpen(o => o && !o.pinned ? null : o), CLOSE_MS);
  };
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden rounded" data-testid="desk-chart-news" data-desk-news>
      {placed.map(p => (
        <button key={p.key} type="button" data-testid="desk-news-mark" data-desk-news data-time={p.time} data-emphasis={p.emphasis ? "true" : "false"}
          aria-label={`${p.count} headline${p.count === 1 ? "" : "s"} at ${newsWhen(p.time, today)}${p.emphasis ? ", beside a big move" : ""}`}
          aria-expanded={open?.key === p.key}
          onClick={() => { keep(); setOpen(o => o?.key === p.key && o.pinned ? null : { key: p.key, pinned: true }); }}
          onMouseEnter={() => { keep(); setOpen(o => o?.pinned ? o : { key: p.key, pinned: false }); }}
          onMouseLeave={leave}
          onFocus={() => { keep(); setOpen(o => o?.pinned ? o : { key: p.key, pinned: false }); }}
          className={cn("pointer-events-auto absolute top-1 z-10 flex h-4 min-w-4 -translate-x-1/2 items-center justify-center rounded-full border px-1 text-[9px] font-semibold leading-none",
            "before:absolute before:-inset-3 before:content-[''] sm:before:-inset-1",
            p.emphasis ? "border-amber-300 bg-amber-300/90 text-background shadow" : "border-sky-300/50 bg-background/85 text-sky-200/90 hover:border-sky-300")}
          style={{ left: p.x }}>
          {p.count > 1 ? p.count : "N"}
        </button>
      ))}
      {tip && <div aria-hidden className={cn("absolute bottom-0 top-5 w-px -translate-x-1/2", tip.emphasis ? "bg-amber-300/40" : "bg-sky-300/25")} style={{ left: tip.x }} />}
      {tip && (
        <div role="dialog" aria-label={`Headlines at ${newsWhen(tip.time, today)}`} data-testid="desk-news-tip" data-desk-news
          onMouseEnter={keep} onMouseLeave={leave}
          className="pointer-events-auto absolute top-6 z-20 max-h-[70%] overflow-y-auto rounded border bg-popover/95 p-2 text-xs shadow-lg"
          style={{ width: box, left: tip.x > width / 2 ? Math.max(4, tip.x - 14 - box) : Math.max(4, Math.min(tip.x + 14, width - box - 4)) }}>
          <div className="mb-1 flex items-start justify-between gap-2">
            <p className={cn("tabular-nums", tip.emphasis ? "text-amber-200" : "text-muted-foreground")}>
              {tip.move ? moveLine(tip.move, today) : `${tip.count} headline${tip.count === 1 ? "" : "s"}`}
            </p>
            <button type="button" aria-label="Close" onClick={() => setOpen(null)}
              className="-mr-1 -mt-1 min-h-11 min-w-11 rounded text-muted-foreground hover:text-foreground sm:min-h-6 sm:min-w-6">×</button>
          </div>
          <ul className="space-y-1.5">
            {tip.items.map(item => (
              <li key={item.url} data-testid="desk-news-item" className="space-y-0.5">
                <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className="block leading-snug text-foreground hover:underline">{item.headline}</a>
                <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground">
                  <span className="capitalize">{item.source}</span>
                  <span>· {newsWhen(item.at, today)}{item.session !== "regular" ? ` · ${item.session}` : ""}{item.before ? " (before this candle)" : ""}</span>
                  {onAsk && (
                    <button type="button" data-testid="desk-news-ask"
                      onClick={() => { setOpen(null); onAsk(newsQuestion(symbol, timeframe, item, tip, today)); }}
                      className="ml-auto min-h-11 rounded px-1.5 text-sky-200 hover:bg-secondary sm:min-h-0 sm:py-0.5">Ask</button>
                  )}
                </p>
              </li>
            ))}
          </ul>
          {tip.count > tip.items.length && <p className="mt-1 text-muted-foreground">{tip.count - tip.items.length} more not shown.</p>}
        </div>
      )}
    </div>
  );
}
