"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

/**
 * The desk's last good reads (the book's rows, saved conversations, sparklines, the session, a symbol's header and
 * since-entry facts), kept in memory while the owner stays on /copilot-lab, so a remount or a return to a symbol shows
 * them at once while the fresh read is on its way. Never written to disk or storage (it holds account data); it goes
 * when the page does. Outside the desk there is no memory and nothing is kept.
 */
const Memory = createContext<Map<string, unknown> | null>(null);

export function DeskMemory({ children }: { children: ReactNode }) {
  const [store] = useState(() => new Map<string, unknown>());
  return <Memory.Provider value={store}>{children}</Memory.Provider>;
}

/** The kept value for ``key`` (undefined when none, or outside the desk) and a function that keeps a new one. */
export function useKept<T>(key: string | null): [T | undefined, (value: T) => void] {
  const store = useContext(Memory);
  const kept = key && store ? store.get(key) as T | undefined : undefined;
  const keep = useCallback((value: T) => { if (key && store) store.set(key, value); }, [key, store]);
  return [kept, keep];
}

/** State that starts from the kept value and keeps each new one. */
export function useKeptState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [kept, keep] = useKept<T>(key);
  const [value, setValue] = useState<T>(() => kept ?? initial);
  const set = useCallback((next: T) => { keep(next); setValue(next); }, [keep]);
  return [value, set];
}
