import type { Config, Result } from "./types";
import { Distribution, Scatter } from "./ResearchPlots";
import { card, field, horizonLabel, returnValue, titles } from "./presentation";

export default function ResearchAnalysis({result,previous,horizon,unit,axis,setHorizon,setUnit,setAxis,config,select}:
  {result:Result;previous:boolean;horizon:string;unit:string;axis:string;setHorizon:(s:string)=>void;setUnit:(s:string)=>void;setAxis:(s:string)=>void;config:Config;select:(id:string)=>void}) {
  const summary=result.horizons[horizon]?.[unit];
  if(!summary)return null;
  const values=result.events.map(e=>({...e,id:e.symbol+":"+e.decision_time,
    x:result.population.events.find(p=>p.occurrence_id===e.symbol+":"+e.decision_time)?.features[axis]?.value??null,
    y:e.outcomes[horizon][unit as "percent"|"prior_daily_atr14"]})).filter(e=>e.y!==null);
  const interval=summary.uncertainty.intervals.difference;
  return <section className={card+" space-y-4"} aria-label="Analysis">
    <div className="flex flex-wrap justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">02 · Read the evidence</p><h2 className="mt-1 text-lg font-semibold">What happened next{previous ? " · Previous result" : ""}</h2></div>
      <div className="flex flex-wrap gap-2"><label className="text-xs text-muted-foreground">Forward window<select aria-label="Horizon" className={field+" mt-1 text-foreground"} value={horizon} onChange={e=>setHorizon(e.target.value)}>{["15m","30m","60m","session_close"].map(h=><option value={h} key={h}>{horizonLabel(h)}</option>)}</select></label><label className="text-xs text-muted-foreground">Return units<select aria-label="Return unit" className={field+" mt-1 text-foreground"} value={unit} onChange={e=>setUnit(e.target.value)}><option value="percent">Percent of next open</option><option value="prior_daily_atr14">Prior daily ATR(14)</option></select></label></div>
    </div>
    <div className="grid gap-3 sm:grid-cols-3">{[
      ["Mean forward return",summary.event_mean,false],["Ordinary baseline",summary.baseline_mean,false],["Difference",summary.difference,true]
    ].map(([label,value,difference])=><div key={String(label)} className="min-w-0 rounded-md border bg-background/50 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums">{returnValue(value as number|null,unit,Boolean(difference))}</p></div>)}</div>
    <p data-testid="analysis-count" className="text-sm"><strong>N {summary.event_n}</strong> with this endpoint · Ordinary {summary.ordinary_n} · Matched ordinary {summary.matched_ordinary_n}</p>
    <div className="space-y-2 rounded-md bg-secondary/50 p-3 text-xs leading-relaxed">
      <p>The baseline is the mean at similar times for the same tickers, weighted to this event mix. It includes moments that meet your conditions. Reference: immediate next complete five-minute open; missing endpoints stay unavailable.</p>
      <p className={interval ? "" : "text-amber-300"}><strong>95% uncertainty for the difference:</strong> {interval ? interval.map(v=>returnValue(v,unit,true)).join(" to ") : "Unavailable · "+(summary.uncertainty.unavailable_reason==="insufficient_weeks" ? "not enough eligible calendar weeks" : "not enough valid joint draws")}. {summary.uncertainty.eligible_weeks} weeks · {summary.uncertainty.valid_draws} valid / {summary.uncertainty.invalid_draws} invalid draws.</p>
      <p>Descriptive discovery research. Weeks are approximate blocks; adaptive choices remain exploratory. 30 minutes is primary. This is not a trading P&amp;L or independent validation.</p>
    </div>
    <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Endpoint exclusions and immutable identities</summary><pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify({exclusions:summary.event_exclusions,data:result.population.data_id,code:result.analysis_code_id,specification:result.spec},null,2)}</pre></details>
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="min-w-0"><h3 className="mb-3 text-sm font-medium">Outcome distribution</h3><Distribution values={values as {id:string;y:number}[]} select={select}/><p className="mt-2 text-xs text-muted-foreground">Select a bin to inspect its first occurrence. Values use {unit==="percent"?"percent returns":"prior daily ATR(14)"} at {horizonLabel(horizon).toLowerCase()}.</p></div>
      <div className="min-w-0"><label className="block text-sm font-medium">Known at decision<select aria-label="Scatter feature" className={field+" mt-2"} value={axis} onChange={e=>setAxis(e.target.value)}>{Object.keys(config.features).map(f=><option key={f} value={f}>{titles[f]||f}</option>)}</select></label><Scatter values={values.filter(v=>v.x!==null) as {id:string;x:number;y:number}[]} select={select}/><p className="text-xs text-muted-foreground">Horizontal: {titles[axis]||axis}. Vertical: forward return. Selections highlight an occurrence; N and statistics stay the complete frozen population. Outcome-axis selections cannot create a predicate.</p></div>
    </div>
  </section>;
}
