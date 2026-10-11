type Fact = { name?: string; fact_name?: string; value?: unknown; unit?: string; source?: string; formed_at?: string; observed_at?: string };
type Opportunity = { id?: string; opportunity_id?: string; symbol?: string; price_facts?: Fact[]; context?: { price_facts?: Fact[] } };
export type AdvisorAnswer = { summary: string; interpretation: string; risks: unknown; conditions: unknown; gaps: unknown; references: { opportunity_id: string; fact_name: string }[] };
export type AdvisorReceipt = { version: string; assignment_id: string; run_id: string; packet_sha256: string; request_sha256: string; received_at: string; transport: string; receipt_sha256: string; submitted_output: { version: string; assignment_id: string; run_id: string; packet_sha256: string; request_sha256: string; answer: AdvisorAnswer } };
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export const advisorStamp = (value?: string | null) => value ? `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" })} ET` : "Unavailable";

export default function AdvisorReceiptView({ packet, question, userPlan, requestedAt, receivedAt, receipt, answer }: {
  packet: Record<string, unknown>; question: string; userPlan: string; requestedAt: string; receivedAt: string | null;
  receipt: AdvisorReceipt | null | undefined; answer: AdvisorAnswer | null;
}) {
  const opportunities = Array.isArray(packet.opportunities) ? packet.opportunities as Opportunity[] : [];
  return <article className="space-y-2 rounded border p-3 break-words" data-testid="advisor-saved-answer">
    <h4 className="font-semibold">Saved advisor response · requested {advisorStamp(requestedAt)} · received {advisorStamp(receivedAt)}</h4>
    <p className="text-xs">Question: {question}</p><p className="text-xs">User plan: {userPlan}</p>
    {receipt && <details><summary className="cursor-pointer text-sm">Exact saved advisor receipt</summary><pre data-testid="advisor-receipt" className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{pretty(receipt)}</pre></details>}
    {answer ? <>
      <p className="text-xs font-semibold text-amber-800">Advisor interpretation · {receipt?.transport ?? "manual-local"} · caller unverified</p>
      <p><strong>Summary:</strong> {answer.summary}</p><p><strong>Interpretation:</strong> {answer.interpretation}</p>
      {(["risks", "conditions", "gaps"] as const).map(field => <div key={field}><strong>{field === "conditions" ? "Proposed conditions" : field === "risks" ? "Risks" : "Gaps"}</strong><pre className="whitespace-pre-wrap break-words text-sm">{typeof answer[field] === "string" ? answer[field] : pretty(answer[field])}</pre></div>)}
      <div><strong>Source citations</strong><ul className="list-disc space-y-1 pl-5 text-sm">{answer.references.map((reference, index) => {
        const opportunity = opportunities.find(item => (item.id ?? item.opportunity_id) === reference.opportunity_id);
        const fact = (opportunity?.price_facts ?? opportunity?.context?.price_facts ?? []).find(item => (item.name ?? item.fact_name) === reference.fact_name);
        return <li key={`${reference.opportunity_id}-${reference.fact_name}-${index}`} className="break-words">{opportunity && fact ? <><strong>{opportunity.symbol ?? reference.opportunity_id}</strong> · {reference.fact_name}: {String(fact.value ?? "value unavailable")} {fact.unit ?? ""} · {fact.source ?? "source unavailable"} · formed {advisorStamp(fact.formed_at)} · observed {advisorStamp(fact.observed_at)}</> : <span className="text-amber-700">Unresolved packet citation: {reference.opportunity_id} · {reference.fact_name}</span>}</li>;
      })}</ul></div>
    </> : <p className="text-sm">No advisor response has been received.</p>}
  </article>;
}
