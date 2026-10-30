"use client";

import { useEffect, useRef, useState } from "react";
import { confirmedElsewhere, createPlanAlert, freshQuote, getSymbolLoop, PLAN_CONFIRMED, previewTimeStop, rememberRisk, savedRisk, savePlanCapture, saveTimeStop, type DrawnPlan, type ExitLesson, type FreshQuote, type LevelHistory, type OptionCandidates, type OptionPick, type PlanConfirmed, type PlanLevel, type ProposalOutcome, type TimeStopPreview, type TradePlan } from "@/lib/copilot";
import { fetchSetup, newClientId, SIDE_LABEL, type CaptureOrigin, type CaptureSetup, type CaptureSide } from "@/lib/captures";
import JoCaseAgainst from "@/components/copilot/JoCaseAgainst";
import LastExitLine from "@/components/copilot/LastExitLine";
import { conditionText, levelText } from "@/components/copilot/ProposalCard";
import { HORIZONS, horizonFor, saveHorizon, type DeskHorizon } from "@/lib/desk";
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

const SIZE_MAX = 120;
const PRICE_MAX = 24;  // a price as typed; what the saved card keeps
const usd = (n: number) => `$${n >= 100 || Number.isInteger(n) ? Math.round(n).toLocaleString("en-US") : n.toFixed(2)}`;
// Rounding down: a whole share or contract only when the risk covers it (the nudge absorbs float error like 150 / 1.5).
const whole = (risk: number, each: number) => Math.floor(risk / each + 1e-9);

/** Size it for me, a stock plan: whole shares whose move from the entry to the invalidation loses at most the risk. */
export function sizeShares(risk: number, entry: number, invalidation: number, last: number | null) {
  const distance = Math.round(Math.abs(entry - invalidation) * 10000) / 10000;
  if (!(risk > 0) || !(distance > 0)) return null;
  const shares = whole(risk, distance);
  return { shares, distance, atRisk: shares * distance, cost: last === null ? null : shares * last };
}

/**
 * Size it for me, a long call or put at its ask. Max loss: the premium is all at risk, so contracts = risk ÷ ask per
 * contract. At invalidation, only with the chain's delta: a contract loses about delta × the distance × the multiplier
 * there, never more than its premium. Nothing is estimated without a delta.
 */
export function sizeContracts(risk: number, pick: { ask_contract: number; ask: number; delta: number | null }, distance: number | null) {
  if (!(risk > 0) || !(pick.ask_contract > 0) || !(pick.ask > 0)) return null;
  const maxLoss = whole(risk, pick.ask_contract);
  const perContract = pick.delta === null || !(distance && distance > 0) ? 0
    : Math.min(Math.abs(pick.delta) * distance * (pick.ask_contract / pick.ask), pick.ask_contract);
  const atInvalidation = perContract > 0 ? { contracts: whole(risk, perContract), perContract } : null;
  return { maxLoss, premium: maxLoss * pick.ask_contract, atInvalidation };
}

/** The computed size leads the owner's size note, which keeps its 120 characters: the owner's words are cut, not the size. */
export function sizedNote(sized: string, note: string): string {
  const both = [sized, note.trim()].filter(Boolean).join("; ");
  return both.length <= SIZE_MAX ? both : `${both.slice(0, SIZE_MAX - 1).trimEnd()}…`;
}

/** A confirmed card's saved part results; parts it never ran start idle. */
const restored = (outcome: ProposalOutcome | null): Record<Part, Result> =>
  ({ plan: IDLE, entry: IDLE, invalidation: IDLE, timeStop: IDLE, ...outcome?.parts });

