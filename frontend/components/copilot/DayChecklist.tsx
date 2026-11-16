"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import type { DeskPlan, DeskSession } from "@/lib/desk";
import type { PaperBook } from "@/lib/paperBook";
import { cn } from "@/lib/utils";
import MorningBrief from "./MorningBrief";
import { GoalsLine } from "./DeskGoals";
import { PaperScoreLine } from "./DeskPaper";
import { RulesSplitLine } from "./DeskRules";

/** Which list the Day button opens: Start the day (before the open and through the session) or Close the day (after 16:00). */
export type DayKind = "start" | "close";

const hhmm = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One step: its number, name and state on one line. ``run`` makes the line a button (it opens the step's own piece);
 *  ``body`` is a piece shown in place under the line (it has its own buttons, so the line is not one). */
function Step({ id, n, name, state, run, open, body, done }: {
  id: string; n: number; name: string; state: ReactNode; run?(): void; open?: boolean; body?: ReactNode; done?: boolean;
}) {
  const line = (
    <>
      <span aria-hidden className={cn("w-4 shrink-0 text-xs tabular-nums", done ? "text-emerald-300" : "text-muted-foreground")}>{done ? "✓" : n}</span>
      <span className="shrink-0 font-medium text-foreground">{name}</span>
      <span data-testid="day-step-state" className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{state}</span>
      {run && <ChevronRight size={14} aria-hidden className={cn("shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />}
    </>
  );
  return (
    <li data-testid={`day-step-${id}`} className="py-1">
      {run ? (
        <button type="button" onClick={run} aria-expanded={open} className="flex min-h-11 w-full items-center gap-2 rounded-md px-1.5 text-left text-sm hover:bg-secondary sm:min-h-8">{line}</button>
      ) : <div className="flex min-h-11 items-center gap-2 px-1.5 text-sm sm:min-h-8">{line}</div>}
      {body && <div className="pb-1 pl-7 pr-1">{body}</div>}
    </li>
  );
}

/**
 * The Day button's checklist (docs/copilot-lab.md § The desk, The day's checklist): the day's routine as one short list in
 * the copilot column, each step one line with its state. A step opens the piece that already does it, where it lives or
 * in place here; nothing is re-implemented and every piece stays where it is on the desk.
 * - **Start the day**: the morning brief (the session read's ``prep``), plans to arm (Arm today's plans' checklist), this
 *   week's goals (the goals line and its editor), and the prep question (into the box, unsent).
 * - **Close the day**: your day (the day read at the top of Now), to review (the close pass), paper next to real (the
 *   paper book's score line), rules followed vs broken, goals, and one thing for tomorrow (the close question, unsent).
 * Opening it reads nothing new and sends nothing to the model: it shows what the desk already read (the session, the
 * thread list's plans, the paper book). Only a step that already sends something does, and none here sends a turn.
 */
export default function DayChecklist({ kind, early = false, prep, plans, book, bookFailed, toReview, onClose, onArm, onPrep, onDayRead, onReview, onTomorrow, fill }: {
  kind: DayKind;
  /** Before the open on a weekday (Start the day also shows in the session and at weekends). */
  early?: boolean;
  prep: DeskSession["prep"] | undefined;
  /** The thread list's plans (armed ones are Arm's list). */
  plans: DeskPlan[];
  book: PaperBook | null; bookFailed: boolean;
  /** Close questions and fills still to answer today (the desk's tally). */
  toReview: number;
  onClose(): void; onArm(): void; onPrep(): void; onDayRead(): void; onReview(): void; onTomorrow(): void;
  /** The brief's Ask about it: into the box, unsent. */
  fill(text: string): void;
}) {
  const [brief, setBrief] = useState(false);
  const lines = prep?.lines ?? [];
  const armed = plans.filter(p => p.stage === "armed").length;
  const goals = book?.goals;
  const met = goals?.progress.filter(p => !p.stale && p.ok === true).length ?? 0;
  const reading = !book ? (bookFailed ? "could not be read" : "reading…") : null;
  const goalsState = reading ?? (!goals ? "unavailable" : goals.goals.length ? `${met} of ${goals.goals.length} on track` : "none set");
  const goalsStep = (n: number) => (
    <Step id="goals" n={n} name={"This week's goals"} state={goalsState} body={goals ? <div className="-mx-3 -mt-1"><GoalsLine goals={goals} /></div> : undefined} />
  );
  const score = book?.run && book.score ? book.score : null;
  const splits = [book?.score?.paper.rules, book?.score?.real_rules].flatMap(s => s ? [s] : []);
  const judged = splits.reduce((n, s) => n + s.followed.trades + s.broken.trades + s.unclear.trades, 0);
  const rules = book?.my_rules ?? [];

  return (
    <section aria-label={kind === "start" ? "Start the day" : "Close the day checklist"} data-testid="day-checklist" data-kind={kind}
      className="mb-4 space-y-2 rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-baseline gap-2">
        <h2 className="font-semibold text-foreground">{kind === "start" ? "Start the day" : "Close the day"}</h2>
        <span className="text-xs text-muted-foreground">{kind === "close" ? "after the close" : early ? "before the open" : "today"}</span>
        <button type="button" onClick={onClose} className="-my-2 ml-auto min-h-11 px-1 text-xs text-muted-foreground hover:text-foreground sm:min-h-0">Close</button>
      </div>
      {kind === "start" ? (
        <ol className="divide-y">
          <Step id="brief" n={1} name="Morning brief" open={brief}
            state={lines.length ? `written${prep?.at != null ? ` ${hhmm(prep.at)} ET` : ""}${prep?.fallback ? " · facts only" : ""}` : "not written yet"}
            run={lines.length ? () => setBrief(b => !b) : undefined}
            body={brief && lines.length ? <MorningBrief prep={prep} fill={fill} max={3} /> : undefined} />
          <Step id="arm" n={2} name={"Arm today's plans"} state={armed ? `${plural(armed, "plan")} armed` : "none armed"} run={onArm} />
          {goalsStep(3)}
          <Step id="prep" n={4} name="Prep the day" state="its question into the box, unsent" run={onPrep} />
        </ol>
      ) : (
        <ol className="divide-y">
          <Step id="day-read" n={1} name="Your day" state="the read at the top of Now" run={onDayRead} />
          <Step id="review" n={2} name="To review" done={toReview === 0} state={toReview ? `${toReview} to review, one at a time` : "nothing left"} run={onReview} />
          <Step id="paper" n={3} name="Paper next to real" state={reading ?? (score ? null : "paper not started")}
            body={score && book?.run ? <PaperScoreLine score={score} since={book.run.started_at} testId="day-paper-score" className="" /> : undefined} />
          <Step id="rules" n={4} name="Rules followed vs broken" state={reading ?? (!rules.length ? "no rules written yet" : judged ? null : "no checked trade closed yet")}
            body={judged ? <div className="-mx-3"><RulesSplitLine paper={book?.score?.paper.rules} real={book?.score?.real_rules} /></div> : undefined} />
          {goalsStep(5)}
          <Step id="tomorrow" n={6} name="One thing for tomorrow" state="its question into the box, unsent" run={onTomorrow} />
        </ol>
      )}
      <p className="border-t pt-2 text-xs text-muted-foreground">Every step also lives where it always does. Nothing here is sent.</p>
    </section>
  );
}
