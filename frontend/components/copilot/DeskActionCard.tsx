"use client";

/*
 * A desk action card (docs/copilot-lab.md § Desk actions): the copilot's ``desk_action`` result, one line saying exactly
 * what will happen, a button with the verb and Dismiss. A view change (``show``) applies itself when it arrives in this
 * tab, with Undo; every other card does nothing until the tap, which calls the desk's own route (``lib/deskAction.ts``).
 * A card a day old, or one whose plan or price has moved, says so and asks again instead of acting. The ticket stays
 * copy-only; nothing here places, stages or sends an order.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { cleanLevel, todayNewYork, validSymbol } from "@/lib/charts";
import { CHART_SETTINGS_SAVED, useChartSettings } from "@/lib/chartSync";
import { applyEdit, MAX_LEVELS } from "@/lib/drawings";
import type { Proposal, ProposalOutcome } from "@/lib/copilot";
import { DESK_CHANGED_EVENT, DESK_VIEW_EVENT, Stale, actionLine, actionVerb, applyShow, arrived, runAction, showOnDesk, staleByAge, undoFor,
  undoShow, type CentreTab, type DeskAction, type DeskView, type Done } from "@/lib/deskAction";
import { cn } from "@/lib/utils";

export type DeskActionProposal = Extract<Proposal, { kind: "desk_action" }>;

const BUTTON = "inline-flex min-h-11 items-center rounded px-3 py-1 text-xs sm:min-h-0";

/** Draws the card's level through the chart settings' own store and sync (the desk's drawings), then reports. */
function DrawLevel({ card, onDone, onFail }: { card: Extract<DeskAction, { action: "draw" }>; onDone(done: Done): void; onFail(why: string): void }) {
  const { settings, setSettings, ready, sync } = useChartSettings(undefined, { borrowed: true });
  const placed = useRef(false);
  const saving = useRef(false);
  const reported = useRef(false);
  useEffect(() => {
    if (!ready || placed.current) return;
    placed.current = true;
    const levels = settings.levels[card.symbol] ?? [];
    if (!validSymbol(card.symbol)) { reported.current = true; onFail(`${card.symbol} cannot carry a level.`); return; }
    if (levels.length >= MAX_LEVELS) { reported.current = true; onFail(`Remove a ${card.symbol} line first: ${MAX_LEVELS} per symbol.`); return; }
    const level = cleanLevel({ id: crypto.randomUUID(), price: card.price, label: card.label ?? `Level ${levels.length + 1}`, drawn_on: todayNewYork() });
    if (!level) { reported.current = true; onFail("That level could not be drawn."); return; }
    setSettings(s => {
      const next = applyEdit(s, { symbol: card.symbol, layer: "levels", before: null, after: level, index: (s.levels[card.symbol] ?? []).length }, "after") ?? s;
      return next.hiddenGroups.levels ? { ...next, hiddenGroups: { ...next.hiddenGroups, levels: false } } : next;
    });
  }, [ready, settings, card, setSettings, onFail]);
  useEffect(() => {
    if (!placed.current || reported.current) return;
    if (sync === "saving") saving.current = true;
    else if (sync === "saved" && saving.current) {
      reported.current = true;
      window.dispatchEvent(new Event(CHART_SETTINGS_SAVED)); // the desk chart's own copy reads the new level now
      onDone({ text: `Drawn: ${card.price.toFixed(2)} on ${card.symbol}${card.label ? ` (${card.label})` : ""}, on the desk chart and in Charts.`, symbol: card.symbol });
    } else if (sync === "offline") { reported.current = true; onFail("The chart settings could not be saved just now. Try again."); }
  }, [sync, card, onDone, onFail]);
  return <span className="text-muted-foreground">Drawing…</span>;
}

