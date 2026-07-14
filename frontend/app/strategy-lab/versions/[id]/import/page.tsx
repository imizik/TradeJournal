import Link from "next/link";
import RunImportWizard from "@/components/strategy-lab/RunImportWizard";
import { getVersion } from "@/lib/strategy-lab/api";

export default async function StrategyRunImportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const version = await getVersion(id);

  return (
    <div className="mx-auto max-w-[1440px] space-y-6">
      <header>
        <Link
          href={`/strategy-lab/versions/${version.id}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to {version.version_label}
        </Link>
        <p className="mt-5 text-xs font-medium uppercase tracking-[0.18em] text-sky-300">
          TradingView evidence
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Import a strategy run</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Preview the Strategy Tester List of Trades CSV, verify its parsing, then bind the
          result to <span className="font-medium text-foreground/90">{version.version_label}</span>.
          This never creates journal fills or trades.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span className="rounded-full border bg-card px-2.5 py-1 capitalize">{version.status}</span>
          <span
            className="rounded-full border bg-card px-2.5 py-1 font-mono"
            title={version.source_fingerprint}
          >
            Version fingerprint {version.source_fingerprint.slice(0, 14)}…
          </span>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Version hypothesis
          </h2>
          <p className={`mt-2 text-sm leading-relaxed ${version.hypothesis ? "text-foreground/90" : "text-muted-foreground"}`}>
            {version.hypothesis || "No hypothesis was recorded for this version."}
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Controlled change
          </h2>
          <p className={`mt-2 text-sm leading-relaxed ${version.change_summary ? "text-foreground/90" : "text-muted-foreground"}`}>
            {version.change_summary || "No controlled-change summary was recorded."}
          </p>
        </div>
      </section>

      <RunImportWizard version={version} />
    </div>
  );
}
