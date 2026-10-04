import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";
import { apiUrl } from "@/lib/api";
import { DEFAULT_SETTINGS, LAYER_GROUPS, MAX_KEPT_LAYOUTS, STORAGE_KEY, cleanLayoutProportions, cleanProportions, layoutKeys, sanitizeSettings, uniqueLayoutNames, validSymbol } from "@/lib/charts";
import type { ChartSettings, Indicators } from "@/lib/charts";
import { cleanDrawings, cleanToolStyles, DRAWING_KINDS, MAX_DRAWINGS } from "@/lib/drawings";

/**
 * Chart settings saved on the server, so the phone and the desktop share
 * levels, watchlist, intervals, indicators, layout, saved layouts and the
 * chart grid's proportions (C7.4; the dock's width stays on each device).
 *
 * The symbol on screen and the recent symbols stay per device: switching
 * symbols is constant and must never race another device's save. Browser
 * storage keeps a full copy, used when the server cannot be reached, plus the
 * revision and server copy it was based on. The server refuses a save based on
 * an older revision (HTTP 409); this device then re-applies its own changes on
 * top of the newer copy and saves again, so edits from both devices survive.
 */
export type SharedSettings = Omit<ChartSettings, "symbol" | "recent">;
export type SyncState = "loading" | "saving" | "saved" | "offline";
type ServerCopy = { revision: number; data: unknown };
type Meta = { revision: number; base: SharedSettings };

const META_KEY = "tradejournal.charts.sync.v1";
const REFRESH_MS = 30_000;
const json = (value: unknown) => JSON.stringify(value);

/** The shared part of the settings in a canonical key order, so equal settings compare equal. */
export function shared(settings: ChartSettings): SharedSettings {
  const { intervals, panelSymbols, watchlist, session, layout, indicators, levels, drawings, toolStyles, magnet, hiddenGroups, studiesHidden, autoLevelsHidden, linkRange, smallSize, immersiveWatchlist, layouts, proportions, layoutProportions } = settings;
  const kept = layouts.map(({ id, name, ...arrangement }) => ({ id, name, ...layoutKeys(arrangement) }));
  const sizes = cleanLayoutProportions(layoutProportions, kept);
  return { intervals, panelSymbols, watchlist, session, layout, indicators, linkRange, smallSize, immersiveWatchlist,
    layouts: kept,
    // Top-level fields, which a tab on an older build leaves out of its saves and the server therefore keeps.
    proportions: cleanProportions(proportions), layoutProportions: Object.fromEntries(Object.keys(sizes).sort().map((id) => [id, sizes[id]])),
    levels: Object.fromEntries(Object.keys(levels).sort().filter((symbol) => levels[symbol].length).map((symbol) => [symbol, levels[symbol]])),
    // Always sent, even empty: the server keeps a field a save leaves out, so omitting it could never clear it.
    drawings: cleanDrawings(Object.fromEntries(Object.keys(drawings).sort().map((symbol) => [symbol, drawings[symbol]])), validSymbol),
    toolStyles: cleanToolStyles(toolStyles), magnet, hiddenGroups: { levels: hiddenGroups.levels, drawings: hiddenGroups.drawings }, studiesHidden, autoLevelsHidden };
}
const same = (a: SharedSettings, b: SharedSettings) => json(a) === json(b);
const fromServer = (data: unknown) => shared(sanitizeSettings(data ?? {}));

/** `theirs` without what this device removed since `base`, plus what it added or changed. */
function mergeItems<T>(base: T[], mine: T[], theirs: T[], id: (item: T) => string): T[] {
  const before = new Map(base.map((item) => [id(item), json(item)]));
  const kept = new Set(mine.map(id));
  const changed = new Map(mine.filter((item) => before.get(id(item)) !== json(item)).map((item) => [id(item), item]));
  const out = theirs.filter((item) => kept.has(id(item)) || !before.has(id(item))).map((item) => changed.get(id(item)) ?? item);
  const present = new Set(out.map(id));
  return [...out, ...[...changed.values()].filter((item) => !present.has(id(item)))];
}

/** `theirs` with each key whose value this device changed since `base` (added, changed or removed) taken from `mine`. */
function mergeKeys<T>(base: Record<string, T>, mine: Record<string, T>, theirs: Record<string, T>): Record<string, T> {
  const out = { ...theirs };
  for (const key of new Set([...Object.keys(base), ...Object.keys(mine)])) {
    if (json(mine[key]) === json(base[key])) continue;
    if (key in mine) out[key] = mine[key];
    else delete out[key];
  }
  return out;
}

