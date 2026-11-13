"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

/*
 * The desk's walls (``GET /copilot/desk/walls``, ``app/engine/desk_walls.py``): the Charts strike ladder's read cut to
 * put wall, call wall, gamma flip, max pain and the expected move for one expiry, on the assumed dealer side. Read once
 * a minute while the page is visible, as the ladder is, and shared: the desk chart and the Chain tab asking for the same
 * ticker and expiry make one request a minute between them (the server's chain cache is the one Charts reads too).
 */

export type WallKind = "put_wall" | "call_wall" | "gamma_flip" | "max_pain";
export type DeskWallLevel = { kind: WallKind; name: string; price: number; hint: string };
export type DeskWalls = {
  symbol: string; state: "ready" | "stale" | "loading" | "unavailable" | "none"; expiration?: string | null;
  spot?: number | null; fetched_at?: number | null; age_s?: number | null; levels: DeskWallLevel[];
  expected_move: { move: number; percent: number | null; low: number; high: number; expiration: string | null; hint: string } | null;
  flip_note?: string | null; assumption?: string; message: string | null; simulated?: boolean; refresh_seconds: number;
};

const REFRESH_MS = 60_000;
/** A read younger than this answers another asker without a request. */
const FRESH_MS = 55_000;
const kept = new Map<string, { at: number; data: DeskWalls }>();
const asking = new Map<string, Promise<DeskWalls>>();

async function ask(symbol: string, expiration: string | null): Promise<DeskWalls> {
  const query = new URLSearchParams({ symbol, ...(expiration ? { expiration } : {}) });
  const response = await fetch(apiUrl(`/copilot/desk/walls?${query}`), { cache: "no-store" });
  const body = await response.json().catch(() => null); // always read the body: an unread one never settles
  if (!response.ok || !body) throw new Error(typeof body?.detail === "string" ? body.detail : `The walls could not be read (${response.status}).`);
  return body as DeskWalls;
}

/** One read per key at a time, and none while a read under a minute old is kept. */
export function readWalls(symbol: string, expiration: string | null, now = Date.now()): Promise<DeskWalls> {
  const key = `${symbol}|${expiration ?? ""}`;
  const have = kept.get(key);
  if (have && now - have.at < FRESH_MS) return Promise.resolve(have.data);
  const pending = asking.get(key);
  if (pending) return pending;
  const next = ask(symbol, expiration)
    .then(data => { kept.set(key, { at: Date.now(), data }); return data; })
    .finally(() => asking.delete(key));
  asking.set(key, next);
  return next;
}

/** The walls for ``symbol`` at ``expiration`` (the nearest when null), read once a minute while the page is visible;
 * null ``symbol`` reads nothing. ``failed``: the last read failed (what is kept is no longer current). */
export function useDeskWalls(symbol: string | null, expiration: string | null = null) {
  const key = symbol ? `${symbol}|${expiration ?? ""}` : null;
  const [state, setState] = useState<{ key: string; data: DeskWalls | null; failed: string | null } | null>(null);
  useEffect(() => {
    if (!symbol || !key) return;
    let gone = false;
    let skipped = false;
    const load = () => {
      if (document.visibilityState === "hidden") { skipped = true; return; }
      skipped = false;
      readWalls(symbol, expiration)
        .then(data => { if (!gone) setState({ key, data, failed: null }); })
        .catch((error: unknown) => {
          if (!gone) setState(prev => ({ key, data: prev?.key === key ? prev.data : null, failed: error instanceof Error ? error.message : "The walls could not be read." }));
        });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    const onShow = () => { if (document.visibilityState === "visible" && skipped) load(); };
    document.addEventListener("visibilitychange", onShow);
    return () => { gone = true; window.clearInterval(timer); document.removeEventListener("visibilitychange", onShow); };
  }, [symbol, expiration, key]);
  const shown = state && state.key === key ? state : null;
  return { data: shown?.data ?? null, failed: shown?.failed ?? null };
}

/** What the chart may draw: only a current, ready read. Stale, missing or failing draws nothing. */
export function drawableWalls(data: DeskWalls | null, failed: string | null): DeskWalls | null {
  return data && data.state === "ready" && !failed ? data : null;
}

const strike = (n: number) => Number.isInteger(n) ? String(n) : String(+n.toFixed(2));

/** The Chain tab's one line: "Walls 600 / 615 · flip 607 · max pain 610 · expected move ±4.20". */
export function wallsLine(data: DeskWalls): string {
  const at = (kind: WallKind) => data.levels.find(l => l.kind === kind)?.price;
  const put = at("put_wall"), call = at("call_wall"), flip = at("gamma_flip"), pain = at("max_pain");
  const parts = [`Walls ${put != null ? strike(put) : "—"} / ${call != null ? strike(call) : "—"}`];
  if (flip != null) parts.push(`flip ${strike(flip)}`);
  if (pain != null) parts.push(`max pain ${strike(pain)}`);
  if (data.expected_move) parts.push(`expected move ±${data.expected_move.move.toFixed(2)}`);
  return parts.join(" · ");
}
