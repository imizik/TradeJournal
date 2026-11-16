"use client";

/*
 * The copilot's paper order card (docs/copilot-lab.md § Paper): what he dictated ("paper 2 NBIS 100c Friday, stop 96",
 * "close my paper NBIS") drafted by ``draft_paper_order``. One line of contract, the live price it would fill at (the ask
 * to buy, the bid to sell) with the quote's time, the cash and the paper buying power left (or, closing, the P&L), his
 * stop and target, and one button: Fill on paper (Close on paper, Trim on paper). The tap goes through the paper book's
 * own route, which re-reads the quote and fills at that moment's price. A price older than the book's freshness window,
 * or none, is greyed with its time and the button is off until Refresh price reads a new one. Edit opens the full
 * confirm, prefilled. Paper only: nothing is placed anywhere.
 */

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { Proposal, ProposalOutcome } from "@/lib/copilot";
import {
  PaperRefused, draftOrder, draftPreview, fillClose, fillOpen, previewClose, previewOpen,
  type PaperDraft, type PaperDraftPreview, type PaperFill,
} from "@/lib/paperBook";
import { cn } from "@/lib/utils";
import { CloseRow, PaperButton } from "./DeskPaper";
import { RulesChecklist } from "./DeskRules";
import ModeMark from "./ModeMark";

export type PaperOrderProposal = Extract<Proposal, { kind: "paper_order" }>;

/** The paper book's freshness window: a fill's quote is at most this old (backend ``paper_book.FRESH_SECONDS``). */
export const FRESH_SECONDS = 120;
const BUTTON = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8";

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const price = (n: number) => n.toFixed(Math.abs(n) < 1 && n !== 0 ? 4 : 2).replace(/(\.\d\d)00$/, "$1");
const at = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit" }) + " ET";

/** The order in one line: "Buy 2 × NBIS $100 Call 11/20/26", "Buy 50 NBIS shares", "Trim NBIS $100 Call 11/20/26 · sell 2 of 5". */
export function draftLine(d: PaperDraft): string {
  const n = d.quantity.toLocaleString("en-US");
  if (d.action === "open") return d.multiplier === 1 ? `Buy ${n} ${d.label}` : `Buy ${n} × ${d.label}`;
  if (d.action === "close") return `Close ${d.label} · all ${n}`;
  return `Trim ${d.label} · sell ${n} of ${d.held.toLocaleString("en-US")}`;
}

const VERB = { open: "Fill on paper", close: "Close on paper", trim: "Trim on paper" } as const;

/** One order key per card: a retried or second tap, even after a reload, records one fill. */
const keyFor = (id: string) => `paper-card-${id}`.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);

/** What a fill did, in one line. */
function doneLine(d: PaperDraft, fill: PaperFill): string {
  const legs = Object.values(fill.legs);
  const each = legs.length === 1 ? `${price(legs[0].price)} (the ${legs[0].action === "buy" ? "ask" : "bid"})` : `${price(Math.abs(fill.per_share))} net`;
  const what = `${fill.quantity.toLocaleString("en-US")}${d.multiplier === 1 ? "" : " ×"} ${fill.label}`;
  if (d.action === "open") return `Paper: bought ${what} at ${each}, quote ${at(fill.quoted_at)}: costs ${usd(fill.cash)}.`;
  return `Paper: sold ${what} at ${each}, quote ${at(fill.quoted_at)}: ${fill.cash >= 0 ? "brings in" : "costs"} ${usd(fill.cash)}, ${fill.pnl! >= 0 ? "made" : "lost"} ${usd(fill.pnl!)}.`;
}

/** The seconds clock, ticking every 15 s so a price greys out once it is older than the window. */
function useNow() {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now() / 1000), 15_000); return () => window.clearInterval(t); }, []);
  return now;
}

