"use client";

import { useEffect, useState } from "react";
import { Crosshair } from "lucide-react";
import DockSection from "./DockSection";
import type { PanelActions } from "@/components/copilot/CopilotPanel";
import { PLAN_BUTTON } from "@/components/copilot/PlanATrade";
import { PlanLine, stopText } from "@/components/dashboard/PlansCard";
import { pnlTone } from "@/components/dashboard/DashboardCard";
import { getSymbolLoop, type PlanBoardLevel, type PlanBoardRow, type SymbolLoop } from "@/lib/copilot";
import { money } from "@/lib/format";

const REFRESH_MS = 60_000;
const nyTime = (iso: string) => new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

function Level({ name, level }: { name: string; level: PlanBoardLevel | null }) {
  if (!level) return null;
  if (level.state === "hit") return <span className="text-amber-300">{name} {level.price.toFixed(2)} · hit</span>;
  return <span>{name} {level.price.toFixed(2)}{level.distance_pct !== undefined && <span className="text-slate-500"> · {Math.abs(level.distance_pct).toFixed(1)}% away</span>}</span>;
}

/**
 * The Charts dock's Copilot tab, above the conversation, for the chart's symbol only (``GET /copilot/symbol/{symbol}``):
 * its open position with the plan it was entered under, its armed plans, and one line of what is new on it. A row opens
 * in the panel itself (the position review, the plan's investigation, a conversation about the new item), never a
 * page change. Each section is a dock section, folded per device; an empty one is left out. "Plan a trade" fills the
 * panel's box with what the chart shows (``context``, read at the press). Read every minute while the tab is open.
 */
