/** Invented price-level snapshots only. No provider, transport, storage or journal imports. */
export type DepthLevel = { priceCents: number; size: number; orders: number | null };
export type DepthBook = { sourceOffsetMs: number | null; bids: DepthLevel[]; asks: DepthLevel[] };
export type ReplayFrame = { offsetMs: number; connected: boolean; book: DepthBook };
export type BookState = "fresh" | "stale" | "disconnected" | "empty" | "unknown-time";

export const DURATION_MS = 20_000;
export const STALE_AFTER_MS = 2_000;
export const SESSION_START_MS = Date.parse("2026-10-09T13:30:00Z");
export const HEATMAP_PRICES = Array.from({ length: 25 }, (_, i) => 23014 - i);

function inventedBook(second: number): DepthBook {
  const center = 23000 + Math.round(Math.sin(second / 3) * 2);
  return {
    sourceOffsetMs: second === 14 ? null : second * 1000,
    bids: Array.from({ length: 8 }, (_, i) => ({
      priceCents: center - i,
      size: 150 + (second * 71 + i * 137) % 850 + (second < 4 && i === 2 ? 1100 : 0),
      orders: i === 3 ? null : i + 1,
    })),
    asks: Array.from({ length: 8 }, (_, i) => ({
      priceCents: center + 2 + i,
      size: 190 + (second * 53 + i * 181) % 850 + (second >= 4 && i === 1 ? 1300 : 0),
      orders: i === 3 ? null : i + 2,
    })),
  };
}

export const REPLAY_FRAMES: ReplayFrame[] = Array.from({ length: 21 }, (_, second) => ({
  offsetMs: second * 1000,
  connected: second < 10 || second >= 13,
  book: second >= 6 && second <= 12 ? inventedBook(5)
    : second === 13 ? { sourceOffsetMs: 13000, bids: [], asks: [] }
    : inventedBook(second),
}));

export function replayAt(offsetMs: number): ReplayFrame {
  const offset = Number.isFinite(offsetMs) ? Math.max(0, Math.min(DURATION_MS, offsetMs)) : 0;
  return REPLAY_FRAMES[Math.floor(offset / 1000)];
}

export function bookAge(frame: ReplayFrame, offsetMs: number): number | null {
  return frame.book.sourceOffsetMs === null ? null : Math.max(0, offsetMs - frame.book.sourceOffsetMs);
}

export function bookState(frame: ReplayFrame, offsetMs: number): BookState {
  if (!frame.connected) return "disconnected";
  const age = bookAge(frame, offsetMs);
  if (age === null) return "unknown-time";
  if (age > STALE_AFTER_MS) return "stale";
  if (!frame.book.bids.length || !frame.book.asks.length) return "empty";
  return "fresh";
}

/** Both sides' nearest five displayed prices; no estimate of unobserved venues or executions. */
export function depthSummary(frame: ReplayFrame, offsetMs: number) {
  if (bookState(frame, offsetMs) !== "fresh") return null;
  const bids = frame.book.bids.slice(0, 5), asks = frame.book.asks.slice(0, 5);
  if (bids.length < 5 || asks.length < 5) return null;
  const bidSize = bids.reduce((sum, level) => sum + level.size, 0);
  const askSize = asks.reduce((sum, level) => sum + level.size, 0);
  const total = bidSize + askSize;
  return {
    bidSize, askSize,
    imbalance: total > 0 ? (bidSize - askSize) / total : null,
    spreadCents: asks[0].priceCents - bids[0].priceCents,
  };
}

export const priceText = (cents: number) => (cents / 100).toFixed(2);
export const sourceTime = (offsetMs: number) => new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
}).format(SESSION_START_MS + offsetMs);
