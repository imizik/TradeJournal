"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Crosshair } from "lucide-react";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { CONTEXT_MAX, copilotLabHref, type LinkOrigin } from "@/lib/copilot";
import type { OriginKind } from "@/lib/captures";

/** Primary-styled: the easiest way into the copilot, before an entry. Thumb-sized on a phone unless a caller sizes it for a toolbar. */
export const PLAN_BUTTON = "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-sky-500 px-3 text-xs font-medium text-white hover:bg-sky-400";

/** "Plan a trade: " and what the page knows, cut to the deep link's limit. With nothing known, the owner names the ticker. */
export const planContext = (line = "") => `Plan a trade: ${line.replace(/\s+/g, " ").trim()}`.trim().slice(0, CONTEXT_MAX);

/**
 * "Plan a trade": opens the Copilot Lab prefilled with the page's symbol, a context line and what prompted it
 * (``origin``, kept by a confirmed plan), so an idea is pressure-tested before the entry. Nothing is sent until the owner presses Send. Owner-only,
 * and nothing while the lab is off.
 */
export default function PlanATrade({ symbol = "", line, origin, originRef = null, className, title, children }: {
  symbol?: string; line?: string; className?: string; title?: string; children?: ReactNode;
  /** What prompts this plan (docs/copilot-lab.md § Origin): the placement's kind, and Radar's event id. */
  origin: OriginKind; originRef?: string | null;
}) {
  const on = useCopilotOn();
  if (!on) return null;
  const from: LinkOrigin = { kind: origin, ref: originRef };
  return <Link href={copilotLabHref(symbol, planContext(line), from)} className={className ?? `${PLAN_BUTTON} h-11 sm:h-9`}
    title={title ?? "Plan a trade with the copilot before you enter. Nothing is sent until you press Send."}>
    {children ?? <><Crosshair size={14} aria-hidden />Plan a trade</>}
  </Link>;
}
