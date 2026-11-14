/**
 * The desk's once-a-minute re-reads (docs/copilot-lab.md § What an open desk asks): one clock for all of them and one request
 * per minute (``GET /copilot/desk/minute``, ``backend/app/engine/desk_minute.py``).
 *
 * - A piece that re-reads each minute registers with ``everyDeskMinute(read)`` (its first read on mount stays its own, so
 *   a cold page never waits on the slowest read). All of them turn on the same beat.
 * - A beat skips while the page is hidden; coming back to the page after a skipped beat turns one at once.
 * - Reads made with ``deskGet`` during a beat (and in the moment after it, so an effect a beat set off joins) go out as
 *   one request; each caller gets back the answer its own route gave, as a normal ``Response``. Anything else, or a
 *   lone read, is a plain request. A server without the batched route (404) gets the reads one by one.
 */

import { apiUrl } from "@/lib/api";

const MINUTE_MS = 60_000;
const WINDOW_MS = 150; // after a beat: reads started by what the beat set off still join its request
const FRESH_MS = 30_000; // a piece that registered (and so read) this recently sits the beat out
const MAX_READS = 16; // backend desk_minute.MAX_READS
/** The reads the server accepts (backend desk_minute.PATHS), plus the centre chart's ``/copilot/desk/<id>/chart``. */
export const BATCHED = new Set([
  "/copilot/desk/threads", "/copilot/desk/session", "/copilot/desk/watching", "/copilot/desk/moving",
  "/copilot/desk/feed", "/copilot/desk/sparks", "/copilot/unusual", "/copilot/scanner", "/copilot/tickets",
  "/copilot/exposure", "/copilot/investigations", "/copilot/desk/health", "/copilot/paper",
]);
const CHART = /^\/copilot\/desk\/(?!\.\.?\/)[A-Za-z0-9_.:%-]+\/chart$/; // an id as the proxy lets through (``:`` may be encoded)

type Waiting = { path: string; signal?: AbortSignal; resolve(r: Response): void; reject(e: unknown): void };
const readers = new Map<number, { read: () => void; since: number }>();
let ids = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let missed = false;
let open = false;
let queue: Waiting[] = [];
let beats = 0;
const beatListeners = new Set<() => void>();

const visible = () => typeof document === "undefined" || document.visibilityState === "visible";

function beat() {
  if (!visible()) { missed = true; return; }
  missed = false;
  beats += 1;
  open = true;
  const now = Date.now();
  setTimeout(flush, WINDOW_MS); // first, so a piece that throws can never leave the window open
  for (const reader of readers.values()) if (now - reader.since >= FRESH_MS) { try { reader.read(); } catch { /* that piece's own */ } }
  for (const listener of beatListeners) listener();
}

function onVisibility() {
  if (missed && visible()) beat();
}

function start() {
  timer = setInterval(beat, MINUTE_MS);
  document.addEventListener("visibilitychange", onVisibility);
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  missed = false;
  document.removeEventListener("visibilitychange", onVisibility);
}

/** Call ``read`` on the desk's shared minute beat (never while the page is hidden). Returns the unsubscribe. */
export function everyDeskMinute(read: () => void): () => void {
  const id = ++ids;
  readers.set(id, { read, since: Date.now() });
  if (!timer) start();
  return () => {
    readers.delete(id);
    if (!readers.size && !beatListeners.size) stop();
  };
}

/** Told on each beat (with ``deskBeats``, a ``useSyncExternalStore`` pair): an effect keyed on the count re-reads on the
 * shared minute and joins its request. */
export function onDeskBeat(listener: () => void): () => void {
  beatListeners.add(listener);
  if (!timer) start();
  return () => {
    beatListeners.delete(listener);
    if (!readers.size && !beatListeners.size) stop();
  };
}
export const deskBeats = () => beats;

const batchable = (path: string) => { const bare = path.split("?")[0]; return BATCHED.has(bare) || CHART.test(bare); };
const aborted = () => new DOMException("The operation was aborted.", "AbortError");

/** ``fetch`` for a desk read: joins the beat's one request while it is gathering, else goes out on its own. */
export function deskGet(path: string, signal?: AbortSignal): Promise<Response> {
  if (!open || !batchable(path) || queue.length >= MAX_READS) return fetch(apiUrl(path), { cache: "no-store", signal });
  if (signal?.aborted) return Promise.reject(aborted());
  return new Promise((resolve, reject) => { queue.push({ path, signal, resolve, reject }); });
}

function alone(item: Waiting) {
  fetch(apiUrl(item.path), { cache: "no-store", signal: item.signal }).then(item.resolve, item.reject);
}

async function flush() {
  open = false;
  const items = queue.filter(item => {
    if (!item.signal?.aborted) return true;
    item.reject(aborted());
    return false;
  });
  queue = [];
  if (items.length < 2) { items.forEach(alone); return; }
  const query = new URLSearchParams(items.map(item => ["read", item.path]));
  let reply: { reads?: { status: number; body: unknown }[] } | null = null;
  let status = 0;
  try {
    const response = await fetch(apiUrl(`/copilot/desk/minute?${query}`), { cache: "no-store" });
    status = response.status;
    // Read through, refused or not: an unread body keeps the request open (and the page never idle).
    reply = await response.json().catch(() => null);
  } catch (error) {
    items.forEach(item => item.reject(error));
    return;
  }
  const reads = status === 200 && Array.isArray(reply?.reads) && reply.reads.length === items.length ? reply.reads : null;
  if (!reads && status === 404) { items.forEach(alone); return; } // a backend without the batched route
  items.forEach((item, i) => {
    if (item.signal?.aborted) { item.reject(aborted()); return; }
    // A 200 that is not the batch's own shape (something in between answered) is a failed read, never a body.
    const read = reads ? reads[i] : { status: status === 200 ? 502 : status || 502, body: status === 200 ? null : reply };
    const code = Number.isInteger(read.status) && read.status >= 200 && read.status <= 599 ? read.status : 502;
    const empty = code === 204 || code === 205 || code === 304;
    item.resolve(new Response(empty ? null : JSON.stringify(read.body ?? null), { status: code, headers: { "Content-Type": "application/json" } }));
  });
}

/** For tests: forget the clock and every waiting read. */
export function resetDeskMinute() {
  stop();
  readers.clear();
  beatListeners.clear();
  queue = [];
  open = false;
  beats = 0;
}
