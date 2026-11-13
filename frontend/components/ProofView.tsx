"use client";
import Link from "next/link";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import { money } from "@/lib/format";
import { ALERT_FEEDBACK_LABELS } from "@/lib/alertFeedback";
import { DashboardCard, dashboardLink } from "./dashboard/DashboardCard";
import { ExitHabitsView, EXIT_HABIT_VERDICT, EXIT_HABIT_CAVEAT, RESPONSE, type ExitHabitsBody } from "./dashboard/ExitHabits";

// The two proofs from the October 22 end goal, read from /analytics/exit-habits and /radar/proof, and a secondary read
// (not a third proof), planned against unplanned trades, from /analytics/plan-proof.
// Every verdict defaults to "not enough data" and shows its rule and sample. See app/engine/radar_proof.py and plan_proof.py.
type Verdict = "helping" | "not_helping" | "not_enough_data";
export type RadarProof = { state: string; reason: string | null; rule_version?: string | null; sessions?: number; events?: number;
  alerted?: { events: number; ratings: Record<string, number> };
  /** Events a pre-trade plan names as its origin, and those whose plan was traded. */
  plans?: { planned: number; traded: number };
  stock_events?: number; group_events?: number; ratings?: Record<string, number>; movers?: Record<string, number>;
  median_lead_minutes?: number | null; brief?: Record<string, number>;
  /** Setup cards (radar_setup_paper.scorecard), one row per kind and direction; absent from an older backend. */
  setups?: SetupScore[] | null;
  verdict?: { verdict: Verdict; reason: string; rule: string; rated: number; timed: number; useful_share: number | null; ahead_share: number | null } };

export type SetupScore = { kind: string; direction: "up" | "down"; cards: number; with_contract: number; planned: number;
  paper_closed: number; paper_green: number; paper_pnl: number; unresolved: number };
const SETUP_NAME: Record<string, string> = { "dip_turn up": "Dip turning up", "dip_turn down": "Pop turning down",
  "gap_reversal up": "Gap down turning up", "gap_reversal down": "Gap up turning down" };
export const signedDollars = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v) >= 1000 ? `${(Math.abs(v) / 1000).toFixed(1)}k` : Math.round(Math.abs(v)).toLocaleString("en-US")}`;
/** "Dip turning up: 6 cards · 2 planned · paper 3 of 4 green, +$210", worded as the setup ping's record line. */
export function setupLine(row: SetupScore): string {
  const name = SETUP_NAME[`${row.kind} ${row.direction}`] ?? `${row.kind.replace(/_/g, " ")} ${row.direction}`;
  const paper = row.paper_closed ? `paper ${row.paper_green} of ${row.paper_closed} green, ${signedDollars(row.paper_pnl)}` : "no paper result yet";
  return `${name}: ${row.cards} card${row.cards === 1 ? "" : "s"} · ${row.planned} planned · ${paper}`;
}

type HabitTally = { n: number; trades: number; pct: number | null };
type PlanGroup = { key: "planned" | "unplanned" | "late"; label: string; in_verdict: boolean; trades: number; pnl: number;
  mean_return_pct: number | null; median_return_pct: number | null; win_rate: number | null; habits: Record<string, HabitTally> };
export type PlanProof = { go_live: string; trades: number; groups: PlanGroup[]; caveat: string;
  verdict: { verdict: Verdict; reason: string; rule: string; planned: number; unplanned: number; caveat: string } };

export const VERDICT: Record<Verdict, { label: string; tone: string }> = {
  helping: { label: "Helping", tone: "bg-secondary text-foreground" },
  not_helping: { label: "Not helping", tone: "bg-primary/15 text-primary" },
  not_enough_data: { label: "Not enough data", tone: "bg-secondary text-muted-foreground" },
};
const RATING: [string, string][] = [["useful", "Useful"], ["already_knew", "Already knew"], ["too_late", "Too late"], ["irrelevant", "Irrelevant"], ["unrated", "Not rated"]];
const MOVERS: [string, string][] = [["radar_first", "Radar first"], ["not_in_movers", "Never in Movers top 10"],
  ["movers_first", "Movers had it first or same minute"], ["unavailable", "Quotes no longer kept"]];
const BRIEF: [string, string][] = [["radar_first", "Radar first"], ["brief_first", "Brief had it first"], ["not_in_brief", "Not in a brief within 5 days"]];
const share = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v * 100)}%`;

