import type { Result } from "./types";
import { card, et, horizonLabel, returnValue } from "./presentation";
import { eventEvidence, horizons } from "./evidence";

export default function EventEvidence({result,horizon,unit,select,previous=false}:
  {result:Result;horizon:string;unit:string;select:(id:string)=>void;previous?:boolean}) {
  const stats=eventEvidence(result,horizon,unit);
  return <section className={card+" scroll-mt-20 space-y-4"} aria-label="Event evidence">
    <div><h2 className="font-semibold">Every event, every endpoint{previous?" · Previous result":""}</h2>
      <p className="mt-1 text-xs text-muted-foreground">Frozen {result.population.definition.start} – {result.population.definition.end}. Returns from the next complete five-minute open; select an event to inspect its exact chart.</p></div>
    <div className="grid gap-3 sm:grid-cols-3">
      <div><p className="text-xs text-muted-foreground">Median · {horizonLabel(horizon)}</p><p className="font-semibold tabular-nums">{returnValue(stats.median,unit)}</p></div>
      <div><p className="text-xs text-muted-foreground">Positive outcomes · valid endpoints</p><p className="font-semibold tabular-nums">{stats.n ? `${stats.positive}/${stats.n} (${(stats.positive/stats.n*100).toFixed(1)}%)` : "Unavailable"}</p></div>
      <div><p className="text-xs text-muted-foreground">Outcome standard deviation</p><p className="font-semibold tabular-nums">{returnValue(stats.spread,unit)}</p></div>
    </div>
    <div className="rounded-md border p-3 text-xs leading-relaxed" aria-label="Concentration check">
      <p className="font-medium">Does one event drive the average?</p>
      <p className="mt-1">Full mean: {returnValue(stats.mean,unit)} · Without the largest return: {returnValue(stats.withoutLargest,unit)} · Without the smallest return: {returnValue(stats.withoutSmallest,unit)}.</p>
      <p className="mt-1 text-muted-foreground">Sensitivity check only; each omission removes one event. The frozen population, baseline and uncertainty remain unchanged. Unavailable with fewer than two valid endpoints.</p>
    </div>
    <p className="text-xs text-muted-foreground sm:hidden">Scroll the table sideways to see all four endpoints.</p>
    <div className="max-h-96 overflow-auto rounded-md border"><table className="w-full min-w-[650px] text-left text-xs tabular-nums" aria-label="Event forward returns">
      <caption className="p-2 text-left text-muted-foreground">{unit==="percent"?"Percent of next open":"Prior daily ATR(14) units"} · positive = price rose; negative = price fell · price returns, not trading profits</caption>
      <thead className="bg-secondary"><tr><th className="p-2">Event · ET</th>{horizons.map(h=><th key={h} className="p-2">{horizonLabel(h)}</th>)}</tr></thead>
      <tbody>{result.events.map(e=><tr key={e.symbol+e.decision_time} className="border-t"><th className="p-2 font-normal"><button className="rounded px-1 py-2 text-left font-medium text-primary hover:bg-secondary" data-event-return-id={e.symbol+":"+e.decision_time} onClick={()=>select(e.symbol+":"+e.decision_time)}>{e.symbol} · {et(e.decision_time)}</button></th>
        {horizons.map(h=>{const endpoint=e.outcomes[h], value=endpoint?.[unit as "percent"|"prior_daily_atr14"], reason=endpoint?.[unit==="percent"?"percent_reason":"prior_daily_atr14_reason"];
          return <td key={h} className="p-2">{returnValue(value,unit)}{value==null&&<span className="block text-muted-foreground">{reason || "missing endpoint"}</span>}</td>;})}</tr>)}</tbody>
    </table>{!result.events.length&&<p className="p-3 text-sm text-muted-foreground">No qualifying events in this frozen run.</p>}</div>
  </section>;
}
