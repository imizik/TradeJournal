"use client";

/**
 * The Paper home's header (docs/copilot-lab.md § Paper home): the paper account's value big at the top, its change over
 * the picked range, the challenge's status line when a challenge is running, and the account's value over time (1D / 1W /
 * 1M / All) from ``GET /copilot/paper/equity``.
 *
 * The big number is the desk's live ``paperValue`` (the same prices as each position card); the line is the recorded
 * minutes plus that live value as its last point. A minute whose prices were missing is a gap and one whose prices were
 * old is drawn grey; a stale live value is grey with its time. Never a zero for "no price".
 */

import { useEffect, useState, type ReactNode } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { PAPER_EVENT, type EquityPoint, type EquityRange, type EquitySeries } from "@/lib/paperBook";
import { cn } from "@/lib/utils";

const RANGES: readonly EquityRange[] = ["1D", "1W", "1M", "ALL"];
const RANGE_WORD: Record<EquityRange, string> = { "1D": "Today", "1W": "Past week", "1M": "Past month", ALL: "All time" };
const W = 320;
const H = 120;
const PAD_Y = 8;

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const at = (epoch: number) => `${new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET`;

/** The series for ``range``: read on mount and on a range change, on the desk's shared minute and after each paper fill. */
export function usePaperEquity(range: EquityRange, on: boolean): { series: EquitySeries | null; failed: boolean } {
  const [series, setSeries] = useState<EquitySeries | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet(`/copilot/paper/equity?range=${range}`, controller.signal)
      .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); setSeries(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load);
    window.addEventListener(PAPER_EVENT, load);
    return () => { controller.abort(); stop(); window.removeEventListener(PAPER_EVENT, load); };
  }, [range, on]);
  return { series: series?.range === range ? series : null, failed };
}

type Segment = { points: string; grey: boolean };

/** The line as polylines: split at a missing price, and grey wherever either end of a step is stale. */
function segments(points: EquityPoint[], x: (t: number) => number, y: (v: number) => number): Segment[] {
  const out: { xy: string[]; grey: boolean }[] = [];
  const xy = (p: EquityPoint) => `${x(p.at).toFixed(1)},${y(p.equity!).toFixed(1)}`;
  let prev: EquityPoint | null = null;
  let current: { xy: string[]; grey: boolean } | null = null;
  for (const p of points) {
    if (p.equity == null) { prev = null; current = null; continue; }
    if (prev) {
      const grey = prev.stale || p.stale;
      if (!current || current.grey !== grey) { current = { xy: [xy(prev)], grey }; out.push(current); }
      current.xy.push(xy(p));
    }
    prev = p;
  }
  return out.map(s => ({ points: s.xy.join(" "), grey: s.grey }));
}

