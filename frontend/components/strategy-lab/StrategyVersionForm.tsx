"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createVersion } from "@/lib/strategy-lab/api";
import type {
  CommissionType,
  ExecutionTiming,
  SessionMode,
  SlippageType,
  StrategyVersionStatus,
  StrategyVersionSummary,
} from "@/lib/strategy-lab/types";

type Props = {
  strategyId: string;
  existingVersions: StrategyVersionSummary[];
};

const inputClass =
  "h-10 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring disabled:cursor-not-allowed disabled:opacity-60";
const textareaClass =
  "min-h-28 resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-ring disabled:cursor-not-allowed disabled:opacity-60";

export default function StrategyVersionForm({ strategyId, existingVersions }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [versionLabel, setVersionLabel] = useState("");
  const [parentVersionId, setParentVersionId] = useState("");
  const [status, setStatus] = useState<StrategyVersionStatus>("draft");
  const [pineSource, setPineSource] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [parametersText, setParametersText] = useState("{}");
  const [entryRuleSummary, setEntryRuleSummary] = useState("");
  const [exitRuleSummary, setExitRuleSummary] = useState("");
  const [executionTiming, setExecutionTiming] = useState<ExecutionTiming>("unknown");
  const [sessionMode, setSessionMode] = useState<SessionMode>("regular");
  const [commissionType, setCommissionType] = useState<CommissionType>("none");
  const [commissionValue, setCommissionValue] = useState("");
  const [slippageType, setSlippageType] = useState<SlippageType>("none");
  const [slippageValue, setSlippageValue] = useState("");
  const [pyramiding, setPyramiding] = useState("0");
  const [knownLimitations, setKnownLimitations] = useState("");
  const [repaintingRiskNotes, setRepaintingRiskNotes] = useState("");
  const [lookaheadRiskNotes, setLookaheadRiskNotes] = useState("");

  const parent = useMemo(
    () => existingVersions.find((version) => version.id === parentVersionId),
    [existingVersions, parentVersionId],
  );
  const currentChampion = useMemo(
    () => existingVersions.find((version) => version.status === "champion"),
    [existingVersions],
  );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    let parameters: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(parametersText);
      if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("Parameters must be a JSON object.");
      }
      parameters = parsed as Record<string, unknown>;
    } catch (caught) {
      setError(caught instanceof Error ? `Parameters: ${caught.message}` : "Parameters must be valid JSON.");
      return;
    }

    const normalizedLabel = versionLabel.trim();
    if (!normalizedLabel || !pineSource.trim()) {
      setError("Version label and Pine source are required.");
      return;
    }

    const pyramidCount = Number(pyramiding);
    if (!Number.isInteger(pyramidCount) || pyramidCount < 0) {
      setError("Pyramiding must be a whole number of zero or greater.");
      return;
    }

    const normalizedCommission = parseOptionalNonNegative(commissionValue, "Commission", commissionType !== "none");
    if (normalizedCommission.error) {
      setError(normalizedCommission.error);
      return;
    }
    const normalizedSlippage = parseOptionalNonNegative(slippageValue, "Slippage", slippageType !== "none");
    if (normalizedSlippage.error) {
      setError(normalizedSlippage.error);
      return;
    }

    setBusy(true);
    try {
      const version = await createVersion(strategyId, {
        version_label: normalizedLabel,
        parent_version_id: parentVersionId || null,
        pine_source: pineSource,
        source_reference: sourceReference.trim() || null,
        change_summary: changeSummary.trim() || null,
        hypothesis: hypothesis.trim() || null,
        parameters,
        entry_rule_summary: entryRuleSummary.trim() || null,
        exit_rule_summary: exitRuleSummary.trim() || null,
        execution_timing: executionTiming,
        session_mode: sessionMode,
        commission_type: commissionType,
        commission_value: normalizedCommission.value,
        slippage_type: slippageType,
        slippage_value: normalizedSlippage.value,
        pyramiding: pyramidCount,
        known_limitations: knownLimitations.trim() || null,
        repainting_risk_notes: repaintingRiskNotes.trim() || null,
        lookahead_risk_notes: lookaheadRiskNotes.trim() || null,
        status,
      });
      router.push(`/strategy-lab/versions/${version.id}`);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the version.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <FormSection
        title="Research change"
        description="Identify the exact Pine revision and the single idea this version is meant to test."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Field label="Version label" htmlFor="version-label">
            <input
              id="version-label"
              value={versionLabel}
              onChange={(event) => setVersionLabel(event.target.value)}
              className={inputClass}
              placeholder="v1.0"
              maxLength={100}
              disabled={busy}
              required
            />
          </Field>
          <Field label="Parent version" htmlFor="parent-version">
            <select
              id="parent-version"
              value={parentVersionId}
              onChange={(event) => setParentVersionId(event.target.value)}
              className={inputClass}
              disabled={busy}
            >
              <option value="">No parent (first version)</option>
              {existingVersions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version_label} · {version.status}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Status" htmlFor="version-status">
            <select
              id="version-status"
              value={status}
              onChange={(event) => setStatus(event.target.value as StrategyVersionStatus)}
              className={inputClass}
              disabled={busy}
            >
              <option value="draft">Draft</option>
              <option value="challenger">Challenger</option>
              <option value="champion">Champion</option>
              <option value="shadow">Shadow</option>
              <option value="retired">Retired</option>
            </select>
          </Field>
        </div>

        {parent && (
          <p className="rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
            This version will trace back to {parent.version_label}. Describe only the controlled change below.
          </p>
        )}
        {status === "champion" && currentChampion && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            Saving this version as champion will move {currentChampion.version_label} back to challenger status.
          </p>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Change summary" htmlFor="change-summary">
            <textarea
              id="change-summary"
              value={changeSummary}
              onChange={(event) => setChangeSummary(event.target.value)}
              className={textareaClass}
              placeholder="What changed from the parent version?"
              disabled={busy}
            />
          </Field>
          <Field label="Hypothesis" htmlFor="hypothesis">
            <textarea
              id="hypothesis"
              value={hypothesis}
              onChange={(event) => setHypothesis(event.target.value)}
              className={textareaClass}
              placeholder="What measurable effect should this change have?"
              disabled={busy}
            />
          </Field>
        </div>
      </FormSection>

      <FormSection
        title="Pine source"
        description="The full source and result-affecting settings form the immutable version fingerprint after a run is imported."
      >
        <Field label="Pine Script" htmlFor="pine-source">
          <textarea
            id="pine-source"
            value={pineSource}
            onChange={(event) => setPineSource(event.target.value)}
            className={`${textareaClass} min-h-[28rem] font-mono text-xs leading-relaxed`}
            placeholder={'//@version=6\nstrategy("...")'}
            spellCheck={false}
            disabled={busy}
            required
          />
        </Field>
        <Field label="Source reference (optional)" htmlFor="source-reference">
          <input
            id="source-reference"
            value={sourceReference}
            onChange={(event) => setSourceReference(event.target.value)}
            className={inputClass}
            placeholder="Git commit, file path, or TradingView reference"
            disabled={busy}
          />
        </Field>
      </FormSection>

      <FormSection title="Rules and parameters" description="Keep enough context to explain what produced a run later.">
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Entry rule summary" htmlFor="entry-rules">
            <textarea
              id="entry-rules"
              value={entryRuleSummary}
              onChange={(event) => setEntryRuleSummary(event.target.value)}
              className={textareaClass}
              disabled={busy}
            />
          </Field>
          <Field label="Exit rule summary" htmlFor="exit-rules">
            <textarea
              id="exit-rules"
              value={exitRuleSummary}
              onChange={(event) => setExitRuleSummary(event.target.value)}
              className={textareaClass}
              disabled={busy}
            />
          </Field>
        </div>
        <Field label="Parameters (JSON object)" htmlFor="parameters-json">
          <textarea
            id="parameters-json"
            value={parametersText}
            onChange={(event) => setParametersText(event.target.value)}
            className={`${textareaClass} min-h-40 font-mono text-xs`}
            placeholder={'{\n  "rvol_min": 1.5,\n  "stop_atr": 0.4\n}'}
            spellCheck={false}
            disabled={busy}
          />
        </Field>
      </FormSection>

      <FormSection
        title="Execution assumptions"
        description="TradingView results are only comparable when these assumptions match."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Field label="Execution timing" htmlFor="execution-timing">
            <select
              id="execution-timing"
              value={executionTiming}
              onChange={(event) => setExecutionTiming(event.target.value as ExecutionTiming)}
              className={inputClass}
              disabled={busy}
            >
              <option value="unknown">Unknown</option>
              <option value="bar_close">Bar close</option>
              <option value="next_bar">Next bar</option>
              <option value="intrabar">Intrabar</option>
            </select>
          </Field>
          <Field label="Session" htmlFor="session-mode">
            <select
              id="session-mode"
              value={sessionMode}
              onChange={(event) => setSessionMode(event.target.value as SessionMode)}
              className={inputClass}
              disabled={busy}
            >
              <option value="regular">Regular hours</option>
              <option value="extended">Extended hours</option>
              <option value="custom">Custom session</option>
            </select>
          </Field>
          <Field label="Pyramiding" htmlFor="pyramiding">
            <input
              id="pyramiding"
              type="number"
              min="0"
              step="1"
              value={pyramiding}
              onChange={(event) => setPyramiding(event.target.value)}
              className={inputClass}
              disabled={busy}
              required
            />
          </Field>
          <Field label="Commission type" htmlFor="commission-type">
            <select
              id="commission-type"
              value={commissionType}
              onChange={(event) => {
                const value = event.target.value as CommissionType;
                setCommissionType(value);
                if (value === "none") setCommissionValue("");
              }}
              className={inputClass}
              disabled={busy}
            >
              <option value="none">None</option>
              <option value="percent">Percent</option>
              <option value="cash_per_order">Cash per order</option>
              <option value="cash_per_contract">Cash per contract</option>
              <option value="custom">Custom</option>
            </select>
          </Field>
          <Field label="Commission value" htmlFor="commission-value">
            <input
              id="commission-value"
              type="number"
              min="0"
              step="0.000001"
              value={commissionValue}
              onChange={(event) => setCommissionValue(event.target.value)}
              className={inputClass}
              placeholder={commissionType === "none" ? "Not used" : "0.100000"}
              disabled={busy || commissionType === "none"}
              required={commissionType !== "none"}
            />
          </Field>
          <div className="hidden xl:block" />
          <Field label="Slippage type" htmlFor="slippage-type">
            <select
              id="slippage-type"
              value={slippageType}
              onChange={(event) => {
                const value = event.target.value as SlippageType;
                setSlippageType(value);
                if (value === "none") setSlippageValue("");
              }}
              className={inputClass}
              disabled={busy}
            >
              <option value="none">None</option>
              <option value="ticks">Ticks</option>
              <option value="percent">Percent</option>
              <option value="cash_per_order">Cash per order</option>
              <option value="custom">Custom</option>
            </select>
          </Field>
          <Field label="Slippage value" htmlFor="slippage-value">
            <input
              id="slippage-value"
              type="number"
              min="0"
              step="0.000001"
              value={slippageValue}
              onChange={(event) => setSlippageValue(event.target.value)}
              className={inputClass}
              placeholder={slippageType === "none" ? "Not used" : "1.000000"}
              disabled={busy || slippageType === "none"}
              required={slippageType !== "none"}
            />
          </Field>
        </div>
      </FormSection>

      <FormSection title="Known risks" description="Record caveats now so a profitable run is not mistaken for reliable evidence.">
        <div className="grid gap-4 lg:grid-cols-3">
          <Field label="Known limitations" htmlFor="known-limitations">
            <textarea
              id="known-limitations"
              value={knownLimitations}
              onChange={(event) => setKnownLimitations(event.target.value)}
              className={textareaClass}
              disabled={busy}
            />
          </Field>
          <Field label="Repainting risk" htmlFor="repainting-risk">
            <textarea
              id="repainting-risk"
              value={repaintingRiskNotes}
              onChange={(event) => setRepaintingRiskNotes(event.target.value)}
              className={textareaClass}
              disabled={busy}
            />
          </Field>
          <Field label="Lookahead risk" htmlFor="lookahead-risk">
            <textarea
              id="lookahead-risk"
              value={lookaheadRiskNotes}
              onChange={(event) => setLookaheadRiskNotes(event.target.value)}
              className={textareaClass}
              disabled={busy}
            />
          </Field>
        </div>
      </FormSection>

      {error && (
        <p role="alert" className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t pt-5">
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => router.push(`/strategy-lab/strategies/${strategyId}`)}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving version..." : "Save Pine version"}
        </Button>
      </div>
    </form>
  );
}

function parseOptionalNonNegative(
  value: string,
  label: string,
  required: boolean,
): { value: string | null; error: string | null } {
  const normalized = value.trim();
  if (!normalized) {
    return required
      ? { value: null, error: `${label} value is required for the selected type.` }
      : { value: null, error: null };
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0
    ? { value: normalized, error: null }
    : { value: null, error: `${label} must be a non-negative number.` };
}

function FormSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
