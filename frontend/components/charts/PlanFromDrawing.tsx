"use client";

import { useEffect, useRef } from "react";
import { ArrowUpDown, Target } from "lucide-react";
import type { PanelActions } from "@/components/copilot/CopilotPanel";
import type { DrawnPlan } from "@/lib/copilot";
import type { PlanPair } from "@/lib/drawPlan";

/** What "Plan this" asks the dock's copilot: the owner's message and the levels it names. */
/** A conversation the chart starts in the dock: its context line, the drawn plan if any, and whether Send shows the chart. */
export type PlanAsk = { text: string; plan: DrawnPlan | null; n: number; chart?: boolean };

/** "Plan this", or "Plan this as invalidation" for one drawn level. */
export const planThisName = (pair: PlanPair) => pair.trigger ? "Plan this" : "Plan this as invalidation";

/**
 * Draw the plan, beside the drawn levels on the main chart: "Plan this" with the side and the two prices it will send,
 * and, for two levels, a swap of which is the entry and which the invalidation. 44 px on a phone.
 */
export default function PlanFromDrawing({ pair, narrow, onPlan, onSwap }: { pair: PlanPair; narrow: boolean; onPlan(): void; onSwap(): void }) {
  const size = narrow ? "min-h-11" : "min-h-7";
  const prices = `${pair.side === "long" ? "Long" : "Short"} · ${pair.trigger ? `${pair.trigger.price.toFixed(2)} → ` : ""}${pair.invalidation.price.toFixed(2)}`;
  return <div role="group" aria-label="Plan from your drawing" className="absolute left-2 top-10 z-10 flex md:top-14 max-w-[calc(100%-1rem)] items-stretch gap-1">
    <button type="button" onClick={onPlan} aria-label={`${planThisName(pair)}: ${prices}`}
      title={pair.trigger ? `The copilot drafts a ${pair.side} plan around entry ${pair.trigger.price.toFixed(2)} and invalidation ${pair.invalidation.price.toFixed(2)}. Nothing is sent until you press Send.`
        : `The copilot drafts the entry and the plan around your invalidation at ${pair.invalidation.price.toFixed(2)}. Nothing is sent until you press Send.`}
      className={`inline-flex min-w-0 items-center gap-1.5 rounded-md bg-sky-500 px-2.5 text-xs font-medium text-white shadow-lg hover:bg-sky-400 ${size}`}>
      <Target size={13} aria-hidden className="shrink-0" /><span className="shrink-0">{planThisName(pair)}</span>
      <span className="min-w-0 truncate font-mono text-[11px] text-sky-50/90">{prices}</span>
    </button>
    {pair.trigger && <button type="button" onClick={onSwap} aria-label="Swap entry and invalidation" title={`Make it a ${pair.side === "long" ? "short" : "long"}: entry ${pair.invalidation.price.toFixed(2)}, invalidation ${pair.trigger.price.toFixed(2)}`}
      className={`inline-flex shrink-0 items-center justify-center rounded-md border border-sky-400/50 bg-[#121924]/95 text-sky-200 shadow-lg hover:bg-slate-800 ${narrow ? "h-11 w-11" : "h-7 w-7"}`}><ArrowUpDown size={14} /></button>}
  </div>;
}

/**
 * Inside the dock's Copilot tab: once the panel can take it, a "Plan this" becomes a new conversation on the chart's
 * symbol with the owner's message in the box (unsent) and the drawn levels beside it, then is spent.
 */
export function StartPlan({ ask, actions, onStarted }: { ask: PlanAsk | null; actions: PanelActions; onStarted(n: number): void }) {
  const { busy, start } = actions;
  const started = useRef(0);
  useEffect(() => {
    if (!ask || busy || started.current === ask.n) return;
    started.current = ask.n;
    start(ask.text, { kind: "chart", ref: null }, ask.plan, ask.chart);
    onStarted(ask.n);
  }, [ask, busy, start, onStarted]);
  return null;
}
