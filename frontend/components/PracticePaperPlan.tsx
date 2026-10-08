"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PaperEvent, type PaperOutcome, type PaperState } from "@/lib/api";

const ET = "America/New_York";
const fmtTime = (epochSeconds: number) => `${new Date(epochSeconds * 1000).toLocaleString("en-US", { timeZone: ET })} ET`;
const num = (v: unknown, digits = 2) => (typeof v === "number" ? v.toFixed(digits) : "—");
// buildApiError wraps the server text as "API <path> -> <status>: <detail>"; show the detail alone.
const detailOf = (err: unknown, fallback: string) => (err instanceof Error ? err.message.replace(/^API \S+ -> \d+:?\s*/, "") || fallback : fallback);

export function PaperBadge({ status }: { status: PaperState["status"] }) {
  const tone = status === "unarmed" ? "bg-amber-500/10 text-amber-700" : "bg-sky-500/10 text-sky-700";
  return <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>PRACTICE · PAPER · {status.toUpperCase()}</span>;
}

function eventDetail(e: PaperEvent): string {
  switch (e.type) {
    case "trigger": return `15m close ${num(e.close)} beyond level ${num(e.level)}; detected ${typeof e.detected_at === "number" ? fmtTime(e.detected_at) : "—"} (${num(e.delay_seconds, 0)}s after close)`;
    case "entry": return `paper fill ${num(e.fill)} (reference ${num(e.reference)})`;
    case "exit": return `${String(e.kind).toUpperCase()} paper fill ${num(e.fill)}${e.ambiguous ? " · ambiguous bar" : ""}${e.gap ? " · gap" : ""}`;
    case "entry_rejected":
    case "missed_trigger":
    case "unresolved": return String(e.reason ?? "");
    default: return "";
  }
}

function Flags({ e }: { e: PaperEvent }) {
  const flags: string[] = [];
  if (e.reconstructed) flags.push("reconstructed");
  if (e.type === "exit" && e.ambiguous) flags.push("ambiguous");
  if (e.type === "missed_trigger" && e.reason === "detected_late") flags.push("late");
  const delivery = e.delivery == null ? "" : e.delivery === "sent" ? "phone alert sent" : e.delivery_error ? `phone alert ${e.delivery}: ${e.delivery_error}` : `phone alert ${e.delivery}`;
  return (
    <>
      {flags.map((f) => <span key={f} className="ml-1 rounded bg-amber-500/10 px-1 text-amber-700">{f}</span>)}
      {delivery && <span className={`ml-1 ${e.delivery === "sent" ? "text-emerald-700" : "text-red-600"}`}>{delivery}</span>}
    </>
  );
}

function Outcome({ label, o }: { label: string; o: PaperOutcome }) {
  return (
    <div className="rounded border bg-background p-2">
      <p className="font-medium">{label} <span className="text-muted-foreground">({o.cost_version})</span></p>
      <p>Paper entry {num(o.entry_fill)} → exit {num(o.exit_fill)} ({o.exit_kind})</p>
      <p>Net {num(o.net_per_share)}/share · planned R {num(o.planned_r, 3)}</p>
      {(o.ambiguous || o.gap) && <p className="text-amber-700">{[o.ambiguous && "ambiguous bar", o.gap && "gap"].filter(Boolean).join(" · ")}</p>}
    </div>
  );
}

export default function PracticePaperPlan({ recordId, onState }: { recordId: string; onState?: (s: PaperState) => void }) {
  const [state, setState] = useState<PaperState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [arming, setArming] = useState(false);
  const [armError, setArmError] = useState("");
  const attempt = useRef("");

  const apply = useCallback((s: PaperState) => { setState(s); onState?.(s); }, [onState]);
  const load = useCallback(async () => {
    setLoadError("");
    try { apply(await api.paperState(recordId)); }
    catch (err) { setLoadError(detailOf(err, "Could not load the paper timeline.")); }
  }, [recordId, apply]);
  useEffect(() => { void load(); }, [load]);

  async function arm() {
    if (arming) return;
    setArming(true);
    setArmError("");
    // One operation ID per click attempt; it is reused until an attempt succeeds, so a retry cannot arm twice.
    if (!attempt.current) attempt.current = `arm-${recordId}-${Date.now()}`;
    try {
      apply(await api.armPaperPlan(recordId, attempt.current));
      attempt.current = "";
    } catch (err) {
      const text = detailOf(err, "Could not arm the plan.");
      setArmError(text);
      // A policy refusal or conflict is final for this attempt; a network failure keeps the ID for the retry.
      if (/-> (4\d\d)/.test(err instanceof Error ? err.message : "")) attempt.current = "";
    } finally {
      setArming(false);
    }
  }

  return (
    <div data-testid="paper-plan" className="space-y-2 rounded border border-sky-500/30 bg-sky-500/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">Practice paper timeline</span>
        {state && <PaperBadge status={state.status} />}
      </div>
      <p className="text-muted-foreground">Paper only. No real order is ever placed.</p>
      {!state && !loadError && <p role="status">Loading paper state…</p>}
      {loadError && <p role="alert" className="text-red-600">{loadError} <button onClick={load} className="underline">Retry</button></p>}
      {state?.status === "unarmed" && (
        <button onClick={arm} disabled={arming} className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">
          {arming ? "Arming paper plan…" : "Arm paper plan"}
        </button>
      )}
      {armError && <p role="alert" className="text-red-600">{armError}</p>}
      {state && state.events.length > 0 && (
        <ol className="space-y-1">
          {state.events.map((e) => (
            <li key={e.seq} className="break-words">
              <span className="font-medium">{e.type.replace(/_/g, " ")}</span> · {fmtTime(e.at)}
              <Flags e={e} />
              {eventDetail(e) && <span className="block text-muted-foreground">{eventDetail(e)}</span>}
            </li>
          ))}
        </ol>
      )}
      {state?.outcome && state.outcome_x3 && (
        <div className="grid gap-2 sm:grid-cols-2">
          <Outcome label="Paper outcome" o={state.outcome} />
          <Outcome label="Paper outcome at 3× costs" o={state.outcome_x3} />
        </div>
      )}
      {state?.policy_version && <p className="text-muted-foreground">Policy {state.policy_version}</p>}
    </div>
  );
}
