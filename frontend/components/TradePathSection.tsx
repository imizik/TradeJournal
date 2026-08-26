"use client";

import type { TradePathMetrics } from "@/lib/api";

function fmtAbs(val: number | null | undefined, decimals = 2, suffix = "%") {
  if (val == null) return "-";
  return `${Math.abs(val).toFixed(decimals)}${suffix}`;
}

function fmtMoney(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : "-"}$${Math.abs(val).toFixed(0)}`;
}

function fmtPrice(val: number | null | undefined) {
  if (val == null) return "-";
  return `$${val.toFixed(0)}`;
}

function fmtMins(val: number | null | undefined) {
  if (val == null) return "-";
  if (val < 60) return `${val}m`;
  const h = Math.floor(val / 60);
  const m = val % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function effColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  if (val >= 80) return "text-emerald-400";
  if (val >= 50) return "text-yellow-400";
  return "text-red-400";
}

function mfeColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val > 0 ? "text-emerald-400" : "text-muted-foreground";
}

function maeColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val > 0 ? "text-red-400" : "text-muted-foreground";
}

function Row({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between border-b border-border py-1.5 text-xs last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-medium ${valueClass ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

type Props = { metrics: TradePathMetrics };

export default function TradePathSection({ metrics }: Props) {
  const mfe = metrics.underlying_mfe_pct;
  const mae = metrics.underlying_mae_pct;
  const eff = metrics.underlying_exit_efficiency;
  const giveback = metrics.underlying_giveback_pct;
  const hasOptionPath =
    metrics.option_mfe_pct != null ||
    metrics.option_peak_unrealized_pnl != null ||
    metrics.option_max_price_seen != null;

  // Visual bar: shows MAE zone (red), captured zone (green), giveback zone (amber)
  // Normalized to MFE as 100%
  const hasBar = mfe != null && mfe > 0 && eff != null;
  const capturedPct = hasBar ? Math.max(0, Math.min(eff!, 100)) : 0;
  const maeVsMfe = hasBar && mae != null ? Math.min((mae / mfe!) * 100, 100) : 0;

  return (
    <div className="rounded-lg border bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Trade Path
        </h2>
        <span className="rounded bg-teal-900/40 px-1.5 py-0.5 text-xs font-medium text-teal-300">
          Underlying
        </span>
      </div>

      {/* Exit efficiency bar */}
      {hasBar && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted-foreground">
            <span>Entry</span>
            <span className={effColor(eff)}>
              {eff!.toFixed(1)}% of move captured
            </span>
            <span>MFE ({fmtAbs(mfe)})</span>
          </div>
          <div className="relative h-3 w-full overflow-hidden rounded-full bg-muted">
            {/* MAE adverse zone */}
            {maeVsMfe > 0 && (
              <div
                className="absolute left-0 top-0 h-full bg-red-900/50"
                style={{ width: `${maeVsMfe}%` }}
              />
            )}
            {/* Captured / exit efficiency */}
            <div
              className="absolute left-0 top-0 h-full rounded-full bg-emerald-600/70"
              style={{ width: `${capturedPct}%` }}
            />
            {/* Giveback zone (from captured to MFE) */}
            {capturedPct < 100 && (
              <div
                className="absolute top-0 h-full bg-amber-700/40"
                style={{ left: `${capturedPct}%`, width: `${100 - capturedPct}%` }}
              />
            )}
          </div>
          <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-sm bg-emerald-600/70" /> Captured
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-sm bg-amber-700/40" /> Giveback
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-sm bg-red-900/50" /> MAE
            </span>
          </div>
        </div>
      )}

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-8">
        <div>
          <Row
            label="Underlying MFE"
            value={fmtAbs(mfe)}
            valueClass={mfeColor(mfe)}
          />
          <Row
            label="Underlying MAE"
            value={fmtAbs(mae)}
            valueClass={maeColor(mae)}
          />
          <Row
            label="Exit Efficiency"
            value={eff != null ? `${eff.toFixed(1)}%` : "-"}
            valueClass={effColor(eff)}
          />
          <Row
            label="Giveback"
            value={giveback != null ? `${giveback.toFixed(2)}%` : "-"}
            valueClass={giveback != null && giveback > 1 ? "text-amber-400" : "text-foreground"}
          />
        </div>
        <div>
          <Row label="Time to MFE" value={fmtMins(metrics.time_to_underlying_mfe_minutes)} />
          <Row label="Time to MAE" value={fmtMins(metrics.time_to_underlying_mae_minutes)} />
          <Row
            label="Moved in Favor First"
            value={metrics.moved_in_favor_first === 1 ? "Yes" : metrics.moved_in_favor_first === 0 ? "No" : "-"}
            valueClass={metrics.moved_in_favor_first === 1 ? "text-emerald-400" : metrics.moved_in_favor_first === 0 ? "text-red-400" : "text-muted-foreground"}
          />
          <Row label="Hold Bucket" value={metrics.hold_duration_bucket ?? "-"} />
          <Row label="Exit Bucket" value={metrics.exit_time_bucket ?? "-"} />
        </div>
      </div>

      {hasOptionPath && (
        <div className="border-t border-border pt-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Option Path
            </h3>
            <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-xs font-medium text-amber-300">
              Contract
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-8">
            <div>
              <Row
                label="Peak Open P&L"
                value={fmtMoney(metrics.option_peak_unrealized_pnl)}
                valueClass={mfeColor(metrics.option_peak_unrealized_pnl)}
              />
              <Row
                label="Worst Open P&L"
                value={fmtMoney(metrics.option_worst_unrealized_pnl)}
                valueClass={maeColor(metrics.option_worst_unrealized_pnl != null ? Math.abs(Math.min(metrics.option_worst_unrealized_pnl, 0)) : null)}
              />
              <Row
                label="Giveback From Peak"
                value={fmtMoney(metrics.option_giveback_from_peak)}
                valueClass={metrics.option_giveback_from_peak != null && metrics.option_giveback_from_peak > 0 ? "text-amber-400" : "text-foreground"}
              />
              <Row
                label="Peak Capture"
                value={metrics.option_exit_efficiency != null ? `${metrics.option_exit_efficiency.toFixed(1)}%` : "-"}
                valueClass={effColor(metrics.option_exit_efficiency)}
              />
            </div>
            <div>
              <Row label="Option MFE" value={fmtAbs(metrics.option_mfe_pct)} valueClass={mfeColor(metrics.option_mfe_pct)} />
              <Row label="Option MAE" value={fmtAbs(metrics.option_mae_pct)} valueClass={maeColor(metrics.option_mae_pct)} />
              <Row label="High Seen" value={fmtPrice(metrics.option_max_price_seen)} />
              <Row label="Low Seen" value={fmtPrice(metrics.option_min_price_seen)} />
              <Row label="Time to Peak" value={fmtMins(metrics.time_to_option_mfe_minutes)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
