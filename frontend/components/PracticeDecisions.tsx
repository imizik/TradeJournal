"use client";

import { useEffect, useRef, useState } from "react";
import type { DecisionRecord, PaperState } from "@/lib/api";
import PracticeDecisionForm from "@/components/PracticeDecisionForm";
import PracticePaperPlan, { PaperBadge } from "@/components/PracticePaperPlan";

// Paper state is fetched per TAKE card, so the number of cards that fetch is capped.
const PAPER_FETCH_LIMIT = 10;
const ET = "America/New_York";

function DecisionCard({ record, focused, withPaper }: { record: DecisionRecord; focused: boolean; withPaper: boolean }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [paper, setPaper] = useState<PaperState | null>(null);
  useEffect(() => {
    if (!focused || !ref.current) return;
    ref.current.open = true;
    ref.current.scrollIntoView?.({ block: "start" });
  }, [focused]);
  const plan = record.plan as { trigger_level?: number; stop?: number; target?: number; target_source?: { source?: string } };
  return (
    <details ref={ref} id={`decision-${record.id}`} data-decision-id={record.id} className="rounded-lg border bg-card p-4">
      <summary className="cursor-pointer list-none">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-semibold">{record.symbol} · {record.decision.toUpperCase()}</span>
          {record.decision === "take" && paper ? <PaperBadge status={paper.status} /> : <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700">PRACTICE · UNARMED</span>}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{record.actor} · received {new Date(record.received_at).toLocaleString("en-US", { timeZone: ET })} ET</p>
        {record.decision === "take" && <p className="mt-2 text-sm">Trigger {plan.trigger_level ?? "—"} · Stop {plan.stop ?? "—"} · Target {plan.target ?? "—"} ({plan.target_source?.source ?? "source unavailable"})</p>}
      </summary>
      <div className="mt-4 border-t pt-3 text-xs">
        {record.decision === "take" && withPaper && <PracticePaperPlan recordId={record.id} onState={setPaper} />}
        <dl className="mt-3 grid gap-2 sm:grid-cols-2">
          <div><dt className="text-muted-foreground">Opportunity</dt><dd className="break-all">{record.opportunity_id}</dd></div>
          {record.rationale && <div><dt className="text-muted-foreground">Rationale</dt><dd className="whitespace-pre-wrap">{record.rationale}</dd></div>}
          {record.wait_condition && <div><dt className="text-muted-foreground">Wait condition</dt><dd>{record.wait_condition}</dd></div>}
          {record.wait_expiry && <div><dt className="text-muted-foreground">Wait ends</dt><dd>{new Date(record.wait_expiry).toLocaleString("en-US", { timeZone: ET })} ET</dd></div>}
          <div><dt className="text-muted-foreground">Input cutoff</dt><dd>{new Date(record.input_cutoff).toLocaleString("en-US", { timeZone: ET })} ET</dd></div>
          <div><dt className="text-muted-foreground">Evidence SHA-256</dt><dd className="break-all">{record.evidence_sha256}</dd></div>
          <div><dt className="text-muted-foreground">Record SHA-256</dt><dd className="break-all">{record.record_sha256}</dd></div>
        </dl>
        <pre className="mt-3 max-h-64 overflow-auto rounded bg-muted p-3 whitespace-pre-wrap">{JSON.stringify(record.evidence, null, 2)}</pre>
        {record.decision === "take" && <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-3 whitespace-pre-wrap">{JSON.stringify(record.plan, null, 2)}</pre>}
        <a href={`/charts?symbol=${encodeURIComponent(record.symbol)}`} className="mt-3 inline-block text-primary underline">Open {record.symbol} in Charts</a>
      </div>
    </details>
  );
}

export default function PracticeDecisions({ records, focusId }: { records: DecisionRecord[]; focusId?: string }) {
  const paperIds = new Set(records.filter((r) => r.decision === "take").slice(0, PAPER_FETCH_LIMIT).map((r) => r.id));
  if (focusId && records.some((r) => r.id === focusId && r.decision === "take")) paperIds.add(focusId);
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Practice decisions</h2>
        <p className="mt-1 text-xs text-muted-foreground">Frozen choices and evidence. Practice only; a TAKE is a paper plan once you arm it, never a real order.</p>
      </div>
      <PracticeDecisionForm />
      {records.length === 0 ? (
        <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">No saved decisions yet.</div>
      ) : records.map((record) => (
        <DecisionCard key={record.id} record={record} focused={record.id === focusId} withPaper={paperIds.has(record.id)} />
      ))}
    </section>
  );
}
