"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createStrategy } from "@/lib/strategy-lab/api";

const SETUP_TYPES = [
  { value: "vwap_reclaim", label: "VWAP reclaim" },
  { value: "opening_range_breakout", label: "Opening-range breakout" },
  { value: "first_pullback", label: "First pullback" },
  { value: "failed_breakout", label: "Failed breakout" },
  { value: "custom", label: "Custom" },
];

export default function StrategyCreateForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [setupType, setSetupType] = useState("custom");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setError("Give the strategy a name before saving it.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const strategy = await createStrategy({
        name: normalizedName,
        description: description.trim() || null,
        setup_type: setupType,
      });
      router.push(`/strategy-lab/strategies/${strategy.id}`);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the strategy.");
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          New strategy
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Start with the research idea. The exact Pine source belongs to a version next.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Name" htmlFor="strategy-name">
          <input
            id="strategy-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            placeholder="VWAP Reclaim"
            maxLength={200}
            disabled={busy}
            required
          />
        </FormField>

        <FormField label="Setup type" htmlFor="strategy-setup-type">
          <select
            id="strategy-setup-type"
            value={setupType}
            onChange={(event) => setSetupType(event.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm outline-none focus:border-ring"
            disabled={busy}
          >
            {SETUP_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Description" htmlFor="strategy-description">
          <textarea
            id="strategy-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="min-h-28 resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-ring"
            placeholder="What setup does this strategy test, and what should stay stable between versions?"
            disabled={busy}
          />
        </FormField>

        {error && (
          <p role="alert" className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full sm:w-auto" disabled={busy}>
          {busy ? "Creating strategy..." : "Create strategy"}
        </Button>
      </form>
    </section>
  );
}

function FormField({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
