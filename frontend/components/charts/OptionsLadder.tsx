"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { fetchOptionsLadder, price } from "@/lib/charts";
import type { OptionsLadder as Ladder, OptionsLayer, OptionStrike, OptionsScope } from "@/lib/charts";
import { contracts, gexText, openInterestChangeText, openInterestPeriodText, optionsAsOf, SCOPE_NAMES, strikeText } from "@/lib/optionsView";
import Sheet from "./Sheet";

const REFRESH_MS = 60_000;
const LABEL = "text-[9px] uppercase tracking-[0.18em] text-slate-500";

/**
 * The strike ladder (C4.5) as a dealer-positioning view: a range bar with the
 * walls, gamma flip, max pain and price; signed dollar gamma by strike, highest
 * strike first; and the read (walls, top gamma, flip, max pain, net gamma, the
 * expected move and the chance of touching each wall). Gamma is always signed on
 * the assumed dealer side here. A click highlights that strike on the charts.
 * It shares the options layer's expirations, refreshes every minute while the
 * page is visible, and is a bottom sheet on a phone.
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
  const key = `${symbol}|${layer.scope}`;

  useEffect(() => {
    let controller: AbortController | null = null;
    let alive = true;
    const load = () => {
      if (document.hidden) return;
      controller?.abort();
      controller = new AbortController();
      fetchOptionsLadder({ symbol, scope: layer.scope, signed: true, spot: priceOf.current() }, controller.signal)
        .then((data) => { if (alive) setResult({ key, data }); })
        .catch((error: Error) => { if (alive && error.name !== "AbortError") setResult({ key, error: error.message }); });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    const onVisible = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { alive = false; controller?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [symbol, layer.scope, key, retry]);

  const shown = result?.key === key ? result : null;
  const data = shown?.data;
  // Highest strike first; the price sits between the strikes around it, and the ladder opens scrolled to it.
  const rows = [...(data?.rows ?? [])].sort((a, b) => b.strike - a.strike);
  const at = data?.spot ?? null;
  const split = at === null ? -1 : rows.findIndex((row) => row.strike < at);
  const bracket = new Set(at === null ? [] : [rows[split - 1]?.strike, rows[split === -1 ? rows.length - 1 : split]?.strike]);
  useEffect(() => {
    const row = spotRow.current;
    if (!data?.rows.length || centred.current === key || !row) return;
    centred.current = key;
    // The panel's own scroll box only (the dock, or the phone's sheet): never the page under it.
    let box = row.parentElement;
    while (box && !(box.scrollHeight > box.clientHeight && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
    if (box) box.scrollTop += row.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 2;
  }, [data, key]);

  const topGamma = Math.max(1, ...rows.map((row) => Math.abs(row.gamma ?? 0)));
  const tap = sheet ? "min-h-11" : "min-h-6";
  const callWall = data?.walls.call_oi ?? null, putWall = data?.walls.put_oi ?? null;
  const wall = (strike: number) => [callWall === strike && "call wall", putWall === strike && "put wall"].filter(Boolean).join(", ");
  const net = data?.net_gamma ?? null;

  const marker = (index: number) => index === split && at !== null && <div ref={spotRow} role="separator" aria-label={`Price ${price(at)}`}
    className="flex items-center gap-1 px-1 text-[9px] text-sky-300"><span className="h-px flex-1 bg-sky-400/50" />{price(at)}<span className="h-px flex-1 bg-sky-400/50" /></div>;

  const strikeRow = (row: OptionStrike, index: number) => {
    const chosen = highlight === row.strike;
    const named = wall(row.strike);
    const gamma = row.gamma ?? 0;
    const tag = callWall === row.strike ? "CW" : putWall === row.strike ? "PW" : "";
    const big = Math.abs(gamma) >= topGamma * 0.6;
    const bar = gamma < 0 ? (big ? "bg-rose-500" : "bg-rose-500/70") : (big ? "bg-emerald-500" : "bg-emerald-500/70");
    const detail = `Net gamma ${gexText(row.gamma)} per 1% (assumed dealer side). Calls ${contracts(row.call_oi)} OI, ${contracts(row.call_volume)} vol · puts ${contracts(row.put_oi)} OI, ${contracts(row.put_volume)} vol. ${openInterestChangeText(row.oi_change)}`;
    return <div key={row.strike}>
      {marker(index)}
      <button aria-label={`Strike ${price(row.strike)}${named ? `, ${named}` : ""}`} aria-pressed={chosen} onClick={() => onStrike(row.strike)}
        title={`${detail} Click to mark ${price(row.strike)} on the charts.`}
        className={`grid w-full grid-cols-[3.25rem_1fr_3.75rem] items-center gap-2 rounded px-1 font-mono text-[11px] ${tap}
          ${chosen ? "bg-sky-400/20" : bracket.has(row.strike) ? "bg-sky-400/10" : "hover:bg-slate-800/60"}`}>
        <span className={`text-right ${bracket.has(row.strike) ? "text-sky-300" : named ? "text-slate-100" : "text-slate-400"}`}>
          {tag && <span className="mr-1 text-[9px] text-slate-500">{tag}</span>}{strikeText(row.strike)}</span>
        <span aria-hidden className="h-2.5 overflow-hidden rounded-full bg-slate-800/70">
          <span className={`block h-full rounded-full ${bar}`} style={{ width: `${Math.max(2, Math.round(Math.abs(gamma) / topGamma * 100))}%` }} /></span>
        <span className={`text-right ${row.gamma == null ? "text-slate-600" : gamma < 0 ? "text-rose-400" : "text-emerald-400"}`}>{gexText(row.gamma)}</span>
      </button>
    </div>;
  };

  const body = <>
    <div className="flex items-center justify-between gap-2 border-b border-slate-700/40 py-1.5 pl-3 pr-1">
      <h2 className="flex min-w-0 items-baseline gap-2 font-mono">
        <span className="text-sm font-semibold text-slate-100">{symbol}</span>
        {at !== null && <span className="text-sm text-sky-300">${price(at)}</span>}
        {net !== null && <span title="Net dollar gamma across every strike in scope, on the assumed dealer side"
          className={`rounded border px-1 text-[9px] tracking-wider ${net < 0 ? "border-rose-500/50 bg-rose-500/10 text-rose-300" : "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"}`}>{net < 0 ? "NEG γ" : "POS γ"}</span>}
      </h2>
      <button aria-label="Close strike ladder" title="Close the strike ladder" onClick={onClose} className={`inline-flex shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${sheet ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
    </div>
    <div className="border-b border-slate-700/40 px-3 py-2">
      <div role="group" aria-label="Ladder expirations" className="flex overflow-hidden rounded border border-slate-700/70 text-[10px]">
        {(Object.keys(SCOPE_NAMES) as OptionsScope[]).map((scope) => <button key={scope} aria-pressed={layer.scope === scope} onClick={() => onLayer({ scope })}
          className={`flex-1 px-1 ${tap} ${layer.scope === scope ? "bg-slate-800 text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>{SCOPE_NAMES[scope]}</button>)}
      </div>
    </div>
    {!shown ? <p role="status" className="px-3 py-3 text-xs text-slate-500">Loading the {symbol} ladder…</p>
      : shown.error ? <div role="alert" className="px-3 py-3 text-xs text-amber-300"><p>{shown.error}</p><button onClick={() => setRetry((value) => value + 1)} className={`mt-2 rounded border border-slate-700 px-3 ${tap}`}>Retry ladder</button></div>
      : !rows.length || !data ? <p role="status" className="px-3 py-3 text-xs text-slate-500">{data?.message ?? "No strikes listed."}</p>
      : <>
        <RangeBar data={data} rows={rows} />
        <div aria-label={`${symbol} strikes`} role="group" className="mx-2 rounded-lg border border-slate-700/50 bg-slate-900/40 px-1.5 pb-1.5">
          <p className={`${LABEL} px-1 py-2`}>Dealer ladder · near spot</p>
          {rows.map(strikeRow)}
          {split === -1 && marker(-1)}
        </div>
        <Read data={data} />
        <p className="px-3 pb-3 text-[10px] leading-4 text-slate-500">
          Gamma is dollar gamma for a 1% move, signed with dealers assumed long calls and short puts: open interest does not say who holds a contract.
          {data.rows[0]?.oi_change ? ` ${openInterestPeriodText(data.rows[0].oi_change)}.` : ""} {optionsAsOf(data)}</p>
      </>}
  </>;

  if (sheet) return <Sheet label="Strike ladder" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Strike ladder">{body}</section>;
}

/** Put wall, flip, max pain, call wall and the price on one track, coloured by each strike's signed gamma. */
function RangeBar({ data, rows }: { data: Ladder; rows: OptionStrike[] }) {
  const marks = [
    { name: "Put wall", value: data.walls.put_oi ?? null, text: "text-rose-400", tick: "bg-rose-400" },
    { name: "Flip", value: data.flip?.price ?? null, text: "text-sky-400", tick: "bg-sky-400" },
    { name: "Max pain", value: data.max_pain?.price ?? null, text: "text-amber-300", tick: "bg-amber-300" },
    { name: "Call wall", value: data.walls.call_oi ?? null, text: "text-emerald-400", tick: "bg-emerald-400" },
  ].filter((mark): mark is typeof mark & { value: number } => mark.value !== null);
  const values = [...rows.map((row) => row.strike), ...marks.map((mark) => mark.value), ...(data.spot ? [data.spot] : [])];
  const low = Math.min(...values), high = Math.max(...values);
  const at = (value: number) => high === low ? 50 : (value - low) / (high - low) * 100;
  const step = rows.length > 1 ? Math.abs(rows[0].strike - rows[1].strike) : 1;
  const ascending = [...rows].reverse();
  // Labels in lanes above the track so neighbours do not overlap.
  const lanes: number[] = [];
  const placed = [...marks].sort((a, b) => a.value - b.value).map((mark) => {
    const left = Math.min(88, Math.max(12, at(mark.value)));
    let lane = lanes.findIndex((end) => left - end >= 30);
    if (lane === -1) { lane = lanes.length; lanes.push(left); } else lanes[lane] = left;
    return { ...mark, left, lane };
  });
  return <figure aria-label="Dealer levels on a range bar" className="px-3 pb-3 pt-2">
    <div className="relative font-mono text-[9px] tracking-wider" style={{ height: `${Math.max(1, lanes.length) * 14}px` }}>
      {placed.map((mark) => <span key={mark.name} className={`absolute -translate-x-1/2 whitespace-nowrap uppercase ${mark.text}`}
        style={{ left: `${mark.left}%`, top: `${mark.lane * 14}px` }}>{mark.name} {strikeText(mark.value)}</span>)}
    </div>
    <div className="relative mt-1.5 h-2">
      <div aria-hidden className="absolute inset-0 overflow-hidden rounded-full bg-slate-800">
        {ascending.map((row) => <span key={row.strike} className={`absolute inset-y-0 ${(row.gamma ?? 0) < 0 ? "bg-rose-500" : "bg-emerald-500"}`}
          style={{ left: `${at(row.strike - step / 2)}%`, width: `${Math.max(0.5, at(row.strike + step / 2) - at(row.strike - step / 2))}%`, opacity: row.gamma == null ? 0.15 : 0.55 }} />)}
      </div>
      {marks.map((mark) => <span key={mark.name} aria-hidden className={`absolute -top-1 h-4 w-0.5 -translate-x-1/2 ${mark.tick}`} style={{ left: `${at(mark.value)}%` }} />)}
      {data.spot !== null && <span aria-hidden className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-sky-200 bg-sky-400 shadow-[0_0_10px_rgba(56,189,248,0.7)]" style={{ left: `${at(data.spot)}%` }} />}
    </div>
    {data.spot !== null && <div className="relative mt-1.5 h-3 font-mono text-[10px] text-sky-300">
      <span className="absolute -translate-x-1/2" style={{ left: `${Math.min(92, Math.max(8, at(data.spot)))}%` }}>{price(data.spot)}</span></div>}
    <figcaption className="sr-only">{marks.map((mark) => `${mark.name} ${price(mark.value)}`).join(", ")}{data.spot !== null ? `, price ${price(data.spot)}` : ""}</figcaption>
  </figure>;
}

/** The read: the levels and the numbers that frame them, one per line. */
function Read({ data }: { data: Ladder }) {
  const move = data.expected_move;
  const percent = (value: number | null | undefined) => value == null ? "—" : `${(value * 100).toFixed(0)}%`;
  const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
  const touchNote = !data.touch ? "needs the expected move"
    : data.touch.call_wall == null && data.touch.put_wall == null ? "needs the expected move" : `by ${day(data.touch.expiration)}, model estimate`;
  const lines: { name: string; value: string; tone: string; note?: string | null }[] = [
    { name: "Call wall", value: strikeText(data.walls.call_oi), tone: "text-emerald-400", note: "most call open interest" },
    { name: "Put wall", value: strikeText(data.walls.put_oi), tone: "text-rose-400", note: "most put open interest" },
    { name: "Top gamma", value: strikeText(data.top_gamma), tone: "text-amber-300", note: "largest net gamma strike" },
    { name: "Gamma flip", value: data.flip ? strikeText(data.flip.price) : "—", tone: "text-sky-400", note: data.flip ? (data.flip.price == null ? data.flip.note : "model estimate") : "SPY, QQQ and SPX only" },
    { name: "Max pain", value: strikeText(data.max_pain?.price), tone: "text-amber-300", note: data.max_pain ? `${day(data.max_pain.expiration)} · folklore, not a forecast` : data.max_pain_reason },
    { name: "Net GEX · in scope", value: gexText(data.net_gamma), tone: (data.net_gamma ?? 0) < 0 ? "text-rose-400" : "text-emerald-400", note: "per 1%, assumed dealer side" },
    { name: "Expected move", value: move?.state === "ready" && move.move != null ? `±${move.move.toFixed(2)}` : "—", tone: "text-slate-100",
      note: move?.state === "ready" ? `${percent(move.percent)} · ${day(move.expiration)} straddle${move.iv ? ` · IV ${percent(move.iv)}` : ""}` : move?.reason ?? "no straddle priced yet" },
    { name: "P(touch) call wall", value: percent(data.touch?.call_wall), tone: "text-emerald-400", note: touchNote },
    { name: "P(touch) put wall", value: percent(data.touch?.put_wall), tone: "text-rose-400", note: touchNote },
    { name: "Put / call", value: `${data.totals?.put_call_oi?.toFixed(2) ?? "—"} OI · ${data.totals?.put_call_volume?.toFixed(2) ?? "—"} vol`, tone: "text-slate-300" },
  ];
  return <section aria-label="The read" className="m-2 rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 pb-1">
    <h3 className={`${LABEL} py-2`}>The read</h3>
    <dl className="font-mono">
      {lines.map((line) => <div key={line.name} className="border-t border-slate-700/40 py-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-[10px] uppercase tracking-wider text-slate-400">{line.name}</dt>
          <dd className={`text-xs ${line.tone}`}>{line.value}</dd>
        </div>
        {line.note && <p className="text-right text-[9px] text-slate-500">{line.note}</p>}
      </div>)}
    </dl>
  </section>;
}
