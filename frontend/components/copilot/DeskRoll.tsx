"use client";

import { useEffect, useState } from "react";
import DeskChain, { type ChainPick } from "@/components/copilot/DeskChain";
import { CopyButton, Row } from "@/components/copilot/DeskTicket";
import { deskGet } from "@/lib/deskMinute";
import { optionLabel, rollCopyText, rollFigures, rollSentence, type NetType, type RollFrom } from "@/lib/rollTicket";
import { cn } from "@/lib/utils";

/**
 * The desk's roll ticket (docs/copilot-lab.md § Ticket, "Roll"): close a held long call or put and open another of the
 * same type, as one order to copy into Robinhood. Leg 1 is the contract held (sell to close, all of it by default, fewer
 * if he types fewer); leg 2 he picks in the Chain below (buy to open, the same count by default). Once picked it reads
 * ``GET /copilot/roll`` once (both legs' quotes from one paced chain pass; again only on "Read the quotes again") and
 * recomputes as he edits with ``lib/rollTicket.ts``. A stale or missing quote is grey with its time and the roll has no
 * net price; a wide one gives a rough one. Different counts on the two legs are two orders, in order. It copies; it reads
 * nothing else and has no button that sends anything.
 */

const STALE_S = 15 * 60; // the server's QUOTE_STALE_S
type Quote = { state: "ok" | "stale" | "missing"; reason?: string; as_of?: number | null; simulated?: boolean; bid?: number; ask?: number; mid?: number; spread_pct?: number | null };
type Leg = { role: "close" | "open"; strike: number; expiry: string; label: string; quote: Quote; wide: boolean };
type Roll = {
  state: "ok"; symbol: string; kind: "call" | "put"; simulated: boolean; held: number; multiplier: number | null; legs: Leg[]; rough: string[];
  close_mid: number | null; open_mid: number | null; net_mid: number | null; net_mid_type: NetType | null;
  net_natural: number | null; net_natural_type: NetType | null;
  underlying: { state: "ok" | "stale" | "missing"; last?: number; as_of?: number | null; reason?: string };
};

const clock = (epoch: number | null | undefined) => epoch ? new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET" : "an unknown time";
const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signedUsd = (n: number) => `${n < 0 ? "−" : "+"}${usd(Math.abs(n))}`;
const per = (n: number | null, type: NetType | null) => n === null || !type ? "—" : type === "even" ? "even (0.00)" : `${n.toFixed(2)} ${type}`;
const field = "w-24 rounded border bg-background px-2 py-1.5 text-base tabular-nums sm:text-sm";
const priceInput = (v: string) => v.replace(/[^\d.]/g, "").replace(/^(\d{0,6}(?:\.\d{0,2})?).*$/, "$1");
const countInput = (v: string) => v.replace(/[^\d]/g, "").slice(0, 4);
const noop = () => undefined;

