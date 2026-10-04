import Link from "next/link";
import { api } from "@/lib/api";
import AnalyticsExplorer from "@/components/AnalyticsExplorer";

type Params = { start?: string; end?: string; account_id?: string; instrument_type?: string };

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const name of ["start", "end", "account_id", "instrument_type"] as const) {
    if (typeof params[name] === "string" && params[name]) query.set(name, params[name]);
  }
  const [accounts, result] = await Promise.allSettled([api.accounts(), api.analytics(query.toString())]);
  const accountOptions = accounts.status === "fulfilled" ? accounts.value : [];
  const invalidFilters = result.status === "rejected" && /-> (400|404|422)/.test(String(result.reason));

  return (
    <div className="min-w-0 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="mt-1 text-sm text-muted-foreground">Explore your results and the trades behind them.</p>
      </div>
      <form action="/analytics" className="grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2 lg:grid-cols-5">
        <label className="min-w-0 text-xs text-muted-foreground">
          Closed from
          <input aria-label="Closed from" name="start" type="date" defaultValue={params.start ?? ""}
            className="mt-1 block w-full min-w-0 rounded-md border bg-background p-2 text-sm text-foreground" />
        </label>
        <label className="min-w-0 text-xs text-muted-foreground">
          Closed through
          <input aria-label="Closed through" name="end" type="date" defaultValue={params.end ?? ""}
            className="mt-1 block w-full min-w-0 rounded-md border bg-background p-2 text-sm text-foreground" />
        </label>
        <label className="text-xs text-muted-foreground">
          Account
          <select aria-label="Account" name="account_id" defaultValue={params.account_id ?? ""}
            className="mt-1 block w-full rounded-md border bg-background p-2 text-sm text-foreground">
            <option value="">All accounts</option>
            {accountOptions.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.last4}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted-foreground">
          Instrument
          <select aria-label="Instrument" name="instrument_type" defaultValue={params.instrument_type ?? ""}
            className="mt-1 block w-full rounded-md border bg-background p-2 text-sm text-foreground">
            <option value="">All instruments</option>
            <option value="stock">Stocks</option>
            <option value="option">Options</option>
          </select>
        </label>
        <div className="flex items-end gap-3">
          <button type="submit" className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background">Apply filters</button>
          <Link href="/analytics" className="py-2 text-sm text-muted-foreground hover:text-foreground">Reset</Link>
        </div>
      </form>
      {result.status === "fulfilled" ? (
        <AnalyticsExplorer key={query.toString()} data={result.value} accounts={accountOptions} />
      ) : (
        <p role="alert" className="rounded-lg border bg-card p-4 text-sm">
          {invalidFilters
            ? "Check your filters: use valid dates with the start on or before the end, and select an available account and instrument."
            : "Analytics could not load. Try again in a moment."}
        </p>
      )}
    </div>
  );
}
