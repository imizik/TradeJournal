"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { MoreHorizontal, Plus } from "lucide-react";
import { useKeptState } from "@/components/copilot/DeskMemory";
import { LABEL, Spark, tone } from "@/components/copilot/Cockpit";
import { getWatchLists, getWatching, importWatchLists, signedPct, stopWatching, watchSymbol,
  type DeskEvents, type DeskSparks, type DeskWatching, type WatchLists } from "@/lib/desk";
import { staleSince, tickFor, useDeskTicks, type DeskTicks } from "@/lib/deskTicks";
import { Flash, PricesAsOf } from "@/components/copilot/Ticks";
import { cn } from "@/lib/utils";
import { EarningsTag } from "@/components/copilot/EarningsTag";

/** Rows shown before "N more". */
const SHOWN = 8;
/** A level this close (percent of the price) counts as near: the row sorts first. */
const NEAR_PCT = 3;
const REFRESH_MS = 60_000;
const ROLE = { entry: "entry", invalidation: "stop" } as const;

/** ``GET /copilot/desk/watching``, read on open, once a minute while the page shows and after ``refresh`` changes (a
 * ticker followed or hidden). The last good read is kept for the desk's remount. */
export function useWatching(on: boolean, refresh: number): { data: DeskWatching | null; failed: boolean; set(next: DeskWatching): void } {
  const [data, setData] = useKeptState<DeskWatching | null>("desk.watching", null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!on) return;
    let controller = new AbortController();
    const read = () => {
      controller.abort();
      controller = new AbortController();
      getWatching(controller.signal).then(next => { setData(next); setFailed(next.state !== "ok"); })
        .catch(error => { if ((error as Error).name !== "AbortError") setFailed(true); });
    };
    read();
    const timer = setInterval(() => { if (document.visibilityState === "visible") read(); }, REFRESH_MS);
    return () => { controller.abort(); clearInterval(timer); };
  }, [on, refresh, setData]);
  return { data, failed, set: setData };
}

type Row = { symbol: string; last: number | null; change: number | null; points: number[] | undefined; stale: boolean;
  level: { price: number; label: string; pct: number } | null; setup: number | null | undefined; near: boolean };

const clock = (epoch: number) => new Date(epoch * 1000).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Each watched name's facts: its price and change from the sparks read, the nearest armed level with the distance to
 * it, and today's Radar setup card. Near (a level within ``NEAR_PCT`` or a setup today) first, then today's biggest
 * moves; a name with no price yet last. */
export function watchRows(symbols: string[], data: DeskWatching | null, sparks: DeskSparks | null, ticks: DeskTicks | null = null): Row[] {
  const rows = symbols.map(symbol => {
    const spark = sparks?.rows[symbol];
    // The live price (in the session) when there is one; else the minute read's.
    const tick = ticks ? tickFor(ticks, symbol) : null;
    const last = tick?.last ?? spark?.last ?? (spark?.points.length ? spark.points[spark.points.length - 1] : null);
    const change = tick?.change_pct ?? spark?.change_pct ?? null;
    const points = spark?.points.length && tick && !tick.stale ? [...spark.points.slice(0, -1), tick.last] : spark?.points;
    let level: Row["level"] = null;
    if (last) {
      for (const one of data?.levels[symbol] ?? []) {
        const pct = (one.price - last) / last * 100;
        if (!level || Math.abs(pct) < Math.abs(level.pct)) level = { price: one.price, label: one.role ? ROLE[one.role] : "alert", pct };
      }
    }
    const setup = data?.setups[symbol] ? data.setups[symbol].at : undefined;
    return { symbol, last, change, points, stale: !!tick?.stale, level, setup,
      near: (level != null && Math.abs(level.pct) <= NEAR_PCT) || setup !== undefined };
  });
  return rows.sort((a, b) => Number(b.near) - Number(a.near) || Number(b.last != null) - Number(a.last != null)
    || Math.abs(b.change ?? 0) - Math.abs(a.change ?? 0) || a.symbol.localeCompare(b.symbol));
}

const CONNECTION: Record<string, string> = {
  off: "The Robinhood connection is off, so the import cannot read your lists. Add names here by hand.",
  signed_out: "Signed out of Robinhood, so the import cannot read your lists. Add names here by hand.",
  expired: "The Robinhood sign-in has expired, so the import cannot read your lists. Add names here by hand.",
};
const connectionWords = (state: string) => CONNECTION[state] ?? "Your Robinhood lists could not be read just now. Try again in a minute.";

