import type { ChartBar, ChartData, Interval } from "../../lib/charts";

/**
 * Deterministic, market-shaped candles for pictures a person judges by eye.
 *
 * The ordinary chart fixture is a smooth sine wave: right for asserting
 * prices, useless for judging clutter, label collisions or how price action
 * reads under the studies. This one is a seeded random walk built from one-
 * minute bars over regular sessions — overnight gaps, a busy open and a quiet
 * midday, trend days and chop, occasional jumps, U-shaped volume — aggregated
 * to every interval, with EMAs, session VWAP and Wilder RSI computed from the
 * bars, so the overlays sit where they would on a real chart. Same seed, same
 * picture; no clock involved.
 */

const SESSIONS = 260;
const LAST_SESSION_UTC = Date.UTC(2026, 9, 9); // Friday 2026-10-09
const MINUTES = 390;
const BARS = 240;
const STEP: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };

function mulberry32(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 09:30 New York on a UTC calendar date, as epoch seconds (handles DST). */
function sessionOpen(dayUtc: number) {
  const zone = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", timeZoneName: "short" })
    .formatToParts(new Date(dayUtc + 12 * 3600_000)).find((part) => part.type === "timeZoneName")?.value;
  return Math.floor(dayUtc / 1000) + 9.5 * 3600 + (zone === "EDT" ? 4 : 5) * 3600;
}

type Minute = { time: number; session: number; minute: number; open: number; high: number; low: number; close: number; volume: number };

function minutes(seed: number, start: number): Minute[] {
  const random = mulberry32(seed);
  const normal = () => Math.sqrt(-2 * Math.log(random() || 1e-12)) * Math.cos(2 * Math.PI * random());
  const days: number[] = [];
  for (let day = LAST_SESSION_UTC; days.length < SESSIONS; day -= 86400_000) {
    const weekday = new Date(day).getUTCDay();
    if (weekday !== 0 && weekday !== 6) days.unshift(day);
  }
  // Intraday volatility and volume both follow a U: busy open, quiet lunch, active close.
  const shape = (m: number) => 0.7 + 1.6 * Math.exp(-m / 25) + 0.6 * Math.exp((m - MINUTES) / 40);
  const sigma = 0.024 / Math.sqrt(MINUTES * 1.05);
  const out: Minute[] = [];
  let price = start;
  days.forEach((day, session) => {
    price *= Math.exp(normal() * 0.009); // overnight gap
    const drift = (random() - 0.5) * 0.0004 * (random() < 0.3 ? 3 : 1); // most days chop, some trend
    const open = sessionOpen(day);
    const dayVolume = 0.6 + random() * 0.9;
    for (let m = 0; m < MINUTES; m++) {
      const jump = random() < 0.002 ? normal() * sigma * 6 : 0;
      const move = drift / MINUTES * 60 + normal() * sigma * shape(m) + jump;
      const o = price;
      const c = o * Math.exp(move);
      const wick = sigma * shape(m) * o;
      out.push({ time: open + m * 60, session, minute: m, open: o, close: c,
        high: Math.max(o, c) + Math.abs(normal()) * wick * 0.6, low: Math.min(o, c) - Math.abs(normal()) * wick * 0.6,
        volume: Math.round(18000 * shape(m) * dayVolume * (1 + Math.abs(move) / sigma * 0.4) * Math.exp(normal() * 0.35)) });
      price = c;
    }
  });
  return out;
}

function aggregate(rows: Minute[], interval: Interval): Minute[] {
  const step = STEP[interval];
  const sessionsPer = interval === "1W" ? 5 : 1;
  const out: Minute[] = [];
  for (const row of rows) {
    const key = step >= 86400 ? Math.floor(row.session / sessionsPer) : row.session * 1000 + Math.floor(row.minute * 60 / step);
    const last = out.at(-1) as (Minute & { key?: number }) | undefined;
    if (last && last.key === key) {
      last.high = Math.max(last.high, row.high); last.low = Math.min(last.low, row.low);
      last.close = row.close; last.volume += row.volume;
    } else out.push(Object.assign({ ...row }, { key }));
  }
  return out;
}

function ema(values: number[], period: number) {
  const k = 2 / (period + 1);
  let value: number | null = null;
  return values.map((v, i) => (value = value === null ? v : v * k + value * (1 - k), i + 1 >= period ? value : null));
}

function rsi(values: number[], period = 14) {
  let gain = 0, loss = 0;
  return values.map((v, i) => {
    if (i === 0) return null;
    const change = v - values[i - 1];
    const up = Math.max(change, 0), down = Math.max(-change, 0);
    if (i <= period) { gain += up / period; loss += down / period; if (i < period) return null; }
    else { gain = (gain * (period - 1) + up) / period; loss = (loss * (period - 1) + down) / period; }
    return loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  });
}

const cache = new Map<string, Minute[]>();
const round = (v: number) => Math.round(v * 100) / 100;

/** Panels for `ChartData.panels`; `seed` and `start` choose the symbol's path. */
export function realisticPanels(intervals: Interval[], seed = 7, start = 96): ChartData["panels"] {
  const key = `${seed}:${start}`;
  if (!cache.has(key)) cache.set(key, minutes(seed, start));
  const base = cache.get(key)!;
  const panels: ChartData["panels"] = {};
  for (const interval of intervals) {
    const rows = interval === "1m" ? base : aggregate(base, interval);
    const closes = rows.map((r) => r.close);
    const [e9, e20, e50, e200, r14] = [ema(closes, 9), ema(closes, 20), ema(closes, 50), ema(closes, 200), rsi(closes)];
    const daily = STEP[interval] >= 86400;
    let session = -1, pv = 0, vol = 0;
    const bars = rows.map((r, i): ChartBar => {
      if (r.session !== session) { session = r.session; pv = 0; vol = 0; }
      pv += (r.high + r.low + r.close) / 3 * r.volume; vol += r.volume;
      return { time: r.time, end_time: r.time + STEP[interval], source: "alpaca_sip", extended: false,
        open: round(r.open), high: round(r.high), low: round(r.low), close: round(r.close), volume: r.volume,
        ema9: e9[i] && round(e9[i]!), ema20: e20[i] && round(e20[i]!), ema50: e50[i] && round(e50[i]!), ema200: e200[i] && round(e200[i]!),
        vwap: daily ? null : round(pv / vol), rsi: r14[i] === null ? null : Math.round(r14[i]! * 100) / 100 };
    }).slice(-BARS);
    const fill = bars[Math.floor(bars.length * 0.8)];
    const exit = bars[Math.floor(bars.length * 0.92)];
    panels[interval] = { bars, markers: [
      { id: "fill-buy", time: fill.time, label: "buy to open 1 call", buy: true },
      { id: "fill-sell", time: exit.time, label: "sell to close 1 call", buy: false },
    ] };
  }
  return panels;
}
