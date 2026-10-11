import { test, expect } from "@playwright/test";
import { createStreamStore } from "../lib/chartStore";
import type { ChartStreamTick } from "../lib/charts";

// Exercise bursts before a frame; browser tests cover the resulting DOM/canvas.
test("stream store preserves OHLC and rollover while notifying only the changed symbol", () => {
  const original = globalThis.window;
  let scheduled: FrameRequestCallback | undefined;
  globalThis.window = { requestAnimationFrame: (fn: FrameRequestCallback) => { scheduled = fn; return 1; }, cancelAnimationFrame: () => {} } as unknown as Window & typeof globalThis;
  try {
    const store = createStreamStore();
    store.status("market", "connected");
    let mrvl = 0, spy = 0;
    store.subscribe("MRVL", () => mrvl++); store.subscribe("SPY", () => spy++);
    const at = Date.now() / 1000;
    const minute = Math.floor(at / 60) * 60;
    const tick = (price: number, stamp: number): ChartStreamTick => ({ type: "tick", symbol: "MRVL", at: stamp, minute: Math.floor(stamp / 60) * 60,
      price, open: price, high: price, low: price, session: "regular", buckets: {} });
    for (const [price, stamp] of [[100, minute], [120, minute + 1], [80, minute + 2], [105, minute + 3], [110, minute + 60]]) store.tick("market", tick(price, stamp));
    expect(mrvl).toBe(0); expect(spy).toBe(0);
    scheduled!(0);
    expect(mrvl).toBe(1); expect(spy).toBe(0);
    const first = store.get("MRVL").ticks[0];
    expect([first.open, first.high, first.low, first.price]).toEqual([100, 120, 80, 105]);
    expect(store.get("MRVL").ticks[1].minute).toBe(minute + 60);
    store.status("market", "connecting"); store.status("market", "connected");
    expect(store.get("MRVL").ticks[0]).toBe(first); // reconnect retains display history
    store.tick("market", tick(1, minute)); scheduled!(0);
    expect(store.get("MRVL").ticks.at(-1)!.price).toBe(110); // late event cannot rewind
    store.retain(["SPY"]);
    expect(store.get("MRVL").ticks).toEqual([]);
    store.dispose();
  } finally { globalThis.window = original; }
});
