import { apiUrl } from "./api";

/** One closed trade replayed bar by bar: GET /trades/{id}/replay (backend app/engine/trade_replay.py). */

export type ReplayPosition = {
  /** Contracts (or shares) open after this bar's fills. */
  held: number;
  /** Per contract, as fills store it (dollars per contract for options). */
  avg_cost: number | null;
  realized: number;
  /** Realized plus the open part at this bar's last trade; null while something is open with no price yet. */
  pnl: number | null;
};
export type TradeReplayBar = { time: number; open: number; high: number; low: number; close: number; volume: number; vwap: number | null } & ReplayPosition;
export type TradeReplayOptionBar = { time: number; open: number; high: number; low: number; close: number };
export type TradeReplayFill = { id: string; time: number; entry: boolean; side: string; contracts: number; price: number; label: string };
export type TradeReplayPing = { time: number; kind: string; title: string | null; sent: boolean };
export type TradeReplayTag = {
  setup: string; mistakes: string[]; primary_mistake: string; broke_cut_rule: boolean; rule_broken_computed: boolean;
  grade: string | null; confidence: string | null; rationale: string | null; model: string | null;
};
export type TradeReplay = {
  trade_id: string; ticker: string; instrument_type: string;
  state: "ok" | "open" | "too_long" | "no_bars"; reason: string | null;
  interval_minutes?: number; contract?: string | null; multiplier?: number; direction?: "long" | "short";
  realized_pnl?: number | null;
  bars?: TradeReplayBar[]; option_bars?: TradeReplayOptionBar[]; option_note?: string | null;
  fills?: TradeReplayFill[]; pings?: TradeReplayPing[];
  /** The leak rules' cut: the minute they said sell (deep red past the hour, or a same-day option past 1 PM). */
  cut?: { rule: "deep_red" | "past_1pm"; time: number; price: number } | null;
  /** 30% under a short-dated long option's first buy (per contract), and the first minute it traded at or under it. */
  cut_line?: { price: number; crossed: { time: number; state: "acted" | "ignored"; held: number; cost: number | null } | null } | null;
  tag?: TradeReplayTag | null;
};

export async function fetchTradeReplay(tradeId: string, signal?: AbortSignal): Promise<TradeReplay> {
  const response = await fetch(apiUrl(`/trades/${tradeId}/replay`), { cache: "no-store", signal });
  if (!response.ok) throw new Error(`Replay unavailable (${response.status})`);
  return response.json();
}

/** What happened on the chart, oldest first, each placed on the bar that holds its moment. */
export type ReplayEvent = { index: number; time: number; kind: "fill" | "ping" | "cut" | "cut_line"; tone: "buy" | "sell" | "ping" | "muted" | "rule"; label: string };

/** The index of the last bar starting at or before ``time`` (the first bar for anything earlier). */
export function barIndexAt(bars: { time: number }[], time: number): number {
  let lo = 0, hi = bars.length - 1, found = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time <= time) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

/** The bar a fill counts on, as the backend's position path counts it: the bar holding its minute, else the next bar
 * (a minute with no candle), else the last (after the last candle). */
export function fillIndexAt(bars: { time: number }[], time: number, intervalSeconds: number): number {
  const minute = Math.floor(time / 60) * 60;
  const index = barIndexAt(bars, minute);
  if (minute < bars[0].time) return 0;
  return bars[index].time + intervalSeconds > minute ? index : Math.min(index + 1, bars.length - 1);
}

const PING_LABEL: Record<string, string> = {
  giveback: "Give-back ping", expiry_first: "Expires-today ping", expiry_final: "30 minutes to the close ping",
  expiry_eve: "Expires-next-session ping", hold_hour: "Held an hour: re-decide ping", wrong_way: "Wrong way at 30 min ping",
  no_exit: "No exit order ping", same_day_1pm: "Same-day option at 1 PM ping", plan_nudge: "No plan yet ping",
  plan_link: "Saved plan link ping", cut_line: "Cut line ping", interrupt: "Habit ping",
};
const CUT_RULE: Record<string, string> = { deep_red: "Cut rule: deep red past the hour, sell here", past_1pm: "Cut rule: same-day option past 1 PM, sell here" };

export const money = (value: number | null | undefined) => value == null ? "–" : `${value >= 0 ? "+" : "-"}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
/** A per-contract price as the broker quotes it. */
export const quoted = (perContract: number, multiplier: number) => `$${(perContract / multiplier).toFixed(2)}`;
export const words = (value: string) => value.replaceAll("_", " ");

export function replayEvents(replay: TradeReplay): ReplayEvent[] {
  const bars = replay.bars ?? [];
  if (!bars.length) return [];
  const multiplier = replay.multiplier ?? 1;
  const out: ReplayEvent[] = [];
  for (const fill of replay.fills ?? []) {
    out.push({ index: fillIndexAt(bars, fill.time, (replay.interval_minutes ?? 1) * 60), time: fill.time, kind: "fill", tone: fill.entry ? "buy" : "sell", label: fill.label });
  }
  for (const ping of replay.pings ?? []) {
    const name = ping.title ?? PING_LABEL[ping.kind] ?? words(ping.kind);
    out.push({ index: barIndexAt(bars, ping.time), time: ping.time, kind: "ping", tone: ping.sent ? "ping" : "muted", label: ping.sent ? name : `${name} (not sent)` });
  }
  if (replay.cut) {
    out.push({ index: barIndexAt(bars, replay.cut.time), time: replay.cut.time, kind: "cut", tone: "rule",
      label: `${CUT_RULE[replay.cut.rule] ?? "Cut rule"} at ${quoted(replay.cut.price, multiplier)}` });
  }
  const crossed = replay.cut_line?.crossed;
  if (replay.cut_line && crossed) {
    const cost = crossed.state === "ignored" && crossed.cost != null && crossed.cost > 0 ? `; holding on cost ${money(-crossed.cost)}` : "";
    out.push({ index: barIndexAt(bars, crossed.time), time: crossed.time, kind: "cut_line", tone: "rule",
      label: `Cut line ${quoted(replay.cut_line.price, multiplier)} hit with ${crossed.held} open${crossed.state === "acted" ? ", sold in time" : cost}` });
  }
  return out.sort((a, b) => a.time - b.time);
}

/** Running best P&L through ``index`` (null until one is known). */
export function peakThrough(bars: TradeReplayBar[], index: number): number | null {
  let peak: number | null = null;
  for (let i = 0; i <= index && i < bars.length; i++) {
    const value = bars[i].pnl;
    if (value != null && (peak == null || value > peak)) peak = value;
  }
  return peak;
}
