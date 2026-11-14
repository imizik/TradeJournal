"use client";

import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import { useDeskWalls, wallsLine, type DeskWalls } from "@/lib/deskWalls";
import { PaperButton } from "@/components/copilot/DeskPaper";
import type { TicketPlan } from "@/components/copilot/DeskTicket";
import type { UnusualRow } from "@/components/copilot/DeskUnusual";
import { isBullish, spreadFigures, spreadLabel, spreadNet, spreadWords } from "@/lib/spreadTicket";
import { cn } from "@/lib/utils";

/**
 * The desk's Chain tab (docs/copilot-lab.md § Chain): one expiry of the selected ticker's option chain around the price,
 * to pick a contract without opening Robinhood. Read only: ``GET /copilot/chain`` (Tradier through the options feed),
 * asked again every 15 s while the tab is open and visible in the regular session, never outside it. The price line
 * moves with the desk's shared ticker (``useDeskTicks``). Tapping a contract opens a small row: Check it (Check a call,
 * pre-filled), Plan it (the plan flow) and Put on ticket (a saved plan's ticket, copy to Robinhood). Nothing here
 * places, sends or stages an order. Contracts on the desk's unusual-options list (``DeskUnusual``) carry a small mark; a
 * Feed row picked there (``focus``) opens here on its expiry with the contract selected, the strike window widened to it.
 * Make it a spread turns a picked contract into the long leg of a same-expiry vertical: the next contract tapped on the
 * same side is the leg sold, and the row shows the net debit or credit at the mid and the natural price, the most it can
 * lose and make, and Plan it / Put on ticket for the spread as one (``lib/spreadTicket.ts``).
 * In roll mode (``roll``, inside the roll ticket ``DeskRoll``) a tapped contract offers only Roll to this.
 * Above the strikes, the shown expiry's walls in one line (the Charts strike ladder's read, ``lib/deskWalls.ts``, once a
 * minute), with the wall and max-pain strikes marked; a read that is not current is grey with its time.
 */

export type ChainSide = "call" | "put";
type Cell = {
  symbol: string; bid: number | null; ask: number | null; mark: number | null; last: number | null; spread: number | null;
  spread_pct: number | null; wide: boolean; spread_note: string | null; volume: number | null; open_interest: number | null;
  delta: number | null; iv: number | null; quoted_at: number | null; state: "ok" | "stale" | "missing"; multiplier: number;
  held: number | null; planned: boolean;
};
type Row = { strike: number; atm: boolean; levels: string[]; call: Cell | null; put: Cell | null };
/** ``earnings``: the expiry lives through the next report (on or after its date); absent from an older backend. */
type Expiry = { date: string; days: number; kind: "0dte" | "weekly" | "monthly"; held: boolean; earnings?: boolean };
export type ChainReply = {
  symbol: string; state: "ok" | "none" | "unavailable"; session: "open" | "closed"; poll_seconds: number | null; expiries: Expiry[];
  expiration: string | null; spot: number | null; spot_at: number | null; spot_issue: string | null; atm_strike: number | null;
  fetched_at: number | null; age_s: number | null; stale: boolean; message: string | null; rows: Row[];
  levels: { role: string; price: number; strike: number | null }[]; simulated: boolean; centred_on?: "price" | "parity";
  /** The next earnings from the cache (dates only), or null when none is known. */
  earnings?: { date: string; status: string | null } | null;
};
/** A contract he picked; with ``short`` it is the long leg of a vertical that sells ``short`` (same side and expiry). */
export type ChainPick = { symbol: string; expiry: string; strike: number; side: ChainSide; short?: number };

const RETRY_MS = [5_000, 15_000, 30_000, 60_000];
const CLOSED_RECHECK_MS = 60_000; // outside the session: a quiet look each minute (the server keeps its read five minutes)
const STALE_AFTER_S = 45; // the server's CHAIN_STALE_S: a chain whose last good read is older is greyed

/** The chain for ``symbol`` at ``expiry`` (the nearest when null), asked again on the server's cadence while ``on`` and
 * the page is visible; the last good read stays on screen through a failed one, with when it failed. */
