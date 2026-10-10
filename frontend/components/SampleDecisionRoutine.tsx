"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl, type DecisionContext, type DecisionRecord } from "@/lib/api";
import { DecisionCard } from "@/components/PracticeDecisions";
import { useAppAccess } from "@/components/AccessProvider";
import FrozenSampleChart from "@/components/FrozenSampleChart";
import SampleReplayPanel, { type SampleReplay } from "@/components/SampleReplayPanel";
import { historicalExpiryInstant } from "@/lib/historicalExpiry";

type Opportunity = { id: string; symbol: string; context: DecisionContext; choice: DecisionRecord | null; take_unavailable?: string | null; replay?: SampleReplay | null };
type Run = { id: string; day: string; sample_data: boolean; market_data?: boolean; historical_replay?: boolean; operational_proof?: boolean; policy_version: string; deadline: string; replay_exercise?: boolean; opportunities: Opportunity[] };
const stamp = (value: string) => `${new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" })} ET`;

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export default function SampleDecisionRoutine({ day, marketOnly = false }: { day?: string | null; marketOnly?: boolean }) {
  const { grants } = useAppAccess();
  const market = marketOnly || grants.market_decision_write === true;
  const [runs, setRuns] = useState<Run[]>([]);
  const [active, setActive] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const activeHistorical = Boolean(active?.historical_replay || active?.opportunities.some(opp => opp.context.packet.historical_replay === true));
  // Choices are immutable: a slower reload/other choice response cannot hide
  // a receipt already accepted for this same run and opportunity.
  const acceptRun = useCallback((next: Run | null) => setActive(previous => {
    if (!next || previous?.id !== next.id) return next;
    return { ...next, opportunities: next.opportunities.map(opp => ({ ...opp,
      choice: opp.choice ?? previous.opportunities.find(saved => saved.id === opp.id)?.choice ?? null,
      replay: opp.replay ?? previous.opportunities.find(saved => saved.id === opp.id)?.replay ?? null })) };
  }), []);
  const load = useCallback(async () => {
    setError(""); setLoading(true);
    try {
      const result = await request<{ runs: Run[] }>(`/practice/runs${day ? `?day=${encodeURIComponent(day)}` : ""}`);
      const visible = market ? result.runs.filter(run => run.market_data) : result.runs;
      setRuns(visible);
      const linked = new URLSearchParams(window.location.search).get("practice_run");
      if (linked && !visible.some(run => run.id === linked)) throw new Error("This practice run is not assigned to your login for this date.");
      const selected = visible.find(run => run.id === linked) ?? visible[0];
      acceptRun(selected ? await request<Run>(`/practice/runs/${encodeURIComponent(selected.id)}`) : null);
    } catch (err) { setError(err instanceof Error ? err.message : "Sample practice could not be loaded."); }
    finally { setLoading(false); }
  }, [day, acceptRun, market]);
  useEffect(() => { void load(); }, [load]);

  return <section className="min-w-0 space-y-5 [overflow-wrap:anywhere]" data-testid="sample-decision-routine">
    <div><h2 className="text-xl font-semibold">{activeHistorical ? "Historical market replay practice" : market ? "Real market decision practice" : "Simulated decision practice"}</h2><p className="mt-2 text-sm text-muted-foreground">{activeHistorical ? "Retrospectively retrieved raw Alpaca prices for a past session. Save your own source-linked choice before any continuation is revealed; replay execution is simulated." : market ? "One manual MU/NBIS session using real frozen provider evidence. Save your own source-linked choice and review it afterward. Decisions stay unarmed; this is not a blind human/agent comparison." : "Invented MU/NBIS evidence. Save your own choice, then reopen the original record. This tests the workflow; an independent comparison has not been established."}</p></div>
    <div className="flex flex-wrap items-center gap-3"><button type="button" onClick={() => void load()} disabled={loading} className="rounded border px-3 py-2">Reload saved practice</button>{runs.map(run => <a key={run.id} className="text-primary underline" href={`/daily/${run.day}?practice_run=${run.id}`}>Review {run.historical_replay ? "historical market" : market ? "market" : "sample"} session {run.day}</a>)}</div>
    {error && <p role="alert" className="text-red-500">{error}</p>}
    {!active && !loading && !error && <p>No frozen practice run is assigned for this date.</p>}
    {active && <><p className="text-sm">{active.day} · {active.historical_replay ? "real decision deadline" : "decision window ends"} {stamp(active.deadline)} · {market ? "real-data decisions" : "simulated drafts"} stay unarmed.</p>
      {active.operational_proof && <p className="text-sm text-amber-500">Operational proof session · separate from Jo’s manual decision session.</p>}
      {active.opportunities.map(opp => <SampleOpportunity key={opp.id} opportunity={opp} run={active} onSaved={acceptRun} />)}</>}
  </section>;
}

