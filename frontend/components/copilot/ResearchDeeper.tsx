"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVE_JOB, enqueueResearch, listResearchJobs, type ResearchJob, type ResearchJobs } from "@/lib/copilot";
import { cn } from "@/lib/utils";

/** How often an active job is re-read. Jobs take minutes; this only has to notice the change. */
export const POLL_MS = 10_000;

const TONE: Record<ResearchJob["status"], string> = {
  queued: "bg-muted text-muted-foreground", running: "bg-sky-500/10 text-sky-300", done: "bg-emerald-500/10 text-emerald-300",
  failed: "bg-rose-500/10 text-rose-300", cancelled: "bg-muted text-muted-foreground",
};

const PING: Record<NonNullable<ResearchJob["notify"]>["status"], string> = {
  sent: "phone ping sent", sending: "phone ping sending", skipped: "no phone ping", failed: "phone ping failed",
  held: "phone ping held by the notification policy",
};

/** A finished job's materiality and what happened to its phone ping. Read-only. */
export function JobMateriality({ job }: { job: ResearchJob }) {
  const note = job.notify;
  if (!note) return null;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
      {note.material_change
        ? <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300" title={note.material_reason}>Material · {note.material_reason}</span>
        : <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">Not material</span>}
      {note.material_change && (
        <span className={cn("text-muted-foreground", note.status === "failed" && "text-rose-300")}
          title={note.error ?? note.reason}>{PING[note.status]}{note.status === "skipped" && note.reason ? ` (${note.reason})` : ""}</span>
      )}
    </span>
  );
}

/** "Research deeper" for one saved investigation: queue a background research job from it and follow its status.
 * Renders nothing unless the research queue is enabled. */
export default function ResearchDeeper({ investigationId, symbol, topic, onFinished, onOpenResult, onDiscuss }: {
  investigationId: string; symbol: string; topic: string;
  onFinished(): void; onOpenResult(id: string): void; onDiscuss(id: string): void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [form, setForm] = useState<{ symbol: string; question: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const active = useRef(new Set<string>());

  const apply = useCallback((result: ResearchJobs) => {
    // Only "Research deeper" jobs: an owner revisit (shown under Linked) may wait for days and must not hide the button.
    const mine = result.jobs.filter(job => job.kind === "question" && job.input.from_investigation === investigationId);
    // A job that was waiting or running and has now finished puts its result under Recent.
    if (mine.some(job => active.current.has(job.id) && !ACTIVE_JOB.has(job.status))) onFinished();
    active.current = new Set(mine.filter(job => ACTIVE_JOB.has(job.status)).map(job => job.id));
    setEnabled(result.queue_enabled);
    setJobs(mine);
  }, [investigationId, onFinished]);

  useEffect(() => {
    const controller = new AbortController();
    listResearchJobs(controller.signal, investigationId).then(apply).catch(() => { if (!controller.signal.aborted) setEnabled(false); });
    return () => controller.abort();
  }, [apply, investigationId]);

  const waiting = jobs.some(job => ACTIVE_JOB.has(job.status));
  useEffect(() => {
    if (!waiting) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      listResearchJobs(controller.signal, investigationId).then(apply).catch(() => { /* the next poll tries again */ });
    }, POLL_MS);
    // Leaving the investigation stops the polls and any read still in flight.
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [waiting, apply, investigationId]);

  async function submit() {
    if (!form || sending) return;
    const question = form.question.trim();
    if (!question) return;
    setSending(true);
    setError(null);
    try {
      const made = await enqueueResearch(question, form.symbol.trim() ? [form.symbol.trim().toUpperCase()] : [], investigationId);
      if (ACTIVE_JOB.has(made.job.status)) active.current.add(made.job.id);
      setJobs(current => [made.job, ...current.filter(job => job.id !== made.job.id)]);
      setForm(null);
      if (!made.created) setError("The same question was already asked today; showing that job.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The research job was not queued.");
    } finally {
      setSending(false);
    }
  }

  if (!enabled) return null;
  return (
    <section aria-label="Research deeper" className="space-y-2 text-xs">
      {!form && !waiting && (
        <button type="button" onClick={() => setForm({ symbol, question: topic })}
          className="min-h-11 rounded border px-2 py-1 text-muted-foreground hover:text-foreground sm:min-h-0">Research deeper</button>
      )}
      {form && (
        <form onSubmit={event => { event.preventDefault(); void submit(); }} className="space-y-2 rounded border bg-card/40 p-2">
          <p className="text-muted-foreground">Queue a background research job: it reads evidence on its own, cites sources and saves its result here. Nothing is traded or watched.</p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-muted-foreground">Symbol
              <input value={form.symbol} onChange={e => setForm({ ...form, symbol: e.target.value.toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 10) })}
                aria-label="Research symbol" className="w-24 rounded border bg-background px-2 py-1 text-base uppercase text-foreground sm:text-xs" />
            </label>
          </div>
          <textarea value={form.question} onChange={e => setForm({ ...form, question: e.target.value.slice(0, 2000) })} rows={3}
            aria-label="Research question" className="w-full rounded border bg-background px-2 py-1 text-base text-foreground sm:text-xs" />
          <div className="flex gap-2">
            <button type="submit" disabled={sending || !form.question.trim()}
              className="min-h-11 rounded bg-primary px-3 py-1 text-primary-foreground disabled:opacity-40 sm:min-h-0">{sending ? "Queuing…" : "Queue research"}</button>
            <button type="button" onClick={() => setForm(null)} className="min-h-11 rounded border px-3 py-1 text-muted-foreground sm:min-h-0">Cancel</button>
          </div>
        </form>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {jobs.length > 0 && (
        <ul aria-label="Research jobs" className="space-y-1">
          {jobs.map(job => (
            <li key={job.id} className="flex flex-wrap items-center gap-2">
              <span className={cn("rounded px-1.5 py-0.5", TONE[job.status])}>Research · {job.status}</span>
              <span className="min-w-0 truncate text-muted-foreground" title={job.input.question}>{job.input.question}</span>
              {job.cost_usd !== null && <span className="tabular-nums text-muted-foreground">${job.cost_usd.toFixed(2)}</span>}
              {job.status === "failed" && job.error && <span className="text-rose-300">{job.error}</span>}
              <JobMateriality job={job} />
              {job.status === "done" && job.investigation_id && (
                <>
                  <button type="button" onClick={() => onOpenResult(job.investigation_id!)} className="min-h-11 rounded border px-2 py-0.5 hover:text-foreground sm:min-h-0">Open result</button>
                  <button type="button" onClick={() => onDiscuss(job.investigation_id!)} className="min-h-11 rounded border px-2 py-0.5 hover:text-foreground sm:min-h-0">Discuss this result</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
