"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { advisorStamp } from "./AdvisorReceiptView";

type Status = {
  schema_version: "advisor-owner-status-v1"; checked_at: string;
  keys: { state: string; expires_at: string | null }; advisor: { state: string };
  assignment: { state: string; expires_at: string | null }; last_save_at: string | null;
};
type Tone = "ok" | "warn" | "bad";
type Line = { label: string; tone: Tone; text: string; recovery?: string; manage?: boolean };

const KEY_STEP = "Operator: run the key check, start the key refresh once, read its journal and confirm the 15-minute timer is enabled.";
const GRANT_STEP = "Operator: install key upkeep with the owner status grant and point the owner reader at the advisor config.";
const NEW_QUESTION = "Assign a new question when you want Jo again. Old answers stay readable here.";

function lines(value: Status): Line[] {
  const keysAt = advisorStamp(value.keys.expires_at);
  const keys: Record<string, Omit<Line, "label">> = {
    fresh: { tone: "ok", text: `Current until ${keysAt}.` },
    expiring: { tone: "warn", text: `Expire soon (${keysAt}). The automatic refresh should replace them first.`, recovery: `If this still shows after ${keysAt}: ${KEY_STEP}` },
    expired: { tone: "bad", text: `Expired at ${keysAt}. Jo's sign-ins and calls are refused.`, recovery: KEY_STEP },
    "issuer-mismatch": { tone: "bad", text: "Belong to a different sign-in issuer or key address.", recovery: "Operator: compare the key refresh settings with the advisor config before refreshing." },
    unreadable: { tone: "bad", text: "Can't be read.", recovery: "Operator: run the key check and confirm the snapshot and the owner read grant exist." },
    "not-configured": { tone: "warn", text: "Not set up for this page.", recovery: GRANT_STEP },
  };
  const advisor: Record<string, Omit<Line, "label">> = {
    enabled: { tone: "ok", text: "Advisor config and Jo's profile are on." },
    "config-disabled": { tone: "bad", text: "The advisor config is turned off.", recovery: "Operator: re-enable it under a reviewed activation, then restart the advisor units." },
    "profile-disabled": { tone: "bad", text: "Jo's advisor profile is turned off.", recovery: "Operator: re-enable the profile under a reviewed activation, then restart the advisor units." },
    "profile-mismatch": { tone: "bad", text: "The advisor config no longer names this page's advisor profile.", recovery: "Operator: verify the installation; the advisor and owner reader must use the same profile." },
    unreadable: { tone: "bad", text: "Can't be read.", recovery: "Operator: confirm the advisor config exists, parses and keeps the owner read grant." },
    "not-configured": { tone: "warn", text: "Not set up for this page.", recovery: GRANT_STEP },
  };
  const questionAt = advisorStamp(value.assignment.expires_at);
  const question: Record<string, Omit<Line, "label">> = {
    pending: { tone: "ok", text: `Open for Jo until ${questionAt}.` },
    answered: { tone: "ok", text: "Answered. Jo can't save to it again.", recovery: NEW_QUESTION, manage: true },
    expired: { tone: "warn", text: `Expired at ${questionAt} without an answer.`, recovery: NEW_QUESTION, manage: true },
    revoked: { tone: "warn", text: "Revoked.", recovery: NEW_QUESTION, manage: true },
    none: { tone: "warn", text: "No question is assigned.", recovery: NEW_QUESTION, manage: true },
    unreadable: { tone: "bad", text: "Can't be read from the advisor ledger.", recovery: "Check again. If it stays, operator: verify the installation before any new question." },
  };
  const unknown: Omit<Line, "label"> = { tone: "bad", text: "Unrecognized state.", recovery: "Operator: verify the installation." };
  return [
    { label: "Sign-in keys", ...(keys[value.keys.state] ?? unknown) },
    { label: "Advisor", ...(advisor[value.advisor.state] ?? unknown) },
    { label: "Selected question", ...(question[value.assignment.state] ?? unknown) },
    { label: "Last Jo save", tone: "ok", text: value.last_save_at ? `${advisorStamp(value.last_save_at)}. Jo read the question before saving.` : "No saved answer yet. Jo's reads alone aren't recorded." },
  ];
}

const dot: Record<Tone, string> = { ok: "bg-emerald-600", warn: "bg-amber-500", bad: "bg-red-600" };
const word: Record<Tone, string> = { ok: "OK", warn: "Attention", bad: "Problem" };

export default function AdvisorConnectionStatus({ canManage }: { canManage: boolean }) {
  const [value, setValue] = useState<Status | null>(null);
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
      const response = await fetch("/api/advisor-owner/status", { cache: "no-store", redirect: "error", signal: pending.signal });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Advisor connection status unavailable.");
      if (body.schema_version !== "advisor-owner-status-v1") throw new Error("Unsupported advisor connection status.");
      if (current === sequence.current) setValue(body);
    } catch (err) {
      if (current === sequence.current && !pending.signal.aborted) setError(err instanceof Error ? err.message : "Advisor connection status unavailable.");
    } finally { if (current === sequence.current) setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void reload(); });
    return () => { active = false; sequence.current += 1; controller.current?.abort(); };
  }, [reload]);
  return <section className="mx-auto mb-4 max-w-4xl rounded border bg-card p-3 text-sm" data-testid="advisor-connection-status" aria-labelledby="advisor-connection-heading">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="advisor-connection-heading" className="font-semibold">Advisor connection</h2>
      <button type="button" onClick={() => void reload()} disabled={loading} className="min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">Check again</button>
    </div>
    {loading && <p role="status" className="mt-2">Checking the advisor connection…</p>}
    {error && <div role="alert" className="mt-2 break-words"><p>{error}</p><p className="text-muted-foreground">The advisor units may be stopped after a host reboot or deploy. Operator: verify the installation, then start the sockets before the services.</p></div>}
    {value && <>
      <ul className="mt-2 divide-y">{lines(value).map(line => <li key={line.label} className="py-2" data-testid="advisor-connection-line">
        <p className="flex items-start gap-2"><span aria-hidden className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot[line.tone]}`} /><span><span className="sr-only">{word[line.tone]}: </span><span className="font-medium">{line.label}:</span> {line.text}</span></p>
        {line.recovery && <p className="ml-[1.125rem] text-muted-foreground">{line.recovery}{line.manage && canManage && <> <Link href="/advisor-review/questions" className="underline">Manage advisor questions</Link></>}</p>}
      </li>)}</ul>
      <p className="mt-1 text-xs text-muted-foreground">Checked {advisorStamp(value.checked_at)}. If Jo reports a sign-in or tool discovery failure while these lines are OK, reconnect the advisor app in ChatGPT as the dedicated advisor user (not Google), refresh its tools and start a new Jo conversation.</p>
    </>}
  </section>;
}
