"use client";

import { useEffect, useState } from "react";
import { CHOICE } from "@/components/copilot/ProofAnswers";
import { ALERT_FEEDBACK_LABELS, saveAlertFeedback, type AlertFeedbackRating } from "@/lib/alertFeedback";
import { saveRating, type Rating } from "@/lib/copilot";
import { getToRate, type ToRate, type ToRateItem } from "@/lib/desk";
import { rateEvent, RATINGS, type RadarRating } from "@/lib/radar";

const NY = "America/New_York";
const TYPE = { alert: "Alert", radar: "Radar", answer: "Answer" } as const;
const LABEL: Record<string, string> = { ...ALERT_FEEDBACK_LABELS, ...Object.fromEntries(RATINGS.map(r => [r.value, r.label])), helped: "Helped", didnt: "Didn't" };
const dayOf = (at: number) => new Date(at * 1000).toLocaleDateString("en-CA", { timeZone: NY });
const when = (at: number, today: string) => new Date(at * 1000).toLocaleString("en-US", {
  timeZone: NY, ...(dayOf(at) === today ? {} : { weekday: "short" }), hour: "numeric", minute: "2-digit" });

/** Saves one rating through the item's own route: the trade page's alert feedback, the Radar feed's rating, or an answer's Helped / Didn't. */
function save(item: ToRateItem, answer: string) {
  if (item.type === "alert") return saveAlertFeedback(item.trade_id, item.id, answer as AlertFeedbackRating, null, 0);
  if (item.type === "radar") return rateEvent(item.event_id, answer as RadarRating);
  return saveRating(item.investigation_id, item.index, answer as Rating);
}

/**
 * Rate yesterday, at the top of today's Main chat (docs/copilot-lab.md § The desk): every position alert, alerted Radar
 * hit and copilot answer since the previous trading session still waiting on a rating (``GET /copilot/desk/to-rate``),
 * newest first, each with one-tap answers saved through its existing route. A saved row leaves the card; the card hides
 * once nothing is left. An alert answered somewhere else since the read leaves too. Read once when Main chat opens.
 */
export default function RateYesterday() {
  const [data, setData] = useState<ToRate | null>(null);
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const [saving, setSaving] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getToRate(controller.signal).then(read => { setData(read); setDone(new Set()); }).catch(() => { /* the card is optional: nothing shows */ });
    return () => controller.abort();
  }, []);

  const left = data?.items.filter(item => !done.has(item.key)) ?? [];
  const more = data ? Math.max(0, data.count - data.items.length) : 0;
  // Everything listed is rated but older items wait past the cap: read the next ones.
  useEffect(() => {
    if (!data || left.length || !more) return;
    const controller = new AbortController();
    getToRate(controller.signal).then(read => { setData(read); setDone(new Set()); }).catch(() => {});
    return () => controller.abort();
  }, [data, left.length, more]);

  async function rate(item: ToRateItem, answer: string) {
    if (saving[item.key]) return;
    setSaving(prev => ({ ...prev, [item.key]: answer }));
    setErrors(prev => ({ ...prev, [item.key]: "" }));
    try {
      await save(item, answer);
      setStatus(`Saved: ${TYPE[item.type]} ${item.label} · ${LABEL[answer] ?? answer}`);
      setDone(prev => new Set(prev).add(item.key));
    } catch (err) {
      if (item.type === "alert" && err instanceof Error && err.message === "conflict") {
        setStatus(`${TYPE[item.type]} ${item.label} was already answered somewhere else.`);
        setDone(prev => new Set(prev).add(item.key));
      } else {
        setErrors(prev => ({ ...prev, [item.key]: "The rating could not be saved. Try again." }));
      }
    } finally {
      setSaving(prev => Object.fromEntries(Object.entries(prev).filter(([key]) => key !== item.key)));
    }
  }

  if (!data || !left.length) return null;
  const waiting = left.length + more;
  return (
    <section aria-label="Rate yesterday" data-testid="rate-yesterday" className="mb-6 min-w-0 rounded-lg border bg-card px-4 py-3">
      <header className="mb-2 flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
        <h3 className="text-sm font-semibold text-foreground">Rate yesterday</h3>
        <span className="tabular-nums">{waiting} waiting</span>
        <span>· Your ratings count on Proof.</span>
      </header>
      <ul className="divide-y">
        {left.map(item => (
          <li key={item.key} data-testid="rate-row" className="min-w-0 space-y-1.5 py-2.5 first:pt-0 last:pb-0">
            <p className="break-words text-xs">
              <span className="font-medium text-foreground">{TYPE[item.type]} · {item.label}</span>
              <span className="tabular-nums text-muted-foreground"> · {when(item.at, data.day)}</span>
            </p>
            {item.detail && <p className="line-clamp-2 break-words text-xs text-muted-foreground">{item.detail}</p>}
            <div role="group" aria-label={`Rate ${TYPE[item.type].toLowerCase()} ${item.label}`} className="flex flex-wrap gap-1.5">
              {(item.answers as string[]).map(answer => (
                <button key={answer} type="button" disabled={!!saving[item.key]} onClick={() => void rate(item, answer)} className={CHOICE}>
                  {saving[item.key] === answer ? "Saving…" : LABEL[answer] ?? answer}
                </button>
              ))}
            </div>
            {errors[item.key] && <p role="alert" className="text-xs text-amber-300">{errors[item.key]}</p>}
          </li>
        ))}
      </ul>
      {more > 0 && <p className="mt-2 text-xs text-muted-foreground">{more} older after these.</p>}
      {status && <p role="status" className="mt-2 break-words text-xs text-muted-foreground">{status}</p>}
    </section>
  );
}
