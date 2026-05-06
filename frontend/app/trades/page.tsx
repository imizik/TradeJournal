import { api, Account } from "@/lib/api";
import TradesTable from "@/components/TradesTable";

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

      <TradesTable trades={trades} accountMap={accountMap} />
    </div>
  );
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
