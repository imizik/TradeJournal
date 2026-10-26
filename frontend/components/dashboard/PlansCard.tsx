"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PlanATrade, { PLAN_BUTTON } from "@/components/copilot/PlanATrade";
import { useCopilotOn } from "@/components/copilot/useCopilotOn";
import { apiUrl } from "@/lib/api";
import { copilotLabHref } from "@/lib/copilot";
import { money } from "@/lib/format";
import { DashboardCard, pnlTone } from "./DashboardCard";

// Each open position beside the plan it was entered under, from GET /copilot/plans/positions
// (backend/app/engine/plan_positions.py). Owner-only, and only while the Copilot Lab is on.
type Invalidation = { price: number; condition: string; state: "armed" | "hit"; distance_usd?: number; distance_pct?: number; hit_at?: number | null };
type TimeStop = { text: string; due_at: number; clock: string; state: string; minutes_left?: number };
export type PlanPosition = {
  trade_id: string; symbol: string; contract: string; instrument: string; direction: string | null; quantity: number;
  unrealized_usd: number | null; unrealized_pct: number | null;
  giveback: "armed" | "fired" | "watching" | null; latest_alert: { kind: string; at: number } | null;
  plan: { setup: string; thesis: string | null; timing: "pre_entry" | "late" | "unverified"; invalidation: Invalidation | null; time_stop: TimeStop | null } | null;
  link_path: string | null; plan_path: string | null;
};
export type PlanPositions = { positions: PlanPosition[]; count: number; quotes_at: number | null; quote_issue: string | null;
  /** Phone pings the notification policy held today (New York), by kind label (backend notification_policy.held_back_today). */
  held_back_today?: { count: number; by_kind: Record<string, number> } };

/** "Held back today: 3 pings (2 plan nudge, 1 one-hour)". */
export function heldBackText(held: PlanPositions["held_back_today"]): string | null {
  if (!held || !held.count) return null;
  const kinds = Object.entries(held.by_kind).map(([kind, n]) => `${n} ${kind}`).join(", ");
  return `Held back today: ${held.count} ping${held.count === 1 ? "" : "s"}${kinds ? ` (${kinds})` : ""}`;
}

const REFRESH_MS = 60_000;
const ALERT: Record<string, string> = { giveback: "Gave back its gain", expiry_first: "Expires today", expiry_final: "Last 30 minutes", hold_hour: "Held an hour" };
const STOP: Record<string, string> = { sent: "sent", skipped: "skipped", expired: "not sent", unknown: "may have sent", sending: "sending" };
const hhmm = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });

export const reviewHref = (row: PlanPosition) => copilotLabHref(row.symbol, `Review this position: ${row.trade_id}`);

function stopText(stop: TimeStop) {
  if (stop.state === "pending") return `Time stop ${stop.clock} · ${stop.minutes_left ? `${stop.minutes_left} min` : "due now"}`;
  return `Time stop ${stop.clock} · ${STOP[stop.state] ?? stop.state}`;
}

function PlanLine({ row }: { row: PlanPosition }) {
  const plan = row.plan;
  if (!plan) return <span className="text-amber-300">No plan</span>;
  const level = plan.invalidation;
  return <>
    {level ? level.state === "hit"
      ? <span className="text-amber-300">Invalidation {level.price.toFixed(2)} · hit</span>
      : <span>Invalidation {level.price.toFixed(2)}{level.distance_pct !== undefined && <span className="text-muted-foreground"> · {Math.abs(level.distance_pct).toFixed(1)}% away</span>}</span>
      : <span className="text-muted-foreground">{plan.setup} · no invalidation</span>}
    {plan.timing === "late" && <span className="text-amber-300">planned late</span>}
  </>;
}

function Row({ row }: { row: PlanPosition }) {
  const action = row.link_path ? { href: row.link_path, text: "Link plan" } : row.plan_path ? { href: row.plan_path, text: "Plan it" } : null;
  const stop = row.plan?.time_stop;
  return <li className="flex min-w-0 items-stretch rounded border bg-background/40" data-testid="plans-card-row">
    <Link href={reviewHref(row)} aria-label={`Review ${row.contract}`} className="min-h-11 min-w-0 flex-1 space-y-1 px-3 py-2 hover:bg-muted/30">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="min-w-0 break-words text-sm font-medium">{row.quantity > 1 ? `${row.quantity}× ` : ""}{row.contract}</span>
        <span className={`ml-auto shrink-0 text-sm tabular-nums ${pnlTone(row.unrealized_usd)}`}>
          {money(row.unrealized_usd, { signed: true, cents: false })}{row.unrealized_pct != null && ` · ${row.unrealized_pct > 0 ? "+" : ""}${row.unrealized_pct.toFixed(0)}%`}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs tabular-nums"><PlanLine row={row} /></div>
      {(stop || row.giveback === "armed" || row.giveback === "fired" || row.latest_alert) && (
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
          {stop && <span>{stopText(stop)}</span>}
          {row.giveback === "fired" ? <span className="text-amber-300">Give-back fired</span> : row.giveback === "armed" ? <span>Give-back armed</span> : null}
          {row.latest_alert && row.latest_alert.kind !== "giveback" && <span>{ALERT[row.latest_alert.kind] ?? row.latest_alert.kind.replace(/_/g, " ")} {hhmm(row.latest_alert.at)}</span>}
        </div>
      )}
    </Link>
    {action && <Link href={action.href} className="flex min-h-11 shrink-0 items-center border-l px-3 text-xs font-medium text-sky-300 hover:bg-muted/30">{action.text}</Link>}
  </li>;
}

/**
 * The Dashboard's Plans card: one row per open position with its P&L and the plan it was entered under (invalidation
 * distance, time stop countdown, give-back watch). A row opens the position review in the Copilot Lab; "Plan it" and
 * "Link plan" open the plan deep link and the one-tap link page. Refreshed every minute while the page is visible.
 */
export default function PlansCard() {
  const on = useCopilotOn();
  const [body, setBody] = useState<PlanPositions | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on) return;
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      fetch(apiUrl("/copilot/plans/positions"), { cache: "no-store", signal })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`Request failed (${r.status}).`)))
        .then((next: PlanPositions) => { setBody(next); setError(null); })
        .catch(failure => { if (!signal.aborted) setError(failure instanceof Error ? failure.message : "Plans are unavailable."); });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, [on]);
  if (!on) return null;

  return <DashboardCard title="Plans" action={body && error ? <span className="text-xs text-amber-300">Not refreshed</span>
    : body?.quote_issue ? <span className="text-xs text-amber-300">Prices: {body.quote_issue}</span> : undefined}>
    <div data-testid="plans-card">
      {error && !body ? <p role="status" className="text-sm text-amber-300">Plans could not load: {error}</p>
        : !body ? <p role="status" className="text-sm text-muted-foreground">Reading your positions…</p>
        : !body.positions.length ? <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-muted-foreground">Nothing open.</p>
          <PlanATrade origin="dashboard" className={`${PLAN_BUTTON} h-11 w-full sm:ml-auto sm:w-auto`} />
        </div>
        : <ul className="grid min-w-0 gap-2 lg:grid-cols-2">{body.positions.map(row => <Row key={row.trade_id} row={row} />)}</ul>}
      {body && heldBackText(body.held_back_today) && <p data-testid="plans-card-held-back" className="mt-2 text-xs text-muted-foreground"
        title="Phone pings the notification policy did not send today: over the daily cap, or too soon after another ping for the same position.">{heldBackText(body.held_back_today)}</p>}
    </div>
  </DashboardCard>;
}
