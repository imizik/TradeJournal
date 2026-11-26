"use client";

/**
 * The ping card (docs/copilot-lab.md § Where a ping opens): where a position ping lands, ahead of the copilot's sheet.
 * It leads with what fired and what holding past that kind of ping has done for him in dollars, then the position as it
 * stands (P&L, bid and mid, contracts, whether an exit order is working, what it is worth at expiry if the stock stays
 * flat), then thumb-sized actions: Open in Robinhood (primary, where he sells), Cut it and Holding…, with Set stop
 * under them; with no Robinhood link, Copy Close all at the bid, Copy Trim half and Set stop as before. Holding is not
 * one tap: it asks for a check-in time (+15m or +30m) or a price stop first. A check-in time rides on the hold's journal
 * entry, and with HOLD_CHECK_IN_PINGS on the server pings again then if the position is still open (engine/hold_check_ins.py).
 *
 * Copy only: an order's lines go on the clipboard, to paste into Robinhood. Nothing here places, sizes or sends an
 * order. Each choice is a ``decision`` day-journal entry ("Exiting. …" / "Holding. …"), so the alert scorecard measures
 * it, and a fill-time pattern interrupt's card records its Noted with it.
 */

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api, apiUrl } from "@/lib/api";
import { money, nyDay, signedPct, type DeskOrder, type DeskThread } from "@/lib/desk";
import { tickedBook, useDeskTicks } from "@/lib/deskTicks";
import { everyDeskMinute } from "@/lib/deskMinute";
import { heldContracts, markNow, planSide, savePlanLevels, type PanelPlan } from "@/lib/deskPosition";
import { trimCount } from "@/lib/closingTicket";
import { copyText } from "@/lib/clipboard";
import { price as priceText } from "@/lib/charts";
import { copyAllText } from "@/components/copilot/DeskTicket";
import { LevelsEditor } from "@/components/copilot/DeskPosition";
import { useStanding } from "@/components/copilot/OptionStanding";
import type { CardLink } from "@/lib/copilot";
import { cn } from "@/lib/utils";


type PingAlert = { id: string; kind: string; kind_label: string; at: number; contract: string; contracts: number; bid: number | null;
  mark: number | null; gain: number | null; gain_pct: number | null; avg_cost: number; quoted_at: number | null };
type PingInterrupt = { id: string; trade_id: string; contract: string; title: string; lines: string[]; noted_at: number | null };
type Habit = { kind_label: string; window_days: number; held: number; closed: number; better: number; worse: number; vs_alert_usd: number };
export type PingCardBody = { symbol: string | null; alert: PingAlert | null; interrupt: PingInterrupt | null; habit: Habit | null;
  broker: { label: string; url: string } | null;
  /** The trade now holding the pinged position, and whether it is still open (absent from an older backend). */
  position?: { trade_id: string | null; open: boolean } | null;
  /** Whether Keep holding's +15m / +30m pings again at that time while the position is open (HOLD_CHECK_IN_PINGS). */
  check_in_pings?: boolean };

/** The pinged position's book row: by its trade (trades are rebuilt, so the server resolves the current one), else a
 * Robinhood-only row of the same contract; never another strike, expiry or account in the ticker. Null when it is closed. */
export function pingRow(body: PingCardBody, rows: readonly DeskThread[]): DeskThread | null {
  if (!body.symbol || body.position?.open === false) return null;
  const mine = rows.filter(r => r.symbol === body.symbol && r.book);
  const id = body.position?.trade_id;
  if (id) { const hit = mine.find(r => r.tradeId === id); if (hit) return hit; }
  const contract = body.alert?.contract ?? body.interrupt?.contract;
  const same = contract ? mine.filter(r => !r.tradeId && `${r.symbol} ${r.instrument}` === contract) : [];
  return same.length === 1 ? same[0] : null;
}

/** The working exit orders among a row's orders: only a closing order is an exit, never a working buy to open (a
 * scale-in) on the same contract (as ``robinhood_fills.exit_working``). */
export function exitOrders(orders: readonly DeskOrder[] | undefined): DeskOrder[] {
  return (orders ?? []).filter(o => o.working && /to close$/i.test(o.action));
}

