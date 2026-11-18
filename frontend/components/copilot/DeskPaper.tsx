"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { tickFor, useDeskTicks, type DeskTicks } from "@/lib/deskTicks";
import {
  PAPER_EVENT, PAPER_SOURCES, PaperRefused, SOURCE_WORD, cancelPaperOrder, orderWords, fillClose, fillOpen, isCredit, orderKey, paperPnl, paperSymbols, paperValue, placeLimitClose,
  placeLimitOpen, previewClose, previewOpen, setPaperAuto, startPaper,
  type ChallengeRecord, type EquityRange, type PaperBook, type PaperChallenge, type PaperFill, type PaperOrder, type PaperPosition, type PaperSource, type PaperStats, type PaperWorkingOrder,
} from "@/lib/paperBook";
import { fillBuzz } from "@/lib/fillBuzz";
import { cn } from "@/lib/utils";
import ModeMark from "./ModeMark";
import { RulesChecklist } from "./DeskRules";
import PaperOrderSheet, { type PaperOrderReview } from "./PaperOrderSheet";
import PaperPositionCard from "./PaperPositionCard";
import PortfolioGraph, { usePaperEquity } from "./PortfolioGraph";
import SwipeToSubmit from "./SwipeToSubmit";

/**
 * His own paper book on the desk (docs/copilot-lab.md § Paper): a Paper button wherever the desk builds an order (the
 * Ticket, the Chain tab, shares of the selected ticker), and the Paper section under the book: the account, open paper
 * positions at the desk's live prices with Close and Trim, working limit orders with Cancel, each position's "Close
 * automatically at stop/target" switch, and the scorecard beside his real trades over the same dates. A market fill is at
 * a live quote read when he taps (the ask to buy, the bid to sell); a limit fills on a later fresh quote that reaches its
 * price, checked once a minute; nothing is placed anywhere.
 */

const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const BUTTON = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
const QUIET = "inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8";
const INPUT = "min-h-11 rounded-md border bg-background px-2 text-sm tabular-nums sm:min-h-8 sm:text-xs";

const usd = (n: number) => `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${usd(n)}`;
const toneOf = (n: number | null | undefined) => n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-emerald-300" : "text-rose-300";
const at = (epoch: number, seconds = false) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}) }) + " ET";
const day = (epoch: number) => new Date(epoch * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" });
const price = (n: number) => n.toFixed(Math.abs(n) < 1 && n !== 0 ? 4 : 2).replace(/(\.\d\d)00$/, "$1");

/** The paper book: read on mount, on the desk's shared minute (joining its one request) and after each paper fill. */
export function usePaperBook(on: boolean): { book: PaperBook | null; failed: boolean; reload(): void } {
  const [book, setBook] = useState<PaperBook | null>(null);
  const [failed, setFailed] = useState(false);
  const [n, setN] = useState(0);
  const reload = useCallback(() => setN(x => x + 1), []);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => deskGet("/copilot/paper", controller.signal)
      // Read the body even when refused: an unread one keeps the request open (and the page never idle).
      .then(async r => { const body = await r.json().catch(() => null); if (!r.ok || !body) throw new Error(String(r.status)); setBook(body); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load);
    window.addEventListener(PAPER_EVENT, load);
    return () => { controller.abort(); stop(); window.removeEventListener(PAPER_EVENT, load); };
  }, [on, n]);
  return { book, failed, reload };
}

/** The fill as one line: "Buy 2 × NBIS $100 Call 11/20/26 at 3.40 (the ask, 10:42:13 AM ET) = $680.00". */
function fillLine(fill: PaperFill, opening: boolean, multiplier: number) {
  const legs = Object.values(fill.legs);
  const spread = legs.length > 1;
  const one = legs[0];
  const priceWords = spread
    ? `${price(Math.abs(fill.per_share))} net ${fill.per_share > 0 ? "credit" : "debit"} (each leg bought at its ask, sold at its bid)`
    : `${price(one.price)} (the ${one.action === "buy" ? "ask" : "bid"})`;
  const verb = opening ? (spread ? "Open" : "Buy") : (spread ? "Close" : "Sell");
  const money = `${fill.cash >= 0 ? "takes in" : "costs"} ${usd(fill.cash)}`;
  // Shares read "Buy 10 NBIS shares" (their label names them); contracts "Buy 2 × NBIS $100 Call 11/20/26".
  return `${verb} ${fill.quantity.toLocaleString("en-US")}${multiplier === 1 ? "" : " ×"} ${fill.label} at ${priceWords}, quote ${at(fill.quoted_at, true)}: ${money}`;
}

/** Market or Limit, as on Robinhood: market fills at the quote read now; a limit is a day order that waits for its price. */
function OrderType({ type, onChange, market = true }: { type: "market" | "limit"; onChange(type: "market" | "limit"): void; market?: boolean }) {
  return (
    <div role="radiogroup" aria-label="Paper order type" className="inline-flex rounded-md border text-xs">
      {(["market", "limit"] as const).map(t => (
        <button key={t} type="button" role="radio" aria-checked={type === t} disabled={t === "market" && !market} data-testid={`paper-type-${t}`}
          onClick={() => onChange(t)}
          className={cn("min-h-11 px-3 first:rounded-l-md last:rounded-r-md disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8",
            type === t ? "bg-violet-400/15 text-violet-100" : "text-muted-foreground hover:bg-secondary")}>{t === "market" ? "Market" : "Limit"}</button>
      ))}
    </div>
  );
}

/** What a limit does, in one line: when it fills, at what, and until when. ``pays``: buying, or a spread costing a debit. */
function limitWords(limit: number, spread: boolean, pays: boolean, closing: boolean) {
  const n = price(limit);
  if (spread) return pays ? `Fills at the natural price once it costs ${n} or less` : `Fills at the natural price once it takes in ${n} or more`;
  return closing ? `Sells at the bid once the bid is ${n} or more` : `Buys at the ask once the ask is ${n} or less`;
}

/**
 * The Paper button: one tap reads a live quote and shows what the order would fill at. Market fills on paper at the
 * quote read then (the ask to buy, the bid to sell); Limit places a day order that fills once a fresh quote reaches its
 * price, until the close or a cancel. A note, a stop and a target (stock prices) can ride with it.
 *
 * On an idea (Paper it on a copilot plan, a Radar setup or a scanner pick) ``source`` and ``ideaId`` record whose idea it
 * was, and the confirm opens prefilled from it; an idea without enough to place an order (``order`` null) shows the
 * button disabled with ``why``. ``strong``: the main action where it stands (a ticket in the desk's Paper mode).
 *
 * The confirm is short: what it fills at, the quantity, Market or Limit and the button. His stop, target, note and rules
 * checklist fold behind one More line, which opens on its own when an idea prefilled any of them or when he has a
 * tick-box rule to answer (an unticked one counts as not followed). ``autoOpen``: open at once (a copilot card's Edit);
 * ``onClose``: told when the confirm closes; ``onFilled``: told what a fill or a placed limit did; ``fixedKey``: the order
 * key to use instead of a new one per opening (a copilot card's, so its Edit can never fill a second time).
 */
