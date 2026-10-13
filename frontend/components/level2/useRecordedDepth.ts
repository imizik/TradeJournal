"use client";

import { useEffect, useRef, useState } from "react";
import { DepthHeatmap } from "@/lib/depthHeatmap";
import type { DepthProfile, HeatBookKind } from "@/lib/depthHeatmap";
import { LEVEL2_TICKER, isRecord } from "./useDepthSession";

/** A liquidity level from the depth recorder: a price whose displayed size stood out and rested. */
export type Wall = { price: number; size: number; mean: number; since: number; last_seen: number; pulled: boolean; share: number };
export type RecordedDepth = {
  /** "none": not asked; "unrecorded": the recorder has nothing for this ticker today. */
  state: "none" | "loading" | "ready" | "unrecorded" | "unavailable";
  /** The recorder is currently receiving this ticker (its last book is under a minute old). */
  recording: boolean;
  walls: { bids: Wall[]; asks: Wall[] };
  profile: DepthProfile | null;
  lastMs: number;
  /** Recorded heatmap columns (10 s), one map per ticker and book kind; filled only when `history` is asked for. */
  heatmap: DepthHeatmap | null;
};

const POLL_MS = 10_000;
const HISTORY_MINUTES = 240;
const NONE: RecordedDepth = { state: "none", recording: false, walls: { bids: [], asks: [] }, profile: null, lastMs: 0, heatmap: null };

const pair = (value: unknown): value is [number, number] => Array.isArray(value) && value.length === 2 && value.every((n) => typeof n === "number" && Number.isFinite(n));
const validWall = (value: unknown): value is Wall => isRecord(value) && ["price", "size", "mean", "since", "last_seen", "share"].every((k) => typeof value[k] === "number" && Number.isFinite(value[k] as number)) && typeof value.pulled === "boolean";
function validProfile(value: unknown): value is DepthProfile {
  return isRecord(value) && typeof value.t === "number" && Array.isArray(value.bids) && value.bids.length <= 120 && value.bids.every(pair)
    && Array.isArray(value.asks) && value.asks.length <= 120 && value.asks.every(pair);
}
function validColumns(value: unknown): value is [number, number, number[]][] {
  return Array.isArray(value) && value.length <= 6000 && value.every((column) => Array.isArray(column) && column.length === 3
    && typeof column[0] === "number" && typeof column[1] === "number" && Array.isArray(column[2]) && column[2].length <= 480
    && column[2].every((n: unknown) => typeof n === "number" && Number.isFinite(n)));
}

/**
 * The depth recorder's data for `symbol` (owner, recorded tickers), polled every
 * 10 seconds while `active`: walls and the latest profile always; heatmap
 * columns only while `history` is on (the last four hours once, then the last
 * two minutes each poll). Nothing reaches the provider; a ticker the recorder
 * does not watch reports "unrecorded". Data is kept in memory for the page.
 */
export function useRecordedDepth(symbol: string, { active, history, kind }: { active: boolean; history: boolean; kind: HeatBookKind }): RecordedDepth {
  const [depth, setDepth] = useState<RecordedDepth & { key: string }>({ ...NONE, key: "" });
  const maps = useRef(new Map<string, DepthHeatmap>());
  const asked = active && LEVEL2_TICKER.test(symbol);
  const requestKey = `${symbol}:${kind}:${history}`;

  useEffect(() => {
    if (!asked) return;
    let cancelled = false;
    // The newest recorded column already held, so a poll after a gap (sleep, outage) asks for everything since.
    let newest = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const mapKey = `${symbol}:${kind}`;
    const map = maps.current.get(mapKey) ?? new DepthHeatmap();
    maps.current.set(mapKey, map);
    const poll = async () => {
      try {
        const minutes = !history ? 1 : newest ? Math.min(HISTORY_MINUTES, Math.max(2, Math.ceil((Date.now() - newest) / 60_000) + 1)) : HISTORY_MINUTES;
        const query = new URLSearchParams({ symbol, kind, minutes: String(minutes), bucket: "10" });
        const response = await fetch(`/api/level2-lab/depth?${query}`, { cache: "no-store" });
        if (cancelled) return;
        if (!response.ok) { setDepth({ ...NONE, state: "unavailable", key: requestKey }); return; }
        const body: unknown = await response.json();
        if (cancelled || !isRecord(body)) return;
        if (body.recorded !== true) { setDepth({ ...NONE, state: "unrecorded", key: requestKey }); return; }
        const walls = isRecord(body.walls) && Array.isArray(body.walls.bids) && Array.isArray(body.walls.asks)
          ? { bids: body.walls.bids.filter(validWall).slice(0, 3), asks: body.walls.asks.filter(validWall).slice(0, 3) } : { bids: [], asks: [] };
        if (history && validColumns(body.columns)) {
          map.load(kind, body.columns);
          if (body.columns.length) newest = Math.max(newest, body.columns[body.columns.length - 1][0]);
        }
        setDepth({ state: "ready", recording: body.recording === true, walls, profile: validProfile(body.profile) ? body.profile : null,
          lastMs: typeof body.last_ms === "number" ? body.last_ms : 0, heatmap: history ? map : null, key: requestKey });
      } catch {
        if (!cancelled) setDepth((current) => current.key === requestKey && current.state === "ready" ? { ...current, recording: false } : { ...NONE, state: "unavailable", key: requestKey });
      } finally {
        if (!cancelled) timer = setTimeout(poll, POLL_MS);
      }
    };
    void poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [asked, symbol, kind, history, requestKey]);

  if (!asked) return NONE;
  // Until this ticker's first answer arrives, never show another ticker's levels.
  return depth.key === requestKey ? depth : { ...NONE, state: "loading" };
}
