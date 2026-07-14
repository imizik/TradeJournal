import { decimalToNumber } from "@/lib/strategy-lab/format";
import type {
  StrategyDrawdownPoint,
  StrategyEquityPoint,
} from "@/lib/strategy-lab/types";

type CurvePoint = StrategyEquityPoint | StrategyDrawdownPoint;

export default function StrategyCurveChart({
  title,
  description,
  points,
  valueKey,
  stroke,
  invert = false,
  formatValue,
}: {
  title: string;
  description: string;
  points: CurvePoint[];
  valueKey: string;
  stroke: string;
  invert?: boolean;
  formatValue: (value: number) => string;
}) {
  const values = points
    .map((point) => ({
      point,
      value: decimalToNumber(
        typeof (point as unknown as Record<string, unknown>)[valueKey] === "string"
          ? ((point as unknown as Record<string, string>)[valueKey] ?? null)
          : null,
      ),
    }))
    .filter((item): item is { point: CurvePoint; value: number } => item.value != null);

  if (values.length < 2) {
    return (
      <section className="rounded-lg border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        <div className="mt-5 rounded-md bg-muted/50 px-4 py-8 text-center text-sm text-muted-foreground">
          This curve is unavailable for the imported data.
        </div>
      </section>
    );
  }

  const width = 720;
  const height = 230;
  const padding = { top: 20, right: 20, bottom: 32, left: 58 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  let minimum = Math.min(...values.map((item) => item.value));
  let maximum = Math.max(...values.map((item) => item.value));

  if (minimum === maximum) {
    const spread = Math.max(Math.abs(minimum) * 0.05, 1);
    minimum -= spread;
    maximum += spread;
  }

  const x = (index: number) =>
    padding.left + (index / Math.max(values.length - 1, 1)) * innerWidth;
  const y = (value: number) => {
    const ratio = (value - minimum) / (maximum - minimum);
    return padding.top + (invert ? ratio : 1 - ratio) * innerHeight;
  };
  const path = values
    .map((item, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(item.value).toFixed(2)}`)
    .join(" ");
  const zeroVisible = minimum <= 0 && maximum >= 0;

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        </div>
        <div className="text-right text-xs tabular-nums text-muted-foreground">
          <span>{formatValue(values[0].value)}</span>
          <span className="px-1.5">→</span>
          <span className="font-medium text-foreground">
            {formatValue(values[values.length - 1].value)}
          </span>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto min-w-[560px] w-full text-muted-foreground"
          role="img"
          aria-label={`${title}. ${description}`}
        >
          <title>{title}</title>
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const gridY = padding.top + ratio * innerHeight;
            return (
              <line
                key={ratio}
                x1={padding.left}
                x2={width - padding.right}
                y1={gridY}
                y2={gridY}
                stroke="currentColor"
                strokeOpacity="0.14"
                strokeWidth="1"
              />
            );
          })}
          {zeroVisible && (
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y(0)}
              y2={y(0)}
              stroke="currentColor"
              strokeOpacity="0.45"
              strokeDasharray="5 5"
            />
          )}
          <path
            d={path}
            fill="none"
            stroke={stroke}
            strokeWidth="2.5"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <circle
            cx={x(values.length - 1)}
            cy={y(values[values.length - 1].value)}
            r="4"
            fill={stroke}
          />
          <text x="4" y={padding.top + 4} fill="currentColor" fontSize="11">
            {formatValue(invert ? minimum : maximum)}
          </text>
          <text x="4" y={height - padding.bottom + 4} fill="currentColor" fontSize="11">
            {formatValue(invert ? maximum : minimum)}
          </text>
          <text
            x={padding.left}
            y={height - 8}
            fill="currentColor"
            fontSize="11"
          >
            Start
          </text>
          <text
            x={width - padding.right}
            y={height - 8}
            fill="currentColor"
            fontSize="11"
            textAnchor="end"
          >
            Trade {values[values.length - 1].point.trade_number ?? values.length - 1}
          </text>
        </svg>
      </div>
    </section>
  );
}
