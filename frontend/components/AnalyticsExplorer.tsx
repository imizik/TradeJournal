"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import type { Account, Analytics, AnalyticsDimension, AnalyticsSummary } from "@/lib/api";

const DIMENSIONS: { value: AnalyticsDimension; label: string; note: string }[] = [
  { value: "ticker", label: "Ticker", note: "Compare names within the selected account, instrument, and close dates." },
  { value: "entry_time", label: "Entry time", note: "Entry times use America/New_York. Overnight positions are grouped by their original entry time." },
  { value: "tag", label: "Tag", note: "A trade can have multiple tags, so tag rows overlap and their totals should not be added together. Untagged trades stay visible." },
  { value: "hold_duration", label: "Hold duration", note: "Uses recorded holding minutes. Missing durations stay in an Unavailable group." },
  { value: "instrument", label: "Instrument", note: "Stocks and options can have different sizing and return characteristics." },
  { value: "repeat_entry", label: "First vs repeat entry", note: "First entry time versus later reconstructed positions in the same ticker, account, and New York day. Uses full history before filtering; simultaneous first entries share a group. Adds within one position are not separate trades." },
];

function money(value: number | null) {
  if (value == null) return "—";
  return `${value < 0 ? "−" : "+"}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function percent(value: number | null) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function color(value: number | null) {
  return value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-400" : "text-red-400";
}

function factor(summary: AnalyticsSummary) {
  return summary.no_losses ? "∞" : summary.profit_factor == null ? "—" : summary.profit_factor.toFixed(2);
}

function Metric({ label, value, detail, tone = "" }: { label: string; value: string; detail?: string; tone?: string }) {
  return <div className="min-w-0 rounded-lg border bg-card p-4">
    <p className="text-xs text-muted-foreground">{label}</p>
    <p className={`mt-1 text-lg font-semibold tabular-nums sm:text-xl ${tone}`}>{value}</p>
    {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}
  </div>;
}

function ClosedPnlCurve({ curve }: { curve: Analytics["curve"] }) {
  if (!curve.length) return <p className="py-8 text-center text-sm text-muted-foreground">No priced closed trades in this selection.</p>;
  const values = [0, ...curve.map((point) => point.cumulative_pnl)];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const width = 720;
  const height = 170;
  const y = (value: number) => high === low ? height / 2 : 12 + (high - value) / span * (height - 24);
  const points = values.map((value, index) => `${12 + index / (values.length - 1) * (width - 24)},${y(value)}`);
  const positive = curve[curve.length - 1].cumulative_pnl >= 0;
  return <div>
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Cumulative closed-trade P&L by trading day">
      <title>Cumulative closed-trade P&amp;L, starting at zero</title>
      <line x1="12" x2={width - 12} y1={y(0)} y2={y(0)} stroke="currentColor" className="text-muted-foreground" strokeDasharray="4 4" opacity="0.4" />
      <polyline points={points.join(" ")} fill="none" stroke="currentColor" strokeWidth="2.5" className={positive ? "text-emerald-400" : "text-red-400"} />
      {curve.map((point, index) => <circle key={point.date} cx={12 + (index + 1) / curve.length * (width - 24)} cy={y(point.cumulative_pnl)} r="3" className={positive ? "fill-emerald-400" : "fill-red-400"}>
        <title>{`${point.date}: ${money(point.cumulative_pnl)} cumulative; ${money(point.pnl)} closed that day`}</title>
      </circle>)}
    </svg>
    <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{curve[0].date} → {curve[curve.length - 1].date}</span><span>Range: {money(low)} to {money(high)}</span></div>
    <p className="mt-2 text-xs text-muted-foreground">Each point is a day with a recorded close. Open positions and their partial realized P&amp;L are excluded. This is closed-trade P&amp;L; account equity requires balances and cash flows.</p>
  </div>;
}

export default function AnalyticsExplorer({ data, accounts }: { data: Analytics; accounts: Account[] }) {
  const [dimension, setDimension] = useState<AnalyticsDimension>("ticker");
  const [sort, setSort] = useState<"total_pnl" | "expectancy" | "median_pnl" | "count">("total_pnl");
  const [minimum, setMinimum] = useState(1);
  const [selection, setSelection] = useState<{ label: string; ids: string[] } | null>(null);
  const [page, setPage] = useState(0);
  const tradesSection = useRef<HTMLElement>(null);
  const summary = data.summary;
  const info = DIMENSIONS.find((item) => item.value === dimension)!;
  const groups = [...data.breakdowns[dimension]].filter((group) => group.count >= minimum).sort((a, b) => {
    const first = a[sort];
    const second = b[sort];
    if (first == null) return second == null ? a.label.localeCompare(b.label) : 1;
    if (second == null) return -1;
    return second - first || a.label.localeCompare(b.label);
  });
  const selectedIds = selection ? new Set(selection.ids) : null;
  const trades = selectedIds ? data.trades.filter((trade) => selectedIds.has(trade.id)) : data.trades;
  const accountNames = new Map(accounts.map((account) => [account.id, account.name]));
  const pageSize = 25;
  function drill(label: string, ids: string[]) {
    setSelection({ label, ids });
    setPage(0);
    tradesSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return <div className="min-w-0 space-y-6">
    <div className="rounded-lg border bg-card px-4 py-3 text-sm" aria-label="Data coverage">
      <p><span className="font-semibold">{summary.pnl_count} of {summary.count}</span> selected closed / expired trades have recorded P&amp;L, across {summary.entry_days} entry days.</p>
      <p className="mt-1 text-xs text-muted-foreground">Dates filter the final close in New York time, inclusive. Dollar metrics and win rate use trades with P&amp;L; breakeven trades remain in the denominator.</p>
      {(data.coverage.missing_pnl > 0 || data.coverage.missing_percentage > 0 || data.coverage.undated_closed_in_scope > 0) && <p className="mt-2 text-xs text-amber-300">
        {data.coverage.missing_pnl} selected trades missing P&amp;L · {data.coverage.missing_percentage} without a usable return percentage · {data.coverage.undated_closed_in_scope} closed trades in this account/instrument scope excluded because their close date is missing (date eligibility unknown).
      </p>}
    </div>

    <section aria-labelledby="analytics-performance" className="space-y-3">
      <h2 id="analytics-performance" className="text-sm font-semibold">Performance</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Closed P&L" value={money(summary.total_pnl)} tone={color(summary.total_pnl)} />
        <Metric label="Expectancy / trade" value={money(summary.expectancy)} detail="Average recorded dollar P&L" tone={color(summary.expectancy)} />
        <Metric label="Median P&L" value={money(summary.median_pnl)} tone={color(summary.median_pnl)} />
        <Metric label="Profit factor" value={factor(summary)} detail="Gross profits / gross losses; ∞ means no recorded losses" />
        <Metric label="Win rate" value={percent(summary.win_rate)} />
        <Metric label="Average winner" value={money(summary.avg_winner)} tone={color(summary.avg_winner)} />
        <Metric label="Average loser" value={money(summary.avg_loser)} tone={color(summary.avg_loser)} />
        <Metric label="Max closed-trade drawdown" value={money(summary.max_drawdown)} detail="Measured at recorded closes" tone={color(summary.max_drawdown)} />
      </div>
      <div className="rounded-lg border bg-card p-4"><ClosedPnlCurve curve={data.curve} /></div>
    </section>

    <section aria-labelledby="profit-concentration" className="space-y-3">
      <div>
        <h2 id="profit-concentration" className="text-sm font-semibold">How concentrated are your profits?</h2>
        <p className="mt-1 text-xs text-muted-foreground">A sensitivity check: remove the biggest winning trades while keeping all losses. Concentrated gains can be part of a strategy; this alone does not diagnose a problem.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.concentration.map((item) => <div key={item.limit} className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Without your best {item.limit === 1 ? "winner" : `${item.limit} winners`}</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums ${color(item.remaining_pnl)}`}>{money(item.remaining_pnl)}</p>
          <p className="mt-2 text-xs text-muted-foreground">{item.removed_count} winners removed · {percent(item.gross_profit_share)} of gross profits · {money(item.winner_pnl)}</p>
          {item.removed_count > 0 && <button type="button" onClick={() => drill(`Best ${item.removed_count} winning trades`, item.trade_ids)} className="mt-3 text-sm text-emerald-400 hover:underline">Inspect winners</button>}
        </div>)}
      </div>
    </section>

    <section aria-labelledby="breakdown-explorer" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 id="breakdown-explorer" className="text-sm font-semibold">Breakdown explorer</h2><p className="mt-1 text-xs text-muted-foreground">Compare groups, then inspect their trades below.</p></div>
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <label>Group by<select aria-label="Group by" value={dimension} onChange={(event) => { setDimension(event.target.value as AnalyticsDimension); setSelection(null); setPage(0); }} className="mt-1 block rounded-md border bg-card p-2 text-sm text-foreground">
            {DIMENSIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select></label>
          <label>Sort by<select aria-label="Sort by" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} className="mt-1 block rounded-md border bg-card p-2 text-sm text-foreground">
            <option value="total_pnl">Total P&amp;L</option><option value="expectancy">Expectancy</option><option value="median_pnl">Median P&amp;L</option><option value="count">Trade count</option>
          </select></label>
          <label>Minimum trades<select aria-label="Minimum trades" value={minimum} onChange={(event) => setMinimum(Number(event.target.value))} className="mt-1 block rounded-md border bg-card p-2 text-sm text-foreground">
            {[1, 10, 20, 50].map((number) => <option key={number} value={number}>{number === 1 ? "All samples" : `${number}+`}</option>)}
          </select></label>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{info.note}</p>
      <p className="text-xs text-muted-foreground">Selected baseline: {money(summary.expectancy)} / trade · {percent(summary.win_rate)} win rate. “Small sample” means fewer than 20 priced trades; larger samples can still be inconclusive.</p>
      <div className="max-w-full overflow-x-auto rounded-lg border bg-card">
        <table className="w-full whitespace-nowrap text-sm" aria-label="Analytics breakdown">
          <thead className="bg-muted text-xs text-muted-foreground"><tr>
            {[info.label, "Trades / days", "Total P&L", "Expectancy", "Median P&L", "Win rate", "Profit factor", "Avg return"].map((label) => <th key={label} className="px-4 py-3 text-left font-medium">{label}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-border">
            {groups.map((group) => <tr key={group.label} className={selection?.label === `${info.label}: ${group.label}` ? "bg-muted/60" : "hover:bg-muted/40"}>
              <td className="px-4 py-3"><button type="button" aria-pressed={selection?.label === `${info.label}: ${group.label}`} onClick={() => drill(`${info.label}: ${group.label}`, group.trade_ids)} className="font-semibold text-foreground underline decoration-muted-foreground/50 underline-offset-4">{group.label}</button>
                {group.pnl_count < 20 && <span className="ml-2 rounded bg-amber-900/20 px-1.5 py-1 text-[10px] text-amber-300">Small sample</span>}</td>
              <td className="px-4 py-3 tabular-nums"><span>{group.count} / {group.entry_days}</span>{group.pnl_count !== group.count && <p className="text-xs text-amber-300">{group.pnl_count} with P&amp;L</p>}</td>
              <td className={`px-4 py-3 tabular-nums ${color(group.total_pnl)}`}>{money(group.total_pnl)}</td>
              <td className={`px-4 py-3 tabular-nums ${color(group.expectancy)}`}>{money(group.expectancy)}</td>
              <td className={`px-4 py-3 tabular-nums ${color(group.median_pnl)}`}>{money(group.median_pnl)}</td>
              <td className="px-4 py-3 tabular-nums">{percent(group.win_rate)}</td>
              <td className="px-4 py-3 tabular-nums">{factor(group)}</td>
              <td className="px-4 py-3 tabular-nums">{percent(group.avg_pnl_pct)}<p className="text-xs text-muted-foreground">n={group.percentage_count}</p></td>
            </tr>)}
            {!groups.length && <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">No groups match this selection and minimum sample.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">Average return is an unweighted mean of available trade percentages. Dollar results reflect actual sizing; these comparisons do not measure planned risk or prove an edge.</p>
    </section>

    <section ref={tradesSection} aria-labelledby="analytics-trades" className="scroll-mt-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 id="analytics-trades" className="text-sm font-semibold">{selection?.label ?? "Trades in this selection"}</h2><p className="mt-1 text-xs text-muted-foreground">{trades.length} trades · most recent close first · timestamps in New York time</p></div>
        {selection && <button type="button" onClick={() => { setSelection(null); setPage(0); }} className="text-sm text-muted-foreground hover:text-foreground">Show all selected trades</button>}
      </div>
      <div className="max-w-full overflow-x-auto rounded-lg border bg-card">
        <table className="w-full whitespace-nowrap text-sm" aria-label="Analytics trades">
          <thead className="bg-muted text-xs text-muted-foreground"><tr>{["Trade", "Account", "Entered", "Closed", "P&L", "Return"].map((label) => <th key={label} className="px-4 py-3 text-left font-medium">{label}</th>)}</tr></thead>
          <tbody className="divide-y divide-border">{trades.slice(page * pageSize, (page + 1) * pageSize).map((trade) => <tr key={trade.id} className="hover:bg-muted/40">
            <td className="px-4 py-3"><Link href={`/trades/${trade.id}`} className="font-semibold hover:underline">{trade.ticker}</Link><p className="text-xs text-muted-foreground">{trade.instrument_type === "option" ? `${trade.expiration ?? ""} · ${trade.strike ?? "—"} ${trade.option_type ?? "option"}` : "Stock"} · {trade.status}</p></td>
            <td className="px-4 py-3">{accountNames.get(trade.account_id) ?? "Unknown account"}</td>
            <td className="px-4 py-3 text-xs tabular-nums">{trade.opened_at.replace("T", " ").slice(0, 16)}</td>
            <td className="px-4 py-3 text-xs tabular-nums">{trade.closed_at.replace("T", " ").slice(0, 16)}</td>
            <td className={`px-4 py-3 tabular-nums ${color(trade.realized_pnl)}`}>{money(trade.realized_pnl)}</td>
            <td className="px-4 py-3 tabular-nums">{percent(trade.pnl_pct)}</td>
          </tr>)}{!trades.length && <tr><td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">No closed trades in this selection. Try a wider date range or reset filters.</td></tr>}</tbody>
        </table>
      </div>
      {trades.length > pageSize && <div className="flex items-center justify-end gap-3 text-xs">
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Previous</button>
        <span>Page {page + 1} of {Math.ceil(trades.length / pageSize)}</span>
        <button type="button" disabled={(page + 1) * pageSize >= trades.length} onClick={() => setPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
      </div>}
    </section>
  </div>;
}
