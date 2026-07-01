"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Database,
  History,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings2,
  X,
} from "lucide-react";
import { api, SyncJob, SyncRun, SyncSummary } from "@/lib/api";

type EnrichRange = "day" | "week" | "month" | "all";
type Tab = "jobs" | "history" | "advanced";

const ENRICHMENT_JOBS = new Set(["polygon_enrich", "alpaca_enrich", "trade_path"]);

function fmtRelative(value: string | null | undefined) {
  if (!value) return "Never synced";
  const diff = Date.now() - new Date(value).getTime();
  if (diff < 60_000) return "Synced just now";
  if (diff < 3_600_000) return `Synced ${Math.max(1, Math.round(diff / 60_000))}m ago`;
  if (diff < 86_400_000) return `Synced ${Math.round(diff / 3_600_000)}h ago`;
  return `Synced ${Math.round(diff / 86_400_000)}d ago`;
}

function fmtTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtDuration(seconds: number | null) {
  if (seconds == null) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.round(seconds / 60)}m`;
}

function statusClass(status: string) {
  if (status === "running" || status === "queued") return "border-sky-500/30 bg-sky-500/10 text-sky-300";
  if (status === "succeeded") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (status === "failed") return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-border bg-secondary text-muted-foreground";
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${statusClass(status)}`}>
      {status === "succeeded" ? "success" : status}
    </span>
  );
}

function SyncStatusIndicator({ summary }: { summary: SyncSummary | null }) {
  if (!summary) {
    return (
      <span className="hidden items-center gap-1.5 rounded border border-border px-2.5 py-1.5 text-xs text-muted-foreground sm:inline-flex">
        <Clock3 className="h-3.5 w-3.5" />
        Checking sync
      </span>
    );
  }

  if (summary.errors_count > 0 && !summary.running) {
    return (
      <span className="hidden items-center gap-1.5 rounded border border-red-500/30 bg-red-500/10 px-2.5 py-1.5 text-xs text-red-300 sm:inline-flex">
        <AlertCircle className="h-3.5 w-3.5" />
        {summary.errors_count} sync error{summary.errors_count === 1 ? "" : "s"}
      </span>
    );
  }

  if (summary.running && summary.active_job) {
    const job = summary.active_job;
    const progress = job.total > 0 ? ` ${job.done}/${job.total}` : "";
    return (
      <span className="hidden max-w-[320px] items-center gap-1.5 rounded border border-sky-500/30 bg-sky-500/10 px-2.5 py-1.5 text-xs text-sky-300 sm:inline-flex">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span className="truncate">Sync running: {job.label}{progress}</span>
      </span>
    );
  }

  return (
    <span className="hidden items-center gap-1.5 rounded border border-border px-2.5 py-1.5 text-xs text-muted-foreground sm:inline-flex">
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
      {fmtRelative(summary.last_success_at)}
    </span>
  );
}

