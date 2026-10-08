import type { ReactNode } from "react";
import type { ChartQuote } from "@/lib/charts";
import { readAt } from "@/lib/symbolInfo";
import type { OverviewBlock, SymbolOverview } from "@/lib/symbolInfo";

const number = (value: number | null, digits = 2) => value == null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits });
const dollars = (value: number | null) => value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 }).format(value);
const yieldPercent = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const quoteLabel = (quote: ChartQuote | null | undefined, fetchedAt: number | null) => {
  const traded = quote?.trade_time ? `last trade ${readAt(quote.trade_time)}` : null;
  return [`Tradier chart quote`, traded, fetchedAt ? `response ${readAt(fetchedAt)}` : null].filter(Boolean).join(" · ");
};
const blockLabel = (block: OverviewBlock) => `${block.source} · ${readAt(block.fetched_at)}`;

function Value({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div title={title} className="min-w-0"><dt className="truncate text-slate-500">{label}</dt><dd className="mt-0.5 truncate font-mono text-slate-200">{value}</dd></div>;
}

function Dataset({ title, block, unavailable, children }: { title: string; block: OverviewBlock; unavailable: string; children: ReactNode }) {
  return <section aria-label={title} className="space-y-2">
    <h3 className="text-slate-400">{title}</h3>
    {block.state === "ready" ? children : <p className={block.state === "none" ? "text-slate-500" : "text-amber-300"}>{block.state === "none" ? unavailable : block.message ?? "Not loaded yet."}</p>}
    {block.state === "ready" && block.message && <p className="text-[10px] text-amber-300">{block.message} Showing the cached copy from {readAt(block.fetched_at)}.</p>}
    <p className="text-[10px] text-slate-500">{block.source} · {readAt(block.fetched_at)}</p>
  </section>;
}

/** Fundamentals plus the quote already loaded by the chart workspace. */
export default function SymbolInfoOverview({ data, quote, quoteFetchedAt }: { data: SymbolOverview; quote?: ChartQuote | null; quoteFetchedAt: number | null }) {
  const qTitle = quoteLabel(quote, quoteFetchedAt);
  const weekLow = quote?.week_52_low ?? null;
  const weekHigh = quote?.week_52_high ?? null;
  const spot = quote?.last ?? null;
  const weekPosition = weekLow != null && weekHigh != null && weekHigh > weekLow && spot != null
    ? Math.max(0, Math.min(100, (spot - weekLow) / (weekHigh - weekLow) * 100)) : null;
  const isFund = /etf|fund/i.test(quote?.instrument_type ?? "");
  // Morningstar lists an ETF's share count and beta but no company; show the ETF state rather than a page of dashes.
  const { company, ratios, statistics } = isFund
    ? Object.fromEntries(Object.entries(data.datasets).map(([key, block]) => [key, { ...block, state: "none" }])) as SymbolOverview["datasets"]
    : data.datasets;
  const name = company.name ?? quote?.name ?? null;
  const noFundamentals = isFund ? "Not available for ETFs or funds." : "Tradier returned no company fundamentals for this symbol.";

  return <div className="space-y-4 text-[11px]">
    <section aria-label="Price and range" className="space-y-2">
      <h3 className="text-slate-400">Price and range</h3>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Value label="Price" value={spot == null ? "—" : `$${price(spot)}`} title={qTitle} />
        <Value label="Change" value={quote?.change == null ? "—" : `${quote.change >= 0 ? "+" : "−"}$${number(Math.abs(quote.change))} (${quote.change_percentage == null ? "—" : `${quote.change_percentage >= 0 ? "+" : ""}${number(quote.change_percentage)}%`})`} title={qTitle} />
        <Value label="Day range" value={quote?.day_low == null || quote?.day_high == null ? "—" : `$${price(quote.day_low)} – $${price(quote.day_high)}`} title={qTitle} />
        <div title={qTitle} className="min-w-0">
          <dt className="text-slate-500">52-week range</dt>
          <dd className="mt-1 text-slate-300">{weekLow == null || weekHigh == null ? "—" : `$${price(weekLow)} – $${price(weekHigh)}`}
            {weekPosition != null && <div className="relative mt-1.5 h-1 rounded bg-slate-700" aria-label={`Price is ${Math.round(weekPosition)} percent through the 52-week range`}><span className="absolute -top-0.5 h-2 w-1 rounded bg-sky-300" style={{ left: `${weekPosition}%` }} /></div>}
          </dd>
        </div>
      </dl>
      <p className="text-[10px] text-slate-500">Tradier chart quote · {quote?.trade_time ? readAt(quote.trade_time) : quoteFetchedAt ? readAt(quoteFetchedAt) : "not read yet"}</p>
    </section>

    <Dataset title="Company" block={company} unavailable={noFundamentals}>
      {name && <h4 title={company.name ? blockLabel(company) : qTitle} className="font-medium text-slate-200">{name}</h4>}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Value label="Sector" value={company.sector ?? "—"} title={blockLabel(company)} />
        <Value label="Employees" value={number(company.employees, 0)} title={blockLabel(company)} />
        <Value label="IPO date" value={company.ipo_date ?? "—"} title={blockLabel(company)} />
      </dl>
      {company.description && <p title={blockLabel(company)} className="line-clamp-2 leading-4 text-slate-400">{company.description}</p>}
    </Dataset>

    <Dataset title="Key statistics" block={statistics} unavailable={noFundamentals}>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Value label="Market cap" value={dollars(statistics.market_cap)} title={blockLabel(statistics)} />
        <Value label="Enterprise value" value={dollars(statistics.enterprise_value)} title={blockLabel(statistics)} />
        <Value label="Shares outstanding" value={number(statistics.shares_outstanding, 0)} title={blockLabel(statistics)} />
        <Value label="Held by institutions" value={yieldPercent(statistics.institutional_ownership)} title={blockLabel(statistics)} />
        <Value label="30-day average volume" value={number(statistics.average_volume_30_day, 0)} title={blockLabel(statistics)} />
      </dl>
    </Dataset>

    <Dataset title="Valuation" block={ratios} unavailable={noFundamentals}>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        <Value label="P/E" value={number(ratios.pe)} title={blockLabel(ratios)} />
        <Value label="P/S" value={number(ratios.price_to_sales)} title={blockLabel(ratios)} />
        <Value label="P/B" value={number(ratios.price_to_book)} title={blockLabel(ratios)} />
        <Value label="EV/EBITDA" value={number(ratios.ev_to_ebitda)} title={blockLabel(ratios)} />
        <Value label="Dividend yield" value={yieldPercent(ratios.dividend_yield)} title={blockLabel(ratios)} />
        <Value label="Beta · 60 months" value={number(ratios.beta_60_month)} title={blockLabel(ratios)} />
      </dl>
    </Dataset>
  </div>;
}
