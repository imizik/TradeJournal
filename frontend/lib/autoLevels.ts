import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import type { AutoLevel, AutoZone, LevelInteraction } from "./charts";
import { etTime, price } from "./charts";

/**
 * Automatic levels on the chart (C2.3). The backend computes them (C2.1) and
 * merges nearby ones into zones (C2.2); this layer draws the nearest few above
 * and below price behind the candles, dimmer than the user's own levels: a lone
 * level as a thin dotted line, a zone as a shaded band. It takes no pointer
 * events of its own, so panning, the crosshair and the user's levels and
 * drawings work through it; the chart asks `hit` where to show a level's card.
 */

/** Zones shown on each side of price. */
export const NEAREST = 3;
const LINE = "#8b97ab";
const HOVER = "#c9d3e2";
const FONT = "ui-sans-serif, system-ui, sans-serif";

/** The zones to draw: any that price is inside, and the nearest `count` wholly above and wholly below it. */
export function nearestZones(zones: AutoZone[], at: number | undefined, count = NEAREST): AutoZone[] {
  if (at === undefined) return [];
  const above = zones.filter((zone) => zone.low > at).sort((a, b) => a.low - b.low).slice(0, count);
  const below = zones.filter((zone) => zone.high < at).sort((a, b) => b.high - a.high).slice(0, count);
  return [...below.reverse(), ...zones.filter((zone) => zone.low <= at && at <= zone.high), ...above];
}

/** A chart label: three member names at most, then how many more ("PDH + ONH + 660 +2"). */
export function shortLabel(label: string): string {
  const parts = label.split(" + ");
  return parts.length <= 3 ? label : `${parts.slice(0, 3).join(" + ")} +${parts.length - 3}`;
}

export const KIND_NAMES: Record<string, string> = {
  prior_day_high: "Prior day high", prior_day_low: "Prior day low", prior_day_close: "Prior day close",
  prior_week_high: "Prior week high", prior_week_low: "Prior week low",
  premarket_high: "Premarket high", premarket_low: "Premarket low", overnight_high: "Overnight high", overnight_low: "Overnight low",
  opening_range_5m_high: "5-minute opening range high", opening_range_5m_low: "5-minute opening range low",
  opening_range_15m_high: "15-minute opening range high", opening_range_15m_low: "15-minute opening range low",
  swing_high: "Swing high (daily pivot)", swing_low: "Swing low (daily pivot)", round: "Round number",
};
export const STATE_NAMES: Record<LevelInteraction["state"], string> = { untested: "Untested", tested: "Tested", broken: "Broken", reclaimed: "Reclaimed", developing: "Still forming" };

/** Where a level came from, in words: "Tradier daily bar", "SIP minute", or the rule a round number follows. */
export function sourceName(level: AutoLevel): string {
  if (!level.source) return "price rule";
  const provider = level.source === "alpaca_sip" ? "SIP" : "Tradier";
  return `${provider} ${level.timeframe === "1D" ? "daily bar" : "minute"}`;
}

/** When it formed: "formed Oct 2, 2026 4:00 PM", "still forming", or nothing for a round number. */
export function formedName(level: AutoLevel): string | null {
  if (level.developing) return "still forming";
  return level.formed_at === null ? null : `formed ${etTime(level.formed_at, true)} ${etTime(level.formed_at)}`;
}

/** A zone's prices as they are: "659.80" or "659.80–660.00". */
export const spanName = (zone: AutoZone) => zone.low === zone.high ? price(zone.low) : `${price(zone.low)}–${price(zone.high)}`;

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
type Placed = { zone: AutoZone; top: number; bottom: number };

export class AutoLevelLayer implements ISeriesPrimitive<Time> {
  private zones: AutoZone[] = [];
  private labels = false;
  private hovered: string | null = null;
  private placed: Placed[] = [];
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

  /** What to draw. `labels` names each line (the main chart). */
  set(zones: AutoZone[], labels: boolean) {
    this.zones = zones;
    this.labels = labels;
    this.update();
  }

  /** The zone whose card is open draws brighter. */
  setHovered(id: string | null) {
    if (id === this.hovered) return;
    this.hovered = id;
    this.update();
  }

  /** Ids of the zones drawn, lowest first; browser tests read it. */
  shown(): string[] { return this.zones.map((zone) => zone.id); }

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
  }

  paneViews() { return this.views; }

  private update() {
    this.updateAllViews();
    this.requestUpdate?.();
  }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      context.save();
      for (const { zone, top, bottom } of this.placed) {
        const [upper, lower] = [Math.round(top * v), Math.round(bottom * v)];
        if (lower < -2 * v || upper > bitmapSize.height + 2 * v) continue;
        const hovered = zone.id === this.hovered;
        const color = hovered ? HOVER : LINE;
        const band = lower - upper >= 3 * v;
        if (band) {
          context.globalAlpha = hovered ? 0.2 : 0.1;
          context.fillStyle = LINE;
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
        // Labels sit at the left: the user's own levels label theirs at the right.
        if (this.labels) {
          context.font = `${Math.round(9 * v)}px ${FONT}`;
          context.fillStyle = color;
          context.textAlign = "left";
          context.textBaseline = "bottom";
          context.fillText(shortLabel(zone.label), Math.round(6 * h), upper - Math.round(2 * v));
        }
      }
      context.restore();
    });
  }
}
