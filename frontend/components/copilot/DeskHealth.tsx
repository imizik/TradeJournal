"use client";

/**
 * Is everything behind the desk live? (docs/copilot-lab.md § Data health) Said once: from 768 px the status line says
 * it and the top bar's dot shows only while a money source is behind; a phone keeps the dot. The dot: green alone
 * when every running source is live ("All live" is its name and tooltip), red naming it when a source that moves money
 * (``MONEY``: Robinhood, Prices, Fill emails) is stale, down or low, amber naming any other, grey alone when one cannot
 * be told. A tap opens the list: each source, its state and last good time in plain words; a tap on a source says what
 * it affects and, where one already exists, the fix. From 768 px the status line along the desk's bottom
 * (``DeskStatusLine``) shows the same rows as a dot and a name each, and opens the same list.
 *
 * The server's rows (``GET /copilot/desk/health``) ride the desk's minute request (``deskMinute``): one read shared by
 * the dot and the status line, no poll of its own. Level 2 is the Tape's own moomoo session, so its row comes from the
 * Tape (``reportLevel2``): "off" with no session, never an error.
 */

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { api } from "@/lib/api";
import { getHealth, type DeskHealth, type HealthRow, type HealthState } from "@/lib/desk";
import { everyDeskMinute } from "@/lib/deskMinute";
import { STALE_SECONDS, useHeldTicks, type DeskTicks } from "@/lib/deskTicks";
import { cn } from "@/lib/utils";

// --------------------------------------------------------------------------- Level 2, from the Tape

export type Level2Health = { running: boolean; failed: boolean; symbol: string | null; at: number | null };
const OFF: Level2Health = { running: false, failed: false, symbol: null, at: null };
let level2: Level2Health = OFF;
const level2Listeners = new Set<() => void>();

/** The Tape says what its depth session is doing (``null`` when it closes or unmounts). */
export function reportLevel2(next: Level2Health | null) {
  const value = next ?? OFF;
  if (value.running === level2.running && value.failed === level2.failed && value.symbol === level2.symbol && value.at === level2.at) return;
  level2 = value;
  for (const listener of level2Listeners) listener();
}
const subscribeLevel2 = (listener: () => void) => { level2Listeners.add(listener); return () => { level2Listeners.delete(listener); }; };

const LEVEL2_AFFECTS = "Level 2 and the Tape under the chart. It runs only while you have a Tape session open.";
export function level2Row(state: Level2Health): HealthRow {
  if (state.failed) return { id: "level2", name: "Level 2", state: "down", line: `Session stopped${state.symbol ? ` · ${state.symbol}` : ""}`, last_at: state.at, affects: LEVEL2_AFFECTS,
    fix: { kind: "text", text: "Open the Tape again to start a new session." } };
  if (state.running) return { id: "level2", name: "Level 2", state: "live", line: `Live${state.symbol ? ` · ${state.symbol}` : ""}`, last_at: state.at, affects: LEVEL2_AFFECTS, fix: null };
  return { id: "level2", name: "Level 2", state: "off", line: "Off · no Tape session open", last_at: null, affects: LEVEL2_AFFECTS, fix: null };
}

// --------------------------------------------------------------------------- the server's rows, one read for the desk

const BAD: HealthState[] = ["stale", "down", "low"];
/** Sources whose being behind leaves positions, fills or prices wrong: red, on the dot and the status line. The rest are amber. */
const MONEY = new Set(["robinhood", "prices", "gmail"]);
const SETTLE_MS = 8_000; // after an open or a return to the page: the desk's own first reads have landed by then

type HealthRead = { data: DeskHealth | null; failed: boolean };
const NOT_READ: HealthRead = { data: null, failed: false };
let health: HealthRead = NOT_READ;
const healthListeners = new Set<() => void>();
let stopReading: (() => void) | null = null;
let stopSoon: ReturnType<typeof setTimeout> | null = null;

function setHealth(next: HealthRead) {
  health = next;
  for (const listener of healthListeners) listener();
}

