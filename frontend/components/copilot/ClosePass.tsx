"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";
import type { DeskThread } from "@/lib/desk";

/** One answer Close the day asks for after the threads' close questions: a fill waiting for its plan. Alert and Radar
 * ratings are optional and never asked here (Now's "How the pings did" shows what followed instead). */
export type CloseStep = { kind: "fill"; id: string; row: DeskThread };

/**
 * The answers Close the day asks for once every thread's close question is answered or skipped: the fills waiting for
 * their plan, in list order. ``passed`` holds the ids answered or skipped this visit, before the thread list reads them back.
 */
export function closeSteps(fills: DeskThread[], passed: ReadonlySet<string>): CloseStep[] {
  return fills.map(row => ({ kind: "fill" as const, id: row.fillToLink!, row })).filter(step => !passed.has(step.id));
}

const LINK = "inline-flex min-h-11 items-center text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-8";

/**
 * Close the day's step after the threads (docs/copilot-lab.md § The desk, Close of day): the fill's link, the same
 * component the thread top uses (``body``), with Skip and the pass's "N of M done". An answer or Skip
 * moves to the next; End stops the pass.
 */
export default function ClosePass({ done, total, body, onSkip, onEnd }: {
  done: number; total: number; body: ReactNode; onSkip(): void; onEnd(): void;
}) {
  return (
    <section aria-label="Close the day" data-testid="close-pass" className="mb-4 space-y-3 rounded-lg border border-primary/40 bg-card p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-foreground">Close the day</h2>
        <span className="text-xs tabular-nums text-muted-foreground" data-testid="close-pass-done">{done} of {total} done</span>
        <span className="ml-auto flex items-center gap-3">
          <button type="button" onClick={onSkip} className={LINK}>Skip</button>
          <button type="button" onClick={onEnd} aria-label="End Close the day" title="End the pass" className={`${LINK} min-w-8 justify-center`}>
            <X size={14} aria-hidden />
          </button>
        </span>
      </div>
      <p className="text-xs text-muted-foreground">Which plan was this fill?</p>
      {body}
    </section>
  );
}
