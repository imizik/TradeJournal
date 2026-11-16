"use client";

/**
 * The Position panel (docs/copilot-lab.md § Where a held option stands): one place under the chart for the selected
 * position, with a button for every way he manages it. ``DeskPosition`` is a real position (a book row), ``DeskPaperPosition``
 * a paper one; each takes props only, so the desk shell can place it anywhere (under the chart today, a dock tab later).
 *
 * It shows the REAL or PAPER mark, the contract and size, the P&L, the price now and the stock's change today, the plan's
 * entry, stop and target, break-even and days left (a real option's full standing, ``OptionStanding``), and any working
 * order; then one row of buttons:
 * - **Stop / target**: two stock prices in place. Real: the plan's invalidation alert armed again at the new stop from a
 *   fresh quote (the copilot's ``plan_stop`` route) and its target saved on the plan (``savePlanLevels``); with no saved
 *   plan the button is "Plan it" (the plan flow). Paper: the position's stop and target after entry
 *   (``setPaperLevels``); a change never fills or closes anything, the close-automatically switch still decides.
 * - **Trim** (a count) and **Close** (all): real, the Ticket's close-now view at the mark (``panelCloseTicket``), copy
 *   only; paper, the paper book's own close row (``CloseRow``).
 * - **Roll** (real only): the Ticket's roll mode. **Note**: real, the book row's note line (saved with the trade);
 *   paper, the position's one note.
 * - **Close at target / Close at stop** (real, with those plan levels): the closing tickets priced at the level.
 * Nothing here sends anything to Robinhood or tells him what to do.
 */