/** The read itself: once now, once more a few seconds after the desk opens or comes back into view, then on the minute. */
function startReading(): () => void {
  let controller = new AbortController();
  const read = () => {
    controller.abort();
    controller = new AbortController();
    getHealth(controller.signal).then(next => setHealth({ data: next, failed: false }))
      .catch(error => { if ((error as Error).name !== "AbortError") setHealth({ data: health.data, failed: true }); });
  };
  read();
  // Robinhood and prices are read because the desk asks: a few seconds after it opens or comes back into view, once
  // its own first reads have landed, ask again so a cold start never reads as "behind" for a minute.
  let again = window.setTimeout(read, SETTLE_MS);
  let hiddenAt: number | null = null;
  const seen = () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt !== null && Date.now() - hiddenAt > SETTLE_MS) { window.clearTimeout(again); again = window.setTimeout(read, SETTLE_MS); }
    hiddenAt = null;
  };
  document.addEventListener("visibilitychange", seen);
  const stop = everyDeskMinute(read);
  return () => { controller.abort(); stop(); window.clearTimeout(again); document.removeEventListener("visibilitychange", seen); };
}

/** The first piece that shows health starts the one read; the last one to go stops it. */
function subscribeHealth(listener: () => void) {
  healthListeners.add(listener);
  if (stopSoon) { clearTimeout(stopSoon); stopSoon = null; }
  if (!stopReading) stopReading = startReading();
  return () => {
    healthListeners.delete(listener);
    if (healthListeners.size) return;
    // A remount in the same moment (React's development double mount) keeps the read going rather than asking twice.
    stopSoon = setTimeout(() => {
      stopSoon = null;
      if (healthListeners.size) return;
      stopReading?.();
      stopReading = null;
      health = NOT_READ;
    }, 0);
  };
}

// --------------------------------------------------------------------------- the book's own Robinhood read

/** What the book's last read said of Robinhood (the thread list's ``robinhood``): its state and as-of. The two reads
 * land at different moments (the book's read starts Robinhood's refresh; the health read a few seconds later can see
 * it done), so on 2026-11-16 the status line's Robinhood was green beside a book that said "Robinhood stale". One rule
 * now: Robinhood is behind when either read says so, and the book's line and the status line both say it. */
export type BookLive = { state: string; as_of?: number | null } | null;
let bookLive: BookLive = null;
const bookListeners = new Set<() => void>();
export function reportBookLive(next: BookLive) {
  if (next?.state === bookLive?.state && (next?.as_of ?? null) === (bookLive?.as_of ?? null)) return;
  bookLive = next;
  for (const listener of bookListeners) listener();
}
const subscribeBook = (listener: () => void) => { bookListeners.add(listener); return () => { bookListeners.delete(listener); }; };
const BOOK_BEHIND: Record<string, { state: HealthState; word: string }> = {
  stale: { state: "stale", word: "stale" }, unavailable: { state: "down", word: "unavailable" },
  signed_out: { state: "down", word: "signed out" }, expired: { state: "down", word: "sign-in expired" },
};
/** The health read's Robinhood row, behind as well when the book's read says it is. */
export function agreeRobinhood(row: HealthRow, book: BookLive): HealthRow {
  const behind = book ? BOOK_BEHIND[book.state] : undefined;
  if (!behind || BAD.includes(row.state)) return row;
  const at = book?.as_of ?? null;
  return { ...row, state: behind.state, last_at: at, line: `The book says ${behind.word}${at ? ` · as of ${clock(at)}` : ""}` };
}

/** Every source behind the desk (Level 2, the Tape's own, after prices) and the summary, from the one shared read.
 * After a failed read the last rows are not given at all: an old "Live" is not known to be live now. */
export function useDeskHealth(): { rows: HealthRow[] | null; failed: boolean; said: ReturnType<typeof summary>; tape: Level2Health } {
  const read = useSyncExternalStore(subscribeHealth, () => health, () => NOT_READ);
  const tape = useSyncExternalStore(subscribeLevel2, () => level2, () => OFF);
  const book = useSyncExternalStore(subscribeBook, () => bookLive, () => null);
  const rows = read.data && !read.failed ? read.data.sources.flatMap(r => r.id === "prices" ? [r, level2Row(tape)]
    : r.id === "robinhood" ? [agreeRobinhood(r, book)] : [r]) : null;
  return { rows, failed: read.failed, said: summary(rows, read.failed), tape };
}