/** Under a price the owner drew on Charts: "from your drawing" while the card's price is theirs, else what they drew. */
function FromDrawing({ name, drawn, value }: { name: string; drawn: number | null; value: string }) {
  // Only the invalidation was drawn: the trigger is the copilot's.
  if (drawn === null) return <span className="block text-xs text-muted-foreground">Drafted by the copilot</span>;
  const same = Math.abs(Number(value) - drawn) < 0.005;
  return <span aria-label={`${name} from your drawing`} className={cn("block text-xs", same ? "text-sky-300" : "text-amber-300")}>
    {same ? "From your drawing" : `Changed from your drawing: ${drawn.toFixed(2)}`}</span>;
}

/**
 * The copilot's whole trade plan (propose_plan kind=trade_plan). The owner edits it; Confirm saves it as their pre-trade
 * plan (the capture route) and arms its entry and invalidation alerts (the alerts route, as a watch does). A time stop
 * the server can read as a time ("out by 15:30", "45m", "2 days") is shown before Confirm and saved as a timed ping;
 * other wording stays a note in the plan. Each part reports its own result, and only a failed part is retried.
 * Nothing is saved or armed before Confirm. A saved card comes back as it was left (``plan.outcome``): confirmed shows
 * its fields and each part's result (a failed part can still be retried), dismissed stays hidden. ``onOutcome``
 * reports a Confirm's results or a Dismiss so the investigation keeps them.
 */