export function PaperButton({ order, quantity = 1, note = null, stop = null, target = null, label = "Paper trade it", source = "mine", ideaId = null, why = null, strong = false, autoOpen = false, onClose, onFilled, fixedKey }: {
  order: PaperOrder | null; quantity?: number | null; note?: string | null; stop?: number | null; target?: number | null; label?: string;
  source?: PaperSource; ideaId?: string | null; why?: string | null; strong?: boolean; autoOpen?: boolean; onClose?(): void; onFilled?(text: string): void; fixedKey?: string;
}) {
  const multiplier = order?.instrument === "stock" ? 1 : 100;
  const [open, setOpen] = useState(false);
  const [qty, setQty] = useState(String(quantity && quantity > 0 ? quantity : 1));
  const [words, setWords] = useState((note ?? "").slice(0, 280));
  const [stopText, setStopText] = useState(stop != null ? String(stop) : "");
  const [targetText, setTargetText] = useState(target != null ? String(target) : "");
  const [preview, setPreview] = useState<PaperFill | null>(null);
  const [type, setType] = useState<"market" | "limit">("market");
  const [limitText, setLimitText] = useState("");
  const [closedNow, setClosedNow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; start: boolean } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [ticked, setTicked] = useState<Record<string, boolean>>({});  // his tick-box rules, answered here
  // Stop, target, note and his rules: folded unless an idea prefilled them, or he has a tick-box rule to answer.
  const [more, setMore] = useState(!!note?.trim() || stop != null || target != null);
  const [broken, setBroken] = useState(0);
  const qtyN = Number(qty);
  const valid = Number.isInteger(qtyN) && qtyN > 0;
  const limitN = Number(limitText);
  const limitValid = limitText.trim() !== "" && limitN > 0;
  const spread = order?.instrument === "spread";
  const credit = !!order && isCredit(order);
  const refuse = (e: unknown) => setError({ text: e instanceof Error ? e.message : "Not filled.", start: e instanceof PaperRefused && /Start a paper account/.test(e.message) });

  const check = async (count = qtyN) => {
    if (!order) return;
    setOpen(true); setBusy(true); setError(null); setDone(null); setKey(fixedKey ?? orderKey()); setClosedNow(false);
    try {
      const found = await previewOpen(order, count);
      setPreview(found); setLimitText(price(Math.abs(found.per_share)));
    } catch (e) {
      setPreview(null);
      // Closed: no live quote to fill at, but a day limit can still be placed before the open.
      if (e instanceof PaperRefused && /market is closed/.test(e.message)) { setClosedNow(true); setType("limit"); } else refuse(e);
    } finally { setBusy(false); }
  };
  const levels = () => {
    const level = (text: string) => text.trim() ? Number(text) : null;
    return { note: words.trim() || null, stop: level(stopText), target: level(targetText), rule_answers: ticked,
      // The idea's id as the book keeps it (letters, digits and _ . : -, at most 64), or none.
      ...(source !== "mine" ? { source, idea_id: ideaId?.replace(/[^A-Za-z0-9_.:-]/g, "").slice(0, 64) || null } : {}) };
  };
  const fill = async () => {
    if (!order || !valid) return;
    setBusy(true); setError(null);
    try {
      const filled = await fillOpen(order, qtyN, levels(), key);
      if (filled) fillBuzz("fill");
      const text = filled ? `Paper: ${fillLine(filled, true, multiplier)}.` : "Already filled on paper.";
      setDone(text); onFilled?.(text);
      setPreview(null);
    } catch (e) { fillBuzz("reject"); refuse(e); } finally { setBusy(false); }
  };
  const place = async () => {
    if (!order || !valid || !limitValid) return;
    setBusy(true); setError(null);
    try {
      const placed = await placeLimitOpen(order, qtyN, limitN, levels(), key);
      if (placed.filled) fillBuzz("fill");
      const text = placed.filled ? `Paper limit filled: ${fillLine(placed.filled, true, multiplier)}.`
        : placed.working ? `Paper limit working: ${spread ? "open" : "buy"} ${qtyN.toLocaleString("en-US")} at ${price(limitN)}${spread ? (credit ? " credit or more" : " debit or less") : " or better"}, until ${at(placed.working.expires_at)} or until you cancel it below.`
        : "Already placed on paper.";
      setDone(text); onFilled?.(text);
      setPreview(null); setClosedNow(false);
    } catch (e) { fillBuzz("reject"); refuse(e); } finally { setBusy(false); }
  };
  const start = async () => {
    setBusy(true);
    try { await startPaper(10_000, false, true); await check(); } catch (e) { refuse(e); } finally { setBusy(false); }
  };
  const close = () => { setOpen(false); setPreview(null); setError(null); setClosedNow(false); setDone(null); onClose?.(); };
  const opened = useRef(false);
  useEffect(() => {
    if (!autoOpen || opened.current || !order) return;
    opened.current = true;
    void check(quantity && quantity > 0 ? quantity : 1);
  }, [autoOpen]); // eslint-disable-line react-hooks/exhaustive-deps -- once, when an Edit opens it

  if (!open) {
    const button = (
      <button type="button" data-testid="paper-button" data-use="ticket.paper" data-source={source} disabled={!order} aria-describedby={!order && why ? `paper-why-${ideaId ?? source}` : undefined}
        onClick={() => { const n = quantity && quantity > 0 ? quantity : 1; setQty(String(n)); setType("market"); check(n); }}
        title={!order && why ? why : "Fill this on paper at the live quote, or place a paper limit: no money, nothing sent"}
        className={cn(BUTTON, strong ? "border-violet-400 bg-violet-400 font-semibold text-black hover:bg-violet-300" : "border-violet-400/60 text-violet-200")}>{label}</button>
    );
    if (order || !why) return button;
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2">
        {button}
        <span id={`paper-why-${ideaId ?? source}`} data-testid="paper-why" className="text-[11px] text-muted-foreground">{why}</span>
      </span>
    );
  }
  const cost = preview ? Math.round(preview.per_share * multiplier * (valid ? qtyN : preview.quantity) * 100) / 100 : null;
  const width = order?.instrument === "spread" ? Math.abs(order.long_strike - order.short_strike) : null;
  const hold = limitValid && valid ? Math.round((credit && width != null ? width - limitN : limitN) * multiplier * qtyN * 100) / 100 : null;
  const form = preview || closedNow;
  // What his rules check: the most it can lose at entry (a market fill's need at the quote read, a limit's hold).
  const size = type === "market" ? (preview?.need_each != null && valid ? Math.round(preview.need_each * qtyN * 100) / 100 : null) : hold;
  const stopN = stopText.trim() && Number(stopText) > 0 ? Number(stopText) : null;
  const entry = order && form ? { side: "paper" as const, instrument: order.instrument, expiry: order.instrument === "stock" ? null : order.expiry, size, stop: stopN } : null;
  return (
    <div data-testid="paper-confirm" className="w-full space-y-2 rounded-md border border-dashed border-violet-400/50 p-2.5">
      <p className="flex flex-wrap items-center gap-x-1 text-[11px]"><ModeMark mode="paper" />{source !== "mine" && <span data-testid="paper-idea" className="text-muted-foreground">· {SOURCE_WORD[source]}&apos;s idea{order ? `: ${orderWords(order)}` : ""}</span>}</p>
      {busy && !form && <p className="text-xs text-muted-foreground">Reading a live quote…</p>}
      {form && !done && (
        <>
          {closedNow && <p className="text-xs text-muted-foreground">The market is closed, so there is no live quote to fill at. A limit placed before the open works from 9:30 AM ET until the close.</p>}
          {preview && type === "market" && <p data-testid="paper-preview" className="text-sm tabular-nums">{fillLine({ ...preview, quantity: valid ? qtyN : preview.quantity, cash: cost ?? preview.cash }, true, multiplier)}.</p>}
          {preview && type === "limit" && <p className="text-xs tabular-nums text-muted-foreground">Now: {fillLine({ ...preview, quantity: valid ? qtyN : preview.quantity, cash: cost ?? preview.cash }, true, multiplier)}.</p>}
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{multiplier === 1 ? "Shares" : order?.instrument === "spread" ? "Spreads" : "Contracts"}
              <input aria-label="Paper quantity" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, ""))} className={cn(INPUT, "w-20")} />
            </label>
            <OrderType type={type} onChange={setType} market={!closedNow} />
            {type === "limit" && (
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Limit $
                <input aria-label="Paper limit price" data-testid="paper-limit" inputMode="decimal" value={limitText} onChange={e => setLimitText(e.target.value.replace(/[^\d.]/g, ""))} className={cn(INPUT, "w-20")} />
              </label>
            )}
          </div>
          {type === "market" && preview ? (
            <p className="text-[11px] text-muted-foreground">Fill on paper re-reads the quote and fills at that moment&apos;s {Object.values(preview.legs).length > 1 ? "natural price" : "ask"}. {preview.buying_power != null && preview.need_each != null && valid && <>Paper buying power after: {preview.buying_power - preview.need_each * qtyN < 0 ? "−" : ""}{usd(preview.buying_power - preview.need_each * qtyN)}{preview.buying_power - preview.need_each * qtyN < 0 ? " (not enough)" : ""}.</>}</p>
          ) : (
            <p data-testid="paper-limit-words" className="text-[11px] text-muted-foreground">{limitValid ? <>{limitWords(limitN, spread, !credit, false)}, on a live quote only. A day order: it works until the close or until you cancel it{hold != null && <>, and holds {usd(hold)} of paper buying power meanwhile</>}.</> : "Name the limit price."}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {type === "market"
              ? <SwipeToSubmit testId="paper-fill" label="Fill on paper" onSubmit={fill} disabled={!valid || !preview} busy={busy} />
              : <SwipeToSubmit testId="paper-place-limit" label="Place limit on paper" onSubmit={place} disabled={!valid || !limitValid} busy={busy} />}
            <button type="button" onClick={close} className={QUIET}>Cancel</button>
            <button type="button" data-testid="paper-more" aria-expanded={more} onClick={() => setMore(m => !m)}
              className={cn(QUIET, "ml-auto")}>{more ? "Less" : "More"}: stop, target, note, your rules{!more && broken > 0 && <span className="ml-1 text-amber-300">· breaks {broken}</span>}</button>
          </div>
          <div data-testid="paper-more-fields" hidden={!more} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Stop
                <input aria-label="Paper stop (stock price)" inputMode="decimal" placeholder="stock $" value={stopText} onChange={e => setStopText(e.target.value)} className={cn(INPUT, "w-20")} />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Target
                <input aria-label="Paper target (stock price)" inputMode="decimal" placeholder="stock $" value={targetText} onChange={e => setTargetText(e.target.value)} className={cn(INPUT, "w-20")} />
              </label>
            </div>
            <input aria-label="Paper note" maxLength={280} placeholder="Why (optional, one line)" value={words} onChange={e => setWords(e.target.value)} className={cn(INPUT, "w-full")} />
            {/* Mounted while folded, so a tick-box rule to answer opens More on its own. */}
            <RulesChecklist entry={entry} ticked={ticked} onTick={(id, on) => setTicked(t => ({ ...t, [id]: on }))}
              onResults={results => { setBroken(results.filter(r => r.status === "fail").length); if (results.some(r => r.kind === "tick")) setMore(true); }} />
          </div>
        </>
      )}
      {error && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" data-testid="paper-refused" className="text-xs text-amber-300">{error.text}</p>
          {error.start && <button type="button" disabled={busy} onClick={start} className={BUTTON}>Start a $10,000 paper account</button>}
          {!form && <button type="button" onClick={close} className={QUIET}>Close</button>}
        </div>
      )}
      {done && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="status" data-testid="paper-done" className="text-xs text-emerald-300">{done}</p>
          <button type="button" onClick={close} className={QUIET}>Done</button>
        </div>
      )}
    </div>
  );
}

