"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import AdvisorReceiptView, { advisorStamp, type AdvisorReceipt } from "./AdvisorReceiptView";

type FrozenRequest = { assignment_id: string; question: string; user_plan: string; requested_at: string; expires_at: string; request_sha256: string; packet: Record<string, unknown> };
type RecordView = { request: FrozenRequest; receipt: AdvisorReceipt | null; status: string };
type Ledger = { selected: string | null; assignments: { assignment_id: string; question: string; requested_at: string; status: string }[]; record?: RecordView };

export default function AdvisorAssignments() {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [record, setRecord] = useState<RecordView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [question, setQuestion] = useState(""); const [plan, setPlan] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(true); const [error, setError] = useState("");
  const operation = useRef<{ id: string; question: string; plan: string } | null>(null);
  const sequence = useRef(0);
  const reload = useCallback(async (id: string | null = null) => {
    const seq = ++sequence.current;
    setBusy(true); setError(""); setRecord(null); setLedger(null);
    try {
      const response = await fetch(`/api/advisor-assignments${id ? `?assignment_id=${id}` : ""}`, { cache: "no-store", redirect: "error" });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Could not read saved questions.");
      if (seq === sequence.current) { setLedger(value); setRecord(value.record ?? null); setSelected(id); }
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Could not read saved questions."); }
    finally { if (seq === sequence.current) setBusy(false); }
  }, []);
  useEffect(() => { let active = true; queueMicrotask(() => { if (active) void reload(); }); return () => { active = false; sequence.current++; }; }, [reload]);
  async function change(body: object) {
    setBusy(true); setError(""); setRecord(null);
    try {
      const session = await fetch("/api/access/me", { cache: "no-store", redirect: "error" });
      if (!session.ok) throw new Error("Owner session unavailable. Reload before retrying.");
      const access = await session.json();
      const response = await fetch("/api/advisor-assignments", { method: "POST", headers: { "Content-Type": "application/json", "x-tj-csrf": access.csrf }, body: JSON.stringify(body), redirect: "error" });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Write could not be confirmed. Reload saved questions before retrying.");
      setLedger(value); setRecord(value.record); setSelected(value.record.request.assignment_id);
      if ("operation_id" in body) { operation.current = null; setQuestion(""); setPlan(""); setConfirmed(false); }
    } catch (err) { setLedger(null); setError(err instanceof Error ? err.message : "Write could not be confirmed. Reload saved questions before retrying."); }
    finally { setBusy(false); }
  }
  const pending = ledger?.assignments.some(a => a.assignment_id === ledger.selected && a.status === "pending");
  return <section className="mx-auto max-w-4xl space-y-4" data-testid="advisor-assignments">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-xl font-semibold">Advisor questions</h1><p className="text-sm text-amber-800">INVENTED DEMO ONLY · INDEPENDENCE UNVERIFIED</p><p className="text-sm text-muted-foreground">Assign one frozen question to the connected advisor, then reopen its saved answer here.</p></div><button onClick={() => void reload(selected)} disabled={busy} className="min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">Reload saved questions</button></div>
    <p className="text-sm text-muted-foreground">Original invented packet only. Real prices, calendar and news are missing. Model, usage and cost unavailable; cited interpretation and usefulness are unverified. Assignment allows access; it does not notify Jo or start reasoning.</p>
    {busy && <p role="status">Reading or saving advisor questions…</p>}
    {error && <p role="alert" className="rounded border border-red-600 p-3 break-words">{error}</p>}
    <form className="space-y-3 rounded border bg-card p-3" onSubmit={event => {
      event.preventDefault();
      if (!operation.current || operation.current.question !== question || operation.current.plan !== plan) operation.current = { id: crypto.randomUUID(), question, plan };
      void change({ operation_id: operation.current.id, question, user_plan: plan, invented_only: confirmed });
    }}>
      <h2 className="font-semibold">New invented question</h2>
      <label className="block text-sm">Question<textarea required maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} disabled={busy} className="mt-1 block min-h-20 w-full rounded border bg-background p-2" /></label>
      <label className="block text-sm">Your invented plan<textarea required maxLength={2000} value={plan} onChange={e => setPlan(e.target.value)} disabled={busy} className="mt-1 block min-h-20 w-full rounded border bg-background p-2" /></label>
      <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={busy} />Only invented scenario text; no real journal, account or credential details.</label>
      <p className="text-xs text-muted-foreground">The question and plan freeze when assigned. Advisor-first disclosure is assisted. Access expires in 30 minutes. Up to 20 questions in this fixture.</p>
      {pending && <p className="text-sm">Answer or revoke the pending assignment before creating another.</p>}
      <button type="submit" disabled={busy || !ledger || pending || !confirmed || !question.trim() || !plan.trim() || ledger.assignments.length >= 20} className="min-h-11 rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">Create and assign question</button>
    </form>
    {ledger && <div className="space-y-2"><h2 className="font-semibold">Saved questions</h2>{!ledger.assignments.length && <p className="text-sm">No questions yet. Create an invented question above.</p>}
      {ledger.assignments.map(item => <button key={item.assignment_id} disabled={busy} onClick={() => void reload(item.assignment_id)} aria-pressed={selected === item.assignment_id} className="block min-h-11 w-full rounded border bg-card p-3 text-left break-words"><span className="font-medium">{item.question}</span><span className="ml-2 rounded bg-muted px-2 py-1 text-xs">{item.status}</span><span className="block text-xs text-muted-foreground">{advisorStamp(item.requested_at)}{item.assignment_id === ledger.selected ? " · currently assigned" : ""}</span></button>)}
    </div>}
    {record && <div className="space-y-3" data-testid="advisor-assignment-record">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm">Status: {record.status} · original expiry {advisorStamp(record.request.expires_at)}</p>{record.status !== "revoked" && <button disabled={busy} onClick={() => void change({ revoke: record.request.assignment_id })} className="min-h-11 rounded border px-3 py-2 text-sm">Revoke assignment</button>}</div>
      {record.status === "revoked" && <p className="text-sm">Advisor access revoked. Previously saved answers remain available here.</p>}
      <AdvisorReceiptView packet={record.request.packet} question={record.request.question} userPlan={record.request.user_plan} requestedAt={record.request.requested_at} receivedAt={record.receipt?.received_at ?? null} receipt={record.receipt} answer={record.receipt?.submitted_output.answer ?? null} />
      <details><summary className="min-h-11 cursor-pointer text-sm">Immutable original request</summary><pre data-testid="assignment-original" className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{JSON.stringify(record.request, null, 2)}</pre></details>
    </div>}
    <p className="text-sm text-muted-foreground">After an uncertain write, reload and inspect the saved request and receipt before retrying. No automatic retries. Reloading never asks the advisor to answer again.</p>
  </section>;
}
