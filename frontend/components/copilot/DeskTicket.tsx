"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import PlayCheck, { type PlayCheckData } from "@/components/copilot/PlayCheck";
import SetupRecordLines, { premiumLine } from "@/components/copilot/SetupRecordLines";
import { deskGet, everyDeskMinute } from "@/lib/deskMinute";
import { getSymbolLoop, type SetupRecord } from "@/lib/copilot";
import type { AnyClosingTicket, ClosingTicket, CloseNowTicket } from "@/lib/closingTicket";
import { spreadCopyText, spreadFigures, spreadSentence } from "@/lib/spreadTicket";
import { cn } from "@/lib/utils";

/**
 * The desk's Ticket tab (docs/copilot-lab.md § Ticket), copy-to-Robinhood mode: one saved plan's order fields, each
 * with its own Copy, and Copy all in the order Robinhood's option order screen asks for them. It copies and never sends:
 * this file reads two GET routes and the clipboard, and the MCP account's Send button is drawn disabled with no handler.
 * A ticket opens only from a saved plan (``openTicket`` from a confirmed plan card, a plan thread's header, a book row,
 * or this tab's list of armed plans not yet entered). A closing ticket (``openClosingTicket``, the held option's "Close
 * at target" / "Close at stop") is filled in the browser from the book row (``lib/closingTicket.ts``): a sell to close
 * of the contracts held with an estimated limit; it reads nothing and has no Send button at all. A two-leg vertical
 * (the Chain tab's Make it a spread, or a plan whose words name one) shows both legs, the net debit or credit at the
 * mid and at the natural price, and copies legs then the net limit (``lib/spreadTicket.ts``); it has no Send button.
 */

export const TICKET_EVENT = "tradejournal:open-ticket";
const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const STALE_S = 15 * 60;  // the server's QUOTE_STALE_S

/** A contract he picked for a ticket (the Chain tab's Put on ticket): it replaces the contract the plan names. With
 *  ``short`` it is the long leg of a vertical spread that sells ``short`` (``kind``: its type) in the same expiry. */
export type TicketPick = { expiry: string; strike: number; short?: number; kind?: "call" | "put" };

/** Opens a saved plan's ticket: on the desk the Ticket tab takes it; anywhere else the desk opens on it. */
export function openTicket(investigationId: string, pick?: TicketPick) {
  const handled = !window.dispatchEvent(new CustomEvent(TICKET_EVENT, { detail: { investigationId, pick }, cancelable: true }));
  if (!handled) window.location.assign(`/copilot-lab?ticket=${encodeURIComponent(investigationId)}`);
}

/** Opens a closing ticket on the desk's Ticket tab. Its buttons live only on the desk, which handles the event. */
export function openClosingTicket(close: AnyClosingTicket) {
  window.dispatchEvent(new CustomEvent(TICKET_EVENT, { detail: { close }, cancelable: true }));
}

export type TicketPlan = {
  investigation_id: string; symbol: string; direction: "long" | "short" | null; instrument: string | null; thesis: string | null;
  option_type?: "call" | "put" | null; // a long call or put plan; anything else has no option ticket
  confirmed_at: number; entry: number | null; invalidation: number | null;
};
type Account = { id: string; label: string; last4: string | null; kind: "roth" | "mcp" | "other" };
type Quote = { state: "ok" | "stale" | "missing"; reason?: string; as_of?: number | null; simulated?: boolean; bid?: number; ask?: number;
  mid?: number; spread?: number; spread_pct?: number | null; multiplier?: number | null };
type Candidate = { expiry: string; strike: number; type: "call" | "put"; days: number; bid?: number; ask?: number; mid?: number;
  ask_contract?: number | null; spread_pct?: number; breakeven_move_pct?: number; expected_move_pct?: number | null; move_needed_vs_expected?: number | null };
type SpreadLeg = { role: "long" | "short"; action: "buy" | "sell"; strike: number; label: string; quote: Quote; wide: boolean };
type Spread = {
  kind: "call" | "put"; expiry: string; type: "debit" | "credit"; width: number; long: number; short: number; label: string;
  source: "plan" | "picked"; multiplier: number | null; legs: SpreadLeg[]; net_mid: number | null; net_natural: number | null;
  rough: string[]; bullish: boolean; against_plan: string | null;
};
type Ticket = {
  state: "ok" | "not_option" | "no_quotes"; reason?: string; investigation_id: string; symbol: string; direction: string | null;
  thesis: string | null; option_type: "call" | "put" | null; entry: number | null; invalidation: number | null; time_stop: string | null;
  target?: number | null; // the plan's profit target (the stock's price), when it has one
  plan_contract_words: string | null; size: { contracts: number | null; risk_usd: number | null; text: string | null };
  accounts: Account[]; account: string | null; simulated: boolean;
  contract: { strike: number; expiry: string; type: "call" | "put"; label: string; source: "plan" | "picked"; multiplier: number | null } | null;
  candidates: { state: "ok" | "stale" | "missing"; reason?: string; as_of?: number | null; rows: Candidate[] } | null;
  quote: Quote | null; underlying: { state: "ok" | "stale" | "missing"; last?: number; as_of?: number | null; reason?: string } | null;
  expected_move_pct: number | null; limit: number | null; contracts: number | null;
  spread?: Spread | null; // a two-leg vertical: then ``contract`` and ``quote`` are null
  check?: PlayCheckData | null; // the Play check: plan parts, habits before the entry, holding overnight
};

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await deskGet(path, signal);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as T;
}

/** The saved plans a ticket can open (armed, not yet entered), newest first; null until read. */
export function useTicketPlans(on: boolean): { plans: TicketPlan[] | null; failed: boolean } {
  const [plans, setPlans] = useState<TicketPlan[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    const controller = new AbortController();
    const load = () => read<{ plans: TicketPlan[] }>("/copilot/tickets", controller.signal)
      .then(body => { setPlans(body.plans); setFailed(false); })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    load();
    const stop = everyDeskMinute(load); // the shared minute: one request with the desk's other reads, none while hidden
    return () => { controller.abort(); stop(); };
  }, [on]);
  return { plans, failed };
}

