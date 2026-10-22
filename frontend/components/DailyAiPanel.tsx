"use client";

import { useAppAccess } from "@/components/AccessProvider";
import { useState } from "react";
import { api, DailyReview, PlanCheck, RuleCheck } from "@/lib/api";
import { timestampET } from "@/lib/dayJournal";

type Status = "idle" | "loading" | "done" | "error";

export default function DailyAiPanel({
  tradeCount,
  day,
  dayLabel,
  tradeIds,
  initialReview = null,
  initialGeneratedAt = null,
  hasDayContext = false,
  contextRevision = 0,
}: {
  tradeCount: number;
  day: string | null;
  dayLabel: string;
  tradeIds: string[];
  initialReview?: DailyReview | null;
  initialGeneratedAt?: string | null;
  hasDayContext?: boolean;
  contextRevision?: number;
}) {
  const { owner } = useAppAccess();
  const [status, setStatus] = useState<Status>(initialReview ? "done" : "idle");
  const [review, setReview] = useState<DailyReview | null>(initialReview);
  const [generatedAt, setGeneratedAt] = useState<string | null>(initialGeneratedAt);
  const [reviewedContextRevision, setReviewedContextRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function handleRunAnalysis() {
    if (!day || (tradeIds.length === 0 && !hasDayContext)) return;

    setStatus("loading");
    setError(null);
    const requestedContextRevision = contextRevision;
    try {
      const response = await api.reviewDay({ day, trade_ids: tradeIds });
      setReview(response.review);
      setGeneratedAt(response.generated_at);
      setReviewedContextRevision(requestedContextRevision);
      setStatus("done");
    } catch (err) {
      // 503 means the review is not set up here; retrying cannot help, so show the server's reason.
      const setup = err instanceof Error ? /-> 503: (.+)$/.exec(err.message)?.[1] : undefined;
      setError(setup ?? "The daily review could not be generated. Please retry.");
      setStatus("error");
    }
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            AI Analysis
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Full-day Claude review, on your Claude plan, for {dayLabel}. Inputs include {tradeCount} journal trade(s){hasDayContext ? " and your saved day thoughts and plans" : ""}.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRunAnalysis}
          disabled={!owner || !day || (tradeIds.length === 0 && !hasDayContext) || status === "loading"}
          className="rounded bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
        >
          {status === "loading" ? "Generating..." : review ? "Regenerate Analysis" : "Run Daily Analysis"}
        </button>
      </div>

      <div className="mt-4 rounded-md bg-muted p-4 text-sm text-muted-foreground">
        {error ? (
          <p className="text-red-400">{error}</p>
        ) : status === "loading" ? (
          <p>Generating review from your saved journal context. This can take a minute…</p>
        ) : review ? (
          <div className="space-y-4">
            {(review.source_data_stale || reviewedContextRevision < contextRevision) && (
              <p className="rounded border border-amber-500/50 bg-amber-950/30 p-3 text-amber-200">
                {review.source_data_stale_reason ?? "Saved analysis may not include the latest thoughts, plans, fills, or market context. Regenerate it to review the current saved inputs."}
              </p>
            )}
            <DailyReviewResult review={review} generatedAt={generatedAt} />
          </div>
        ) : (
          <p>
            No analysis has been generated yet. The review will use saved journal trades and any saved day thoughts or plans available for this date. Actual market path evidence may be unavailable; any gaps should remain explicit.
          </p>
        )}
      </div>
    </section>
  );
}

function DailyReviewResult({ review, generatedAt }: { review: DailyReview; generatedAt: string | null }) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="rounded bg-background px-2 py-0.5 text-xs font-semibold text-foreground">
            {review.day_grade}
          </span>
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Daily Review</span>
          {generatedAt && (
            <span className="text-xs text-muted-foreground">
              Saved {timestampET(generatedAt)}
            </span>
          )}
        </div>
        <p className="text-foreground/90">{review.summary}</p>
      </div>

      {review.market_read && <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">The Market That Day</h3>
        <p className="text-foreground/80">{review.market_read}</p>
      </div>}
      <PlanVsExecution items={review.plan_vs_execution} />
      <ExpectationChecks items={review.expectation_checks} />
      <RulesCheck items={review.rules_check} />
      <ReviewList title="Key Takeaways" items={review.key_takeaways} />
      <ReviewList title="Compared With Your Normal" items={review.vs_baseline} />

      <div className="grid gap-3 md:grid-cols-2">
        <TradeCallout title="Best Trade" trade={review.best_trade} tone="good" />
        <TradeCallout title="Weakest Trade" trade={review.worst_trade} tone="bad" />
      </div>

      <ReviewList title="Patterns" items={review.patterns} />
      <ReviewList title="Next Session Rules" items={review.next_session_rules} />
      {!!review.data_gaps?.length && <div className="rounded border border-amber-500/40 p-3 text-xs text-amber-200">
        <h3 className="mb-1 font-semibold uppercase tracking-wide">What the review could not see</h3>
        <ul className="space-y-1">{review.data_gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
      </div>}
      {review.generated_by && <p className="text-xs text-muted-foreground">Written by {review.generated_by}.</p>}
    </div>
  );
}

