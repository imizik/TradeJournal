"use client";

import { useEffect, useState } from "react";
import { getDayPlan, saveDayPlan, type DayPlanBody } from "@/lib/desk";

const SAVED = "tradejournal:day-plan-saved";
const clock = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return `${(h + 11) % 12 + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};

/**
 * The pre-market plan card (docs/copilot-lab.md § The day plan): before the open he sets the day's max size (dollars of
 * premium in one option position) and a hard exit time; with DAY_PLAN_ALERTS on, the phone pings when a position goes
 * over the size, when the exit time comes with today's options still open, and when one is opened after it. Saving is a
 * day-journal entry; nothing here sizes or places an order.
 */
export default function DayPlanCard({ className = "", bare = false }: { className?: string; /** In a checklist step that names it: no heading. */ bare?: boolean }) {
  const [body, setBody] = useState<DayPlanBody | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [size, setSize] = useState("");
  const [exit, setExit] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getDayPlan(controller.signal).then(setBody).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    // The card can show twice (the left column and Start the day): a save in one updates the other.
    const saved = (event: Event) => { setBody((event as CustomEvent<DayPlanBody>).detail); setEditing(false); };
    window.addEventListener(SAVED, saved);
    return () => { controller.abort(); window.removeEventListener(SAVED, saved); };
  }, []);

  const plan = body?.plan ?? null;
  const edit = () => {
    setSize(plan?.max_usd != null ? String(plan.max_usd) : "");
    setExit(plan?.exit_by ?? "");
    setError(null);
    setEditing(true);
  };
  const save = async () => {
    const max = size.trim() ? Number(size) : null;
    if (max !== null && !(max > 0)) return setError("Max size is dollars, above $0.");
    if (max === null && !exit) return setError("Set a max size, an exit time or both.");
    setSaving(true);
    setError(null);
    try {
      window.dispatchEvent(new CustomEvent(SAVED, { detail: await saveDayPlan(max, exit || null) }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  if (!body) return failed ? null : <p className={`text-xs text-muted-foreground ${className}`}>Reading today&apos;s plan…</p>;
  const input = "min-h-11 w-full rounded-md border bg-background px-2 text-base sm:min-h-8 sm:text-sm";
  return (
    <section aria-label="Today's plan" data-testid="day-plan" className={`space-y-2 rounded-lg border bg-card p-3 text-sm ${className}`}>
      <div className="flex items-baseline gap-2">
        {!bare && <h2 className="font-semibold text-foreground">Today&apos;s plan</h2>}
        <span className="text-xs text-muted-foreground">{body.pings ? "pings hold you to it" : "pings are off on the server"}</span>
        {plan && !editing && <button type="button" onClick={edit} className="-my-2 ml-auto min-h-11 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Change</button>}
      </div>
      {!editing && !plan ? (
        <button type="button" onClick={edit} data-testid="day-plan-set" className="min-h-11 w-full rounded-md border px-3 text-left text-sm hover:bg-secondary sm:min-h-8">
          Set a max size and a hard exit time for today →
        </button>
      ) : editing ? (
        <form className="space-y-2" onSubmit={e => { e.preventDefault(); void save(); }}>
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1 text-xs text-muted-foreground">Max size, $ a position
              <input aria-label="Max size in dollars" inputMode="decimal" value={size} onChange={e => setSize(e.target.value)} placeholder="500" className={input} />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">Out by (ET)
              <input aria-label="Hard exit time" type="time" value={exit} onChange={e => setExit(e.target.value)} className={input} />
            </label>
          </div>
          {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={saving} className="min-h-11 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60 sm:min-h-8">{saving ? "Saving…" : "Save plan"}</button>
            <button type="button" onClick={() => setEditing(false)} className="min-h-11 px-2 text-xs text-muted-foreground hover:text-foreground sm:min-h-8">Cancel</button>
          </div>
        </form>
      ) : (
        <p data-testid="day-plan-line" className="text-foreground">
          {plan && [plan.max_usd != null && `Max $${plan.max_usd.toLocaleString("en-US")} a position`, plan.exit_by && `out by ${clock(plan.exit_by)} ET`].filter(Boolean).join(" · ")}
        </p>
      )}
    </section>
  );
}
