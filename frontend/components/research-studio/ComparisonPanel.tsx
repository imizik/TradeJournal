import { useState } from "react";
import type { Comparison, Occurrence, Result } from "./types";
import { button, card, et, horizonLabel, returnValue } from "./presentation";

export default function ComparisonPanel({comparison,horizon,unit,previous,inspect}:
  {comparison:Comparison;horizon:string;unit:string;previous:boolean;inspect:(e:Occurrence,r:Result)=>void}) {
  const [which,setWhich]=useState<"retained"|"removed"|"added">("retained");
  const summary=comparison.horizons[horizon][unit], change=summary.change;
  const labels={retained:"Stayed",removed:"Removed",added:"Added"};
  const parent=comparison.parent_result,variant=comparison.variant_result;
  const interval=change.uncertainty.intervals.difference;
  return <section aria-label="Variant comparison" className={card+" space-y-4"}>
    <div><p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">03 · Compare the variation</p><h2 className="mt-1 text-lg font-semibold">Did the changed conditions separate the outcomes?{previous ? " · Previous comparison" : ""}</h2></div>
    <p className="text-xs text-muted-foreground">Same frozen dataset · {horizonLabel(horizon)} · Variant minus parent · Descriptive, outcome-informed exploration.</p>
    <div className="grid gap-3 sm:grid-cols-2">{(["parent","variant"] as const).map(key=><div key={key} className="rounded-md border bg-background/50 p-3"><h3 className="text-sm font-semibold capitalize">{key} · N {summary[key].event_n}</h3><dl className="mt-2 space-y-1 text-sm"><div className="flex flex-wrap justify-between gap-1"><dt className="text-muted-foreground">Mean forward return</dt><dd>{returnValue(summary[key].event_mean,unit)}</dd></div><div className="flex flex-wrap justify-between gap-1"><dt className="text-muted-foreground">Ordinary baseline</dt><dd>{returnValue(summary[key].baseline_mean,unit)}</dd></div><div className="flex flex-wrap justify-between gap-1"><dt className="text-muted-foreground">Difference</dt><dd>{returnValue(summary[key].difference,unit,true)}</dd></div></dl><p className="mt-2 text-xs text-muted-foreground">Matched ordinary {summary[key].matched_ordinary_n} · Total ordinary {summary[key].ordinary_n}</p></div>)}</div>
    <div className="rounded-md bg-secondary/50 p-3 text-sm leading-relaxed"><p>Change in mean return: <strong>{returnValue(change.event_mean,unit,true)}</strong> · Change in baseline-adjusted difference: <strong>{returnValue(change.difference,unit,true)}</strong></p><p className={"mt-2 text-xs "+(interval?"text-muted-foreground":"text-amber-300")}>Joint 95% interval for that difference change: {interval ? interval.map(v=>returnValue(v,unit,true)).join(" to ") : "Unavailable · "+(change.uncertainty.unavailable_reason==="insufficient_weeks"?"not enough eligible calendar weeks":"not enough valid paired draws")}. {change.uncertainty.eligible_weeks} eligible calendar weeks · {change.uncertainty.valid_draws} valid / {change.uncertainty.invalid_draws} invalid paired draws. The same week draws are applied to both full populations; this does not undo prior outcome exposure.</p></div>
    <div className="grid grid-cols-3 gap-2" role="group" aria-label="Compared event sets">{(["retained","removed","added"] as const).map(set=><button key={set} aria-pressed={set===which} className={button+" min-w-0 flex-col "+(set===which?"border-primary bg-primary/10":"")} onClick={()=>setWhich(set)}><span className="text-xs">{labels[set]}</span><strong className="text-lg tabular-nums">{comparison.sets[set].length}</strong></button>)}</div>
    <p className="text-xs leading-relaxed text-muted-foreground">Counts describe selected decision moments, not endpoint N. A stricter rule can choose a later moment in the same session: that is added, not retained. Retained occurrences have identical outcomes under these analysis definitions.</p>
    <div className="max-h-48 overflow-auto rounded-md border p-2" data-testid="comparison-events">{comparison.sets[which].length ? comparison.sets[which].map(id=>{
      const context=which==="removed"?parent:variant, event=context.population.events.find(e=>e.occurrence_id===id);
      return event&&<button key={id} className={button+" mb-1 w-full flex-wrap justify-between text-left"} data-compare-occurrence={id} onClick={()=>inspect(event,context)}><span>{event.symbol}</span><span className="text-xs text-muted-foreground">{et(event.decision_time)}</span></button>;
    }):<p className="p-2 text-sm text-muted-foreground">No {which} occurrences in this comparison.</p>}</div>
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Comparison identity and method</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify({comparison:comparison.comparison_id,data:comparison.data_id,code:comparison.comparison_code_id,method:comparison.method},null,2)}</pre></details>
  </section>;
}
