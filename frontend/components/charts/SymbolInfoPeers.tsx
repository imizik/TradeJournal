"use client";

import { useEffect, useState } from "react";
import { fetchSymbolPeers } from "@/lib/symbolInfo";
import type { SymbolPeers } from "@/lib/symbolInfo";
import { getGroupComparison, nyTime, type GroupComparison, type RadarGroup } from "@/lib/radar";
import { Block } from "./SymbolInfoParts";

const REFRESH_MS = 60_000;

export type PeersResult = { symbol: string; data?: SymbolPeers; error?: boolean } | null;

/**
 * The Peers read (T3.4): Polygon's related companies for the active symbol, each with today's
 * change. One request per symbol (after it settles for 300 ms), read again each minute while the
 * page is visible. It lives in the symbol info panel, not in the block, so moving the block (it
 * sits last in Overview) never reads again.
 */
export type MovementResult = { key: string; data?: GroupComparison; error?: boolean } | null;

export function usePeers(symbol: string, enabled: boolean, owner: boolean, group?: string) {
  const [result, setResult] = useState<PeersResult>(null);
  const [movement, setMovement] = useState<MovementResult>(null);
  const movementKey = `${symbol}|${group ?? ""}`;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let active = true;
    let sequence = 0;
    queueMicrotask(() => { if (active) setMovement(null); });
    const run = (quiet: boolean) => {
      const request = ++sequence;
      if (owner) getGroupComparison(symbol, group, controller.signal)
        .then((data) => { if (active && request === sequence) setMovement({ key: movementKey, data }); })
        .catch(() => { if (active && request === sequence) setMovement({ key: movementKey, error: true }); });
      fetchSymbolPeers(symbol, controller.signal).then((data) => { if (active && request === sequence) setResult({ symbol, data }); })
        .catch(() => { if (active && request === sequence && !quiet) setResult({ symbol, error: true }); });
    };
    const timer = setTimeout(() => run(false), 300);
    const again = setInterval(() => { if (!document.hidden) run(true); }, REFRESH_MS);
    return () => { active = false; clearTimeout(timer); clearInterval(again); controller.abort(); };
  }, [symbol, enabled, owner, group, movementKey]);
  return { peers: result, movement: owner && movement?.key === movementKey ? movement : null };
}

/** The Peers block: chips with today's move; a chip click goes through the same handler a watchlist row uses. */
export default function SymbolInfoPeers({ symbol, result, onSelect, movement, onGroup }: { symbol: string; result: PeersResult; onSelect(symbol: string): void; movement?: MovementResult; onGroup?(group: RadarGroup): void }) {
  const shown = result?.symbol === symbol ? result : null;
  const data = shown?.data;
  const source = data ? `${data.source.label}${data.source.age_seconds != null ? `, read ${Math.round(data.source.age_seconds / 3600)} h ago` : ""}` : "";
  // A failed read or a stale list opens the block whatever was saved.
  const problem = !!shown?.error || (!!data && (data.source.state === "stale" || (data.state === "ready" && data.quotes.state !== "ok") || (data.state !== "ready" && data.state !== "none")));
  return <Block name="peers" title="Peers" forceOpen={problem}><div role="group" aria-label="Peers">
    {!shown ? <p role="status" className="text-xs text-slate-500">Loading peers…</p>
      : shown.error ? <p className="text-xs text-slate-500">Peers unavailable.</p>
      : data && data.state === "ready" ? <>
        <p className="mb-1 text-[10px] text-slate-500">Day change</p>
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
        {data.source.provider === "curated" && <p className="mt-1 text-[10px] text-slate-500">{data.source.label}</p>}
        {(data.source.state === "stale" || data.quotes.state !== "ok") && <p className="mt-1 text-[10px] text-amber-300">{data.quotes.state !== "ok" ? `Quotes: ${data.quotes.message ?? "unavailable"}` : data.source.message}</p>}
      </>
      : data && data.state === "none" ? <p className="text-xs text-slate-500">No related companies listed for {symbol} (funds and ETFs have none).</p>
      : <p className="text-xs text-slate-500">{data?.source.message ?? "Peers unavailable."}</p>}
  </div>{onGroup && <GroupMovement result={movement ?? null} onGroup={onGroup} onSelect={onSelect} />}</Block>;
}


