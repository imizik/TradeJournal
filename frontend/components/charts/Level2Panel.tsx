"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import LiveDepthSession from "@/components/level2/LiveDepthSession";
import { LEVEL2_TICKER } from "@/components/level2/useDepthSession";
import type { DepthSession } from "@/components/level2/useDepthSession";
import type { RecordedDepth } from "@/components/level2/useRecordedDepth";
import { HEAT_BOOK_LABELS } from "@/lib/depthHeatmap";
import type { DepthHeatmap, HeatBookKind } from "@/lib/depthHeatmap";
import Sheet from "./Sheet";

/** Which order-flow layers the main chart draws. Levels and the profile are the quiet default; the heatmap is opt-in. */
export type OrderFlow = { levels: boolean; profile: boolean; heatmap: boolean; kind: HeatBookKind };
export const DEFAULT_FLOW: OrderFlow = { levels: true, profile: true, heatmap: false, kind: "arca" };
export const FLOW_KEY = "tradejournal.charts.orderflow.v1";
export function cleanFlow(saved: Partial<OrderFlow>): OrderFlow {
  const flag = (value: unknown, fallback: boolean) => typeof value === "boolean" ? value : fallback;
  return { levels: flag(saved.levels, DEFAULT_FLOW.levels), profile: flag(saved.profile, DEFAULT_FLOW.profile),
    heatmap: flag(saved.heatmap, DEFAULT_FLOW.heatmap), kind: saved.kind === "mpid" ? "mpid" : "arca" };
}

/** How much of the heatmap has filled, refreshed with the data at most once a second. */
function HeatStats({ heatmap, kind }: { heatmap: DepthHeatmap | null; kind: HeatBookKind }) {
  const [, setVersion] = useState(0);
  useEffect(() => {
    if (!heatmap) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = heatmap.subscribe(() => { timer ??= setTimeout(() => { timer = null; setVersion(heatmap.version); }, 1_000); });
    return () => { off(); if (timer) clearTimeout(timer); };
  }, [heatmap]);
  if (!heatmap) return <p className="text-[10px] leading-4 text-slate-500">Nothing collected for this symbol yet</p>;
  const columns = heatmap.columns(kind);
  const minutes = columns.length ? (columns[columns.length - 1].start + columns[columns.length - 1].width - columns[0].start) / 60_000 : 0;
  return <p className="text-[10px] leading-4 text-slate-500">
    {columns.length ? `${minutes < 1 ? "<1" : Math.round(minutes)} min of ${HEAT_BOOK_LABELS[kind]} collected` : "Nothing collected for this book yet"}
    {heatmap.skipped ? ` · ${heatmap.skipped} updates without a usable source time left out` : ""}
  </p>;
}

/**
 * The optional Level 2 dock panel: owner-only (ChartWorkspace never renders it
 * otherwise). It shows the Charts page's one manual session (`session`, owned
 * by ChartWorkspace so it keeps running with the dock closed) for the chart's
 * US stock or ETF ticker, and the heatmap's controls. One ticker streams at a
 * time: while another is running, the panel only offers to stop it. Anything
 * that is not a plain ticker (an option, an index) says so and makes no
 * request. Connect stays an explicit click.
 */
export default function Level2Panel({ symbol, sheet, session, onConnect, heatmap, flow, onFlow, recorded, recording, heatAllowed, onClose }: {
  symbol: string; sheet: boolean; session: DepthSession; onConnect(ticker: string): void; heatmap: DepthHeatmap | null;
  flow: OrderFlow; onFlow(next: OrderFlow): void; recorded: RecordedDepth["state"]; recording: boolean; heatAllowed: boolean; onClose(): void;
}) {
  const supported = LEVEL2_TICKER.test(symbol);
  const elsewhere = session.running && session.symbol !== symbol ? session.symbol : null;
  const source = recorded === "ready" ? (recording ? "Recorded · about 5 seconds behind live, back to 4 AM" : "Recorded today · not receiving right now")
    : recorded === "unrecorded" ? "Not on the recorder's watchlist · Connect below for a live session; liquidity levels need the recorder"
      : recorded === "loading" ? "Checking the recorder…" : "Recorder data unavailable · Connect below for a live session";
  const toggle = (name: "levels" | "profile" | "heatmap", label: string, note = "") => <label className="flex min-w-0 items-center gap-2">
    <input type="checkbox" checked={flow[name]} onChange={(event) => onFlow({ ...flow, [name]: event.target.checked })} />{label}{note && <span className="text-slate-500">{note}</span>}</label>;
  const controls = <div className="min-w-0 space-y-1 border-b border-sky-400/20 px-3 py-2 text-xs text-slate-300" aria-label="Order flow">
    <p role="status" className="text-[11px] leading-4 text-slate-400">{source}</p>
    {toggle("levels", "Liquidity levels")}
    {toggle("profile", "Depth profile")}
    {toggle("heatmap", "Heatmap", heatAllowed ? "" : " · 1m–5m candles only")}
    <label className="flex min-w-0 items-center gap-2">Book
      <select value={flow.kind} onChange={(event) => onFlow({ ...flow, kind: event.target.value as HeatBookKind })} className="min-w-0 flex-1 truncate rounded border border-slate-700 bg-slate-900 px-1 py-0.5">
        {(Object.keys(HEAT_BOOK_LABELS) as HeatBookKind[]).map((kind) => <option key={kind} value={kind}>{HEAT_BOOK_LABELS[kind]}</option>)}
      </select></label>
    {flow.heatmap && <HeatStats heatmap={heatmap} kind={flow.kind} />}
    <p className="text-[10px] leading-4 text-slate-500">Displayed size in one provider book, not the whole market or executable liquidity. A level marks size that stood out and rested; it is not a prediction and can be pulled. Heatmap brightness is relative to the view; blank means no usable update, not zero.</p>
  </div>;
  const body = <>
    <div className="flex items-center justify-between border-b border-slate-700/40 py-1 pl-3 pr-1">
      <h2 className="text-xs font-medium text-slate-200">{symbol} Level 2</h2>
      <button aria-label="Close Level 2" title="Close Level 2" onClick={onClose} className={`inline-flex items-center justify-center rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200 ${sheet ? "h-11 w-11" : "h-7 w-7"}`}><X size={14} /></button>
    </div>
    {supported && !elsewhere
      ? <>{controls}<LiveDepthSession compact symbol={symbol} session={{ ...session, connect: onConnect }} /></>
      : <div className="space-y-2 px-3 py-3 text-xs leading-5 text-slate-400">
        <p role="status">{elsewhere ? `One symbol streams at a time, and ${elsewhere} is running for its heatmap.` : `Level 2 depth covers US stock and ETF tickers, so nothing is shown for ${symbol}.`}{session.running ? "" : " No provider connection was started."}</p>
        {elsewhere && <p><button onClick={session.stop} className="text-sky-300 underline">Stop {elsewhere}</button>{supported ? ` to start ${symbol}.` : ""}</p>}
      </div>}
    <p className="px-3 py-2 text-[10px] leading-4 text-slate-500">Equity depth only; it is separate from an option contract&apos;s depth. Recorded tickers come from the depth recorder; a Connect session lives only in this page.</p>
  </>;
  if (sheet) return <Sheet label="Level 2" onClose={onClose}>{body}</Sheet>;
  return <section aria-label="Level 2">{body}</section>;
}
