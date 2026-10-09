import type { ChartPosition } from "@/lib/chartJournal";
import { apiUrl } from "@/lib/api";
import { cleanDrawings, cleanToolStyles, DEFAULT_TOOL_STYLES } from "./drawings";
import type { Drawing, DrawingKind, ToolStyle } from "./drawings";
import type { Earnings } from "./symbolInfo";
import type { AlertsPayload } from "./alerts";

export const INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as const;
export type Interval = typeof INTERVALS[number];
export type ChartBar = {
  time: number; end_time: number; open: number; high: number; low: number; close: number; volume: number;
  source: "alpaca_sip" | "tradier" | "sample_fixture";
  volumePending?: boolean;
  extended: boolean; ema9: number | null; ema20: number | null; ema50: number | null; ema200: number | null;
  vwap: number | null; rsi: number | null;
  /**
   * The regular session's volume-weighted standard deviation of minute prices around VWAP
   * (C2.7's VWAP bands): null where VWAP is; absent on candles from an older build or a live tick.
   */
  vwap_sd?: number | null;
  /**
   * Relative volume (C2.4): today's regular-session volume through this candle over the
   * baseline's average through the same minute. Present on a workspace response's intraday
   * candles when the symbol trades today; null where there is none (outside regular hours,
   * no baseline yet, or too few baseline sessions had traded by then). History pages omit it.
   */
  rvol?: number | null;
};
/** One recorded split, from the provider named in `PriceAdjustment.source`. */
export type SplitRecord = { ex_date: string; ratio: number; label: string };
/**
 * The chart's single price basis: split-adjusted, built from recorded splits at
 * display time while stored bars stay raw. `unknown` means no split data was
 * available, so prices are as the provider supplied them and `warnings` says so.
 */
export type PriceAdjustment = {
  basis: "split_adjusted"; status: "ok" | "stale" | "unknown"; source: string; as_of: number | null;
  splits: SplitRecord[]; daily: Record<string, "provider_adjusted" | "adjusted_here" | "unverified">;
  dividends: "unsupported"; dividends_note: string; warnings: string[];
};
export type FillMarker = { id: string; time: number; label: string; buy: boolean };
/**
 * One automatic level (C2.1), on the chart's basis. `evidence` says what kind of
 * number it is: a provider field (observed), a formula over bars (calculated), a
 * heuristic (inferred) or a convention (assumed: signed gamma and the gamma flip,
 * C4.4). `bar_time` is the start of the bar that set it; `formed_at` is when it
 * became final, null while `developing`, for round numbers and for option strikes.
 */
export type AutoLevel = {
  kind: string; label: string; price: number; evidence: "observed" | "calculated" | "inferred" | "assumed";
  timeframe: "1m" | "1D" | null; source: "tradier" | "alpaca_sip" | null;
  bar_time: number | null; formed_at: number | null; developing: boolean;
};
/** Total span is less than one band (C2.2). `score` counts distinct origins, not independent evidence. */
export type AutoZone = { id: string; low: number; high: number; label: string; score: number; members: AutoLevel[] };
/**
 * A symbol's automatic levels for `day` (the session in progress, or the next
 * one). `band` is a tenth of the daily ATR, null without one; `missing` says
 * why a group of levels is absent.
 */
export type AutoLevels = {
  day: string; as_of: number; atr: number | null; band: number | null; zones: AutoZone[]; missing: Record<string, string>;
  session?: "regular" | "extended";
  /** False when the zones leave the automatic levels out (only options levels asked for); absent before C4.4. */
  auto?: boolean;
  /** The options levels layer (C4.4) when asked for: what its strikes are and why any are missing. */
  options?: OptionsInfo;
  /** The expected-move range bands (C2.7) when asked for: each captured straddle, or why there is none yet. */
  ranges?: RangesInfo;
};
/**
 * One expiration's at-the-money straddle (C2.7), captured once a session five minutes after
 * the open around the price then (`anchor`), and fixed for the rest of the day. `move` is the
 * straddle's mid per share; `tags` say whether it is the nearest expiration, the nearest Friday or both.
 */
export type RangeBand = {
  expiration: string; tags: ("nearest" | "friday")[]; today: boolean; anchor: number; move: number; percent: number;
  strike: number; iv: number | null; quoted_at: number | null; captured_at: number;
};
export type RangesInfo = {
  state: "ready" | "loading" | "waiting" | "closed" | "unavailable" | "none"; message: string | null;
  symbol: string; root: string; source: string; day: string; bands: RangeBand[];
};
/** Max pain (C4.7): one expiration's strike where its open contracts would pay least. Inferred. */
export type MaxPain = { price: number; expiration: string; note: string };
/** One strike's open interest and volume (observed) and dollar gamma for a 1% move (calculated), across a scope's expirations (C4.2). */
export type OptionStrike = {
  strike: number; call_oi: number | null; put_oi: number | null; call_volume: number | null; put_volume: number | null;
  call_gamma: number | null; put_gamma: number | null;
  oi_change?: { session: string | null; previous_session: string | null; status: "ready" | "unavailable"; calls?: number | null; puts?: number | null };
  /** Both sides' dollar gamma: summed, or the calls' less the puts' when signed (assumed). */
  gamma: number | null;
  /** Its place by the layer's measure on both sides together, then by each side's open interest and volume. */
  rank: number | null; call_oi_rank: number | null; put_oi_rank: number | null; call_volume_rank: number | null; put_volume_rank: number | null;
};
export type OptionsMeasure = "oi" | "volume" | "gamma";
export type OptionsScope = "nearest" | "week" | "all";
/** Where signed gamma crosses zero near the price: a model estimate on an assumed dealer side; null price when it does not cross. */
export type GammaFlip = { price: number | null; low: number; high: number; note: string; assumption: string };
export type OptionsTotals = {
  call_oi: number; put_oi: number; call_volume: number; put_volume: number;
  put_call_oi: number | null; put_call_volume: number | null; call_volume_oi: number | null; put_volume_oi: number | null;
};
/**
 * What the options levels (C4.4) or the strike ladder (C4.5) rest on. `spot` is
 * the price gamma was computed at; `fetched_at` the oldest chain's read time
 * (seconds); `greeks_updated_at` the provider's IV stamp, verbatim.
 */
