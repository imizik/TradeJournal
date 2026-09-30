import { useMemo, useSyncExternalStore } from "react";
import { applyTicks, intradayInterval } from "@/lib/charts";
import type { ChartPanelData, ChartStreamTick, Interval, TickScope } from "@/lib/charts";

/**
 * Chart state that changes faster than the workspace should re-render: the
 * live trade stream and the one-second clock. Both live outside React state.
 * Components read the slice they show through `useSyncExternalStore`, so a
 * tick re-renders only the panels whose candles moved (plus the quote), and
 * the clock re-renders only the countdowns and ages that display it.
 */
type Listener = () => void;

export type StreamStatus = "connecting" | "connected" | "fallback";
/** `seq` counts every tick ever published, so a panel can apply only the ticks it has not seen. */
export type StreamState = { key: string; status: StreamStatus; ticks: ChartStreamTick[]; seq: number };
const IDLE: StreamState = { key: "", status: "fallback", ticks: [], seq: 0 };
const NO_TICKS: ChartStreamTick[] = [];

export function createStreamStore() {
  let state = IDLE;
  const listeners = new Set<Listener>();
  const publish = (next: StreamState) => { state = next; listeners.forEach((fn) => fn()); };
  return {
    get: () => state,
    subscribe(fn: Listener) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    status(key: string, status: StreamStatus) {
      if (state.key === key && state.status === status) return;
      publish(state.key === key ? { ...state, status } : { key, status, ticks: [], seq: state.seq });
    },
    /** Keeps the last two minutes (at most 120 trades); REST refreshes every 15 seconds. */
    tick(key: string, tick: ChartStreamTick) {
      const kept = state.key === key ? state.ticks.filter((old) => old.at > Date.now() / 1000 - 120) : [];
      publish({ key, status: "connected", ticks: [...kept, tick].slice(-120), seq: state.seq + 1 });
    },
  };
}
export type StreamStore = ReturnType<typeof createStreamStore>;
/** One workspace request's stream, and the REST snapshot its ticks must be newer than. */
export type LiveFeed = TickScope & { store: StreamStore; key: string };

/** Read one derived value of the stream. `select` must return a primitive or an object the state already holds. */
export function useStream<T>(live: LiveFeed, select: (ticks: ChartStreamTick[], state: StreamState) => T): T {
  const read = () => { const state = live.store.get(); return select(state.key === live.key ? state.ticks : NO_TICKS, state); };
  return useSyncExternalStore(live.store.subscribe, read, read);
}

/**
 * Applies the stream to one panel's REST candles and keeps the result's
 * identity until a tick changes this panel's candles, which is what lets the
 * other panels skip the render. New ticks are applied incrementally; a new
 * REST base (every 15 seconds) starts again from the ticks newer than it.
 */
function panelSelector(interval: Interval) {
  let memo: { rest: ChartPanelData; scope: string; ticks: ChartStreamTick[]; seq: number; panel: ChartPanelData } | null = null;
  return (state: StreamState, feed: LiveFeed, rest: ChartPanelData | undefined) => {
    if (!rest || !intradayInterval(interval)) return rest;
    const ticks = state.key === feed.key ? state.ticks : NO_TICKS;
    const scope = `${feed.key}|${feed.fetched}`;
    if (memo && memo.rest === rest && memo.scope === scope) {
      if (memo.ticks === ticks) return memo.panel;
      const fresh = state.seq - memo.seq;
      if (ticks !== NO_TICKS && fresh >= 0 && fresh <= ticks.length) {
        const bars = applyTicks(memo.panel.bars, ticks.slice(ticks.length - fresh), interval, feed);
        memo = { ...memo, ticks, seq: state.seq, panel: bars === memo.panel.bars ? memo.panel : { ...memo.panel, bars } };
        return memo.panel;
      }
    }
    const bars = applyTicks(rest.bars, ticks, interval, feed);
    memo = { rest, scope, ticks, seq: state.seq, panel: bars === rest.bars ? rest : { ...rest, bars } };
    return memo.panel;
  };
}

/** One panel's candles with the streamed trades applied; `rest` is its REST candles plus older history. */
export function useLivePanel(live: LiveFeed, interval: Interval, rest: ChartPanelData | undefined): ChartPanelData | undefined {
  const select = useMemo(() => panelSelector(interval), [interval]);
  const read = () => select(live.store.get(), live, rest);
  return useSyncExternalStore(live.store.subscribe, read, () => rest);
}

// One shared timer for every clock reader, running only while one is mounted.
let now = typeof window === "undefined" ? 0 : Date.now() / 1000;
let timer: number | undefined;
const clockListeners = new Set<Listener>();
function subscribeClock(fn: Listener) {
  clockListeners.add(fn);
  if (timer === undefined) {
    now = Date.now() / 1000;
    timer = window.setInterval(() => { now = Date.now() / 1000; clockListeners.forEach((listener) => listener()); }, 1000);
  }
  return () => {
    clockListeners.delete(fn);
    if (!clockListeners.size && timer !== undefined) { window.clearInterval(timer); timer = undefined; }
  };
}

/**
 * A value derived from the browser clock, re-evaluated each second. The
 * component re-renders only when the value changes, so `select` should return
 * a primitive: a countdown's text re-renders each second, a stale flag only
 * when it flips.
 */
export function useClock<T>(select: (now: number) => T): T {
  return useSyncExternalStore(subscribeClock, () => select(now), () => select(0));
}
