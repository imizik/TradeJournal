"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import SetupRecordLines, { premiumLine } from "@/components/copilot/SetupRecordLines";
import { apiUrl } from "@/lib/api";
import { getSymbolLoop, type SetupRecord } from "@/lib/copilot";
import type { ClosingTicket } from "@/lib/closingTicket";
import { cn } from "@/lib/utils";

/**
 * The desk's Ticket tab (docs/copilot-lab.md § Ticket), copy-to-Robinhood mode: one saved plan's order fields, each
 * with its own Copy, and Copy all in the order Robinhood's option order screen asks for them. It copies and never sends:
 * this file reads two GET routes and the clipboard, and the MCP account's Send button is drawn disabled with no handler.
 * A ticket opens only from a saved plan (``openTicket`` from a confirmed plan card, a plan thread's header, a book row,
 * or this tab's list of armed plans not yet entered). A closing ticket (``openClosingTicket``, the held option's "Close
 * at target" / "Close at stop") is filled in the browser from the book row (``lib/closingTicket.ts``): a sell to close
 * of the contracts held with an estimated limit; it reads nothing and has no Send button at all.
 */

export const TICKET_EVENT = "tradejournal:open-ticket";
const LABEL = "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const READ_MS = 60_000;
const STALE_S = 15 * 60;  // the server's QUOTE_STALE_S

/** A contract he picked for a ticket (the Chain tab's Put on ticket): it replaces the contract the plan names. */
export type TicketPick = { expiry: string; strike: number };

/** Opens a saved plan's ticket: on the desk the Ticket tab takes it; anywhere else the desk opens on it. */
export function openTicket(investigationId: string, pick?: TicketPick) {
  const handled = !window.dispatchEvent(new CustomEvent(TICKET_EVENT, { detail: { investigationId, pick }, cancelable: true }));
  if (!handled) window.location.assign(`/copilot-lab?ticket=${encodeURIComponent(investigationId)}`);
}

/** Opens a closing ticket on the desk's Ticket tab. Its buttons live only on the desk, which handles the event. */
export function openClosingTicket(close: ClosingTicket) {
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
type Ticket = {
  state: "ok" | "not_option" | "no_quotes"; reason?: string; investigation_id: string; symbol: string; direction: string | null;
  thesis: string | null; option_type: "call" | "put" | null; entry: number | null; invalidation: number | null; time_stop: string | null;
  plan_contract_words: string | null; size: { contracts: number | null; risk_usd: number | null; text: string | null };
  accounts: Account[]; account: string | null; simulated: boolean;
  contract: { strike: number; expiry: string; type: "call" | "put"; label: string; source: "plan" | "picked"; multiplier: number | null } | null;
  candidates: { state: "ok" | "stale" | "missing"; reason?: string; as_of?: number | null; rows: Candidate[] } | null;
  quote: Quote | null; underlying: { state: "ok" | "stale" | "missing"; last?: number; as_of?: number | null; reason?: string } | null;
  expected_move_pct: number | null; limit: number | null; contracts: number | null;
};

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), { cache: "no-store", signal });
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
    const timer = setInterval(load, READ_MS);
    return () => { controller.abort(); clearInterval(timer); };
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
  /** A closing ticket from a held option's plan; it takes the tab over an open plan ticket. */
  close?: ClosingTicket | null;
  onPlaced(symbol: string): void; onPlan(): void;
}) {
  if (close) return <ClosingView key={`${close.symbol}|${close.expiry}|${close.strike}|${close.at}`} ticket={close} onClose={onClose} onPlaced={onPlaced} />;
  if (open) return <TicketView key={`${open}|${pick?.expiry ?? ""}|${pick?.strike ?? ""}`} investigationId={open} initialPick={pick} onClose={onClose} onPlaced={onPlaced} />;
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
    const query = pick ? `?expiration=${pick.expiry}&strike=${pick.strike}` : "";
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

  const ageing = !!ticket?.quote && ticket.quote.state === "ok" && !ticket.quote.simulated && ticket.quote.as_of != null && nowS - ticket.quote.as_of > STALE_S;
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

  // No contract named: two or three real contracts to choose from; nothing is chosen for him.
  if (!ticket.contract) {
    const c = ticket.candidates;
    return (
      <div data-testid="desk-ticket" className="space-y-3">
        {head}
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
            Estimate, not a quote: if {t.symbol} reaches {t.level.toFixed(2)} (now {t.stock.toFixed(2)}{t.stockAt ? `, ${clock(t.stockAt)}` : ""}), the mark {t.mark.toFixed(2)} {signed(t.delta * (t.level - t.stock))} by its delta {t.delta.toFixed(2)} ≈ {t.estimate.toFixed(2)}. Time, IV and the spread move it; set your own.
          </span>
        </Row>
        <Row name="Proceeds"><span className="tabular-nums">{limitN !== null && qtyN ? `about ${usd(limitN * 100 * qtyN)} at this limit` : "—"}</span></Row>
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
