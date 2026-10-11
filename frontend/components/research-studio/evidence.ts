import type { Definition, Result } from "./types";

export const horizons = ["15m", "30m", "60m", "session_close"];
export function eventEvidence(result: Result, horizon: string, unit: string) {
  const values = result.events.map(e => e.outcomes[horizon]?.[unit as "percent" | "prior_daily_atr14"])
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const n = values.length;
  if (!n) return {n, positive: 0, mean: null, median: null, spread: null, withoutLargest: null, withoutSmallest: null};
  const sorted = [...values].sort((a,b) => a-b), sum = values.reduce((a,b) => a+b, 0), mean = sum/n;
  return {n, positive: values.filter(v => v>0).length, mean,
    median: n%2 ? sorted[(n-1)/2] : (sorted[n/2-1]+sorted[n/2])/2,
    spread: n>1 ? Math.sqrt(values.reduce((a,v) => a+(v-mean)**2,0)/(n-1)) : null,
    withoutLargest: n>1 ? (sum-sorted[n-1])/(n-1) : null,
    withoutSmallest: n>1 ? (sum-sorted[0])/(n-1) : null};
}
export function sameQuestion(a: Definition, b: Definition) {
  const signature = (d: Definition) => JSON.stringify({universe:[...d.universe].sort(),
    window_start:d.window_start, window_end:d.window_end,
    predicates:d.predicates.map(p=>JSON.stringify([p.feature,p.minimum,p.maximum])).sort()});
  return signature(a)===signature(b);
}
export function disjointPeriods(a: Definition, b: Definition) { return a.end<b.start || b.end<a.start; }
export function sameCalculation(a: Result, b: Result) {
  return a.analysis_code_id===b.analysis_code_id && JSON.stringify(a.spec)===JSON.stringify(b.spec);
}
