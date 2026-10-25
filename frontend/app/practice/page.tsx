import { notFound } from "next/navigation";
import { requireAccess } from "@/lib/accessServer";
import { api } from "@/lib/serverApi";
import PracticeRoutine from "@/components/PracticeRoutine";
import PracticeDecisions from "@/components/PracticeDecisions";

type PracticeParams = { decision?: string; practice_run?: string };

export default async function PracticePage({ searchParams }: { searchParams: Promise<PracticeParams> }) {
  if (!(await requireAccess()).owner) notFound();
  const { decision } = await searchParams;
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
    <section className="rounded-lg border border-primary/30 bg-card p-4">
      <h2 className="font-semibold">Decision Replay Lab</h2>
      <p className="mt-1 text-sm text-muted-foreground">Revisit two frozen moments from an invented options trade. Save your decision before revealing what followed.</p>
      <a href="/practice/replay" className="mt-3 inline-flex min-h-11 items-center rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Open a replay</a>
    </section>
    <div id="daily-practice" className="scroll-mt-4"><PracticeRoutine /></div>
    <div id="saved-decisions" className="scroll-mt-4"><PracticeDecisions records={decisions} focusId={decision} /></div>
  </div>;
}