export function useDeskChain(symbol: string | null, expiry: string | null, on: boolean, strike: number | null = null) {
  const [data, setData] = useState<ChainReply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedAt, setFailedAt] = useState<number | null>(null);
  useEffect(() => {
    setData(was => (was && was.symbol === symbol ? was : null)); // eslint-disable-line react-hooks/set-state-in-effect -- a new ticker drops the old chain
    setError(null); setFailedAt(null);
    if (!on || !symbol) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let failures = 0;
    let cadence: number | null = null;
    let gone = false;
    let loaded = false;
    let skipped = false; // a load the hidden page skipped: the page showing again makes it
    const schedule = (ms: number | null) => {
      if (timer) clearTimeout(timer);
      timer = ms !== null && !gone ? setTimeout(load, ms) : null;
    };
    const load = async () => {
      if (document.visibilityState === "hidden") { skipped = true; return; } // picked up again when the page shows
      skipped = false;
      controller?.abort();
      controller = new AbortController();
      try {
        const query = new URLSearchParams({ symbol, ...(expiry ? { expiration: expiry } : {}), ...(strike !== null ? { strike: String(strike) } : {}) });
        const response = await fetch(apiUrl(`/copilot/chain?${query}`), { cache: "no-store", signal: controller.signal });
        const body = await response.json().catch(() => null); // always read the body: an unread one never settles
        if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `The chain could not be read (${response.status}).`);
        if (gone) return;
        failures = 0;
        loaded = true;
        cadence = (body as ChainReply).poll_seconds;
        setData(body as ChainReply); setError(null); setFailedAt(null);
        schedule(cadence ? cadence * 1000 : (body as ChainReply).simulated ? null : CLOSED_RECHECK_MS);
      } catch (e) {
        if (gone || controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : "The chain could not be read.");
        setFailedAt(Date.now() / 1000);
        schedule(RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]);
      }
    };
    const onShow = () => { if (document.visibilityState === "visible" && (skipped || cadence || failures || !loaded)) load(); };
    load();
    document.addEventListener("visibilitychange", onShow);
    return () => { gone = true; controller?.abort(); if (timer) clearTimeout(timer); document.removeEventListener("visibilitychange", onShow); };
  }, [symbol, expiry, on, strike]);
  return { data, error, failedAt };
}

const clock = (epoch: number | null | undefined, seconds = false) => epoch
  ? new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}) })
  : "an unknown time";