export default function PaperOrderCard({ proposal, onOutcome }: { proposal: PaperOrderProposal; onOutcome(outcome: ProposalOutcome): void }) {
  const d = proposal as unknown as PaperDraft;
  const id = proposal.client_id ?? proposal.id;
  const saved = proposal.outcome;
  const [phase, setPhase] = useState<"open" | "working" | "done" | "dismissed">(saved?.state === "dismissed" ? "dismissed" : saved?.state === "confirmed" ? "done" : "open");
  const [preview, setPreview] = useState<PaperDraftPreview | null>(d.preview);
  const [issue, setIssue] = useState<string | null>(d.issue);
  const [note, setNote] = useState<string | null>(saved?.note ?? null);
  const [failed, setFailed] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [rulesShown, setRulesShown] = useState(d.action !== "open"); // an opening fill waits until his rules are on the card
  const now = useNow();
  if (phase === "dismissed") return null;

  const order = draftOrder(d);
  const closing = d.action !== "open";
  const fresh = !!preview && now - preview.quoted_at <= FRESH_SECONDS;
  const open = phase === "open";

  async function refresh() {
    setPhase("working"); setFailed(null);
    try {
      const found = d.action === "open" ? await previewOpen(order!, d.quantity) : await previewClose(d.position_id, d.quantity);
      setPreview(draftPreview(found, closing)); setIssue(null);
    } catch (e) { setIssue(e instanceof Error ? e.message : "No quote right now."); }
    finally { setPhase("open"); }
  }

  async function fill() {
    if (!fresh || !rulesShown) return;
    setPhase("working"); setFailed(null);
    try {
      const filled = d.action === "open"
        ? await fillOpen(order!, d.quantity, { stop: d.stop ?? null, target: d.target ?? null, rule_answers: ticked,
            ...(d.idea === "copilot" ? { source: "copilot" as const, idea_id: keyFor(id) } : {}) }, keyFor(id))
        : await fillClose(d.position_id, d.quantity, keyFor(id));
      const text = filled ? doneLine(d, filled) : "Already filled on paper.";
      setNote(text); setPhase("done");
      onOutcome({ state: "confirmed", note: text });
    } catch (e) {
      setFailed(e instanceof PaperRefused || e instanceof Error ? e.message : "Not filled.");
      setPhase("open");
    }
  }

  function edited(text: string) {
    setNote(text); setPhase("done");
    onOutcome({ state: "confirmed", note: text });
  }

  const money = preview && (closing
    ? <>{preview.cash >= 0 ? "Brings in" : "Costs"} {usd(preview.cash)}{preview.pnl != null && <> · P&amp;L <span className={preview.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>{signed(preview.pnl)}</span></>}</>
    : <>Costs {usd(preview.cash)}{preview.buying_power_after != null && <> · buying power left {preview.buying_power_after < 0 ? "−" : ""}{usd(preview.buying_power_after)}{preview.buying_power_after < 0 && " (not enough)"}</>}</>);
  const quoteWords = preview && (preview.price != null && preview.side ? `${preview.side === "ask" ? "Fills at the ask" : "Fills at the bid"} ${price(preview.price)}`
    : `Fills at the natural price ${price(Math.abs(preview.per_share))} net`);
  const levels = d.action === "open" && (d.stop != null || d.target != null)
    ? [d.stop != null && `Stop ${d.stop}`, d.target != null && `Target ${d.target}`].filter(Boolean).join(" · ") : null;
  const entry = d.action === "open" && open && fresh && preview
    ? { side: "paper" as const, instrument: d.instrument, expiry: d.expiry ?? null, size: Math.abs(preview.cash), stop: d.stop ?? null } : null;

  return (
    <section aria-label="Paper order" data-testid="paper-order-card" data-action={d.action} data-phase={phase}
      className="mt-2 space-y-1.5 rounded-md border border-dashed border-violet-400/50 p-2.5 text-xs">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ModeMark mode="paper" short />
        <span data-testid="paper-order-line" className="min-w-0 flex-1 font-medium text-foreground">{draftLine(d)}</span>
        {(open || phase === "working") && (
          <button type="button" aria-label="Dismiss" title="Dismiss" onClick={() => { setPhase("dismissed"); onOutcome({ state: "dismissed" }); }}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded text-muted-foreground hover:text-foreground sm:min-h-6 sm:min-w-6">
            <X size={13} aria-hidden />
          </button>
        )}
      </p>
      {phase !== "done" && d.picked.map(line => <p key={line} data-testid="paper-order-picked" className="text-amber-200/90">{line}</p>)}
      {phase !== "done" && (preview ? (
        <div data-testid="paper-order-price" data-fresh={fresh} className={cn("space-y-0.5 tabular-nums", !fresh && "text-muted-foreground")}>
          <p>{quoteWords} · quote {at(preview.quoted_at)}{!fresh && ", not live"}</p>
          <p>{money}</p>
        </div>
      ) : (
        <p data-testid="paper-order-price" data-fresh="false" className="text-muted-foreground">No live price: {issue ?? "no quote yet."}</p>
      ))}
      {phase !== "done" && preview && issue && <p className="text-muted-foreground">{issue}</p>}
      {phase !== "done" && levels && <p data-testid="paper-order-levels" className="text-muted-foreground tabular-nums">{levels} (stock prices)</p>}
      {entry && <RulesChecklist entry={entry} ticked={ticked} onTick={(rule, on) => setTicked(t => ({ ...t, [rule]: on }))} onResults={() => setRulesShown(true)} />}
      {(open || phase === "working") && !editing && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" data-testid="paper-order-fill" disabled={!fresh || !rulesShown || phase === "working"} onClick={() => void fill()}
            title={fresh ? "Fills on paper at the live quote when you tap: no money, nothing sent" : "No live price: refresh it first"}
            className={cn(BUTTON, "border-violet-400/70 text-violet-100")}>{phase === "working" ? "Working…" : VERB[d.action]}</button>
          {!fresh && <button type="button" data-testid="paper-order-refresh" disabled={phase === "working"} onClick={() => void refresh()} className={BUTTON}>Refresh price</button>}
          {open && <button type="button" data-testid="paper-order-edit" onClick={() => setEditing(true)} className={QUIET}>Edit</button>}
        </div>
      )}
      {/* Edit: the full confirm, prefilled. Once it fills (or places a limit) the card is done, so it cannot fill twice. */}
      {/* The card's own key: a fill the card already made (its reply lost, or before a reload) answers "Already filled". */}
      {editing && (d.action === "open"
        ? <PaperButton order={order} quantity={d.quantity} stop={d.stop ?? null} target={d.target ?? null} autoOpen onFilled={edited} fixedKey={keyFor(id)}
            source={d.idea === "copilot" ? "copilot" : "mine"} ideaId={d.idea === "copilot" ? keyFor(id) : null} onClose={() => setEditing(false)} />
        : <CloseRow position={{ id: d.position_id, remaining: d.held, held: 0, multiplier: d.multiplier, instrument: d.instrument, credit: d.credit }}
            trim quantity={d.quantity} onFilled={edited} fixedKey={keyFor(id)} onDone={() => setEditing(false)} />)}
      {failed && <p role="alert" className="text-amber-300">{failed}</p>}
      {phase === "done" && note && !editing && <p role="status" data-testid="paper-order-done" className="text-emerald-300">{note}</p>}
    </section>
  );
}
