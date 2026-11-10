"use client";

import { useEffect, useState } from "react";
import { ALERT_FEEDBACK_LABELS, saveAlertFeedback, type AlertFeedback, type AlertFeedbackRating } from "@/lib/alertFeedback";
import type { DeskAlertToAnswer } from "@/lib/desk";
import { getEvent, rateEvent, RATINGS, type RadarRating } from "@/lib/radar";
import { cn } from "@/lib/utils";

/**
 * The two answers /proof measures, offered (never counted as waiting) where the owner sees the pings and hits: a sent position alert's feedback
 * (``PUT /trades/{trade_id}/phone-alerts/{id}/feedback``, the trade page's route) and a Radar hit's rating
 * (``POST /radar/events/{id}/feedback``, the Radar feed's). One tap saves; an answered one is a line with Change.
 */

export const CHOICE = "inline-flex min-h-11 items-center rounded-md border px-2.5 text-xs font-medium hover:bg-secondary disabled:opacity-50 sm:min-h-8";
const LINK = "min-h-11 text-xs font-medium text-primary underline-offset-2 hover:underline sm:min-h-0";
const ALERT_KIND: Record<string, string> = { giveback: "Give-back", hold_hour: "Open an hour", expiry_first: "Expires today",
  expiry_final: "30 minutes to the close", expiry_eve: "Expires next session", wrong_way: "Wrong way at 30 min" };
const when = (at: number | null, today: boolean) => at == null ? "" : new Date(at * 1000).toLocaleString("en-US", {
  timeZone: "America/New_York", ...(today ? {} : { month: "short", day: "numeric" }), hour: "numeric", minute: "2-digit" });