/** Close or trim an open paper position: a live quote first, then Fill on paper at the bid (the ask to buy a leg back),
 *  or a sell limit that waits for its price until the close. What a working sell limit holds cannot be sold twice. */
export function CloseRow({ position, trim, quantity, onDone, onFilled, fixedKey, sheet }: {
  position: Pick<PaperPosition, "id" | "remaining" | "held" | "multiplier" | "instrument" | "credit">; trim: boolean;
  /** Shown as the Paper home's order sheet (``PaperOrderSheet``): its title, and what sits above the order (Sell all or
   *  Trim, Show on chart). Cancel is the sheet's own. */
  sheet?: { title: string; top?: React.ReactNode };
  /** The count to start from (a copilot card's Edit); half, rounded down, for a trim otherwise. */
  quantity?: number; onDone(): void;
  /** Told what a fill or a placed limit did. ``fixedKey``: the order key to use (a copilot card's), not a new one. */
  onFilled?(text: string): void; fixedKey?: string;
}) {
  const free = position.remaining - (position.held ?? 0);
  const [qty, setQty] = useState(String(quantity ?? (trim ? Math.max(1, Math.floor(free / 2)) : free)));
  const [preview, setPreview] = useState<PaperFill | null>(null);
  const [type, setType] = useState<"market" | "limit">("market");
  const [limitText, setLimitText] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [key] = useState(() => fixedKey ?? orderKey());
  const qtyN = Number(qty);
  const valid = Number.isInteger(qtyN) && qtyN > 0 && qtyN <= free;
  const limitN = Number(limitText);
  const limitValid = limitText.trim() !== "" && limitN > 0;
  const spread = position.instrument === "spread";
  useEffect(() => {
    let live = true;
    previewClose(position.id, Number(qty) || free).then(p => { if (live) { setPreview(p); setLimitText(price(Math.abs(p.per_share))); } })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : "No quote."); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [position.id]); // eslint-disable-line react-hooks/exhaustive-deps -- one quote when the row opens
  const fill = async () => {
    setBusy(true); setError(null);
    try {
      const filled = await fillClose(position.id, qtyN, key);
      if (filled) fillBuzz("fill");
      const text = filled ? `Paper: ${fillLine(filled, false, position.multiplier)}; ${filled.pnl! >= 0 ? "made" : "lost"} ${usd(filled.pnl!)}.` : "Already filled on paper.";
      setDone(text); onFilled?.(text);
    } catch (e) { fillBuzz("reject"); setError(e instanceof Error ? e.message : "Not filled."); } finally { setBusy(false); }
  };
  const place = async () => {
    setBusy(true); setError(null);
    try {
      const placed = await placeLimitClose(position.id, qtyN, limitN, key);
      if (placed.filled) fillBuzz("fill");
      const text = placed.filled ? `Paper limit filled: ${fillLine(placed.filled, false, position.multiplier)}; ${placed.filled.pnl! >= 0 ? "made" : "lost"} ${usd(placed.filled.pnl!)}.`
        : placed.working ? `Paper limit working: ${spread ? "close" : "sell"} ${qtyN} at ${price(limitN)}, until ${at(placed.working.expires_at)} or until you cancel it.` : "Already placed on paper.";
      setDone(text); onFilled?.(text);
    } catch (e) { fillBuzz("reject"); setError(e instanceof Error ? e.message : "Not placed."); } finally { setBusy(false); }
  };
  const share = preview && valid ? Math.round(preview.per_share * position.multiplier * qtyN * 100) / 100 : null;
  const inner = (
    <div data-testid="paper-close" className={cn("space-y-1.5", !sheet && "border-t border-dashed border-violet-400/30 px-3 py-2")}>
      {busy && !preview && !error && <p className="text-xs text-muted-foreground">Reading a live quote…</p>}
      {preview && !done && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <OrderType type={type} onChange={setType} />
            {type === "limit" && (
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Limit $
                <input aria-label="Paper sell limit price" data-testid="paper-close-limit" inputMode="decimal" value={limitText} onChange={e => setLimitText(e.target.value.replace(/[^\d.]/g, ""))} className={cn(INPUT, "w-20")} />
              </label>
            )}
          </div>
          <p className={cn("tabular-nums", type === "market" ? "text-xs" : "text-[11px] text-muted-foreground")}>{type === "limit" && "Now: "}{fillLine({ ...preview, quantity: valid ? qtyN : preview.quantity, cash: share ?? preview.cash }, false, position.multiplier)}.</p>
          {type === "limit" && <p className="text-[11px] text-muted-foreground">{limitValid ? `${limitWords(limitN, spread, position.credit, true)}, on a live quote only; until the close or until you cancel it.` : "Name the limit price."}</p>}
          <div className="flex flex-wrap items-center gap-2">
            {trim && <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Of {free}
              <input aria-label="Paper quantity to trim" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, ""))} className={cn(INPUT, "w-16")} />
            </label>}
            {type === "market"
              ? <SwipeToSubmit testId="paper-close-fill" label="Fill on paper" onSubmit={fill} disabled={!valid} busy={busy} />
              : <SwipeToSubmit testId="paper-close-place" label="Place limit on paper" onSubmit={place} disabled={!valid || !limitValid} busy={busy} />}
            {!sheet && <button type="button" onClick={onDone} className={QUIET}>Cancel</button>}
          </div>
        </>
      )}
      {error && <div className="flex flex-wrap items-center gap-2"><p role="alert" className="text-xs text-amber-300">{error}</p>{!sheet && <button type="button" onClick={onDone} className={QUIET}>Close</button>}</div>}
      {done && <div className="flex flex-wrap items-center gap-2"><p role="status" className="text-xs text-emerald-300">{done}</p><button type="button" onClick={onDone} className={QUIET}>Done</button></div>}
    </div>
  );
  if (!sheet) return inner;
  const legs = preview ? Object.values(preview.legs) : [];
  const review: PaperOrderReview = {
    title: sheet.title, side: "sell", orderType: type, quantity: qtyN, unit: position.multiplier === 1 ? "shares" : "contracts",
    price: type === "limit" ? (limitValid ? limitN : null) : legs.length === 1 ? legs[0].price : preview ? Math.abs(preview.per_share) : null,
    quotedAt: preview?.quoted_at ?? null, estimated: type === "market" ? share : null, buyingPowerAfter: null,
  };
  return <PaperOrderSheet review={review} onCancel={onDone}>{sheet.top}{inner}</PaperOrderSheet>;
}

