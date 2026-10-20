"use client";
import { useEffect, useState } from "react";
import { getPlans, type PlanDelivery, type PlansView, type PlanState, type PlanView } from "@/lib/conditionalPlans";

const zone = "America/New_York";
const clock = (value: string | number) => new Date(typeof value === "number" ? value * 1000 : value).toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit", second: "2-digit" }) + " ET";
const minute = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" });
const ago = (from: string, to: string) => { const s = Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000)); return s < 120 ? `${s} s ago` : `${Math.round(s / 60)} min ago`; };
const button = "inline-flex min-h-11 items-center justify-center rounded-md border px-3 text-sm hover:bg-secondary disabled:opacity-50";
const ACTIVE: PlanState[] = ["pending_activation", "watching", "triggered"];
const warn = "border-amber-500/40 bg-amber-500/10 text-amber-200";
const good = "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
const muted = "border-border bg-secondary/40 text-muted-foreground";

/** Short badge; never says watching unless a fresh heartbeat acknowledges it. */
function badge(p: PlanView): [string, string] {
  switch (p.state) {
    case "pending_activation": return ["Saved · not monitored yet", warn];
    case "watching": return p.monitoring ? ["Watching", good] : ["Not monitored · monitor not reporting", warn];
    case "triggered": return p.monitoring ? ["Triggered · not entered", good] : ["Triggered · not entered · monitor not reporting", warn];
    case "unavailable": return ["Monitoring failed · not watched", warn];
    case "invalidated": return ["Invalidated", muted];
    case "expired": return ["Expired", muted];
    case "cancelled": return ["Cancelled", muted];
  }
}

const reasons: Record<string, string> = {
  monitor_accepted: "The app monitor accepted fresh price evidence and started checking closes.",
  confirmed_closes: "The confirming closes were seen.",
  invalidation_close: "A completed close crossed the invalidation level.",
  monitoring_window_ended: "The watch reached its expiry time.",
  owner_cancelled: "Cancelled on request.",
  monitor_disabled: "Cancelled because the monitor was switched off.",
  ticker_removed: "Cancelled because the ticker was removed from your scanner list.",
  verified_session_unavailable: "Stopped: no verified open regular session.",
  stale_source: "Stopped: the price source was stale.",
  stale_bars: "Stopped: no recent completed minute bars.",
  invalid_bar: "Stopped: a malformed minute bar was received.",
  duplicate_bars: "Stopped: duplicate minute bars were received.",
  missing_minute: "Stopped: a minute bar was missing.",
  monitoring_gap: "Stopped: a gap of more than three minutes in evidence.",
  source_unavailable: "Stopped: the price source could not be read.",
};

const outcome: Record<PlanDelivery["outcome"], string> = {
  sent: "Sent to ntfy (your phone showing it is not confirmed)",
  failed: "Failed",
  unknown: "Unknown: it may have gone out; it will not be resent",
  not_sent: "Not sent",
};
const stateName: Record<PlanState, string> = { pending_activation: "Saved", watching: "Watching", triggered: "Triggered",
  invalidated: "Invalidated", expired: "Expired", cancelled: "Cancelled", unavailable: "Monitoring failed" };

