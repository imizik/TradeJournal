"use client";

import type { Fill, FillMarketContext } from "@/lib/api";

function isEntry(fill: Fill) {
  return fill.side === "buy_to_open" || fill.side === "sell_to_open" || fill.side === "buy";
}

function fmt$(val: number | null | undefined, decimals = 2) {
  if (val == null) return "-";
  return `$${val.toFixed(decimals)}`;
}

function fmtPct(val: number | null | undefined, decimals = 2) {
  if (val == null) return "-";
  const sign = val >= 0 ? "+" : "";
  return `${sign}${val.toFixed(decimals)}%`;
}

function fmtNum(val: number | null | undefined, decimals = 2) {
  if (val == null) return "-";
  return val.toFixed(decimals);
}

function fmtVol(val: number | null | undefined) {
  if (val == null) return "-";
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}K`;
  return String(val);
}

function pctColor(val: number | null | undefined) {
  if (val == null) return "text-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function Flag({ label, value }: { label: string; value: number | null }) {
  if (value === null) return null;
  const on = value === 1;
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${
        on ? "bg-amber-900/40 text-amber-300" : "bg-muted text-muted-foreground line-through"
      }`}
    >
      {label}
    </span>
  );
}

function Row({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between border-b border-border py-1.5 text-xs last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-medium ${valueClass ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const label = source.replace("alpaca_", "").toUpperCase();
  return (
    <span className="rounded bg-violet-900/40 px-1.5 py-0.5 text-xs font-medium text-violet-300">
      Alpaca/{label}
    </span>
  );
}

type Props = {
  fills: Fill[];
  contexts: Record<string, FillMarketContext>;
};

export default function AlpacaContextSection({ fills, contexts }: Props) {
  const entryFills = fills.filter(isEntry);
  const exitFills = fills.filter((f) => !isEntry(f));

  const entryCtx = entryFills.map((f) => contexts[f.id]).find(Boolean) ?? null;
  const exitCtx = exitFills.map((f) => contexts[f.id]).find(Boolean) ?? null;

  if (!entryCtx && !exitCtx) return null;

  const ctx = entryCtx ?? exitCtx!;
  const source = ctx.data_source;

  // Active flags
  const flags: { label: string; value: number | null }[] = [
    { label: "Chase Entry", value: ctx.is_chase_entry },
    { label: "Trend Aligned", value: ctx.is_trend_aligned },
    { label: "Late Move", value: ctx.is_late_move },
    { label: "VWAP Reclaim", value: ctx.is_vwap_reclaim },
    { label: "OR Breakout", value: ctx.is_opening_range_breakout },
    { label: "PM Breakout", value: ctx.is_premarket_breakout },
    { label: "Near Resistance", value: ctx.is_near_resistance_on_call_entry },
    { label: "Near Support", value: ctx.is_near_support_on_put_entry },
    { label: "Overnight", value: ctx.is_overnight },
  ].filter((f) => f.value !== null);

  const activeFlags = flags.filter((f) => f.value === 1);
  const inactiveFlags = flags.filter((f) => f.value === 0);

  return (
    <div className="rounded-lg border bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Alpaca Market Context
        </h2>
        <SourceBadge source={source} />
      </div>

      {/* Entry / Exit price context */}
      <div className="grid grid-cols-2 gap-6">
        {entryCtx && (
          <div>
            <p className="mb-2 text-xs font-semibold text-blue-400">ENTRY</p>
            <Row label="Underlying" value={fmt$(entryCtx.entry_underlying_price)} />
            <Row
              label="vs VWAP"
              value={fmtPct(entryCtx.entry_vs_vwap_pct)}
              valueClass={pctColor(entryCtx.entry_vs_vwap_pct)}
            />
            <Row label="RSI-14" value={fmtNum(entryCtx.entry_rsi_14, 1)} />
            <Row label="EMA-9" value={fmt$(entryCtx.entry_ema_9)} />
            <Row label="EMA-20" value={fmt$(entryCtx.entry_ema_20)} />
            <Row
              label="vs EMA-9"
              value={fmtPct(entryCtx.entry_vs_ema9_pct)}
              valueClass={pctColor(entryCtx.entry_vs_ema9_pct)}
            />
            <Row label="MACD Hist" value={fmtNum(entryCtx.entry_macd_histogram, 3)} />
            <Row label="ATR-14" value={fmt$(entryCtx.entry_atr_14)} />
          </div>
        )}
        {exitCtx && (
          <div>
            <p className="mb-2 text-xs font-semibold text-orange-400">EXIT</p>
            <Row label="Underlying" value={fmt$(exitCtx.entry_underlying_price)} />
            <Row
              label="vs VWAP"
              value={fmtPct(exitCtx.entry_vs_vwap_pct)}
              valueClass={pctColor(exitCtx.entry_vs_vwap_pct)}
            />
            <Row label="RSI-14" value={fmtNum(exitCtx.entry_rsi_14, 1)} />
            <Row
              label="vs EMA-9"
              value={fmtPct(exitCtx.entry_vs_ema9_pct)}
              valueClass={pctColor(exitCtx.entry_vs_ema9_pct)}
            />
          </div>
        )}
      </div>

      {/* Intraday structure */}
      {entryCtx && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Intraday Structure
          </p>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <Row label="Prev Close" value={fmt$(entryCtx.previous_day_close)} />
              <Row label="Gap" value={fmtPct(entryCtx.entry_gap_pct)} valueClass={pctColor(entryCtx.entry_gap_pct)} />
              <Row label="PM High" value={fmt$(entryCtx.premarket_high)} />
              <Row label="PM Low" value={fmt$(entryCtx.premarket_low)} />
              <Row label="OR-5 High" value={fmt$(entryCtx.opening_range_5m_high)} />
              <Row label="OR-5 Low" value={fmt$(entryCtx.opening_range_5m_low)} />
              <Row label="OR-15 High" value={fmt$(entryCtx.opening_range_15m_high)} />
              <Row label="OR-15 Low" value={fmt$(entryCtx.opening_range_15m_low)} />
            </div>
            <div>
              <Row label="Day High (at entry)" value={fmt$(entryCtx.entry_day_high_so_far)} />
              <Row label="Day Low (at entry)" value={fmt$(entryCtx.entry_day_low_so_far)} />
              <Row label="Day Range Used" value={fmtPct(entryCtx.entry_day_range_used_pct, 1)} />
              <Row
                label="Dist from Day High"
                value={fmtPct(entryCtx.entry_distance_from_day_high_pct)}
                valueClass={pctColor(entryCtx.entry_distance_from_day_high_pct)}
              />
              <Row
                label="Dist from Day Low"
                value={fmtPct(entryCtx.entry_distance_from_day_low_pct)}
                valueClass={pctColor(entryCtx.entry_distance_from_day_low_pct)}
              />
              <Row label="RVOL" value={fmtNum(entryCtx.simple_relative_volume, 2)} />
              <Row label="Cum Volume" value={fmtVol(entryCtx.cumulative_volume_at_entry)} />
              <Row label="ADV-20" value={fmtVol(entryCtx.avg_daily_volume_20)} />
            </div>
          </div>
        </div>
      )}

      {/* Setup flags */}
      {flags.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Setup Flags
          </p>
          <div className="flex flex-wrap gap-1.5">
            {activeFlags.map((f) => (
              <Flag key={f.label} label={f.label} value={f.value} />
            ))}
            {inactiveFlags.map((f) => (
              <Flag key={f.label} label={f.label} value={f.value} />
            ))}
          </div>
          {ctx.entry_time_bucket && (
            <p className="mt-2 text-xs text-muted-foreground">
              Time bucket: <span className="font-medium text-foreground">{ctx.entry_time_bucket}</span>
              {ctx.dte_bucket && (
                <> · DTE: <span className="font-medium text-foreground">{ctx.dte_bucket}</span></>
              )}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
