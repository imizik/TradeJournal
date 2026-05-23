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

// ---------------------------------------------------------------------------
// Tooltip bubble
// ---------------------------------------------------------------------------

function Tip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex items-center ml-1 shrink-0">
      <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-muted text-[9px] font-bold text-muted-foreground cursor-default select-none leading-none">
        ?
      </span>
      {/* Pops above — won't clip against card bottom */}
      <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 w-56 rounded border border-border bg-popover px-2.5 py-2 text-[11px] leading-relaxed text-foreground shadow-xl opacity-0 group-hover:opacity-100 transition-opacity duration-150 whitespace-normal">
        {text}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Row with optional tooltip
// ---------------------------------------------------------------------------

function Row({
  label,
  value,
  valueClass,
  tip,
}: {
  label: string;
  value: string;
  valueClass?: string;
  tip?: string;
}) {
  return (
    <div className="flex justify-between border-b border-border py-1.5 text-xs last:border-0">
      <span className="text-muted-foreground flex items-center gap-0">
        {label}
        {tip && <Tip text={tip} />}
      </span>
      <span className={`font-medium tabular-nums ${valueClass ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flag badge with tooltip
// ---------------------------------------------------------------------------

function Flag({ label, value, tip }: { label: string; value: number | null; tip?: string }) {
  if (value === null) return null;
  const on = value === 1;
  return (
    <span className="group relative">
      <span
        className={`inline-block rounded px-2 py-0.5 text-xs font-medium cursor-default ${
          on ? "bg-amber-900/40 text-amber-300" : "bg-muted text-muted-foreground line-through"
        }`}
      >
        {label}
      </span>
      {tip && (
        <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 w-56 rounded border border-border bg-popover px-2.5 py-2 text-[11px] leading-relaxed text-foreground shadow-xl opacity-0 group-hover:opacity-100 transition-opacity duration-150 whitespace-normal">
          {tip}
        </span>
      )}
    </span>
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

// ---------------------------------------------------------------------------
// Score bar (0-100)
// ---------------------------------------------------------------------------

function ScoreBar({ label, value, tip, colorFn }: {
  label: string;
  value: number | null;
  tip?: string;
  colorFn?: (v: number) => string;
}) {
  if (value == null) return null;
  const pct = Math.max(0, Math.min(100, value));
  const color = colorFn ? colorFn(value) : "bg-blue-500";
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground flex items-center gap-0">
          {label}
          {tip && <Tip text={tip} />}
        </span>
        <span className="font-semibold tabular-nums">{value.toFixed(0)}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tooltip content
// ---------------------------------------------------------------------------

const TIPS = {
  underlying:       "Stock price at the exact minute of your fill, from Alpaca minute bars.",
  vsVwap:           "How far entry was from session VWAP (resets at 9:30). Above = bullish bias. >+2% = stretched / potential chase.",
  rsi14:            "Momentum 0–100. <30 = oversold (reversal zone), >70 = overbought (chase risk). 40–60 = neutral. Best entries: buying 30–50 or selling 50–70.",
  ema9:             "9-day exponential moving average. Short-term trend line. Price above = near-term bullish.",
  ema20:            "20-day EMA. Medium-term trend. Ideal bull stack: price > EMA9 > EMA20.",
  vsEma9:           "How extended price is from EMA-9. >5% above = stretched, pullback likely. <0 = bearish.",
  macdHist:         "MACD histogram = MACD line minus signal. >0 = bullish momentum. <0 = bearish. Crossing zero is the signal. Magnitude shows strength.",
  atr14:            "Average True Range (14-day) in dollars — the stock's normal daily swing. Use for stop sizing: 0.5–1× ATR is a common stop distance.",
  prevClose:        "Yesterday's closing price. Reference for gap and overnight sentiment.",
  gap:              "Today's open vs yesterday's close. +8% = gapped up 8%. Big gaps often drive momentum but can also exhaust quickly.",
  pmHigh:           "Premarket session high (4am–9:30am ET). Often acts as resistance on first test. Breakout above = bullish continuation.",
  pmLow:            "Premarket session low. Often acts as support. Break below = bearish.",
  or5High:          "High of the first 5 minutes of regular trading (9:30–9:35). Classic breakout level — price above = OR breakout setup.",
  or5Low:           "Low of the first 5 minutes. Break below = bearish opening range breakdown.",
  or15High:         "High of first 15 minutes. More reliable than OR-5 as a reference since it has more price discovery.",
  or15Low:          "Low of first 15 minutes of trading.",
  dayHigh:          "Highest price reached from open to your entry. Near this = you're buying near HOD.",
  dayLow:           "Lowest price from open to your entry. Near this = support zone.",
  dayRangeUsed:     "Where entry sits in the day's range (0% = at LOD, 100% = at HOD). >80% = chasing the top. <20% = near the bottom.",
  distDayHigh:      "Distance from day's high at entry. -1% = 1% below HOD. Near 0% = buying at the high — high rejection risk.",
  distDayLow:       "Distance from day's low at entry. Near 0% = at LOD — bounce or breakdown point.",
  rvol:             "Relative volume vs expected for this time of day. >1.5 = unusually active (confirms moves). <0.5 = quiet tape. Based on 20-day average at same minute of day.",
  rvolSimple:       "Fallback RVOL (linear). Assumes volume spreads evenly through the day — less accurate early in session.",
  cumVol:           "Total shares traded from market open to your entry time. Context for how liquid the session has been.",
  adv20:            "20-day average daily volume. The stock's normal full-day volume. Used to compute RVOL.",
  moneyness:        "How far in/out of the money the option was at entry. Positive = ITM (intrinsic value). Negative = OTM (all time value).",
  setupScore:       "Aggregate 0–100 setup quality. 50 = neutral. Above 65 = strong setup. Below 35 = weak / chased. Combines trend, VWAP, MACD, OR break, chase penalty.",
  chaseScore:       "0–100 chase intensity. <30 = disciplined. 40–59 = somewhat extended. ≥60 = extended entry (RSI>70, far above VWAP, or day range exhausted).",

  // Flags
  flagAboveVwap:    "Price was on the correct side of VWAP at entry (above for longs, below for shorts). Confirms intraday bias.",
  flagVwapReclaim:  "True VWAP reclaim: the bar before entry was on the wrong side of VWAP, but entry bar crossed back. Stronger signal than simply being above VWAP.",
  flagNearRes:      "Entry was within 0.5% of the day high or prior day high — buying near known resistance. Higher failure risk.",
  flagChase:        "Chase score ≥ 40: entry is extended. At least one of: RSI>70, price >2% above VWAP, or >80% of day range used.",
  flagLate:         "Entering when move is mostly over — near HOD on longs, near LOD on shorts. Risk/reward is compressed.",
  flagOrBreak:      "Entry was above OR-5 high (long) or below OR-5 low (short). Classic early momentum setup.",
  flagPmBreak:      "Entry broke above premarket high (long) or below PM low (short). Continuation of overnight sentiment.",
  flagNearSup:      "Short/put entry within 0.5% of day low or prior day low — selling near known support. Bounce risk.",
  flagOvernight:    "Fill occurred outside regular trading hours (before 9:30am or after 4pm ET). Wider spreads, lower liquidity.",
  flagTrend:        "Price > EMA9 > EMA20 and MACD hist > 0 (bull), or inverse for bear. All three conditions required.",
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

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

  const flags: { label: string; value: number | null; tip: string }[] = [
    { label: "Trend Aligned",   value: ctx.is_trend_aligned,                    tip: TIPS.flagTrend },
    { label: "VWAP Reclaim",    value: ctx.is_vwap_reclaim,                    tip: TIPS.flagVwapReclaim },
    { label: "Above VWAP",      value: ctx.is_above_vwap,                      tip: TIPS.flagAboveVwap },
    { label: "OR Breakout",     value: ctx.is_opening_range_breakout,           tip: TIPS.flagOrBreak },
    { label: "PM Breakout",     value: ctx.is_premarket_breakout,               tip: TIPS.flagPmBreak },
    { label: "Chase Entry",     value: ctx.is_chase_entry,                      tip: TIPS.flagChase },
    { label: "Late Move",       value: ctx.is_late_move,                        tip: TIPS.flagLate },
    { label: "Near Resistance", value: ctx.is_near_resistance_on_call_entry,    tip: TIPS.flagNearRes },
    { label: "Near Support",    value: ctx.is_near_support_on_put_entry,        tip: TIPS.flagNearSup },
    { label: "Overnight",       value: ctx.is_overnight,                        tip: TIPS.flagOvernight },
  ].filter((f) => f.value !== null);

  const activeFlags = flags.filter((f) => f.value === 1);
  const inactiveFlags = flags.filter((f) => f.value === 0);

  // RVOL: prefer time-adjusted (more accurate), fall back to simple
  const rvolDisplay = ctx.rvol_time_adjusted ?? ctx.simple_relative_volume;
  const rvolTip = ctx.rvol_time_adjusted != null ? TIPS.rvol : TIPS.rvolSimple;
  const rvolLabel = ctx.rvol_time_adjusted != null ? "RVOL (adj)" : "RVOL";

  return (
    <div className="rounded-lg border bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Alpaca Market Context
        </h2>
        <SourceBadge source={source} />
      </div>

      {/* Setup scores */}
      {entryCtx && (entryCtx.setup_quality_score != null || entryCtx.chase_score != null) && (
        <div className="space-y-2 pb-2 border-b border-border">
          <ScoreBar
            label="Setup Quality"
            value={entryCtx.setup_quality_score}
            tip={TIPS.setupScore}
            colorFn={(v) => v >= 65 ? "bg-emerald-500" : v >= 45 ? "bg-blue-500" : "bg-red-500"}
          />
          <ScoreBar
            label="Chase Score"
            value={entryCtx.chase_score}
            tip={TIPS.chaseScore}
            colorFn={(v) => v < 30 ? "bg-emerald-500" : v < 50 ? "bg-amber-500" : "bg-red-500"}
          />
        </div>
      )}

      {/* Entry / Exit indicators */}
      <div className="grid grid-cols-2 gap-6">
        {entryCtx && (
          <div>
            <p className="mb-2 text-xs font-semibold text-blue-400">ENTRY</p>
            <Row label="Underlying" value={fmt$(entryCtx.entry_underlying_price)} tip={TIPS.underlying} />
            <Row label="vs VWAP"   value={fmtPct(entryCtx.entry_vs_vwap_pct)}   valueClass={pctColor(entryCtx.entry_vs_vwap_pct)} tip={TIPS.vsVwap} />
            <Row label="RSI-14"    value={fmtNum(entryCtx.entry_rsi_14, 1)}      tip={TIPS.rsi14} />
            <Row label="EMA-9"     value={fmt$(entryCtx.entry_ema_9)}            tip={TIPS.ema9} />
            <Row label="EMA-20"    value={fmt$(entryCtx.entry_ema_20)}           tip={TIPS.ema20} />
            <Row label="vs EMA-9"  value={fmtPct(entryCtx.entry_vs_ema9_pct)}   valueClass={pctColor(entryCtx.entry_vs_ema9_pct)} tip={TIPS.vsEma9} />
            <Row label="MACD Hist" value={fmtNum(entryCtx.entry_macd_histogram, 3)} tip={TIPS.macdHist} />
            <Row label="ATR-14"    value={fmt$(entryCtx.entry_atr_14)}           tip={TIPS.atr14} />
            {entryCtx.moneyness_pct != null && (
              <Row
                label={entryCtx.is_itm ? "Moneyness (ITM)" : "Moneyness (OTM)"}
                value={fmtPct(entryCtx.moneyness_pct)}
                valueClass={entryCtx.is_itm ? "text-emerald-400" : "text-amber-400"}
                tip={TIPS.moneyness}
              />
            )}
          </div>
        )}
        {exitCtx && (
          <div>
            <p className="mb-2 text-xs font-semibold text-orange-400">EXIT</p>
            <Row label="Underlying" value={fmt$(exitCtx.entry_underlying_price)} tip={TIPS.underlying} />
            <Row label="vs VWAP"   value={fmtPct(exitCtx.entry_vs_vwap_pct)}   valueClass={pctColor(exitCtx.entry_vs_vwap_pct)} tip={TIPS.vsVwap} />
            <Row label="RSI-14"    value={fmtNum(exitCtx.entry_rsi_14, 1)}      tip={TIPS.rsi14} />
            <Row label="vs EMA-9"  value={fmtPct(exitCtx.entry_vs_ema9_pct)}   valueClass={pctColor(exitCtx.entry_vs_ema9_pct)} tip={TIPS.vsEma9} />
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
              <Row label="Prev Close" value={fmt$(entryCtx.previous_day_close)}       tip={TIPS.prevClose} />
              <Row label="Gap"        value={fmtPct(entryCtx.entry_gap_pct)}          valueClass={pctColor(entryCtx.entry_gap_pct)} tip={TIPS.gap} />
              <Row label="PM High"    value={fmt$(entryCtx.premarket_high)}            tip={TIPS.pmHigh} />
              <Row label="PM Low"     value={fmt$(entryCtx.premarket_low)}             tip={TIPS.pmLow} />
              <Row label="OR-5 High"  value={fmt$(entryCtx.opening_range_5m_high)}    tip={TIPS.or5High} />
              <Row label="OR-5 Low"   value={fmt$(entryCtx.opening_range_5m_low)}     tip={TIPS.or5Low} />
              <Row label="OR-15 High" value={fmt$(entryCtx.opening_range_15m_high)}   tip={TIPS.or15High} />
              <Row label="OR-15 Low"  value={fmt$(entryCtx.opening_range_15m_low)}    tip={TIPS.or15Low} />
            </div>
            <div>
              <Row label="Day High (at entry)" value={fmt$(entryCtx.entry_day_high_so_far)}              tip={TIPS.dayHigh} />
              <Row label="Day Low (at entry)"  value={fmt$(entryCtx.entry_day_low_so_far)}               tip={TIPS.dayLow} />
              <Row label="Day Range Used"      value={fmtPct(entryCtx.entry_day_range_used_pct, 1)}      tip={TIPS.dayRangeUsed} />
              <Row label="Dist from Day High"  value={fmtPct(entryCtx.entry_distance_from_day_high_pct)} valueClass={pctColor(entryCtx.entry_distance_from_day_high_pct)} tip={TIPS.distDayHigh} />
              <Row label="Dist from Day Low"   value={fmtPct(entryCtx.entry_distance_from_day_low_pct)}  valueClass={pctColor(entryCtx.entry_distance_from_day_low_pct)}  tip={TIPS.distDayLow} />
              <Row label={rvolLabel}  value={fmtNum(rvolDisplay, 2)} tip={rvolTip} />
              <Row label="Cum Volume" value={fmtVol(entryCtx.cumulative_volume_at_entry)} tip={TIPS.cumVol} />
              <Row label="ADV-20"     value={fmtVol(entryCtx.avg_daily_volume_20)}        tip={TIPS.adv20} />
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
              <Flag key={f.label} label={f.label} value={f.value} tip={f.tip} />
            ))}
            {inactiveFlags.map((f) => (
              <Flag key={f.label} label={f.label} value={f.value} tip={f.tip} />
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
