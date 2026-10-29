"use client";

import Link from "next/link";
import type { WeekLessons } from "@/lib/copilot";

const SAID: Record<string, string> = { yes: "Followed", partly: "Partly", no: "Didn't follow" };

/** Review my week's "Your exit lessons this week": each answered exit review (``get_week_review``'s ``lessons``) on one
 * line, the owner's own words, opening the plan's thread (its symbol in the simulated fixture, which has none). */
export default function ExitLessons({ lessons }: { lessons: WeekLessons }) {
  if (!lessons.rows.length) return null;
  return (
    <section aria-label="Your exit lessons this week" data-testid="week-exit-lessons" className="mt-3 rounded-lg border bg-card p-3">
      <p className="text-sm font-medium text-foreground">
        Your exit lessons this week
        <span className="font-normal text-muted-foreground">
          {" "}· {lessons.answered} of {lessons.exited} exit{lessons.exited === 1 ? "" : "s"} reviewed{lessons.simulated ? " · simulated" : ""}
        </span>
      </p>
      <ul className="mt-1.5 divide-y">
        {lessons.rows.map((row, i) => (
          <li key={`${row.symbol}-${i}`}>
            <Link href={row.thread ? `/copilot-lab?investigation=${row.thread}` : `/copilot-lab?${new URLSearchParams({ symbol: row.symbol })}`}
              title={row.lesson}
              className="flex min-h-11 items-center gap-2 py-1 text-sm hover:text-foreground sm:min-h-9">
              <span className="w-12 shrink-0 font-medium text-foreground">{row.symbol}</span>
              {row.followed && <span className="shrink-0 text-xs text-muted-foreground">{SAID[row.followed]}</span>}
              <span className="min-w-0 flex-1 truncate text-muted-foreground">“{row.lesson}”</span>
              <span aria-hidden className="shrink-0 text-muted-foreground">›</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