export function useJson<T>(path: string) {
  const [body, setBody] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(apiUrl(path), { cache: "no-store", signal: controller.signal })
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then(data => { setBody(data); setCheckedAt(Date.now()); })
      .catch(() => { if (!controller.signal.aborted) { setError(true); setCheckedAt(Date.now()); } });
    return () => controller.abort();
  }, [path]);
  return { body, error, checkedAt };
}

// The answer first: chip and verdict sentence large and bright. The sample, rule and caveat (all kept, none hidden)
// follow together in small muted text.
function VerdictHead({ tone, label, reason }: { tone: string; label: string; reason: string }) {
  return <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
    <span className={`inline-flex h-7 items-center rounded-md px-2.5 text-[13px] font-semibold ${tone}`}>{label}</span>
    <span className="text-base font-semibold leading-snug text-foreground">{reason}</span>
  </div>;
}

function VerdictBlock({ verdict, reason, sample, rule, testId, label, caveat, caveatTestId }: { verdict: Verdict; reason: string; sample: string; rule: string;
  testId: string; label?: string; caveat?: string; caveatTestId?: string }) {
  const v = VERDICT[verdict];
  return <div className="space-y-2" data-testid={testId}>
    <VerdictHead tone={v.tone} label={label ?? v.label} reason={reason} />
    <div className="space-y-1 text-xs text-muted-foreground">
      <p>Sample: {sample}</p>
      <p>Rule: {rule}</p>
      {caveat && <p data-testid={caveatTestId}>{caveat}</p>}
    </div>
  </div>;
}

function Counts({ title, rows, counts }: { title: string; rows: [string, string][]; counts: Record<string, number> }) {
  return <div className="space-y-1">
    <h3 className="text-[13.5px] font-semibold tracking-tight">{title}</h3>
    <ul className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-2">{rows.map(([key, label]) =>
      <li key={key} className="flex justify-between gap-3 text-xs"><span className="text-muted-foreground">{label}</span><span className="tabular-nums">{counts[key] ?? 0}</span></li>)}</ul>
  </div>;
}

const BEFORE_AFTER_KIND: Record<string, string> = { giveback: "Gave back its gain", hold_hour: "Held an hour", expiry_first: "Expires today (90 min left)" };

