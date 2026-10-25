"use client";

import { useEffect, useState } from "react";
import { alertText, type LevelAlert } from "@/lib/alerts";
import { listAlerts, listResearchJobs, listTimeStops, type ResearchJob, type TimeStop } from "@/lib/copilot";
import { JobMateriality } from "./ResearchDeeper";

const at = (seconds: number) => new Date(seconds * 1000).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const day = (iso: string) => new Date(`${iso}Z`).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });

const ROLE = { entry: { armed: "Entry · armed", fired: "Entry · hit" }, invalidation: { armed: "Invalidation · armed", fired: "Invalidation · hit" } };
/** A plan's time stop: waiting for its time, then sent, or skipped when no position opened after the plan was open. */
const STOP: Record<TimeStop["delivery"], string> = { scheduled: "pending", pending: "sending", sending: "sending", sent: "sent",
  skipped: "skipped", expired: "not sent", unknown: "may have sent" };

/** What the owner confirmed from this investigation: its level alerts (a plan's entry and invalidation by name), its
 * plan's time stop and revisit jobs, read from their own routes. */
export default function LinkedActivity({ investigationId, refreshKey }: { investigationId: string; refreshKey: number }) {
  const [alerts, setAlerts] = useState<LevelAlert[]>([]);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [stops, setStops] = useState<{ time_stops: TimeStop[]; enabled: boolean }>({ time_stops: [], enabled: true });
  useEffect(() => {
    const controller = new AbortController();
    listAlerts(controller.signal).then(payload => setAlerts(payload.alerts.filter(alert =>
      (alert.source_kind as string) === "copilot" && alert.source_id === investigationId))).catch(() => { /* shown when readable */ });
    listResearchJobs(controller.signal, investigationId).then(payload => setJobs(payload.jobs.filter(job =>
      job.kind === "reassess" && job.input.investigation_id === investigationId))).catch(() => { /* shown when readable */ });
    listTimeStops(investigationId, controller.signal).then(setStops).catch(() => { /* shown when readable */ });
    return () => controller.abort();
  }, [investigationId, refreshKey]);
  if (!alerts.length && !jobs.length && !stops.time_stops.length) return null;
  return (
    <section aria-label="Linked to this investigation" className="space-y-1 text-xs">
      <p className="text-muted-foreground">Linked to this investigation</p>
      <ul className="space-y-1">
        {alerts.map(alert => (
          <li key={alert.id} className="flex flex-wrap items-center gap-2">
            <span className={alert.state === "active" ? "rounded bg-sky-500/10 px-1.5 py-0.5 text-sky-300" : "rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300"}>
              {alert.plan_role ? ROLE[alert.plan_role][alert.state === "active" ? "armed" : "fired"] : alert.state === "active" ? "Alert · armed" : "Alert · fired"}
            </span>
            <span className="text-foreground">{alert.symbol} · {alertText(alert, alert.price)}</span>
            {alert.label && <span className="text-muted-foreground">{alert.label}</span>}
            {alert.state === "fired" && alert.event && <span className="text-muted-foreground">fired {at(alert.event.event_at)} ET at {alert.event.price}</span>}
          </li>
        ))}
        {stops.time_stops.map(stop => (
          <li key={stop.id} className="flex flex-wrap items-center gap-2">
            <span className={stop.delivery === "sent" ? "rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300" : stop.delivery === "scheduled" ? "rounded bg-sky-500/10 px-1.5 py-0.5 text-sky-300" : "rounded bg-muted px-1.5 py-0.5 text-muted-foreground"}>
              Time stop · {STOP[stop.delivery]}
            </span>
            <span className="text-foreground">{stop.symbol} · {at(stop.due_at)} ET</span>
            <span className="text-muted-foreground">{stop.text}</span>
            {stop.delivery === "scheduled" && !stops.enabled && <span className="text-muted-foreground">Time-stop pings are off on this server.</span>}
            {stop.error && stop.delivery !== "sent" && <span className="text-muted-foreground">{stop.error}</span>}
          </li>
        ))}
        {jobs.map(job => (
          <li key={job.id} className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">Revisit · {job.status}</span>
            <span className="min-w-0 truncate text-muted-foreground" title={job.input.question}>{job.input.question}</span>
            {job.status === "queued" && job.next_attempt_at && <span className="text-muted-foreground">due {day(job.next_attempt_at)}</span>}
            {job.cost_usd !== null && <span className="tabular-nums text-muted-foreground">${job.cost_usd.toFixed(2)}</span>}
            <JobMateriality job={job} />
          </li>
        ))}
      </ul>
    </section>
  );
}