function GroupMovement({ result, onGroup, onSelect }: { result: MovementResult; onGroup(group: RadarGroup): void; onSelect(symbol: string): void }) {
  const data = result?.data;
  return <div role="group" aria-label="Group movement" className="mt-3 border-t border-slate-700/60 pt-2 text-xs">
    <p className="font-medium text-slate-200">Group movement · 15 min</p>
    {!result ? <p role="status" className="mt-1 text-slate-500">Loading recorded movement…</p>
      : result.error ? <p className="mt-1 text-amber-300">Group movement unavailable. Previous values hidden until a fresh read succeeds.</p>
      : data && <>
        {data.group && <label className="mt-2 block text-slate-400">Compare group
          <select aria-label="Comparison group" value={data.group.name} onChange={(event) => {
            const group = data.groups.find((g) => g.name === event.target.value); if (group) onGroup(group);
          }} className="mt-1 min-h-11 w-full min-w-0 rounded border border-slate-600 bg-slate-900 px-1 text-xs text-slate-200 lg:min-h-8">
            {data.groups.map((g) => <option key={g.name}>{g.name}</option>)}
          </select>
        </label>}
        {data.reason && <p className={`mt-2 ${data.state === "stale" || data.state === "partial" ? "text-amber-300" : "text-slate-400"}`}>{data.reason}</p>}
        {data.window && <p className="my-2 text-[11px] text-slate-400">{data.live ? "Recorded" : "Last recorded session"} {data.session}<br />{nyTime(data.window.start)}–{nyTime(data.window.end)} ET</p>}
        {data.coverage && <p className="mb-2 text-slate-300">{data.coverage.peers_up} up · {data.coverage.peers_down} down · {data.coverage.peers_available} of {data.coverage.peers_total} peers available</p>}
        {data.coverage && <p className="mb-2 text-[10px] text-slate-500">{data.coverage.recorded_minutes} of {data.coverage.expected_minutes} minutes recorded. Returns use the two endpoint passes.</p>}
        <ul className="space-y-1" aria-label="Same-window movements">
          {data.rows.map((row) => <li key={row.symbol} className="border-b border-slate-800 pb-1">
            <button onClick={() => { if (data.group) onGroup(data.group); onSelect(row.symbol); }} aria-label={`Compare chart ${row.symbol}`}
              className="flex min-h-11 w-full items-center justify-between gap-2 text-left lg:min-h-7">
              <span className="text-slate-200">{row.symbol}<span className="ml-1 text-[10px] text-slate-500">{row.role === "selected" ? "selected" : row.role === "benchmark" ? "benchmark" : ""}</span></span>
              <span className={row.change_pct == null ? "text-slate-500" : row.change_pct > 0 ? "text-emerald-300" : row.change_pct < 0 ? "text-rose-300" : "text-slate-400"}>{row.change_pct == null ? "—" : `${row.change_pct > 0 ? "+" : ""}${row.change_pct.toFixed(2)}%`}</span>
            </button>
            {row.reason && <p className="text-[10px] text-amber-300">{row.reason}</p>}
            {row.start && row.end && <details className="text-[10px] text-slate-500"><summary className="cursor-pointer">Observation times</summary>
              <p>Trades: {nyTime(row.start.trade_at, true)} → {nyTime(row.end.trade_at, true)} ET</p>
              <p>Read: {nyTime(row.start.retrieved_at, true)} → {nyTime(row.end.retrieved_at, true)} ET</p>
            </details>}
          </li>)}
        </ul>
        <p className="mt-2 break-words text-[10px] text-slate-500">{data.source} · {data.universe_version}. Sampled price changes, not candle confirmation or a trade signal.</p>
      </>}
  </div>;
}