function SampleOpportunity({ opportunity: opp, run, onSaved }: { opportunity: Opportunity; run: Run; onSaved: (run: Run) => void }) {
  const { grants, sample_replay_enabled, historical_replay_enabled, owner } = useAppAccess();
  const market = run.market_data === true;
  const historical = run.historical_replay === true || opp.context.packet.historical_replay === true;
  const canWrite = market
    ? grants.market_decision_write === true && (!historical || grants.historical_replay === true)
    : grants.decision_write === true;
  const [decision, setDecision] = useState<"take" | "wait" | "skip">("skip");
  const [rationale, setRationale] = useState("");
  const [condition, setCondition] = useState("");
  const [expiry, setExpiry] = useState(() => {
    if (historical) return "";
    const ends = new Date(run.deadline);
    return new Date(ends.getTime() - ends.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const expiryDate = new Date(expiry);
  const expiryInstant = historical ? historicalExpiryInstant(expiry)
    : Number.isFinite(expiryDate.getTime()) ? expiryDate.toISOString() : null;
  const historicalMaximum = typeof opp.context.packet.plan_expiry_max === "string" ? opp.context.packet.plan_expiry_max : null;
  const historicalCutoff = typeof opp.context.packet.simulated_as_of === "string" ? opp.context.packet.simulated_as_of : null;
  const expiryWithinHistoricalWindow = !historical || Boolean(expiryInstant && historicalMaximum && historicalCutoff
    && Date.parse(expiryInstant) > Date.parse(historicalCutoff) && Date.parse(expiryInstant) <= Date.parse(historicalMaximum));
  const expiryRequired = decision === "wait" || (market && decision === "take");
  const [expiryConfirmed, setExpiryConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reopened, setReopened] = useState(false);
  const [decisionOpenToken, setDecisionOpenToken] = useState(0);
  const [replayReopened, setReplayReopened] = useState(false);
  const [refs, setRefs] = useState({ trigger_fact: "", stop_fact: "", target_fact: "" });
  const [guardMax, setGuardMax] = useState("");
  const factValue = (name: string) => opp.context.price_facts.find(fact => fact.name === name)?.value;
  const plan = market ? { instrument: "stock", direction: "long", trigger: {kind: "close_beyond_level", interval: "15m", session: "regular"},
    ...refs, trigger_level: factValue(refs.trigger_fact), stop: factValue(refs.stop_fact), target: factValue(refs.target_fact),
    entry_guard: {min: factValue(refs.trigger_fact), max: Number(guardMax)}, expiry: expiryInstant,
    max_holding_sessions: 2, freshness_limit_seconds: 7200, cost_model: {version: "p0-cost-v1", slippage_bps: 1, slippage_per_share: .01}
  } as Record<string, unknown> : (opp.context.packet.sample_plan ?? {}) as Record<string, unknown>;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (historical && expiryRequired && (!expiryWithinHistoricalWindow || !expiryConfirmed)) {
      setError("Choose and confirm the historical expiry before saving."); return;
    }
    setBusy(true); setError("");
    try {
      const body = { decision, rationale, ...(decision === "take" ? { plan } : {}),
        ...(decision === "wait" ? { wait_condition: condition, wait_expiry: expiryInstant } : {}) };
      onSaved(await request<Run>(`/practice/opportunities/${encodeURIComponent(opp.id)}/agent-choice`, body));
    } catch (err) { setError(err instanceof Error ? err.message : "The decision was not saved. Reload before retrying if completion is uncertain."); }
    finally { setBusy(false); }
  }
  async function reopen() {
    if (!opp.choice) return;
    setError(""); setBusy(true);
    try {
      const record = await request<DecisionRecord>(`/decisions/${encodeURIComponent(opp.choice.id)}`);
      onSaved({ ...run, opportunities: run.opportunities.map(value => value.id === opp.id ? { ...value, choice: record } : value) });
      setReopened(true);
      if (historical) setDecisionOpenToken(value => value + 1);
    } catch (err) { setError(err instanceof Error ? err.message : "The saved record could not be reopened."); }
    finally { setBusy(false); }
  }
  async function replay(start: boolean) {
    setBusy(true); setError("");
    try {
      const next = start ? await request<Run>(`/practice/opportunities/${encodeURIComponent(opp.id)}/${historical ? "historical-replay" : "sample-replay"}`, {})
        : await request<Run>(`/practice/runs/${run.id}`);
      onSaved(next); setReplayReopened(!start);
    } catch (err) { setError(err instanceof Error ? err.message : "Reload before retrying an uncertain replay."); }
    finally { setBusy(false); }
  }
  return <article className="space-y-4 rounded-lg border bg-card p-4" aria-label={`${opp.symbol} ${historical ? "historical" : market ? "market" : "sample"} opportunity`}>
    <div className="flex flex-wrap items-center gap-3"><h3 className="text-lg font-semibold">{opp.symbol}</h3>{!market && <a href={`/charts?symbol=${opp.symbol}`} className="text-primary underline">Open {opp.symbol} chart</a>}<a href={`/daily/${run.day}?practice_run=${run.id}`} className="text-primary underline">Daily Review</a></div>
    {historical ? <HistoricalEvidence opportunity={opp} deadline={run.deadline} /> : market ? <MarketEvidence opportunity={opp} /> : <div className="space-y-2 text-sm"><p><strong>Frozen sample evidence</strong> · captured {stamp(opp.context.captured_at)} · {opp.context.price_facts.length} timestamped price facts</p><p>Source: simulated bars · USD per share · cutoff {stamp(opp.context.captured_at)}</p><p>{String(opp.context.packet.scenario)}</p><p>Sample long plan: trigger ${String(plan.trigger_level ?? "unavailable")}, stop ${String(plan.stop ?? "unavailable")}, target ${String(plan.target ?? "unavailable")}. A regular-session 15-minute close above the trigger is the stated condition; the plan uses fixed levels, an entry guard, and a two-session maximum.</p><p className="text-muted-foreground">EMA/RSI charts use a separate simulated chart window. Live news, options and daily history are outside this exercise. No model calls, monitoring or execution are started by saving.</p><details><summary className="cursor-pointer">Inspect frozen packet and rules</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(opp.context, null, 2)}</pre></details></div>}
    {(historical || run.replay_exercise) && <p className="text-sm text-muted-foreground">{historical ? "Historical continuation stays sealed until you start your saved TAKE. WAIT/SKIP create no replay or paper entry." : <>{String(opp.context.packet.replay_notice)} The hidden continuation is revealed only after you start a saved TAKE. WAIT/SKIP produce no paper entry.</>}</p>}
    <div className="grid min-w-0 gap-4 xl:grid-cols-2"><FrozenSampleChart context={opp.context} /><div className="min-w-0 space-y-4">
    {opp.choice ? <><p role="status">Saved decision {opp.choice.id}{reopened ? " · original record reopened" : ""}.</p><button type="button" disabled={busy} onClick={() => void reopen()} className="rounded border px-3 py-2">Reopen saved {opp.symbol} decision</button><DecisionCard record={opp.choice} focused={historical && reopened} openToken={historical ? decisionOpenToken : undefined} withPaper={false} idPrefix="routine-" /></> : market && (owner || !canWrite) ? <p>Jo has not saved a decision for this opportunity. This login can inspect the session only.</p> : <form onSubmit={save} className="grid gap-3 text-sm">
      <label className="grid gap-1">{opp.symbol} choice<select value={decision} onChange={event => { setDecision(event.target.value as typeof decision); setExpiryConfirmed(false); }} className="rounded border bg-background p-2"><option value="take" disabled={market && Boolean(opp.take_unavailable)}>TAKE · {historical ? "historical paper plan" : market ? "unarmed real-data draft" : "simulated draft"}</option><option value="wait">WAIT</option><option value="skip">SKIP</option></select></label>
      <label className="grid gap-1">{opp.symbol} reason<textarea required maxLength={2000} value={rationale} onChange={event => setRationale(event.target.value)} className="rounded border bg-background p-2" rows={3} /></label>
      {decision === "take" && !market && <p>Saving TAKE uses the frozen sample plan above, including its entry guard, expiry and sample cost assumptions. It cannot be armed.</p>}
      {market && decision === "take" && <>
        {(["trigger_fact", "stop_fact", "target_fact"] as const).map(role => <label key={role} className="grid gap-1">{opp.symbol} {role.replace("_fact", "")} source fact<select required value={refs[role]} onChange={event => setRefs({...refs, [role]: event.target.value})} className="min-w-0 rounded border bg-background p-2"><option value="">Choose a frozen fact</option>{opp.context.price_facts.map(fact => <option key={fact.name} value={fact.name}>{fact.name} = ${fact.value} · {stamp(fact.formed_at)}</option>)}</select></label>)}
        <label className="grid gap-1">{opp.symbol} maximum reference entry price<input required type="number" min="0" step="any" value={guardMax} onChange={event => setGuardMax(event.target.value)} className="rounded border bg-background p-2" /></label>
        <p>The reference entry starts at the selected trigger. Stop must be below trigger; target must be above the maximum entry. Saving commits a conditional long plan, not an entry or monitoring request.</p>
      </>}
      {expiryRequired && <>
        {decision === "wait" && <label className="grid gap-1">{opp.symbol} wait condition<input required maxLength={500} value={condition} onChange={event => { setCondition(event.target.value); setExpiryConfirmed(false); }} className="rounded border bg-background p-2" /></label>}
        <label className="grid gap-1">{opp.symbol} {decision === "wait" ? "waiting" : "plan"} ends ({historical ? "historical clock · Eastern time" : browserTimeZone})<input required type={historical ? "text" : "datetime-local"} placeholder={historical ? "YYYY-MM-DD HH:mm" : undefined} value={expiry} onChange={event => { setExpiry(event.target.value); setExpiryConfirmed(false); }} aria-invalid={historical && Boolean(expiry) && !expiryWithinHistoricalWindow} aria-describedby={`${opp.id}-expiry-preview`} className="rounded border bg-background p-2" /></label>
        <p id={`${opp.id}-expiry-preview`} className="text-muted-foreground">{expiryInstant ? <>Will save as <time dateTime={expiryInstant}>{stamp(expiryInstant)}</time>. {historical ? <>UTC: <code>{expiryInstant}</code>. Plan expiry maximum {historicalMaximum ? stamp(historicalMaximum) : "unavailable"}; real decision deadline {stamp(run.deadline)}.</> : "Daily Review shows Eastern time."}</> : historical ? "Enter YYYY-MM-DD HH:mm in Eastern time. Choose a valid, unambiguous date and time." : "Choose an expiry to preview its Eastern time."}</p>
        {historical && expiryInstant && !expiryWithinHistoricalWindow && <p role="alert">Expiry must be after the historical cutoff {historicalCutoff ? stamp(historicalCutoff) : "unavailable"} and no later than {historicalMaximum ? stamp(historicalMaximum) : "unavailable"}.</p>}
        {historical && expiryWithinHistoricalWindow && <label className="flex items-start gap-2"><input required type="checkbox" checked={expiryConfirmed} onChange={event => setExpiryConfirmed(event.target.checked)} />Confirm {opp.symbol} expiry matches my condition or plan: {stamp(expiryInstant!)}.</label>}
      </>}
      <button disabled={busy || !canWrite || (market && decision === "take" && Boolean(opp.take_unavailable)) || (expiryRequired && (!expiryWithinHistoricalWindow || (historical && !expiryConfirmed)))} className="w-fit rounded bg-primary px-4 py-2 text-primary-foreground">Save {opp.symbol} decision</button>
    </form>}
    {(historical ? opp.choice?.decision === "take" : run.replay_exercise && Boolean(opp.choice)) && opp.choice && <SampleReplayPanel symbol={opp.symbol} decision={opp.choice.decision} value={opp.replay ?? null} busy={busy} canStart={historical ? Boolean(!owner && canWrite && historical_replay_enabled) : Boolean(grants.sample_replay && sample_replay_enabled)} reopened={replayReopened} historical={historical} onStart={() => void replay(true)} onReopen={() => void replay(false)} />}
    {error && <p role="alert" className="text-red-500">{error}</p>}
    </div></div>
  </article>;
}

function MarketEvidence({opportunity: opp}: {opportunity: Opportunity}) {
  const bars = opp.context.packet.recent_minute_bars as {t: string}[];
  return <div className="space-y-2 text-sm">
    <p><strong>Frozen real-market evidence</strong> · captured {stamp(opp.context.captured_at)} · {opp.context.price_facts.length} timestamped price facts</p>
    <p>Source: {opp.context.provider} · raw USD/share · volume in shares · newest minute starts {bars[0] ? stamp(bars[0].t) : "unavailable"}.</p>
    <p>Only completed regular-session minutes are included. Gaps remain missing. {opp.context.provider === "alpaca_iex" ? "IEX prices and volumes are not consolidated market coverage." : "Coverage follows the named provider and supplied bars."} News, options and daily history are unavailable in this pilot.</p>
    <CoverageSummary packet={opp.context.packet} />
    {opp.take_unavailable && <p role="status" className="text-amber-500">{opp.take_unavailable}. WAIT/SKIP remain available until the decision deadline.</p>}
    <p>TAKE is available only during the verified regular session with a latest frozen minute no older than five minutes. The server rechecks freshness on save. No watcher, replay or broker order is started.</p>
    <details><summary className="cursor-pointer">Inspect frozen packet and rules</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(opp.context, null, 2)}</pre></details>
  </div>;
}

