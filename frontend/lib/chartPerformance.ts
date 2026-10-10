import { useEffect } from "react";
import type { ChartStreamTick } from "@/lib/charts";

/** Opt-in, bounded, local diagnostics; no telemetry or provider requests. */
type Sample = { symbol: string; ms: number };
type Diagnostics = { samples: Record<string, Sample[]>; summary: () => Record<string, { count: number; p50: number; p95: number; last: Sample }> };
declare global { interface Window { __tjChartPerformance?: Diagnostics } }
let enabled: boolean | undefined;
const switches = new Map<string, number>();
function diagnosticsEnabled() {
  if (typeof window === "undefined") return false;
  if (enabled === undefined) {
    try { enabled = localStorage.getItem("tj:chart-performance") === "1"; } catch { enabled = false; }
  }
  return enabled;
}
export function recordChartTiming(metric: string, ms: number, symbol: string) {
  if (!Number.isFinite(ms) || !diagnosticsEnabled()) return;
  const diagnostics = window.__tjChartPerformance ??= {
    samples: {},
    summary() {
      return Object.fromEntries(Object.entries(this.samples).map(([name, samples]) => {
        const sorted = samples.map((sample) => sample.ms).sort((a, b) => a - b);
        return [name, { count: samples.length, p50: sorted[Math.floor(sorted.length * .5)],
          p95: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * .95))], last: samples.at(-1)! }];
      }));
    },
  };
  const samples = diagnostics.samples[metric] ??= [];
  samples.push({ symbol, ms });
  if (samples.length > 120) samples.shift();
}
export function receiveChartTick(tick: ChartStreamTick): ChartStreamTick {
  if (!diagnosticsEnabled()) return tick;
  const now = Date.now() / 1000;
  if (tick.provider_ms !== undefined) recordChartTiming("provider_to_backend_estimate", tick.provider_ms, tick.symbol);
  if (tick.received_at !== undefined) recordChartTiming("backend_to_browser_estimate", (now - tick.received_at) * 1000, tick.symbol);
  if (tick.relay_ms !== undefined) recordChartTiming("backend_relay", tick.relay_ms, tick.symbol);
  if (tick.sent_at !== undefined) recordChartTiming("sse_to_browser_estimate", (now - tick.sent_at) * 1000, tick.symbol);
  return { ...tick, receivedMono: performance.now() };
}
/** Two frames after the commit provide a paint opportunity, not a pixel-level timestamp. */
function afterPaint(callback: () => void) {
  let second: number | undefined;
  const first = requestAnimationFrame(() => { second = requestAnimationFrame(callback); });
  return () => { cancelAnimationFrame(first); if (second !== undefined) cancelAnimationFrame(second); };
}
export function useQuoteTiming(tick: ChartStreamTick | undefined) {
  useEffect(() => {
    if (!diagnosticsEnabled() || tick?.receivedMono === undefined) return;
    return afterPaint(() => recordChartTiming("quote_receipt_to_paint_opportunity", performance.now() - tick.receivedMono!, tick.symbol));
  }, [tick]);
}
export function startSymbolTiming(symbol: string) {
  if (!diagnosticsEnabled()) return;
  switches.clear(); switches.set(symbol, performance.now());
}
export function chartCommitted(symbol: string, tick: ChartStreamTick | undefined, main: boolean) {
  if (!diagnosticsEnabled()) return;
  return afterPaint(() => {
    if (tick?.receivedMono !== undefined) recordChartTiming("candle_receipt_to_paint_opportunity", performance.now() - tick.receivedMono, symbol);
    const start = switches.get(symbol);
    if (main && start !== undefined) {
      recordChartTiming("symbol_to_usable_chart", performance.now() - start, symbol);
      switches.delete(symbol);
    }
  });
}