const money = (n: number | null | undefined) => n == null ? "—" : n.toFixed(2);
const count = (n: number | null | undefined) => n == null ? "—" : n >= 10_000 ? `${(n / 1000).toFixed(0)}k` : n.toLocaleString("en-US");
const delta = (n: number | null | undefined) => n == null ? "—" : n.toFixed(2).replace(/^(-?)0\./, "$1.");
/** A bid or ask: a contract with no market shows a dash, never 0.00. */
const quote = (c: Cell, n: number | null) => c.state === "missing" && !n ? "—" : money(n);
const pct = (n: number | null | undefined) => n == null ? "—" : `${n.toFixed(0)}%`;
const strikeText = (n: number) => Number.isInteger(n) ? String(n) : String(+n.toFixed(2));
const kindWord = (side: ChainSide) => side === "call" ? "Call" : "Put";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const shortDate = (iso: string) => { const [y, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}/${y.slice(2)}`; };
const chipDate = (e: Expiry) => { const [, m, d] = e.date.split("-"); return `${MONTHS[Number(m) - 1]} ${Number(d)}`; };
/** As Robinhood names an option: "NBIS $105 Call 11/14/26". */
export const contractLabel = (p: ChainPick) => `${p.symbol} $${strikeText(p.strike)} ${kindWord(p.side)} ${shortDate(p.expiry)}`;
/** As a Discord call reads, for Check a call: "NBIS 11/14 105C". */
export const callText = (p: ChainPick) => { const [, m, d] = p.expiry.split("-"); return `${p.symbol} ${Number(m)}/${Number(d)} ${strikeText(p.strike)}${p.side === "call" ? "C" : "P"}`; };

type Column = { key: string; label: string; title: string; show(c: Cell): string };
const COL: Record<string, Column> = {
  bid: { key: "bid", label: "Bid", title: "Bid", show: c => quote(c, c.bid) },
  ask: { key: "ask", label: "Ask", title: "Ask", show: c => quote(c, c.ask) },
  mark: { key: "mark", label: "Mark", title: "Mark: the middle of bid and ask", show: c => money(c.mark) },
  spread: { key: "spread", label: "Spr", title: "Spread: ask minus bid", show: c => money(c.spread) },
  delta: { key: "delta", label: "Δ", title: "Delta", show: c => delta(c.delta) },
  iv: { key: "iv", label: "IV", title: "Implied volatility", show: c => pct(c.iv) },
  volume: { key: "volume", label: "Vol", title: "Volume today", show: c => count(c.volume) },
  oi: { key: "oi", label: "OI", title: "Open interest", show: c => count(c.open_interest) },
};
const FULL = ["bid", "ask", "mark", "spread", "delta", "iv", "volume", "oi"].map(k => COL[k]);
const COMPACT = ["bid", "ask", "mark", "delta", "oi"].map(k => COL[k]);

/** The tab's layout from its own width: calls and puts side by side when there is room, else one side with a toggle. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const observer = new ResizeObserver(entries => setWidth(entries[0].contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** The saved plan whose ticket a contract can go on: the newest armed long-call (or long-put) plan in this ticker. */
export function ticketPlanFor(plans: TicketPlan[] | null, symbol: string, side: ChainSide): TicketPlan | null {
  return (plans ?? []).find(p => p.symbol === symbol && p.option_type === side) ?? null;
}

/** The saved plan a spread's ticket opens on: the newest armed plan in this ticker on the spread's own direction (a
 *  bullish spread on a long-call plan, a bearish one on a long-put plan). */
export function spreadPlanFor(plans: TicketPlan[] | null, symbol: string, bullish: boolean): TicketPlan | null {
  return ticketPlanFor(plans, symbol, bullish ? "call" : "put");
}

/** The roll ticket's pick (``DeskRoll``): the contract held, and where the contract to roll to goes. */
export type ChainRoll = { side: ChainSide; strike: number; expiry: string; onPick(pick: ChainPick): void };

export default function DeskChain({ symbol, plans, onCheck, onPlan, onTicket, unusual = [], focus = null, roll = null }: {
  symbol: string | null; plans: TicketPlan[] | null;
  onCheck(text: string): void; onPlan(pick: ChainPick, line: string): void; onTicket(investigationId: string, pick: ChainPick): void;
  unusual?: UnusualRow[]; focus?: { pick: ChainPick; n: number } | null;
  /** Roll mode, inside the roll ticket: opens on the held contract's expiry and side, and a tapped contract offers
   *  "Roll to this" instead of the usual actions. */
  roll?: ChainRoll | null;
}) {
  // The expiry he picked belongs to its ticker: a new ticker starts at its nearest, with no extra read of the old date.
  // A Feed pick seeds the first read, so the tab never reads the nearest expiry first.
  const seeded = focus && focus.pick.symbol === symbol ? focus.pick : null;
  const [chosen, setChosen] = useState<{ symbol: string | null; date: string } | null>(seeded ? { symbol, date: seeded.expiry } : roll ? { symbol, date: roll.expiry } : null);
  const expiry = chosen && chosen.symbol === symbol ? chosen.date : null;
  const setExpiry = (date: string) => setChosen({ symbol, date });
  const [side, setSide] = useState<ChainSide>(seeded?.side ?? roll?.side ?? "call");
  const [picked, setPicked] = useState<ChainPick | null>(seeded);
  const [spreadFrom, setSpreadFrom] = useState<ChainPick | null>(null); // Make it a spread: the long leg, waiting for the leg sold
  // A Feed row's contract: its expiry, selected, on the side shown, its strike inside the window.
  useEffect(() => {
    if (!focus || focus.pick.symbol !== symbol) return;
    setChosen({ symbol, date: focus.pick.expiry }); // eslint-disable-line react-hooks/set-state-in-effect -- a pick from the Feed
    setPicked(focus.pick);
    setSide(focus.pick.side);
  }, [focus?.n]); // eslint-disable-line react-hooks/exhaustive-deps -- once per pick
  const focusStrike = focus && focus.pick.symbol === symbol && focus.pick.expiry === expiry ? focus.pick.strike : null;
  const { data, error, failedAt } = useDeskChain(symbol, expiry, true, focusStrike);
  // The shown expiry's walls; the nearest asks as the desk chart does, so the two share one read a minute.
  const chainOk = data && data.symbol === symbol && data.state === "ok" && data.expiration ? data : null;
  const walls = useDeskWalls(chainOk ? symbol : null, chainOk && chainOk.expiration !== chainOk.expiries[0]?.date ? chainOk.expiration : null);
  const scrolled = useRef<number | null>(null);
  const ticks = useDeskTicks(symbol ? [symbol] : []);
  const live = tickFor(ticks, symbol);
  const { ref, width } = useWidth();
  // Bring a Feed pick's row into view once its expiry has loaded.
  useEffect(() => {
    if (!focus || scrolled.current === focus.n || !data || data.symbol !== symbol || data.expiration !== focus.pick.expiry) return;
    const row = ref.current?.querySelector(`[data-strike="${focus.pick.strike}"]`);
    if (row) { scrolled.current = focus.n; row.scrollIntoView({ block: "nearest" }); }
  }, [focus, data, symbol, ref]);
  const both = width >= 720;
  const cols = both ? (width >= 1040 ? FULL : COMPACT) : (width >= 520 ? FULL : COMPACT);
  const [nowS, setNowS] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = setInterval(() => setNowS(Date.now() / 1000), 5_000); return () => clearInterval(timer); }, []);

  if (!symbol) return <p data-testid="desk-chain" className="text-sm text-muted-foreground">Pick a ticker in your book or Watching list to see its option chain.</p>;
  const shown = data && data.symbol === symbol ? data : null;
  if (!shown) {
    return (
      <div data-testid="desk-chain" ref={ref}>
        <p className="text-sm text-muted-foreground">{error ? error : `Reading the ${symbol} option chain…`}</p>
      </div>
    );
  }
  const price = live?.last ?? shown.spot;
  const readAge = shown.fetched_at ? nowS - shown.fetched_at : null;
  // Stale: the server says so, or no good read has landed for a while in the session (a failing refresh).
  const stale = !shown.simulated && shown.session === "open" && (shown.stale || (readAge !== null && readAge > STALE_AFTER_S));
  const sides: ChainSide[] = both ? ["call", "put"] : [side];
  const selected = picked && picked.symbol === symbol && picked.expiry === shown.expiration ? picked : null;
  const long = spreadFrom && spreadFrom.symbol === symbol && spreadFrom.expiry === shown.expiration ? spreadFrom : null;
  // A tap while a spread is being made: the same side, another strike, is the leg sold; anything else starts over.
  const pick = (side: ChainSide, strike: number) => {
    const next = { symbol, expiry: shown.expiration!, strike, side };
    if (long && side === long.side && strike !== long.strike) { setPicked(next); return; }
    setSpreadFrom(null); setPicked(next);
  };
  const isChosen = (side: ChainSide, strike: number) => (selected?.side === side && selected.strike === strike) || (long?.side === side && long.strike === strike);
  const cellAt = (side: ChainSide, strike: number) => shown.rows.find(r => r.strike === strike)?.[side] ?? null;
  const lineAfter = price != null ? lineIndex(shown.rows, price) : null;
  const span = 1 + cols.length * sides.length;
  const marks = new Map(unusual.filter(u => u.symbol === symbol && u.expiration === shown.expiration).map(u => [`${u.side}:${u.strike}`, u]));
  // This expiry's walls; an answer with no expiry (nothing to read, or a ticker not followed) speaks for any.
  const wallsHere = walls.data && walls.data.symbol === symbol && (walls.data.expiration === shown.expiration || !walls.data.expiration) ? walls.data : null;
  const strikeWalls = wallStrikes(wallsHere && wallsHere.state === "ready" && !walls.failed ? wallsHere : null);

  return (
    <div data-testid="desk-chain" ref={ref} className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-semibold">{symbol} options</span>
        {price != null && <span data-testid="chain-price" className={cn("text-sm tabular-nums", live?.stale && "text-muted-foreground")}>{price.toFixed(2)}</span>}
        <QuoteAge reply={shown} stale={stale} failedAt={failedAt} error={error} />
      </div>
      <ExpiryPicker expiries={shown.expiries} chosen={shown.expiration} report={shown.earnings ?? null} onPick={e => { setExpiry(e); setPicked(null); setSpreadFrom(null); }} />
      {!both && shown.rows.length > 0 && (
        <span role="radiogroup" aria-label="Calls or puts" className="inline-flex overflow-hidden rounded-md border">
          {(["call", "put"] as const).map(s => (
            <button key={s} type="button" role="radio" aria-checked={side === s} onClick={() => setSide(s)}
              className={cn("min-h-11 px-4 text-xs sm:min-h-8", side === s ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
              {s === "call" ? "Calls" : "Puts"}
            </button>
          ))}
        </span>
      )}
      {shown.state === "ok" && <WallsRead walls={wallsHere} failed={walls.failed} />}
      {shown.state !== "ok" ? <p className="text-sm text-muted-foreground">{shown.message}</p> : (
        <div className={cn("overflow-x-auto rounded-lg border", stale && "opacity-60")} data-stale={stale ? "true" : undefined}>
          <table className="w-full border-collapse text-xs tabular-nums" aria-label={`${symbol} ${shown.expiration} option chain`}>
            <thead className="text-[11px] text-muted-foreground">
              {both && (
                <tr className="border-b">
                  <th colSpan={cols.length} className="px-1.5 py-1 text-center font-medium">Calls</th>
                  <th className="px-1.5 py-1" />
                  <th colSpan={cols.length} className="px-1.5 py-1 text-center font-medium">Puts</th>
                </tr>
              )}
              <tr className="border-b">
                {both && [...cols].reverse().map(c => <th key={`c-${c.key}`} title={c.title} className="px-1.5 py-1 text-right font-normal">{c.label}</th>)}
                <th className="px-1.5 py-1 text-center font-medium">Strike</th>
                {cols.map(c => <th key={`p-${c.key}`} title={c.title} className="px-1.5 py-1 text-right font-normal">{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {shown.rows.map((row, i) => (
                <Fragment key={row.strike}>
                  {lineAfter === i && <PriceLine span={span} symbol={symbol} price={price!} stale={!!live?.stale} />}
                  <tr className={cn("border-b last:border-b-0", row.atm && "bg-sky-400/5")} data-strike={row.strike}>
                    {both && <Cells cell={row.call} cols={[...cols].reverse()} itm={price != null && row.strike < price}
                      chosen={isChosen("call", row.strike)}
                      onPick={() => pick("call", row.strike)} side="call" strike={row.strike} />}
                    <StrikeCell row={row} sides={sides} marks={marks} walls={strikeWalls.get(row.strike)} />
                    {sides.slice(both ? 1 : 0).map(s => (
                      <Cells key={s} cell={row[s]} cols={cols} itm={price != null && (s === "call" ? row.strike < price : row.strike > price)}
                        chosen={isChosen(s, row.strike)}
                        onPick={() => pick(s, row.strike)} side={s} strike={row.strike} />
                    ))}
                  </tr>
                  {selected && selected.strike === row.strike && sides.includes(selected.side) && (
                    <tr><td colSpan={span} className="border-b bg-muted/30 p-0">
                      {roll ? <RollPick pick={selected} cell={row[selected.side]} roll={roll} onClose={() => setPicked(null)} />
                        : long && selected.side === long.side && selected.strike !== long.strike
                        ? <SpreadActions long={long} short={selected} longCell={cellAt(long.side, long.strike)} shortCell={row[selected.side]} plans={plans}
                            spot={price ?? null} onPlan={onPlan} onTicket={onTicket} onBack={() => { setPicked(long); setSpreadFrom(null); }} onClose={() => { setPicked(null); setSpreadFrom(null); }} />
                        : <Actions pick={selected} cell={row[selected.side]} plans={plans} onCheck={onCheck} onPlan={onPlan} onTicket={onTicket}
                            building={!!long} onSpread={() => setSpreadFrom(selected)} onBack={() => setSpreadFrom(null)} onClose={() => { setPicked(null); setSpreadFrom(null); }} />}
                    </td></tr>
                  )}
                </Fragment>
              ))}
              {lineAfter === shown.rows.length && <PriceLine span={span} symbol={symbol} price={price!} stale={!!live?.stale} />}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        {shown.centred_on === "parity" ? "No current price: centred where calls and puts cost the same. " : ""}
        Held contracts and your saved plans&apos; contracts and levels are marked. {roll ? `Tap the ${roll.side} to roll to; other expiries are in the dates above.` : "Tap a contract to check it, plan it or put it on a ticket;"} nothing is sent from here.
      </p>
    </div>
  );
}

/** The row the price line sits before (rows.length: after the last). */
function lineIndex(rows: Row[], price: number): number | null {
  if (!rows.length) return null;
  const at = rows.findIndex(r => r.strike > price);
  return at === -1 ? rows.length : at;
}

function PriceLine({ span, symbol, price, stale }: { span: number; symbol: string; price: number; stale: boolean }) {
  return (
    <tr data-testid="chain-price-line" aria-label={`${symbol} at ${price.toFixed(2)}`}>
      <td colSpan={span} className="p-0">
        <div className="flex items-center gap-2">
          <div className={cn("h-px flex-1", stale ? "bg-muted-foreground/40" : "bg-sky-400/70")} />
          <span className={cn("rounded px-1.5 text-[11px] font-medium tabular-nums", stale ? "text-muted-foreground" : "bg-sky-400/15 text-sky-300")}>{symbol} {price.toFixed(2)}</span>
          <div className={cn("h-px flex-1", stale ? "bg-muted-foreground/40" : "bg-sky-400/70")} />
        </div>
      </td>
    </tr>
  );
}

/** The strikes the walls name (put wall, call wall, max pain), each with its names and what they mean. The gamma flip is a
 * price between strikes, so it stays in the read line. */
function wallStrikes(walls: DeskWalls | null): Map<number, { name: string; hint: string }[]> {
  const out = new Map<number, { name: string; hint: string }[]>();
  for (const level of walls?.levels ?? []) {
    if (level.kind === "gamma_flip") continue;
    out.set(level.price, [...(out.get(level.price) ?? []), { name: level.name.toLowerCase(), hint: level.hint }]);
  }
  return out;
}

/** The shown expiry's walls in one line: current, or grey with its time and why it is not. */
function WallsRead({ walls, failed }: { walls: DeskWalls | null; failed: string | null }) {
  if (!walls && !failed) return <p data-testid="chain-walls" data-state="loading" className="text-[11px] text-muted-foreground">Walls: reading…</p>;
  if (!walls || walls.state === "none") return failed ? <p data-testid="chain-walls" data-state="failed" className="text-[11px] text-muted-foreground">Walls unavailable: {failed}</p> : null;
  if (walls.state === "loading") return <p data-testid="chain-walls" data-state="loading" className="text-[11px] text-muted-foreground">Walls: {walls.message ?? "reading the chain…"}</p>;
  const current = walls.state === "ready" && !failed;
  const has = walls.levels.length > 0 || !!walls.expected_move;
  const when = walls.fetched_at ? `as of ${clock(walls.fetched_at)} ET, not current` : "not read";
  const why = failed ?? walls.message;
  return (
    <p data-testid="chain-walls" data-state={current ? "ready" : "stale"} title={walls.assumption ?? undefined}
      className={cn("text-xs tabular-nums", current ? "text-foreground/90" : "text-muted-foreground")}>
      {has ? wallsLine(walls) : "Walls unavailable"}
      <span className="text-[11px] text-muted-foreground">
        {current ? " · dealer side assumed" : ` · ${when}${why ? `: ${why}` : ""}`}
        {walls.simulated ? " · simulated" : ""}
      </span>
    </p>
  );
}

function StrikeCell({ row, sides, marks, walls = [] }: { row: Row; sides: ChainSide[]; marks: Map<string, UnusualRow>; walls?: { name: string; hint: string }[] }) {
  const held = sides.flatMap(s => row[s]?.held ? [`${row[s]!.held} held ${s}${row[s]!.held === 1 ? "" : "s"}`] : []);
  const planned = sides.some(s => row[s]?.planned);
  const odd = sides.flatMap(s => { const u = marks.get(`${s}:${row.strike}`); return u ? [`Unusual ${s}: volume ${u.volume.toLocaleString("en-US")} against open interest ${u.open_interest.toLocaleString("en-US")}${u.ratio === null ? "" : ` (${u.ratio}×)`}`] : []; });
  return (
    <td className={cn("whitespace-nowrap border-x px-1.5 py-1 text-center", row.atm && "font-semibold")}>
      <span>{strikeText(row.strike)}</span>
      {row.atm && <span className="ml-1 text-[10px] font-normal text-sky-300" title="At the money: the strike nearest the price">ATM</span>}
      {(held.length > 0 || planned || row.levels.length > 0 || odd.length > 0 || walls.length > 0) && (
        <span className="block text-[10px] font-normal leading-tight">
          {held.length > 0 && <span data-testid="chain-held" className="text-emerald-400" title={held.join(", ")}>held</span>}
          {planned && <span data-testid="chain-planned" className="ml-1 text-amber-300" title="The contract a saved plan names">plan</span>}
          {row.levels.map(l => <span key={l} data-testid="chain-level" className="ml-1 text-muted-foreground" title={`Your plan's ${l} price is at this strike`}>{l}</span>)}
          {odd.length > 0 && <span data-testid="chain-unusual" className="ml-1 text-orange-300" title={odd.join("; ")}>unusual</span>}
          {walls.map(w => <span key={w.name} data-testid="chain-wall" className="ml-1 text-violet-300" title={`${w.hint} Dealer side assumed.`}>{w.name}</span>)}
        </span>
      )}
    </td>
  );
}

