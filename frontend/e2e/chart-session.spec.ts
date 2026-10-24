import { expect, test } from "@playwright/test";
import { createChartSession, type ChartSnapshot } from "../lib/chartSession";
import type { ChartData } from "../lib/charts";

test("chart session snapshots expire, stay bounded and drop unfinished history", () => {
  let now = Date.parse("2026-10-23T19:00:00Z");
  const cache = createChartSession(() => now);
  const snapshot = (key: string): ChartSnapshot => ({ response: { key, session: "regular", data: { checked_at: now / 1000 } as ChartData },
    older: { key: "regular", panels: { "SPY|5m": { bars: [], markers: [], exhausted: false, warmup: "pending", issue: null, loading: true } } }, ranges: new Map() });
  for (let i = 0; i < 5; i++) cache.put(snapshot(String(i)));
  expect(cache.get("0")).toBeUndefined();
  expect(cache.get("4")?.older.panels).toEqual({});
  expect(cache.get("3")).toBeDefined();
  now += 5 * 60_000;
  expect(cache.get("4")).toBeUndefined();
  now = Date.parse("2026-10-24T03:59:30Z");
  cache.put(snapshot("midnight"));
  now += 60_000;
  expect(cache.get("midnight")).toBeUndefined();
  expect(createChartSession(() => now).get("3")).toBeUndefined();
});
