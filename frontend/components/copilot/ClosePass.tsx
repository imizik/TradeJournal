"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";
import type { DeskAlertToAnswer, DeskHitToRate, DeskThread } from "@/lib/desk";

/** One answer Close the day asks for after the threads' close questions. */
export type CloseStep = { kind: "alert"; id: string; alert: DeskAlertToAnswer } | { kind: "hit"; id: string; hit: DeskHitToRate }
  | { kind: "fill"; id: string; row: DeskThread };

/**
 * The answers Close the day asks for once every thread's close question is answered or skipped: today's position alerts
 * with no feedback, today's Radar hits not rated, then the fills waiting for their plan, in that order. ``passed`` holds
 * the ids answered or skipped this visit, before the session and thread list read them back.
 */
export function closeSteps(alerts: DeskAlertToAnswer[] | undefined, hits: DeskHitToRate[] | undefined, fills: DeskThread[],
  passed: ReadonlySet<string>): CloseStep[] {
  return [
    ...(alerts ?? []).filter(a => a.today && !a.feedback).map(alert => ({ kind: "alert" as const, id: alert.id, alert })),
    ...(hits ?? []).filter(h => h.today && !h.rating).map(hit => ({ kind: "hit" as const, id: hit.event_id, hit })),
    ...fills.map(row => ({ kind: "fill" as const, id: row.fillToLink!, row })),
  ].filter(step => !passed.has(step.id));
}

const ASK: Record<CloseStep["kind"], string> = {
  alert: "Was this alert useful? Your answer counts on Proof.",
  hit: "Did Radar find this early enough to matter? Your rating counts on Proof.",
  fill: "Which plan was this fill?",
};
const LINK = "inline-flex min-h-11 items-center text-xs font-medium text-muted-foreground hover:text-foreground sm:min-h-8";

/**
 * Close the day's step after the threads (docs/copilot-lab.md § The desk, Close of day): the step's own answer, the same
 * component the Briefing and the thread top use (``body``), with Skip and the pass's "N of M done". An answer or Skip
 * moves to the next; End stops the pass.
 */
export default function ClosePass({ step, done, total, body, onSkip, onEnd }: {
  step: CloseStep; done: number; total: number; body: ReactNode; onSkip(): void; onEnd(): void;
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
      <p className="text-xs text-muted-foreground">{ASK[step.kind]}</p>
      {body}
    </section>
  );
}
