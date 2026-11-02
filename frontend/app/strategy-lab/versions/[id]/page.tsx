import Link from "next/link";
import { getVersion, listRuns } from "@/lib/strategy-lab/api";
import {
  formatMoney,
  formatPercentPoints,
  formatStrategyDate,
  formatStrategyDateTime,
} from "@/lib/strategy-lab/format";
import type { StrategyRunSummary } from "@/lib/strategy-lab/types";

export default async function StrategyVersionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [version, runPage] = await Promise.all([
    getVersion(id),
    listRuns({ versionId: id, limit: 200 }),
  ]);

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <header className="space-y-4">
        <Link
          href={`/strategy-lab/strategies/${version.strategy_definition_id}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to strategy
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-foreground">{version.version_label}</h1>
              <StatusBadge status={version.status} />
              {version.locked && (
                <span className="inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium bg-secondary text-muted-foreground">
                  Result-producing fields locked
                </span>
              )}
            </div>
            <p className="mt-1 text-sm tabular-nums text-muted-foreground">
              Created {formatStrategyDateTime(version.created_at, "UTC")} · fingerprint{" "}
              <span className="font-mono text-foreground/70" title={version.source_fingerprint}>
                {version.source_fingerprint.slice(0, 14)}…
              </span>
            </p>
          </div>
          <Link
            href={`/strategy-lab/versions/${version.id}/import`}
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Import TradingView run
          </Link>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <ResearchCard title="Hypothesis" value={version.hypothesis} empty="No hypothesis was recorded for this version." />
        <ResearchCard title="Controlled change" value={version.change_summary} empty="No change summary was recorded." />
      </div>

      <section aria-label="Exact Pine source" className="rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
          <h2 className="text-[13.5px] font-semibold tracking-tight">Exact Pine source</h2>
          {version.source_reference && (
            <span className="max-w-full break-all rounded-md border bg-background px-2 py-1 font-mono text-[11px] text-muted-foreground">
              {version.source_reference}
            </span>
          )}
        </div>
        <div className="p-4">
        <p className="text-xs text-muted-foreground">This source and the assumptions below identify the code that produced imported results.</p>
        <pre className="mt-3 max-h-[46rem] overflow-auto rounded-md border bg-background p-4 text-xs leading-relaxed text-foreground/90">
          <code>{version.pine_source}</code>
        </pre>
      </div></section>

      <section aria-label="Rules and parameters" className="rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5"><h2 className="text-[13.5px] font-semibold tracking-tight">Rules and parameters</h2></div>
<div className="space-y-4 p-4"><p className="text-xs text-muted-foreground">Human-readable intent beside the structured values used for traceability.</p>        <div className="grid gap-4 lg:grid-cols-2">
          <ResearchCard title="Entry rules" value={version.entry_rule_summary} empty="No entry-rule summary recorded." nested />
          <ResearchCard title="Exit rules" value={version.exit_rule_summary} empty="No exit-rule summary recorded." nested />
        </div>
        <div>
          <h3 className="text-xs text-muted-foreground">Parameters</h3>
          <pre className="mt-2 overflow-x-auto rounded-md border bg-background p-4 text-xs leading-relaxed text-foreground/85">
            {JSON.stringify(version.parameters, null, 2)}
          </pre>
        </div>
      </div></section>

      <section className="space-y-4">
        <div>
          <h2 className="text-[13.5px] font-semibold tracking-tight">Execution assumptions</h2>
          <p className="mt-1 text-xs text-muted-foreground">Treat runs as comparable only when result-affecting assumptions align.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Assumption label="Execution" value={humanize(version.execution_timing)} />
          <Assumption label="Session" value={humanize(version.session_mode)} />
          <Assumption label="Commission" value={costLabel(version.commission_type, version.commission_value)} />
          <Assumption label="Slippage" value={costLabel(version.slippage_type, version.slippage_value)} />
          <Assumption label="Pyramiding" value={String(version.pyramiding)} />
          <Assumption label="Parent" value={version.parent_version_id ? "Linked" : "None"} />
        </div>
      </section>

      <section aria-label="Research risks" className="rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5"><h2 className="text-[13.5px] font-semibold tracking-tight">Research risks</h2></div>
<div className="space-y-4 p-4"><p className="text-xs text-muted-foreground">Caveats recorded before interpreting backtest performance.</p>        <div className="grid gap-4 lg:grid-cols-3">
          <RiskCard title="Known limitations" value={version.known_limitations} />
          <RiskCard title="Repainting risk" value={version.repainting_risk_notes} />
          <RiskCard title="Lookahead risk" value={version.lookahead_risk_notes} />
        </div>
      </div></section>

      <section aria-label="TradingView runs" className="rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
          <h2 className="text-[13.5px] font-semibold tracking-tight">TradingView runs</h2>
          <span className="inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium bg-secondary text-muted-foreground tabular-nums">{runPage.total} total</span>
        </div>
<div className="space-y-3 p-4"><p className="text-xs text-muted-foreground">Every run below is bound to this exact version fingerprint.</p>
        {runPage.items.length === 0 ? (
          <div className="rounded-md border border-dashed p-8 text-center">
            <h3 className="text-[13.5px] font-semibold tracking-tight">No imported evidence yet</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">
              Run this Pine version in TradingView, export the Strategy Tester List of Trades CSV, then preview it here.
            </p>
            <Link
              href={`/strategy-lab/versions/${version.id}/import`}
              className="mt-5 inline-flex rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary"
            >
              Import first run
            </Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[940px] text-sm">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <Th>Run</Th>
                  <Th>Period</Th>
                  <Th>Trades</Th>
                  <Th>Net P&amp;L</Th>
                  <Th>Return</Th>
                  <Th>Max drawdown</Th>
                  <Th>Metrics</Th>
                  <Th>Imported</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runPage.items.map((run) => <RunTableRow key={run.id} run={run} />)}
              </tbody>
            </table>
          </div>
        )}
        {runPage.total > runPage.items.length && (
          <p className="text-xs text-muted-foreground">Showing the newest {runPage.items.length} runs.</p>
        )}
      </div></section>
    </div>
  );
}

function RunTableRow({ run }: { run: StrategyRunSummary }) {
  return (
    <tr className="hover:bg-muted/40">
      <Td>
        <Link href={`/strategy-lab/runs/${run.id}`} className="font-semibold text-foreground hover:underline">
          {run.symbol} · {run.timeframe}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">{run.source_file_name || "TradingView CSV"}</p>
      </Td>
      <Td><span className="tabular-nums">{runPeriod(run)}</span></Td>
      <Td><span className="tabular-nums">{run.trade_count}</span></Td>
      <Td><span className={`tabular-nums ${pnlClass(run.total_net_pnl)}`}>{formatMoney(run.total_net_pnl, run.currency)}</span></Td>
      <Td><span className={`tabular-nums ${pnlClass(run.net_return_pct)}`}>{formatPercentPoints(run.net_return_pct)}</span></Td>
      <Td><span className="tabular-nums">{formatPercentPoints(run.max_drawdown_pct)}</span></Td>
      <Td><MetricsBadge status={run.metrics_status} /></Td>
      <Td>{formatStrategyDateTime(run.imported_at, "UTC", { year: undefined, timeZoneName: undefined })}</Td>
    </tr>
  );
}

function ResearchCard({ title, value, empty, nested = false }: { title: string; value: string | null; empty: string; nested?: boolean }) {
  return <div className={nested ? "rounded-md border bg-background" : "rounded-lg border bg-card"}><h2 className="border-b px-3.5 py-2.5 text-[13.5px] font-semibold tracking-tight">{title}</h2><p className={`p-4 text-sm leading-relaxed ${value ? "text-foreground/90" : "text-muted-foreground"}`}>{value || empty}</p></div>;
}

function Assumption({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-sm font-semibold capitalize text-foreground">{value}</p></div>;
}

function RiskCard({ title, value }: { title: string; value: string | null }) {
  return <div className={`rounded-md border bg-background p-4`}><h3 className={`text-xs font-medium text-muted-foreground`}>{title}</h3><p className="mt-2 text-sm leading-relaxed text-foreground/80">{value || "None recorded."}</p></div>;
}

function StatusBadge({ status }: { status: string }) {
  const style = status === "champion" ? "bg-secondary text-foreground" : "bg-secondary text-muted-foreground";
  return <span className={`inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium capitalize ${style}`}>{status}</span>;
}

function MetricsBadge({ status }: { status: StrategyRunSummary["metrics_status"] }) {
  const style = status === "stale" ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground";
  return <span className={`inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium capitalize ${style}`}>{status}</span>;
}

function Th({ children }: { children: React.ReactNode }) { return <th className="whitespace-nowrap px-4 py-2 text-left font-medium">{children}</th>; }
function Td({ children }: { children: React.ReactNode }) { return <td className="px-4 py-3 align-top text-foreground/85">{children}</td>; }
function humanize(value: string) { return value.replace(/_/g, " "); }
function costLabel(type: string, value: string | null) { return type === "none" ? "None" : `${humanize(type)}${value == null ? "" : ` · ${value}`}`; }
function pnlClass(value: string | null) { if (value == null) return "text-muted-foreground"; return Number(value) >= 0 ? "text-emerald-400" : "text-red-400"; }
function runPeriod(run: StrategyRunSummary) {
  if (run.backtest_start || run.backtest_end) return `${formatStrategyDate(run.backtest_start)} → ${formatStrategyDate(run.backtest_end)}`;
  if (run.observed_start_at || run.observed_end_at) {
    return `${formatStrategyDateTime(run.observed_start_at, run.source_timezone, { year: "numeric", hour: undefined, minute: undefined, timeZoneName: undefined })} → ${formatStrategyDateTime(run.observed_end_at, run.source_timezone, { year: "numeric", hour: undefined, minute: undefined, timeZoneName: undefined })}`;
  }
  return "—";
}