function HistoricalEvidence({opportunity: opp, deadline}: {opportunity: Opportunity; deadline: string}) {
  const packet = opp.context.packet;
  const cutoff = typeof packet.simulated_as_of === "string" ? packet.simulated_as_of : "";
  const bars = Array.isArray(packet.recent_minute_bars) ? packet.recent_minute_bars as {t: string}[] : [];
  const newest = [...bars].sort((a, b) => Date.parse(b.t) - Date.parse(a.t))[0];
  const ageSeconds = newest && cutoff ? Math.max(0, Math.floor((Date.parse(cutoff) - (Date.parse(newest.t) + 60_000)) / 1000)) : null;
  return <div className="space-y-2 text-sm">
    <p><strong>Historical market evidence</strong> · provider retrieved {stamp(typeof packet.retrieved_at === "string" ? packet.retrieved_at : opp.context.captured_at)} · {opp.context.price_facts.length} timestamped price facts</p>
    <p>Source: {opp.context.provider} · raw USD/share · volume in shares · original bar timestamps are retained.</p>
    <p>Simulated information cutoff {cutoff ? stamp(cutoff) : "unavailable"}. Real decision deadline {stamp(deadline)}. These clocks are separate.</p>
    <p>Newest completed minute {newest ? stamp(new Date(Date.parse(newest.t) + 60_000).toISOString()) : "unavailable"}; age at simulated cutoff {ageSeconds === null ? "unavailable" : `${Math.floor(ageSeconds / 60)}m ${ageSeconds % 60}s`} · latest-bar eligibility limit 5 minutes · selected plan-fact freshness limit 120 minutes at the cutoff. {opp.take_unavailable ? `TAKE eligibility: unavailable · ${opp.take_unavailable}` : ageSeconds !== null && ageSeconds <= 300 ? "Latest-bar age is within the limit; source-linked plan-fact freshness and plan validation still apply at save." : "Latest-bar age is outside the limit or unavailable."}</p>
    <CoverageSummary packet={packet} />
    <details><summary className="cursor-pointer">Historical price facts and source times</summary><div className="mt-2 space-y-2">{opp.context.price_facts.map(fact=><p key={fact.name} className="break-words">{fact.name}: {fact.value} {fact.unit} · {fact.source} · formed {stamp(fact.formed_at)} · observed {stamp(fact.observed_at)}</p>)}</div></details>
    <p className="text-muted-foreground">Historical prices may include provider corrections made after the original session. Replay execution is simulated. Frozen split coverage is unavailable: replay evaluates the first session only, and an outcome needing the next session becomes unresolved. No provider request or live route is started from this screen.</p>
    <details><summary className="cursor-pointer">Inspect frozen packet and rules</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(opp.context, null, 2)}</pre></details>
  </div>;
}

