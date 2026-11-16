"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { saveGoals, type Goal, type GoalBook, type GoalKind, type GoalProgress, type WeeklyGoals } from "@/lib/weeklyGoals";
import { cn } from "@/lib/utils";

/**
 * His weekly goals on the desk (docs/copilot-lab.md § Weekly goals): one compact line in the Paper section ("This week:
 * max loss $220 (goal $300) ✓ · …"), a small "Set this week's goals" control when none is set, and a row in the Friday
 * paper review card. Progress is the server's, computed from his trades; a goal whose source is behind is grey with
 * why and its time, never ticked. No pings.
 */

const INPUT = "min-h-11 rounded-md border bg-background px-2 text-sm sm:min-h-8 sm:text-xs";
const BUTTON = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8";
const DEFAULT_N: Record<GoalKind, number> = { rules_pct: 80, max_loss: 300, max_trades_day: 5 };
const SHORT: Record<GoalKind, string> = { rules_pct: "Follow all my rules on N% of trades", max_loss: "Max loss per trade $N", max_trades_day: "No more than N trades a day" };

/** One goal's progress: the server's words, ✓ met so far, ✗ missed; grey when behind or nothing to judge yet. */
function Item({ p }: { p: GoalProgress }) {
  return (
    <span data-testid="goal-progress" data-ok={p.ok == null ? "none" : String(p.ok)} data-stale={p.stale ? "true" : undefined} title={p.stale ?? p.goal}
      className={cn(p.stale ? "text-muted-foreground/70" : p.ok == null ? "text-muted-foreground" : "text-foreground/90")}>
      {p.text}
      {!p.stale && p.ok === true && <span className="ml-1 text-emerald-400" aria-label="on track">✓</span>}
      {!p.stale && p.ok === false && <span className="ml-1 text-rose-400" aria-label="missed">✗</span>}
    </span>
  );
}

function Stale({ items }: { items: GoalProgress[] }) {
  const why = [...new Set(items.map(p => p.stale).filter((s): s is string => !!s))];
  return why.length ? <p data-testid="goals-stale" className="text-[11px] text-muted-foreground">{why.join(" ")}</p> : null;
}

type Draft = { kind: GoalKind; n: string; book: GoalBook };

