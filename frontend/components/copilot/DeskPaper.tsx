"use client";

import { useCallback, useEffect, useState } from "react";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { useDeskTicks } from "@/lib/deskTicks";
import {
  PAPER_EVENT, PAPER_SOURCES, PaperRefused, SOURCE_WORD, cancelPaperOrder, orderWords, fillClose, fillOpen, isCredit, orderKey, paperPnl, paperSymbols, paperValue, placeLimitClose,
  placeLimitOpen, previewClose, previewOpen, setPaperAuto, startPaper,
  type PaperBook, type PaperFill, type PaperOrder, type PaperPosition, type PaperSource, type PaperStats, type PaperWorkingOrder,
} from "@/lib/paperBook";
import { cn } from "@/lib/utils";

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
            type === t ? "bg-amber-400/15 text-amber-100" : "text-muted-foreground hover:bg-secondary")}>{t === "market" ? "Market" : "Limit"}</button>
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
 * button disabled with ``why``.
 */
export function PaperButton({ order, quantity = 1, note = null, stop = null, target = null, label = "Paper trade it", source = "mine", ideaId = null, why = null }: {
  order: PaperOrder | null; quantity?: number | null; note?: string | null; stop?: number | null; target?: number | null; label?: string;
  source?: PaperSource; ideaId?: string | null; why?: string | null;
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
  const qtyN = Number(qty);
  const valid = Number.isInteger(qtyN) && qtyN > 0;
  const limitN = Number(limitText);
  const limitValid = limitText.trim() !== "" && limitN > 0;
  const spread = order?.instrument === "spread";
  const credit = !!order && isCredit(order);
  const refuse = (e: unknown) => setError({ text: e instanceof Error ? e.message : "Not filled.", start: e instanceof PaperRefused && /Start a paper account/.test(e.message) });

  const check = async (count = qtyN) => {
    if (!order) return;
    setOpen(true); setBusy(true); setError(null); setDone(null); setKey(orderKey()); setClosedNow(false);
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
    return { note: words.trim() || null, stop: level(stopText), target: level(targetText),
      // The idea's id as the book keeps it (letters, digits and _ . : -, at most 64), or none.
      ...(source !== "mine" ? { source, idea_id: ideaId?.replace(/[^A-Za-z0-9_.:-]/g, "").slice(0, 64) || null } : {}) };
  };
  const fill = async () => {
    if (!order || !valid) return;
    setBusy(true); setError(null);
    try {
      const filled = await fillOpen(order, qtyN, levels(), key);
      setDone(filled ? `Paper: ${fillLine(filled, true, multiplier)}.` : "Already filled on paper.");
      setPreview(null);
    } catch (e) { refuse(e); } finally { setBusy(false); }
  };
  const place = async () => {
    if (!order || !valid || !limitValid) return;
    setBusy(true); setError(null);
    try {
      const placed = await placeLimitOpen(order, qtyN, limitN, levels(), key);
      setDone(placed.filled ? `Paper limit filled: ${fillLine(placed.filled, true, multiplier)}.`
        : placed.working ? `Paper limit working: ${spread ? "open" : "buy"} ${qtyN.toLocaleString("en-US")} at ${price(limitN)}${spread ? (credit ? " credit or more" : " debit or less") : " or better"}, until ${at(placed.working.expires_at)} or until you cancel it below.`
        : "Already placed on paper.");
      setPreview(null); setClosedNow(false);
    } catch (e) { refuse(e); } finally { setBusy(false); }
  };
  const start = async () => {
    setBusy(true);
    try { await startPaper(10_000); await check(); } catch (e) { refuse(e); } finally { setBusy(false); }
  };

  if (!open) {
    const button = (
      <button type="button" data-testid="paper-button" data-source={source} disabled={!order} aria-describedby={!order && why ? `paper-why-${ideaId ?? source}` : undefined}
        onClick={() => { const n = quantity && quantity > 0 ? quantity : 1; setQty(String(n)); setType("market"); check(n); }}
        title={!order && why ? why : "Fill this on paper at the live quote, or place a paper limit: no money, nothing sent"}
        className={cn(BUTTON, "border-amber-400/60 text-amber-200")}>{label}</button>
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
  return (
    <div data-testid="paper-confirm" className="w-full space-y-2 rounded-md border border-dashed border-amber-400/50 p-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-200">Paper · not real money{source !== "mine" && <span data-testid="paper-idea" className="ml-1 font-normal normal-case tracking-normal text-muted-foreground">· {SOURCE_WORD[source]}&apos;s idea{order ? `: ${orderWords(order)}` : ""}</span>}</p>
      {busy && !form && <p className="text-xs text-muted-foreground">Reading a live quote…</p>}
      {form && !done && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <OrderType type={type} onChange={setType} market={!closedNow} />
            {type === "limit" && (
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Limit $
                <input aria-label="Paper limit price" data-testid="paper-limit" inputMode="decimal" value={limitText} onChange={e => setLimitText(e.target.value.replace(/[^\d.]/g, ""))} className={cn(INPUT, "w-20")} />
              </label>
            )}
          </div>
          {closedNow && <p className="text-xs text-muted-foreground">The market is closed, so there is no live quote to fill at. A limit placed before the open works from 9:30 AM ET until the close.</p>}
          {preview && type === "market" && <p data-testid="paper-preview" className="text-sm tabular-nums">{fillLine({ ...preview, quantity: valid ? qtyN : preview.quantity, cash: cost ?? preview.cash }, true, multiplier)}.</p>}
          {preview && type === "limit" && <p className="text-xs tabular-nums text-muted-foreground">Now: {fillLine({ ...preview, quantity: valid ? qtyN : preview.quantity, cash: cost ?? preview.cash }, true, multiplier)}.</p>}
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">{multiplier === 1 ? "Shares" : order?.instrument === "spread" ? "Spreads" : "Contracts"}
              <input aria-label="Paper quantity" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, ""))} className={cn(INPUT, "w-20")} />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Stop
              <input aria-label="Paper stop (stock price)" inputMode="decimal" placeholder="stock $" value={stopText} onChange={e => setStopText(e.target.value)} className={cn(INPUT, "w-20")} />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">Target
              <input aria-label="Paper target (stock price)" inputMode="decimal" placeholder="stock $" value={targetText} onChange={e => setTargetText(e.target.value)} className={cn(INPUT, "w-20")} />
            </label>
          </div>
          <input aria-label="Paper note" maxLength={280} placeholder="Why (optional, one line)" value={words} onChange={e => setWords(e.target.value)} className={cn(INPUT, "w-full")} />
          {type === "market" && preview ? (
            <p className="text-[11px] text-muted-foreground">Fill on paper re-reads the quote and fills at that moment&apos;s {Object.values(preview.legs).length > 1 ? "natural price" : "ask"}. {preview.buying_power != null && preview.need_each != null && valid && <>Paper buying power after: {preview.buying_power - preview.need_each * qtyN < 0 ? "−" : ""}{usd(preview.buying_power - preview.need_each * qtyN)}{preview.buying_power - preview.need_each * qtyN < 0 ? " (not enough)" : ""}.</>}</p>
          ) : (
            <p data-testid="paper-limit-words" className="text-[11px] text-muted-foreground">{limitValid ? <>{limitWords(limitN, spread, !credit, false)}, on a live quote only. A day order: it works until the close or until you cancel it{hold != null && <>, and holds {usd(hold)} of paper buying power meanwhile</>}.</> : "Name the limit price."}</p>
          )}
          <div className="flex flex-wrap gap-2">
            {type === "market"
              ? <button type="button" data-testid="paper-fill" disabled={busy || !valid || !preview} onClick={fill} className={cn(BUTTON, "border-amber-400/70 text-amber-100")}>Fill on paper</button>
              : <button type="button" data-testid="paper-place-limit" disabled={busy || !valid || !limitValid} onClick={place} className={cn(BUTTON, "border-amber-400/70 text-amber-100")}>Place limit on paper</button>}
            <button type="button" onClick={() => { setOpen(false); setPreview(null); setError(null); setClosedNow(false); }} className={QUIET}>Cancel</button>
          </div>
        </>
      )}
      {error && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" data-testid="paper-refused" className="text-xs text-amber-300">{error.text}</p>
          {error.start && <button type="button" disabled={busy} onClick={start} className={BUTTON}>Start a $10,000 paper account</button>}
          {!form && <button type="button" onClick={() => { setOpen(false); setError(null); }} className={QUIET}>Close</button>}
        </div>
      )}
      {done && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="status" data-testid="paper-done" className="text-xs text-emerald-300">{done}</p>
          <button type="button" onClick={() => { setOpen(false); setDone(null); }} className={QUIET}>Done</button>
        </div>
      )}
    </div>
  );
}

