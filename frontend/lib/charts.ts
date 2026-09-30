import { apiUrl } from "@/lib/api";

export const INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as const;
export type Interval = typeof INTERVALS[number];
export type ChartBar = {
  time: number; end_time: number; open: number; high: number; low: number; close: number; volume: number;
  volumePending?: boolean;
  extended: boolean; ema9: number | null; ema20: number | null; ema50: number | null; ema200: number | null;
  vwap: number | null; rsi: number | null;
};
export type FillMarker = { id: string; time: number; label: string; buy: boolean };
export type ChartPanelData = { bars: ChartBar[]; markers: FillMarker[] };
export type ChartQuote = {
  symbol: string; name: string; last: number | null; change: number | null;
  change_percentage: number | null; volume: number | null; previous_close: number | null; trade_time: number | null;
};
export type ChartData = {
  symbol: string; provider: string; session: "regular" | "extended"; delayed: boolean;
  refresh_seconds: number; checked_at: number; fetched_at: Record<string, number>;
  panels: Partial<Record<Interval, ChartPanelData>>; quotes: ChartQuote[]; issues: string[];
  intraday_as_of: number | null; history_note: string; fills: FillMarker[]; fills_truncated: boolean;
};
export type ChartStreamTick = {
  type: "tick"; symbol: string; at: number; price: number; open: number; high: number; low: number;
  minute: number; session: "pre" | "regular" | "post";
  buckets: Partial<Record<Interval, { time: number; end_time: number; extended: boolean }>>;
};
export type PriceLevel = { id: string; price: number; label: string };
export type Indicators = Record<"ema9" | "ema20" | "ema50" | "ema200" | "vwap" | "volume" | "rsi" | "fills", boolean>;
export type ChartSettings = {
  symbol: string; intervals: Interval[]; watchlist: string[]; session: "regular" | "extended";
  layout: "multi" | "single"; indicators: Indicators; levels: Record<string, PriceLevel[]>;
};
export const DEFAULT_SETTINGS: ChartSettings = {
  symbol: "MRVL", intervals: ["5m", "15m", "1h", "1D", "1m"],
  watchlist: ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"],
  session: "extended", layout: "multi",
  indicators: { ema9: true, ema20: true, ema50: true, ema200: false, vwap: true, volume: true, rsi: true, fills: true },
  levels: {},
};
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
        bars.push({ ...bucket, open: tick.open, high: tick.high, low: tick.low, close: tick.price, volume: 0,
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

export type CrosshairLink = ReturnType<typeof createCrosshairLink>;
export function createCrosshairLink() {
  const listeners = new Set<(time: number | null, source: string) => void>();
  return {
    listen(fn: (time: number | null, source: string) => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    emit(time: number | null, source: string) { listeners.forEach((fn) => fn(time, source)); },
  };
}
