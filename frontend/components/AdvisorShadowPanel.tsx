"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiUrl } from "@/lib/api";

type Fact = { name?: string; fact_name?: string; value?: unknown; unit?: string; source?: string; formed_at?: string; observed_at?: string };
type PacketOpportunity = { id?: string; opportunity_id?: string; symbol?: string; price_facts?: Fact[]; context?: { price_facts?: Fact[] } };
type Answer = { summary: string; interpretation: string; risks: unknown; conditions: unknown; gaps: unknown; references: { opportunity_id: string; fact_name: string }[] };
type AdvisorRequest = { question: string; user_plan: string };
type AdvisorState = {
  request: AdvisorRequest;
  requested_at: string;
  comparison?: string;
  response: Answer | null;
  received_at: string | null;
};
type Snapshot = {
  packet: Record<string, unknown>;
  packet_sha256: string;
  assignment_id: string;
  expires_at: string;
  advisor: AdvisorState | null;
  independence: string;
  transport: string;
  demo_only: boolean;
};
type ExportedPacket = {
  packet: Record<string, unknown>;
  packet_sha256: string;
  question: string;
  user_plan: string;
  comparison: string;
  instructions: string;
  answer_contract: Record<string, unknown>;
};

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const result = await response.json(); detail = result.detail ?? detail; } catch { /* keep status */ }
    throw new Error(detail);
  }
  return response.json();
}

const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const stamp = (value?: string | null) => value ? `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" })} ET` : "Unavailable";
const listText = (value: unknown) => typeof value === "string" ? value : pretty(value);

function validateAnswer(value: unknown): Answer {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Answer must be a JSON object.");
  const answer = value as Record<string, unknown>;
  if (typeof answer.summary !== "string" || typeof answer.interpretation !== "string") throw new Error("Answer needs string summary and interpretation fields.");
  for (const field of ["summary", "interpretation", "risks", "conditions", "gaps"]) {
    if (typeof answer[field] !== "string" || !answer[field].trim()) throw new Error(`${field} must be a nonempty string.`);
  }
  if (!Array.isArray(answer.references) || answer.references.length > 10 || !answer.references.every((item) => item && typeof item === "object" && typeof item.opportunity_id === "string" && typeof item.fact_name === "string")) {
    throw new Error("references must be a list of {opportunity_id, fact_name} objects.");
  }
  return answer as unknown as Answer;
}

function citations(packet: Record<string, unknown>, references: Answer["references"]) {
  const opportunities = Array.isArray(packet.opportunities) ? packet.opportunities as PacketOpportunity[] : [];
  return references.map((reference, index) => {
    const opportunity = opportunities.find((item) => (item.id ?? item.opportunity_id) === reference.opportunity_id);
    const facts = opportunity?.price_facts ?? opportunity?.context?.price_facts ?? [];
    const fact = facts.find((item) => (item.name ?? item.fact_name) === reference.fact_name);
    return <li key={`${reference.opportunity_id}-${reference.fact_name}-${index}`} className="break-words">
      {opportunity && fact ? <><strong>{opportunity.symbol ?? reference.opportunity_id}</strong> · {reference.fact_name}: {String(fact.value ?? "value unavailable")} {fact.unit ?? ""} · {fact.source ?? "source unavailable"} · formed {stamp(fact.formed_at)} · observed {stamp(fact.observed_at)}</> : <span className="text-amber-700">Unresolved packet citation: {reference.opportunity_id} · {reference.fact_name}</span>}
    </li>;
  });
}