export default function CopilotLoop({ symbol, narrow, actions, context }: {
  symbol: string; narrow: boolean; actions: PanelActions; context(): string;
}) {
  const [loop, setLoop] = useState<SymbolLoop | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      const signal = controller.signal;
      getSymbolLoop(symbol, signal).then(next => { setLoop(next); setError(false); }).catch(() => { if (!signal.aborted) setError(true); });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    const shown = () => { if (document.visibilityState === "visible") read(); };
    document.addEventListener("visibilitychange", shown);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", shown); };
  }, [symbol]);

  const row = `w-full rounded border border-slate-700/70 px-2 py-1.5 text-left text-xs hover:bg-slate-800/60 disabled:opacity-50 ${narrow ? "min-h-11" : ""}`;
  const positions = loop?.positions.state === "ok" ? loop.positions.rows : [];
  const plans: PlanBoardRow[] = loop?.plans.state === "ok" ? loop.plans.rows : [];
  const radar = loop?.new.radar.state === "ok" ? loop.new.radar : null;
  const thesis = loop?.new.thesis.state === "ok" ? loop.new.thesis : null;
  // The newest of the two kinds, as one line.
  const event = radar?.rows[0], trigger = thesis?.rows[0];
  const newest = event && (!trigger?.fired_at || Date.parse(event.first_seen_at) >= Date.parse(trigger.fired_at))
    ? { text: `Radar ${nyTime(event.first_seen_at)}: ${event.summary ?? "event"}`, origin: { kind: "radar_event" as const, ref: event.event_id } }
    : trigger ? { text: `Thesis watch${trigger.fired_at ? ` ${nyTime(trigger.fired_at)}` : ""}: ${trigger.text}`, origin: { kind: "thesis_watch" as const, ref: null } } : null;
  const fresh = (radar?.count ?? 0) + (thesis?.count ?? 0);
  const missing = loop ? [loop.positions.state === "unavailable" && "positions", loop.plans.state === "unavailable" && "plans",
    (loop.new.radar.state === "unavailable" || loop.new.thesis.state === "unavailable") && "what's new"].filter(Boolean) : [];
  const urgent = positions.some(p => p.giveback === "fired" || p.plan?.invalidation?.state === "hit");

  return <div data-testid="copilot-loop" className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" disabled={actions.busy} onClick={() => actions.start(context(), { kind: "chart", ref: null })}
        title="Plan a trade on this chart: its interval, last price and nearest automatic levels go in the box. Nothing is sent until you press Send."
        className={`${PLAN_BUTTON} disabled:opacity-50 ${narrow ? "h-11" : "h-7"}`}><Crosshair size={13} aria-hidden />Plan a trade</button>
      {error && <span role="status" className="text-[11px] text-amber-300">{loop ? "Not refreshed" : `${symbol}'s positions and plans could not load`}</span>}
      {!error && missing.length > 0 && <span role="status" className="text-[11px] text-amber-300">Not read just now: {missing.join(", ")}</span>}
      {!error && loop?.quote_issue && <span className="text-[11px] text-amber-300">Prices: {loop.quote_issue}</span>}
    </div>
    {(positions.length > 0 || plans.length > 0 || !!newest) && <div className="overflow-hidden rounded border border-slate-700/70 [&>section:first-child]:border-t-0">
      {positions.length > 0 && <DockSection name="copilot-position" ariaLabel={`${symbol} open position`} title={positions.length > 1 ? "Positions" : "Position"}
        count={positions.length} defaultOpen forceOpen={urgent} narrow={narrow}>
        <ul className="space-y-1.5">{positions.map(p => <li key={p.trade_id}>
          <button type="button" disabled={actions.busy} onClick={() => actions.start(`Review this position: ${p.trade_id}`)} aria-label={`Review ${p.contract}`} className={row}>
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="min-w-0 truncate font-medium text-slate-100">{p.quantity > 1 ? `${p.quantity}× ` : ""}{p.contract}</span>
              <span className={`ml-auto shrink-0 tabular-nums ${pnlTone(p.unrealized_usd)}`}>
                {money(p.unrealized_usd, { signed: true, cents: false })}{p.unrealized_pct != null && ` · ${p.unrealized_pct > 0 ? "+" : ""}${p.unrealized_pct.toFixed(0)}%`}
              </span>
            </span>
            <span className="mt-0.5 flex flex-wrap gap-x-2 tabular-nums text-slate-300"><PlanLine row={p} /></span>
            {(p.plan?.time_stop || p.giveback) && <span className="mt-0.5 flex flex-wrap gap-x-2 tabular-nums text-slate-400">
              {p.plan?.time_stop && <span>{stopText(p.plan.time_stop)}</span>}
              {p.giveback && <span className={p.giveback === "fired" ? "text-amber-300" : undefined}>Give-back {p.giveback}</span>}
            </span>}
          </button>
        </li>)}</ul>
      </DockSection>}
      {plans.length > 0 && <DockSection name="copilot-plans" ariaLabel={`${symbol} armed plans`} title="Armed plans" count={plans.length} defaultOpen={false} narrow={narrow}>
        <ul className="space-y-1.5">{plans.map(p => <li key={p.investigation_id}>
          <button type="button" disabled={actions.busy} onClick={() => actions.open(p.investigation_id)} aria-label={`Open the ${symbol} plan${p.direction ? ` (${p.direction})` : ""}`} className={row}>
            <span className="flex flex-wrap gap-x-2 tabular-nums text-slate-300">
              {p.direction && <span className="font-medium capitalize text-slate-100">{p.direction}</span>}
              <Level name="Entry" level={p.entry} /><Level name="Invalidation" level={p.invalidation} />
              {p.time_stop?.state === "pending" && <span className="text-slate-400">{p.time_stop.text}</span>}
            </span>
            {p.thesis && <span className="mt-0.5 block truncate text-slate-500">{p.thesis}</span>}
          </button>
        </li>)}</ul>
      </DockSection>}
      {newest && <DockSection name="copilot-new" ariaLabel={`New on ${symbol} since you looked`} title="New since you looked" count={fresh} defaultOpen narrow={narrow}>
        <button type="button" disabled={actions.busy} onClick={() => actions.start(newest.text, newest.origin)} title="Ask the copilot about it here" className={row}>
          <span className="line-clamp-2 text-slate-300">{newest.text}</span>
        </button>
      </DockSection>}
    </div>}
  </div>;
}
