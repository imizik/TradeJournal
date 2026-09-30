import { apiUrl } from "@/lib/api";

export const INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as const;
export type Interval = typeof INTERVALS[number];
export type ChartBar = {
  time: number; end_time: number; open: number; high: number; low: number; close: number; volume: number;
  source: "alpaca_sip" | "tradier";
  volumePending?: boolean;
  extended: boolean; ema9: number | null; ema20: number | null; ema50: number | null; ema200: number | null;
  vwap: number | null; rsi: number | null;
};
export type FillMarker = { id: string; time: number; label: string; buy: boolean };
export type ChartPanelData = { bars: ChartBar[]; markers: FillMarker[] };
export type HistoryPage = {
  symbol: string; interval: Interval; session: ChartSettings["session"]; before: number; limit: number;
  bars: ChartBar[]; markers: FillMarker[]; older_cursor: number | null; exhausted: boolean;
  continuation: string | null; warmup: "ready" | "pending" | "insufficient";
  source: "alpaca_sip"; price_basis: "raw"; fills_truncated: boolean;
  issue: { code: string; message: string; retry_at: number } | null;
  /** Set when a shown session was resampled with clock hours because the calendar was unavailable. */
  calendar_note?: string | null;
};
/** Today's session windows from the backend's market calendar (UTC seconds), the same ones resampling uses. */
export type MarketDay = {
  date: string; status: "open" | "closed" | "unknown"; source: string; description: string | null;
  sessions: { part: "pre" | "regular" | "post"; start: number; end: number }[]; note: string | null;
};
export type ChartQuote = {
  symbol: string; name: string; last: number | null; change: number | null;
  change_percentage: number | null; volume: number | null; previous_close: number | null; trade_time: number | null;
};
export type ChartData = {
  symbol: string; provider: string; session: "regular" | "extended"; delayed: boolean;
  refresh_seconds: number; checked_at: number; fetched_at: Record<string, number>;
  panels: Partial<Record<Interval, ChartPanelData>>; quotes: ChartQuote[]; issues: string[];
  intraday_as_of: number | null; history_note: string; fills: FillMarker[]; fills_truncated: boolean;
  market?: MarketDay;
};
export type ChartStreamTick = {
  type: "tick"; symbol: string; at: number; price: number; open: number; high: number; low: number;
  minute: number; session: "pre" | "regular" | "post";
  buckets: Partial<Record<Interval, { time: number; end_time: number; extended: boolean }>>;
};
export type PriceLevel = { id: string; price: number; label: string };
export type Indicators = Record<"ema9" | "ema20" | "ema50" | "ema200" | "vwap" | "volume" | "rsi" | "fills", boolean>;
export type SmallChartSize = "compact" | "normal" | "tall";
export type ChartSettings = {
  symbol: string; intervals: Interval[]; watchlist: string[]; session: "regular" | "extended";
  layout: "multi" | "single"; indicators: Indicators; levels: Record<string, PriceLevel[]>;
  recent: string[]; linkRange: boolean; smallSize: SmallChartSize; immersiveWatchlist: boolean;
};
export const DEFAULT_SETTINGS: ChartSettings = {
  symbol: "MRVL", intervals: ["5m", "15m", "1h", "1D", "1m"],
  watchlist: ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"],
  session: "extended", layout: "multi",
  indicators: { ema9: true, ema20: true, ema50: true, ema200: false, vwap: true, volume: true, rsi: true, fills: true },
  levels: {}, recent: [], linkRange: false, smallSize: "normal", immersiveWatchlist: false,
};
export const SMALL_HEIGHTS: Record<SmallChartSize, number> = { compact: 160, normal: 245, tall: 360 };
export const STORAGE_KEY = "tradejournal.charts.v1";
export const validSymbol = (value: string) => /^[A-Z][A-Z0-9./-]{0,14}$/.test(value);