export default function PortfolioGraph({ value, unpriced = 0, series, failed = false, range, onRange, status = null, className }: {
  /** The desk's live account value (``paperValue``), or null when a position has no price at all. */
  value: { value: number; at: number | null; stale: boolean } | null;
  /** How many open positions have no price (when ``value`` is null). */
  unpriced?: number;
  series: EquitySeries | null; failed?: boolean;
  range: EquityRange; onRange(range: EquityRange): void;
  /** The challenge's status line, under the change. */
  status?: ReactNode;
  className?: string;
}) {
  const base = series?.base ?? null;
  const change = value && base ? Math.round((value.value - base.value) * 100) / 100 : null;
  const pct = change != null && base && base.value ? Math.round(change / Math.abs(base.value) * 10000) / 100 : null;
  const grey = !value || value.stale;
  const tone = grey || change == null || change === 0 ? "text-muted-foreground" : change > 0 ? "text-emerald-300" : "text-rose-300";

  const points: EquityPoint[] = [...(series?.points ?? [])];
  // A run that began inside the range starts the line at its starting cash; the live value is the line's last point.
  if (base && series?.run && base.at === series.run.started_at && (points.length === 0 || base.at < points[0].at))
    points.unshift({ at: base.at, equity: base.value, prices_at: null, stale: false });
  // The live value at its prices' time (a flat account's: the newest point's), never before the newest point.
  const liveAt = value ? Math.max(value.at ?? 0, points.at(-1)?.at ?? 0) : 0;
  if (value && liveAt > 0) points.push({ at: liveAt, equity: value.value, prices_at: value.at, stale: value.stale });
  const drawn = points.filter(p => p.equity != null);
  const hasLine = drawn.length >= 2;

  let lines: Segment[] = [];
  let baseY: number | null = null;
  if (hasLine) {
    const t0 = points[0].at, t1 = points[points.length - 1].at;
    const values = [...drawn.map(p => p.equity!), ...(base ? [base.value] : [])];
    const lo = Math.min(...values), hi = Math.max(...values);
    const x = (t: number) => t1 > t0 ? (t - t0) / (t1 - t0) * W : 0;
    const y = (v: number) => hi > lo ? PAD_Y + (hi - v) / (hi - lo) * (H - 2 * PAD_Y) : H / 2;
    lines = segments(points, x, y);
    baseY = base ? y(base.value) : null;
  }
  const lineTone = change != null && change < 0 ? "text-rose-300" : "text-emerald-300";

  return (
    <div data-testid="paper-home-header" className={cn("px-3 pb-2", className)}>
      <p data-testid="paper-value" className={cn("text-[28px] font-semibold leading-8 tabular-nums tracking-tight", grey ? "text-muted-foreground" : "text-foreground")}>
        {value ? usd(value.value) : <span className="text-base font-normal">Needs a live price for {unpriced} open</span>}
      </p>
      <p data-testid="paper-change" className={cn("mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-xs tabular-nums", tone)}>
        <span>{change != null ? `${signed(change)}${pct != null ? ` (${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(2)}%)` : ""}` : "—"}</span>
        <span className="text-muted-foreground">{RANGE_WORD[range]}</span>
        {value?.stale && value.at != null && <span className="text-[11px] text-muted-foreground">as of {at(value.at)}</span>}
      </p>
      {status}
      {hasLine ? (
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" data-testid="paper-graph"
          aria-label={`Paper account value, ${RANGE_WORD[range].toLowerCase()}${change != null ? `: ${signed(change)}` : ""}`} className="mt-2 h-[120px] w-full">
          {baseY != null && <line x1={0} x2={W} y1={baseY} y2={baseY} stroke="currentColor" strokeOpacity={0.3} strokeWidth={1} strokeDasharray="2 4"
            vectorEffect="non-scaling-stroke" className="text-muted-foreground" />}
          {lines.map((s, i) => (
            <polyline key={i} points={s.points} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
              vectorEffect="non-scaling-stroke" data-grey={s.grey || undefined} className={s.grey ? "text-muted-foreground/60" : lineTone} />
          ))}
        </svg>
      ) : (
        <div className="mt-2 flex h-[120px] items-center justify-center rounded-md border border-dashed border-border/60">
          <p className="px-3 text-center text-xs text-muted-foreground">
            {failed ? "The history could not be read; it reads again in a minute." : !series ? "Reading the history…" : "The line fills in a minute at a time while the market is open."}
          </p>
        </div>
      )}
      <div role="radiogroup" aria-label="Paper graph range" className="mt-2 flex text-xs">
        {RANGES.map(r => (
          <button key={r} type="button" role="radio" aria-checked={range === r} data-testid={`paper-range-${r}`} onClick={() => onRange(r)}
            className={cn("min-h-11 flex-1 rounded-md px-3 font-medium sm:min-h-8 sm:flex-none",
              range === r ? "bg-violet-400/15 text-violet-100" : "text-muted-foreground hover:bg-secondary hover:text-foreground")}>
            {r === "ALL" ? "All" : r}
          </button>
        ))}
      </div>
    </div>
  );
}
