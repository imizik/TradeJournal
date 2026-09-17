import { api, Account, Fill, PositionQuote } from "@/lib/api";
import DashboardActions from "@/components/DashboardActions";
import { OpenPositionsTable, RecentClosedTable } from "@/components/DashboardTables";
import PerformanceOverview from "@/components/PerformanceOverview";
import {
  buildOpenPositionMeta,
  computeUnrealizedPnl,
  getPositionMarketValue,
  type OpenPositionRow,
} from "@/lib/dashboard";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

// Main dashboard route.
export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ account?: string; type?: string }>;
}) {
  const resolvedParams = await searchParams;
  const statsParams = new URLSearchParams();

  if (resolvedParams.account && resolvedParams.account !== "all") {
    statsParams.set("account", resolvedParams.account);
  }
  if (resolvedParams.type && resolvedParams.type !== "all") {
    statsParams.set("type", resolvedParams.type);
  }

  const statsQuery = statsParams.toString();

  const [stats, allTrades, accounts, params] = await Promise.all([
    api.stats(statsQuery),
    api.trades(),
    api.accounts(),
    Promise.resolve(resolvedParams),
  ]);

  const accountMap = Object.fromEntries(accounts.map((a: Account) => [a.id, a]));
  const accountOptions = Array.from(new Map(accounts.map((a) => [a.type, a])).values());

  function filterUrl(overrides: Record<string, string>) {
    const sp = new URLSearchParams({
      account: params.account ?? "all",
      type: params.type ?? "all",
      ...overrides,
    });

    ["account", "type"].forEach((key) => {
      if (sp.get(key) === "all") sp.delete(key);
    });

    const s = sp.toString();
    return `/${s ? `?${s}` : ""}`;
  }

  const trades = allTrades.filter((trade) => {
    if (params.account && params.account !== "all") {
      const acct = accountMap[trade.account_id];
      if (!acct || acct.type !== params.account) return false;
    }

    if (params.type && params.type !== "all" && trade.instrument_type !== params.type) {
      return false;
    }

    return true;
  });

  const openTrades = trades.filter((trade) => trade.status === "open");

  // Build position quote requests for option positions
  const optionPositions = openTrades
    .filter((t) => t.instrument_type === "option" && t.expiration && t.strike != null && t.option_type)
    .map((t) => ({
      ticker: t.ticker,
      expiration: t.expiration!,
      strike: t.strike!,
      option_type: t.option_type!,
    }));

  // Stock tickers that aren't covered by option positions
  const stockTickers = [...new Set(
    openTrades.filter((t) => t.instrument_type === "stock").map((t) => t.ticker)
  )];

  const [bulkFills, optionQuotes, stockPrices] = await Promise.all([
    openTrades.length > 0
      ? api.bulkTradeFills(openTrades.map((t) => t.id))
      : Promise.resolve({} as Record<string, Fill[]>),
    optionPositions.length > 0
      ? api.positionQuotes(optionPositions)
      : Promise.resolve([] as PositionQuote[]),
    stockTickers.length > 0
      ? api.stockQuotes(stockTickers)
      : Promise.resolve({} as Record<string, number | null>),
  ]);

  const openTradeFills = bulkFills;

  // Build a quotes map keyed by trade id
  const quotesByTradeId: Record<string, PositionQuote> = {};
  let optIdx = 0;
  for (const trade of openTrades) {
    if (trade.instrument_type === "option" && trade.expiration && trade.strike != null && trade.option_type) {
      if (optIdx < optionQuotes.length) {
        quotesByTradeId[trade.id] = optionQuotes[optIdx];
        optIdx++;
      }
    } else if (trade.instrument_type === "stock") {
      quotesByTradeId[trade.id] = {
        ticker: trade.ticker,
        underlying_price: stockPrices[trade.ticker] ?? null,
        option_last_price: null,
        option_bid: null,
        option_ask: null,
        option_mid: null,
        option_iv: null,
      };
    }
  }
  const openPositionRows: OpenPositionRow[] = openTrades
    .map((trade) => ({
      trade,
      meta: buildOpenPositionMeta(trade, openTradeFills[trade.id] ?? []),
    }))
    .filter(({ meta }) => meta.qtyLeft > 0);

  const positionMarks = openPositionRows.map(({ trade, meta }) => ({
    trade,
    meta,
    marketValue: getPositionMarketValue(trade, meta, quotesByTradeId[trade.id]),
    unrealizedPnl: computeUnrealizedPnl(trade, meta, quotesByTradeId[trade.id]),
  }));
  const quotedPositions = positionMarks.filter(({ marketValue }) => marketValue != null);
  const allPositionsQuoted = openPositionRows.length > 0 && quotedPositions.length === openPositionRows.length;
  const totalUnrealizedPnl = allPositionsQuoted && positionMarks.every(({ unrealizedPnl }) => unrealizedPnl != null)
    ? positionMarks.reduce((sum, { unrealizedPnl }) => sum + (unrealizedPnl ?? 0), 0)
    : null;
  const grossMarkedValue = quotedPositions.length > 0
    ? quotedPositions.reduce((sum, { marketValue }) => sum + (marketValue ?? 0), 0)
    : null;
  const netMarkedValue = allPositionsQuoted && positionMarks.every(({ meta }) => meta.direction !== "unknown")
    ? positionMarks.reduce((sum, { meta, marketValue }) =>
        sum + (meta.direction === "short" ? -1 : 1) * (marketValue ?? 0), 0)
    : null;
  const largestMarkedPosition = quotedPositions.reduce<typeof quotedPositions[number] | null>(
    (largest, position) => !largest || (position.marketValue ?? 0) > (largest.marketValue ?? 0) ? position : largest,
    null,
  );

  const recentClosed = trades.filter((trade) => trade.status !== "open").slice(0, 10);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
        <DashboardActions />
      </div>

      <div className="flex flex-wrap gap-4 text-sm">
        <FilterGroup label="Account">
          <FilterPill href={filterUrl({ account: "all" })} active={!params.account || params.account === "all"}>
            All
          </FilterPill>
          {accountOptions.map((account) => (
            <FilterPill
              key={account.id}
              href={filterUrl({ account: account.type })}
              active={params.account === account.type}
            >
              {account.name}
            </FilterPill>
          ))}
        </FilterGroup>

        <FilterGroup label="Type">
          {["all", "option", "stock"].map((type) => (
            <FilterPill key={type} href={filterUrl({ type })} active={(params.type ?? "all") === type}>
              {type}
            </FilterPill>
          ))}
        </FilterGroup>
      </div>

      <PerformanceOverview trades={trades} />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Today's Closed P&L" value={fmt$(stats.today_pnl)} valueClass={pnlColor(stats.today_pnl)} />
        <StatCard
          label="Unrealized P&L"
          value={totalUnrealizedPnl != null ? fmt$(totalUnrealizedPnl) : "-"}
          valueClass={pnlColor(totalUnrealizedPnl)}
          detail={`${quotedPositions.length} of ${openPositionRows.length} open positions quoted`}
        />
        <StatCard label="Open Positions" value={String(openPositionRows.length)} />
      </div>

      {openPositionRows.length > 0 && (
        <section>
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Current Exposure
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Quoted market value; option values use premium × 100. This does not include account cash or represent maximum loss.
              </p>
            </div>
          </div>
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            <StatCard
              label="Gross Marked Value"
              value={grossMarkedValue != null ? fmtMoney(grossMarkedValue) : "-"}
              detail={`${quotedPositions.length} of ${openPositionRows.length} positions marked`}
            />
            <StatCard
              label="Net Marked Value"
              value={netMarkedValue != null ? fmtSignedMoney(netMarkedValue) : "-"}
              valueClass={pnlColor(netMarkedValue)}
            />
            <StatCard
              label="Largest Position"
              value={largestMarkedPosition ? `${largestMarkedPosition.trade.ticker} · ${fmtMoney(largestMarkedPosition.marketValue)}` : "-"}
            />
          </div>

          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Open Positions
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Shows what is still open, what has already been trimmed, and how much cost basis is still left in the
                position.
              </p>
            </div>
          </div>

          <OpenPositionsTable rows={openPositionRows} accountMap={accountMap} quotes={quotesByTradeId} />
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Recent Closed
        </h2>
        <RecentClosedTable trades={recentClosed} accountMap={accountMap} />
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  valueClass = "text-foreground",
  detail,
}: {
  label: string;
  value: string;
  valueClass?: string;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
      {detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}
    </div>
  );
}

function fmtMoney(val: number | null | undefined) {
  if (val == null) return "-";
  return `$${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtSignedMoney(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : "-"}$${Math.abs(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="mr-0.5 font-medium text-muted-foreground">{label}:</span>
      {children}
    </div>
  );
}

function FilterPill({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize transition-colors ${
        active
          ? "bg-foreground text-background"
          : "bg-secondary text-muted-foreground hover:bg-secondary/80"
      }`}
    >
      {children}
    </a>
  );
}
