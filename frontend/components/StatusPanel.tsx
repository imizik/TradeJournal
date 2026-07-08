"use client";

import { useEffect, useRef, useState } from "react";
import { api, CoverageStats, JobStatus } from "@/lib/api";
import { X, RefreshCw } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Jobs = {
  polygon: JobStatus | null;
  alpaca: JobStatus | null;
  path: JobStatus | null;
};

const JOB_LABELS: Record<keyof Jobs, string> = {
  polygon: "Polygon Enrichment",
  alpaca: "Alpaca Context",
  path: "Trade Path Metrics",
};

const JOB_COLORS: Record<keyof Jobs, { bar: string; dot: string }> = {
  polygon: { bar: "bg-sky-500", dot: "bg-sky-400" },
  alpaca:  { bar: "bg-violet-500", dot: "bg-violet-400" },
  path:    { bar: "bg-teal-500", dot: "bg-teal-400" },
};

const JOB_RATE: Record<keyof Jobs, string> = {
  polygon: "3 req/min · ~20s/call",
  alpaca:  "60 req/min · ~1s/call",
  path:    "no API limit",
};

function fmtEta(secs: number): string {
  if (secs < 60) return `~${Math.round(secs)}s left`;
  if (secs < 3600) return `~${Math.round(secs / 60)}m left`;
  return `~${(secs / 3600).toFixed(1)}h left`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ProgressBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/10">
      <div
        className={`absolute left-0 top-0 h-full rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${Math.max(2, pct)}%` }}
      />
    </div>
  );
}