/** A bid older than this is not "the bid": the card prices at the mid now instead and says so. */
const FRESH_BID_SECONDS = 10 * 60;
/** The button the ping's Close or Trim link asked for. */
const ASKED = "ring-4 ring-amber-400 ring-offset-2 ring-offset-card";
const BIG = "flex min-h-12 w-full items-center justify-center rounded-lg px-4 text-base font-semibold";
const hhmm = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const usd0 = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** What holding past this kind of ping has done, in one line; null before any was held. */
export function habitLine(h: Habit | null): string | null {
  if (!h || !h.held) return null;
  const label = h.kind_label.toLowerCase();
  if (!h.closed) return `You held past ${h.held} ${label} ping${h.held === 1 ? "" : "s"} in ${h.window_days} days; none has closed yet.`;
  const net = h.vs_alert_usd;
  const said = net < 0 ? `selling at the ping would have made $${Math.abs(net).toLocaleString("en-US", { maximumFractionDigits: 0 })} more`
    : net > 0 ? `holding made $${net.toLocaleString("en-US", { maximumFractionDigits: 0 })} more than selling at the ping` : "holding came out even";
  return `Held past ${h.closed} ${label} ping${h.closed === 1 ? "" : "s"} (${h.window_days} days): ${said}.`;
}

export async function readPingCard(card: CardLink, symbol: string | null, signal?: AbortSignal): Promise<PingCardBody> {
  const query = new URLSearchParams({ ...(symbol ? { symbol } : {}), [card.kind]: card.id });
  const response = await fetch(apiUrl(`/copilot/desk/ping-card?${query}`), { cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body as PingCardBody;
}

/**
 * ``card`` the ping, ``rows`` the desk's book, ``onSymbol`` hears the ping's ticker once read (the desk centres on it),
 * ``onAsk`` opens the copilot with a question in the box (unsent), ``onPlan`` the plan flow for a position with no plan,
 * ``onDismiss`` puts the card away (the chart and its Position panel are under it).
 */
export default function PingCard({ card, rows, ordersLive, onSymbol, onAsk, onPlan, onDismiss }: {
  card: CardLink; rows: readonly DeskThread[]; ordersLive: boolean; onSymbol(symbol: string): void; onAsk(text: string): void;
  onPlan(symbol: string): void; onDismiss(): void;
}) {
  const [body, setBody] = useState<PingCardBody | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readPingCard(card, null, controller.signal).then(read => { setBody(read); if (read.symbol) onSymbol(read.symbol); })
      .catch(e => { if (!controller.signal.aborted) setFailed(e instanceof Error ? e.message : "Could not read the ping."); });
    return () => controller.abort();
  }, [card, onSymbol]);
  const row = body ? pingRow(body, rows) : null;
  return (
    <section aria-label="Ping" data-testid="ping-card" className="relative m-2 space-y-3 rounded-xl border-2 border-primary/60 bg-card p-3 sm:m-3">
      <button type="button" onClick={onDismiss} aria-label="Put the card away"
        className="absolute right-1.5 top-1.5 inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground">
        <X size={16} aria-hidden />
      </button>
      {failed ? <p role="status" className="pr-10 text-sm text-muted-foreground">This ping could not be read: {failed}</p>
        : !body ? <p role="status" className="pr-10 text-sm text-muted-foreground">Reading the ping…</p>
        : <>
          <Trigger body={body} />
          {row ? <Act key={row.key} act={card.act} body={body} row={row} rows={rows} ordersLive={ordersLive} onAsk={onAsk} onPlan={onPlan} />
            : <p data-testid="ping-card-closed" className="text-sm text-muted-foreground">
                {body.position?.open === false ? `This ${body.symbol ?? ""} position is closed.`
                  : rows.length ? `This ${body.symbol ?? ""} position is not on the desk now: it may already be closed.` : "Reading your positions…"}
              </p>}
        </>}
    </section>
  );
}

