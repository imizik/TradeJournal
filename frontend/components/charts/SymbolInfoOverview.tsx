import type { ReactNode } from "react";
import type { ChartQuote } from "@/lib/charts";
import { readAt } from "@/lib/symbolInfo";
import type { OverviewBlock, PeerRatio, PeerValuation, SymbolOverview } from "@/lib/symbolInfo";
import SymbolInfoOwnership, { ownersReported } from "./SymbolInfoOwnership";
import { Block, EXPLAIN, Row, Rows } from "./SymbolInfoParts";
import type { FooterSource } from "./SymbolInfoParts";

const number = (value: number | null, digits = 2) => value == null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: digits });
const dollars = (value: number | null) => value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 }).format(value);
const yieldPercent = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;
const price = (value: number) => value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const quoteLabel = (quote: ChartQuote | null | undefined, fetchedAt: number | null) => {
  const traded = quote?.trade_time ? `last trade ${readAt(quote.trade_time)}` : null;
  return [`Tradier chart quote`, traded, fetchedAt ? `response ${readAt(fetchedAt)}` : null].filter(Boolean).join(" · ");
};
const blockLabel = (block: OverviewBlock) => `${block.source} · ${readAt(block.fetched_at)}`;

const range = (low: number, high: number) => `$${price(low)}–${price(high)}`;

/** A ratio with its peers' median beside it ("52.5 · peers 31"), when at least three peers report one. */
function againstPeers(value: number | null, field: PeerRatio, peers: PeerValuation | null | undefined, group: string | undefined) {
  const median = peers?.state === "ready" ? peers.median[field] ?? null : null;
  if (median == null) return { value: number(value), note: "" };
  return {
    value: <>{number(value)}<span className="text-slate-500"> · peers {number(median, median >= 100 ? 0 : 1)}</span></>,
    note: `\nPeers: median of ${peers?.counted[field]} ${group ? `in ${group}` : "related companies"} with a positive value · ${peers?.source} · ${readAt(peers?.fetched_at ?? null)}`,
  };
}


/** One dataset's block: its rows, or why there are none. The source line is the tab's single footer. */
function Dataset({ name, title, block, unavailable, children }: { name: string; title: string; block: OverviewBlock; unavailable: string; children: ReactNode }) {
  return <Block name={name} title={title} forceOpen={block.state !== "ready" && block.state !== "none" || !!block.message}>
    {block.state === "ready" ? children : <p className={block.state === "none" ? "text-slate-500" : "text-amber-300"}>{block.state === "none" ? unavailable : block.message ?? "Not loaded yet."}</p>}
    {block.state === "ready" && block.message && <p className="text-[10px] text-amber-300">{block.message} Showing the cached copy ({readAt(block.fetched_at)}).</p>}
  </Block>;
}