function Cells({ cell, cols, itm, chosen, onPick, side, strike }: {
  cell: Cell | null; cols: Column[]; itm: boolean; chosen: boolean; onPick(): void; side: ChainSide; strike: number;
}) {
  if (!cell) return <>{cols.map(c => <td key={c.key} className="px-1.5 py-1 text-right text-muted-foreground/60">—</td>)}</>;
  const quiet = cell.state !== "ok";
  return (
    <>
      {cols.map((c, i) => (
        <td key={c.key} className={cn("p-0", itm && "bg-muted/40", chosen && "bg-sky-400/15", cell.held && "font-semibold")}>
          <button type="button" onClick={onPick} aria-label={i === 0 ? `${strikeText(strike)} ${side}` : undefined} tabIndex={i === 0 ? 0 : -1}
            aria-hidden={i === 0 ? undefined : true} aria-pressed={i === 0 ? chosen : undefined}
            title={cell.state === "stale" ? `Quote from ${clock(cell.quoted_at)}` : cell.state === "missing" ? "No usable bid and ask" : c.key === "mark" && cell.spread_note ? cell.spread_note : undefined}
            className={cn("block min-h-9 w-full px-1.5 py-1 text-right hover:bg-secondary", quiet && "text-muted-foreground",
              c.key === "mark" && cell.wide && cell.state === "ok" && "text-amber-300")}>
            {c.show(cell)}
          </button>
        </td>
      ))}
    </>
  );
}

