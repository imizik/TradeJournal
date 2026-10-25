"use client";

import { useEffect, useRef, useState } from "react";
import { createPlanAlert, freshQuote, previewTimeStop, savePlanCapture, saveTimeStop, type LevelHistory, type PlanLevel, type TimeStopPreview, type TradePlan } from "@/lib/copilot";
import { fetchSetup, newClientId, SIDE_LABEL, type CaptureSetup, type CaptureSide } from "@/lib/captures";
import { conditionText, levelText } from "@/components/copilot/ProposalCard";
import { cn } from "@/lib/utils";

const SIDE: Record<string, CaptureSide> = { "long stock": "buy_stock", "short stock": "short_stock", "long calls": "buy_calls", "short puts": "buy_puts" };
type Part = "plan" | "entry" | "invalidation" | "timeStop";
type Result = { state: "idle" | "working" | "done" | "failed"; text: string };
const PART_LABEL: Record<Part, string> = { plan: "Pre-trade plan", entry: "Entry alert", invalidation: "Invalidation alert", timeStop: "Time stop" };
const IDLE: Result = { state: "idle", text: "" };
const field = "w-full rounded border bg-background px-2 py-2 text-base text-foreground disabled:opacity-60 sm:text-sm";
/** The invalidation study's approval-only wording candidates: why a level's history is evidence beside the card, never a rule. */
export const EVIDENCE_NOT_RULE_URL =
  "https://github.com/imizik/TradeJournal/blob/main/backend/reports/invalidation_study_2026-10-25.md#defaults-the-copilot-could-suggest--approval-only";

