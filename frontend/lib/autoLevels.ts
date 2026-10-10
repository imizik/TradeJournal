import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { AutoLevel, AutoLevels, AutoZone, LevelInteraction } from "./charts";
import { etTime, price } from "./charts";

/**
 * Automatic levels on the chart (C2.3). The backend computes them (C2.1) and
 * merges nearby ones into zones (C2.2); this layer draws the nearest few above
 * and below price behind the candles, dimmer than the user's own levels: a lone
 * level as a thin dotted line, a zone as a shaded band. It takes no pointer
 * events of its own, so panning, the crosshair and the user's levels and
 * drawings work through it; the chart asks `hit` where to show a level's card.
 *
 * Option strikes (C4.4) join the same zones on the backend, so a call wall at
 * the prior day's high is one zone. A zone with an option member is tinted by
 * it: calls teal, puts rose, other ranked strikes violet, the gamma flip amber,
 * max pain (C4.7) orange. The range bands' expected-move levels (C2.7) join the
 * zones the same way and draw blue. A strike chosen on the ladder (C4.5) draws
 * as a solid highlighted line.
 */

/** Zones shown on each side of price. */
export const NEAREST = 3;
const LINE = "#8b97ab";
const HOVER = "#c9d3e2";
const HIGHLIGHT = "#7dd3fc";
/** Behind a tag: the chart's own background, so the name reads over candles. */
const TAG_BACKGROUND = "#10151e";
/** An option zone's tint, by its most telling member. */
function tint(zone: AutoZone): string {
  const kinds = new Set(zone.members.map((member) => member.kind));
  if (kinds.has("call_wall") || kinds.has("call_volume_wall")) return "#4fd1b5";
  if (kinds.has("put_wall") || kinds.has("put_volume_wall")) return "#f08aa0";
  if (kinds.has("gamma_flip")) return "#f5c76b";
  if (kinds.has("max_pain")) return "#fb923c";
  if (zone.members.some(isRange)) return "#7aa7ff";
  return zone.members.some(isOption) ? "#a99af0" : LINE;
}
const FONT = "ui-sans-serif, system-ui, sans-serif";

/** Option strike kinds (C4.4, C4.7); the walls, the flip and max pain always draw while the layer is on. */
const OPTION_KINDS = new Set(["call_wall", "put_wall", "call_volume_wall", "put_volume_wall", "options_oi", "options_volume", "options_gamma", "gamma_flip", "max_pain"]);
const ALWAYS = new Set(["call_wall", "put_wall", "call_volume_wall", "put_volume_wall", "gamma_flip", "max_pain"]);
/** The range bands' expected-move levels (C2.7); every one draws while the bands are on. */
const RANGE_KINDS = new Set(["expected_move_high", "expected_move_low"]);
export const isOption = (level: AutoLevel) => OPTION_KINDS.has(level.kind);
export const isRange = (level: AutoLevel) => RANGE_KINDS.has(level.kind);
const hasOption = (zone: AutoZone) => zone.members.some(isOption);
const hasRange = (zone: AutoZone) => zone.members.some(isRange);
const hasAuto = (zone: AutoZone) => zone.members.some((member) => !isOption(member) && !isRange(member));

/**
 * The zones a chart may show of what the backend sent, by which groups are on.
 * The backend merges only the groups asked for; until a response for a changed
 * choice arrives, a zone without a member of a shown group is left out.
 */
export function autoLevelsShown(levels: AutoLevels | null | undefined, auto: boolean, options: boolean, ranges = false): AutoLevels | null {
  if (!levels || (!auto && !options && !ranges)) return null;
  const zones = levels.zones.filter((zone) => (auto && hasAuto(zone)) || (options && hasOption(zone)) || (ranges && hasRange(zone)));
  return zones.length === levels.zones.length ? levels : { ...levels, zones };
}

/**
 * The zones to draw: the nearest automatic ones (C2.3) and, with the options
 * layer on, the nearest `options` option zones each side plus every wall, the
 * flip and max pain; with the range bands on (C2.7), every expected-move level.
 * Lowest first. A zone of several kinds counts for each.
 */
