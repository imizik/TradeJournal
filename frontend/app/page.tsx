import { api, Account, Fill, Trade, PositionQuote } from "@/lib/api";
import DashboardActions from "@/components/DashboardActions";
import { OpenPositionsTable, RecentClosedTable } from "@/components/DashboardTables";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function isEntryFill(fill: Fill) {
  return fill.side === "buy_to_open" || fill.side === "sell_to_open" || fill.side === "buy";
}

function buildOpenPositionMeta(trade: Trade, fills: Fill[]) {
  const entryQty = fills.filter(isEntryFill).reduce((sum, fill) => sum + fill.contracts, 0);
  const exitedQty = fills.filter((fill) => !isEntryFill(fill)).reduce((sum, fill) => sum + fill.contracts, 0);
  const openedQty = entryQty || trade.contracts;
  const qtyLeft = Math.max(openedQty - exitedQty, 0);
  const capitalLeft = qtyLeft * trade.avg_entry_premium;

  return {
    openedQty,
    exitedQty,
    qtyLeft,
    capitalLeft,
    realizedSoFar: trade.realized_pnl,
    lastActivityAt: fills.at(-1)?.executed_at ?? trade.opened_at,
  };
}

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

  const [openTradeFillEntries, optionQuotes, stockPrices] = await Promise.all([
    Promise.all(
      openTrades.map(async (trade) => [trade.id, await api.tradeFills(trade.id)] as const),
    ),
    optionPositions.length > 0
      ? api.positionQuotes(optionPositions)
      : Promise.resolve([] as PositionQuote[]),
    stockTickers.length > 0
      ? api.stockQuotes(stockTickers)
      : Promise.resolve({} as Record<string, number | null>),
  ]);

  // Build a quotes map keyed by trade id
  const quotesByTradeId: Record<string, PositionQuote> = {};
  // Map option quotes back to trades
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

  const openTradeFills = Object.fromEntries(openTradeFillEntries);
  const openPositionRows = openTrades
    .map((trade) => ({
      trade,
      meta: buildOpenPositionMeta(trade, openTradeFills[trade.id] ?? []),
    }))
    .filter(({ meta }) => meta.qtyLeft > 0);

  // Sum unrealized P&L across all open positions that have a live quote
  const totalUnrealizedPnl = openPositionRows.reduce<number | null>((sum, { trade, meta }) => {
    const quote = quotesByTradeId[trade.id];
    if (!quote) return sum;
    const rawMark =
      trade.instrument_type === "stock"
        ? quote.underlying_price
        : (quote.option_mid ?? quote.option_last_price);
    if (rawMark == null) return sum;
    const markPerContract = trade.instrument_type === "option" ? rawMark * 100 : rawMark;
    const pnl = (markPerContract - trade.avg_entry_premium) * meta.qtyLeft;
    return (sum ?? 0) + pnl;
  }, null);

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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
        <StatCard label="Today's P&L" value={fmt$(stats.today_pnl)} valueClass={pnlColor(stats.today_pnl)} />
        {(() => {
          const totalPnl =
            totalUnrealizedPnl != null ? stats.total_pnl + totalUnrealizedPnl : stats.total_pnl;
          return (
            <StatCard label="Total P&L" value={fmt$(totalPnl)} valueClass={pnlColor(totalPnl)} />
          );
        })()}
        <StatCard label="Realized P&L" value={fmt$(stats.total_pnl)} valueClass={pnlColor(stats.total_pnl)} />
        <StatCard
          label="Unrealized P&L"
          value={totalUnrealizedPnl != null ? fmt$(totalUnrealizedPnl) : "-"}
          valueClass={pnlColor(totalUnrealizedPnl)}
        />
        <StatCard label="Win Rate" value={`${((stats.win_rate ?? 0) * 100).toFixed(1)}%`} />
        <StatCard label="Open Positions" value={String(stats.open_trades)} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Avg Winner" value={fmtPct(stats.avg_win_pct)} valueClass="text-emerald-400" />
        <StatCard label="Avg Loser" value={fmtPct(stats.avg_loss_pct)} valueClass="text-red-400" />
        <StatCard label="Avg Hold" value={stats.avg_hold_mins ? `${Math.round(stats.avg_hold_mins)}m` : "-"} />
      </div>

      {openPositionRows.length > 0 && (
        <section>
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
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
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
