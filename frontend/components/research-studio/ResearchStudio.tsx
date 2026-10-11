"use client";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import ResearchChart from "./ResearchChart";
import type { Chart, Definition, Occurrence, Population, Result, Status } from "./types";

type Config = {universe: string[]; start: string; end: string; features: Record<string, string>};
const initial: Definition = {version: 1, predicates: [{feature: "move_15m_atr", minimum: null, maximum: -.25}, {feature: "rvol", minimum: 1.5, maximum: null}], universe: ["MU"], start: "2023-07-03", end: "2024-09-30", window_start: 600, window_end: 690};
const field = "rounded border bg-background px-2 py-1 text-sm min-w-0";
const button = "rounded border px-3 py-1.5 text-sm hover:bg-secondary disabled:opacity-40";
const number = (v: number | null) => v === null ? "Unavailable" : v.toFixed(3);
function key(d: Definition) { return JSON.stringify({ version: d.version, start: d.start, end: d.end, window_start: d.window_start, window_end: d.window_end, universe: [...d.universe].sort(), predicates: d.predicates.map(p => ({ feature: p.feature, minimum: p.minimum, maximum: p.maximum })).sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) }); }
class ResearchError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function command<T>(action: string, args: object = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl("/research-studio/command"), {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, arguments: args}), signal, cache: "no-store"});
  const data = await response.json(); if (!response.ok) throw new ResearchError(data.detail || "Research unavailable", response.status); return data;
}
async function prepared<T>(action: string, args: object, signal?: AbortSignal): Promise<T> {
  const deadline = performance.now() + 65000;
  while (true) {
    try { return await command<T>(action, args, signal); }
    catch (error) {
      if (!(error instanceof ResearchError) || error.status !== 409 || !error.message.includes("preparation is busy") || signal?.aborted || performance.now() >= deadline) throw error;
      await new Promise<void>(resolve => setTimeout(resolve, 100));
      if (signal?.aborted) throw new Error("Preview superseded");
    }
  }
}
function et(stamp: string) { return new Date(stamp).toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" }); }
export default function ResearchStudio() {
  const [config, setConfig] = useState<Config | null>(null), [error, setError] = useState("");
  const [draft, setDraft] = useState<Definition>(initial), [population, setPopulation] = useState<Population | null>(null), [previewKey, setPreviewKey] = useState("");
  const [loading, setLoading] = useState(false), [submitting, setSubmitting] = useState(false), [run, setRun] = useState<Status | null>(null), [runKey, setRunKey] = useState("");
  const [result, setResult] = useState<Result | null>(null), [runs, setRuns] = useState<Status[]>([]);
  const [selected, setSelected] = useState<Occurrence | null>(null), [chart, setChart] = useState<Chart | null>(null), [chartLoading, setChartLoading] = useState(false);
  const [symbol, setSymbol] = useState("MU"), [day, setDay] = useState("2023-07-03"), [clock, setClock] = useState("10:00");
  const [horizon, setHorizon] = useState("30m"), [unit, setUnit] = useState("percent"), [axis, setAxis] = useState("move_15m_atr");
  const [informed, setInformed] = useState(false), [selectedSaved, setSelectedSaved] = useState(false);
  const current = key(draft), currentRef = useRef(current); useEffect(() => { currentRef.current = current; }, [current]);
  const chartSequence = useRef(0), runSequence = useRef(0);
  useEffect(() => { fetch(apiUrl("/research-studio/config"), {cache: "no-store"}).then(async r => { const c = await r.json(); if (!r.ok) throw new Error(c.detail); setConfig(c); }).catch(e => setError(String(e.message))); }, []);
  useEffect(() => {
    if (!config) return;
    const abort = new AbortController();
    const timer = setTimeout(() => { setLoading(true); setError(""); void prepared<Population>("preview", {raw: draft}, abort.signal).then(p => {
      if (!abort.signal.aborted && currentRef.current === current) { setPopulation(p); setPreviewKey(current); }
    }).catch(e => { if (!abort.signal.aborted) setError(e.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); }); }, 80);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [config, current, draft]);
  async function history() { try { setRuns((await command<{runs: Status[]}>("runs")).runs); } catch (e) { setError((e as Error).message); } }
  useEffect(() => { if (config) { command<{runs: Status[]}>("runs").then(r => setRuns(r.runs)).catch(e => setError(e.message)); } }, [config]);
  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    let active = true, pending = false;
    const id = setInterval(() => { if (pending) return; pending = true; command<Status>("status", {run_id: run.run_id}).then(s => { if (active) setRun(prior => prior?.run_id === s.run_id ? s : prior); }).catch(e => { if (active) setError(e.message); }).finally(() => { pending = false; }); }, 250);
    return () => { active = false; clearInterval(id); };
  }, [run]);
  async function start() {
    const frozen = current, seq = ++runSequence.current; setSubmitting(true); setError("");
    try { const s = await command<Status>("enqueue", {raw: draft, operation_id: crypto.randomUUID(), outcome_informed: informed});
      if (seq !== runSequence.current) return;
      setRun(s); setRunKey(frozen); setResult(null);
      if (s.status === "queued") await command("execute");
      await history();
    } catch (e) { setError((e as Error).message); } finally { if (seq === runSequence.current) setSubmitting(false); }
  }
  async function reopen(s: Status) {
    ++runSequence.current; setRun(s); if (s.definition) { currentRef.current = key(s.definition); setDraft(s.definition); setRunKey(key(s.definition)); }
    setResult(null); setChart(null); setSelected(null); ++chartSequence.current;
    if (s.status === "completed") await revealResult(s);
  }
  async function revealResult(s: Status) {
    const seq = runSequence.current;
    try { const r = await command<Result>("result", {run_id: s.run_id, operation_id: crypto.randomUUID()});
      if (seq === runSequence.current) { setResult(r); setInformed(true); } await history();
    } catch (e) { setError((e as Error).message); }
  }
  async function control(action: "cancel" | "retry") {
    if (!run) return; const seq = runSequence.current; try { const s = await command<Status>(action, {run_id: run.run_id, operation_id: crypto.randomUUID()}); if (seq === runSequence.current) setRun(s); if (action === "retry") await command("execute"); await history(); } catch (e) { setError((e as Error).message); }
  }
  async function inspect(e: Occurrence, reveal = false, saved = false) {
    const seq = ++chartSequence.current; setSelected(e); setSelectedSaved(saved); setChart(null); setChartLoading(true);
    try { const c = await prepared<Chart>("chart", {symbol: e.symbol, decision_time: e.decision_time, data_id: saved ? result?.population.data_id : population?.data_id, run_id: saved ? result?.run_id : null, reveal, operation_id: crypto.randomUUID()});
      if (seq === chartSequence.current) { setChart(c); setSelected({...e, occurrence_id: c.occurrence_id, decision_time: c.decision_time, features: c.features}); if (reveal) setInformed(true); }
    } catch (err) { if (seq === chartSequence.current) setError((err as Error).message); } finally { if (seq === chartSequence.current) setChartLoading(false); }
  }
  function edit(d: Definition) { currentRef.current = key(d); setLoading(true); setChartLoading(false); setDraft(d); ++chartSequence.current; setChart(null); setSelected(null); }
  async function browse() {
    if (!population || previewKey !== current) return;
    // UTC offset is resolved by the server from an explicit offset supplied by
    // the date's ET calendar (DST); avoid the browser's local timezone.
    const candidate = new Date(`${day}T${clock}:00Z`);
    const hour = Number(new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour: "2-digit", hourCycle: "h23"}).format(candidate));
    const offset = (candidate.getUTCHours() - hour + 24) % 24;
    candidate.setUTCHours(candidate.getUTCHours() + offset);
    const target = draft.universe.includes(symbol) ? symbol : draft.universe[0];
    await inspect({symbol: target, decision_time: candidate.toISOString(), occurrence_id: target + ":" + candidate.toISOString(), session: day, features: {}});
  }
  function useSelected() {
    if (!selected || !chart) return;
    const v = chart.features.move_15m_atr.value, volume = chart.features.rvol.value;
    if (v === null || volume === null) { setError("This bar has unavailable move or volume history. Choose a complete observation."); return; }
    edit({...draft, universe: [selected.symbol], predicates: [{feature: "move_15m_atr", minimum: null, maximum: v}, {feature: "rvol", minimum: volume, maximum: null}]});
  }
  const previous = !!run && current !== runKey;
  const shownPopulation = result?.population ?? population;
  const events = shownPopulation?.events ?? [];
  const summary = result?.horizons[horizon]?.[unit];
  const selectedOutcome = result?.events.find(e => e.symbol + ":" + e.decision_time === selected?.occurrence_id)?.outcomes[horizon];
  const values = result ? result.events.map(e => ({...e, id: e.symbol + ":" + e.decision_time, x: result.population.events.find(p => p.occurrence_id === e.symbol + ":" + e.decision_time)?.features[axis]?.value ?? null, y: e.outcomes[horizon][unit as "percent" | "prior_daily_atr14"]})).filter(e => e.y !== null) : [];
  const selectId = (id: string) => { const e = events.find(e => e.occurrence_id === id); if (e) void inspect(e, false, !!result); };
  return <div className="mx-auto max-w-[1500px] space-y-4">
    <header><h1 className="text-2xl font-semibold">Research Studio</h1><p className="text-sm text-muted-foreground">Discovery event lab · July 3, 2023–September 30, 2024 · Descriptive exploration, not independent validation or trading P&amp;L.</p></header>
    {error && <p role="alert" aria-label="Research error" className="rounded border border-amber-500 p-3">{error}</p>}
    {!config ? <p>Waiting for the local research connection. See the R3 runbook for setup.</p> : <>
    <section className="rounded border bg-card p-4 space-y-3" aria-label="Conditions">
      <div className="flex justify-between flex-wrap gap-2"><h2 className="font-medium">Experiment conditions</h2><span className="text-xs text-amber-300">{informed ? "Draft choices after viewing outcomes are outcome-informed" : "Outcome-free population preview"}</span></div>
      <div className="flex flex-wrap gap-3">
        <label>Targets<select aria-label="Targets" className={field} value={draft.universe.length === 1 ? draft.universe[0] : "all"} onChange={e => edit({...draft, universe: e.target.value === "all" ? config.universe : [e.target.value]})}><option value="all">Core universe</option>{config.universe.map(s => <option key={s}>{s}</option>)}</select></label>
        <label>Decision window start (ET minutes)<input aria-label="Window start" className={field + " w-24"} type="number" step="5" min="575" max="960" value={draft.window_start} onChange={e => edit({...draft, window_start: Number(e.target.value)})}/></label>
        <label>End<input aria-label="Window end" className={field + " w-24"} type="number" step="5" min="575" max="960" value={draft.window_end} onChange={e => edit({...draft, window_end: Number(e.target.value)})}/></label>
      </div>
      {draft.predicates.map((p, i) => <div key={i} className="flex flex-wrap items-center gap-2">
        <select aria-label={`Condition ${i+1}`} className={field} value={p.feature} onChange={e => edit({...draft, predicates: draft.predicates.map((v,j) => j === i ? {...v, feature: e.target.value} : v)})}>{Object.entries(config.features).map(([f,u]) => <option value={f} key={f}>{f} · {u}</option>)}</select>
        {(["minimum", "maximum"] as const).map(bound => <label key={bound}>{bound === "minimum" ? "≥" : "≤"}<input aria-label={`Condition ${i+1} ${bound}`} className={field + " w-24"} type="number" step="any" value={p[bound] ?? ""} onChange={e => edit({...draft, predicates: draft.predicates.map((v,j) => j === i ? {...v, [bound]: e.target.value === "" ? null : Number(e.target.value)} : v)})}/></label>)}
        {draft.predicates.length > 1 && <button className={button} onClick={() => edit({...draft, predicates: draft.predicates.filter((_,j) => j !== i)})}>Remove condition {i+1}</button>}
      </div>)}
      <div className="flex gap-2 flex-wrap"><button className={button} disabled={draft.predicates.length >= 3} onClick={() => edit({...draft, predicates: [...draft.predicates, {feature: "day_move", minimum: null, maximum: 0}]})}>Add AND condition</button><button className={button + " bg-sky-950"} disabled={loading || submitting || previewKey !== current || !!run && ["queued", "running"].includes(run.status)} onClick={start}>{submitting ? "Preparing immutable run…" : "Run analysis"}</button><span role="status">{loading ? "Preparing population…" : population && previewKey === current ? `Preview: ${population.event_count} events · ${population.eligible_moments} ordinary moments` : "Preview does not match this draft"}</span></div>
      {population && <div className="text-xs text-muted-foreground">{population.distinct_dates} dates · {population.distinct_calendar_weeks} calendar weeks · largest-day share {population.largest_day_fraction === null ? "unavailable" : (population.largest_day_fraction*100).toFixed(1)+"%"}. Eligible: {population.eligible_symbols.join(", ") || "none"}. Unavailable: {population.unavailable_symbols.join(", ") || "none"}.<details><summary>Coverage and exclusions {previewKey !== current ? "(previous preview)" : ""}</summary><pre className="overflow-auto max-h-48">{JSON.stringify({coverage: population.coverage, exclusions: population.exclusions}, null, 2)}</pre></details></div>}
    </section>
    {run && <section className="rounded border p-3 space-y-2" aria-label="Run status"><p>{previous ? "Previous result — draft changed" : "Frozen run"} · <code className="break-all">{run.run_id}</code> · attempt {run.attempt} · <strong>{run.status}</strong></p>{run.reason && <p>{run.reason}</p>}<div className="flex gap-2">{["queued", "running"].includes(run.status) && <button className={button} onClick={() => control("cancel")}>Cancel run</button>}{["failed", "cancelled"].includes(run.status) && <button className={button} onClick={() => control("retry")}>Retry frozen run</button>}{run.status === "queued" && <button className={button} onClick={() => command("execute").catch(e => setError(e.message))}>Start queued worker</button>}{run.status === "completed" && !result && <button className={button} onClick={() => revealResult(run)}>Reveal analysis (records exposure)</button>}</div></section>}
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
    <div className="space-y-4 min-w-0">
      <section className="rounded border p-4 space-y-3" aria-label="Chart explorer"><h2 className="font-medium">Discovery chart</h2><div className="flex flex-wrap gap-2"><select aria-label="Chart symbol" className={field} value={draft.universe.includes(symbol) ? symbol : draft.universe[0]} onChange={e => setSymbol(e.target.value)}>{draft.universe.map(s => <option key={s}>{s}</option>)}</select><input aria-label="Chart date" className={field} type="date" min={draft.start} max={draft.end} value={day} onChange={e => setDay(e.target.value)}/><input aria-label="Decision clock" type="time" step="300" className={field} value={clock} onChange={e => setClock(e.target.value)}/><button className={button} disabled={loading || previewKey !== current} onClick={browse}>Inspect decision</button></div>
      {chartLoading ? <p role="status">Loading exact occurrence chart…</p> : chart ? <ResearchChart chart={chart} select={stamp => { if (selected) void inspect({...selected, decision_time: stamp, occurrence_id: selected.symbol+":"+stamp}, false, selectedSaved); }}/> : <p className="text-sm text-muted-foreground">Start with a completed discovery bar or select an occurrence below. No live feed is connected.</p>}
      </section>
      {result && summary && <section className="rounded border p-4 space-y-3" aria-label="Analysis"><h2 className="font-medium">Analysis {previous ? "· Previous result" : ""}</h2><div className="flex gap-2"><select aria-label="Horizon" className={field} value={horizon} onChange={e => setHorizon(e.target.value)}>{["15m","30m","60m","session_close"].map(h => <option key={h}>{h}</option>)}</select><select aria-label="Return unit" className={field} value={unit} onChange={e => setUnit(e.target.value)}><option value="percent">Percent of next open</option><option value="prior_daily_atr14">Prior daily ATR(14)</option></select></div>
      <p data-testid="analysis-count">N {summary.event_n} · Ordinary {summary.ordinary_n} · Matched ordinary {summary.matched_ordinary_n}</p><p>Event mean {number(summary.event_mean)} · Baseline {number(summary.baseline_mean)} · Difference {number(summary.difference)}</p>
      <p className="text-xs">Baseline includes qualifiers, matched by ticker/decision clock and weighted to event composition. Reference: immediate next complete five-minute open. Missing endpoints stay unavailable.</p>
      <p className="text-xs">Joint calendar-week 95% intervals: {summary.uncertainty.intervals.difference ? `[${summary.uncertainty.intervals.difference.map(v => v.toFixed(3)).join(", ")}] difference` : `Unavailable: ${summary.uncertainty.unavailable_reason}`} · {summary.uncertainty.eligible_weeks} weeks · {summary.uncertainty.valid_draws} valid / {summary.uncertainty.invalid_draws} invalid draws. Weeks are approximate blocks; adaptive choices remain exploratory. 30m is primary.</p>
      <details><summary>Endpoint exclusions and immutable identities</summary><pre className="overflow-auto text-xs">{JSON.stringify({exclusions: summary.event_exclusions, data: result.population.data_id, code: result.analysis_code_id, specification: result.spec}, null, 2)}</pre></details>
      <h3>Outcome distribution · select a bin to highlight occurrences</h3><Distribution values={values as {id:string;y:number}[]} select={selectId}/>
      <label>Decision feature<select aria-label="Scatter feature" className={field} value={axis} onChange={e => setAxis(e.target.value)}>{Object.keys(config.features).map(f => <option key={f}>{f}</option>)}</select></label><Scatter values={values.filter(v => v.x !== null) as {id:string;x:number;y:number}[]} select={selectId}/>
      <p className="text-xs text-muted-foreground">Selections only highlight an occurrence; N and statistics remain the complete frozen population. Outcome-axis selections cannot create a predicate.</p>
      </section>}
      <section className="rounded border p-4" aria-label="Occurrences"><h2 className="font-medium">Occurrences · {events.length} {result ? "in frozen run" : "in preview"}</h2><div className="max-h-72 overflow-auto"><table className="w-full text-sm"><thead><tr><th>Ticker</th><th>Decision ET</th><th>Move / daily ATR14</th><th>RVOL</th></tr></thead><tbody>{events.map(e => <tr key={e.occurrence_id} className={selected?.occurrence_id === e.occurrence_id ? "bg-sky-950" : ""}><td><button className={button} data-occurrence-id={e.occurrence_id} onClick={() => selectId(e.occurrence_id)}>{e.symbol}</button></td><td>{et(e.decision_time)}</td><td>{number(e.features.move_15m_atr.value)}</td><td>{number(e.features.rvol.value)}</td></tr>)}</tbody></table>{!events.length && <p>No eligible occurrences. Check coverage and exclusions.</p>}</div></section>
    </div>
    <aside className="space-y-4 min-w-0"><section className="rounded border p-4 space-y-2" aria-label="Occurrence inspector"><h2 className="font-medium">Common inspector</h2>{selected ? <><p data-testid="selected-id" className="break-all text-xs">{selected.occurrence_id}</p><p>{et(selected.decision_time)}</p><h3>Known at decision</h3>{chart && <><dl className="text-xs space-y-1">{Object.entries(chart.features).map(([k,v]) => <div key={k}><dt>{k} · {v.unit}</dt><dd>{number(v.value)} {v.reasons.join(", ")}</dd></div>)}</dl><button className={button} onClick={useSelected}>Use decision features as conditions</button><h3>What happened next</h3><button className={button} disabled={chart.revealed} onClick={() => inspect(selected, true, selectedSaved)}>Reveal future chart (records exposure)</button>{result && (selectedOutcome ? <div className="text-sm space-y-1"><p>{horizon} completed close: {selectedOutcome.endpoint_price === null ? "Unavailable" : "$"+selectedOutcome.endpoint_price.toFixed(3)}{selectedOutcome.endpoint_time ? " · "+et(selectedOutcome.endpoint_time) : ""}</p><p>Return from next open: {number(selectedOutcome.percent)}{selectedOutcome.percent !== null ? "%" : " · "+selectedOutcome.percent_reason}</p><p>Prior daily ATR(14) return: {number(selectedOutcome.prior_daily_atr14)}{selectedOutcome.prior_daily_atr14 === null ? " · "+selectedOutcome.prior_daily_atr14_reason : ""}</p></div> : <p>Not an event in this frozen run.</p>)}</>}</> : <p className="text-sm">Select a candle, distribution, scatter point or occurrence.</p>}</section>
    <section className="rounded border p-4 space-y-2"><h2>Saved runs</h2><button className={button} onClick={history}>Refresh history</button>{runs.map(s => <button key={s.run_id} className={button + " block w-full text-left"} onClick={() => reopen(s)}>{s.definition?.universe.join(", ")} · {s.status} · attempt {s.attempt}<span className="block break-all text-xs">{s.run_id}</span><span className="text-xs">{s.exposures} aggregate exposures · Reopening a completed result records exposure</span></button>)}</section></aside>
    </div></>}
  </div>;
}
function Distribution({values, select}: {values: {id:string;y:number}[];select:(id:string)=>void}) {
  if (!values.length) return <p>No available endpoints for this distribution.</p>;
  const lo = Math.min(...values.map(v=>v.y)), hi=Math.max(...values.map(v=>v.y)), width=(hi-lo||1)/10;
  const bins=Array.from({length:10},(_,i)=>values.filter(v=>Math.min(9,Math.floor((v.y-lo)/width))===i));
  const max=Math.max(...bins.map(b=>b.length));
  return <div className="flex h-28 items-end gap-1" aria-label="Outcome distribution">{bins.map((b,i)=><button key={i} className="bg-sky-700 min-w-0 flex-1 text-xs hover:bg-sky-500" style={{height:`${Math.max(10,b.length/max*100)}%`}} title={`${(lo+i*width).toFixed(3)} to ${(lo+(i+1)*width).toFixed(3)}: ${b.length}`} disabled={!b.length} onClick={()=>select(b[0].id)} aria-label={`Distribution bin ${i+1}: ${b.length} occurrences; inspect first`}>{b.length}</button>)}</div>;
}
function Scatter({values, select}: {values: {id:string;x:number;y:number}[];select:(id:string)=>void}) {
  if (!values.length) return <p>No paired feature/outcome observations.</p>;
  const xs=values.map(v=>v.x),ys=values.map(v=>v.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
  return <svg viewBox="0 0 600 180" className="w-full" aria-label="Decision feature versus forward return"><line x1="20" y1="160" x2="580" y2="160" stroke="currentColor"/><line x1="20" y1="10" x2="20" y2="160" stroke="currentColor"/>{values.map(v=><circle key={v.id} cx={25+(v.x-xmin)/(xmax-xmin||1)*540} cy={155-(v.y-ymin)/(ymax-ymin||1)*140} r="4" fill="#38bdf8" role="button" tabIndex={0} aria-label={`Inspect ${v.id}`} onClick={()=>select(v.id)} onKeyDown={e=>{if(e.key==="Enter")select(v.id);}}><title>{v.id}: feature {v.x.toFixed(3)}, return {v.y.toFixed(3)}</title></circle>)}</svg>;
}
