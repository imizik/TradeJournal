"use client";

import { useState } from "react";
import { listAlerts } from "@/lib/copilot";
import { removeAlert, type LevelAlert } from "@/lib/alerts";
import { savePlanDone } from "@/lib/desk";

const BUTTON = "min-h-11 rounded border px-2 disabled:opacity-40 sm:min-h-7";

/**
 * The thread menu's Mark plan done (docs/copilot-lab.md § The desk): ends a plan that was never entered or was given up
 * on with a ``plan_done`` day-journal entry. While its entry or invalidation alert is still armed it says so first and
 * removes them (the alerts route's ``DELETE``) only when the owner agrees. The plan, its conversation and the journal stay.
 * ``label`` and ``buttonClass`` dress its first button (Arm today's plans calls it Drop).
 */
export default function MarkPlanDone({ investigationId, symbol, onDone, label = "Mark plan done", buttonClass = "w-full text-foreground hover:bg-muted" }: {
  investigationId: string; symbol: string; onDone(): void; label?: string; buttonClass?: string;
}) {
  const [armed, setArmed] = useState<LevelAlert[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finish = async (remove: LevelAlert[]) => {
    setBusy(true);
    setError(null);
    try {
      for (const alert of remove) await removeAlert(alert.id);
      await savePlanDone(symbol, "Marked done");
      onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Not done.");
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const { alerts } = await listAlerts();
      const live = alerts.filter(a => a.source_id === investigationId && a.plan_role && a.state === "active");
      setBusy(false);
      if (live.length) setArmed(live);
      else await finish([]);
    } catch (failure) {
      setBusy(false);
      setError(failure instanceof Error ? failure.message : "The alerts could not be read.");
    }
  };

  if (!armed) return (
    <div className="space-y-1">
      <button type="button" onClick={() => void start()} disabled={busy} className={`${BUTTON} ${buttonClass}`}>{label}</button>
      {error && <p role="status" className="text-primary">Not done: {error}</p>}
    </div>
  );
  const levels = armed.map(a => `${a.plan_role} ${a.price.toFixed(2)}`).join(" and ");
  return (
    <div role="group" aria-label="Mark plan done" className="space-y-2 rounded border border-primary/40 p-2">
      <p className="text-foreground">Its {levels} {armed.length === 1 ? "alert is" : "alerts are"} still armed. Remove {armed.length === 1 ? "it" : "them"} and mark the plan done?</p>
      <p className="text-muted-foreground">The plan, this conversation and your journal stay.</p>
      <div className="flex justify-end gap-1.5">
        <button type="button" onClick={() => setArmed(null)} disabled={busy} className={`${BUTTON} text-muted-foreground hover:text-foreground`}>Cancel</button>
        <button type="button" onClick={() => void finish(armed)} disabled={busy} className={`${BUTTON} bg-primary text-primary-foreground`}>Remove alerts and mark done</button>
      </div>
      {error && <p role="status" className="text-primary">Not done: {error}</p>}
    </div>
  );
}
