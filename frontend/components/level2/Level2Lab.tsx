"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import LiveDepthSession from "@/components/level2/LiveDepthSession";
import {
  bookAge, bookState, depthSummary, DURATION_MS, HEATMAP_PRICES, priceText,
  REPLAY_FRAMES, replayAt, sourceTime, type BookState, type ReplayFrame,
} from "@/lib/level2Replay";

const STATE_LABEL: Record<BookState, string> = {
  fresh: "Fresh simulated book", stale: "Stale simulated book", disconnected: "Simulated disconnect",
  empty: "Empty simulated book", "unknown-time": "Source time unavailable",
};
const quantity = (value: number) => value.toLocaleString("en-US");

function Heatmap({ offsetMs }: { offsetMs: number }) {
  const visible = REPLAY_FRAMES.filter(frame => frame.offsetMs <= offsetMs);
  const width = 600, left = 64, top = 12, cellW = (width - left - 12) / REPLAY_FRAMES.length, cellH = 10;
  return <section aria-labelledby="heatmap-title" className="min-w-0 rounded-lg border bg-card p-4">
    <h2 id="heatmap-title" className="font-semibold">Liquidity heatmap</h2>
    <p className="mt-1 text-xs text-muted-foreground">Synthetic displayed sizes over replay time. Green = bid · red = ask · brighter = larger size.</p>
    <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable liquidity heatmap" onKeyDown={event => {
      const element = event.currentTarget;
      if (event.key === "End") { event.preventDefault(); element.scrollLeft = element.scrollWidth - element.clientWidth; }
      if (event.key === "Home") { event.preventDefault(); element.scrollLeft = 0; }
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") { event.preventDefault(); element.scrollLeft += event.key === "ArrowRight" ? 80 : -80; }
    }}>
    <svg viewBox={`0 0 ${width} 295`} role="img" aria-label="Synthetic ARCA liquidity heatmap" className="w-full min-w-[600px]">
      <title>Synthetic ARCA price-level liquidity; blank columns mark unavailable books or future replay time.</title>
      {HEATMAP_PRICES.map((price, row) => <g key={price}>
        <line x1={left} x2={width - 12} y1={top + row * cellH} y2={top + row * cellH} className="stroke-border" />
        {row % 4 === 0 && <text x={left - 7} y={top + row * cellH + 8} textAnchor="end" className="fill-muted-foreground" fontSize="10">{priceText(price)}</text>}
      </g>)}
      {visible.flatMap(frame => {
        if (bookState(frame, frame.offsetMs) !== "fresh") return [];
        return (["bids", "asks"] as const).flatMap(side => frame.book[side].map(level => {
          const row = HEATMAP_PRICES.indexOf(level.priceCents);
          if (row < 0 || level.size === 0) return null;
          return <rect key={`${frame.offsetMs}-${side}-${level.priceCents}`} data-column={frame.offsetMs / 1000}
            x={left + frame.offsetMs / 1000 * cellW} y={top + row * cellH + 1} width={cellW - 1} height={cellH - 1}
            className={side === "bids" ? "fill-emerald-400" : "fill-red-400"} opacity={0.15 + 0.85 * Math.min(level.size / 2300, 1)}>
            <title>{`${sourceTime(frame.offsetMs)} ET · ${side === "bids" ? "Bid" : "Ask"} ${priceText(level.priceCents)} · ${quantity(level.size)} synthetic shares`}</title>
          </rect>;
        }));
      })}
      {[0, 5, 10, 15, 20].map(second => <text key={second} x={left + (second + 0.5) * cellW} y={278} textAnchor="middle" className="fill-muted-foreground" fontSize="11">{second}s</text>)}
    </svg>
    </div>
    <p className="mb-2 text-xs text-muted-foreground sm:hidden">Scroll the heatmap horizontally to inspect later replay times.</p>
    <p className="text-xs text-muted-foreground">Blank ≠ zero liquidity. Stale, disconnected, empty and unknown-time books are omitted. Scale: 0–2,300 synthetic shares per cell. No future columns are drawn.</p>
  </section>;
}