/** Close or trim an open paper position: a live quote first, then Fill on paper at the bid (the ask to buy a leg back),
 *  or a sell limit that waits for its price until the close. What a working sell limit holds cannot be sold twice. */
function CloseRow({ position, trim, onDone }: { position: PaperPosition; trim: boolean; onDone(): void }) {
  const free = position.remaining - (position.held ?? 0);
  const [qty, setQty] = useState(String(trim ? Math.max(1, Math.floor(free / 2)) : free));
  const [preview, setPreview] = useState<PaperFill | null>(null);
  const [type, setType] = useState<"market" | "limit">("market");
  const [limitText, setLimitText] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [key] = useState(orderKey);
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
      setDone(filled ? `Paper: ${fillLine(filled, false, position.multiplier)}; ${filled.pnl! >= 0 ? "made" : "lost"} ${usd(filled.pnl!)}.` : "Already filled on paper.");
    } catch (e) { setError(e instanceof Error ? e.message : "Not filled."); } finally { setBusy(false); }
  };
  const place = async () => {
    setBusy(true); setError(null);
    try {
      const placed = await placeLimitClose(position.id, qtyN, limitN, key);
      setDone(placed.filled ? `Paper limit filled: ${fillLine(placed.filled, false, position.multiplier)}; ${placed.filled.pnl! >= 0 ? "made" : "lost"} ${usd(placed.filled.pnl!)}.`
        : placed.working ? `Paper limit working: ${spread ? "close" : "sell"} ${qtyN} at ${price(limitN)}, until ${at(placed.working.expires_at)} or until you cancel it.` : "Already placed on paper.");
    } catch (e) { setError(e instanceof Error ? e.message : "Not placed."); } finally { setBusy(false); }
  };
  const share = preview && valid ? Math.round(preview.per_share * position.multiplier * qtyN * 100) / 100 : null;
  return (
    <div data-testid="paper-close" className="space-y-1.5 border-t border-dashed border-amber-400/30 px-3 py-2">
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
              ? <button type="button" data-testid="paper-close-fill" disabled={busy || !valid} onClick={fill} className={cn(BUTTON, "border-amber-400/70 text-amber-100")}>Fill on paper</button>
              : <button type="button" data-testid="paper-close-place" disabled={busy || !valid || !limitValid} onClick={place} className={cn(BUTTON, "border-amber-400/70 text-amber-100")}>Place limit on paper</button>}
            <button type="button" onClick={onDone} className={QUIET}>Cancel</button>
          </div>
        </>
      )}
      {error && <div className="flex flex-wrap items-center gap-2"><p role="alert" className="text-xs text-amber-300">{error}</p><button type="button" onClick={onDone} className={QUIET}>Close</button></div>}
      {done && <div className="flex flex-wrap items-center gap-2"><p role="status" className="text-xs text-emerald-300">{done}</p><button type="button" onClick={onDone} className={QUIET}>Done</button></div>}
    </div>
  );
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
                <p data-testid="paper-order-terms"><span className="font-medium">{verb} {what}</span> · <span className="text-amber-200">limit {price(o.limit)}</span> {terms}</p>
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
            <input type="checkbox" data-testid="paper-auto" checked={!!p.auto} disabled={busy} onChange={e => flip(e.target.checked)} className="h-4 w-4 accent-amber-400" />
            <span className={cn(p.auto && "text-amber-100")}>Close automatically at stop/target</span>
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
          <polyline points={line(a)} fill="none" stroke="rgb(252 211 77)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </> : <>
          <circle cx={x(0)} cy={y(b[0])} r="2" fill="hsl(var(--muted-foreground))" />
          <circle cx={x(0)} cy={y(a[0])} r="2" fill="rgb(252 211 77)" />
        </>}
      </svg>
      <figcaption className="flex justify-between text-[11px] text-muted-foreground">
        <span>{days[0].slice(5).replace("-", "/")}</span>
        <span><span className="text-amber-300">— paper</span> · <span>- - real</span> · closed P&amp;L by day</span>
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
      <thead><tr className="text-muted-foreground"><th className="py-1 text-left font-normal">Since {day(since)}</th><th className="text-right font-medium text-amber-200">Paper</th><th className="text-right font-medium">Real</th></tr></thead>
      <tbody>{rows.map(([name, cell]) => <tr key={name} className="border-t border-border/50"><td className="py-1 text-muted-foreground">{name}</td><td className="text-right">{cell(paper)}</td><td className="text-right">{cell(real)}</td></tr>)}</tbody>
    </table>
  );
}

