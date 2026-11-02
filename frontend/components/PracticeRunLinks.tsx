export default function PracticeRunLinks({ runs }: { runs: { id: string; day: string }[] }) {
  if (!runs.length) return null;
  return <section className="space-y-3 rounded-lg border bg-card p-4"><div className="-mx-4 -mt-4 flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5"><h2 className="text-[13.5px] font-semibold tracking-tight">Practice sessions</h2></div><p className="text-sm text-muted-foreground">Practice-only dates are available even when the journal has no trades.</p><div className="flex flex-wrap gap-3">{runs.map(run => <a key={run.id} href={`/daily/${run.day}?practice_run=${run.id}`} className="rounded-md border px-3 py-2 text-sm text-primary underline">Review practice {run.day}</a>)}</div></section>;
}
