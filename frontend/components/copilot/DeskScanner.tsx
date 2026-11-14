"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { type ScannerCandidateRow, type ScannerMonitoring } from "@/lib/api";
import { etTime, monitoringText } from "@/components/ScannerFreshness";
import type { DeskGuide } from "@/components/copilot/DeskChart";
import { cn } from "@/lib/utils";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";

/**
 * Today's setup-scanner candidates on the desk (docs/copilot-lab.md § Scanner on the desk), from ``GET /copilot/scanner``:
 * read once a minute while the lab is on; database reads only. The Feed shows them behind its Scanner filter. Tapping a
 * row opens the ticker on the desk chart with the trigger, stop and target as thin lines. Display only: nothing here
 * changes the scanner, pings, rates or sends anything.
 */

export type ScannerRadarCard = { id: string; event_id: string; words: string; levels_line: string; plan_state: string; investigation_id: string | null; href: string };
export type DeskScannerRow = {
  id: string; symbol: string; setup: ScannerCandidateRow["setup"]; direction: ScannerCandidateRow["direction"]; words: string; bar_end: string;
  trigger: number | null; stop: number; target: number; vwap: number | null; range_high: number | null; range_low: number | null;
  flags: string[]; contract_line: string | null; status: ScannerCandidateRow["status"]; pnl: number | null; exit_reason: string | null;
  /** He neither holds, watches nor plans it. */
  new: boolean;
  /** The Radar setup card on the same name, day and direction: shown once, in this row. */
  radar: ScannerRadarCard | null;
};
export type DeskScannerReply = {
  state: "ok" | "off" | "unavailable"; day: string | null; monitoring: ScannerMonitoring | null; rows: DeskScannerRow[];
  message: string | null; simulated: boolean;
};


export function useDeskScanner(on: boolean): DeskScannerReply | null {
  const [data, setData] = useState<DeskScannerReply | null>(null);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/scanner", controller.signal)
      // A refusal is read through too, so the request ends (an unread body holds it open).
      .then(async r => (r.ok ? r.json() : r.text().catch(() => "").then(() => Promise.reject(new Error(String(r.status))))))
      .then((body: DeskScannerReply) => setData(body))
      .catch(() => { /* the last good list stays */ });
    load();
    const stop = everyDeskMinute(load); // the shared minute: one request with the desk's other reads, none while hidden
    return () => { controller.abort(); stop(); };
  }, [on]);
  return data;
}

/** A row's levels as the desk chart's thin lines. */
export function scannerGuides(row: DeskScannerRow): DeskGuide[] {
  return [
    ...(row.trigger !== null ? [{ price: row.trigger, label: "Scan trigger" }] : []),
    { price: row.stop, label: "Scan stop" },
    { price: row.target, label: "Scan target" },
  ];
}

const STATUS: Record<DeskScannerRow["status"], string> = {
  no_contract: "Paper: no contract", pending_entry: "Paper: awaiting entry", open: "Paper: open", exiting: "Paper: exiting",
  exit: "Paper: closed", unresolved: "Paper: unresolved",
};
const EXIT_REASON: Record<string, string> = { stop: "Stop", target: "Target", time_stop: "60-min time stop", flat: "Flat by close" };
const ACTION = "inline-flex min-h-11 items-center gap-1 rounded-md border px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7";
const two = (n: number) => n.toFixed(2);
function money(value: number) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

/** The Feed's Scanner section. */
/** A card a ping opened the desk on: an amber edge, as the book marks its selected row. */
export const FOCUSED = "bg-secondary/50 shadow-[inset_3px_0_0_0_hsl(var(--primary))]";

/** Brings the element into view once it is ``on`` (a ping's card). */
export function useInView<T extends HTMLElement = HTMLLIElement>(on: boolean) {
  const ref = useRef<T>(null);
  useEffect(() => { if (on) ref.current?.scrollIntoView({ block: "nearest" }); }, [on]);
  return ref;
}