import { useState, type FormEvent, type ReactNode } from "react";
import { money, signedPct, type DeskThread } from "@/lib/desk";
import { tickFor, tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { price as priceText, todayNewYork } from "@/lib/charts";
import { daysLeft } from "@/lib/optionStanding";
import { CLOSING_LABEL, trimCount } from "@/lib/closingTicket";
import {
  accountWords, heldContracts, levelsProblem, markNow, panelCloseTicket, paperBreakEven, planSide, savePlanLevels, type PanelPlan,
  type PlanSide,
} from "@/lib/deskPosition";
import { NOTE_SAVED_EVENT, addDeskNote, rowTrade } from "@/lib/deskNotes";
import { paperPnl, setPaperLevels, type PaperPosition, type PaperWorkingOrder } from "@/lib/paperBook";
import { openClosingTicket, openRollTicket } from "@/components/copilot/DeskTicket";
import { OptionStanding, useStanding, type PlanLevels } from "@/components/copilot/OptionStanding";
import { OrderLines } from "@/components/copilot/DeskOrders";
import { NoteLines, type DeskNotesState } from "@/components/copilot/DeskNotes";
import { CloseRow } from "@/components/copilot/DeskPaper";
import ModeMark, { MODE_FRAME } from "@/components/copilot/ModeMark";
import { cn } from "@/lib/utils";

const BUTTON = "inline-flex min-h-11 items-center rounded-md border px-2.5 text-xs font-medium text-foreground hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-7";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-2.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-7";
const INPUT = "min-h-11 w-24 rounded-md border bg-background px-2 text-base tabular-nums sm:min-h-7 sm:text-xs";
const pct = (value: number | null | undefined) => value == null ? null : `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
const level = (value: number | null | undefined) => value == null ? "—" : priceText(value);
/** A typed stock price: a number above zero, null when blank, NaN when not a price. */
const typed = (text: string) => text.trim() === "" ? null : Number(text);

function Fig({ label, children, testId, className }: { label: string; children: ReactNode; testId?: string; className?: string }) {
  return <span data-testid={testId} className={cn("whitespace-nowrap", className)}><span className="text-muted-foreground">{label} </span>{children}</span>;
}

/** The stock now and its change today: "ORCL 247.00 −1.0% today" (greyed when not a live price). */
function StockNow({ symbol, last, change, live }: { symbol: string; last: number; change: number | null; live: boolean }) {
  return (
    <Fig label={symbol} testId="position-stock" className={cn(!live && "opacity-60")}>
      <span className="tabular-nums">{priceText(last)}</span>
      {change != null && <span className={cn("tabular-nums", change > 0 ? "text-emerald-300" : change < 0 ? "text-rose-300" : "text-muted-foreground")}> {pct(change)} today</span>}
    </Fig>
  );
}

/** Two stock prices in place, Save and Cancel. ``needStop``: a stop cannot be cleared here (a real plan's stop is its alert). */
function LevelsEditor({ symbol, side, last, stop, target, needStop, save, onDone, note }: {
  symbol: string; side: PlanSide; last: number | null; stop: number | null; target: number | null; needStop: boolean;
  save(stop: number | null, target: number | null): Promise<string>; onDone(said: string | null): void; note?: ReactNode;
}) {
  const [stopText, setStopText] = useState(stop != null ? String(stop) : "");
  const [targetText, setTargetText] = useState(target != null ? String(target) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stopN = typed(stopText), targetN = typed(targetText);
  const problem = needStop && stopN === null ? "Name the stop: a stock price."
    : (stopN !== null && Number.isNaN(stopN)) || (targetN !== null && Number.isNaN(targetN)) ? "Prices are numbers."
    : levelsProblem(side, last, stopN, targetN);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (problem || busy) return;
    setBusy(true); setError(null);
    try { onDone(await save(stopN, targetN)); } catch (e) { setError(e instanceof Error ? e.message : "Not saved. Try again."); } finally { setBusy(false); }
  };
  return (
    <form data-testid="position-levels-editor" onSubmit={submit} className="space-y-1.5 rounded-md border border-border/70 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-muted-foreground">Stop
          <input aria-label="Stop (stock price)" inputMode="decimal" value={stopText} onChange={e => setStopText(e.target.value.replace(/[^\d.]/g, ""))} placeholder="stock $" className={INPUT} />
        </label>
        <label className="flex items-center gap-1.5 text-muted-foreground">Target
          <input aria-label="Target (stock price)" inputMode="decimal" value={targetText} onChange={e => setTargetText(e.target.value.replace(/[^\d.]/g, ""))} placeholder="none" className={INPUT} />
        </label>
        <span className="tabular-nums text-muted-foreground">{symbol} {last != null ? priceText(last) : "price unavailable"}</span>
      </div>
      {note}
      {(problem || error) && <p role="alert" data-testid="position-levels-problem" className="text-amber-300">{error ?? problem}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" data-testid="position-levels-save" disabled={busy || !!problem} className={BUTTON}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={() => onDone(null)} className={QUIET}>Cancel</button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------------------------------------ real

type Open = "levels" | "trim" | "note" | null;

/**
 * A real position: a book row (``row``) with ``rows`` (the desk's book, so an option leg of a structure is told apart),
 * ``fallback`` the stock's last price when the desk's ticker is not running, ``change`` its change today in percent,
 * ``plan`` its saved plan (null: none), ``levels`` the plan lines the chart drew (for the What if…, when there is no
 * ``plan`` to edit), ``earnings`` the next report's date and ``onPlan`` the plan flow for a symbol.
 */
export function DeskPosition({ row, rows, fallback = null, change = null, plan, levels = {}, earnings = null, onPlan }: {
  row: DeskThread; rows: readonly DeskThread[]; fallback?: { last: number; at: number } | null; change?: number | null;
  plan: PanelPlan | null; levels?: PlanLevels; earnings?: string | null; onPlan?(symbol: string): void;
}) {
  const book = row.book;
  const symbol = row.symbol ?? "";
  const ticks = useDeskTicks([row.symbol, book?.tick?.quote]);
  const read = useStanding(row, rows, fallback);
  const [open, setOpen] = useState<Open>(null);
  const [said, setSaid] = useState<string | null>(null);
  const [trimText, setTrimText] = useState("");
  // What was just saved shows until the desk's next read of the plan says otherwise.
  const [saved, setSaved] = useState<{ stop: number | null; target: number | null } | null>(null);
  const planKey = plan ? `${plan.investigationId}|${plan.stop}|${plan.target}` : "";
  const [seen, setSeen] = useState(planKey);
  if (seen !== planKey) { setSeen(planKey); setSaved(null); }
  if (!book || !row.symbol) return null;

  const current = plan && saved ? { ...plan, ...saved } : plan;
  // What the plan line shows: the plan he can edit, else the book's own plan levels (read only).
  const booked = book.plan_levels;
  const shown = current ?? (booked && (booked.stop != null || booked.target != null) ? { entry: levels.entry ?? null, stop: booked.stop, target: booked.target } : null);
  const pnl = tickedBook(book, ticks);
  const mark = markNow(book, ticks);
  const live = tickFor(ticks, row.symbol);
  const stock = live ? { last: live.last, change: live.change_pct ?? change, live: !live.stale } : fallback ? { last: fallback.last, change, live: false } : null;
  const held = heldContracts(book);
  const contract = row.instrument && row.instrument !== row.symbol ? row.instrument : row.title;
  const standing = read && read !== "unknown" && read !== "incomplete" ? read : null;
  // Close and Trim: a single long call or put the book reads as one leg, priced at the mark now.
  const closeAll = standing && book.option?.direction === "long" && held ? panelCloseTicket(row, ticks, held) : null;
  const half = held ? trimCount(held, { half: true }) : null;
  const roll = standing?.roll ?? null;
  const closing = standing?.closing ?? [];
  const side = planSide({ entry: current?.entry, stop: current?.stop }, { option: book.option, sign: book.tick?.sign });
  const trade = rowTrade(row);
  const working = (book.orders ?? []).filter(o => o.working);

  const toggle = (next: Open) => { setSaid(null); setOpen(open === next ? null : next); };
  const openTrim = () => { setTrimText(half ? String(half) : ""); toggle("trim"); };
  const trimN = /^\d+$/.test(trimText.trim()) ? Number(trimText) : null;
  const trimTicket = held && trimN !== null && trimN >= 1 && trimN < held ? panelCloseTicket(row, ticks, trimN) : null;
  // The note line: only the text line (his saved notes stay under the book row, where they always were); a save shows there at once.
  const notes: DeskNotesState = {
    data: { trades: {}, fills: {} }, open: open === "note" ? row.key : null, setOpen: id => setOpen(id ? "note" : null),
    save: async (target, text) => { const note = await addDeskNote(target, text); window.dispatchEvent(new CustomEvent(NOTE_SAVED_EVENT, { detail: note })); setSaid("Note saved with the trade."); },
  };

  return (
    <section aria-label={`Position: ${symbol} ${contract}`} data-testid="desk-position" data-mode="real" data-use="position"
      className={cn("space-y-2 rounded-md bg-card/40 py-1.5 pr-2 text-xs", MODE_FRAME.real)}>
      <div data-testid="position-head" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
        <ModeMark mode="real" detail={accountWords(book)} className="self-center" />
        <span><span className="text-sm font-semibold text-foreground">{symbol}</span> <span className="text-muted-foreground">{contract}{held != null ? ` ×${held.toLocaleString("en-US", { maximumFractionDigits: 4 })}` : ""}</span></span>
        <Fig label="P&L" testId="position-pnl" className={cn(pnl.stale && "opacity-60")}>
          <span className={pnl.usd == null ? "text-muted-foreground" : pnl.usd > 0 ? "text-emerald-300" : pnl.usd < 0 ? "text-rose-300" : "text-muted-foreground"}>
            {pnl.usd != null ? money(pnl.usd) : "—"}{pnl.pct != null && ` (${signedPct(pnl.pct, 1)})`}
          </span>
        </Fig>
        {mark && <Fig label="Now" testId="position-mark" className={cn(!mark.live && "opacity-60")}>{priceText(mark.share)}{book.option ? " a share" : ""}</Fig>}
        {stock && book.option && <StockNow symbol={symbol} last={stock.last} change={stock.change} live={stock.live} />}
      </div>
      <div data-testid="position-plan" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
        {shown ? <>
          <Fig label="Entry">{level(shown.entry)}</Fig>
          <Fig label="Stop" testId="position-stop">{level(shown.stop)}</Fig>
          <Fig label="Target" testId="position-target">{level(shown.target)}</Fig>
        </> : <span className="text-muted-foreground">{book.planned ? "Planned with a time stop only: no stop or target price." : "No saved plan for this position."}</span>}
        {working.length > 0 && <span data-testid="position-orders" className="min-w-0"><OrderLines orders={working} /></span>}
      </div>
      {book.option && <OptionStanding row={row} rows={rows} fallback={fallback}
        levels={current ? { entry: current.entry ?? levels.entry, stop: current.stop, target: current.target } : levels} earnings={earnings} />}
      <div role="group" aria-label="Manage this position" data-testid="position-actions" className="flex flex-wrap items-center gap-1.5">
        {current && side ? (
          <button type="button" data-testid="position-levels" aria-expanded={open === "levels"} onClick={() => toggle("levels")}
            title="Move the plan's stop or target (stock prices). The stop's alert is armed again at the new price. Nothing is sent." className={BUTTON}>Stop / target</button>
        ) : !book.planned && onPlan ? (
          <button type="button" data-testid="position-plan-it" onClick={() => onPlan(symbol)}
            title="This position has no saved plan: plan its stop and target. Nothing is sent." className={BUTTON}>Plan it</button>
        ) : null}
        {closeAll && held! >= 2 && (
          <button type="button" data-testid="position-trim" aria-expanded={open === "trim"} onClick={openTrim}
            title="Sell part of it: a closing ticket at the mark now, to copy into Robinhood. Nothing is sent." className={BUTTON}>Trim</button>
        )}
        {closeAll && (
          <button type="button" data-testid="position-close" onClick={() => { setOpen(null); openClosingTicket(closeAll); }}
            title={`Close all ${held}: a closing ticket at the mark now, to copy into Robinhood. Nothing is sent.`} className={BUTTON}>Close</button>
        )}
        {roll && (
          <button type="button" data-testid="roll-open" onClick={() => { setOpen(null); openRollTicket(roll); }}
            title={`Close your ${roll.held} contract${roll.held === 1 ? "" : "s"} and open another (a later expiry or another strike), as one order on the Ticket. Nothing is sent.`}
            className={BUTTON}>Roll</button>
        )}
        {trade && (
          <button type="button" data-testid="position-note" aria-expanded={open === "note"} onClick={() => toggle("note")}
            title="Note: why you're in, or why you leave (saved with the trade)" className={BUTTON}>Note</button>
        )}
        {closing.length > 0 && (
          <span data-testid="close-from-plan" className="inline-flex flex-wrap gap-1.5">
            {closing.map(t => (
              <button key={t.at} type="button" onClick={() => { setOpen(null); openClosingTicket(t); }}
                title={`A closing sell of your ${t.contracts} contract${t.contracts === 1 ? "" : "s"} on the Ticket, priced for ${t.symbol} at ${priceText(t.level)}. Nothing is sent.`}
                className={cn(BUTTON, "text-muted-foreground hover:text-foreground")}>
                {CLOSING_LABEL[t.at]}
              </button>
            ))}
          </span>
        )}
      </div>
      {open === "levels" && current && side && (
        <LevelsEditor symbol={symbol} side={side} last={stock?.last ?? null} stop={current.stop} target={current.target} needStop={current.stop !== null}
          save={async (stop, target) => {
            const words = await savePlanLevels({ symbol, plan: current, side, stop, target });
            setSaved({ stop: stop ?? current.stop, target });
            return words;
          }}
          onDone={words => { setOpen(null); setSaid(words); }}
          note={<p className="text-[11px] text-muted-foreground">The stop is the plan&apos;s phone alert, armed again at the new price from a live quote; the target is a line. Nothing is sent to Robinhood.</p>} />
      )}
      {open === "trim" && closeAll && held && (
        <div data-testid="position-trim-pick" className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-muted-foreground">Sell
            <input aria-label="Contracts to trim" inputMode="numeric" value={trimText} onChange={e => setTrimText(e.target.value.replace(/[^\d]/g, "").slice(0, 4))} className={cn(INPUT, "w-16")} />
            of {held}
          </label>
          <button type="button" data-testid="position-trim-open" disabled={!trimTicket} onClick={() => { if (trimTicket) { setOpen(null); openClosingTicket(trimTicket); } }} className={BUTTON}>Open ticket</button>
          <button type="button" onClick={() => setOpen(null)} className={QUIET}>Cancel</button>
          {!trimTicket && <span className="text-amber-300">{`A trim sells 1 to ${held - 1}; Close sells all ${held}.`}</span>}
        </div>
      )}
      {open === "note" && trade && <NoteLines notes={notes} id={row.key} trade={null} target={{ trade_id: trade }} label="this position" />}
      {said && <p role="status" data-testid="position-said" className="text-emerald-300">{said}</p>}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------ paper

/** A paper position: the same panel, on paper (no Roll). ``orders`` are the paper book's working orders. */
export function DeskPaperPosition({ position: p, orders = [] }: { position: PaperPosition; orders?: PaperWorkingOrder[] }) {
  const ticks = useDeskTicks([...p.legs.map(l => l.quote), p.symbol]);
  const [open, setOpen] = useState<"levels" | "trim" | "close" | "note" | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pnl = paperPnl(p, ticks);
  const free = p.remaining - (p.held ?? 0);
  const stockTick = tickFor(ticks, p.symbol);
  const legTick = p.legs.length === 1 ? tickFor(ticks, p.legs[0].quote) : null;
  const breakEven = paperBreakEven(p);
  const days = p.expiry ? daysLeft(p.expiry, todayNewYork()) : null;
  const working = orders.filter(o => o.position === p.id);
  const toggle = (next: typeof open) => { setSaid(null); setError(null); setOpen(open === next ? null : next); };
  const saveNote = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await setPaperLevels(p.id, { note: noteText.trim() || null });
      setOpen(null); setSaid(noteText.trim() ? "Paper note saved." : "Paper note cleared.");
    } catch (e) { setError(e instanceof Error ? e.message : "Not saved."); } finally { setBusy(false); }
  };
  return (
    <section aria-label={`Paper position: ${p.label}`} data-testid="desk-paper-position" data-mode="paper" data-use="position"
      className={cn("space-y-2 rounded-md px-2.5 py-1.5 text-xs", MODE_FRAME.paper)}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
        <ModeMark mode="paper" className="self-center" />
        <span><span className="text-sm font-semibold text-foreground">{p.label}</span> <span className="text-muted-foreground">×{p.remaining.toLocaleString("en-US")}</span></span>
        <Fig label="P&L" testId="paper-position-pnl" className={cn(pnl?.stale && "opacity-60")}>
          {pnl ? <span className={pnl.pnl > 0 ? "text-emerald-300" : pnl.pnl < 0 ? "text-rose-300" : "text-muted-foreground"}>
            {pnl.pnl > 0 ? "+" : pnl.pnl < 0 ? "−" : ""}${Math.abs(pnl.pnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}{pnl.pct != null && ` (${pct(pnl.pct)})`}
          </span> : <span className="text-muted-foreground">no price yet</span>}
        </Fig>
        {legTick && p.instrument !== "stock" && <Fig label="Now" className={cn(legTick.stale && "opacity-60")}>{priceText(legTick.last)} a share</Fig>}
        {stockTick && <StockNow symbol={p.symbol} last={stockTick.last} change={stockTick.change_pct} live={!stockTick.stale} />}
      </div>
      <div data-testid="paper-position-plan" className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
        <Fig label="Entry">{p.stock != null ? priceText(p.stock) : "—"}</Fig>
        <Fig label="Stop" testId="paper-position-stop">{level(p.stop)}</Fig>
        <Fig label="Target" testId="paper-position-target">{level(p.target)}</Fig>
        {breakEven != null && <Fig label="Break-even">{priceText(breakEven)}</Fig>}
        {days != null && <Fig label="Expiry"><span className={cn(days <= 2 && "text-amber-300")}>{days < 0 ? "Expired" : `${days}d left`}</span></Fig>}
        {(p.stop != null || p.target != null) && <span className="text-muted-foreground">Close automatically {p.auto ? "on" : "off"}</span>}
        {working.map(o => <span key={o.id} data-testid="paper-position-order" className="text-muted-foreground">Working: {o.side === "close" ? "sell" : "buy"} {o.quantity} at {priceText(o.limit)}</span>)}
        {p.note && <span data-testid="paper-position-note" className="min-w-0 truncate text-muted-foreground">“{p.note}”</span>}
      </div>
      <div role="group" aria-label="Manage this paper position" data-testid="paper-position-actions" className="flex flex-wrap items-center gap-1.5">
        <button type="button" data-testid="paper-position-levels" aria-expanded={open === "levels"} onClick={() => toggle("levels")}
          title="Change this paper position's stop or target (stock prices). It never fills or closes by itself." className={BUTTON}>Stop / target</button>
        {free > 1 && <button type="button" data-testid="paper-position-trim" aria-expanded={open === "trim"} onClick={() => toggle("trim")} className={BUTTON}>Trim</button>}
        <button type="button" data-testid="paper-position-close" disabled={free <= 0} aria-expanded={open === "close"} onClick={() => toggle("close")}
          title={p.held ? `${p.held} held for a working sell limit` : "Close it on paper at the live bid, or with a limit"} className={BUTTON}>Close</button>
        <button type="button" data-testid="paper-position-note-button" aria-expanded={open === "note"} onClick={() => { setNoteText(p.note ?? ""); toggle("note"); }} className={BUTTON}>Note</button>
      </div>
      {open === "levels" && (
        <LevelsEditor symbol={p.symbol} side={p.bias} last={stockTick?.last ?? null} stop={p.stop} target={p.target} needStop={false}
          save={async (stop, target) => {
            const change: { stop?: number | null; target?: number | null } = {};
            if (stop !== p.stop) change.stop = stop;
            if (target !== p.target) change.target = target;
            if (!Object.keys(change).length) return "Nothing changed.";
            const saved = await setPaperLevels(p.id, change);
            return `Paper: stop ${level(saved.stop)}, target ${level(saved.target)}. Nothing was closed; Close automatically is ${p.auto ? "on" : "off"}.`;
          }}
          onDone={words => { setOpen(null); setSaid(words); }}
          note={<p className="text-[11px] text-muted-foreground">Stock prices. A change never fills or closes anything; with Close automatically on, the first bar past a level after this change sells.</p>} />
      )}
      {(open === "trim" || open === "close") && <CloseRow key={`${p.id}|${open}`} position={p} trim={open === "trim"} onDone={() => setOpen(null)} />}
      {open === "note" && (
        <form onSubmit={saveNote} className="flex flex-wrap items-center gap-2">
          <input autoFocus aria-label="Paper note" maxLength={280} value={noteText} onChange={e => setNoteText(e.target.value)} placeholder="Why you're in (one line)"
            className="min-h-11 min-w-0 flex-1 rounded-md border bg-background px-2 text-base sm:min-h-7 sm:text-xs" />
          <button type="submit" data-testid="paper-position-note-save" disabled={busy} className={BUTTON}>Save</button>
          <button type="button" onClick={() => setOpen(null)} className={QUIET}>Cancel</button>
        </form>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {said && <p role="status" data-testid="paper-position-said" className="text-emerald-300">{said}</p>}
    </section>
  );
}