/** Fundamentals plus the quote already loaded by the chart workspace. */
export default function SymbolInfoOverview({ data, quote, quoteFetchedAt, peers, peerGroup, children }: { data: SymbolOverview; quote?: ChartQuote | null; quoteFetchedAt: number | null;
  /** The Peers read's valuation medians, shown beside P/E, P/S, P/B and EV/EBITDA. */ peers?: PeerValuation | null; peerGroup?: string;
  /** Blocks placed last, above the source line (Peers). */ children?: ReactNode }) {
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
  // The 13F block shows "Held by institutions" with its as-of date; Key statistics shows it only when that block does not.
  const heldInOwnership = company.state === "ready" && ownersReported(company.ownership);
  const held = statistics.institutional_ownership != null && statistics.institutional_ownership > 0 ? yieldPercent(statistics.institutional_ownership) : "—";
  const sources: FooterSource[] = [
    { source: "Tradier chart quote", at: quote?.trade_time ?? quoteFetchedAt ?? null, label: "Price and range" },
    { source: company.source, at: company.fetched_at, label: "Company" },
    { source: statistics.source, at: statistics.fetched_at, label: "Key statistics" },
    { source: ratios.source, at: ratios.fetched_at, label: "Valuation" },
  ];

  return <div className="space-y-2 text-[11px]">
    <Block name="price" title="Price and range">
      <Rows>
        <Row label="Price" value={spot == null ? "—" : `$${price(spot)}`} title={qTitle} />
        <Row label="Change" value={quote?.change == null ? "—" : `${quote.change >= 0 ? "+" : "−"}$${number(Math.abs(quote.change))} (${quote.change_percentage == null ? "—" : `${quote.change_percentage >= 0 ? "+" : ""}${number(quote.change_percentage)}%`})`} title={qTitle} />
        <Row label="Day range" value={quote?.day_low == null || quote?.day_high == null ? "—" : range(quote.day_low, quote.day_high)} title={qTitle} />
        <Row label="52-week range" value={weekLow == null || weekHigh == null ? "—" : range(weekLow, weekHigh)} title={qTitle} explain={EXPLAIN.week52} />
      </Rows>
      {weekPosition != null && <div title={qTitle} className="relative mt-1 h-1 rounded bg-slate-700" role="img" aria-label={`Price is ${Math.round(weekPosition)} percent through the 52-week range`}><span className="absolute -top-0.5 h-2 w-1 rounded bg-sky-300" style={{ left: `${weekPosition}%` }} /></div>}
    </Block>

    <Dataset name="company" title="Company" block={company} unavailable={noFundamentals}>
      {name && <h4 title={company.name ? blockLabel(company) : qTitle} className="font-medium text-slate-200">{name}</h4>}
      <Rows>
        <Row label="Sector" value={company.sector ?? "—"} title={blockLabel(company)} />
        <Row label="Employees" value={number(company.employees, 0)} title={blockLabel(company)} />
        <Row label="IPO date" value={company.ipo_date ?? "—"} title={blockLabel(company)} />
      </Rows>
      {company.description && <p title={blockLabel(company)} className="line-clamp-2 leading-4 text-slate-400">{company.description}</p>}
    </Dataset>

    <Dataset name="statistics" title="Key statistics" block={statistics} unavailable={noFundamentals}>
      <Rows>
        <Row label="Market cap" value={dollars(statistics.market_cap)} title={blockLabel(statistics)} explain={EXPLAIN.marketCap} />
        <Row label="Enterprise value" value={dollars(statistics.enterprise_value)} title={blockLabel(statistics)} explain={EXPLAIN.enterpriseValue} />
        <Row label="Shares outstanding" value={number(statistics.shares_outstanding, 0)} title={blockLabel(statistics)} explain={EXPLAIN.shares} />
        {!heldInOwnership && <Row label="Held by institutions" value={held} title={`${blockLabel(statistics)}${held === "—" ? " · not reported" : ""}`} explain={EXPLAIN.held} />}
        <Row label="30-day avg volume" value={number(statistics.average_volume_30_day, 0)} title={`30-day average volume · ${blockLabel(statistics)}`} explain={EXPLAIN.volume} />
      </Rows>
    </Dataset>

    <Dataset name="valuation" title="Valuation" block={ratios} unavailable={noFundamentals}>
      <Rows>
        {([["P/E", "pe", EXPLAIN.pe], ["P/S", "price_to_sales", EXPLAIN.ps], ["P/B", "price_to_book", EXPLAIN.pb], ["EV/EBITDA", "ev_to_ebitda", EXPLAIN.evEbitda]] as const).map(([label, field, explain]) => {
          const shown = againstPeers(ratios[field], field, peers, peerGroup);
          return <Row key={field} label={label} value={shown.value} title={`${blockLabel(ratios)}${shown.note}`} explain={explain} />;
        })}
        <Row label="Dividend yield" value={yieldPercent(ratios.dividend_yield)} title={blockLabel(ratios)} explain={EXPLAIN.dividend} />
        <Row label="Beta (60 mo)" value={number(ratios.beta_60_month)} title={`Beta, 60 months · ${blockLabel(ratios)}`} explain={EXPLAIN.beta} />
      </Rows>
    </Dataset>

    <SymbolInfoOwnership symbol={data.symbol} company={company} fund={isFund} unavailable={noFundamentals} sources={sources}>{children}</SymbolInfoOwnership>
  </div>;
}