function Banner({ v }: { v: PlansView }) {
  const r = v.readiness;
  let tone = warn, title: string, detail: string;
  if (!v.enabled || !v.configured) {
    title = "Price watches are off";
    detail = "Jo cannot accept a watch and nothing below is being monitored. "
      + (!v.configured ? "The market-watch exchange is not configured." : !v.app_flag ? "The conditional-plan switch is off." : "Stock awareness is off, which this needs.");
  } else if (r.heartbeat !== "fresh" || !r.monitor_enabled) {
    title = "Monitor not reporting";
    detail = (r.heartbeat_at ? `Last heartbeat ${clock(r.heartbeat_at)} (${ago(r.heartbeat_at, v.checked_at)}). ` : "No heartbeat has been recorded. ")
      + "Nothing is being watched right now, and Jo will refuse new watches.";
  } else if (!r.session_open_now) {
    title = "Monitor running · market closed";
    detail = "Jo will refuse new watches until the regular session opens.";
    tone = muted;
  } else {
    title = "Monitor running";
    detail = `Heartbeat ${clock(r.heartbeat_at!)}. Session closes ${clock(r.session_close_at!)}.`;
    tone = good;
  }
  return <section aria-label="Monitor status" data-testid="plan-monitor" className={`space-y-1 rounded-lg border p-4 ${tone}`}>
    <p className="font-medium">{title}</p>
    <p className="text-sm">{detail}</p>
    {v.enabled && v.configured && r.symbols && <p className="text-sm">Eligible tickers: {r.symbols.length ? r.symbols.join(", ") : "none selected"} · {v.plans_today ?? 0} of {v.max_daily_plans} watches saved today</p>}
  </section>;
}

function Rule({ p }: { p: PlanView }) {
  const [above, below] = p.direction === "long" ? ["above", "below"] : ["below", "above"];
  const closes = p.confirm_bars === 1 ? "1 completed 1-minute close" : `${p.confirm_bars} consecutive completed 1-minute closes`;
  return <p className="text-sm">Alert after {closes} {above} <strong>{p.trigger_price}</strong>. Ends on one close {below} <strong>{p.invalidation_price}</strong>. Expires {clock(p.expires_at)}.</p>;
}

function Plan({ p }: { p: PlanView }) {
  const [label, tone] = badge(p);
  const reason = p.reason && reasons[p.reason];
  return <li data-testid="plan-card" data-state={p.state} className="min-w-0 space-y-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold">{p.symbol} · {p.direction === "long" ? "Long" : "Short"} watch</h2>
      <span data-testid="plan-badge" className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>
    </div>
    <Rule p={p} />
    {p.state === "triggered" && <p className="text-sm text-amber-200">Triggered means the price condition was met. It does not mean you entered, and no order was placed. Invalidation is still checked until expiry.</p>}
    {p.state === "unavailable" && <p className="text-sm text-amber-200">The price condition is unknown; this is not a trade invalidation. A failed watch does not resume. Ask Jo for a new one if you still want it.</p>}
    {p.state === "pending_activation" && <p className="text-sm text-amber-200">{p.accepted_by_monitor ? "The monitor has the plan but has not yet accepted fresh price evidence." : "Jo saved this, but the app monitor has not picked it up."} Do not rely on it until it reads Watching.</p>}
    {reason && <p className="text-sm text-muted-foreground">{reason}{p.state_at ? ` ${clock(p.state_at)}.` : ""}</p>}
    {p.cancel_requested && p.state !== "cancelled" && <p className="text-sm text-muted-foreground">Cancellation requested; waiting for the monitor to confirm it.</p>}
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[9rem_1fr]">
      <dt className="text-muted-foreground">Monitoring</dt>
      <dd data-testid="plan-monitoring">{p.monitoring ? `Active · heartbeat ${clock(p.heartbeat_at!)}` : ACTIVE.includes(p.state) ? `Not active${p.heartbeat_at ? ` · last heartbeat ${clock(p.heartbeat_at)}` : ""}` : "Stopped"}</dd>
      <dt className="text-muted-foreground">Last evaluated bar</dt>
      <dd>{p.last_bar ? `${minute(p.last_bar.time)}–${minute(p.last_bar.end_time)} close ${p.last_bar.close} · ${p.last_bar.consecutive} of ${p.confirm_bars} confirming · checked ${clock(p.last_evaluated_at!)}` : "None yet"}</dd>
      <dt className="text-muted-foreground">Phone alerts</dt>
      <dd>{p.deliveries.length ? <ul className="space-y-1">{p.deliveries.map((d, i) => <li key={i}>{d.event_state ? stateName[d.event_state] : "Alert"} alert, attempt {d.attempt}: {outcome[d.outcome]}{d.error_code ? ` (${d.error_code})` : ""} · {clock(d.occurred_at)}</li>)}</ul> : "None sent yet"}</dd>
      <dt className="text-muted-foreground">Based on</dt>
      <dd>{p.source.kind === "check" ? "Jo's pre-trade check" : "Stock alert"} · price {p.source.price} observed {clock(p.source.observed_at)} · <code className="break-all text-xs">{p.source.id}</code></dd>
      <dt className="text-muted-foreground">Jo&apos;s reason</dt>
      <dd className="whitespace-pre-wrap">{p.rationale}</dd>
      <dt className="text-muted-foreground">Saved</dt>
      <dd>{new Date(p.created_at).toLocaleDateString("en-US", { timeZone: zone, month: "short", day: "numeric" })} {clock(p.created_at)} · <code className="break-all text-xs">{p.plan_id}</code></dd>
    </dl>
    {!!p.events.length && <details className="rounded-md border px-3">
      <summary className="min-h-11 cursor-pointer py-3 text-sm">History ({p.events.length})</summary>
      <ol className="space-y-1 pb-3 text-sm text-muted-foreground">{p.events.map((e) => <li key={e.state}>{clock(e.occurred_at)} · {stateName[e.state]} · {reasons[e.reason] ?? e.reason}{e.bar ? ` Close ${e.bar.close}.` : ""}</li>)}</ol>
    </details>}
  </li>;
}

