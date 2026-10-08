"use client";

import { useEffect, useState } from "react";
import { fetchSymbolPeers } from "@/lib/symbolInfo";
import type { SymbolPeers } from "@/lib/symbolInfo";

const REFRESH_MS = 60_000;

/**
 * The Peers strip (T3.4): Polygon's related companies for the active symbol, each with today's
 * change. One request per symbol (after it settles for 300 ms), read again each minute while the
 * page is visible; a chip click goes through the same handler a watchlist row uses.
 */
export default function SymbolInfoPeers({ symbol, onSelect }: { symbol: string; onSelect(symbol: string): void }) {
  const [result, setResult] = useState<{ symbol: string; data?: SymbolPeers; error?: boolean } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const run = (quiet: boolean) => {
      fetchSymbolPeers(symbol, controller.signal).then((data) => { if (active) setResult({ symbol, data }); })
        .catch(() => { if (active && !quiet) setResult({ symbol, error: true }); });
    };
    const timer = setTimeout(() => run(false), 300);
    const again = setInterval(() => { if (!document.hidden) run(true); }, REFRESH_MS);
    return () => { active = false; clearTimeout(timer); clearInterval(again); controller.abort(); };
  }, [symbol]);

  const shown = result?.symbol === symbol ? result : null;
  const data = shown?.data;
  const source = data ? `${data.source.label}${data.source.age_seconds != null ? `, read ${Math.round(data.source.age_seconds / 3600)} h ago` : ""}` : "";
  return <div role="group" aria-label="Peers" className="border-b border-slate-700/40 px-3 py-2">
    <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-600">Peers</p>
    {!shown ? <p role="status" className="text-xs text-slate-500">Loading peers…</p>
      : shown.error ? <p className="text-xs text-slate-500">Peers unavailable.</p>
      : data && data.state === "ready" ? <>
        <div className="flex flex-wrap gap-1">
          {data.peers.map((peer) => {
            const change = peer.change_percentage;
            return <button key={peer.symbol} aria-label={`Peer ${peer.symbol}`} title={`${peer.name ?? peer.symbol}${peer.last != null ? ` · $${peer.last.toFixed(2)}` : ""} · ${source}`}
              onClick={() => onSelect(peer.symbol)} className="flex min-h-11 items-center gap-1 rounded border border-slate-700 px-2 py-1 text-[11px] hover:border-sky-400/60 lg:min-h-0">
              <span className="font-medium text-slate-200">{peer.symbol}</span>
              <span className={change == null ? "text-slate-500" : change > 0 ? "text-emerald-300" : change < 0 ? "text-rose-300" : "text-slate-400"}>
                {change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`}</span>
            </button>;
          })}
        </div>
        {(data.source.state === "stale" || data.quotes.state !== "ok") && <p className="mt-1 text-[10px] text-amber-300">{data.quotes.state !== "ok" ? `Quotes: ${data.quotes.message ?? "unavailable"}` : data.source.message}</p>}
      </>
      : data && data.state === "none" ? <p className="text-xs text-slate-500">No related companies listed for {symbol} (funds and ETFs have none).</p>
      : <p className="text-xs text-slate-500">{data?.source.message ?? "Peers unavailable."}</p>}
  </div>;
}
