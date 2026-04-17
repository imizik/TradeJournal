"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";

export default function DashboardActions() {
  const [syncStatus, setSyncStatus] = useState<Status>("idle");
  const [rebuildStatus, setRebuildStatus] = useState<Status>("idle");
  const [resyncStatus, setResyncStatus] = useState<Status>("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const busy = syncStatus === "loading" || rebuildStatus === "loading" || resyncStatus === "loading";

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
        href="/fills"
        className="rounded border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
      >
        Manual Fill
      </a>
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