/** Working paper limits, each with its last check and Cancel. */
function WorkingOrders({ orders }: { orders: PaperWorkingOrder[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!orders.length) return null;
  const cancel = async (id: string) => {
    setBusy(id); setError(null);
    try { await cancelPaperOrder(id); } catch (e) { setError(e instanceof Error ? e.message : "Not canceled."); } finally { setBusy(null); }
  };
  return (
    <div className="border-t border-border/60">
      <p className={cn(LABEL, "px-3 pt-1.5")}>Working orders</p>
      <ul aria-label="Working paper orders" data-testid="paper-orders">
        {orders.map(o => {
          const verb = o.instrument === "spread" ? (o.side === "open" ? "Open" : "Close") : (o.side === "open" ? "Buy" : "Sell");
          const what = o.instrument === "stock" ? `${o.quantity.toLocaleString("en-US")} ${o.label}` : `${o.quantity.toLocaleString("en-US")} × ${o.label}`;
          const terms = o.instrument === "spread" ? (o.pays ? "debit or less" : "credit or more") : "or better";
          const c = o.check;
          const last = !c ? "not checked yet" : c.quoted_at == null ? "no quote yet" : `quote ${at(c.quoted_at)}${c.issue ? ", not live" : c.natural != null ? `: ${price(c.natural)} now` : ""}`;
          return (
            <li key={o.id} data-testid="paper-order" className="flex items-center gap-2 px-3 py-1.5 text-xs tabular-nums">
              <div className="min-w-0 flex-1">
                <p data-testid="paper-order-terms"><span className="font-medium">{verb} {what}</span> · <span className="text-violet-200">limit {price(o.limit)}</span> {terms}</p>
                <p className="text-[11px] text-muted-foreground">until {at(o.expires_at)}{o.reserve > 0 && ` · holds ${usd(o.reserve)}`} · <span data-testid="paper-order-check" title={c?.issue ?? undefined}>{last}</span></p>
              </div>
              <button type="button" data-testid="paper-order-cancel" disabled={busy === o.id} onClick={() => cancel(o.id)} className={cn(BUTTON, "px-2")}>Cancel</button>
            </li>
          );
        })}
      </ul>
      {error && <p role="alert" className="px-3 pb-1 text-xs text-amber-300">{error}</p>}
    </div>
  );
}

/** The position's stop and target, the "Close automatically at stop/target" switch (off by default, so whether he kept
 *  his stop still means something), and what touched. */
function Levels({ p }: { p: PaperPosition }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const has = p.stop != null || p.target != null;
  if (!has && !p.note) return null;
  const flip = async (on: boolean) => {
    setBusy(true); setError(null);
    try { await setPaperAuto(p.id, on); } catch (e) { setError(e instanceof Error ? e.message : "Not changed."); } finally { setBusy(false); }
  };
  const touched = Object.entries(p.touched ?? {}).map(([level, when]) => `${level} touched ${at(when!)}`);
  return (
    <div className="space-y-1 px-3 pb-1.5 text-[11px] text-muted-foreground">
      {(has || p.note) && <p className="truncate">{p.stop != null && <>Stop {p.stop} </>}{p.target != null && <>· Target {p.target} </>}{p.note && <>· {p.note}</>}</p>}
      {has && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <label className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 sm:min-h-0">
            <input type="checkbox" data-testid="paper-auto" checked={!!p.auto} disabled={busy} onChange={e => flip(e.target.checked)} className="h-4 w-4 accent-violet-400" />
            <span className={cn(p.auto && "text-violet-100")}>Close automatically at stop/target</span>
          </label>
          {p.exiting && <span data-testid="paper-exiting" className="text-amber-200">Touched: selling at the next fresh bid</span>}
          {!p.exiting && touched.length > 0 && <span data-testid="paper-touched">{touched.join(" · ")}{p.auto ? "" : ", nothing closed"}</span>}
        </div>
      )}
      {error && <p role="alert" className="text-amber-300">{error}</p>}
    </div>
  );
}

