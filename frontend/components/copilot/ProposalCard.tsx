"use client";

import { useRef, useState } from "react";
import { createWatch, enqueueRevisit, freshQuote, operationId, saveMemory, type Proposal } from "@/lib/copilot";

const CONDITION: Record<string, string> = { touches: "touches", crosses: "crosses", closes_beyond: "closes beyond" };
const number = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 4 });

/** What the card says will be created, exactly as Confirm sends it. */
export function proposalText(proposal: Proposal): string {
  if (proposal.kind === "memory") return `${proposal.memory_kind}${proposal.symbol ? ` · ${proposal.symbol}` : ""}`;
  if (proposal.kind === "revisit") return `Research again in ${proposal.horizon_days} day${proposal.horizon_days === 1 ? "" : "s"}: ${proposal.question}`;
  const close = proposal.condition === "closes_beyond" ? `${proposal.interval} close beyond` : CONDITION[proposal.condition];
  return `${proposal.symbol} ${close} ${number(proposal.price)}`;
}

/** A proposal from the model: nothing exists until the owner presses Confirm. */
export default function ProposalCard({ proposal, investigationId, alertsSupported, onDone }: {
  proposal: Proposal; investigationId: string | null; alertsSupported: boolean; onDone(): void;
}) {
  const [phase, setPhase] = useState<"open" | "confirming" | "done" | "dismissed">("open");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState(proposal.kind === "memory" ? proposal.text : "");
  const operation = useRef(operationId());  // one id per card: a retried Confirm replays, never duplicates
  if (phase === "dismissed") return null;
  const watch = proposal.kind === "watch";
  const memory = proposal.kind === "memory";
  const title = watch ? "Proposed watch" : memory ? "Proposed memory" : "Proposed revisit";
  // A memory needs no investigation: it is saved to the memory store as the owner's own words.
  const ready = memory ? text.trim().length > 0 : !!investigationId;

  async function confirm() {
    if (!ready || phase !== "open") return;
    setPhase("confirming");
    setError(null);
    try {
      if (proposal.kind === "memory") {
        await saveMemory(proposal, text.trim(), investigationId, operation.current);
        setNote(`Remembered (${proposal.memory_kind}${proposal.symbol ? `, ${proposal.symbol}` : ""}). It joins your approved memories from the next turn.`);
      } else if (proposal.kind === "watch") {
        // The side the alert waits on comes from the price now, so a stale or missing quote is refused.
        const quote = await freshQuote(proposal.symbol);
        if (!quote.fresh || quote.last === null) throw new Error(`The latest ${proposal.symbol} quote is stale or missing, so the alert was not set. Try again in a moment.`);
        if (quote.last === proposal.price) throw new Error(`${proposal.symbol} is at ${number(proposal.price)} now, so the alert has no side to wait on.`);
        await createWatch(investigationId!, proposal, quote.last);
        setNote(`Alert set: ${proposalText(proposal)} (${proposal.symbol} was ${number(quote.last)}).`);
      } else {
        const made = await enqueueRevisit(investigationId!, proposal.question, proposal.horizon_days);
        const queued = made.created ? "Revisit queued." : "This revisit was already queued today.";
        setNote(made.queue_enabled ? queued : `${queued} The research queue is off, so it waits until the queue is turned on.`);
      }
      setPhase("done");
      onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "That was not confirmed.");
      setPhase("open");
    }
  }

  return (
    <section aria-label={title} className="mt-2 space-y-1.5 rounded border border-sky-500/30 bg-sky-500/5 p-2 text-xs">
      <p className="font-medium text-foreground">{title} · {proposalText(proposal)}</p>
      {proposal.kind === "watch" && (
        <>
          <p className="text-muted-foreground">Label: {proposal.label}</p>
          <p className="text-muted-foreground">Why: {proposal.why}</p>
        </>
      )}
      {proposal.kind === "memory" && (
        <>
          {phase === "done"
            ? <p className="whitespace-pre-wrap text-foreground">{text}</p>
            : <textarea value={text} onChange={e => setText(e.target.value.slice(0, 4000))} rows={3} aria-label="Memory text"
                disabled={phase === "confirming"}
                className="w-full rounded border bg-background px-2 py-1 text-base text-foreground sm:text-sm" />}
          {proposal.interpretation && <p className="text-muted-foreground">How it will be used: {proposal.interpretation}</p>}
          {phase !== "done" && <p className="text-muted-foreground">Your words, saved as an approved memory when you confirm. Edit first if the paraphrase is off.</p>}
        </>
      )}
      {phase === "done" ? <p role="status" className="text-emerald-300">{note}</p> : (
        <div className="flex flex-wrap items-center gap-2">
          {watch && !alertsSupported
            ? <span className="text-muted-foreground">Awaiting alert support: watches cannot be confirmed here yet.</span>
            : <button type="button" onClick={() => void confirm()} disabled={!ready || phase === "confirming"}
                className="min-h-11 rounded bg-primary px-3 py-1 text-primary-foreground disabled:opacity-40 sm:min-h-0">
                {phase === "confirming" ? "Confirming…" : !ready && !memory ? "Saving…" : "Confirm"}</button>}
          <button type="button" onClick={() => setPhase("dismissed")} disabled={phase === "confirming"}
            className="min-h-11 rounded border px-3 py-1 text-muted-foreground hover:text-foreground disabled:opacity-40 sm:min-h-0">Dismiss</button>
          <span className="text-muted-foreground">{memory ? "Nothing is remembered until you confirm." : "Nothing is active until you confirm."}</span>
        </div>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </section>
  );
}
