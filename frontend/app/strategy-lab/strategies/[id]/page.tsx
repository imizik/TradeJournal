import Link from "next/link";
import { getStrategy, listRuns } from "@/lib/strategy-lab/api";
import { formatStrategyDateTime } from "@/lib/strategy-lab/format";
import type { StrategyRunSummary, StrategyVersionSummary } from "@/lib/strategy-lab/types";

export default async function StrategyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [strategy, runPage] = await Promise.all([
    getStrategy(id),
    listRuns({ strategyId: id, limit: 200 }),
  ]);
  const runs = runPage.items;
  const runsByVersion = new Map<string, StrategyRunSummary[]>();
  for (const run of runs) {
    const current = runsByVersion.get(run.strategy_version_id) ?? [];
    current.push(run);
    runsByVersion.set(run.strategy_version_id, current);
  }

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <header className="space-y-4">
        <Link href="/strategy-lab" className="text-sm text-muted-foreground hover:text-foreground">
          ← Strategy Lab
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold text-foreground">{strategy.name}</h1>
              <span className="rounded-full border bg-card px-2.5 py-1 text-xs font-medium capitalize text-muted-foreground">
                {humanize(strategy.setup_type)}
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
              {strategy.description || "No strategy description has been recorded yet."}
            </p>
          </div>
          <Link
            href={`/strategy-lab/strategies/${strategy.id}/versions/new`}
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            New Pine version
          </Link>
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard label="Versions" value={String(strategy.versions.length)} />
        <SummaryCard label="Imported runs" value={String(runs.length)} />
        <SummaryCard
          label="Current champion"
          value={strategy.versions.find((version) => version.status === "champion")?.version_label ?? "None"}
        />
      </div>

      {strategy.versions.length === 0 ? (
        <section className="rounded-lg border border-dashed bg-card p-10 text-center">
          <h2 className="font-semibold text-foreground">Store Pine v1</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">
            A version captures the full Pine source, hypothesis, parameters, and execution assumptions that produce a run.
          </p>
          <Link
            href={`/strategy-lab/strategies/${strategy.id}/versions/new`}
            className="mt-5 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Create first version
          </Link>
        </section>
      ) : (
        <section className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Version history</h2>
            <p className="mt-1 text-xs text-muted-foreground">Newest first. Run-backed versions are locked for result-affecting changes.</p>
          </div>

          {strategy.versions.map((version) => (
            <VersionCard key={version.id} version={version} runs={runsByVersion.get(version.id) ?? []} />
          ))}
        </section>
      )}

      {runPage.total > runPage.items.length && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Showing the newest {runPage.items.length} of {runPage.total} runs. Open a version to focus its history.
        </p>
      )}
    </div>
  );
}

function VersionCard({ version, runs }: { version: StrategyVersionSummary; runs: StrategyRunSummary[] }) {
  return (
    <article className="overflow-hidden rounded-lg border bg-card">
      <div className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/strategy-lab/versions/${version.id}`} className="font-semibold text-foreground hover:underline">
                {version.version_label}
              </Link>
              <StatusBadge status={version.status} />
              {version.locked && (
                <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-200">
                  Locked after run
                </span>
              )}
            </div>
            <p className="mt-2 text-sm text-foreground/90">
              {version.hypothesis || "No hypothesis recorded for this version."}
            </p>
            {version.change_summary && (
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Changed: {version.change_summary}</p>
            )}
          </div>
          <div className="text-right text-xs text-muted-foreground">
            <p>{formatDate(version.created_at)}</p>
            <p className="mt-1 font-mono" title={version.source_fingerprint}>
              {version.source_fingerprint.slice(0, 10)}…
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <Chip>{humanize(version.execution_timing)}</Chip>
          <Chip>{humanize(version.session_mode)} session</Chip>
          <Chip>Pyramiding {version.pyramiding}</Chip>
          <Chip>{costLabel(version.commission_type, version.commission_value)} commission</Chip>
          <Chip>{costLabel(version.slippage_type, version.slippage_value)} slippage</Chip>
        </div>
      </div>

      <div className="border-t bg-background/30 px-5 py-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            TradingView runs · {runs.length}
          </p>
          <Link href={`/strategy-lab/versions/${version.id}/import`} className="text-xs font-medium text-sky-300 hover:text-sky-200">
            Import run
          </Link>
        </div>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No results imported for this exact Pine version yet.</p>
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {runs.map((run) => <RunRow key={run.id} run={run} />)}
          </div>
        )}
      </div>
    </article>
  );
}

function RunRow({ run }: { run: StrategyRunSummary }) {
  const metricsLabel =
    run.metrics_status === "ready"
      ? "Metrics ready"
      : run.metrics_status === "stale"
        ? "Metrics stale"
        : "Metrics pending";
  const metricsClass =
    run.metrics_status === "ready"
      ? "bg-emerald-500/10 text-emerald-300"
      : run.metrics_status === "stale"
        ? "bg-amber-500/10 text-amber-200"
        : "bg-secondary text-muted-foreground";

  return (
    <Link
      href={`/strategy-lab/runs/${run.id}`}
      className="rounded-md border bg-card px-3 py-3 transition-colors hover:bg-secondary/60"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">{run.symbol} · {run.timeframe}</p>
          <p className="mt-1 text-xs text-muted-foreground">{dateRange(run.backtest_start, run.backtest_end)}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${metricsClass}`}>
          {metricsLabel}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{run.trade_count} trades</span>
        <span className={pnlClass(run.total_net_pnl)}>{formatMoney(run.total_net_pnl, run.currency)}</span>
        <span>{run.net_return_pct == null ? "Return unavailable" : `${signed(run.net_return_pct)}% return`}</span>
      </div>
    </Link>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border bg-card p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{value}</p></div>;
}

function StatusBadge({ status }: { status: string }) {
  const style = status === "champion" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : status === "challenger" ? "border-sky-500/30 bg-sky-500/10 text-sky-300" : "border-border bg-secondary text-muted-foreground";
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${style}`}>{status}</span>;
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full border bg-background px-2 py-1">{children}</span>;
}

function humanize(value: string) { return value.replace(/_/g, " "); }
function formatDate(value: string) { return formatStrategyDateTime(value, "UTC", { hour: undefined, minute: undefined, timeZoneName: undefined }); }
function dateRange(start: string | null, end: string | null) { return start || end ? `${start ?? "Start unknown"} → ${end ?? "End unknown"}` : "Backtest dates not recorded"; }
function costLabel(type: string, value: string | number | null) { return type === "none" ? "No" : `${humanize(type)}${value == null ? "" : ` ${value}`}`; }
function signed(value: string | number) { const number = Number(value); return `${number >= 0 ? "+" : ""}${number.toFixed(2)}`; }
function pnlClass(value: string | number | null) { if (value == null) return "text-muted-foreground"; return Number(value) >= 0 ? "text-emerald-300" : "text-red-300"; }
function formatMoney(value: string | number | null, currency: string) { if (value == null) return "P&L unavailable"; const number = Number(value); return `${number >= 0 ? "+" : "-"}${new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(Math.abs(number))}`; }
