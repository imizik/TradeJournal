import { expect, test } from "@playwright/test";
import { beginHistoryLoad, type OlderPanel, type OlderState } from "../lib/chartHistory";

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
