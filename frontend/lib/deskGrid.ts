/**
 * The centre's Grid (docs/copilot-lab.md § The desk): which names fill its 4, 6 or 9 small charts, the layout kept per
 * device, and the one batched bars read (``GET /copilot/desk/grid``).
 *
 * Slots fill in order: a pinned name keeps its slot; the rest take his followed held positions first (the book's order),
 * then his Watching list in its order. A ticker set to Not following never fills a slot, pinned or not.
 */

import { apiUrl } from "@/lib/api";

export const GRID_SIZES = [4, 6, 9] as const;
export type GridSize = typeof GRID_SIZES[number];
export const GRID_TIMEFRAMES = ["1m", "5m"] as const;
export type GridTimeframe = typeof GRID_TIMEFRAMES[number];
/** ``pins[i]``: the ticker pinned to slot ``i`` (nine kept, so a smaller grid and back loses no pin). */
export type GridLayout = { size: GridSize; timeframe: GridTimeframe; pins: (string | null)[] };

export const GRID_STORE = "desk.grid.v1";
export const DEFAULT_LAYOUT: GridLayout = { size: 6, timeframe: "5m", pins: Array(9).fill(null) };
const TICKER = /^[A-Z][A-Z0-9.\-]{0,9}$/;

export const gridTicker = (raw: string): string | null => {
  const name = raw.trim().toUpperCase();
  return TICKER.test(name) ? name : null;
};

/** The layout saved on this device, or the default; anything malformed falls back field by field. */
export function readGridLayout(): GridLayout {
  try {
    const saved = JSON.parse(window.localStorage.getItem(GRID_STORE) ?? "null") as Partial<GridLayout> | null;
    if (!saved || typeof saved !== "object") return DEFAULT_LAYOUT;
    const size = (GRID_SIZES as readonly number[]).includes(saved.size as number) ? saved.size as GridSize : DEFAULT_LAYOUT.size;
    const timeframe = (GRID_TIMEFRAMES as readonly string[]).includes(saved.timeframe as string) ? saved.timeframe as GridTimeframe : DEFAULT_LAYOUT.timeframe;
    const pins = Array.from({ length: 9 }, (_, i) => {
      const pin = Array.isArray(saved.pins) ? saved.pins[i] : null;
      return typeof pin === "string" ? gridTicker(pin) : null;
    });
    return { size, timeframe, pins };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function saveGridLayout(layout: GridLayout) {
  try { window.localStorage.setItem(GRID_STORE, JSON.stringify(layout)); } catch { /* private mode: this view only */ }
}

/** Pin ``symbol`` to slot ``slot`` (taking it off any other slot), or unpin the slot with ``null``. */
export function pinTo(layout: GridLayout, slot: number, symbol: string | null): GridLayout {
  const pins = layout.pins.map((pin, i) => i === slot ? symbol : pin === symbol ? null : pin);
  return { ...layout, pins };
}

/**
 * The names in each of ``size`` slots: pinned names in their own slots, then the followed held positions in order, then
 * the Watching list in order, each name once; ``hidden`` (Not following) never shows. ``null``: an empty slot.
 */
export function gridSlots(layout: GridLayout, held: readonly string[], watched: readonly string[], hidden: ReadonlySet<string>): (string | null)[] {
  const used = new Set<string>();
  const pins = Array.from({ length: layout.size }, (_, i) => {
    const pin = layout.pins[i];
    if (!pin || hidden.has(pin) || used.has(pin)) return null;
    used.add(pin);
    return pin;
  });
  const queue: string[] = [];
  for (const name of [...held, ...watched]) {
    if (name && !hidden.has(name) && !used.has(name) && !queue.includes(name)) queue.push(name);
  }
  return pins.map(pin => pin ?? queue.shift() ?? null);
}

// --------------------------------------------------------------------------- the read

export type GridBar = { time: number; open: number; high: number; low: number; close: number; volume: number; extended: boolean;
  vwap: number | null; prior: boolean };
export type GridLevel = { price: number; role: "entry" | "invalidation" | "alert"; label: string | null };
export type GridTile = { state: "ok" | "pending" | "unavailable"; bars: GridBar[]; last: number | null; change_pct: number | null;
  levels: GridLevel[]; source: string | null;
  /** When the server read these minutes; ``stale``: older than a refresh or two on a live day (its re-read failed). */
  read_at: number | null; stale: boolean };
/** ``live``: the bars can still change, so the Grid reads again in a minute. ``day``: the session shown (New York). */
export type GridRead = { state: "ok" | "unavailable"; as_of: number; day: string; timeframe: GridTimeframe; step: number; live: boolean;
  rows: Record<string, GridTile> };

export async function getDeskGrid(symbols: string[], timeframe: GridTimeframe, signal?: AbortSignal): Promise<GridRead> {
  const query = new URLSearchParams({ symbols: symbols.join(","), timeframe });
  const response = await fetch(apiUrl(`/copilot/desk/grid?${query}`), { cache: "no-store", signal });
  if (!response.ok) {
    await response.text().catch(() => ""); // an unread body keeps the request open in Chromium
    throw new Error(`Request failed (${response.status}).`);
  }
  return await response.json() as GridRead;
}