/** Whose idea a paper position was, when it was not his own ticket: a small tag after its label. */
function SourceTag({ source }: { source?: PaperSource }) {
  if (!source || source === "mine") return null;
  return <span data-testid="paper-source" className="ml-1.5 rounded border border-border px-1 align-middle text-[10px] uppercase tracking-wide text-muted-foreground">{SOURCE_WORD[source]}</span>;
}

/** Closed paper P&L by whose idea it was, one compact line: "Mine +$84.50 50%/2 · Copilot …" (win rate / closed trades).
 *  Only once a paper trade has closed. */
function BySource({ rows }: { rows?: PaperStats["by_source"] }) {
  const shown = PAPER_SOURCES.map(s => rows?.find(r => r.source === s)).filter((r): r is NonNullable<typeof r> => !!r);
  if (!shown.some(r => r.trades > 0)) return null;
  return (
    <p data-testid="paper-by-source" aria-label="Closed paper P&L by whose idea" title="Closed paper P&L, win rate and trades by whose idea it was"
      className="flex flex-wrap gap-x-2.5 px-3 pt-0.5 text-[11px] tabular-nums">
      {shown.map(r => (
        <span key={r.source} data-testid="paper-by-source-cell" data-source={r.source} className="whitespace-nowrap">
          <span className="text-muted-foreground">{SOURCE_WORD[r.source]} </span>
          {r.trades === 0 ? <span className="text-muted-foreground">—</span> : <>
            <span className={toneOf(r.pnl)}>{signed(r.pnl)}</span><span className="text-muted-foreground"> {r.win_rate}%/{r.trades}</span></>}
        </span>
      ))}
    </p>
  );
}

/** Both sides' closed P&L by day, one small chart: paper solid, real dashed, a zero line. */
function Curve({ paper, real }: { paper: PaperStats["curve"]; real: PaperStats["curve"] }) {
  const days = [...new Set([...paper, ...real].map(p => p.day))].sort();
  if (days.length === 0) return <p className="text-xs text-muted-foreground">No closed trades yet on either side.</p>;
  const carry = (curve: PaperStats["curve"]) => { let last = 0; return days.map(d => { const hit = curve.find(p => p.day === d); if (hit) last = hit.pnl; return last; }); };
  const a = carry(paper), b = carry(real);
  const values = [0, ...a, ...b];
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const x = (i: number) => days.length === 1 ? 100 : i / (days.length - 1) * 200;
  const y = (v: number) => 44 - (v - lo) / span * 40;
  const line = (vals: number[]) => vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <figure className="space-y-1">
      <svg viewBox="0 0 200 48" preserveAspectRatio="none" className="h-14 w-full" role="img" aria-label="Closed P&L by day: paper and real">
        <line x1="0" x2="200" y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity="0.25" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
        {days.length > 1 ? <>
          <polyline points={line(b)} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth="1.25" strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />
          <polyline points={line(a)} fill="none" stroke="rgb(196 181 253)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </> : <>
          <circle cx={x(0)} cy={y(b[0])} r="2" fill="hsl(var(--muted-foreground))" />
          <circle cx={x(0)} cy={y(a[0])} r="2" fill="rgb(196 181 253)" />
        </>}
      </svg>
      <figcaption className="flex justify-between text-[11px] text-muted-foreground">
        <span>{days[0].slice(5).replace("-", "/")}</span>
        <span><span className="text-violet-300">— </span><ModeMark mode="paper" short /> · <span>- - </span><ModeMark mode="real" /> · closed P&amp;L by day</span>
        <span>{days[days.length - 1].slice(5).replace("-", "/")}</span>
      </figcaption>
    </figure>
  );
}