/** The Paper section under the book: one panel, folded to its account line and score line until Progress is opened. */
export default function DeskPaper({ book, failed, symbol, top = null }: { book: PaperBook | null; failed: boolean; symbol: string | null; top?: React.ReactNode }) {
  const [progress, setProgress] = useState(false);
  const [closing, setClosing] = useState<{ id: string; trim: boolean } | null>(null);
  const [cash, setCash] = useState("10000");
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ticks = useDeskTicks(paperSymbols(book?.positions));
  const start = async (reset: boolean) => {
    setError(null);
    try { await startPaper(Number(cash), reset); setResetting(false); } catch (e) { setError(e instanceof Error ? e.message : "Not started."); }
  };
  const head = (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 pb-1.5 pt-2.5">
      <h2 className={cn(LABEL, "text-amber-200")}>Paper</h2>
      <span className="rounded border border-amber-400/50 px-1 text-[10px] uppercase tracking-wide text-amber-200">not real money</span>
      {book?.run && <span className="text-[11px] text-muted-foreground">run {book.run.number} · since {day(book.run.started_at)}</span>}
      {book?.run && <button type="button" aria-expanded={progress} data-testid="paper-progress-toggle" onClick={() => setProgress(p => !p)} className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">{progress ? "Hide progress" : "Progress"}</button>}
    </div>
  );
  const frame = (children: React.ReactNode) => (
    <section aria-label="Paper book" data-testid="desk-paper" className="rounded-lg border border-dashed border-amber-400/40 bg-card">{head}{children}</section>
  );
  if (!book) return frame(<p className="px-3 pb-2.5 text-xs text-muted-foreground">{failed ? "Your paper book could not be read; it reads again in a minute." : "Reading your paper book…"}</p>);
  const startForm = (reset: boolean) => (
    <div className="flex flex-wrap items-center gap-2">
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
      <div className="space-y-2 px-3 pb-3">
        <p className="text-xs text-muted-foreground">Trade the way you would on Robinhood, with no money: Paper on the Ticket or the Chain fills at the live ask (the bid to sell), or places a day limit, and keeps score against your real trades.</p>
        {startForm(false)}
      </div>,
    );
  }
  const acct = book.account!, score = book.score!;
  const value = paperValue(book, ticks);
  const pnlNow = value ? Math.round((value.value - book.run.starting_cash) * 100) / 100 : null;
  const positions = book.positions ?? [];
  const closed = book.closed ?? [];
  return frame(
    <div className="pb-2">
      {top}
      <p data-testid="paper-account" className="flex flex-wrap gap-x-3 gap-y-0.5 px-3 pb-1.5 text-xs tabular-nums">
        <span data-testid="paper-value"><span className="text-muted-foreground">Value </span>{value ? <span className={cn(value.stale && "text-muted-foreground")}>{usd(value.value)}</span>
          : <span className="text-muted-foreground">needs a live price for {acct.unpriced} open</span>}</span>
        {value && pnlNow != null && <span className={value.stale ? "text-muted-foreground" : toneOf(pnlNow)}>{signed(pnlNow)}{value.stale && value.at && <span className="ml-1 text-[11px]">as of {at(value.at)}</span>}</span>}
        <span><span className="text-muted-foreground">Cash </span>{acct.cash < 0 ? "−" : ""}{usd(acct.cash)}</span>
        <span><span className="text-muted-foreground">Buying power </span>{usd(acct.buying_power)}</span>
        {acct.collateral > 0 && <span><span className="text-muted-foreground">Held for spreads </span>{usd(acct.collateral)}</span>}
        {(acct.reserved ?? 0) > 0 && <span><span className="text-muted-foreground">Held for orders </span>{usd(acct.reserved!)}</span>}
      </p>
      <WorkingOrders orders={book.orders ?? []} />
      {positions.length > 0 ? (
        <ul aria-label="Paper positions">
          {positions.map(p => {
            const pnl = paperPnl(p, ticks);
            return (
              <li key={p.id} data-testid="paper-position" className="border-t border-border/60">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-1.5">
                  <span className="min-w-0 flex-1 text-sm sm:truncate"><span className="font-semibold">{p.label}</span> <span className="text-xs text-muted-foreground">×{p.remaining.toLocaleString("en-US")}</span><SourceTag source={p.source} /></span>
                  {pnl ? (
                    <span data-testid="paper-pnl" className={cn("text-sm tabular-nums", pnl.stale ? "text-muted-foreground" : toneOf(pnl.pnl))} title={pnl.stale ? `Price from ${at(pnl.at)}, not live` : undefined}>
                      {signed(pnl.pnl)}{pnl.pct != null && <span className="ml-1 text-xs">{pnl.pct > 0 ? "+" : pnl.pct < 0 ? "−" : ""}{Math.abs(pnl.pct)}%</span>}
                      {pnl.stale && <span className="ml-1 text-[11px]">as of {at(pnl.at)}</span>}
                    </span>
                  ) : <span data-testid="paper-pnl" className="text-xs text-muted-foreground">{p.awaiting_close ? "Expired: settles on the close once it is read" : "No price yet"}</span>}
                  <span className="flex gap-1">
                    {p.remaining - (p.held ?? 0) > 1 && <button type="button" onClick={() => setClosing({ id: p.id, trim: true })} className={cn(BUTTON, "px-2")}>Trim</button>}
                    <button type="button" data-testid="paper-close-button" disabled={p.remaining - (p.held ?? 0) <= 0} title={p.held ? `${p.held} held for a working sell limit` : undefined}
                      onClick={() => setClosing({ id: p.id, trim: false })} className={cn(BUTTON, "px-2")}>Close</button>
                  </span>
                </div>
                <Levels p={p} />
                {closing?.id === p.id && <CloseRow key={`${p.id}|${closing.trim}`} position={p} trim={closing.trim} onDone={() => setClosing(null)} />}
              </li>
            );
          })}
        </ul>
      ) : <p className="border-t border-border/60 px-3 py-1.5 text-xs text-muted-foreground">No paper positions. Paper on the Ticket or the Chain{symbol ? `, or ${symbol} shares here` : ""}.</p>}
      {symbol && <div className="flex flex-wrap gap-2 px-3 pt-1.5"><PaperButton key={symbol} order={{ instrument: "stock", symbol }} quantity={10} label={`Paper buy ${symbol} shares`} /></div>}
      <p data-testid="paper-score-line" className="flex flex-wrap gap-x-3 px-3 pt-1.5 text-xs tabular-nums">
        <span><span className="text-amber-200">Paper </span><span className={toneOf(score.paper.pnl)}>{signed(score.paper.pnl)}</span>{score.paper.win_rate != null && <span className="text-muted-foreground"> · {score.paper.win_rate}% of {score.paper.trades}</span>}</span>
        <span><span className="text-muted-foreground">Real </span>{score.real.trades === 0 ? <span className="text-muted-foreground">no closed trades</span> : <>
          <span className={toneOf(score.real.pnl)}>{signed(score.real.pnl)}</span><span className="text-muted-foreground"> · {score.real.win_rate}% of {score.real.trades}</span></>}</span>
        <span className="text-muted-foreground">closed, since {day(book.run.started_at)}</span>
      </p>
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
                    <p className={cn("text-[11px]", c.verdict?.kind === "stop" || c.verdict?.kind === "target" ? "text-foreground/80" : "text-muted-foreground")}>{c.verdict?.auto && <span data-testid="paper-auto-tag" className="mr-1 rounded border border-amber-400/50 px-1 text-[10px] uppercase tracking-wide text-amber-200">auto</span>}{c.verdict?.text}{c.note ? ` · “${c.note}”` : ""}</p>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-muted-foreground">None yet.</p>}
          </div>
          {book.earlier.length > 0 && (
            <p className="text-[11px] text-muted-foreground">Earlier runs: {book.earlier.map(r => `run ${r.number} (${day(r.started_at)}–${day(r.ended_at)}, ${usd(r.starting_cash)} start) ${signed(r.realized)} closed over ${r.trades}`).join("; ")}.</p>
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
