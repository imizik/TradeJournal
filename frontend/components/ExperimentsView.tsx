"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ChevronDown, RefreshCw } from "lucide-react";
import { useJson, type PlanProof, type RadarProof } from "./ProofView";
import { EXIT_HABIT_VERDICT, type ExitHabitsBody } from "./dashboard/ExitHabits";
import { ALERT_FEEDBACK_LABELS } from "@/lib/alertFeedback";
import { unavailable, type AnswerScorecard } from "@/lib/copilot";
import type { ShadowWeek } from "@/lib/shadowBook";
import { money } from "@/lib/format";

type Path = "alerts" | "radar" | "copilot" | "plans" | "shadow";
type Bar = { label: string; count: number; muted?: boolean };
type Entry = {
  id: Path; name: string; question: string; state: string; sample: string;
  period?: string; next: string; caveat: string; result?: string;
  chart?: { title: string; bars: Bar[] }; examples?: ReactNode;
  href: string; action: string; cost?: string;
};
const linkClass = "inline-flex min-h-11 items-center text-sm text-sky-300 hover:underline";
const names: Record<Path, [string, string, string, string]> = {
  alerts: ["Position alerts", "Did a reminder prompt a useful review?", "/proof", "Open alert feedback"],
  radar: ["Radar", "Did it find something worth investigating?", "/radar", "Rate Radar events"],
  copilot: ["Copilot answers", "Are the answers useful at an acceptable cost?", "/copilot-lab", "Open the Copilot desk"],
  plans: ["Plan before entry", "Do trades with a plan differ from those without one?", "/proof", "Open planning proof"],
  shadow: ["Copilot Shadow book", "Does the paper trader produce testable decisions?", "/radar", "Open the Shadow book"],
};

function entry(id: Path, error: boolean): Entry {
  const [name, question, href, action] = names[id];
  return { id, name, question, href, action, state: error ? "Unavailable" : "Loading", sample: "—",
    next: error ? "Refresh to try this source again. Its data is unavailable, not zero." : "Reading the existing scorecard…",
    caveat: "Historical records do not establish that a service is currently running." };
}

/** Same-scale count bars, not performance scores. Zero remains visible as a label. */
function CountChart({ title, bars }: { title: string; bars: Bar[] }) {
  const max = Math.max(1, ...bars.map(b => b.count));
  return <figure aria-label={title} className="space-y-3 rounded-lg border bg-background/40 p-4">
    <figcaption className="text-sm font-medium">{title}</figcaption>
    {bars.map(b => <div key={b.label} className="space-y-1">
      <div className="flex justify-between gap-3 text-xs"><span>{b.label}</span><span className="font-mono tabular-nums">{b.count}</span></div>
      <div aria-hidden className="h-2 overflow-hidden rounded-sm bg-muted">
        <div className={`h-full rounded-sm ${b.muted ? "bg-muted-foreground/40" : "bg-primary"}`} style={{ width: `${b.count / max * 100}%` }} />
      </div>
    </div>)}
  </figure>;
}

