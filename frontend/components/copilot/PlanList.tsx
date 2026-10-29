"use client";

import Link from "next/link";
import type { HomeActions } from "@/components/copilot/CopilotPanel";
import { HORIZONS, type DeskPlan, type DeskPlanStage } from "@/lib/desk";
import { cn } from "@/lib/utils";

const STAGES: { id: DeskPlanStage; title: string }[] = [
  { id: "armed", title: "Armed" }, { id: "in_position", title: "In position" },
  { id: "exited", title: "Exited this week" }, { id: "done", title: "Done this week" },
];
const DOT: Record<DeskPlanStage, string> = { armed: "bg-sky-400", in_position: "bg-primary", exited: "bg-rose-400", done: "bg-muted-foreground" };

const pct = (value: number) => `${Math.abs(value).toFixed(1)}%`;
const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}R`;
const clock = (at: number) => new Date(at * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const date = (at: number) => new Date(at * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

/** The plan's one number on the right and the quiet line under it. Levels are on the underlying. */
function lines(plan: DeskPlan): { value: string | null; tone: string; detail: string } {
  const { entry, invalidation, timeStop } = plan;
  // A time stop on a later day names its day.
  const due = timeStop && date(timeStop.due_at) !== date(Date.now() / 1000) ? `${date(timeStop.due_at)} ` : "";
  const stop = timeStop?.state === "pending" ? `time stop ${due}${clock(timeStop.due_at)}` : null;
  if (plan.stage === "armed") {
    const value = entry?.state === "hit" ? "Entry hit" : entry?.distance_pct !== undefined ? `${pct(entry.distance_pct)} to entry` : null;
    const detail = [entry && `Entry ${entry.price.toFixed(2)}`, invalidation && `invalidation ${invalidation.price.toFixed(2)}`, stop]
      .filter(Boolean).join(" · ");
    return { value, tone: "text-foreground", detail: detail ? detail[0].toUpperCase() + detail.slice(1) : "Plan armed" };
  }
  if (plan.stage === "in_position") {
    const level = invalidation && (invalidation.state === "hit" ? `Invalidation ${invalidation.price.toFixed(2)} hit`
      : invalidation.distance_pct !== undefined ? `${pct(invalidation.distance_pct)} to invalidation ${invalidation.price.toFixed(2)}`
      : `Invalidation ${invalidation.price.toFixed(2)}`);
    const detail = [plan.note, level, stop].filter(Boolean).join(" · ");
    return { value: plan.r === null ? null : signed(plan.r), tone: plan.r === null ? "" : plan.r >= 0 ? "text-emerald-300" : "text-rose-300",
      detail: detail ? detail[0].toUpperCase() + detail.slice(1) : "No invalidation on file" };
  }
  if (plan.stage === "exited") return { value: plan.at ? `Exited ${date(plan.at)}` : "Exited", tone: "text-muted-foreground", detail: "Exit review waiting" };
  return { value: plan.at ? date(plan.at) : null, tone: "text-muted-foreground", detail: plan.note ?? "Done" };
}

function Row({ plan, active, actions }: { plan: DeskPlan; active: boolean; actions: HomeActions }) {
  const { value, tone, detail } = lines(plan);
  const horizon = HORIZONS.find(h => h.id === plan.horizon)?.label;
  const href = plan.investigationId ? `/copilot-lab?investigation=${plan.investigationId}` : `/copilot-lab?${new URLSearchParams({ symbol: plan.symbol })}`;
  return (
    <li>
      <Link href={href} aria-label={[plan.symbol, plan.instrument, horizon].filter(Boolean).join(" ")} title={plan.thesis ?? undefined}
        onClick={event => {
          if (!plan.investigationId || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
          event.preventDefault();
          actions.open(plan.investigationId);
        }}
        className={cn("block min-h-11 w-full rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-secondary", active && "bg-secondary ring-1 ring-border",
          plan.stage === "done" && "opacity-70")}>
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="shrink-0 font-semibold text-foreground">{plan.symbol}</span>
          {plan.instrument && <span className="min-w-0 truncate text-xs text-muted-foreground">{plan.instrument}</span>}
          {horizon && <span className="shrink-0 rounded border px-1 text-[10px] leading-4 text-muted-foreground">{horizon}</span>}
          {value && <span className={cn("ml-auto shrink-0 text-xs tabular-nums", tone)}>{value}</span>}
        </span>
        <span className="block truncate text-xs text-muted-foreground" title={detail}>{detail}</span>
      </Link>
    </li>
  );
}

/**
 * The thread list's Plans view (docs/copilot-lab.md § The desk): every plan from the thread list's read, grouped Armed,
 * In position, Exited this week and Done this week, one row each with its instrument, horizon and its distance to the
 * entry (armed) or to the invalidation with its R (in position). A row opens its thread; a done plan with no saved
 * thread opens by its symbol. Read-only.
 */
export default function PlanList({ plans, actions, active }: { plans: DeskPlan[]; actions: HomeActions; active: string | null }) {
  if (!plans.length) return <p className="px-2.5 text-xs text-muted-foreground">No plans yet. A plan card&apos;s Confirm arms one.</p>;
  return (
    <div data-testid="desk-plans" className="space-y-3">
      {STAGES.map(({ id, title }) => {
        const items = plans.filter(p => p.stage === id);
        if (!items.length) return null;
        return (
          <section key={id} aria-label={title} className="space-y-0.5">
            <div className="flex items-center gap-2 px-2.5">
              <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[id])} />
              <h3 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
              <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">{items.length}</span>
            </div>
            <ul className="space-y-0.5">
              {items.map(plan => (
                <Row key={`${plan.stage}:${plan.investigationId ?? plan.symbol}:${plan.at ?? ""}`} plan={plan} actions={actions}
                  active={!!active && plan.investigationId === active} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