function CoverageSummary({packet}: {packet: Record<string, unknown>}) {
  const raw = Array.isArray(packet.recent_minute_bars) ? packet.recent_minute_bars as {t?: unknown}[] : [];
  const starts = raw.map(bar => typeof bar.t === "string" ? Date.parse(bar.t) : NaN).filter(Number.isFinite).sort((a,b) => a-b);
  const present = new Set(starts);
  const absent: number[] = [];
  const declaredStart = typeof packet.window_start === "string" ? Date.parse(packet.window_start) : NaN;
  const declaredEnd = typeof packet.window_end === "string" ? Date.parse(packet.window_end) : NaN;
  const bounded = Number.isFinite(declaredStart) && Number.isFinite(declaredEnd) && declaredStart < declaredEnd
    && declaredEnd - declaredStart <= 240 * 60_000 && declaredStart % 60_000 === 0 && declaredEnd % 60_000 === 0;
  const rangeStart = bounded ? declaredStart : starts[0];
  const rangeEnd = bounded ? declaredEnd : starts.at(-1) === undefined ? NaN : starts.at(-1)! + 60_000;
  if (Number.isFinite(rangeStart) && Number.isFinite(rangeEnd)) {
    for (let at=rangeStart; at<rangeEnd; at+=60_000) if (!present.has(at)) absent.push(at);
  }
  const partial: {at: number; count: number}[] = [];
  if (Number.isFinite(rangeStart) && Number.isFinite(rangeEnd) && rangeStart < rangeEnd) {
    const first = Math.floor(rangeStart / 900_000) * 900_000;
    const last = Math.floor((rangeEnd - 1) / 900_000) * 900_000;
    for (let at=first; at<=last; at+=900_000) {
      const count = starts.filter(minute => minute >= at && minute < at + 900_000).length;
      if (count < 15) partial.push({at, count});
    }
  }
  const failures = Array.isArray(packet.missing) ? packet.missing : [];
  const stampAt = (at: number) => `${new Date(at).toLocaleString("en-US", {timeZone:"America/New_York"})} ET`;
  return <div className="space-y-1 rounded bg-muted/40 p-2" aria-label="Minute coverage summary">
    <p><strong>Supplied minute coverage</strong> · {absent.length} missing minute slot{absent.length === 1 ? "" : "s"} {bounded ? "in the declared coverage window" : "between first and last supplied bars"} · {partial.length} partial 15-minute interval{partial.length === 1 ? "" : "s"}. Partial intervals never confirm a trigger.</p>
    {absent.length > 0 && <details><summary className="cursor-pointer">Original missing minute timestamps ({absent.length})</summary><ul className="mt-1 max-h-40 overflow-auto">{absent.map(at=><li key={at}>{stampAt(at)}</li>)}</ul></details>}
    {partial.length > 0 && <details><summary className="cursor-pointer">Partial 15-minute intervals ({partial.length})</summary><ul className="mt-1 max-h-40 overflow-auto">{partial.map(({at,count})=><li key={at}>{stampAt(at)} · {count}/15 supplied</li>)}</ul></details>}
    <p>Packet input failures: {failures.length ? failures.map(String).join("; ") : "none reported"}.</p>
  </div>;
}
