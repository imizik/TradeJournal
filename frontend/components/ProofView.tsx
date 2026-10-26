"use client";
import Link from "next/link";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { money } from "@/lib/format";
import { DashboardCard, dashboardLink } from "./dashboard/DashboardCard";
import { ExitHabitsView, RESPONSE, type ExitHabitsBody } from "./dashboard/ExitHabits";

// The two proofs from the October 22 end goal, read from /analytics/exit-habits and /radar/proof, and a secondary read
// (not a third proof), planned against unplanned trades, from /analytics/plan-proof.
// Every verdict defaults to "not enough data" and shows its rule and sample. See app/engine/radar_proof.py and plan_proof.py.
type Verdict = "helping" | "not_helping" | "not_enough_data";
type RadarProof = { state: string; reason: string | null; rule_version?: string | null; sessions?: number; events?: number;
  alerted?: { events: number; ratings: Record<string, number> };
  /** Events a pre-trade plan names as its origin, and those whose plan was traded. */
  plans?: { planned: number; traded: number };
  stock_events?: number; group_events?: number; ratings?: Record<string, number>; movers?: Record<string, number>;
  median_lead_minutes?: number | null; brief?: Record<string, number>;
  verdict?: { verdict: Verdict; reason: string; rule: string; rated: number; timed: number; useful_share: number | null; ahead_share: number | null } };

type HabitTally = { n: number; trades: number; pct: number | null };
type PlanGroup = { key: "planned" | "unplanned" | "late"; label: string; in_verdict: boolean; trades: number; pnl: number;
  mean_return_pct: number | null; median_return_pct: number | null; win_rate: number | null; habits: Record<string, HabitTally> };
type PlanProof = { go_live: string; trades: number; groups: PlanGroup[]; caveat: string;
  verdict: { verdict: Verdict; reason: string; rule: string; planned: number; unplanned: number; caveat: string } };

const VERDICT: Record<Verdict, { label: string; tone: string }> = {
  helping: { label: "Helping", tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" },
  not_helping: { label: "Not helping", tone: "border-red-500/40 bg-red-500/10 text-red-300" },
  not_enough_data: { label: "Not enough data", tone: "border-border bg-muted text-muted-foreground" },
};
const RATING: [string, string][] = [["useful", "Useful"], ["already_knew", "Already knew"], ["too_late", "Too late"], ["irrelevant", "Irrelevant"], ["unrated", "Not rated"]];
const MOVERS: [string, string][] = [["radar_first", "Radar first"], ["not_in_movers", "Never in Movers top 10"],
  ["movers_first", "Movers had it first or same minute"], ["unavailable", "Quotes no longer kept"]];
const BRIEF: [string, string][] = [["radar_first", "Radar first"], ["brief_first", "Brief had it first"], ["not_in_brief", "Not in a brief within 5 days"]];
const share = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;

function useJson<T>(path: string) {
  const [body, setBody] = useState<T | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl(path), { cache: "no-store", signal: controller.signal })
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(setBody).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [path]);
  return { body, error };
}

function VerdictBlock({ verdict, reason, sample, rule, testId }: { verdict: Verdict; reason: string; sample: string; rule: string; testId: string }) {
  const v = VERDICT[verdict];
  return <div className="space-y-1.5" data-testid={testId}>
    <div className="flex flex-wrap items-center gap-2">
      <span className={`rounded-md border px-2 py-0.5 text-sm font-semibold ${v.tone}`}>{v.label}</span>
      <span className="text-sm">{reason}</span>
    </div>
    <p className="text-xs text-muted-foreground">Sample: {sample}</p>
    <p className="text-xs text-muted-foreground">Rule: {rule}</p>
  </div>;
}

function Counts({ title, rows, counts }: { title: string; rows: [string, string][]; counts: Record<string, number> }) {
  return <div className="space-y-1">
    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
    <ul className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-2">{rows.map(([key, label]) =>
      <li key={key} className="flex justify-between gap-3 text-xs"><span className="text-muted-foreground">{label}</span><span className="tabular-nums">{counts[key] ?? 0}</span></li>)}</ul>
  </div>;
}

function Status({ error, what }: { error: boolean; what: string }) {
  return <p role="status" className={`text-sm ${error ? "text-amber-300" : "text-muted-foreground"}`}>{error ? `${what} could not load.` : `Loading ${what.toLowerCase()}…`}</p>;
}

function AlertsProof() {
  const { body, error } = useJson<ExitHabitsBody>("/analytics/exit-habits");
  return <DashboardCard title="Do position alerts help you reconsider?" action={<Link href="/analytics" className={dashboardLink}>Analytics →</Link>}>
    {body ? <div className="space-y-4">
      <VerdictBlock testId="proof-alerts-verdict" verdict={body.verdict.verdict} reason={body.verdict.reason} rule={body.verdict.rule}
        sample={`${body.verdict.sample} of the last ${body.window} trades since ${body.go_live} vs ${body.baseline_trades} before`} />
      <Counts title={`What you did after ${body.alerts_total} alert${body.alerts_total === 1 ? "" : "s"}`}
        rows={[...Object.entries(RESPONSE), ["unmatched", "Not matched to fills"]]} counts={body.responses} />
      <div className="border-t pt-3"><ExitHabitsView body={body} alertsShown={5} /></div>
    </div> : <Status error={error} what="Alert follow-up" />}
  </DashboardCard>;
}

