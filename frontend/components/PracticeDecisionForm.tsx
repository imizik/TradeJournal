"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { api, type DecisionContext } from "@/lib/api";

export default function PracticeDecisionForm() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [symbol, setSymbol] = useState("");
  const [choice, setChoice] = useState<"take" | "wait" | "skip">("skip");
  const [rationale, setRationale] = useState("");
  const [waitCondition, setWaitCondition] = useState("");
  const [waitExpiry, setWaitExpiry] = useState("");
  const [planText, setPlanText] = useState("");
  const [context, setContext] = useState<DecisionContext | null>(null);
  const [error, setError] = useState("");
  const [savedId, setSavedId] = useState("");
  const [saving, setSaving] = useState(false);
  const operationId = useRef("");
  const contextOperationId = useRef("");
  const contextSymbol = useRef("");
  const sessionCalendar = context?.packet.session_calendar as { status?: string; close?: number | null; description?: string } | undefined;

  function edited() {
    operationId.current = "";
  }

  async function freeze() {
    setError("");
    setSavedId("");
    setContext(null);
    try {
      const normalizedSymbol = symbol.trim().toUpperCase();
      if (!contextOperationId.current || contextSymbol.current !== normalizedSymbol) {
        contextOperationId.current = crypto.randomUUID();
        contextSymbol.current = normalizedSymbol;
      }
      const value = await api.freezeDecisionContext(normalizedSymbol, contextOperationId.current);
      setContext(value);
      contextOperationId.current = "";
      contextSymbol.current = "";
      operationId.current = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not freeze market context.");
    }
  }

  async function save() {
    setError("");
    setSavedId("");
    if (!context) return setError("Freeze market context before saving a decision.");
    let plan: Record<string, unknown> | undefined;
    if (choice === "take") {
      try { plan = JSON.parse(planText) as Record<string, unknown>; }
      catch { return setError("TAKE plan must be valid JSON."); }
    }
    if (saving) return;
    setSaving(true);
    if (!operationId.current) operationId.current = crypto.randomUUID();
    try {
      const record = await api.createDecision({
        operation_id: operationId.current,
        opportunity_id: `${context.symbol}:${context.captured_at}`,
        actor: "human", decision: choice, symbol: context.symbol,
        context_id: context.context_id, rationale,
        wait_condition: choice === "wait" ? waitCondition : undefined,
        wait_expiry: choice === "wait" ? new Date(waitExpiry).toISOString() : undefined,
        plan,
      });
      setSavedId(record.id);
      setContext(null);
      setPlanText("");
      operationId.current = "";
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the decision. The choice was not recorded.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="rounded-lg border bg-card p-4">
      <summary className="cursor-pointer font-medium">Save a human decision</summary>
      <div className="mt-4 grid gap-3 text-sm">
        <label className="grid gap-1">Symbol
          <input value={symbol} onChange={(e) => { setSymbol(e.target.value.toUpperCase()); setContext(null); edited(); }} maxLength={15} className="rounded border bg-background px-3 py-2" placeholder="SPY" />
        </label>
        <button onClick={freeze} disabled={!symbol.trim()} className="w-fit rounded border px-3 py-2 disabled:opacity-50">Freeze market context</button>
        {context && <div className="rounded border bg-muted/30 p-3 text-xs">
          <p>Saved server context for {context.symbol} · {new Date(context.captured_at).toLocaleString("en-US", { timeZone: "America/New_York" })} ET · {context.provider}</p>
          <p>Session calendar: {sessionCalendar?.status ?? "unavailable"}{sessionCalendar?.close != null ? ` · closes ${Math.floor(sessionCalendar.close / 60)}:${String(sessionCalendar.close % 60).padStart(2, "0")} ET` : ""}{sessionCalendar?.description ? ` · ${sessionCalendar.description}` : ""}</p>
          <p className="mt-1 break-all text-muted-foreground">Context {context.context_sha256}</p>
          <p className="mt-2">Timestamped minute facts available for plans: {context.price_facts.length}</p>
          {choice === "take" && <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap">{context.price_facts.slice(-12).map((f) => `${f.name} = ${f.value} (${f.unit}, ${f.formed_at})`).join("\n")}</pre>}
        </div>}
        <label className="grid gap-1">Your choice
          <select value={choice} onChange={(e) => { setChoice(e.target.value as typeof choice); edited(); }} className="rounded border bg-background px-3 py-2">
            <option value="take">TAKE · practice draft</option><option value="wait">WAIT</option><option value="skip">SKIP</option>
          </select>
        </label>
        {choice === "wait" && <>
          <label className="grid gap-1">What would change your decision?
            <input value={waitCondition} onChange={(e) => { setWaitCondition(e.target.value); edited(); }} className="rounded border bg-background px-3 py-2" />
          </label>
          <label className="grid gap-1">Waiting ends
            <input type="datetime-local" value={waitExpiry} onChange={(e) => { setWaitExpiry(e.target.value); edited(); }} className="rounded border bg-background px-3 py-2" />
          </label>
        </>}
        {choice !== "wait" && <label className="grid gap-1">Reason / notes
          <textarea value={rationale} onChange={(e) => { setRationale(e.target.value); edited(); }} maxLength={2000} rows={3} className="rounded border bg-background px-3 py-2" />
        </label>}
        {choice === "take" && <label className="grid gap-1">Practice plan JSON
          <textarea value={planText} onChange={(e) => { setPlanText(e.target.value); edited(); }} rows={9} className="rounded border bg-background px-3 py-2 font-mono text-xs" placeholder={'{"instrument":"stock","direction":"long","trigger":{"kind":"close_beyond_level","interval":"15m","session":"regular"},"trigger_level":0,"trigger_fact":"minute:0:c","stop":0,"stop_fact":"minute:0:l","target":0,"target_fact":"minute:0:h","entry_guard":{"min":0,"max":0},"expiry":"2026-10-08T15:00:00-04:00","max_holding_sessions":2,"freshness_limit_seconds":3600,"cost_model":{"version":"p0-cost-v1","slippage_bps":1,"slippage_per_share":0.01}}'} />
          <span className="text-xs text-muted-foreground">Prices must exactly match source facts above; the saved TAKE remains unarmed.</span>
        </label>}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        {savedId && <p role="status" className="text-sm text-emerald-700">Saved decision {savedId}.</p>}
        <button onClick={save} disabled={saving || pending || !context} className="w-fit rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">Save immutable decision</button>
      </div>
    </details>
  );
}
