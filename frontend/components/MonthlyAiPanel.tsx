"use client";

import { useAppAccess } from "@/components/AccessProvider";
import { useState } from "react";
import { api, MonthlyFinding, MonthlyReview } from "@/lib/api";

const VERDICT = {
  keep: { label: "Keep", tone: "border-emerald-500/50 text-emerald-300" },
  tighten: { label: "Tighten", tone: "border-amber-500/50 text-amber-300" },
  drop: { label: "Drop", tone: "border-border text-muted-foreground" },
  now_a_habit: { label: "Now a habit", tone: "border-sky-500/50 text-sky-300" },
} as const;
const COMMITMENT = {
  kept: "border-emerald-500/50 text-emerald-300", broken: "border-red-500/50 text-red-300",
  partly: "border-amber-500/50 text-amber-300", unclear: "border-border text-muted-foreground",
} as const;

/** One month's review on the Claude plan: where the P&L came from and leaked, habits, rules, one commitment. */
export default function MonthlyAiPanel({ month, monthLabel, closedTrades, initialReview = null, initialGeneratedAt = null }: {
  month: string; monthLabel: string; closedTrades: number; initialReview?: MonthlyReview | null; initialGeneratedAt?: string | null;
}) {
  const { owner } = useAppAccess();
  const [review, setReview] = useState<MonthlyReview | null>(initialReview);
  const [generatedAt, setGeneratedAt] = useState<string | null>(initialGeneratedAt);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setStatus("loading");
    setError(null);
    try {
      const response = await api.reviewMonth(month);
      setReview(response.review);
      setGeneratedAt(response.generated_at);
      setStatus("idle");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate the monthly review");
      setStatus("error");
    }
  }

  return (
    <section className="rounded-lg border bg-card p-5" aria-label="Monthly review">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Monthly Review</h2>
          <p className="mt-1 text-sm text-muted-foreground">Claude review, on your Claude plan, across the {closedTrades} trade(s) that closed in {monthLabel}.</p>
        </div>
        <button type="button" onClick={run} disabled={!owner || status === "loading"}
          className="rounded bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50">
          {status === "loading" ? "Generating..." : review ? "Regenerate Monthly Review" : "Run Monthly Review"}
        </button>
      </div>
      <div className="mt-4 rounded-md bg-muted p-4 text-sm text-muted-foreground">
        {error ? <p className="text-red-400">{error}</p>
          : status === "loading" ? <p>Reviewing the month&apos;s statistics and daily reviews. This can take a minute or two…</p>
          : review ? <Result review={review} generatedAt={generatedAt} />
          : <p>No monthly review yet. It is written automatically on the first nightly run of the next month, or run it now.</p>}
      </div>
    </section>
  );
}

function Result({ review, generatedAt }: { review: MonthlyReview; generatedAt: string | null }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="rounded bg-background px-2 py-0.5 text-xs font-semibold text-foreground">{review.month_grade}</span>
          {generatedAt && <span className="text-xs text-muted-foreground">Saved {new Date(generatedAt).toLocaleString()}</span>}
        </div>
        <p className="text-foreground/90">{review.summary}</p>
      </div>
      <div className="rounded border border-sky-500/40 p-3" aria-label="Next month's commitment">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-sky-300">Your One Commitment For Next Month</h3>
        <p className="text-foreground">{review.one_commitment}</p>
      </div>
      {review.last_commitment_check && <div className="flex gap-2">
        <span className={`h-fit shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold capitalize ${COMMITMENT[review.last_commitment_check.result] ?? COMMITMENT.unclear}`}>{review.last_commitment_check.result}</span>
        <span><span className="text-foreground/90">Last month: {review.last_commitment_check.commitment}</span>
          <span className="block text-xs text-muted-foreground">{review.last_commitment_check.evidence}</span></span>
      </div>}
      <div className="grid gap-3 md:grid-cols-2">
        <Findings title="Where Your Money Came From" items={review.edge} tone="border-emerald-900/50" />
        <Findings title="Where It Leaked" items={review.leaks} tone="border-red-900/50" />
      </div>
      <Findings title="Habits That Repeat" items={review.recurring_patterns} />
      {!!review.rules_scorecard?.length && <div aria-label="Rules scorecard">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Rules Scorecard</h3>
        <ul className="space-y-2">{review.rules_scorecard.map((rule, index) => {
          const verdict = VERDICT[rule.verdict] ?? VERDICT.keep;
          return <li key={index} className="flex gap-2">
            <span className={`h-fit shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${verdict.tone}`}>{verdict.label}</span>
            <span><span className="text-foreground/90">{rule.rule}</span><span className="block text-xs text-muted-foreground">Kept {rule.kept} · broken {rule.broken}</span></span>
          </li>;
        })}</ul>
      </div>}
      {!!review.vs_last_month?.length && <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Compared With Last Month</h3>
        <ul className="space-y-1">{review.vs_last_month.map((item, index) => <li key={index} className="text-foreground/80">{item}</li>)}</ul>
      </div>}
      {!!review.data_gaps?.length && <div className="rounded border border-amber-500/40 p-3 text-xs text-amber-200">
        <h3 className="mb-1 font-semibold uppercase tracking-wide">What the review could not see</h3>
        <ul className="space-y-1">{review.data_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
      </div>}
      {review.generated_by && <p className="text-xs text-muted-foreground">Written by {review.generated_by}.</p>}
    </div>
  );
}

function Findings({ title, items, tone = "border-border" }: { title: string; items?: MonthlyFinding[]; tone?: string }) {
  if (!items?.length) return null;
  return (
    <div className={`rounded-md border bg-background/40 p-3 ${tone}`}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <ul className="space-y-2">{items.map((item, index) => <li key={index}>
        <span className="text-foreground/90">{item.finding}</span><span className="block text-xs text-muted-foreground">{item.evidence}</span>
      </li>)}</ul>
    </div>
  );
}
