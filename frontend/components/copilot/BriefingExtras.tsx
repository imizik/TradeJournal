"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarCheck, Sparkles } from "lucide-react";
import { BriefingToAnswer } from "@/components/copilot/ProofAnswers";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { HELD, clock, type Today } from "@/components/today/TodayView";
import { apiUrl } from "@/lib/api";
import type { DeskSession, DeskThread } from "@/lib/desk";

const BUTTON = "inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-8";

/**
 * What the Today screen showed that the Briefing did not, now that the desk is home: pings the notification policy held
 * back today (merged, quiet window or over the daily cap), behind a disclosure, and today's replay when a clip is kept.
 * One read of ``GET /today`` when the Briefing opens. What matters right now? and Review my week (one turn each,
 * ``onWhatMatters``, ``onReviewWeek``) sit beside them. First,
 * the alerts and Radar hits still waiting on an answer for /proof (the session read's ``to_answer``), answered in place,
 * then the Radar events since the last Radar visit (``radar``, the thread list's rows), each opening on its decision.
 */
export default function BriefingExtras({ onReviewWeek, onWhatMatters, toAnswer, radar = [] }: {
  onReviewWeek(): void; onWhatMatters(): void; toAnswer?: DeskSession["to_answer"]; radar?: DeskThread[];
}) {
  const [body, setBody] = useState<Pick<Today, "day" | "held"> | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/today"), { cache: "no-store", signal: controller.signal })
      .then(r => (r.ok ? r.json() : null)).then(next => { if (next) setBody(next); })
      .catch(() => { /* the Briefing stands without it */ });
    return () => controller.abort();
  }, []);
  const held = body?.held.state === "ok" && body.held.count > 0 ? body.held : null;
  return (
    <div className="mb-4 flex flex-wrap items-start gap-x-4 gap-y-2 border-b pb-4 text-sm" data-testid="briefing-extras">
      <BriefingToAnswer toAnswer={toAnswer} />
      {radar.length > 0 && (
        <details className="min-w-0 basis-full sm:basis-auto open:basis-full" data-testid="briefing-radar-new">
          <summary className="w-fit cursor-pointer list-none text-xs font-medium text-foreground hover:underline [&::-webkit-details-marker]:hidden">
            {radar.length} new on Radar ▾
          </summary>
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
        <details className="min-w-0 flex-1">
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
      <div className="ml-auto flex flex-wrap gap-2">
        <button type="button" onClick={onWhatMatters} className={BUTTON}
          title="One copilot turn across your open positions, armed watches and open investigations">
          <Sparkles size={14} aria-hidden />What matters right now?
        </button>
        <button type="button" onClick={onReviewWeek} className={BUTTON}
          title="One copilot turn reviewing your latest trading week: planned vs unplanned, follow-through, alerts and exits">
          <CalendarCheck size={14} aria-hidden />Review my week
        </button>
        {body && <WatchDayLink from={body.day} className={BUTTON} />}
      </div>
    </div>
  );
}
