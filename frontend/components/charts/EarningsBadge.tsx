"use client";

import { useClock } from "@/lib/chartStore";
import { earningsBadge, eventDay } from "@/lib/symbolInfo";
import type { Earnings } from "@/lib/symbolInfo";

/**
 * "Earnings in 5 d · est." in a chart's header, from the report day back to 14
 * days before it (T1.4, C2.5). It reads the clock itself, so New York's
 * midnight moves it without re-rendering the chart. A smaller chart, and a
 * phone, show the short form ("E 5 d?"); the full sentence is on hover.
 */
export default function EarningsBadge({ earnings, compact = false, className = "" }: { earnings?: Earnings | null; compact?: boolean; className?: string }) {
  const next = earnings?.next;
  const text = useClock((now) => earningsBadge(next, now * 1000));
  if (!text || !next || !earnings) return null;
  const estimated = next.status === "estimated";
  const title = `${next.label} earnings ${eventDay(next.date)}: ${estimated ? "Tradier's estimate; the company has not confirmed it" : "confirmed"}. Time of day not published. ${earnings.source}.`;
  const short = text.replace("Earnings in ", "E ").replace("Earnings today", "E today").replace("Earnings tomorrow", "E 1 d").replace(" · est.", "?");
  return <span role="note" aria-label={text} title={title}
    className={`${className} shrink-0 whitespace-nowrap rounded border bg-[#10151e]/90 px-1.5 py-0.5 font-mono text-[10px] text-violet-200 ${estimated ? "border-dashed border-violet-400/50" : "border-violet-400/60"}`}>
    {compact ? short : <><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{text}</span></>}</span>;
}
