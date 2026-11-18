"use client";

/**
 * Robinhood-style paper portfolio graph for the phone Paper home: latest equity, signed $/% change over the picked
 * range, inline SVG line with dashed baseline, and 1D / 1W / 1M / All range selector. Self-contained and not wired in yet.
 */

import { useState } from "react";
import { cn } from "@/lib/utils";

export type PortfolioPoint = { t: number; equity: number };
type Range = "1D" | "1W" | "1M" | "All";

const RANGES: readonly Range[] = ["1D", "1W", "1M", "All"];
const DAY_SECONDS = 86_400;
const SVG_WIDTH = 320;
const SVG_HEIGHT = 120;
const PAD_Y = 8;

const NY_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const nyDay = (epochSeconds: number) => NY_DAY.format(new Date(epochSeconds * 1000));

const formatTimeET = (epochSeconds: number) =>
  `${new Date(epochSeconds * 1000).toLocaleTimeString("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  })} ET`;

const usd = (n: number) =>
  `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const formatEquity = (n: number) => `${Math.round(n * 100) < 0 ? "−" : ""}${usd(n)}`;

function formatChange(delta: number, baseline: number): { text: string; up: boolean } {
  const rounded = Math.round(delta * 100) / 100;
  const zero = rounded === 0;
  const up = rounded >= 0;
  const sign = zero ? "+" : rounded > 0 ? "+" : "−";
  const pct = baseline !== 0 ? (delta / Math.abs(baseline)) * 100 : null;
  const pctRounded = pct != null ? Math.round(pct * 100) / 100 : null;
  const pctText =
    pctRounded != null
      ? ` (${pctRounded === 0 ? "+" : pctRounded > 0 ? "+" : "−"}${Math.abs(pctRounded).toFixed(2)}%)`
      : "";
  return { text: `${sign}${usd(rounded)}${pctText}`, up };
}

function filterRange(sorted: PortfolioPoint[], range: Range): PortfolioPoint[] {
  if (sorted.length === 0 || range === "All") return sorted;
  const latestT = sorted[sorted.length - 1].t;
  if (range === "1D") {
    const day = nyDay(latestT);
    return sorted.filter(p => nyDay(p.t) === day);
  }
  const cutoff = latestT - (range === "1W" ? 7 : 30) * DAY_SECONDS;
  return sorted.filter(p => p.t >= cutoff);
}

export default function PortfolioGraph({
  points,
  start,
  asOf,
  stale = false,
  label = "Paper",
  className,
}: {
  points: { t: number; equity: number }[];
  start: number;
  asOf: number | null;
  stale?: boolean;
  label?: string;
  className?: string;
}) {
  const [range, setRange] = useState<Range>("1D");

  const sorted = [...points].sort((a, b) => a.t - b.t);
  const filtered = filterRange(sorted, range);
  const latestPoint = sorted.length > 0 ? sorted[sorted.length - 1] : null;
  const latestEquity = latestPoint ? latestPoint.equity : start;

  const hasChart = filtered.length >= 2;
  const baseline =
    range === "All"
      ? start
      : hasChart
        ? filtered[0].equity
        : null;

  const change =
    baseline != null && latestPoint != null
      ? formatChange(latestEquity - baseline, baseline)
      : null;

  const tone = stale
    ? "text-muted-foreground"
    : change
      ? change.up
        ? "text-emerald-300"
        : "text-rose-300"
      : "text-muted-foreground";

  let polylinePoints = "";
  let baselineY = SVG_HEIGHT / 2;
  if (hasChart && baseline != null) {
    const tMin = filtered[0].t;
    const tMax = filtered[filtered.length - 1].t;
    const tSpan = tMax - tMin;
    const values = [...filtered.map(p => p.equity), baseline];
    const yMin = Math.min(...values);
    const yMax = Math.max(...values);
    const ySpan = yMax - yMin;

    const xOf = (t: number, i: number) =>
      tSpan > 0
        ? ((t - tMin) / tSpan) * SVG_WIDTH
        : (i / (filtered.length - 1)) * SVG_WIDTH;
    const yOf = (v: number) =>
      ySpan > 0
        ? PAD_Y + ((yMax - v) / ySpan) * (SVG_HEIGHT - 2 * PAD_Y)
        : SVG_HEIGHT / 2;

    polylinePoints = filtered
      .map((p, i) => `${xOf(p.t, i).toFixed(1)},${yOf(p.equity).toFixed(1)}`)
      .join(" ");
    baselineY = yOf(baseline);
  }

  const lineTone = change?.up !== false ? "text-emerald-300" : "text-rose-300";
  const ariaSummary = change
    ? `${label} portfolio over ${range}: ${formatEquity(latestEquity)}, ${change.text}${stale && asOf != null ? `, as of ${formatTimeET(asOf)}` : ""}`
    : `${label} portfolio over ${range}: ${formatEquity(latestEquity)}`;

  return (
    <section
      aria-label={`${label} portfolio graph`}
      className={cn("rounded-lg border border-dashed border-violet-400/40 bg-card p-3", className)}
    >
      <div className="flex items-center gap-2">
        <span className="inline-flex shrink-0 items-center rounded border border-dashed border-violet-400/70 px-1 text-[10px] font-semibold uppercase leading-4 tracking-wide text-violet-200">
          {label}
        </span>
      </div>

      <p
        className={cn(
          "mt-1 text-[28px] font-semibold leading-8 tabular-nums tracking-tight",
          stale ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {formatEquity(latestEquity)}
      </p>

      <p className={cn("mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-xs tabular-nums", tone)}>
        <span>{change ? change.text : "—"}</span>
        <span className="text-[11px] text-muted-foreground">{range}</span>
        {stale && asOf != null && (
          <span className="text-[11px] text-muted-foreground">as of {formatTimeET(asOf)}</span>
        )}
      </p>

      {hasChart ? (
        <svg
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={ariaSummary}
          className="mt-2 h-[120px] w-full"
        >
          <line
            x1={0}
            x2={SVG_WIDTH}
            y1={baselineY}
            y2={baselineY}
            stroke="currentColor"
            strokeOpacity={0.25}
            strokeWidth={1}
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
            className="text-muted-foreground"
          />
          <polyline
            points={polylinePoints}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            className={lineTone}
          />
        </svg>
      ) : (
        <div className="mt-2 flex h-[120px] items-center justify-center">
          <p className="text-xs text-muted-foreground">No paper history yet</p>
        </div>
      )}

      <div role="radiogroup" aria-label="Portfolio range" className="mt-2 inline-flex rounded-md border text-xs">
        {RANGES.map(r => (
          <button
            key={r}
            type="button"
            role="radio"
            aria-checked={range === r}
            onClick={() => setRange(r)}
            className={cn(
              "min-h-11 px-3 font-medium first:rounded-l-md last:rounded-r-md sm:min-h-8",
              range === r
                ? "bg-violet-400/15 text-violet-100"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {r}
          </button>
        ))}
      </div>
    </section>
  );
}
