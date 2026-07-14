"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  commitImport,
  previewImport,
  recalculateMetrics,
} from "@/lib/strategy-lab/api";
import {
  formatDecimal,
  formatPercentPoints,
  formatStrategyDateTime,
} from "@/lib/strategy-lab/format";
import type {
  ImportIssue,
  ParsedStrategyTradePreview,
  StrategyRunImportPreview,
  StrategyVersionDetail,
} from "@/lib/strategy-lab/types";

type Phase = "idle" | "previewing" | "ready" | "committing";

const inputClass =
  "h-10 w-full rounded-md border bg-background px-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring";

export default function RunImportWizard({
  version,
}: {
  version: StrategyVersionDetail;
}) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [sourceTimezone, setSourceTimezone] = useState("America/New_York");
  const [preview, setPreview] = useState<StrategyRunImportPreview | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [backtestStart, setBacktestStart] = useState("");
  const [backtestEnd, setBacktestEnd] = useState("");
  const [initialCapital, setInitialCapital] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [extendedHours, setExtendedHours] = useState(false);
  const [notes, setNotes] = useState("");

  const invalidatePreview = () => {
    setPreview(null);
    setError(null);
    setPhase("idle");
  };

  const selectFile = (next: File | null) => {
    setFile(next);
    invalidatePreview();
  };

  const changeTimezone = (next: string) => {
    setSourceTimezone(next);
    invalidatePreview();
  };

  const runPreview = async () => {
    if (!file) {
      setError("Choose a TradingView List of Trades CSV first.");
      return;
    }
    if (!sourceTimezone.trim()) {
      setError("Enter the timezone TradingView used for these timestamps.");
      return;
    }

    setPhase("previewing");
    setError(null);
    try {
      const next = await previewImport({
        strategyVersionId: version.id,
        sourceTimezone: sourceTimezone.trim(),
        file,
      });
      setPreview(next);
      setPhase("ready");
    } catch (caught) {
      setPreview(null);
      setPhase("idle");
      setError(caught instanceof Error ? caught.message : "Unable to preview this CSV.");
    }
  };

  const commit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !preview?.can_commit) return;

    setPhase("committing");
    setError(null);
    try {
      const result = await commitImport({
        file,
        metadata: {
          strategy_version_id: version.id,
          expected_version_fingerprint: version.source_fingerprint,
          expected_source_sha256: preview.source_sha256,
          expected_preview_fingerprint: preview.preview_fingerprint,
          symbol: symbol.trim(),
          timeframe: timeframe.trim(),
          source_timezone: sourceTimezone.trim(),
          backtest_start: backtestStart || null,
          backtest_end: backtestEnd || null,
          initial_capital: initialCapital.trim() || null,
          currency: currency.trim().toUpperCase() || "USD",
          extended_hours: extendedHours,
          notes: notes.trim() || null,
        },
      });

      // The run is already durable at this point. Metrics are a separate,
      // repeatable calculation, so a failure here must never retry the import.
      try {
        await recalculateMetrics(result.run_id);
      } catch {
        // The run detail page exposes the pending state and a safe retry action.
      }
      router.push(`/strategy-lab/runs/${result.run_id}`);
      router.refresh();
    } catch (caught) {
      setPhase("ready");
      setError(caught instanceof Error ? caught.message : "Unable to import this run.");
    }
  };

  const busy = phase === "previewing" || phase === "committing";

  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-card p-5">
        <StepHeading
          number="1"
          title="Preview the TradingView export"
          description="Nothing is stored until the preview passes and you confirm the run metadata."
          complete={Boolean(preview)}
        />

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.55fr)_auto] lg:items-end">
          <Field label="List of Trades CSV" htmlFor="strategy-run-csv">
            <label htmlFor="strategy-run-csv" className="flex h-10 cursor-pointer items-center gap-3 rounded-md border bg-background px-3 text-sm hover:bg-secondary/40">
              <FileSpreadsheet className="h-4 w-4 shrink-0 text-sky-300" />
              <span className="min-w-0 flex-1 truncate text-foreground/85">
                {file?.name || "Choose CSV file"}
              </span>
              <input
                id="strategy-run-csv"
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                disabled={busy}
                onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              />
            </label>
          </Field>
          <Field
            label="Source timezone"
            htmlFor="strategy-run-source-timezone"
            hint="Timezone shown in TradingView, not your browser timezone."
          >
            <input
              id="strategy-run-source-timezone"
              className={inputClass}
              value={sourceTimezone}
              list="strategy-lab-timezones"
              disabled={busy}
              onChange={(event) => changeTimezone(event.target.value)}
              placeholder="America/New_York"
            />
            <datalist id="strategy-lab-timezones">
              <option value="America/New_York" />
              <option value="America/Chicago" />
              <option value="America/Denver" />
              <option value="America/Los_Angeles" />
              <option value="UTC" />
            </datalist>
          </Field>
          <Button type="button" onClick={runPreview} disabled={!file || busy}>
            {phase === "previewing" && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {phase === "previewing" ? "Reading CSV" : preview ? "Preview again" : "Preview CSV"}
          </Button>
        </div>

        {error && (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-red-900/50 bg-red-950/20 px-3 py-2 text-sm text-red-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="break-words">{error}</span>
          </div>
        )}
      </section>

      {preview && <PreviewReport preview={preview} />}

      <form onSubmit={commit} className="rounded-lg border bg-card p-5">
        <StepHeading
          number="2"
          title="Describe and store the run"
          description="These facts identify the TradingView test. Version assumptions below are copied and frozen by the backend."
          complete={false}
          disabled={!preview?.can_commit}
        />

        {!preview ? (
          <div className="mt-5 rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            Complete the CSV preview to unlock run metadata and import.
          </div>
        ) : !preview.can_commit ? (
          <div className="mt-5 rounded-md border border-amber-900/50 bg-amber-950/20 p-4 text-sm text-amber-200">
            This preview cannot be committed. Resolve rejected trades or open the existing duplicate run, then preview the corrected export.
          </div>
        ) : (
          <>
            <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <Field label="Symbol" htmlFor="strategy-run-symbol" required>
                <input
                  id="strategy-run-symbol"
                  className={inputClass}
                  value={symbol}
                  required
                  disabled={phase === "committing"}
                  onChange={(event) => setSymbol(event.target.value.toUpperCase())}
                  placeholder="SPY"
                />
              </Field>
              <Field label="Timeframe" htmlFor="strategy-run-timeframe" required>
                <input
                  id="strategy-run-timeframe"
                  className={inputClass}
                  value={timeframe}
                  required
                  disabled={phase === "committing"}
                  onChange={(event) => setTimeframe(event.target.value)}
                  placeholder="5m"
                />
              </Field>
              <Field label="Backtest start" htmlFor="strategy-run-backtest-start" hint="Optional declared range">
                <input
                  id="strategy-run-backtest-start"
                  type="date"
                  className={inputClass}
                  value={backtestStart}
                  disabled={phase === "committing"}
                  onChange={(event) => setBacktestStart(event.target.value)}
                />
              </Field>
              <Field label="Backtest end" htmlFor="strategy-run-backtest-end" hint="Optional declared range">
                <input
                  id="strategy-run-backtest-end"
                  type="date"
                  className={inputClass}
                  value={backtestEnd}
                  min={backtestStart || undefined}
                  disabled={phase === "committing"}
                  onChange={(event) => setBacktestEnd(event.target.value)}
                />
              </Field>
              <Field label="Initial capital" htmlFor="strategy-run-initial-capital" hint="Enables capital-based return and drawdown %">
                <input
                  id="strategy-run-initial-capital"
                  type="number"
                  min="0"
                  step="any"
                  className={inputClass}
                  value={initialCapital}
                  disabled={phase === "committing"}
                  onChange={(event) => setInitialCapital(event.target.value)}
                  placeholder="100000"
                />
              </Field>
              <Field label="Currency" htmlFor="strategy-run-currency">
                <input
                  id="strategy-run-currency"
                  className={inputClass}
                  value={currency}
                  maxLength={3}
                  disabled={phase === "committing"}
                  onChange={(event) => setCurrency(event.target.value.toUpperCase())}
                />
              </Field>
              <label className="flex min-h-10 items-center gap-3 self-end rounded-md border bg-background px-3 text-sm">
                <input
                  type="checkbox"
                  checked={extendedHours}
                  disabled={phase === "committing"}
                  onChange={(event) => setExtendedHours(event.target.checked)}
                  className="h-4 w-4 rounded border-border"
                />
                Extended-hours data included
              </label>
            </div>

            <div className="mt-4">
              <Field label="Run notes" htmlFor="strategy-run-notes" hint="Optional context unique to this export or test window.">
                <textarea
                  id="strategy-run-notes"
                  rows={3}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-ring"
                  value={notes}
                  disabled={phase === "committing"}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Why this period was tested, TradingView settings not already captured, or data caveats…"
                />
              </Field>
            </div>

            <FrozenAssumptions version={version} />

            <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t pt-5">
              <div className="flex max-w-2xl items-start gap-2 text-xs text-muted-foreground">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                The server will reparse the same file and verify its content hash, preview fingerprint, and version fingerprint before committing.
              </div>
              <Button
                type="submit"
                disabled={phase === "committing" || !symbol.trim() || !timeframe.trim()}
              >
                {phase === "committing" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <ArrowRight className="mr-2 h-4 w-4" />
                )}
                {phase === "committing" ? "Importing run" : "Import run"}
              </Button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

function PreviewReport({ preview }: { preview: StrategyRunImportPreview }) {
  return (
    <section className="space-y-5 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            {preview.can_commit ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : (
              <AlertTriangle className="h-5 w-5 text-amber-400" />
            )}
            <h2 className="font-semibold text-foreground">
              {preview.can_commit ? "Preview is ready" : "Preview needs attention"}
            </h2>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {preview.source_file_name || "CSV export"} · {preview.encoding} · timestamps interpreted as {preview.source_timezone}
          </p>
        </div>
        <span className="rounded-full border bg-background px-2.5 py-1 font-mono text-[11px] text-muted-foreground" title={preview.source_sha256}>
          SHA-256 {preview.source_sha256.slice(0, 12)}…
        </span>
      </div>

      {preview.duplicate_run_id && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-sky-900/50 bg-sky-950/20 px-4 py-3 text-sm">
          <span className="text-sky-200">These exact CSV bytes were already imported for this version.</span>
          <Link href={`/strategy-lab/runs/${preview.duplicate_run_id}`} className="font-medium text-sky-300 hover:underline">
            Open existing run →
          </Link>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <PreviewStat label="Source rows" value={preview.source_row_count} />
        <PreviewStat label="Accepted trades" value={preview.accepted_trade_count} tone="good" />
        <PreviewStat label="Rejected trades" value={preview.rejected_trade_count} tone={preview.rejected_trade_count ? "warn" : undefined} />
        <PreviewStat label="Skipped rows" value={preview.skipped_row_count} />
        <PreviewStat label="Warnings" value={preview.warning_count} tone={preview.warning_count ? "warn" : undefined} />
        <PreviewStat label="Preview rows" value={preview.trades.length} suffix={preview.preview_truncated ? "+" : ""} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border bg-background p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Observed trade window</h3>
          <p className="mt-2 text-sm text-foreground/90">
            {formatStrategyDateTime(preview.observed_start_at, preview.source_timezone)}
            <span className="mx-2 text-muted-foreground">→</span>
            {formatStrategyDateTime(preview.observed_end_at, preview.source_timezone)}
          </p>
        </div>
        <details className="rounded-md border bg-background p-4">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Detected column mapping ({Object.keys(preview.mapping).length})
          </summary>
          <dl className="mt-3 grid gap-1 text-xs">
            {Object.entries(preview.mapping).map(([target, source]) => (
              <div key={target} className="flex justify-between gap-4">
                <dt className="font-mono text-foreground/80">{target}</dt>
                <dd className="truncate text-right text-muted-foreground" title={source}>{source}</dd>
              </div>
            ))}
          </dl>
        </details>
      </div>

      {preview.warnings.length > 0 && (
        <IssueList
          title={`Warnings${preview.warnings_truncated ? " (truncated)" : ""}`}
          issues={preview.warnings}
        />
      )}

      {preview.rejected_trades.length > 0 && (
        <details className="rounded-md border border-amber-900/50 bg-amber-950/10 p-4" open>
          <summary className="cursor-pointer text-sm font-semibold text-amber-200">
            Rejected trade groups ({preview.rejected_trade_count}){preview.rejected_trades_truncated ? " · list truncated" : ""}
          </summary>
          <div className="mt-3 space-y-3">
            {preview.rejected_trades.map((trade, index) => (
              <div key={`${trade.trade_number ?? "unknown"}-${index}`} className="rounded border border-amber-900/40 bg-background/50 p-3">
                <p className="text-xs font-medium text-foreground">
                  Trade {trade.trade_number ?? "unknown"} · {trade.raw_row_count} source row{trade.raw_row_count === 1 ? "" : "s"}
                </p>
                <ul className="mt-2 space-y-1 text-xs text-amber-200/90">
                  {trade.issues.map((issue, issueIndex) => (
                    <li key={`${issue.code}-${issueIndex}`}>• {issue.message}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}

      <PreviewTradesTable preview={preview} />
    </section>
  );
}

function PreviewTradesTable({ preview }: { preview: StrategyRunImportPreview }) {
  if (preview.trades.length === 0) return null;
  return (
    <div>
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Parsed trade sample</h3>
          <p className="mt-1 text-xs text-muted-foreground">Review pairing, timestamps, quantities, and source P&amp;L before import.</p>
        </div>
        {preview.preview_truncated && <span className="text-xs text-amber-300">Preview truncated</span>}
      </div>
      <div className="overflow-x-auto rounded-md border bg-background">
        <table className="w-full min-w-[1040px] text-sm">
          <thead className="bg-muted/70 text-xs uppercase text-muted-foreground">
            <tr>
              <Th>#</Th><Th>Side</Th><Th>Entry</Th><Th>Exit</Th><Th>Entry price</Th><Th>Exit price</Th><Th>Qty</Th><Th>Net P&amp;L</Th><Th>Return</Th><Th>Warnings</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {preview.trades.map((trade) => (
              <PreviewTradeRow key={trade.trade_number} trade={trade} timezone={preview.source_timezone} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PreviewTradeRow({ trade, timezone }: { trade: ParsedStrategyTradePreview; timezone: string }) {
  return (
    <tr>
      <Td>{trade.trade_number}</Td>
      <Td><span className="capitalize">{trade.direction}</span></Td>
      <Td>{formatStrategyDateTime(trade.entry_at, timezone)}</Td>
      <Td>{formatStrategyDateTime(trade.exit_at, timezone)}</Td>
      <Td>{formatDecimal(trade.entry_price, 4)}</Td>
      <Td>{formatDecimal(trade.exit_price, 4)}</Td>
      <Td>{formatDecimal(trade.quantity, 6)}</Td>
      <Td>{formatDecimal(trade.net_pnl)}</Td>
      <Td>{formatPercentPoints(trade.return_pct, 2)}</Td>
      <Td>{trade.warning_count || "—"}</Td>
    </tr>
  );
}

function FrozenAssumptions({ version }: { version: StrategyVersionDetail }) {
  const values = [
    ["Execution", humanize(version.execution_timing)],
    ["Session", humanize(version.session_mode)],
    ["Commission", costLabel(version.commission_type, version.commission_value)],
    ["Slippage", costLabel(version.slippage_type, version.slippage_value)],
    ["Pyramiding", String(version.pyramiding)],
  ];

  return (
    <div className="mt-5 rounded-md border bg-background p-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-sky-300" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Inherited version assumptions</h3>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {values.map(([label, value]) => (
          <div key={label}>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="mt-1 text-sm font-medium capitalize text-foreground">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function StepHeading({
  number,
  title,
  description,
  complete,
  disabled = false,
}: {
  number: string;
  title: string;
  description: string;
  complete: boolean;
  disabled?: boolean;
}) {
  return (
    <div className={`flex items-start gap-3 ${disabled ? "opacity-60" : ""}`}>
      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${complete ? "bg-emerald-500/20 text-emerald-300" : "bg-sky-500/15 text-sky-300"}`}>
        {complete ? <CheckCircle2 className="h-4 w-4" /> : number}
      </div>
      <div>
        <h2 className="font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  required = false,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5 text-xs font-medium text-muted-foreground">
      <label htmlFor={htmlFor}>{label}{required && <span className="ml-1 text-red-400">*</span>}</label>
      {children}
      {hint && <span className="font-normal leading-relaxed text-muted-foreground/80">{hint}</span>}
    </div>
  );
}

function PreviewStat({ label, value, suffix = "", tone }: { label: string; value: number; suffix?: string; tone?: "good" | "warn" }) {
  const color = tone === "good" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : "text-foreground";
  return <div className="rounded-md border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p><p className={`mt-1 text-lg font-semibold tabular-nums ${color}`}>{value}{suffix}</p></div>;
}

function IssueList({ title, issues }: { title: string; issues: ImportIssue[] }) {
  return (
    <details className="rounded-md border border-amber-900/50 bg-amber-950/10 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-amber-200">{title}</summary>
      <ul className="mt-3 space-y-2 text-xs text-amber-100/80">
        {issues.map((issue, index) => (
          <li key={`${issue.code}-${issue.trade_number ?? "none"}-${index}`}>
            <span className="font-mono text-amber-300">{issue.code}</span> · {issue.message}
            {issue.trade_number != null ? ` · trade ${issue.trade_number}` : ""}
            {issue.row_number != null ? ` · row ${issue.row_number}` : ""}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="whitespace-nowrap px-3 py-2 text-left font-medium">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="whitespace-nowrap px-3 py-3 align-top text-foreground/85">{children}</td>;
}

function humanize(value: string) {
  return value.replaceAll("_", " ");
}

function costLabel(type: string, value: string | null) {
  return type === "none" ? "None" : `${humanize(type)}${value == null ? "" : ` · ${value}`}`;
}
