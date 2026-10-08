import { readAt } from "@/lib/symbolInfo";
import type { FinancialQuarter, SymbolFinancials } from "@/lib/symbolInfo";

const dollars = (value: number) => {
  const size = Math.abs(value);
  const [scaled, unit] = size >= 1e9 ? [value / 1e9, "B"] : size >= 1e6 ? [value / 1e6, "M"] : size >= 1e3 ? [value / 1e3, "K"] : [value, ""];
  return `${scaled < 0 ? "-" : ""}$${Math.abs(scaled).toFixed(Math.abs(scaled) >= 100 || !unit ? 0 : 1)}${unit}`;
};
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const eps = (value: number) => `${value < 0 ? "-" : ""}$${Math.abs(value).toFixed(2)}`;
const growth = (value: number | null) => value == null ? "" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(0)}%`;
const quarterName = (q: FinancialQuarter) => q.fiscal_period && q.fiscal_year ? `${q.fiscal_period} FY${String(q.fiscal_year).slice(-2)}` : q.end.slice(0, 7);

type Metric = { key: keyof FinancialQuarter; label: string; format(value: number): string; yoy?: keyof FinancialQuarter };
const METRICS: Metric[] = [
  { key: "revenue", label: "Revenue", format: dollars, yoy: "revenue_yoy" },
  { key: "gross_margin", label: "Gross margin", format: percent },
  { key: "operating_margin", label: "Operating margin", format: percent },
  { key: "net_income", label: "Net income", format: dollars, yoy: "net_income_yoy" },
  { key: "eps_diluted", label: "Diluted EPS", format: eps, yoy: "eps_diluted_yoy" },
];

function Bars({ metric, quarters }: { metric: Metric; quarters: FinancialQuarter[] }) {
  const values = quarters.map((q) => q[metric.key] as number | null);
  const top = Math.max(0, ...values.map((value) => value == null ? 0 : Math.abs(value)));
  return <section aria-label={metric.label} className="space-y-1">
    <h3 className="text-slate-400">{metric.label}</h3>
    <ol className="grid grid-cols-8 gap-1">
      {quarters.map((q, index) => {
        const value = values[index];
        const height = value == null || top === 0 ? 0 : Math.max(2, Math.abs(value) / top * 100);
        const change = metric.yoy ? growth(q[metric.yoy] as number | null) : "";
        return <li key={q.end} title={q.gap ? `${quarterName(q)}: reported only in the annual 10-K, not shown` : `${quarterName(q)} ended ${q.end}`} className="min-w-0 text-center">
          <div className="flex h-10 items-end justify-center">
            {value != null && <div data-testid="bar" style={{ height: `${height}%` }} className={`w-3/4 rounded-sm ${value < 0 ? "bg-rose-500/80" : "bg-sky-500/80"}`} />}
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-slate-200">{value == null ? "—" : metric.format(value)}</div>
          <div className={`h-3 truncate font-mono text-[9px] ${change.startsWith("-") ? "text-rose-300" : "text-emerald-300"}`}>{change}</div>
        </li>;
      })}
    </ol>
  </section>;
}

/** Revenue, margins, net income and diluted EPS for the last eight fiscal quarters, from SEC EDGAR (T3.2). */
export default function SymbolInfoFinancials({ data }: { data: SymbolFinancials }) {
  if (data.state !== "ready") {
    return <div className="space-y-1 text-xs"><p className={data.state === "none" ? "text-slate-500" : "text-amber-300"}>{data.message ?? "SEC financials are unavailable."}</p></div>;
  }
  return <div className="space-y-3 text-xs">
    <ol aria-label="Quarters" className="grid grid-cols-8 gap-1 text-center text-[9px] uppercase tracking-wider text-slate-500">
      {data.quarters.map((q) => <li key={q.end} className="min-w-0 truncate" title={q.end}>{quarterName(q)}</li>)}
    </ol>
    {METRICS.map((metric) => <Bars key={metric.key} metric={metric} quarters={data.quarters} />)}
    {data.message && <p className="text-[10px] text-amber-300">{data.message}</p>}
    <p className="text-[10px] text-slate-500">
      {data.entity ? `${data.entity} · ` : ""}{data.source} · read {readAt(data.fetched_at)}. Margins are calculated from revenue, gross profit and operating income.
      Percentages under a bar are growth against the same fiscal quarter a year earlier. Q4 appears only in the annual 10-K and is not derived (—).
    </p>
  </div>;
}