export default function DeskRoll({ from, onClose, onPlaced }: { from: RollFrom; onClose(): void; onPlaced(symbol: string): void }) {
  const [to, setTo] = useState<ChainPick | null>(null);
  const [roll, setRoll] = useState<Roll | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [closeQty, setCloseQty] = useState(String(from.held));
  const [openQty, setOpenQty] = useState<string | null>(null); // null: follows the close count
  const [limit, setLimit] = useState("");
  const [limitType, setLimitType] = useState<"debit" | "credit">("debit");
  // The limits as the quotes set them (net, close, open), so an ageing quote can take back any he has not changed.
  const [seeded, setSeeded] = useState({ net: "", close: "", open: "" });
  const [closeLimit, setCloseLimit] = useState("");
  const [openLimit, setOpenLimit] = useState("");
  const [nowS, setNowS] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = setInterval(() => setNowS(Date.now() / 1000), 30_000); return () => clearInterval(timer); }, []);

  useEffect(() => {
    if (!to) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ symbol: from.symbol, option_type: from.side, strike: String(from.strike), expiration: from.expiry,
      held: String(from.held), new_strike: String(to.strike), new_expiration: to.expiry, ...(from.cost ? { cost: String(from.cost) } : {}) });
    setRoll(null); setError(null); // eslint-disable-line react-hooks/set-state-in-effect -- a new pick reads anew
    deskGet(`/copilot/roll?${query}`, controller.signal).then(async response => {
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `The roll could not be priced (${response.status}).`);
      const found = body as Roll;
      setRoll(found);
      const mid = found.net_mid !== null && found.net_mid_type ? found.net_mid : null;
      const seed = { net: mid !== null ? mid.toFixed(2) : "", close: found.close_mid !== null ? found.close_mid.toFixed(2) : "",
        open: found.open_mid !== null ? found.open_mid.toFixed(2) : "" };
      setSeeded(seed); setLimit(seed.net); setCloseLimit(seed.close); setOpenLimit(seed.open);
      setLimitType(found.net_mid_type === "credit" ? "credit" : "debit");
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "The roll could not be priced."); });
    return () => controller.abort();
  }, [from, to, reload]);

  const quotedAt = roll ? Math.min(...roll.legs.map(l => l.quote.state === "ok" && !l.quote.simulated && l.quote.as_of != null ? l.quote.as_of : Infinity)) : Infinity;
  const ageing = Number.isFinite(quotedAt) && nowS - quotedAt > STALE_S;
  useEffect(() => { // the quote aged on the clock: take back the prices it filled in, unless he changed them
    if (!ageing || !(seeded.net || seeded.close || seeded.open)) return;
    const take = (was: string, seed: string) => (seed && was === seed ? "" : was);
    setLimit(was => take(was, seeded.net)); setCloseLimit(was => take(was, seeded.close)); setOpenLimit(was => take(was, seeded.open)); // eslint-disable-line react-hooks/set-state-in-effect -- the quote aged on the clock
    setSeeded({ net: "", close: "", open: "" });
  }, [ageing, seeded]);

  const held = optionLabel(from.symbol, from.side, from.strike, from.expiry);
  const closeN = /^\d+$/.test(closeQty) && Number(closeQty) > 0 && Number(closeQty) <= from.held ? Number(closeQty) : null;
  const openText = openQty ?? closeQty;
  const openN = /^\d+$/.test(openText) && Number(openText) > 0 ? Number(openText) : null;
  const over = /^\d+$/.test(closeQty) && Number(closeQty) > from.held;
  const twoOrders = closeN !== null && openN !== null && closeN !== openN;

  const head = (
    <div className="space-y-1">
      <p className="text-sm"><span className="font-semibold">{from.symbol}</span><span className="text-muted-foreground"> · Roll your {from.held} {held}</span></p>
      <p className="text-xs text-muted-foreground">Closes the contract you hold and opens another, as one order you copy into Robinhood. It copies; it never sends.</p>
    </div>
  );
  const foot = (
    <div className="flex flex-wrap gap-2 border-t pt-3">
      {roll && to && <button type="button" onClick={() => onPlaced(from.symbol)} className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary sm:min-h-8">I placed it</button>}
      <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Not now</button>
    </div>
  );
  const legOne = (quote: React.ReactNode) => (
    <>
      {from.account && <Row name="Account"><span>{from.account}</span></Row>}
      <Row name="Leg 1: Sell to close" copy={<CopyButton text={`Sell to close ${held}`} label="leg 1" />}>
        <span className="font-mono tabular-nums">{held}</span>
        {quote}
      </Row>
      <Row name="Contracts closed" copy={<CopyButton text={closeN ? String(closeN) : ""} label="contracts closed" disabled={!closeN} />}>
        <input aria-label="Contracts to close" inputMode="numeric" value={closeQty} onChange={e => setCloseQty(countInput(e.target.value))} className={field} />
        <span className={cn("block text-xs", over ? "text-amber-300" : "text-muted-foreground")}>
          {over ? `You hold ${from.held}: a roll closes at most that many.` : `You hold ${from.held}${closeN && closeN < from.held ? `; you keep ${from.held - closeN}` : ""}.`}
        </span>
      </Row>
    </>
  );

  // Leg 2 not picked yet (or being changed): the Chain to pick it, on the held contract's side and expiry.
  if (!to) {
    return (
      <div data-testid="desk-roll" className="space-y-3">
        {head}
        <div className="rounded-lg border bg-card px-3 py-1.5">
          {legOne(null)}
          <Row name="Leg 2: Buy to open"><span className="text-sm text-muted-foreground">Pick the {from.side} to roll to in the chain below: a later expiry, another strike, or both.</span></Row>
        </div>
        <div className="rounded-lg border p-2">
          <DeskChain symbol={from.symbol} plans={null} onCheck={noop} onPlan={noop} onTicket={noop}
            roll={{ side: from.side, strike: from.strike, expiry: from.expiry, onPick: setTo }} />
        </div>
        {foot}
      </div>
    );
  }

  const target = optionLabel(from.symbol, from.side, to.strike, to.expiry);
  const legTwo = (quote: React.ReactNode) => (
    <>
      <Row name="Leg 2: Buy to open" copy={<CopyButton text={`Buy to open ${target}`} label="leg 2" />}>
        <span className="font-mono tabular-nums">{target}</span>
        {quote}
        <button type="button" onClick={() => setTo(null)} className="mt-0.5 block text-xs text-foreground underline underline-offset-2">Pick another</button>
      </Row>
      <Row name="Contracts opened" copy={<CopyButton text={openN ? String(openN) : ""} label="contracts opened" disabled={!openN} />}>
        <input aria-label="Contracts to open" inputMode="numeric" value={openText} onChange={e => setOpenQty(countInput(e.target.value))} className={field} />
        <span className="block text-xs text-muted-foreground">{openQty === null ? "The same as you close." : "Your own count."}</span>
      </Row>
    </>
  );
  if (error || !roll) {
    return (
      <div data-testid="desk-roll" className="space-y-3">
        {head}
        <div className="rounded-lg border bg-card px-3 py-1.5">{legOne(null)}{legTwo(null)}</div>
        {error ? <p role="alert" className="text-sm">{error}</p> : <p className="text-sm text-muted-foreground">Reading both contracts&apos; quotes…</p>}
        {foot}
      </div>
    );
  }

  const aged = (q: Quote) => q.state === "ok" && !q.simulated && q.as_of != null && nowS - q.as_of > STALE_S;
  const ok = (q: Quote) => q.state === "ok" && !aged(q);
  const [closeLeg, openLeg] = roll.legs;
  const fresh = ok(closeLeg.quote) && ok(openLeg.quote);
  const rough = [...roll.rough, ...roll.legs.filter(l => aged(l.quote)).map(l => `${l.role === "close" ? "the contract you hold" : "the new contract"}'s quote is now older than 15 minutes`)];
  const quoteLine = (l: Leg) => {
    const q = l.quote;
    return (
      <span data-testid="roll-leg-quote" className={cn("block text-xs tabular-nums", ok(q) ? "text-muted-foreground" : "text-muted-foreground/70")}>
        {ok(q) ? <>Bid {q.bid!.toFixed(2)} · Ask {q.ask!.toFixed(2)} · Mid {q.mid!.toFixed(2)} · as of {clock(q.as_of)}{l.wide && <span className="text-amber-300"> · wide ({q.spread_pct}% of the mid)</span>}</>
          : aged(q) ? `Quote stale (last ${clock(q.as_of)}): now older than 15 minutes.`
          : q.state === "stale" ? `Quote stale (last ${clock(q.as_of)}): ${q.reason}` : `No quote: ${q.reason ?? "the chain could not be read."}`}
      </span>
    );
  };

  const limitN = limit.trim() && Number(limit) >= 0 ? Number(limit) : null;
  const signedNet = limitN === null ? null : limitType === "credit" ? -limitN : limitN;
  const closeLimitN = closeLimit.trim() && Number(closeLimit) > 0 ? Number(closeLimit) : null;
  const openLimitN = openLimit.trim() && Number(openLimit) > 0 ? Number(openLimit) : null;
  const spot = roll.underlying.state === "ok" ? roll.underlying.last ?? null : null;
  // The new contract's own break-even is at its mid; the dollars are at the limit he types (one order's net, or two).
  const computed = rollFigures(from.side, from.strike, to.strike, from.expiry, to.expiry, {
    closeQty: closeN, openQty: openN, multiplier: roll.multiplier, spot, costPerContract: from.cost,
    closePrice: twoOrders ? closeLimitN : fresh ? roll.close_mid : null, openPrice: twoOrders ? openLimitN : fresh ? roll.open_mid : null,
    net: twoOrders ? null : signedNet,
  });
  // The dollars that change hands follow a limit he has (one net, or both orders' prices), never the mids alone.
  const priced = twoOrders ? closeLimitN !== null && openLimitN !== null : signedNet !== null;
  const f = priced ? computed : { ...computed, netUsd: null, inTradeAfter: null, atRiskAfter: null, tradeBreakeven: null, ahead: false };
  const be = fresh && roll.open_mid !== null ? rollFigures(from.side, from.strike, to.strike, from.expiry, to.expiry,
    { closeQty: null, openQty: null, multiplier: null, closePrice: null, openPrice: roll.open_mid, spot }) : null;
  const sentence = fresh ? rollSentence(from.symbol, from.side, from.strike, from.expiry, to.strike, to.expiry, { ...f, breakeven: be?.breakeven ?? null }) : null;
  const all = closeN && openN ? rollCopyText({ symbol: from.symbol, side: from.side, oldStrike: from.strike, oldExpiry: from.expiry, newStrike: to.strike,
    newExpiry: to.expiry, closeQty: closeN, openQty: openN, net: limitN, netType: limitN === null ? null : limitN === 0 ? "even" : limitType,
    closeLimit: closeLimitN, openLimit: openLimitN }) : "";
  const roughTag = rough.length > 0 ? <span className="ml-1 rounded border border-amber-300/50 px-1 text-[10px] uppercase tracking-wide text-amber-300">rough</span> : null;
  const m = roll.multiplier;
  const legDollars = (price: number | null, n: number | null) => price !== null && n && m ? usd(price * m * n) : "—";

  return (
    <div data-testid="desk-roll" data-net={fresh ? roll.net_mid_type ?? undefined : undefined} className="space-y-3">
      {head}
      {roll.simulated && <p className="text-xs text-amber-300">Simulated quotes (sandbox fixture).</p>}
      <div className="rounded-lg border bg-card px-3 py-1.5">
        {legOne(quoteLine(closeLeg))}
        {legTwo(quoteLine(openLeg))}
        <Row name="Closing brings in">
          <span data-testid="roll-proceeds" className="tabular-nums">{fresh ? <>{legDollars(roll.close_mid, closeN)} at the mid · {legDollars(closeLeg.quote.bid ?? null, closeN)} at the bid</> : <span className="text-muted-foreground">—</span>}</span>
        </Row>
        <Row name="The new one costs">
          <span data-testid="roll-cost" className="tabular-nums">{fresh ? <>{legDollars(roll.open_mid, openN)} at the mid · {legDollars(openLeg.quote.ask ?? null, openN)} at the ask</> : <span className="text-muted-foreground">—</span>}</span>
        </Row>
        {!twoOrders && (
          <Row name="Net price">
            <span data-testid="roll-net" className="tabular-nums">
              {fresh && roll.net_mid !== null ? <>{per(roll.net_mid, roll.net_mid_type)} at the mid · {per(roll.net_natural, roll.net_natural_type)} at the natural price</>
                : <span className="text-muted-foreground">No net price: {rough[0] ?? "a leg has no fresh quote"}.</span>}
              {roughTag}
            </span>
            {rough.length > 0 && <span data-testid="roll-rough" className="block text-xs text-amber-300">Rough: {rough.join("; ")}.</span>}
            {fresh && roll.net_mid !== null && <span className="block text-xs text-muted-foreground">Natural: sell yours at the bid and buy the new one at the ask, the worst fill.</span>}
          </Row>
        )}
        {twoOrders ? (
          <Row name="Two orders">
            <span data-testid="roll-two-orders" className="block text-xs text-amber-300">Robinhood&apos;s roll takes one count for both legs. With {closeN} closed and {openN} opened, place two orders, in this order: sell to close first, then buy to open.</span>
            <span className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted-foreground">1. Sell limit</span>
              <input aria-label="Sell to close limit price per share" inputMode="decimal" value={closeLimit} onChange={e => setCloseLimit(priceInput(e.target.value))} placeholder="set it" className={field} />
              <span className="text-muted-foreground">2. Buy limit</span>
              <input aria-label="Buy to open limit price per share" inputMode="decimal" value={openLimit} onChange={e => setOpenLimit(priceInput(e.target.value))} placeholder="set it" className={field} />
            </span>
            {rough.length > 0 && <span data-testid="roll-rough" className="block text-xs text-amber-300">Rough: {rough.join("; ")}.</span>}
          </Row>
        ) : (
          <Row name="Limit (net)" copy={<CopyButton text={limitN !== null ? `${limitN.toFixed(2)} ${limitN === 0 ? "even" : limitType}` : ""} label="limit price" disabled={limitN === null} />}>
            <span className="flex flex-wrap items-center gap-2">
              <input aria-label={`Net limit price per share, ${limitType}`} inputMode="decimal" value={limit} onChange={e => setLimit(priceInput(e.target.value))} placeholder="set it" className={field} />
              <span role="radiogroup" aria-label="Debit or credit" className="inline-flex overflow-hidden rounded-md border">
                {(["debit", "credit"] as const).map(t => (
                  <button key={t} type="button" role="radio" aria-checked={limitType === t} onClick={() => setLimitType(t)}
                    className={cn("min-h-11 px-3 text-xs sm:min-h-8", limitType === t ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
                    {t === "debit" ? "Debit (you pay)" : "Credit (you take in)"}
                  </button>
                ))}
              </span>
            </span>
            <span className="block text-xs text-muted-foreground">{fresh && roll.net_mid !== null ? `The net mid as of ${clock(Math.min(closeLeg.quote.as_of ?? Infinity, openLeg.quote.as_of ?? Infinity))}${rough.length ? " (rough)" : ""}` : "No fresh net price: set it yourself."}</span>
          </Row>
        )}
        <Row name="The roll">
          <span data-testid="roll-net-usd" className="tabular-nums">
            {f.netUsd === null ? "—" : f.netUsd > 0 ? `You pay ${usd(f.netUsd)}` : f.netUsd < 0 ? `You take in ${usd(-f.netUsd)}` : "Even money"}
            {f.netUsd !== null && <span className="text-muted-foreground"> {twoOrders ? "across the two orders" : "at this limit"}</span>}
          </span>
        </Row>
        <Row name="New break-even">
          {be?.breakeven != null ? (
            <span data-testid="roll-breakeven" className="tabular-nums">{from.symbol} {be.breakeven.toFixed(2)} at expiry
              <span className="text-muted-foreground"> · the new contract at its mid {roll.open_mid!.toFixed(2)}{be.movePct !== null && spot !== null ? ` · needs ${be.movePct >= 0 ? "+" : "−"}${Math.abs(be.movePct).toFixed(1)}% from ${spot}` : ""}</span>
            </span>
          ) : "—"}
          {f.ahead ? <span data-testid="roll-trade-breakeven" className="block text-xs text-emerald-300">Counting the whole trade you are {usd(-f.inTradeAfter!)} ahead: you have taken out more than you put in.</span>
            : f.tradeBreakeven !== null ? <span data-testid="roll-trade-breakeven" className="block text-xs text-muted-foreground">Counting everything this trade has cost you: {from.symbol} {f.tradeBreakeven.toFixed(2)} at expiry to get it all back.</span> : null}
        </Row>
        <Row name="Time">
          <span data-testid="roll-days" className="tabular-nums">{f.daysAdded > 0 ? `${f.daysAdded} more days` : f.daysAdded === 0 ? "Same expiry" : `${-f.daysAdded} fewer days`}</span>
        </Row>
        <Row name="Money in the trade">
          <span data-testid="roll-basis" className="tabular-nums">
            {f.basisBefore === null ? <span className="text-muted-foreground">The book has no cost for this contract, so this cannot be counted.</span>
              : f.inTradeAfter === null ? <>{usd(f.basisBefore)} paid for these {closeN}</>
              : <>{usd(f.basisBefore)} paid for these {closeN} → {f.inTradeAfter >= 0 ? usd(f.inTradeAfter) : `${usd(-f.inTradeAfter)} taken out`} after the roll <span className="text-muted-foreground">({signedUsd(f.netUsd!)})</span></>}
          </span>
        </Row>
        <Row name="At risk from here">
          <span data-testid="roll-risk" className="tabular-nums">
            {f.atRiskBefore !== null && f.atRiskAfter !== null
              ? <>{usd(f.atRiskBefore)} (what yours are worth now) → {usd(f.atRiskAfter)} (what the new ones cost) <span className="text-muted-foreground">· a long option can lose all of it</span></>
              : "—"}
          </span>
        </Row>
      </div>
      {sentence && <p data-testid="roll-sentence" className="text-sm">{sentence}{rough.length > 0 && <span className="text-amber-300"> Rough: the quotes are not clean.</span>}</p>}
      {!fresh && <button type="button" onClick={() => setReload(r => r + 1)} className="text-xs text-foreground underline underline-offset-2">Read the quotes again</button>}
      <p data-testid="roll-plan" className="text-xs text-muted-foreground">Your plan stays with the contract you hold. After the roll fills, plan the new contract: its stop, target and time stop.</p>
      <div className="space-y-2">
        <CopyButton text={all} label={twoOrders ? "Copy both orders for Robinhood" : "Copy all for Robinhood"} wide disabled={!all} />
        <p className="text-xs text-muted-foreground">
          {twoOrders ? `You place them yourself in Robinhood: first sell ${closeN} of your ${held}, then buy ${openN} of the ${target}. Nothing is sent from here.`
            : `You place it yourself in Robinhood: open your ${from.symbol} ${from.side} position, Roll, pick ${target}, then the limit as a ${limitN === 0 ? "net of 0.00" : limitType} and the quantity. Nothing is sent from here.`}
        </p>
      </div>
      {foot}
    </div>
  );
}