/** One sent position alert: its four answers and an optional reason saved with the tap. */
export function AlertAnswer({ alert, onAnswered }: { alert: DeskAlertToAnswer; onAnswered?(id: string): void }) {
  const [saved, setSaved] = useState<AlertFeedback | null>(alert.feedback);
  const [editing, setEditing] = useState(!alert.feedback);
  const [reason, setReason] = useState(alert.feedback?.reason ?? "");
  const [saving, setSaving] = useState<AlertFeedbackRating | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(rating: AlertFeedbackRating) {
    if (saving) return;
    setSaving(rating); setError(null);
    try {
      setSaved(await saveAlertFeedback(alert.trade_id, alert.id, rating, reason, saved?.version ?? 0));
      setEditing(false);
      onAnswered?.(alert.id);
    } catch (err) {
      setError(err instanceof Error && err.message === "conflict"
        ? "This answer changed somewhere else. Reload the desk to see it before changing it."
        : err instanceof Error ? err.message : "Save could not be confirmed. Try again.");
    } finally { setSaving(null); }
  }

  return (
    <div data-testid="alert-answer" className="min-w-0 space-y-1.5">
      <p className="text-xs">
        <span className="font-medium text-foreground">{ALERT_KIND[alert.kind] ?? alert.kind} · {alert.contract}</span>
        <span className="text-muted-foreground"> · {when(alert.at, alert.today)}</span>
      </p>
      {saved && !editing ? (
        <p role="status" className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
          <span className="min-w-0 break-words">Answered: <span className="font-medium text-foreground">{ALERT_FEEDBACK_LABELS[saved.rating]}</span>
            {saved.reason && <> · {saved.reason}</>}</span>
          <button type="button" className={LINK} onClick={() => { setReason(saved.reason ?? ""); setEditing(true); }}>Change</button>
        </p>
      ) : (
        <>
          <input value={reason} maxLength={500} onChange={e => setReason(e.target.value)} disabled={!!saving}
            aria-label={`Reason for the ${alert.symbol} alert (optional)`} placeholder="Reason (optional)"
            className="block min-h-11 w-full max-w-md rounded-md border bg-background px-2 text-xs sm:min-h-8" />
          <div role="group" aria-label="Was this alert useful?" className="flex flex-wrap gap-1.5">
            {(Object.entries(ALERT_FEEDBACK_LABELS) as [AlertFeedbackRating, string][]).map(([value, label]) => (
              <button key={value} type="button" disabled={!!saving} onClick={() => void save(value)} aria-pressed={saved?.rating === value}
                className={cn(CHOICE, saved?.rating === value && "border-primary bg-primary/10")}>
                {saving === value ? "Saving…" : label}
              </button>
            ))}
            {saved && <button type="button" className={LINK} onClick={() => { setEditing(false); setError(null); }}>Cancel</button>}
          </div>
          {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
        </>
      )}
    </div>
  );
}

/** One Radar hit's rating: Useful, Already knew, Too late or Irrelevant. The newest rating is the one /proof counts. */
export function HitRating({ eventId, initial, onRated }: { eventId: string; initial: RadarRating | null; onRated?(id: string): void }) {
  const [saved, setSaved] = useState(initial);
  const [editing, setEditing] = useState(!initial);
  const [saving, setSaving] = useState<RadarRating | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function rate(rating: RadarRating) {
    if (saving) return;
    setSaving(rating); setError(null);
    try {
      setSaved((await rateEvent(eventId, rating)).rating);
      setEditing(false);
      onRated?.(eventId);
    } catch { setError("The rating could not be saved. Try again."); } finally { setSaving(null); }
  }

  if (saved && !editing) return (
    <p role="status" className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
      <span>Rated: <span className="font-medium text-foreground">{RATINGS.find(r => r.value === saved)?.label}</span></span>
      <button type="button" className={LINK} onClick={() => setEditing(true)}>Change</button>
    </p>
  );
  return (
    <>
      <div role="group" aria-label="Rate this Radar hit" className="flex flex-wrap gap-1.5">
        {RATINGS.map(({ value, label }) => (
          <button key={value} type="button" disabled={!!saving} onClick={() => void rate(value)} aria-pressed={saved === value}
            className={cn(CHOICE, saved === value && "border-primary bg-primary/10")}>
            {saving === value ? "Saving…" : label}
          </button>
        ))}
        {saved && <button type="button" className={LINK} onClick={() => { setEditing(false); setError(null); }}>Cancel</button>}
      </div>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
    </>
  );
}

const SECTION = "rounded-lg border bg-card p-3";

/** A position's thread: the alerts sent today for its symbol, each asking whether it was useful. Nothing when none. */
export function ThreadAlertAnswers({ symbol, rows }: { symbol: string | null; rows: DeskAlertToAnswer[] | undefined }) {
  const today = (rows ?? []).filter(r => r.today && r.symbol === symbol);
  if (!symbol || !today.length) return null;
  return (
    <section aria-label="Today's alerts" data-testid="thread-alert-answers" className={cn(SECTION, "space-y-3")}>
      <p className="text-xs text-muted-foreground">Was {today.length === 1 ? "this alert" : "each alert"} useful? Optional; an answer counts on Proof.</p>
      {today.map(alert => <AlertAnswer key={alert.id} alert={alert} />)}
    </section>
  );
}

/** A Radar hit's thread: its rating, beside the hit's decision. Reads the hit's current rating once. */
export function ThreadHitRating({ eventId }: { eventId: string }) {
  const [read, setRead] = useState<{ rating: RadarRating | null } | null>(null);
  useEffect(() => {
    let active = true;
    getEvent(eventId).then(detail => { if (active) setRead({ rating: detail.rating }); }).catch(() => { /* RadarDecision says so */ });
    return () => { active = false; };
  }, [eventId]);
  if (!read) return null;
  return (
    <section aria-label="Rate this hit" data-testid="thread-hit-rating" className={cn(SECTION, "mb-4 space-y-2")}>
      <p className="text-xs text-muted-foreground">Did Radar find this early enough to matter? Optional; a rating counts on Proof.</p>
      <HitRating eventId={eventId} initial={read.rating} />
    </section>
  );
}
