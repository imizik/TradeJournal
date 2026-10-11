import { useEffect, useMemo, useRef, useState } from "react";
import type { Conclusion } from "./types";
import { card, et, field, horizonLabel, primary } from "./presentation";
import { command } from "./transport";

export default function Conclusions({runIds,horizon,unit,onSeen,wide=false}:
  {runIds:string[];horizon:string;unit:string;onSeen:()=>void;wide?:boolean}) {
  const scope=JSON.stringify(runIds),scopeRef=useRef(scope);
  useEffect(()=>{scopeRef.current=scope;},[scope]);
  const ids=useMemo(()=>JSON.parse(scope) as string[],[scope]);
  const [notes,setNotes]=useState<Conclusion[]>([]),[verdict,setVerdict]=useState("Unclear"),[reason,setReason]=useState("");
  const [saving,setSaving]=useState(false),[error,setError]=useState(""),[loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    command<{notes:Conclusion[]}>("notes",{run_ids:ids}).then(r=>{if(active){setNotes(r.notes);if(r.notes.length)onSeen();}})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[ids,onSeen]);
  async function save() {
    const frozen=scope;setSaving(true);setError("");
    try {
      const note=await command<Conclusion>("conclude",{run_ids:ids,verdict,reason,horizon,unit,operation_id:crypto.randomUUID()});
      if(scopeRef.current===frozen){setNotes(prior=>[...prior,note]);setReason("");}
    }catch(e){if(scopeRef.current===frozen)setError((e as Error).message);}
    finally{if(scopeRef.current===frozen)setSaving(false);}
  }
  return <section className={card+" space-y-3"} aria-label="Conclusions">
    <div><p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Keep the reasoning</p><h2 className="mt-1 text-lg font-semibold">What do you conclude?</h2></div>
    <p className="text-xs leading-relaxed text-muted-foreground">For {ids.length===2?"this parent / variant comparison":"this frozen run"} · {horizonLabel(horizon)} · {unit==="percent"?"percent returns":"prior daily ATR(14)"}. A verdict is an exploratory note, not a validated trading edge. New notes append; earlier notes stay intact.</p>
    {error&&<p role="alert" aria-label="Conclusion error" className="rounded-md border border-amber-500/50 p-2 text-sm text-amber-300">{error}</p>}
    <div className={wide?"grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)]":"space-y-3"}><label className="block text-xs text-muted-foreground">Verdict<select aria-label="Conclusion verdict" disabled={saving} className={field+" mt-1 text-foreground"} value={verdict} onChange={e=>setVerdict(e.target.value)}>{["Promising","Rejected","Unclear"].map(v=><option key={v}>{v}</option>)}</select></label>
    <label className="block text-xs text-muted-foreground">Why?<textarea aria-label="Conclusion reason" disabled={saving} className={field+" mt-1 min-h-24 resize-y text-foreground"} maxLength={2000} value={reason} placeholder="What did the evidence show, and what remains unanswered?" onChange={e=>setReason(e.target.value)}/></label></div>
    <button className={primary} disabled={saving||loading||!reason.trim()} onClick={save}>{saving?"Saving conclusion…":"Save conclusion"}</button>
    {loading?<p className="text-xs text-muted-foreground">Loading saved notes…</p>:<ol className="space-y-3" data-testid="conclusion-history">{notes.map(note=><li key={note.operation_id} className="rounded-md border bg-background/40 p-3"><p className="flex flex-wrap justify-between gap-1 text-sm"><strong>{note.verdict}</strong><span className="text-xs text-muted-foreground">{et(note.created)}</span></p><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed">{note.reason}</p><p className="mt-2 text-xs text-muted-foreground">{horizonLabel(note.horizon)} · {note.unit==="percent"?"Percent":"Daily ATR(14)"} · {note.outcome_informed?"Outcome-informed":"Exposure history recorded"} · Note {note.sequence}</p><details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">Linked immutable runs</summary><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify({runs:note.run_ids,comparison:note.comparison_id,references:note.references},null,2)}</pre></details></li>)}</ol>}
  </section>;
}