/** One desk action card. ``onOutcome`` keeps what happened with the conversation, as a proposal's outcome. */
export default function DeskActionCard({ proposal, onOutcome }: { proposal: DeskActionProposal; onOutcome(outcome: ProposalOutcome): void }) {
  const card = proposal as unknown as DeskAction;
  const id = proposal.client_id ?? proposal.id;
  const saved = proposal.outcome;
  const [phase, setPhase] = useState<"open" | "working" | "drawing" | "done" | "stale" | "failed" | "dismissed">(
    saved?.state === "dismissed" ? "dismissed" : saved?.state === "confirmed" ? "done" : "open");
  const [note, setNote] = useState<string | null>(saved?.note ?? null);
  const [shown, setShown] = useState<string | null>(null); // the symbol a done card can show on the desk
  const [undone, setUndone] = useState(false);
  const [noDesk, setNoDesk] = useState(false);

  const finish = useCallback((done: Done) => {
    setNote(done.text);
    setShown(done.symbol ?? null);
    setPhase("done");
    onOutcome({ state: "confirmed", note: done.text });
  }, [onOutcome]);
  const fail = useCallback((why: string) => { setNote(why); setPhase("failed"); }, []);

  // A view change applies itself once, when it arrived in this tab's stream; a reopened one waits for a tap.
  const applied = useRef(false);
  useEffect(() => {
    if (card.action !== "show" || applied.current || saved || !arrived(id)) return;
    applied.current = true;
    // The desk moved (or said it is not on this page): the card says so. Once, when it arrived.
    if (applyShow(id, card)) finish({ text: "Shown on the desk." }); // eslint-disable-line react-hooks/set-state-in-effect -- reports what the desk did
    else setNoDesk(true);
  }, [card, id, saved, finish]);

  if (phase === "dismissed") return null;

  async function tap() {
    if (phase === "working" || phase === "drawing") return;
    setNote(null);
    if (card.action === "show") {
      if (applyShow(id, card)) { setUndone(false); finish({ text: "Shown on the desk." }); }
      else setNoDesk(true);
      return;
    }
    const old = staleByAge(card, Date.now() / 1000);
    if (old) { setNote(old); setPhase("stale"); return; }
    if (card.action === "draw") { setPhase("drawing"); return; }
    setPhase("working");
    try {
      finish(await runAction(card, Date.now() / 1000));
    } catch (failure) {
      const why = failure instanceof Error ? failure.message : "That did not work. Try again.";
      setNote(why);
      setPhase(failure instanceof Stale ? "stale" : "failed");
    }
  }

  const reveal = (symbol: string) => { showOnDesk({ symbol, tab: "chart", reveal: true }); };
  const undo = () => { if (undoShow(id)) setUndone(true); };
  const canUndo = card.action === "show" && phase === "done" && !undone && !!undoFor(id);

  return (
    <section aria-label="Desk action" data-testid="desk-action" data-action={card.action} data-phase={phase}
      className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-primary/30 bg-primary/5 p-2 text-xs">
      <p className="min-w-0 flex-1 basis-48 font-medium text-foreground">{actionLine(card)}</p>
      {phase === "drawing" && card.action === "draw" && <DrawLevel card={card} onDone={finish} onFail={fail} />}
      {(phase === "open" || phase === "failed") && (
        <button type="button" onClick={() => void tap()} className={cn(BUTTON, "bg-primary text-primary-foreground")}>{actionVerb(card)}</button>
      )}
      {phase === "working" && <span className="text-muted-foreground">Working…</span>}
      {phase === "done" && card.action === "show" && (canUndo
        ? <button type="button" onClick={undo} className={cn(BUTTON, "border text-muted-foreground hover:text-foreground")}>Undo</button>
        : <button type="button" onClick={() => void tap()} className={cn(BUTTON, "border text-muted-foreground hover:text-foreground")}>Show again</button>)}
      {phase === "done" && shown && (
        <button type="button" onClick={() => reveal(shown)} className={cn(BUTTON, "border text-muted-foreground hover:text-foreground")}>Show it</button>
      )}
      {(phase === "open" || phase === "failed" || phase === "stale") && (
        <button type="button" aria-label="Dismiss" title="Dismiss" onClick={() => { setPhase("dismissed"); onOutcome({ state: "dismissed" }); }}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded text-muted-foreground hover:text-foreground sm:min-h-6 sm:min-w-6">
          <X size={13} aria-hidden />
        </button>
      )}
      {note && (
        <p role={phase === "done" ? "status" : "alert"} className={cn("basis-full", phase === "done" ? "text-emerald-300" : "text-amber-300")}>
          {undone ? "Undone: the desk is back as it was." : note}
        </p>
      )}
      {noDesk && <p role="status" className="basis-full text-muted-foreground">This shows on the desk; open the desk to see it.</p>}
    </section>
  );
}

/**
 * The desk page's side of the cards, given its own state setters: a view card moves the centre (its ticker, the Chain or
 * the Chart) and reports what it replaced for Undo; a tap that changed a list reads the desk again; a phone's "Show it"
 * (``reveal``) closes the copilot's sheet onto the centre.
 */
export function useDeskActionHost({ picked, tab, setPicked, setPickedKey, setTab, setRefresh, setSheet }: {
  picked: string | null; tab: CentreTab; setPicked(symbol: string | null): void; setPickedKey(key: string | null): void;
  setTab(tab: CentreTab): void; setRefresh(next: (n: number) => number): void; setSheet(open: boolean): void;
}) {
  const now = useRef({ picked, tab });
  useEffect(() => { now.current = { picked, tab }; }, [picked, tab]);
  useEffect(() => {
    const onView = (event: Event) => {
      event.preventDefault();
      const detail = (event as CustomEvent<DeskView & { was: DeskView }>).detail;
      if ("symbol" in detail && detail.symbol !== undefined) { detail.was.symbol = now.current.picked; setPicked(detail.symbol); setPickedKey(null); }
      if (detail.tab) { detail.was.tab = now.current.tab; setTab(detail.tab); }
      if (detail.reveal && window.matchMedia("(max-width: 1179px)").matches) { // the sheet layout (CopilotLab.module.css)
        setSheet(false);
        document.getElementById("desk-centre")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ timeframe?: string; tape?: boolean }>).detail ?? {};
      if (!detail.timeframe && detail.tape === undefined) setRefresh(n => n + 1); // a timeframe or the Tape is the chart's own
    };
    window.addEventListener(DESK_VIEW_EVENT, onView);
    window.addEventListener(DESK_CHANGED_EVENT, onChanged);
    return () => { window.removeEventListener(DESK_VIEW_EVENT, onView); window.removeEventListener(DESK_CHANGED_EVENT, onChanged); };
  }, [setPicked, setPickedKey, setTab, setRefresh, setSheet]);
}
