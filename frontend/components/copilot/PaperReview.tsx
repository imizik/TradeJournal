"use client";

import type { PaperReview } from "@/lib/paperBook";

/**
 * The top of the desk's Paper section (docs/copilot-lab.md § Paper): the "How am I doing?" chip, which asks the copilot
 * (it reads the paper book with get_paper_book), and the newest Friday paper review with its date, shown until the next
 * one. The review is the copilot's, written from the week's paper and real trades after Friday's close.
 */

export const PAPER_QUESTION = "How am I doing on paper?";

/** "Fri Nov 13" for the review's Friday (a calendar date, so read in UTC). */
const friday = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });

export default function PaperReviewCard({ review, onAsk }: { review: PaperReview | null | undefined; onAsk(text: string): void }) {
  const lines = (review?.text ?? "").split("\n").map(line => line.trim()).filter(Boolean);
  return (
    <div data-testid="paper-review" className="space-y-1 px-3 pb-2">
      <div className="flex flex-wrap items-center gap-2">
        {review && <p className="text-[11px] font-medium uppercase tracking-wide text-amber-200">Paper review · {friday(review.day)}</p>}
        <button type="button" data-testid="paper-how-am-i-doing" onClick={() => onAsk(PAPER_QUESTION)}
          className="ml-auto inline-flex min-h-11 items-center rounded-full border border-amber-400/50 px-3 text-xs text-amber-100 hover:bg-amber-400/10 sm:min-h-7">
          How am I doing?
        </button>
      </div>
      {review && (
        <div data-testid="paper-review-text" className="space-y-0.5 text-xs leading-snug">
          {lines.map((line, i) => {
            const label = /^(Week|Worked|Stops and targets|Next week):\s*/.exec(line);
            return label
              ? <p key={i}><span className="text-muted-foreground">{label[1]}: </span>{line.slice(label[0].length)}</p>
              : <p key={i} className="text-muted-foreground">{line}</p>;
          })}
        </div>
      )}
    </div>
  );
}