function Editor({ goals, onDone }: { goals: WeeklyGoals; onDone(): void }) {
  const usable = goals.kinds.filter(k => !k.why_not);
  const fresh = (): Draft => {
    const taken = new Set(drafts.map(d => d.kind));
    const kind = (usable.find(k => !taken.has(k.kind)) ?? usable[0]).kind;
    return { kind, n: String(DEFAULT_N[kind]), book: "real" };
  };
  const [drafts, setDrafts] = useState<Draft[]>(() => goals.goals.length
    ? goals.goals.map(g => ({ kind: g.kind, n: String(g.n), book: g.book }))
    : [{ kind: usable[0]?.kind ?? "max_loss", n: String(DEFAULT_N[usable[0]?.kind ?? "max_loss"]), book: "real" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (i: number, patch: Partial<Draft>) => setDrafts(d => d.map((x, j) => j === i ? { ...x, ...patch } : x));
  const save = async (list: Draft[]) => {
    if (list.some(d => !d.n.trim())) { setError("Give each goal its number."); return; }
    setBusy(true); setError(null);
    try {
      await saveGoals(list.map(d => ({ kind: d.kind, n: Number(d.n), book: d.book })) as Goal[]);
      onDone();
    } catch (e) { setError(e instanceof Error ? e.message : "Not saved."); } finally { setBusy(false); }
  };
  return (
    <div data-testid="goals-editor" className="space-y-1.5 rounded-md border border-border/70 px-2 py-1.5">
      <p className="text-[11px] text-muted-foreground">One or two goals for the week. They carry over until you change them; progress counts your real trades Monday to Friday (or your paper book, if you pick Paper).</p>
      <ol className="space-y-1">
        {drafts.map((d, i) => {
          const info = goals.kinds.find(k => k.kind === d.kind);
          return (
            <li key={i} data-testid="goals-editor-row" className="flex flex-wrap items-center gap-1.5">
              <select aria-label={`Goal ${i + 1}`} value={d.kind} onChange={e => { const kind = e.target.value as GoalKind; set(i, { kind, n: String(DEFAULT_N[kind]) }); }} className={cn(INPUT, "min-w-0 max-w-[16rem]")}>
                {goals.kinds.map(k => <option key={k.kind} value={k.kind} disabled={!!k.why_not}>{SHORT[k.kind]}{k.why_not ? ` — ${k.why_not}` : ""}</option>)}
              </select>
              <label className="flex items-center gap-1 text-xs text-muted-foreground">N
                <input aria-label={`Goal ${i + 1} N`} inputMode="numeric" value={d.n} onChange={e => set(i, { n: e.target.value.replace(/[^\d]/g, "") })} className={cn(INPUT, "w-20 tabular-nums")} />
                {info?.unit === "$" ? "dollars" : info?.unit}
              </label>
              <select aria-label={`Goal ${i + 1} trades`} value={d.book} onChange={e => set(i, { book: e.target.value as GoalBook })} className={INPUT}>
                <option value="real">Real trades</option>
                <option value="paper">Paper</option>
              </select>
              {drafts.length > 1 && <button type="button" aria-label={`Remove goal ${i + 1}`} onClick={() => setDrafts(x => x.filter((_, j) => j !== i))} className={cn(QUIET, "px-2")}><X size={13} aria-hidden /></button>}
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        {drafts.length < goals.max && usable.length > 0 && <button type="button" onClick={() => setDrafts(x => [...x, fresh()])} className={QUIET}>Add a goal</button>}
        {goals.goals.length > 0 && <button type="button" data-testid="goals-clear" disabled={busy} onClick={() => save([])} className={QUIET}>Clear goals</button>}
        <button type="button" data-testid="goals-save" disabled={busy} onClick={() => save(drafts)} className={cn(BUTTON, "ml-auto border-amber-400/70 text-amber-100")}>Save goals</button>
        <button type="button" onClick={onDone} className={QUIET}>Cancel</button>
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    </div>
  );
}

/** The Paper section's goals line, or only the small control when none is set. */
export function GoalsLine({ goals }: { goals?: WeeklyGoals }) {
  const [editing, setEditing] = useState(false);
  if (!goals) return null;
  const edit = (word: string) => (
    <button type="button" data-testid="goals-set" aria-expanded={editing} onClick={() => setEditing(e => !e)}
      className="text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">{word}</button>
  );
  return (
    <div data-testid="goals" data-use="paper.goals" className="space-y-1 px-3 pt-1 text-[11px] tabular-nums">
      {goals.goals.length === 0 ? <p>{edit("Set this week's goals")}</p> : (
        <p data-testid="goals-line" className="flex flex-wrap gap-x-1.5">
          <span className="text-amber-200">{goals.label}:</span>
          {goals.progress.length
            ? goals.progress.map((p, i) => <span key={`${p.kind}-${p.book}`}>{i > 0 && <span className="text-muted-foreground">· </span>}<Item p={p} /></span>)
            : <span className="text-muted-foreground">{goals.goals.map(g => SHORT[g.kind].replace(/\bN\b/, String(g.n)) + (g.book === "paper" ? " (paper)" : "")).join(" · ")}</span>}
          <span className="ml-1">{edit("Edit")}</span>
        </p>
      )}
      <Stale items={goals.progress} />
      {editing && <Editor goals={goals} onDone={() => setEditing(false)} />}
    </div>
  );
}

/** The Friday review card's row: the goals in force that week, measured over it. Nothing when none were set. */
export function GoalsReviewRow({ goals }: { goals?: GoalProgress[] }) {
  if (!goals?.length) return null;
  return (
    <div data-testid="paper-review-goals" className="text-xs leading-snug">
      <p className="flex flex-wrap gap-x-1.5"><span className="text-muted-foreground">Goals:</span>
        {goals.map((p, i) => <span key={`${p.kind}-${p.book}`}>{i > 0 && <span className="text-muted-foreground">· </span>}<Item p={p} /></span>)}
      </p>
      <Stale items={goals} />
    </div>
  );
}