function BeforeAfter({ data, goLive }: { data: NonNullable<ExitHabitsBody["before_after"]>; goLive: string }) {
  const cell = (n: number, of: number, pct: number | null) => of ? <><span className="font-medium">{share(pct)}</span> <span className="whitespace-nowrap text-muted-foreground">· {n} of {of}</span></> : <span className="text-muted-foreground">none yet</span>;
  const leftOut = data.rows.reduce((sum, r) => sum + r.since.left_out, 0);
  return <div className="space-y-1.5" data-testid="proof-alert-before-after">
    <h3 className="text-[13.5px] font-semibold tracking-tight">Acted within 15 minutes: before alerts and since</h3>
    <table className="w-full text-xs">
      <thead><tr className="text-left text-muted-foreground"><th className="py-0.5 font-normal">Moment</th><th className="py-0.5 font-normal">Before alerts</th><th className="py-0.5 font-normal">Since {new Date(`${goLive}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}</th></tr></thead>
      <tbody>{data.rows.map(r => <tr key={r.kind} data-testid={`before-after-${r.kind}`} className="border-t border-border/50">
        <td className="py-1 pr-2 text-muted-foreground">{BEFORE_AFTER_KIND[r.kind] ?? r.kind.replace(/_/g, " ")}</td>
        <td className="py-1 pr-2 tabular-nums">{cell(r.before.n, r.before.of, r.before.pct)}</td>
        <td className="py-1 tabular-nums">{cell(r.since.n, r.since.of, r.since.pct)}</td>
      </tr>)}</tbody>
    </table>
    <p className="text-xs text-muted-foreground">Closed or trimmed within 15 minutes of the moment. Before: every closed option trade from Jul 2025 to Oct 19, 2026
      where that moment came, from a frozen study ({data.source}). Since: alerts actually sent, once the position settled{leftOut ? `; ${leftOut} still open, rolled or unmatched left out` : ""}.
      A difference does not show that the alerts caused it.</p>
  </div>;
}

function Status({ error, what }: { error: boolean; what: string }) {
  return <p role="status" className={`text-sm ${error ? "text-red-400" : "text-muted-foreground"}`}>{error ? `${what} could not load.` : `Loading ${what.toLowerCase()}…`}</p>;
}

function AlertsProof() {
  const { body, error } = useJson<ExitHabitsBody>("/analytics/exit-habits");
  return <DashboardCard title="Exit habits and alert follow-up" action={<Link href="/analytics" className={dashboardLink}>Analytics →</Link>}>
    {body ? <div className="space-y-4">
      <VerdictBlock testId="proof-alerts-verdict" label={EXIT_HABIT_VERDICT[body.verdict.verdict].label} verdict={body.verdict.verdict} reason={body.verdict.reason} rule={body.verdict.rule}
        sample={`${body.verdict.sample} of the last ${body.window} trades since ${body.go_live} vs ${body.baseline_trades} before`} caveat={EXIT_HABIT_CAVEAT} />
      {body.feedback && <div className="space-y-2" data-testid="proof-alert-feedback">
        <Counts title="Your alert feedback" rows={[...Object.entries(ALERT_FEEDBACK_LABELS), ["unanswered", "Unanswered"]]}
          counts={{ ...body.feedback.counts, unanswered: body.feedback.unanswered }} />
        <p className="text-xs">{body.feedback.responded} of {body.feedback.total} alerts have feedback.</p>
        <p className="text-xs text-muted-foreground">All recorded sent or delivery-unconfirmed position alerts. Unanswered does not mean unseen or unhelpful.
          Self-reported usefulness, not evidence of higher returns. Open a recent alert below to respond.</p>
      </div>}
      <Counts title={`What you did after ${body.alerts_total} alert${body.alerts_total === 1 ? "" : "s"}`}
        rows={[...Object.entries(RESPONSE), ["unmatched", "Not matched to fills"]]} counts={body.responses} />
      {body.before_after && <BeforeAfter data={body.before_after} goLive={body.go_live} />}
      <div className="border-t pt-3"><ExitHabitsView body={body} alertsShown={5} /></div>
    </div> : <Status error={error} what="Alert follow-up" />}
  </DashboardCard>;
}

function RadarProofCard() {
  const { body, error } = useJson<RadarProof>("/radar/proof");
  return <><RadarVerdictCard body={body} error={error} />{(!body || body.setups !== undefined) && <RadarSetupsCard body={body} error={error} />}</>;
}

// Setup cards have no verdict rule: the chip says so, and the counts follow. Paper results are a record, not proof.
function RadarSetupsCard({ body, error }: { body: RadarProof | null; error: boolean }) {
  const rows = body?.setups ?? [];
  const sum = (key: "paper_closed" | "paper_green" | "paper_pnl" | "cards" | "unresolved") => rows.reduce((n, r) => n + r[key], 0);
  const closed = sum("paper_closed"), cards = sum("cards"), unresolved = sum("unresolved");
  return <DashboardCard title="Radar setup cards">
    {!body ? <Status error={error} what="Setup cards" />
      : body.setups == null ? <p className="text-sm text-muted-foreground">Setup cards could not be read right now.</p>
      : <div className="space-y-3" data-testid="proof-radar-setups">
        <VerdictHead tone={VERDICT.not_enough_data.tone} label="Record only"
          reason={cards ? `${cards} card${cards === 1 ? "" : "s"}; paper ${closed ? `${sum("paper_green")} of ${closed} green, ${signedDollars(sum("paper_pnl"))}` : "has no closed result yet"}.` : "No setup cards yet."} />
        {rows.length > 0 && <ul className="space-y-0.5 text-sm">{rows.map(r => <li key={`${r.kind}-${r.direction}`} data-testid="proof-setup-line" className="break-words">{setupLine(r)}</li>)}</ul>}
        <p className="text-xs text-muted-foreground">Paper: one contract, ask in and bid out, $0.65 a side, out at the invalidation, after 60 minutes or 5 minutes before the close.
          {unresolved > 0 && ` ${unresolved} unresolved (no contract or no fresh quote).`} Not part of the Radar verdict; there is no verdict rule for setups yet.</p>
      </div>}
  </DashboardCard>;
}

function RadarVerdictCard({ body, error }: { body: RadarProof | null; error: boolean }) {
  return <DashboardCard title="Does Radar find what you'd miss, early enough?" action={<Link href="/radar" className={dashboardLink}>Open Radar →</Link>}>
    {!body ? <Status error={error} what="Radar proof" />
      : !body.verdict ? <div data-testid="proof-radar-verdict">
        <VerdictHead tone={VERDICT.not_enough_data.tone} label={VERDICT.not_enough_data.label} reason={body.reason ?? "Radar is off."} />
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
  return <DashboardCard title="Do planned trades do better?" action={<Link href="/dashboard" className={dashboardLink}>Dashboard →</Link>}>
    {body ? <div className="space-y-3">
      <p className="text-xs text-muted-foreground">A secondary read, not a third proof.</p>
      <VerdictBlock testId="proof-planning-verdict" verdict={body.verdict.verdict} reason={body.verdict.reason} rule={body.verdict.rule}
        sample={`${body.verdict.planned} planned vs ${body.verdict.unplanned} unplanned closed long options since ${body.go_live}; ${late} with a late plan, not counted`} caveat={body.caveat} caveatTestId="proof-planning-caveat" />
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

type OutcomeKind = { count: number; complete: number; held: number; median_d1_pct: number | null; d1_measured: number;
  actions: Record<string, number>; alt_usd_total: number | null; alt_usd_n: number };
type Outcomes = { since: string; summary: Record<string, OutcomeKind>; note: string };
const OUTCOME_KINDS: [string, string][] = [["ping", "Phone pings"], ["plan", "Plans"], ["radar_event", "Radar events"],
  ["research", "Jo research"], ["shadow_decision", "Shadow decisions"]];

// What followed each output (app/engine/outcomes.py), per kind: no verdict, only counts and the underlying's path.
function OutcomesCard() {
  const { body, error } = useJson<Outcomes>("/analytics/outcomes");
  const kinds = body ? OUTCOME_KINDS.filter(([key]) => body.summary[key]) : [];
  return <DashboardCard title="Outcomes">
    {body ? <div className="space-y-3">
      <p className="text-sm" data-testid="proof-outcomes-caveat">Counts and price paths, not causation.</p>
      {kinds.length ? <div className="overflow-x-auto"><table className="w-full text-xs tabular-nums" data-testid="proof-outcomes">
        <thead className="border-b text-left text-xs font-medium text-muted-foreground"><tr>
          <th className="py-1 pr-3 font-medium">Since {body.since}</th><th className="py-1 pr-3 font-medium">Count</th>
          <th className="py-1 pr-3 font-medium">Median +1d</th><th className="py-1 pr-3 font-medium">What you did</th>
          <th className="py-1 font-medium">Vs alternative</th></tr></thead>
        <tbody className="divide-y">{kinds.map(([key, label]) => { const k = body.summary[key];
          return <tr key={key} data-testid={`outcome-kind-${key}`}>
            <td className="py-1.5 pr-3">{label}</td>
            <td className="py-1.5 pr-3">{k.count}{k.complete < k.count && <span className="text-muted-foreground"> ({k.count - k.complete} open)</span>}
              {k.held > 0 && <span className="text-muted-foreground"> · {k.held} held</span>}</td>
            <td className="py-1.5 pr-3">{points(k.median_d1_pct)}{k.d1_measured > 0 && <span className="text-muted-foreground"> of {k.d1_measured}</span>}</td>
            <td className="py-1.5 pr-3">{Object.entries(k.actions).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([a, n]) => `${a} ${n}`).join(" · ")}</td>
            <td className="py-1.5">{k.alt_usd_total == null ? "—" : money(k.alt_usd_total, { signed: true, cents: false })}</td>
          </tr>; })}</tbody>
      </table></div> : <p className="text-sm text-muted-foreground">No outcomes recorded yet; the sync pipeline fills them in.</p>}
      <p className="text-xs text-muted-foreground">Median +1d is the underlying&apos;s change to the next session&apos;s close. Vs alternative: pings against
        closing at the alert&apos;s midpoint mark; Radar, one share taken at first sight in its direction, against SPY to the session&apos;s close.</p>
    </div> : <Status error={error} what="Outcomes" />}
  </DashboardCard>;
}

export default function ProofView() {
  return <div className="space-y-4"><AlertsProof /><RadarProofCard /><PlanningProofCard /><OutcomesCard /></div>;
}
