"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { REVIEW_WEEK, usePlanStreak, type PlanStreakEntry } from "@/components/PlanStreak";
import { VERDICT, setupLine, useJson, type RadarProof } from "@/components/ProofView";
import { EXIT_HABIT_VERDICT, type ExitHabitsBody } from "@/components/dashboard/ExitHabits";
import { cn } from "@/lib/utils";
import { unavailable, type AnswerScorecard, type BriefScorecard } from "@/lib/copilot";

/*
 * This week on the desk (docs/copilot-lab.md § The desk), folded at the foot of the thread list's drawer: the copilot's
 * answers, the morning brief's scorecard, the two proofs and the week's planned entries. Read-only.
 */

const NY = "America/New_York";
const MAX_TILES = 40;
// This week's tiles: planned before entry, not (no plan, or one saved late), or a suggested plan waiting to be linked.
const WEEK_TILE: Record<PlanStreakEntry["state"], { mark: string; label: string; tone: string }> = {
  planned: { mark: "+", label: "planned", tone: "bg-emerald-400/15 text-emerald-300" },
  late: { mark: "−", label: "plan saved late", tone: "bg-rose-400/15 text-rose-300" },
  unplanned: { mark: "−", label: "no plan", tone: "bg-rose-400/15 text-rose-300" },
  pending: { mark: "·", label: "waiting to be linked", tone: "bg-muted text-muted-foreground" },
};
/** ``Tue 10:31`` by the New York clock. */
const weekClock = (seconds: number) => new Date(seconds * 1000).toLocaleString("en-US",
  { timeZone: NY, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).replace(",", "");
const Quiet = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;

/** This week's two proofs, as /proof reads them (``GET /analytics/exit-habits``, ``GET /radar/proof``): each label and
 * what it rests on, never recomputed here. A read that is missing or fails says so. */
function WeekProof() {
  const alerts = useJson<ExitHabitsBody>("/analytics/exit-habits");
  const radar = useJson<RadarProof>("/radar/proof");
  const line = (name: string, label: ReactNode, rest: ReactNode, testId: string) => (
    <p data-testid={testId} className="min-w-0 break-words">
      <span className="text-muted-foreground">{name}: </span><span className="font-medium text-foreground">{label}</span>
      {rest && <span className="text-xs text-muted-foreground"> · {rest}</span>}
    </p>
  );
  const feedback = alerts.body?.feedback;
  const verdict = radar.body?.verdict;
  return (
    <section aria-label="Proof this week" data-testid="week-proof" className="space-y-1 border-b pb-3 text-sm">
      {alerts.body ? line("Alerts", EXIT_HABIT_VERDICT[alerts.body.verdict.verdict].label,
        feedback ? <>based on <span className="tabular-nums">{feedback.responded}</span> of <span className="tabular-nums">{feedback.total}</span> alerts answered</>
          : <>based on <span className="tabular-nums">{alerts.body.verdict.sample}</span> of the last <span className="tabular-nums">{alerts.body.window}</span> trades</>, "week-proof-alerts")
        : line("Alerts", alerts.error ? "could not load" : "reading…", null, "week-proof-alerts")}
      {radar.body ? line("Radar", verdict ? VERDICT[verdict.verdict].label : VERDICT.not_enough_data.label,
        verdict ? <><span className="tabular-nums">{verdict.rated}</span> hit{verdict.rated === 1 ? "" : "s"} rated</> : radar.body.reason ?? "Radar is off", "week-proof-radar")
        : line("Radar", radar.error ? "could not load" : "reading…", null, "week-proof-radar")}
      {radar.body && radar.body.setups !== undefined && (
        <div data-testid="week-proof-setups">
          <p className="text-muted-foreground">Setup cards:</p>
          {radar.body.setups == null ? <p className="text-xs text-muted-foreground">could not load</p>
            : radar.body.setups.length === 0 ? <p className="text-xs text-muted-foreground">No setup cards yet.</p>
            : <ul className="space-y-0.5 text-xs">{radar.body.setups.map(r => <li key={`${r.kind}-${r.direction}`} data-testid="week-proof-setup-line" className="break-words">{setupLine(r)}</li>)}</ul>}
        </div>
      )}
      <Link href="/proof" className="inline-flex min-h-11 items-center text-xs font-medium text-primary hover:underline sm:min-h-0">Open Proof →</Link>
    </section>
  );
}

/** This week's copilot, as ``GET /copilot/answer-scorecard`` counts it: Helped of rated, answers, the median wait for the
 * first text, what it cost; then pushbacks, follow-ups and failed turns. A read that fails says so. */
function WeekCopilot() {
  const card = useJson<AnswerScorecard>("/copilot/answer-scorecard?days=7");
  const seconds = (ms: number | null | undefined) => ms == null ? null : `${(ms / 1000).toFixed(1)} s`;
  let line: ReactNode = card.error ? "could not load" : "reading…";
  let detail: ReactNode = null;
  if (card.body) {
    const a = card.body.answers, c = card.body.cost, l = card.body.latency;
    if (unavailable(a)) line = "could not count the answers";
    else {
      const wait = seconds(!unavailable(l) ? l.ask?.first_text_ms.p50 : undefined);  // the desk's questions; a scheduled kind would mislead here
      line = <>Helped <span className="tabular-nums">{a.helped}</span> of <span className="tabular-nums">{a.rated}</span> rated · <span className="tabular-nums">{a.total}</span> answer{a.total === 1 ? "" : "s"}
        {wait && <> · first text <span className="tabular-nums">{wait}</span> median</>}
        {!unavailable(c) && <> · <span className="tabular-nums">${c.total_usd.toFixed(2)}</span></>}</>;
      detail = <>Pushed back on <span className="tabular-nums">{a.pushback}</span> · <span className="tabular-nums">{a.follow_ups}</span> follow-up{a.follow_ups === 1 ? "" : "s"} · <span className="tabular-nums">{a.failed}</span> failed</>;
    }
  }
  return (
    <section aria-label="Copilot this week" data-testid="week-copilot" className="space-y-1 border-b pb-3 text-sm">
      <p data-testid="week-copilot-line" className="min-w-0 break-words"><span className="text-muted-foreground">Copilot: </span><span className="font-medium text-foreground">{line}</span></p>
      {detail && <p data-testid="week-copilot-detail" className="text-xs text-muted-foreground">{detail}</p>}
    </section>
  );
}

/** The morning brief, as ``GET /copilot/brief-scorecard`` scores it: symbols named over the week's briefs and how many
 * moved 3+ points vs SPY by the close, then one small row per brief day (newest first). A read that fails says so. */
function WeekBrief() {
  const card = useJson<BriefScorecard>("/copilot/brief-scorecard?days=7");
  const body = card.body;
  if (body && body.state === "ok" && body.briefs === 0) return <Quiet>No morning brief in the last 7 days.</Quiet>;
  let line: ReactNode = card.error || body?.state === "unavailable" ? "could not load" : "reading…";
  if (body && body.state === "ok") {
    line = <>named <span className="tabular-nums">{body.named}</span> symbol{body.named === 1 ? "" : "s"} over <span className="tabular-nums">{body.briefs}</span> brief{body.briefs === 1 ? "" : "s"}
      {" · "}<span className="tabular-nums">{body.moved}</span> moved 3+ pts vs SPY by the close
      {body.unknown > 0 && <> · <span className="tabular-nums">{body.unknown}</span> without bars</>}</>;
  }
  const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).replace(",", "");
  const rows = body?.state === "ok" ? body.rows.slice(0, 5) : [];
  return (
    <section aria-label="Morning brief this week" data-testid="week-brief" className="space-y-1 border-b pb-3 text-sm">
      <p data-testid="week-brief-line" className="min-w-0 break-words"><span className="text-muted-foreground">Morning brief: </span><span className="font-medium text-foreground">{line}</span></p>
      {rows.length > 0 && (
        <ul aria-label="Morning briefs by day" className="space-y-0.5 text-xs text-muted-foreground">
          {rows.map(row => (
            <li key={row.day} data-testid="week-brief-row">
              {day(row.day)}: {row.state === "unavailable" ? "could not score"
                : <>{row.named} named, {row.moved} moved{row.unknown > 0 && `, ${row.unknown} without bars`}{row.state === "in_progress" && " (in progress)"}</>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** This week, folded: open it to read each part (each reads only once shown). */
export default function ThisWeek() {
  return (
    <details data-testid="this-week" className="group rounded-lg border bg-card">
      <summary className="flex min-h-11 cursor-pointer list-none items-center px-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground [&::-webkit-details-marker]:hidden sm:min-h-9">
        This week <span aria-hidden className="ml-auto group-open:rotate-180">▾</span>
      </summary>
      <div className="border-t p-3"><WeekTab /></div>
    </details>
  );
}

function WeekTab() {
  return <div className="space-y-3"><WeekCopilot /><WeekBrief /><WeekProof /><WeekRecord /></div>;
}

/** This week's entries, planned before entry or not (the plan streak's own counts, so tiles by kind, not by day), and the
 * streak with what one more planned entry makes. */
function WeekRecord() {
  const streak = usePlanStreak();
  if (!streak) return <Quiet>Reading this week…</Quiet>;
  if (!streak.show) return <Quiet>No entries are tracked yet. Once a plan is saved before an entry, this week&apos;s record shows here.</Quiet>;
  const { planned, total, pending, entries } = streak.this_week;
  // The latest entries when there are more than fit, still oldest first; each opens its trade, where the linked plan shows.
  const shown = entries.slice(-MAX_TILES);
  return (
    <div className="space-y-2 text-sm">
      {shown.length > 0 && (
        <ol aria-label="This week's entries" className="flex flex-wrap items-center gap-1">
          {entries.length > MAX_TILES && <li className="text-xs tabular-nums text-muted-foreground">+{entries.length - MAX_TILES} earlier</li>}
          {shown.map(entry => {
            const tile = WEEK_TILE[entry.state];
            const label = `${entry.short} · ${weekClock(entry.entry_time)} · ${tile.label}`;
            return (
              <li key={entry.trade_id}>
                <Link href={`/trades/${encodeURIComponent(entry.trade_id)}`} title={label} aria-label={label}
                  className={cn("flex h-8 w-8 items-center justify-center rounded text-xs tabular-nums hover:ring-1 hover:ring-primary sm:h-6 sm:w-6", tile.tone)}>
                  {tile.mark}
                </Link>
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-foreground">
        {total ? <><span className="tabular-nums">{planned}</span> of <span className="tabular-nums">{total}</span> entries this week were planned before entry.</> : "No entries yet this week."}
        {pending > 0 && <> <span className="tabular-nums">{pending}</span> waiting to be linked.</>}
      </p>
      <p className="text-xs text-muted-foreground">
        Plan streak <span className="tabular-nums">{streak.current}</span>, best <span className="tabular-nums">{streak.best}</span>.
        {streak.current > 0 ? <> One more planned entry makes <span className="tabular-nums">{streak.current + 1}</span> in a row.</>
          : streak.last_break ? <> Last unplanned: {streak.last_break.contract}{streak.last_break.reason === "late" ? " (plan saved late)" : ""}.</> : null}
      </p>
      <Link href={REVIEW_WEEK} className="inline-flex min-h-11 items-center text-xs text-muted-foreground hover:text-primary sm:min-h-0">Review my week →</Link>
    </div>
  );
}