export default function AdvisorShadowPanel({ runId, onRefresh }: { runId: string; onRefresh: () => Promise<unknown> }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [exported, setExported] = useState<ExportedPacket | null>(null);
  const [question, setQuestion] = useState("");
  const [userPlan, setUserPlan] = useState("");
  const [answerJson, setAnswerJson] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const reloadSequence = useRef(0);

  const reload = useCallback(async () => {
    const sequence = ++reloadSequence.current;
    await Promise.resolve();
    if (sequence !== reloadSequence.current) return;
    setLoading(true);
    setError("");
    try {
      const next = await request<Snapshot>(`/advisor-shadow/runs/${encodeURIComponent(runId)}`);
      if (sequence === reloadSequence.current) setSnapshot(next);
    } catch (err) {
      if (sequence === reloadSequence.current) { setSnapshot(null); setError(err instanceof Error ? err.message : "Could not load the advisor-shadow run."); }
    } finally { if (sequence === reloadSequence.current) setLoading(false); }
  }, [runId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void reload(); });
    return () => { active = false; reloadSequence.current += 1; };
  }, [reload]);

  async function exportForAdvisor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    try {
      const result = await request<ExportedPacket>(`/advisor-shadow/runs/${encodeURIComponent(runId)}/advisor-packet`, { question, user_plan: userPlan });
      setExported(result);
      setSuccess(`Advisor packet saved. Comparison: ${result.comparison}. Independence remains unverified.`);
      await onRefresh();
      await reload();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create the advisor packet."); }
    finally { setBusy(false); }
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    let answer: Answer;
    try { answer = validateAnswer(JSON.parse(answerJson)); }
    catch (err) { setError(err instanceof Error ? err.message : "Enter a valid structured answer."); setBusy(false); return; }
    try {
      await request(`/advisor-shadow/runs/${encodeURIComponent(runId)}/advisor-output`, answer);
      setSuccess("Advisor response saved for owner review.");
      await reload();
      await onRefresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the advisor response."); }
    finally { setBusy(false); }
  }

  return <section className="space-y-3 rounded-lg border border-amber-500/50 bg-card p-4" data-testid="advisor-shadow-panel">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold">Manual advisor shadow</h3><p className="text-sm text-amber-800">DEMO ONLY · INDEPENDENCE UNVERIFIED · manual transport</p><p className="text-xs text-muted-foreground">Caller-supplied interpretation is unverified. No backend inference runs. Model, usage, and cost are unavailable.</p></div><button type="button" onClick={() => void reload()} disabled={loading || busy} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Reload advisor record</button></div>
    {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
    {success && <p role="status" className="break-words text-sm text-emerald-700">{success}</p>}
    {loading && <p className="text-sm text-muted-foreground">Loading this run’s advisor record…</p>}
    {!loading && snapshot && <>
      <div className="grid gap-1 rounded border p-3 text-xs sm:grid-cols-2"><p>Assignment <strong className="break-all">{snapshot.assignment_id}</strong></p><p>Expires {stamp(snapshot.expires_at)}</p><p>Packet SHA-256 <strong className="break-all">{snapshot.packet_sha256}</strong></p><p>Independence <strong>{snapshot.independence}</strong> · {snapshot.transport}</p></div>
      <details><summary className="cursor-pointer text-sm">Exact neutral packet</summary><pre data-testid="advisor-packet" className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{pretty(snapshot.packet)}</pre></details>
      <form onSubmit={exportForAdvisor} className="grid gap-2 rounded border p-3" data-testid="advisor-export-form">
        <h4 className="text-sm font-semibold">Prepare advisor packet</h4>
        <p className="text-xs text-amber-800">Creating this export durably marks the run assisted before the packet is exposed, unless all five human choices are already frozen. Copy the returned packet to the separate manual advisor workflow.</p>
        <label className="text-sm">Your question<textarea required maxLength={2000} value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} className="mt-1 w-full rounded border bg-background p-2" /></label>
        <label className="text-sm">Your plan<textarea required maxLength={2000} value={userPlan} onChange={(event) => setUserPlan(event.target.value)} rows={3} className="mt-1 w-full rounded border bg-background p-2" /></label>
        <button type="submit" disabled={busy || !question.trim() || !userPlan.trim()} className="w-fit rounded border px-3 py-2 text-sm disabled:opacity-50">{busy ? "Saving…" : "Save and expose advisor packet"}</button>
      </form>
      {exported && <div className="space-y-2 rounded border border-sky-500/40 p-3"><h4 className="text-sm font-semibold">Packet for manual copy</h4><p className="text-xs">Question and plan are included. Copy this packet into your manual advisor workflow; only shadow output uses the loopback gateway.</p><textarea readOnly aria-label="Advisor packet for copying" value={pretty(exported)} rows={16} className="w-full rounded border bg-background p-2 font-mono text-xs" data-testid="advisor-export-packet" /></div>}
      <form onSubmit={submitAnswer} className="grid gap-2 rounded border p-3" data-testid="advisor-answer-form">
        <h4 className="text-sm font-semibold">Paste structured advisor answer</h4>
        <p className="text-xs text-muted-foreground">Expected fields: summary, interpretation, risks, conditions, gaps, and references containing opportunity_id and fact_name. The answer is stored as caller-supplied text; cited facts must be in the packet.</p>
        <textarea required maxLength={65536} value={answerJson} onChange={(event) => setAnswerJson(event.target.value)} rows={10} placeholder='{"summary":"…","interpretation":"…","risks":"…","conditions":"…","gaps":"…","references":[]}' className="w-full rounded border bg-background p-2 font-mono text-xs" />
        <button type="submit" disabled={busy || !answerJson.trim()} className="w-fit rounded border px-3 py-2 text-sm disabled:opacity-50">{busy ? "Saving…" : "Save advisor response"}</button>
      </form>
      {snapshot.advisor && <article className="space-y-2 rounded border p-3" data-testid="advisor-saved-answer"><h4 className="font-semibold">Saved advisor response · requested {stamp(snapshot.advisor.requested_at)} · received {stamp(snapshot.advisor.received_at)}</h4><p className="text-xs">Question: {snapshot.advisor.request.question}</p><p className="text-xs">User plan: {snapshot.advisor.request.user_plan}</p>{snapshot.advisor.response ? <><p className="text-xs font-semibold text-amber-800">Manually supplied interpretation · caller unverified</p><p><strong>Summary:</strong> {snapshot.advisor.response.summary}</p><p><strong>Interpretation:</strong> {snapshot.advisor.response.interpretation}</p><div><strong>Risks</strong><pre className="whitespace-pre-wrap text-sm">{listText(snapshot.advisor.response.risks)}</pre></div><div><strong>Proposed conditions</strong><pre className="whitespace-pre-wrap text-sm">{listText(snapshot.advisor.response.conditions)}</pre></div><div><strong>Gaps</strong><pre className="whitespace-pre-wrap text-sm">{listText(snapshot.advisor.response.gaps)}</pre></div><div><strong>Source citations</strong><ul className="list-disc space-y-1 pl-5 text-sm">{citations(snapshot.packet, snapshot.advisor.response.references)}</ul></div></> : <p className="text-sm">No advisor response has been received.</p>}</article>}
    </>}
  </section>;
}