function RadarProofCard() {
  const { body, error } = useJson<RadarProof>("/radar/proof");
  return <DashboardCard title="Does Radar find what you'd miss, early enough?" action={<Link href="/radar" className={dashboardLink}>Open Radar →</Link>}>
    {!body ? <Status error={error} what="Radar proof" />
      : !body.verdict ? <div className="space-y-1.5" data-testid="proof-radar-verdict">
        <span className={`rounded-md border px-2 py-0.5 text-sm font-semibold ${VERDICT.not_enough_data.tone}`}>{VERDICT.not_enough_data.label}</span>
        <p className="text-sm text-muted-foreground">{body.reason ?? "Radar is off."}</p>
      </div>
      : <div className="space-y-4">
        <VerdictBlock testId="proof-radar-verdict" verdict={body.verdict.verdict} reason={body.verdict.reason} rule={body.verdict.rule}
          sample={`${body.verdict.rated} rated (${share(body.verdict.useful_share)} useful) · ${body.verdict.timed} timed stock events (${share(body.verdict.ahead_share)} ahead of Movers)`} />
        <p className="text-xs text-muted-foreground">{body.events} event{body.events === 1 ? "" : "s"} over {body.sessions} session{body.sessions === 1 ? "" : "s"} of {body.rule_version}: {body.stock_events} stock, {body.group_events} group (groups are rated, not timed).</p>
        <Counts title="Your ratings" rows={RATING} counts={body.ratings ?? {}} />
        {body.alerted && <p className="text-xs text-muted-foreground">Sent to your phone as Radar alerts: {body.alerted.events} ({body.alerted.ratings.useful ?? 0} rated useful). Shown apart from events only seen in the feed; not part of the verdict.</p>}
        {body.plans && <p className="text-xs text-muted-foreground">Led to a pre-trade plan: {body.plans.planned}; to a trade: {body.plans.traded}. Not part of the verdict.</p>}
        <Counts title="Stock events vs Movers top 10" rows={MOVERS} counts={body.movers ?? {}} />
        {body.median_lead_minutes != null && <p className="text-xs text-muted-foreground">When Radar was first, it led Movers by a median {body.median_lead_minutes} min.</p>}
        <Counts title="Stock events vs the morning brief" rows={BRIEF} counts={body.brief ?? {}} />
        <p className="text-xs text-muted-foreground">The brief names a handful of stocks a day, so it is shown but not part of the verdict.</p>
      </div>}
  </DashboardCard>;
}

const points = (v: number | null) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

function PlanningProofCard() {
  const { body, error } = useJson<PlanProof>("/analytics/plan-proof");
  const late = body?.groups.find((g) => g.key === "late")?.trades ?? 0;
  return <DashboardCard title="Do planned trades do better?" action={<Link href="/" className={dashboardLink}>Dashboard →</Link>}>
    {body ? <div className="space-y-3">
      <p className="text-xs text-muted-foreground">A secondary read, not a third proof.</p>
      <VerdictBlock testId="proof-planning-verdict" verdict={body.verdict.verdict} reason={body.verdict.reason} rule={body.verdict.rule}
        sample={`${body.verdict.planned} planned vs ${body.verdict.unplanned} unplanned closed long options since ${body.go_live}; ${late} with a late plan, not counted`} />
      <p className="text-xs text-amber-300" data-testid="proof-planning-caveat">{body.caveat}</p>
      <ul className="space-y-2">{body.groups.map((g) => <li key={g.key} className="space-y-0.5" data-testid={`plan-group-${g.key}`}>
        <p className="text-sm">{g.label}</p>
        <p className="flex flex-wrap gap-x-3 text-xs tabular-nums text-muted-foreground">
          <span>{g.trades} trade{g.trades === 1 ? "" : "s"}</span><span>{money(g.pnl, { signed: true, cents: false })}</span>
          <span>mean return {points(g.mean_return_pct)}</span><span>median {points(g.median_return_pct)}</span>
          <span>win rate {share(g.win_rate)}</span>
          <span>green to red {g.habits.green_to_red?.trades ? `${g.habits.green_to_red.n} of ${g.habits.green_to_red.trades}` : "—"}</span>
        </p>
      </li>)}</ul>
    </div> : <Status error={error} what="Planning read" />}
  </DashboardCard>;
}

export default function ProofView() {
  return <div className="space-y-4"><AlertsProof /><RadarProofCard /><PlanningProofCard /></div>;
}
