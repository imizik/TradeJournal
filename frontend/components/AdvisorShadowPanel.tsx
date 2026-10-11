"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { apiUrl } from "@/lib/api";
import AdvisorReceiptView, { type AdvisorAnswer as Answer, type AdvisorReceipt } from "./AdvisorReceiptView";

type AdvisorRequest = { question: string; user_plan: string };
type ImportEnvelope = { version: string; assignment_id: string; run_id: string; packet_sha256: string; request_sha256: string; answer: Answer };
type AdvisorState = {
  version?: string;
  export?: ExportedPacket;
  receipt?: AdvisorReceipt | null;
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
  version: string;
  assignment_id: string;
  run_id: string;
  request_sha256: string;
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

function validateEnvelope(value: unknown, exported: ExportedPacket): ImportEnvelope {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Paste Jo's complete JSON envelope.");
  const envelope = value as Record<string, unknown>;
  const keys = ["version", "assignment_id", "run_id", "packet_sha256", "request_sha256"] as const;
  if (Object.keys(envelope).sort().join() !== [...keys, "answer"].sort().join() || keys.some((key) => envelope[key] !== exported[key])) {
    throw new Error("Answer identity must match this saved assignment, run, packet and request exactly.");
  }
  const answer = validateAnswer(envelope.answer);
  if (!answer.references.length) throw new Error("Cite at least one original opportunity_id and fact_name pair.");
  return { ...envelope, answer } as ImportEnvelope;
}

// Object key order does not change the submitted JSON content.
function exactContent(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(exactContent).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${exactContent(item)}`).join(",")}}`;
  return JSON.stringify(value);
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
  const currentRun = useRef(runId);
  useEffect(() => { currentRun.current = runId; }, [runId]);

  const reload = useCallback(async () => {
    if (currentRun.current !== runId) return;
    const sequence = ++reloadSequence.current;
    await Promise.resolve();
    if (sequence !== reloadSequence.current) return;
    setLoading(true);
    setError("");
    try {
      const next = await request<Snapshot>(`/advisor-shadow/runs/${encodeURIComponent(runId)}`);
      if (sequence === reloadSequence.current) {
        setSnapshot(next);
        setExported(next.advisor?.export ?? null);
        setQuestion(next.advisor?.request.question ?? "");
        setUserPlan(next.advisor?.request.user_plan ?? "");
      }
    } catch (err) {
      if (sequence === reloadSequence.current) { setSnapshot(null); setError(err instanceof Error ? err.message : "Could not load the advisor-shadow run."); }
    } finally { if (sequence === reloadSequence.current) setLoading(false); }
  }, [runId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) { setExported(null); setAnswerJson(""); setSuccess(""); setBusy(false); void reload(); } });
    return () => { active = false; reloadSequence.current += 1; };
  }, [reload]);

  async function exportForAdvisor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    try {
      const result = await request<ExportedPacket>(`/advisor-shadow/runs/${encodeURIComponent(runId)}/advisor-handoff`, { question, user_plan: userPlan });
      if (currentRun.current !== runId) return;
      setExported(result);
      setSuccess(`Advisor packet saved. Comparison: ${result.comparison}. Independence remains unverified.`);
      await onRefresh();
      await reload();
    } catch (err) {
      if (currentRun.current !== runId) return;
      try {
        const saved = await request<Snapshot>(`/advisor-shadow/runs/${encodeURIComponent(runId)}`);
        if (currentRun.current !== runId) return;
        setSnapshot(saved); setExported(saved.advisor?.export ?? null);
        setQuestion(saved.advisor?.request.question ?? ""); setUserPlan(saved.advisor?.request.user_plan ?? "");
        if (saved.advisor?.export && saved.advisor.request.question === question && saved.advisor.request.user_plan === userPlan) {
          setSuccess("Saved handoff recovered from the owner record. No retry was sent.");
          await onRefresh();
        } else if (saved.advisor?.export) setError("A different immutable advisor request is already saved. Review the saved handoff; this request was not accepted.");
        else setError(`${err instanceof Error ? err.message : "Export result uncertain."} No matching saved handoff found. Reload the record before a manual retry.`);
      } catch { if (currentRun.current === runId) setError("Export result uncertain. Reload the owner record before a manual retry; no retry was sent."); }
    }
    finally { if (currentRun.current === runId) setBusy(false); }
  }

  async function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setSuccess("");
    let envelope: ImportEnvelope | Answer;
    try {
      envelope = exported ? validateEnvelope(JSON.parse(answerJson), exported) : validateAnswer(JSON.parse(answerJson));
    }
    catch (err) { setError(err instanceof Error ? err.message : "Enter a valid structured answer."); setBusy(false); return; }
    try {
      await request(`/advisor-shadow/runs/${encodeURIComponent(runId)}/${exported ? "advisor-import" : "advisor-output"}`, envelope);
      if (currentRun.current !== runId) return;
      setSuccess("Advisor response saved for owner review.");
      await reload();
      await onRefresh();
    } catch (err) {
      if (currentRun.current !== runId) return;
      // A missing response is ambiguous: read the immutable receipt before any retry.
      try {
        const saved = await request<Snapshot>(`/advisor-shadow/runs/${encodeURIComponent(runId)}`);
        if (currentRun.current !== runId) return;
        setSnapshot(saved); setExported(saved.advisor?.export ?? null);
        setQuestion(saved.advisor?.request.question ?? ""); setUserPlan(saved.advisor?.request.user_plan ?? "");
        const stored = exported ? saved.advisor?.receipt?.submitted_output : saved.advisor?.response;
        if (stored && exactContent(stored) === exactContent(envelope)) {
          setSuccess("Saved advisor receipt recovered from the owner record. No retry was sent.");
          await onRefresh();
        } else if (stored) setError("A different immutable advisor answer is already saved. Review the saved receipt; this answer was not accepted.");
        else setError(`${err instanceof Error ? err.message : "Save result uncertain."} No saved receipt found. You may retry manually after checking this record; no retry was sent.`);
      } catch { if (currentRun.current === runId) setError("Save result uncertain. Reload the owner record before a manual retry; no retry was sent."); }
    }
    finally { if (currentRun.current === runId) setBusy(false); }
  }

  return <section className="space-y-3 rounded-lg border border-amber-500/50 bg-card p-4" data-testid="advisor-shadow-panel">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold">Jo advisor handoff</h3><p className="text-sm text-amber-800">DEMO ONLY · INDEPENDENCE UNVERIFIED · {snapshot?.advisor?.receipt?.transport ?? "manual transport"}</p><p className="text-xs text-muted-foreground">Caller-supplied interpretation is unverified. No backend inference runs. Model, usage, and cost are unavailable.</p></div><button type="button" onClick={() => void reload()} disabled={loading || busy} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Reload advisor record</button></div>
    {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
    {success && <p role="status" className="break-words text-sm text-emerald-700">{success}</p>}
    {loading && <p className="text-sm text-muted-foreground">Loading this run’s advisor record…</p>}
    {!loading && snapshot && <>
      <div className="grid gap-1 rounded border p-3 text-xs sm:grid-cols-2"><p>Assignment <strong className="break-all">{snapshot.assignment_id}</strong></p><p>Expires {stamp(snapshot.expires_at)}</p><p>Packet SHA-256 <strong className="break-all">{snapshot.packet_sha256}</strong></p><p>Independence <strong>{snapshot.independence}</strong> · {snapshot.advisor?.receipt?.transport ?? snapshot.transport}</p></div>
      <details><summary className="cursor-pointer text-sm">Exact neutral packet</summary><pre data-testid="advisor-packet" className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{pretty(snapshot.packet)}</pre></details>
      <form onSubmit={exportForAdvisor} className="grid gap-2 rounded border p-3" data-testid="advisor-export-form">
        <h4 className="text-sm font-semibold">Prepare advisor packet</h4>
        <p className="text-xs text-amber-800">Creating this export durably marks the run assisted before the packet is exposed, unless all five human choices are already frozen. Use an invented scenario for both question and plan; exclude real journal, account and credential details. This saves locally. Copying to signed-in Jo shares this invented packet, question and plan with Jo; send only after owner approval.</p>
        <label className="text-sm">Your question<textarea required maxLength={2000} value={question} readOnly={!!snapshot.advisor} onChange={(event) => setQuestion(event.target.value)} rows={2} className="mt-1 w-full rounded border bg-background p-2" /></label>
        <label className="text-sm">Your plan<textarea required maxLength={2000} value={userPlan} readOnly={!!snapshot.advisor} onChange={(event) => setUserPlan(event.target.value)} rows={3} className="mt-1 w-full rounded border bg-background p-2" /></label>
        <button type="submit" disabled={busy || !!snapshot.advisor || !question.trim() || !userPlan.trim()} className="w-fit rounded border px-3 py-2 text-sm disabled:opacity-50">{busy ? "Saving…" : "Save and expose advisor packet"}</button>
      </form>
      {exported && <div className="space-y-2 rounded border border-sky-500/40 p-3"><h4 className="text-sm font-semibold">Packet for manual copy</h4><p className="text-xs">Copy the complete JSON to signed-in Jo only after approval, then paste Jo’s complete JSON answer envelope below. A separately approved advisor connector can deliver this saved request; activation is an owner setup step. Hashes bind saved content; they do not verify Jo’s interpretation.</p><textarea readOnly aria-label="Advisor packet for copying" value={pretty(exported)} rows={16} className="w-full rounded border bg-background p-2 font-mono text-xs" data-testid="advisor-export-packet" /></div>}
      <form onSubmit={submitAnswer} className="grid gap-2 rounded border p-3" data-testid="advisor-answer-form">
        <h4 className="text-sm font-semibold">Paste structured advisor answer</h4>
        <p className="text-xs text-muted-foreground">Echo version, assignment_id, run_id, packet_sha256 and request_sha256 exactly; put summary, interpretation, risks, conditions, gaps and original fact references in answer. Legacy Phase-1 records still accept their original raw answer. Caller interpretation stays unverified.</p>
        <textarea required maxLength={65536} value={answerJson} onChange={(event) => setAnswerJson(event.target.value)} rows={10} placeholder={exported ? "Paste Jo’s complete JSON envelope matching answer_contract, including identity and answer." : "Paste the original Phase-1 structured answer JSON."} className="w-full rounded border bg-background p-2 font-mono text-xs" />
        <button type="submit" disabled={busy || !snapshot.advisor || !answerJson.trim()} className="w-fit rounded border px-3 py-2 text-sm disabled:opacity-50">{busy ? "Saving…" : "Save advisor response"}</button>
      </form>
      {snapshot.advisor && <AdvisorReceiptView packet={snapshot.packet} question={snapshot.advisor.request.question} userPlan={snapshot.advisor.request.user_plan} requestedAt={snapshot.advisor.requested_at} receivedAt={snapshot.advisor.received_at} receipt={snapshot.advisor.receipt} answer={snapshot.advisor.response} />}
    </>}
  </section>;
}
