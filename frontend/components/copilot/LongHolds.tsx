"use client";

import Link from "next/link";
import type { WeekLongHolds } from "@/lib/copilot";

/** Review my week's "Your long holds": each open position set to a long hold (``get_week_review``'s ``long_holds``) on
 * one line, days held and the plan's thesis in the owner's words, with "Still the thesis?" opening the plan's thread (its
 * symbol without one). The desk never asks about these day to day; this is their weekly look. */
export default function LongHolds({ holds }: { holds: WeekLongHolds }) {
  if (!holds.rows.length) return null;
  return (
    <section aria-label="Your long holds" data-testid="week-long-holds" className="mt-3 rounded-lg border bg-card p-3">
      <p className="text-sm font-medium text-foreground">
        Your long holds
        <span className="font-normal text-muted-foreground">
          {" "}· {holds.rows.length} held, not asked about day to day{holds.simulated ? " · simulated" : ""}
        </span>
      </p>
      <ul className="mt-1.5 divide-y">
        {holds.rows.map((row, i) => (
          <li key={`${row.symbol}-${i}`}>
            <Link href={row.thread ? `/copilot-lab?investigation=${row.thread}` : `/copilot-lab?${new URLSearchParams({ symbol: row.symbol })}`}
              title={row.thesis ?? row.contract}
              className="flex min-h-11 flex-wrap items-center gap-x-2 py-1 text-sm hover:text-foreground sm:min-h-9 sm:flex-nowrap">
              <span className="w-12 shrink-0 font-medium text-foreground">{row.symbol}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{row.days_held}d</span>
              {/* On a phone the thesis takes its own line, so the owner's words stay readable. */}
              <span className="order-last line-clamp-2 basis-full text-muted-foreground sm:order-none sm:line-clamp-1 sm:min-w-0 sm:flex-1 sm:basis-0">
                {row.thesis ? `“${row.thesis}”` : `${row.contract} · no plan`}
              </span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">Still the thesis? ›</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
