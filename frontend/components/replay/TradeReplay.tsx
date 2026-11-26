"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { Pause, Play, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { DashboardCard } from "@/components/dashboard/DashboardCard";
import { fetchTradeReplay, money, peakThrough, quoted, replayEvents, words, type ReplayEvent, type TradeReplay as Replay } from "@/lib/tradeReplay";

// The trade page's Replay card: a closed trade drawn on its underlying's minute chart, scrubbed or played bar by bar,
// with every fill, the pings that fired, the leak rules' cut, the Opus tag and the P&L at each bar.

const TradeReplayChart = dynamic(() => import("./TradeReplayChart"), { ssr: false, loading: () => <div className="h-64 sm:h-80" /> });

const SPEEDS = [{ label: "1×", ms: 250 }, { label: "4×", ms: 60 }, { label: "16×", ms: 16 }] as const;
const clock = (time: number, multiDay: boolean) => `${new Date(time * 1000).toLocaleString("en-US", { timeZone: "America/New_York",
  ...(multiDay ? { month: "short", day: "numeric" } : {}), hour: "numeric", minute: "2-digit" })} ET`;
const DOT: Record<ReplayEvent["tone"], string> = { buy: "bg-emerald-400", sell: "bg-red-400", ping: "bg-amber-300", muted: "bg-zinc-500", rule: "bg-violet-400" };
const tone = (value: number | null) => value == null || value === 0 ? "text-muted-foreground" : value > 0 ? "text-emerald-400" : "text-red-400";
const button = "inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border text-foreground hover:bg-muted disabled:opacity-40 sm:min-h-9 sm:min-w-9";

function Tag({ tag }: { tag: NonNullable<Replay["tag"]> }) {
  const mistakes = tag.mistakes.filter(m => m !== tag.primary_mistake && m !== "none");
  return <div data-testid="trade-replay-tag" className="mb-3 space-y-1.5 text-sm">
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="inline-flex min-h-[22px] items-center rounded-md bg-secondary px-2 text-[11.5px] font-medium">Setup: {words(tag.setup)}</span>
      {tag.primary_mistake !== "none" && <span className="inline-flex min-h-[22px] items-center rounded-md bg-red-500/15 px-2 text-[11.5px] font-medium text-red-300">Mistake: {words(tag.primary_mistake)}</span>}
      {mistakes.map(m => <span key={m} className="inline-flex min-h-[22px] items-center rounded-md bg-secondary px-2 text-[11.5px] text-muted-foreground">{words(m)}</span>)}
      {(tag.broke_cut_rule || tag.rule_broken_computed) && <span className="inline-flex min-h-[22px] items-center rounded-md bg-violet-500/20 px-2 text-[11.5px] font-medium text-violet-200">Broke the cut rule</span>}
      {tag.grade && <span className="inline-flex min-h-[22px] items-center rounded-md bg-secondary px-2 text-[11.5px] font-medium">Grade {tag.grade}</span>}
    </div>
    {tag.rationale && <p className="text-xs text-muted-foreground">{tag.rationale} <span className="text-muted-foreground/70">(Opus, tagged after the fact)</span></p>}
  </div>;
}

