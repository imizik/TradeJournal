"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import FrozenSampleChart from "@/components/FrozenSampleChart";
import { getReplayAttempt, listReplayScenarios, revealReplayCheckpoint, saveReplayChoice, startReplayAttempt, type ReplayAttempt, type ReplayChoice, type ReplayScenario } from "@/lib/personalReplay";

const stamp = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" }) + " ET";
const stampExact = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }) + " ET";
const money = (value: number | null) => value == null ? "Unavailable" : `$${value.toFixed(2)}`;
const pct = (value: number | null) => value == null ? "Unavailable" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
const markSourceLabel = (value: string | null) => value === "synthetic_option_mark" ? "Invented option mark" : value ?? "Source unavailable";
const planStateLabel = (value: string) => value === "captured_before_checkpoint" ? "Captured before this checkpoint" : value.replaceAll("_", " ");
const expiryLabel = (value: string) => {
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" }) : value;
};

export default function PersonalReplay({ initialAttemptId }: { initialAttemptId: string | null }) {
  const [scenarios, setScenarios] = useState<ReplayScenario[]>([]);
  const [attempt, setAttempt] = useState<ReplayAttempt | null>(null);
  const [decision, setDecision] = useState<ReplayChoice["decision"] | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attemptLoading, setAttemptLoading] = useState(Boolean(initialAttemptId));
  const revealedHeading = useRef<HTMLHeadingElement>(null);
  const completionHeading = useRef<HTMLHeadingElement>(null);
  const readVersion = useRef(0);

  const loadAttempt = useCallback(async (id: string) => {
    const version = ++readVersion.current;
    setAttemptLoading(true);
    setDecision(null);
    setRationale("");
    setAttempt(null);
    setError("");
    try { const next = await getReplayAttempt(id); if (version === readVersion.current) setAttempt(next); }
    catch (err) { if (version === readVersion.current) setError(err instanceof Error ? err.message : "Saved replay could not be loaded."); }
    finally { if (version === readVersion.current) setAttemptLoading(false); }
  }, []);

  useEffect(() => {
    let active = true;
    void listReplayScenarios().then(data => { if (active) setScenarios(data.scenarios); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : "Replay scenarios could not be loaded."); });
    if (initialAttemptId) void Promise.resolve().then(() => { if (active) return loadAttempt(initialAttemptId); });
    else void Promise.resolve().then(() => { if (active) { setAttempt(null); setAttemptLoading(false); } });
    return () => { active = false; readVersion.current += 1; };
  }, [initialAttemptId, loadAttempt]);

  const revealTransition = attempt ? `${attempt.phase}:${attempt.revealed.length}` : "";
  useEffect(() => {
    if (revealTransition.endsWith(":0")) return;
    const target = revealTransition.startsWith("complete:") ? completionHeading.current : revealedHeading.current;
    if (target) {
      target.focus();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [revealTransition]);

  async function start() {
    readVersion.current += 1;
    setDecision(null); setRationale("");
    setBusy(true); setError("");
    let key: string | null = null;
    try {
      key = "tj-personal-replay-operation";
      let operationId = sessionStorage.getItem(key);
      if (!operationId) { operationId = crypto.randomUUID(); sessionStorage.setItem(key, operationId); }
      const next = await startReplayAttempt(operationId);
      sessionStorage.removeItem(key);
      setAttempt(next);
      history.pushState({}, "", `/practice/replay?attempt=${encodeURIComponent(next.attempt_id)}`);
    } catch (err) { setError(err instanceof Error ? err.message : "Replay could not start. Retry safely with the same request."); }
    finally { setBusy(false); }
  }

  async function saveChoice(event: React.FormEvent) {
    event.preventDefault();
    if (!attempt?.checkpoint) return;
    setBusy(true); setError("");
    try {
      if (!decision) return;
      const next = await saveReplayChoice(attempt.attempt_id, attempt.checkpoint.id, decision, rationale);
      setAttempt(next);
      setRationale("");
    } catch (err) { setError(err instanceof Error ? err.message : "Choice may not have saved. Reload this replay before retrying."); }
    finally { setBusy(false); }
  }

  async function reveal() {
    if (!attempt?.checkpoint || !attempt.choice) return;
    setBusy(true); setError("");
    try { setAttempt(await revealReplayCheckpoint(attempt.attempt_id, attempt.checkpoint.id)); setDecision(null); }
    catch (err) { setError(err instanceof Error ? err.message : "The reveal could not be loaded."); }
    finally { setBusy(false); }
  }

  const checkpoint = attempt?.checkpoint;
  const activeScenario = scenarios.find(row => row.id === attempt?.scenario_id) ?? scenarios[0];
  const optionContract = checkpoint?.position.option_contract ?? activeScenario?.option_contract;
  const contractLabel = optionContract ? `${activeScenario?.symbol ?? "XYZ"} ${optionContract.right[0].toUpperCase()}${optionContract.right.slice(1)} $${optionContract.strike} · expires ${expiryLabel(optionContract.expiry)} · ${optionContract.dte_at_entry} DTE at entry` : activeScenario ? `${activeScenario.symbol} · ${activeScenario.instrument}` : "";
  return <div className="min-w-0 space-y-4" data-testid="personal-replay">
    {!attempt && <section className="rounded-lg border bg-card p-4 sm:p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">One synthetic scenario · two decision points</p>
      {attemptLoading ? <p role="status">Resuming saved replay…</p> : activeScenario && !initialAttemptId && !error ? <><h2 className="mt-2 text-xl font-semibold">{activeScenario.title}</h2><p className="mt-1 text-sm">{activeScenario.symbol} · {activeScenario.instrument}</p><p className="mt-2 text-sm text-muted-foreground">{activeScenario.description}</p><p className="mt-3 text-xs text-muted-foreground">Invented position and price path. No real journal records or live market feed. Option marks are synthetic reference estimates, not executable fills.</p>{activeScenario.repeat_status === "repeat" && <p className="mt-2 text-sm text-amber-400">You have opened this scenario before. Starting again creates a new attempt and does not change saved choices.</p>}<div className="mt-4 flex flex-wrap items-center gap-3">{activeScenario.latest_attempt_id && <a href={`/practice/replay?attempt=${encodeURIComponent(activeScenario.latest_attempt_id)}`} className="inline-flex min-h-11 items-center rounded border px-4 py-2 text-primary underline">Resume last replay</a>}<button type="button" disabled={busy} onClick={() => void start()} className="min-h-11 rounded bg-primary px-4 py-2 font-medium text-primary-foreground">{busy ? "Opening replay…" : "Start replay"}</button></div></> : !error && <p>Loading the available replay…</p>}
    </section>}

    {attempt && <>
      <section className="rounded-lg border bg-card p-4 sm:p-5">
        {attempt.revealed.map((item, index) => { const first = item.continuation[0]; const last = item.continuation.at(-1); return <article key={item.checkpoint_id} className="mb-4 space-y-2 rounded border border-emerald-700/40 bg-emerald-950/10 p-3" data-testid={`replay-reveal-${item.checkpoint_id}`} aria-live="polite"><h3 ref={index === attempt.revealed.length - 1 ? revealedHeading : undefined} tabIndex={-1} className="font-semibold focus:outline-none">After checkpoint {index + 1}</h3><p className="text-sm">Your choice: {item.choice.decision}{item.choice.rationale ? ` · “${item.choice.rationale}”` : ""}</p><p className="text-sm">Recorded synthetic action: {item.actual_action.decision} {item.actual_action.contracts} contracts{item.actual_action.at ? ` at ${stamp(item.actual_action.at)}` : item.actual_action.fill ? ` filled at ${stamp(item.actual_action.fill.filled_at)} for $${item.actual_action.fill.price_per_contract.toFixed(2)} per contract` : " · time unavailable"}.</p><details className="rounded border p-2 text-xs"><summary className="cursor-pointer font-medium">What was knowable at checkpoint {index + 1}</summary><p className="mt-1">Cutoff: {stamp(item.checkpoint.input_cutoff)} · {item.checkpoint.position.contracts} contracts · entry {money(item.checkpoint.position.entry_premium_per_contract)} each · estimated mark {money(item.checkpoint.position.checkpoint_mark_per_contract)} · open return {pct(item.checkpoint.position.open_return_pct)}.</p><div className="mt-2"><FrozenSampleChart compact decisionReplay context={item.checkpoint.chart_context} /></div></details><div><p className="text-sm">Following underlying closes: {item.continuation.length ? <>{item.continuation.length} synthetic 1-minute bars from {stamp(first!.interval_start)} to {stamp(last!.interval_end)}; close moved ${first!.close.toFixed(2)} → ${last!.close.toFixed(2)}.</> : "No eligible bars are available."}</p>{item.continuation.length > 0 && <details className="mt-2 rounded border p-2 text-xs"><summary className="cursor-pointer">Inspect per-bar prices and source times</summary><div className="mt-2 max-h-56 overflow-auto"><table className="min-w-full text-left"><thead><tr>{["End ET", "Close", "Observed", "Published", "Retrieved", "Source"].map(label => <th key={label} className="whitespace-nowrap px-2 py-1">{label}</th>)}</tr></thead><tbody>{item.continuation.map(bar => <tr key={bar.interval_start} className="border-t"><th className="whitespace-nowrap px-2 py-1 font-normal">{stamp(bar.interval_end)}</th><td className="px-2 py-1 tabular-nums">${bar.close.toFixed(2)}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.observed_at)}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.published_at)}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.retrieved_at)}</td><td className="whitespace-nowrap px-2 py-1">{bar.source} · {bar.price_basis}</td></tr>)}</tbody></table></div></details>}</div><div className="rounded border p-2 text-sm"><p className="font-medium">Plan and choice reflection</p><p className="mt-1 text-xs text-muted-foreground">Original plan, captured {item.original_plan.captured_at ? stamp(item.original_plan.captured_at) : "time unavailable"}: {item.original_plan.text ?? "unavailable"}</p><p className="mt-1">Your reason: {item.choice.rationale || "No reason recorded."}</p><p className="mt-1 text-xs text-muted-foreground">Consider where your decision fit or differed from the plan. There is no automatic grading; the later path cannot establish whether your reasoning was sound.</p></div>{item.final_outcome && <div className="rounded border p-2"><p className="text-sm font-medium">Synthetic realized P&amp;L: {item.final_outcome.pnl.value >= 0 ? "+" : "−"}${Math.abs(item.final_outcome.pnl.value).toFixed(2)} {item.final_outcome.pnl.unit}.</p><p className="mt-1 text-xs text-muted-foreground">{item.final_outcome.pnl.status}. It comes from invented fixture fills and says nothing about executable counterfactual returns.</p><p className="mt-1 text-xs text-muted-foreground">Later retrospective rationale: {item.final_outcome.later_retrospective_rationale.status} — {item.final_outcome.later_retrospective_rationale.reason}</p></div>}</article>; })}
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs font-medium uppercase tracking-wide text-primary">{attempt.phase === "complete" ? "Replay complete" : `Checkpoint ${attempt.revealed.length + 1} of 2`}</p><h2 ref={attempt.phase === "complete" ? completionHeading : undefined} tabIndex={-1} className="mt-1 text-xl font-semibold focus:outline-none">{activeScenario?.title ?? "Trade decision replay"}</h2><p className="mt-1 text-sm text-muted-foreground">{contractLabel}</p></div>{attempt.repeated && <span className="rounded border px-2 py-1 text-xs text-muted-foreground">Repeated attempt · choices are new</span>}</div>
        {checkpoint && <><p className="mt-3 text-sm">Information cutoff: <time dateTime={checkpoint.input_cutoff}>{stamp(checkpoint.input_cutoff)}</time></p>
          <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(17rem,0.7fr)]">
            <div className="min-w-0"><FrozenSampleChart compact decisionReplay context={checkpoint.chart_context} />
              <details className="mt-2 rounded border p-3 text-xs"><summary className="cursor-pointer">Inspect {checkpoint.bars.length} frozen bars and source times</summary><div className="mt-2 max-h-72 overflow-auto"><table className="min-w-full text-left"><thead><tr>{["Interval ET", "O", "H", "L", "C", "Volume", "Observed", "Published", "Retrieved", "Source · basis"].map(label => <th key={label} className="whitespace-nowrap px-2 py-1">{label}</th>)}</tr></thead><tbody>{checkpoint.bars.map(bar => <tr key={bar.interval_start} className="border-t"><th className="whitespace-nowrap px-2 py-1 font-normal">{stamp(bar.interval_start)}–{stamp(bar.interval_end)}</th>{[bar.open, bar.high, bar.low, bar.close].map((price, index) => <td key={index} className="px-2 py-1 tabular-nums">${price.toFixed(2)}</td>)}<td className="px-2 py-1 tabular-nums">{bar.volume.toLocaleString("en-US")}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.observed_at)}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.published_at)}</td><td className="whitespace-nowrap px-2 py-1">{stampExact(bar.retrieved_at)}</td><td className="whitespace-nowrap px-2 py-1">{bar.source} · {bar.price_basis}</td></tr>)}</tbody></table></div></details>
            </div>
            <div className="min-w-0 space-y-3"><div className="rounded border p-3"><p className="text-xs uppercase tracking-wide text-muted-foreground">Position at this moment</p><p className="mt-1 font-medium">{checkpoint.position.contracts} contracts · entry {money(checkpoint.position.entry_premium_per_contract)} per contract</p><p className="mt-1 text-sm">Estimated reference mark {money(checkpoint.position.checkpoint_mark_per_contract)} · open return {pct(checkpoint.position.open_return_pct)}</p><p className="mt-1 text-sm">Peak open return so far {pct(checkpoint.position.peak_open_return_pct)}</p><p className="mt-2 text-xs text-muted-foreground">{checkpoint.position.mark_type ?? "Mark type unavailable"} · {markSourceLabel(checkpoint.position.mark_source)}{checkpoint.position.mark_time ? ` · as of ${stamp(checkpoint.position.mark_time)}` : ""}</p><details className="mt-2 text-xs"><summary className="cursor-pointer">Mark evidence</summary><p className="mt-1 break-all">Source identifier: {checkpoint.position.mark_source ?? "unavailable"}</p><p>Observed: {checkpoint.position.mark_observed_at ? stampExact(checkpoint.position.mark_observed_at) : "unavailable"}</p><p>Published: {checkpoint.position.mark_published_at ? stampExact(checkpoint.position.mark_published_at) : "unavailable"}</p><p>Retrieved: {checkpoint.position.mark_retrieved_at ? stampExact(checkpoint.position.mark_retrieved_at) : "unavailable"}</p><p>Peak reference mark time: {checkpoint.position.peak_mark_time ? stampExact(checkpoint.position.peak_mark_time) : "unavailable"}</p><p>Historical bid/ask, Greeks and news: unavailable.</p><p>Evidence status: {checkpoint.evidence_status}</p></details></div>
              <div className="rounded border p-3"><p className="text-xs uppercase tracking-wide text-muted-foreground">Original plan</p><p className="mt-1 text-sm">{checkpoint.original_plan.text ?? "Plan text unavailable."}</p><p className="mt-2 text-xs text-muted-foreground">{checkpoint.original_plan.source} · {planStateLabel(checkpoint.original_plan.state)}{checkpoint.original_plan.captured_at ? ` · captured ${stamp(checkpoint.original_plan.captured_at)}` : ""}</p></div>
              {checkpoint.id === "later-look" && <p className="text-xs text-muted-foreground">Practice choices do not change the historical path. This checkpoint still shows the original position.</p>}
              {attempt.choice ? <div className="space-y-3 rounded border border-primary/40 p-3" data-testid="saved-replay-choice"><p role="status" className="font-medium">Saved before reveal: {attempt.choice.decision}{attempt.choice.rationale ? ` · “${attempt.choice.rationale}”` : ""}</p><p className="text-sm text-muted-foreground">Your choice is fixed. Reveal the next moment to continue.</p><button type="button" disabled={busy} onClick={() => void reveal()} className="min-h-11 w-full rounded bg-primary px-4 py-2 font-medium text-primary-foreground">{busy ? "Revealing…" : "Reveal what happened next"}</button></div> : <form onSubmit={saveChoice} className="space-y-3 rounded border p-3" data-testid="replay-choice-form"><fieldset disabled={busy} className="space-y-3"><legend className="font-semibold">What would you do?</legend><div className="grid grid-cols-3 gap-2">{(["hold", "reduce", "exit"] as const).map(value => <button key={value} type="button" aria-label={value === "reduce" ? "Reduce" : value[0].toUpperCase() + value.slice(1)} aria-pressed={decision === value} onClick={() => setDecision(value)} className={`min-h-11 rounded border px-2 capitalize ${decision === value ? "border-primary bg-primary/10 text-primary" : ""}`}>{value}</button>)}</div>
                <p className="text-xs text-muted-foreground">Reduce means sell one of the two contracts. Your practice action does not change the historical position shown at the next checkpoint.</p>
                <label className="grid gap-1 text-sm">Why? <span className="font-normal text-muted-foreground">Optional, one sentence is enough.</span><textarea maxLength={240} rows={2} value={rationale} onChange={event => setRationale(event.target.value)} className="rounded border bg-background p-2" placeholder="Add a reason, or leave this blank." /></label>
                <button disabled={!decision} className="min-h-11 w-full rounded bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50">Save my choice</button></fieldset></form>}
            </div>
          </div>
        </>}
        {attempt.phase === "complete" && <div className="mt-4 space-y-3 rounded border p-3" data-testid="replay-comparison"><h3 className="font-semibold">Practice versus history</h3><div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Practice choices compared with the synthetic recorded actions</caption><thead><tr><th className="px-2 py-2">Moment</th><th className="px-2 py-2">Your choice</th><th className="px-2 py-2">Recorded action</th></tr></thead><tbody>{attempt.revealed.map((item, index) => <tr key={item.checkpoint_id} className="border-t"><th scope="row" className="px-2 py-2 font-medium">{index === 0 ? "First look" : "Later look"}</th><td className="px-2 py-2">{item.choice.decision}</td><td className="px-2 py-2">{item.actual_action.decision}</td></tr>)}</tbody></table></div><p className="text-sm text-muted-foreground">Known before each choice: only the frozen position, original plan and underlying bars shown by that cutoff. Missing: contemporaneous later reasoning. The recorded scenario path continued independently of your practice choices.</p><p className="text-sm text-muted-foreground">Option marks are estimates, not executable fills. Synthetic realized P&amp;L comes from invented fills and cannot tell us what an unchosen hold, reduction or exit would have earned. There is no automatic score.</p><button type="button" disabled={busy} onClick={() => void start()} className="min-h-11 rounded border px-4 py-2">Try this scenario again with new choices</button></div>}
      </section>
    </>}
    {error && <p role="alert" className="rounded border border-red-500/50 p-3 text-sm text-red-400">{error} <button type="button" className="ml-2 underline" onClick={() => attempt ? void loadAttempt(attempt.attempt_id) : window.location.reload()}>Reload and recover</button></p>}
  </div>;
}
