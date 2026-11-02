"use client";

import { useAppAccess } from "@/components/AccessProvider";
import { useState } from "react";
import { api, MonthlyFinding, MonthlyReview } from "@/lib/api";
import { timeET } from "@/lib/format";

const VERDICT = {
  keep: { label: "Keep", tone: "bg-secondary text-foreground" },
  tighten: { label: "Tighten", tone: "bg-primary/15 text-primary" },
  drop: { label: "Drop", tone: "bg-secondary text-muted-foreground" },
  now_a_habit: { label: "Now a habit", tone: "bg-secondary text-foreground" },
} as const;
const COMMITMENT = {
  kept: "bg-secondary text-foreground", broken: "bg-primary/15 text-primary",
  partly: "bg-secondary text-foreground", unclear: "bg-secondary text-muted-foreground",
} as const;

/** One month's review: where the P&L came from and leaked, habits, rules, one commitment. */
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
    <section className="rounded-lg border bg-card" aria-label="Monthly review">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
        <h2 className="text-[13.5px] font-semibold tracking-tight">Monthly Review</h2>
        <button type="button" onClick={run} disabled={!owner || status === "loading"}
          className={`inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium transition-colors disabled:opacity-50 sm:min-h-9 ${review ? "border hover:bg-secondary" : "bg-primary text-primary-foreground hover:bg-primary/90"}`}>
          {status === "loading" ? "Generating..." : review ? "Regenerate Monthly Review" : "Run Monthly Review"}
        </button>
      </div>
      <div className="space-y-3 p-4 text-sm text-muted-foreground">
        <p>Claude review across the {closedTrades} trade{closedTrades === 1 ? "" : "s"} that closed in {monthLabel}.</p>
        {error ? <p className="text-red-400">{error}</p>
          : status === "loading" ? <p>Reviewing the month&apos;s statistics and daily reviews. This can take a minute or two…</p>
          : review ? <Result review={review} generatedAt={generatedAt} />
          : <p>No monthly review yet. It is written automatically on the first nightly run of the next month. You can run it now; a review written before the month ends is replaced by that nightly one.</p>}
      </div>
    </section>
  );
}

function Result({ review, generatedAt }: { review: MonthlyReview; generatedAt: string | null }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="inline-flex h-[22px] items-center rounded-md bg-secondary px-2 text-[11.5px] font-medium text-foreground">{review.month_grade}</span>
          {generatedAt && <span className="text-xs tabular-nums text-muted-foreground">Saved {timeET(generatedAt, { year: true })}</span>}
        </div>
        <p className="text-foreground/90">{review.summary}</p>
      </div>
      <div className="rounded-md border border-primary/40 bg-primary/15 p-3" aria-label="Next month's commitment">
        <h3 className="mb-1 text-xs font-medium text-primary">Your One Commitment For Next Month</h3>
        <p className="text-foreground">{review.one_commitment}</p>
      </div>
      {review.last_commitment_check && <div className="flex gap-2">
        <span className={`inline-flex h-[22px] w-fit shrink-0 items-center whitespace-nowrap rounded-md px-2 text-[11.5px] font-medium capitalize ${COMMITMENT[review.last_commitment_check.result] ?? COMMITMENT.unclear}`}>{review.last_commitment_check.result}</span>
        <span><span className="text-foreground/90">Last month: {review.last_commitment_check.commitment}</span>
          <span className="block text-xs text-muted-foreground">{review.last_commitment_check.evidence}</span></span>
      </div>}
      <div className="grid gap-3 md:grid-cols-2">
        <Findings title="Where Your Money Came From" items={review.edge} />
        <Findings title="Where It Leaked" items={review.leaks} />
      </div>
      <Findings title="Habits That Repeat" items={review.recurring_patterns} />
      {!!review.rules_scorecard?.length && <div aria-label="Rules scorecard">
        <h3 className="mb-2 text-xs font-medium text-muted-foreground">Rules Scorecard</h3>
        <ul className="space-y-2">{review.rules_scorecard.map((rule, index) => {
          const verdict = VERDICT[rule.verdict] ?? VERDICT.keep;
          return <li key={index} className="flex gap-2">
            <span className={`inline-flex h-[22px] w-fit shrink-0 items-center whitespace-nowrap rounded-md px-2 text-[11.5px] font-medium ${verdict.tone}`}>{verdict.label}</span>
            <span><span className="text-foreground/90">{rule.rule}</span><span className="block text-xs text-muted-foreground">Kept {rule.kept} · broken {rule.broken}</span></span>
          </li>;
        })}</ul>
      </div>}
      {!!review.vs_last_month?.length && <div>
        <h3 className="mb-2 text-xs font-medium text-muted-foreground">Compared With Last Month</h3>
        <ul className="space-y-1">{review.vs_last_month.map((item, index) => <li key={index} className="text-foreground/80">{item}</li>)}</ul>
      </div>}
      {!!review.data_gaps?.length && <div className="rounded-md border p-3 text-xs">
        <h3 className="mb-1 font-medium text-red-400">What the review could not see</h3>
        <ul className="space-y-1">{review.data_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
      </div>}
      {review.generated_by && <p className="text-xs text-muted-foreground">Written by {review.generated_by}.</p>}
    </div>
  );
}

function Findings({ title, items }: { title: string; items?: MonthlyFinding[] }) {
  if (!items?.length) return null;
  return (
    <div className="rounded-md border bg-background/40 p-3">
      <h3 className="mb-2 text-xs font-medium text-muted-foreground">{title}</h3>
      <ul className="space-y-2">{items.map((item, index) => <li key={index}>
        <span className="text-foreground/90">{item.finding}</span><span className="block text-xs text-muted-foreground">{item.evidence}</span>
      </li>)}</ul>
    </div>
  );
}
