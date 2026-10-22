import { expect, test } from "@playwright/test";
import { beginHistoryLoad, mergePastRvol, type OlderPanel, type OlderState } from "../lib/chartHistory";
import type { ChartBar, HistoryPage, RvolBaseline } from "../lib/charts";

test("a queued history response survives the next request from an older render", () => {
  const initial: OlderState = { key: "extended", panels: {} };
  const frame = "NVDA|5m";
  // This callback was created while no history was present. React applies it
  // after the prior request's response updater, before committing either.
  const startNext = (state: OlderState) => beginHistoryLoad(state, initial.key, frame);
  const history: OlderPanel = {
    bars: [{ time: 1784036400, end_time: 1784036700, source: "alpaca_sip", open: 90, high: 91, low: 89, close: 90.5,
      volume: 100, ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null, extended: false }],
    markers: [{ id: "entry", time: 1784036400, label: "entry", buy: true }],
    exhausted: true, warmup: "ready", issue: "retryable", loading: false,
    calendarNote: "calendar unavailable", adjustmentNote: "recorded split", historyStart: "2026-07-14",
    adjustment: { basis: "split_adjusted", status: "ok", source: "alpaca_corporate_actions", as_of: 1784036400,
      splits: [], daily: {}, dividends: "unsupported", dividends_note: "", warnings: [] },
  };
  const other: OlderPanel = { ...history, markers: [] };
  const receive = (state: OlderState): OlderState => ({ ...state, panels: { [frame]: history, "SPY|15m": other } });
  const next = [receive, startNext].reduce((state, update) => update(state), initial);
  expect(next.panels[frame]).toEqual({ ...history, issue: null, loading: true });
  expect(next.panels[frame]!.bars).toBe(history.bars);
  expect(next.panels[frame]!.markers).toBe(history.markers);
  expect(next.panels["SPY|15m"]).toBe(other);
  expect(initial.panels).toEqual({});
});

test("a stale history request cannot resurrect a frame after its session changes", () => {
  const state: OlderState = { key: "regular", panels: {} };
  expect(beginHistoryLoad(state, "extended", "NVDA|5m")).toBe(state);
});

test("a session split between two history pages keeps its first RVol answer, so its candles and baseline agree (C2.6)", () => {
  const bar = (time: number, rvol: number | null): ChartBar => ({ time, end_time: time + 300, source: "alpaca_sip", open: 1, high: 1, low: 1, close: 1,
    volume: 1, ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null, extended: false, rvol });
  const baseline = (day: string, state: RvolBaseline["state"]): RvolBaseline => ({ state, day, sessions: [], traded: 0, missing: [], message: null });
  // 2026-09-15 09:30 and 2026-09-14 15:55 New York.
  const sep15 = Date.parse("2026-09-15T13:30:00Z") / 1000, sep14 = Date.parse("2026-09-14T19:55:00Z") / 1000;
  const page = { bars: [bar(sep14, 0.8), bar(sep15, 1.4)], rvol: { "2026-09-14": baseline("2026-09-14", "ready"), "2026-09-15": baseline("2026-09-15", "ready") } } as unknown as HistoryPage;
  // The first page saw Sep 15 still building: the later page's Sep 15 candle drops its value, and Sep 14 is new.
  const merged = mergePastRvol({ "2026-09-15": baseline("2026-09-15", "building") }, page);
  expect(merged.bars.map((b) => b.rvol)).toEqual([0.8, null]);
  expect(Object.fromEntries(Object.entries(merged.rvol).map(([day, b]) => [day, b.state]))).toEqual({ "2026-09-14": "ready", "2026-09-15": "building" });
  // The first page takes the page as it is.
  expect(mergePastRvol(undefined, page)).toEqual({ bars: page.bars, rvol: page.rvol });
});
