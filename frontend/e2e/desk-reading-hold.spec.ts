import { expect, test } from "@playwright/test";
import { heldReading, type HeldReading } from "../lib/deskTicks";

const at = (iso: string) => Date.parse(iso) / 1000;
const read = (last: number, when: string, extra: Partial<HeldReading["reading"]> = {}): HeldReading => ({
  reading: { last, at: at(when), daily: false, prev_close: 100, vwap: null, vwap_at: null, rvol: null, ...extra },
  invalidation: null, ticked: false,
});

test("the reading line holds what it showed instead of blanking or stepping back to an older price", () => {
  const store = new Map<string, HeldReading>();
  const after = read(103, "2026-11-13T17:30:00-05:00");
  expect(heldReading("NVDA", after, store)).toBe(after);
  // A read loading: the last price stays.
  expect(heldReading("NVDA", null, store)).toBe(after);
  // The regular close (an older minute, or the daily candle) comes back: still the extended-hours price.
  expect(heldReading("NVDA", read(102, "2026-11-13T15:59:00-05:00"), store)).toBe(after);
  expect(heldReading("NVDA", read(102, "2026-11-13T17:45:00-05:00", { daily: true }), store)).toBe(after);
  // A newer price shows at once; one without a previous close keeps the day's.
  const newer = heldReading("NVDA", read(104, "2026-11-13T17:32:00-05:00", { prev_close: null }), store)!;
  expect(newer.reading.last).toBe(104);
  expect(newer.reading.prev_close).toBe(100);
  // Never another symbol's price.
  expect(heldReading("AMD", null, store)).toBeNull();
});
