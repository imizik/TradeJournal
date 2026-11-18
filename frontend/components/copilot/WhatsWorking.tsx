"use client";

import { useEffect, useState } from "react";
import { deskGet } from "@/lib/deskMinute";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";
import ModeMark from "./ModeMark";
import type { PaperRecord } from "./PaperRecordLine";

/**
 * What's working (docs/copilot-lab.md § What's working): where his money comes from and where it leaks. Opened in place
 * from "How I'm doing" (or ⌘K's "What's working"), it reads ``GET /copilot/desk/whats-working`` once per opening and
 * shows the top 3 buckets making money and the top 3 losing it, REAL beside PAPER, each with its sample. Only buckets of
 * 5 or more trades are named; a smaller one is too few to judge. Read only.
 */

export type Bucket = { label: string; trades: number; wins: number; losses: number; pnl: number; avg_pnl: number | null;
  win_rate: number | null; judged: boolean; dimension?: string };
export type Side = Bucket & { missing: Record<string, number>; making: Bucket[]; losing: Bucket[]; dimensions: Record<string, Bucket[]> };
export type WhatsWorkingReport = { as_of: number; min_trades: number; window_days: number;
  windows: Record<"recent" | "all", { real: Side; paper: Side }> };

const tone = (n: number) => Math.round(n * 100) === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";

async function readJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await deskGet(path, signal);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

function Row({ b }: { b: Bucket }) {
  return (
    <li data-testid="whats-working-bucket" className="py-0.5">
      <span className="block text-foreground/90">{b.label}</span>
      <span className="block tabular-nums text-muted-foreground">
        <span className={tone(b.pnl)}>{money(b.pnl, { signed: true, cents: false })}</span> · {b.trades} trades · {b.wins}W {b.losses}L
      </span>
    </li>
  );
}

function Column({ mode, side, min }: { mode: "real" | "paper"; side: Side; min: number }) {
  const none = (what: string) => <li className="py-0.5 text-muted-foreground">{side.trades < min ? "Too few trades to judge" : `Nothing ${what} with ${min}+ trades`}</li>;
  return (
    <div data-testid={`whats-working-${mode}`} className="min-w-0">
      <p className="flex items-baseline justify-between gap-1">
        <ModeMark mode={mode} short />
        <span className="tabular-nums text-muted-foreground">{side.trades} closed</span>
      </p>
      <p className="mt-1 text-[11px] text-emerald-300/90">Making money</p>
      <ul>{side.making.length ? side.making.map(b => <Row key={`${b.dimension}:${b.label}`} b={b} />) : none("making money")}</ul>
      <p className="mt-1 text-[11px] text-rose-300/90">Losing money</p>
      <ul>{side.losing.length ? side.losing.map(b => <Row key={`${b.dimension}:${b.label}`} b={b} />) : none("losing money")}</ul>
      {side.missing.pnl > 0 && <p className="mt-1 text-[11px] text-muted-foreground">{side.missing.pnl} closed without a P&amp;L, left out</p>}
    </div>
  );
}

export function WhatsWorkingView() {
  const [report, setReport] = useState<WhatsWorkingReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [window_, setWindow] = useState<"recent" | "all">("recent");
  useEffect(() => {
    const controller = new AbortController();
    readJson<WhatsWorkingReport>("/copilot/desk/whats-working", controller.signal)
      .then(setReport).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not read it."); });
    return () => controller.abort();
  }, []);
  if (error) return <p role="alert" className="px-3 pb-2 text-xs text-amber-300">What&apos;s working: {error}</p>;
  if (!report) return <p className="px-3 pb-2 text-xs text-muted-foreground">Reading your trades…</p>;
  const w = report.windows[window_];
  const pick = (name: "recent" | "all", text: string) => (
    <button type="button" aria-pressed={window_ === name} onClick={() => setWindow(name)}
      className={cn("inline-flex min-h-11 items-center rounded px-1.5 sm:min-h-6", window_ === name ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}>{text}</button>
  );
  return (
    <div data-testid="whats-working" className="space-y-1 border-t px-3 pb-2 pt-1.5 text-xs">
      <div className="flex flex-wrap items-center gap-x-1">
        {pick("recent", `Last ${report.window_days} days`)}{pick("all", "All time")}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Column mode="real" side={w.real} min={report.min_trades} />
        <Column mode="paper" side={w.paper} min={report.min_trades} />
      </div>
      <p className="text-[11px] text-muted-foreground">Buckets: call, put or shares; entry time (New York); hold; days to expiry; paper also by whose idea and your rules. Under {report.min_trades} trades is too few to judge.</p>
    </div>
  );
}

/** The "What's working ▸" line at the foot of How I'm doing: opens the view in place. */
export default function WhatsWorking() {
  const [open, setOpen] = useState(false);
  return (
    <div className="-mx-3 mt-1 border-t">
      <button type="button" aria-expanded={open} data-testid="whats-working-toggle" onClick={() => setOpen(o => !o)}
        title="Where your money comes from and where it leaks, real beside paper"
        className="flex min-h-11 w-full items-center gap-2 px-3 py-1 text-left text-xs hover:bg-secondary sm:min-h-7">
        <span className="min-w-0 flex-1 text-foreground/90">What&apos;s working</span>
        <span aria-hidden className="text-muted-foreground">{open ? "▾" : "▸"}</span>
      </button>
      {open && <WhatsWorkingView />}
    </div>
  );
}

/** The real ticket's paper record for the order being built (its option type, entered now): null until read or none. */
export function usePaperRecord(optionType: "call" | "put" | null): PaperRecord | null {
  const [record, setRecord] = useState<PaperRecord | null>(null);
  useEffect(() => {
    if (!optionType) return;
    const controller = new AbortController();
    readJson<{ record: PaperRecord | null }>(`/copilot/desk/whats-working/record?option_type=${optionType}`, controller.signal)
      .then(found => setRecord(found.record)).catch(() => undefined);  // informational only: no line when unread
    return () => controller.abort();
  }, [optionType]);
  return optionType ? record : null;
}
