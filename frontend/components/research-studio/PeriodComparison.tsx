import { useEffect, useRef, useState } from "react";
import type { Occurrence, Result, Status } from "./types";
import { button, card, field, horizonLabel, returnValue } from "./presentation";
import { disjointPeriods, eventEvidence, sameCalculation, sameQuestion } from "./evidence";
import { command } from "./transport";
import EventEvidence from "./EventEvidence";

export default function PeriodComparison({result,runs,horizon,unit,inspect,onSeen}:
  {result:Result;runs:Status[];horizon:string;unit:string;inspect:(e:Occurrence,r:Result)=>void;onSeen:()=>void}) {
  const [selected,setSelected]=useState(""),[other,setOther]=useState<Result|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const generation=useRef(0),mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  const candidates=runs.filter(s=>s.status==="completed"&&s.definition&&sameQuestion(result.population.definition,s.definition)&&disjointPeriods(result.population.definition,s.definition));
  async function load() {
    const seq=++generation.current;setOther(null);setLoading(true);setError("");
    try {
      const r=await command<Result>("result",{run_id:selected,operation_id:crypto.randomUUID()});
      if(!mounted.current||seq!==generation.current)return;
      onSeen();
      if(r.run_id!==selected||!sameQuestion(result.population.definition,r.population.definition)||!disjointPeriods(result.population.definition,r.population.definition)||!sameCalculation(result,r))throw new Error("These runs do not share the same rules and calculation version in separate periods. Rerun both periods on the same release.");
      setOther(r);
    } catch(e) {if(mounted.current&&seq===generation.current)setError((e as Error).message);}
    finally {if(mounted.current&&seq===generation.current)setLoading(false);}
  }
  const results=other?[result,other]:[result];
  return <section className={card+" scroll-mt-20 space-y-4"} aria-label="Period comparison">
    <div><h2 className="font-semibold">Same question, separate periods</h2><p className="mt-1 text-xs text-muted-foreground">Compare completed saved runs with identical predicates, universe and decision window. Each period retains its own baseline and uncertainty. No paired cross-period significance test.</p></div>
    <div className="flex flex-wrap items-end gap-2"><label className="w-full min-w-0 text-xs text-muted-foreground sm:w-auto sm:flex-1">Saved period<select aria-label="Comparison period" className={field+" mt-1"} value={selected} onChange={e=>{++generation.current;setSelected(e.target.value);setOther(null);setLoading(false);setError("");}}><option value="">Choose a completed run</option>{candidates.map(s=><option key={s.run_id} value={s.run_id}>{s.definition!.start} – {s.definition!.end} · {s.run_id.slice(0,8)}</option>)}</select></label><button className={button+" w-full sm:w-auto"} disabled={!selected||loading} onClick={load}>{loading?"Loading frozen period…":"Load period (records exposure)"}</button></div>
    {!candidates.length&&<p className="text-sm text-muted-foreground">Run and save the same rules in another study period to compare it here.</p>}
    {error&&<p role="alert" className="text-sm text-amber-300">{error}</p>}
    <div className="grid gap-3 lg:grid-cols-2">{results.map(r=>{const stats=eventEvidence(r,horizon,unit),summary=r.horizons[horizon]?.[unit],atr=r.horizons[horizon]?.prior_daily_atr14,ci=summary?.uncertainty.intervals.difference;
      return <article key={r.run_id} className="min-w-0 rounded-md border p-3" aria-label={`Period ${r.population.definition.start}`}><h3 className="text-sm font-semibold">{r.population.definition.start} – {r.population.definition.end}</h3><p className="mt-1 text-xs text-muted-foreground">{horizonLabel(horizon)} · {unit==="percent"?"Percent of next open":"Prior daily ATR(14)"}</p>
        <dl className="mt-3 space-y-2 text-sm">{[["Valid events",stats.n],["Mean",returnValue(summary?.event_mean,unit)],["Median",returnValue(stats.median,unit)],["Positive outcomes",stats.n?`${stats.positive}/${stats.n} (${(stats.positive/stats.n*100).toFixed(1)}%)`:"Unavailable"],["Outcome standard deviation",returnValue(stats.spread,unit)],["Ordinary baseline",returnValue(summary?.baseline_mean,unit)],["Difference",returnValue(summary?.difference,unit,true)],["Volatility-normalized mean",returnValue(atr?.event_mean,"prior_daily_atr14")]].map(([label,value])=><div key={label} className="flex flex-wrap justify-between gap-x-3"><dt className="text-muted-foreground">{label}</dt><dd className="tabular-nums">{value}</dd></div>)}</dl>
        <p className="mt-3 text-xs text-muted-foreground">95% interval for this period&apos;s difference: {ci?ci.map(v=>returnValue(v,unit,true)).join(" to "):"Unavailable · "+summary?.uncertainty.unavailable_reason}.</p><p className="mt-2 break-all text-xs text-muted-foreground">Frozen run {r.run_id.slice(0,8)} · {r.interpretation}</p>
      </article>;})}</div>
    {other&&<EventEvidence result={other} horizon={horizon} unit={unit} select={id=>{const e=other.population.events.find(e=>e.occurrence_id===id);if(e)inspect(e,other);}}/>}
  </section>;
}
