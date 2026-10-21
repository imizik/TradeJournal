import type { ChartBar, FillMarker, PriceAdjustment, RvolBaseline } from "./charts";

export type OlderPanel = { bars: ChartBar[]; markers: FillMarker[]; exhausted: boolean; warmup: string; issue: string | null; loading: boolean; calendarNote?: string | null; adjustment?: PriceAdjustment; adjustmentNote?: string | null; historyStart?: string | null;
  /** Each loaded older session's RVol baseline by New York date (C2.6). */
  rvol?: Record<string, RvolBaseline> };
/** Older history per frame (`symbol|interval`), for one session. */
export type OlderState = { key: string; panels: Partial<Record<string, OlderPanel>> };

/** A new request must preserve responses already queued since its callback was rendered. */
export function beginHistoryLoad(state: OlderState, session: string, key: string): OlderState {
  if (state.key !== session) return state;
  const prior = state.panels[key] ?? { bars: [], markers: [], exhausted: false, warmup: "pending", issue: null, loading: false };
  return { ...state, panels: { ...state.panels, [key]: { ...prior, issue: null, loading: true } } };
}
