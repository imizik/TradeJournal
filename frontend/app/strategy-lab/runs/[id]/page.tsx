import Link from "next/link";
import RunMetricsPanel from "@/components/strategy-lab/RunMetricsPanel";
import StrategyRunTradesTable from "@/components/strategy-lab/StrategyRunTradesTable";
import {
  getMetricsOrNull,
  getRun,
  getRunTrades,
} from "@/lib/strategy-lab/api";
import {
  formatMoney,
  formatStrategyDate,
  formatStrategyDateTime,
} from "@/lib/strategy-lab/format";

export default async function StrategyRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [run, trades, metrics] = await Promise.all([
    getRun(id),
    getRunTrades(id, { limit: 100 }),
    getMetricsOrNull(id),
  ]);

  return (
    <div className="mx-auto max-w-[1600px] space-y-7">
      <header>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Link href="/strategy-lab" className="hover:text-foreground">Strategy Lab</Link>
          <span>/</span>
          <Link
            href={`/strategy-lab/strategies/${run.strategy_definition_id}`}
            className="hover:text-foreground"
          >
            {run.strategy_name}
          </Link>
          <span>/</span>
          <Link
            href={`/strategy-lab/versions/${run.strategy_version_id}`}
            className="hover:text-foreground"
          >
            {run.version_label}
          </Link>
        </div>

        <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-xl font-semibold text-foreground">
                {run.symbol} · {run.timeframe}
              </h1>
              <span className="text-sm text-muted-foreground">Simulated strategy run</span>
            </div>
            <p className="mt-1 text-sm tabular-nums text-muted-foreground">
              {runPeriod(run.backtest_start, run.backtest_end, run.observed_start_at, run.observed_end_at, run.source_timezone)}
              <span className="mx-2">·</span>
              {run.trade_count} imported trade{run.trade_count === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge label={run.version_status} />
            <StatusBadge label={`${run.metrics_status} metrics`} metrics={run.metrics_status} />
          </div>
        </div>
      </header>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <div className="min-w-0 rounded-lg border bg-card">
          <h2 className="border-b px-3.5 py-2.5 text-[13.5px] font-semibold tracking-tight">Research context</h2>
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <TextFact
              label="Version hypothesis"
              value={run.version_hypothesis}
              empty="No hypothesis recorded."
            />
            <TextFact
              label="Controlled change"
              value={run.version_change_summary}
              empty="No change summary recorded."
            />
            <TextFact label="Run notes" value={run.notes} empty="No run-specific notes." />
            <div>
              <p className="text-xs text-muted-foreground">Parameters</p>
              <pre className="mt-2 max-h-52 overflow-auto rounded-md border bg-background p-3 text-xs leading-relaxed text-foreground/85">
                {JSON.stringify(run.parameters, null, 2)}
              </pre>
            </div>
          </div>
        </div>

        <div className="min-w-0 rounded-lg border bg-card">
          <h2 className="border-b px-3.5 py-2.5 text-[13.5px] font-semibold tracking-tight">Source identity</h2>
          <dl className="space-y-3 p-4 text-sm">
            <SourceFact label="File" value={run.source_file_name || "TradingView CSV"} />
            <SourceFact label="Source" value={run.source} />
            <SourceFact label="Timezone" value={run.source_timezone} />
            <SourceFact label="Warnings" value={String(run.source_warning_count)} />
            <SourceFact
              label="Imported"
              value={formatStrategyDateTime(run.imported_at, "UTC")}
            />
            <SourceFact label="CSV SHA-256" value={run.source_sha256 || "—"} mono />
            <SourceFact label="Version fingerprint" value={run.version_fingerprint} mono />
          </dl>
        </div>
      </section>

      <section>
        <div className="mb-3">
          <h2 className="text-[13.5px] font-semibold tracking-tight">
            Frozen test assumptions
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Stored on this run so later strategy revisions cannot rewrite its interpretation.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          <Assumption label="Initial capital" value={formatMoney(run.initial_capital, run.currency)} />
          <Assumption label="Currency" value={run.currency} />
          <Assumption label="Execution" value={humanize(run.execution_timing)} />
          <Assumption label="Session" value={humanize(run.session_mode)} />
          <Assumption label="Extended hours" value={run.extended_hours ? "Included" : "Excluded"} />
          <Assumption label="Commission" value={costLabel(run.commission_type, run.commission_value)} />
          <Assumption label="Slippage" value={costLabel(run.slippage_type, run.slippage_value)} />
          <Assumption label="Pyramiding" value={String(run.pyramiding)} />
        </div>
      </section>

      <RunMetricsPanel
        runId={run.id}
        currency={run.currency}
        initialCapital={run.initial_capital}
        initialStatus={run.metrics_status}
        initialMetrics={metrics}
      />

      <StrategyRunTradesTable
        runId={run.id}
        sourceTimezone={run.source_timezone}
        currency={run.currency}
        initialPage={trades}
      />
    </div>
  );
}

function TextFact({ label, value, empty }: { label: string; value: string | null; empty: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-2 text-sm leading-relaxed ${value ? "text-foreground/90" : "text-muted-foreground"}`}>
        {value || empty}
      </p>
    </div>
  );
}

function SourceFact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`${mono ? "break-all font-mono text-xs" : "text-sm"} text-right text-foreground/85`} title={mono ? value : undefined}>
        {mono && value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value}
      </dd>
    </div>
  );
}

function Assumption({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-2 text-sm font-semibold capitalize text-foreground">{value}</p>
    </div>
  );
}

function StatusBadge({ label, metrics }: { label: string; metrics?: "pending" | "ready" | "stale" }) {
  const style = metrics === "ready"
    ? "bg-secondary text-muted-foreground"
    : metrics === "stale"
      ? "bg-primary/15 text-primary"
      : "bg-secondary text-muted-foreground";
  return <span className={`inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium capitalize ${style}`}>{label}</span>;
}

function runPeriod(
  backtestStart: string | null,
  backtestEnd: string | null,
  observedStart: string | null,
  observedEnd: string | null,
  timezone: string,
) {
  if (backtestStart || backtestEnd) {
    return `${formatStrategyDate(backtestStart)} → ${formatStrategyDate(backtestEnd)}`;
  }
  return `${formatStrategyDateTime(observedStart, timezone, { hour: undefined, minute: undefined, timeZoneName: undefined })} → ${formatStrategyDateTime(observedEnd, timezone, { hour: undefined, minute: undefined, timeZoneName: undefined })}`;
}

function humanize(value: string) {
  return value.replaceAll("_", " ");
}

function costLabel(type: string, value: string | null) {
  return type === "none" ? "None" : `${humanize(type)}${value == null ? "" : ` · ${value}`}`;
}