export function restoreSettings(): ChartSettings {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (!value || typeof value !== "object") return DEFAULT_SETTINGS;
    const levels: Record<string, PriceLevel[]> = {};
    if (value.levels && typeof value.levels === "object") {
      for (const [symbol, rows] of Object.entries(value.levels)) {
        if (!validSymbol(symbol) || !Array.isArray(rows)) continue;
        levels[symbol] = rows.filter((row) => row && typeof row.id === "string" && Number.isFinite(row.price) && row.price > 0 && typeof row.label === "string")
          .slice(0, 30).map((row) => ({ id: row.id, price: row.price, label: row.label.slice(0, 30) }));
      }
    }
    return {
      ...DEFAULT_SETTINGS,
      symbol: typeof value.symbol === "string" && validSymbol(value.symbol) ? value.symbol : DEFAULT_SETTINGS.symbol,
      intervals: Array.isArray(value.intervals) && value.intervals.length === 5 && value.intervals.every((i: Interval) => INTERVALS.includes(i)) ? value.intervals : DEFAULT_SETTINGS.intervals,
      watchlist: Array.isArray(value.watchlist) ? [...new Set<string>(value.watchlist.filter((s: unknown): s is string => typeof s === "string" && validSymbol(s)))].slice(0, 30) : DEFAULT_SETTINGS.watchlist,
      session: value.session === "regular" ? "regular" : "extended",
      layout: value.layout === "single" ? "single" : "multi",
      indicators: Object.fromEntries(Object.entries(DEFAULT_SETTINGS.indicators).map(([key, fallback]) => [key, typeof value.indicators?.[key] === "boolean" ? value.indicators[key] : fallback])) as Indicators,
      levels,
      recent: Array.isArray(value.recent) ? [...new Set<string>(value.recent.filter((s: unknown): s is string => typeof s === "string" && validSymbol(s)))].slice(0, 8) : [],
      linkRange: value.linkRange === true,
      smallSize: value.smallSize === "compact" || value.smallSize === "tall" ? value.smallSize : "normal",
      immersiveWatchlist: value.immersiveWatchlist === true,
    };
  } catch { return DEFAULT_SETTINGS; }
}

export async function fetchChartData(settings: ChartSettings, signal: AbortSignal): Promise<ChartData> {
  const query = new URLSearchParams({
    symbol: settings.symbol, intervals: (settings.layout === "single" ? settings.intervals.slice(0, 1) : settings.intervals).join(","),
    watchlist: settings.watchlist.join(","), session: settings.session,
  });
  const response = await fetch(apiUrl(`/charts/workspace?${query}`), { cache: "no-store", signal });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message ?? "Unable to load chart data.");
  return body;
}

export async function fetchChartHistory({ symbol, interval, session, before, continuation, signal }: {
  symbol: string; interval: Interval; session: ChartSettings["session"]; before: number;
  continuation?: string | null; signal: AbortSignal;
}): Promise<HistoryPage> {
  const query = new URLSearchParams({ symbol, interval, session, before: String(before) });
  if (continuation) query.set("continuation", continuation);
  const response = await fetch(apiUrl(`/charts/history?${query}`), { cache: "no-store", signal });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail?.message ?? "Unable to load older candles.");
  return body;
}

