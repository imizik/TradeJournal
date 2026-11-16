/**
 * How he uses the desk (docs/copilot-lab.md § How I use the desk; backend ``app/engine/desk_use.py``).
 *
 * Counting is quiet: each desk piece in ``PIECES`` has a stable id, and the desk counts its opens, its taps (a click on
 * anything inside an element marked ``data-use="<id>"``) and its time on screen (every 15 seconds while the page shows,
 * each marked piece with a box in the viewport gets 15 seconds). Only these ids are counted: no keystrokes, no message
 * text, no tickers. Counts wait on this device (localStorage, by New York day and device size) and are sent to the app's
 * own server at most once every five minutes, checked on the 15-second tick and when the page shows again; never on a
 * timer of their own and never while the page is hidden, so an idle desk asks no more than before. Counts not yet saved
 * stay here until a save works; ``useMeta`` says since when saving has failed.
 *
 * Folding is per device size: ``desk`` from 768 px, ``phone`` below.
 */

import { apiUrl } from "@/lib/api";
import { nyDay } from "@/lib/desk";

export type DeskSize = "desk" | "phone";
/** How a folded piece goes away: a slim labelled stub in place, or into its area's "More". Null: counted, never folded. */
export type FoldMode = "stub" | "more" | null;
export type Piece = { id: string; label: string; area: string; fold: FoldMode;
  /** Holds safety information (open positions and their risk, working orders, sources down, alerts): never suggested,
   * never folded. */
  safety?: boolean;
  /** Foldable by his own choice in "How I use the desk", but never suggested (it shows his plan levels). */
  quiet?: boolean };

/** Every piece the desk counts, by area. Folding one never changes what the app reads or pings. */
export const PIECES: readonly Piece[] = [
  { id: "needs", label: "Needs you", area: "Top", fold: null, safety: true },
  { id: "health", label: "Health dot", area: "Top", fold: null, safety: true },
  { id: "pnl", label: "Day P&L", area: "Top", fold: null },
  { id: "accounts", label: "Account line", area: "Top", fold: "stub" },
  { id: "moving", label: "What's moving", area: "Top", fold: "stub" },
  { id: "threads", label: "Thread list", area: "Top", fold: null },
  { id: "palette", label: "Jump to… (⌘K)", area: "Top", fold: null },
  { id: "keys", label: "Desk keys", area: "Top", fold: null },
  { id: "plan", label: "Plan a trade", area: "Top", fold: null },
  { id: "book", label: "Book: positions and working orders", area: "Left", fold: null, safety: true },
  { id: "paper", label: "Paper", area: "Left", fold: "stub" },
  { id: "paper.rules", label: "My rules", area: "Left", fold: null },
  { id: "paper.goals", label: "Weekly goals", area: "Left", fold: null },
  { id: "strategy.overnight", label: "QQQ overnight book", area: "Left", fold: "stub" },
  { id: "strategy.momentum", label: "QQQ momentum book", area: "Left", fold: "stub" },
  { id: "replay.practice", label: "Replay practice", area: "Left", fold: "stub" },
  { id: "watching", label: "Watching", area: "Left", fold: "stub", quiet: true },
  { id: "dayblock", label: "Since you looked · brief · day report", area: "Left", fold: null },
  { id: "dayfacts", label: "At risk now (under the book's heading)", area: "Left", fold: null, safety: true },
  { id: "tab.chart", label: "Chart tab", area: "Centre", fold: null },
  { id: "tab.chain", label: "Chain tab", area: "Centre", fold: "more" },
  { id: "tab.ticket", label: "Ticket tab", area: "Centre", fold: "more" },
  { id: "tab.check", label: "Check a call tab", area: "Centre", fold: "more" },
  { id: "tab.grid", label: "Grid tab", area: "Centre", fold: "more" },
  { id: "chart.studies", label: "Chart studies row", area: "Centre", fold: "more" },
  { id: "chart.tape", label: "Tape (Level 2)", area: "Centre", fold: "more" },
  { id: "chart.replay", label: "Replay button", area: "Centre", fold: "more" },
  { id: "chart.timeline", label: "Timeline", area: "Centre", fold: null },
  { id: "ticket.copy", label: "Ticket: Copy", area: "Centre", fold: null },
  { id: "ticket.paper", label: "Paper it", area: "Centre", fold: null },
  { id: "ticket.spread", label: "Ticket: spread", area: "Centre", fold: null },
  { id: "ticket.roll", label: "Ticket: roll", area: "Centre", fold: null },
  { id: "side.copilot", label: "Copilot", area: "Right", fold: null },
  { id: "side.feed", label: "Feed", area: "Right", fold: null },
  { id: "feed.mine", label: "Feed: Mine", area: "Right", fold: null },
  { id: "feed.ideas", label: "Feed: Ideas", area: "Right", fold: null },
  { id: "feed.market", label: "Feed: Market", area: "Right", fold: null },
  { id: "feed.all", label: "Feed: All", area: "Right", fold: null },
  { id: "feed.chatter", label: "Chatter", area: "Right", fold: "more" },
  { id: "view.book", label: "Phone: Book view", area: "Phone", fold: null },
  { id: "view.ticker", label: "Phone: ticker view", area: "Phone", fold: null },
  { id: "view.feed", label: "Phone: Feed view", area: "Phone", fold: null },
];
export const PIECE = new Map(PIECES.map(p => [p.id, p]));
export const foldable = (id: string) => { const p = PIECE.get(id); return !!p?.fold && !p.safety; };
/** A short name for a suggestion's sentence ("Grid", not "Grid tab"). */
export const shortName = (id: string) => (PIECE.get(id)?.label ?? id).replace(/ tab$/, "").replace(/ \(.*\)$/, "").replace(/^Chatter$/, "chatter");

