"use client";

import { useState } from "react";
import type { Trade } from "@/lib/api";
import { formatHoldDuration } from "@/lib/dashboard";

type Period = "1D" | "1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL";

const PERIODS: Period[] = ["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"];
const PERIOD_LABEL: Record<Period, string> = {
  "1D": "Today",
  "1W": "1W",
  "1M": "1M",
  "3M": "3M",
  YTD: "YTD",
  "1Y": "1Y",
  ALL: "All-Time",
};

type ClosedTrade = Trade & { realized_pnl: number; closed_at: string };
type ChartPoint = { x: number; y: number; date: string; value: number };

function formatMoney(value: number | null, signed = true) {
  if (value == null || !Number.isFinite(value)) return "—";
  const amount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (!signed || value === 0) return value < 0 ? `-${amount}` : amount;
  return `${value > 0 ? "+" : "-"}${amount}`;
}

function startOfPeriod(period: Period, now: Date): number | null {
  const start = new Date(now);
  switch (period) {
    case "1D":
      start.setHours(0, 0, 0, 0);
      return start.getTime();
    case "1W":
      start.setDate(start.getDate() - 7);
      break;
    case "1M":
      start.setMonth(start.getMonth() - 1);
      break;
    case "3M":
      start.setMonth(start.getMonth() - 3);
      break;
    case "YTD":
      start.setMonth(0, 1);
      start.setHours(0, 0, 0, 0);
      return start.getTime();
    case "1Y":
      start.setFullYear(start.getFullYear() - 1);
      break;
    case "ALL":
      return null;
  }
  return start.getTime();
}

function shortMoney(value: number) {
  const rounded = Math.round(Math.abs(value));
  const amount = `$${new Intl.NumberFormat("en-US").format(rounded)}`;
  return value < 0 ? `-${amount}` : value > 0 ? `+${amount}` : "$0";
}

function axisDate(value: string) {
  const date = new Date(value);
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
}