export function shownZones(zones: AutoZone[], at: number | undefined, options: number | null, ranges = false): AutoZone[] {
  if (at === undefined) return [];
  const chosen = new Map(nearestZones(zones.filter(hasAuto), at).map((zone) => [zone.id, zone]));
  if (options !== null) {
    for (const zone of nearestZones(zones.filter(hasOption), at, options)) chosen.set(zone.id, zone);
    for (const zone of zones) if (zone.members.some((member) => ALWAYS.has(member.kind))) chosen.set(zone.id, zone);
  }
  if (ranges) for (const zone of zones) if (hasRange(zone)) chosen.set(zone.id, zone);
  return [...chosen.values()].sort((a, b) => a.low - b.low);
}

/** The zones to draw: any that price is inside, and the nearest `count` wholly above and wholly below it. */
export function nearestZones(zones: AutoZone[], at: number | undefined, count = NEAREST): AutoZone[] {
  if (at === undefined) return [];
  const above = zones.filter((zone) => zone.low > at).sort((a, b) => a.low - b.low).slice(0, count);
  const below = zones.filter((zone) => zone.high < at).sort((a, b) => b.high - a.high).slice(0, count);
  return [...below.reverse(), ...zones.filter((zone) => zone.low <= at && at <= zone.high), ...above];
}

/** Which member names a zone on the chart: option landmarks, then the expected move, prior day and week, session ranges, swings, round numbers, ranked strikes. */
const LABEL_ORDER = [
  ["call_wall", "put_wall", "max_pain", "gamma_flip", "call_volume_wall", "put_volume_wall"],
  ["expected_move_high", "expected_move_low"],
  ["prior_day_high", "prior_day_low", "prior_day_close", "prior_week_high", "prior_week_low"],
  ["premarket_high", "premarket_low", "overnight_high", "overnight_low"],
  ["opening_range_5m_high", "opening_range_5m_low", "opening_range_15m_high", "opening_range_15m_low"],
  ["swing_high", "swing_low"],
  ["round"],
  ["options_oi", "options_volume", "options_gamma"],
];
const labelRank = (kind: string) => { const rank = LABEL_ORDER.findIndex((kinds) => kinds.includes(kind)); return rank < 0 ? LABEL_ORDER.length : rank; };

/**
 * A zone's tag on the chart: its most telling member's name and how many more
 * the zone holds ("Max pain +2", "PDH +1"). A round number reads "Round 223"
 * so the count never looks like a price. The card lists every member.
 */
export function chartLabel(zone: AutoZone): string {
  if (!zone.members.length) return zone.label;
  const top = zone.members.reduce((best, member) => labelRank(member.kind) < labelRank(best.kind) ? member : best);
  const name = top.kind === "round" ? `Round ${top.label}` : top.label;
  return zone.members.length > 1 ? `${name} +${zone.members.length - 1}` : name;
}

export const KIND_NAMES: Record<string, string> = {
  prior_day_high: "Prior day high", prior_day_low: "Prior day low", prior_day_close: "Prior day close",
  prior_week_high: "Prior week high", prior_week_low: "Prior week low",
  premarket_high: "Premarket high", premarket_low: "Premarket low", overnight_high: "Overnight high", overnight_low: "Overnight low",
  opening_range_5m_high: "5-minute opening range high", opening_range_5m_low: "5-minute opening range low",
  opening_range_15m_high: "15-minute opening range high", opening_range_15m_low: "15-minute opening range low",
  swing_high: "Swing high (daily pivot)", swing_low: "Swing low (daily pivot)", round: "Round number",
  call_wall: "Call wall: most call open interest", put_wall: "Put wall: most put open interest",
  call_volume_wall: "Call volume wall: most calls traded", put_volume_wall: "Put volume wall: most puts traded",
  options_oi: "Open interest, ranked", options_volume: "Option volume, ranked", options_gamma: "Gamma, ranked",
  gamma_flip: "Gamma flip: signed gamma crosses zero",
  max_pain: "Max pain: least paid out at expiry",
  expected_move_high: "Expected move, upper", expected_move_low: "Expected move, lower",
};
export const STATE_NAMES: Record<LevelInteraction["state"], string> = {
  untested: "No completed interaction", touched: "Contact observed", approached: "Approached",
  tested: "Contact and departure", broken: "Closed across zone", reclaimed: "Returned to approach side", developing: "Combination still changing",
};