function Ladder({ frame, state }: { frame: ReplayFrame; state: BookState }) {
  const { bids, asks } = frame.book;
  const largest = Math.max(1, ...bids.map(level => level.size), ...asks.map(level => level.size));
  return <section aria-labelledby="ladder-title" className="min-w-0 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="ladder-title" className="font-semibold">Depth ladder</h2>
      <span className="text-xs text-muted-foreground">{bids.length} bid / {asks.length} ask levels</span>
    </div>
    <p className="my-2 text-xs text-muted-foreground">ARCA fixture · sizes in synthetic shares · — = unavailable order count</p>
    {state !== "fresh" && <p className="mb-3 rounded border border-amber-400/40 p-2 text-xs text-amber-300" role="status">
      {state === "empty" ? "No displayed levels in this snapshot." : "Retained snapshot for inspection only. Current spread and imbalance are unavailable."}
    </p>}
    <table aria-label="Synthetic depth ladder" className={`w-full table-fixed text-right text-xs tabular-nums ${state === "fresh" ? "" : "opacity-60"}`}>
      <thead className="text-muted-foreground"><tr>
        <th className="py-2 font-normal">Orders</th><th className="font-normal text-emerald-400">Bid size</th><th className="font-normal">Bid $</th>
        <th className="font-normal">Ask $</th><th className="font-normal text-red-400">Ask size</th><th className="font-normal">Orders</th>
      </tr></thead>
      <tbody>{Array.from({ length: Math.max(bids.length, asks.length) }, (_, i) => {
        const bid = bids[i], ask = asks[i];
        return <tr key={i} className="border-t border-border/50">
          <td className="py-2 text-muted-foreground">{bid?.orders ?? "—"}</td>
          <td className="relative text-emerald-300"><span aria-hidden className="absolute inset-y-1 right-0 bg-emerald-400/15" style={{ width: `${(bid?.size ?? 0) / largest * 100}%` }} /><span className="relative">{bid ? quantity(bid.size) : "—"}</span></td>
          <td className="font-medium">{bid ? priceText(bid.priceCents) : "—"}</td>
          <td className="font-medium">{ask ? priceText(ask.priceCents) : "—"}</td>
          <td className="relative text-red-300"><span aria-hidden className="absolute inset-y-1 left-0 bg-red-400/15" style={{ width: `${(ask?.size ?? 0) / largest * 100}%` }} /><span className="relative">{ask ? quantity(ask.size) : "—"}</span></td>
          <td className="text-muted-foreground">{ask?.orders ?? "—"}</td>
        </tr>;
      })}</tbody>
    </table>
    <p className="mt-3 text-xs text-muted-foreground">Bars scale to the largest displayed level. Price-level aggregates, not individual orders or guaranteed executable liquidity.</p>
  </section>;
}

