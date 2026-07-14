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
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-sky-300">Pine research</p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Strategy Lab</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Keep each Pine revision tied to its hypothesis, execution assumptions, and TradingView evidence.
        </p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Strategies</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                One research idea can have many controlled Pine versions and runs.
              </p>
            </div>
            <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-muted-foreground">
              {strategies.length} total
            </span>
          </div>

          {strategies.length === 0 ? (
            <div className="rounded-lg border border-dashed bg-card p-10 text-center">
              <h3 className="font-semibold text-foreground">Create your first strategy</h3>
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
                  className="group rounded-lg border bg-card p-5 transition-colors hover:bg-secondary/50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-foreground group-hover:text-white">{strategy.name}</h3>
                      <span className="mt-2 inline-flex rounded-full border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
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
        </section>

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