export type OptionsInfo = {
  state: "ready" | "loading" | "unavailable" | "none"; message: string | null;
  symbol: string; root: string; scope: OptionsScope; source: string; spot: number | null;
  expirations: string[]; scope_note: string | null;
  mode?: OptionsMeasure; signed?: boolean;
  fetched_at?: number; last_trade_at?: number | null; greeks_updated_at?: string | null;
  excluded?: Record<string, number>; missing?: Record<string, number>; totals?: OptionsTotals;
  strikes?: OptionStrike[]; flip?: GammaFlip | null;
  /** The scope's nearest expiration's max pain (C4.7); absent before it, null without open interest. */
  max_pain?: MaxPain | null;
  max_pain_reason?: string | null;
};
export type OptionsLadder = OptionsInfo & {
  signed: boolean; rows: OptionStrike[];
  walls: Partial<Record<"call_oi" | "put_oi" | "call_volume" | "put_volume", number | null>>;
};
export type LevelEvent = { event: "tested" | "approached" | "broken" | "reclaimed"; time: number; bar_time?: number; direction?: "above" | "below" };
/** How price treated a zone today on one intraday panel's closed bars (C2.3). */
export type LevelInteraction = {
  state: "untested" | "touched" | "approached" | "tested" | "broken" | "reclaimed" | "developing";
  events: LevelEvent[]; at_level: boolean; near_level?: boolean; since?: number;
  last_close?: number | null; last_close_at?: number | null;
};
/**
 * What today's relative volume is measured against (C2.4): the market calendar's 20
 * sessions before `day`, of which `traded` had regular-session volume. Only `ready`
 * has candle values; otherwise `message` says why and `missing` lists sessions not stored yet.
 */
export type RvolBaseline = {
  state: "ready" | "building" | "insufficient" | "unavailable"; day: string; sessions: string[];
  traded: number; missing: string[]; message: string | null;
};
/** `level_events` (intraday panels of a workspace response): each automatic zone's interactions, by zone id. */
export type ChartPanelData = { bars: ChartBar[]; markers: FillMarker[]; level_events?: Record<string, LevelInteraction> };
export type HistoryPage = {
  symbol: string; interval: Interval; session: ChartSettings["session"]; before: number; limit: number;
  bars: ChartBar[]; markers: FillMarker[]; older_cursor: number | null; exhausted: boolean;
  continuation: string | null; warmup: "ready" | "pending" | "insufficient";
  source: "alpaca_sip" | "tradier"; price_basis: "split_adjusted"; adjustment: PriceAdjustment; fills_truncated: boolean;
  /** Daily and weekly pages: the date of the earliest bar Tradier holds (not the listing date). */
  history_start?: string | null;
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
  symbol: string; name: string; instrument_type?: string; last: number | null; change: number | null;
  change_percentage: number | null; volume: number | null; previous_close: number | null;
  /** Tradier's explicit current regular-session close; null until it is known. */
  regular_close?: number | null; trade_time: number | null;
  day_high?: number | null; day_low?: number | null; week_52_high?: number | null; week_52_low?: number | null;
};
/** One symbol's candles in a workspace response. */
export type SymbolPanels = {
  panels: Partial<Record<Interval, ChartPanelData>>; fetched_at: Record<string, number>;
  intraday_as_of: number | null; issues: string[];
  /** Fill markers stop at the newest 1,000 in the window; the chart says so. */
  fills_truncated?: boolean;
  adjustment?: PriceAdjustment | null;
  /** Absent from a backend older than C2.3. */
  auto_levels?: AutoLevels | null;
  /** Today's relative-volume baseline; null on a day with no session, absent from a backend older than C2.4. */
  rvol?: RvolBaseline | null;
  /** The symbol's earnings from the backend's cache (C2.5); absent from a backend older than C2.5. */
  earnings?: Earnings | null;
  /** Open trades on the symbol (C3.2); absent from a backend older than C3.2. */
  positions?: ChartPosition[];
};
export type ChartData = SymbolPanels & {
  sample_data?: boolean;
  symbol: string; provider: string; session: "regular" | "extended"; delayed: boolean;
  refresh_seconds: number; checked_at: number; quotes: ChartQuote[];
  history_note: string; fills: FillMarker[]; fills_truncated: boolean;
  market?: MarketDay;
  /** Symbols that panels hold on their own (C7.1), without quotes. */
  extras?: Record<string, SymbolPanels>;
  /** Every level alert (C5.1); absent from a backend older than C5.1. */
  alerts?: AlertsPayload;
};
export type ChartStreamTick = {
  type: "tick"; symbol: string; at: number; price: number; open: number; high: number; low: number;
  minute: number; session: "pre" | "regular" | "post";
  buckets: Partial<Record<Interval, { time: number; end_time: number; extended: boolean }>>;
};
/**
 * `drawn_on` is the New York date the price was seen; levels saved before C0.6
 * have none. A level without `color` draws in the default blue; `hidden` and
 * `locked` (C1.3) are present only when set, so older levels keep their shape.
 */
export type PriceLevel = { id: string; price: number; label: string; drawn_on?: string; color?: string; hidden?: boolean; locked?: boolean };
export const LEVEL_LABEL_MAX = 30;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const COLOR = /^#[0-9a-f]{6}$/;
/** A level in the one shape the workspace saves and compares, or null if it is not one the page could have made. */
export function cleanLevel(row: unknown): PriceLevel | null {
  const value = row as Partial<PriceLevel> | null;
  if (!value || typeof value.id !== "string" || typeof value.price !== "number" || !Number.isFinite(value.price) || value.price <= 0 || typeof value.label !== "string") return null;
  return {
    id: value.id, price: value.price, label: value.label.slice(0, LEVEL_LABEL_MAX),
    ...(typeof value.drawn_on === "string" && DAY.test(value.drawn_on) ? { drawn_on: value.drawn_on } : {}),
    ...(typeof value.color === "string" && COLOR.test(value.color) ? { color: value.color } : {}),
    ...(value.hidden === true ? { hidden: true } : {}),
    ...(value.locked === true ? { locked: true } : {}),
  };
}
export const todayNewYork = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
/** The splits that decide where a level sits, as a comparable string. */
export const splitsKey = (adjustment?: PriceAdjustment | null) => adjustment?.splits.map((s) => `${s.ex_date}:${s.ratio}`).join(",") ?? "";
/**
 * A saved level on the adjusted basis. Levels hold the price the user saw on
 * `drawn_on`; every recorded split after that date moves it by the same ratio
 * the candles moved by. A level without a date is shown as saved.
 */