export default function TradeReplay({ tradeId }: { tradeId: string }) {
  const [replay, setReplay] = useState<Replay | null>(null);
  const [failed, setFailed] = useState(false);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    fetchTradeReplay(tradeId, control.signal).then(body => {
      setReplay(body);
      const bars = body.bars ?? [];
      // Start on the first fill's bar, with the setup before it on screen; play forward from there.
      const first = replayEvents(body).find(e => e.kind === "fill");
      setIndex(first ? first.index : Math.max(0, bars.length - 1));
    }).catch(error => { if (!control.signal.aborted) { console.warn("Replay", error); setFailed(true); } });
    return () => control.abort();
  }, [tradeId]);

  const bars = useMemo(() => replay?.bars ?? [], [replay]);
  const events = useMemo(() => replay ? replayEvents(replay) : [], [replay]);
  const last = bars.length - 1;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setIndex(i => {
      if (i >= last) { setPlaying(false); return i; }
      return i + 1;
    }), SPEEDS[speed].ms);
    return () => window.clearInterval(timer);
  }, [playing, speed, last]);

  if (failed) return <DashboardCard title="Replay"><p className="text-sm text-muted-foreground">The replay could not be loaded. Reload to try again.</p></DashboardCard>;
  if (!replay) return <DashboardCard title="Replay"><p className="text-sm text-muted-foreground">Loading the replay…</p></DashboardCard>;
  if (replay.state === "open") return null;
  if (replay.state !== "ok" || !bars.length) return <DashboardCard title="Replay"><p className="text-sm text-muted-foreground">{replay.reason ?? "No bars to replay."}</p></DashboardCard>;

  const multiplier = replay.multiplier ?? 1;
  const multiDay = new Set(bars.map(b => new Date(b.time * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York" }))).size > 1;
  const bar = bars[Math.min(index, last)];
  const option = (replay.option_bars ?? []).filter(o => o.time <= bar.time).at(-1);
  const vsVwap = bar.vwap ? (bar.close - bar.vwap) / bar.vwap : null;
  const peak = peakThrough(bars, index);
  const here = events.filter(e => e.index === index);
  const previous = [...events].reverse().find(e => e.index < index);
  const next = events.find(e => e.index > index);
  const go = (to: number) => { setPlaying(false); setIndex(Math.max(0, Math.min(last, to))); };
  const unit = replay.instrument_type === "stock" ? (bar.held === 1 ? "share" : "shares") : (bar.held === 1 ? "contract" : "contracts");

  return <DashboardCard id="replay" title="Replay" action={<span className="text-xs text-muted-foreground">{replay.interval_minutes === 1 ? "1-minute" : `${replay.interval_minutes}-minute`} bars · {replay.ticker}</span>}>
    <div data-testid="trade-replay">
      {replay.tag && <Tag tag={replay.tag} />}
      <TradeReplayChart replay={replay} events={events} index={index} />

      <div className="mt-3 flex items-center gap-1.5">
        <button type="button" className={button} aria-label="Back to the first bar" onClick={() => go(0)} disabled={index === 0}><SkipBack size={15} /></button>
        <button type="button" className={button} aria-label="Previous event" onClick={() => previous && go(previous.index)} disabled={!previous}><StepBack size={15} /></button>
        <button type="button" className={`${button} flex-1 gap-1.5 px-3 text-sm font-medium sm:flex-none`} aria-label={playing ? "Pause" : "Play"}
          onClick={() => { if (index >= last) setIndex(0); setPlaying(p => !p); }}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause" : "Play"}</button>
        <button type="button" className={button} aria-label="Next event" onClick={() => next && go(next.index)} disabled={!next}><StepForward size={15} /></button>
        <button type="button" className={button} aria-label="To the last bar" onClick={() => go(last)} disabled={index === last}><SkipForward size={15} /></button>
        <button type="button" className={`${button} px-2 text-xs`} aria-label="Playback speed" onClick={() => setSpeed(s => (s + 1) % SPEEDS.length)}>{SPEEDS[speed].label}</button>
      </div>
      <input type="range" min={0} max={last} value={index} aria-label="Replay position" data-testid="trade-replay-scrub"
        onChange={e => { setPlaying(false); setIndex(Number(e.target.value)); }}
        className="mt-2 h-8 w-full cursor-pointer accent-violet-400" />

      <div data-testid="trade-replay-readout" className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-secondary px-3 py-2 text-sm tabular-nums sm:grid-cols-4">
        <div><p className="text-xs text-muted-foreground">Time</p><p className="font-medium">{clock(bar.time, multiDay)}</p></div>
        <div><p className="text-xs text-muted-foreground">{replay.ticker}</p><p className="font-medium">${bar.close.toFixed(2)}
          {vsVwap != null && <span className="ml-1 text-xs text-muted-foreground">{Math.abs(vsVwap * 100).toFixed(1)}% {vsVwap >= 0 ? "above" : "below"} VWAP</span>}</p></div>
        <div><p className="text-xs text-muted-foreground">Position</p><p className="font-medium">{bar.held > 0
          ? <>{bar.held} {unit} @ {quoted(bar.avg_cost ?? 0, multiplier)}{option && <span className="ml-1 text-xs text-muted-foreground">now ${option.close.toFixed(2)}</span>}</>
          : bar.pnl == null ? "Not in yet" : "Flat"}</p></div>
        <div><p className="text-xs text-muted-foreground">P&L {peak != null && <span>(best {money(peak)})</span>}</p>
          <p className={`font-semibold ${tone(bar.pnl)}`}>{bar.pnl == null ? (bar.held > 0 ? "No price" : "–") : money(bar.pnl)}</p></div>
      </div>
      {here.length > 0 && <ul aria-label="At this bar" className="mt-2 space-y-1 text-sm">
        {here.map((e, i) => <li key={i} className="flex items-start gap-2"><span className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[e.tone]}`} />{e.label}</li>)}
      </ul>}
      {replay.option_note && <p className="mt-2 text-xs text-muted-foreground">{replay.option_note}</p>}

      <details className="mt-3 text-sm" open>
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">What happened ({events.length})</summary>
        <ol className="mt-1 divide-y">
          {events.map((e, i) => <li key={i}>
            <button type="button" onClick={() => go(e.index)} className={`flex min-h-11 w-full items-start gap-2 py-2 text-left hover:bg-muted/50 sm:min-h-0 ${e.index > index ? "opacity-45" : ""} ${e.index === index ? "font-medium" : ""}`}>
              <span className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[e.tone]}`} />
              <span className={`${multiDay ? "w-28" : "w-[4.5rem]"} shrink-0 tabular-nums text-xs leading-5 text-muted-foreground`}>{clock(e.time, multiDay).replace(" ET", "")}</span>
              <span>{e.label}</span>
            </button>
          </li>)}
        </ol>
        <p className="mt-2 text-xs text-muted-foreground">P&L is each bar&apos;s last trade, not a price you could surely have sold at.{replay.cut_line && <> The cut line is 30% under your first buy.</>}</p>
      </details>
    </div>
  </DashboardCard>;
}
