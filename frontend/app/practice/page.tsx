import { notFound, redirect } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";
import PracticeRoutine from "@/components/PracticeRoutine";
import PracticeDecisions from "@/components/PracticeDecisions";
import ScalpShortlistPanel from "@/components/ScalpShortlistPanel";

export const dynamic = "force-dynamic";

type PracticeParams = { decision?: string; practice_run?: string };

/** Retired while the desk is home: every visit opens the desk's Practice fold (routine, saved decisions, 9:40 scalp
 * shortlist, Decision replay lab). ``?decision=`` and ``?practice_run=`` carry over (the desk opens that line on them),
 * and a ``#scalp-shortlist`` anchor survives the redirect. With the desk off (development, the browser suite) the page
 * still renders. */
export default async function PracticePage({ searchParams }: { searchParams: Promise<PracticeParams> }) {
  if (!(await requireAccess()).owner) notFound();
  const params = await searchParams;
  if (await api.copilotOn()) {
    const kept = new URLSearchParams();
    for (const key of ["decision", "practice_run"] as const) {
      const value = params[key];
      if (typeof value === "string" && value.trim()) kept.set(key, value.trim());
    }
    redirect(kept.size ? `/copilot-lab?${kept}` : "/copilot-lab");
  }
  const { decision } = params;
  const { decisions } = await api.decisions();
  // Alert links can name records outside the recent-decision window.
  if (decision && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(decision)
      && !decisions.some((record) => record.id === decision)) {
    const focused = await api.decision(decision).catch(() => null);
    if (focused) decisions.unshift(focused);
  }
  return <div className="min-w-0 space-y-6">
    <header>
      <h1 className="text-xl font-semibold">Daily Practice</h1>
      <p className="mt-1 text-sm text-muted-foreground">Prepare, save choices, and review paper practice separately from your journal.</p>
      <a href="#saved-decisions" className="mt-2 inline-flex min-h-11 items-center text-sm text-primary hover:underline">Saved decisions ↓</a>
    </header>
    <section className="rounded-lg border bg-card p-4">
      <div className="-mx-4 -mt-4 flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5"><h2 className="text-[13.5px] font-semibold tracking-tight">Decision Replay Lab</h2></div>
      <p className="mt-3 text-sm text-muted-foreground">Revisit two frozen moments from an invented options trade. Save your decision before revealing what followed.</p>
      <a href="/practice/replay" className="mt-3 inline-flex min-h-11 items-center rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary">Open a replay</a>
    </section>
    <div id="scalp-shortlist" className="scroll-mt-4"><ScalpShortlistPanel history /></div>
    <div id="daily-practice" className="scroll-mt-4"><PracticeRoutine /></div>
    <div id="saved-decisions" className="scroll-mt-4"><PracticeDecisions records={decisions} focusId={decision} /></div>
  </div>;
}