function ExpectationChecks({ items }: { items?: DailyReview["expectation_checks"] }) {
  if (!items?.length) return null;
  const labels = { supported: "Supported", invalidated: "Invalidated", mixed: "Mixed", unresolved: "Unresolved" } as const;
  const tones = { supported: "border-emerald-500/50 text-emerald-300", invalidated: "border-red-500/50 text-red-300", mixed: "border-amber-500/50 text-amber-200", unresolved: "border-border text-muted-foreground" } as const;
  return <section aria-label="Morning expectations against the day">
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your Expectations vs the Day</h3>
    <p className="mb-2 text-xs text-muted-foreground">Review assessments should cite observed evidence. Open the saved note to see its original words; use its symbol chart to inspect the day’s price path.</p>
    <ul className="space-y-2">{items.map((item) => <li key={item.entry_id} className="rounded border border-border p-3">
      <div className="flex flex-wrap items-center gap-2"><span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold ${tones[item.assessment]}`}>{labels[item.assessment]}</span><a href={`#thought-${encodeURIComponent(item.entry_id)}`} className="text-xs text-primary underline">Open original thought</a></div>
      <p className="mt-2 text-sm"><span className="font-medium text-foreground">Expected:</span> {item.expected}</p>
      <p className="mt-1 text-sm"><span className="font-medium text-foreground">Observed:</span> {item.observed}</p>
      <p className="mt-1 text-sm text-muted-foreground">Evidence: {item.evidence}</p>
    </li>)}</ul>
  </section>;
}

const RESULT = {
  kept: { label: "Kept", tone: "border-emerald-500/50 text-emerald-300" },
  broken: { label: "Broken", tone: "border-red-500/50 text-red-300" },
  partly: { label: "Partly", tone: "border-amber-500/50 text-amber-300" },
  not_tested: { label: "Not tested", tone: "border-border text-muted-foreground" },
} as const;

const PLAN_RESULT = {
  followed: { label: "Followed", tone: "border-emerald-500/50 text-emerald-300" },
  deviated: { label: "Deviated", tone: "border-red-500/50 text-red-300" },
  partly: { label: "Partly", tone: "border-amber-500/50 text-amber-300" },
  no_plan: { label: "No plan", tone: "border-border text-muted-foreground" },
} as const;

/** Each captured plan against what was actually done. */
function PlanVsExecution({ items }: { items?: PlanCheck[] }) {
  if (!items?.length) return null;
  return (
    <div aria-label="Plan versus execution">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your Plan vs What You Did</h3>
      <ul className="space-y-2">
        {items.map((item, index) => {
          const result = PLAN_RESULT[item.result] ?? PLAN_RESULT.no_plan;
          return <li key={index} className="flex gap-2">
            <span className={`h-fit shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${result.tone}`}>{result.label}</span>
            <span className="min-w-0"><span className="font-medium text-foreground">{item.ticker}</span>
              <span className="block text-xs text-muted-foreground">Planned: {item.planned}</span>
              <span className="block text-xs text-muted-foreground">Did: {item.did}</span></span>
          </li>;
        })}
      </ul>
    </div>
  );
}

/** The last review's rules, checked against this day. */
function RulesCheck({ items }: { items?: RuleCheck[] }) {
  if (!items?.length) return null;
  return (
    <div aria-label="Rules from the last review">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Rules From {items[0].set_on}</h3>
      <ul className="space-y-2">
        {items.map((item, index) => {
          const result = RESULT[item.result] ?? RESULT.not_tested;
          return <li key={index} className="flex gap-2">
            <span className={`h-fit shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${result.tone}`}>{result.label}</span>
            <span><span className="text-foreground/90">{item.rule}</span>{item.evidence && <span className="block text-xs text-muted-foreground">{item.evidence}</span>}</span>
          </li>;
        })}
      </ul>
    </div>
  );
}

function ReviewList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <ul className="space-y-1">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className="text-foreground/80">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function TradeCallout({
  title,
  trade,
  tone,
}: {
  title: string;
  trade: DailyReview["best_trade"];
  tone: "good" | "bad";
}) {
  const toneClass = tone === "good" ? "border-emerald-900/50" : "border-red-900/50";

  return (
    <div className={`rounded-md border bg-background/40 p-3 ${toneClass}`}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <p className="mt-1 font-medium text-foreground">{trade.ticker ?? "No trade selected"}</p>
      <p className="mt-1 text-foreground/75">{trade.reason}</p>
      {trade.trade_id && (
        <a href={`/trades/${trade.trade_id}`} className="mt-2 inline-block text-xs font-medium text-blue-400 hover:text-blue-300">
          Open trade
        </a>
      )}
    </div>
  );
}