/** What fired, and what holding past it has done. */
function Trigger({ body }: { body: PingCardBody }) {
  const { alert, interrupt } = body;
  const habit = habitLine(body.habit);
  return (
    <div data-testid="ping-card-trigger" className="space-y-1 pr-10">
      {alert && <>
        <p className="text-base font-semibold text-foreground">{alert.kind_label} · {hhmm(alert.at)}</p>
        <p className="text-sm text-muted-foreground">{alert.contract}{alert.gain != null && <> · was <span className="tabular-nums">{money(alert.gain)}{alert.gain_pct != null && ` (${signedPct(alert.gain_pct * 100, 0)})`}</span> at the ping</>}</p>
      </>}
      {interrupt && <>
        <p className="text-base font-semibold text-foreground">{interrupt.title}</p>
        <ul className="space-y-0.5 text-sm text-muted-foreground">{interrupt.lines.filter(Boolean).map(l => <li key={l}>{l}</li>)}</ul>
      </>}
      {!alert && !interrupt && <p className="text-base font-semibold text-foreground">{body.symbol}</p>}
      {habit && <p data-testid="ping-card-habit" className={cn("text-sm font-medium", (body.habit?.vs_alert_usd ?? 0) < 0 ? "text-rose-300" : "text-foreground")}>{habit}</p>}
    </div>
  );
}

type Done = { text: string; copied?: boolean };

