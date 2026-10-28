"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  getDeskHistory, getDeskPicture, getDeskTimeline,
  type ContextTab, type DeskHistory, type DeskThreadRef, type DeskTimeline, type DeskTimelineRow,
} from "@/lib/desk";
import { cn } from "@/lib/utils";

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
  thesis: { label: "Thesis watch", dot: "bg-sky-400" },
  ping: { label: "Ping", dot: "bg-violet-400" },
  decision: { label: "Decision", dot: "bg-emerald-400" },
};
const TABS: { id: ContextTab; label: string }[] = [{ id: "chart", label: "Chart" }, { id: "timeline", label: "Timeline" }, { id: "history", label: "Your history" }];
const MAX_TILES = 40;

const Quiet = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;
const failed = (failure: unknown) => failure instanceof Error ? failure.message : "Unavailable right now.";

/** Today's minute bars with the plan's levels and the owner's fills, drawn by the server's ping-picture renderer.
 * The last picture stays up while a newer one is read. */
function ChartTab({ thread }: { thread: DeskThreadRef }) {
  const [shown, setShown] = useState<{ url: string } | { reason: string } | null>(null);
  const current = useRef<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskPicture(thread.id, controller.signal).then(result => {
      if (controller.signal.aborted) {
        if ("url" in result) URL.revokeObjectURL(result.url);
        return;
      }
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = "url" in result ? result.url : null;
      setShown(result);
    }).catch(failure => { if (!controller.signal.aborted) setShown({ reason: failed(failure) }); });
    return () => controller.abort();
  }, [thread.id, thread.refreshKey]);
  useEffect(() => () => { if (current.current) URL.revokeObjectURL(current.current); }, []);
  if (!shown) return <Quiet>Reading today&apos;s chart…</Quiet>;
  if ("reason" in shown) return <Quiet>Chart unavailable: {shown.reason}</Quiet>;
  return (
    // An object URL of the server's PNG: next/image has nothing to optimise here.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={shown.url} width={720} height={360} className="h-auto w-full rounded border"
      alt={`${thread.symbol} today: minute bars with the plan's entry and invalidation lines and your fills`} />
  );
}

/** What touched the thread, newest first, the New York time on the right and a dot by kind. */
function TimelineTab({ thread }: { thread: DeskThreadRef }) {
  const [read, setRead] = useState<{ data: DeskTimeline } | { error: string } | null>(null);
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

/** The owner's own record at the plan's invalidation: a tile per past trade that crossed it while held, won or not,
 * and the server's one sentence from those counts. */
function HistoryTab({ thread }: { thread: DeskThreadRef }) {
  const [read, setRead] = useState<{ data: DeskHistory } | { error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getDeskHistory(thread.id, controller.signal).then(data => { if (!controller.signal.aborted) setRead({ data }); })
      .catch(failure => { if (!controller.signal.aborted) setRead({ error: failed(failure) }); });
    return () => controller.abort();
  }, [thread.id, thread.refreshKey]);
  if (!read) return <Quiet>Reading your history…</Quiet>;
  if ("error" in read) return <Quiet>Your history is unavailable: {read.error}</Quiet>;
  const data = read.data;
  if (data.state !== "ok") return <Quiet>{data.reason}</Quiet>;
  const tiles = [...Array(data.won).fill("won"), ...Array(data.not_won).fill("did not win")] as string[];
  return (
    <div className="space-y-2 text-sm">
      {tiles.length > 0 && (
        <div role="img" aria-label={`${data.won} won, ${data.not_won} did not`} className="flex flex-wrap items-center gap-1">
          {tiles.slice(0, MAX_TILES).map((tile, i) => (
            <span key={i} title={tile} className={cn("h-3 w-3 rounded-sm", tile === "won" ? "bg-emerald-400/80" : "bg-rose-400/80")} />
          ))}
          {tiles.length > MAX_TILES && <span className="text-xs tabular-nums text-muted-foreground">+{tiles.length - MAX_TILES}</span>}
        </div>
      )}
      <p className="text-foreground">{data.sentence}</p>
      <p className="text-xs text-muted-foreground">
        At <span className="tabular-nums">{data.level}</span>, <span className="tabular-nums">{Math.abs(data.distance_pct).toFixed(1)}%</span> {data.side} the
        {data.entry_from === "planned" ? " planned entry " : " price "}<span className="tabular-nums">{data.entry}</span>, over the last {data.window_days} days.
        {" "}Evidence to weigh, not a rule.{data.simulated ? " Simulated." : ""}
      </p>
    </div>
  );
}

/** The desk's Context pane for the open thread: today's chart first, then its timeline and the owner's history at its
 * invalidation, each read only when its tab opens. Read-only: nothing here arms or sends. */
export default function Inspector({ thread }: { thread: DeskThreadRef | null }) {
  const [tab, setTab] = useState<ContextTab>("chart");
  if (!thread) return <Quiet>Open a thread to see its chart, timeline and your history here.</Quiet>;
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-semibold text-foreground">{thread.symbol ?? "Across everything"}</span>
        {thread.symbol && <span className="text-xs text-muted-foreground">today</span>}
        {thread.symbol && <Link href={`/charts?symbol=${encodeURIComponent(thread.symbol)}`} className="ml-auto text-xs text-muted-foreground hover:text-primary">Open in Charts →</Link>}
      </div>
      <div role="tablist" aria-label="Context" className="flex gap-3 border-b text-xs">
        {TABS.map(item => (
          <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}
            className={cn("-mb-px min-h-9 border-b-2 pb-1 sm:min-h-0", tab === item.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {item.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={TABS.find(item => item.id === tab)!.label}>
        {tab === "chart" ? <ChartTab key={thread.id} thread={thread} />
          : tab === "timeline" ? <TimelineTab key={thread.id} thread={thread} />
            : <HistoryTab key={thread.id} thread={thread} />}
      </div>
    </div>
  );
}