export function levelOnBasis(level: PriceLevel, splits: { ex_date: string; ratio: number }[]): { price: number; moved: boolean } {
  if (!level.drawn_on) return { price: level.price, moved: false };
  const factor = splits.reduce((product, s) => s.ex_date > level.drawn_on! ? product * s.ratio : product, 1);
  return { price: level.price / factor, moved: factor !== 1 };
}
export type Indicators = Record<"ema9" | "ema20" | "ema50" | "ema200" | "vwap" | "volume" | "rsi" | "fills", boolean>;
/** The user's levels and drawings, each hidden from every chart at once (C1.3). */
export type HiddenGroups = Record<"levels" | "drawings", boolean>;
export const LAYER_GROUPS = ["levels", "drawings"] as const;
/** The studies the Indicators group hides together; fill arrows are the Journal group. */
export const STUDIES = ["ema9", "ema20", "ema50", "ema200", "vwap", "volume", "rsi"] as const;
/** What the charts draw: with the Indicators group hidden every study is off, and each one's own setting is kept for when it shows again. */
export const shownIndicators = (indicators: Indicators, groupHidden: boolean): Indicators =>
  groupHidden ? { ...indicators, ...Object.fromEntries(STUDIES.map((key) => [key, false])) } : indicators;
export type SmallChartSize = "compact" | "normal" | "tall";
/**
 * How a wide screen shares the chart grid (C7.4): the smaller row's share of
 * the height the main chart and that row split, and each smaller chart's share
 * of the row's width (four, summing to 1). A phone ignores them and keeps its
 * S/M/L heights.
 */
export type Proportions = { lower: number; columns: number[] };
/** The smaller row's share, at least and at most; the screen's own minimum sizes apply on top. */
export const LOWER_SHARE = { min: 0.15, max: 0.6 } as const;
/** No smaller chart narrower than this share of the row. */
export const COLUMN_MIN = 0.1;
/** On screen, in pixels: the main chart (C7.3's minimum), a smaller chart with its header, and a smaller chart's width. */
export const MAIN_MIN_PX = 320;
export const LOWER_MIN_PX = 180;
export const COLUMN_MIN_PX = 160;
/**
 * The smaller row's share that reproduces C7.3's S/M/L heights (226, 311 and
 * 426px with headers) in a 1440×900 window, whose grid gives 823px to the two
 * rows. A layout saved before C7.4 opens at the size it had.
 */
export const SMALL_SHARES: Record<SmallChartSize, number> = { compact: 0.275, normal: 0.378, tall: 0.518 };
const EQUAL_COLUMNS = [0.25, 0.25, 0.25, 0.25];
export const DEFAULT_PROPORTIONS: Proportions = { lower: SMALL_SHARES.normal, columns: EQUAL_COLUMNS };
const thousandths = (value: number) => Math.round(value * 1000) / 1000;
/**
 * Proportions from outside this code, kept to what the dividers can make: the
 * row share clamped into range, the columns scaled to sum to 1 with none under
 * `COLUMN_MIN`, everything to three decimals so equal sizes compare equal.
 * No usable row share means none at all (null: follow the S/M/L size);
 * unusable columns become equal ones.
 */
export function cleanProportions(value: unknown): Proportions | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const { lower, columns } = value as { lower?: unknown; columns?: unknown };
  if (typeof lower !== "number" || !Number.isFinite(lower)) return null;
  return { lower: thousandths(Math.min(LOWER_SHARE.max, Math.max(LOWER_SHARE.min, lower))), columns: cleanColumns(columns) };
}
function cleanColumns(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 4 || !value.every((share) => typeof share === "number" && Number.isFinite(share) && share >= 0)) return EQUAL_COLUMNS;
  const total = value.reduce((sum, share) => sum + share, 0);
  if (total <= 0) return EQUAL_COLUMNS;
  const raw = value.map((share) => share / total);
  // Lift any column under the minimum, taking the difference from the others in proportion to how far each is above it.
  const short = raw.reduce((sum, share) => sum + Math.max(0, COLUMN_MIN - share), 0);
  const spare = raw.reduce((sum, share) => sum + Math.max(0, share - COLUMN_MIN), 0);
  const fair = short ? raw.map((share) => share <= COLUMN_MIN ? COLUMN_MIN : share - short * (share - COLUMN_MIN) / spare) : raw;
  const rounded = fair.map(thousandths);
  // Rounding leaves at most a few thousandths over or under 1: the widest column absorbs it.
  const widest = rounded.indexOf(Math.max(...rounded));
  rounded[widest] = thousandths(rounded[widest] + 1 - rounded.reduce((sum, share) => sum + share, 0));
  return rounded;
}
/** The proportions an arrangement shows: its own, or those matching its S/M/L size when it has none (saved before C7.4). */
export const sizesOf = ({ proportions, smallSize }: { proportions?: Proportions | null; smallSize: SmallChartSize }): Proportions =>
  proportions ?? { lower: SMALL_SHARES[smallSize], columns: EQUAL_COLUMNS };
