"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";
type EnrichRange = "day" | "week" | "month" | "all";

export default function DashboardActions() {
  const [syncStatus, setSyncStatus] = useState<Status>("idle");
  const [rebuildStatus, setRebuildStatus] = useState<Status>("idle");
  const [resyncStatus, setResyncStatus] = useState<Status>("idle");
  const [enrichStatus, setEnrichStatus] = useState<Status>("idle");
  const [enrichRange, setEnrichRange] = useState<EnrichRange>("week");
  const [enrichProgress, setEnrichProgress] = useState<{ done: number; total: number; current: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const busy = syncStatus === "loading" || rebuildStatus === "loading" || resyncStatus === "loading" || enrichStatus === "loading";

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  async function handleSync() {
    setSyncStatus("loading");
    setMsg(null);
    try {
      const r = await api.importFills();
      setMsg(`Synced: ${r.saved} new fill(s), ${r.skipped} skipped.`);
      setSyncStatus("done");
    } catch (e) {
      setMsg(`Sync failed: ${(e as Error).message}`);
      setSyncStatus("error");
    } finally {
      setTimeout(() => setSyncStatus("idle"), 3000);
    }
  }

  async function handleRebuild() {
    setRebuildStatus("loading");
    setMsg(null);
    try {
      const r = await api.rebuild();
      setMsg(`Rebuilt ${r.trades_rebuilt} trade(s).`);
      setRebuildStatus("done");
      window.location.reload();
    } catch (e) {
      setMsg(`Rebuild failed: ${(e as Error).message}`);
      setRebuildStatus("error");
    } finally {
      setTimeout(() => setRebuildStatus("idle"), 3000);
    }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.enrichStatus();
        setEnrichProgress({ done: s.done, total: s.total, current: s.current });
        if (!s.running) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          if (s.error) {
            setMsg(`Enrich failed: ${s.error}`);
            setEnrichStatus("error");
          } else {
            setMsg(`Enriched ${s.enriched} of ${s.total} fill(s).`);
            setEnrichStatus("done");
          }
          setEnrichProgress(null);
          setTimeout(() => setEnrichStatus("idle"), 4000);
        }
      } catch {
        clearInterval(pollRef.current!);
        pollRef.current = null;
        setEnrichStatus("error");
        setEnrichProgress(null);
      }
    }, 2000);
  }

  async function handleEnrich() {
    setEnrichStatus("loading");
    setEnrichProgress(null);
    setMsg(null);
    try {
      const r = await api.enrichMissing(enrichRange);
      if (!r.started) {
        setMsg("No fills missing enrichment data.");
        setEnrichStatus("done");
        setTimeout(() => setEnrichStatus("idle"), 3000);
        return;
      }
      setEnrichProgress({ done: 0, total: r.total_missing, current: "" });
      startPolling();
    } catch (e) {
      setMsg(`Enrich failed: ${(e as Error).message}`);
      setEnrichStatus("error");
      setTimeout(() => setEnrichStatus("idle"), 4000);
    }
  }

  async function handleResyncAll() {
    const confirmed = window.confirm(
      "Resync all will delete every imported fill and rebuilt trade, then re-import everything from Gmail from scratch. Continue?",
    );
    if (!confirmed) return;

    setResyncStatus("loading");
    setMsg(null);
    try {
      const r = await api.resyncAll();
      const anomalySuffix = r.anomalies.length ? ` ${r.anomalies.length} anomaly/anomalies logged.` : "";
      setMsg(`Resynced from scratch: ${r.saved} fill(s) imported, ${r.trades_rebuilt} trade(s) rebuilt.${anomalySuffix}`);
      setResyncStatus("done");
      window.location.reload();
    } catch (e) {
      setMsg(`Resync failed: ${(e as Error).message}`);
      setResyncStatus("error");
    } finally {
      setTimeout(() => setResyncStatus("idle"), 3000);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {msg && <span className="mr-1 text-xs text-muted-foreground">{msg}</span>}
      <a
        href="/daily"
        className="rounded border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
      >
        Daily Review
      </a>
      <a
        href="/fills"
        className="rounded border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
      >
        Manual Fill
      </a>
      <div className="flex items-center rounded border border-border">
        <select
          value={enrichRange}
          onChange={(e) => setEnrichRange(e.target.value as EnrichRange)}
          disabled={busy}
          className="rounded-l bg-transparent px-2 py-1.5 text-xs text-muted-foreground focus:outline-none disabled:opacity-50"
        >
          <option value="day">1d</option>
          <option value="week">1w</option>
          <option value="month">1mo</option>
          <option value="all">All</option>
        </select>
        <button
          onClick={handleEnrich}
          disabled={busy}
          className="rounded-r border-l border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary disabled:opacity-50"
        >
          {enrichStatus === "loading"
            ? enrichProgress && enrichProgress.total > 0
              ? `${enrichProgress.done}/${enrichProgress.total}${enrichProgress.current ? ` ${enrichProgress.current}` : ""}`
              : "Starting..."
            : enrichStatus === "done"
              ? "Done"
              : "Enrich Missing"}
        </button>
      </div>
      <button
        onClick={handleSync}
        disabled={busy}
        className="rounded bg-secondary px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80 disabled:opacity-50"
      >
        {syncStatus === "loading" ? "Syncing..." : syncStatus === "done" ? "Synced OK" : "Sync Emails"}
      </button>
      <button
        onClick={handleRebuild}
        disabled={busy}
        className="rounded bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
      >
        {rebuildStatus === "loading" ? "Rebuilding..." : rebuildStatus === "done" ? "Done" : "Rebuild All"}
      </button>
      <button
        onClick={handleResyncAll}
        disabled={busy}
        className="rounded bg-rose-900/40 px-3 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-900/60 disabled:opacity-50"
      >
        {resyncStatus === "loading" ? "Resyncing..." : resyncStatus === "done" ? "Resynced OK" : "Resync All"}
      </button>
    </div>
  );
}