/**
 * Three-way merge: re-apply this device's edits since `base` to `theirs`, the
 * newer copy another device saved. Levels, drawings, the watchlist and saved
 * layouts merge item by item (a layout or a drawing is one item: saved, changed
 * or deleted whole, so hiding or locking one is a change to it), and a saved
 * layout's proportions with it, by its id; indicators, tool styles and hidden
 * groups merge key by key; any other setting this device changed keeps this
 * device's value (the grid's proportions are one value).
 */
export function rebase(base: SharedSettings, mine: SharedSettings, theirs: SharedSettings): SharedSettings {
  const out: SharedSettings = { ...theirs, indicators: { ...theirs.indicators } };
  const scalars = ["intervals", "panelSymbols", "session", "layout", "linkRange", "smallSize", "immersiveWatchlist", "magnet", "studiesHidden", "autoLevelsHidden", "proportions"] as const;
  for (const key of scalars) if (json(mine[key]) !== json(base[key])) Object.assign(out, { [key]: mine[key] });
  for (const key of Object.keys(mine.indicators) as (keyof Indicators)[])
    if (mine.indicators[key] !== base.indicators[key]) out.indicators[key] = mine.indicators[key];
  out.hiddenGroups = { ...theirs.hiddenGroups };
  for (const group of LAYER_GROUPS) if (mine.hiddenGroups[group] !== base.hiddenGroups[group]) out.hiddenGroups[group] = mine.hiddenGroups[group];
  out.toolStyles = { ...theirs.toolStyles };
  for (const kind of DRAWING_KINDS) if (json(mine.toolStyles[kind]) !== json(base.toolStyles[kind])) out.toolStyles[kind] = mine.toolStyles[kind];
  out.watchlist = mergeItems(base.watchlist, mine.watchlist, theirs.watchlist, (symbol) => symbol).slice(0, 30);
  out.layouts = uniqueLayoutNames(mergeItems(base.layouts, mine.layouts, theirs.layouts, (layout) => layout.id).slice(0, MAX_KEPT_LAYOUTS));
  out.layoutProportions = mergeKeys(base.layoutProportions, mine.layoutProportions, theirs.layoutProportions); // shared() drops those of deleted layouts
  const levels = { ...theirs.levels };
  for (const symbol of new Set([...Object.keys(base.levels), ...Object.keys(mine.levels)])) {
    const merged = mergeItems(base.levels[symbol] ?? [], mine.levels[symbol] ?? [], theirs.levels[symbol] ?? [], (level) => level.id).slice(0, 30);
    if (merged.length) levels[symbol] = merged;
    else delete levels[symbol];
  }
  const drawings = { ...theirs.drawings };
  for (const symbol of new Set([...Object.keys(base.drawings), ...Object.keys(mine.drawings)])) {
    const merged = mergeItems(base.drawings[symbol] ?? [], mine.drawings[symbol] ?? [], theirs.drawings[symbol] ?? [], (drawing) => drawing.id).slice(0, MAX_DRAWINGS);
    if (merged.length) drawings[symbol] = merged;
    else delete drawings[symbol];
  }
  return shared({ ...DEFAULT_SETTINGS, ...out, levels, drawings });
}

class Conflict extends Error {
  constructor(readonly current: ServerCopy) { super("revision_conflict"); }
}

async function fetchSettings(): Promise<ServerCopy> {
  const response = await fetch(apiUrl("/charts/settings"), { cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (!response.ok) throw new Error("Chart settings are unavailable.");
  return response.json();
}

async function saveSettings(baseRevision: number, data: SharedSettings): Promise<ServerCopy> {
  const response = await fetch(apiUrl("/charts/settings"), {
    method: "PUT", headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(10_000),
    body: JSON.stringify({ base_revision: baseRevision, data }),
  });
  const body = await response.json().catch(() => null);
  if (response.status === 409 && body?.detail?.current) throw new Conflict(body.detail.current);
  if (!response.ok) throw new Error("Chart settings could not be saved.");
  return body;
}

function readLocal(): { settings: ChartSettings | null; meta: Meta | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const meta = JSON.parse(localStorage.getItem(META_KEY) ?? "null");
    return {
      settings: raw ? sanitizeSettings(JSON.parse(raw)) : null,
      meta: meta && Number.isInteger(meta.revision) && meta.revision >= 0 && meta.base
        ? { revision: meta.revision, base: fromServer(meta.base) } : null,
    };
  } catch { return { settings: null, meta: null }; }
}

function writeLocal(settings: ChartSettings, meta: Meta): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    localStorage.setItem(META_KEY, JSON.stringify(meta));
    return true;
  } catch { return false; }
}

/**
 * The workspace's settings: loaded from the server (merging in anything this
 * browser changed that the server has not seen, including settings saved
 * before the server kept them), saved there shortly after each change, and
 * refreshed when the page regains focus or every 30 seconds while visible.
 */