const clock = (epoch: number | null | undefined) => epoch ? new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET" : "an unknown time";
const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const signedPct = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}%`;
const shortDate = (iso: string) => { const [y, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}/${y.slice(2)}`; };
const kindWord = (kind: string) => kind === "call" ? "Call" : "Put";

/** Cost, the most a long option can lose (its premium) and break-even, as the server's ``desk_ticket.figures``. */
export function ticketFigures(kind: "call" | "put", strike: number, limit: number | null, contracts: number | null, multiplier: number | null,
  spot: number | null, expectedPct: number | null) {
  if (limit === null || !(limit > 0)) return { cost: null, breakeven: null, movePct: null, vsExpected: null };
  const cost = contracts && contracts > 0 && multiplier ? Math.round(limit * multiplier * contracts * 100) / 100 : null;
  const breakeven = kind === "call" ? strike + limit : strike - limit;
  const movePct = spot && spot > 0 ? (breakeven - spot) / spot * 100 : null;
  const vsExpected = movePct !== null && expectedPct && expectedPct > 0 ? Math.abs(movePct) / expectedPct : null;
  return { cost, breakeven, movePct, vsExpected };
}

/** Whether ``SetupRecordLines`` has a line to show for this side. */
function hasRecord(setup: SetupRecord | null, side: "call" | "put") {
  if (!setup) return false;
  const mine = side === "call" ? setup.calls : setup.puts;
  return !!((mine.gap?.record && setup.gap_pct !== null) || (mine.trend?.record && setup.vs_sma_pct !== null));
}

/** What Copy all puts on the clipboard: Robinhood's option order screen, top to bottom. */
export function copyAllText(t: { symbol: string; type: "call" | "put"; expiry: string; strike: number; limit: string; contracts: string; action?: "Buy" | "Sell" }) {
  return [t.symbol, `${t.action ?? "Buy"} · ${kindWord(t.type)}`, `Expiration ${shortDate(t.expiry)}`, `Strike $${t.strike}`,
    `Limit price ${t.limit || "(set it)"}`, `Contracts ${t.contracts || "(set it)"}`].join("\n");
}

/** The clipboard, else the page's own copy command (a page not served over HTTPS has no clipboard API). */
async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch { /* fall back below */ }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("copy refused");
}

function CopyButton({ text, label, disabled = false, wide = false }: { text: string; label: string; disabled?: boolean; wide?: boolean }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = () => copyText(text).then(() => setState("copied"), () => setState("failed"))
    .finally(() => setTimeout(() => setState("idle"), 1800));
  return (
    <button type="button" onClick={copy} disabled={disabled} aria-label={wide ? label : `Copy ${label}`}
      className={cn("inline-flex min-h-11 items-center justify-center gap-1.5 rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8",
        wide ? "border-foreground/70 text-foreground" : "text-muted-foreground")}>
      {state === "copied" ? <Check size={13} aria-hidden className="text-emerald-400" /> : <Copy size={13} aria-hidden />}
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : wide ? label : "Copy"}
    </button>
  );
}

function Row({ name, children, copy }: { name: string; children: React.ReactNode; copy?: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-2 border-t py-1.5 first:border-t-0 sm:grid-cols-[9rem_minmax(0,1fr)_auto]">
      <span className="text-xs text-muted-foreground">{name}</span>
      <div className="min-w-0 text-sm">{children}</div>
      <div>{copy}</div>
    </div>
  );
}

