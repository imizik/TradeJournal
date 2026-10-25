"use client";

import Link from "next/link";
import { CalendarCheck } from "lucide-react";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";

export const WEEK_REVIEW_CONTEXT = "Review my week";

/** The lab's deep link for a week review; ``monday`` names a past week, otherwise the copilot reads the latest one. */
export const weekReviewHref = (monday?: string) =>
  `/copilot-lab?${new URLSearchParams({ context: monday ? `${WEEK_REVIEW_CONTEXT} of ${monday}` : WEEK_REVIEW_CONTEXT })}`;

const BUTTON = "inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-sky-500/60 px-3 text-xs font-medium text-sky-200 hover:bg-sky-500/15 sm:min-h-9";

/**
 * "Review my week": opens the Copilot Lab with "Review my week" in the message box, so one Send gets the weekly review
 * (planned vs unplanned, follow-through, alerts, habits, best and worst exits). Owner-only, and nothing while the lab is off.
 */
export default function ReviewMyWeek({ monday, className }: { monday?: string; className?: string }) {
  const on = useCopilotOn();
  if (!on) return null;
  return <Link href={weekReviewHref(monday)} className={className ?? BUTTON}
    title="Open the copilot with a review of your trading week. Nothing is sent until you press Send.">
    <CalendarCheck size={14} aria-hidden />Review my week
  </Link>;
}