/** One line of the owner's own history at the drafted invalidation, e.g. "12 of 31 past NBIS trades crossed −2.1% while held; 5 recovered; median −18% from there." */
export function historyText(h: LevelHistory): string {
  const signed = (n: number, digits: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(digits)}%`;
  const median = h.median_from_cross_pct === null ? "" : `; median ${signed(h.median_from_cross_pct, 0)} from there`;
  return `${h.crossed} of ${h.trades} past ${h.symbol} trades crossed ${signed(h.distance_pct, 1)} while held; ${h.recovered} recovered${median}.`;
}

/**
 * The copilot's whole trade plan (propose_plan kind=trade_plan). The owner edits it; Confirm saves it as their pre-trade
 * plan (the capture route) and arms its entry and invalidation alerts (the alerts route, as a watch does). A time stop
 * the server can read as a time ("out by 15:30", "45m", "2 days") is shown before Confirm and saved as a timed ping;
 * other wording stays a note in the plan. Each part reports its own result, and only a failed part is retried.
 * Nothing is saved or armed before Confirm.
 */
export default function TradePlanCard({ plan, investigationId, alertsSupported, history = null, onDone }: {
  plan: TradePlan; investigationId: string | null; alertsSupported: boolean; history?: LevelHistory | null; onDone(): void;
}) {
  const [dismissed, setDismissed] = useState(false);
  const [thesis, setThesis] = useState(plan.thesis);
  const [entry, setEntry] = useState(String(plan.entry_trigger.price));
  const [stop, setStop] = useState(String(plan.invalidation.price));
  const [timeStop, setTimeStop] = useState(plan.time_stop ?? "");
  const [size, setSize] = useState(plan.size_note ?? "");
  const [setup, setSetup] = useState<CaptureSetup | null>(null);
  const [setupError, setSetupError] = useState(false);
  const [picked, setAccount] = useState("");
  const [results, setResults] = useState<Record<Part, Result>>({ plan: IDLE, entry: IDLE, invalidation: IDLE, timeStop: IDLE });
  // The server's reading of the time stop, for the words it was asked about; a failed read leaves it a note.
  const [preview, setPreview] = useState<{ text: string; read: TimeStopPreview | null } | null>(null);
  const clientId = useRef(newClientId());  // one plan per card: a retried save returns the first one
  useEffect(() => { fetchSetup().then(setSetup).catch(() => setSetupError(true)); }, []);
  const stopText = timeStop.trim();
  useEffect(() => {
    if (!stopText || !alertsSupported) return;
    const controller = new AbortController();
    const wait = setTimeout(() => {
      previewTimeStop(stopText, controller.signal).then(read => setPreview({ text: stopText, read }))
        .catch(() => { if (!controller.signal.aborted) setPreview({ text: stopText, read: null }); });
    }, 300);
    return () => { clearTimeout(wait); controller.abort(); };
  }, [stopText, alertsSupported]);
  if (dismissed) return null;

  const side = SIDE[`${plan.direction} ${plan.instrument}`];
  const accounts = setup?.accounts ?? [];
  const account = picked || setup?.default_account_id || (accounts.length === 1 ? accounts[0].id : "");
  const entryLevel: PlanLevel = { ...plan.entry_trigger, price: Number(entry) };
  const stopLevel: PlanLevel = { ...plan.invalidation, price: Number(stop) };
  const long = plan.direction === "long";
  const problem = !thesis.trim() ? "Write the thesis in a sentence."
    : ![entryLevel.price, stopLevel.price].every(p => Number.isFinite(p) && p > 0) ? "Entry and invalidation must be positive prices."
    : long && !(stopLevel.price < entryLevel.price) ? "A long plan's invalidation must be below its entry."
    : !long && !(stopLevel.price > entryLevel.price) ? "A short plan's invalidation must be above its entry."
    : setupError ? "Your journal accounts could not be read, so the plan cannot be saved. Reload and try again."
    : setup && !account ? (accounts.length ? "Choose the journal account this plan is for." : "Add a journal account before saving plans.")
    : null;
  const started = Object.values(results).some(r => r.state !== "idle");
  const busy = Object.values(results).some(r => r.state === "working");
  const reading = alertsSupported && !!stopText && preview?.text !== stopText;
  const timed = alertsSupported && !reading && preview?.read?.due_at ? preview.read : null;
  const parts: Part[] = alertsSupported ? ["plan", "entry", "invalidation", ...(timed ? ["timeStop" as const] : [])] : ["plan"];
  const finished = parts.every(p => results[p].state === "done");
  const ready = !problem && !!account && (!alertsSupported || !!investigationId) && !reading;

  const wording = [`Entry: ${levelText(entryLevel)}.`, `Invalidation: ${levelText(stopLevel)}.`,
    timeStop.trim() && `Time stop: ${timeStop.trim()}.`, size.trim() && `Size: ${size.trim()}.`].filter(Boolean).join(" ").slice(0, 400);
  const note = [`Thesis: ${thesis.trim()}`, plan.contract && `Contract: ${plan.contract}.`, "From a Copilot Lab plan card."]
    .filter(Boolean).join(" ").slice(0, 500);

  async function run(part: Part): Promise<boolean> {
    setResults(r => ({ ...r, [part]: { state: "working", text: "" } }));
    try {
      let text: string;
      if (part === "plan") {
        await savePlanCapture({ client_id: clientId.current, underlying: plan.symbol, account_id: account, side, wording, note, investigation_id: investigationId });
        text = "Saved as your pre-trade plan. It is suggested for the trade when the fill arrives.";
      } else if (part === "timeStop") {
        await saveTimeStop(clientId.current, investigationId!, plan.symbol, stopText);
        text = `Set for ${timed?.when ?? "its time"}.`;
        onDone();
      } else {
        const level = part === "entry" ? entryLevel : stopLevel;
        // The side the alert waits on comes from the price now, so a stale or missing quote is refused, as for a watch.
        const quote = await freshQuote(plan.symbol);
        if (!quote.fresh || quote.last === null) throw new Error(`The latest ${plan.symbol} quote is stale or missing, so it was not set.`);
        if (quote.last === level.price) throw new Error(`${plan.symbol} is at ${level.price} now, so the alert has no side to wait on.`);
        // An invalidation already crossed would arm on the wrong side and wait for the move back.
        if (part === "invalidation" && (long ? quote.last < level.price : quote.last > level.price))
          throw new Error(`${plan.symbol} is at ${quote.last}, already past the invalidation at ${level.price}, so it was not set.`);
        await createPlanAlert(investigationId!, plan.symbol, level, quote.last, `${plan.symbol} ${part}: ${levelText(level)}`.slice(0, 60), part);
        text = `Set: ${plan.symbol} ${levelText(level)}.`;
        onDone();
      }
      setResults(r => ({ ...r, [part]: { state: "done", text } }));
      return true;
    } catch (failure) {
      setResults(r => ({ ...r, [part]: { state: "failed", text: failure instanceof Error ? failure.message : "Not done." } }));
      return false;
    }
  }

  /** The plan first: its alerts are armed only once it is saved, so a failed save leaves nothing armed without a plan. */
  async function savePlanThenAlerts() {
    if (!(await run("plan"))) return;
    for (const part of parts.slice(1)) if (results[part].state !== "done") await run(part);
  }

  async function confirm() {
    if (!ready || started) return;
    await savePlanThenAlerts();
  }

  const locked = started;
  return (
    <section aria-label="Proposed trade plan" className="mt-2 space-y-2 rounded border border-sky-500/30 bg-sky-500/5 p-3 text-sm">
      <p className="font-medium text-foreground">
        Proposed trade plan · {plan.symbol} · {SIDE_LABEL[side]}{plan.contract ? ` · ${plan.contract}` : ""}
      </p>
      {plan.last !== undefined && <p className="text-xs text-muted-foreground">{plan.symbol} was {plan.last} when this was drafted.</p>}
      <label className="block space-y-1">
        <span className="text-xs text-muted-foreground">Thesis</span>
        <textarea value={thesis} onChange={e => setThesis(e.target.value.slice(0, 300))} rows={3} disabled={locked} className={field} />
      </label>
      <div className="grid grid-cols-2 items-end gap-2">
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Entry ({conditionText(plan.entry_trigger)})</span>
          <input value={entry} onChange={e => setEntry(e.target.value)} inputMode="decimal" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Invalidation ({conditionText(plan.invalidation)})</span>
          <input value={stop} onChange={e => setStop(e.target.value)} inputMode="decimal" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
      </div>
      {history && (
        <p aria-label="Your history at this level" className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Your history at this level: </span>
          {Number(stop) === history.level ? (
            <>
              {historyText(history)}{history.small && " Too few trades to weigh."}{history.simulated && " (Simulated.)"}{" "}
              <a href={EVIDENCE_NOT_RULE_URL} target="_blank" rel="noreferrer" className="underline hover:text-foreground">why this is evidence, not a rule</a>
            </>
          ) : "you changed the invalidation; re-ask the copilot to refresh it."}
        </p>
      )}
      <label className="block space-y-1">
        <span className="text-xs text-muted-foreground">Time stop</span>
        <input value={timeStop} onChange={e => setTimeStop(e.target.value.slice(0, 80))} placeholder="e.g. out by 15:30" disabled={locked} className={cn(field, "min-h-11")} />
      </label>
      {alertsSupported && stopText && !locked && (
        <p aria-label="When it pings" className="text-xs text-muted-foreground">
          {reading ? "Reading the time…"
            : timed ? `Pings ${timed.when} if you hold ${plan.symbol} then, from an entry after this plan.${timed.enabled ? "" : " Time-stop pings are off on this server for now."}`
            : `Kept as a note: ${preview?.read && "reason" in preview.read ? preview.read.reason : "the time could not be read."}`}
        </p>
      )}
      <label className="block space-y-1">
        <span className="text-xs text-muted-foreground">Size</span>
        <input value={size} onChange={e => setSize(e.target.value.slice(0, 120))} placeholder="e.g. one starter, no adds" disabled={locked} className={cn(field, "min-h-11")} />
      </label>
      {setup && !setup.default_account_id && accounts.length > 1 && (
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Journal account</span>
          <select value={picked} onChange={e => setAccount(e.target.value)} disabled={locked} className={cn(field, "min-h-11")}>
            <option value="">Choose…</option>
            {accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </label>
      )}
      {!alertsSupported && <p className="text-xs text-muted-foreground">Awaiting alert support: Confirm saves the plan; its entry and invalidation alerts cannot be set here yet.</p>}
      {problem && !locked && <p role="alert" className="text-xs text-amber-300">{problem}</p>}
      {started && (
        <ul aria-label="Plan results" className="space-y-1">
          {parts.map(part => {
            const r = results[part];
            return (
              <li key={part} className="flex flex-wrap items-center gap-2 text-xs">
                <span className={cn("font-medium", r.state === "done" ? "text-emerald-300" : r.state === "failed" ? "text-amber-300" : "text-muted-foreground")}>
                  {PART_LABEL[part]}: {r.state === "done" ? "done" : r.state === "failed" ? "failed" : r.state === "working" ? "working…" : "waits for the plan"}
                </span>
                {r.text && <span className={r.state === "failed" ? "text-amber-300" : "text-muted-foreground"}>{r.text}</span>}
                {r.state === "failed" && (
                  <button type="button" onClick={() => void (part === "plan" ? savePlanThenAlerts() : run(part))} disabled={busy}
                    className="min-h-11 rounded border px-3 py-1 text-foreground disabled:opacity-40">Retry {PART_LABEL[part].toLowerCase()}</button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {!started && (
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
          <button type="button" onClick={() => void confirm()} disabled={!ready}
            className="min-h-11 rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-40">
            {!investigationId && alertsSupported ? "Saving…" : "Confirm"}</button>
          <button type="button" onClick={() => setDismissed(true)}
            className="min-h-11 rounded border px-4 py-2 text-muted-foreground hover:text-foreground">Dismiss</button>
          <span className="col-span-2 text-xs text-muted-foreground">Nothing is saved or armed until you confirm.</span>
        </div>
      )}
      {finished && <p role="status" className="text-xs text-emerald-300">Plan confirmed.</p>}
    </section>
  );
}
