/**
 * His weekly goals (backend ``app/engine/weekly_goals.py``, docs/copilot-lab.md § Weekly goals): one or two, carried
 * over week to week until he changes them, with progress computed from his real trades (or his paper book) and never
 * typed. A goal whose source is behind carries ``stale`` (why, with its time) and is shown grey, never as on track.
 */

import { apiUrl } from "@/lib/api";
import { PAPER_EVENT } from "@/lib/paperBook";

export type GoalKind = "rules_pct" | "max_loss" | "max_trades_day";
export type GoalBook = "real" | "paper";
export type Goal = { kind: GoalKind; n: number; book: GoalBook };
/** One goal over one week: ``ok`` true met so far, false missed, null nothing to judge yet (or behind). */
export type GoalProgress = Goal & { goal: string; text: string; ok: boolean | null; stale: string | null };
export type GoalKindInfo = { kind: GoalKind; words: string; unit: string; min: number; max: number; why_not: string | null };
export type WeeklyGoals = { goals: Goal[]; kinds: GoalKindInfo[]; max: number; monday: string; label: string; progress: GoalProgress[] };

export async function saveGoals(goals: Goal[]): Promise<WeeklyGoals> {
  const response = await fetch(apiUrl("/copilot/goals"), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goals }) });
  const reply = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof reply?.detail === "string" ? reply.detail : `Not saved (${response.status}).`);
  window.dispatchEvent(new Event(PAPER_EVENT));  // the paper read carries the line and the review's row
  return reply as WeeklyGoals;
}
