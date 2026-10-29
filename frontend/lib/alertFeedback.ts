import { apiUrl } from "@/lib/api";

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

/** Saves the owner's answer for one sent position alert (the trade page's form and the desk's buttons); 409 is ``conflict``. */
export async function saveAlertFeedback(tradeId: string, alertId: string, rating: AlertFeedbackRating, reason: string | null,
  baseVersion: number): Promise<AlertFeedback> {
  const response = await fetch(apiUrl(`/trades/${encodeURIComponent(tradeId)}/phone-alerts/${encodeURIComponent(alertId)}/feedback`), {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, reason: reason?.trim() || null, base_version: baseVersion }),
  });
  if (!response.ok) throw new Error(response.status === 409 ? "conflict" : "Save could not be confirmed. Try again.");
  return response.json();
}
