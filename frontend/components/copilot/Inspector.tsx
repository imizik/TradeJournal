"use client";

import { useEffect, useState, type ReactNode } from "react";
import { getDeskTimeline, type DeskThreadRef, type DeskTimeline as Timeline, type DeskTimelineRow } from "@/lib/desk";
import { cn } from "@/lib/utils";

/*
 * The desk's timeline (docs/copilot-lab.md § The desk), folded under the cockpit centre's chart (``Cockpit.tsx``
 * ``CentreChart``; the chart itself is ``DeskChart.tsx``). Read-only: nothing here arms or sends.
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
const Quiet = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;
const failed = (failure: unknown) => failure instanceof Error ? failure.message : "Unavailable right now.";

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
