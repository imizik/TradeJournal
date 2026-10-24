"use client";
import Link from "next/link";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { money } from "@/lib/format";
import { DashboardCard, dashboardLink } from "./DashboardCard";

// What happened after each phone alert, and the audit's four exit habits against the trades before the alerts.
// Counts only: no grades, and no trend language while there are fewer than 30 trades. See backend/app/engine/exit_habits.py.
type Group = { n: number; trades: number; excluded: number; pct: number | null; pnl: number };
type Habit = { key: string; label: string; recent: Group; baseline: Group };
type Alert = { id: string; kind: string; contract: string; contracts: number; detected_at: number; trade_id: string | null;
  response: string | null; vs_alert: number | null; note: string | null };
type ExitHabitsBody = { go_live: string; window: number; since_go_live: number; recent_trades: number; baseline_trades: number;
  habits: Habit[]; alerts: Alert[] };

const KIND: Record<string, string> = { giveback: "Gave back its gain", expiry_first: "Expires today", expiry_final: "Last 30 minutes",
  hold_hour: "Held an hour" };
const RESPONSE: Record<string, string> = { closed_15m: "Closed within 15 min", trimmed_15m: "Trimmed within 15 min",
  closed_later: "Closed later that day", held_overnight: "Held overnight", expired: "Let it expire", still_open: "Still open" };
const ALERTS_SHOWN = 3;

const kindLabel = (kind: string) => KIND[kind] ?? kind.replace(/_/g, " ");
const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const time = (s: number) => new Date(s * 1000).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const pct = (v: number | null) => v == null ? "—" : `${Math.round(v * 100)}%`;

function Line({ name, group }: { name: string; group: Group }) {
  return <p className="flex flex-wrap justify-between gap-x-3 text-xs">
    <span className="text-muted-foreground">{name}</span>
    <span className="tabular-nums">{group.trades ? <>{group.n} of {group.trades} · {pct(group.pct)} · {money(group.pnl, { signed: true, cents: false })}
      {group.excluded > 0 && <span className="text-muted-foreground"> · {group.excluded} without data</span>}</>
      : group.excluded ? <span className="text-muted-foreground">{group.excluded} trades, no data</span> : "no trades"}</span>
  </p>;
}

function result(a: Alert) {
  if (a.vs_alert == null) return a.note ?? "No result.";
  const by = money(Math.abs(a.vs_alert), { cents: false });
  if (a.vs_alert > 0) return `You came out ${by} better than closing at the alert.`;
  if (a.vs_alert < 0) return `Closing at the alert would have been ${by} better.`;
  return "The same as closing at the alert.";
}

function ExitHabitsView({ body }: { body: ExitHabitsBody }) {
  const since = day(body.go_live);
  const recentName = body.recent_trades < body.window ? `Since ${since} (${body.recent_trades} of ${body.window} so far)` : `Last ${body.window}`;
  return <div className="min-w-0 space-y-3 break-words" data-testid="exit-habits">
    <p className="text-xs text-muted-foreground">Closed long options: {body.since_go_live} since phone alerts went live on {since}, against {body.baseline_trades} before.
      {body.recent_trades < body.window && " Too few trades yet to read a change; these are counts only."}</p>
    <ul className="space-y-2">{body.habits.map((h) => <li key={h.key} className="space-y-0.5" data-testid={`habit-${h.key}`}>
      <p className="text-sm">{h.label}</p>
      <Line name={recentName} group={h.recent} />
      <Line name={`Before ${since}`} group={h.baseline} />
    </li>)}</ul>
    <div className="border-t pt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recent alerts</h3>
      {body.alerts.length ? <ul className="divide-y divide-border">{body.alerts.slice(0, ALERTS_SHOWN).map((a) => <li key={a.id} className="space-y-0.5 py-2" data-testid="exit-habits-alert">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          {a.trade_id ? <Link href={`/trades/${a.trade_id}?alert=${encodeURIComponent(a.id)}`} className="text-sm font-medium text-primary hover:underline">{a.contract}</Link>
            : <span className="text-sm font-medium">{a.contract}</span>}
          <span className="text-xs text-muted-foreground">{kindLabel(a.kind)} · {time(a.detected_at)} ET</span>
        </div>
        <p className="text-xs">{a.response ? RESPONSE[a.response] ?? a.response.replace(/_/g, " ") : "Not matched to fills"}</p>
        <p className={`text-xs ${a.vs_alert == null ? "text-muted-foreground" : ""}`}>{result(a)}</p>
      </li>)}</ul> : <p className="py-2 text-sm text-muted-foreground">No phone alerts sent yet.</p>}
    </div>
  </div>;
}

export default function ExitHabits() {
  const [body, setBody] = useState<ExitHabitsBody | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl("/analytics/exit-habits"), { cache: "no-store", signal: controller.signal })
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(setBody).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  return <DashboardCard title="Exit habits" action={<Link href="/analytics" className={dashboardLink}>Analytics →</Link>}>
    {body ? <ExitHabitsView body={body} />
      : <p role="status" className={`text-sm ${error ? "text-amber-300" : "text-muted-foreground"}`}>{error ? "Exit habits could not load." : "Loading exit habits…"}</p>}
  </DashboardCard>;
}
