import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesAttachedParameter, Time } from "lightweight-charts";
import type { ChartBar } from "./charts";

const UP = "#2bc9a4";
const DOWN = "#ee617a";
/** The thinnest body, as a share of a candle's slot, for the lowest-volume candle in view. */
const THINNEST = 0.2;
/** The fattest body: nearly the whole slot, so neighbours at the highest volume do not touch. */
const FATTEST = 0.92;

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];
type Drawn = { x: number; half: number; wick: number; top: number; bottom: number; high: number; low: number; up: boolean };

/**
 * Volume candles: each body is as wide as its volume is large among the candles
 * in view (TradingView's "Volume candles"). The real candle series stays, drawn
 * transparent, so the price scale, last-price label, crosshair and the other
 * layers behave as before; this primitive draws the visible bodies and wicks.
 */
export class VolumeCandles implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<"Candlestick"> | null = null;
  private requestUpdate: (() => void) | null = null;
  private drawn: Drawn[] = [];
  private on = false;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "normal", renderer: () => this.renderer }];

  constructor(private readonly bars: () => ChartBar[]) {}

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.chart = chart;
    this.series = series as ISeriesApi<"Candlestick">;
    this.requestUpdate = requestUpdate;
  }

  detached() { this.chart = null; this.series = null; this.requestUpdate = null; }

  set(on: boolean) { this.on = on; this.requestUpdate?.(); }
  update() { this.requestUpdate?.(); }

  /** What is drawn, for tests: each candle's body width in CSS pixels, in view order. */
  widths() { this.updateAllViews(); return this.drawn.map((d) => d.half * 2); }

  updateAllViews() {
    this.drawn = [];
    const { chart, series } = this;
    const bars = this.bars();
    const scale = chart?.timeScale();
    const range = scale?.getVisibleLogicalRange();
    if (!this.on || !chart || !series || !scale || !range || !bars.length) return;
    const [zero, one] = [scale.logicalToCoordinate(0 as Logical), scale.logicalToCoordinate(1 as Logical)];
    if (zero === null || one === null) return;
    const slot = Math.abs(one - zero);
    const from = Math.max(0, Math.floor(range.from) - 1);
    const to = Math.min(bars.length - 1, Math.ceil(range.to) + 1);
    let max = 0, min = Infinity;
    for (let i = from; i <= to; i++) { max = Math.max(max, bars[i].volume); min = Math.min(min, bars[i].volume); }
    for (let i = from; i <= to; i++) {
      const bar = bars[i];
      const x = scale.logicalToCoordinate(i as Logical);
      const [open, close, high, low] = [bar.open, bar.close, bar.high, bar.low].map((price) => series.priceToCoordinate(price));
      if (x === null || open === null || close === null || high === null || low === null) continue;
      const share = max > min ? THINNEST + (FATTEST - THINNEST) * ((bar.volume - min) / (max - min)) : 0.7;
      this.drawn.push({ x, half: (slot * share) / 2, wick: 1, top: Math.min(open, close), bottom: Math.max(open, close), high, low, up: bar.close >= bar.open });
    }
  }

  paneViews() { return this.views; }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio: h, verticalPixelRatio: v }) => {
      for (const d of this.drawn) {
        context.fillStyle = d.up ? UP : DOWN;
        const wickWidth = Math.max(1, Math.round(h));
        context.fillRect(Math.round(d.x * h - wickWidth / 2), Math.round(d.high * v), wickWidth, Math.max(1, Math.round((d.low - d.high) * v)));
        const left = Math.round((d.x - d.half) * h);
        context.fillRect(left, Math.round(d.top * v), Math.max(1, Math.round((d.x + d.half) * h) - left), Math.max(1, Math.round((d.bottom - d.top) * v)));
      }
    });
  }
}
