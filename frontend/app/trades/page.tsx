import { api } from "@/lib/serverApi";
import type { Account } from "@/lib/api";
import TradesTable from "@/components/TradesTable";
import TradesTickerInput from "@/components/TradesTickerInput";
import { newYorkToday } from "@/lib/format";
import { filterTradesByAccount } from "@/lib/tradeFilters";

export default async function TradesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; ticker?: string | string[]; account?: string; account_id?: string; type?: string }>;
}) {
  const p = await searchParams;
  const qp = new URLSearchParams();
  if (p.status) qp.set("status", p.status);
  const rawTicker = Array.isArray(p.ticker) ? p.ticker[0] : p.ticker;
  const ticker = rawTicker?.trim().toUpperCase();
  if (ticker) qp.set("ticker", ticker);

  const [allTrades, accounts] = await Promise.all([
    api.trades(qp.toString()),
    api.accounts(),
  ]);
  const accountMap = Object.fromEntries(accounts.map((a: Account) => [a.id, a]));

  // Client-side type + account filters (not in API yet — filter here)
  const scopedTrades = filterTradesByAccount(allTrades, accountMap, p.account_id, p.account);
  const trades = p.type && p.type !== "all" ? scopedTrades.filter((t) => t.instrument_type === p.type) : scopedTrades;

  function filterUrl(overrides: Record<string, string>) {
    const sp = new URLSearchParams({
      status: p.status ?? "all",
      account: p.account ?? "all",
      type: p.type ?? "all",
      ...(p.account_id ? { account_id: p.account_id } : {}),
      ...overrides,
    });
    // Clean "all" values to keep URLs tidy
    ["status", "account", "type"].forEach((k) => { if (sp.get(k) === "all") sp.delete(k); });
    if (sp.get("account_id")) sp.delete("account");
    if (sp.get("account") === "") sp.delete("account");
    if (!sp.get("account_id")) sp.delete("account_id");
    if (ticker && overrides.ticker !== "") sp.set("ticker", ticker);
    const s = sp.toString();
    return `/trades${s ? `?${s}` : ""}`;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-foreground">Trades</h1>
        {ticker && <p className="text-sm text-muted-foreground">Ticker {ticker}</p>}
      </div>

      {/* Filters: one wrapping row so the table starts high, even on a phone. */}
      <form action="/trades" method="get" className="flex flex-wrap items-center gap-x-5 gap-y-1" aria-label="Search trades">
        {p.status && <input type="hidden" name="status" value={p.status} />}
        {p.account && <input type="hidden" name="account" value={p.account} />}
        {p.account_id && <input type="hidden" name="account_id" value={p.account_id} />}
        {p.type && <input type="hidden" name="type" value={p.type} />}
        <FilterGroup label="Status">
          {["all", "open", "closed", "expired"].map((s) => (
            <FilterPill key={s} href={filterUrl({ status: s })}
              active={(p.status ?? "all") === s}>{s}</FilterPill>
          ))}
        </FilterGroup>
        <FilterGroup label="Account">
          <FilterPill href={filterUrl({ account: "all", account_id: "" })} active={!p.account_id && (!p.account || p.account === "all")}>All</FilterPill>
          {accounts.map((a) => (
            <FilterPill key={a.id} href={filterUrl({ account: "", account_id: a.id })}
              active={p.account_id ? p.account_id === a.id : p.account === a.type}>{a.name}</FilterPill>
          ))}
        </FilterGroup>
        <FilterGroup label="Type">
          {["all", "option", "stock"].map((t) => (
            <FilterPill key={t} href={filterUrl({ type: t })}
              active={(p.type ?? "all") === t}>{t}</FilterPill>
          ))}
        </FilterGroup>
        <TradesTickerInput initial={ticker ?? ""} />
      </form>

      <TradesTable returnTo={filterUrl({}) === "/trades" ? undefined : filterUrl({})} trades={trades} accountMap={accountMap} thisYear={Number(newYorkToday().slice(0, 4))} />
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-1">
      <span className="mr-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

/** A filter chip; the link is taller than the chip so it stays easy to tap. */
function FilterPill({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <a href={href} aria-current={active ? "true" : undefined} className="group inline-flex min-h-9 items-center">
      <span className={`inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium capitalize transition-colors ${
        active ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground group-hover:text-foreground"
      }`}>{children}</span>
    </a>
  );
}
