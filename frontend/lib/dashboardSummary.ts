import type { Trade } from "@/lib/api";

/** Journal timestamps are timezone-free ET wall clocks; compare their dates
 * directly, never reinterpret them in the browser or server's timezone. */
export function weekStart(today: string): string {
  const day = new Date(`${today}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
  return day.toISOString().slice(0, 10);
}

export function closedInPeriod(trades: Trade[], start: string, end: string) {
  const closed = trades.filter((trade) => trade.status !== "open" && trade.closed_at
    && trade.closed_at.slice(0, 10) >= start && trade.closed_at.slice(0, 10) <= end);
  const complete = closed.every((trade) => trade.realized_pnl != null && Number.isFinite(trade.realized_pnl));
  return { count: closed.length, pnl: complete ? closed.reduce((sum, trade) => sum + (trade.realized_pnl ?? 0), 0) : null };
}

export function recentCloses(trades: Trade[]) {
  return trades.filter((trade) => trade.status !== "open")
    .sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? "") || a.id.localeCompare(b.id))
    .slice(0, 5);
}