export default function Level2Lab() {
  const [offsetMs, setOffsetMs] = useState(0);
  const [playRequested, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const playing = playRequested && offsetMs < DURATION_MS;
  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now(), elapsed = (now - previous) * speed;
      previous = now;
      setOffsetMs(value => Math.min(DURATION_MS, value + elapsed));
    }, 100);
    const pauseWhenHidden = () => { if (document.hidden) setPlaying(false); };
    document.addEventListener("visibilitychange", pauseWhenHidden);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", pauseWhenHidden); };
  }, [playing, speed]);

  const frame = replayAt(offsetMs), state = bookState(frame, offsetMs), summary = depthSummary(frame, offsetMs);
  const age = bookAge(frame, offsetMs);
  const seek = (second: number) => { setPlaying(false); setOffsetMs(second * 1000); };
  return <div className="mx-auto max-w-6xl space-y-4" data-testid="level2-lab">
    <header className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Level 2 lab</h1>
      </div>
      <p className="text-sm text-muted-foreground">An isolated manual provider diagnostic and a separate synthetic replay. Neither updates saved trade metrics.</p>
    </header>

    <LiveDepthSession />

    <section aria-labelledby="synthetic-replay-title" className="space-y-4 rounded-lg border border-amber-400/20 p-4" data-testid="synthetic-replay">
    <header className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="synthetic-replay-title" className="text-lg font-semibold">Synthetic replay</h2>
        <span className="rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs font-semibold text-amber-300">SYNTHETIC REPLAY</span>
      </div>
      <p className="text-sm text-muted-foreground">US.NVDA · invented ARCA price-level book. No provider connection or real market data.</p>
      <p className="text-xs text-muted-foreground">One venue fixture, not consolidated depth or a TotalView/ArcaBook entitlement claim. Nasdaq coverage is unverified.</p>
    </header>

    <section aria-label="Replay controls" className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => { if (offsetMs >= DURATION_MS) { setOffsetMs(0); setPlaying(true); } else setPlaying(!playing); }}>{playing ? "Pause replay" : "Play replay"}</Button>
        <Button variant="outline" onClick={() => seek(Math.min(20, Math.floor(offsetMs / 1000) + 1))} disabled={offsetMs >= DURATION_MS}>Step 1s</Button>
        <Button variant="outline" onClick={() => seek(0)}>Reset</Button>
        <label className="ml-1 flex items-center gap-2 text-sm">Speed
          <select aria-label="Replay speed" className="h-10 rounded border bg-background px-2" value={speed} onChange={event => setSpeed(Number(event.target.value))}>
            {[1, 2, 4].map(value => <option key={value} value={value}>{value}×</option>)}
          </select>
        </label>
        <span className="text-xs text-muted-foreground" data-testid="replay-progress">{(offsetMs / 1000).toFixed(1)} / 20.0s · {playing ? "Playing" : offsetMs >= DURATION_MS ? "Ended" : "Paused"}</span>
      </div>
      <label className="mt-4 block text-xs text-muted-foreground" htmlFor="depth-replay-position">Replay position</label>
      <input id="depth-replay-position" aria-label="Replay position" type="range" min="0" max="20" step="1" value={Math.floor(offsetMs / 1000)} onChange={event => seek(Number(event.target.value))} className="mt-1 h-8 w-full accent-emerald-400" />
      <div className="flex flex-wrap gap-2 text-xs">
        {[{ second: 4, label: "Liquidity shift" }, { second: 8, label: "Stale" }, { second: 10, label: "Disconnect" }, { second: 13, label: "Empty" }, { second: 14, label: "Unknown time" }, { second: 16, label: "Recovery" }].map(({ second, label }) =>
          <Button key={second} variant="secondary" size="sm" onClick={() => seek(second)}>{label}</Button>)}
      </div>
    </section>

    <section aria-label="Book status" className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p data-testid="book-state" className={state === "fresh" ? "text-sm font-medium text-emerald-300" : "text-sm font-medium text-amber-300"}>{STATE_LABEL[state]}</p>
        <p className="text-xs text-muted-foreground">Source age: <span data-testid="book-age">{age === null ? "Unavailable" : `${(age / 1000).toFixed(1)}s`}</span> · replay clock</p>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">Invented session: Oct 9, 2026 · source <span data-testid="book-source-time">{frame.book.sourceOffsetMs === null ? "unavailable" : `${sourceTime(frame.book.sourceOffsetMs)} ET`}</span>. Fresh ≤ 2s on the replay clock; this is not measured provider latency.</p>
      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted-foreground">ARCA spread</dt><dd data-testid="book-spread" className="mt-1 font-semibold tabular-nums">{summary ? `$${priceText(summary.spreadCents)}` : "Unavailable"}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Top 5 bid shares</dt><dd data-testid="bid-total" className="mt-1 font-semibold tabular-nums text-emerald-300">{summary ? quantity(summary.bidSize) : "Unavailable"}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Top 5 ask shares</dt><dd data-testid="ask-total" className="mt-1 font-semibold tabular-nums text-red-300">{summary ? quantity(summary.askSize) : "Unavailable"}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Top 5 imbalance</dt><dd data-testid="book-imbalance" className="mt-1 font-semibold tabular-nums">{summary?.imbalance !== null && summary?.imbalance !== undefined ? `${summary.imbalance >= 0 ? "+" : ""}${(summary.imbalance * 100).toFixed(1)}%` : "Unavailable"}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">Imbalance = (bid size − ask size) / (bid size + ask size), nearest five prices per side. Positive means more displayed bid size; it is not a trading signal.</p>
    </section>
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.3fr)]">
      <Ladder frame={frame} state={state} />
      <Heatmap offsetMs={offsetMs} />
    </div>
    <p className="text-xs text-muted-foreground">This replay is memory-only, starts paused, stops at 20 seconds and pauses when this tab is hidden. It has no archive, recording or ML pipeline.</p>
    </section>
  </div>;
}