function ActiveJobRow({ jobKey, job }: { jobKey: keyof Jobs; job: JobStatus }) {
  const { bar, dot } = JOB_COLORS[jobKey];
  const isSetup = job.done === 0 && !!job.current;
  const pct = isSetup ? 0 : job.total > 0 ? (job.done / job.total) * 100 : 0;

  // ETA — only meaningful once progress has started
  let eta: string | null = null;
  if (!isSetup && job.started_at && job.done > 0 && job.done < job.total) {
    const elapsedSecs = (Date.now() - new Date(job.started_at).getTime()) / 1000;
    if (elapsedSecs > 3) {
      const rate = job.done / elapsedSecs; // fills per second
      const remainingSecs = (job.total - job.done) / rate;
      eta = fmtEta(remainingSecs);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${dot}`} />
            <span className={`relative inline-flex h-2 w-2 rounded-full ${dot}`} />
          </span>
          <span className="text-sm font-medium text-foreground">{JOB_LABELS[jobKey]}</span>
        </div>
        <div className="flex items-center gap-2 text-xs tabular-nums text-muted-foreground">
          {!isSetup && <span>{job.done.toLocaleString()} / {job.total.toLocaleString()}</span>}
          {eta && <span className="text-muted-foreground/60">{eta}</span>}
        </div>
      </div>
      <ProgressBar pct={pct} color={bar} />
      {job.current && (
        <p className="truncate text-xs text-muted-foreground/60">{job.current}</p>
      )}
      <p className="text-[10px] text-muted-foreground/40">{JOB_RATE[jobKey]}</p>
    </div>
  );
}

function CoverageRow({
  label,
  done,
  total,
  missing,
  color,
}: {
  label: string;
  done: number;
  total: number;
  missing: number;
  color: string;
}) {
  const pct = total > 0 ? (done / total) * 100 : 100;
  const complete = missing === 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground/80">{label}</span>
        <span className={complete ? "text-emerald-400" : "text-amber-400"}>
          {complete ? "✓ complete" : `${missing.toLocaleString()} missing`}
        </span>
      </div>
      <ProgressBar pct={pct} color={color} />
      <div className="flex justify-between text-[10px] text-muted-foreground/50">
        <span>{done.toLocaleString()} enriched</span>
        <span>{total.toLocaleString()} total</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main drawer
// ---------------------------------------------------------------------------

type Props = { open: boolean; onClose: () => void };

export default function StatusPanel({ open, onClose }: Props) {
  const [jobs, setJobs] = useState<Jobs>({ polygon: null, alpaca: null, path: null });
  const [coverage, setCoverage] = useState<CoverageStats | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchJobs() {
    const [polygon, alpaca, path] = await Promise.allSettled([
      api.enrichStatus(),
      api.alpacaEnrichStatus(),
      api.tradePathStatus(),
    ]);
    setJobs({
      polygon: polygon.status === "fulfilled" ? polygon.value : null,
      alpaca:  alpaca.status  === "fulfilled" ? alpaca.value  : null,
      path:    path.status    === "fulfilled" ? path.value    : null,
    });
  }

  async function fetchCoverage() {
    setCoverageLoading(true);
    setCoverageError(null);
    try {
      setCoverage(await api.coverage());
    } catch (e) {
      setCoverageError(e instanceof Error ? e.message : "Failed");
    } finally {
      setCoverageLoading(false);
    }
  }

  useEffect(() => {
    if (!open) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    fetchJobs();
    fetchCoverage();
    pollRef.current = setInterval(() => {
      if (!document.hidden) fetchJobs();
    }, 5000);
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [open]);

  const activeJobs = (Object.entries(jobs) as [keyof Jobs, JobStatus | null][]).filter(
    ([, j]) => j?.running
  );

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity duration-200 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />

      {/* Drawer — slides in from the left, same width as nav so it replaces it visually */}
      <div
        className={`fixed left-0 top-0 z-50 flex h-screen w-72 flex-col bg-card shadow-2xl transition-transform duration-250 ease-in-out ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Background Jobs</h2>
            <p className="text-xs text-muted-foreground">Enrichment pipeline status</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-7">

          {/* Active jobs */}
          <section>
            <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              Active Jobs
            </p>
            {activeJobs.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3">
                <span className="h-2 w-2 rounded-full bg-muted-foreground/30" />
                <p className="text-xs text-muted-foreground">No jobs currently running</p>
              </div>
            ) : (
              <div className="space-y-5">
                {activeJobs.map(([key, job]) => (
                  <ActiveJobRow key={key} jobKey={key} job={job!} />
                ))}
              </div>
            )}
          </section>

          <div className="border-t border-border/60" />

          {/* Coverage */}
          <section>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                Enrichment Coverage
              </p>
              <button
                onClick={fetchCoverage}
                disabled={coverageLoading}
                className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                title="Refresh coverage"
              >
                <RefreshCw className={`h-3 w-3 ${coverageLoading ? "animate-spin" : ""}`} />
              </button>
            </div>

            {coverageError && (
              <p className="text-xs text-red-400">{coverageError}</p>
            )}

            {!coverage && !coverageError && (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="space-y-1.5 animate-pulse">
                    <div className="h-3 w-32 rounded bg-muted" />
                    <div className="h-1.5 w-full rounded-full bg-muted" />
                    <div className="h-2 w-24 rounded bg-muted" />
                  </div>
                ))}
              </div>
            )}

            {coverage && (
              <div className="space-y-5">
                <div>
                  <p className="mb-3 text-[10px] font-medium uppercase text-muted-foreground/40">
                    Fills · {coverage.fills.total.toLocaleString()} total
                  </p>
                  <div className="space-y-4">
                    <CoverageRow
                      label="Polygon"
                      done={coverage.fills.polygon_enriched}
                      total={coverage.fills.total}
                      missing={coverage.fills.polygon_missing}
                      color="bg-sky-500"
                    />
                    <CoverageRow
                      label="Alpaca Context"
                      done={coverage.fills.alpaca_enriched}
                      total={coverage.fills.total}
                      missing={coverage.fills.alpaca_missing}
                      color="bg-violet-500"
                    />
                  </div>
                </div>

                <div>
                  <p className="mb-3 text-[10px] font-medium uppercase text-muted-foreground/40">
                    Closed Trades · {coverage.trades.total_closed.toLocaleString()} total
                  </p>
                  <CoverageRow
                    label="Path Metrics"
                    done={coverage.trades.path_metrics_done}
                    total={coverage.trades.total_closed}
                    missing={coverage.trades.path_metrics_missing}
                    color="bg-teal-500"
                  />
                </div>
              </div>
            )}
          </section>

          <div className="border-t border-border/60" />

          <p className="text-[10px] leading-relaxed text-muted-foreground/40">
            Run jobs from the dashboard action bar. Coverage updates each time this panel opens.
          </p>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Hook — tells the nav button whether any job is running (for pulse dot)
// ---------------------------------------------------------------------------

export function useAnyJobRunning(): boolean {
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function check() {
      const results = await Promise.allSettled([
        api.enrichStatus(),
        api.alpacaEnrichStatus(),
        api.tradePathStatus(),
      ]);
      if (!mounted) return;
      setRunning(results.some((r) => r.status === "fulfilled" && r.value.running));
    }
    check();
    // 30s idle cadence + skip hidden tabs: this poll runs for the whole app
    // session and every request is metered egress on hosted Postgres.
    const id = setInterval(() => {
      if (!document.hidden) check();
    }, 30000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  return running;
}
