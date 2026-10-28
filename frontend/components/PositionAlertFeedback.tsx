"use client";
import { useState } from "react";
import { apiUrl } from "@/lib/api";
import { ALERT_FEEDBACK_LABELS, feedbackTime, type AlertFeedback, type AlertFeedbackRating } from "@/lib/alertFeedback";

export default function PositionAlertFeedback({ tradeId, alertId, initial }: {
  tradeId: string; alertId: string; initial: AlertFeedback | null;
}) {
  const [saved, setSaved] = useState(initial);
  const [editing, setEditing] = useState(!initial);
  const [rating, setRating] = useState<AlertFeedbackRating | null>(initial?.rating ?? null);
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  async function save() {
    if (!rating || saving) return;
    setSaving(true); setError(null);
    try {
      const response = await fetch(apiUrl(`/trades/${encodeURIComponent(tradeId)}/phone-alerts/${encodeURIComponent(alertId)}/feedback`), {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, reason: reason.trim() || null, base_version: saved?.version ?? 0 }),
      });
      if (!response.ok) {
        if (response.status === 409) {
          setConflict(true);
          throw new Error("Feedback may have changed. Your draft is still here; reload to check the saved response before editing.");
        }
        throw new Error("Save could not be confirmed. Your draft is still here; try again.");
      }
      setSaved(await response.json()); setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save could not be confirmed. Please try again.");
    } finally { setSaving(false); }
  }

  return <div className="space-y-2 border-t pt-3" data-testid="position-alert-feedback">
    <h4 className="text-sm font-semibold">Was this alert useful?</h4>
    <p className="text-xs text-muted-foreground">Your assessment of the notification, separate from what the trade earned.</p>
    {saved && <div className="space-y-1 text-xs" role="status">
      <p>Saved: <span className="font-medium">{ALERT_FEEDBACK_LABELS[saved.rating]}</span></p>
      {saved.reason && <p className="whitespace-pre-wrap break-words">{saved.reason}</p>}
      <p className="text-muted-foreground">{saved.version > 1 ? "Updated" : "Recorded"} {feedbackTime(saved.updated_at)}</p>
    </div>}
    {editing ? <form className="space-y-2" onSubmit={e => { e.preventDefault(); void save(); }}>
      <fieldset disabled={saving || conflict} className="grid grid-cols-2 gap-2">
        <legend className="sr-only">Your response</legend>
        {(Object.entries(ALERT_FEEDBACK_LABELS) as [AlertFeedbackRating, string][]).map(([value, label]) =>
          <label key={value} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-2 py-2 text-xs ${rating === value ? "border-primary bg-primary/10" : "hover:bg-muted"}`}>
            <input type="radio" name={`alert-feedback-${alertId}`} value={value} checked={rating === value}
              onChange={() => setRating(value)} />{label}
          </label>)}
      </fieldset>
      <label className="block text-xs">Reason (optional)
        <textarea value={reason} maxLength={500} rows={2} disabled={saving || conflict} onChange={e => setReason(e.target.value)}
          className="mt-1 block w-full rounded-md border bg-background p-2 text-sm" />
      </label>
      {error && <p role="alert" className="text-xs text-amber-300">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={!rating || saving || conflict} className="min-h-11 rounded-md bg-primary px-3 font-medium text-primary-foreground disabled:opacity-50">
          {saving ? "Saving…" : "Save feedback"}
        </button>
        {saved && <button type="button" disabled={saving} className="min-h-11 rounded-md border px-3" onClick={() => {
          setEditing(false); setRating(saved.rating); setReason(saved.reason ?? ""); setError(null); setConflict(false);
        }}>Cancel edit</button>}
        {conflict && <button type="button" className="min-h-11 rounded-md border px-3" onClick={() => window.location.reload()}>Reload saved feedback</button>}
      </div>
    </form> : <button type="button" className="min-h-11 rounded-md border px-3 text-xs" onClick={() => setEditing(true)}>Edit feedback</button>}
  </div>;
}