function QuoteAge({ reply, stale, failedAt, error }: { reply: ChainReply; stale: boolean; failedAt: number | null; error: string | null }) {
  if (reply.simulated) return <span className="text-xs text-amber-300">Simulated quotes (sandbox fixture)</span>;
  const read = reply.fetched_at;
  if (reply.session === "closed") {
    return <span data-testid="chain-age" className="text-xs text-muted-foreground">Market closed · quotes as of {clock(read)} ET</span>;
  }
  if (stale) {
    return (
      <span data-testid="chain-age" data-stale="true" className="text-xs text-muted-foreground">
        Quotes {clock(read, true)} ET · not live{failedAt && error ? `: ${error}` : reply.message ? `: ${reply.message}` : ""}
      </span>
    );
  }
  return (
    <span data-testid="chain-age" className="text-xs text-muted-foreground">
      Quotes {clock(read, true)} ET
    </span>
  );
}

function ExpiryPicker({ expiries, chosen, report = null, onPick }: { expiries: Expiry[]; chosen: string | null;
  report?: ChainReply["earnings"]; onPick(date: string): void }) {
  const through = report ? ` · includes the ${shortDate(report.date)} earnings report (time of day not published)` : "";
  if (!expiries.length) return null;
  return (<>
    <div role="radiogroup" aria-label="Expiry" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
      {expiries.map(e => (
        <button key={e.date} type="button" role="radio" aria-checked={e.date === chosen} onClick={() => onPick(e.date)}
          title={`${e.date} · ${e.days === 0 ? "expires today" : `${e.days} day${e.days === 1 ? "" : "s"}`}${e.kind === "monthly" ? " · monthly" : ""}${e.held ? " · you hold contracts here" : ""}${e.earnings ? through : ""}`}
          className={cn("inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md border px-2.5 text-xs sm:min-h-8",
            e.date === chosen ? "border-foreground/70 bg-secondary font-medium text-foreground" : "text-muted-foreground hover:text-foreground")}>
          {e.kind === "0dte" ? "0DTE" : chipDate(e)}
          {e.kind !== "0dte" && <span className="text-[10px] text-muted-foreground">{e.days}d</span>}
          {e.kind === "monthly" && <span className="text-[10px] text-muted-foreground">M</span>}
          {e.held && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-label="held" />}
          {e.earnings && <span data-testid="chain-expiry-earnings" className="rounded border border-sky-300/40 px-0.5 text-[9px] leading-3 text-sky-200" aria-label="includes earnings">ER</span>}
        </button>
      ))}
    </div>
    {report && expiries.some(e => e.earnings) && (
      <p data-testid="chain-earnings-note" className="text-[11px] text-muted-foreground">
        <span className="text-sky-200">ER</span>: these expiries include the {shortDate(report.date)} earnings report{report.status === "estimated" ? " (date estimated)" : ""}; time of day not published.
      </p>
    )}
  </>);
}

