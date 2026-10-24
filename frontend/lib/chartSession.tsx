"use client";
import { createContext, useContext, useMemo } from "react";
import { useAppAccess } from "@/components/AccessProvider";
import { nyDay } from "./charts";
import type { ChartData, ChartSettings } from "./charts";
import type { OlderState } from "./chartHistory";

export type ChartResponse = { key: string; session: ChartSettings["session"]; data: ChartData };
export type ChartSnapshot = { response: ChartResponse; older: OlderState; ranges: Map<string, { from: number; to: number }> };
/** Browser memory only. A new identity/grant set gets a new store; never shared
 * with server requests, persisted to disk, or reused across NY session dates. */
export function createChartSession(clock: () => number = Date.now) {
  const entries = new Map<string, { snapshot: ChartSnapshot; saved: number; day: string }>();
  return {
    get(key: string) {
      const entry = entries.get(key);
      return entry && clock() - entry.saved < 5 * 60_000 && entry.day === nyDay(clock() / 1000) ? entry.snapshot : undefined;
    },
    put(snapshot: ChartSnapshot) {
      entries.delete(snapshot.response.key);
      const panels = Object.fromEntries(Object.entries(snapshot.older.panels).filter(([, panel]) => panel && !panel.loading));
      snapshot.older = { ...snapshot.older, panels };
      entries.set(snapshot.response.key, { snapshot,
        saved: snapshot.response.data.checked_at * 1000, day: nyDay(snapshot.response.data.checked_at) });
      while (entries.size > 4) entries.delete(entries.keys().next().value!);
    },
  };
}
const Context = createContext<ReturnType<typeof createChartSession> | null>(null);
export function ChartSessionProvider({ children }: { children: React.ReactNode }) {
  const access = useAppAccess();
  const identity = JSON.stringify([access.identifier, access.owner, access.csrf, access.grants, access.sample_data]);
  const cache = useMemo(() => createChartSession(), [identity]); // eslint-disable-line react-hooks/exhaustive-deps -- identity explicitly scopes all cached data
  return <Context.Provider key={identity} value={access.owner ? cache : null}>{children}</Context.Provider>;
}
export const useChartSession = () => useContext(Context);