/** Where a level came from, in words: "Tradier daily bar", "SIP minute", or the rule a round number follows. */
export function sourceName(level: AutoLevel): string {
  if (isOption(level) || isRange(level)) return "Tradier option chains";
  if (!level.source) return "price rule";
  const provider = level.source === "alpaca_sip" ? "SIP" : "Tradier";
  return `${provider} ${level.timeframe === "1D" ? "daily bar" : "minute"}`;
}

/** When it formed: "formed Oct 2, 2026 4:00 PM", "still forming", or nothing for a round number. */
export function formedName(level: AutoLevel): string | null {
  // Open interest holds still through a session; volume trades and gamma follows the price.
  if (isOption(level)) return level.developing ? "moves during the session"
    : level.formed_at === null ? null : `first observed ${etTime(level.formed_at)} ET`;
  // An expected-move level is fixed once captured for the session.
  if (isRange(level)) return level.formed_at === null ? null : `priced ${etTime(level.formed_at)} ET, fixed for the session`;
  if (level.developing) return "still forming";
  return level.formed_at === null ? null : `formed ${etTime(level.formed_at, true)} ${etTime(level.formed_at)}`;
}

/** A zone's prices as they are: "659.80" or "659.80–660.00". */
export const spanName = (zone: AutoZone) => zone.low === zone.high ? price(zone.low) : `${price(zone.low)}–${price(zone.high)}`;

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
type Placed = { zone: AutoZone; top: number; bottom: number };
/** A tag's height and the gap kept between two tags, in CSS pixels. */
const TAG_HEIGHT = 14;
const TAG_GAP = 2;

