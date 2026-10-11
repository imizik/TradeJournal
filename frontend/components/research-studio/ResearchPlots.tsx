export function Distribution({values, select}: {values: {id:string;y:number}[];select:(id:string)=>void}) {
  if (!values.length) return <p>No available endpoints for this distribution.</p>;
  const lo = Math.min(...values.map(v=>v.y)), hi=Math.max(...values.map(v=>v.y)), width=(hi-lo||1)/10;
  const bins=Array.from({length:10},(_,i)=>values.filter(v=>Math.min(9,Math.floor((v.y-lo)/width))===i));
  const max=Math.max(...bins.map(b=>b.length));
  return <div className="flex h-28 items-end gap-1" aria-label="Outcome distribution">{bins.map((b,i)=><button key={i} className="bg-sky-700 min-w-0 flex-1 text-xs hover:bg-sky-500" style={{height:`${Math.max(10,b.length/max*100)}%`}} title={`${(lo+i*width).toFixed(3)} to ${(lo+(i+1)*width).toFixed(3)}: ${b.length}`} disabled={!b.length} onClick={()=>select(b[0].id)} aria-label={`Distribution bin ${i+1}: ${b.length} occurrences; inspect first`}>{b.length}</button>)}</div>;
}
export function Scatter({values, select}: {values: {id:string;x:number;y:number}[];select:(id:string)=>void}) {
  if (!values.length) return <p>No paired feature/outcome observations.</p>;
  const xs=values.map(v=>v.x),ys=values.map(v=>v.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
  return <svg viewBox="0 0 600 180" className="w-full" aria-label="Decision feature versus forward return"><line x1="20" y1="160" x2="580" y2="160" stroke="currentColor"/><line x1="20" y1="10" x2="20" y2="160" stroke="currentColor"/>{values.map(v=><circle key={v.id} cx={25+(v.x-xmin)/(xmax-xmin||1)*540} cy={155-(v.y-ymin)/(ymax-ymin||1)*140} r="4" fill="#38bdf8" role="button" tabIndex={0} aria-label={`Inspect ${v.id}`} onClick={()=>select(v.id)} onKeyDown={e=>{if(e.key==="Enter")select(v.id);}}><title>{v.id}: feature {v.x.toFixed(3)}, return {v.y.toFixed(3)}</title></circle>)}</svg>;
}
