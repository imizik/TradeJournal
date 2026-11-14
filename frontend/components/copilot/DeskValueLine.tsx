"use client";

/**
 * The day's account value line beside the account line (docs/robinhood-read-feed.md § The value line): total account value
 * through the session (or one account's, while the account line is narrowed to it), grey outside regular hours, the
 * day's fills as dots, and the change since the first reading in dollars and percent. Hover or tap: the high and low of
 * the day, the latest value, and every break with its times.
 *
 * Built only from the readings the app already took. A break (no reading for longer than the feed allows: feed off,
 * sign-in expired, app restarted, no desk open) is a gap in the line, never a straight line or a drop to zero. Before
 * the day's first reading: nothing.
 */

import { useId, useState } from "react";
import { money, signedPct, type DeskDayLine, type DeskValueSeries } from "@/lib/desk";
import { tone } from "@/components/copilot/Cockpit";
import { cn } from "@/lib/utils";

const ET = "America/New_York";
const W = 112;
const H = 26;
const PAD = 2;
const NEAR = 180; // a fill this close past a segment's end (one or two refreshes) sits on that end
const clock = (at: number) => new Date(at * 1000).toLocaleTimeString("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" });
const usd = (value: number) => `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

/** Where a fill sits on the line: on the segment its time falls in (between two readings, on the straight piece between
 * them), or on a segment's end a refresh or two away; else nowhere (inside a break, no reading tells its value). */
export function onLine(segments: [number, number][][], at: number): [number, number] | null {
  for (const s of segments) {
    const start = s[0][0], end = s[s.length - 1][0];
    if (at < start - NEAR || at > end + NEAR) continue;
    if (at <= start) return s[0];
    if (at >= end) return s[s.length - 1];
    const i = s.findIndex(p => p[0] >= at);
    const [a, b] = [s[i - 1], s[i]];
    return [at, a[1] + (b[1] - a[1]) * (at - a[0]) / (b[0] - a[0])];
  }
  return null;
}

export function DeskValueLine({ line, active }: { line: DeskDayLine | null | undefined; active: string | null }) {
  const [open, setOpen] = useState(false);
  const clip = useId().replace(/:/g, "");
  const series: DeskValueSeries | undefined = line?.series[active ?? "all"];
  if (!line || !series) return null;
  const { segments, first, last } = series;
  const lo = Math.min(first.at, line.open ?? first.at);
  const hi = Math.max(last.at, lo + 60); // the readings so far fill the width (a whole-day axis leaves the morning a sliver)
  const span = series.high.value - series.low.value;
  const [bottom, top] = span > 0 ? [series.low.value - span * 0.08, series.high.value + span * 0.08] : [series.low.value - 1, series.high.value + 1];
  const x = (at: number) => PAD + (W - 2 * PAD) * (at - lo) / (hi - lo);
  const y = (value: number) => PAD + (H - 2 * PAD) * (top - value) / (top - bottom);
  const path = (s: [number, number][]) => s.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const fills = line.fills.filter(f => !active || f.masked === active)
    .map(f => ({ ...f, point: onLine(segments, f.at) })).filter(f => f.point);
  const regular = line.open != null && line.close != null;
  const who = active ? series.label : "All accounts";
  const describe = `${who}: ${usd(last.value)} at ${clock(last.at)}, ${money(series.change)}${series.change_pct != null ? ` ${signedPct(series.change_pct, 1)}` : ""} since ${clock(first.at)}`;
  return (
    <div className="group/value relative shrink-0">
      <button type="button" data-testid="desk-value-line" aria-expanded={open} aria-label={`Account value today. ${describe}`}
        onClick={() => setOpen(o => !o)} onBlur={() => setOpen(false)}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-md px-1 text-xs hover:bg-secondary sm:min-h-0 sm:py-0.5">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden className="max-sm:w-24">
          {regular && <clipPath id={clip}><rect x={x(line.open!)} y={0} width={Math.max(0, x(line.close!) - x(line.open!))} height={H} /></clipPath>}
          <line x1={PAD} x2={W - PAD} y1={y(first.value)} y2={y(first.value)} className="stroke-muted-foreground/40" strokeDasharray="1 2" strokeWidth={1} />
          {segments.map((s, i) => (
            <g key={i} data-testid="value-segment">
              {/* Outside regular hours grey; inside it the day's tone. A lone reading is a dot. */}
              {s.length > 1 ? <path d={path(s)} fill="none" strokeWidth={1.25} className="stroke-muted-foreground/70" />
                : <circle cx={x(s[0][0])} cy={y(s[0][1])} r={1.25} className="fill-muted-foreground/70" />}
              {regular && (s.length > 1 ? <path d={path(s)} fill="none" strokeWidth={1.25} stroke="currentColor" clipPath={`url(#${clip})`} className={tone(series.change)} />
                : <circle cx={x(s[0][0])} cy={y(s[0][1])} r={1.25} fill="currentColor" clipPath={`url(#${clip})`} className={tone(series.change)} />)}
            </g>
          ))}
          {fills.map((f, i) => (
            <circle key={i} data-testid="value-fill" cx={x(f.point![0])} cy={y(f.point![1])} r={2} className="fill-foreground stroke-background" strokeWidth={0.75}>
              <title>{`${clock(f.at)} ${f.text}`}</title>
            </circle>
          ))}
        </svg>
        <span data-testid="value-change" className={cn("tabular-nums", tone(series.change))}>
          {money(series.change)}{series.change_pct != null && ` ${signedPct(series.change_pct, 1)}`}
        </span>
        <span className="tabular-nums text-[11px] text-muted-foreground max-sm:hidden">since {clock(first.at)}</span>
        {series.quiet_since != null && <span data-testid="value-quiet" className="tabular-nums text-[11px] text-muted-foreground">· last {clock(series.quiet_since)}</span>}
      </button>
      <div role="tooltip" data-testid="value-detail" className={cn("absolute left-0 top-full z-50 mt-1 w-60 rounded-md border bg-card p-2 text-xs shadow-md",
        open ? "block" : "hidden group-hover/value:block")}>
        <p className="font-medium">{who} today</p>
        <p className="tabular-nums">{usd(last.value)} <span className="text-muted-foreground">at {clock(last.at)}</span></p>
        <p className="tabular-nums"><span className={tone(series.change)}>{money(series.change)}{series.change_pct != null && ` ${signedPct(series.change_pct, 2)}`}</span>
          <span className="text-muted-foreground"> since {clock(first.at)}</span></p>
        <p data-testid="value-high-low" className="tabular-nums">
          <span className="text-muted-foreground">High </span>{usd(series.high.value)}<span className="text-muted-foreground"> at {clock(series.high.at)}</span>
          <br /><span className="text-muted-foreground">Low </span>{usd(series.low.value)}<span className="text-muted-foreground"> at {clock(series.low.at)}</span>
        </p>
        {series.breaks.map(b => (
          <p key={b.from} data-testid="value-break" className="tabular-nums text-muted-foreground">No readings {clock(b.from)}–{clock(b.to)}</p>
        ))}
        {series.quiet_since != null && <p className="tabular-nums text-muted-foreground">No reading since {clock(series.quiet_since)}</p>}
        <p className="mt-1 text-[11px] text-muted-foreground">From the app&apos;s own reads of Robinhood. Grey: outside regular hours. Dots: fills.</p>
      </div>
    </div>
  );
}