export class AutoLevelLayer implements ISeriesPrimitive<Time> {
  private zones: AutoZone[] = [];
  private labels = false;
  private at: number | undefined;
  private drawnTags: { text: string; top: number; bottom: number }[] = [];
  private hovered: string | null = null;
  private placed: Placed[] = [];
  private highlight: { price: number; y: number | null } | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "bottom", renderer: () => this.renderer }];

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.series = null;
    this.requestUpdate = null;
  }

  /** What to draw. `labels` names each zone (the main chart); `at`, the latest price, decides which tag wins when two would overlap. */
  set(zones: AutoZone[], labels: boolean, at?: number) {
    this.zones = zones;
    this.labels = labels;
    this.at = at;
    this.update();
  }

  /** The zone whose card is open draws brighter. */
  setHovered(id: string | null) {
    if (id === this.hovered) return;
    this.hovered = id;
    this.update();
  }

  /** A strike chosen on the ladder (C4.5), drawn as a solid line until another or none. */
  setHighlight(value: number | null) {
    if (value === (this.highlight?.price ?? null)) return;
    this.highlight = value === null ? null : { price: value, y: null };
    this.update();
  }

  /** Ids of the zones drawn, lowest first; browser tests read it. */
  shown(): string[] { return this.zones.map((zone) => zone.id); }

  /** The tags last drawn, their text and their top and bottom in CSS pixels; browser tests read it. */
  tags(): { text: string; top: number; bottom: number }[] { return this.drawnTags; }

  /** Where a zone's middle is drawn, in pixels from the top of the pane, or null when it is off the scale. */
  y(id: string): number | null {
    const entry = this.placed.find((item) => item.zone.id === id);
    return entry ? (entry.top + entry.bottom) / 2 : null;
  }

  /** The zone at `y`: inside its band, or within `slop` pixels of its line; the nearest wins. */
  hit(y: number, slop: number): string | null {
    let best: { id: string; distance: number } | null = null;
    for (const { zone, top, bottom } of this.placed) {
      const distance = y < top ? top - y : y > bottom ? y - bottom : 0;
      if (distance <= slop && (!best || distance < best.distance)) best = { id: zone.id, distance };
    }
    return best?.id ?? null;
  }

  updateAllViews() {
    const series = this.series;
    this.placed = series ? this.zones.flatMap((zone) => {
      const [top, bottom] = [series.priceToCoordinate(zone.high), series.priceToCoordinate(zone.low)];
      return top === null || bottom === null ? [] : [{ zone, top, bottom }];
    }) : [];
    if (this.highlight) this.highlight.y = series?.priceToCoordinate(this.highlight.price) ?? null;
  }

  paneViews() { return this.views; }

  private update() {
    this.updateAllViews();
    this.requestUpdate?.();
  }

  /**
   * Each zone's name on a solid tag just above its upper edge, at the left: the
   * user's own levels label theirs at the right. Tags never overlap: the zone
   * whose card is open wins, then the zones nearest the price; a tag that would
   * cover another is left out, and its zone still has its card on hover.
   */
  private drawTags(context: CanvasRenderingContext2D, height: number, h: number, v: number) {
    const at = this.at;
    const distance = ({ zone }: Placed) => at === undefined ? 0 : zone.low > at ? zone.low - at : zone.high < at ? at - zone.high : 0;
    const order = [...this.placed].sort((a, b) => Number(b.zone.id === this.hovered) - Number(a.zone.id === this.hovered) || distance(a) - distance(b));
    const taken: [number, number][] = [];
    this.drawnTags = [];
    context.font = `${Math.round(10 * v)}px ${FONT}`;
    context.textAlign = "left";
    context.textBaseline = "middle";
    for (const placed of order) {
      const bottom = placed.top - 1;
      const top = bottom - TAG_HEIGHT;
      if (top < 0 || bottom * v > height) continue; // a tag cut by the pane's edge would read as a different name
      if (taken.some(([a, b]) => top < b + TAG_GAP && bottom > a - TAG_GAP)) continue;
      taken.push([top, bottom]);
      const text = chartLabel(placed.zone);
      this.drawnTags.push({ text, top, bottom });
      const hovered = placed.zone.id === this.hovered;
      const [x, width] = [Math.round(4 * h), Math.ceil(context.measureText(text).width + 8 * h)];
      context.globalAlpha = 0.9;
      context.fillStyle = TAG_BACKGROUND;
      context.beginPath();
      context.roundRect(x, Math.round(top * v), width, Math.round(TAG_HEIGHT * v), Math.round(3 * h));
      context.fill();
      context.globalAlpha = 1;
      context.fillStyle = hovered ? HOVER : tint(placed.zone);
      context.fillText(text, x + Math.round(4 * h), Math.round((top + TAG_HEIGHT / 2) * v));
    }
  }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      context.save();
      for (const { zone, top, bottom } of this.placed) {
        const [upper, lower] = [Math.round(top * v), Math.round(bottom * v)];
        if (lower < -2 * v || upper > bitmapSize.height + 2 * v) continue;
        const hovered = zone.id === this.hovered;
        const base = tint(zone);
        const color = hovered ? HOVER : base;
        const band = lower - upper >= 3 * v;
        if (band) {
          context.globalAlpha = hovered ? 0.2 : 0.1;
          context.fillStyle = base;
          context.fillRect(0, upper, bitmapSize.width, lower - upper);
        }
        context.globalAlpha = hovered ? 0.95 : 0.55;
        context.strokeStyle = color;
        context.lineWidth = Math.max(1, Math.floor(v));
        context.setLineDash([Math.round(2 * h), Math.round(3 * h)]);
        context.beginPath();
        for (const row of band ? [upper, lower] : [Math.round((upper + lower) / 2)]) {
          const at = row + (context.lineWidth % 2 ? 0.5 : 0);
          context.moveTo(0, at);
          context.lineTo(bitmapSize.width, at);
        }
        context.stroke();
        context.setLineDash([]);
      }
      if (this.labels) this.drawTags(context, bitmapSize.height, h, v);
      else this.drawnTags = [];
      const marked = this.highlight;
      if (marked && marked.y !== null) {
        const row = Math.round(marked.y * v) + 0.5;
        context.globalAlpha = 0.95;
        context.strokeStyle = HIGHLIGHT;
        context.lineWidth = Math.max(1, Math.floor(v));
        context.beginPath();
        context.moveTo(0, row);
        context.lineTo(bitmapSize.width, row);
        context.stroke();
        context.font = `${Math.round(10 * v)}px ${FONT}`;
        context.fillStyle = HIGHLIGHT;
        context.textAlign = "left";
        context.textBaseline = "bottom";
        context.fillText(`Strike ${price(marked.price)}`, Math.round(6 * h), row - Math.round(2 * v));
      }
      context.restore();
    });
  }
}
