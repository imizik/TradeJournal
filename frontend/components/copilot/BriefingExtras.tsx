"use client";

import { useEffect, useState } from "react";
import WatchDayLink from "@/components/replay/WatchDayLink";
import { HELD, clock, type Today } from "@/components/today/TodayView";
import { apiUrl } from "@/lib/api";

/**
 * What the Today screen showed that the Briefing did not, now that the desk is home: pings the notification policy held
 * back today (merged, quiet window or over the daily cap), behind a disclosure, and today's replay when a clip is kept.
 * One read of ``GET /today`` when the Briefing opens.
 */
export default function BriefingExtras() {
  const [body, setBody] = useState<Pick<Today, "day" | "held"> | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/today"), { cache: "no-store", signal: controller.signal })
      .then(r => (r.ok ? r.json() : null)).then(next => { if (next) setBody(next); })
      .catch(() => { /* the Briefing stands without it */ });
    return () => controller.abort();
  }, []);
  if (!body) return null;
  const held = body.held.state === "ok" && body.held.count > 0 ? body.held : null;
  return (
    <div className="mb-4 flex flex-wrap items-start gap-x-4 gap-y-2 border-b pb-4 text-sm empty:hidden" data-testid="briefing-extras">
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
      <WatchDayLink from={body.day} className="ml-auto inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-8" />
    </div>
  );
}