export default function DashboardActions() {
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refreshSummary() {
    try {
      setSummary(await api.syncSummary());
    } catch {
      // Keep the toolbar quiet if the backend is still booting.
    }
  }

  useEffect(() => {
    refreshSummary();
    pollRef.current = setInterval(refreshSummary, summary?.running ? 2000 : 15000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [summary?.running]);

  return (
    <div className="flex items-center gap-2">
      <SyncStatusIndicator summary={summary} />
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded bg-foreground px-3 py-1.5 text-xs font-semibold text-background transition-colors hover:bg-foreground/90"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        Sync / Update Data
      </button>
      <SyncCenterDrawer open={open} onClose={() => setOpen(false)} onSummaryChange={setSummary} />
    </div>
  );
}

function SyncCenterDrawer({
  open,
  onClose,
  onSummaryChange,
}: {
  open: boolean;
  onClose: () => void;
  onSummaryChange: (summary: SyncSummary) => void;
}) {
  const [tab, setTab] = useState<Tab>("jobs");
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  const [range, setRange] = useState<EnrichRange>("week");
  const [forceAll, setForceAll] = useState(false);
  const [details, setDetails] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const running = useMemo(() => jobs.some((job) => job.running) || Boolean(summary?.running), [jobs, summary]);

  async function refresh() {
    const [nextSummary, nextJobs] = await Promise.all([api.syncSummary(), api.syncJobs()]);
    setSummary(nextSummary);
    setJobs(nextJobs);
    onSummaryChange(nextSummary);
    if (tab === "history") {
      setRuns(await api.syncRuns());
    }
  }

  useEffect(() => {
    if (!open) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }

    refresh().catch((e) => setMessage((e as Error).message));
    pollRef.current = setInterval(() => {
      refresh().catch(() => {});
    }, running ? 2000 : 10000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [open, tab, running]);

  async function runPipeline() {
    setBusyAction("pipeline");
    setMessage(null);
    try {
      await api.runSyncPipeline();
      setMessage("Full sync pipeline queued.");
      await refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function connectGmail() {
    setBusyAction("gmail_auth");
    setMessage("Opening Gmail authorization...");
    try {
      const { auth_url } = await api.startGmailAuth();
      window.location.assign(auth_url);
    } catch (e) {
      setMessage((e as Error).message);
      setBusyAction(null);
    }
  }

  async function runJob(job: SyncJob) {
    setBusyAction(job.job_type);
    setMessage(null);
    try {
      const effectiveRange = forceAll && job.job_type === "alpaca_enrich" ? "all" : range;
      await api.runSyncJob(job.job_type, effectiveRange, forceAll && ENRICHMENT_JOBS.has(job.job_type));
      setMessage(`${job.label} queued.`);
      await refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function runAdvanced(kind: "rebuild" | "resync") {
    const text =
      kind === "rebuild"
        ? "Rebuild All will delete derived trade rows and recreate FIFO trades from existing fills. Continue?"
        : "Resync All will delete imported fills, keep manual fills, re-import from Gmail, and rebuild trades. Continue?";
    if (!window.confirm(text)) return;

    setBusyAction(kind);
    setMessage(null);
    try {
      if (kind === "rebuild") {
        await api.advancedRebuildAll();
      } else {
        await api.advancedResyncAll();
      }
      setMessage(kind === "rebuild" ? "Advanced rebuild queued." : "Advanced resync queued.");
      await refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed right-0 top-0 z-50 flex h-screen w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="border-b border-border px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-base font-semibold text-foreground">Data Sync Center</h2>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Run the full pipeline or manage each sync and enrichment job separately.
              </p>
            </div>
            <button
              onClick={onClose}
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="Close Sync Center"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <SyncStatusIndicator summary={summary} />
            <button
              onClick={runPipeline}
              disabled={!!busyAction || !!running}
              className="inline-flex items-center gap-2 rounded bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-emerald-950 transition-colors hover:bg-emerald-400 disabled:opacity-50"
            >
              {busyAction === "pipeline" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Sync Everything
            </button>
          </div>

          {message && (
            <div className="mt-3 rounded border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
              {message}
            </div>
          )}
        </header>

        <div className="flex border-b border-border px-5">
          <TabButton active={tab === "jobs"} onClick={() => setTab("jobs")} icon={<RefreshCw className="h-3.5 w-3.5" />}>
            Jobs
          </TabButton>
          <TabButton active={tab === "history"} onClick={() => setTab("history")} icon={<History className="h-3.5 w-3.5" />}>
            History
          </TabButton>
          <TabButton active={tab === "advanced"} onClick={() => setTab("advanced")} icon={<Settings2 className="h-3.5 w-3.5" />}>
            Advanced
          </TabButton>
        </div>

        <main className="flex-1 overflow-y-auto px-5 py-5">
          {tab === "jobs" && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3">
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  Range
                  <span className="relative">
                    <select
                      value={range}
                      onChange={(e) => setRange(e.target.value as EnrichRange)}
                      suppressHydrationWarning
                      className="appearance-none rounded border border-border bg-background py-1 pl-2 pr-7 text-xs text-foreground focus:outline-none"
                    >
                      <option value="day">1d</option>
                      <option value="week">1w</option>
                      <option value="month">1mo</option>
                      <option value="all">All</option>
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-1.5 top-1.5 h-3 w-3 text-muted-foreground" />
                  </span>
                </label>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={forceAll}
                    onChange={(e) => setForceAll(e.target.checked)}
                    className="accent-emerald-500"
                  />
                  Force re-run existing enrichment/path metrics
                </label>
                <button
                  onClick={connectGmail}
                  disabled={!!busyAction}
                  className="inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
                >
                  {busyAction === "gmail_auth" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Connect Gmail
                </button>
              </div>

              <div className="grid gap-3">
                {jobs.map((job) => (
                  <SyncJobRow
                    key={job.job_type}
                    job={job}
                    busy={busyAction === job.job_type}
                    disabled={!!busyAction || (running && !job.running)}
                    detailsOpen={details === job.job_type}
                    onDetails={() => setDetails(details === job.job_type ? null : job.job_type)}
                    onRun={() => runJob(job)}
                  />
                ))}
              </div>
            </div>
          )}

          {tab === "history" && (
            <SyncHistory runs={runs} onRefresh={async () => setRuns(await api.syncRuns())} />
          )}

          {tab === "advanced" && (
            <AdvancedSyncActions
              disabled={!!busyAction || !!running}
              busyAction={busyAction}
              onRun={runAdvanced}
            />
          )}
        </main>
      </aside>
    </>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-3 text-xs font-medium transition-colors ${
        active
          ? "border-foreground text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function SyncJobRow({
  job,
  busy,
  disabled,
  detailsOpen,
  onDetails,
  onRun,
}: {
  job: SyncJob;
  busy: boolean;
  disabled: boolean;
  detailsOpen: boolean;
  onDetails: () => void;
  onRun: () => void;
}) {
  const pct = job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;

  return (
    <section className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={job.status} />
            <h3 className="text-sm font-semibold text-foreground">{job.label}</h3>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{job.description}</p>
          <p className="mt-2 truncate text-xs text-muted-foreground/80">
            {job.message ?? "Idle. No recent message."}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={onDetails}
            className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            Details
          </button>
          <button
            onClick={onRun}
            disabled={disabled || job.running}
            className="inline-flex min-w-16 items-center justify-center gap-1.5 rounded bg-secondary px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80 disabled:opacity-50"
          >
            {busy || job.running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            {job.status === "failed" ? "Retry" : "Run"}
          </button>
        </div>
      </div>

      {(job.running || job.total > 0) && (
        <div className="mt-3">
          <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${Math.max(job.running ? 4 : 0, pct)}%` }} />
          </div>
          <div className="mt-1 flex flex-wrap justify-between gap-2 text-[11px] text-muted-foreground">
            <span>{job.done.toLocaleString()} / {job.total.toLocaleString()}</span>
            <span>{job.items_processed.toLocaleString()} processed - {job.errors_count} errors</span>
          </div>
        </div>
      )}

      {detailsOpen && (
        <div className="mt-3 grid gap-2 rounded border border-border bg-background p-3 text-xs text-muted-foreground sm:grid-cols-2">
          <Detail label="Last run" value={fmtTime(job.last_run_at)} />
          <Detail label="Started" value={fmtTime(job.started_at)} />
          <Detail label="Finished" value={fmtTime(job.finished_at)} />
          <Detail label="Latest error" value={job.error_summary ?? "-"} />
        </div>
      )}
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/60">{label}</p>
      <p className="mt-0.5 break-words text-foreground">{value}</p>
    </div>
  );
}

function SyncHistory({ runs, onRefresh }: { runs: SyncRun[]; onRefresh: () => void }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Sync History</h3>
        <button
          onClick={onRefresh}
          className="inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-secondary text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Timestamp</th>
              <th className="px-3 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium">Duration</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Items</th>
              <th className="px-3 py-2 font-medium">Errors</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-card">
            {runs.map((run) => (
              <tr key={run.id}>
                <td className="px-3 py-2 text-muted-foreground">{fmtTime(run.started_at ?? run.created_at)}</td>
                <td className="px-3 py-2 text-foreground">{run.label}</td>
                <td className="px-3 py-2 text-muted-foreground">{fmtDuration(run.duration_seconds)}</td>
                <td className="px-3 py-2"><StatusBadge status={run.status} /></td>
                <td className="px-3 py-2 tabular-nums text-muted-foreground">{run.items_processed.toLocaleString()}</td>
                <td className="px-3 py-2 text-muted-foreground">{run.error_summary ?? run.errors_count}</td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td className="px-3 py-6 text-center text-muted-foreground" colSpan={6}>
                  No sync history yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdvancedSyncActions({
  disabled,
  busyAction,
  onRun,
}: {
  disabled: boolean;
  busyAction: string | null;
  onRun: (kind: "rebuild" | "resync") => void;
}) {
  return (
    <div className="space-y-3">
      <section className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
        <h3 className="text-sm font-semibold text-amber-200">Rebuild All</h3>
        <p className="mt-1 text-xs leading-relaxed text-amber-100/80">
          Deletes derived trade, trade-fill, tag, and path rows, then reconstructs trades from the current fill history.
          Fill rows are preserved.
        </p>
        <button
          onClick={() => onRun("rebuild")}
          disabled={disabled}
          className="mt-3 inline-flex items-center gap-2 rounded border border-amber-400/40 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-400/10 disabled:opacity-50"
        >
          {busyAction === "rebuild" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          Run Rebuild All
        </button>
      </section>

      <section className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
        <h3 className="text-sm font-semibold text-red-200">Resync All</h3>
        <p className="mt-1 text-xs leading-relaxed text-red-100/80">
          Deletes imported Gmail fills, keeps manual fills, re-imports execution emails from Gmail, and rebuilds derived trades.
          Use this only when import history needs repair.
        </p>
        <button
          onClick={() => onRun("resync")}
          disabled={disabled}
          className="mt-3 inline-flex items-center gap-2 rounded border border-red-400/40 px-3 py-1.5 text-xs font-medium text-red-100 hover:bg-red-400/10 disabled:opacity-50"
        >
          {busyAction === "resync" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <AlertCircle className="h-3.5 w-3.5" />}
          Run Resync All
        </button>
      </section>
    </div>
  );
}