function Actions({ pick, cell, plans, onCheck, onPlan, onTicket, onClose, building = false, onSpread, onBack }: {
  pick: ChainPick; cell: Cell | null; plans: TicketPlan[] | null;
  onCheck(text: string): void; onPlan(pick: ChainPick, line: string): void; onTicket(investigationId: string, pick: ChainPick): void; onClose(): void;
  /** Make it a spread was tapped on this contract: it is the long leg, waiting for the leg sold. */
  building?: boolean; onSpread(): void; onBack(): void;
}) {
  const label = contractLabel(pick);
  const plan = ticketPlanFor(plans, pick.symbol, pick.side);
  const priced = cell && cell.state === "ok" && cell.mark != null;
  const line = `${label}${priced ? ` (mark ${cell!.mark!.toFixed(2)}, from the chain)` : ""}. My entry trigger, invalidation and time stop:`;
  const button = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
  return (
    <div data-testid="chain-actions" className="space-y-2 px-3 py-2.5 font-sans">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-sm font-semibold">{label}</span>
        {cell && (
          <span className="text-xs text-muted-foreground">
            {cell.state === "missing" ? "No usable bid and ask right now."
              : <>Bid {quote(cell, cell.bid)} · Ask {quote(cell, cell.ask)} · Mark {money(cell.mark)} · Spread {money(cell.spread)}{cell.spread_pct != null ? ` (${cell.spread_pct}%)` : ""} · Vol {count(cell.volume)} · OI {count(cell.open_interest)} · Δ {delta(cell.delta)} · IV {pct(cell.iv)}</>}
            {cell.state === "stale" && <> · <span className="text-muted-foreground">quote from {clock(cell.quoted_at)}, not live</span></>}
            {cell.held ? <> · <span className="text-emerald-400">you hold {cell.held}</span></> : null}
          </span>
        )}
      </div>
      {cell?.wide && cell.spread_note && <p className="text-xs text-amber-300">{cell.spread_note}. A limit near the mark may not fill quickly.</p>}
      {building ? (
        <div data-testid="chain-spread-building" className="flex flex-wrap items-center gap-2">
          <p className="text-xs">Buy this one. Now tap the {pick.side} to <span className="font-semibold">sell</span> in the same expiry: a {pick.side === "call" ? "higher" : "lower"} strike makes a debit spread, a {pick.side === "call" ? "lower" : "higher"} one a credit spread.</p>
          <button type="button" onClick={onBack} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Back to one contract</button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={button} onClick={() => onCheck(callText(pick))}>Check it</button>
          <button type="button" className={button} onClick={() => onPlan(pick, line)}>Plan it</button>
          <button type="button" className={button} disabled={!plan} onClick={() => plan && onTicket(plan.investigation_id, pick)}>Put on ticket</button>
          <button type="button" className={button} onClick={onSpread}>Make it a spread</button>
          <PaperButton key={label} order={{ instrument: "option", symbol: pick.symbol, option_type: pick.side, expiry: pick.expiry, strike: pick.strike }} label="Paper" />
          <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Close</button>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        {plan ? `Put on ticket opens your saved ${pick.symbol} plan's ticket with this contract, to copy into Robinhood. Nothing is sent from here.`
          : `A ticket opens from a saved plan: there is no armed ${pick.symbol} ${pick.side} plan yet, so Plan it first.`}
      </p>
    </div>
  );
}

/** Roll mode's row under a tapped contract: its quote, and Roll to this (a contract of the held side other than the one
 *  held), else why not. */
function RollPick({ pick, cell, roll, onClose }: { pick: ChainPick; cell: Cell | null; roll: ChainRoll; onClose(): void }) {
  const same = pick.side === roll.side && pick.strike === roll.strike && pick.expiry === roll.expiry;
  const why = pick.side !== roll.side ? `A roll keeps the ${roll.side}: pick a ${roll.side}.` : same ? "This is the contract you hold: pick another strike or expiry." : null;
  const button = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
  return (
    <div data-testid="chain-roll-pick" className="space-y-2 px-3 py-2.5 font-sans">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-sm font-semibold">{contractLabel(pick)}</span>
        {cell && (
          <span className="text-xs text-muted-foreground">
            {cell.state === "missing" ? "No usable bid and ask right now."
              : <>Bid {quote(cell, cell.bid)} · Ask {quote(cell, cell.ask)} · Mark {money(cell.mark)} · Δ {delta(cell.delta)} · OI {count(cell.open_interest)}</>}
            {cell.state === "stale" && <> · quote from {clock(cell.quoted_at)}, not live</>}
          </span>
        )}
      </div>
      {why ? <p className="text-xs text-amber-300">{why}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} disabled={!!why} onClick={() => roll.onPick(pick)}>Roll to this</button>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Close</button>
      </div>
    </div>
  );
}

/** The row under a spread's leg sold: both legs' quotes, the net at the mid and the natural price, the width, and per
 *  spread at the mid the most it can lose and make and its break-even. A leg not quoted now gives no net number; a wide
 *  one gives a rough one. Plan it and Put on ticket carry the spread as one (both legs). */
function SpreadActions({ long, short, longCell, shortCell, plans, spot, onPlan, onTicket, onBack, onClose }: {
  long: ChainPick; short: ChainPick; longCell: Cell | null; shortCell: Cell | null; plans: TicketPlan[] | null; spot: number | null;
  onPlan(pick: ChainPick, line: string): void; onTicket(investigationId: string, pick: ChainPick): void; onBack(): void; onClose(): void;
}) {
  const kind = long.side;
  const label = spreadLabel(long.symbol, kind, long.strike, short.strike, long.expiry);
  const ok = (c: Cell | null) => !!c && c.state === "ok" && c.bid != null && c.ask != null;
  const net = ok(longCell) && ok(shortCell) ? spreadNet(kind, long.strike, short.strike, longCell!, shortCell!) : null;
  const width = Math.abs(short.strike - long.strike);
  const f = spreadFigures(kind, long.strike, short.strike, net && net.mid > 0 && net.mid < width ? net.mid : null, 1, longCell?.multiplier ?? 100, spot);
  const rough = [[long, longCell], [short, shortCell]].flatMap(([p, c]) => {
    const leg = `the $${strikeText((p as ChainPick).strike)} leg`, cell = c as Cell | null;
    return !cell || cell.state === "missing" ? [`${leg} has no usable quote`] : cell.state === "stale" ? [`${leg}'s quote is from ${clock(cell.quoted_at)}, not live`]
      : cell.wide ? [`${leg}'s market is wide`] : [];
  });
  const bullish = isBullish(kind, long.strike, short.strike);
  const plan = spreadPlanFor(plans, long.symbol, bullish);
  const pick: ChainPick = { ...long, short: short.strike };
  const words = spreadWords(long.symbol, kind, long.strike, short.strike, long.expiry);
  const line = `${label}${net && !rough.length ? ` (net ${f.type} ${net.mid.toFixed(2)} at the mid, from the chain)` : ""}. Contract: ${words}. My entry trigger, invalidation and time stop:`;
  const button = "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45 sm:min-h-8";
  const leg = (action: string, p: ChainPick, c: Cell | null) => (
    <span className={cn("block text-xs tabular-nums", !ok(c) || c!.state !== "ok" ? "text-muted-foreground/80" : "text-muted-foreground")}>
      <span className="font-medium text-foreground">{action}</span> {contractLabel(p)} · {!c || c.state === "missing" ? "no usable bid and ask"
        : <>Bid {quote(c, c.bid)} · Ask {quote(c, c.ask)}{c.state === "stale" ? ` · quote from ${clock(c.quoted_at)}, not live` : ""}</>}
    </span>
  );
  return (
    <div data-testid="chain-spread" data-spread={f.type} className="space-y-2 px-3 py-2.5 font-sans">
      <div className="space-y-0.5">
        <span className="font-mono text-sm font-semibold">{label}</span>
        {leg("Buy", long, longCell)}
        {leg("Sell", short, shortCell)}
      </div>
      <p data-testid="chain-spread-net" className="text-xs tabular-nums">
        {net && !rough.some(r => !r.endsWith("wide")) ? <>
          Net {f.type} {net.mid.toFixed(2)} at the mid · {net.natural > 0 ? `${net.natural.toFixed(2)} at the natural price` : `no ${f.type} at the natural price`} · width {strikeText(width)}
          {f.maxLoss !== null && f.maxGain !== null && <> · per spread at the mid: risk ${f.maxLoss.toFixed(0)} to make ${f.maxGain.toFixed(0)}, break-even {f.breakeven!.toFixed(2)}</>}
          {f.warning && <span className="text-amber-300"> · {f.warning}</span>}
        </> : <span className="text-muted-foreground">No net price: {rough[0] ?? "a leg has no quote"}. Width {strikeText(width)}.</span>}
        {rough.length > 0 && net && <span className="ml-1 rounded border border-amber-300/50 px-1 text-[10px] uppercase tracking-wide text-amber-300">rough</span>}
      </p>
      {rough.length > 0 && <p className="text-xs text-amber-300">Rough: {rough.join("; ")}.</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={() => onPlan(pick, line)}>Plan it</button>
        <button type="button" className={button} disabled={!plan} onClick={() => plan && onTicket(plan.investigation_id, pick)}>Put on ticket</button>
        <PaperButton key={label} order={{ instrument: "spread", symbol: long.symbol, option_type: kind, expiry: long.expiry, long_strike: long.strike, short_strike: short.strike }} label="Paper" />
        <button type="button" onClick={onBack} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Back to one contract</button>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Close</button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {plan ? `Put on ticket opens your saved ${long.symbol} plan's ticket with this spread, both legs and the net price, to copy into Robinhood. Nothing is sent from here.`
          : `A ticket opens from a saved plan: there is no armed ${long.symbol} ${bullish ? "long (call)" : "short (put)"} plan for this ${bullish ? "bullish" : "bearish"} spread yet, so Plan it first.`}
      </p>
    </div>
  );
}
