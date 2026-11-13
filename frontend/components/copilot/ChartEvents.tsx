"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type { IChartApi, Logical } from "lightweight-charts";
import type { DeskChartData, DeskChartEvents } from "@/lib/desk";
import { cn } from "@/lib/utils";

/**
 * Known events on the desk chart's date axis (``desk_events.chart``): the symbol's next and most recent earnings, and on
 * SPY, QQQ and IWM the macro days (FOMC, CPI, jobs), faint. A date on the candles shown sits on its day's first candle;
 * a date ahead sits where its day would be, counting weekdays at a session's candles per day; one past the right edge
 * pins there with an arrow. Earnings dates have no time of day (the calendar publishes none), so none is claimed.
 */

const ET = "America/New_York";
const nyDate = new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" });
const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });
const LONG = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const SHORT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
/** The New York date of an epoch-seconds time. */
export const nyDayOf = (seconds: number) => nyDate.format(seconds * 1000);
const noon = (iso: string) => new Date(`${iso}T12:00:00Z`);
const MACRO_WORD = { fomc: "FOMC", cpi: "CPI", jobs: "Jobs" } as const;
const REGULAR_SECONDS = 390 * 60;

export type ChartEvent = { key: string; kind: "earnings" | "last" | "macro"; date: string; chip: string; lines: string[] };

