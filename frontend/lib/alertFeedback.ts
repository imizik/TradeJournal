export const ALERT_FEEDBACK_LABELS = {
  prompted_review: "Prompted a review",
  already_aware: "Already aware",
  too_late: "Too late",
  not_useful: "Not useful",
} as const;

export type AlertFeedbackRating = keyof typeof ALERT_FEEDBACK_LABELS;
export type AlertFeedback = { rating: AlertFeedbackRating; reason: string | null; version: number;
  created_at: number; updated_at: number };

export const feedbackTime = (at: number) => new Date(at * 1000).toLocaleString("en-US", {
  timeZone: "America/New_York", year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
}) + " ET";