/** The Ticket tab: the open ticket, else the list of saved plans a ticket can open, else what to do with none. */
export default function DeskTicket({ plans, failed, open, pick = null, close = null, onOpen, onClose, onPlaced, onPlan }: {
  plans: TicketPlan[] | null; failed: boolean; open: string | null; pick?: TicketPick | null; onOpen(investigationId: string): void; onClose(): void;
  /** A closing ticket from a held option's plan or a copilot close card; it takes the tab over an open plan ticket. */
  close?: AnyClosingTicket | null;
  onPlaced(symbol: string): void; onPlan(): void;
}) {
  // Each click is a fresh ticket (a new mark or stock price re-fills the limit), keyed on what it was priced from.
  if (close?.at === "now") return <CloseNowView key={`${close.symbol}|${close.expiry}|${close.strike}|${close.shortStrike}|${close.contracts}|${close.mark}|${close.shortMark}`} ticket={close} onClose={onClose} onPlaced={onPlaced} />;
  if (close) return <ClosingView key={`${close.symbol}|${close.expiry}|${close.strike}|${close.at}|${close.stock}|${close.mark}`} ticket={close} onClose={onClose} onPlaced={onPlaced} />;
  if (open) return <TicketView key={`${open}|${pick?.expiry ?? ""}|${pick?.strike ?? ""}|${pick?.short ?? ""}|${pick?.kind ?? ""}`} investigationId={open} initialPick={pick} onClose={onClose} onPlaced={onPlaced} />;
  return (
    <div data-testid="desk-ticket" className="space-y-3">
      <p className="text-xs text-muted-foreground">A ticket opens only from a saved plan. It fills in what you type into Robinhood; nothing is sent from here.</p>
      {failed && !plans ? <p className="text-sm text-muted-foreground">Your saved plans could not be read. Try again in a moment.</p>
        : !plans ? <p className="text-sm text-muted-foreground">Reading your saved plans…</p>
        : plans.length === 0 ? (
          <div className="space-y-2 rounded-lg border bg-card p-3">
            <p className="text-sm">No saved plan is armed and waiting for an entry.</p>
            <button type="button" onClick={onPlan} className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-semibold text-foreground hover:bg-secondary sm:min-h-8">Plan a trade</button>
          </div>
        ) : (
          <ul aria-label="Saved plans" className="divide-y rounded-lg border bg-card">
            {plans.map(p => (
              <li key={p.investigation_id}>
                <button type="button" onClick={() => onOpen(p.investigation_id)} className="flex min-h-11 w-full items-baseline gap-2 px-3 py-2 text-left hover:bg-secondary">
                  <span className="text-sm font-semibold">{p.symbol}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">{p.instrument ?? p.direction ?? ""}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{p.thesis ?? ""}</span>
                  <span className="whitespace-nowrap text-xs text-muted-foreground">Saved {new Date(p.confirmed_at * 1000).toLocaleDateString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" })}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}

function TicketView({ investigationId, initialPick, onClose, onPlaced }: {
  investigationId: string; initialPick: TicketPick | null; onClose(): void; onPlaced(symbol: string): void;
}) {
  const [pick, setPick] = useState<TicketPick | null>(initialPick);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [limit, setLimit] = useState("");
  const [qty, setQty] = useState("");
  const [setup, setSetup] = useState<SetupRecord | null>(null);
  const [reload, setReload] = useState(0);
  const [seeded, setSeeded] = useState("");  // the limit as the quote set it, so an ageing quote can take it back
  const seededQty = useRef("");  // the count the plan's size gave, re-seeded on a re-read until he edits it
  // The server judges the quote's age once; an open ticket keeps judging it on this clock.
  const [nowS, setNowS] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = setInterval(() => setNowS(Date.now() / 1000), 30_000); return () => clearInterval(timer); }, []);

  useEffect(() => {
    const controller = new AbortController();
    const query = pick ? `?expiration=${pick.expiry}&strike=${pick.strike}${pick.short != null ? `&short_strike=${pick.short}&option_type=${pick.kind ?? ""}` : ""}` : "";
    read<Ticket>(`/copilot/tickets/${encodeURIComponent(investigationId)}${query}`, controller.signal).then(found => {
      setTicket(found); setError(null);
      setAccount(was => was ?? found.account);
      const mid = found.limit !== null ? found.limit.toFixed(2) : "";
      setLimit(mid); setSeeded(mid);
      const count = found.contracts ? String(found.contracts) : "";
      setQty(was => (!was || was === seededQty.current ? count : was)); seededQty.current = count;
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "The ticket could not be read."); });
    return () => controller.abort();
  }, [investigationId, pick, reload]);

  const ageing = quotedAt(ticket) !== null && nowS - quotedAt(ticket)! > STALE_S;
  useEffect(() => { if (ageing && seeded) { setLimit(was => (was === seeded ? "" : was)); setSeeded(""); } }, [ageing, seeded]); // eslint-disable-line react-hooks/set-state-in-effect -- the quote aged on the clock

  const symbol = ticket?.symbol;
  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    getSymbolLoop(symbol, controller.signal, { setup: true })
      .then(loop => { if (loop.setup?.state === "ok") setSetup(loop.setup); }).catch(() => undefined);
    return () => controller.abort();
  }, [symbol]);

  const foot = (placed: boolean) => (
    <div className="flex flex-wrap gap-2 border-t pt-3">
      {placed && <button type="button" onClick={() => onPlaced(symbol!)} className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary sm:min-h-8">I placed it</button>}
      <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Not now</button>
    </div>
  );
  if (error) return <div data-testid="desk-ticket" className="space-y-3"><p role="alert" className="text-sm">{error}</p>{foot(false)}</div>;
  if (!ticket) return <p data-testid="desk-ticket" className="text-sm text-muted-foreground">Reading the ticket…</p>;

  const head = (
    <div className="space-y-1">
      <p className="text-sm"><span className="font-semibold">{ticket.symbol}</span>{ticket.thesis && <span className="text-muted-foreground"> · {ticket.thesis}</span>}</p>
      <p className="text-xs text-muted-foreground">
        A ticket for your saved plan{ticket.entry !== null && `: entry ${ticket.entry}`}{ticket.invalidation !== null && `, out at ${ticket.invalidation}`}{ticket.time_stop && `, ${ticket.time_stop}`}. It copies; it never sends.
        {ticket.simulated && <span className="ml-1 text-amber-300">Simulated quotes (sandbox fixture).</span>}
      </p>
    </div>
  );
  if (ticket.state !== "ok") return <div data-testid="desk-ticket" className="space-y-3">{head}<p className="text-sm">{ticket.reason}</p>{foot(false)}</div>;

  const chosen = ticket.accounts.find(a => a.id === account) ?? ticket.accounts[0];
  const switcher = (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground">Account</span>
      <span role="radiogroup" aria-label="Account" className="inline-flex overflow-hidden rounded-md border">
        {ticket.accounts.map(a => (
          <button key={a.id} type="button" role="radio" aria-checked={a.id === chosen?.id} onClick={() => setAccount(a.id)}
            className={cn("min-h-11 px-3 text-xs sm:min-h-8", a.id === chosen?.id ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {a.label}{a.last4 ? ` ••${a.last4}` : ""}
          </button>
        ))}
      </span>
    </div>
  );

  if (ticket.spread) {
    return <SpreadView ticket={ticket} spread={ticket.spread} head={head} switcher={switcher} foot={foot(true)} limit={limit} setLimit={setLimit}
      qty={qty} setQty={setQty} nowS={nowS} onReread={() => setReload(r => r + 1)} />;
  }

  // No contract named: two or three real contracts to choose from; nothing is chosen for him.
  if (!ticket.contract) {
    const c = ticket.candidates;
    return (
      <div data-testid="desk-ticket" className="space-y-3">
        {head}
        {ticket.check && <PlayCheck check={ticket.check} investigationId={ticket.investigation_id} symbol={ticket.symbol} contracts={null} paid={null} />}
        <div className="rounded-lg border bg-card p-3">
          <p className={LABEL}>Choose a contract</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {ticket.plan_contract_words ? `Your plan says "${ticket.plan_contract_words}", which does not name one contract. ` : "Your plan names no contract. "}
            These are {ticket.simulated ? "simulated" : "real"} {ticket.option_type}s from the chain{c?.as_of ? `, quoted as of ${clock(c.as_of)}` : ""}. None is picked for you.
          </p>
          {!c || c.state === "missing" ? <p className="mt-2 text-sm">{c?.reason ?? "No option candidates could be read."}</p> : (
            <ul className="mt-2 divide-y">
              {c.rows.map(r => (
                <li key={`${r.expiry}-${r.strike}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                  <span className="text-sm font-medium tabular-nums">${r.strike} {kindWord(r.type)} {shortDate(r.expiry)}</span>
                  {c.state === "stale" ? <span className="text-xs text-amber-300">Quote stale ({clock(c.as_of)}): no premium shown</span> : (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {r.ask_contract != null ? `${usd(r.ask_contract)} a contract at the ask` : "no premium"} · spread {r.spread_pct}% ·
                      {" "}break-even {r.breakeven_move_pct !== undefined ? signedPct(r.breakeven_move_pct) : "—"}
                      {r.expected_move_pct ? ` vs expected ±${r.expected_move_pct}%` : ""} · {r.days}d
                    </span>
                  )}
                  <button type="button" onClick={() => setPick({ expiry: r.expiry, strike: r.strike })}
                    className="ml-auto inline-flex min-h-11 items-center rounded-md border px-3 text-xs hover:bg-secondary sm:min-h-8">Use this</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {foot(false)}
      </div>
    );
  }

  const k = ticket.contract, q = ticket.quote;
  const limitN = limit.trim() && Number(limit) > 0 ? Number(limit) : null;
  const qtyN = /^\d+$/.test(qty.trim()) && Number(qty) > 0 ? Number(qty) : null;
  const spot = ticket.underlying?.state === "ok" ? ticket.underlying.last ?? null : null;
  const f = ticketFigures(k.type, k.strike, limitN, qtyN, k.multiplier, spot, ticket.expected_move_pct);
  const premium = premiumLine(setup, f.cost);
  const aged = q?.state === "ok" && !q.simulated && q.as_of != null && nowS - q.as_of > STALE_S;
  const fresh = q?.state === "ok" && !aged;
  const all = copyAllText({ symbol: ticket.symbol, type: k.type, expiry: k.expiry, strike: k.strike, limit: limitN !== null ? limitN.toFixed(2) : "", contracts: qtyN ? String(qtyN) : "" });
  const field = "w-24 rounded border bg-background px-2 py-1.5 text-base tabular-nums sm:text-sm";
  return (
    <div data-testid="desk-ticket" className="space-y-3">
      {head}
      {switcher}
      <div className="rounded-lg border bg-card px-3 py-1.5">
        <Row name="Contract" copy={<CopyButton text={k.label} label="contract" />}>
          <span className="font-mono tabular-nums">{k.label}</span>
          {k.source === "picked" && <span className="block text-xs text-muted-foreground">Your pick from the chain{ticket.plan_contract_words ? ` (your plan says: ${ticket.plan_contract_words})` : ""}</span>}
          {k.source === "plan" && ticket.plan_contract_words && <span className="block text-xs text-muted-foreground">Your plan says: {ticket.plan_contract_words}</span>}
        </Row>
        <Row name="Quantity" copy={<CopyButton text={qtyN ? String(qtyN) : ""} label="quantity" disabled={!qtyN} />}>
          <input aria-label="Quantity in contracts" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, "").slice(0, 4))} placeholder="set it" className={field} />
          <span className="block text-xs text-muted-foreground">{ticket.size.text ? `Plan's size: ${ticket.size.text}` : "Your plan gives no size."}</span>
        </Row>
        <Row name="Limit price" copy={<CopyButton text={limitN !== null ? limitN.toFixed(2) : ""} label="limit price" disabled={limitN === null} />}>
          <input aria-label="Limit price per share" inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value.replace(/[^\d.]/g, "").replace(/^(\d{0,6}(?:\.\d{0,2})?).*$/, "$1"))} placeholder="set it" className={field} />
          <span className="block text-xs text-muted-foreground">{fresh ? `The mid as of ${clock(q!.as_of)}` : "No fresh quote: set it yourself."}</span>
        </Row>
        <Row name="Cost"><span className="tabular-nums">{f.cost !== null ? usd(f.cost) : "—"}</span></Row>
        <Row name="Most you can lose"><span className="tabular-nums">{f.cost !== null ? `${usd(f.cost)} (the premium)` : "The premium you pay"}</span></Row>
        <Row name="Break-even">
          {f.breakeven !== null ? (
            <span className="tabular-nums">{ticket.symbol} {f.breakeven.toFixed(2)} at expiry
              {f.movePct !== null && <span className="text-muted-foreground"> · needs {signedPct(f.movePct)} from {spot}{ticket.underlying?.as_of ? ` (${clock(ticket.underlying.as_of)})` : ""}</span>}
              {ticket.expected_move_pct && <span className="text-muted-foreground"> · expected move ±{ticket.expected_move_pct}%</span>}
            </span>
          ) : "—"}
          {ticket.underlying && ticket.underlying.state !== "ok" && <span className="block text-xs text-amber-300">{ticket.underlying.reason}</span>}
        </Row>
        <Row name="Your record">
          <SetupRecordLines symbol={ticket.symbol} side={k.type} setup={setup} />
          {premium && <p className="text-xs text-muted-foreground">{premium}</p>}
          {!premium && !hasRecord(setup, k.type) && <span className="text-xs text-muted-foreground">No record for this setup in your journal yet.</span>}
        </Row>
        <Row name="Before you place it">
          {fresh ? (
            <span data-testid="ticket-quote" className="text-xs tabular-nums">Bid {q!.bid!.toFixed(2)} · Ask {q!.ask!.toFixed(2)} · Spread ${q!.spread!.toFixed(2)}{q!.spread_pct != null ? ` (${q!.spread_pct}% of the mid)` : ""} · as of {clock(q!.as_of)}</span>
          ) : (
            <span data-testid="ticket-quote" className="text-xs text-amber-300">
              {aged ? `Quote stale (last ${clock(q!.as_of)}): it is now older than 15 minutes.` : q?.state === "stale" ? `Quote stale (last ${clock(q.as_of)}): ${q.reason}` : `No quote: ${q?.reason ?? "the chain could not be read."}`}
              {" "}<button type="button" onClick={() => setReload(r => r + 1)} className="text-foreground underline underline-offset-2">Read the quote again</button>
            </span>
          )}
        </Row>
      </div>
      {ticket.check && <PlayCheck check={ticket.check} investigationId={ticket.investigation_id} symbol={ticket.symbol} contracts={qtyN} paid={f.cost} />}
      {chosen?.kind === "mcp" ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled aria-disabled="true" title="Sending is off" className="inline-flex min-h-11 cursor-not-allowed items-center rounded-md border px-3 text-xs opacity-45 sm:min-h-8">Send to Robinhood for your approval</button>
            <CopyButton text={all} label="Copy all for Robinhood" wide />
          </div>
          <p className="text-xs text-muted-foreground">Sending is off: Robinhood has not given your account the approvals setting, and the MCP account is empty. Copy the fields and place it yourself in Robinhood.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <CopyButton text={all} label="Copy all for Robinhood" wide />
          <p className="text-xs text-muted-foreground">You place it yourself in Robinhood: open {ticket.symbol}, Trade, Trade options, then enter each field. Nothing is sent from here.</p>
        </div>
      )}
      {foot(true)}
    </div>
  );
}

/** The oldest time among the ticket's fresh quotes (one contract's, or both legs' of a spread); only live ones age, so
 *  simulated quotes count only when ``simulated`` is asked for (to say their time, never to age them). */
function quotedAt(ticket: Ticket | null, simulated = false): number | null {
  if (!ticket) return null;
  const quotes = ticket.spread ? ticket.spread.legs.map(l => l.quote) : ticket.quote ? [ticket.quote] : [];
  const times = quotes.filter(q => q.state === "ok" && (simulated || !q.simulated) && q.as_of != null).map(q => q.as_of!);
  return times.length ? Math.min(...times) : null;
}

const ROLE_WORD = { entry: "entry", target: "target", stop: "stop" } as const;

/**
 * A two-leg vertical: each leg with its own quote (grey with its time when stale or missing), the net debit or credit
 * at the mid and the natural price, the width, and what the limit and count he types give: the most he can lose and
 * make, break-even, and the spread's worth at expiry at his plan's levels. Copy all puts the legs, then the net limit
 * price as a debit or credit, then the quantity on the clipboard. It copies; there is no Send button.
 */
function SpreadView({ ticket, spread: s, head, switcher, foot, limit, setLimit, qty, setQty, nowS, onReread }: {
  ticket: Ticket; spread: Spread; head: React.ReactNode; switcher: React.ReactNode; foot: React.ReactNode;
  limit: string; setLimit(v: string): void; qty: string; setQty(v: string): void; nowS: number; onReread(): void;
}) {
  const limitN = limit.trim() && Number(limit) > 0 ? Number(limit) : null;
  const qtyN = /^\d+$/.test(qty.trim()) && Number(qty) > 0 ? Number(qty) : null;
  const spot = ticket.underlying?.state === "ok" ? ticket.underlying.last ?? null : null;
  const f = spreadFigures(s.kind, s.long, s.short, limitN, qtyN, s.multiplier, spot, ticket.expected_move_pct,
    { entry: ticket.entry, target: ticket.target ?? null, stop: ticket.invalidation });
  const aged = (q: Quote) => q.state === "ok" && !q.simulated && q.as_of != null && nowS - q.as_of > STALE_S;
  const legOk = (q: Quote) => q.state === "ok" && !aged(q);
  const fresh = s.legs.every(l => legOk(l.quote));
  const rough = [...s.rough, ...s.legs.filter(l => l.quote.state === "ok" && aged(l.quote)).map(l => `the $${l.strike} leg's quote is now older than 15 minutes`)];
  const roughTag = rough.length > 0 ? <span className="ml-1 rounded border border-amber-300/50 px-1 text-[10px] uppercase tracking-wide text-amber-300">rough</span> : null;
  const sentence = spreadSentence(s.kind, s.long, s.short, limitN, qtyN, f);
  const all = spreadCopyText({ symbol: ticket.symbol, kind: s.kind, expiry: s.expiry, long: s.long, short: s.short,
    limit: limitN !== null ? limitN.toFixed(2) : "", contracts: qtyN ? String(qtyN) : "" });
  const field = "w-24 rounded border bg-background px-2 py-1.5 text-base tabular-nums sm:text-sm";
  const per = (n: number | null) => n === null ? "—" : `${n.toFixed(2)} ${s.type}`;
  return (
    <div data-testid="desk-ticket" data-spread={s.type} className="space-y-3">
      {head}
      {switcher}
      <div className="rounded-lg border bg-card px-3 py-1.5">
        <Row name="Spread" copy={<CopyButton text={s.label} label="spread" />}>
          <span className="font-mono tabular-nums">{s.label}</span>
          <span className="block text-xs text-muted-foreground">
            {s.type === "debit" ? "You pay to open it" : "You take in a credit to open it"} · width {s.width}{s.multiplier ? ` · ×${s.multiplier} a spread` : ""}
            {s.source === "picked" ? ` · your pick from the chain${ticket.plan_contract_words ? ` (your plan says: ${ticket.plan_contract_words})` : ""}` : ticket.plan_contract_words ? ` · your plan says: ${ticket.plan_contract_words}` : ""}
          </span>
          {s.against_plan && <span data-testid="spread-against" className="block text-xs text-amber-300">{s.against_plan}</span>}
        </Row>
        {s.legs.map((l, i) => {
          const q = l.quote, ok = legOk(q);
          return (
            <Row key={l.role} name={`Leg ${i + 1}: ${l.action === "buy" ? "Buy" : "Sell"}`} copy={<CopyButton text={`${l.action === "buy" ? "Buy" : "Sell"} ${l.label}`} label={`leg ${i + 1}`} />}>
              <span className={cn("font-mono tabular-nums", !ok && "text-muted-foreground")}>{l.label}</span>
              <span data-testid="spread-leg-quote" className={cn("block text-xs tabular-nums", ok ? "text-muted-foreground" : "text-muted-foreground/80")}>
                {ok ? <>Bid {q.bid!.toFixed(2)} · Ask {q.ask!.toFixed(2)} · Mid {q.mid!.toFixed(2)} · as of {clock(q.as_of)}{l.wide && <span className="text-amber-300"> · wide ({q.spread_pct}% of the mid)</span>}</>
                  : aged(q) ? `Quote stale (last ${clock(q.as_of)}): now older than 15 minutes.`
                  : q.state === "stale" ? `Quote stale (last ${clock(q.as_of)}): ${q.reason}` : `No quote: ${q.reason ?? "the chain could not be read."}`}
              </span>
            </Row>
          );
        })}
        <Row name="Net price">
          <span data-testid="spread-net" className="tabular-nums">
            {s.net_mid !== null && fresh ? <>{per(s.net_mid)} at the mid · {s.net_natural !== null && s.net_natural > 0 ? per(s.net_natural) : s.type === "credit" ? "no credit" : "—"} at the natural price</> : <span className="text-muted-foreground">No net price: {rough[0] ?? "a leg has no fresh quote"}.</span>}
            {roughTag}
          </span>
          {rough.length > 0 && <span data-testid="spread-rough" className="block text-xs text-amber-300">Rough: {rough.join("; ")}.</span>}
          {s.net_mid !== null && fresh && <span className="block text-xs text-muted-foreground">Natural: {s.type === "debit" ? "buy at the ask and sell at the bid, the most you would pay" : "sell at the bid and buy at the ask, the least you would take in"}.</span>}
        </Row>
        <Row name="Quantity" copy={<CopyButton text={qtyN ? String(qtyN) : ""} label="quantity" disabled={!qtyN} />}>
          <input aria-label="Quantity in spreads" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, "").slice(0, 4))} placeholder="set it" className={field} />
          <span className="block text-xs text-muted-foreground">{ticket.size.text ? `Plan's size: ${ticket.size.text}.` : "Your plan gives no size."} One spread is one of each leg.</span>
        </Row>
        <Row name={`Limit (${s.type})`} copy={<CopyButton text={limitN !== null ? limitN.toFixed(2) : ""} label="limit price" disabled={limitN === null} />}>
          <input aria-label={`Net limit price per share, ${s.type}`} inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value.replace(/[^\d.]/g, "").replace(/^(\d{0,6}(?:\.\d{0,2})?).*$/, "$1"))} placeholder="set it" className={field} />
          <span className="block text-xs text-muted-foreground">{fresh && s.net_mid !== null && ticket.limit !== null ? `The net mid as of ${clock(quotedAt(ticket, true))}${rough.length ? " (rough)" : ""}` : "No fresh net price: set it yourself."}</span>
        </Row>
        {f.warning ? <Row name="Check the price"><span data-testid="spread-warning" className="text-xs text-amber-300">{f.warning}</span></Row> : <>
          <Row name={s.type === "debit" ? "Cost" : "Credit"}><span className="tabular-nums">{s.type === "debit" ? (f.cost !== null ? usd(f.cost) : "—") : (f.credit !== null ? usd(f.credit) : "—")}</span></Row>
          <Row name="Most you can lose"><span data-testid="spread-max-loss" className="tabular-nums">{f.maxLoss !== null ? usd(f.maxLoss) : "—"}{f.maxLoss !== null && <span className="text-muted-foreground"> {s.type === "debit" ? "(what you pay)" : "(the width less the credit)"}</span>}</span></Row>
          <Row name="Most you can make"><span data-testid="spread-max-gain" className="tabular-nums">{f.maxGain !== null ? usd(f.maxGain) : "—"}{f.maxGain !== null && <span className="text-muted-foreground"> {s.type === "debit" ? "(the width less what you pay)" : "(the credit)"}</span>}</span></Row>
          <Row name="Break-even">
            {f.breakeven !== null ? (
              <span className="tabular-nums">{ticket.symbol} {f.breakeven.toFixed(2)} at expiry
                {f.movePct !== null && <span className="text-muted-foreground"> · needs {signedPct(f.movePct)} from {spot}{ticket.underlying?.as_of ? ` (${clock(ticket.underlying.as_of)})` : ""}</span>}
                {ticket.expected_move_pct && <span className="text-muted-foreground"> · expected move ±{ticket.expected_move_pct}%</span>}
              </span>
            ) : "—"}
            {ticket.underlying && ticket.underlying.state !== "ok" && <span className="block text-xs text-amber-300">{ticket.underlying.reason}</span>}
          </Row>
          {f.atLevels.length > 0 && (
            <Row name="At your levels">
              <ul data-testid="spread-levels" className="space-y-0.5 text-xs tabular-nums">
                {f.atLevels.map(a => (
                  <li key={a.role}>At your {ROLE_WORD[a.role]} {a.price}: worth {a.worth.toFixed(2)} at expiry{a.pnl !== null ? <>, <span className={a.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>{a.pnl >= 0 ? "+" : "−"}{usd(Math.abs(a.pnl))}</span></> : ""}</li>
                ))}
              </ul>
              <span className="block text-xs text-muted-foreground">At expiry only: before then time and volatility move it, and that is not estimated here.</span>
            </Row>
          )}
        </>}
      </div>
      {sentence && <p data-testid="spread-sentence" className="text-sm">{sentence}{rough.length > 0 && <span className="text-amber-300"> Rough: the legs&apos; quotes are not clean.</span>}</p>}
      {ticket.check && <PlayCheck check={ticket.check} investigationId={ticket.investigation_id} symbol={ticket.symbol} contracts={qtyN} paid={f.cost} unit="spreads" />}
      {!fresh && (
        <button type="button" onClick={onReread} className="text-xs text-foreground underline underline-offset-2">Read the quotes again</button>
      )}
      <div className="space-y-2">
        <CopyButton text={all} label="Copy all for Robinhood" wide />
        <p className="text-xs text-muted-foreground">You place it yourself in Robinhood: open {ticket.symbol}, Trade, Trade options, pick both legs (Buy the ${s.long}, Sell the ${s.short}, {shortDate(s.expiry)}), then the limit as a {s.type} and the quantity. Nothing is sent from here.</p>
      </div>
      {foot}
    </div>
  );
}

/**
 * A close-now ticket (the copilot's close and trim cards, ``closeNowTicket``): a sell to close of all or part of a held
 * long call or put at the mark now, or the closing spread of a held vertical (sell the bought leg, buy back the sold one)
 * at its net mark. Filled in the browser from the book row; it copies and never sends (no Send button).
 */
function CloseNowView({ ticket: t, onClose, onPlaced }: { ticket: CloseNowTicket; onClose(): void; onPlaced(symbol: string): void }) {
  const [limit, setLimit] = useState(t.limit.toFixed(2));
  const [qty, setQty] = useState(String(t.contracts));
  const limitN = limit.trim() && Number(limit) > 0 ? Number(limit) : null;
  const qtyN = /^\d+$/.test(qty.trim()) && Number(qty) > 0 && Number(qty) <= t.held ? Number(qty) : null;
  const spread = t.shortStrike !== null;
  const unit = spread ? "spread" : "contract";
  const kind = kindWord(t.side).toLowerCase();
  const label = spread ? `${t.symbol} $${t.strike}/$${t.shortStrike} ${kindWord(t.side)} ${shortDate(t.expiry)}` : `${t.symbol} $${t.strike} ${kindWord(t.side)} ${shortDate(t.expiry)}`;
  const action = spread ? `Close spread: sell the $${t.strike} ${kind}, buy back the $${t.shortStrike} ${kind}` : "Sell to close";
  const limitText = limitN !== null ? limitN.toFixed(2) : "";
  const all = spread
    ? [t.symbol, action, `Expiration ${shortDate(t.expiry)}`, `Limit price ${limitText ? `${limitText} ${t.credit ? "credit" : "debit"}` : "(set it)"}`,
       `Quantity ${qtyN ? String(qtyN) : "(set it)"}`].join("\n")
    : copyAllText({ symbol: t.symbol, type: t.side, expiry: t.expiry, strike: t.strike, action: "Sell", limit: limitText, contracts: qtyN ? String(qtyN) : "" });
  const left = qtyN ? t.held - qtyN : null;
  const markWords = spread
    ? `Mark now ${t.mark.toFixed(2)} − ${t.shortMark!.toFixed(2)} = ${t.net < 0 ? "−" : ""}${Math.abs(t.net).toFixed(2)}`
    : `Mark now ${t.mark.toFixed(2)}`;
  const whole = t.contracts === t.held;
  const field = "w-24 rounded border bg-background px-2 py-1.5 text-base tabular-nums sm:text-sm";
  return (
    <div data-testid="desk-ticket" data-closing="now" className="space-y-3">
      <div className="space-y-1">
        <p className="text-sm"><span className="font-semibold">{t.symbol}</span><span className="text-muted-foreground"> · {whole ? "Close" : "Trim"} at the mark now</span></p>
        <p className="text-xs text-muted-foreground">A closing {spread ? "spread" : "sell"} of {whole ? `all ${t.held}` : `${t.contracts} of the ${t.held}`} {unit}{t.held === 1 ? "" : "s"} you hold, priced at {spread ? "the spread's net" : "today's"} mark. It copies; it never sends.</p>
      </div>
      <div className="rounded-lg border bg-card px-3 py-1.5">
        {t.account && <Row name="Account"><span>{t.account}</span></Row>}
        <Row name="Action" copy={<CopyButton text={action} label="action" />}><span className="font-medium">{action}</span></Row>
        <Row name="Contract" copy={<CopyButton text={label} label="contract" />}><span className="font-mono tabular-nums">{label}</span></Row>
        <Row name="Quantity" copy={<CopyButton text={qtyN ? String(qtyN) : ""} label="quantity" disabled={!qtyN} />}>
          <input aria-label={`Quantity in ${unit}s`} inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, "").slice(0, 4))} placeholder="set it" className={field} />
          <span data-testid="close-now-left" className="block text-xs text-muted-foreground">
            {qtyN === null ? `You hold ${t.held}: set 1 to ${t.held}.` : `You hold ${t.held}; ${left === 0 ? "none left after this" : `${left} left after this`}.`}
          </span>
        </Row>
        <Row name="Limit price" copy={<CopyButton text={limitText} label="limit price" disabled={limitN === null} />}>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <input aria-label={spread ? `Limit price, net ${t.credit ? "credit" : "debit"} per spread` : "Limit price per share"} inputMode="decimal" value={limit}
              onChange={e => setLimit(e.target.value.replace(/[^\d.]/g, "").replace(/^(\d{0,6}(?:\.\d{0,2})?).*$/, "$1"))} placeholder="set it" className={field} />
            {spread && <span className="text-xs">{t.credit ? "credit" : "debit"}</span>}
            <span data-testid="close-now-mark" className="text-xs tabular-nums text-muted-foreground">{markWords}{t.markLive ? "" : " (last read)"}</span>
          </span>
          <span className="block text-xs text-muted-foreground">
            {spread && !t.credit ? "Closing this spread costs money: the leg you sold is worth more than the one you bought. " : ""}
            Priced at the mark: a sell at or under the bid fills at once, at about the bid; above the mark it can wait unfilled. Set your own.
          </span>
        </Row>
        <Row name={t.credit ? "Proceeds" : "Cost"}>
          <span data-testid="close-now-proceeds" className="tabular-nums">{limitN !== null && qtyN ? `about ${usd(limitN * t.multiplier * qtyN)} at this limit` : "—"}</span>
        </Row>
      </div>
      <div className="space-y-2">
        <CopyButton text={all} label="Copy all for Robinhood" wide />
        <p className="text-xs text-muted-foreground">You place it yourself in Robinhood: open {t.symbol}, your {spread ? "spread" : `${kind} position`}, {spread ? "Close" : "Sell"}, then enter each field. Nothing is sent from here.</p>
      </div>
      <div className="flex flex-wrap gap-2 border-t pt-3">
        <button type="button" onClick={() => onPlaced(t.symbol)} className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary sm:min-h-8">I placed it</button>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Not now</button>
      </div>
    </div>
  );
}

/**
 * A closing ticket: a sell to close of the contracts held, with the limit estimated for the stock at the plan's level
 * and today's mark beside it. Filled in the browser from the book row; it copies and never sends (no Send button).
 */
function ClosingView({ ticket: t, onClose, onPlaced }: { ticket: ClosingTicket; onClose(): void; onPlaced(symbol: string): void }) {
  const [limit, setLimit] = useState(t.estimate.toFixed(2));
  const [qty, setQty] = useState(String(t.contracts));
  const limitN = limit.trim() && Number(limit) > 0 ? Number(limit) : null;
  const qtyN = /^\d+$/.test(qty.trim()) && Number(qty) > 0 ? Number(qty) : null;
  const label = `${t.symbol} $${t.strike} ${kindWord(t.side)} ${shortDate(t.expiry)}`;
  const where = t.at === "target" ? "target" : "stop (invalidation)";
  const all = copyAllText({ symbol: t.symbol, type: t.side, expiry: t.expiry, strike: t.strike, action: "Sell",
    limit: limitN !== null ? limitN.toFixed(2) : "", contracts: qtyN ? String(qtyN) : "" });
  const signed = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(2)}`;
  const field = "w-24 rounded border bg-background px-2 py-1.5 text-base tabular-nums sm:text-sm";
  return (
    <div data-testid="desk-ticket" data-closing={t.at} className="space-y-3">
      <div className="space-y-1">
        <p className="text-sm"><span className="font-semibold">{t.symbol}</span><span className="text-muted-foreground"> · Close at {where}, {t.level.toFixed(2)}</span></p>
        <p className="text-xs text-muted-foreground">A closing sell of the {t.contracts} contract{t.contracts === 1 ? "" : "s"} you hold, priced for {t.symbol} at your plan&apos;s {t.at}. It copies; it never sends.</p>
      </div>
      <div className="rounded-lg border bg-card px-3 py-1.5">
        <Row name="Account"><span>{t.account}</span></Row>
        <Row name="Action" copy={<CopyButton text="Sell to close" label="action" />}><span className="font-medium">Sell to close</span></Row>
        <Row name="Contract" copy={<CopyButton text={label} label="contract" />}><span className="font-mono tabular-nums">{label}</span></Row>
        <Row name="Quantity" copy={<CopyButton text={qtyN ? String(qtyN) : ""} label="quantity" disabled={!qtyN} />}>
          <input aria-label="Quantity in contracts" inputMode="numeric" value={qty} onChange={e => setQty(e.target.value.replace(/[^\d]/g, "").slice(0, 4))} placeholder="set it" className={field} />
          <span className="block text-xs text-muted-foreground">You hold {t.contracts}.</span>
        </Row>
        <Row name="Limit price" copy={<CopyButton text={limitN !== null ? limitN.toFixed(2) : ""} label="limit price" disabled={limitN === null} />}>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <input aria-label="Limit price per share" inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value.replace(/[^\d.]/g, "").replace(/^(\d{0,6}(?:\.\d{0,2})?).*$/, "$1"))} placeholder="set it" className={field} />
            <span data-testid="closing-mark" className="text-xs tabular-nums text-muted-foreground">Mark now {t.mark.toFixed(2)}{t.markLive ? "" : " (last read)"}</span>
          </span>
          <span data-testid="closing-estimate" className="block text-xs text-amber-300">
            {t.past
              ? <>{t.symbol} is already {t.at === "stop" ? "through your stop" : "past your target"} ({t.stock.toFixed(2)}{t.stockAt ? `, ${clock(t.stockAt)}` : ""} against {t.level.toFixed(2)}): the limit starts at today&apos;s mark, not a price for the level. Set your own.</>
              : <>Estimate, not a quote: if {t.symbol} reaches {t.level.toFixed(2)} (now {t.stock.toFixed(2)}{t.stockAt ? `, ${clock(t.stockAt)}` : ""}), the mark {t.mark.toFixed(2)} {signed(t.delta * (t.level - t.stock))} by its delta {signed(t.delta)}{t.floored ? `, raised to ${t.estimate.toFixed(2)}, its least value there (worth at expiry, or a cent)` : ` ≈ ${t.estimate.toFixed(2)}`}. Time, IV and the spread move it; set your own.</>}
          </span>
        </Row>
        <Row name="When to place it">
          <span data-testid="closing-when" className="text-xs">
            {t.past ? `${t.symbol} is already there: placed now, a sell at about today's mark closes it now.`
              : t.at === "stop" ? `Place it only once ${t.symbol} is at ${t.level.toFixed(2)}. This limit is under today's mark ${t.mark.toFixed(2)}, and a sell limit under the bid fills at once, at about the bid: placed early, it closes the position now, not at your stop.`
              : `It can wait in Robinhood as a limit: it fills only if the option trades up to it. If ${t.symbol} gets there faster or slower than the estimate assumes, the option may not reach it.`}
          </span>
        </Row>
        <Row name="Proceeds"><span className="tabular-nums">{limitN !== null && qtyN ? `about ${usd(limitN * t.multiplier * qtyN)} at this limit` : "—"}</span></Row>
      </div>
      <div className="space-y-2">
        <CopyButton text={all} label="Copy all for Robinhood" wide />
        <p className="text-xs text-muted-foreground">You place it yourself in Robinhood: open {t.symbol}, your {kindWord(t.side).toLowerCase()} position, Sell, then enter each field. Nothing is sent from here.</p>
      </div>
      <div className="flex flex-wrap gap-2 border-t pt-3">
        <button type="button" onClick={() => onPlaced(t.symbol)} className="inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary sm:min-h-8">I placed it</button>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Not now</button>
      </div>
    </div>
  );
}
