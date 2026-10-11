"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import AdvisorReceiptView, { advisorStamp, type AdvisorReceipt } from "./AdvisorReceiptView";

type OwnerReview = {
  schema_version: "advisor-owner-review-v1"; demo_only: true;
  request: { assignment_id: string; run_id: string; packet_sha256: string; request_sha256: string; question: string; user_plan: string; requested_at: string; expires_at: string; comparison: string; transport: string; packet: Record<string, unknown> };
  receipt: AdvisorReceipt | null; assignment: { enabled: boolean; expired: boolean }; read_at: string;
};

export default function AdvisorOwnerReview() {
  const [value, setValue] = useState<OwnerReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    const current = ++sequence.current;
    controller.current?.abort();
    const pending = new AbortController(); controller.current = pending;
    setLoading(true); setError(""); setValue(null);
    try {
      const response = await fetch("/api/advisor-owner", { cache: "no-store", redirect: "error", signal: pending.signal });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not read the saved advisor record.");
      if (body.schema_version !== "advisor-owner-review-v1" || body.demo_only !== true) throw new Error("Unsupported advisor record.");
      if (current === sequence.current) setValue(body);
    } catch (err) {
      if (current === sequence.current && !pending.signal.aborted) setError(err instanceof Error ? err.message : "Could not read the saved advisor record.");
    } finally { if (current === sequence.current) setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void reload(); });
    return () => { active = false; sequence.current += 1; controller.current?.abort(); };
  }, [reload]);
  return <section className="mx-auto max-w-4xl space-y-4" data-testid="advisor-owner-review">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-xl font-semibold">Advisor review</h1><p className="text-sm text-amber-800">INVENTED DEMO ONLY · INDEPENDENCE UNVERIFIED · OWNER READ ONLY</p><p className="text-sm text-muted-foreground">One frozen request from the isolated advisor ledger. No journal records, writes or advisor retry are sent.</p></div><button type="button" onClick={() => void reload()} disabled={loading} className="min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">Reload advisor record</button></div>
    {loading && <p role="status">Reading the isolated advisor record…</p>}
    {error && <div role="alert" className="rounded border border-red-600 p-3 break-words"><p>{error}</p><p className="text-sm">No saved record is displayed. Reload to read it again; no write or retry was sent.</p></div>}
    {value && <>
      <div className="rounded border bg-card p-3 text-sm"><p>Read {advisorStamp(value.read_at)} · original request expires {advisorStamp(value.request.expires_at)}</p><p>{!value.assignment.enabled ? "Advisor assignment revoked. Owner recovery remains available." : value.assignment.expired ? "Advisor assignment expired. Owner recovery remains available." : "Advisor assignment active."}</p><p>Request origin {value.request.transport} · saved answer {value.receipt?.transport ?? "not received"} · comparison {value.request.comparison}</p><p>{value.request.comparison === "assisted" ? "Advisor-first disclosure · assisted comparison." : "Human choices frozen before disclosure · independence remains unverified."}</p><p>Missing inputs: {Array.isArray(value.request.packet.missing) ? value.request.packet.missing.map(String).join(" · ") : "Unavailable"}</p><p className="text-xs text-muted-foreground">Model, usage and cost unavailable. Hashes bind saved content; interpretation and trading usefulness remain unverified.</p></div>
      <AdvisorReceiptView packet={value.request.packet} question={value.request.question} userPlan={value.request.user_plan} requestedAt={value.request.requested_at} receivedAt={value.receipt?.received_at ?? null} receipt={value.receipt} answer={value.receipt?.submitted_output.answer ?? null} />
      <details><summary className="min-h-11 cursor-pointer text-sm">Frozen request identity and packet</summary><dl className="grid gap-2 text-xs sm:grid-cols-2">{(["assignment_id", "run_id", "packet_sha256", "request_sha256"] as const).map(key => <div key={key}><dt>{key}</dt><dd className="break-all">{value.request[key]}</dd></div>)}</dl><pre data-testid="advisor-owner-request" className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{JSON.stringify(value.request, null, 2)}</pre></details>
      <p className="text-sm text-muted-foreground">After an uncertain advisor save, compare the complete saved receipt and submitted answer before any explicit advisor retry. An absent receipt is not proof a pending save failed. Reopening this page retrieves the ledger again.</p>
    </>}
  </section>;
}