/** The smaller row's share that leaves both rows their minimum on screen, given the height they split; null when they cannot both fit. */
export function lowerLimits(space: number): { min: number; max: number } | null {
  const min = Math.max(LOWER_SHARE.min, LOWER_MIN_PX / space);
  const max = Math.min(LOWER_SHARE.max, (space - MAIN_MIN_PX) / space);
  return space > 0 && min <= max ? { min, max } : null;
}
/** The narrowest a smaller chart may be dragged, in pixels, given the four charts' total width. */
export const columnMinPx = (total: number) => Math.max(COLUMN_MIN_PX, COLUMN_MIN * total);
/** The side dock's width on a wide screen (per device): bounds and default, and the chart grid it must leave. */
export const DOCK_WIDTH = { min: 200, max: 480, default: 256 } as const;
export const GRID_MIN_PX = 640;
/**
 * How the panels are arranged, and nothing about what they show beyond the
 * symbols panels hold: the main symbol, levels, watchlist and indicators belong
 * to the workspace, so switching layouts never moves them. Keys match
 * `ChartSettings` so an arrangement spreads straight into it. `proportions` is
 * C7.4's: a saved layout keeps them beside itself, in `layoutProportions`.
 */
export type Arrangement = {
  layout: "multi" | "single"; intervals: Interval[]; panelSymbols: (string | null)[]; smallSize: SmallChartSize; linkRange: boolean;
  proportions?: Proportions | null;
};
/**
 * A named arrangement ("0DTE SPY", "Names"), saved with the workspace. Saved
 * exactly as C7.2 saved one, so a tab still on an older build keeps it.
 */
export type SavedLayout = Omit<Arrangement, "proportions"> & { id: string; name: string };
export type ChartSettings = {
  symbol: string; intervals: Interval[]; watchlist: string[]; session: "regular" | "extended";
  /** Per panel, aligned with `intervals`: a symbol the panel holds, or null to follow `symbol`. The main panel always follows. */
  panelSymbols: (string | null)[];
  layout: "multi" | "single"; indicators: Indicators; levels: Record<string, PriceLevel[]>;
  /** Rays, trend lines, zones and notes per symbol (C1.2). */
  drawings: Record<string, Drawing[]>;
  /** The style each drawing tool last used, so the next one starts there. */
  toolStyles: Record<DrawingKind, ToolStyle>;
  /** Snap placed and dragged anchors to the nearest open, high, low or close. */
  magnet: boolean;
  /** Groups hidden from every chart, from the chart menu's Layers (C1.3). */
  hiddenGroups: HiddenGroups;
  /**
   * The Indicators group hidden from every chart (C1.4). A field of its own, not
   * a `hiddenGroups` key: a tab on an older build saves `hiddenGroups` whole and
   * would drop a key it does not know, while the server keeps a field left out.
   */
  studiesHidden: boolean;
  /** Automatic levels hidden from every chart (C2.3); a field of its own for the same reason. */
  autoLevelsHidden: boolean;
  /** The options levels layer (C4.4): off until asked for, and its filters. */
  optionsLayer: OptionsLayer;
  /** The range bands (C2.7): expected-move levels and VWAP ±1σ/±2σ, off until shown; a field of its own like `autoLevelsHidden`. */
  rangeBandsHidden: boolean;
  recent: string[]; linkRange: boolean; smallSize: SmallChartSize;
  /**
   * Full screen's dock as C7.3 shared it. Since C7.4 each device keeps its own
   * choice; this is read once to seed it and left alone for older tabs.
   */
  immersiveWatchlist: boolean;
  layouts: SavedLayout[];
  /** The chart grid's shares on a wide screen (C7.4); null follows `smallSize`, as before C7.4. */
  proportions: Proportions | null;
  /**
   * Each saved layout's proportions, by layout id. Kept beside the layouts, not
   * in them: the server keeps a top-level field a save leaves out, while a tab on
   * an older build rebuilds every layout from the keys it knows.
   */
  layoutProportions: Record<string, Proportions>;
};
/**
 * The options levels layer (C4.4): hidden until asked for. `mode` ranks strikes by
 * open interest, volume or gamma; `scope` is the nearest expiration (0DTE when it
 * is today's), the nearest one's week, or every one within 45 days; `nearest` is
 * how many option zones each side of the price draw besides the walls; `signed`
 * gives gamma an assumed dealer side and, on SPY, QQQ and SPX, the gamma flip.
 */
export type OptionsLayer = { hidden: boolean; mode: OptionsMeasure; scope: OptionsScope; nearest: number; signed: boolean };
export const OPTIONS_NEAREST = { min: 1, max: 5 } as const;
export const DEFAULT_OPTIONS_LAYER: OptionsLayer = { hidden: true, mode: "oi", scope: "week", nearest: 3, signed: false };
export function cleanOptionsLayer(input: unknown): OptionsLayer {
  const value = (input && typeof input === "object" ? input : {}) as Partial<Record<keyof OptionsLayer, unknown>>;
  const nearest = Number(value.nearest);
  return {
    hidden: value.hidden !== false,
    mode: value.mode === "volume" || value.mode === "gamma" ? value.mode : "oi",
    scope: value.scope === "nearest" || value.scope === "all" ? value.scope : "week",
    nearest: Number.isInteger(nearest) && nearest >= OPTIONS_NEAREST.min && nearest <= OPTIONS_NEAREST.max ? nearest : DEFAULT_OPTIONS_LAYER.nearest,
    signed: value.signed === true,
  };
}
/** The workspace's `options` query for a shown layer (measure, scope, signed), or null while it is hidden. Only gamma has a sign. */
export const optionsQuery = (layer: OptionsLayer) => layer.hidden ? null : `${layer.mode}.${layer.scope}.${layer.signed && layer.mode === "gamma" ? 1 : 0}`;

