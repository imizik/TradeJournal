"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import PlanATrade, { PLAN_BUTTON } from "@/components/copilot/PlanATrade";
import { getPlansBoard, type PlanBoardLevel, type PlanBoardRow, type PlansBoard as Board } from "@/lib/copilot";
import { cn } from "@/lib/utils";

const REFRESH_MS = 60_000;
const ET = "America/New_York";
const day = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: ET });
const hhmm = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-GB", { timeZone: ET, hour: "2-digit", minute: "2-digit" });
const md = (seconds: number) => new Date(seconds * 1000).toLocaleDateString("en-US", { timeZone: ET, month: "short", day: "numeric" });
/** "10:41" today, "Oct 23 10:41" another day (New York time). */
const when = (seconds: number) => day(seconds) === day(Date.now() / 1000) ? hhmm(seconds) : `${md(seconds)} ${hhmm(seconds)}`;
const signed = (value: number, text: string) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${text}`;

const POSITION: Record<PlanBoardRow["position"], { text: string; tone: string }> = {
  in_position: { text: "In position", tone: "bg-emerald-500/10 text-emerald-300" },
  fill_to_link: { text: "Fill to link", tone: "bg-amber-500/10 text-amber-300" },
  closed: { text: "Closed", tone: "bg-muted text-muted-foreground" },
  waiting: { text: "Waiting for entry", tone: "bg-muted text-muted-foreground" },
};
const STOP: Record<string, string> = { sent: "sent", skipped: "skipped", expired: "not sent", unknown: "may have sent", pending: "pending", sending: "sending" };

function Level({ name, level }: { name: string; level: PlanBoardLevel | null }) {
  if (!level) return null;
  const price = level.price.toFixed(2);
  if (level.state === "hit")
    return <span className="text-amber-300">{name} {price} · hit{level.hit_at ? ` at ${when(level.hit_at)}` : ""}</span>;
  return (
    <span>
      <span className="text-muted-foreground">{name}</span> <span className="text-foreground">{price}</span>
      {level.distance_pct !== undefined && level.distance_usd !== undefined && (
        <span className="text-muted-foreground"> {signed(level.distance_pct, `${Math.abs(level.distance_pct).toFixed(1)}%`)} ({signed(level.distance_usd, `$${Math.abs(level.distance_usd).toFixed(2)}`)})</span>
      )}
    </span>
  );
}

function Row({ plan, open }: { plan: PlanBoardRow; open(id: string): void }) {
  const position = POSITION[plan.position];
  const stop = plan.time_stop;
  return (
    <li>
      <Link href={`/copilot-lab?investigation=${plan.investigation_id}`} aria-label={`${plan.symbol} plan`}
        onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) { event.preventDefault(); open(plan.investigation_id); } }}
        className="block min-h-11 space-y-1 rounded border bg-background/40 px-3 py-2 hover:border-foreground/30">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold text-foreground">{plan.symbol}</span>
          {plan.direction && <span className="text-muted-foreground">{plan.direction}</span>}
          {plan.last !== null && <span className="tabular-nums text-muted-foreground">last {plan.last.toFixed(2)}</span>}
          <span className={cn("ml-auto rounded px-1.5 py-0.5 text-xs", position.tone)}>{position.text}</span>
        </div>
        {plan.thesis && <p className="truncate text-muted-foreground" title={plan.thesis}>{plan.thesis}</p>}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs tabular-nums">
          <Level name="Entry" level={plan.entry} />
          <Level name="Invalidation" level={plan.invalidation} />
          {stop && <span className="text-muted-foreground">Time stop {when(stop.due_at)}{stop.state === "pending" ? "" : ` · ${STOP[stop.state] ?? stop.state}`}</span>}
        </div>
      </Link>
    </li>
  );
}

/**
 * The lab home's Plans board: each confirmed copilot plan that is still armed (an entry or invalidation alert, a pending
 * time stop, or an open position linked to its plan), nearest to a trigger first, from ``GET /copilot/plans``. Refreshed
 * every minute while the page is visible. A row opens its investigation in place.
 */
export default function PlansBoard({ open }: { open(id: string): void }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      getPlansBoard(signal).then(next => { setBoard(next); setError(null); }).catch(failure => {
        if (!signal.aborted) setError(failure instanceof Error ? failure.message : "Plans are unavailable.");
      });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, []);

  return (
    <section aria-label="Plans" className="space-y-2 rounded border bg-card/40 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Plans</h2>
        {board?.plans.length ? <span className="text-xs text-muted-foreground">{board.plans.length} armed · nearest trigger first</span> : null}
        {board?.quote_issue && <span className="text-xs text-amber-300">Prices: {board.quote_issue}</span>}
        {board && error && <span className="text-xs text-amber-300">Not refreshed: {error}</span>}
      </div>
      {error && !board ? <p className="text-muted-foreground">Plans unavailable: {error}</p>
        : !board ? <p className="text-muted-foreground">Reading your plans…</p>
        : !board.plans.length ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-muted-foreground">No armed plans. Plan the next one before you enter.</p>
            <PlanATrade origin="copilot" className={`${PLAN_BUTTON} h-11 w-full sm:ml-auto sm:w-auto`} />
          </div>
        ) : (
          <ul className="space-y-2">
            {board.plans.map(plan => <Row key={plan.investigation_id} plan={plan} open={open} />)}
          </ul>
        )}
    </section>
  );
}
