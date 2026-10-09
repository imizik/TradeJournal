import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, Logical, SeriesAttachedParameter, Time } from "lightweight-charts";
import type { ChartBar } from "./charts";

/** The premarket and after-hours tint behind the candles. */
const SHADE = "#6b84bd10";

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

/**
 * Extended-hours shading: one flat band for each run of premarket or
 * after-hours candles, behind everything else on the chart. A histogram column
 * per candle left hairline gaps between the columns that read as stripes.
 * It reads the panel's candles through `bars`, so a streamed candle needs only
 * `update()`, and it measures only the candles in view.
 */
export class SessionShade implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private requestUpdate: (() => void) | null = null;
  /** Each run's left and right edge, in CSS pixels from the pane's left. */
  private runs: [number, number][] = [];
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
  private readonly views: readonly IPrimitivePaneView[] = [{ zOrder: () => "bottom", renderer: () => this.renderer }];

  constructor(private readonly bars: () => ChartBar[]) {}

  attached({ chart, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.chart = chart;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.chart = null;
    this.requestUpdate = null;
  }

  /** The candles changed: measure again on the next frame. */
  update() { this.requestUpdate?.(); }

  updateAllViews() {
    this.runs = [];
    const bars = this.bars();
    const scale = this.chart?.timeScale();
    const range = scale?.getVisibleLogicalRange();
    if (!scale || !range || !bars.length) return;
    const [zero, one] = [scale.logicalToCoordinate(0 as Logical), scale.logicalToCoordinate(1 as Logical)];
    if (zero === null || one === null) return;
    const half = (one - zero) / 2;
    const from = Math.max(0, Math.floor(range.from) - 1);
    const to = Math.min(bars.length - 1, Math.ceil(range.to) + 1);
    let start: number | null = null;
    for (let index = from; index <= to + 1; index++) {
      const extended = index <= to && !!bars[index].extended;
      if (extended && start === null) start = index;
      if (extended || start === null) continue;
      const [left, right] = [scale.logicalToCoordinate(start as Logical), scale.logicalToCoordinate((index - 1) as Logical)];
      if (left !== null && right !== null) this.runs.push([left - half, right + half]);
      start = null;
    }
  }

  paneViews() { return this.views; }

  private draw(target: Target) {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: h }) => {
      context.fillStyle = SHADE;
      for (const [left, right] of this.runs) {
        const x = Math.round(left * h);
        context.fillRect(x, 0, Math.round(right * h) - x, bitmapSize.height);
      }
    });
  }
}