export function mergeBars(older: ChartBar[], current: ChartBar[]): ChartBar[] {
  const byTime = new Map(older.map((bar) => [bar.time, bar]));
  for (const bar of current) byTime.set(bar.time, bar);
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

export function retainHistory(bars: ChartBar[], live: ChartBar[], visible: { from: number; to: number } | null, ceiling = 12000): ChartBar[] {
  const liveTimes = new Set(live.map((bar) => bar.time));
  const saved = bars.filter((bar) => !liveTimes.has(bar.time));
  const allowance = Math.max(0, ceiling - live.length);
  if (saved.length <= allowance) return saved;
  if (!visible) return saved.slice(-allowance);
  let start = 0, end = saved.length;
  while (end - start > allowance) {
    const left = Math.max(0, visible.from - saved[start].time);
    const right = Math.max(0, saved[end - 1].time - visible.to);
    if (left >= right && saved[start].time < visible.from) start++;
    else if (saved[end - 1].time > visible.to) end--;
    else break; // The visible range itself fills the ceiling.
  }
  return saved.slice(start, end);
}

export const chartStreamUrl = (symbol: string) => apiUrl(`/charts/stream?symbol=${encodeURIComponent(symbol)}`);

export function parseChartTick(value: unknown): ChartStreamTick | null {
  if (!value || typeof value !== "object") return null;
  const tick = value as Partial<ChartStreamTick>;
  if (tick.type !== "tick" || typeof tick.symbol !== "string" || !validSymbol(tick.symbol)
    || ![tick.at, tick.price, tick.open, tick.high, tick.low, tick.minute].every((part) => typeof part === "number" && Number.isFinite(part))
    || (tick.price ?? 0) <= 0 || (tick.low ?? 0) <= 0 || (tick.high ?? 0) < (tick.low ?? 0)
    || !["pre", "regular", "post"].includes(tick.session ?? "") || !tick.buckets || typeof tick.buckets !== "object") return null;
  return tick as ChartStreamTick;
}

/** Live prices move candles immediately; REST remains authoritative for volume and studies. */
export function overlayLiveTicks(data: ChartData, ticks: ChartStreamTick[], session: ChartSettings["session"]): ChartData {
  const fetched = data.fetched_at.intraday ?? 0;
  const newer = ticks.filter((tick) => tick.symbol === data.symbol && tick.at > fetched && (session === "extended" || tick.session === "regular"));
  if (!newer.length) return data;
  const panels = { ...data.panels };
  let latestMinute = data.intraday_as_of ?? 0;
  for (const interval of INTERVALS) {
    if (interval === "1D" || interval === "1W") continue;
    const panel = panels[interval];
    if (!panel) continue;
    let bars = panel.bars;
    for (const tick of newer) {
      const bucket = tick.buckets[interval];
      if (!bucket || !Number.isFinite(bucket.time) || !Number.isFinite(bucket.end_time)) continue;
      const last = bars.at(-1);
      if (last && bucket.time < last.time) continue;
      if (bars === panel.bars) bars = bars.slice();
      if (last && bucket.time === last.time) {
        bars[bars.length - 1] = { ...last, high: Math.max(last.high, tick.high), low: Math.min(last.low, tick.low), close: tick.price };
      } else {
        bars.push({ ...bucket, source: "tradier", open: tick.open, high: tick.high, low: tick.low, close: tick.price, volume: 0,
          volumePending: true,
          ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null });
        if (bars.length > 1200) bars.shift();
      }
      latestMinute = Math.max(latestMinute, tick.minute);
    }
    if (bars !== panel.bars) panels[interval] = { ...panel, bars };
  }
  return { ...data, panels, intraday_as_of: latestMinute || null };
}

export const price = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const etTime = (stamp: number, daily = false) => new Date(stamp * 1000).toLocaleString("en-US", {
  timeZone: "America/New_York", ...(daily ? { month: "short", day: "numeric", year: "numeric" } : { hour: "numeric", minute: "2-digit" }),
});
export function barAt(bars: ChartBar[], time: number): ChartBar | undefined {
  let low = 0, high = bars.length;
  while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time <= time) low = mid + 1; else high = mid; }
  const bar = bars[low - 1];
  return bar && time < bar.end_time ? bar : undefined;
}

export const INTERVAL_SECONDS: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };
export const intradayInterval = (interval: Interval) => interval !== "1D" && interval !== "1W";

const nyClock = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hourCycle: "h23", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const nyDate = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
export type SessionWindow = MarketDay["sessions"][number];
/**
 * The session windows that apply at `now`: the backend's calendar day when it
 * is for today's New York date, otherwise the clock rule the backend also falls
 * back to without a calendar (weekdays 04:00, 09:30, 16:00, 20:00).
 */
export function sessionsFor(now: number, market?: MarketDay | null): SessionWindow[] {
  if (market?.date === nyDate.format(new Date(now * 1000))) return market.sessions;
  const parts = Object.fromEntries(nyClock.formatToParts(new Date(now * 1000)).map((p) => [p.type, p.value]));
  if (parts.weekday === "Sat" || parts.weekday === "Sun") return [];
  // Weekday midnights are never DST transitions, so minute offsets are exact.
  const midnight = Math.floor(now) - (Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second));
  return ([["pre", 240, 570], ["regular", 570, 960], ["post", 960, 1200]] as const)
    .map(([part, start, end]) => ({ part, start: midnight + start * 60, end: midnight + end * 60 }));
}
export function nySession(now: number, market?: MarketDay | null): SessionWindow | null {
  return sessionsFor(now, market).find((segment) => segment.start <= now && now < segment.end) ?? null;
}

