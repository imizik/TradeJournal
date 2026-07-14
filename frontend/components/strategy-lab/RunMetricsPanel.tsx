"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import StrategyCurveChart from "@/components/strategy-lab/StrategyCurveChart";
import { recalculateMetrics } from "@/lib/strategy-lab/api";
import {
  decimalToNumber,
  formatDecimal,
  formatDurationMinutes,
  formatMoney,
  formatPercentPoints,
  formatStrategyDateTime,
  formatWinRate,
} from "@/lib/strategy-lab/format";
import type {
  StrategyMetricBreakdown,
  StrategyRunMetrics,
  StrategyRunMetricsStatus,
} from "@/lib/strategy-lab/types";

function signedClass(value: string | null | undefined) {
  const number = decimalToNumber(value);
  if (number == null) return "text-muted-foreground";
  return number >= 0 ? "text-emerald-400" : "text-red-400";
}

function readableReason(value: string) {
  return value.replaceAll("_", " ");
}

function moneyFromNumber(value: number, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export default function RunMetricsPanel({
  runId,
  currency,
  initialCapital,
  initialStatus,
  initialMetrics,
}: {
  runId: string;
  currency: string;
  initialCapital: string | null;
  initialStatus: StrategyRunMetricsStatus;
  initialMetrics: StrategyRunMetrics | null;
}) {
  const [metrics, setMetrics] = useState(initialMetrics);
  const [status, setStatus] = useState(initialStatus);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recalculate = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await recalculateMetrics(runId);
      setMetrics(next);
      setStatus("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Metrics calculation failed");
    } finally {
      setLoading(false);
    }
  };

  if (!metrics) {
    return (
      <section className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-amber-300">
              <AlertTriangle className="h-4 w-4" />
              <h2 className="font-semibold">Run metrics are pending</h2>
            </div>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              The imported trades are safely stored. Calculate the versioned summary to unlock coverage,
              breakdowns, equity, and drawdown.
            </p>
            {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
          </div>
          <Button onClick={recalculate} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Calculating" : "Calculate metrics"}
          </Button>
        </div>
      </section>
    );
  }

  if (status === "stale") {
    return (
      <section className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-amber-300">
              <AlertTriangle className="h-4 w-4" />
              <h2 className="font-semibold">Run metrics need an upgrade</h2>
            </div>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              This run has metrics from {metrics.calculation_version}, which may not contain the
              current coverage and curve schema. Recalculate them before reviewing performance.
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Last calculated {formatStrategyDateTime(metrics.calculated_at, "UTC")}
            </p>
            {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
          </div>
          <Button onClick={recalculate} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Refreshing" : "Upgrade metrics"}
          </Button>
        </div>
      </section>
    );
  }

  const complete =
    metrics.coverage.accounting_complete && metrics.coverage.chronology_complete;
  const usesSourceReturn =
    metrics.coverage.net_return_basis === "source_cumulative_return_pct";
  const hasInitialCapital = (decimalToNumber(initialCapital) ?? 0) > 0;

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Run performance
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Calculation {metrics.calculation_version} · {formatStrategyDateTime(
                metrics.calculated_at,
                metrics.coverage.source_timezone,
              )}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={recalculate} disabled={loading}>
            <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Recalculate
          </Button>
        </div>

        {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <MetricCard
            label="Net P&L"
            value={formatMoney(metrics.total_net_pnl, currency)}
            valueClass={signedClass(metrics.total_net_pnl)}
          />
          <MetricCard
            label={usesSourceReturn ? "Source return" : "Net return"}
            value={formatPercentPoints(metrics.net_return_pct, 2)}
            valueClass={signedClass(metrics.net_return_pct)}
          />
          <MetricCard
            label="Expectancy"
            value={formatMoney(metrics.expectancy, currency)}
            valueClass={signedClass(metrics.expectancy)}
            note="per covered trade"
          />
          <MetricCard
            label="Max drawdown"
            value={formatMoney(metrics.max_drawdown, currency)}
            valueClass="text-red-400"
            note={
              metrics.max_drawdown_pct == null
                ? undefined
                : formatPercentPoints(metrics.max_drawdown_pct, 2)
            }
          />
          <MetricCard
            label="Profit factor"
            value={formatDecimal(metrics.profit_factor, 3)}
          />
          <MetricCard label="Trades" value={String(metrics.trade_count)} />
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <MetricCard label="Win rate" value={formatWinRate(metrics.win_rate, 1)} />
          <MetricCard label="Payoff" value={formatDecimal(metrics.payoff_ratio, 3)} />
          <MetricCard
            label="Average winner"
            value={formatMoney(metrics.average_winner, currency)}
            valueClass="text-emerald-400"
          />
          <MetricCard
            label="Average loser"
            value={formatMoney(metrics.average_loser, currency)}
            valueClass="text-red-400"
          />
          <MetricCard
            label="Average hold"
            value={formatDurationMinutes(metrics.average_holding_minutes)}
          />
          <MetricCard
            label="Top trade share"
            value={formatPercentPoints(metrics.top_1_profit_contribution_pct, 1)}
            note="can exceed 100% of net profit"
          />
        </div>
      </section>

      <section
        className={`rounded-lg border p-4 ${
          complete
            ? "border-emerald-900/50 bg-emerald-950/20"
            : "border-amber-900/50 bg-amber-950/20"
        }`}
      >
        <div className="flex items-start gap-3">
          {complete ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          )}
          <div className="min-w-0 flex-1">
            <h3 className={`text-sm font-semibold ${complete ? "text-emerald-300" : "text-amber-300"}`}>
              {complete ? "Complete accounting and chronology" : "Partial source coverage"}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {complete
                ? "Every imported trade has P&L and an exit timestamp. Totals and curves represent the complete run."
                : "Unavailable values remain blank so incomplete source data is never presented as a complete result."}
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(metrics.coverage.fields).map(([field, item]) => (
                <div key={field} className="rounded bg-background/40 px-3 py-2 text-xs">
                  <p className="font-medium text-foreground">{readableReason(field)}</p>
                  <p className="mt-0.5 text-muted-foreground">
                    {item.available}/{metrics.coverage.total_trades} available
                    {item.invalid ? ` · ${item.invalid} invalid` : ""}
                  </p>
                </div>
              ))}
            </div>
            {Object.keys(metrics.coverage.undefined_metrics).length > 0 && (
              <details className="mt-3 text-xs text-muted-foreground">
                <summary className="cursor-pointer font-medium text-foreground/80">
                  Why some metrics are unavailable
                </summary>
                <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                  {Object.entries(metrics.coverage.undefined_metrics).map(([field, reason]) => (
                    <li key={field}>
                      <span className="text-foreground/70">{readableReason(field)}:</span>{" "}
                      {readableReason(reason)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <StrategyCurveChart
          title={hasInitialCapital ? "Equity curve" : "Cumulative P&L curve"}
          description={
            hasInitialCapital
              ? "Initial capital plus realized trade P&L, ordered by exit time."
              : "Realized P&L from a zero baseline because initial capital was not supplied."
          }
          points={metrics.equity_curve}
          valueKey="equity"
          stroke="#38bdf8"
          formatValue={(value) => moneyFromNumber(value, currency)}
        />
        <StrategyCurveChart
          title="Drawdown curve"
          description="Positive peak-to-trough dollar decline after each realized trade."
          points={metrics.drawdown_curve}
          valueKey="drawdown"
          stroke="#f59e0b"
          invert
          formatValue={(value) => moneyFromNumber(value, currency)}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <BreakdownTable
          title="Direction breakdown"
          rows={[
            ["Long", metrics.long_summary],
            ["Short", metrics.short_summary],
          ]}
          currency={currency}
        />
        <BreakdownTable
          title="Entry-time breakdown"
          rows={["premarket", "open", "mid", "close", "afterhours", "unknown"].map(
            (bucket) => [bucket, metrics.time_bucket_summary[bucket]] as [string, StrategyMetricBreakdown],
          )}
          currency={currency}
        />
      </div>

      <section className="rounded-lg border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">Excursion and concentration</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Average MFE" value={formatMoney(metrics.average_mfe, currency)} />
          <MetricCard label="Median MFE" value={formatMoney(metrics.median_mfe, currency)} />
          <MetricCard label="Average MAE" value={formatMoney(metrics.average_mae, currency)} />
          <MetricCard label="Median MAE" value={formatMoney(metrics.median_mae, currency)} />
          <MetricCard label="Top 1 share" value={formatPercentPoints(metrics.top_1_profit_contribution_pct, 1)} />
          <MetricCard label="Top 3 share" value={formatPercentPoints(metrics.top_3_profit_contribution_pct, 1)} />
          <MetricCard label="Top 5 share" value={formatPercentPoints(metrics.top_5_profit_contribution_pct, 1)} />
        </div>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  value,
  note,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  note?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
      {note && <p className="mt-1 text-[11px] text-muted-foreground">{note}</p>}
    </div>
  );
}

function BreakdownTable({
  title,
  rows,
  currency,
}: {
  title: string;
  rows: Array<[string, StrategyMetricBreakdown | undefined]>;
  currency: string;
}) {
  return (
    <section className="overflow-hidden rounded-lg border bg-card">
      <div className="border-b px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-sm">
          <thead className="bg-muted/70 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Group</th>
              <th className="px-3 py-2 text-right font-medium">Trades</th>
              <th className="px-3 py-2 text-right font-medium">Win rate</th>
              <th className="px-3 py-2 text-right font-medium">P&L</th>
              <th className="px-3 py-2 text-right font-medium">Expectancy</th>
              <th className="px-3 py-2 text-right font-medium">PF</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(([label, row]) => (
              <tr key={label}>
                <td className="px-3 py-2.5 font-medium capitalize">{label}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{row?.trade_count ?? 0}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatWinRate(row?.win_rate)}</td>
                <td className={`px-3 py-2.5 text-right tabular-nums ${signedClass(row?.total_pnl)}`}>
                  {formatMoney(row?.total_pnl, currency)}
                </td>
                <td className={`px-3 py-2.5 text-right tabular-nums ${signedClass(row?.expectancy)}`}>
                  {formatMoney(row?.expectancy, currency)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatDecimal(row?.profit_factor, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