export default function PlanWatches() {
  const [data, setData] = useState<PlansView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getPlans(controller.signal).then((v) => { setData(v); setError(null); })
      .catch((reason) => { if (!controller.signal.aborted) setError((reason as Error).message); });
    // Heartbeats age in seconds; reload often enough that "active" never outlives one.
    const timer = setInterval(() => setRefresh((r) => r + 1), 30_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [refresh]);
  const active = data?.plans.filter((p) => ACTIVE.includes(p.state)) ?? [];
  const ended = data?.plans.filter((p) => !ACTIVE.includes(p.state)) ?? [];
  return <div className="min-w-0 space-y-6 break-words" data-testid="plan-watches">
    <header className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs text-muted-foreground">Jo&apos;s follow-through</p><h1 className="text-xl font-semibold">Price watches</h1></div>
        <button type="button" onClick={() => setRefresh((r) => r + 1)} className={button}>Refresh</button>
      </div>
      <p className="text-sm text-muted-foreground">Numeric close conditions Jo saved for you. Advisory phone alerts only: no orders, no entries. Numeric candle closes, not chart-pattern recognition.</p>
    </header>
    {error && <p role="alert" className="text-sm text-amber-300">{error}{data && " Showing the previously loaded status; it may be out of date."}</p>}
    {!data && !error && <p role="status" className="text-sm text-muted-foreground">Loading price watches…</p>}
    {data && <>
      <Banner v={data} />
      <p className="text-sm text-muted-foreground">Alerts go to your phone as an ntfy push.{data.delivery.configured ? " ntfy accepting a push does not prove your phone showed it." : " ntfy is not configured on this server, so no phone alert can be sent."} When Jo can&apos;t accept a watch it is told why and should tell you; refused requests are not saved here.</p>
      <section aria-label="Active watches" className="space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Current ({active.length})</h2>
        {active.length ? <ul className="space-y-3">{active.map((p) => <Plan key={p.plan_id} p={p} />)}</ul> : <p className="text-sm text-muted-foreground">No current watches. Nothing is being monitored for you.</p>}
      </section>
      {!!ended.length && <section aria-label="Ended watches" className="space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Ended ({ended.length})</h2>
        <ul className="space-y-3">{ended.map((p) => <Plan key={p.plan_id} p={p} />)}</ul>
      </section>}
      <p className="text-xs text-muted-foreground">Checked {clock(data.checked_at)} · latest {data.limit} watches</p>
    </>}
  </div>;
}