export const TICK_MS = 15_000;
export const FLUSH_MS = 5 * 60_000;
export const WINDOW_DAYS = 14;
const STORE_KEY = "desk.use.v1";
const META_KEY = "desk.use.meta.v1";
export const USE_EVENT = "desk-use-meta";

type Counts = [number, number, number]; // opens, taps, seconds on screen
type Store = Partial<Record<DeskSize, Record<string, Record<string, Counts>>>>;
export type UseMeta = { lastTry: number | null; failedSince: number | null; lastSaved: number | null };

export const deskSize = (): DeskSize => typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches ? "phone" : "desk";

function load<T>(key: string, empty: T): T {
  try { const raw = window.localStorage.getItem(key); return raw ? JSON.parse(raw) as T : empty; } catch { return empty; }
}
function keep(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* counting is best effort */ }
}
export const readMeta = (): UseMeta => load<UseMeta>(META_KEY, { lastTry: null, failedSince: null, lastSaved: null });
function writeMeta(meta: UseMeta) {
  keep(META_KEY, meta);
  window.dispatchEvent(new Event(USE_EVENT));
}

function add(pieces: Iterable<string>, at: 0 | 1 | 2, n: number) {
  const known = [...pieces].filter(p => PIECE.has(p));
  if (!known.length || typeof window === "undefined") return;
  const store = load<Store>(STORE_KEY, {});
  const size = deskSize(), day = nyDay();
  const days = (store[size] ??= {});
  const today = (days[day] ??= {});
  for (const piece of known) {
    const c = (today[piece] ??= [0, 0, 0]);
    c[at] += n;
  }
  keep(STORE_KEY, store);
}
export const countOpen = (id: string) => add([id], 0, 1);
export const countTap = (id: string) => add([id], 1, 1);
export const countSeen = (ids: Iterable<string>, seconds: number) => add(ids, 2, seconds);

/** Counts on this device not yet saved: one size's, summed per piece over days on or after ``from``. */
export function pending(size: DeskSize, from: string): Record<string, Counts> {
  const out: Record<string, Counts> = {};
  for (const [day, pieces] of Object.entries(load<Store>(STORE_KEY, {})[size] ?? {})) {
    if (day < from) continue;
    for (const [piece, c] of Object.entries(pieces)) {
      const o = (out[piece] ??= [0, 0, 0]);
      o[0] += c[0]; o[1] += c[1]; o[2] += c[2];
    }
  }
  return out;
}
export const hasPending = () => Object.values(load<Store>(STORE_KEY, {})).some(days => Object.values(days ?? {}).some(p => Object.keys(p).length > 0));

let flushing = false;
/** Send what waits on this device (one request per size with counts), then take exactly what was sent off the store, so
 * a tap while the request was out is kept. ``force`` skips the five-minute rest (opening "How I use the desk"). */
