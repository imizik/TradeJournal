import { api } from "@/lib/serverApi";
import type { Account } from "@/lib/api";
import TradesTable from "@/components/TradesTable";
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

      <form action="/trades" method="get" className="flex flex-wrap items-end gap-2" aria-label="Search trades">
        {p.status && <input type="hidden" name="status" value={p.status} />}
        {p.account && <input type="hidden" name="account" value={p.account} />}
        {p.account_id && <input type="hidden" name="account_id" value={p.account_id} />}
        {p.type && <input type="hidden" name="type" value={p.type} />}
        <label className="grid gap-1 text-xs text-muted-foreground">Ticker
          <input name="ticker" defaultValue={p.ticker ?? ""} placeholder="All tickers" className="h-9 w-48 rounded-md border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground" />
        </label>
        <button className="min-h-11 rounded-md border px-3 text-sm hover:bg-secondary sm:min-h-9" type="submit">Apply ticker</button>
        {ticker && <a className="inline-flex min-h-9 items-center px-2 text-sm text-muted-foreground hover:text-foreground" href={filterUrl({ ticker: "" })}>Clear ticker</a>}
      </form>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-4 text-sm">
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
      </div>

      <TradesTable returnTo={filterUrl({}) === "/trades" ? undefined : filterUrl({})} trades={trades} accountMap={accountMap} thisYear={Number(newYorkToday().slice(0, 4))} />
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
      className={`inline-flex min-h-11 items-center rounded-full px-2.5 text-xs font-medium capitalize transition-colors sm:min-h-9 ${
        active
          ? "bg-foreground text-background"
          : "bg-secondary text-muted-foreground hover:bg-secondary/80"
      }`}
    >
      {children}
    </a>
  );
}
