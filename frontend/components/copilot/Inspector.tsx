"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  DESK_MARKET, DESK_TIMEFRAMES, getDeskPicture, getDeskTimeline,
  type DeskTimeframe, type DeskThreadRef, type DeskTimeline as Timeline, type DeskTimelineRow,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

/*
 * The desk's chart and timeline (docs/copilot-lab.md § The desk), shown in the cockpit's centre (``Cockpit.tsx``
 * ``CentreChart``). Read-only: nothing here arms or sends.
 */

const NY = "America/New_York";
const nyDay = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: NY });
/** Today's rows by the New York clock, earlier ones by their day. */
const when = (seconds: number) => nyDay(seconds) === nyDay(Date.now() / 1000)
  ? new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: NY, hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
  : new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: NY, month: "short", day: "numeric" });

const KIND: Record<DeskTimelineRow["kind"], { label: string; dot: string }> = {
  alert: { label: "Alert", dot: "bg-primary" },
  time_stop: { label: "Time stop", dot: "bg-primary/50" },
  revisit: { label: "Revisit", dot: "bg-muted-foreground" },
  fill: { label: "Fill", dot: "bg-foreground" },
  thesis: { label: "Thesis watch", dot: "bg-foreground/60" },
  ping: { label: "Ping", dot: "bg-violet-400" },
  decision: { label: "Decision", dot: "bg-emerald-400" },
};
const REFRESH_MS = 60_000;

const Quiet = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;
const failed = (failure: unknown) => failure instanceof Error ? failure.message : "Unavailable right now.";

/** The server's picture (ping-picture renderer) of the thread's symbol, or the market's, on ``timeframe`` (today's
 * minutes when none). The last picture stays up while a newer one is read. */
function ChartTab({ id, refreshKey, alt, timeframe }: { id: string; refreshKey: number; alt: string; timeframe?: DeskTimeframe }) {
  const [shown, setShown] = useState<{ url: string } | { reason: string } | null>(null);
  const current = useRef<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskPicture(id, controller.signal, timeframe).then(result => {
      if (controller.signal.aborted) {
        if ("url" in result) URL.revokeObjectURL(result.url);
        return;
      }
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = "url" in result ? result.url : null;
      setShown(result);
    }).catch(failure => { if (!controller.signal.aborted) setShown({ reason: failed(failure) }); });
    return () => controller.abort();
  }, [id, refreshKey, timeframe]);
  useEffect(() => () => { if (current.current) URL.revokeObjectURL(current.current); }, []);
  if (!shown) return <Quiet>Reading today&apos;s chart…</Quiet>;
  if ("reason" in shown) return <Quiet>Chart unavailable: {shown.reason}</Quiet>;
  return (
    // An object URL of the server's PNG: next/image has nothing to optimise here.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={shown.url} width={720} height={360} className="h-auto w-full rounded border" alt={alt} />
  );
}

const Dot = ({ tone, children }: { tone: string; children: ReactNode }) => (
  <span><span aria-hidden className={cn("mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle", tone)} />{children}</span>
);
const SPAN: Record<DeskTimeframe, string> = { "2m": "today: minute bars", "15m": "recent sessions: 15-minute bars", "1D": "the last few months: daily bars" };

/** The thread's chart on 2m (today), 15m (recent sessions) or 1D (a few months), and what its dots are: the owner's
 * fills, the phone pings sent and Radar hits on the symbol today, so an alert can be judged against what price did
 * next. The dots and the plan's lines show on the intraday views. ``market`` (no thread): QQQ today with the owner's
 * fills and pings, read again each minute. ``extra`` sits at the end of the timeframe row (Open in Charts). */
export function ThreadChart({ thread, market = false, extra }: { thread?: DeskThreadRef; market?: boolean; extra?: ReactNode }) {
  const [timeframe, setTimeframe] = useState<DeskTimeframe>("2m");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!market) return;
    const timer = setInterval(() => { if (document.visibilityState === "visible") setTick(n => n + 1); }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [market]);
  if (market || !thread) {
    return (
      <div className="space-y-2">
        {extra && <div className="flex">{extra}</div>}
        <ChartTab id={DESK_MARKET} refreshKey={tick} alt="QQQ today: minute bars with your fills and the phone pings sent today" />
        <p aria-label="Legend" className="flex gap-3 text-xs text-muted-foreground"><Dot tone="bg-primary">your fills</Dot><Dot tone="bg-violet-400">pings</Dot></p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <div role="group" aria-label="Timeframe" className="flex gap-1">
          {DESK_TIMEFRAMES.map(item => (
            <button key={item} type="button" aria-pressed={timeframe === item} onClick={() => setTimeframe(item)}
              className={cn("min-h-9 rounded border px-2 text-xs tabular-nums sm:min-h-0 sm:py-0.5",
                timeframe === item ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {item}
            </button>
          ))}
        </div>
        {extra}
      </div>
      <ChartTab id={thread.id} refreshKey={thread.refreshKey} timeframe={timeframe}
        alt={`${thread.symbol} ${SPAN[timeframe]}${timeframe === "1D" ? "" : " with the plan's entry and invalidation lines, your fills, and today's pings and Radar hits"}`} />
      <p aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Dot tone="bg-primary">your fills</Dot>
        <Dot tone="bg-violet-400">pings</Dot>
        <Dot tone="bg-foreground/60">Radar</Dot>
        {timeframe === "1D" && <span>· marked on 2m and 15m</span>}
      </p>
    </div>
  );
}

/** What touched the thread, newest first, the New York time on the right and a dot by kind. */
export function DeskTimeline({ thread }: { thread: DeskThreadRef }) {
  const [read, setRead] = useState<{ data: Timeline } | { error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskTimeline(thread.id, controller.signal).then(data => { if (!controller.signal.aborted) setRead({ data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ error: failed(failure) }); });
    return () => controller.abort();
  }, [thread.id, thread.refreshKey]);
  if (!read) return <Quiet>Reading the timeline…</Quiet>;
  if ("error" in read) return <Quiet>Timeline unavailable: {read.error}</Quiet>;
  const { rows, unavailable, recent_days } = read.data;
  return (
    <div className="space-y-2">
      {rows.length ? (
        <ol aria-label="Timeline" className="space-y-2">
          {rows.map((row, i) => (
            <li key={`${row.kind}-${row.at}-${i}`} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", KIND[row.kind].dot)} />
              <span className="min-w-0 flex-1 break-words">
                <span className="sr-only">{KIND[row.kind].label}: </span>
                <span className="text-foreground">{row.text}</span>
                {row.detail && <span className="block text-xs text-muted-foreground">{row.detail}</span>}
              </span>
              <time dateTime={new Date(row.at * 1000).toISOString()} className="shrink-0 text-xs tabular-nums text-muted-foreground">{when(row.at)}</time>
            </li>
          ))}
        </ol>
      ) : <Quiet>Nothing has touched this thread in the last {recent_days} days.</Quiet>}
      {unavailable.length > 0 && <p className="text-xs text-muted-foreground">Could not read: {unavailable.join(", ")}.</p>}
    </div>
  );
}