export type BarClock = { state: "live"; remaining: number } | { state: "paused" | "delayed" | "stale" | "closed" | "waiting"; remaining?: undefined };
/**
 * Seconds until the forming intraday bar closes, from the local clock and the
 * backend's session windows (holidays and early closes included). Anything
 * that would make the number misleading returns a named state instead, so no
 * provider call is needed.
 */
export function barClock({ now, interval, bars, session, market, paused, delayed, stale }: {
  now: number; interval: Interval; bars: ChartBar[] | undefined; session: ChartSettings["session"];
  market?: MarketDay | null; paused: boolean; delayed: boolean; stale: boolean;
}): BarClock | null {
  if (!intradayInterval(interval)) return null;
  if (paused) return { state: "paused" };
  if (delayed) return { state: "delayed" };
  if (stale) return { state: "stale" };
  const segment = nySession(now, market);
  if (!segment || (session === "regular" && segment.part !== "regular")) return { state: "closed" };
  const last = bars?.at(-1);
  // A halted symbol, or an open day the calendar missed, has no bars in the segment.
  if (!last || last.end_time <= segment.start) return { state: "waiting" };
  const second = Math.floor(now);
  const width = INTERVAL_SECONDS[interval];
  // Buckets anchor at the segment start and the last one ends with it (13:00 on a half day).
  const finish = Math.min(segment.start + (Math.floor((second - segment.start) / width) + 1) * width, segment.end);
  return { state: "live", remaining: Math.max(0, finish - second) };
}
/** "Early close 1:00 PM ET" when today's regular session ends before 16:00. */
export function earlyClose(market?: MarketDay | null): string | null {
  const regular = market?.status === "open" ? market.sessions.find((segment) => segment.part === "regular") : undefined;
  if (!regular || regular.end - regular.start >= 23_400) return null; // 6.5 hours is a full session
  return `Early close ${etTime(regular.end)} ET`;
}
export const countdown = (seconds: number) => {
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds / 60) % 60, s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
};

/**
 * How a new bar array relates to the one already drawn. Streamed ticks keep
 * unchanged bar objects, so the prefix check is usually reference equality;
 * REST refreshes compare values, and any changed older bar forces a reset.
 */
export function barChange(prev: ChartBar[], next: ChartBar[]): "same" | "last" | "append" | "reset" {
  if (!prev.length || !next.length) return prev.length === next.length ? "same" : "reset";
  const appended = next.length === prev.length + 1;
  if (!appended && next.length !== prev.length) return "reset";
  const stable = appended ? prev.length : prev.length - 1;
  for (let i = stable - 1; i >= 0; i--) if (!sameBar(prev[i], next[i])) return "reset";
  if (appended) return next[stable].time > prev[stable - 1].time ? "append" : "reset";
  const a = prev[stable], b = next[stable];
  if (a.time !== b.time) return "reset";
  return sameBar(a, b) ? "same" : "last";
}
const BAR_KEYS = ["time", "end_time", "source", "open", "high", "low", "close", "volume", "volumePending", "extended", "ema9", "ema20", "ema50", "ema200", "vwap", "rsi"] as const;
const sameBar = (a: ChartBar, b: ChartBar) => a === b || BAR_KEYS.every((key) => a[key] === b[key]);

export type TimeRange = { from: number; to: number };
export type RangeLink = ReturnType<typeof createRangeLink>;
/**
 * Shares a visible time range between charts. The chart the user is moving
 * owns the link briefly; echoes from charts applying its range are dropped,
 * which is what keeps five subscribers from feeding back into each other.
 */
export function createRangeLink(hold = 250) {
  const listeners = new Map<string, (range: TimeRange) => void>();
  let owner = "", ownedAt = 0;
  return {
    listen(id: string, fn: (range: TimeRange) => void) { listeners.set(id, fn); return () => { listeners.delete(id); }; },
    emit(range: TimeRange, source: string) {
      const now = performance.now();
      if (owner && owner !== source && now - ownedAt < hold) return;
      owner = source; ownedAt = now;
      listeners.forEach((fn, id) => { if (id !== source) fn(range); });
    },
  };
}

export type CrosshairLink = ReturnType<typeof createCrosshairLink>;
export function createCrosshairLink() {
  const listeners = new Set<(time: number | null, source: string) => void>();
  return {
    listen(fn: (time: number | null, source: string) => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    emit(time: number | null, source: string) { listeners.forEach((fn) => fn(time, source)); },
  };
}
