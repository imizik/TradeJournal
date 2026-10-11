import { useCallback, useMemo, useSyncExternalStore } from "react";
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
/** Each symbol has its own immutable, bounded minute-bucket snapshot. */
export type StreamState = { key: string; status: StreamStatus; ticks: ChartStreamTick[]; seq: number };
const NO_TICKS: ChartStreamTick[] = [];

export function createStreamStore() {
  let key = "", status: StreamStatus = "fallback";
  const states = new Map<string, StreamState>();
  const listeners = new Map<string, Set<Listener>>();
  const pending = new Map<string, ChartStreamTick[]>();
  let frame: number | undefined;
  let recover = () => {};
  const get = (symbol: string) => {
    let state = states.get(symbol);
    if (!state) { state = { key, status, ticks: [], seq: 0 }; states.set(symbol, state); }
    return state;
  };
  const notify = (symbol: string) => listeners.get(symbol)?.forEach((fn) => fn());
  const flush = () => {
    if (frame !== undefined) window.cancelAnimationFrame(frame);
    frame = undefined;
    for (const [symbol, incoming] of pending) {
      const state = get(symbol);
      // Per-symbol minute buckets: a burst must keep its open, high and low,
      // including the previous minute when a frame straddles a boundary.
      const ticks = state.ticks.filter((tick) => tick.at > Date.now() / 1000 - 120);
      for (const tick of incoming) {
        const previous = ticks.at(-1);
        if (previous && tick.at < previous.at) continue;
        if (previous?.minute === tick.minute) ticks[ticks.length - 1] = {
          ...tick, open: previous.open, high: Math.max(previous.high, tick.high), low: Math.min(previous.low, tick.low),
        };
        else ticks.push(tick);
      }
      states.set(symbol, { key, status, ticks: ticks.slice(-64), seq: state.seq + 1 });
      notify(symbol);
    }
    pending.clear();
  };
  return {
    get,
    flush,
    onGap(fn: () => void) { recover = fn; },
    subscribe(symbol: string, fn: Listener) {
      const group = listeners.get(symbol) ?? new Set<Listener>();
      listeners.set(symbol, group); group.add(fn);
      return () => { group.delete(fn); if (!group.size) listeners.delete(symbol); };
    },
    retain(symbols: string[]) {
      const wanted = new Set(symbols);
      for (const symbol of states.keys()) if (!wanted.has(symbol)) states.delete(symbol);
      for (const symbol of pending.keys()) if (!wanted.has(symbol)) pending.delete(symbol);
    },
    status(nextKey: string, nextStatus: StreamStatus) {
      if (key === nextKey && status === nextStatus) return;
      if (key !== nextKey) { states.clear(); pending.clear(); }
      key = nextKey; status = nextStatus;
      for (const [symbol, state] of states) {
        states.set(symbol, { ...state, key, status }); notify(symbol);
      }
      for (const symbol of listeners.keys()) if (!states.has(symbol)) notify(symbol);
    },
    tick(nextKey: string, tick: ChartStreamTick) {
      if (key !== nextKey || status !== "connected") this.status(nextKey, "connected");
      const ticks = pending.get(tick.symbol) ?? [];
      // Merge before the frame as well, bounding work during a large burst.
      const previous = ticks.at(-1);
      if (previous && tick.at < previous.at) return;
      if (previous?.minute === tick.minute) ticks[ticks.length - 1] = {
        ...tick, open: previous.open, high: Math.max(previous.high, tick.high), low: Math.min(previous.low, tick.low),
      };
      else ticks.push(tick);
      if (ticks.length > 64) recover();
      pending.set(tick.symbol, ticks.slice(-64));
      if (frame === undefined) frame = window.requestAnimationFrame(flush);
    },
    dispose() {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      frame = undefined; pending.clear(); states.clear();
    },
  };
}
export type StreamStore = ReturnType<typeof createStreamStore>;
/** One workspace request's stream, and the REST snapshot its ticks must be newer than. */
export type LiveFeed = TickScope & { store: StreamStore; key: string };

/** Read one derived value of the stream. `select` must return a primitive or an object the state already holds. */
export function useStream<T>(live: LiveFeed, select: (ticks: ChartStreamTick[], state: StreamState) => T): T {
  const subscribe = useCallback((fn: Listener) => live.store.subscribe(live.symbol, fn), [live.store, live.symbol]);
  const read = () => { const state = live.store.get(live.symbol); return select(state.key === live.key ? state.ticks : NO_TICKS, state); };
  return useSyncExternalStore(subscribe, read, read);
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
    const scope = `${feed.key}|${feed.symbol}|${feed.session}|${feed.fetched}`;
    if (memo && memo.rest === rest && memo.scope === scope) {
      if (memo.ticks === ticks) return memo.panel;
      // Unchanged minute objects were already applied. Replaying them can
      // temporarily rewind a larger candle's close and cause a needless render.
      const changed = ticks.filter((tick) => !memo!.ticks.includes(tick));
      const bars = applyTicks(memo.panel.bars, changed, interval, feed);
      memo = { ...memo, ticks, seq: state.seq, panel: bars === memo.panel.bars ? memo.panel : { ...memo.panel, bars } };
      return memo.panel;
    }
    const bars = applyTicks(rest.bars, ticks, interval, feed);
    memo = { rest, scope, ticks, seq: state.seq, panel: bars === rest.bars ? rest : { ...rest, bars } };
    return memo.panel;
  };
}

/** One panel's candles with the streamed trades applied; `rest` is its REST candles plus older history. */
export function useLivePanel(live: LiveFeed, interval: Interval, rest: ChartPanelData | undefined): ChartPanelData | undefined {
  const select = useMemo(() => panelSelector(interval), [interval]);
  const subscribe = useCallback((fn: Listener) => live.store.subscribe(live.symbol, fn), [live.store, live.symbol]);
  const read = () => select(live.store.get(live.symbol), live, rest);
  return useSyncExternalStore(subscribe, read, () => rest);
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