export const DEFAULT_SETTINGS: ChartSettings = {
  symbol: "MRVL", intervals: ["5m", "15m", "1h", "1D", "1m"], panelSymbols: [null, null, null, null, null],
  watchlist: ["SPY", "QQQ", "MRVL", "NVDA", "AMD", "AAPL", "META", "MSFT"],
  session: "extended", layout: "multi",
  indicators: { ema9: true, ema20: true, ema50: true, ema200: false, vwap: true, volume: true, rsi: true, fills: true },
  levels: {}, drawings: {}, toolStyles: DEFAULT_TOOL_STYLES, magnet: false, hiddenGroups: { levels: false, drawings: false }, studiesHidden: false, autoLevelsHidden: false,
  optionsLayer: DEFAULT_OPTIONS_LAYER, rangeBandsHidden: true, recent: [], linkRange: false, smallSize: "normal", immersiveWatchlist: false, layouts: [],
  proportions: null, layoutProportions: {},
};
export const SMALL_HEIGHTS: Record<SmallChartSize, number> = { compact: 160, normal: 245, tall: 360 };
export const STORAGE_KEY = "tradejournal.charts.v1";
export const validSymbol = (value: string) => /^[A-Z][A-Z0-9./-]{0,14}$/.test(value);
/** Panels may hold two symbols besides the main one: each costs its own chart-feed reads. */
export const MAX_HELD_SYMBOLS = 2;
export const heldSymbols = (panelSymbols: (string | null)[]) => [...new Set(panelSymbols.filter((s): s is string => !!s))];
/** The most layouts this page lets you save. */
export const MAX_LAYOUTS = 12;
/**
 * Two devices that each save a layout at the limit leave more than `MAX_LAYOUTS`.
 * Merging and reading keep those (the menu shows the overflow and asks for a
 * deletion) rather than dropping a layout someone saved; past this a document is
 * runaway and the tail is ignored.
 */
export const MAX_KEPT_LAYOUTS = MAX_LAYOUTS * 2;
export const LAYOUT_NAME_MAX = 30;

/** Settings from outside this code (browser storage, the server), with anything malformed replaced by its default. */
export function sanitizeSettings(input: unknown): ChartSettings {
  try {
    const value = JSON.parse(JSON.stringify(input ?? null)); // a detached copy, checked field by field below
    if (!value || typeof value !== "object" || Array.isArray(value)) return DEFAULT_SETTINGS;
    const levels: Record<string, PriceLevel[]> = {};
    if (value.levels && typeof value.levels === "object") {
      for (const [symbol, rows] of Object.entries(value.levels)) {
        if (!validSymbol(symbol) || !Array.isArray(rows)) continue;
        levels[symbol] = rows.map(cleanLevel).filter((row): row is PriceLevel => !!row).slice(0, 30);
      }
    }
    const layouts = sanitizeLayouts(value.layouts);
    return {
      ...DEFAULT_SETTINGS,
      symbol: typeof value.symbol === "string" && validSymbol(value.symbol) ? value.symbol : DEFAULT_SETTINGS.symbol,
      intervals: Array.isArray(value.intervals) && value.intervals.length === 5 && value.intervals.every((i: Interval) => INTERVALS.includes(i)) ? value.intervals : DEFAULT_SETTINGS.intervals,
      panelSymbols: sanitizePanelSymbols(value.panelSymbols),
      watchlist: Array.isArray(value.watchlist) ? [...new Set<string>(value.watchlist.filter((s: unknown): s is string => typeof s === "string" && validSymbol(s)))].slice(0, 30) : DEFAULT_SETTINGS.watchlist,
      session: value.session === "regular" ? "regular" : "extended",
      layout: value.layout === "single" ? "single" : "multi",
      indicators: Object.fromEntries(Object.entries(DEFAULT_SETTINGS.indicators).map(([key, fallback]) => [key, typeof value.indicators?.[key] === "boolean" ? value.indicators[key] : fallback])) as Indicators,
      levels,
      drawings: cleanDrawings(value.drawings, validSymbol),
      toolStyles: cleanToolStyles(value.toolStyles),
      magnet: value.magnet === true,
      hiddenGroups: { levels: value.hiddenGroups?.levels === true, drawings: value.hiddenGroups?.drawings === true },
      studiesHidden: value.studiesHidden === true,
      autoLevelsHidden: value.autoLevelsHidden === true,
      optionsLayer: cleanOptionsLayer(value.optionsLayer),
      rangeBandsHidden: value.rangeBandsHidden !== false,
      recent: Array.isArray(value.recent) ? [...new Set<string>(value.recent.filter((s: unknown): s is string => typeof s === "string" && validSymbol(s)))].slice(0, 8) : [],
      linkRange: value.linkRange === true,
      smallSize: value.smallSize === "compact" || value.smallSize === "tall" ? value.smallSize : "normal",
      immersiveWatchlist: value.immersiveWatchlist === true,
      layouts,
      proportions: cleanProportions(value.proportions),
      layoutProportions: cleanLayoutProportions(value.layoutProportions, layouts),
    };
  } catch { return DEFAULT_SETTINGS; }
}

const isInterval = (value: unknown): value is Interval => INTERVALS.includes(value as Interval);

/**
 * Saved layouts from outside this code. A layout whose arrangement is not exactly
 * one the page could have saved is dropped whole: repairing it would let a click
 * apply, and the next save keep, an arrangement nobody made. Only the name is
 * normalized (spacing, length) and made unique, which changes nothing about what
 * applying the layout does.
 */
function sanitizeLayouts(value: unknown): SavedLayout[] {
  if (!Array.isArray(value)) return [];
  const ids = new Set<string>();
  const out: SavedLayout[] = [];
  for (const row of value) {
    if (out.length >= MAX_KEPT_LAYOUTS) break;
    if (!row || typeof row !== "object") continue;
    const name = typeof row.name === "string" ? layoutName(row.name) : "";
    const arrangement = savedArrangement(row);
    if (!name || !arrangement || typeof row.id !== "string" || !row.id || row.id.length > 64 || ids.has(row.id)) continue;
    ids.add(row.id);
    out.push({ id: row.id, name, ...arrangement });
  }
  return uniqueLayoutNames(out);
}

/** Saved layouts' proportions, for layouts that exist; one an older tab deleted lets its proportions go. */
export function cleanLayoutProportions(value: unknown, layouts: SavedLayout[]): Record<string, Proportions> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const ids = new Set(layouts.map((layout) => layout.id));
  return Object.fromEntries(Object.entries(value).filter(([id]) => ids.has(id))
    .map(([id, row]) => [id, cleanProportions(row)] as const).filter((entry): entry is [string, Proportions] => !!entry[1]));
}

