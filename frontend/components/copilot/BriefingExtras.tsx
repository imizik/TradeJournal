"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarCheck, Sparkles } from "lucide-react";
import { hhmm } from "@/components/copilot/SessionTape";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { HELD, clock, type Today } from "@/components/today/TodayView";
import { apiUrl } from "@/lib/api";
import type { DeskSession, DeskThread } from "@/lib/desk";

const BUTTON = "inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-8";

/** A tap that opens a symbol's desk view, as a ping's own link does. */
const symbolHref = (symbol: string) => `/copilot-lab?${new URLSearchParams({ symbol })}`;
const SUMMARY = "w-fit cursor-pointer list-none text-xs font-medium text-foreground hover:underline [&::-webkit-details-marker]:hidden";

/**
 * Now's "Today" section: today's phone pings (each with its time and words; a symbol opens its desk view), the pings
 * the notification policy held back (merged, quiet window or over the daily cap, one read of ``GET /today``), the Radar
 * events since the last Radar visit (``radar``, the thread list's rows, each opening on its decision), and today's
 * replay when a clip is kept. Every count opens its list. What matters right now? and Review my week (one turn each in
 * today's conversation, ``onWhatMatters``, ``onReviewWeek``) sit beside them.
 */
export default function BriefingExtras({ onReviewWeek, onWhatMatters, session, radar = [] }: {
  onReviewWeek(): void; onWhatMatters(): void; session: DeskSession | null; radar?: DeskThread[];
}) {
  const [body, setBody] = useState<Pick<Today, "day" | "held"> | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/today"), { cache: "no-store", signal: controller.signal })
      .then(r => (r.ok ? r.json() : null)).then(next => { if (next) setBody(next); })
      .catch(() => { /* Now stands without it */ });
    return () => controller.abort();
  }, []);
  const held = body?.held.state === "ok" && body.held.count > 0 ? body.held : null;
  const pings = [...(session?.events.filter(e => e.kind === "ping") ?? [])].sort((a, b) => b.at - a.at);
  const sent = Math.max(session?.pings?.sent ?? 0, pings.length);
  return (
    <section aria-label="Pings and Radar today" className="mb-4 space-y-2 rounded-lg border bg-card px-4 py-3 text-sm" data-testid="briefing-extras">
      <h2 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Pings and Radar today</h2>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        {sent > 0 ? (
          <details className="min-w-0 basis-full sm:basis-auto open:basis-full" data-testid="now-pings">
            <summary className={SUMMARY}><span className="tabular-nums">{sent}</span> ping{sent === 1 ? "" : "s"} sent ▾</summary>
            <ul className="mt-2 space-y-1">
              {pings.map((ping, i) => (
                <li key={`${ping.at}-${i}`} className="flex min-w-0 items-baseline gap-2 text-xs">
                  <span className="shrink-0 tabular-nums text-muted-foreground">{hhmm(ping.at)}</span>
                  {ping.symbol && <Link href={symbolHref(ping.symbol)} className="shrink-0 font-semibold text-foreground hover:underline">{ping.symbol}</Link>}
                  <span className="min-w-0 break-words text-muted-foreground">{ping.text}</span>
                </li>
              ))}
              {pings.length < sent && <li className="text-xs text-muted-foreground">{sent - pings.length} more not listed here.</li>}
            </ul>
          </details>
        ) : session && <span className="text-xs text-muted-foreground">No pings yet today.</span>}
        {radar.length > 0 && (
          <details className="min-w-0 basis-full sm:basis-auto open:basis-full" data-testid="briefing-radar-new">
            <summary className={SUMMARY}>{radar.length} new on Radar ▾</summary>
            <ul className="mt-2 space-y-1">
              {[...radar].sort((a, b) => (b.changedAt ?? 0) - (a.changedAt ?? 0)).map(row => (
                <li key={row.key} className="min-w-0">
                  {row.path ? (
                    <Link href={row.path} className="flex min-h-11 min-w-0 items-baseline gap-1.5 text-sm hover:underline sm:min-h-0">
                      <span className="shrink-0 font-semibold text-foreground">{row.symbol ?? "Radar"}</span>
                      <span className="min-w-0 truncate text-xs text-muted-foreground">{row.title}</span>
                    </Link>
                  ) : <span className="text-xs text-muted-foreground">{row.title}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
        {held && (
          <details className="min-w-0 basis-full sm:basis-auto open:basis-full">
            <summary className="w-fit cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              Held back · {held.count} ▾
            </summary>
            <ul className="mt-2 space-y-2">
              {held.rows.map((row, i) => (
                <li key={i} data-testid="briefing-held-row" className="min-w-0">
                  <p className="text-xs text-muted-foreground">{HELD[row.decision] ?? row.decision} · {row.kind} · {clock(row.at)}</p>
                  <p className="break-words text-sm text-foreground">{row.title}</p>
                  <p className="line-clamp-2 whitespace-pre-line break-words text-xs text-muted-foreground">{row.body}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onWhatMatters} className={BUTTON}
          title="One copilot turn across your open positions, armed watches and open questions, in today's conversation">
          <Sparkles size={14} aria-hidden />What matters right now?
        </button>
        <button type="button" onClick={onReviewWeek} className={BUTTON}
          title="One copilot turn reviewing your latest trading week: planned vs unplanned, follow-through, alerts and exits">
          <CalendarCheck size={14} aria-hidden />Review my week
        </button>
        {body && <WatchDayLink from={body.day} className={BUTTON} />}
      </div>
    </section>
  );
}
