"use client";

import { useEffect, useState } from "react";
import { nyTime } from "@/lib/radar";
import { exitText, getShadowWeek, money, planTitle, weekShift, type ShadowDecision, type ShadowWeek } from "@/lib/shadowBook";
import { cn } from "@/lib/utils";

const BADGE: Record<ShadowDecision["decision"], { label: string; className: string }> = {
  plan: { label: "Plan", className: "bg-sky-500/10 text-sky-300" },
  skip: { label: "Skip", className: "bg-muted text-muted-foreground" },
  not_decided: { label: "Not decided", className: "bg-muted text-muted-foreground" },
  filtered: { label: "Below the bar", className: "bg-muted text-muted-foreground" },
  error: { label: "Error", className: "bg-amber-500/10 text-amber-300" },
  deciding: { label: "Deciding…", className: "bg-muted text-muted-foreground" },
};
const STATUS: Partial<Record<ShadowDecision["status"], string>> = {
  pending_entry: "Waiting for the entry quote", open: "Open", exiting: "Exiting", unresolved: "Unresolved",
};

function Decision({ d }: { d: ShadowDecision }) {
  const badge = BADGE[d.decision];
  const plan = d.plan;
  return (
    <li className="rounded-lg border bg-card p-3 text-sm" data-testid="shadow-decision">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", badge.className)}>{badge.label}</span>
        <span className="min-w-0 break-words font-medium text-foreground">{d.event.summary}</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">Radar {d.session_date} {nyTime(d.event.first_seen_at)}{d.decided_at ? ` · decided ${nyTime(d.decided_at)}` : ""}</p>
      {plan ? (
        <div className="mt-2 space-y-1">
          <p className="font-medium text-foreground">{planTitle(plan)} <span className="text-xs font-normal text-muted-foreground">({plan.unit})</span></p>
          <p className="text-xs tabular-nums text-muted-foreground">
            At {plan.entry_trigger.price} · invalid {plan.invalidation.price} · target {plan.target} · out by {plan.time_stop}
          </p>
          <p className="break-words text-xs text-foreground">{plan.thesis}</p>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums">
            {d.entry ? <span>In {d.entry.price}{d.entry.shares ? ` × ${d.entry.shares}` : ""} at {nyTime(d.entry.at)}</span> : null}
            {d.exit ? <span>Out {d.exit.price} at {nyTime(d.exit.at)} ({exitText(d.exit.reason)})</span> : null}
            {d.result ? (
              <span className={cn("font-medium", d.result.pnl >= 0 ? "text-emerald-300" : "text-rose-300")}>
                {money(d.result.pnl)}{d.result.return_pct != null ? ` (${d.result.return_pct}%)` : ""}
              </span>
            ) : null}
            {STATUS[d.status] ? <span className="text-muted-foreground">{STATUS[d.status]}{d.unresolved ? `: ${d.unresolved}` : ""}</span> : null}
          </div>
        </div>
      ) : (
        d.reason && <p className="mt-1.5 break-words text-xs text-foreground">{d.reason}</p>
      )}
    </li>
  );
}

/** Events below the strong-event bar: one line, opened to a short list; no turn was spent on them. */
function Filtered({ rows }: { rows: ShadowDecision[] }) {
  return (
    <details className="rounded-lg border bg-card px-3 py-2 text-sm" data-testid="shadow-filtered">
      <summary className="cursor-pointer text-muted-foreground">
        {rows.length} event{rows.length === 1 ? "" : "s"} below the bar, no turn spent
      </summary>
      <ul className="mt-2 space-y-1 text-xs">
        {rows.map((d) => (
          <li key={d.id} className="break-words">
            <span className="tabular-nums text-muted-foreground">{d.session_date} {nyTime(d.event.first_seen_at)}</span> {d.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function ShadowBookView() {
  const [week, setWeek] = useState<string | undefined>();
  const [data, setData] = useState<ShadowWeek | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getShadowWeek(week, controller.signal).then((next) => { setData(next); setError(null); })
      .catch((e) => { if ((e as Error).name !== "AbortError") setError("The shadow book could not be reached."); });
    return () => controller.abort();
  }, [week]);

  if (error && !data) return <p role="alert" className="text-xs text-amber-300">{error}</p>;
  if (!data) return null;
  const { shadow, owner, note } = data.summary;
  const thisWeek = week === undefined;
  const filtered = data.decisions.filter((d) => d.decision === "filtered");
  const decided = data.decisions.filter((d) => d.decision !== "filtered");
  return (
    <section aria-label="Shadow book" className="space-y-2" data-testid="shadow-book">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">Shadow book</h2>
        <div className="flex items-center gap-1 text-xs">
          <button type="button" className="h-9 rounded-md border px-2.5" onClick={() => setWeek(weekShift(data.week.start, -1))}>Earlier week</button>
          <button type="button" className="h-9 rounded-md border px-2.5 disabled:opacity-40" disabled={thisWeek} onClick={() => setWeek(undefined)}>This week</button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        The copilot&apos;s own paper book: it decides on Radar events by itself, one unit a position. Paper only; never your account, alerts or phone.
        {!data.enabled && " Off now (SHADOW_BOOK_ENABLED)."}
      </p>
      <p className="rounded-lg border bg-card px-3 py-2.5 text-sm" data-testid="shadow-week-line">
        Week of {data.week.start}: shadow {money(shadow.pnl_usd)} on {shadow.closed} closed of {shadow.plans} plans ({shadow.turns} turns{shadow.filtered ? `, ${shadow.filtered} below the bar` : ""})
        {" · "}{owner.state === "ok" ? `you ${money(owner.pnl_usd)} on ${owner.trades} trades` : "your week unavailable"}
        <span className="block text-xs text-muted-foreground">{note}</span>
      </p>
      {data.decisions.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No shadow decisions {thisWeek ? "this" : "that"} week.</p>
      ) : (
        <>
          {filtered.length > 0 && <Filtered rows={filtered} />}
          {decided.length > 0 && <ul className="space-y-2">{decided.map((d) => <Decision key={d.id} d={d} />)}</ul>}
        </>
      )}
    </section>
  );
}
