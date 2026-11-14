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
import { CHART_SETTINGS_SAVED, readChartSettings, useChartSettings } from "@/lib/chartSync";
import { applyEdit, MAX_LEVELS } from "@/lib/drawings";
import type { Proposal, ProposalOutcome } from "@/lib/copilot";
import { freshQuote } from "@/lib/copilot";
import { DESK_CHANGED_EVENT, DESK_GO_EVENT, DESK_POSITION_EVENT, DESK_VIEW_EVENT, Stale, actionLine, actionVerb, applyShow, arrived, heldFacts, revealCentre,
  rowForLeg, runAction, showOnDesk, staleByAge, staleByPrice, ticketDone, ticketFromBook, undoFor, undoShow, type CentreTab, type DeskAction,
  type DeskView, type Done, type PositionDetail } from "@/lib/deskAction";
import type { DeskThread } from "@/lib/desk";
import { peekDeskTicks } from "@/lib/deskTicks";
import { openClosingTicket } from "@/components/copilot/DeskTicket";
import { cn } from "@/lib/utils";

export type DeskActionProposal = Extract<Proposal, { kind: "desk_action" }>;

const BUTTON = "inline-flex min-h-11 items-center rounded px-3 py-1 text-xs sm:min-h-0";

/** Draws the card's level through the chart settings' own store and sync (the desk's drawings), then reports. */
function DrawLevel({ card, onDone, onFail }: { card: Extract<DeskAction, { action: "draw" }>; onDone(done: Done): void; onFail(why: string): void }) {
  const { settings, setSettings, ready, sync } = useChartSettings(undefined, { borrowed: true });
  const placed = useRef<string | null>(null); // the new level's id
  const saving = useRef(false);
  const reported = useRef(false);
  const checking = useRef(false);
  useEffect(() => {
    if (!ready || placed.current) return;
    placed.current = "pending";
    const levels = settings.levels[card.symbol] ?? [];
    if (!validSymbol(card.symbol)) { reported.current = true; onFail(`${card.symbol} cannot carry a level.`); return; }
    if (levels.length >= MAX_LEVELS) { reported.current = true; onFail(`Remove a ${card.symbol} line first: ${MAX_LEVELS} per symbol.`); return; }
    const level = cleanLevel({ id: crypto.randomUUID(), price: card.price, label: card.label ?? `Level ${levels.length + 1}`, drawn_on: todayNewYork() });
    if (!level) { reported.current = true; onFail("That level could not be drawn."); return; }
    placed.current = level.id;
    setSettings(s => {
      const next = applyEdit(s, { symbol: card.symbol, layer: "levels", before: null, after: level, index: (s.levels[card.symbol] ?? []).length }, "after") ?? s;
      return next.hiddenGroups.levels ? { ...next, hiddenGroups: { ...next.hiddenGroups, levels: false } } : next;
    });
  }, [ready, settings, card, setSettings, onFail]);
  useEffect(() => {
    if (!placed.current || reported.current) return;
    if (sync === "saving") saving.current = true;
    else if (sync === "saved" && saving.current && !checking.current) {
      // "Saved" can also mean a save that met another device's and merged, with the merged copy (holding the level) still
      // to be sent: report only once the server's copy has the level; otherwise wait for the next save.
      saving.current = false;
      checking.current = true;
      void readChartSettings().then(server => {
        checking.current = false;
        if (reported.current) return;
        if (server?.levels[card.symbol]?.some(l => l.id === placed.current)) {
          reported.current = true;
          window.dispatchEvent(new Event(CHART_SETTINGS_SAVED)); // the desk chart's own copy reads the new level now
          onDone({ text: `Drawn: ${card.price.toFixed(2)} on ${card.symbol}${card.label ? ` (${card.label})` : ""}, on the desk chart and in Charts.`, symbol: card.symbol });
        }
      });
    } else if (sync === "offline") { reported.current = true; onFail("The chart settings could not be saved just now. Try again."); }
  }, [sync, card, onDone, onFail]);
  // A save that never confirms (the merged copy lost, the server gone) fails plainly instead of waiting for ever.
  useEffect(() => {
    const timer = window.setTimeout(() => { if (!reported.current) { reported.current = true; onFail("The level could not be confirmed as saved. Check the chart, then try again."); } }, 15_000);
    return () => window.clearTimeout(timer);
  }, [onFail]);
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
    if (card.action === "draw") {
      try {
        const moved = staleByPrice(card, (await freshQuote(card.symbol)).last ?? card.last);
        if (moved) { setNote(moved); setPhase("stale"); return; }
      } catch { /* no quote: a level is harmless to draw, so it is drawn at the price he asked for */ }
      setPhase("drawing");
      return;
    }
    if (card.action === "close" || card.action === "trim") {
      // The desk's own book row as it is now, priced at the mark the desk holds: the Ticket tab's closing view, copy-only.
      const detail: PositionDetail = { symbol: card.symbol, legs: card.legs, rows: null };
      if (window.dispatchEvent(new CustomEvent(DESK_POSITION_EVENT, { detail, cancelable: true })) || !detail.rows) { setNoDesk(true); return; }
      try {
        const ticket = ticketFromBook(card, detail.rows, peekDeskTicks());
        openClosingTicket(ticket);
        revealCentre(); // on a phone the copilot's sheet gives way to the ticket
        finish({ text: ticketDone(ticket), symbol: card.symbol });
      } catch (failure) {
        setNote(failure instanceof Error ? failure.message : "No ticket was opened. Try again.");
        setPhase(failure instanceof Stale ? "stale" : "failed");
      }
      return;
    }
    setPhase("working");
    try {
      finish(await runAction(card, Date.now() / 1000));
    } catch (failure) {
      const why = failure instanceof Error ? failure.message : "That did not work. Try again.";
      setNote(why);
      setPhase(failure instanceof Stale ? "stale" : "failed");
    }
  }

  const facts = phase === "done" ? null : card.action === "plan_idea" ? card.levels_line : heldFacts(card);
  const reveal = (symbol: string) => { showOnDesk({ symbol, tab: "chart", reveal: true }); };
  const undo = () => { if (undoShow(id)) setUndone(true); };
  const canUndo = card.action === "show" && phase === "done" && !undone && !!undoFor(id);

  return (
    <section aria-label="Desk action" data-testid="desk-action" data-action={card.action} data-phase={phase}
      className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-primary/30 bg-primary/5 p-2 text-xs">
      <p className="min-w-0 flex-1 basis-48 font-medium text-foreground">{actionLine(card)}</p>
      {facts && <p data-testid="desk-action-facts" className="basis-full text-muted-foreground tabular-nums">{facts}</p>}
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
export function useDeskActionHost({ picked, tab, rows, go, setPicked, setPickedKey, setTab, setRefresh, setSheet, showCentre }: {
  picked: string | null; tab: CentreTab; rows: readonly DeskThread[]; go(href: string): void; setPicked(symbol: string | null): void;
  setPickedKey(key: string | null): void; setTab(tab: CentreTab): void; setRefresh(next: (n: number) => number): void; setSheet(open: boolean): void;
  /** The desk's own "the selected ticker's tools come forward": a phone's ticker view, the centre below 1180 px. */
  showCentre(): void;
}) {
  const now = useRef({ picked, tab, rows });
  useEffect(() => { now.current = { picked, tab, rows }; }, [picked, tab, rows]);
  // A position card asks for its book rows; a plan card follows the Feed's own Plan it link in place.
  useEffect(() => {
    const onPosition = (event: Event) => {
      event.preventDefault();
      const detail = (event as CustomEvent<PositionDetail>).detail;
      detail.rows = detail.legs.map(leg => rowForLeg(now.current.rows, detail.symbol, leg));
    };
    const onGo = (event: Event) => { event.preventDefault(); go((event as CustomEvent<{ href: string }>).detail.href); };
    window.addEventListener(DESK_POSITION_EVENT, onPosition);
    window.addEventListener(DESK_GO_EVENT, onGo);
    return () => { window.removeEventListener(DESK_POSITION_EVENT, onPosition); window.removeEventListener(DESK_GO_EVENT, onGo); };
  }, [go]);
  useEffect(() => {
    const onView = (event: Event) => {
      event.preventDefault();
      const detail = (event as CustomEvent<DeskView & { was: DeskView }>).detail;
      if ("symbol" in detail && detail.symbol !== undefined) { detail.was.symbol = now.current.picked; setPicked(detail.symbol); setPickedKey(null); }
      if (detail.tab) { detail.was.tab = now.current.tab; setTab(detail.tab); }
      if (detail.reveal && window.matchMedia("(max-width: 1179px)").matches) { // the sheet layout (CopilotLab.module.css)
        setSheet(false);
        showCentre();
      }
    };
    const onChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ timeframe?: string; tape?: boolean }>).detail ?? {};
      if (!detail.timeframe && detail.tape === undefined) setRefresh(n => n + 1); // a timeframe or the Tape is the chart's own
    };
    window.addEventListener(DESK_VIEW_EVENT, onView);
    window.addEventListener(DESK_CHANGED_EVENT, onChanged);
    return () => { window.removeEventListener(DESK_VIEW_EVENT, onView); window.removeEventListener(DESK_CHANGED_EVENT, onChanged); };
  }, [setPicked, setPickedKey, setTab, setRefresh, setSheet, showCentre]);
}
