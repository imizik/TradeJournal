"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import ResearchChart from "./ResearchChart";
import type { Chart, Comparison, Config, Definition, Occurrence, Population, Result, Status } from "./types";

import { Copy, FlaskConical, ArrowRight } from "lucide-react";
import QuestionEditor from "./QuestionEditor";
import ResearchAnalysis from "./ResearchAnalysis";
import ComparisonPanel from "./ComparisonPanel";
import Conclusions from "./Conclusions";
import { command, prepared } from "./transport";
import { button, card, et, field, n as number, titles } from "./presentation";
const initial: Definition = {version: 1, predicates: [{feature: "move_15m_atr", minimum: null, maximum: -.25}, {feature: "rvol", minimum: 1.5, maximum: null}], universe: ["MU"], start: "2023-07-03", end: "2024-09-30", window_start: 600, window_end: 690};
function key(d: Definition) { return JSON.stringify({ version: d.version, start: d.start, end: d.end, window_start: d.window_start, window_end: d.window_end, universe: [...d.universe].sort(), predicates: d.predicates.map(p => ({ feature: p.feature, minimum: p.minimum, maximum: p.maximum })).sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) }); }
export default function ResearchStudio() {
  const [config, setConfig] = useState<Config | null>(null), [error, setError] = useState("");
  const [draft, setDraft] = useState<Definition>(initial), [population, setPopulation] = useState<Population | null>(null), [previewKey, setPreviewKey] = useState("");
  const [loading, setLoading] = useState(false), [submitting, setSubmitting] = useState(false), [run, setRun] = useState<Status | null>(null), [runKey, setRunKey] = useState("");
  const [result, setResult] = useState<Result | null>(null), [runs, setRuns] = useState<Status[]>([]);
  const [selected, setSelected] = useState<Occurrence | null>(null), [chart, setChart] = useState<Chart | null>(null), [chartLoading, setChartLoading] = useState(false);
  const [symbol, setSymbol] = useState("MU"), [day, setDay] = useState("2023-07-03"), [clock, setClock] = useState("10:00");
  const [horizon, setHorizon] = useState("30m"), [unit, setUnit] = useState("percent"), [axis, setAxis] = useState("move_15m_atr");
  const [informed, setInformed] = useState(false), [selectedSaved, setSelectedSaved] = useState(false);
  const [editing, setEditing] = useState(false);
  const [parent, setParent] = useState<Status | null>(null), [comparison, setComparison] = useState<Comparison | null>(null), [comparing, setComparing] = useState(false);
  const [selectedContext, setSelectedContext] = useState<Result | null>(null);
  const markInformed = useCallback(() => setInformed(true), []);
  const current = (parent?.run_id || "") + "|" + key(draft), currentRef = useRef(current); useEffect(() => { currentRef.current = current; }, [current]);
  const chartSequence = useRef(0), runSequence = useRef(0), comparisonAbort = useRef<AbortController | null>(null);
  useEffect(() => () => comparisonAbort.current?.abort(), []);
  useEffect(() => { fetch(apiUrl("/research-studio/config"), {cache: "no-store"}).then(async r => { const c = await r.json(); if (!r.ok) throw new Error(c.detail); setConfig(c); }).catch(e => setError(String(e.message))); }, []);
  const parentId=parent?.run_id;
  useEffect(() => {
    if (!config) return;
    const abort = new AbortController();
    const timer = setTimeout(() => { setLoading(true); setError(""); void prepared<Population>("preview", {raw: draft, ...(parentId ? {parent_run_id: parentId} : {})}, abort.signal).then(p => {
      if (!abort.signal.aborted && currentRef.current === current) { setPopulation(p); setPreviewKey(current); }
    }).catch(e => { if (!abort.signal.aborted) setError(e.message); }).finally(() => { if (!abort.signal.aborted) setLoading(false); }); }, 40);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [config, current, draft, parentId]);
  async function history() { try { setRuns((await command<{runs: Status[]}>("runs")).runs); } catch (e) { setError((e as Error).message); } }
  useEffect(() => { if (config) { command<{runs: Status[]}>("runs").then(r => setRuns(r.runs)).catch(e => setError(e.message)); } }, [config]);
  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    let active = true, pending = false;
    const id = setInterval(() => { if (pending) return; pending = true; command<Status>("status", {run_id: run.run_id}).then(s => { if (active) setRun(prior => prior?.run_id === s.run_id ? s : prior); }).catch(e => { if (active) setError(e.message); }).finally(() => { pending = false; }); }, 250);
    return () => { active = false; clearInterval(id); };
  }, [run]);
  async function start() {
    const frozen = current, seq = ++runSequence.current; comparisonAbort.current?.abort(); ++chartSequence.current; setChart(null); setSelected(null); setChartLoading(false); setResult(null); setComparison(null); setSelectedContext(null); setComparing(false); setSubmitting(true); setError("");
    try { const s = await command<Status>(parent ? "variant" : "enqueue", {raw: draft, ...(parent ? {parent_run_id: parent.run_id} : {}), operation_id: crypto.randomUUID(), outcome_informed: informed});
      if (seq !== runSequence.current) return;
      ++chartSequence.current; setChart(null); setSelected(null); setChartLoading(false);
      setRun(s); setRunKey(frozen); setResult(null);
      if (s.status === "queued") await command("execute");
      await history();
    } catch (e) { setError((e as Error).message); } finally { if (seq === runSequence.current) setSubmitting(false); }
  }
  async function reopen(s: Status) {
    const seq = ++runSequence.current; comparisonAbort.current?.abort(); ++chartSequence.current;
    setSubmitting(false); setComparing(false); setComparison(null); setResult(null); setChart(null); setSelected(null); setSelectedContext(null); setChartLoading(false); setError("");
    try {
      const ancestor = s.parent_run_id ? await command<Status>("describe", {run_id:s.parent_run_id}) : null;
      if(seq!==runSequence.current)return;
      setParent(ancestor); setRun(s);
      if(s.definition) {
        const frozen=(ancestor?.run_id || "")+"|"+key(s.definition);
        currentRef.current=frozen; setDraft(s.definition); setRunKey(frozen);
      }
      if(s.status==="completed")await revealResult(s);
    } catch(e) { if(seq===runSequence.current)setError((e as Error).message); }
  }
  function duplicate() {
    if(!run || !result)return;
    ++runSequence.current; comparisonAbort.current?.abort(); ++chartSequence.current;
    const definition=result.population.definition;
    setParent({...run,definition}); setDraft(definition); setEditing(true);
    currentRef.current=run.run_id+"|"+key(definition);
    setRun(null); setResult(null); setComparison(null); setChart(null); setSelected(null); setSelectedContext(null); setChartLoading(false); setSubmitting(false); setComparing(false); setLoading(true);
  }
  function selectPeriod(value: string) {
    const period = config?.newer_mu?.periods.find(p=>p.start===value);
    const next: Definition = period ? {...initial, version:2, start:period.start, end:period.end} : initial;
    resetQuestion(); setPopulation(null); setPreviewKey(""); currentRef.current="|"+key(next); setDraft(next); setDay(next.start); setSymbol("MU"); setError("");
  }
  function resetQuestion() {
    ++runSequence.current; comparisonAbort.current?.abort(); ++chartSequence.current; setParent(null); setRun(null); setResult(null); setComparison(null); setChart(null); setSelected(null); setSelectedContext(null); setSubmitting(false); setComparing(false); setChartLoading(false); setLoading(true);
    currentRef.current="|"+key(draft);
  }
  async function compareParent() {
    if(!parent || !run)return;
    const seq=runSequence.current, abort=new AbortController(); comparisonAbort.current?.abort(); comparisonAbort.current=abort; setComparing(true); setError("");
    try {
      const pair=await prepared<Comparison>("compare",{parent_run_id:parent.run_id,variant_run_id:run.run_id,operation_id:crypto.randomUUID()},abort.signal);
      if(abort.signal.aborted || seq!==runSequence.current)return;
      const latest=await command<Status>("status",{run_id:pair.variant_run_id});
      if(seq===runSequence.current){setComparison(pair);setInformed(true);setRun(prior=>prior?.run_id===latest.run_id?{...prior,...latest}:prior);}
      await history();
    }catch(e){if(seq===runSequence.current)setError((e as Error).message);}
    finally{if(seq===runSequence.current)setComparing(false);}
  }
  async function revealResult(s: Status) {
    const seq = runSequence.current;
    try { const r = await command<Result>("result", {run_id: s.run_id, operation_id: crypto.randomUUID()});
      const latest=await command<Status>("status",{run_id:s.run_id});
      if (seq === runSequence.current) { setResult(r); setInformed(true); setEditing(false); setRun(prior=>prior?.run_id===latest.run_id?{...prior,...latest}:prior); } await history();
    } catch (e) { setError((e as Error).message); }
  }
  async function control(action: "cancel" | "retry") {
    if (!run) return; const seq = runSequence.current; try { const s = await command<Status>(action, {run_id: run.run_id, operation_id: crypto.randomUUID()}); if (seq === runSequence.current) setRun(s); if (action === "retry") await command("execute"); await history(); } catch (e) { setError((e as Error).message); }
  }
  async function recover() {
    if (!run) return; const seq=runSequence.current; setError("");
    try { await command("recover"); const s=await command<Status>("status",{run_id:run.run_id}); if(seq===runSequence.current) setRun(s); await history(); }
    catch(e) {setError((e as Error).message);}
  }
  async function inspect(e: Occurrence, reveal = false, saved = false, context?: Result) {
    const source = saved ? context ?? result : null;
    const seq = ++chartSequence.current, initiatingRun = runSequence.current; setSelectedContext(source); setSelected(e); setSelectedSaved(saved); setChart(null); setChartLoading(true);
    try { const c = await prepared<Chart>("chart", {symbol: e.symbol, decision_time: e.decision_time, data_id: saved ? source?.population.data_id : population?.data_id, run_id: saved ? source?.run_id : null, reveal, operation_id: crypto.randomUUID()});
      if (seq === chartSequence.current && initiatingRun === runSequence.current) { setChart(c); setSelected({...e, occurrence_id: c.occurrence_id, decision_time: c.decision_time, features: c.features}); if (reveal) setInformed(true); }
    } catch (err) { if (seq === chartSequence.current && initiatingRun === runSequence.current) setError((err as Error).message); } finally { if (seq === chartSequence.current && initiatingRun === runSequence.current) setChartLoading(false); }
  }
  function edit(d: Definition) { currentRef.current = (parent?.run_id || "")+"|"+key(d); setEditing(true); setLoading(true); setChartLoading(false); setDraft(d); ++chartSequence.current; setChart(null); setSelected(null); }
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
    edit({...draft, universe: parent ? draft.universe : [selected.symbol], predicates: [{feature: "move_15m_atr", minimum: null, maximum: v}, {feature: "rvol", minimum: volume, maximum: null}]});
  }
  const previous = !!run && current !== runKey;
  const shownPopulation = result?.population ?? (previewKey===current ? population : null);
  const events = shownPopulation?.events ?? [];
  const selectedOutcome = (selectedContext ?? result)?.events.find(e => e.symbol + ":" + e.decision_time === selected?.occurrence_id)?.outcomes[horizon];
  const selectId = (id: string) => { const e = events.find(e => e.occurrence_id === id); if (e && (result || previewKey===current)) void inspect(e, false, !!result); };
  const noteIds=comparison ? [comparison.parent_run_id,comparison.variant_run_id] : run ? [run.run_id] : [];
  const supportsR4=!!config?.capabilities?.includes("variants")&&!!config?.capabilities?.includes("conclusions");
  const unchangedVariant=!!parent?.definition && key(parent.definition)===key(draft);
  return <div className="mx-auto w-full min-w-0 max-w-[1500px] space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0"><p className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground"><FlaskConical size={14}/>{draft.version===2?"Newer MU comparison":"Discovery workspace"}</p><h1 className="text-2xl font-semibold tracking-tight">Research Studio</h1><p className="mt-1 text-sm leading-relaxed text-muted-foreground">Ask a question. Inspect the evidence. Keep the reasoning.</p></div>
      <div className="rounded-md border bg-card px-3 py-2 text-xs leading-relaxed text-muted-foreground"><p>{draft.start} – {draft.end}</p><p>Descriptive exploration · not independent validation or trading P&amp;L</p></div>
    </header>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"><span className="font-medium text-foreground">1 · Question</span><ArrowRight size={12}/><span className={result?"font-medium text-foreground":""}>2 · Evidence</span><ArrowRight size={12}/><span className={comparison?"font-medium text-foreground":""}>3 · Compare &amp; conclude</span></div>
    {error&&<p role="alert" aria-label="Research error" className="rounded-lg border border-amber-500/50 bg-amber-500/5 p-3 text-sm leading-relaxed text-amber-300">{error}</p>}
    {!config ? <div className={card}><p className="font-medium">Waiting for the research connection</p><p className="mt-1 text-sm text-muted-foreground">See the R3 runbook for local setup. Your private data connection stays server-side.</p></div> : <>
    {!supportsR4&&<p role="status" className="rounded-lg border border-amber-500/50 p-3 text-sm text-amber-300">Connected to an earlier research worker. Restart the manual sidecar on the updated release to enable variants and conclusions. Preview, runs and saved results remain available.</p>}
    {config.newer_mu&&<section className={card+" space-y-2"} aria-label="Research period">
      <label className="block text-sm font-medium">Study period<select aria-label="Study period" className={field+" mt-2 max-w-lg"} disabled={!!run&&["queued","running"].includes(run.status)||submitting||comparing} value={draft.version===2?draft.start:"discovery"} onChange={e=>selectPeriod(e.target.value)}><option value="discovery">Original discovery · July 2023–September 2024</option>{config.newer_mu.periods.map(p=><option key={p.start} value={p.start}>{p.label}</option>)}</select></label>
      <p className="text-xs leading-relaxed text-muted-foreground">Compare the same MU decline and volume rules across separate periods. Newer dates are exposed exploratory data and cannot later count as an unseen test. Changing periods starts a separate question.</p>
    </section>}
    <QuestionEditor config={config} draft={draft} edit={edit} population={population} loading={loading} ready={previewKey===current} submitting={submitting} active={!!run&&["queued","running"].includes(run.status)} informed={informed} variant={!!parent} unchanged={unchangedVariant} expanded={editing} onToggle={()=>setEditing(!editing)} onRun={start} onReset={resetQuestion}/>
    {run&&<section className={card+" space-y-3"} aria-label="Run status">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className={"text-sm font-medium "+(previous?"text-amber-300":"")}>{previous?"Previous result — draft changed":parent?"Frozen variant":"Frozen run"} · attempt {run.attempt}</p><p className="mt-1 text-xs text-muted-foreground">{run.status==="completed"?"Calculation saved. Reveal outcomes explicitly when ready.":run.status==="running"?"Calculating in the isolated research worker.":"This run keeps its original data and attempt history."}</p></div><strong className="rounded-md border bg-secondary px-2 py-1 text-xs capitalize">{run.status}</strong></div>
      {run.reason&&<p className="text-sm text-amber-300">{run.reason}</p>}
      <div className="flex flex-wrap gap-2">{["queued","running"].includes(run.status)&&<><button className={button} onClick={()=>control("cancel")}>Cancel run</button><button className={button} onClick={()=>run.status==="running"?recover():command("execute").catch(e=>setError(e.message))}>{run.status==="running"?"Check worker / recover interrupted run":"Start queued worker"}</button></>}
        {["failed","cancelled"].includes(run.status)&&<button className={button} onClick={()=>control("retry")}>Retry frozen run</button>}
        {run.status==="completed"&&!result&&<button className={button+" bg-primary text-primary-foreground hover:bg-primary/90"} disabled={submitting} onClick={()=>revealResult(run)}>Reveal analysis (records exposure)</button>}
        {result&&supportsR4&&<button className={button} disabled={submitting||comparing} onClick={duplicate}><Copy size={14}/>Duplicate as variant</button>}
        {result&&parent&&<button className={button} disabled={comparing||submitting||previous} onClick={compareParent}>{comparing?"Comparing frozen populations…":"Compare with parent (records exposures)"}</button>}
      </div>
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Run identity and exposure history</summary><p className="mt-2 break-all"><code>{run.run_id}</code></p><p className="mt-1">{run.exposures} aggregate exposures · Cached reopen records another exposure.</p>{parent&&<p className="mt-1 break-all">Parent: {parent.run_id}</p>}</details>
    </section>}
    {result&&<ResearchAnalysis result={result} previous={previous} horizon={horizon} unit={unit} axis={axis} setHorizon={setHorizon} setUnit={setUnit} setAxis={setAxis} config={config} select={selectId}/>}
    {comparison&&<ComparisonPanel comparison={comparison} horizon={horizon} unit={unit} previous={previous} inspect={(e,r)=>{void inspect(e,false,true,r);}}/>}
    {comparison&&<Conclusions wide key={noteIds.join(":")} runIds={noteIds} horizon={horizon} unit={unit} onSeen={markInformed}/>}
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-5">
        <section className={card+" space-y-3"} aria-label="Chart explorer"><div><h2 className="font-semibold">Inspect an occurrence</h2><p className="mt-1 text-xs text-muted-foreground">Known at decision first. Future candles stay behind an explicit reveal.</p></div>
          <div className="grid min-w-0 grid-cols-2 items-end gap-2 sm:grid-cols-[90px_minmax(0,1fr)_minmax(0,1fr)_auto]"><label className="min-w-0 text-xs text-muted-foreground">Ticker<select aria-label="Chart symbol" className={field+" mt-1 text-foreground"} value={draft.universe.includes(symbol)?symbol:draft.universe[0]} onChange={e=>setSymbol(e.target.value)}>{draft.universe.map(s=><option key={s}>{s}</option>)}</select></label><label className="min-w-0 text-xs text-muted-foreground">Session date<input aria-label="Chart date" className={field+" mt-1 text-foreground"} type="date" min={draft.start} max={draft.end} value={day} onChange={e=>setDay(e.target.value)}/></label><label className="min-w-0 text-xs text-muted-foreground">Decision · ET<input aria-label="Decision clock" className={field+" mt-1 text-foreground"} type="time" step="300" value={clock} onChange={e=>setClock(e.target.value)}/></label><button className={button} disabled={loading||previewKey!==current} onClick={browse}>Inspect decision</button></div>
          {chartLoading?<p role="status" className="text-sm text-muted-foreground">Loading exact occurrence chart…</p>:chart?<ResearchChart chart={chart} select={stamp=>{if(selected)void inspect({...selected,decision_time:stamp,occurrence_id:selected.symbol+":"+stamp},false,selectedSaved,selectedContext??undefined);}}/>:<p className="rounded-md border border-dashed p-5 text-sm leading-relaxed text-muted-foreground">Start with a completed research bar or select an occurrence below. No live feed is connected.</p>}
        </section>
        <section className={card+" space-y-3"} aria-label="Occurrences"><div><h2 className="font-semibold">Occurrences · {events.length} {result?"in frozen run":"in preview"}</h2><p className="mt-1 text-xs text-muted-foreground">First qualifying completed bar per ticker / session. Select a ticker to inspect.</p></div><div className="max-h-80 overflow-auto"><table className="w-full table-fixed text-left text-xs sm:text-sm"><thead className="text-muted-foreground"><tr><th className="w-[15%] pb-2 font-medium">Ticker</th><th className="w-[40%] pb-2 font-medium">Decision · ET</th><th className="w-[25%] pb-2 font-medium">15m move / daily ATR14</th><th className="w-[20%] pb-2 font-medium">RVOL</th></tr></thead><tbody>{events.map(e=><tr key={e.occurrence_id} className={"border-t "+(selected?.occurrence_id===e.occurrence_id?"bg-primary/10":"")}><td className="py-2 pr-1"><button className="rounded px-1 py-1 font-semibold text-primary hover:bg-secondary" data-occurrence-id={e.occurrence_id} onClick={()=>selectId(e.occurrence_id)}>{e.symbol}</button></td><td className="py-2 pr-2">{et(e.decision_time)}</td><td className="py-2 pr-1 tabular-nums">{number(e.features.move_15m_atr.value)}</td><td className="py-2 tabular-nums">{number(e.features.rvol.value)}</td></tr>)}</tbody></table>{!events.length&&<p className="py-5 text-sm text-muted-foreground">No eligible occurrences. Check coverage and exclusions.</p>}</div></section>
      </div>
      <aside className="min-w-0 space-y-5">
        <section className={card+" space-y-3"} aria-label="Occurrence inspector"><h2 className="font-semibold">Common inspector</h2>{selected?<><div><p className="font-medium">{selected.symbol}</p><p className="text-xs text-muted-foreground">{et(selected.decision_time)}</p></div><h3 className="border-t pt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Known at decision</h3>{chart&&<>
          <dl className="space-y-2 text-sm">{["move_15m_atr","rvol","gap"].map(k=>{const v=chart.features[k];return v&&<div key={k} className="rounded-md bg-secondary/40 p-2"><dt className="text-xs text-muted-foreground">{titles[k]}</dt><dd className="mt-1 font-medium tabular-nums">{number(v.value)}</dd><dd className="mt-1 text-xs text-muted-foreground">{v.unit}{v.reasons.length>0?" · "+v.reasons.join(", "):""}</dd></div>;})}</dl>
          <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">All decision features and identity</summary><p data-testid="selected-id" className="mt-2 break-all">{selected.occurrence_id}</p><dl className="mt-2 space-y-2">{Object.entries(chart.features).map(([k,v])=><div key={k}><dt>{titles[k]||k} · {v.unit}</dt><dd>{number(v.value)} {v.reasons.join(", ")}</dd></div>)}</dl></details>
          <button className={button+" w-full"} disabled={draft.version===2} title={draft.version===2?"Newer MU rules are fixed for this comparison":undefined} onClick={useSelected}>Use decision features as conditions</button>
          <h3 className="border-t pt-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">What happened next</h3><button className={button+" w-full"} disabled={chart.revealed} onClick={()=>inspect(selected,true,selectedSaved,selectedContext??undefined)}>Reveal future chart (records exposure)</button>
          {result&&(selectedOutcome?<div className="space-y-2 text-xs leading-relaxed"><p>{horizon} completed close: {selectedOutcome.endpoint_price===null?"Unavailable":"$"+selectedOutcome.endpoint_price.toFixed(3)}{selectedOutcome.endpoint_time?" · "+et(selectedOutcome.endpoint_time):""}</p><p>Return from next open: {number(selectedOutcome.percent)}{selectedOutcome.percent!==null?"%":" · "+selectedOutcome.percent_reason}</p><p>Prior daily ATR(14) return: {number(selectedOutcome.prior_daily_atr14)}{selectedOutcome.prior_daily_atr14===null?" · "+selectedOutcome.prior_daily_atr14_reason:""}</p></div>:<p className="text-xs text-muted-foreground">Not an event in this frozen run.</p>)}
        </>}</>:<p className="text-sm leading-relaxed text-muted-foreground">Select a candle, distribution, scatter point or occurrence. Its exact frozen bars and features appear here.</p>}</section>
        {result&&supportsR4&&!comparison&&noteIds.length>0&&<Conclusions key={noteIds.join(":")} runIds={noteIds} horizon={horizon} unit={unit} onSeen={markInformed}/>}
        <section className={card+" space-y-3"} aria-label="Saved runs"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Saved runs</h2><button className={button+" text-xs"} onClick={history}>Refresh history</button></div><p className="text-xs leading-relaxed text-muted-foreground">Reopening a completed result records exposure. Attempts and abandoned variants stay in history.</p>{runs.map(s=><button key={s.run_id} className={button+" block w-full text-left"} onClick={()=>reopen(s)}><span className="flex flex-wrap justify-between gap-1"><strong>{s.definition?.universe.length===1?s.definition.universe[0]:"Core universe"}</strong><span className="text-xs capitalize text-muted-foreground">{s.status}</span></span><span className="mt-1 block text-xs text-muted-foreground">{s.parent_run_id?"Variant":"Question"} · {s.definition?.predicates.length} conditions · attempt {s.attempt}</span><span className="mt-1 block text-xs text-muted-foreground">{s.exposures} aggregate exposures · {s.run_id.slice(0,8)} · {s.definition?.start} – {s.definition?.end}</span></button>)}{!runs.length&&<p className="text-sm text-muted-foreground">Your saved questions will appear here.</p>}</section>
      </aside>
    </div></>}
  </div>;
}