/** "Thu" within the coming week, else "Nov 20". */
function near(iso: string, today: string): string {
  const days = Math.round((noon(iso).getTime() - noon(today).getTime()) / 86_400_000);
  return days === 0 ? "today" : days > 0 && days < 7 ? WEEKDAY.format(noon(iso)) : SHORT.format(noon(iso));
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

/** The events as chips with their hover lines, next earnings first. */
export function chartEvents(events: DeskChartEvents | undefined, today: string): ChartEvent[] {
  if (!events) return [];
  const out: ChartEvent[] = [];
  const next = events.earnings?.next;
  if (next) {
    const implied = next.implied?.percent != null
      ? `Options price a ±${percent(next.implied.percent)}${next.implied.move != null ? ` ($${next.implied.move.toFixed(2)})` : ""} move by the ${SHORT.format(noon(next.implied.expiration))} expiry.`
      : null;
    out.push({ key: `er:${next.date}`, kind: "earnings", date: next.date, chip: `ER ${near(next.date, today)}${next.status === "estimated" ? "?" : ""}`,
      lines: [`Earnings ${LONG.format(noon(next.date))}${next.label ? ` · ${next.label}` : ""}`,
        next.status === "estimated" ? "Estimated date, not yet confirmed." : "Confirmed date.",
        "Time of day not published.", ...(implied ? [implied] : [])] });
  }
  const last = events.earnings?.last;
  if (last) out.push({ key: `er-last:${last.date}`, kind: "last", date: last.date, chip: "ER",
    lines: [`Last earnings ${LONG.format(noon(last.date))}${last.label ? ` · ${last.label}` : ""}`] });
  for (const m of events.macro ?? []) {
    out.push({ key: `macro:${m.kind}:${m.date}`, kind: "macro", date: m.date, chip: MACRO_WORD[m.kind] ?? m.kind,
      lines: [`${m.name} · ${LONG.format(noon(m.date))} ${m.time} ET`] });
  }
  return out;
}

/** Weekdays after ``from`` through ``to`` (both New York dates). */
function weekdaysBetween(from: string, to: string): number {
  let count = 0;
  for (let d = noon(from).getTime() + 86_400_000; d <= noon(to).getTime(); d += 86_400_000) {
    const day = new Date(d).getUTCDay();
    if (day !== 0 && day !== 6) count += 1;
  }
  return count;
}

/** Where ``date`` falls on the candles, as a logical index: its day's first candle; past the last candle, a session's
 * candles per weekday ahead; null before the first candle or on a day the candles skip. */
export function eventLogical(data: Pick<DeskChartData, "bars" | "step" | "timeframe">, date: string): number | null {
  const bars = data.bars;
  if (!bars.length) return null;
  const days = bars.map(b => nyDate.format(b.time * 1000));
  const first = days[0], last = days[days.length - 1];
  if (date < first) return null;
  if (date <= last) {
    const i = days.indexOf(date);
    return i < 0 ? null : i;
  }
  const ahead = weekdaysBetween(last, date);
  if (data.timeframe === "1D") return bars.length - 1 + ahead;
  // Intraday: from the last day's last regular candle to the end of its session (its after-hours candles already sit
  // past it), whole sessions between, then the day's first candle.
  const perDay = Math.max(1, Math.round(REGULAR_SECONDS / data.step));
  let anchor = bars.length - 1;
  while (anchor > 0 && days[anchor] === last && bars[anchor].extended) anchor -= 1;
  const regular = bars.filter((b, i) => days[i] === last && !b.extended).length;
  return Math.max(bars.length, anchor + Math.max(0, perDay - regular) + (ahead - 1) * perDay + 1);
}

type Placed = ChartEvent & { x: number | null; pinned: boolean };

/** The chips over the chart: on the date axis, each with its lines on hover, focus or tap. */
export function ChartEventMarks({ chart, data }: { chart: IChartApi | null; data: DeskChartData | null }) {
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const today = data ? nyDate.format(data.as_of * 1000) : "";
  const items = useMemo(() => data ? chartEvents(data.events, today) : [], [data, today]);
  useEffect(() => {
    if (!chart || !items.length) return;
    const bump = () => setVersion(v => v + 1);
    const scale = chart.timeScale();
    scale.subscribeVisibleLogicalRangeChange(bump);
    scale.subscribeSizeChange(bump);
    bump();
    return () => { scale.unsubscribeVisibleLogicalRangeChange(bump); scale.unsubscribeSizeChange(bump); };
  }, [chart, items]);
  const placed = useMemo<Placed[]>(() => {
    void version;
    if (!chart || !data) return [];
    const scale = chart.timeScale();
    const width = scale.width();
    return items.map(item => {
      const logical = eventLogical(data, item.date);
      const x = logical === null ? null : scale.logicalToCoordinate(logical as Logical);
      return { ...item, x: x === null || x < 0 ? null : x, pinned: x !== null && x > width };
    });
  }, [chart, data, items, version]);
  if (!chart || !data || !placed.length) return null;
  const axis = chart.timeScale().height();
  // Past the right edge: the next earnings, and the nearest macro day, pinned with an arrow.
  const pinned = [placed.find(p => p.pinned && p.kind === "earnings"), placed.find(p => p.pinned && p.kind === "macro")].filter((p): p is Placed => !!p);
  const onAxis = placed.filter(p => p.x !== null && !p.pinned);
  const tip = placed.find(p => p.key === open);
  const chip = (p: Placed, style: CSSProperties, arrow = false) => (
    <button key={p.key} type="button" data-testid="desk-chart-event" data-kind={p.kind} data-date={p.date} data-pinned={arrow ? "true" : "false"}
      aria-label={p.lines.join(" ")} aria-expanded={open === p.key}
      onClick={() => setOpen(o => o === p.key ? null : p.key)}
      onMouseEnter={() => setOpen(p.key)} onMouseLeave={() => setOpen(o => o === p.key ? null : o)}
      onFocus={() => setOpen(p.key)} onBlur={() => setOpen(o => o === p.key ? null : o)}
      className={cn("pointer-events-auto absolute z-10 rounded border px-1 text-[10px] leading-4 tabular-nums",
        p.kind === "earnings" && "border-sky-300/60 bg-background/90 text-sky-200",
        p.kind === "last" && "border-sky-300/25 bg-background/80 text-sky-200/60",
        p.kind === "macro" && "border-foreground/10 bg-background/70 text-muted-foreground/70")}
      style={style}>
      {p.chip}{arrow ? " →" : ""}
    </button>
  );
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden rounded" data-testid="desk-chart-events">
      {onAxis.map(p => chip(p, { left: p.x!, bottom: axis + 3, transform: "translateX(-50%)" }))}
      {pinned.map((p, i) => chip(p, { right: chart.priceScale("right").width() + 4, bottom: axis + 3 + i * 20 }, true))}
      {tip && (
        <div role="tooltip" data-testid="desk-chart-event-tip"
          className="absolute z-20 max-w-[min(18rem,85%)] rounded border bg-popover/95 px-2 py-1.5 text-xs shadow"
          style={{ bottom: axis + 24, ...(tip.pinned || (tip.x ?? 0) > chart.timeScale().width() / 2
            ? { right: tip.pinned ? chart.priceScale("right").width() + 4 : Math.max(8, chart.timeScale().width() - (tip.x ?? 0)) }
            : { left: Math.max(8, (tip.x ?? 0) - 8) }) }}>
          {tip.lines.map((line, i) => <p key={i} className={i === 0 ? "text-foreground" : "text-muted-foreground"}>{line}</p>)}
        </div>
      )}
    </div>
  );
}

/** The header's words for the next earnings: "Earnings Thu · ±5.2% implied", or null. */
export function earningsHeader(events: DeskChartEvents | undefined, asOf: number): string | null {
  const next = events?.earnings?.next;
  if (!next) return null;
  const today = nyDate.format(asOf * 1000);
  const implied = next.implied?.percent != null ? ` · ±${percent(next.implied.percent)} implied` : "";
  return `Earnings ${near(next.date, today)}${next.status === "estimated" ? " (est.)" : ""}${implied}`;
}