export default function TradePlanCard({ plan, investigationId, alertsSupported, history = null, candidates = null, origin, drawn = null, onDone, onOutcome }: {
  plan: TradePlan; investigationId: string | null; alertsSupported: boolean; history?: LevelHistory | null;
  /** The turn's option candidates, offered as a pick list for the contract beside the copilot's own wording. */
  candidates?: OptionCandidates | null;
  /** What prompted the conversation; the saved plan records it (docs/copilot-lab.md § Origin). */
  origin?: CaptureOrigin;
  /** The levels the owner drew on Charts for this plan ("Plan this"): shown beside the prices, flagged where they differ. */
  drawn?: DrawnPlan | null; onDone(): void; onOutcome(outcome: ProposalOutcome): void;
}) {
  const saved = plan.outcome?.state === "confirmed" ? plan.outcome : null;
  const [dismissed, setDismissed] = useState(plan.outcome?.state === "dismissed");
  const [thesis, setThesis] = useState(saved?.fields?.thesis ?? plan.thesis);
  const [contract, setContract] = useState(saved?.fields?.contract ?? plan.contract ?? "");
  const picks = (candidates?.picks ?? []).filter(p => p.label !== plan.contract);
  const [entry, setEntry] = useState(saved?.fields?.entry ?? String(plan.entry_trigger.price));
  const [stop, setStop] = useState(saved?.fields?.invalidation ?? String(plan.invalidation.price));
  const [timeStop, setTimeStop] = useState(saved?.fields?.time_stop ?? plan.time_stop ?? "");
  const [size, setSize] = useState(saved?.fields?.size_note ?? plan.size_note ?? "");
  // The owner's pick; until then the time stop sets it (due today: a day trade), else a swing.
  const [pickedHorizon, setHorizon] = useState<DeskHorizon | null>(saved?.fields?.horizon || null);
  // Size it for me: the risk this browser last used; the card is client-only, so it reads storage on mount.
  const [risk, setRisk] = useState(() => savedRisk());
  const [sizeEdited, setSizeEdited] = useState(false);  // the owner's own size note after sizing wins over the count
  const [quote, setQuote] = useState<FreshQuote | "failed" | null>(null);
  const [setup, setSetup] = useState<CaptureSetup | null>(null);
  const [setupError, setSetupError] = useState(false);
  const [picked, setAccount] = useState("");
  const [results, setResults] = useState<Record<Part, Result>>(() => restored(saved));
  // The server's reading of the time stop, for the words it was asked about; a failed read leaves it a note.
  const [preview, setPreview] = useState<{ text: string; read: TimeStopPreview | null } | null>(null);
  // One plan per card, its id kept with it: a save retried here, after a reload or from another window returns the first one.
  const clientId = useRef(plan.client_id ?? newClientId());
  useEffect(() => { fetchSetup().then(setSetup).catch(() => setSetupError(true)); }, []);
  // A draft shows the symbol's last exit lesson; a confirmed or dismissed card never reads it.
  const [lastExit, setLastExit] = useState<ExitLesson | null>(null);
  const drafting = !saved && !dismissed;
  useEffect(() => {
    if (!drafting) return;
    const controller = new AbortController();
    getSymbolLoop(plan.symbol, controller.signal)
      .then(loop => setLastExit(loop.last_exit?.state === "ok" ? loop.last_exit.lesson : null)).catch(() => undefined);
    return () => controller.abort();
  }, [drafting, plan.symbol]);
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
  const riskUsd = Number(risk);
  const wantsQuote = plan.instrument === "stock" && riskUsd > 0 && quote === null;
  useEffect(() => {
    if (!wantsQuote) return;
    freshQuote(plan.symbol).then(setQuote).catch(() => setQuote("failed"));
  }, [wantsQuote, plan.symbol]);
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
  // A restored card also lists the parts it ran, whatever this window reads now.
  const rows = (Object.keys(PART_LABEL) as Part[]).filter(p => parts.includes(p) || results[p].state !== "idle");
  const finished = parts.every(p => results[p].state === "done");
  const horizon = pickedHorizon ?? horizonFor(timed?.due_at);
  const ready = !problem && !!account && (!alertsSupported || !!investigationId) && !reading;

  const sizing = sizeIt();
  const sizeText = sizing?.note && !sizeEdited ? sizedNote(sizing.note, size) : size.trim();
  const wording = [`Entry: ${levelText(entryLevel)}.`, `Invalidation: ${levelText(stopLevel)}.`,
    timeStop.trim() && `Time stop: ${timeStop.trim()}.`, sizeText && `Size: ${sizeText}.`].filter(Boolean).join(" ").slice(0, 400);

  /** What the typed risk buys, in plain lines, and the line Confirm puts in front of the size note (none for zero). */
  function sizeIt(): { lines: string[]; note: string | null } | null {
    if (!(riskUsd > 0)) return null;
    const losing = long ? entryLevel.price - stopLevel.price : stopLevel.price - entryLevel.price;
    const distance = Number.isFinite(losing) && losing > 0 ? losing : null;
    const stopAt = stopLevel.price.toFixed(2);
    if (plan.instrument === "stock") {
      if (distance === null) return { lines: ["Size needs an invalidation on the losing side of the entry."], note: null };
      const live = quote && quote !== "failed" && quote.fresh && quote.last !== null ? quote : null;
      const s = sizeShares(riskUsd, entryLevel.price, stopLevel.price, live?.last ?? null);
      if (!s) return null;
      if (s.shares === 0) return { lines: [`${usd(riskUsd)} does not cover one share: it is ${s.distance.toFixed(2)} a share to the ${stopAt} invalidation.`], note: null };
      const cost = live && s.cost !== null ? `${usd(s.cost)} at the ${live.last} quote${live.age_s !== null ? ` (${Math.round(live.age_s)}s old)` : ""}.`
        : quote === null ? "Reading the quote for the cost…" : "Cost not shown: the latest quote is stale or missing.";
      return {
        lines: [`${s.shares} share${s.shares === 1 ? "" : "s"}: ${usd(s.atRisk)} lost if it reaches the ${stopAt} invalidation (${s.distance.toFixed(2)} a share).`, cost],
        note: `${s.shares} shares${live ? ` at ${live.last}` : ""}, ${usd(s.atRisk)} at risk to ${stopAt}, risk ${usd(riskUsd)}`,
      };
    }
    const pick: OptionPick | undefined = candidates?.picks.find(p => p.label === contract);
    if (!pick || pick.ask_contract === null || !pick.ask) return { lines: [
      !candidates?.picks.length ? "No option premiums in this conversation yet: ask the copilot which strike and expiry, then choose a contract from its list to size it."
        : contract ? `${contract} has no premium from the option chain here: choose a contract from the Contract list to size it.`
        : "Choose a contract from the Contract list to size it."], note: null };
    const c = sizeContracts(riskUsd, { ask_contract: pick.ask_contract, ask: pick.ask, delta: pick.delta ?? null }, distance);
    if (!c) return null;
    const read = candidates?.as_of ? ` from the option chain read at ${new Date(candidates.as_of).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" })} ET` : " from the option chain";
    const n = (k: number) => `${k} contract${k === 1 ? "" : "s"}`;
    const lines = [
      c.maxLoss === 0 ? `Max loss: ${usd(riskUsd)} does not buy one contract at the ${usd(pick.ask_contract)} ask.`
        : `Max loss: ${n(c.maxLoss)}, ${usd(c.premium)} of premium, all of it at risk.`,
      !c.atInvalidation ? (pick.delta == null ? "At invalidation: the chain gives no delta, so there is no estimate." : "At invalidation: needs an invalidation on the losing side of the entry.")
        : `At invalidation: about ${n(c.atInvalidation.contracts)}, each losing about ${usd(c.atInvalidation.perContract)} if ${plan.symbol} reaches ${stopAt} (delta ${pick.delta}); the premium is still all at risk past it.`,
      `Priced at the ${pick.ask.toFixed(2)} ask (${usd(pick.ask_contract)} a contract)${read}${candidates?.simulated ? " (simulated)" : ""}.`,
    ];
    return { lines, note: c.maxLoss === 0 ? null : `${n(c.maxLoss)} of ${pick.label} at ${pick.ask.toFixed(2)}, ${usd(c.premium)} max loss, risk ${usd(riskUsd)}` };
  }
  const note = [`Thesis: ${thesis.trim()}`, contract && `Contract: ${contract}.`, "From a Copilot Lab plan card."]
    .filter(Boolean).join(" ").slice(0, 500);

  /** What the investigation keeps once a Confirm or a retry finishes: each part's result and the fields as confirmed. */
  function report(all: Record<Part, Result>) {
    const ran = Object.fromEntries(Object.entries(all).filter(([, r]) => r.state === "done" || r.state === "failed")
      .map(([part, r]) => [part, { state: r.state, text: r.text.slice(0, 500) }]));
    // Within what the investigation stores, so an odd input never stops the conversation from saving.
    onOutcome({ state: "confirmed", parts: ran, fields: { thesis: thesis.trim().slice(0, 300), contract: contract.slice(0, 80),
      entry: entry.slice(0, PRICE_MAX), invalidation: stop.slice(0, PRICE_MAX), time_stop: timeStop.slice(0, 80), size_note: size.slice(0, SIZE_MAX), horizon } });
  }

  async function run(part: Part): Promise<Result> {
    setResults(r => ({ ...r, [part]: { state: "working", text: "" } }));
    try {
      let text: string;
      if (part === "plan") {
        await savePlanCapture({ client_id: clientId.current, underlying: plan.symbol, account_id: account, side, wording, note, investigation_id: investigationId,
          // The lab's own plans point at their investigation.
          origin: !origin || (origin.kind === "copilot" && !origin.ref) ? { kind: "copilot", ref: investigationId, text: origin?.text ?? null } : origin });
        // How often the desk checks in on it after the close, from today on (one save per card and horizon).
        await saveHorizon(plan.symbol, horizon, `horizon-${clientId.current}-${horizon}`);
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
      const done: Result = { state: "done", text };
      setResults(r => ({ ...r, [part]: done }));
      return done;
    } catch (failure) {
      const failed: Result = { state: "failed", text: failure instanceof Error ? failure.message : "Not done." };
      setResults(r => ({ ...r, [part]: failed }));
      return failed;
    }
  }

  async function retry(part: Part) {
    report({ ...results, [part]: await run(part) });
  }

  /** The plan first: its alerts are armed only once it is saved, so a failed save leaves nothing armed without a plan. */
  async function savePlanThenAlerts() {
    const all = { ...results, plan: await run("plan") };
    if (all.plan.state !== "done") return report(all);
    for (const part of parts.slice(1)) if (results[part].state !== "done") all[part] = await run(part);
    report(all);
    // Charts labels the levels this plan was drawn from, and shows its alerts.
    const detail: PlanConfirmed = { symbol: plan.symbol, side: plan.direction, entry: entryLevel.price, invalidation: stopLevel.price, drawn };
    window.dispatchEvent(new CustomEvent(PLAN_CONFIRMED, { detail }));
  }

  async function confirm() {
    if (!ready || started) return;
    setResults(r => ({ ...r, plan: { state: "working", text: "" } }));
    // Another window may have confirmed this card already: show what it did instead of saving and arming it again.
    const elsewhere = investigationId ? await confirmedElsewhere(investigationId, plan.id) : null;
    if (elsewhere) {
      const f = elsewhere.fields;
      if (f) { setThesis(f.thesis); setContract(f.contract); setEntry(f.entry); setStop(f.invalidation); setTimeStop(f.time_stop); setSize(f.size_note); setHorizon(f.horizon || null); }
      setResults(restored(elsewhere));
      onOutcome(elsewhere);
      return;
    }
    await savePlanThenAlerts();
  }

  const locked = started;
  return (
    <section aria-label="Proposed trade plan" className="mt-2 space-y-2 rounded border border-sky-500/30 bg-sky-500/5 p-3 text-sm">
      <p className="font-medium text-foreground">
        Proposed trade plan · {plan.symbol} · {SIDE_LABEL[side]}{contract ? ` · ${contract}` : ""}
      </p>
      {picks.length > 0 && (
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Contract</span>
          <select value={contract} onChange={e => setContract(e.target.value)} disabled={locked} className={cn(field, "min-h-11")}>
            <option value={plan.contract ?? ""}>{plan.contract ? `${plan.contract} (as drafted)` : "None named"}</option>
            {picks.map(p => (
              <option key={p.label} value={p.label}>
                {p.label} · {p.days}d{p.ask_contract !== null ? ` · $${p.ask_contract.toLocaleString("en-US")} ask` : ""}
              </option>
            ))}
          </select>
          <span className="block text-xs text-muted-foreground">
            From the option chain{candidates?.simulated ? " (simulated)" : ""}: trade-offs to weigh, not a recommendation.
          </span>
        </label>
      )}
      {plan.last !== undefined && <p className="text-xs text-muted-foreground">{plan.symbol} was {plan.last} when this was drafted.</p>}
      {drafting && <LastExitLine symbol={plan.symbol} lesson={lastExit} />}
      <label className="block space-y-1">
        <span className="text-xs text-muted-foreground">Thesis</span>
        <textarea value={thesis} onChange={e => setThesis(e.target.value.slice(0, 300))} rows={3} disabled={locked} className={field} />
      </label>
      <div className="grid grid-cols-2 items-end gap-2">
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Entry ({conditionText(plan.entry_trigger)})</span>
          <input value={entry} onChange={e => setEntry(e.target.value.slice(0, PRICE_MAX))} inputMode="decimal" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Invalidation ({conditionText(plan.invalidation)})</span>
          <input value={stop} onChange={e => setStop(e.target.value.slice(0, PRICE_MAX))} inputMode="decimal" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
      </div>
      {/* Below both inputs, in their columns, so a longer caption never moves one input out of line. */}
      {drawn && (
        <div className="-mt-1 grid grid-cols-2 gap-2">
          <FromDrawing name="Entry" drawn={drawn.trigger} value={entry} />
          <FromDrawing name="Invalidation" drawn={drawn.invalidation} value={stop} />
        </div>
      )}
      {drawn && drawn.side !== plan.direction && (
        <p role="note" className="text-xs text-amber-300">You drew a {drawn.side}; this draft is a {plan.direction}.</p>
      )}
      {history && (
        <p aria-label="Your history at this level" className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Your history at this level: </span>
          {Number(stop) === history.level && Number(entry) === history.entry ? (
            <>
              {historyText(history)}{history.small && " Too few trades to weigh."}{history.simulated && " (Simulated.)"}{" "}
              <a href={EVIDENCE_NOT_RULE_URL} target="_blank" rel="noreferrer" className="underline hover:text-foreground">why this is evidence, not a rule</a>
            </>
          ) : "you changed the levels; re-ask the copilot to refresh it."}
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
        <span className="text-xs text-muted-foreground">Horizon</span>
        <select value={horizon} onChange={e => setHorizon(e.target.value as DeskHorizon)} disabled={locked} aria-describedby={`horizon-${plan.id}`}
          className={cn(field, "min-h-11")}>
          {HORIZONS.map(h => <option key={h.id} value={h.id}>{h.label}</option>)}
        </select>
        <span id={`horizon-${plan.id}`} className="block text-xs text-muted-foreground">
          {horizon === "day" ? "The desk asks how it went after every close." : horizon === "swing" ? "The desk asks after a close only when something happened to it."
            : "No daily question; Review my week looks at it."}
        </span>
      </label>
      <div className="grid grid-cols-[6rem_1fr] items-end gap-2">
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Risk $</span>
          <input value={risk} onChange={e => { const v = e.target.value.replace(/[^\d.]/g, "").slice(0, 9); setRisk(v); rememberRisk(v); }}
            inputMode="decimal" placeholder="e.g. 150" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Size</span>
          <input value={size} onChange={e => { setSize(e.target.value.slice(0, SIZE_MAX)); if (sizing?.note) setSizeEdited(true); }}
            placeholder="e.g. one starter, no adds" disabled={locked} className={cn(field, "min-h-11")} />
        </label>
      </div>
      {sizing && (
        <div aria-label="Size it for me" className="space-y-0.5 text-xs text-muted-foreground">
          {sizing.lines.map(line => <p key={line}>{line}</p>)}
          {sizing.note && !locked && <p>{sizeEdited ? "Your size note is kept as you wrote it." : `Confirm puts this size in front of the size note${sizeText.endsWith("…") ? `, which is cut to fit ${SIZE_MAX} characters` : ""}.`}</p>}
        </div>
      )}
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
          {rows.map(part => {
            const r = results[part];
            return (
              <li key={part} className="flex flex-wrap items-center gap-2 text-xs">
                <span className={cn("font-medium", r.state === "done" ? "text-emerald-300" : r.state === "failed" ? "text-amber-300" : "text-muted-foreground")}>
                  {PART_LABEL[part]}: {r.state === "done" ? "done" : r.state === "failed" ? "failed" : r.state === "working" ? "working…" : "waits for the plan"}
                </span>
                {r.text && <span className={r.state === "failed" ? "text-amber-300" : "text-muted-foreground"}>{r.text}</span>}
                {r.state === "failed" && (
                  <button type="button" onClick={() => void (part === "plan" ? savePlanThenAlerts() : retry(part))} disabled={busy}
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
          <button type="button" onClick={() => { setDismissed(true); onOutcome({ state: "dismissed" }); }}
            className="min-h-11 rounded border px-4 py-2 text-muted-foreground hover:text-foreground">Dismiss</button>
          <span className="col-span-2 text-xs text-muted-foreground">Nothing is saved or armed until you confirm.</span>
        </div>
      )}
      {finished && <p role="status" className="text-xs text-emerald-300">Plan confirmed.</p>}
      {investigationId && (finished || saved) && <JoCaseAgainst investigationId={investigationId} proposalId={plan.id} />}
    </section>
  );
}
