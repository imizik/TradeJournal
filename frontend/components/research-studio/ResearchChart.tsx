"use client";
import { useState } from "react";
import type { Chart } from "./types";
export default function ResearchChart({ chart, select }: { chart: Chart; select: (stamp: string) => void }) {
  const [count, setCount] = useState(78), [ending, setEnding] = useState<number | null>(null);
  const end = Math.min(ending ?? chart.bars.length, chart.bars.length);
  const bars = chart.bars.slice(Math.max(0, end-count), end);
  if (!bars.length) return <p>No complete chart bars at this cutoff. Missing prices remain unavailable.</p>;
  const lo = Math.min(...bars.map(b => b.low)), hi = Math.max(...bars.map(b => b.high));
  const y = (p: number) => 180 - (p - lo) / (hi - lo || 1) * 160;
  const x = (i: number) => 30 + (i + .5) * 850 / bars.length;
  const decision = Date.parse(chart.decision_time) / 1000;
  return <div>
    <div className="flex flex-wrap items-center gap-3 text-xs mb-2"><label>Candles visible <select aria-label="Chart zoom" className="border rounded bg-background" value={count} onChange={e => setCount(Number(e.target.value))}><option value="78">Full session</option><option value="24">24 candles</option><option value="12">12 candles</option></select></label><label>Chart end <input aria-label="Chart pan" type="range" min="1" max={chart.bars.length} value={end} onChange={e=>setEnding(Number(e.target.value))}/></label></div>
    <svg viewBox="0 0 920 210" className="w-full rounded bg-background" aria-label={`${chart.symbol} historical five-minute candles`}>
      <text x="4" y="16" fill="currentColor" fontSize="12">{hi.toFixed(2)}</text><text x="4" y="198" fill="currentColor" fontSize="12">{lo.toFixed(2)}</text>
      {bars.map((b, i) => <g key={b.time} role="button" tabIndex={0} data-bar-close={new Date((b.time + 300) * 1000).toISOString()} aria-label={`Select completed bar ${new Date((b.time + 300) * 1000).toISOString()}`} onClick={() => select(new Date((b.time + 300) * 1000).toISOString())} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(new Date((b.time + 300) * 1000).toISOString()); } }} className="cursor-pointer">
        <title>{new Date(b.time * 1000).toISOString()} · O {b.open} H {b.high} L {b.low} C {b.close}</title>
        <rect x={x(i) - 850 / bars.length / 2} y="10" width={850 / bars.length} height="185" fill="transparent" />
        <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={b.close >= b.open ? "#34d399" : "#fb7185"} />
        <rect x={x(i) - Math.max(1, 300 / bars.length)} width={Math.max(2, 600 / bars.length)} y={Math.min(y(b.open), y(b.close))} height={Math.max(1, Math.abs(y(b.open) - y(b.close)))} fill={b.close >= b.open ? "#34d399" : "#fb7185"} />
        {b.time + 300 === decision && <line x1={x(i)} x2={x(i)} y1="5" y2="200" stroke="#38bdf8" strokeDasharray="3 3" />}
      </g>)}
    </svg>
    <p className="text-xs text-muted-foreground">Five-minute RTH · Factory inferred split basis · {chart.revealed ? "Future revealed and recorded" : "Completed prices through decision only"}. Click a candle to inspect its completed close.</p>
  </div>;
}
