"use client";

import { useState } from "react";
import { paperLine, planSetup, scoreLine, setupWords, type RadarSetupCard, type RadarSetups as Setups } from "@/lib/radar";
import { cn } from "@/lib/utils";

const pnlTone = (pnl: number | null | undefined) =>
  pnl == null || pnl === 0 ? "text-muted-foreground" : pnl > 0 ? "text-emerald-400" : "text-red-400";

/** One setup card: the phone card's words, the paper result and Plan it (the Telegram tap's own path). */
export function SetupCard({ card, today, onPlanned }: { card: RadarSetupCard; today: string; onPlanned: (card: RadarSetupCard) => void }) {
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  async function plan() {
    setBusy(true); setReply(null);
    try {
      const out = await planSetup(card.id);
      if (out.plan_state && out.plan_state !== card.plan.state) {
        onPlanned({ ...card, plan: { ...card.plan, state: out.plan_state, investigation_id: out.investigation_id ?? card.plan.investigation_id,
          note: out.plan_state === "refused" ? out.reply : card.plan.note } });
      }
      setReply(out.reply);
    } catch { setReply("Plan it did not reach the server. Nothing was saved."); }
    setBusy(false);
  }
  const planned = card.plan.state === "planned";
  const refused = card.plan.state === "refused";
  const note = reply ?? (refused && card.plan.note ? `Not planned: ${card.plan.note}` : null);
  return (
    <li className="space-y-1.5 rounded-lg border bg-card p-3" data-testid="radar-setup">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <h3 className="text-sm font-semibold text-foreground">{card.title.replace(/^Radar setup: /, "")}</h3>
        <span className="text-xs text-muted-foreground">{card.created_at_ny}</span>
      </div>
      <p className="text-sm tabular-nums text-foreground">{card.levels_line}</p>
      {card.contract_line && <p className="break-words text-xs tabular-nums text-muted-foreground">{card.contract_line}</p>}
      {card.record && <p className="text-xs text-muted-foreground">{card.record}</p>}
      <p className={cn("text-xs tabular-nums", card.paper.state === "closed" ? pnlTone(card.paper.pnl) : "text-muted-foreground")}
        data-testid="radar-setup-paper">{paperLine(card)}</p>
      {(planned || (!refused && card.session_date === today) || note) && <div className="flex flex-wrap items-center gap-2 pt-0.5">
        {planned && <span className="inline-flex h-9 items-center rounded-md bg-secondary px-3 text-xs font-medium text-muted-foreground">Planned</span>}
        {!planned && !refused && card.session_date === today && (
          <button type="button" onClick={plan} disabled={busy}
            className="h-10 rounded-md border px-4 text-xs font-medium text-foreground hover:bg-secondary disabled:opacity-60 sm:h-9">
            {busy ? "Planning…" : "Plan it"}
          </button>
        )}
        {note && <p role="status" className="text-xs text-muted-foreground">{note}</p>}
      </div>}
    </li>
  );
}

/** One session's setup cards and one record strip per setup type and direction. */
export default function RadarSetups({ data, today, onPlanned }: { data: Setups; today: string; onPlanned: (card: RadarSetupCard) => void }) {
  return (
    <section aria-label="Setups" className="space-y-2" data-testid="radar-setups">
      <h2 className="text-[13.5px] font-semibold tracking-tight">Setups</h2>
      {data.setups.length === 0
        ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No setup cards for this session.</p>
        : <ul className="space-y-2">{data.setups.map((card) => <SetupCard key={card.id} card={card} today={today} onPlanned={onPlanned} />)}</ul>}
      {data.scorecard.length > 0 && (
        <div className="rounded-lg border bg-card px-3 py-2" aria-label="Setup record" data-testid="radar-setup-record">
          <p className="text-xs font-medium text-muted-foreground">Record, all sessions · paper results per contract</p>
          <ul className="mt-1 space-y-1">
            {data.scorecard.map((s) => (
              <li key={`${s.kind}:${s.direction}`} className="flex flex-wrap justify-between gap-x-3 text-xs tabular-nums">
                <span className="font-medium text-foreground">{setupWords(s.kind, s.direction)}</span>
                <span className={s.paper_closed ? pnlTone(s.paper_pnl) : "text-muted-foreground"}>{scoreLine(s)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