/** Robinhood's row when it is behind (the health read's, or the book's own word), else null: the book's line says the
 * same thing as the status line. */
export function useRobinhoodBehind(): HealthRow | null {
  const { rows } = useDeskHealth();
  const row = rows?.find(r => r.id === "robinhood");
  return row && BAD.includes(row.state) ? row : null;
}

// --------------------------------------------------------------------------- the dot

const DOT: Record<HealthState, string> = {
  live: "bg-emerald-400", closed: "bg-muted-foreground/50", off: "bg-muted-foreground/50", quiet: "bg-muted-foreground/50",
  unknown: "bg-muted-foreground/50", stale: "bg-amber-400", down: "bg-amber-400", low: "bg-amber-400",
};
const WORD: Record<HealthState, string> = {
  live: "live", closed: "closed", off: "off", quiet: "quiet", unknown: "unknown", stale: "behind", down: "down", low: "low",
};

/** The dot's summary from every row: red naming a money source behind first ("Robinhood down", "Robinhood + 1 behind";
 * ``short``, its name alone, for a phone), amber naming any other ("Chatter behind", "2 sources behind"), grey when
 * something cannot be told, else green. */
export function summary(rows: HealthRow[] | null, failed: boolean): { tone: "ok" | "unknown" | "amber" | "red"; text: string; short?: string } {
  if (failed) return { tone: "unknown", text: "Health unknown" };
  if (!rows) return { tone: "unknown", text: "Checking…" };
  const bad = rows.filter(r => BAD.includes(r.state));
  const money = bad.find(r => MONEY.has(r.id));
  if (money) return { tone: "red", short: money.name,
    text: bad.length === 1 ? `${money.name} ${WORD[money.state]}` : `${money.name} + ${bad.length - 1} behind` };
  if (bad.length === 1) return { tone: "amber", text: `${bad[0].name} ${WORD[bad[0].state]}` };
  if (bad.length > 1) return { tone: "amber", text: `${bad.length} sources behind` };
  const unknown = rows.filter(r => r.state === "unknown");
  if (unknown.length) return { tone: "unknown", text: unknown.length === 1 ? `${unknown[0].name} unknown` : `${unknown.length} unknown` };
  return { tone: "ok", text: rows.some(r => r.state === "live") ? "All live" : "Market closed · all fine" };
}

/** Open and closed by its button; a tap away closes it, and Escape closes this list only, not the desk's drawer or sheet
 * behind it (the desk listens on window). */
function useHealthOpen() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent | TouchEvent) => { if (box.current && !box.current.contains(event.target as Node)) setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("touchstart", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("touchstart", away); document.removeEventListener("keydown", key); };
  }, [open]);
  return { open, setOpen, box };
}

/** The list of every source, under the dot or (``up``) above the status line. */
function HealthList({ rows, failed, tape, up = false }: { rows: HealthRow[] | null; failed: boolean; tape: Level2Health; up?: boolean }) {
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <div role="dialog" aria-label="Data health" data-testid="desk-health-list"
      className={cn("absolute z-50 w-[min(22rem,calc(100vw-2rem))] rounded-md border bg-card p-1 text-xs shadow-lg",
        up ? "bottom-full left-2 mb-1" : "right-0 top-full mt-1 max-sm:fixed max-sm:left-4 max-sm:right-4 max-sm:top-14 max-sm:w-auto")}>
      <p className="px-2 pb-1 pt-1.5 text-muted-foreground">
        {failed ? "Could not check just now; the next minute asks again." : "What feeds the desk. Tap one for what it affects."}
      </p>
      <ul>
        {/* Without the server's rows the Tape's own still shows. */}
        {(rows ?? [level2Row(tape)]).map(row => <Source key={row.id} row={row} open={picked === row.id} onPick={() => setPicked(picked === row.id ? null : row.id)} />)}
      </ul>
    </div>
  );
}

