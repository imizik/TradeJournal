"use client";
import { useState } from "react";
import type { DecisionContext } from "@/lib/api";
import { frozenWindow, type FrozenMinute, type FrozenQuarter } from "@/lib/frozen-evidence";
const price = (value: number) => `$${value.toFixed(4)}`;
const clock = (at: number) => new Date(at).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const utc = (at: number) => new Date(at).toISOString();
export default function FrozenSampleChart({ context }: { context: DecisionContext }) {
  const [interval, setInterval] = useState<"1m" | "15m">("1m");
  let window;
  try {
    if (context.provider !== "sample_fixture" || context.packet.sample_data !== true) throw new Error("A frozen sample packet is required.");
    window = frozenWindow(context.packet.recent_minute_bars, context.captured_at);
  } catch (error) {
    return <section aria-label={`${context.symbol} frozen evidence chart`} className="min-w-0 rounded border p-3"><h4 className="font-semibold">Frozen evidence chart</h4><p role="status">Chart unavailable: {error instanceof Error ? error.message : "Invalid frozen data."} Inspect the original packet.</p></section>;
  }
  const { minutes, quarters } = window;
  const bars: (FrozenMinute | FrozenQuarter)[] = interval === "1m" ? minutes : quarters;
  const plan = (context.packet.sample_plan ?? {}) as Record<string, unknown>;
  const levels = ([ ["Trigger", plan.trigger_level], ["Stop", plan.stop], ["Target", plan.target] ] as const)
    .filter((value): value is readonly ["Trigger" | "Stop" | "Target", number] => typeof value[1] === "number" && Number.isFinite(value[1]) && value[1] > 0 && value[1] <= Number.MAX_SAFE_INTEGER);
  const values = bars.flatMap(b => [b.l, b.h, ...(b.vw === null ? [] : [b.vw])]);
  const low = Math.min(...values, ...levels.map(l => l[1]));
  const high = Math.max(...values, ...levels.map(l => l[1]));
  const padding = Math.max((high - low) * .07, .05);
  const y = (p: number) => 185 - (p - low + padding) / (high - low + 2 * padding) * 165;
  const step = interval === "1m" ? 60_000 : 900_000;
  const begin = bars[0].at, end = bars.at(-1)!.at + step;
  const x = (at: number) => 55 + (at - begin + step / 2) / (end - begin) * 310;
  const width = Math.min(18, 310 * step / (end - begin) * .65);
  const maxVolume = Math.max(1, ...bars.map(b => b.v));
  const segments: string[][] = [];
  bars.forEach((bar, i) => {
    // Missing VWAP/minutes and incomplete aggregate buckets never get bridged.
    const partial = "complete" in bar && !bar.complete;
    if (bar.vw === null || partial) return;
    const previous = bars[i - 1];
    if (!previous || previous.vw === null || bar.at - previous.at !== step || ("complete" in previous && !previous.complete)) segments.push([]);
    segments.at(-1)!.push(`${x(bar.at)},${y(bar.vw)}`);
  });
  return <section aria-label={`${context.symbol} frozen evidence chart`} className="min-w-0 space-y-3 rounded border p-3 text-sm" data-context-id={context.context_id} data-evidence-sha256={context.context_sha256}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">Frozen evidence chart</h4><div className="flex gap-2" aria-label={`${context.symbol} frozen interval`}>{(["1m", "15m"] as const).map(value => <button type="button" key={value} aria-pressed={interval === value} onClick={() => setInterval(value)} className="rounded border px-2 py-1">{value}</button>)}</div></div>
    <p>{minutes.length} completed frozen minutes · USD/share · volume in shares · Eastern time.</p>
    <p className="text-xs text-muted-foreground">Cutoff <time dateTime={context.captured_at}>{new Date(context.captured_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET</time>. Invented evidence only; no live feed or replay continuation.</p>
    <svg viewBox="0 0 400 300" role="img" aria-label={`${context.symbol} frozen ${interval} price and volume`} className="block w-full" data-testid="frozen-candles">
      <title>{context.symbol} frozen candles, packet VWAP, fixed levels and volume</title>
      {[low, (low + high) / 2, high].map((p, i) => <g key={i}><line x1="55" x2="365" y1={y(p)} y2={y(p)} stroke="currentColor" opacity=".12" /><text x="4" y={y(p) + 4} fontSize="13" fill="currentColor">{p.toFixed(2)}</text></g>)}
      {levels.map(([label, p]) => <g key={label}><line x1="55" x2="365" y1={y(p)} y2={y(p)} stroke={label === "Stop" ? "#fb7185" : label === "Target" ? "#34d399" : "#fbbf24"} strokeDasharray="4 3"/><text x="365" y={y(p) - 3} textAnchor="end" fontSize="12" fill="currentColor">{label} {p.toFixed(2)}</text></g>)}
      {bars.map(bar => { const partial = "complete" in bar && !bar.complete; const color = bar.c >= bar.o ? "#34d399" : "#fb7185"; return <g key={bar.at} data-minute-start={utc(bar.at)}><title>{clock(bar.at)} ET: open {price(bar.o)}, high {price(bar.h)}, low {price(bar.l)}, close {price(bar.c)}, volume {bar.v.toLocaleString("en-US")}{partial ? " · partial interval" : ""}</title><line x1={x(bar.at)} x2={x(bar.at)} y1={y(bar.h)} y2={y(bar.l)} stroke={color}/><rect x={x(bar.at)-width/2} y={Math.min(y(bar.o), y(bar.c))} width={width} height={Math.max(1, Math.abs(y(bar.o)-y(bar.c)))} fill={partial ? "none" : color} stroke={color} strokeDasharray={partial ? "2 2" : undefined}/><rect x={x(bar.at)-width/2} y={270-bar.v/maxVolume*55} width={width} height={bar.v/maxVolume*55} fill={color} opacity={partial ? .35 : .65}/></g>; })}
      {segments.map((points, i) => <polyline key={i} points={points.join(" ")} fill="none" stroke="#60a5fa" strokeWidth="1.6" />)}
      <text x="4" y="216" fontSize="13" fill="currentColor">Volume</text><text x="4" y="232" fontSize="12" fill="currentColor">{maxVolume.toLocaleString("en-US")}</text>
      <text x="55" y="290" fontSize="13" fill="currentColor">{clock(begin)} ET</text><text x="365" y="290" textAnchor="end" fontSize="13" fill="currentColor">{clock(end)} ET</text>
    </svg>
    <p className="text-xs">Blue: packet VWAP (last supplied value per 15-minute interval) · dashed: fixed plan levels. {String(context.packet.vwap_basis ?? "VWAP values are supplied by the frozen sample packet.")}</p>
    {minutes.some(bar => bar.vw === null) && <p className="text-xs text-muted-foreground">VWAP unavailable for {minutes.filter(bar => bar.vw === null).length} frozen minutes; gaps stay visible.</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-xs" aria-label={`${context.symbol} frozen 15-minute summary`}><caption className="pb-2 text-left font-medium">15-minute price and volume · clock-aligned · partial intervals are not trigger confirmations.</caption><thead><tr>{["Interval ET", "Coverage", "Open", "High", "Low", "Close", "Volume"].map(h => <th key={h} className="whitespace-nowrap px-2 py-1">{h}</th>)}</tr></thead><tbody>{quarters.map(bar => <tr key={bar.at} data-start={utc(bar.at)} className="border-t"><th scope="row" className="whitespace-nowrap px-2 py-2 font-normal"><time dateTime={utc(bar.at)}>{clock(bar.at)}–{clock(bar.at+900_000)}</time></th><td className="whitespace-nowrap px-2 py-2">{bar.complete ? "Complete" : "Partial"} · {bar.count}/15</td>{[bar.o,bar.h,bar.l,bar.c].map((p,i) => <td key={i} className="whitespace-nowrap px-2 py-2 tabular-nums">{price(p)}</td>)}<td className="whitespace-nowrap px-2 py-2 tabular-nums">{bar.v.toLocaleString("en-US")}</td></tr>)}</tbody></table></div>
    <details><summary>Frozen source identity</summary><p className="break-all">Context {context.context_id}</p><p className="break-all">Evidence SHA-256: {context.context_sha256}</p><p>No hash verification is implied by this display.</p></details>
  </section>;
}
