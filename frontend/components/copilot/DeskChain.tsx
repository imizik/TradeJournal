"use client";

import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import { tickFor, useDeskTicks } from "@/lib/deskTicks";
import type { TicketPlan } from "@/components/copilot/DeskTicket";
import type { UnusualRow } from "@/components/copilot/DeskUnusual";
import { cn } from "@/lib/utils";

/**
 * The desk's Chain tab (docs/copilot-lab.md § Chain): one expiry of the selected ticker's option chain around the price,
 * to pick a contract without opening Robinhood. Read only: ``GET /copilot/chain`` (Tradier through the options feed),
 * asked again every 15 s while the tab is open and visible in the regular session, never outside it. The price line
 * moves with the desk's shared ticker (``useDeskTicks``). Tapping a contract opens a small row: Check it (Check a call,
 * pre-filled), Plan it (the plan flow) and Put on ticket (a saved plan's ticket, copy to Robinhood). Nothing here
 * places, sends or stages an order. Contracts on the desk's unusual-options list (``DeskUnusual``) carry a small mark; a
 * Feed row picked there (``focus``) opens here on its expiry with the contract selected, the strike window widened to it.
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
export type ChainPick = { symbol: string; expiry: string; strike: number; side: ChainSide };

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

export default function DeskChain({ symbol, plans, onCheck, onPlan, onTicket, unusual = [], focus = null }: {
  symbol: string | null; plans: TicketPlan[] | null;
  onCheck(text: string): void; onPlan(pick: ChainPick, line: string): void; onTicket(investigationId: string, pick: ChainPick): void;
  unusual?: UnusualRow[]; focus?: { pick: ChainPick; n: number } | null;
}) {
  // The expiry he picked belongs to its ticker: a new ticker starts at its nearest, with no extra read of the old date.
  const [chosen, setChosen] = useState<{ symbol: string | null; date: string } | null>(null);
  const expiry = chosen && chosen.symbol === symbol ? chosen.date : null;
  const setExpiry = (date: string) => setChosen({ symbol, date });
  const [side, setSide] = useState<ChainSide>("call");
  const [picked, setPicked] = useState<ChainPick | null>(null);
  // A Feed row's contract: its expiry, selected, on the side shown, its strike inside the window.
  useEffect(() => {
    if (!focus || focus.pick.symbol !== symbol) return;
    setChosen({ symbol, date: focus.pick.expiry }); // eslint-disable-line react-hooks/set-state-in-effect -- a pick from the Feed
    setPicked(focus.pick);
    setSide(focus.pick.side);
  }, [focus?.n]); // eslint-disable-line react-hooks/exhaustive-deps -- once per pick
  const focusStrike = focus && focus.pick.symbol === symbol && focus.pick.expiry === expiry ? focus.pick.strike : null;
  const { data, error, failedAt } = useDeskChain(symbol, expiry, true, focusStrike);
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
  const lineAfter = price != null ? lineIndex(shown.rows, price) : null;
  const span = 1 + cols.length * sides.length;
  const marks = new Map(unusual.filter(u => u.symbol === symbol && u.expiration === shown.expiration).map(u => [`${u.side}:${u.strike}`, u]));

  return (
    <div data-testid="desk-chain" ref={ref} className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-semibold">{symbol} options</span>
        {price != null && <span data-testid="chain-price" className={cn("text-sm tabular-nums", live?.stale && "text-muted-foreground")}>{price.toFixed(2)}</span>}
        <QuoteAge reply={shown} stale={stale} failedAt={failedAt} error={error} />
      </div>
      <ExpiryPicker expiries={shown.expiries} chosen={shown.expiration} report={shown.earnings ?? null} onPick={e => { setExpiry(e); setPicked(null); }} />
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
                      chosen={selected?.side === "call" && selected.strike === row.strike}
                      onPick={() => setPicked({ symbol, expiry: shown.expiration!, strike: row.strike, side: "call" })} side="call" strike={row.strike} />}
                    <StrikeCell row={row} sides={sides} marks={marks} />
                    {sides.slice(both ? 1 : 0).map(s => (
                      <Cells key={s} cell={row[s]} cols={cols} itm={price != null && (s === "call" ? row.strike < price : row.strike > price)}
                        chosen={selected?.side === s && selected.strike === row.strike}
                        onPick={() => setPicked({ symbol, expiry: shown.expiration!, strike: row.strike, side: s })} side={s} strike={row.strike} />
                    ))}
                  </tr>
                  {selected && selected.strike === row.strike && sides.includes(selected.side) && (
                    <tr><td colSpan={span} className="border-b bg-muted/30 p-0">
                      <Actions pick={selected} cell={row[selected.side]} plans={plans} onCheck={onCheck} onPlan={onPlan} onTicket={onTicket} onClose={() => setPicked(null)} />
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
        Held contracts and your saved plans&apos; contracts and levels are marked. Tap a contract to check it, plan it or put it on a ticket; nothing is sent from here.
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

function StrikeCell({ row, sides, marks }: { row: Row; sides: ChainSide[]; marks: Map<string, UnusualRow> }) {
  const held = sides.flatMap(s => row[s]?.held ? [`${row[s]!.held} held ${s}${row[s]!.held === 1 ? "" : "s"}`] : []);
  const planned = sides.some(s => row[s]?.planned);
  const odd = sides.flatMap(s => { const u = marks.get(`${s}:${row.strike}`); return u ? [`Unusual ${s}: volume ${u.volume.toLocaleString("en-US")} against open interest ${u.open_interest.toLocaleString("en-US")}${u.ratio === null ? "" : ` (${u.ratio}×)`}`] : []; });
  return (
    <td className={cn("whitespace-nowrap border-x px-1.5 py-1 text-center", row.atm && "font-semibold")}>
      <span>{strikeText(row.strike)}</span>
      {row.atm && <span className="ml-1 text-[10px] font-normal text-sky-300" title="At the money: the strike nearest the price">ATM</span>}
      {(held.length > 0 || planned || row.levels.length > 0 || odd.length > 0) && (
        <span className="block text-[10px] font-normal leading-tight">
          {held.length > 0 && <span data-testid="chain-held" className="text-emerald-400" title={held.join(", ")}>held</span>}
          {planned && <span data-testid="chain-planned" className="ml-1 text-amber-300" title="The contract a saved plan names">plan</span>}
          {row.levels.map(l => <span key={l} data-testid="chain-level" className="ml-1 text-muted-foreground" title={`Your plan's ${l} price is at this strike`}>{l}</span>)}
          {odd.length > 0 && <span data-testid="chain-unusual" className="ml-1 text-orange-300" title={odd.join("; ")}>unusual</span>}
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

function Actions({ pick, cell, plans, onCheck, onPlan, onTicket, onClose }: {
  pick: ChainPick; cell: Cell | null; plans: TicketPlan[] | null;
  onCheck(text: string): void; onPlan(pick: ChainPick, line: string): void; onTicket(investigationId: string, pick: ChainPick): void; onClose(): void;
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
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={() => onCheck(callText(pick))}>Check it</button>
        <button type="button" className={button} onClick={() => onPlan(pick, line)}>Plan it</button>
        <button type="button" className={button} disabled={!plan} onClick={() => plan && onTicket(plan.investigation_id, pick)}>Put on ticket</button>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center rounded-md px-3 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Close</button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {plan ? `Put on ticket opens your saved ${pick.symbol} plan's ticket with this contract, to copy into Robinhood. Nothing is sent from here.`
          : `A ticket opens from a saved plan: there is no armed ${pick.symbol} ${pick.side} plan yet, so Plan it first.`}
      </p>
    </div>
  );
}
