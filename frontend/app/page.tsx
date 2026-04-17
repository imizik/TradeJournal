import { api, Account, Fill, Trade } from "@/lib/api";
import DashboardActions from "@/components/DashboardActions";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

function fmtMoney(val: number | null | undefined) {
  if (val == null) return "-";
  return `$${val.toFixed(2)}`;
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "-";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function fmtQty(val: number | null | undefined) {
  if (val == null) return "-";
  const rounded = Number(val.toFixed(6));
  return String(rounded);
}

function fmtDateShort(val: string | null | undefined) {
  if (!val) return "-";
  return new Date(val).toLocaleDateString();
}

function fmtOptionType(val: string | null | undefined) {
  if (!val) return <span className="text-muted-foreground/40">-</span>;
  return val.toUpperCase();
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
    qtyLeft: qtyLeft || trade.contracts,
    capitalLeft,
    realizedSoFar: trade.realized_pnl,
    lastActivityAt: fills.at(-1)?.executed_at ?? trade.opened_at,
  };
}

function StatusBadge({ status }: { status: Trade["status"] }) {
  const cls =
    status === "open"
      ? "bg-blue-900/40 text-blue-300"
      : status === "expired"
        ? "bg-muted text-muted-foreground"
        : "bg-muted text-foreground/70";

  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
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
  const openTradeFillEntries = await Promise.all(
    openTrades.map(async (trade) => [trade.id, await api.tradeFills(trade.id)] as const),
  );
  const openTradeFills = Object.fromEntries(openTradeFillEntries);
  const openPositionRows = openTrades.map((trade) => ({
    trade,
    meta: buildOpenPositionMeta(trade, openTradeFills[trade.id] ?? []),
  }));
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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Today's P&L" value={fmt$(stats.today_pnl)} valueClass={pnlColor(stats.today_pnl)} />
        <StatCard label="Total P&L" value={fmt$(stats.total_pnl)} valueClass={pnlColor(stats.total_pnl)} />
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

          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="bg-muted text-xs uppercase text-muted-foreground">
                <tr>
                  <Th>Ticker</Th>
                  <Th>Account</Th>
                  <Th>Instrument</Th>
                  <Th>Strike</Th>
                  <Th>Type</Th>
                  <Th>Expiry</Th>
                  <Th>Qty Left</Th>
                  <Th>Avg Cost</Th>
                  <Th>Cost Left</Th>
                  <Th>Realized</Th>
                  <Th>Opened</Th>
                  <Th>Last Activity</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {openPositionRows.map(({ trade, meta }) => (
                  <tr key={trade.id} className="hover:bg-muted/50">
                    <Td>
                      <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                        {trade.ticker}
                      </a>
                    </Td>
                    <Td>
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                          accountMap[trade.account_id]?.type === "roth_ira"
                            ? "bg-purple-900/40 text-purple-300"
                            : "bg-sky-900/40 text-sky-300"
                        }`}
                      >
                        {accountMap[trade.account_id]?.name ?? "-"}
                      </span>
                    </Td>
                    <Td>
                      <span className="capitalize">{trade.instrument_type}</span>
                    </Td>
                    <Td>{trade.strike != null ? fmtMoney(trade.strike) : <span className="text-muted-foreground/40">-</span>}</Td>
                    <Td>{fmtOptionType(trade.option_type)}</Td>
                    <Td>{trade.expiration ? fmtDateShort(trade.expiration) : <span className="text-muted-foreground/40">-</span>}</Td>
                    <Td>
                      <div className="flex flex-col">
                        <span className="font-medium">{fmtQty(meta.qtyLeft)}</span>
                        <span className="text-xs text-muted-foreground">
                          {`opened ${fmtQty(meta.openedQty)}${meta.exitedQty > 0 ? ` | trimmed ${fmtQty(meta.exitedQty)}` : ""}`}
                        </span>
                      </div>
                    </Td>
                    <Td>{fmtMoney(trade.avg_entry_premium)}</Td>
                    <Td>{fmtMoney(meta.capitalLeft)}</Td>
                    <Td>
                      <span className={pnlColor(meta.realizedSoFar)}>{fmt$(meta.realizedSoFar)}</span>
                    </Td>
                    <Td>{fmtDateShort(trade.opened_at)}</Td>
                    <Td>{fmtDateShort(meta.lastActivityAt)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Recent Closed
        </h2>
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <Th>Ticker</Th>
                <Th>Account</Th>
                <Th>Instrument</Th>
                <Th>Strike</Th>
                <Th>Type</Th>
                <Th>Expiry</Th>
                <Th>P&amp;L</Th>
                <Th>P&amp;L %</Th>
                <Th>Hold</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {recentClosed.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                    No closed trades yet.
                  </td>
                </tr>
              )}
              {recentClosed.map((trade) => (
                <tr key={trade.id} className="hover:bg-muted/50">
                  <Td>
                    <a href={`/trades/${trade.id}`} className="font-semibold hover:underline">
                      {trade.ticker}
                    </a>
                  </Td>
                  <Td>
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                        accountMap[trade.account_id]?.type === "roth_ira"
                          ? "bg-purple-900/40 text-purple-300"
                          : "bg-sky-900/40 text-sky-300"
                      }`}
                    >
                      {accountMap[trade.account_id]?.name ?? "-"}
                    </span>
                  </Td>
                  <Td>{trade.instrument_type}</Td>
                  <Td>{trade.strike != null ? `$${trade.strike}` : <span className="text-muted-foreground/40">-</span>}</Td>
                  <Td>{trade.option_type ?? <span className="text-muted-foreground/40">-</span>}</Td>
                  <Td>{trade.expiration ?? <span className="text-muted-foreground/40">-</span>}</Td>
                  <Td>
                    <span className={pnlColor(trade.realized_pnl)}>{fmt$(trade.realized_pnl)}</span>
                  </Td>
                  <Td>
                    <span className={pnlColor(trade.pnl_pct)}>{fmtPct(trade.pnl_pct)}</span>
                  </Td>
                  <Td>{trade.hold_duration_mins ? `${Math.round(trade.hold_duration_mins)}m` : "-"}</Td>
                  <Td>
                    <StatusBadge status={trade.status} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3">{children}</td>;
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