/** Sync from Robinhood: his own lists by name and size, his custom lists ticked; the stocks and ETFs of the ones he
 * keeps ticked are added. Only reads Robinhood; nothing is written to his lists. */
function Import({ first, onDone, onClose }: { first: boolean; onDone(line: string, next: DeskWatching | undefined): void; onClose(): void }) {
  const [lists, setLists] = useState<WatchLists | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  useEffect(() => {
    getWatchLists().then(found => {
      setLists(found);
      setTicked(new Set(found.lists.filter(l => l.ticked).map(l => l.id)));
    }).catch(error => setSaid((error as Error).message));
  }, []);
  const bring = () => {
    setBusy(true);
    importWatchLists([...ticked]).then(done => {
      if (done.state !== "ok") setSaid(connectionWords(done.state));
      else onDone(done.line ?? "Done.", done.watching);
    }).catch(error => setSaid((error as Error).message)).finally(() => setBusy(false));
  };
  const message = said ?? (lists && lists.state !== "ok" ? connectionWords(lists.state) : lists && !lists.lists.length ? "No lists of your own on Robinhood to bring in." : null);
  return (
    <div data-testid="watch-import" className="border-t px-3 py-2 text-xs">
      <p className="mb-1.5 text-muted-foreground">{first ? "Import" : "Sync"} from Robinhood: the stocks and ETFs of the lists you tick. Crypto, futures and indexes are skipped; names you stopped watching here stay off. Nothing is changed on Robinhood.</p>
      {!lists && !said && <p className="text-muted-foreground">Reading your lists…</p>}
      {message && <p role="status" className="text-muted-foreground">{message}</p>}
      {lists?.state === "ok" && lists.lists.length > 0 && !said && (
        <>
          <ul aria-label="Your Robinhood lists" className="space-y-0.5">
            {lists.lists.map(list => (
              <li key={list.id}>
                <label className="flex min-h-11 items-center gap-2 sm:min-h-7">
                  <input type="checkbox" checked={ticked.has(list.id)} onChange={() => setTicked(prev => {
                    const next = new Set(prev);
                    if (!next.delete(list.id)) next.add(list.id);
                    return next;
                  })} />
                  {/* His list's own name and emoji: shown as data, as Robinhood holds them. */}
                  <span className="min-w-0 truncate text-foreground">{list.emoji ? `${list.emoji} ` : ""}{list.name}</span>
                  <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{list.count}</span>
                </label>
              </li>
            ))}
          </ul>
          {lists.not_offered > 0 && <p className="mt-1 text-muted-foreground">Robinhood&apos;s own lists and the options list are not offered.</p>}
        </>
      )}
      <div className="mt-1.5 flex gap-2">
        {lists?.state === "ok" && lists.lists.length > 0 && !said && (
          <button type="button" disabled={busy || !ticked.size} onClick={bring}
            className="inline-flex min-h-11 items-center rounded-md border px-2.5 text-foreground hover:bg-secondary disabled:opacity-50 sm:min-h-7">
            {busy ? "Reading…" : `Bring in ${ticked.size} list${ticked.size === 1 ? "" : "s"}`}
          </button>
        )}
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center px-1 text-muted-foreground hover:text-foreground sm:min-h-7">{said || message ? "Close" : "Cancel"}</button>
      </div>
    </div>
  );
}

/**
 * Watching: the names he watches and does not hold, under the book (docs/copilot-lab.md § The desk). The list is the
 * app's own watchlist (the Charts one); adding and removing here writes there and never to Robinhood. One compact row
 * each (price, change today, the book's sparkline, the nearest armed level or today's setup card), about eight shown and
 * the rest behind "N more"; a phone folds the section to one line until tapped. Selecting a row puts the ticker on the
 * centre's chart and the copilot, as a book row does; its menu offers Ask the copilot, Plan a trade, Open in Charts and
 * Stop watching. Facts only, no amber: nothing here suggests a trade.
 */