/** ``onlyRed``: from 768 px the status line says health, so the top bar's dot shows only while a money source is behind. */
export default function DeskHealthDot({ onlyRed = false }: { onlyRed?: boolean }) {
  const { rows, failed, said, tape } = useDeskHealth();
  const { open, setOpen, box } = useHealthOpen();
  const dot = said.tone === "red" ? "bg-rose-500" : said.tone === "amber" ? "bg-amber-400" : said.tone === "ok" ? "bg-emerald-400" : "bg-muted-foreground/50";
  if (onlyRed && said.tone !== "red") return null;

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog" data-testid="desk-health"
        data-tone={said.tone} aria-label={`Data health: ${said.text}`} title={`${said.text} · is every source behind the desk live?`}
        className={cn("inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 text-xs sm:min-h-8",
          said.tone === "red" ? "font-medium text-rose-300 max-sm:flex-col max-sm:gap-0.5 max-sm:px-1" : said.tone === "amber" ? "text-amber-300" : "text-muted-foreground",
          open ? "bg-secondary" : "hover:bg-secondary")}>
        <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", dot)} />
        {/* Words only when something is behind: a dot that never changes width keeps the top bar from jumping. */}
        {(said.tone === "red" || said.tone === "amber") && <span data-testid="desk-health-words" className="hidden whitespace-nowrap sm:inline">{said.text}</span>}
        {/* A phone has no status line: money behind names its source under the dot, as the Day button's word sits. */}
        {said.short && <span aria-hidden data-testid="desk-health-short" className="whitespace-nowrap text-[10px] leading-none sm:hidden">{said.short}</span>}
      </button>
      {open && <HealthList rows={rows} failed={failed} tape={tape} />}
    </div>
  );
}

function Source({ row, open, onPick }: { row: HealthRow; open: boolean; onPick(): void }) {
  const bad = BAD.includes(row.state);
  const red = bad && MONEY.has(row.id); // as the dot and the status line show it
  return (
    <li data-testid={`health-${row.id}`} data-state={row.state} data-tone={red ? "red" : bad ? "amber" : undefined}>
      <button type="button" onClick={onPick} aria-expanded={open}
        className="flex min-h-9 w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-secondary">
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", red ? "bg-rose-500" : DOT[row.state])} />
        <span className="w-24 shrink-0 font-medium text-foreground">{row.name}</span>
        <span className={cn("min-w-0 flex-1", red ? "text-rose-300" : bad ? "text-amber-300" : "text-muted-foreground")}>
          {row.line}<span className="sr-only"> ({WORD[row.state]})</span>
        </span>
      </button>
      {open && (
        <div className="space-y-1 px-2 pb-2 pl-[1.375rem] text-muted-foreground" data-testid={`health-${row.id}-more`}>
          <p>{row.affects}</p>
          {row.fix?.kind === "text" && <p className="text-foreground/80">{row.fix.text}</p>}
          {row.fix?.kind === "gmail_reconnect" && <GmailReconnect />}
        </div>
      )}
    </li>
  );
}

/** Gmail's existing Reconnect (the banner's ``/auth/gmail/start``): nothing new, the same sign-in page. */
function GmailReconnect() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await api.startGmailAuth();
      window.location.assign(auth_url);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" onClick={go} disabled={busy}
        className="rounded border border-amber-400/40 px-2 py-1 font-medium text-amber-200 hover:bg-amber-500/10 disabled:opacity-60">
        {busy ? "Opening…" : "Reconnect Gmail"}
      </button>
      {error && <p className="text-amber-300">{error}</p>}
    </>
  );
}

// --------------------------------------------------------------------------- the status line

const ET = "America/New_York";
const clock = (at: number, seconds = false) => new Date(at * 1000).toLocaleTimeString("en-US",
  { timeZone: ET, hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), hourCycle: "h23" });

/** A source behind, in words: "Robinhood behind since 10:31", "Fill emails down since 9:12", "Copilot budget low". */
export function behindWords(row: HealthRow): string {
  if (row.state === "low") return `${row.name} low`;
  return `${row.name} ${row.state === "stale" ? "behind" : "down"}${row.last_at ? ` since ${clock(row.last_at)}` : ""}`;
}