function PerformanceChart({ trades }: { trades: ClosedTrade[] }) {
  if (trades.length === 0) {
    return (
      <div className="flex h-52 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
        No closed trades in this period.
      </div>
    );
  }

  const ordered = [...trades].sort(
    (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime(),
  );
  const series = [{ date: ordered[0].closed_at, value: 0 }];
  let cumulative = 0;
  for (const trade of ordered) {
    cumulative += trade.realized_pnl;
    series.push({ date: trade.closed_at, value: cumulative });
  }

  const width = 900;
  const height = 220;
  const left = 72;
  const right = 18;
  const top = 16;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = series.map((point) => point.value);
  const minValue = Math.min(0, ...values);
  const maxValue = Math.max(0, ...values);
  const valueSpan = maxValue - minValue || 1;
  const firstTime = new Date(series[0].date).getTime();
  const lastTime = new Date(series.at(-1)!.date).getTime();
  const timeSpan = lastTime - firstTime;
  const points: ChartPoint[] = series.map((point) => ({
    x: left + (timeSpan > 0 ? ((new Date(point.date).getTime() - firstTime) / timeSpan) * plotWidth : plotWidth / 2),
    y: top + ((maxValue - point.value) / valueSpan) * plotHeight,
    date: point.date,
    value: point.value,
  }));
  const zeroY = top + (maxValue / valueSpan) * plotHeight;
  const lineColor = values.at(-1)! >= 0 ? "text-emerald-400" : "text-red-400";
  const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
  const areaPath = `${linePath} L${points.at(-1)!.x},${zeroY} L${points[0].x},${zeroY} Z`;

  return (
    <svg
      aria-label="Cumulative P&L for closed trades by close date"
      className="h-52 w-full overflow-visible"
      role="img"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="realized-pnl-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.2" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.015" />
        </linearGradient>
      </defs>
      <line x1={left} x2={width - right} y1={zeroY} y2={zeroY} className="stroke-border" strokeDasharray="4 5" />
      <text x={left - 10} y={top + 4} textAnchor="end" className="fill-muted-foreground" fontSize="11">
        {shortMoney(maxValue)}
      </text>
      <text x={left - 10} y={top + plotHeight} textAnchor="end" className="fill-muted-foreground" fontSize="11">
        {shortMoney(minValue)}
      </text>
      <path d={areaPath} fill="url(#realized-pnl-fill)" className={lineColor} />
      <path d={linePath} fill="none" className={lineColor.replace("text-", "stroke-")} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
      {points.slice(1).map((point, index) => (
        <circle key={`${point.date}-${index}`} cx={point.x} cy={point.y} r="2.5" className={lineColor.replace("text-", "fill-")}>
          <title>{`${axisDate(point.date)} · ${formatMoney(point.value)}`}</title>
        </circle>
      ))}
      <text x={left} y={height - 5} className="fill-muted-foreground" fontSize="11">
        {axisDate(series[0].date)}
      </text>
      <text x={width - right} y={height - 5} textAnchor="end" className="fill-muted-foreground" fontSize="11">
        {axisDate(series.at(-1)!.date)}
      </text>
    </svg>
  );
}

function Metric({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

export default function PerformanceOverview({ trades }: { trades: Trade[] }) {
  const [period, setPeriod] = useState<Period>("ALL");
  const start = startOfPeriod(period, new Date());
  const periodTrades = trades.filter(
    (trade): trade is ClosedTrade =>
      trade.status !== "open" &&
      trade.realized_pnl != null &&
      trade.closed_at != null &&
      Number.isFinite(new Date(trade.closed_at).getTime()) &&
      (start == null || new Date(trade.closed_at).getTime() >= start),
  );
  const orderedTrades = [...periodTrades].sort(
    (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime(),
  );
  const totalPnl = periodTrades.reduce((sum, trade) => sum + trade.realized_pnl, 0);
  const winners = periodTrades.filter((trade) => trade.realized_pnl > 0);
  const losers = periodTrades.filter((trade) => trade.realized_pnl < 0);
  const grossProfit = winners.reduce((sum, trade) => sum + trade.realized_pnl, 0);
  const grossLoss = Math.abs(losers.reduce((sum, trade) => sum + trade.realized_pnl, 0));
  const profitFactor =
    grossLoss > 0 ? (grossProfit / grossLoss).toFixed(2) : grossProfit > 0 ? "∞" : "—";
  const expectancy = periodTrades.length > 0 ? totalPnl / periodTrades.length : null;
  let cumulative = 0;
  let peak = 0;
  let maxDrawdown = 0;
  for (const trade of orderedTrades) {
    cumulative += trade.realized_pnl;
    peak = Math.max(peak, cumulative);
    maxDrawdown = Math.min(maxDrawdown, cumulative - peak);
  }
  const avgWinner = winners.length > 0 ? grossProfit / winners.length : null;
  const avgLoser = losers.length > 0 ? losers.reduce((sum, trade) => sum + trade.realized_pnl, 0) / losers.length : null;
  const heldTrades = periodTrades.filter((trade) => trade.hold_duration_mins != null);
  const avgHold = heldTrades.length > 0
    ? heldTrades.reduce((sum, trade) => sum + (trade.hold_duration_mins ?? 0), 0) / heldTrades.length
    : null;

  return (
    <section aria-labelledby="performance-heading" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="performance-heading" className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Trading Performance
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">Closed trades in the selected period</p>
        </div>
        <div className="flex rounded-full border bg-card p-1" aria-label="Performance period">
          {PERIODS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={period === option}
              onClick={() => setPeriod(option)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                period === option
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4 sm:p-5">
        <div className="mb-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {PERIOD_LABEL[period]}{" "}Closed P&amp;L
          </p>
          <p className={`mt-1 text-3xl font-semibold tabular-nums sm:text-4xl ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {formatMoney(totalPnl)}
          </p>
        </div>
        <PerformanceChart trades={periodTrades} />
        <p className="mt-2 text-xs text-muted-foreground">
          Cumulative P&amp;L from closed trades. Open positions and their partial realized P&amp;L are excluded; this is not account equity or an investment return adjusted for cash flow.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Win Rate" value={periodTrades.length ? `${((winners.length / periodTrades.length) * 100).toFixed(1)}%` : "—"} />
        <Metric label="Profit Factor" value={profitFactor} />
        <Metric label="Expectancy / Trade" value={formatMoney(expectancy)} valueClass={expectancy == null ? "text-muted-foreground" : expectancy >= 0 ? "text-emerald-400" : "text-red-400"} />
        <Metric label="Max Drawdown (Closed Trades)" value={formatMoney(maxDrawdown, false)} valueClass={maxDrawdown < 0 ? "text-red-400" : "text-foreground"} />
        <Metric label="Avg Winner" value={formatMoney(avgWinner)} valueClass="text-emerald-400" />
        <Metric label="Avg Loser" value={formatMoney(avgLoser)} valueClass="text-red-400" />
        <Metric label="Avg Hold" value={formatHoldDuration(avgHold)} />
        <Metric label="Closed Trades" value={String(periodTrades.length)} />
      </div>
    </section>
  );
}
