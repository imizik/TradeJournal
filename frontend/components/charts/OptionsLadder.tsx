"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { fetchOptionsLadder, price } from "@/lib/charts";
import type { OptionsLadder as Ladder, OptionsLayer, OptionStrike, OptionsScope } from "@/lib/charts";
import { contracts, gammaText, optionsAsOf, SCOPE_NAMES } from "@/lib/optionsView";
import Sheet from "./Sheet";

const REFRESH_MS = 60_000;

/**
 * The strike ladder (C4.5): a side panel, off until opened, centred on the
 * price. Puts' volume and open interest sit left of each strike, calls' right,
 * each open interest shaded by its size; gamma is the bar under the strike.
 * A click highlights that strike on the charts. It shares the options layer's
 * scope and gamma sign, refreshes every minute while the page is visible, and
 * is a bottom sheet on a phone.
 */
export default function OptionsLadder({ symbol, layer, spot, highlight, sheet, onStrike, onLayer, onClose }: {
  symbol: string; layer: OptionsLayer; spot(): number | null; highlight: number | null; sheet: boolean;
  onStrike(strike: number): void; onLayer(patch: Partial<OptionsLayer>): void; onClose(): void;
}) {
  const [result, setResult] = useState<{ key: string; data?: Ladder; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const centred = useRef("");
  const spotRow = useRef<HTMLDivElement>(null);
  const priceOf = useRef(spot);
  useEffect(() => { priceOf.current = spot; });
  const signed = layer.signed;
  const key = `${symbol}|${layer.scope}|${signed}`;

  useEffect(() => {
    let controller: AbortController | null = null;
    let alive = true;
    const load = () => {
      if (document.hidden) return;
      controller?.abort();
      controller = new AbortController();
      fetchOptionsLadder({ symbol, scope: layer.scope, signed, spot: priceOf.current() }, controller.signal)
        .then((data) => { if (alive) setResult({ key, data }); })
        .catch((error: Error) => { if (alive && error.name !== "AbortError") setResult({ key, error: error.message }); });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    const onVisible = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { alive = false; controller?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [symbol, layer.scope, signed, key, retry]);

  const shown = result?.key === key ? result : null;
  const data = shown?.data;
  const rows = data?.rows ?? [];
  // The price sits between the strikes around it; the ladder opens scrolled to it, once per symbol and scope.
  const at = data?.spot ?? null;
  const split = at === null ? -1 : rows.findIndex((row) => row.strike > at);
  useEffect(() => {
    const row = spotRow.current;
    if (!data?.rows.length || centred.current === key || !row) return;
    centred.current = key;
    // The panel's own scroll box only (the dock, or the phone's sheet): never the page under it.
    let box = row.parentElement;
    while (box && !(box.scrollHeight > box.clientHeight && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
    if (box) box.scrollTop += row.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 2;
  }, [data, key]);

  const most = (pick: (row: OptionStrike) => number | null) => Math.max(1, ...rows.map((row) => Math.abs(pick(row) ?? 0)));
  const [topOi, topGamma] = [Math.max(most((row) => row.call_oi), most((row) => row.put_oi)), most((row) => row.gamma)];
  const tap = sheet ? "min-h-11" : "min-h-6";
  const wall = (strike: number) => [data?.walls.call_oi === strike && "call wall", data?.walls.put_oi === strike && "put wall"].filter(Boolean).join(", ");

  const marker = (index: number) => index === split && at !== null && <div ref={spotRow} role="separator" aria-label={`Price ${price(at)}`}
    className="flex items-center gap-1 px-2 text-[9px] text-sky-300"><span className="h-px flex-1 bg-sky-400/50" />{price(at)}<span className="h-px flex-1 bg-sky-400/50" /></div>;

  const body = <>
    <div className="flex items-center justify-between border-b border-slate-700/40 py-1 pl-3 pr-1">
      <h2 className="text-xs font-medium text-slate-200">{symbol} strike ladder</h2>
      <button aria-label="Close strike ladder" title="Close the strike ladder" onClick={onClose} className={`inline-flex items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${sheet ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
    </div>
    <div className="space-y-1.5 border-b border-slate-700/40 px-3 py-2">
      <div role="group" aria-label="Ladder expirations" className="flex overflow-hidden rounded border border-slate-700/70 text-[10px]">
        {(Object.keys(SCOPE_NAMES) as OptionsScope[]).map((scope) => <button key={scope} aria-pressed={layer.scope === scope} onClick={() => onLayer({ scope })}
          className={`flex-1 px-1 ${tap} ${layer.scope === scope ? "bg-slate-800 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>{SCOPE_NAMES[scope]}</button>)}
      </div>
      <label className={`flex items-center gap-2 text-[10px] text-slate-400 ${tap}`}>
        <input type="checkbox" checked={signed} onChange={(event) => onLayer({ signed: event.target.checked })} className="accent-amber-400" />
        Signed gamma (assumed dealer side)
      </label>
      {data?.totals && <p className="font-mono text-[10px] text-slate-500">P/C OI {data.totals.put_call_oi?.toFixed(2) ?? "—"} · P/C vol {data.totals.put_call_volume?.toFixed(2) ?? "—"} · calls {contracts(data.totals.call_oi)} · puts {contracts(data.totals.put_oi)}</p>}
    </div>
    {!shown ? <p role="status" className="px-3 py-3 text-xs text-slate-500">Loading the {symbol} ladder…</p>
      : shown.error ? <div role="alert" className="px-3 py-3 text-xs text-amber-300"><p>{shown.error}</p><button onClick={() => setRetry((value) => value + 1)} className={`mt-2 rounded border border-slate-700 px-3 ${tap}`}>Retry ladder</button></div>
      : !rows.length ? <p role="status" className="px-3 py-3 text-xs text-slate-500">{data?.message ?? "No strikes listed."}</p>
      : <div aria-label={`${symbol} strikes`} role="group" className="pb-2">
        <div aria-hidden className="sticky top-0 z-10 grid grid-cols-[1fr_1fr_auto_1fr_1fr] gap-1 bg-[#121924] px-2 py-1 text-[9px] uppercase tracking-wider text-slate-600">
          <span className="text-right">Put vol</span><span className="text-right">Put OI</span>
          <span className="w-14 text-center">Strike</span><span>Call OI</span><span>Call vol</span>
        </div>
        {rows.map((row, index) => {
          const chosen = highlight === row.strike;
          const named = wall(row.strike);
          const share = (value: number | null, top: number) => `${Math.round(Math.abs(value ?? 0) / top * 100)}%`;
          return <div key={row.strike}>
            {marker(index)}
            <button aria-label={`Strike ${price(row.strike)}${named ? `, ${named}` : ""}`} aria-pressed={chosen} onClick={() => onStrike(row.strike)}
              title={`Gamma ${gammaText(row.gamma, signed)}. Click to mark ${price(row.strike)} on the charts.`}
              className={`grid w-full grid-cols-[1fr_1fr_auto_1fr_1fr] items-center gap-1 px-2 font-mono text-[10px] ${tap} ${chosen ? "bg-sky-400/15" : "hover:bg-slate-800/60"}`}>
              <span className="text-right text-slate-500">{contracts(row.put_volume)}</span>
              <span className="relative text-right text-rose-200/90"><span aria-hidden className="absolute inset-y-0 right-0 bg-rose-400/15" style={{ width: share(row.put_oi, topOi) }} /><span className="relative">{contracts(row.put_oi)}</span></span>
              <span className={`relative w-14 text-center ${named ? "font-semibold text-slate-100" : "text-slate-300"}`}>{price(row.strike)}
                <span aria-hidden className={`absolute -bottom-0.5 left-1/2 h-0.5 -translate-x-1/2 rounded ${signed && (row.gamma ?? 0) < 0 ? "bg-rose-400/80" : signed ? "bg-emerald-400/80" : "bg-violet-400/80"}`} style={{ width: share(row.gamma, topGamma) }} /></span>
              <span className="relative text-teal-200/90"><span aria-hidden className="absolute inset-y-0 left-0 bg-teal-400/15" style={{ width: share(row.call_oi, topOi) }} /><span className="relative">{contracts(row.call_oi)}</span></span>
              <span className="text-slate-500">{contracts(row.call_volume)}</span>
            </button>
          </div>;
        })}
        {split === -1 && marker(-1)}
        <p className="px-3 pt-2 text-[10px] leading-4 text-slate-500">Bars: open interest by size; under each strike, dollar gamma for a 1% move{signed ? ", green where calls outweigh puts on the assumed dealer side" : ""}. {data && optionsAsOf(data)}</p>
      </div>}
  </>;

  if (sheet) return <Sheet label="Strike ladder" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Strike ladder">{body}</section>;
}
