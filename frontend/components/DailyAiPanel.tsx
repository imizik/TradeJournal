"use client";

import { useState } from "react";
import { api, DailyReview } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";

export default function DailyAiPanel({
  tradeCount,
  day,
  dayLabel,
  tradeIds,
  initialReview = null,
  initialGeneratedAt = null,
}: {
  tradeCount: number;
  day: string | null;
  dayLabel: string;
  tradeIds: string[];
  initialReview?: DailyReview | null;
  initialGeneratedAt?: string | null;
}) {
  const [status, setStatus] = useState<Status>(initialReview ? "done" : "idle");
  const [review, setReview] = useState<DailyReview | null>(initialReview);
  const [generatedAt, setGeneratedAt] = useState<string | null>(initialGeneratedAt);
  const [error, setError] = useState<string | null>(null);

  async function handleRunAnalysis() {
    if (!day || tradeIds.length === 0) return;

    setStatus("loading");
    setError(null);
    try {
      const response = await api.reviewDay({ day, trade_ids: tradeIds });
      setReview(response.review);
      setGeneratedAt(response.generated_at);
      setStatus("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate daily analysis");
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
            Full-day Anthropic review across the {tradeCount} trade(s) shown for {dayLabel}.
          </p>
        </div>
        <button
          type="button"
          onClick={handleRunAnalysis}
          disabled={!day || tradeIds.length === 0 || status === "loading"}
          className="rounded bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
        >
          {status === "loading" ? "Generating..." : review ? "Regenerate Analysis" : "Run Daily Analysis"}
        </button>
      </div>

      <div className="mt-4 rounded-md bg-muted p-4 text-sm text-muted-foreground">
        {error ? (
          <p className="text-red-400">{error}</p>
        ) : status === "loading" ? (
          <p>Generating review from trade, fill, and enrichment context...</p>
        ) : review ? (
          <DailyReviewResult review={review} generatedAt={generatedAt} />
        ) : (
          <p>
            No analysis has been generated yet. The review will use trades, fills, realized P&L, and any enriched
            fill indicators currently available for this day.
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
              Saved {new Date(generatedAt).toLocaleString()}
            </span>
          )}
        </div>
        <p className="text-foreground/90">{review.summary}</p>
      </div>

      <ReviewList title="Key Takeaways" items={review.key_takeaways} />

      <div className="grid gap-3 md:grid-cols-2">
        <TradeCallout title="Best Trade" trade={review.best_trade} tone="good" />
        <TradeCallout title="Weakest Trade" trade={review.worst_trade} tone="bad" />
      </div>

      <ReviewList title="Patterns" items={review.patterns} />
      <ReviewList title="Next Session Rules" items={review.next_session_rules} />
    </div>
  );
}

function ReviewList({ title, items }: { title: string; items: string[] }) {
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