function Sources({ selected, onSelect }: { selected: Path | null; onSelect: (path: Path | null) => void }) {
  const alerts = useJson<ExitHabitsBody>("/analytics/exit-habits");
  const radar = useJson<RadarProof>("/radar/proof");
  const answers = useJson<AnswerScorecard>("/copilot/answer-scorecard?days=14");
  const status = useJson<{ enabled: boolean }>("/copilot/status");
  const plans = useJson<PlanProof>("/analytics/plan-proof");
  const shadow = useJson<ShadowWeek>("/radar/shadow-book");
  const settled = [alerts, radar, answers, status, plans, shadow].every(s => s.body !== null || s.error);
  const checkedAt = Math.max(...[alerts, radar, answers, status, plans, shadow].map(s => s.checkedAt ?? 0));
  const readAt = checkedAt ? new Date(checkedAt).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "…";

  const rows: Entry[] = [];
  const a = alerts.body;
  const alertRow = entry("alerts", alerts.error);
  if (a) {
    const f = a.feedback;
    Object.assign(alertRow, {
      state: !f ? "Feedback unavailable" : f.total === 0 ? "No alerts recorded" : f.responded === 0 ? "Needs feedback" : "Collecting",
      sample: f ? `${f.responded} / ${f.total} alerts answered` : `${a.alerts_total} alerts; feedback unavailable`,
      period: `Habit comparison since ${a.go_live}; feedback covers all recorded sent or delivery-unconfirmed position alerts.`,
      result: `${EXIT_HABIT_VERDICT[a.verdict.verdict].label}. ${a.verdict.reason}`,
      next: f && f.unanswered > 0 ? `Review a recent alert and record whether it helped. ${f.unanswered} remain unanswered.` : a.verdict.reason,
      caveat: "Unanswered does not mean unseen or unhelpful. Habit changes and actions after alerts do not establish that alerts caused them.",
      chart: f ? { title: "What you said about the alerts", bars: [
        ...Object.entries(ALERT_FEEDBACK_LABELS).map(([key, label]) => ({ label, count: f.counts[key] ?? 0 })),
        { label: "Unanswered", count: f.unanswered, muted: true },
      ] } : undefined,
      examples: <div className="space-y-1"><h3 className="text-xs font-medium">Recent alerts</h3>
        {a.alerts.slice(0, 3).map(alert => <div key={alert.id} className="text-sm">
          {alert.trade_id ? <Link className={linkClass} href={`/trades/${alert.trade_id}?alert=${alert.id}`}>{alert.contract} · {alert.kind.replaceAll("_", " ")}</Link>
            : <span>{alert.contract} · trade link unavailable</span>}
        </div>)}
      </div>,
    });
  }
  rows.push(alertRow);

  const r = radar.body;
  const radarRow = entry("radar", radar.error);
  if (r) {
    Object.assign(radarRow, {
      state: !r.verdict ? (r.state === "no_data" ? "No events recorded" : "Unavailable") : r.verdict.rated === 0 ? "Needs feedback" : r.verdict.verdict === "not_enough_data" ? "Collecting" : "Ready to review",
      sample: r.verdict ? `${r.verdict.rated} / ${r.events ?? 0} events rated` : "—",
      period: r.rule_version ? `${r.rule_version} · ${r.sessions ?? 0} event-bearing sessions in this usefulness read` : undefined,
      result: r.verdict?.reason ?? r.reason ?? "No Radar evidence available.",
      next: r.verdict ? "Rate events you actually reviewed. Keep the current rules unchanged while the timing study collects evidence." : "Check the Radar source before drawing a conclusion.",
      caveat: "These are usefulness ratings. Event-bearing sessions are not certified sessions in the separate frozen first-20 timing study. That study's progress is not connected here; no timing-study verdict is inferred.",
      chart: r.ratings ? { title: "Radar usefulness ratings", bars: [
        { label: "Useful", count: r.ratings.useful ?? 0 }, { label: "Already knew", count: r.ratings.already_knew ?? 0 },
        { label: "Too late", count: r.ratings.too_late ?? 0 }, { label: "Irrelevant", count: r.ratings.irrelevant ?? 0 },
        { label: "Not rated", count: r.ratings.unrated ?? 0, muted: true },
      ] } : undefined,
    });
  }
  rows.push(radarRow);

  const c = answers.body;
  const copilotRow = entry("copilot", answers.error);
  if (c) {
    const rated = unavailable(c.answers) ? null : c.answers;
    Object.assign(copilotRow, {
      state: !rated ? "Ratings unavailable" : rated.total === 0 ? "No saved answers" : rated.rated === 0 ? "Needs feedback" : "Collecting",
      sample: rated ? `${rated.rated} / ${rated.total} saved answers rated` : "—",
      period: `Last ${c.window.days} days. ${status.body ? status.body.enabled ? "Copilot is enabled." : "Copilot is off; these are historical records." : "Current activation is unverified."}`,
      next: rated ? "Rate an answer after using it. Review usefulness and speed before proposing a model or prompt change." : "Refresh to retry the ratings read; other scorecard sections may still be available.",
      caveat: "Ratings describe saved answers, not all model turns. Missing ratings and unsaved conversations limit coverage. Helped does not mean profitable, and different models may have handled different tasks.",
      cost: !unavailable(c.cost) ? `${money(c.cost.total_usd)} recorded across turns in this window` : "Cost unavailable",
      chart: rated ? { title: "Saved answer feedback", bars: [
        { label: "Helped", count: rated.helped }, { label: "Didn't help", count: rated.didnt },
        { label: "Not rated", count: rated.total - rated.rated, muted: true },
      ] } : undefined,
    });
  } else if (status.body && !status.body.enabled) {
    copilotRow.state = "Off";
    copilotRow.next = "Copilot is off, so its answer scorecard is unavailable. No activation is needed to review the other paths.";
  }
  rows.push(copilotRow);

  const p = plans.body;
  const planRow = entry("plans", plans.error);
  if (p) Object.assign(planRow, {
    state: p.verdict.planned === 0 ? "Needs planned trades" : p.verdict.verdict === "not_enough_data" ? "Collecting" : "Ready to review",
    sample: `${p.verdict.planned} planned · ${p.verdict.unplanned} unplanned`, period: `Closed long options entered since ${p.go_live}`,
    result: p.verdict.reason, next: "Use a plan when it serves your decision and link it to the trade. Do not trade more to fill a sample.",
    caveat: p.caveat,
    chart: { title: "Trades available for comparison", bars: p.groups.map(g => ({ label: g.label, count: g.trades, muted: !g.in_verdict })) },
  });
  rows.push(planRow);

  const s = shadow.body;
  const shadowRow = entry("shadow", shadow.error);
  if (s) Object.assign(shadowRow, {
    state: !s.enabled ? "Off" : s.summary.shadow.plans === 0 ? "No paper plans" : "Collecting",
    sample: `${s.summary.shadow.turns} model turns · ${s.summary.shadow.closed} closed paper positions`,
    period: `${s.week.start} to ${s.week.end} · ${s.enabled ? "enabled" : "off; historical records"}`,
    next: s.summary.shadow.plans === 0 ? "Inspect skips, filters and errors before changing the decision rules. Model activity alone is not a result." : "Wait for resolved paper positions and review their recorded assumptions.",
    caveat: "This is the Copilot Shadow book, separate from Jo's scanner-based Shadow Isaac. Its paper units and your real trades are not a like-for-like comparison; no winner is declared.",
    chart: { title: "Paper-book activity (counts overlap)", bars: [
      { label: "Decision records", count: s.summary.shadow.decisions }, { label: "Model turns", count: s.summary.shadow.turns },
      { label: "Plans", count: s.summary.shadow.plans }, { label: "Closed paper positions", count: s.summary.shadow.closed },
    ] },
  });
  rows.push(shadowRow);

  const active = rows.find(row => row.id === selected);
  return <>
    <p className="text-xs text-muted-foreground" role="status">{settled ? `Checked ${readAt} ET. Each path has its own measurement window.` : "Reading current scorecards…"}</p>
    <div className="overflow-hidden rounded-lg border bg-card" aria-label="Experiment paths">
      {rows.map(row => <button key={row.id} type="button" onClick={() => onSelect(selected === row.id ? null : row.id)}
        aria-expanded={selected === row.id} aria-controls="experiment-detail" data-testid={`experiment-${row.id}`}
        className={`grid w-full gap-2 border-b px-4 py-3 text-left last:border-b-0 sm:grid-cols-[1fr_auto] sm:items-center ${selected === row.id ? "bg-secondary" : "hover:bg-secondary/50"}`}>
        <span className="min-w-0 space-y-0.5"><span className="block text-sm font-medium">{row.name}</span>
          <span className="block text-xs text-muted-foreground">{row.sample}</span></span>
        <span className="flex items-center justify-between gap-3 text-xs"><span className="rounded-md border px-2 py-1">{row.state}</span>
          <ChevronDown aria-hidden className={`h-4 w-4 shrink-0 transition-transform ${selected === row.id ? "rotate-180" : ""}`} /></span>
      </button>)}
    </div>
    <div id="experiment-detail">{active && <section aria-label={active.question} className="space-y-4 rounded-lg border bg-card p-4 sm:p-5">
      <header className="space-y-1"><h2 className="text-base font-medium">{active.question}</h2>
        {active.period && <p className="text-xs text-muted-foreground">{active.period}</p>}</header>
      {active.result && <p className="text-sm">{active.result}</p>}
      {active.chart && <CountChart {...active.chart} />}
      <div className="space-y-1"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Next review step</h3>
        <p className="text-sm">{active.next}</p></div>
      {active.cost && <p className="text-xs text-muted-foreground">{active.cost}</p>}
      <p className="text-xs leading-relaxed text-muted-foreground">{active.caveat}</p>
      {active.examples}
      <Link href={active.href} className={linkClass}>{active.action} →</Link>
    </section>}</div>
    <details className="rounded-lg border p-4 text-sm">
      <summary className="cursor-pointer font-medium">Review plan and scope</summary>
      <div className="mt-3 space-y-3 text-xs leading-relaxed text-muted-foreground">
        <p>First checkpoint: two weeks of using this overview. Check delivery, unanswered feedback and usable samples before starting a live comparison. This is a feasibility review, not a deadline to prove a trading benefit.</p>
        <p>Review weekly; continuing unchanged is a valid decision. The existing alert and Radar rules keep their own review windows. No alert holds, model changes or scheduled experiments are started here.</p>
        <p>Next candidate: facts versus the same facts with an AI explanation. Offline preparation comes first; no live assignment or paid evaluation is active from this page.</p>
        <p>This first overview covers five existing paths. Jo tasks, Duet, Research Studio, the Factory and the opening-session prototype have not been verified here. There is no combined performance score or cross-version trend.</p>
        <Link className={linkClass} href="/proof">Read the existing proof rules →</Link>
      </div>
    </details>
  </>;
}

export default function ExperimentsView() {
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Path | null>("alerts");
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground">Five existing paths · evidence and feedback</p>
      <button type="button" onClick={() => setRefresh(n => n + 1)} className="inline-flex min-h-11 items-center gap-2 rounded-md border px-3 text-xs hover:bg-secondary">
        <RefreshCw className="h-3.5 w-3.5" aria-hidden />Refresh evidence
      </button>
    </div>
    <Sources key={refresh} selected={selected} onSelect={setSelected} />
  </div>;
}