export default function Watching({ data, failed, sparks, held, selected, earnings = null, onSelect, onAsk, onPlan, onChange }: {
  data: DeskWatching | null; failed: boolean; sparks: DeskSparks | null; held: ReadonlySet<string>; selected: string | null;
  /** Earnings tags (``useDeskEvents``), by symbol. */
  earnings?: DeskEvents | null;
  onSelect(symbol: string): void; onAsk(symbol: string): void; onPlan(symbol: string): void; onChange(next: DeskWatching): void;
}) {
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [menu, setMenu] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const away = (event: MouseEvent) => { if (!menuRef.current?.contains(event.target as Node)) setMenu(null); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setMenu(null); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [menu]);

  const symbols = (data?.symbols ?? []).filter(s => !held.has(s)); // a name he holds is the book's row only
  const ticks = useDeskTicks(symbols);
  const rows = watchRows(symbols, data, sparks, ticks);
  const shown = all ? rows : rows.slice(0, SHOWN);
  const add = (event: FormEvent) => {
    event.preventDefault();
    const symbol = typed.trim().toUpperCase();
    if (!symbol) return;
    setBusy(true);
    setSaid(null);
    watchSymbol(symbol).then(next => {
      onChange(next);
      setTyped("");
      setAdding(false);
      setSaid(held.has(symbol) ? `${symbol} is in your book; it shows there.` : null);
    }).catch(error => setSaid((error as Error).message)).finally(() => setBusy(false));
  };
  const stop = (symbol: string) => {
    setMenu(null);
    setSaid(null);
    stopWatching(symbol).then(onChange).catch(() => setSaid(`${symbol}: not saved. Try again.`));
  };
  const first = !data?.imported_at;

  return (
    <section aria-label="Watching" data-testid="desk-watching" className="rounded-lg border bg-card">
      <div className="flex min-w-0 items-center gap-x-2 px-3 pb-1.5 pt-2.5 max-sm:py-0">
        {/* A phone: one line with the count until tapped. */}
        <button type="button" aria-expanded={phoneOpen} onClick={() => setPhoneOpen(open => !open)} data-testid="watching-toggle"
          className={cn(LABEL, "flex min-h-11 flex-1 items-center gap-1 text-left sm:hidden")}>
          Watching · <span className="tabular-nums">{symbols.length}</span> {phoneOpen ? "▴" : "▾"}
        </button>
        <h2 className={cn(LABEL, "hidden sm:block")}>Watching{symbols.length > 0 && <> · <span className="tabular-nums">{symbols.length}</span></>}</h2>
        <PricesAsOf at={staleSince(ticks, symbols)} />
        <span className={cn("ml-auto flex items-center gap-1", !phoneOpen && "max-sm:hidden")}>
          <button type="button" onClick={() => { setImporting(open => !open); setAdding(false); }} aria-expanded={importing}
            className="inline-flex min-h-11 items-center px-1 text-[11px] text-muted-foreground hover:text-foreground sm:min-h-6">
            {first ? "Import from Robinhood" : "Sync from Robinhood"}
          </button>
          <button type="button" onClick={() => { setAdding(open => !open); setImporting(false); setSaid(null); }} aria-expanded={adding} aria-label="Add a ticker to watch"
            className="inline-flex min-h-11 min-w-11 items-center justify-center gap-0.5 rounded text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-6 sm:min-w-0 sm:px-1">
            <Plus size={12} aria-hidden />Add
          </button>
        </span>
      </div>
      <div data-testid="watching-body" className={cn(!phoneOpen && "max-sm:hidden")}>
        {adding && (
          <form onSubmit={add} className="flex items-center gap-2 border-t px-3 py-1.5">
            <input autoFocus value={typed} onChange={event => setTyped(event.target.value.toUpperCase())} aria-label="Ticker to watch" placeholder="Ticker"
              maxLength={10} className="h-11 w-28 rounded-md border bg-background px-2 text-sm uppercase sm:h-7" />
            <button type="submit" disabled={busy || !typed.trim()} className="inline-flex min-h-11 items-center rounded-md border px-2.5 text-xs hover:bg-secondary disabled:opacity-50 sm:min-h-7">
              {busy ? "Checking…" : "Watch"}
            </button>
          </form>
        )}
        {importing && <Import first={first} onClose={() => setImporting(false)}
          onDone={(line, next) => { if (next) onChange(next); setImporting(false); setSaid(line); }} />}
        {said && <p role="status" data-testid="watching-said" className="border-t px-3 py-1.5 text-xs text-muted-foreground">{said}</p>}
        {failed && !data?.symbols.length ? <p className="border-t px-3 py-2 text-xs text-muted-foreground">Watching could not be read just now.</p>
          : !data ? <p className="border-t px-3 py-2 text-xs text-muted-foreground">Reading your watchlist…</p>
          : !rows.length ? <p className="border-t px-3 py-2 text-xs text-muted-foreground">No names watched{data.symbols.length ? " beyond your book" : ""}. Add a ticker or import your Robinhood lists.</p>
          : (
            <ul>
              {shown.map(row => {
                const on = row.symbol === selected;
                const report = earnings?.rows[row.symbol];
                return (
                  <li key={row.symbol} data-testid="watch-row" className={cn("relative flex items-stretch border-t", on && "bg-secondary shadow-[inset_2px_0_0_hsl(var(--foreground))]")}>
                    <button type="button" onClick={() => onSelect(row.symbol)} aria-pressed={on} aria-label={`${row.symbol}, watching`}
                      className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_48px_minmax(60px,auto)] items-center gap-2 py-1.5 pl-3 text-left hover:bg-secondary">
                      <span className="min-w-0 overflow-hidden">
                        <span className="block text-sm font-semibold text-foreground">{row.symbol}</span>
                        {(row.level || row.setup !== undefined || report) && (
                          <span data-testid="watch-meta" className="flex flex-wrap gap-x-1.5 text-[11px] text-muted-foreground [&>*]:whitespace-nowrap">
                            {report && earnings && <EarningsTag tag={report} day={earnings.today} />}
                            {row.level && <span className="tabular-nums">{row.level.label} {price(row.level.price)} · {Math.abs(row.level.pct).toFixed(1)}% away</span>}
                            {row.setup !== undefined && <span data-testid="watch-setup" className="rounded border px-1">Setup{row.setup ? ` ${clock(row.setup)}` : ""}</span>}
                          </span>
                        )}
                      </span>
                      <Spark points={row.points} label={`${row.symbol} today`} />
                      <span data-testid="watch-price" className={cn("whitespace-nowrap text-right text-sm tabular-nums", row.stale && "opacity-50")}>
                        <Flash value={row.last}>{row.last != null ? price(row.last) : "—"}</Flash>
                        <span className={cn("block text-[11px]", tone(row.change))}>{row.change != null ? signedPct(row.change, 2) : "—"}</span>
                      </span>
                    </button>
                    <button type="button" onClick={() => setMenu(open => open === row.symbol ? null : row.symbol)} aria-label={`${row.symbol}: more`} aria-haspopup="menu" aria-expanded={menu === row.symbol}
                      className="flex w-8 shrink-0 items-center justify-center text-muted-foreground/60 hover:bg-secondary hover:text-foreground max-sm:w-11">
                      <MoreHorizontal size={14} aria-hidden />
                    </button>
                    {menu === row.symbol && (
                      <div ref={menuRef} role="menu" aria-label={`${row.symbol} actions`}
                        className="absolute right-1 top-full z-20 mt-0.5 min-w-44 rounded-md border bg-popover p-1 text-xs shadow-lg">
                        <button type="button" role="menuitem" onClick={() => { setMenu(null); onAsk(row.symbol); }} className="flex min-h-11 w-full items-center rounded px-2 text-left hover:bg-secondary sm:min-h-8">Ask the copilot</button>
                        <button type="button" role="menuitem" onClick={() => { setMenu(null); onPlan(row.symbol); }} className="flex min-h-11 w-full items-center rounded px-2 text-left hover:bg-secondary sm:min-h-8">Plan a trade</button>
                        <Link role="menuitem" href={`/charts?symbol=${encodeURIComponent(row.symbol)}`} onClick={() => setMenu(null)} className="flex min-h-11 w-full items-center rounded px-2 hover:bg-secondary sm:min-h-8">Open in Charts</Link>
                        <button type="button" role="menuitem" onClick={() => stop(row.symbol)} className="flex min-h-11 w-full items-center rounded px-2 text-left text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">Stop watching</button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        {rows.length > SHOWN && (
          <button type="button" aria-expanded={all} onClick={() => setAll(open => !open)} data-testid="watching-more"
            className="flex min-h-11 w-full items-center gap-1 border-t px-3 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground sm:min-h-8">
            {all ? "Show fewer ▴" : <><span className="tabular-nums">{rows.length - SHOWN}</span> more ▾</>}
          </button>
        )}
      </div>
    </section>
  );
}
