"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { apngFrames } from "@/lib/apng";

// Watch your day (backend/app/routers/replay.py): each symbol's clip is an animated PNG cut into frames here and drawn
// to a canvas, so the range input under it scrubs to any frame. Frame i shows the day before times[i] (epoch seconds).
type Clip = { symbol: string; frames: number; fps: number; width: number; height: number; bytes: number; times: number[]; path: string };
type Day = { date: string; fills: number; pings: number; clips: Clip[] };

const clock = (stamp: number) => new Date(stamp * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const dayLabel = (date: string) => new Date(`${date}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

function ReplayClip({ clip }: { clip: Clip }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [frames, setFrames] = useState<Blob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(clip.frames - 1);
  const [playing, setPlaying] = useState(false);
  const wanted = useRef(index);

  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl(clip.path), { cache: "no-store", signal: controller.signal })
      .then(r => r.ok ? r.arrayBuffer() : Promise.reject(new Error(`Request failed (${r.status}).`)))
      .then(buffer => setFrames(apngFrames(buffer)))
      .catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The clip could not load."); });
    return () => controller.abort();
  }, [clip.path]);

  // Draw the wanted frame; a slower decode that finishes after a newer one is dropped.
  useEffect(() => {
    wanted.current = index;
    const blob = frames?.[Math.min(index, frames.length - 1)];
    if (!blob) return;
    let cancelled = false;
    createImageBitmap(blob).then(bitmap => {
      if (!cancelled && wanted.current === index) canvas.current?.getContext("2d")?.drawImage(bitmap, 0, 0, clip.width, clip.height);
      bitmap.close();
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [frames, index, clip.width, clip.height]);

  useEffect(() => {
    if (!playing || !frames) return;
    const timer = setInterval(() => setIndex(i => {
      if (i >= frames.length - 1) { setPlaying(false); return i; }
      return i + 1;
    }), 1000 / clip.fps);
    return () => clearInterval(timer);
  }, [playing, frames, clip.fps]);

  const last = (frames?.length ?? clip.frames) - 1;
  const play = () => {
    if (index >= last) setIndex(0);
    setPlaying(p => !p);
  };
  const at = clip.times[Math.min(index, clip.times.length - 1)];

  return <section aria-label={`${clip.symbol} replay`} data-testid="replay-clip" className="min-w-0 rounded-lg border bg-card">
    <h2 className="flex items-baseline gap-2 px-4 py-3 text-sm font-semibold">
      {clip.symbol}
      <span className="ml-auto text-xs font-normal tabular-nums text-muted-foreground" data-testid="replay-clock">{at ? `${clock(at)} ET` : ""}</span>
    </h2>
    <canvas ref={canvas} width={clip.width} height={clip.height} role="img" aria-label={`${clip.symbol} at ${at ? clock(at) : ""}`}
      className="block h-auto w-full bg-[#12151c]" style={{ aspectRatio: `${clip.width} / ${clip.height}` }} />
    {error ? <p role="status" className="px-4 py-3 text-sm text-amber-300">This clip could not load: {error}</p>
      : <div className="flex items-center gap-3 px-3 py-2">
        <button type="button" onClick={play} disabled={!frames} aria-label={playing ? `Pause ${clip.symbol}` : `Play ${clip.symbol}`}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md border hover:bg-muted/30 disabled:opacity-50">
          {playing ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
        </button>
        <input type="range" min={0} max={last} step={1} value={index} disabled={!frames} aria-label={`Scrub ${clip.symbol}`}
          onChange={e => { setPlaying(false); setIndex(Number(e.target.value)); }}
          className="h-11 min-w-0 flex-1 accent-sky-400" />
      </div>}
  </section>;
}

export default function ReplayView({ date, first = null }: { date: string; first?: string | null }) {
  const [day, setDay] = useState<Day | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl(`/replay/${date}`), { cache: "no-store", signal: controller.signal })
      .then(r => r.status === 404 ? Promise.reject(new Error("No replay for this day: clips are built at the close on days you trade and kept 14 days."))
        : r.ok ? r.json() : Promise.reject(new Error(`Request failed (${r.status}).`)))
      .then((next: Day) => { setDay(next); setError(null); })
      .catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The replay is unavailable."); });
    return () => controller.abort();
  }, [date]);

  const clips = day ? [...day.clips].sort((a, b) => Number(b.symbol === first) - Number(a.symbol === first)) : [];
  return <div className="mx-auto max-w-2xl space-y-3" data-testid="replay">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 className="text-lg font-semibold text-foreground">Watch your day</h1>
      <p className="text-xs text-muted-foreground">{dayLabel(date)}{day ? ` · ${plural(day.fills, "fill")}, ${plural(day.pings, "ping")}` : ""}</p>
    </div>
    {error ? <p role="status" className="text-sm text-amber-300">{error}</p>
      : !day ? <p role="status" className="text-sm text-muted-foreground">Loading the day…</p>
      : clips.map(clip => <ReplayClip key={clip.symbol} clip={clip} />)}
  </div>;
}
