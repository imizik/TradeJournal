"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/research/store";
import { EditableText, PositionDot } from "./primitives";

export default function Checklist({
  ticker,
  onSetTicker,
}: {
  ticker: string;
  onSetTicker: (t: string) => void;
}) {
  const { data, setChecklistAnswer, overlays } = useWorkspace();

  const companyOptions = useMemo(
    () =>
      Object.values(data.companies)
        .sort((a, b) => (a.ticker < b.ticker ? -1 : 1))
        .map((c) => ({ ticker: c.ticker, label: `${c.ticker} · ${c.name}` })),
    [data.companies]
  );

  const answers = data.checklistByTicker[ticker] ?? {};
  const done = data.checklistTemplate.filter((q) => answers[q.id]?.checked).length;

  return (
    <div className="max-w-3xl p-5">
      <div className="text-lg font-semibold text-foreground">Bear-Case Checklist</div>
      <div className="mb-4 text-xs text-muted-foreground">
        Run this <b className="text-foreground">before</b> averaging down on a name. This checklist is{" "}
        <b className="text-foreground">per ticker</b> — discipline over emotion.
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={ticker}
          suppressHydrationWarning
          onChange={(e) => onSetTicker(e.target.value)}
          className="rounded-md border border-border bg-card px-3 py-1.5 font-mono text-sm font-semibold text-foreground outline-none focus:border-ring"
        >
          {companyOptions.map((o) => (
            <option key={o.ticker} value={o.ticker}>
              {o.label}
            </option>
          ))}
        </select>
        <PositionDot open={overlays.openTickers.has(ticker)} />
        <span className="font-mono text-xs text-muted-foreground">
          {done}/{data.checklistTemplate.length} checked
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {data.checklistTemplate.map((q) => {
          const a = answers[q.id] ?? { checked: false, notes: "" };
          return (
            <div
              key={q.id}
              className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-2.5"
            >
              <button
                type="button"
                onClick={() => setChecklistAnswer(ticker, q.id, { checked: !a.checked })}
                className={cn(
                  "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border text-xs font-bold",
                  a.checked
                    ? "border-emerald-500 bg-emerald-500 text-emerald-950"
                    : "border-border bg-background text-transparent"
                )}
              >
                ✓
              </button>
              <div className="min-w-0 flex-1">
                <div
                  className={cn(
                    "text-sm leading-snug",
                    a.checked ? "text-muted-foreground line-through" : "text-foreground/90"
                  )}
                >
                  {q.text}
                </div>
                <div className="mt-1.5">
                  <EditableText
                    value={a.notes}
                    onCommit={(v) => setChecklistAnswer(ticker, q.id, { notes: v })}
                    placeholder="notes for this name…"
                    mono
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