function Score({ paper, real, since }: { paper: PaperStats; real: PaperStats; since: number }) {
  const rows: [string, (s: PaperStats) => React.ReactNode][] = [
    ["Closed P&L", s => <span className={toneOf(s.pnl)}>{signed(s.pnl)}</span>],
    ["Trades", s => s.trades],
    ["Win rate", s => s.win_rate == null ? "—" : `${s.win_rate}%`],
    ["Avg winner", s => s.avg_win == null ? "—" : <span className="text-emerald-300">{signed(s.avg_win)}</span>],
    ["Avg loser", s => s.avg_loss == null ? "—" : <span className="text-rose-300">{signed(s.avg_loss)}</span>],
    ["Largest loss", s => s.largest_loss == null ? "—" : <span className="text-rose-300">{signed(s.largest_loss)}</span>],
  ];
  return (
    <table data-testid="paper-score" className="w-full text-xs tabular-nums">
      <thead><tr className="text-muted-foreground"><th className="py-1 text-left font-normal">Since {day(since)}</th><th className="text-right font-medium"><ModeMark mode="paper" short /></th><th className="text-right font-medium"><ModeMark mode="real" /></th></tr></thead>
      <tbody>{rows.map(([name, cell]) => <tr key={name} className="border-t border-border/50"><td className="py-1 text-muted-foreground">{name}</td><td className="text-right">{cell(paper)}</td><td className="text-right">{cell(real)}</td></tr>)}</tbody>
    </table>
  );
}

/** Paper next to real: closed P&L and win rate for each, with their marks, since the run started. The Paper section's
 *  line, and the desk's Close the day checklist shows the same line (``testId`` apart). */
