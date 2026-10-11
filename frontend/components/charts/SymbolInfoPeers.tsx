"use client";

import { useEffect, useState } from "react";
import { fetchSymbolPeers } from "@/lib/symbolInfo";
import type { SymbolPeers } from "@/lib/symbolInfo";
import { Block } from "./SymbolInfoParts";

const REFRESH_MS = 60_000;

export type PeersResult = { symbol: string; data?: SymbolPeers; error?: boolean } | null;

/**
 * The Peers read (T3.4): Polygon's related companies for the active symbol, each with today's
 * change. One request per symbol (after it settles for 300 ms), read again each minute while the
 * page is visible. It lives in the symbol info panel, not in the block, so moving the block (it
 * sits last in Overview) never reads again.
 */
export function usePeers(symbol: string, enabled: boolean): PeersResult {
  const [result, setResult] = useState<PeersResult>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let active = true;
    const run = (quiet: boolean) => {
      fetchSymbolPeers(symbol, controller.signal).then((data) => { if (active) setResult({ symbol, data }); })
        .catch(() => { if (active && !quiet) setResult({ symbol, error: true }); });
    };
    const timer = setTimeout(() => run(false), 300);
    const again = setInterval(() => { if (!document.hidden) run(true); }, REFRESH_MS);
    return () => { active = false; clearTimeout(timer); clearInterval(again); controller.abort(); };
  }, [symbol, enabled]);
  return result;
}

/** The Peers block: chips with today's move; a chip click goes through the same handler a watchlist row uses. */
export default function SymbolInfoPeers({ symbol, result, onSelect }: { symbol: string; result: PeersResult; onSelect(symbol: string): void }) {
  const shown = result?.symbol === symbol ? result : null;
  const data = shown?.data;
  const source = data ? `${data.source.label}${data.source.age_seconds != null ? `, read ${Math.round(data.source.age_seconds / 3600)} h ago` : ""}` : "";
  return <Block name="peers" title="Peers"><div role="group" aria-label="Peers">
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
  </div></Block>;
}