/** How fresh the desk's prices are: the newest live price while the session runs, else what the Prices row says. */
function pricesWords(ticks: DeskTicks, row: HealthRow | undefined): { text: string; late: boolean } | null {
  const times = ticks.open ? Object.values(ticks.rows).map(t => t.at) : [];
  if (times.length) {
    const newest = Math.max(...times);
    return { text: `Prices ${clock(newest, true)}`, late: Date.now() / 1000 - newest > STALE_SECONDS };
  }
  if (!row) return null;
  if (row.state === "closed") return { text: "Prices · market closed", late: false };
  return row.last_at ? { text: `Prices ${clock(row.last_at)}`, late: BAD.includes(row.state) } : { text: "Prices · no read yet", late: false };
}

/**
 * The status line along the desk's bottom, from 768 px (a phone has its tab bar there, and the top bar's dot): the mode's
 * mark with whose book (``mark``), then only what is not fine, in words: a source behind, red when it leaves positions,
 * fills or prices wrong ("Robinhood behind since 10:31"), amber for the rest; one that cannot be told, grey; prices that
 * stopped ticking in the session. When nothing is wrong it says so once: "All live", or after the close "Market closed ·
 * all fine". A tap opens the Data health list (every source); ``market`` (the clock and SPY / QQQ / VIX) is its hover.
 * It shares the dot's read and the desk's live prices: it asks for nothing of its own.
 */
export function DeskStatusLine({ mark, market = null, className }: { mark: ReactNode; market?: string | null; className?: string }) {
  const { rows, failed, said, tape } = useDeskHealth();
  const { open, setOpen, box } = useHealthOpen();
  const ticks = useHeldTicks();
  const pricesRow = rows?.find(r => r.id === "prices");
  const prices = pricesWords(ticks, pricesRow);
  // Not fine: behind first (money before the rest), then any that cannot be told.
  const bad = rows ? rows.filter(r => BAD.includes(r.state)).sort((a, b) => Number(MONEY.has(b.id)) - Number(MONEY.has(a.id))) : [];
  const unknown = rows ? rows.filter(r => r.state === "unknown") : [];
  const late = prices?.late && !bad.some(r => r.id === "prices") ? prices : null;
  const fine = !!rows && !bad.length && !unknown.length && !late;
  return (
    <div ref={box} className={cn("relative", className)}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog" data-testid="desk-status-line" data-tone={said.tone}
        title={`${market ? `${market}\n` : ""}Data health: what feeds the desk`}
        className={cn("flex h-7 w-full min-w-0 items-center gap-3 overflow-hidden whitespace-nowrap px-3.5 text-left text-[11px] text-muted-foreground hover:bg-secondary/60",
          open && "bg-secondary/60")}>
        {mark}
        <span aria-hidden className="h-3 w-px shrink-0 bg-border" />
        {failed ? <span className="shrink-0">Health unknown · the next minute asks again</span>
          : !rows ? <span className="shrink-0">Checking sources…</span>
          : fine ? <span data-testid="status-fine" className="inline-flex shrink-0 items-center gap-1">
              <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              {pricesRow?.state === "closed" ? "Market closed · all fine" : "All live"}
            </span>
          : <>
            {bad.map(row => {
              const red = MONEY.has(row.id);
              return (
                <span key={row.id} data-testid={`status-${row.id}`} data-state={row.state} data-tone={red ? "red" : "amber"}
                  className={cn("inline-flex shrink-0 items-center gap-1", red ? "font-medium text-rose-300" : "text-amber-300")}>
                  <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", red ? "bg-rose-500" : DOT[row.state])} />
                  {behindWords(row)}
                </span>
              );
            })}
            {late && <span data-testid="status-prices" className="shrink-0 tabular-nums text-amber-300">{late.text}</span>}
            {unknown.map(row => (
              <span key={row.id} data-testid={`status-${row.id}`} data-state={row.state} className="inline-flex shrink-0 items-center gap-1">
                <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/50" />{row.name} unknown
              </span>
            ))}
          </>}
      </button>
      {open && <HealthList rows={rows} failed={failed} tape={tape} up />}
    </div>
  );
}
