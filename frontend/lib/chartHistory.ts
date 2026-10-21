import { nyDay } from "./charts";
import type { ChartBar, FillMarker, HistoryPage, PriceAdjustment, RvolBaseline } from "./charts";

export type OlderPanel = { bars: ChartBar[]; markers: FillMarker[]; exhausted: boolean; warmup: string; issue: string | null; loading: boolean; calendarNote?: string | null; adjustment?: PriceAdjustment; adjustmentNote?: string | null; historyStart?: string | null;
  /** Each loaded older session's RVol baseline by New York date (C2.6). */
  rvol?: Record<string, RvolBaseline> };
/** Older history per frame (`symbol|interval`), for one session. */
export type OlderState = { key: string; panels: Partial<Record<string, OlderPanel>> };

/**
 * Older sessions' RVol (C2.6) across pages. The first answer for a session stands: a session split
 * between two pages never shows a later page's values beside an earlier page's "building" (its
 * window was stored in between); a reload brings the newer answer.
 */
export function mergePastRvol(prior: Record<string, RvolBaseline> | undefined, page: HistoryPage): { bars: ChartBar[]; rvol: Record<string, RvolBaseline> } {
  if (!prior) return { bars: page.bars, rvol: page.rvol ?? {} };
  const bars = page.bars.map((bar) => {
    const was = prior[nyDay(bar.time)];
    return was && was.state !== "ready" && bar.rvol != null ? { ...bar, rvol: null } : bar;
  });
  return { bars, rvol: { ...page.rvol, ...prior } };
}

/** A new request must preserve responses already queued since its callback was rendered. */
export function beginHistoryLoad(state: OlderState, session: string, key: string): OlderState {
  if (state.key !== session) return state;
  const prior = state.panels[key] ?? { bars: [], markers: [], exhausted: false, warmup: "pending", issue: null, loading: false };
  return { ...state, panels: { ...state.panels, [key]: { ...prior, issue: null, loading: true } } };
}