/** An arrangement exactly as the page saves one (main panel following, at most two held symbols), or null. */
function savedArrangement({ layout, intervals, panelSymbols, smallSize, linkRange }: Record<string, unknown>): Arrangement | null {
  if ((layout !== "multi" && layout !== "single") || (smallSize !== "compact" && smallSize !== "normal" && smallSize !== "tall") || typeof linkRange !== "boolean"
    || !Array.isArray(intervals) || intervals.length !== 5 || !intervals.every(isInterval)
    || !Array.isArray(panelSymbols) || panelSymbols.length !== 5 || panelSymbols[0] !== null
    || !panelSymbols.every((symbol) => symbol === null || (typeof symbol === "string" && validSymbol(symbol)))
    || heldSymbols(panelSymbols).length > MAX_HELD_SYMBOLS) return null;
  return { layout, intervals, panelSymbols, smallSize, linkRange };
}

/** A layout name as saved: single-spaced and short. Empty means unusable. */
export const layoutName = (input: string) => input.replace(/\s+/g, " ").trim().slice(0, LAYOUT_NAME_MAX);
const sameName = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
export const nameTaken = (layouts: SavedLayout[], name: string, exceptId?: string) => layouts.some((layout) => layout.id !== exceptId && sameName(layout.name, name));

/**
 * Two devices can each save a layout under one name before either sees the
 * other's. Names identify layouts to the person choosing, so the later one in
 * the list becomes "Name (2)". Idempotent: unique names pass through unchanged.
 */
export function uniqueLayoutNames(layouts: SavedLayout[]): SavedLayout[] {
  const taken: string[] = [];
  return layouts.map((layout) => {
    let name = layout.name;
    for (let n = 2; taken.some((other) => sameName(other, name)); n++) {
      const suffix = ` (${n})`;
      name = `${layout.name.slice(0, LAYOUT_NAME_MAX - suffix.length)}${suffix}`;
    }
    taken.push(name);
    return name === layout.name ? layout : { ...layout, name };
  });
}

/** A layout's keys as C7.2 saved them, in a fixed order: what goes in the saved list. */
export const layoutKeys = ({ layout, intervals, panelSymbols, smallSize, linkRange }: Arrangement): Omit<Arrangement, "proportions"> =>
  ({ layout, intervals, panelSymbols, smallSize, linkRange });
/** The current arrangement with the proportions it shows, keys in a fixed order so equal arrangements compare equal as text. */
export const arrangementOf = (arrangement: Arrangement): Required<Arrangement> => ({ ...layoutKeys(arrangement), proportions: sizesOf(arrangement) });
export const sameArrangement = (a: Arrangement, b: Arrangement) => JSON.stringify(arrangementOf(a)) === JSON.stringify(arrangementOf(b));
/** A saved layout with its proportions (none for one saved before C7.4, or by an older tab). */
export const layoutWithSizes = (settings: ChartSettings, layout: SavedLayout): SavedLayout & Arrangement => ({ ...layout, proportions: settings.layoutProportions[layout.id] ?? null });
/** The saved layout the panels are arranged as right now, if any; editing a panel or dragging a divider afterwards leaves none. */
export const activeLayout = (settings: ChartSettings) => settings.layouts.find((layout) => sameArrangement(layoutWithSizes(settings, layout), settings));
/** Switching layouts changes how panels are arranged and leaves the main symbol, levels and watchlist where they are. */
export const applyLayout = (settings: ChartSettings, layout: SavedLayout): ChartSettings => ({ ...settings, ...arrangementOf(layoutWithSizes(settings, layout)) });
/** Save the current arrangement as layout `id` (a new one, or one replaced), its proportions beside it. */
export const storeLayout = (settings: ChartSettings, id: string, name: string): Pick<ChartSettings, "layouts" | "layoutProportions"> => {
  const saved = { id, name, ...layoutKeys(settings) };
  const exists = settings.layouts.some((layout) => layout.id === id);
  return { layouts: exists ? settings.layouts.map((layout) => layout.id === id ? saved : layout) : [...settings.layouts, saved],
    layoutProportions: { ...settings.layoutProportions, [id]: sizesOf(settings) } };
};
/** "5m | 15m | 1h | 1D | 1m · SPY, QQQ" (just the main chart's interval for a single chart). */
export const layoutSummary = (layout: Arrangement) => {
  const held = heldSymbols(layout.panelSymbols);
  return `${layout.intervals.slice(0, layout.layout === "single" ? 1 : 5).join(" | ")}${held.length ? ` · ${held.join(", ")}` : ""}`;
};

function sanitizePanelSymbols(value: unknown): (string | null)[] {
  const kept = new Set<string>();
  return Array.from({ length: 5 }, (_, index) => {
    const symbol = Array.isArray(value) ? value[index] : null;
    if (index === 0 || typeof symbol !== "string" || !validSymbol(symbol)) return null;
    if (!kept.has(symbol) && kept.size >= MAX_HELD_SYMBOLS) return null;
    kept.add(symbol);
    return symbol;
  });
}

/**
 * Make panel `index` the main chart. The intervals swap; a symbol the panel
 * holds becomes the main symbol, and the panel keeps the previous main symbol.
 * Panels that held the new main symbol now simply follow it.
 */
export function focusPanel(settings: ChartSettings, index: number): ChartSettings {
  const intervals = [...settings.intervals];
  [intervals[0], intervals[index]] = [intervals[index], intervals[0]];
  const held = settings.panelSymbols[index];
  if (!held || held === settings.symbol) return { ...settings, intervals };
  return { ...settings, intervals, symbol: held,
    panelSymbols: settings.panelSymbols.map((other, i) => i === index ? settings.symbol : other === held ? null : other),
    recent: [settings.symbol, ...settings.recent.filter((r) => r !== settings.symbol && r !== held)].slice(0, 8) };
}

/** `extras` lists the intervals each symbol held by a panel needs. */
/**
 * `options` asks for the options levels layer (`optionsQuery`) and `ranges` for the range bands (C2.7);
 * with either, `auto: false` leaves the automatic levels out of the zones.
 */
