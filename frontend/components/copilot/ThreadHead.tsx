"use client";

import { useEffect, useState, type ReactNode } from "react";
import PlanLadder, { daysTo } from "@/components/copilot/PlanLadder";
import { getThreadPlan, type DeskPosition, type DeskThreadPlan, type DeskThreadRef } from "@/lib/desk";
import type { PlanBoardRow } from "@/lib/copilot";
import { cn } from "@/lib/utils";

/*
 * The open thread's header on the Copilot desk: what state it is in, what it is (instrument, expiry or days held), the
 * symbol, the thesis on one line, and the price. An option shows its own mark and P&L, with the underlying's price
 * beneath, labelled, so the two are never read as one. Read-only; nothing here places, sizes or arms an order.
 */

const REFRESH_MS = 60_000;
const price = (value: number) => value.toFixed(2);
const pct = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
const expiryDay = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const WAITING: Record<PlanBoardRow["position"], string> = {
  waiting: "waiting for entry", fill_to_link: "a fill to link", closed: "position closed", in_position: "in position",
};

type Chip = { text: string; tone: string };

function chipOf(data: DeskThreadPlan | null, draft: boolean): Chip | null {
  if (draft) return { text: "Draft · not armed", tone: "bg-primary/10 text-primary" };
  if (!data) return null;
  if (data.position) return { text: "In position", tone: "bg-emerald-400/10 text-emerald-300" };
  const plan = data.plan;
  if (plan && ([plan.entry, plan.invalidation].some(level => level?.state === "armed") || plan.time_stop?.state === "pending"))
    return { text: "Armed", tone: "bg-sky-400/10 text-sky-300" };
  if (plan) return { text: plan.position === "closed" ? "Closed" : "Plan done", tone: "bg-secondary text-muted-foreground" };
  if (data.unavailable) return { text: "Plan unavailable", tone: "bg-secondary text-muted-foreground" };
  return { text: "Not planned", tone: "bg-secondary text-muted-foreground" };
}

function metaOf(data: DeskThreadPlan | null): string | null {
  const position = data?.position, plan = data?.plan;
  if (position?.instrument === "option" && position.option) {
    const { side, strike, expiry } = position.option, days = daysTo(expiry);
    return `${strike}${side === "put" ? "P" : "C"} · ${expiryDay(expiry)} · ${days <= 0 ? "expires today" : `${plural(days, "day")} left`}`;
  }
  if (position) return `Stock · ${!position.days_held ? "opened today" : `held ${plural(position.days_held, "day")}`}`;
  if (plan) return `${plan.direction ? `${plan.direction[0].toUpperCase()}${plan.direction.slice(1)} plan` : "Plan"} · ${WAITING[plan.position]}`;
  return data && !data.unavailable ? "No plan yet" : null;
}

/** The right-hand price block. An option's mark is per share here (the journal keeps it per contract). */
function PriceBlock({ symbol, position, plan }: { symbol: string; position: DeskPosition | null; plan: PlanBoardRow | null }) {
  const change = position?.unrealized_pct;
  const tone = change == null ? "" : change >= 0 ? "text-emerald-300" : "text-rose-300";
  if (position?.instrument === "option") {
    const mark = position.mark == null ? null : position.mark / 100;
    return (
      <div className="flex flex-col items-start gap-1 sm:items-end" data-testid="thread-price">
        <div className="flex items-baseline gap-2.5">
          <span className="text-xs text-muted-foreground">option mark</span>
          <span className="text-2xl font-medium tabular-nums tracking-tight">{mark == null ? "—" : price(mark)}</span>
          {change != null && <span className={cn("text-sm tabular-nums", tone)} title="Open P&L on the option, not the underlying's move">{pct(change)}</span>}
        </div>
        {plan?.last != null && (
          <span className="text-xs text-muted-foreground">{symbol} <span className="tabular-nums">{price(plan.last)}</span> · underlying</span>
        )}
      </div>
    );
  }
  if (position) return (
    <div className="flex flex-col items-start gap-1 sm:items-end" data-testid="thread-price">
      <div className="flex items-baseline gap-2.5">
        <span className="text-2xl font-medium tabular-nums tracking-tight">{position.mark == null ? "—" : price(position.mark)}</span>
        {change != null && <span className={cn("text-sm tabular-nums", tone)} title="Open P&L on the shares">{pct(change)}</span>}
      </div>
      {position.avg_entry != null && <span className="text-xs text-muted-foreground">Avg cost <span className="tabular-nums">{price(position.avg_entry)}</span></span>}
    </div>
  );
  if (plan?.last != null) return (
    <div className="flex items-baseline gap-2.5" data-testid="thread-price">
      <span className="text-xs text-muted-foreground">last</span>
      <span className="text-2xl font-medium tabular-nums tracking-tight">{price(plan.last)}</span>
    </div>
  );
  return null;
}

/** The header alone, for a thread whose plan and position were already read. */
export function ThreadHead({ thread, data, draft = false }: { thread: DeskThreadRef; data: DeskThreadPlan | null; draft?: boolean }) {
  const chip = chipOf(data, draft), meta = metaOf(data);
  const symbol = thread.symbol ?? data?.plan?.symbol ?? thread.title;
  const thesis = data?.position?.plan?.thesis ?? data?.plan?.thesis ?? null;
  return (
    <header role="group" aria-label="Thread header" className="flex flex-wrap items-start gap-x-6 gap-y-3">
      <div className="flex min-w-0 flex-[1_1_18rem] flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {chip && <span className={cn("inline-flex h-5 items-center whitespace-nowrap rounded px-1.5 text-[11px] font-medium", chip.tone)}>{chip.text}</span>}
          {meta && <span>{meta}</span>}
        </div>
        <h2 className="text-3xl font-semibold leading-none tracking-tight text-foreground">{symbol}</h2>
        {thesis && <p className="max-w-[60ch] truncate text-sm text-muted-foreground" title={thesis}>{thesis}</p>}
      </div>
      {data && <div className="sm:pt-5"><PriceBlock symbol={symbol} position={data.position} plan={data.plan} /></div>}
    </header>
  );
}

/**
 * The top of the open thread: its header, and the plan ladder when it has a plan with an entry and an invalidation.
 * Reads ``GET /copilot/plans`` and ``GET /copilot/plans/positions`` when the thread opens or its activity changes, then
 * each minute while the page is visible. Nothing for a conversation across everything with no plan.
 */
export default function DeskThreadTop({ thread, draft = false, hero = null, compact = false }: {
  thread: DeskThreadRef | null; draft?: boolean; hero?: ReactNode; compact?: boolean;
}) {
  const [read, setRead] = useState<{ id: string; data: DeskThreadPlan } | null>(null);
  const id = thread?.id, symbol = thread?.symbol ?? null, refreshKey = thread?.refreshKey;
  useEffect(() => {
    if (!id) return;
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      getThreadPlan({ id, symbol }, signal).then(data => { if (!signal.aborted) setRead({ id, data }); }).catch(() => undefined);
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") load(); }, REFRESH_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [id, symbol, refreshKey]);

  if (!thread) return null;
  const data = read?.id === thread.id ? read.data : null;
  if (!thread.symbol && !data?.plan) return null;
  return (
    <div className="mb-4 space-y-4 border-b pb-4">
      <ThreadHead thread={thread} data={data} draft={draft} />
      {hero}
      {data?.plan && <PlanLadder plan={data.plan} position={data.position} dimmed={draft} compact={compact} />}
    </div>
  );
}
