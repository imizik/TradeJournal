import { useCallback, useSyncExternalStore } from "react";
import { fetchSymbolNews } from "./symbolInfo";
import type { SymbolNews } from "./symbolInfo";

/**
 * One news read per symbol, shared by everything that wants it (T3.5). The News
 * tab and the chart's news markers both call `useSymbolNews`; while either is
 * mounted with `wanted`, the symbol is read once after a 300 ms settle (so
 * stepping through symbols reads only where it stops) and then each minute while
 * the page is visible, and both see the same copy. When the last one lets go the
 * timers stop and the copy is dropped, so the next one starts with a fresh read.
 */
export type NewsFeed = { data: SymbolNews | null; error: string | null };
const EMPTY: NewsFeed = { data: null, error: null };
const SETTLE_MS = 300;
const REFRESH_MS = 60_000;

type Entry = { feed: NewsFeed; listeners: Set<() => void>; settle?: ReturnType<typeof setTimeout>; again?: ReturnType<typeof setInterval>; controller?: AbortController };
const entries = new Map<string, Entry>();

function load(symbol: string, entry: Entry, quiet: boolean) {
  entry.controller?.abort();
  const controller = new AbortController();
  entry.controller = controller;
  const set = (feed: NewsFeed) => { if (entries.get(symbol) !== entry || controller.signal.aborted) return; entry.feed = feed; entry.listeners.forEach((listener) => listener()); };
  fetchSymbolNews(symbol, controller.signal).then((data) => set({ data, error: null }))
    // A refresh that fails keeps what is shown; only the first read says so.
    .catch(() => { if (!quiet || !entry.feed.data) set({ data: null, error: "News unavailable. Try again." }); });
}

function subscribe(symbol: string, listener: () => void) {
  let entry = entries.get(symbol);
  if (!entry) {
    const made: Entry = { feed: EMPTY, listeners: new Set() };
    entry = made;
    entries.set(symbol, made);
    made.settle = setTimeout(() => load(symbol, made, false), SETTLE_MS);
    made.again = setInterval(() => { if (!document.hidden) load(symbol, made, true); }, REFRESH_MS);
  }
  entry.listeners.add(listener);
  const held = entry;
  return () => {
    held.listeners.delete(listener);
    if (held.listeners.size || entries.get(symbol) !== held) return;
    clearTimeout(held.settle); clearInterval(held.again); held.controller?.abort();
    entries.delete(symbol);
  };
}

/** Read again now (the News tab's Retry): clears the error and shows loading until the answer. */
function retry(symbol: string) {
  const entry = entries.get(symbol);
  if (!entry) return;
  entry.feed = EMPTY;
  entry.listeners.forEach((listener) => listener());
  load(symbol, entry, false);
}

const none = () => () => {};
/** `symbol`'s news while `wanted`, shared with every other caller for the same symbol. */
export function useSymbolNews(symbol: string, wanted: boolean): NewsFeed & { retry(): void } {
  const sub = useCallback((listener: () => void) => wanted ? subscribe(symbol, listener) : none(), [symbol, wanted]);
  const feed = useSyncExternalStore(sub, () => wanted ? entries.get(symbol)?.feed ?? EMPTY : EMPTY, () => EMPTY);
  const again = useCallback(() => retry(symbol), [symbol]);
  return { ...feed, retry: again };
}
