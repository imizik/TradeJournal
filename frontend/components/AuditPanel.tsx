"use client";

import { useState } from "react";
import { api, AuditFill, AuditPath, AuditIndicators, TradeAudit } from "@/lib/api";

function n(val: number | null | undefined, d = 4) {
  if (val == null) return "-";
  return val.toFixed(d);
}

function DiscrepancyBadge({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-xs text-emerald-400">✓ no discrepancies</span>;
  return (
    <div className="space-y-1">
      {items.map((d, i) => (
        <p key={i} className="text-xs text-amber-400">⚠ {d}</p>
      ))}
    </div>
  );
}

function FillAuditBlock({ fill }: { fill: AuditFill }) {
  const barFound = fill.raw_bar != null;
  return (
    <div className="rounded border border-border p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${fill.is_entry ? "bg-blue-900/40 text-blue-300" : "bg-orange-900/40 text-orange-300"}`}>
          {fill.is_entry ? "ENTRY" : "EXIT"}
        </span>
        <span className="text-xs text-muted-foreground">{fill.executed_at_et}</span>
        <span className="text-xs font-medium">{fill.contracts}x @ ${fill.price}</span>
      </div>

      {/* Cache */}
      <div className="space-y-0.5 text-xs">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Cache file</span>
          <span className={fill.cache_exists ? "text-emerald-400" : "text-red-400"}>
            {fill.cache_exists ? "✓ found" : "✗ missing"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Total bars in file</span>
          <span>{fill.total_bars_in_file}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">RTH bars to fill</span>
          <span>{fill.rth_bars_to_fill}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Pre-market bars</span>
          <span>{fill.pm_bars}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">OR-5 bars</span>
          <span>{fill.or5_bars}</span>
        </div>
      </div>

      {/* Entry bar */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">Entry bar</p>
        {barFound ? (
          <div className="space-y-0.5 text-xs">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Bar time (ET)</span>
              <span>{fill.raw_bar!.timestamp_et}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">O / H / L / C</span>
              <span className="font-mono">
                {fill.raw_bar!.open.toFixed(2)} / {fill.raw_bar!.high.toFixed(2)} / {fill.raw_bar!.low.toFixed(2)} / {fill.raw_bar!.close.toFixed(2)}
              </span>
            </div>
            {fill.raw_bar!.bars_back > 0 && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Bars back used</span>
                <span className="text-amber-400">{fill.raw_bar!.bars_back} ({fill.raw_bar!.bars_back}m back)</span>
              </div>
            )}
          </div>
        ) : (
          <span className="text-xs text-red-400">✗ no bar found within 5 minutes</span>
        )}
      </div>

      {/* Formulas */}
      {Object.keys(fill.formulas).length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">Formulas</p>
          <div className="space-y-0.5">
            {Object.entries(fill.formulas).map(([k, v]) => (
              <div key={k}>
                <p className="text-xs text-muted-foreground">{k}</p>
                <p className="text-xs font-mono text-foreground/70 break-all">{v}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Structure */}
      {fill.structure && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">Intraday structure</p>
          <div className="grid grid-cols-2 gap-x-4 text-xs">
            <div className="flex justify-between"><span className="text-muted-foreground">Day high bar</span><span>{fill.structure.day_high_bar_et ?? "-"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Day low bar</span><span>{fill.structure.day_low_bar_et ?? "-"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">PM high</span><span>{fill.structure.pm_high != null ? `$${fill.structure.pm_high.toFixed(2)}` : "-"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">PM low</span><span>{fill.structure.pm_low != null ? `$${fill.structure.pm_low.toFixed(2)}` : "-"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">OR-5 high</span><span>{fill.structure.or5_high != null ? `$${fill.structure.or5_high.toFixed(2)}` : "-"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">OR-5 low</span><span>{fill.structure.or5_low != null ? `$${fill.structure.or5_low.toFixed(2)}` : "-"}</span></div>
          </div>
        </div>
      )}

      {/* Stored vs recomputed */}
      {(Object.keys(fill.stored).length > 0 || Object.keys(fill.recomputed).length > 0) && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">Stored vs recomputed</p>
          <div className="space-y-0.5 text-xs">
            {(["underlying_price", "vwap", "vs_vwap_pct", "day_high_so_far", "day_low_so_far", "day_range_used_pct", "premarket_high", "premarket_low", "or5_high", "or5_low"] as const).map((key) => {
              const s = fill.stored[key];
              const r = fill.recomputed[key as keyof typeof fill.recomputed];
              if (s == null && r == null) return null;
              const diff = s != null && r != null ? Math.abs(s - r) : null;
              const warn = diff != null && diff > 0.05;
              return (
                <div key={key} className={`flex justify-between ${warn ? "text-amber-400" : ""}`}>
                  <span className="text-muted-foreground shrink-0">{key}</span>
                  <span className="font-mono text-right">
                    {s != null ? n(s, 2) : "-"} → {r != null ? n(r, 2) : "-"}
                    {warn && <span className="ml-1 text-amber-400">⚠</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <DiscrepancyBadge items={fill.discrepancies} />
    </div>
  );
}

function PathAuditBlock({ path }: { path: AuditPath }) {
  if (path.error) {
    return (
      <div className="rounded border border-border p-3 text-xs text-muted-foreground">
        <p className="text-amber-400">⚠ {path.error}</p>
        <p className="mt-1">{path.window_bars} bars in window ({path.window_start_et} → {path.window_end_et})</p>
      </div>
    );
  }

  const stored = path.stored ?? {};
  const mfeDiff = path.mfe_pct_recomputed != null && stored.mfe_pct != null
    ? Math.abs(path.mfe_pct_recomputed - stored.mfe_pct)
    : null;
  const maeDiff = path.mae_pct_recomputed != null && stored.mae_pct != null
    ? Math.abs(path.mae_pct_recomputed - stored.mae_pct)
    : null;

  return (
    <div className="rounded border border-border p-3 space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Window</span>
        <span>{path.window_start_et} → {path.window_end_et} ({path.window_bars} bars)</span>
      </div>
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Entry underlying used</span>
        <span>${path.entry_underlying_used?.toFixed(4) ?? "-"}</span>
      </div>
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Direction</span>
        <span className={path.bullish ? "text-emerald-400" : "text-red-400"}>{path.bullish ? "bullish" : "bearish"}</span>
      </div>

      <div className="pt-1 space-y-0.5 text-xs">
        <p className="text-xs font-medium text-muted-foreground">MFE</p>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Recomputed</span>
          <span className="text-emerald-400">{path.mfe_pct_recomputed?.toFixed(3)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Stored</span>
          <span className={mfeDiff != null && mfeDiff > 0.1 ? "text-amber-400" : ""}>{stored.mfe_pct?.toFixed(3) ?? "-"}%{mfeDiff != null && mfeDiff > 0.1 && " ⚠"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">MFE bar (ET)</span>
          <span>{path.mfe_bar_et ?? "-"} H:{path.mfe_bar_high?.toFixed(2)} L:{path.mfe_bar_low?.toFixed(2)}</span>
        </div>
      </div>

      <div className="pt-1 space-y-0.5 text-xs">
        <p className="text-xs font-medium text-muted-foreground">MAE</p>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Recomputed</span>
          <span className="text-red-400">{path.mae_pct_recomputed?.toFixed(3)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Stored</span>
          <span className={maeDiff != null && maeDiff > 0.1 ? "text-amber-400" : ""}>{stored.mae_pct?.toFixed(3) ?? "-"}%{maeDiff != null && maeDiff > 0.1 && " ⚠"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">MAE bar (ET)</span>
          <span>{path.mae_bar_et ?? "-"} H:{path.mae_bar_high?.toFixed(2)} L:{path.mae_bar_low?.toFixed(2)}</span>
        </div>
      </div>

      {stored.exit_efficiency != null && (
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Exit efficiency (stored)</span>
          <span>{stored.exit_efficiency.toFixed(1)}%</span>
        </div>
      )}
    </div>
  );
}

function IndicatorAuditBlock({ ind }: { ind: AuditIndicators }) {
  if (ind.error) {
    return (
      <div className="rounded border border-border p-3 text-xs text-red-400">✗ {ind.error}</div>
    );
  }
  return (
    <div className="rounded border border-border p-3 space-y-1.5 text-xs">
      <div className="flex justify-between">
        <span className="text-muted-foreground">Daily bars available</span>
        <span>{ind.total_daily_bars_available}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">Bar range</span>
        <span>{ind.earliest_bar} → {ind.latest_bar}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">SMA-20 needs</span>
        <span>{ind.sma_20_bars_needed} bars</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">SMA-50 needs</span>
        <span>{ind.sma_50_bars_needed} bars</span>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">RSI window</span>
        <span>{ind.rsi_14_window}</span>
      </div>
      {ind.warmup_note && <p className="text-muted-foreground/70 pt-1">{ind.warmup_note}</p>}
      {ind.rsi_formula && (
        <div className="pt-1">
          <p className="text-muted-foreground mb-0.5">RSI formula</p>
          <p className="font-mono text-foreground/60 break-all">{ind.rsi_formula}</p>
        </div>
      )}
      {ind.ema_formula && (
        <div className="pt-1">
          <p className="text-muted-foreground mb-0.5">EMA formula</p>
          <p className="font-mono text-foreground/60 break-all">{ind.ema_formula}</p>
        </div>
      )}
    </div>
  );
}

type Props = { tradeId: string };

export default function AuditPanel({ tradeId }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audit, setAudit] = useState<TradeAudit | null>(null);

  const handleOpen = async () => {
    if (!open) {
      setOpen(true);
      if (!audit) {
        setLoading(true);
        setError(null);
        try {
          const data = await api.auditTrade(tradeId);
          setAudit(data);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Failed to load audit");
        } finally {
          setLoading(false);
        }
      }
    } else {
      setOpen(false);
    }
  };

  const handleRefresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.auditTrade(tradeId);
      setAudit(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-80 shrink-0">
      {/* Toggle button */}
      <button
        onClick={handleOpen}
        className={`w-full rounded px-3 py-2 text-xs font-semibold transition-colors ${
          open
            ? "bg-violet-900/60 text-violet-200 hover:bg-violet-900/40"
            : "bg-muted text-muted-foreground hover:bg-muted/70"
        }`}
      >
        {open ? "Hide Audit" : "Show Audit"}
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-violet-400">Data Audit</h3>
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {loading ? "Loading…" : "Refresh"}
            </button>
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          {loading && !audit && (
            <p className="text-xs text-muted-foreground">Computing audit from cached bars…</p>
          )}

          {audit && (
            <>
              {/* Direction badge */}
              {audit.direction && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Direction</span>
                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${audit.direction === "bullish" ? "bg-emerald-900/40 text-emerald-300" : "bg-red-900/40 text-red-300"}`}>
                    {audit.direction}
                  </span>
                </div>
              )}

              {/* Fills */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Fills</p>
                <div className="space-y-3">
                  {audit.fills.map((f) => <FillAuditBlock key={f.fill_id} fill={f} />)}
                </div>
              </div>

              {/* Path */}
              {audit.path && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Trade Path (MFE / MAE)</p>
                  <PathAuditBlock path={audit.path} />
                </div>
              )}

              {/* Indicators */}
              {audit.indicators && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Daily Indicator Cache</p>
                  <IndicatorAuditBlock ind={audit.indicators} />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