/** The position as it stands, and what to do about it. */
function Act({ act, body, row, rows, ordersLive, onAsk, onPlan }: {
  act?: "close" | "trim"; body: PingCardBody; row: DeskThread; rows: readonly DeskThread[]; ordersLive: boolean; onAsk(text: string): void; onPlan(symbol: string): void;
}) {
  const book = row.book!;
  const symbol = row.symbol!;
  const ticks = useDeskTicks([symbol, book.tick?.quote]);
  const read = useStanding(row, rows, null);
  const standing = read && typeof read === "object" ? read : null;
  const pnl = tickedBook(book, ticks);
  const mark = markNow(book, ticks);
  const held = heldContracts(book);
  const option = book.option;
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [holding, setHolding] = useState(false);
  const [stopping, setStopping] = useState<"stop" | "hold" | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => everyDeskMinute(() => setNow(Date.now() / 1000)), []); // a bid goes stale while the card is open

  // The bid: the ping's own when it is fresh, else the mid now (and the button says which).
  const alert = body.alert;
  const bidAt = alert?.quoted_at ?? alert?.at ?? null;
  const freshBid = alert?.bid != null && bidAt !== null && now - bidAt <= FRESH_BID_SECONDS ? alert.bid / 100 : null;
  const sellAt = freshBid ?? mark?.share ?? null;
  const basis = freshBid !== null ? "bid" : "mid";
  // Only a lone long call or put (``useStanding`` reads a spread's leg as unknown): selling one leg of a structure alone
  // could leave its short leg naked, so the Position panel's own guard holds here too.
  const copyable = !!standing && !!option && option.direction === "long" && (option.side === "call" || option.side === "put") && option.strike != null && option.expiry
    && held != null && Number.isInteger(held) && held >= 1 && sellAt !== null && sellAt > 0;
  const half = held && held >= 2 ? trimCount(held, { half: true }) : null;
    const working = ordersLive ? exitOrders(book.orders) : null;
  const atExpiry = standing?.standing.atExpiry ?? null;
  const stockNow = standing?.stock?.last ?? null;
  const plan: PanelPlan | null = row.investigationId && book.plan_levels?.stop != null
    ? { investigationId: row.investigationId, entry: null, stop: book.plan_levels.stop, target: book.plan_levels.target ?? null } : null;
  const side = planSide({ entry: null, stop: plan?.stop }, { option, sign: book.tick?.sign });
  const fired = alert ? `${alert.kind_label} ping at ${hhmm(alert.at)}` : body.interrupt ? `Fill pattern: ${body.interrupt.title}` : "Ping";

  // An interrupt's card: any choice made here (a copy, a hold, a stop saved) records its Noted.
  const noted = async () => {
    const i = body.interrupt;
    if (i && i.noted_at == null) await fetch(apiUrl(`/trades/${encodeURIComponent(i.trade_id)}/fill-interrupts/${encodeURIComponent(i.id)}/noted`), { method: "POST" }).catch(() => undefined);
  };
  const log = async (choice: "Exiting" | "Holding", what: string, checkIn?: 15 | 30) => {
    const ping = checkIn ? (alert ? { alert: alert.id } : body.interrupt ? { interrupt: body.interrupt.id } : null) : null;
    await api.addDayJournalEntry(nyDay(), { operation_id: `decision-${uid()}`, kind: "decision", symbol, text: `${choice}. ${fired}; ${what}.`,
      ...(ping ? { check_in: { minutes: checkIn!, ...ping } } : {}) });
    await noted();
  };
  const copyClose = async (contracts: number) => {
    if (!copyable || sellAt === null) return;
    setError(null);
    const limit = sellAt.toFixed(2);
    const ok = await copyText(copyAllText({ symbol, type: option!.side as "call" | "put", expiry: option!.expiry!, strike: option!.strike!, limit, contracts: String(contracts), action: "Sell" }));
    if (!ok) { setError("The clipboard refused the copy. Long-press to copy from the Ticket instead."); return; }
    const whole = contracts === held;
    const what = whole ? `copied close all ${contracts} at ${basis} ${limit}` : `copied trim ${contracts} of ${held} at ${basis} ${limit}`;
    setDone({ text: `Copied: sell ${contracts} at ${limit}. Paste it in Robinhood.`, copied: true });
    log("Exiting", what).catch(() => setError("Copied, but the decision was not saved."));
  };
  const cutIt = async () => {
    setError(null);
    try {
      await log("Exiting", "said Cut it on the card");
      setDone({ text: "Saved: cutting it. Sell it in Robinhood." });
    } catch (e) { setError(e instanceof Error ? e.message : "Not saved."); }
  };
  const keepFor = async (minutes: 15 | 30) => {
    const at = Date.now() / 1000 + minutes * 60;
    setHolding(false);
    try {
      await log("Holding", `check again at ${hhmm(at)}`, minutes);
      setDone({ text: body.check_in_pings ? `Holding. I'll ping you at ${hhmm(at)} if it's still open.` : `Holding. Check again at ${hhmm(at)}.` });
    } catch (e) { setError(e instanceof Error ? e.message : "Not saved."); }
  };

  return (
    <div className="space-y-3">
      <dl data-testid="ping-card-figures" className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm tabular-nums">
        <Figure label="P&L">
          <span className={pnl.usd == null ? "text-muted-foreground" : pnl.usd > 0 ? "text-emerald-300" : pnl.usd < 0 ? "text-rose-300" : ""}>
            {pnl.usd != null ? money(pnl.usd) : "—"}{pnl.pct != null && ` (${signedPct(pnl.pct, 0)})`}
          </span>
        </Figure>
        <Figure label="Contracts">{held != null ? held.toLocaleString("en-US", { maximumFractionDigits: 4 }) : "—"}</Figure>
        <Figure label="Bid / mid">
          {freshBid !== null ? priceText(freshBid) : "—"} / {mark ? <span className={cn(!mark.live && "opacity-60")}>{priceText(mark.share)}</span> : "—"}
        </Figure>
        <Figure label="Exit order">
          {working === null ? <span className="text-muted-foreground">unknown</span>
            : working.length ? <span className="text-emerald-300">{working.map(o => `${o.action} ${o.quantity ?? ""}${o.limit != null ? ` @ ${priceText(o.limit)}` : ""}`).join(", ")}</span>
            : <span data-testid="ping-card-no-exit" className="font-medium text-amber-300">None working</span>}
        </Figure>
        {atExpiry !== null && stockNow !== null && (
          <Figure label={`At expiry if ${symbol} stays ${priceText(stockNow)}`} wide>
            <span className={atExpiry <= 0 ? "font-medium text-rose-300" : ""}>{usd0(atExpiry).replace("+", "")}</span>
          </Figure>
        )}
      </dl>

      <div role="group" aria-label="Act on this position" className="space-y-2">
        {/* Robinhood first: it is where he sells. Cut it records the choice (an Exiting decision, as a Telegram tap does). */}
        {body.broker ? <>
          <a href={body.broker.url} target="_blank" rel="noreferrer" data-testid="ping-card-robinhood"
            className={cn(BIG, "bg-primary text-primary-foreground", act && ASKED)}>Open {symbol} in {body.broker.label}</a>
          <div className="grid grid-cols-2 gap-2">
            <button type="button" data-testid="ping-card-cut" onClick={() => void cutIt()} className={cn(BIG, "border text-foreground hover:bg-secondary")}>Cut it</button>
            <button type="button" data-testid="ping-card-holding" onClick={() => setHolding(true)} className={cn(BIG, "border text-foreground hover:bg-secondary")}>Holding…</button>
          </div>
        </> : copyable ? <>
          <button type="button" data-testid="ping-card-close" data-asked={act === "close" || undefined} autoFocus={act === "close"}
            onClick={() => void copyClose(held!)} className={cn(BIG, "bg-primary text-primary-foreground", act === "close" && ASKED)}>
            Copy Close all {held} @ {basis} {sellAt!.toFixed(2)}
          </button>
          <div className="grid grid-cols-2 gap-2">
            {half ? <button type="button" data-testid="ping-card-trim" data-asked={act === "trim" || undefined} autoFocus={act === "trim"}
              onClick={() => void copyClose(half)} className={cn(BIG, "border text-foreground hover:bg-secondary", act === "trim" && ASKED)}>Copy Trim {half}</button>
              : <span />}
            <button type="button" data-testid="ping-card-stop" onClick={() => plan && side ? setStopping(stopping === "stop" ? null : "stop") : onPlan(symbol)}
              className={cn(BIG, "border text-foreground hover:bg-secondary")}>Set stop</button>
          </div>
        </> : (
          <p className="text-sm text-muted-foreground">Close and Trim copy a single long call or put with a price; use the Position panel below for this one.</p>
        )}
        {stopping && plan && side && (
          <LevelsEditor symbol={symbol} side={side} last={stockNow} stop={plan.stop} target={plan.target} needStop
            save={async (stop, target) => {
              const saved = await savePlanLevels({ symbol, plan, side, stop, target });
              if (stopping === "hold") await log("Holding", `stop moved to ${saved.stop != null ? priceText(saved.stop) : "none"}`);
              else await noted();
              return saved.text;
            }}
            onDone={words => { setStopping(null); if (words) setDone({ text: words }); }}
            note={<p className="text-[11px] text-muted-foreground">A stock price. It re-arms the plan&apos;s stop alert; nothing is sent to Robinhood.</p>} />
        )}
        {holding ? (
          <div data-testid="ping-card-hold-pick" className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Keep holding until:</span>
            <button type="button" onClick={() => void keepFor(15)} className="min-h-11 rounded-md border px-3 font-medium hover:bg-secondary">+15m</button>
            <button type="button" onClick={() => void keepFor(30)} className="min-h-11 rounded-md border px-3 font-medium hover:bg-secondary">+30m</button>
            <button type="button" onClick={() => { setHolding(false); if (plan && side) setStopping("hold"); else onPlan(symbol); }}
              className="min-h-11 rounded-md border px-3 font-medium hover:bg-secondary">Price stop</button>
            <button type="button" onClick={() => setHolding(false)} className="min-h-11 px-2 text-muted-foreground hover:text-foreground">Cancel</button>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-sm">
            {body.broker
              ? <button type="button" data-testid="ping-card-stop" onClick={() => plan && side ? setStopping(stopping === "stop" ? null : "stop") : onPlan(symbol)}
                  className="min-h-11 px-1 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">Set stop</button>
              : <button type="button" data-testid="ping-card-hold" onClick={() => setHolding(true)}
                  className="min-h-11 px-1 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">Keep holding…</button>}
            <button type="button" onClick={() => onAsk(`${fired} on ${symbol}. Should I close, trim or hold here, and why?`)}
              className="ml-auto min-h-11 px-1 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">Ask copilot</button>
          </div>
        )}
      </div>
      {done && (
        <p role="status" data-testid="ping-card-done" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-emerald-300">
          {done.text}
          {done.copied && body.broker && <a href={body.broker.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center font-medium text-foreground underline underline-offset-2">Open {body.broker.label}</a>}
        </p>
      )}
      {error && <p role="alert" className="text-sm text-amber-300">{error}</p>}
    </div>
  );
}

function Figure({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cn("min-w-0", wide && "col-span-2")}>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{children}</dd>
    </div>
  );
}
