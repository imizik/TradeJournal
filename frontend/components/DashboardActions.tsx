"use client";

import { useEffect, useRef, useState } from "react";
import { API, api } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";
type EnrichRange = "day" | "week" | "month" | "all";

export default function DashboardActions() {
  const [syncStatus, setSyncStatus] = useState<Status>("idle");
  const [rebuildStatus, setRebuildStatus] = useState<Status>("idle");
  const [resyncStatus, setResyncStatus] = useState<Status>("idle");
  const [enrichStatus, setEnrichStatus] = useState<Status>("idle");
  const [enrichRange, setEnrichRange] = useState<EnrichRange>("week");
  const [enrichProgress, setEnrichProgress] = useState<{ done: number; total: number; current: string } | null>(null);
  const [alpacaEnrichStatus, setAlpacaEnrichStatus] = useState<Status>("idle");
  const [alpacaEnrichProgress, setAlpacaEnrichProgress] = useState<{ done: number; total: number; current: string } | null>(null);
  const [alpacaForce, setAlpacaForce] = useState(false);
  const [pathStatus, setPathStatus] = useState<Status>("idle");
  const [pathProgress, setPathProgress] = useState<{ done: number; total: number; current: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const alpacaPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pathPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Data-modifying ops block each other (sync/rebuild/resync touch fills+trades)
  const dataModifying = syncStatus === "loading" || rebuildStatus === "loading" || resyncStatus === "loading";
  // Enrichment jobs are independent — each only blocks itself
  const enrichBusy = enrichStatus === "loading";
  const alpacaBusy = alpacaEnrichStatus === "loading";
  const pathBusy = pathStatus === "loading";
  // Resync needs everything quiet since it wipes and rebuilds
  const busy = dataModifying;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmailAuth = params.get("gmail_auth");
    if (gmailAuth === "success") {
      setMsg("Gmail connected. Run Sync Emails again.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (gmailAuth === "error") {
      setMsg("Gmail connection was cancelled or failed.");
      window.history.replaceState({}, "", window.location.pathname);
    }

    // Reconnect to any in-progress enrichment after tab switch or remount
    api.enrichStatus().then((s) => {
      if (s.running) {
        setEnrichStatus("loading");
        setEnrichProgress({ done: s.done, total: s.total, current: s.current });
        startPolling();
      }
    }).catch(() => {});

    api.alpacaEnrichStatus().then((s) => {
      if (s.running) {
        setAlpacaEnrichStatus("loading");
        setAlpacaEnrichProgress({ done: s.done, total: s.total, current: s.current });
        startAlpacaPolling();
      }
    }).catch(() => {});

    api.tradePathStatus().then((s) => {
      if (s.running) {
        setPathStatus("loading");
        setPathProgress({ done: s.done, total: s.total, current: s.current });
        startPathPolling();
      }
    }).catch(() => {});

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (alpacaPollRef.current) clearInterval(alpacaPollRef.current);
      if (pathPollRef.current) clearInterval(pathPollRef.current);
    };
  }, []);

  async function connectGmail() {
    setSyncStatus("loading");
    setMsg("Opening Gmail authorization...");
    const { auth_url } = await api.startGmailAuth();
    window.location.assign(auth_url);
  }

  async function handleSync() {
    setSyncStatus("loading");
    setMsg(null);
    try {
      const r = await api.importFills();
      if (r.enrich_started) {
        setMsg(`Synced: ${r.saved} new fill(s), ${r.skipped} skipped. Enriching ${r.enrich_total} fill(s)...`);
        setEnrichProgress({ done: 0, total: r.enrich_total, current: "" });
        setEnrichStatus("loading");
        startPolling();
      } else {
        setMsg(`Synced: ${r.saved} new fill(s), ${r.skipped} skipped.`);
      }
      setSyncStatus("done");
    } catch (e) {
      const message = (e as Error).message;
      if (message.includes("Gmail authorization is required")) {
        try {
          await connectGmail();
        } catch (authError) {
          setMsg(`Could not open Gmail authorization: ${(authError as Error).message}`);
          setSyncStatus("error");
        }
        return;
      }
      setMsg(`Sync failed: ${message}`);
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

  function startAlpacaPolling() {
    if (alpacaPollRef.current) clearInterval(alpacaPollRef.current);
    alpacaPollRef.current = setInterval(async () => {
      try {
        const s = await api.alpacaEnrichStatus();
        setAlpacaEnrichProgress({ done: s.done, total: s.total, current: s.current });
        if (!s.running) {
          clearInterval(alpacaPollRef.current!);
          alpacaPollRef.current = null;
          if (s.error) {
            setMsg(`Alpaca enrich failed: ${s.error}`);
            setAlpacaEnrichStatus("error");
          } else {
            setMsg(`Alpaca: enriched ${s.enriched} of ${s.total} fill(s).`);
            setAlpacaEnrichStatus("done");
          }
          setAlpacaEnrichProgress(null);
          setTimeout(() => setAlpacaEnrichStatus("idle"), 4000);
        }
      } catch {
        clearInterval(alpacaPollRef.current!);
        alpacaPollRef.current = null;
        setAlpacaEnrichStatus("error");
        setAlpacaEnrichProgress(null);
      }
    }, 2000);
  }

  async function handleAlpacaEnrich() {
    setAlpacaEnrichStatus("loading");
    setAlpacaEnrichProgress(null);
    setMsg(null);
    try {
      const r = await api.alpacaEnrichMissing(enrichRange, alpacaForce);
      if (!r.started) {
        setMsg("No fills missing Alpaca context.");
        setAlpacaEnrichStatus("done");
        setTimeout(() => setAlpacaEnrichStatus("idle"), 3000);
        return;
      }
      setAlpacaEnrichProgress({ done: 0, total: r.total_missing, current: "" });
      startAlpacaPolling();
    } catch (e) {
      setMsg(`Alpaca enrich failed: ${(e as Error).message}`);
      setAlpacaEnrichStatus("error");
      setTimeout(() => setAlpacaEnrichStatus("idle"), 4000);
    }
  }

  function startPathPolling() {
    if (pathPollRef.current) clearInterval(pathPollRef.current);
    pathPollRef.current = setInterval(async () => {
      try {
        const s = await api.tradePathStatus();
        setPathProgress({ done: s.done, total: s.total, current: s.current });
        if (!s.running) {
          clearInterval(pathPollRef.current!);
          pathPollRef.current = null;
          if (s.error) {
            setMsg(`Path metrics failed: ${s.error}`);
            setPathStatus("error");
          } else {
            setMsg(`Path metrics: computed ${s.enriched} of ${s.total} trade(s).`);
            setPathStatus("done");
          }
          setPathProgress(null);
          setTimeout(() => setPathStatus("idle"), 4000);
        }
      } catch {
        clearInterval(pathPollRef.current!);
        pathPollRef.current = null;
        setPathStatus("error");
        setPathProgress(null);
      }
    }, 2000);
  }

  async function handleComputePath() {
    setPathStatus("loading");
    setPathProgress(null);
    setMsg(null);
    try {
      const r = await api.computeTradePaths(enrichRange);
      if (!r.started) {
        setMsg("No closed trades missing path metrics.");
        setPathStatus("done");
        setTimeout(() => setPathStatus("idle"), 3000);
        return;
      }
      setPathProgress({ done: 0, total: r.total_missing, current: "" });
      startPathPolling();
    } catch (e) {
      setMsg(`Path metrics failed: ${(e as Error).message}`);
      setPathStatus("error");
      setTimeout(() => setPathStatus("idle"), 4000);
    }
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
          disabled={dataModifying || enrichBusy}
          className="rounded-l bg-transparent px-2 py-1.5 text-xs text-muted-foreground focus:outline-none disabled:opacity-50"
        >
          <option value="day">1d</option>
          <option value="week">1w</option>
          <option value="month">1mo</option>
          <option value="all">All</option>
        </select>
        <button
          onClick={handleEnrich}
          disabled={dataModifying || enrichBusy}
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
      <div className="flex items-center rounded border border-violet-800/50">
        <button
          onClick={handleAlpacaEnrich}
          disabled={dataModifying || alpacaBusy}
          className="rounded-l bg-violet-900/30 px-3 py-1.5 text-xs font-medium text-violet-300 transition-colors hover:bg-violet-900/50 disabled:opacity-50"
        >
          {alpacaEnrichStatus === "loading"
            ? alpacaEnrichProgress && alpacaEnrichProgress.total > 0
              ? `Alpaca ${alpacaEnrichProgress.done}/${alpacaEnrichProgress.total}${alpacaEnrichProgress.current ? ` ${alpacaEnrichProgress.current}` : ""}`
              : "Alpaca Starting..."
            : alpacaEnrichStatus === "done"
              ? "Alpaca Done"
              : "Alpaca Context"}
        </button>
        <label className="flex cursor-pointer items-center gap-1 border-l border-violet-800/50 px-2 py-1.5 text-xs text-violet-400 hover:text-violet-300">
          <input
            type="checkbox"
            checked={alpacaForce}
            onChange={(e) => setAlpacaForce(e.target.checked)}
            disabled={dataModifying || alpacaBusy}
            className="accent-violet-500 disabled:opacity-50"
          />
          All
        </label>
      </div>
      <button
        onClick={handleComputePath}
        disabled={dataModifying || pathBusy}
        className="rounded border border-teal-800/50 bg-teal-900/30 px-3 py-1.5 text-xs font-medium text-teal-300 transition-colors hover:bg-teal-900/50 disabled:opacity-50"
      >
        {pathStatus === "loading"
          ? pathProgress && pathProgress.total > 0
            ? `Path ${pathProgress.done}/${pathProgress.total}${pathProgress.current ? ` ${pathProgress.current}` : ""}`
            : "Path Starting..."
          : pathStatus === "done"
            ? "Path Done"
            : "Path Metrics"}
      </button>
      <button
        onClick={handleSync}
        disabled={busy}
        className="rounded bg-secondary px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80 disabled:opacity-50"
      >
        {syncStatus === "loading" ? "Syncing..." : syncStatus === "done" ? "Synced OK" : "Sync Emails"}
      </button>
      <a
        href={`${API}/auth/gmail/start/browser`}
        className="rounded border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
      >
        Connect Gmail
      </a>
      <button
        onClick={handleRebuild}
        disabled={busy}
        className="rounded bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
      >
        {rebuildStatus === "loading" ? "Rebuilding..." : rebuildStatus === "done" ? "Done" : "Rebuild All"}
      </button>
      <button
        onClick={handleResyncAll}
        disabled={busy || enrichBusy || alpacaBusy || pathBusy}
        className="rounded bg-rose-900/40 px-3 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-900/60 disabled:opacity-50"
      >
        {resyncStatus === "loading" ? "Resyncing..." : resyncStatus === "done" ? "Resynced OK" : "Resync All"}
      </button>
    </div>
  );
}
