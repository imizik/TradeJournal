"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarCheck } from "lucide-react";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { getPractice, practiceLine } from "@/lib/copilot";
import { cn } from "@/lib/utils";

export const WEEK_REVIEW_CONTEXT = "Review my week";

/** The lab's deep link for a week review; ``monday`` names a past week, otherwise the copilot reads the latest one. */
export const weekReviewHref = (monday?: string) =>
  `/copilot-lab?${new URLSearchParams({ context: monday ? `${WEEK_REVIEW_CONTEXT} of ${monday}` : WEEK_REVIEW_CONTEXT })}`;

/** The active practice goal's line ("Practicing: exit at my invalidation · 2 of 3 this week"), or null. One read when ``on``. */
export function usePracticeLine(on: boolean): string | null {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    getPractice(controller.signal).then(now => setLine(practiceLine(now))).catch(() => { /* the line is extra */ });
    return () => controller.abort();
  }, [on]);
  return line;
}

/** The lab home's line under Review my week; nothing while no goal is active. */
export function PracticeLine({ className }: { className?: string }) {
  const line = usePracticeLine(true);
  return line ? <p className={className ?? "text-xs text-sky-200/80"}>{line}</p> : null;
}

const BUTTON = "inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-sky-500/60 px-3 text-xs font-medium text-sky-200 hover:bg-sky-500/15 sm:min-h-9";

/**
 * "Review my week": opens the Copilot Lab with "Review my week" in the message box, so one Send gets the weekly review
 * (planned vs unplanned, follow-through, alerts, habits, best and worst exits). Owner-only, and nothing while the lab is off.
 */
export default function ReviewMyWeek({ monday, className, practice = false }: { monday?: string; className?: string; practice?: boolean }) {
  const on = useCopilotOn();
  const line = usePracticeLine(on && practice);
  if (!on) return null;
  // With the practice line the button may wrap on a phone instead of pushing the header wider than the screen.
  return <Link href={weekReviewHref(monday)} className={cn(className ?? BUTTON, line && "min-w-0 shrink py-1")}
    title="Open the copilot with a review of your trading week. Nothing is sent until you press Send.">
    <CalendarCheck size={14} aria-hidden />
    {line ? <span className="flex flex-col items-start leading-tight">Review my week<span className="whitespace-normal text-left text-[11px] font-normal text-sky-200/80">{line}</span></span>
      : "Review my week"}
  </Link>;
}