export async function fetchChartData({ symbol, intervals, watchlist, session, extras, options = null, ranges = false, auto = true }: {
  symbol: string; intervals: Interval[]; watchlist: string[]; session: ChartSettings["session"]; extras: Record<string, Interval[]>;
  options?: string | null; ranges?: boolean; auto?: boolean;
}, signal: AbortSignal): Promise<ChartData> {
  const query = new URLSearchParams({ symbol, intervals: intervals.join(","), watchlist: watchlist.join(","), session });
  const held = Object.entries(extras).map(([name, frames]) => `${name}:${frames.join(".")}`).join(",");
  if (held) query.set("extras", held);
  if (options) query.set("options", options);
  if (ranges) query.set("ranges", "1");
  if ((options || ranges) && !auto) query.set("auto", "0");
  const response = await fetch(apiUrl(`/charts/workspace?${query}`), { cache: "no-store", signal });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message ?? "Unable to load chart data.");
  return body;
}

/** The strike ladder (C4.5) around `spot`, the chart's latest price. */
export async function fetchOptionsLadder({ symbol, scope, signed, spot }: { symbol: string; scope: OptionsScope; signed: boolean; spot: number | null }, signal: AbortSignal): Promise<OptionsLadder> {
  const query = new URLSearchParams({ scope, signed: signed ? "1" : "0" });
  if (spot && spot > 0) query.set("spot", String(spot));
  const response = await fetch(apiUrl(`/charts/options/${encodeURIComponent(symbol)}/ladder?${query}`), { cache: "no-store", signal });
  if (!response.ok) throw new Error("The strike ladder is unavailable. Try again.");
  return response.json();
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

export const chartStreamUrl = (symbols: string[]) => apiUrl(`/charts/stream?symbols=${encodeURIComponent(symbols.join(","))}`);

/** Resolve a validated timestamp against the same New York session windows supplied by the backend. */
export function marketSessionAt(stamp: number | null | undefined, market?: MarketDay): "pre" | "regular" | "post" | null {
  if (stamp == null || !Number.isFinite(stamp) || !market) return null;
  return market.sessions.find((part) => stamp >= part.start && stamp < part.end)?.part ?? null;
}

/** Extended-hours percent only uses a timestamped trade and its session's explicit close reference. */
export function sessionChange(priceValue: number | null | undefined, session: "pre" | "regular" | "post" | null,
  quote: ChartQuote | undefined): number | null {
  if (!session) return null;
  const reference = session === "post" ? quote?.regular_close : quote?.previous_close;
  return priceValue != null && priceValue > 0 && reference != null && reference > 0
    ? (priceValue / reference - 1) * 100 : null;
}

/**
 * A quote's change when no trade is fresh: in pre- or postmarket, by the same
 * rule as a trade (`sessionChange`); otherwise its last regular-session price
 * against the previous close, else Tradier's own day change. After the close
 * this is the day's closing change.
 */
export function quoteChange(quote: ChartQuote | undefined, session: "pre" | "regular" | "post" | null): number | null {
  if (!quote) return null;
  if (session === "pre" || session === "post") return sessionChange(quote.last, session, quote);
  return quote.last != null && quote.last > 0 && quote.previous_close != null && quote.previous_close > 0
    ? (quote.last / quote.previous_close - 1) * 100 : quote.change_percentage;
}

export function parseChartTick(value: unknown): ChartStreamTick | null {
  if (!value || typeof value !== "object") return null;
  const tick = value as Partial<ChartStreamTick>;
  if (tick.type !== "tick" || typeof tick.symbol !== "string" || !validSymbol(tick.symbol)
    || ![tick.at, tick.price, tick.open, tick.high, tick.low, tick.minute].every((part) => typeof part === "number" && Number.isFinite(part))
    || (tick.price ?? 0) <= 0 || (tick.low ?? 0) <= 0 || (tick.high ?? 0) < (tick.low ?? 0)
    || !["pre", "regular", "post"].includes(tick.session ?? "") || !tick.buckets || typeof tick.buckets !== "object") return null;
  return tick as ChartStreamTick;
}

/** What a streamed trade is applied against: the REST snapshot it must be newer than, in the selected session. */
export type TickScope = { symbol: string; fetched: number; session: ChartSettings["session"] };
export const liveTick = (tick: ChartStreamTick, scope: TickScope) =>
  tick.symbol === scope.symbol && tick.at > scope.fetched && (scope.session === "extended" || tick.session === "regular");

/**
 * Live prices move one panel's candles immediately; REST remains authoritative
 * for volume and studies. Returns `bars` itself when no tick changes a candle,
 * so a panel whose candles did not move does not re-render. The 15-second REST
 * refresh replaces the base, so streamed candles never accumulate.
 */
export function applyTicks(bars: ChartBar[], ticks: ChartStreamTick[], interval: Interval, scope: TickScope): ChartBar[] {
  if (!intradayInterval(interval)) return bars;
  let out = bars;
  for (const tick of ticks) {
    const bucket = tick.buckets[interval];
    if (!liveTick(tick, scope) || !bucket || !Number.isFinite(bucket.time) || !Number.isFinite(bucket.end_time)) continue;
    const last = out.at(-1);
    if (last && bucket.time < last.time) continue;
    if (last && bucket.time === last.time) {
      const high = Math.max(last.high, tick.high), low = Math.min(last.low, tick.low);
      if (high === last.high && low === last.low && tick.price === last.close) continue;
      if (out === bars) out = bars.slice();
      out[out.length - 1] = { ...last, high, low, close: tick.price };
    } else {
      if (out === bars) out = bars.slice();
      out.push({ ...bucket, source: "tradier", open: tick.open, high: tick.high, low: tick.low, close: tick.price, volume: 0,
        volumePending: true,
        ema9: null, ema20: null, ema50: null, ema200: null, vwap: null, rsi: null });
    }
  }
  return out;
}

/** The selected symbol's headline price: a newer streamed trade, then a newer extended-hours candle, then the quote. */
export function shownPrice({ tick, quote, candle, scope }: {
  tick: ChartStreamTick | undefined; quote: ChartQuote | undefined; candle: ChartBar | undefined; scope: TickScope;
}): { price: number | null | undefined; source: string; at: number | null | undefined } {
  if (tick && liveTick(tick, scope)) return { price: tick.price, source: "Live trade", at: tick.at };
  if (scope.session === "extended" && candle?.extended && candle.time > (quote?.trade_time ?? 0))
    return { price: candle.close, source: "Extended-hours candle", at: candle.time };
  return { price: quote?.last, source: "Tradier quote", at: quote?.trade_time };
}

/** Intraday candles older than 45 seconds read as stale: the countdown and status stop implying freshness. */
export const staleCandles = (now: number, fetched: number | undefined) => !!fetched && Math.floor(now - fetched) > 45;

/**
 * A volume bar's opacity by relative volume (C2.4): faint under 0.5×, as before up to
 * 1.5×, brighter to 2.5×, brightest beyond. A candle without RVol keeps the plain shade.
 */
export function volumeAlpha(rvol: number | null | undefined): string {
  if (rvol == null) return "3d";
  return rvol < 0.5 ? "1f" : rvol < 1.5 ? "3d" : rvol < 2.5 ? "80" : "d9";
}
const sessionDay = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
/** "RVol vs 20 sessions Sep 1 – Sep 28", or "vs 18 of 20" when some never traded in regular hours. */
export function rvolCoverage(baseline: RvolBaseline): string {
  const days = baseline.sessions;
  if (!days.length) return "RVol: no sessions";
  const span = `${sessionDay.format(new Date(`${days[0]}T12:00:00Z`))} – ${sessionDay.format(new Date(`${days.at(-1)}T12:00:00Z`))}`;
  return `RVol vs ${baseline.traded === days.length ? days.length : `${baseline.traded} of ${days.length}`} sessions ${span}`;
}
/** "2.6×", with two decimals under 0.1× so a quiet candle never reads 0.0×. */
export const rvolText = (rvol: number) => `${rvol.toFixed(rvol < 0.1 ? 2 : 1)}×`;

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

/** An earnings date on the candle that holds it (C2.5). */
export type EarningsMark = { time: number; date: string; label: string; estimated: boolean };
/**
 * Each report date with a loaded candle, past reports and the next one alike.
 * A daily or weekly candle holds the date's New York midday. Intraday, the
 * date's first candle carries it, because the report's time of day is unknown.
 * A date without a loaded candle (a future one, or older than the history) has none.
 */
export function earningsMarks(bars: ChartBar[], earnings: Earnings | null | undefined, interval: Interval): EarningsMark[] {
  if (!earnings || !bars.length) return [];
  const dates = [...earnings.reports.map((report) => ({ ...report, estimated: false })),
    ...(earnings.next ? [{ date: earnings.next.date, label: earnings.next.label, estimated: earnings.next.status === "estimated" }] : [])];
  const marks: EarningsMark[] = [];
  for (const entry of dates) {
    const midnight = Date.parse(`${entry.date}T00:00:00Z`) / 1000;
    if (!intradayInterval(interval)) {
      // 16:30 UTC is 12:30 New York in summer and 11:30 in winter: inside every regular session.
      const bar = barAt(bars, midnight + 16.5 * 3600);
      if (bar) marks.push({ ...entry, time: bar.time });
      continue;
    }
    // New York's midnight is 04:00 or 05:00 UTC; no candle starts between 20:00 and 04:00 New York.
    const after = midnight + 4 * 3600;
    let low = 0, high = bars.length;
    while (low < high) { const mid = (low + high) >>> 1; if (bars[mid].time < after) low = mid + 1; else high = mid; }
    if (low < bars.length && nyDate.format(bars[low].time * 1000) === entry.date) marks.push({ ...entry, time: bars[low].time });
  }
  return marks.sort((a, b) => a.time - b.time);
}

export const INTERVAL_SECONDS: Record<Interval, number> = { "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800 };
export const intradayInterval = (interval: Interval) => interval !== "1D" && interval !== "1W";
/** The widest step between neighboring candles that is still ordinary: a longer one asks for the missing history (C0.7). */
export const gapSeconds = (interval: Interval) => (interval === "1W" ? 21 : interval === "1D" ? 10 : 5) * 86400;

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
/** Candles a chart opens on: the main chart, and each smaller panel. */
export const OPENING_BARS = 110;
export const PANEL_OPENING_BARS = 65;
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
const BAR_KEYS = ["time", "end_time", "source", "open", "high", "low", "close", "volume", "volumePending", "extended", "ema9", "ema20", "ema50", "ema200", "vwap", "vwap_sd", "rsi", "rvol"] as const;
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

/** Alt+R resets a chart's view (latest candles, automatic price scale); End scrolls it to the latest candle at the same zoom. */
export type ChartCommand = "reset" | "realtime";
export type ChartCommands = ReturnType<typeof createChartCommands>;
/** Workspace hotkeys reach every chart through this, as the crosshair link does. */
/** Bring an item into view on one panel (C1.4): its anchors' times (none for a level) and its prices, on the chart's basis. */
export type ChartJump = { panel: string; times: number[]; prices: number[] };
export function createChartCommands() {
  const listeners = new Set<(command: ChartCommand) => void>();
  const jumps = new Set<(jump: ChartJump) => void>();
  // Each panel's picture of itself, for a plan's frozen chart image (C3.4).
  const pictures = new Map<string, () => HTMLCanvasElement | null>();
  return {
    listen(fn: (command: ChartCommand) => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    emit(command: ChartCommand) { listeners.forEach((fn) => fn(command)); },
    listenJump(fn: (jump: ChartJump) => void) { jumps.add(fn); return () => { jumps.delete(fn); }; },
    jump(target: ChartJump) { jumps.forEach((fn) => fn(target)); },
    provideSnapshot(panel: string, fn: () => HTMLCanvasElement | null) { pictures.set(panel, fn); return () => { if (pictures.get(panel) === fn) pictures.delete(panel); }; },
    /** The panel as drawn now: candles, studies and the lines drawn on its canvas. Null when it is not on screen. */
    snapshot(panel: string): HTMLCanvasElement | null { try { return pictures.get(panel)?.() ?? null; } catch { return null; } },
  };
}
