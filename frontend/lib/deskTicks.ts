/**
 * The desk's live prices (``GET /copilot/desk/ticks``, docs/copilot-lab.md § Live prices): one shared ticker for every
 * piece of the desk that shows a price (the book, Watching, the chart's reading line and last candle).
 *
 * - Each piece names its symbols with ``useDeskTicks``; the ticker asks for all of them in one read.
 * - It asks only while some piece is mounted and the tab is visible, every few seconds in the regular session (the
 *   server says how often). Outside it the server answers ``closed`` with the next open, and the ticker waits for it.
 * - A failed or refused read backs off (5, 10, 20, 40, 60 s); a slow one waits longer before the next.
 * - A price whose last good read is older than ``STALE_SECONDS`` in the session is shown greyed with its time
 *   (``stale``); after ``DROP_SECONDS`` the desk's minute reads show again. A symbol with no price shows what the desk
 *   already had, never a zero.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { apiUrl } from "@/lib/api";
import type { DeskBook } from "@/lib/desk";

/** One symbol's price (an option's OCC symbol: its mark per share of premium), change today and when it was read. */
export type DeskTick = { last: number; change_pct: number | null; prev_close: number | null; at: number };
export type DeskTicksReply = {
  state: "ok" | "closed" | "unavailable"; as_of: string; rows: Record<string, DeskTick>;
  opens_at?: number | null; closes_at?: number; poll_seconds: number | null;
};
/** What the desk shows from: the rows kept, whether the session is open, and when the ticker last heard anything. */
export type DeskTicks = { rows: Record<string, DeskTick>; open: boolean; checked: number };

export const STALE_SECONDS = 20;
/** A tick older than this is dropped: the desk's minute reads (newer by then) show instead, as before live prices. */
export const DROP_SECONDS = 60;
const POLL_MS = 5_000;
const MAX_BACKOFF_MS = 60_000;
const SLOW_MS = 1_500;
const CLOSED_RECHECK_MS = 30 * 60_000;
const START_MS = 300; // the desk's pieces mount one after another: one first read for all of them
const SOON_MS = 250;

const EMPTY: DeskTicks = { rows: {}, open: false, checked: 0 };
let snapshot: DeskTicks = EMPTY;
const listeners = new Set<() => void>();
const wanted = new Map<number, string[]>();
let ids = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let controller: AbortController | null = null;
let failures = 0;
let restAt = 0; // closed: the earliest moment worth asking again (a remount or a return to the tab waits for it)
let again = false; // a symbol arrived while a read was out: read again soon after it

function emit(next: DeskTicks) {
  snapshot = next;
  for (const listener of listeners) listener();
}

function union(): string[] {
  return [...new Set([...wanted.values()].flat())].sort();
}

function schedule(ms: number) {
  if (timer) clearTimeout(timer);
  timer = wanted.size ? setTimeout(poll, Math.max(0, ms)) : null;
}

function visible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** When to read next from a standing start: after the closed wait if the session is shut, else at once. */
function startIn(ms: number) {
  return Math.max(ms, restAt - Date.now());
}

function onVisibility() {
  if (visible() && wanted.size) schedule(startIn(0)); // back on the tab: a fresh price now, not one from before it was hidden
}

async function poll() {
  timer = null;
  const symbols = union();
  if (!symbols.length || !visible() || controller) return; // hidden: the visibility listener starts it again
  controller = new AbortController();
  again = false;
  const started = Date.now();
  try {
    const response = await fetch(apiUrl(`/copilot/desk/ticks?${new URLSearchParams({ symbols: symbols.join(",") })}`), { cache: "no-store", signal: controller.signal });
    // Read the body even when refused: an unread one keeps the request open in the browser (and the page never idle).
    const reply = await response.json().catch(() => null) as DeskTicksReply | null;
    if (!response.ok || !reply) throw new Error(`Request failed (${response.status}).`);
    const took = Date.now() - started;
    const now = Math.floor(Date.now() / 1000);
    if (reply.state === "closed") {
      failures = 0;
      emit({ rows: {}, open: false, checked: now });
      const opens = reply.opens_at ? reply.opens_at * 1000 - Date.now() : CLOSED_RECHECK_MS;
      const wait = Math.min(Math.max(opens, POLL_MS), CLOSED_RECHECK_MS);
      restAt = Date.now() + wait;
      schedule(wait);
      return;
    }
    restAt = 0;
    // Rows kept for symbols this read did not name stay: a piece that asked a moment earlier keeps its price.
    emit({ rows: { ...snapshot.rows, ...reply.rows }, open: true, checked: now });
    if (reply.state === "unavailable") {
      failures += 1;
      schedule(Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** (failures - 1)));
      return;
    }
    failures = 0;
    const every = (reply.poll_seconds ?? POLL_MS / 1000) * 1000;
    schedule(again ? SOON_MS : took > SLOW_MS ? Math.max(every, took * 3) : every);
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    failures += 1;
    emit({ ...snapshot, checked: Math.floor(Date.now() / 1000) });
    schedule(Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** (failures - 1)));
  } finally {
    controller = null;
  }
}

