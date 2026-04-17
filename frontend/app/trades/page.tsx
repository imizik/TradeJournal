import { api, Account, Trade } from "@/lib/api";

function pnlColor(val: number | null | undefined) {
  if (val == null) return "text-muted-foreground";
  return val >= 0 ? "text-emerald-400" : "text-red-400";
}

function fmt$(val: number | null | undefined) {
  if (val == null) return "—";
  return `${val >= 0 ? "+" : ""}$${val.toFixed(0)}`;
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return "—";
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
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

export default async function TradesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; ticker?: string; account?: string; type?: string }>;
}) {
  const p = await searchParams;
  const qp = new URLSearchParams();
  if (p.status) qp.set("status", p.status);
  if (p.ticker) qp.set("ticker", p.ticker);

  const [allTrades, accounts] = await Promise.all([
    api.trades(qp.toString()),
    api.accounts(),
  ]);
  const accountMap = Object.fromEntries(accounts.map((a: Account) => [a.id, a]));

  // Client-side type + account filters (not in API yet — filter here)
  const trades = allTrades.filter((t) => {
    if (p.account && p.account !== "all") {
      const acct = accountMap[t.account_id];
      if (!acct || acct.type !== p.account) return false;
    }
    if (p.type && p.type !== "all") {
      if (t.instrument_type !== p.type) return false;
    }
    return true;
  });

  function filterUrl(overrides: Record<string, string>) {
    const sp = new URLSearchParams({
      status: p.status ?? "all",
      account: p.account ?? "all",
      type: p.type ?? "all",
      ...overrides,
    });
    // Clean "all" values to keep URLs tidy
    ["status", "account", "type"].forEach((k) => { if (sp.get(k) === "all") sp.delete(k); });
    const s = sp.toString();
    return `/trades${s ? `?${s}` : ""}`;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-foreground">Trades</h1>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-4 text-sm">
        <FilterGroup label="Status">
          {["all", "open", "closed", "expired"].map((s) => (
            <FilterPill key={s} href={filterUrl({ status: s })}
              active={(p.status ?? "all") === s}>{s}</FilterPill>
          ))}
        </FilterGroup>
        <FilterGroup label="Account">
          <FilterPill href={filterUrl({ account: "all" })} active={!p.account || p.account === "all"}>All</FilterPill>
          {accounts.map((a) => (
            <FilterPill key={a.id} href={filterUrl({ account: a.type })}
              active={p.account === a.type}>{a.name}</FilterPill>
          ))}
        </FilterGroup>
        <FilterGroup label="Type">
          {["all", "option", "stock"].map((t) => (
            <FilterPill key={t} href={filterUrl({ type: t })}
              active={(p.type ?? "all") === t}>{t}</FilterPill>
          ))}
        </FilterGroup>
      </div>

      <div className="rounded-lg border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-xs text-muted-foreground uppercase">
            <tr>
              <Th>Ticker</Th>
              <Th>Account</Th>
              <Th>Strike</Th>
              <Th>Type</Th>
              <Th>Expiry</Th>
              <Th>Contracts</Th>
              <Th>Entry</Th>
              <Th>Exit</Th>
              <Th>P&L</Th>
              <Th>P&L %</Th>
              <Th>Hold</Th>
              <Th>Bucket</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {trades.length === 0 && (
              <tr>
                <td colSpan={13} className="px-4 py-8 text-center text-muted-foreground">
                  No trades found.
                </td>
              </tr>
            )}
            {trades.map((t) => (
              <tr key={t.id} className="hover:bg-muted/50">
                <Td>
                  <a href={`/trades/${t.id}`} className="font-semibold hover:underline">
                    {t.ticker}
                  </a>
                </Td>
                <Td>
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                    accountMap[t.account_id]?.type === "roth_ira"
                      ? "bg-purple-900/40 text-purple-300"
                      : "bg-sky-900/40 text-sky-300"
                  }`}>
                    {accountMap[t.account_id]?.name ?? "—"}
                  </span>
                </Td>
                <Td>{t.strike != null ? `$${t.strike}` : <span className="text-muted-foreground/40">—</span>}</Td>
                <Td>{t.option_type ?? <span className="text-muted-foreground/40">—</span>}</Td>
                <Td>{t.expiration ?? <span className="text-muted-foreground/40">—</span>}</Td>
                <Td>{t.contracts}</Td>
                <Td>${t.avg_entry_premium}</Td>
                <Td>{t.avg_exit_premium != null ? `$${t.avg_exit_premium}` : "—"}</Td>
                <Td><span className={pnlColor(t.realized_pnl)}>{fmt$(t.realized_pnl)}</span></Td>
                <Td><span className={pnlColor(t.pnl_pct)}>{fmtPct(t.pnl_pct)}</span></Td>
                <Td>{t.hold_duration_mins != null ? `${Math.round(t.hold_duration_mins)}m` : "—"}</Td>
                <Td>{t.entry_time_bucket ?? "—"}</Td>
                <Td><StatusBadge status={t.status} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
      <span className="text-muted-foreground font-medium mr-0.5">{label}:</span>
      {children}
    </div>
  );
}

function FilterPill({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
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