export async function flush(force = false): Promise<boolean> {
  if (flushing || typeof window === "undefined") return false;
  const meta = readMeta();
  const now = Date.now();
  if (!hasPending()) { if (meta.lastTry === null) writeMeta({ ...meta, lastTry: now }); return true; }
  if (!force && meta.lastTry !== null && now - meta.lastTry < FLUSH_MS) return false;
  if (!force && meta.lastTry === null) { writeMeta({ ...meta, lastTry: now }); return false; } // the first save waits five minutes
  flushing = true;
  // Claimed before the request goes out, so another window's tick sees a save under way and waits its five minutes.
  writeMeta({ ...meta, lastTry: now });
  const sent = load<Store>(STORE_KEY, {});
  try {
    for (const size of ["desk", "phone"] as const) {
      const rows = Object.entries(sent[size] ?? {}).flatMap(([day, pieces]) => Object.entries(pieces)
        .map(([piece, [opens, taps, seen_s]]) => ({ day, piece, opens: Math.max(0, opens), taps: Math.max(0, taps), seen_s: Math.max(0, seen_s) }))
        .filter(r => r.opens || r.taps || r.seen_s)).slice(0, 400);
      if (!rows.length) continue;
      const response = await fetch(apiUrl("/copilot/desk/use"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ size, rows }) });
      if (!response.ok) throw new Error(String(response.status));
      const store = load<Store>(STORE_KEY, {});
      for (const row of rows) {
        const c = store[size]?.[row.day]?.[row.piece];
        if (!c) continue;
        c[0] = Math.max(0, c[0] - row.opens); c[1] = Math.max(0, c[1] - row.taps); c[2] = Math.max(0, c[2] - row.seen_s);
        if (c[0] <= 0 && c[1] <= 0 && c[2] <= 0) delete store[size]![row.day][row.piece];
        if (!Object.keys(store[size]![row.day]).length) delete store[size]![row.day];
      }
      keep(STORE_KEY, store);
    }
    writeMeta({ lastTry: now, failedSince: null, lastSaved: now });
    return true;
  } catch {
    writeMeta({ lastTry: now, failedSince: meta.failedSince ?? now, lastSaved: meta.lastSaved });
    return false;
  } finally {
    flushing = false;
  }
}

/** Is this element on screen now: a box of its own (or, for ``display: contents``, one of its children's) inside the viewport. */
function onScreen(el: Element): boolean {
  const boxes = el.getClientRects().length ? [el.getBoundingClientRect()] : [...el.children].map(c => c.getBoundingClientRect());
  return boxes.some(r => r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < window.innerHeight && r.left < window.innerWidth);
}
/** The 15-second tick's look: every marked piece on screen, once each. */
export function piecesOnScreen(root: ParentNode = document): Set<string> {
  const seen = new Set<string>();
  root.querySelectorAll<HTMLElement>("[data-use]").forEach(el => { const id = el.dataset.use; if (id && !seen.has(id) && onScreen(el)) seen.add(id); });
  return seen;
}

// ------------------------------------------------------------------------------------------- the server's summary, folds
export type PieceUse = { opens: number; taps: number; seen_s: number; last_used: string | null };
export type Folds = { folded: string[]; snoozed_until: string | null };
export type UseSummary = { size: DeskSize; today: string; window_days: number; window_start: string; days_with_use: number;
  first_day: string | null; pieces: Record<string, PieceUse>; folds: Folds };

export async function readUse(size: DeskSize, signal?: AbortSignal): Promise<UseSummary> {
  const response = await fetch(apiUrl(`/copilot/desk/use?size=${size}`), { signal });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.folds) throw new Error(String(response.status));
  return body as UseSummary;
}
export async function saveFolds(size: DeskSize, folds: Folds): Promise<Folds> {
  const response = await fetch(apiUrl("/copilot/desk/folds"), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ size, ...folds }) });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body) throw new Error(typeof body?.detail === "string" ? body.detail : `Saving failed (${response.status}).`);
  return body as Folds;
}

/** "Near zero" in the window: opened at most once and tapped at most once. */
export const nearZero = (use: PieceUse | undefined) => !use || (use.opens <= 1 && use.taps <= 1);
/** The pieces to suggest folding: only once there are ``WINDOW_DAYS`` days of desk use on this size, never while snoozed,
 * never a safety piece or one already folded, and only pieces that were on screen in the window (a book switched off is
 * not "unused"). */
export function suggestions(summary: UseSummary | null, folded: ReadonlySet<string>): string[] {
  if (!summary || summary.days_with_use < summary.window_days) return [];
  if (summary.folds.snoozed_until && summary.folds.snoozed_until > summary.today) return [];
  return PIECES.filter(p => foldable(p.id) && !p.quiet && !folded.has(p.id) && (summary.pieces[p.id]?.seen_s ?? 0) > 0 && nearZero(summary.pieces[p.id])).map(p => p.id);
}
/** "Tape, chatter or Grid"; past three, "Tape, chatter, Grid or 4 more" (Pick lists them all). */
export function nameList(ids: string[], most = 3): string {
  const names = ids.map(shortName);
  if (names.length > most) return `${names.slice(0, most).join(", ")} or ${names.length - most} more`;
  return names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}
export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