function want(id: number, symbols: string[]) {
  const before = new Set(union());
  if (symbols.length) wanted.set(id, symbols); else wanted.delete(id);
  const after = union();
  if (!after.length) return stop();
  if (!timer && !controller) return schedule(startIn(START_MS));
  // A symbol nobody asked for yet: read it soon (in the session) rather than at the next turn of the clock.
  if ((snapshot.open || !snapshot.checked) && after.some(s => !before.has(s))) {
    if (controller) again = true;
    else schedule(SOON_MS);
  }
}

function stop() {
  if (timer) clearTimeout(timer);
  timer = null;
  controller?.abort();
  controller = null;
  failures = 0;
  again = false;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (typeof document !== "undefined" && listeners.size === 1) document.addEventListener("visibilitychange", onVisibility);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
  };
}

/** The live prices for ``symbols`` (tickers, or an option's OCC symbol), shared with every other piece of the desk. The
 * ticker runs while any piece is mounted and stops when the last one goes. */
export function useDeskTicks(symbols: readonly (string | null | undefined)[]): DeskTicks {
  const key = [...new Set(symbols.filter((s): s is string => !!s).map(s => s.toUpperCase()))].sort().join(",");
  const [id] = useState(() => ++ids);
  useEffect(() => {
    want(id, key ? key.split(",") : []);
    return () => want(id, []);
  }, [id, key]);
  const ticks = useSyncExternalStore(subscribe, () => snapshot, () => EMPTY);
  // In the session a price can turn stale while no read lands (a read backing off): look again every few seconds.
  const [, setBeat] = useState(0);
  useEffect(() => {
    if (!ticks.open) return;
    const timer = setInterval(() => setBeat(n => n + 1), POLL_MS);
    return () => clearInterval(timer);
  }, [ticks.open]);
  return ticks;
}

/** A symbol's tick while the session is open, with ``stale`` once its last good read is older than ``STALE_SECONDS``;
 * none once it is older than ``DROP_SECONDS``. */
export function tickFor(ticks: DeskTicks, symbol: string | null | undefined, now = Date.now() / 1000): (DeskTick & { stale: boolean }) | null {
  const row = symbol && ticks.open ? ticks.rows[symbol.toUpperCase()] : undefined;
  return row && now - row.at <= DROP_SECONDS ? { ...row, stale: now - row.at > STALE_SECONDS } : null;
}

/** A book row's P&L moved to the newest price, by the positions' own formula (``book.tick``, from the server): the same
 * numbers the server would give at that price. The server's numbers when there is no tick. */
export function tickedBook(book: DeskBook | undefined, ticks: DeskTicks, now = Date.now() / 1000):
  { usd: number | null; pct: number | null; at: number | null; stale: boolean } {
  const base = { usd: book?.usd ?? null, pct: book?.pct ?? null, at: null, stale: false };
  const terms = book?.tick;
  const tick = terms ? tickFor(ticks, terms.quote, now) : null;
  if (!terms || !tick || !terms.cost) return base;
  const mark = tick.last * terms.scale;
  return {
    usd: Math.round(terms.sign * (mark - terms.cost) * terms.quantity * 100) / 100,
    pct: Math.round(1000 * terms.sign * (mark - terms.cost) / terms.cost) / 10,
    at: tick.at, stale: tick.stale,
  };
}

/** The oldest stale tick's time among ``symbols`` (null when every one is live or has none): the "prices as of" line. */
export function staleSince(ticks: DeskTicks, symbols: readonly (string | null | undefined)[], now = Date.now() / 1000): number | null {
  const times = symbols.flatMap(s => { const t = tickFor(ticks, s, now); return t?.stale ? [t.at] : []; });
  return times.length ? Math.min(...times) : null;
}

/** For tests: forget everything the ticker holds and stop it. */
export function resetDeskTicks() {
  stop();
  wanted.clear();
  restAt = 0;
  snapshot = EMPTY;
}
