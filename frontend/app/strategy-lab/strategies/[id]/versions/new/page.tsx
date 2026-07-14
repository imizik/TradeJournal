import Link from "next/link";
import StrategyVersionForm from "@/components/strategy-lab/StrategyVersionForm";
import { getStrategy } from "@/lib/strategy-lab/api";

export default async function NewStrategyVersionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const strategy = await getStrategy(id);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <Link href={`/strategy-lab/strategies/${strategy.id}`} className="text-sm text-muted-foreground hover:text-foreground">
          ← {strategy.name}
        </Link>
        <h1 className="mt-3 text-2xl font-semibold text-foreground">New Pine version</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Capture the exact code, controlled change, and execution assumptions before running it in TradingView.
        </p>
      </header>

      <StrategyVersionForm strategyId={strategy.id} existingVersions={strategy.versions} />
    </div>
  );
}
