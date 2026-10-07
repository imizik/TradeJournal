import type { DecisionRecord } from "@/lib/api";
import PracticeDecisionForm from "@/components/PracticeDecisionForm";

export default function PracticeDecisions({ records }: { records: DecisionRecord[] }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Practice decisions</h2>
        <p className="mt-1 text-xs text-muted-foreground">Frozen choices and evidence. Every record is a draft; nothing is armed.</p>
      </div>
      <PracticeDecisionForm />
      {records.length === 0 ? (
        <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">No saved decisions yet.</div>
      ) : records.map((record) => {
        const plan = record.plan as { trigger_level?: number; stop?: number; target?: number; target_source?: { source?: string } };
        return (
          <details key={record.id} className="rounded-lg border bg-card p-4">
            <summary className="cursor-pointer list-none">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold">{record.symbol} · {record.decision.toUpperCase()}</span>
                <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700">PRACTICE · UNARMED</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{record.actor} · received {new Date(record.received_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET</p>
              {record.decision === "take" && <p className="mt-2 text-sm">Trigger {plan.trigger_level ?? "—"} · Stop {plan.stop ?? "—"} · Target {plan.target ?? "—"} ({plan.target_source?.source ?? "source unavailable"})</p>}
            </summary>
            <div className="mt-4 border-t pt-3 text-xs">
              <dl className="grid gap-2 sm:grid-cols-2">
                <div><dt className="text-muted-foreground">Opportunity</dt><dd>{record.opportunity_id}</dd></div>
                <div><dt className="text-muted-foreground">Input cutoff</dt><dd>{new Date(record.input_cutoff).toLocaleString("en-US", { timeZone: "America/New_York" })} ET</dd></div>
                <div><dt className="text-muted-foreground">Evidence SHA-256</dt><dd className="break-all">{record.evidence_sha256}</dd></div>
                <div><dt className="text-muted-foreground">Record SHA-256</dt><dd className="break-all">{record.record_sha256}</dd></div>
              </dl>
              <pre className="mt-3 max-h-64 overflow-auto rounded bg-muted p-3 whitespace-pre-wrap">{JSON.stringify(record.evidence, null, 2)}</pre>
              {record.decision === "take" && <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-3 whitespace-pre-wrap">{JSON.stringify(record.plan, null, 2)}</pre>}
              <a href={`/charts?symbol=${encodeURIComponent(record.symbol)}`} className="mt-3 inline-block text-primary underline">Open {record.symbol} in Charts</a>
            </div>
          </details>
        );
      })}
    </section>
  );
}