const pct = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}%`;
const dayTime = (epoch: number) => `${new Date(epoch * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric" })} ${at(epoch)}`;

/** "Run 3 · failed Nov 21 · −8.1%": a challenge run's permanent record. */
export function runRecord(number: number, record: ChallengeRecord) {
  const when = record.at != null ? ` ${day(record.at)}` : "";
  return `Run ${number} · ${record.result}${when}${record.pct != null ? ` · ${pct(record.pct)}` : ""}`;
}

/** The paper challenge in one line of the Paper section: today's P&L against the daily limit, the distance to the target
 *  and to the max drawdown, from the desk's live prices when they are live, else the backend's last read (grey, with its
 *  time; never a zero). A lock, a fail or a pass replaces the line with what happened and what it means. */
export function ChallengeLine({ c, live }: { c: PaperChallenge; live: { value: number; at: number | null; stale: boolean } | null }) {
  if (c.result?.kind === "fail") {
    return (
      <p role="status" data-testid="paper-challenge" data-state="failed" className="mx-3 mb-1.5 rounded-md border border-rose-400/50 bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200">
        <span className="font-semibold">Challenge failed {day(c.result.at)}</span> · {pct(c.result.pct)} · {c.result.reason} No new paper opens; closes still work.
        {c.result.next_run_at != null && <> A new run can start {dayTime(c.result.next_run_at)}.</>}
      </p>
    );
  }
  if (c.result?.kind === "pass") {
    return (
      <p role="status" data-testid="paper-challenge" data-state="passed" className="mx-3 mb-1.5 rounded-md border border-emerald-400/50 bg-emerald-500/10 px-2 py-1.5 text-xs text-emerald-200">
        <span className="font-semibold">Challenge passed {day(c.result.at)} · {pct(c.result.pct)}</span> · {c.result.reason} Closes still work; start a new run to go again.
      </p>
    );
  }
  if (c.lock) {
    return (
      <p role="status" data-testid="paper-challenge" data-state="locked" className="mx-3 mb-1.5 rounded-md border border-amber-400/60 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
        <span className="font-semibold">Locked: daily loss limit hit</span> · today <span className="whitespace-nowrap">{signed(c.lock.pnl)}</span> of the <span className="whitespace-nowrap">−{usd(c.lock.limit)}</span> limit. New paper opens unlock {dayTime(c.lock.until)}; closes still work.
      </p>
    );
  }
  // Live equity from the desk's ticks when every price is live; otherwise the backend's last read, shown grey with its time.
  const fromTicks = live && !live.stale;
  const equity = fromTicks ? live!.value : c.equity;
  const stale = !fromTicks && !(c.fresh && c.equity != null);
  const when = fromTicks ? live!.at : c.prices_at;
  if (equity == null || c.start_of_day == null || c.daily_limit == null) {
    return (
      <p data-testid="paper-challenge" data-state="stale" className="px-3 pb-1.5 text-xs text-muted-foreground">
        Challenge · needs a live price{when ? ` (last ${at(when)})` : ""} to judge today against the limits.
      </p>
    );
  }
  const today = Math.round((equity - c.start_of_day) * 100) / 100;
  const floor = Math.round(Math.max(c.peak, equity) * (1 - c.rules.max_dd_pct / 100) * 100) / 100;
  const toTarget = Math.round((c.target_equity - equity) * 100) / 100;
  const toFloor = Math.round((equity - floor) * 100) / 100;
  const used = today < 0 ? -today / c.daily_limit : 0;
  return (
    <p data-testid="paper-challenge" data-state={stale ? "stale" : "live"} className={cn("flex flex-wrap gap-x-3 px-3 pb-1.5 text-xs tabular-nums", stale && "text-muted-foreground")}>
      <span className={cn(!stale && "text-muted-foreground")}>Challenge</span>
      <span data-testid="paper-challenge-today">Today <span className={stale ? undefined : used >= 0.66 ? "text-amber-300" : toneOf(today)}>{signed(today)}</span>
        <span className={cn(!stale && "text-muted-foreground")}> of <span className="whitespace-nowrap">−{usd(c.daily_limit)}</span> limit</span></span>
      <span data-testid="paper-challenge-target">{toTarget > 0 ? <>{usd(toTarget)} <span className={cn(!stale && "text-muted-foreground")} title={`Target: equity ${usd(c.target_equity)} (+${c.rules.target_pct}%)`}>to target</span></> : "At the target"}</span>
      <span data-testid="paper-challenge-floor">{usd(toFloor)} <span className={cn(!stale && "text-muted-foreground")} title={`Max drawdown: equity ${usd(floor)} fails the run (−${c.rules.max_dd_pct}% from the ${usd(Math.max(c.peak, equity))} peak)`}>to max drawdown</span></span>
      {stale && when && <span className="text-[11px]">as of {at(when)}</span>}
    </p>
  );
}

export function PaperScoreLine({ score, since, testId = "paper-score-line", className = "px-3 pt-1.5" }: {
  score: NonNullable<PaperBook["score"]>; since: number; testId?: string; className?: string;
}) {
  return (
    <p data-testid={testId} className={cn("flex flex-wrap gap-x-3 text-xs tabular-nums", className)}>
      <span className="inline-flex items-center gap-1"><ModeMark mode="paper" short />{" "}<span className={toneOf(score.paper.pnl)}>{signed(score.paper.pnl)}</span>{score.paper.win_rate != null && <span className="text-muted-foreground"> · {score.paper.win_rate}% of {score.paper.trades}</span>}</span>
      <span className="inline-flex items-center gap-1"><ModeMark mode="real" />{" "}{score.real.trades === 0 ? <span className="text-muted-foreground">no closed trades</span> : <>
        <span className={toneOf(score.real.pnl)}>{signed(score.real.pnl)}</span><span className="text-muted-foreground"> · {score.real.win_rate}% of {score.real.trades}</span></>}</span>
      <span className="text-muted-foreground">closed, since {day(since)}</span>
    </p>
  );
}

const nyDay = (epoch: number) => new Date(epoch * 1000).toLocaleDateString("en-CA", { timeZone: "America/New_York" });

/** A position's change today: all of its P&L when it was opened on the day of its price; shares from the previous close
 *  (the desk's tick); otherwise null (an option's previous close is not read, so it is left out rather than guessed). */
function todayChange(p: PaperPosition, ticks: DeskTicks): number | null {
  const pnl = paperPnl(p, ticks);
  if (!pnl) return null;
  if (nyDay(p.opened_at) === nyDay(pnl.at)) return pnl.pnl;
  if (p.instrument !== "stock") return null;
  const tick = tickFor(ticks, p.symbol);
  return tick?.prev_close != null && pnl.live ? Math.round((tick.last - tick.prev_close) * p.remaining * 100) / 100 : null;
}

/** The Paper section (the desk's Practice block opens it in place): one panel, folded to its account line and score line
 *  until Progress is opened. His rules and goals are the desk's own line (``RulesAndGoals``): they cover real trades too. */
export default function DeskPaper({ book, failed, symbol, top = null, onPick }: {
  book: PaperBook | null; failed: boolean; symbol: string | null; top?: React.ReactNode;
  /** Shows a position's ticker on the desk: its chart, with the position's own panel (stop and target, trim, close, note) under it. */
  onPick?(symbol: string): void;
}) {
  const [progress, setProgress] = useState(false);
  const [closing, setClosing] = useState<{ id: string; trim: boolean } | null>(null);
  const [range, setRange] = useState<EquityRange>("1D");
  const equity = usePaperEquity(range, !!book?.run);
  const [cash, setCash] = useState("10000");
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ticks = useDeskTicks(paperSymbols(book?.positions));
  const start = async (reset: boolean, challenge = false) => {
    setError(null);
    try { await startPaper(Number(cash), reset, challenge); setResetting(false); } catch (e) { setError(e instanceof Error ? e.message : "Not started."); }
  };
  const head = (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 pb-1.5 pt-2.5">
      <h2 className="self-center"><ModeMark mode="paper" /></h2>
      {book?.run && <span className="text-[11px] text-muted-foreground">run {book.run.number} · since {day(book.run.started_at)}</span>}
      {book?.run && <button type="button" aria-expanded={progress} data-testid="paper-progress-toggle" onClick={() => setProgress(p => !p)} className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">{progress ? "Hide progress" : "Progress"}</button>}
    </div>
  );
  const frame = (children: React.ReactNode) => (
    <section aria-label="Paper book" data-testid="desk-paper" className="rounded-lg border border-dashed border-violet-400/40 bg-card">{head}{children}</section>
  );
  if (!book) return frame(<p className="px-3 pb-2.5 text-xs text-muted-foreground">{failed ? "Your paper book could not be read; it reads again in a minute." : "Reading your paper book…"}</p>);
  const cooldown = book.cooldown_until ?? null;
  const startForm = (reset: boolean) => cooldown != null ? (
    <p data-testid="paper-cooldown" className="text-xs text-muted-foreground">Your last challenge failed: a new run can start {dayTime(cooldown)}.
      {reset && <button type="button" onClick={() => setResetting(false)} className={cn(QUIET, "ml-1")}>OK</button>}</p>
  ) : (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" data-testid={reset ? "paper-challenge-reset" : "paper-challenge-start"} onClick={() => start(reset, true)}
        title="$10,000 · +10% target · a 3% daily loss locks opens until the next trading day · an 8% drawdown fails the run (no new run for 7 days)"
        className={cn(BUTTON, "border-violet-400 bg-violet-400 font-semibold text-black hover:bg-violet-300")}>Start $10,000 challenge</button>
      <span className="text-[11px] text-muted-foreground">+10% target · 3% daily lock · 8% max drawdown</span>
      <span className="text-[11px] text-muted-foreground">or</span>
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Start with $
        <input aria-label="Paper starting cash" inputMode="numeric" value={cash} onChange={e => setCash(e.target.value.replace(/[^\d]/g, ""))} className={cn(INPUT, "w-24")} />
      </label>
      <button type="button" data-testid={reset ? "paper-reset-confirm" : "paper-start"} onClick={() => start(reset)} className={BUTTON}>{reset ? "Start a new run" : "Start paper trading"}</button>
      {reset && <button type="button" onClick={() => setResetting(false)} className={QUIET}>Cancel</button>}
      {error && <p role="alert" className="w-full text-xs text-amber-300">{error}</p>}
    </div>
  );
  if (!book.run) {
    return frame(
      <div className="pb-3">
        <div className="space-y-2 px-3">
          <p className="text-xs text-muted-foreground">Trade the way you would on Robinhood, with no money: Paper on the Ticket or the Chain fills at the live ask (the bid to sell), or places a day limit, and keeps score against your real trades.</p>
          {startForm(false)}
        </div>
      </div>,
    );
  }
  const acct = book.account!, score = book.score!;
  const value = paperValue(book, ticks);
  const positions = book.positions ?? [];
  const closed = book.closed ?? [];
  return frame(
    <div className="pb-2">
      {top}
      <div data-testid="paper-account">
        <PortfolioGraph value={value} unpriced={acct.unpriced} series={equity.series} failed={equity.failed} range={range} onRange={setRange}
          status={book.challenge && <div className="-mx-3 mt-1"><ChallengeLine c={book.challenge} live={value} /></div>} />
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 px-3 pb-1.5 text-xs tabular-nums">
        <span><span className="text-muted-foreground">Cash </span>{acct.cash < 0 ? "−" : ""}{usd(acct.cash)}</span>
        <span><span className="text-muted-foreground">Buying power </span>{usd(acct.buying_power)}</span>
        {acct.collateral > 0 && <span><span className="text-muted-foreground">Held for spreads </span>{usd(acct.collateral)}</span>}
        {(acct.reserved ?? 0) > 0 && <span><span className="text-muted-foreground">Held for orders </span>{usd(acct.reserved!)}</span>}
        </p>
      </div>
      <WorkingOrders orders={book.orders ?? []} />
      {positions.length > 0 ? (
        <ul aria-label="Paper positions" className="space-y-1.5 border-t border-border/60 px-3 pt-2">
          {positions.map(p => {
            const free = p.remaining - (p.held ?? 0);
            const open = closing?.id === p.id;
            return (
              <li key={p.id} data-testid="paper-position">
                <PaperPositionCard position={p} todayChange={todayChange(p, ticks)} tag={<SourceTag source={p.source} />} expanded={open}
                  onOpen={() => setClosing(open ? null : { id: p.id, trim: false })} />
                <Levels p={p} />
                {open && (
                  // The order sheet: a bottom sheet over the page on a phone, in place under the card on a laptop.
                  <div data-testid="paper-sheet" className="fixed inset-0 z-50 flex items-end bg-black/60 sm:static sm:z-auto sm:mt-1.5 sm:block sm:bg-transparent"
                    onClick={e => { if (e.target === e.currentTarget) setClosing(null); }}>
                    <div className="max-h-[90dvh] w-full overflow-y-auto sm:max-h-none">
                      {free > 0 ? (
                        <CloseRow key={`${p.id}|${closing.trim}`} position={p} trim={closing.trim} onDone={() => setClosing(null)}
                          sheet={{ title: `${closing.trim ? "Trim" : "Sell"} ${p.label}`, top: (
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <div role="radiogroup" aria-label="Sell all or trim" className="inline-flex rounded-md border text-xs">
                                {([false, true] as const).map(t => (
                                  <button key={String(t)} type="button" role="radio" aria-checked={closing.trim === t} disabled={t && free <= 1}
                                    data-testid={t ? "paper-trim-button" : "paper-close-button"} onClick={() => setClosing({ id: p.id, trim: t })}
                                    className={cn("min-h-11 px-3 first:rounded-l-md last:rounded-r-md disabled:opacity-45 sm:min-h-8",
                                      closing.trim === t ? "bg-violet-400/15 text-violet-100" : "text-muted-foreground hover:bg-secondary")}>{t ? "Trim" : `Sell all ${free}`}</button>
                                ))}
                              </div>
                              {onPick && <button type="button" data-testid="paper-position-show" onClick={() => { setClosing(null); onPick(p.symbol); }}
                                title={`Show ${p.symbol} on the desk, with this position's panel under the chart`} className={QUIET}>Show on chart</button>}
                            </div>
                          ) }} />
                      ) : <p className="rounded-lg border border-dashed border-violet-400/40 bg-card px-3 py-2 text-xs text-muted-foreground">All {p.remaining} held for a working sell limit; cancel it to sell another way.</p>}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      ) : <p className="border-t border-border/60 px-3 py-1.5 text-xs text-muted-foreground">No paper positions. Paper on the Ticket or the Chain{symbol ? `, or ${symbol} shares here` : ""}.</p>}
      {symbol && !(book.challenge?.lock || book.challenge?.result) && <div className="flex flex-wrap gap-2 px-3 pt-1.5"><PaperButton key={symbol} order={{ instrument: "stock", symbol }} quantity={10} label={`Paper buy ${symbol} shares`} /></div>}
      <PaperScoreLine score={score} since={book.run.started_at} />
      <BySource rows={score.paper.by_source} />
      {progress && (
        <div data-testid="paper-progress" className="space-y-3 px-3 pt-2">
          <Score paper={score.paper} real={score.real} since={book.run.started_at} />
          <Curve paper={score.paper.curve} real={score.real.curve} />
          <div>
            <p className={LABEL}>Closed paper trades</p>
            {closed.length ? (
              <ul className="divide-y divide-border/50">
                {closed.map(c => (
                  <li key={c.id} data-testid="paper-closed" className="py-1.5 text-xs">
                    <div className="flex items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate"><span className="font-medium">{c.label}</span> ×{c.quantity} · {day(c.opened_at)}–{day(c.closed_at!)}<SourceTag source={c.source} /></span>
                      <span className={cn("tabular-nums", toneOf(c.realized))}>{signed(c.realized)}</span>
                    </div>
                    <p className={cn("text-[11px]", c.verdict?.kind === "stop" || c.verdict?.kind === "target" ? "text-foreground/80" : "text-muted-foreground")}>{c.verdict?.auto && <span data-testid="paper-auto-tag" className="mr-1 rounded border border-violet-400/50 px-1 text-[10px] uppercase tracking-wide text-violet-200">auto</span>}{c.verdict?.text}{c.note ? ` · “${c.note}”` : ""}</p>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-muted-foreground">None yet.</p>}
          </div>
          {book.earlier.length > 0 && (
            <div data-testid="paper-earlier" className="text-[11px] text-muted-foreground">
              {book.earlier.some(r => r.challenge) && (
                <ul className="mb-1">{book.earlier.filter(r => r.challenge).map(r => (
                  <li key={r.number} data-testid="paper-run-record" className={cn(r.challenge!.result === "passed" ? "text-emerald-300" : r.challenge!.result === "failed" ? "text-rose-300" : undefined)}>{runRecord(r.number, r.challenge!)}</li>
                ))}</ul>
              )}
              {book.earlier.some(r => !r.challenge) && <p>Earlier runs: {book.earlier.filter(r => !r.challenge).map(r => `run ${r.number} (${day(r.started_at)}–${day(r.ended_at)}, ${usd(r.starting_cash)} start) ${signed(r.realized)} closed over ${r.trades}`).join("; ")}.</p>}
            </div>
          )}
          {resetting ? startForm(true) : (
            <button type="button" data-testid="paper-reset" onClick={() => setResetting(true)} className={QUIET}>New run…</button>
          )}
          <p className="text-[11px] text-muted-foreground">A new run starts fresh cash; this run&apos;s trades stay in its history. Real is your closed trades in the journal over the same dates.</p>
        </div>
      )}
    </div>,
  );
}
