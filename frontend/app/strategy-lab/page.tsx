import Link from "next/link";
import StrategyCreateForm from "@/components/strategy-lab/StrategyCreateForm";
import { listStrategies } from "@/lib/strategy-lab/api";
import { formatStrategyDateTime } from "@/lib/strategy-lab/format";

export const metadata = {
  title: "Strategy Lab · Trade Journal",
};

export default async function StrategyLabPage() {
  const strategies = await listStrategies();

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <header>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold text-foreground">Strategy Lab</h1>
          <span className="text-sm text-muted-foreground">Pine research</span>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Keep each Pine revision tied to its hypothesis, execution assumptions, and TradingView evidence.
        </p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section aria-label="Strategies" className="min-w-0 rounded-lg border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3.5 py-2.5">
            <h2 className="text-[13.5px] font-semibold tracking-tight">Strategies</h2>
            <span className="inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium bg-secondary text-muted-foreground tabular-nums">
              {strategies.length} total
            </span>
          </div>
<div className="space-y-3 p-4"><p className="text-xs text-muted-foreground">One research idea can have many controlled Pine versions and runs.</p>
          {strategies.length === 0 ? (
            <div className="rounded-md border border-dashed p-10 text-center">
              <h3 className="text-[13.5px] font-semibold tracking-tight">Create your first strategy</h3>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                Name the setup here, then save the exact Pine source and assumptions as version 1.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {strategies.map((strategy) => (
                <Link
                  key={strategy.id}
                  href={`/strategy-lab/strategies/${strategy.id}`}
                  className="group rounded-md border bg-background p-4 transition-colors hover:bg-secondary/50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-foreground">{strategy.name}</h3>
                      <span className="mt-2 inline-flex h-[22px] items-center rounded-md px-2 text-[11.5px] font-medium bg-secondary text-muted-foreground">
                        {humanize(strategy.setup_type)}
                      </span>
                    </div>
                    <span aria-hidden className="text-muted-foreground transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </div>
                  <p className="mt-4 line-clamp-3 min-h-10 text-sm leading-relaxed text-muted-foreground">
                    {strategy.description || "No strategy description yet."}
                  </p>
                  <p className="mt-4 text-xs text-muted-foreground">
                    Updated {formatDate(strategy.updated_at)}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </div></section>

        <div className="xl:sticky xl:top-6">
          <StrategyCreateForm />
        </div>
      </div>
    </div>
  );
}

function humanize(value: string) {
  return value.replace(/_/g, " ");
}

function formatDate(value: string) {
  return formatStrategyDateTime(value, "UTC", {
    hour: undefined,
    minute: undefined,
    timeZoneName: undefined,
  });
}