export function ScannerList({ reply, onOpen, onPlan, focused = null }: {
  reply: DeskScannerReply | null; onOpen(row: DeskScannerRow): void; onPlan(href: string): void;
  /** The candidate a scanner ping opened the desk on. */
  focused?: string | null;
}) {
  if (!reply) return <p className="text-xs text-muted-foreground">Reading the scanner…</p>;
  const m = reply.monitoring;
  const stale = m?.state === "stale";
  const status = m ? monitoringText(m) : null;
  const when = reply.simulated ? "Simulated (sandbox fixture)"
    : stale && m?.last_judged_bar_end ? `As of ${etTime(m.last_judged_bar_end, false)} ET` : null;
  return (
    <section data-testid="feed-scanner" aria-label="Scanner" className="space-y-2">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Setup scanner · today</span>
        {when && <span data-testid="scanner-when" className={cn(reply.simulated && "text-amber-300", stale && "text-muted-foreground")}>{when}</span>}
        <Link href="/scanner" className="ml-auto hover:text-foreground">Scanner page →</Link>
      </p>
      {status && !reply.simulated && <p data-testid="scanner-freshness" className={cn("px-1 text-xs", status.warn ? "text-primary" : "text-muted-foreground")}>{status.text}</p>}
      {reply.state !== "ok" || !reply.rows.length ? (
        <p className="rounded-md border bg-card px-3 py-2.5 text-xs text-muted-foreground">
          {reply.message ?? (reply.state === "off" ? "The scanner is switched off." : "No setups so far today.")}
        </p>
      ) : (
        <ol className={cn("divide-y rounded-lg border bg-card", stale && "opacity-60")} data-stale={stale || undefined}>
          {reply.rows.map(row => <ScannerRow key={row.id} row={row} onOpen={onOpen} onPlan={onPlan} focused={row.id === focused} />)}
        </ol>
      )}
      <p className="px-1 text-xs text-muted-foreground">The scanner&apos;s rules paper trades, shown as found: one contract, not your trades. Nothing here places an order.</p>
    </section>
  );
}

function ScannerRow({ row, onOpen, onPlan, focused }: { row: DeskScannerRow; onOpen(row: DeskScannerRow): void; onPlan(href: string): void; focused: boolean }) {
  const at = useInView(focused);
  const levels = [row.trigger !== null ? `Trigger ${two(row.trigger)}` : null, `Stop ${two(row.stop)}`, `Target ${two(row.target)}`].filter(Boolean).join(" · ");
  const result = row.pnl !== null ? ` · ${EXIT_REASON[row.exit_reason ?? ""] ?? row.exit_reason ?? "Closed"} ${money(row.pnl)}` : "";
  return (
    <li ref={at} data-testid="scanner-row" data-symbol={row.symbol} data-focused={focused || undefined} aria-current={focused || undefined}
      className={cn("min-w-0", focused && FOCUSED)}>
      <button type="button" onClick={() => onOpen(row)} title={`Open ${row.symbol} on the chart with the scanner's levels`}
        className="block w-full min-w-0 px-3 py-2 text-left hover:bg-secondary">
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="font-semibold text-foreground">{row.symbol}</span>
          <span className="text-xs text-muted-foreground">{row.words}</span>
          {row.new && <span data-testid="scanner-new" className="rounded-full bg-secondary px-1.5 text-[11px] text-sky-300">new to you</span>}
          {row.radar && <span data-testid="scanner-radar" className="rounded border px-1.5 text-[11px] text-muted-foreground">Radar setup too</span>}
          <span className="ml-auto whitespace-nowrap text-xs tabular-nums text-muted-foreground">{etTime(row.bar_end, false)}</span>
        </span>
        <span className="block text-sm tabular-nums text-foreground">{levels}</span>
        <span className="block text-xs tabular-nums text-muted-foreground">
          {row.contract_line ?? "No contract"} · {STATUS[row.status]}
          {row.pnl !== null && <span className={row.pnl > 0 ? "text-emerald-400" : row.pnl < 0 ? "text-red-400" : undefined}>{result}</span>}
        </span>
        {row.radar && <span className="block text-xs text-muted-foreground">Radar: {row.radar.levels_line}</span>}
      </button>
      {row.radar && row.radar.plan_state === "none" && (
        <div className="px-3 pb-2"><button type="button" onClick={() => onPlan(row.radar!.href)} className={ACTION}>Plan it</button></div>
      )}
    </li>
  );
}
