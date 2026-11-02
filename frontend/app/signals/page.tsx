import SignalsRefresh from "@/components/SignalsRefresh";
import SignalsHistory from "@/components/SignalsHistory";
import { api } from "@/lib/serverApi";

export const dynamic = "force-dynamic";

export default async function SignalsPage({ searchParams }: { searchParams: Promise<{ filter?: string }> }) {
  const alerts = await api.tradingViewAlerts("limit=200");
  const { filter } = await searchParams;
  const initialFilter = ["all", "tradeable", "pending", "skipped", "error"].includes(filter ?? "") ? filter as "all" | "tradeable" | "pending" | "skipped" | "error" : "all";

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <h1 className="text-xl font-semibold">Signals</h1>
            <span className="text-sm tabular-nums text-muted-foreground">{alerts.length} recent</span>
          </div>
          <SignalsRefresh />
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          TradingView alerts and their latest scalp analysis. Read-only: nothing here places an order or
          changes your fills and trades.
        </p>
      </div>

      <SignalsHistory alerts={alerts} initialFilter={initialFilter} />
    </div>
  );
}
