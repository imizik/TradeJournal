"use client";

import { useEffect, useState } from "react";
import MarkPlanDone from "@/components/copilot/MarkPlanDone";
import { api } from "@/lib/api";
import { getDeskThreads, nyDay, type DeskPlan, type DeskThreads } from "@/lib/desk";
import { cn } from "@/lib/utils";

/** A "Still good" answer: a ``decision`` day-journal entry that starts this way. */
export const ARMED = "Armed for today.";
const BUTTON = "min-h-11 rounded border px-2.5 text-xs disabled:opacity-40 sm:min-h-7";
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const clock = (at: number) => new Date(at * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const date = (at: number) => new Date(at * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

/** The plan's levels in words: "Entry 31.00 · invalidation 29.00 · time stop 15:30". */
export function planLine(plan: DeskPlan) {
  const stop = plan.timeStop?.state === "pending" ? plan.timeStop.due_at : null;
  const due = stop === null ? null : `${date(stop) !== date(Date.now() / 1000) ? `${date(stop)} ` : ""}${clock(stop)}`;
  const parts = [plan.entry && `entry ${plan.entry.price.toFixed(2)}`, plan.invalidation && `invalidation ${plan.invalidation.price.toFixed(2)}`,
    due && `time stop ${due}`].filter(Boolean).join(" · ");
  return parts ? parts[0].toUpperCase() + parts.slice(1) : "No levels on file";
}

/** Earnings first, then news or any other thesis-watch trigger fired today on the symbol (the thread list's new rows). */
function flags(data: DeskThreads, symbol: string) {
  return data.threads.filter(r => r.group === "new" && r.key.startsWith("thesis:") && r.symbol === symbol)
    .map(r => r.status.text).sort((a, b) => Number(b.startsWith("Earnings")) - Number(a.startsWith("Earnings"))).slice(0, 2);
}

/**
 * Arm today's plans (docs/copilot-lab.md § The desk): before the open, each armed plan with its entry, invalidation and
 * time stop and today's earnings or thesis-watch flags, and three answers. **Still good** logs a ``decision`` day-journal
 * entry ("Armed for today. …"); **Change** opens the plan's thread with a question in the box, unsent; **Drop** is Mark
 * plan done, asking first while its alerts are armed. "N of M checked" counts the plans answered today (a Still good
 * read back from today's journal, or dropped on this visit). Ask the copilot puts the old question in the box instead.
 * Nothing here arms, sizes or sends an order.
 */
export default function ArmChecklist({ change, ask, onClose, onDropped }: {
  change(plan: DeskPlan, text: string): void; ask(): void; onClose(): void; onDropped(): void;
}) {
  const [data, setData] = useState<DeskThreads | null>(null);
  const [plans, setPlans] = useState<DeskPlan[] | null>(null);
  const [good, setGood] = useState<Set<string>>(new Set());
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // The list is kept as first read, so a dropped plan stays on it, checked.
    Promise.all([getDeskThreads(controller.signal), api.dayJournal(nyDay())]).then(([threads, journal]) => {
      setData(threads);
      setPlans(threads.plans.filter(p => p.stage === "armed"));
      setGood(new Set(journal.entries.filter(e => e.kind === "decision" && e.symbol && e.text.startsWith(ARMED)).map(e => e.symbol!)));
    }).catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Plans unavailable."); });
    return () => controller.abort();
  }, []);

  const key = (plan: DeskPlan) => plan.investigationId ?? plan.symbol;
  const stillGood = async (plan: DeskPlan) => {
    setBusy(key(plan));
    setError(null);
    try {
      await api.addDayJournalEntry(nyDay(), { operation_id: `armed-${uid()}`, kind: "decision", symbol: plan.symbol, text: `${ARMED} ${planLine(plan)}.` });
      setGood(current => new Set(current).add(plan.symbol));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Not saved.");
    } finally {
      setBusy(null);
    }
  };
  const checked = (plan: DeskPlan) => dropped.has(key(plan)) ? "Dropped" : good.has(plan.symbol) ? "Still good" : null;
  const done = plans?.filter(checked).length ?? 0;

  return (
    <section aria-label="Arm today's plans" data-testid="arm-checklist" className="mb-4 space-y-3 rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-baseline gap-2">
        <h2 className="font-semibold text-foreground">Arm today&apos;s plans</h2>
        {plans && plans.length > 0 && (
          <span data-testid="arm-progress" className="text-xs text-muted-foreground">
            <span className="tabular-nums">{done}</span> of <span className="tabular-nums">{plans.length}</span> checked
          </span>
        )}
        <button type="button" onClick={onClose} className="-my-2 ml-auto min-h-11 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Close</button>
      </div>
      {!plans && !error && <p className="text-xs text-muted-foreground">Reading your armed plans…</p>}
      {plans && !plans.length && <p className="text-xs text-muted-foreground">No plan is armed. Plan a trade, or ask the copilot below.</p>}
      {plans && plans.length > 0 && (
        <ul className="divide-y">
          {plans.map(plan => {
            const answer = checked(plan);
            const notes = data ? flags(data, plan.symbol) : [];
            const line = planLine(plan);
            return (
              <li key={key(plan)} aria-label={plan.symbol} className={cn("space-y-1.5 py-2.5 first:pt-0 last:pb-0", answer && "opacity-70")}>
                <div className="flex min-w-0 items-baseline gap-1.5">
                  <span className="shrink-0 font-semibold text-foreground">{plan.symbol}</span>
                  {plan.instrument && <span className="min-w-0 truncate text-xs text-muted-foreground">{plan.instrument}</span>}
                  {answer && <span className="ml-auto shrink-0 text-xs text-emerald-300">✓ {answer}</span>}
                </div>
                <p className="text-xs text-foreground">{line}</p>
                {notes.map(note => <p key={note} className="truncate text-xs text-primary" title={note}>⚑ {note}</p>)}
                {!answer && (
                  <div className="flex flex-wrap gap-1.5 [&_[role=group]]:basis-full">
                    <button type="button" disabled={busy !== null} onClick={() => void stillGood(plan)} className={cn(BUTTON, "text-foreground hover:bg-muted")}>Still good</button>
                    <button type="button" disabled={busy !== null || !plan.investigationId}
                      onClick={() => change(plan, `Change my ${plan.symbol} plan before the open: ${line}. What should change, and why?`)}
                      className={cn(BUTTON, "text-foreground hover:bg-muted")}>Change</button>
                    {plan.investigationId && (
                      <div className="contents text-xs">
                        <MarkPlanDone investigationId={plan.investigationId} symbol={plan.symbol} label="Drop" buttonClass="text-xs text-foreground hover:bg-muted sm:px-2.5"
                          onDone={() => { setDropped(current => new Set(current).add(key(plan))); onDropped(); }} />
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {error && <p role="status" className="text-xs text-primary">Not done: {error}</p>}
      <p className="border-t pt-2 text-xs text-muted-foreground">
        Nothing here arms, sizes or sends an order.{" "}
        <button type="button" onClick={ask} className="min-h-11 underline-offset-2 hover:text-foreground hover:underline sm:min-h-0">Ask the copilot instead</button>
      </p>
    </section>
  );
}