export function useChartSettings() {
  const [settings, setSettings] = useState<ChartSettings>(DEFAULT_SETTINGS);
  const [ready, setReady] = useState(false);
  const [sync, setSync] = useState<SyncState>("loading");
  const [stored, setStored] = useState(true);
  // Set when a save was refused and merged; cleared by this device's next change.
  const [merged, setMerged] = useState(false);
  const latest = useRef(settings);
  const revision = useRef(0);
  const confirmed = useRef(shared(DEFAULT_SETTINGS)); // the server's copy at `revision`
  const saving = useRef(false);
  const edits = useRef(0);
  const pending = useRef<number | undefined>(undefined);

  const push = useCallback(async () => {
    const sending = shared(latest.current);
    if (saving.current || same(sending, confirmed.current)) return;
    saving.current = true;
    setSync("saving");
    let saved: SyncState = "saved";
    try {
      const saved = await saveSettings(revision.current, sending);
      revision.current = saved.revision;
      confirmed.current = sending;
    } catch (err) {
      if (err instanceof Conflict) {
        // Another device saved first: keep its changes and put this device's on top.
        const theirs = fromServer(err.current.data);
        const merged = rebase(confirmed.current, shared(latest.current), theirs);
        revision.current = err.current.revision;
        confirmed.current = theirs;
        setSettings((prior) => ({ ...merged, symbol: prior.symbol, recent: prior.recent })); // saved again next
        setMerged(true);
      } else saved = "offline";
    }
    saving.current = false;
    setStored(writeLocal(latest.current, { revision: revision.current, base: confirmed.current }));
    setSync(saved);
  }, []);

  useEffect(() => {
    let alive = true;
    const local = readLocal();
    const base = local.meta?.base ?? shared(DEFAULT_SETTINGS);
    // This browser's copy shows while the server's loads (read after hydration,
    // so the server render matches). Anything changed meanwhile is part of this
    // device's changes, merged in below.
    queueMicrotask(() => { if (alive && local.settings) setSettings(local.settings); });
    fetchSettings().then((server) => {
      if (!alive) return;
      const theirs = server.data ? fromServer(server.data) : shared(DEFAULT_SETTINGS);
      revision.current = server.revision;
      confirmed.current = theirs;
      // A first visit after the server started keeping settings has no base:
      // everything saved in this browser merges in as this device's changes.
      setSettings((current) => {
        const mine = shared(current);
        return { ...(same(mine, base) ? theirs : rebase(base, mine, theirs)), symbol: current.symbol, recent: current.recent };
      });
      setSync("saved");
    }, () => {
      if (!alive) return;
      revision.current = local.meta?.revision ?? 0;
      confirmed.current = base;
      setSync("offline");
    }).finally(() => { if (alive) setReady(true); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    latest.current = settings;
    if (!ready) return;
    edits.current += 1;
    setStored(writeLocal(settings, { revision: revision.current, base: confirmed.current }));
    window.clearTimeout(pending.current);
    if (same(shared(settings), confirmed.current)) return;
    setSync((state) => state === "saved" ? "saving" : state);
    // A change made while a save is in flight waits for it, then saves on top.
    const attempt = () => { if (saving.current) pending.current = window.setTimeout(attempt, 250); else void push(); };
    pending.current = window.setTimeout(attempt, 400);
  }, [settings, ready, push]);

  useEffect(() => {
    if (!ready) return;
    const refresh = async () => {
      if (document.hidden || saving.current) return;
      // Unsaved changes (made offline, or while a save failed) go first; a conflict merges them.
      if (!same(shared(latest.current), confirmed.current)) { void push(); return; }
      const before = edits.current;
      try {
        const server = await fetchSettings();
        setSync((state) => state === "offline" ? "saved" : state);
        // A change made during the request is newer than this copy; its save will merge.
        if (edits.current !== before || saving.current || server.revision === revision.current) return;
        const theirs = server.data ? fromServer(server.data) : shared(DEFAULT_SETTINGS);
        revision.current = server.revision;
        confirmed.current = theirs;
        setSettings((prior) => ({ ...theirs, symbol: prior.symbol, recent: prior.recent }));
      } catch { setSync("offline"); }
    };
    const onVisible = () => { if (!document.hidden) void refresh(); };
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); window.removeEventListener("focus", onVisible); };
  }, [ready, push]);

  useEffect(() => () => window.clearTimeout(pending.current), []);

  const update = useCallback((action: SetStateAction<ChartSettings>) => { setMerged(false); setSettings(action); }, []);
  return { settings, setSettings: update, ready, sync, merged, stored };
}
